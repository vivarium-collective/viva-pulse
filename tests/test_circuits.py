"""PulseCircuitProcess, the circuit module registry, and pulse_cardiovascular.

Engine tests drive the real Pulse build. Where a test needs an oracle, it is a
separate PulseEngine loaded directly through Pulse's own Python API, never a
restatement of the wrapper's own output. Each docstring names the proposition
that the test would falsify.
"""

import math

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.circuits import MODULES, ActionBinding, CircuitModule, Request
from viva_pulse.circuits.cardiovascular import CARDIOVASCULAR, MULTIPLIERS
from viva_pulse.composites import pulse_cardiovascular
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess
from viva_pulse.runtime import ensure_pulse_importable

SETPOINTS = {f"{m}_multiplier" for m in MULTIPLIERS} | {"hemorrhage_severity"}


def _leaves(tree, prefix=()):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _leaves(value, prefix + (key,))
        else:
            yield prefix + (key,), value


def _cv(row):
    return row["circuits"]["cardiovascular"]


# Oracle requests, written out with Pulse's own names and units, independent of
# the module's Request table: store path -> (compartment or None, property, unit class, unit).
ORACLE = {
    ("hemodynamics", "heart_rate_bpm"): (None, "HeartRate", "FrequencyUnit", "Per_min"),
    ("hemodynamics", "mean_arterial_pressure_mmHg"): (None, "MeanArterialPressure", "PressureUnit", "mmHg"),
    ("hemodynamics", "blood_volume_mL"): (None, "BloodVolume", "VolumeUnit", "mL"),
    ("central", "aorta", "pressure_mmHg"): ("Aorta", "Pressure", "PressureUnit", "mmHg"),
    ("central", "left_heart", "volume_mL"): ("LeftHeart", "Volume", "VolumeUnit", "mL"),
    ("renal", "left_kidney", "inflow_mL_per_min"): ("LeftKidneyVasculature", "Inflow", "VolumePerTimeUnit", "mL_Per_min"),
    ("renal", "right_glomerular_capillaries", "outflow_mL_per_min"):
        ("RightGlomerularCapillaries", "Outflow", "VolumePerTimeUnit", "mL_Per_min"),
    ("peripheral", "right_leg", "volume_mL"): ("RightLegVasculature", "Volume", "VolumeUnit", "mL"),
    ("peripheral", "brain", "inflow_mL_per_min"): ("BrainVasculature", "Inflow", "VolumePerTimeUnit", "mL_Per_min"),
}


def _direct_engine(paths, advance_s):
    """Oracle: an engine loaded straight through Pulse's API, advanced in one call."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = []
    for path in paths:
        compartment, prop, unit_cls, unit_name = ORACLE[path]
        unit = getattr(getattr(scalars, unit_cls), unit_name)
        requests.append(SEDataRequest.create_liquid_compartment_request(compartment, prop, unit=unit)
                        if compartment else SEDataRequest.create_physiology_request(prop, unit=unit))
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"),
                                      SEDataRequestManager(requests))
    engine.advance_time_s(0.0)
    if advance_s:
        engine.advance_time_s(advance_s)
    return [float(v) for v in engine.pull_data()[1:]]


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


def _active_actions(process):
    """Pulse's own serialized state, used to see which actions are active in the engine."""
    import PyPulse

    return process._engine.serialize_to_string(PyPulse.serialization_format.json)


def _baseline_setpoints(**changes):
    values = {f"{m}_multiplier": 1.0 for m in MULTIPLIERS}
    values["hemorrhage_severity"] = 0.0
    values.update(changes)
    return {"setpoints": {"cardiovascular": values}}


# -- registry and configuration (no engine) ------------------------------------


def test_cardiovascular_module_covers_the_diagram_branches():
    """Falsifies: the module silently lost a diagram branch or a compartment property."""
    groups = {r.path[0] for r in CARDIOVASCULAR.outputs}
    assert groups == {"hemodynamics", "central", "renal", "peripheral"}
    compartments = {r.compartment for r in CARDIOVASCULAR.outputs if r.compartment}
    assert {"Aorta", "LeftHeart", "RightHeart", "VenaCava", "PulmonaryCapillaries",
            "LeftKidneyVasculature", "BrainVasculature", "RightLegVasculature"} <= compartments
    # 20 system scalars + (10 central + 8 renal + 14 peripheral) compartments x 4
    # properties, minus Pericardium's 2 flows
    assert len(CARDIOVASCULAR.outputs) == 20 + (10 + 8 + 14) * 4 - 2
    assert MODULES["cardiovascular"] is CARDIOVASCULAR


