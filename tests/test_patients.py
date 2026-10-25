"""Any patient file on the whole-body engine: stabilized once, then loaded from the cache.

Nothing is mocked. Every cold stabilization runs Pulse's ``initialize_engine``
(about 13 s), so the module shares one cache directory and one first load;
the cache is observed for real, through the file it writes and load times.
"""

import inspect
import json
import re
import time
from types import SimpleNamespace

import pytest

from viva_pulse.composites.circuits import (
    pulse_cardiovascular, pulse_mechanical_ventilation, pulse_respiratory,
    pulse_supplemental_oxygen, pulse_thermal, pulse_whole_body_circuits)
from viva_pulse.composites.hemorrhage import pulse_hemorrhage, pulse_resuscitation
from viva_pulse.core import build_core
from viva_pulse.patients import CACHE_ENV_VAR, DATA_DIRS, _data_digest, resolve_patient_file
from viva_pulse.processes import VITALS, PulseCircuitProcess, PulseProcess
from viva_pulse.runtime import ensure_pulse_importable

HR = ("cardiovascular", "hemodynamics", "heart_rate_bpm")


def _patient_spec(**changes):
    """StandardMale, younger and heavier, with a heart-rate baseline Pulse ships no state for."""
    spec = json.loads((ensure_pulse_importable() / "patients" / "StandardMale.json").read_text())
    spec["Name"] = "VivaTestPatient"
    spec["Age"]["ScalarTime"]["Value"] = 30.0
    spec["Weight"]["ScalarMass"]["Value"] = 190.0
    spec["HeartRateBaseline"]["ScalarFrequency"]["Value"] = changes.get("heart_rate", 64.0)
    return spec


def _heart_rate(state):
    for key in HR:
        state = state[key]
    return state


def _cardiovascular(**config):
    return PulseCircuitProcess({"modules": ["cardiovascular"], **config}, core=build_core())


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    directory = tmp_path_factory.mktemp("states")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(CACHE_ENV_VAR, str(directory))
        yield directory


@pytest.fixture(scope="module")
def patient(tmp_path_factory):
    path = tmp_path_factory.mktemp("patients") / "VivaTestPatient.json"
    path.write_text(json.dumps(_patient_spec()))
    return path


@pytest.fixture(scope="module")
def first_load(cache, patient):
    """The first load of ``patient``, which must stabilize it. Requested by every test
    that writes to ``cache``, so it always runs first and finds the cache empty."""
    assert not any(cache.iterdir())
    start = time.perf_counter()
    state = _cardiovascular(patient_file=str(patient)).initial_state()
    seconds = time.perf_counter() - start
    files = sorted(cache.iterdir())
    return SimpleNamespace(state=state, seconds=seconds, files=files, stat=files[0].stat())


def _unchanged(first_load):
    """The first load's state file is still the same file (a re-stabilization would
    ``os.replace`` it: new inode and mtime)."""
    stat = first_load.files[0].stat()
    return (stat.st_ino, stat.st_mtime_ns) == (first_load.stat.st_ino, first_load.stat.st_mtime_ns)


def test_unshipped_patient_loads_as_that_patient(first_load):
    """Falsifies: a whole-body patient_file is ignored (StandardMale's state loads,
    HR about 72), or its stabilized state is not what the engine loads. The patient's
    heart-rate baseline is 64 bpm."""
    assert _heart_rate(first_load.state) == pytest.approx(64.0, abs=1.5)
    assert first_load.state["irreversible_state"] is False
    # One complete state file, named after the patient; no temporary file left behind.
    assert len(first_load.files) == 1
    assert first_load.files[0].name.startswith("VivaTestPatient-")
    assert first_load.files[0].name.endswith("@0s.json")


def test_second_load_uses_the_cache(cache, patient, first_load):
    """Falsifies: the cache lookup misses for an unchanged patient and stabilizes again.
    A new stabilization would replace the file (new inode and mtime) and take about as
    long as the first load (about 13 s); a hit loads in well under a second."""
    start = time.perf_counter()
    state = _cardiovascular(patient_file=str(patient)).initial_state()
    seconds = time.perf_counter() - start
    assert _unchanged(first_load)
    assert seconds < 2.0 and seconds < first_load.seconds / 5, (seconds, first_load.seconds)
    assert _heart_rate(state) == _heart_rate(first_load.state)


