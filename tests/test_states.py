"""Saving engine states during a run (``viva_pulse.states``). Real Pulse; nothing is mocked.

The uninterrupted engine is the oracle for a reloaded state. Each docstring names the
proposition the test would falsify.
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

import viva_pulse
from viva_pulse.core import build_core
from viva_pulse.processes import VITALS, PulseProcess, _initialize_engine, _load_engine
from viva_pulse.runtime import ensure_pulse_importable
from viva_pulse.states import save_states


def _requests():
    ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest

    return [SEDataRequest.create_physiology_request(p, getattr(getattr(scalars, c), u) if c else None)
            for p, c, u in VITALS.values()]


def _bleeding():
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", _requests())
    from pulse.cdm.patient_actions import SEHemorrhage, eHemorrhage_Compartment

    action = SEHemorrhage()
    action.set_compartment(eHemorrhage_Compartment.RightLeg)
    action.get_severity().set_value(0.5)
    engine.process_action(action)
    return engine


def _time(path):
    return json.loads(path.read_text())["SimulationTime"]["ScalarTime"].get("Value", 0.0)


def test_states_are_saved_at_each_time_and_named_by_it(tmp_path):
    """Falsifies: a file is saved at the wrong time (its recorded SimulationTime or the engine's
    time differs from the request), named by something other than its time, or a time is
    skipped. A time equal to the current one saves without advancing."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    paths = save_states(engine, tmp_path, [0, 2.5, 10], name="male")
    assert [p.name for p in paths] == ["male@0s.json", "male@2.5s.json", "male@10s.json"]
    for path, t in zip(paths, [0, 2.5, 10]):
        assert _time(path) == pytest.approx(t, abs=1e-9)
    assert engine.pull_data()[0] == pytest.approx(10, abs=1e-9)


def test_a_saved_state_continues_the_run(tmp_path):
    """Falsifies: a saved state does not continue the run it came from. Saved during a
    hemorrhage at 10 s and advanced 20 s, every vital must agree with the uninterrupted run
    (probe: 2e-8 relative, not bit-identical), including the blood lost, so the bleed (its
    run-time path, link and action) is in the state."""
    run = _bleeding()
    (path,) = save_states(run, tmp_path, [10.0], name="bleed")
    state = json.loads(path.read_text())
    assert "RightLeg1Hemorrhage" in {p["CircuitPath"]["Name"] for p in state["CircuitManager"]["FluidPath"]}
    assert run.advance_time_s(20.0)
    uninterrupted = dict(zip(VITALS, run.pull_data()[1:]))

    resumed_engine = _load_engine("", "HumanAdultWholeBody", str(path), _requests())
    assert resumed_engine.advance_time_s(20.0)
    resumed = dict(zip(VITALS, resumed_engine.pull_data()[1:]))
    for name in VITALS:
        assert resumed[name] == pytest.approx(uninterrupted[name], rel=1e-6), name
    assert uninterrupted["total_hemorrhaged_volume_mL"] > 50  # the bleed ran on after the save


def test_a_saved_state_starts_a_process(tmp_path):
    """Falsifies: a saved state can't be a process's state_file (the checkpoint-and-branch use)."""
    (path,) = save_states(_bleeding(), tmp_path, [10.0], name="bleed")
    vitals = PulseProcess({"state_file": str(path)}, core=build_core()).initial_state()
    assert vitals["total_hemorrhaged_volume_mL"] > 0


@pytest.mark.parametrize("times, message", [
    ([], "empty"),
    ([5, 5], "strictly increasing"),
    ([10, 5], "strictly increasing"),
    ([math.nan], "finite"),
])
def test_bad_times_raise(tmp_path, times, message):
    """Falsifies: an empty, repeated, decreasing or non-finite time list is accepted."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    with pytest.raises(ValueError, match=message):
        save_states(engine, tmp_path, times)


def test_a_time_before_the_engine_raises(tmp_path):
    """Falsifies: a time already past is silently saved at the current time instead."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    save_states(engine, tmp_path, [5])
    with pytest.raises(ValueError, match="before the engine's time"):
        save_states(engine, tmp_path, [2])


