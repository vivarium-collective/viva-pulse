"""Stabilized whole-body states for any patient file, stabilized once and cached.

Pulse ships stabilized states for its own patients only. Any other patient file
has to be stabilized by ``initialize_engine`` first, which takes about 13 s;
loading a saved state takes about 0.04 s. ``stabilized_state`` does the
stabilization once per patient and keeps the result as a state file in a cache
directory, so every later run of the same patient loads it directly.

The cache key covers everything the stabilized state depends on:

- the patient file's bytes;
- the Pulse install (``install_identity``): Pulse's own version and git hash,
  the SHA-256 of the loaded ``PyPulse`` binary (Pulse is linked into it
  statically, so any code change shows up there, committed or not), and the
  SHA-256 of the data files initialization reads (``DATA_DIRS``);
- the engine model type.
"""

from __future__ import annotations

import functools
import hashlib
import os
import tempfile
from pathlib import Path

import platformdirs

from .runtime import ensure_pulse_importable

#: Environment variable that overrides the cache directory.
CACHE_ENV_VAR = "VIVA_PULSE_CACHE_DIR"

#: The engine the cached states are made for (the only one Pulse can serialize).
MODEL_TYPE = "HumanAdultWholeBody"

#: Directories under the data root (``<install>/bin``) that Pulse reads when it
#: initializes an engine: stabilization criteria, the default environment and
#: nutrition, substances, and the ECG waveforms. A few hundred KB in all.
DATA_DIRS = ("config", "environments", "nutrition", "substances", "ecg")


def cache_dir() -> Path:
    """The directory holding cached states: ``$VIVA_PULSE_CACHE_DIR`` if set, else
    ``states/`` in the user cache directory (``platformdirs.user_cache_path("viva-pulse")``)."""
    override = os.environ.get(CACHE_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return platformdirs.user_cache_path("viva-pulse") / "states"


def resolve_patient_file(patient_file: str, install_dir: str = "") -> Path:
    """Return the patient file's absolute path.

    A bare name (no path separator) is a file in ``<install>/bin/patients/``;
    anything else is a filesystem path, relative to the working directory.
    A file that does not exist raises ``FileNotFoundError`` naming the path.
    """
    separators = {os.sep, os.altsep} - {None}
    if any(sep in patient_file for sep in separators):
        path = Path(patient_file).expanduser().resolve()
    else:
        path = ensure_pulse_importable(install_dir) / "patients" / patient_file
    if not path.is_file():
        raise FileNotFoundError(f"Pulse patient file not found: {path}")
    return path


def _update(digest, data: bytes) -> None:
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


@functools.cache
def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@functools.cache
def _data_digest(bin_dir: str) -> str:
    digest = hashlib.sha256()
    root = Path(bin_dir)
    files = sorted(p for name in DATA_DIRS for p in (root / name).rglob("*") if p.is_file())
    for path in files:
        _update(digest, path.relative_to(root).as_posix().encode())
        _update(digest, path.read_bytes())
    return digest.hexdigest()


def install_identity(install_dir: str = "") -> str:
    """Identify the Pulse install in use: ``<version>-<git hash>-<binary sha256>-<data sha256>``.

    The version and git hash are Pulse's own (``pulse.engine.PulseEngine.version``
    and ``git_hash``). The git hash names the engine commit but not uncommitted
    source changes or the toolchain, so the digest of the ``PyPulse`` binary that
    is actually loaded is included too. The data files Pulse reads at
    initialization (``DATA_DIRS``) are not compiled in, so their digest is
    included as well. Digests are computed once per process.
    """
    bin_dir = ensure_pulse_importable(install_dir)
    import PyPulse
    from pulse.engine.PulseEngine import git_hash, version

    return (f"{version()}-{git_hash()}-{_file_digest(PyPulse.__file__)}-"
            f"{_data_digest(str(bin_dir))}")


def stabilized_state(patient_file: str, install_dir: str = "") -> Path:
    """Return the path of a stabilized whole-body state for ``patient_file``.

    The state is looked up in ``cache_dir()`` by its cache key (see the module
    docstring). On a miss, the patient is stabilized with Pulse's
    ``initialize_engine``, saved to a temporary file in the cache directory,
    checked to load, and moved into place atomically, so a concurrent run never
    sees a partial file. Two runs that miss at the same time both stabilize and
    write equivalent files; the last one to finish wins.
    """
    bin_dir = ensure_pulse_importable(install_dir)
    patient_path = resolve_patient_file(patient_file, install_dir)
    content = patient_path.read_bytes()

    key = hashlib.sha256()
    for part in (content, install_identity(install_dir).encode(), MODEL_TYPE.encode()):
        _update(key, part)

    directory = cache_dir()
    state_path = directory / f"{patient_path.stem}-{key.hexdigest()}@0s.json"
    if state_path.is_file():
        return state_path
    directory.mkdir(parents=True, exist_ok=True)
    _stabilize(bin_dir, patient_path, content, state_path)
    return state_path


def _stabilize(bin_dir: Path, patient_path: Path, content: bytes, state_path: Path) -> None:
    from pulse.cdm.engine import SEDataRequestManager
    from pulse.cdm.patient import SEPatientConfiguration
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    def temporary(suffix: str) -> str:
        fd, path = tempfile.mkstemp(dir=state_path.parent, prefix=f".{patient_path.stem}.", suffix=suffix)
        os.close(fd)
        return path

    # Stabilize the exact bytes that were hashed, even if the file changes meanwhile.
    patient_copy = temporary(".patient.json")
    partial = temporary(".json")
    try:
        Path(patient_copy).write_bytes(content)
        configuration = SEPatientConfiguration()
        # Pulse takes the data root from the patient configuration (default "./").
        configuration.set_data_root_dir(f"{bin_dir}/")
        configuration.set_patient_file(patient_copy)
        engine = PulseEngine(getattr(eModelType, MODEL_TYPE), f"{bin_dir}/")
        engine.log_to_console(False)
        if not engine.initialize_engine(configuration, SEDataRequestManager([])):
            raise RuntimeError(f"Pulse failed to stabilize patient {patient_path}")
        if not engine.serialize_to_file(partial):
            raise RuntimeError(f"Pulse failed to save the stabilized state of {patient_path}")
        check = PulseEngine(getattr(eModelType, MODEL_TYPE), f"{bin_dir}/")
        check.log_to_console(False)
        if not check.serialize_from_file(partial, SEDataRequestManager([])):
            raise RuntimeError(f"Pulse failed to reload the stabilized state of {patient_path}")
        os.replace(partial, state_path)
    finally:
        for path in (patient_copy, partial):
            Path(path).unlink(missing_ok=True)