def test_cached_state_matches_a_cold_stabilization(cache, patient, first_load):
    """Falsifies: the cached state differs from the patient as Pulse stabilizes it (for
    example saved from another patient, or before stabilization finished). A PulseProcess
    loaded from the cache and an engine initialized directly through Pulse's API from the
    same patient file must agree after 30 s. They are not bit-identical (the state
    round-trips through JSON; a direct probe of Pulse measured 3.7e-10 relative after
    60 s); 1e-6 allows for that and is orders of magnitude below any patient difference
    (64 vs 72 bpm is 1e-1)."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.cdm.patient import SEPatientConfiguration
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = [SEDataRequest.create_physiology_request(
                    prop, unit=getattr(getattr(scalars, cls), unit) if cls else None)
                for prop, cls, unit in VITALS.values()]
    configuration = SEPatientConfiguration()
    configuration.set_data_root_dir(f"{bin_dir}/")
    configuration.set_patient_file(str(patient))
    cold = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    cold.log_to_console(False)
    assert cold.initialize_engine(configuration, SEDataRequestManager(requests))
    assert cold.advance_time_s(30.0)
    expected = dict(zip(VITALS, cold.pull_data()[1:]))

    process = PulseProcess({"patient_file": str(patient)}, core=build_core())
    stores = {k: v for k, v in process.initial_state().items() if k in VITALS}
    for name, delta in process.update({"hemorrhage_severity": 0.0, "iv_rate_mL_per_min": 0.0},
                                      30.0).items():
        stores[name] += delta
    assert _unchanged(first_load)  # the process loaded the cached file, not a new one
    for name in VITALS:
        assert stores[name] == pytest.approx(expected[name], rel=1e-6, abs=1e-9), name


def test_changed_patient_contents_stabilize_anew(cache, tmp_path, first_load):
    """Falsifies: the cache key ignores the patient file's contents, so an edited patient
    under the same name reuses the old state. Same file name, different heart-rate
    baseline: a second state file must appear and load as the edited patient."""
    edited = tmp_path / "VivaTestPatient.json"
    edited.write_text(json.dumps(_patient_spec(heart_rate=80.0)))
    before = set(cache.iterdir())
    state = _cardiovascular(patient_file=str(edited)).initial_state()
    added = set(cache.iterdir()) - before
    assert len(added) == 1 and added.pop().name.startswith("VivaTestPatient-")
    assert _unchanged(first_load)
    assert _heart_rate(state) == pytest.approx(80.0, abs=1.5)


def test_data_files_are_part_of_the_install_identity(tmp_path):
    """Falsifies: an edit to a data file Pulse reads at initialization (not compiled into
    PyPulse) leaves the cache key unchanged, so a stale state is reused; or DATA_DIRS
    names a directory the install doesn't have."""
    bin_dir = ensure_pulse_importable()
    assert all((bin_dir / name).is_dir() for name in DATA_DIRS)
    for name in DATA_DIRS:
        (tmp_path / name).mkdir()
    (tmp_path / "config" / "DynamicStabilization.json").write_text("{}")
    (tmp_path / "states").mkdir()
    before = _data_digest(str(tmp_path))
    _data_digest.cache_clear()
    (tmp_path / "states" / "Other@0s.json").write_text("{}")  # outside DATA_DIRS
    assert _data_digest(str(tmp_path)) == before
    _data_digest.cache_clear()
    (tmp_path / "config" / "DynamicStabilization.json").write_text('{"changed": 1}')
    assert _data_digest(str(tmp_path)) != before
    _data_digest.cache_clear()


@pytest.mark.parametrize("make", [
    lambda **config: _cardiovascular(**config),
    lambda **config: PulseProcess(config, core=build_core()),
], ids=["PulseCircuitProcess", "PulseProcess"])
def test_state_and_patient_file_together_raise(make):
    """Falsifies: with both start files set, one is silently ignored and the run uses a
    patient other than the one asked for."""
    with pytest.raises(ValueError, match="state_file .* and patient_file .* are both set"):
        make(state_file="StandardFemale@0s.json", patient_file="StandardFemale.json")


