"""Supplemental oxygen, the one-airway-device rule, and every module on one engine
(``pulse_whole_body_circuits``), on the WholeBody engine.

Engine tests drive the real Pulse build. Oracles are the single-module composites
(the same engine with fewer requests must give identical readings), Pulse's own
serialized state (which actions are active, with which values), and effect sizes
measured on the real engine (recorded in .build-progress.md, Phase 5). Each
docstring names the proposition the test would falsify.
"""

import json
import math
from collections import Counter

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.circuits import MODULES, CircuitModule, Request
from viva_pulse.circuits.respiratory import MECHANICAL_VENTILATOR, VENTILATOR_BASELINE
from viva_pulse.circuits.supplemental_oxygen import OXYGEN_BASELINE, SUPPLEMENTAL_OXYGEN
from viva_pulse.composites import (pulse_cardiovascular, pulse_mechanical_ventilation, pulse_respiratory,
                                   pulse_supplemental_oxygen, pulse_thermal, pulse_whole_body_circuits)
from viva_pulse.composites.circuits import WHOLE_BODY_MODULES
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess

INTERVAL = 30.0


def _leaves(tree, prefix=()):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _leaves(value, prefix + (key,))
        else:
            yield prefix + (key,), value


def _sim(generator, **params):
    core = build_core()
    return Composite({"state": generator(core, **params)}, core=core)


def _rows(sim):
    return {row["time"]: row["circuits"] for row in gather_emitter_results(sim)[("emitter",)]}


def _run(generator, duration, **params):
    sim = _sim(generator, interval=INTERVAL, **params)
    sim.run(duration)
    return _rows(sim)


def _active_actions(sim):
    """Oracle: Pulse's own serialized active actions."""
    import PyPulse

    engine = sim.state["pulse"]["instance"]._engine
    state = json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))
    return state.get("ActiveActions", {}).get("AnyAction", [])


def _oxygen_action(sim):
    found = [a["PatientAction"]["SupplementalOxygen"] for a in _active_actions(sim)
             if "SupplementalOxygen" in a.get("PatientAction", {})]
    return found[0] if found else None


def _oxygenation(row):
    return row["supplemental_oxygen"]["oxygenation"]


@pytest.fixture(scope="module")
def baseline():
    """The combined composite, unperturbed, 120 s."""
    return _run(pulse_whole_body_circuits, 120)


# -- registry and configuration (no engine) ------------------------------------


def test_setpoint_and_config_names_are_unique_across_modules():
    """Falsifies: two modules share a setpoint or config name, which would make the
    flat parameters of pulse_whole_body_circuits ambiguous (one value for both)."""
    names = Counter(p for m in MODULES.values() for b in m.bindings for p in b.ports)
    names.update(k for m in MODULES.values() for k in m.params)
    assert not [n for n, count in names.items() if count > 1]


def test_whole_body_composite_includes_every_whole_body_module():
    """Falsifies: a module that runs on whole_body is left out of the combined composite (the
    point modules are opt-in, through point_reads), or point_reads adds anything else."""
    whole_body = {name for name, m in MODULES.items() if "whole_body" in m.model_types}
    points = {name for name, m in MODULES.items() if m.prepare_state}
    assert {m.name for m in WHOLE_BODY_MODULES} == whole_body - points
    document = pulse_whole_body_circuits(build_core(), point_reads=True)
    assert set(document["pulse"]["config"]["modules"]) == whole_body


def test_airway_devices_are_declared():
    """Falsifies: an airway device escapes the one-device rule because its module does
    not declare which setpoint connects it."""
    assert MECHANICAL_VENTILATOR.airway_device == "connected"
    assert SUPPLEMENTAL_OXYGEN.airway_device == "oxygen_connected"
    assert SUPPLEMENTAL_OXYGEN.model_types == frozenset({"whole_body"})
    with pytest.raises(ValueError, match="airway_device"):
        CircuitModule(name="x", model_types=frozenset({"whole_body"}),
                      outputs=(Request(("a",), "physiology", "HeartRate", None),), airway_device="missing")


@pytest.mark.parametrize("changes, match", [
    ({"oxygen_connected": 0.5}, "0 or 1"),
    ({"oxygen_flow_L_per_min": 0.0}, "oxygen_flow"),
    ({"oxygen_flow_L_per_min": -2.0}, "oxygen_flow"),
    ({"oxygen_flow_L_per_min": math.inf}, "oxygen_flow"),
])
def test_oxygen_validation(changes, match):
    """Falsifies: a meaningless oxygen setting reaches Pulse (zero flow divides by zero
    in Pulse's flow-control resistance)."""
    with pytest.raises(ValueError, match=match):
        SUPPLEMENTAL_OXYGEN.bindings[0].validate({**OXYGEN_BASELINE, **changes}, {})


