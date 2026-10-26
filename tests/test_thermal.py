"""Thermal module (Pulse's internal + external temperature circuit) on the WholeBody engine.

Engine tests drive the real Pulse build. Oracles are an engine loaded directly
through Pulse's API with requests spelled out here, Pulse's own serialized
state (which actions are active), and effect sizes measured on the real engine
(recorded in .build-progress.md, Phase 3). The StandardMale state is not
thermally settled, so effects are measured against an unperturbed run, never
against t = 0. Each docstring names the proposition the test would falsify.
"""

import json
import math

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.circuits import MODULES
from viva_pulse.circuits.thermal import ENVIRONMENT_BASELINE, THERMAL, THERMAL_APPLICATION_BASELINE
from viva_pulse.composites import pulse_thermal
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess
from viva_pulse.runtime import ensure_pulse_importable

INTERVAL = 30.0


def _thermal(row):
    return row["circuits"]["thermal"]


def _skin(row):
    return _thermal(row)["energy"]["skin_temperature_C"]


def _leaves(tree, prefix=()):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _leaves(value, prefix + (key,))
        else:
            yield prefix + (key,), value


def _sim(**params):
    core = build_core()
    return Composite({"state": pulse_thermal(core, interval=INTERVAL, **params)}, core=core)


def _rows(sim):
    return {row["time"]: row for row in gather_emitter_results(sim)[("emitter",)]}


def _run(duration, **params):
    sim = _sim(**params)
    sim.run(duration)
    return _rows(sim)


def _thermal_application_active(sim):
    """Oracle: whether Pulse's own serialized state holds an active thermal application."""
    import PyPulse

    engine = sim.state["pulse"]["instance"]._engine
    state = json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))
    return "ThermalApplication" in json.dumps(state.get("ActiveActions", {}))


@pytest.fixture(scope="module")
def baseline():
    """An unperturbed 600 s run (skin 32.36 -> 31.12 C, core 37.03 -> 37.07 C)."""
    return _run(600)


# Independent oracle requests: store path -> (request kind, compartment, property, unit class, unit)
ORACLE = {
    ("energy", "core_temperature_C"): ("physiology", None, "CoreTemperature", "TemperatureUnit", "C"),
    ("energy", "sweat_rate_g_per_min"): ("physiology", None, "SweatRate", "MassPerTimeUnit", "g_Per_min"),
    ("heat_loss", "radiative_W"): ("environment", None, "RadiativeHeatLoss", "PowerUnit", "W"),
    ("environment", "relative_humidity"): ("environment", None, "EnvironmentalConditions-RelativeHumidity", None, None),
    ("compartments", "internal_core", "heat_kJ"): ("thermal", "InternalCore", "Heat", "EnergyUnit", "kJ"),
    ("compartments", "clothing", "temperature_C"): ("thermal", "Clothing", "Temperature", "TemperatureUnit", "C"),
    ("compartments", "external_skin", "heat_out_W"): ("thermal", "ExternalSkin", "HeatTransferRateOut", "PowerUnit", "W"),
}


def _direct_engine(at_engine_time_s):
    """Oracle engine through Pulse's API, advanced to an absolute engine time."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = []
    for kind, compartment, prop, unit_cls, unit_name in ORACLE.values():
        unit = getattr(getattr(scalars, unit_cls), unit_name) if unit_cls else None
        if kind == "thermal":
            requests.append(SEDataRequest.create_thermal_compartment_request(compartment, prop, unit=unit))
        elif kind == "environment":
            requests.append(SEDataRequest.create_environment_request(prop, unit=unit))
        else:
            requests.append(SEDataRequest.create_physiology_request(prop, unit=unit))
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"),
                                      SEDataRequestManager(requests))
    engine.advance_time_s(0.0)
    if at_engine_time_s:
        engine.advance_time_s(at_engine_time_s)
    return [float(v) for v in engine.pull_data()[1:]]


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


# -- registry and configuration (no engine) ------------------------------------


def test_module_covers_the_temperature_circuit():
    """Falsifies: the module lost a reading group or compartment, exposes a request
    Pulse cannot serve (InternalGround temperature, Heat outside the internal
    compartments; probe P8), or is allowed on an engine without an energy model."""
    assert MODULES["thermal"] is THERMAL
    assert THERMAL.model_types == frozenset({"whole_body"})
    assert {r.path[0] for r in THERMAL.outputs} == {"energy", "heat_loss", "environment", "compartments"}
    assert {r.compartment for r in THERMAL.outputs if r.compartment} == {
        "InternalCore", "InternalSkin", "ExternalCore", "ExternalSkin", "Clothing", "Enclosure",
        "Ambient", "Active"}
    assert {r.compartment for r in THERMAL.outputs if r.property == "Heat"} == {"InternalCore", "InternalSkin"}
    assert not [r for r in THERMAL.outputs if r.property == "Temperature" and r.compartment == "Active"]
    assert len(THERMAL.outputs) == 4 + 8 + 7 + 7 + 2 + 8 * 2


def test_thermal_module_is_rejected_on_ventilation_mechanics():
    """Falsifies: the module loads on the airway-only engine, which has no energy model."""
    with pytest.raises(ValueError, match="does not support model_type"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["thermal"]},
                            core=build_core())


def test_default_setpoints_pass_their_validators():
    """Falsifies: a group's own baseline is rejected by its validator."""
    for binding in THERMAL.bindings:
        binding.validate(dict(binding.ports), {})