def test_missing_patient_file_raises(cache, tmp_path):
    """Falsifies: a patient path that does not exist reaches Pulse, or falls back to a
    shipped patient, instead of failing with its path."""
    missing = (tmp_path / "NoSuchPatient.json").resolve()
    process = _cardiovascular(patient_file=str(missing))
    with pytest.raises(FileNotFoundError, match=re.escape(str(missing))):
        process.initial_state()
    with pytest.raises(FileNotFoundError, match="patients/NoSuchPatient.json"):
        _cardiovascular(patient_file="NoSuchPatient.json").initial_state()


def test_patient_names_resolve_in_the_install_and_paths_in_the_working_directory(tmp_path,
                                                                                  monkeypatch):
    """Falsifies: a bare name is read from the working directory, or a relative path from
    the install's patients/ directory."""
    bin_dir = ensure_pulse_importable()
    assert resolve_patient_file("StandardFemale.json") == bin_dir / "patients" / "StandardFemale.json"
    (tmp_path / "here").mkdir()
    (tmp_path / "here" / "StandardFemale.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    assert resolve_patient_file("here/StandardFemale.json") == (tmp_path / "here" / "StandardFemale.json").resolve()


GENERATORS = [pulse_hemorrhage, pulse_resuscitation, pulse_cardiovascular, pulse_respiratory,
              pulse_mechanical_ventilation, pulse_thermal, pulse_supplemental_oxygen,
              pulse_whole_body_circuits]


@pytest.mark.parametrize("generator", GENERATORS, ids=lambda g: g.__name__)
def test_every_generator_with_state_file_passes_patient_file(generator):
    """Falsifies: a generator that takes state_file drops patient_file, so its runs
    silently use the default patient."""
    assert {"state_file", "patient_file"} <= set(inspect.signature(generator).parameters)
    doc = generator(build_core(), patient_file="Gus.json")
    assert doc["pulse"]["config"]["patient_file"] == "Gus.json"


@pytest.mark.parametrize("generator", GENERATORS, ids=lambda g: g.__name__)
def test_every_generator_passes_circuit_modifiers(generator):
    """Falsifies: a generator drops circuit_modifiers, so its runs use the unmodified patient."""
    assert "circuit_modifiers" in inspect.signature(generator).parameters
    doc = generator(build_core(), circuit_modifiers={"Aorta1ToBone1": 2.0})
    assert doc["pulse"]["config"]["circuit_modifiers"] == {"Aorta1ToBone1": 2.0}


def test_composite_runs_the_patient_from_the_cache(cache, patient, first_load, run_composite):
    """Falsifies: patient_file stops at the generator, or the composite does not load the
    cached state (a new stabilization would replace the cache file)."""
    _, rows = run_composite(pulse_hemorrhage, 2, patient_file=str(patient), severity=0.0)
    assert rows[0]["heart_rate_bpm"] == pytest.approx(_heart_rate(first_load.state), rel=1e-9)
    assert _unchanged(first_load)


def test_point_reads_run_on_the_patient(cache, patient, first_load):
    """Falsifies: with point modules, the process edits and loads state_file's state
    (StandardMale, HR about 72) instead of the patient's cached state, or reads its points
    from a different state than the engine runs."""
    process = PulseCircuitProcess({"modules": ["cardiovascular", "cardiovascular_points"],
                                   "patient_file": str(patient),
                                   "cardiovascular_point_nodes": ["Aorta1"],
                                   "cardiovascular_point_paths": ["Aorta1ToBone1"]}, core=build_core())
    state = process.initial_state()
    assert _heart_rate(state) == pytest.approx(64.0, abs=1.5)
    assert _unchanged(first_load)
    saved = json.loads(first_load.files[0].read_text())
    node = next(n for n in saved["CircuitManager"]["FluidNode"] if n["CircuitNode"]["Name"] == "Aorta1")
    expected = node["Pressure"]["ScalarPressure"]["Value"]
    assert state["cardiovascular_points"]["nodes"]["Aorta1"]["pressure_mmHg"] == pytest.approx(expected, rel=1e-9)
