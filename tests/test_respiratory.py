"""Respiratory and mechanical-ventilator modules, on the VentilationMechanics and
WholeBody engines.

Engine tests drive the real Pulse build. Oracles are separate engines loaded
directly through Pulse's API with requests spelled out here, or effect sizes
measured on the real engine (recorded in .build-progress.md, Phase 2). Each
docstring names the proposition the test would falsify.
"""

import math

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.circuits import MODULES
from viva_pulse.circuits.respiratory import (MECHANICAL_VENTILATOR, MULTIPLIERS, RESPIRATORY,
                                             VENTILATOR_BASELINE)
from viva_pulse.composites import pulse_mechanical_ventilation, pulse_respiratory
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess
from viva_pulse.runtime import ensure_pulse_importable

ENGINES = ("ventilation_mechanics", "whole_body")


def _mech(row):
    return row["circuits"]["respiratory"]["mechanics"]


def _vent(row):
    return row["circuits"]["mechanical_ventilator"]


def _leaves(tree, prefix=()):
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _leaves(value, prefix + (key,))
        else:
            yield prefix + (key,), value


def _run(generator, duration, change=None, **params):
    """Run a generator; ``change`` = (time, module, {port: value}) written mid-run."""
    core = build_core()
    sim = Composite({"state": generator(core, **params)}, core=core)
    if change:
        at, module, values = change
        sim.run(at)
        sim.state["interventions"][module].update(values)
        sim.run(duration - at)
    else:
        sim.run(duration)
    return sim, gather_emitter_results(sim)[("emitter",)]


# Independent oracle requests: store path -> (gas compartment or None, property, unit class, unit)
ORACLE = {
    ("mechanics", "tidal_volume_mL"): (None, "TidalVolume", "VolumeUnit", "mL"),
    ("mechanics", "respiration_rate_bpm"): (None, "RespirationRate", "FrequencyUnit", "Per_min"),
    ("mechanics", "total_lung_volume_mL"): (None, "TotalLungVolume", "VolumeUnit", "mL"),
    ("lungs", "left_alveoli", "absolute_pressure_cmH2O"): ("LeftAlveoli", "Pressure", "PressureUnit", "cmH2O"),
    ("lungs", "right_lung", "volume_mL"): ("RightLungPulmonary", "Volume", "VolumeUnit", "mL"),
    ("pleura", "left_pleural_cavity", "absolute_pressure_cmH2O"): ("LeftPleuralCavity", "Pressure", "PressureUnit", "cmH2O"),
}