@pytest.mark.parametrize("kwargs, match", [
    ({"name": "setpoints"}, "reserved"),
    ({"model_types": frozenset({"martian"})}, "unknown model types"),
    ({"outputs": (Request(("a",), "physiology", "HeartRate", None),
                  Request(("a",), "physiology", "BloodVolume", None))}, "duplicate output paths"),
    ({"outputs": (Request(("a",), "physiology", "HeartRate", None),
                  Request(("a", "b"), "physiology", "BloodVolume", None))}, "prefix"),
    ({"bindings": (ActionBinding({"x": 0.0}, build=lambda v, c: None),
                   ActionBinding({"x": 0.0}, build=lambda v, c: None))}, "duplicate setpoint"),
])
def test_circuit_module_rejects_inconsistent_definitions(kwargs, match):
    """Falsifies: a malformed module definition is accepted and fails later, inside a run."""
    base = {"name": "m", "model_types": frozenset({"whole_body"}),
            "outputs": (Request(("a",), "physiology", "HeartRate", None),)}
    with pytest.raises(ValueError, match=match):
        CircuitModule(**{**base, **kwargs})


@pytest.mark.parametrize("config, match", [
    ({}, "at least one"),
    ({"modules": ["kidneys"]}, "unknown circuit modules"),
    ({"modules": ["cardiovascular", "cardiovascular"]}, "more than once"),
    ({"modules": ["cardiovascular"], "model_type": "hemodynamics"}, r"\(known\) is not supported"),
    ({"modules": ["cardiovascular"], "model_type": "mouse"}, r"\(unknown\) is not supported"),
    ({"modules": ["cardiovascular"], "hemorrhage_compartment": "Thumb"}, "hemorrhage_compartment"),
])
def test_process_rejects_invalid_config(config, match):
    """Falsifies: an invalid configuration silently runs a different model (e.g. a
    'hemodynamics' request quietly running WholeBody, as PulseEngine.py itself does)."""
    with pytest.raises(ValueError, match=match):
        PulseCircuitProcess(config, core=build_core())


def test_modules_override_replaces_the_default_list():
    """Falsifies: the modules override doesn't reach the process config as given (exactly
    the modules named, nothing added)."""
    process = PulseCircuitProcess({"modules": ["cardiovascular"]}, core=build_core())
    assert process.config["modules"] == ["cardiovascular"]


@pytest.mark.parametrize("values, match", [
    ({**{f"{m}_multiplier": 1.0 for m in MULTIPLIERS}, "venous_compliance_multiplier": 0.0}, "> 0"),
    ({**{f"{m}_multiplier": 1.0 for m in MULTIPLIERS}, "heart_rate_multiplier": -1.0}, "> 0"),
])
def test_multiplier_validation(values, match):
    """Falsifies: a non-positive multiplier (a cut or inverted vessel) reaches Pulse."""
    binding = CARDIOVASCULAR.bindings[0]
    with pytest.raises(ValueError, match=match):
        binding.validate(values, {})


@pytest.mark.parametrize("severity", [-0.1, 1.5])
def test_hemorrhage_severity_validation(severity):
    """Falsifies: an out-of-range severity reaches Pulse."""
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        CARDIOVASCULAR.bindings[1].validate({"hemorrhage_severity": severity}, {})


def test_default_setpoints_pass_their_validators():
    """Falsifies: a module's own baseline is rejected by its validator, so an untouched
    run would fail on its first setpoint change back to baseline."""
    for binding in CARDIOVASCULAR.bindings:
        binding.validate(dict(binding.ports), {"hemorrhage_compartment": "RightLeg"})


