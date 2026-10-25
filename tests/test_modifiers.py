"""Circuit modifiers: Pulse's configuration Modifiers, applied when a patient is stabilized.

Nothing is mocked. Every cold stabilization runs Pulse's ``initialize_engine``
(about 13 s), so the module shares one cache directory. The expected values
come from the shipped StandardMale state (Pulse's own modifiers and the
unmodified circulation) and from a probe of the same change through Pulse's
API (``docs/plan/plan-circuit-level-access.md``): ``Aorta1ToBone1`` x5 re-tunes
to x4.35 and raises cardiac output by about 10% while MAP holds.
"""

import json
from types import SimpleNamespace

import pytest

from viva_pulse.composites.circuits import pulse_cardiovascular
from viva_pulse.core import build_core
from viva_pulse.patients import CACHE_ENV_VAR
from viva_pulse.processes import PulseCircuitProcess, PulseProcess
from viva_pulse.runtime import ensure_pulse_importable

PATH = "Aorta1ToBone1"
HEMODYNAMICS = ("cardiovascular", "hemodynamics")


def _cardiovascular(**config):
    return PulseCircuitProcess({"modules": ["cardiovascular"], **config}, core=build_core())


def _hemodynamics(state):
    for key in HEMODYNAMICS:
        state = state[key]
    return state


def _resistance_baseline(state, name):
    path = next(p for p in state["CircuitManager"]["FluidPath"] if p["CircuitPath"]["Name"] == name)
    return path["ResistanceBaseline"]["ScalarPressureTimePerVolume"]["Value"]


@pytest.fixture(scope="module")
def shipped():
    return json.loads((ensure_pulse_importable() / "states" / "StandardMale@0s.json").read_text())


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    directory = tmp_path_factory.mktemp("states")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(CACHE_ENV_VAR, str(directory))
        yield directory


@pytest.fixture(scope="module")
def modified(cache):
    """The first load with ``PATH`` x5: stabilizes the unmodified patient, then the modified one."""
    assert not any(cache.iterdir())
    state = _cardiovascular(circuit_modifiers={PATH: 5.0}).initial_state()
    files = {f.name: f.stat() for f in cache.iterdir()}
    return SimpleNamespace(state=state, files=files)


def _saved(cache, modified, shipped):
    """The cached states whose modifiers differ from Pulse's own."""
    states = [json.loads((cache / name).read_text()) for name in modified.files]
    return [s for s in states if s["Configuration"]["Modifiers"] != shipped["Configuration"]["Modifiers"]]


def test_the_patient_is_stabilized_with_the_modifier(cache, modified, shipped):
    """Falsifies: the modifier is ignored (the shipped state loads), Pulse's own modifiers are
    dropped (sent alone, CO falls about 28%), the multiplier replaces Pulse's value instead of
    scaling it (5.0, not 5.1), or the cache key ignores the modifiers (one file, not two)."""
    assert len(modified.files) == 2  # the unmodified patient, then the modified one
    (saved,) = _saved(cache, modified, shipped)
    defaults = shipped["Configuration"]["Modifiers"]
    recorded = saved["Configuration"]["Modifiers"]
    assert recorded[PATH]["Value"] == pytest.approx(defaults[PATH]["Value"] * 5.0, rel=1e-12)
    assert {k: v for k, v in recorded.items() if k != PATH} == {k: v for k, v in defaults.items() if k != PATH}
    # Stabilization re-tunes the path (x4.35 in the probe), not back to the shipped value.
    ratio = _resistance_baseline(saved, PATH) / _resistance_baseline(shipped, PATH)
    assert 3.5 < ratio < 5.0, ratio

    reference = _hemodynamics(_cardiovascular().initial_state())
    loaded = _hemodynamics(modified.state)
    assert loaded["cardiac_output_L_per_min"] > 1.05 * reference["cardiac_output_L_per_min"]
    assert loaded["mean_arterial_pressure_mmHg"] == pytest.approx(
        reference["mean_arterial_pressure_mmHg"], abs=1.0)