def _direct_engine(model_type, at_engine_time_s):
    """Oracle engine through Pulse's API, advanced to an absolute engine time."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.cdm.patient import SEPatientConfiguration
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = []
    for compartment, prop, unit_cls, unit_name in ORACLE.values():
        unit = getattr(getattr(scalars, unit_cls), unit_name)
        requests.append(SEDataRequest.create_gas_compartment_request(compartment, prop, unit=unit)
                        if compartment else SEDataRequest.create_physiology_request(prop, unit=unit))
    manager = SEDataRequestManager(requests)
    if model_type == "whole_body":
        engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
        engine.log_to_console(False)
        assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"), manager)
    else:
        engine = PulseEngine(eModelType.HumanAdultVentilationMechanics, f"{bin_dir}/")
        engine.log_to_console(False)
        configuration = SEPatientConfiguration()
        configuration.set_data_root_dir(f"{bin_dir}/")
        configuration.set_patient_file(str(bin_dir / "patients" / "StandardMale.json"))
        assert engine.initialize_engine(configuration, manager)
    engine.advance_time_s(0.0)
    if at_engine_time_s:
        engine.advance_time_s(at_engine_time_s)
    return [float(v) for v in engine.pull_data()[1:]]


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


def _setpoints(respiratory=None, ventilator=None):
    values = {"respiratory": {**{f"{m}_multiplier": 1.0 for m in MULTIPLIERS}, "intubated": 0.0,
                              **(respiratory or {})}}
    if ventilator is not None:
        values["mechanical_ventilator"] = {**VENTILATOR_BASELINE, **ventilator}
    return {"setpoints": values}


# -- registry and configuration (no engine) ------------------------------------


def test_modules_cover_the_airway_circuit_and_run_on_both_engines():
    """Falsifies: a module lost a compartment group or is not allowed on an engine
    that serves all of its requests (probe P6)."""
    assert {r.path[0] for r in RESPIRATORY.outputs} == {"mechanics", "lungs", "pleura"}
    assert {r.compartment for r in RESPIRATORY.outputs if r.compartment} >= {
        "Trachea", "LeftAlveoli", "RightAlveoli", "LeftLungPulmonary", "LeftPleuralCavity"}
    assert len(RESPIRATORY.outputs) == 24 + (6 + 2) * 4
    assert len(MECHANICAL_VENTILATOR.outputs) == 18
    for module in (RESPIRATORY, MECHANICAL_VENTILATOR):
        assert module.model_types == frozenset(ENGINES)
        assert MODULES[module.name] is module


def test_cardiovascular_module_is_rejected_on_ventilation_mechanics():
    """Falsifies: a module is loaded on an engine that lacks its system (VentilationMechanics
    has no blood), which would only show up later as NaN or a crash."""
    with pytest.raises(ValueError, match="does not support model_type"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["cardiovascular"]},
                            core=build_core())


def test_state_file_on_ventilation_mechanics_raises():
    """Falsifies: a state file on VentilationMechanics (which has no serialization) is
    silently ignored, so the run uses a different patient than the one asked for.
    (WholeBody takes either file; tests/test_patients.py covers it.)"""
    with pytest.raises(ValueError, match="state_file .* is not used by model_type"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                             "state_file": "StandardFemale@0s.json"}, core=build_core())


def test_default_setpoints_pass_their_validators():
    """Falsifies: a module's own baseline is rejected by its validator."""
    config = {"intubation_type": "Tracheal", "ventilator_mode": "AssistedControl"}
    for module in (RESPIRATORY, MECHANICAL_VENTILATOR):
        for binding in module.bindings:
            binding.validate(dict(binding.ports), config)


@pytest.mark.parametrize("changes, match", [
    ({"connected": 0.5}, "0 or 1"),
    ({"respiration_rate_bpm": 0.0}, "> 0"),
    ({"respiration_rate_bpm": 30.0, "inspiratory_period_s": 2.5}, "inspiratory_period_s"),
    ({"slope_s": 1.5}, "slope_s"),
    ({"peep_cmH2O": 25.0}, "peep_cmH2O"),
    ({"fraction_inspired_oxygen": 1.2}, "fraction_inspired_oxygen"),
])
def test_ventilator_validation(changes, match):
    """Falsifies: a ventilator setting that Pulse's own ToSettings would reject (or that is
    physically meaningless) reaches the engine."""
    with pytest.raises(ValueError, match=match):
        MECHANICAL_VENTILATOR.bindings[0].validate({**VENTILATOR_BASELINE, **changes}, {})


@pytest.mark.parametrize("generator, params, match", [
    (pulse_respiratory, {"intubation_type": "Nostril"}, "intubation_type"),
    (pulse_respiratory, {"left_compliance_multiplier": 0.0}, "> 0"),
    (pulse_mechanical_ventilation, {"ventilator_mode": "Turbo"}, "ventilator_mode"),
    (pulse_mechanical_ventilation, {"peep_cmH2O": 30.0}, "peep_cmH2O"),
    (pulse_mechanical_ventilation, {"tidal_volme": 1.0}, "unexpected"),
])
def test_generators_validate_parameters_when_building(generator, params, match):
    """Falsifies: a bad parameter only fails deep inside sim.run()."""
    with pytest.raises((ValueError, TypeError), match=match):
        generator(None, **params)


# -- real engine ----------------------------------------------------------------


@pytest.mark.parametrize("model_type", ENGINES)
def test_store_tracks_pulse(model_type):
    """Falsifies: the patient-initialized load path (VentilationMechanics), the gas-
    compartment requests, or the store mapping is wrong. Stores after 20 one-second
    updates must equal an independent engine at the same engine time."""
    sim, rows = _run(pulse_respiratory, 20, model_type=model_type)
    # Pulse accumulates engine time as a float (e.g. 25.9999999999995 s); advancing an
    # oracle by that would floor to one 0.02 s step fewer, so round to the timestep.
    engine_time = round(sim.state["pulse"]["instance"]._engine.pull_data()[0] / 0.02) * 0.02
    oracle = _direct_engine(model_type, engine_time)
    for path, expected in zip(ORACLE, oracle):
        assert _at(rows[-1]["circuits"]["respiratory"], path) == pytest.approx(expected, rel=1e-6, abs=1e-6), path


