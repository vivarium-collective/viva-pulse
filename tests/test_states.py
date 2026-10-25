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