@pytest.mark.parametrize("group, changes, match", [
    (0, {"ambient_temperature_C": -300.0}, "absolute zero"),
    (0, {"mean_radiant_temperature_C": -273.15}, "absolute zero"),
    (0, {"respiration_ambient_temperature_C": -280.0}, "absolute zero"),
    (0, {"relative_humidity": 1.2}, "relative_humidity"),
    (0, {"air_velocity_m_per_s": -1.0}, "air_velocity"),
    (0, {"clothing_resistance_clo": -0.1}, "clothing_resistance"),
    (1, {"active_heating_W": -5.0}, "active_heating_W"),
    (1, {"active_cooling_W": -5.0}, "active_cooling_W"),
    (1, {"active_heating_area_fraction": 0.0}, "active_heating_area_fraction"),
    (1, {"active_cooling_area_fraction": 1.5}, "active_cooling_area_fraction"),
    (1, {"applied_temperature_area_fraction": 0.0}, "applied_temperature_area_fraction"),
    (1, {"applied_temperature_on": 0.5}, "0 or 1"),
    (1, {"applied_temperature_C": -300.0}, "absolute zero"),
])
def test_setpoint_validation(group, changes, match):
    """Falsifies: a physically meaningless thermal setting reaches the engine. Pulse
    clamps some of these silently (an area fraction above 1 becomes 1)."""
    binding = THERMAL.bindings[group]
    with pytest.raises(ValueError, match=match):
        binding.validate({**binding.ports, **changes}, {})


@pytest.mark.parametrize("params, match", [
    ({"relative_humidity": 2.0}, "relative_humidity"),
    ({"active_heating_W": -1.0}, "active_heating_W"),
    ({"ambient_temp_C": 30.0}, "unexpected"),
])
def test_generator_validates_parameters_when_building(params, match):
    """Falsifies: a bad parameter only fails deep inside sim.run()."""
    with pytest.raises((ValueError, TypeError), match=match):
        pulse_thermal(None, **params)


# -- real engine ----------------------------------------------------------------


def test_every_shipped_state_uses_the_baseline_environment():
    """Falsifies: the environment baselines differ from a shipped state's conditions.
    The group is always sent whole, so its first change would silently replace the
    other conditions with the baselines."""
    bin_dir = ensure_pulse_importable()
    states = sorted(p.name for p in (bin_dir / "states").glob("*@0s.json"))
    assert states
    for state in states:
        process = PulseCircuitProcess({"modules": ["thermal"], "state_file": state}, core=build_core())
        environment = process.initial_state()["thermal"]["environment"]
        for port, value in ENVIRONMENT_BASELINE.items():
            assert environment[port] == pytest.approx(value), (state, port)