@pytest.mark.parametrize("params, match", [
    ({"hemorrhage_severity": 1.5}, r"\[0, 1\]"),
    ({"systemic_resistance_multiplier": 0.0}, "> 0"),
    ({"hemorrhage_compartment": "Thumb"}, "hemorrhage_compartment"),
])
def test_generator_validates_parameters_when_building(params, match):
    """Falsifies: a bad parameter only fails deep inside sim.run()."""
    with pytest.raises(ValueError, match=match):
        pulse_cardiovascular(None, **params)


def test_generator_rejects_unknown_parameters():
    """Falsifies: a misspelled multiplier is silently ignored and the run is unmodified."""
    with pytest.raises(TypeError, match="unexpected"):
        pulse_cardiovascular(None, sytemic_resistance_multiplier=2.0)


# -- real engine ----------------------------------------------------------------


def test_stores_hold_only_their_own_ports(run_composite):
    """Falsifies: initial_state() leaks readings into the setpoint store (or setpoints
    into the readings store). Regression: input and output ports once shared the
    module name, and readings landed in interventions/cardiovascular."""
    _, rows = run_composite(pulse_cardiovascular, 2)
    for row in rows:
        assert set(row["interventions"]["cardiovascular"]) == SETPOINTS
        assert set(_cv(row)) == {"hemodynamics", "central", "renal", "peripheral"}


def test_setpoints_default_to_baseline_without_interventions():
    """Falsifies: an omitted setpoint defaults to 0.0 (zeroing every vessel's resistance)."""
    core = build_core()
    doc = pulse_cardiovascular(core)
    del doc["interventions"]
    sim = Composite({"state": doc}, core=core)
    sim.run(1)
    row = gather_emitter_results(sim)[("emitter",)][-1]
    expected = {p: (0.0 if p == "hemorrhage_severity" else 1.0) for p in SETPOINTS}
    assert row["interventions"]["cardiovascular"] == expected


def test_first_row_carries_loaded_values(run_composite):
    """Falsifies: nested delta ports start from 0 instead of Pulse's loaded state."""
    paths = [("hemodynamics", "mean_arterial_pressure_mmHg"), ("central", "aorta", "pressure_mmHg"),
             ("peripheral", "right_leg", "volume_mL"), ("renal", "left_kidney", "inflow_mL_per_min")]
    oracle = _direct_engine(paths, 0.0)
    _, rows = run_composite(pulse_cardiovascular, 1)
    assert rows[0]["time"] == 0.0
    for path, expected in zip(paths, oracle):
        assert _at(_cv(rows[0]), path) == pytest.approx(expected, rel=1e-9), path


def test_store_tracks_pulse_after_accumulating_deltas(run_composite):
    """Falsifies: deltas accumulate wrongly or land on the wrong store (request-index
    mix-up). The stores after 20 one-second updates must equal an independent engine
    advanced 20 s in one call."""
    paths = [("hemodynamics", "heart_rate_bpm"), ("hemodynamics", "blood_volume_mL"),
             ("central", "aorta", "pressure_mmHg"), ("central", "left_heart", "volume_mL"),
             ("renal", "right_glomerular_capillaries", "outflow_mL_per_min"),
             ("peripheral", "brain", "inflow_mL_per_min")]
    oracle = _direct_engine(paths, 20.0)
    _, rows = run_composite(pulse_cardiovascular, 20)
    for path, expected in zip(paths, oracle):
        assert _at(_cv(rows[-1]), path) == pytest.approx(expected, rel=1e-6, abs=1e-6), path


def test_every_reading_is_finite(run_composite):
    """Falsifies: a request Pulse cannot serve silently emits NaN."""
    _, rows = run_composite(pulse_cardiovascular, 5)
    for row in rows:
        bad = [p for p, v in _leaves(_cv(row)) if not math.isfinite(v)]
        assert not bad, bad


def test_unserved_request_fails_the_load(monkeypatch):
    """Falsifies: the NaN guard does not fire. Pulse returns NaN for Pericardium Inflow
    (a pressure space with no blood path); the load must fail and name it."""
    probe = CircuitModule(name="probe", model_types=frozenset({"whole_body"}),
                          outputs=(Request(("inflow",), "liquid_compartment", "Inflow",
                                           ("VolumePerTimeUnit", "mL_Per_min"), compartment="Pericardium"),))
    monkeypatch.setitem(MODULES, "probe", probe)
    process = PulseCircuitProcess({"modules": ["probe"]}, core=build_core())
    with pytest.raises(ValueError, match="Pericardium.Inflow"):
        process.initial_state()