@pytest.mark.parametrize("generator, params, match", [
    (pulse_supplemental_oxygen, {"oxygen_device": "Snorkel"}, "oxygen_device"),
    (pulse_supplemental_oxygen, {"oxygen_flow_L_per_min": 0.0}, "oxygen_flow"),
    (pulse_whole_body_circuits, {"connected": 1.0, "oxygen_connected": 1.0}, "one airway device"),
    (pulse_whole_body_circuits, {"hemorrhage_compartment": "Elbow"}, "hemorrhage_compartment"),
    (pulse_whole_body_circuits, {"ambient_temperature_C": -300.0}, "absolute zero"),
    (pulse_whole_body_circuits, {"oxygen_conected": 1.0}, "unexpected"),
])
def test_generators_validate_parameters_when_building(generator, params, match):
    """Falsifies: a bad parameter, or two connected airway devices, only fails deep
    inside sim.run()."""
    with pytest.raises((ValueError, TypeError), match=match):
        generator(None, **params)


# -- real engine ----------------------------------------------------------------


def test_combined_readings_equal_the_single_module_composites(baseline):
    """Falsifies: combining modules on one engine mis-maps a reading (shared request
    dedupe, nested slot mapping) or perturbs the engine. Pulse's dynamics do not depend
    on which values are requested, so at baseline every module's subtree must equal its
    own composite's at the same time, and no reading may be NaN."""
    for row in baseline.values():
        bad = [p for p, v in _leaves(row) if not math.isfinite(v)]
        assert not bad, bad
    singles = {
        "cardiovascular": _run(pulse_cardiovascular, 120),
        "respiratory": _run(pulse_respiratory, 120, model_type="whole_body"),
        "mechanical_ventilator": _run(pulse_mechanical_ventilation, 120, model_type="whole_body",
                                      connected=0.0, intubated=0.0),
        "thermal": _run(pulse_thermal, 120),
        "supplemental_oxygen": _run(pulse_supplemental_oxygen, 120, oxygen_connected=0.0),
    }
    assert set(singles) == {m.name for m in WHOLE_BODY_MODULES}
    for name, rows in singles.items():
        expected = dict(_leaves(rows[120][name]))
        actual = dict(_leaves(baseline[120][name]))
        assert actual.keys() == expected.keys(), name
        for path, value in expected.items():
            # Not exact: identical Pulse runs in one process occasionally differ by ~1e-14, which
            # can grow over 120 s (once seen: 4.5e-11 absolute on a value of 1.3e-4). A
            # mis-mapped reading or a perturbed engine differs by orders of magnitude more.
            assert actual[path] == pytest.approx(value, rel=1e-6, abs=1e-9), (name, path)


def test_room_air_blood_gases_are_in_normal_ranges(baseline):
    """Falsifies: a blood-gas reading is in the wrong unit or mapped to the wrong property.
    On room air the loaded patient must sit in the normal adult ranges: PaO2 75-100 mmHg,
    PaCO2 35-45 mmHg, SpO2 0.95-1.0, FiO2 0.21 (measured 91.4, 37.8, 0.976, 0.21)."""
    gases = _oxygenation(baseline[0])
    assert 75.0 <= gases["arterial_oxygen_pressure_mmHg"] <= 100.0
    assert 35.0 <= gases["arterial_carbon_dioxide_pressure_mmHg"] <= 45.0
    assert 0.95 <= gases["oxygen_saturation"] <= 1.0
    assert gases["fraction_inspired_oxygen"] == pytest.approx(0.21, abs=0.005)


def test_oxygen_devices_raise_arterial_oxygen_in_order():
    """Falsifies: the device type is not sent (e.g. always a nasal cannula). At their
    Pulse default flows, measured PaO2 at 120 s is 240 (nasal cannula 3.5 L/min), 393
    (simple mask 7.5) and 563 mmHg (non-rebreather 10), against 91 on room air; FiO2
    0.51, 0.59, 0.96."""
    pao2, fio2 = {}, {}
    for device, flow in (("NasalCannula", 3.5), ("SimpleMask", 7.5), ("NonRebreatherMask", 10.0)):
        row = _run(pulse_supplemental_oxygen, 120, oxygen_device=device, oxygen_flow_L_per_min=flow)[120]
        pao2[device] = _oxygenation(row)["arterial_oxygen_pressure_mmHg"]
        fio2[device] = _oxygenation(row)["fraction_inspired_oxygen"]
    assert 150.0 < pao2["NasalCannula"] < pao2["SimpleMask"] - 75.0
    assert pao2["SimpleMask"] < pao2["NonRebreatherMask"] - 75.0
    assert fio2["NasalCannula"] > 0.4
    assert fio2["NonRebreatherMask"] > 0.9


def test_oxygen_action_carries_the_setpoints():
    """Falsifies: the device, the flow or the wall supply is not what Pulse receives.
    Pulse's own serialized action must hold the device, the flow, and an infinite
    (wall) volume."""
    sim = _sim(pulse_supplemental_oxygen, interval=1.0, oxygen_device="SimpleMask",
               oxygen_flow_L_per_min=6.5)
    sim.run(2)
    action = _oxygen_action(sim)
    assert action["Device"] == "SimpleMask"
    assert action["Flow"]["ScalarVolumePerTime"] == {"Value": 6.5, "Unit": "L/min"}
    assert action["Volume"]["ScalarVolume"] == {"Value": "Infinity", "Unit": "L"}


