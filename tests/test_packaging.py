"""Packaging: the declared dependencies must be installable on every Python
version that ``requires-python`` admits.

Regression: ``requires-python = ">=3.10"`` together with ``bigraph-viz>=2.0.3``
(which requires Python >= 3.11) could not be resolved, so the v0.2.0 image build
(``uv sync`` in the Dockerfile) failed. This runs ``uv lock``, the same
resolution that ``uv sync`` performs, on a copy of pyproject.toml, so no lock
file is written into the repo. It queries the live package index.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dependencies_resolve_for_every_supported_python(tmp_path):
    """Falsifies: some Python version inside requires-python cannot install the
    declared dependencies (uv lock resolves every version in the range)."""
    uv = shutil.which("uv")
    assert uv, "uv is required to develop viva-pulse (see README.md)"
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    result = subprocess.run([uv, "lock", "--project", str(tmp_path)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr


def test_wheel_declares_the_license_it_ships(tmp_path):
    """Falsifies: the package metadata names a different license than the LICENSE file it
    ships. Regression: pyproject declared MIT while the repo was published as Apache 2.0."""
    import zipfile

    uv = shutil.which("uv")
    assert uv, "uv is required to develop viva-pulse (see README.md)"
    result = subprocess.run([uv, "build", "--wheel", "-o", str(tmp_path), str(ROOT)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    (wheel,) = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        metadata = zf.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
        shipped = zf.read(next(n for n in names if n.endswith(".dist-info/licenses/LICENSE"))).decode()
    assert "License-Expression: Apache-2.0" in metadata.splitlines()
    assert "Apache License" in shipped and "Version 2.0, January 2004" in shipped
    assert shipped == (ROOT / "LICENSE").read_text()


LIBRARY_RUN = """
import importlib.util, json
from pathlib import Path
from process_bigraph import Composite, gather_emitter_results
import viva_pulse
import viva_pulse.visualizations
from viva_pulse.core import build_core
from viva_pulse.composites.hemorrhage import pulse_hemorrhage
core = build_core()
sim = Composite({"state": pulse_hemorrhage(core)}, core=core)
sim.run(2)
rows = gather_emitter_results(sim)[("emitter",)]
print(json.dumps({"module": viva_pulse.__file__, "rows": len(rows),
                  "bled_mL": rows[-1]["total_hemorrhaged_volume_mL"],
                  "workbench": importlib.util.find_spec("vivarium_workbench") is not None}))
"""


def test_library_runs_without_extras(tmp_path):
    """Falsifies: installing viva-pulse without extras leaves the library unable to drive Pulse,
    or still drags in the workbench. Regression: the workbench and the study/figure deps were
    core dependencies, so a project depending on viva-pulse inherited its workbench git pin and
    could not lock against another workbench rev (viva-matrix)."""
    import json
    import os
    import sys

    from viva_pulse.runtime import resolve_install_dir

    install = resolve_install_dir()
    uv = shutil.which("uv")
    assert uv, "uv is required to develop viva-pulse (see README.md)"
    venv = tmp_path / "venv"
    python = venv / "bin" / "python"
    for cmd in ([uv, "venv", "--python", sys.executable, str(venv)],
                [uv, "pip", "install", "--python", str(python), str(ROOT)]):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stderr
    result = subprocess.run([str(python), "-I", "-c", LIBRARY_RUN], capture_output=True,
                            text=True, timeout=300, cwd=tmp_path,
                            env={**os.environ, "PULSE_INSTALL_DIR": str(install)})
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.splitlines()[-1])
    assert Path(out["module"]).is_relative_to(venv)
    assert out["workbench"] is False
    assert out["rows"] == 3 and out["bled_mL"] > 0


def test_protobuf_bound_matches_the_pulse_build():
    """Falsifies: pyproject's protobuf range admits a runtime older than the one Pulse's
    generated ``_pb2`` code was built for (which it refuses at import), admits the untested next
    major, or excludes the built version. Regression: the dependency was a bare ``protobuf``."""
    import re
    import tomllib

    from packaging.requirements import Requirement
    from packaging.version import Version

    from viva_pulse.runtime import resolve_install_dir

    generated = {m.group(1) for path in (resolve_install_dir() / "python" / "pulse").rglob("*_pb2.py")
                 if (m := re.search(r"^# Protobuf Python Version: (\S+)$", path.read_text(), re.M))}
    assert len(generated) == 1, f"generated code names several protobuf versions: {generated}"
    built = Version(generated.pop())
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    (bound,) = [Requirement(d).specifier for d in deps if Requirement(d).name == "protobuf"]
    assert built in bound
    floors = [Version(s.version) for s in bound if s.operator in (">=", ">", "==", "~=")]
    assert floors and max(floors) >= built
    assert Version(f"{built.major + 1}.0.0") not in bound