def test_systemic_resistance_multiplier_reaches_the_circuit(run_composite):
    """Falsifies: the multiplier action is never applied. Doubling systemic resistance
    in Pulse triggers the baroreflex: SVR rises and heart rate falls (measured 72 -> 43
    bpm at 60 s; baseline drift is < 0.1 bpm)."""
    _, base = run_composite(pulse_cardiovascular, 60)
    _, high = run_composite(pulse_cardiovascular, 60, systemic_resistance_multiplier=2.0)
    hb, hh = _cv(base[-1])["hemodynamics"], _cv(high[-1])["hemodynamics"]
    assert hh["systemic_vascular_resistance_mmHg_min_per_L"] > 1.3 * hb["systemic_vascular_resistance_mmHg_min_per_L"]
    assert hh["heart_rate_bpm"] < hb["heart_rate_bpm"] - 15.0
    assert hh["cardiac_output_L_per_min"] < hb["cardiac_output_L_per_min"]


def test_setpoint_changed_mid_run_is_forwarded():
    """Falsifies: act-on-change misses a setpoint written to the store during a run."""
    core = build_core()
    sim = Composite({"state": pulse_cardiovascular(core)}, core=core)
    sim.run(10)
    sim.state["interventions"]["cardiovascular"]["systemic_resistance_multiplier"] = 2.0
    sim.run(50)
    rows = gather_emitter_results(sim)[("emitter",)]
    assert rows[-1]["interventions"]["cardiovascular"]["systemic_resistance_multiplier"] == 2.0
    hr = [_cv(r)["hemodynamics"]["heart_rate_bpm"] for r in rows]
    assert abs(hr[10] - hr[0]) < 1.0          # unmodified for the first 10 s
    assert hr[-1] < hr[10] - 15.0             # then the reflex response to 2x SVR


def test_hemorrhage_mass_balance(run_composite):
    """Falsifies: the hemorrhage action, or one of the volume readings, is not wired
    to the right store. Over 120 s the blood volume deficit equals the volume Pulse
    reports lost (measured 355 vs 360 mL) and the bleeding limb loses volume."""
    _, rows = run_composite(pulse_cardiovascular, 120, hemorrhage_compartment="RightLeg",
                            hemorrhage_severity=0.8)
    first, last = _cv(rows[0]), _cv(rows[-1])
    lost = last["hemodynamics"]["total_hemorrhaged_volume_mL"]
    deficit = first["hemodynamics"]["blood_volume_mL"] - last["hemodynamics"]["blood_volume_mL"]
    assert lost > 200.0
    assert deficit == pytest.approx(lost, rel=0.05)
    assert last["peripheral"]["right_leg"]["volume_mL"] < 0.8 * first["peripheral"]["right_leg"]["volume_mL"]
    assert last["peripheral"]["left_leg"]["volume_mL"] > 0.9 * first["peripheral"]["left_leg"]["volume_mL"]


def test_irreversible_state_latches_and_freezes_readings(run_composite):
    """Falsifies: the irreversible_state flag never sets, or the readings keep
    changing after death. Aorta severity 1.0 is irreversible at ~68 s. Pulse itself
    refuses to advance once irreversible (``Controller.cpp:790``), so this pins the
    output contract; it cannot tell whether the process's own latch is present."""
    _, rows = run_composite(pulse_cardiovascular, 100, hemorrhage_compartment="Aorta",
                            hemorrhage_severity=1.0)
    flags = [r["circuits"]["irreversible_state"] for r in rows]
    assert not flags[0] and flags[-1]
    first_dead = flags.index(True)
    frozen = [_cv(r)["hemodynamics"]["blood_volume_mL"] for r in rows[first_dead:]]
    assert len(set(frozen)) == 1