def test_disconnecting_oxygen_restores_room_air():
    """Falsifies: oxygen_connected = 0 is not forwarded, or Pulse keeps the device.
    After 120 s at 6 L/min (FiO2 0.61), disconnecting must remove Pulse's action and
    return FiO2 to 0.21 (measured within 120 s)."""
    sim = _sim(pulse_supplemental_oxygen, interval=INTERVAL, oxygen_flow_L_per_min=6.0)
    sim.run(120)
    assert _oxygen_action(sim) is not None
    sim.state["interventions"]["supplemental_oxygen"]["oxygen_connected"] = 0.0
    sim.run(120)
    assert _oxygen_action(sim) is None
    rows = _rows(sim)
    assert _oxygenation(rows[120])["fraction_inspired_oxygen"] > 0.5
    assert _oxygenation(rows[240])["fraction_inspired_oxygen"] == pytest.approx(0.21, abs=0.005)


def _airway_process():
    process = PulseCircuitProcess({"modules": ["mechanical_ventilator", "supplemental_oxygen"]},
                                  core=build_core())
    process.initial_state()
    return process


def _airway(connected, oxygen_connected):
    return {"setpoints": {"mechanical_ventilator": {**VENTILATOR_BASELINE, "connected": connected},
                          "supplemental_oxygen": {**OXYGEN_BASELINE, "oxygen_connected": oxygen_connected}}}


def test_two_connected_airway_devices_raise():
    """Falsifies: oxygen connects while the ventilator is connected. Pulse refuses ("Can
    only change airway mode from the Free mode") and every advance then fails, so the
    process would latch irreversible_state and the run would be lost."""
    process = _airway_process()
    process.update(_airway(1.0, 0.0), 1.0)
    with pytest.raises(ValueError, match="one airway device"):
        process.update(_airway(1.0, 1.0), 1.0)


@pytest.mark.parametrize("before, after", [((1.0, 0.0), (0.0, 1.0)), ((0.0, 1.0), (1.0, 0.0))])
def test_airway_devices_cannot_swap_in_one_update(before, after):
    """Falsifies: one device connects in the update another disconnects. For ventilator ->
    oxygen Pulse processes the oxygen before the ventilator's disconnect and stalls."""
    process = _airway_process()
    process.update(_airway(*before), 1.0)
    with pytest.raises(ValueError, match="one update earlier"):
        process.update(_airway(*after), 1.0)


def test_staged_handover_from_ventilator_to_oxygen_works():
    """Falsifies: the documented handover (disconnect, then connect one update later)
    fails in Pulse. The engine must keep advancing, with oxygen active (FiO2 > 0.4)."""
    process = _airway_process()
    process.update(_airway(1.0, 0.0), 30.0)
    process.update(_airway(0.0, 0.0), 1.0)
    for _ in range(4):
        update = process.update(_airway(0.0, 1.0), 30.0)
        assert "irreversible_state" not in update
    fio2 = process._pull(process._engine)[[r.property for r in process._requests].index("FractionOfInspiredOxygen")]
    assert fio2 > 0.4


def test_oxygen_slows_the_heart(baseline):
    """Falsifies: the modules do not share one engine (an oxygen setpoint cannot reach a
    cardiovascular reading). A non-rebreather at 10 L/min drops heart rate 71.9 -> 65.9
    bpm within 120 s and raises breathing rate 12.0 -> 14.2."""
    row = _run(pulse_whole_body_circuits, 120, oxygen_connected=1.0, oxygen_device="NonRebreatherMask",
               oxygen_flow_L_per_min=10.0)[120]
    base = baseline[120]
    hr = row["cardiovascular"]["hemodynamics"]["heart_rate_bpm"]
    assert hr < base["cardiovascular"]["hemodynamics"]["heart_rate_bpm"] - 3.0
    rr = row["respiratory"]["mechanics"]["respiration_rate_bpm"]
    assert rr > base["respiratory"]["mechanics"]["respiration_rate_bpm"] + 1.0


def test_doubling_systemic_resistance_slows_breathing(baseline):
    """Falsifies: a cardiovascular setpoint cannot reach the respiratory readings.
    Systemic resistance x2 drops breathing rate 12.0 -> 10.6 and tidal volume 512 -> 457 mL
    within 120 s (heart rate 72 -> 43 through the baroreflex)."""
    row = _run(pulse_whole_body_circuits, 120, systemic_resistance_multiplier=2.0)[120]
    base = baseline[120]["respiratory"]["mechanics"]
    assert row["respiratory"]["mechanics"]["respiration_rate_bpm"] < base["respiration_rate_bpm"] - 0.8
    assert row["respiratory"]["mechanics"]["tidal_volume_mL"] < base["tidal_volume_mL"] - 30.0