def test_ventilation_mechanics_settles_before_time_zero():
    """Falsifies: the VentilationMechanics engine starts unsettled. It does no
    stabilization, so PeakInspiratoryPressure is NaN until the first breath; without
    settling the load fails (NaN guard) or the first row is meaningless."""
    sim, rows = _run(pulse_mechanical_ventilation, 2)
    assert sim.state["pulse"]["instance"]._engine.pull_data()[0] > 0.0
    for row in rows:
        bad = [p for p, v in _leaves(row["circuits"]["respiratory"]) if not math.isfinite(v)]
        assert not bad, bad
    assert math.isfinite(_mech(rows[0])["peak_inspiratory_pressure_cmH2O"])


@pytest.mark.parametrize("max_settle_s", [2.5, 0.0])
def test_settling_that_runs_out_names_the_unserved_request(max_settle_s):
    """Falsifies: an engine still unsettled after max_settle_s starts anyway with NaN
    stores. The first breath completes after ~6 s, so 2.5 s must fail the load, naming
    the request. 0.0 means no settling (bigraph-schema before 1.8.3 replaced an explicit
    0.0 with the 30 s default, so that load succeeded)."""
    process = PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                                   "max_settle_s": max_settle_s}, core=build_core())
    with pytest.raises(ValueError, match="NaN for: physiology:PeakInspiratoryPressure"):
        process.initial_state()


def test_missing_patient_file_raises():
    """Falsifies: a patient file that does not exist reaches Pulse (whose failure would
    be a log line or a crash) instead of failing with its path."""
    process = PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                                   "patient_file": "NoSuchPatient.json"}, core=build_core())
    with pytest.raises(FileNotFoundError, match="NoSuchPatient.json"):
        process.initial_state()


def test_compliance_drop_is_compensated_only_when_coupled():
    """Falsifies: the multiplier action is not applied, or the engine choice has no
    effect. Halving lung compliance cuts tidal volume on both engines (measured
    471 -> 270 mL isolated, 510 -> 388 mL coupled); only the whole-body engine's
    chemoreflex raises the rate (12.0 -> 15.0); the isolated airway keeps 12.0."""
    half = {"left_compliance_multiplier": 0.5, "right_compliance_multiplier": 0.5}
    results = {}
    for model_type in ENGINES:
        _, base = _run(pulse_respiratory, 60, model_type=model_type)
        _, stiff = _run(pulse_respiratory, 60, model_type=model_type, **half)
        results[model_type] = (_mech(base[-1]), _mech(stiff[-1]))
    vm_base, vm_stiff = results["ventilation_mechanics"]
    wb_base, wb_stiff = results["whole_body"]
    assert vm_stiff["tidal_volume_mL"] < 0.7 * vm_base["tidal_volume_mL"]
    assert wb_stiff["tidal_volume_mL"] < 0.85 * wb_base["tidal_volume_mL"]
    assert vm_stiff["respiration_rate_bpm"] == pytest.approx(vm_base["respiration_rate_bpm"], abs=0.5)
    assert wb_stiff["respiration_rate_bpm"] > wb_base["respiration_rate_bpm"] + 2.0


@pytest.mark.parametrize("model_type", ENGINES)
def test_ventilator_delivers_its_settings(model_type):
    """Falsifies: the pressure-control action is not built from the setpoints (e.g. it
    hard-codes the HowTo defaults 19/5 cmH2O, 12 bpm, 1.0 s, FiO2 0.21). Every setting
    is non-default; the ventilator's own monitor and the airway must
    report them (measured PIP 21.98, PEEP 7.19-7.25, RR 15.96, I:E 0.47 = 1.2/2.55,
    FiO2 0.4). Mandatory mode, because in AssistedControl a rate above the patient's
    own can lock Pulse into auto-triggering (.build-progress.md, Phase 2)."""
    _, rows = _run(pulse_mechanical_ventilation, 60, model_type=model_type,
                   ventilator_mode="ContinuousMandatoryVentilation", inspiratory_pressure_cmH2O=22.0,
                   peep_cmH2O=7.0, respiration_rate_bpm=16.0, inspiratory_period_s=1.2,
                   fraction_inspired_oxygen=0.4)
    vent = _vent(rows[-1])
    assert vent["peak_inspiratory_pressure_cmH2O"] == pytest.approx(22.0, abs=0.5)
    assert vent["total_peep_cmH2O"] == pytest.approx(7.0, abs=0.5)
    assert vent["respiration_rate_bpm"] == pytest.approx(16.0, abs=0.5)
    assert vent["inspiratory_expiratory_ratio"] == pytest.approx(1.2 / (60 / 16 - 1.2), abs=0.02)
    assert _mech(rows[-1])["fraction_inspired_oxygen"] == pytest.approx(0.4, abs=0.01)