def test_invalid_setpoint_sends_no_action():
    """Falsifies: validation runs per group, so a valid multiplier change is sent to
    Pulse before an invalid severity in the same update raises. Oracle: the actions
    active in Pulse's own serialized state."""
    process = PulseCircuitProcess({"modules": ["cardiovascular"]}, core=build_core())
    process.initial_state()
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        process.update(_baseline_setpoints(systemic_resistance_multiplier=2.0,
                                           hemorrhage_severity=1.5), 1.0)
    assert "CardiovascularMechanicsModification" not in _active_actions(process)
    process.update(_baseline_setpoints(systemic_resistance_multiplier=2.0), 1.0)
    assert "CardiovascularMechanicsModification" in _active_actions(process)


def test_changing_one_multiplier_keeps_the_others(run_composite):
    """Falsifies: only the changed multiplier is sent. Pulse replaces the whole modifier
    set on every send (``PBPatientActions`` clears first), so a partial send would drop
    the earlier systemic x2. The run must end where a plain systemic x2 run ends."""
    _, plain = run_composite(pulse_cardiovascular, 60, systemic_resistance_multiplier=2.0)
    core = build_core()
    sim = Composite({"state": pulse_cardiovascular(core, systemic_resistance_multiplier=2.0)}, core=core)
    sim.run(10)
    sim.state["interventions"]["cardiovascular"]["heart_rate_multiplier"] = 1.0000001
    sim.run(50)
    rows = gather_emitter_results(sim)[("emitter",)]
    for key in ("systemic_vascular_resistance_mmHg_min_per_L", "heart_rate_bpm"):
        assert _cv(rows[-1])["hemodynamics"][key] == pytest.approx(
            _cv(plain[-1])["hemodynamics"][key], rel=1e-3), key


def test_returning_multipliers_to_baseline_removes_the_modification():
    """Falsifies: a return to 1.0 is never sent, leaving the modification active in Pulse."""
    process = PulseCircuitProcess({"modules": ["cardiovascular"]}, core=build_core())
    process.initial_state()
    process.update(_baseline_setpoints(systemic_resistance_multiplier=2.0), 1.0)
    assert "CardiovascularMechanicsModification" in _active_actions(process)
    process.update(_baseline_setpoints(), 1.0)
    assert "CardiovascularMechanicsModification" not in _active_actions(process)


def test_setting_severity_to_zero_stops_the_bleed():
    """Falsifies: a severity change back to 0 is not forwarded and the bleed continues."""
    core = build_core()
    sim = Composite({"state": pulse_cardiovascular(core, hemorrhage_severity=0.8)}, core=core)
    sim.run(30)
    sim.state["interventions"]["cardiovascular"]["hemorrhage_severity"] = 0.0
    sim.run(30)
    lost = [_cv(r)["hemodynamics"]["total_hemorrhaged_volume_mL"] for r in gather_emitter_results(sim)[("emitter",)]]
    assert lost[30] > 50.0
    assert lost[-1] == pytest.approx(lost[32], abs=1e-6)


def test_identical_requests_across_modules_share_values(monkeypatch):
    """Falsifies: request dedupe maps a shared request to the wrong store. A second module
    requesting the same Pulse value as the cardiovascular module must see identical
    readings, equal to an independent engine."""
    twin = CircuitModule(name="twin", model_types=frozenset({"whole_body"}),
                         outputs=(Request(("map",), "physiology", "MeanArterialPressure", ("PressureUnit", "mmHg")),
                                  Request(("aorta",), "liquid_compartment", "Pressure", ("PressureUnit", "mmHg"),
                                          compartment="Aorta")))
    monkeypatch.setitem(MODULES, "twin", twin)
    process = PulseCircuitProcess({"modules": ["cardiovascular", "twin"]}, core=build_core())
    assert len(process._requests) == len(CARDIOVASCULAR.outputs)
    state = process.initial_state()
    for _ in range(5):
        delta = process.update(_baseline_setpoints(), 1.0)
        for path, value in _leaves(delta):
            node = state
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] += value
    oracle = _direct_engine([("hemodynamics", "mean_arterial_pressure_mmHg"), ("central", "aorta", "pressure_mmHg")], 5.0)
    assert state["twin"]["map"] == state["cardiovascular"]["hemodynamics"]["mean_arterial_pressure_mmHg"]
    assert state["twin"]["aorta"] == state["cardiovascular"]["central"]["aorta"]["pressure_mmHg"]
    assert [state["twin"]["map"], state["twin"]["aorta"]] == pytest.approx(oracle, rel=1e-6)