def test_the_command_line_saves_a_sequence(tmp_path):
    """Falsifies: ``python -m viva_pulse.states`` doesn't load the named state or doesn't save
    at the requested times; or a relative path is looked up under bin/states/."""
    # Run the viva_pulse under test, whatever the working directory.
    env = {**os.environ, "PYTHONPATH": str(Path(viva_pulse.__file__).parents[1])}
    out = tmp_path / "out"
    result = subprocess.run([sys.executable, "-m", "viva_pulse.states", "StandardMale@0s.json",
                             "--times", "1", "2", "--out", str(out)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in out.iterdir()) == ["StandardMale@1s.json", "StandardMale@2s.json"]

    result = subprocess.run([sys.executable, "-m", "viva_pulse.states", "out/StandardMale@2s.json",
                             "--times", "3", "--out", "later"], capture_output=True, text=True, cwd=tmp_path,
                            env=env)
    assert result.returncode == 0, result.stderr
    assert _time(tmp_path / "later" / "StandardMale@3s.json") == pytest.approx(3, abs=1e-9)


def test_a_time_between_steps_saves_at_the_next_step(tmp_path):
    """Falsifies: a time between Pulse's 0.02 s steps is saved before it, or named by the
    request rather than the time the state holds."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    (path,) = save_states(engine, tmp_path, [1.01], name="mid")
    assert path.name == "mid@1.02s.json"
    assert _time(path) == pytest.approx(1.02, abs=1e-9)


def test_two_times_in_one_step_raise(tmp_path):
    """Falsifies: two requested times that fall on the same step return the same file twice."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    with pytest.raises(ValueError, match="both fall on Pulse's step"):
        save_states(engine, tmp_path, [1.005, 1.01])


def test_an_existing_state_is_never_overwritten(tmp_path):
    """Falsifies: saving over an existing file silently replaces a state."""
    save_states(_load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", []), tmp_path, [1])
    with pytest.raises(FileExistsError, match="never overwrites"):
        save_states(_load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", []), tmp_path, [1])


def test_names_keep_microseconds_at_large_times():
    """Falsifies: names lose digits at large times (%g keeps 6 significant digits, so 10000.02 s
    would be named 10000 and collide with its neighbours)."""
    from viva_pulse.states import _seconds

    assert [_seconds(t) for t in (0.0, 2.5, 10000.02, 86400.000001, 1e6)] == \
        ["0", "2.5", "10000.02", "86400.000001", "1000000"]


def test_a_ventilation_mechanics_engine_raises_before_advancing(tmp_path):
    """Falsifies: an engine Pulse can't serialize is advanced first and fails only at the save."""
    engine = _initialize_engine("", "HumanAdultVentilationMechanics", "StandardMale.json", [])
    engine.advance_time_s(0.0)
    before = engine.pull_data()[0]
    with pytest.raises(ValueError, match="only whole-body engines"):
        save_states(engine, tmp_path, [1.0])
    assert engine.pull_data()[0] == before
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["", "a/b", "a@b"])
def test_bad_names_raise(tmp_path, name):
    """Falsifies: a name that would write into a subdirectory, or that the '@' convention can't
    split back, is accepted."""
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", [])
    with pytest.raises(ValueError, match="name must be"):
        save_states(engine, tmp_path, [1], name=name)


def _run(generator, seconds, save=None, **params):
    from process_bigraph import Composite, gather_emitter_results

    core = build_core()
    document = generator(core, **params)
    if save:
        document["pulse"]["config"].update(save)
    sim = Composite({"state": document}, core=core)
    sim.run(seconds)
    return gather_emitter_results(sim)[("emitter",)]


@pytest.mark.parametrize("generator, params", [
    ("pulse_hemorrhage", {"severity": 0.5}),
    ("pulse_cardiovascular", {"hemorrhage_severity": 0.5}),
], ids=["PulseProcess", "PulseCircuitProcess"])
def test_a_process_saves_at_update_boundaries_without_changing_the_run(tmp_path, generator, params,
                                                                       assert_rows_close):
    """Falsifies: a process saves off its update boundaries (stepping its engine mid-update
    would shift the run), saves a time twice or not at all, or saving changes what the
    composite emits (rows must match an unsaved run to 1e-9; stepping would shift them far
    more)."""
    import viva_pulse.composites as composites

    make = getattr(composites, generator)
    save = {"save_state_times_s": [0, 2.5, 5], "save_state_dir": str(tmp_path), "save_state_name": "run"}
    saved_rows = _run(make, 6, save, **params)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run@0s.json", "run@3s.json", "run@5s.json"]
    assert [_time(tmp_path / f"run@{t}s.json") for t in (0, 3, 5)] == pytest.approx([0, 3, 5], abs=1e-9)
    assert_rows_close(saved_rows, _run(make, 6, **params))



def test_a_composite_branches_from_its_saved_state(tmp_path):
    """Falsifies: a state a composite saved mid-run doesn't continue that run when a new
    composite starts from it (checkpoint-and-branch)."""
    from viva_pulse.composites import pulse_hemorrhage

    full = _run(pulse_hemorrhage, 6, {"save_state_times_s": [3], "save_state_dir": str(tmp_path)}, severity=0.5)
    branch = _run(pulse_hemorrhage, 3, state_file=str(tmp_path / "state@3s.json"), severity=0.5)
    for name in VITALS:
        assert branch[-1][name] == pytest.approx(full[-1][name], rel=1e-6), name


@pytest.mark.parametrize("config, message", [
    ({"save_state_times_s": [1.0]}, "save_state_dir must be set"),
    ({"save_state_times_s": [2.0, 1.0], "save_state_dir": "x"}, "strictly increasing"),
    ({"save_state_times_s": [1.0], "save_state_dir": "x", "save_state_name": "a@b"}, "name must be"),
])
def test_bad_process_save_config_raises(config, message):
    """Falsifies: a process accepts save settings that would fail or misname mid-run."""
    with pytest.raises(ValueError, match=message):
        PulseProcess(config, core=build_core())


def test_saving_on_ventilation_mechanics_raises():
    """Falsifies: a process whose engine Pulse can't serialize accepts save times."""
    from viva_pulse.processes import PulseCircuitProcess

    with pytest.raises(ValueError, match="whole_body only"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                             "save_state_times_s": [1.0], "save_state_dir": "x"}, core=build_core())


def test_existing_states_raise_when_the_process_is_built(tmp_path):
    """Falsifies: a name collision surfaces only when the run reaches that time, after the
    simulated time before it is spent."""
    (tmp_path / "run@600s.json").write_text("{}")
    with pytest.raises(FileExistsError, match="already holds states named 'run'"):
        PulseProcess({"save_state_times_s": [600.0], "save_state_dir": str(tmp_path),
                      "save_state_name": "run"}, core=build_core())


def _bleed_checkpoint(tmp_path, severity=0.8):
    from viva_pulse.composites import pulse_hemorrhage

    _run(pulse_hemorrhage, 10, {"save_state_times_s": [10], "save_state_dir": str(tmp_path)}, severity=severity)
    return tmp_path / "state@10s.json"


def test_a_branch_can_stop_a_checkpoint_bleed(tmp_path):
    """Falsifies: a branch from a mid-bleed checkpoint that sets the severity back to 0 sends
    nothing (the process assumed nothing was active at load), so Pulse keeps bleeding while the
    store says it stopped (review: identical blood loss for severity 0 and 0.8)."""
    from viva_pulse.composites import pulse_hemorrhage

    checkpoint = _bleed_checkpoint(tmp_path)
    stopped = _run(pulse_hemorrhage, 20, state_file=str(checkpoint), severity=0.0)
    bleeding = _run(pulse_hemorrhage, 20, state_file=str(checkpoint), severity=0.8)
    lost = lambda rows: rows[-1]["total_hemorrhaged_volume_mL"] - rows[0]["total_hemorrhaged_volume_mL"]
    assert lost(stopped) < 1.0
    assert lost(bleeding) > 20.0


def test_a_branch_with_the_checkpoint_setpoints_continues_it_exactly(tmp_path):
    """Falsifies: a branch with the checkpoint's own setpoints (which the process resends,
    their action being active in the loaded state) drifts from the uninterrupted run; it must
    match it as closely as a plain reload does (1.8e-8 measured)."""
    from viva_pulse.composites import pulse_hemorrhage

    full = _run(pulse_hemorrhage, 30, {"save_state_times_s": [10], "save_state_dir": str(tmp_path)}, severity=0.8)
    branch = _run(pulse_hemorrhage, 20, state_file=str(tmp_path / "state@10s.json"), severity=0.8)
    for name in VITALS:
        assert branch[-1][name] == pytest.approx(full[-1][name], rel=1e-7), name


def _ventilated_checkpoint(tmp_path):
    from viva_pulse.composites import pulse_mechanical_ventilation

    _run(pulse_mechanical_ventilation, 10, {"save_state_times_s": [10], "save_state_dir": str(tmp_path)},
         model_type="whole_body")
    return tmp_path / "state@10s.json"


def test_a_branch_can_disconnect_a_checkpoint_ventilator(tmp_path):
    """Falsifies: a branch setting connected back to its baseline 0 sends nothing, so the
    ventilator keeps running behind a store that says disconnected. Disconnected, its monitor
    reads 0."""
    from viva_pulse.composites import pulse_mechanical_ventilation

    checkpoint = _ventilated_checkpoint(tmp_path)
    rows = _run(pulse_mechanical_ventilation, 5, model_type="whole_body", state_file=str(checkpoint),
                connected=0.0)
    assert rows[-1]["circuits"]["mechanical_ventilator"]["tidal_volume_mL"] == 0.0
    still = _run(pulse_mechanical_ventilation, 5, model_type="whole_body", state_file=str(checkpoint))
    assert still[-1]["circuits"]["mechanical_ventilator"]["tidal_volume_mL"] > 100.0


def test_extubating_an_intubated_checkpoint_raises(tmp_path):
    """Falsifies: a branch asking to extubate an intubated checkpoint is silently dropped
    (Pulse's Python rejects an Off intubation) instead of raising."""
    from viva_pulse.composites import pulse_mechanical_ventilation

    checkpoint = _ventilated_checkpoint(tmp_path)
    with pytest.raises(Exception, match="extubation"):
        _run(pulse_mechanical_ventilation, 2, model_type="whole_body", state_file=str(checkpoint),
             intubated=0.0, connected=0.0)


def test_a_bleed_in_another_compartment_raises(tmp_path):
    """Falsifies: a checkpoint bleeding where the branch's process can't reach (another
    compartment) loads silently, bleeding on behind a store that says no bleed."""
    checkpoint = _bleed_checkpoint(tmp_path)
    process = PulseProcess({"state_file": str(checkpoint), "hemorrhage_compartment": "LeftLeg"},
                           core=build_core())
    with pytest.raises(ValueError, match=r"Hemorrhage \(RightLeg\)"):
        process.initial_state()


def test_a_ventilated_checkpoint_refuses_another_airway_device(tmp_path):
    """Falsifies: a process whose only airway device is oxygen loads a checkpoint whose airway
    the ventilator holds; connecting the oxygen would make every advance fail (review: the
    engine went irreversible within 3 updates)."""
    from viva_pulse.composites import pulse_supplemental_oxygen

    checkpoint = _ventilated_checkpoint(tmp_path)
    with pytest.raises(Exception, match="airway is held by equipment"):
        _run(pulse_supplemental_oxygen, 2, state_file=str(checkpoint))


def test_a_branch_can_return_a_checkpoint_multiplier_to_baseline(tmp_path):
    """Falsifies: a branch setting a checkpoint's resistance multiplier back to 1.0 sends
    nothing, so the 1.5 stays in effect (the branches would then match)."""
    from viva_pulse.composites import pulse_cardiovascular

    _run(pulse_cardiovascular, 5, {"save_state_times_s": [5], "save_state_dir": str(tmp_path)},
         systemic_resistance_multiplier=1.5)
    checkpoint = str(tmp_path / "state@5s.json")
    kept = _run(pulse_cardiovascular, 10, state_file=checkpoint, systemic_resistance_multiplier=1.5)
    reset = _run(pulse_cardiovascular, 10, state_file=checkpoint)
    map_ = lambda rows: rows[-1]["circuits"]["cardiovascular"]["hemodynamics"]["mean_arterial_pressure_mmHg"]
    assert abs(map_(kept) - map_(reset)) > 0.5


def test_a_circuit_branch_can_stop_a_checkpoint_bleed(tmp_path):
    """Falsifies: PulseCircuitProcess (not only PulseProcess) leaves a checkpoint's bleed
    running when the branch sets its severity to 0."""
    from viva_pulse.composites import pulse_cardiovascular

    _run(pulse_cardiovascular, 10, {"save_state_times_s": [10], "save_state_dir": str(tmp_path)},
         hemorrhage_severity=0.8)
    rows = _run(pulse_cardiovascular, 20, state_file=str(tmp_path / "state@10s.json"))
    volume = [r["circuits"]["cardiovascular"]["hemodynamics"]["blood_volume_mL"] for r in rows]
    bleeding = _run(pulse_cardiovascular, 20, state_file=str(tmp_path / "state@10s.json"),
                    hemorrhage_severity=0.8)
    lost = volume[0] - volume[-1]
    lost_bleeding = (bleeding[0]["circuits"]["cardiovascular"]["hemodynamics"]["blood_volume_mL"]
                     - bleeding[-1]["circuits"]["cardiovascular"]["hemodynamics"]["blood_volume_mL"])
    assert lost_bleeding > 20 and lost < lost_bleeding / 4


def test_a_branch_can_disconnect_checkpoint_oxygen(tmp_path):
    """Falsifies: a branch can't switch off a checkpoint's supplemental oxygen (inspired O2
    stays above room air)."""
    from viva_pulse.composites import pulse_supplemental_oxygen

    _run(pulse_supplemental_oxygen, 5, {"save_state_times_s": [5], "save_state_dir": str(tmp_path)},
         oxygen_connected=1.0)
    rows = _run(pulse_supplemental_oxygen, 10, state_file=str(tmp_path / "state@5s.json"),
                oxygen_connected=0.0)
    assert rows[-1]["circuits"]["supplemental_oxygen"]["oxygenation"]["fraction_inspired_oxygen"] == \
        pytest.approx(0.21, abs=0.01)