@pytest.mark.parametrize("model_type", ENGINES)
def test_ventilator_reconnects(model_type):
    """Falsifies: once disconnected (a configuration action), the ventilator cannot be
    reconnected by the pressure-control action (measured PEEP 5.01 -> 0.0 -> 5.01)."""
    core = build_core()
    sim = Composite({"state": pulse_mechanical_ventilation(core, model_type=model_type)}, core=core)
    sim.run(40)
    sim.state["interventions"]["mechanical_ventilator"]["connected"] = 0.0
    sim.run(40)
    sim.state["interventions"]["mechanical_ventilator"]["connected"] = 1.0
    sim.run(40)
    rows = gather_emitter_results(sim)[("emitter",)]
    assert _vent(rows[40])["total_peep_cmH2O"] == pytest.approx(5.0, abs=0.3)
    assert _vent(rows[80])["total_peep_cmH2O"] < 0.5
    assert _vent(rows[-1])["total_peep_cmH2O"] == pytest.approx(5.0, abs=0.3)
    assert _vent(rows[-1])["peak_inspiratory_pressure_cmH2O"] == pytest.approx(19.0, abs=0.5)


@pytest.mark.parametrize("model_type", ENGINES)
def test_disconnecting_the_ventilator_removes_peep(model_type):
    """Falsifies: connected = 0 does not disconnect, e.g. because the action is dropped
    by Pulse's Python API (a bare pressure-control action with connection Off fails its
    is_valid, and the ventilator keeps running at PEEP 5). PEEP must fall to ~0
    (measured 5.01 -> 0.0)."""
    _, rows = _run(pulse_mechanical_ventilation, 120, model_type=model_type,
                   change=(60, "mechanical_ventilator", {"connected": 0.0}))
    assert _vent(rows[60])["total_peep_cmH2O"] == pytest.approx(5.0, abs=0.3)
    assert _vent(rows[-1])["total_peep_cmH2O"] < 0.5
    assert _mech(rows[-1])["total_peep_cmH2O"] < 0.5


def test_changing_peep_mid_run_is_forwarded():
    """Falsifies: a changed ventilator setting is not re-sent (measured 5.0 -> 10.0)."""
    _, rows = _run(pulse_mechanical_ventilation, 120, change=(60, "mechanical_ventilator", {"peep_cmH2O": 10.0}))
    assert _vent(rows[60])["total_peep_cmH2O"] == pytest.approx(5.0, abs=0.3)
    assert _vent(rows[-1])["total_peep_cmH2O"] == pytest.approx(10.0, abs=0.5)


def test_intubation_raises_airway_resistance():
    """Falsifies: the intubation action is not sent. An endotracheal tube raises
    inspiratory resistance from 1.5 to ~10 cmH2O·s/L (measured 10.2)."""
    _, rows = _run(pulse_respiratory, 30, change=(10, "respiratory", {"intubated": 1.0}))
    assert _mech(rows[5])["inspiratory_resistance_cmH2O_s_per_L"] == pytest.approx(1.5, abs=0.1)
    assert _mech(rows[-1])["inspiratory_resistance_cmH2O_s_per_L"] > 8.0


def test_extubation_raises_instead_of_being_silently_dropped():
    """Falsifies: an extubation is accepted although Pulse's Python API drops it
    (SEIntubation.is_valid rejects Off), leaving the store saying 'not intubated'
    while the engine stays intubated."""
    process = PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"]},
                                  core=build_core())
    process.initial_state()
    process.update(_setpoints({"intubated": 1.0}), 1.0)
    with pytest.raises(ValueError, match="extubation"):
        process.update(_setpoints({"intubated": 0.0}), 1.0)