def test_a_second_load_uses_the_cache(cache, modified):
    """Falsifies: the modified patient is stabilized again on every load."""
    state = _cardiovascular(circuit_modifiers={PATH: 5.0}).initial_state()
    assert {f.name: f.stat() for f in cache.iterdir()} == modified.files
    assert _hemodynamics(state) == _hemodynamics(modified.state)


def test_whole_body_vitals_run_the_modified_patient(cache, modified):
    """Falsifies: PulseProcess drops circuit_modifiers and runs the shipped patient."""
    process = PulseProcess({"circuit_modifiers": {PATH: 5.0}}, core=build_core())
    vitals = process.initial_state()
    assert vitals["cardiac_output_L_per_min"] == pytest.approx(
        _hemodynamics(modified.state)["cardiac_output_L_per_min"], rel=1e-9)
    assert {f.name: f.stat() for f in cache.iterdir()} == modified.files


def test_a_composite_runs_the_modified_patient(cache, modified, run_composite):
    """Falsifies: circuit_modifiers stops at the generator."""
    _, rows = run_composite(pulse_cardiovascular, 2, circuit_modifiers={PATH: 5.0})
    first = rows[0]["circuits"]["cardiovascular"]["hemodynamics"]
    assert first["cardiac_output_L_per_min"] == pytest.approx(
        _hemodynamics(modified.state)["cardiac_output_L_per_min"], rel=1e-9)


def test_an_unknown_name_fails_the_load_naming_it(cache, modified):
    """Falsifies: Pulse's rejection of a name is swallowed, or the error hides which modifiers."""
    with pytest.raises(RuntimeError, match="NoSuchPath"):
        _cardiovascular(circuit_modifiers={"NoSuchPath": 2.0}).initial_state()


def test_no_modifiers_load_the_shipped_state(tmp_path, monkeypatch):
    """Falsifies: an empty map stabilizes StandardMale instead of loading its shipped state."""
    monkeypatch.setenv(CACHE_ENV_VAR, str(tmp_path))
    _cardiovascular(circuit_modifiers={}).initial_state()
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("make", [
    lambda **config: _cardiovascular(**config),
    lambda **config: PulseProcess(config, core=build_core()),
], ids=["PulseCircuitProcess", "PulseProcess"])
def test_modifiers_with_a_state_file_raise(make):
    """Falsifies: modifiers are silently ignored when the run starts from a stabilized state,
    which Pulse never re-initializes."""
    with pytest.raises(ValueError, match="circuit_modifiers .* need patient_file"):
        make(state_file="StandardFemale@0s.json", circuit_modifiers={PATH: 2.0})


def test_modifiers_on_ventilation_mechanics_raise():
    """Falsifies: modifiers are silently ignored on the engine that does not apply them."""
    with pytest.raises(ValueError, match="whole_body only"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                             "circuit_modifiers": {"RightAlveoliToRightPleuralConnection": 2.0}},
                            core=build_core())



@pytest.mark.parametrize("multiplier", [0.0, -1.0, float("nan"), float("inf"), "5", True])
def test_bad_multipliers_raise_before_loading(multiplier):
    """Falsifies: a multiplier Pulse accepts but that makes no physical patient (0 and -1
    stabilize and would be cached as a patient), or one that fails only after a stabilization,
    gets past construction."""
    with pytest.raises(ValueError, match="finite numbers > 0"):
        _cardiovascular(circuit_modifiers={PATH: multiplier})


def test_a_hit_does_not_need_the_unmodified_state(cache, modified, shipped):
    """Falsifies: a cached modified patient still reads (or, once evicted, re-stabilizes) the
    unmodified patient to compute its key. Runs last: it removes the unmodified state."""
    (unmodified,) = [cache / name for name in modified.files
                     if json.loads((cache / name).read_text())["Configuration"]["Modifiers"]
                     == shipped["Configuration"]["Modifiers"]]
    unmodified.unlink()
    remaining = {f.name: f.stat() for f in cache.iterdir()}
    state = _cardiovascular(circuit_modifiers={PATH: 5.0}).initial_state()
    assert {f.name: f.stat() for f in cache.iterdir()} == remaining
    assert _hemodynamics(state) == _hemodynamics(modified.state)