def test_state_with_another_environment_fails_the_load(tmp_path):
    """Falsifies: a state whose environment differs from the baselines loads, and the
    first environment change silently resets its other conditions to Standard.json."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm.engine import SEDataRequestManager
    from pulse.cdm.environment_actions import SEChangeEnvironmentalConditions
    from pulse.cdm.scalars import TemperatureUnit
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"),
                                      SEDataRequestManager([]))
    change = SEChangeEnvironmentalConditions()
    change.get_environmental_conditions().get_ambient_temperature().set_value(30.0, TemperatureUnit.C)
    engine.process_action(change)
    engine.advance_time_s(1.0)
    state = tmp_path / "Warm@1s.json"
    assert engine.serialize_to_file(str(state))

    process = PulseCircuitProcess({"modules": ["thermal"], "state_file": str(state)}, core=build_core())
    with pytest.raises(ValueError, match="ambient_temperature_C"):
        process.initial_state()


def test_store_tracks_pulse():
    """Falsifies: an environment or thermal-compartment request is mis-mapped, or the
    store mapping is wrong. Stores after 20 one-second updates must equal an
    independent engine at the same engine time, and no value may be NaN."""
    core = build_core()
    sim = Composite({"state": pulse_thermal(core)}, core=core)
    sim.run(20)
    rows = gather_emitter_results(sim)[("emitter",)]
    for row in rows:
        bad = [p for p, v in _leaves(_thermal(row)) if not math.isfinite(v)]
        assert not bad, bad
    engine_time = round(sim.state["pulse"]["instance"]._engine.pull_data()[0] / 0.02) * 0.02
    for path, expected in zip(ORACLE, _direct_engine(engine_time)):
        assert _at(_thermal(rows[-1]), path) == pytest.approx(expected, rel=1e-6, abs=1e-6), path


def test_cold_environment_cools_skin_then_core(baseline):
    """Falsifies: the environment action is not built from the setpoints, or replaces the
    conditions instead of merging. At -10 C with a 5 m/s wind, skin is measured 3.2 C below
    the unperturbed run after 120 s and core 0.18 C below after 600 s. Pulse reads back the
    new conditions, and keeps the atmospheric pressure the action does not carry."""
    rows = _run(600, ambient_temperature_C=-10.0, mean_radiant_temperature_C=-10.0,
                air_velocity_m_per_s=5.0)
    assert _skin(rows[120]) < _skin(baseline[120]) - 2.0
    core = _thermal(rows[600])["energy"]["core_temperature_C"]
    assert core < _thermal(baseline[600])["energy"]["core_temperature_C"] - 0.1
    environment = _thermal(rows[600])["environment"]
    assert environment["ambient_temperature_C"] == pytest.approx(-10.0)
    assert environment["mean_radiant_temperature_C"] == pytest.approx(-10.0)
    assert environment["air_velocity_m_per_s"] == pytest.approx(5.0)
    assert environment["relative_humidity"] == pytest.approx(0.6)
    assert environment["atmospheric_pressure_mmHg"] == pytest.approx(760.0)


def test_every_environment_setpoint_reaches_pulse():
    """Falsifies: an environment setpoint is dropped, swapped with another, or sent in the
    wrong unit. Each is set to its own non-baseline value; Pulse must read each back."""
    values = {"ambient_temperature_C": 15.0, "mean_radiant_temperature_C": 30.0,
              "respiration_ambient_temperature_C": 5.0, "relative_humidity": 0.3,
              "air_velocity_m_per_s": 1.5, "clothing_resistance_clo": 1.2}
    assert set(values) == set(ENVIRONMENT_BASELINE)
    environment = _thermal(_run(30, **values)[30])["environment"]
    for port, value in values.items():
        assert environment[port] == pytest.approx(value), port


def test_breathed_air_temperature_drives_respiration_heat_loss(baseline):
    """Falsifies: the breathed-air temperature is not sent. Pulse computes respiration
    heat loss from RespirationAmbientTemperature, which does not follow the ambient
    temperature; breathing -10 C air raises it from 8.06 to 13.34 W within 30 s."""
    rows = _run(30, respiration_ambient_temperature_C=-10.0)
    assert (_thermal(rows[30])["heat_loss"]["respiration_W"]
            > _thermal(baseline[30])["heat_loss"]["respiration_W"] + 3.0)


def test_every_thermal_application_setting_reaches_pulse():
    """Falsifies: a thermal-application field is dropped, swapped or sent in the wrong
    unit. Every field is non-default; Pulse's own serialized active action must carry
    each value."""
    sim = _sim(active_heating_W=150.0, active_heating_area_fraction=0.7, active_cooling_W=40.0,
               active_cooling_area_fraction=0.3, applied_temperature_on=1.0,
               applied_temperature_C=30.0, applied_temperature_area_fraction=0.6)
    sim.run(INTERVAL)
    import PyPulse

    engine = sim.state["pulse"]["instance"]._engine
    actions = json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))["ActiveActions"]
    [application] = [a["EnvironmentAction"]["ThermalApplication"] for a in actions["AnyAction"]
                     if "ThermalApplication" in a.get("EnvironmentAction", {})]
    heating, cooling = application["ActiveHeating"], application["ActiveCooling"]
    applied = application["AppliedTemperature"]
    assert heating["Power"]["ScalarPower"] == {"Value": 150, "Unit": "W"}
    assert heating["SurfaceAreaFraction"]["Scalar0To1"]["Value"] == pytest.approx(0.7)
    assert cooling["Power"]["ScalarPower"] == {"Value": 40, "Unit": "W"}
    assert cooling["SurfaceAreaFraction"]["Scalar0To1"]["Value"] == pytest.approx(0.3)
    assert applied["State"] == "On"
    assert applied["Temperature"]["ScalarTemperature"] == {"Value": 30, "Unit": "degC"}
    assert applied["SurfaceAreaFraction"]["Scalar0To1"]["Value"] == pytest.approx(0.6)


def test_active_heating_and_cooling_move_skin_temperature_oppositely(baseline):
    """Falsifies: heating and cooling are swapped or not sent. 200 W of heating is measured
    +0.61 C on skin at 120 s against the unperturbed run, with net heat gained through the
    skin; 200 W of cooling -0.62 C."""
    heated = _run(120, active_heating_W=200.0)
    cooled = _run(120, active_cooling_W=200.0)
    assert _skin(heated[120]) > _skin(baseline[120]) + 0.4
    assert _thermal(heated[120])["heat_loss"]["skin_W"] < 0.0
    assert _skin(cooled[120]) < _skin(baseline[120]) - 0.4


def test_heating_power_scales_with_area_fraction():
    """Falsifies: the area fraction is not sent. Pulse applies power x fraction, so
    500 W over 40% of the skin must match 200 W over all of it exactly."""
    full = _run(60, active_heating_W=200.0)
    partial = _run(60, active_heating_W=500.0, active_heating_area_fraction=0.4)
    assert _skin(partial[60]) == pytest.approx(_skin(full[60]), rel=1e-9)
    assert _skin(full[60]) != pytest.approx(_skin(_run(60, active_heating_W=500.0)[60]), rel=1e-6)


def test_applied_temperature_acts_only_when_on(baseline):
    """Falsifies: the applied temperature ignores its on/off switch. 10 C over the whole
    skin is measured -2.16 C on skin at 120 s, with 656 W flowing into the applied-
    temperature node; switched off, the same temperature has no effect at all."""
    on = _run(120, applied_temperature_on=1.0, applied_temperature_C=10.0)
    assert _skin(on[120]) < _skin(baseline[120]) - 1.5
    assert _thermal(on[120])["compartments"]["active"]["heat_in_W"] > 400.0
    off = _run(60, applied_temperature_on=0.0, applied_temperature_C=10.0)
    assert _skin(off[60]) == pytest.approx(_skin(baseline[60]), rel=1e-12)


def test_switching_heating_off_removes_the_application():
    """Falsifies: returning to zero power is not forwarded, or Pulse keeps the application.
    Under heating skin warms; after power returns to 0 Pulse's own state holds no thermal
    application and skin cools (measured 32.36 -> 32.67 C over 120 s of heating, then
    32.58 C 30 s after switching off and 32.34 C at 240 s)."""
    sim = _sim(active_heating_W=200.0)
    sim.run(120)
    assert _thermal_application_active(sim)
    sim.state["interventions"]["thermal"]["active_heating_W"] = 0.0
    sim.run(120)
    assert not _thermal_application_active(sim)
    rows = _rows(sim)
    assert _skin(rows[120]) > _skin(rows[0])
    assert _skin(rows[240]) < _skin(rows[120])
    assert _thermal(rows[240])["heat_loss"]["skin_W"] > 0.0


def test_thermal_application_baseline_is_inert():
    """Falsifies: the thermal_application baseline would perturb the patient if sent.
    Sending the whole group at its baseline must leave Pulse with no active application."""
    process = PulseCircuitProcess({"modules": ["thermal"]}, core=build_core())
    process.initial_state()
    engine = process._ensure_engine()
    engine.process_action(THERMAL.bindings[1].build(dict(THERMAL_APPLICATION_BASELINE), {}))
    engine.advance_time_s(1.0)
    import PyPulse

    state = json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))
    assert "ThermalApplication" not in json.dumps(state.get("ActiveActions", {}))
