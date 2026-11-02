"""Workbench studies: every baseline and variant runs, and every readout exists.

The workbench resolves each study entry itself (``dry_run`` returns the exact
spec id and generator overrides a real run would use, with no side effects).
The document is then built with the strict generator builder, which rejects
undeclared parameters, and run on the real engine. The workbench's static
``check-observables`` cannot see stores that processes create through their
output wires (``vitals/`` here), so the readout paths are checked against the
realized composite instead.
"""

import importlib
import pkgutil
import sqlite3
from pathlib import Path

import pytest
import yaml
from process_bigraph import Composite, allocate_core
from process_bigraph.composite_generator import _REGISTRY, build_generator
from process_bigraph.visualization import Visualization
from vivarium_workbench.lib.investigations import build_viz_composite, gather_emitter_outputs
from vivarium_workbench.lib.study_runs import run_study_baseline, run_study_variant
from vivarium_workbench.testing import Run

import viva_pulse.visualizations
from viva_pulse.core import build_core
from viva_pulse.runtime import resolve_install_dir


def _visualization_classes():
    """Every ``Visualization`` subclass in ``viva_pulse.visualizations``'s submodules: the
    rule the workbench's env worker registers them by, so a new figure is never missed."""
    classes = {}
    for module in pkgutil.iter_modules(viva_pulse.visualizations.__path__):
        namespace = vars(importlib.import_module(f"viva_pulse.visualizations.{module.name}"))
        classes.update({value.__name__: value for value in namespace.values()
                        if isinstance(value, type) and issubclass(value, Visualization)
                        and value is not Visualization})
    return classes


VISUALIZATIONS = _visualization_classes()

ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "workspace" / "studies"


def _entries():
    for study_yaml in sorted(STUDIES.glob("*/study.yaml")):
        spec = yaml.safe_load(study_yaml.read_text())
        study = spec["name"]
        for entry in spec.get("baseline", []):
            yield pytest.param(study, "baseline", entry["name"], id=f"{study}/{entry['name']}")
        for entry in spec.get("variants", []):
            yield pytest.param(study, "variant", entry["name"], id=f"{study}/{entry['name']}")


def _resolve(study, kind, name):
    if kind == "baseline":
        body, status = run_study_baseline(ROOT, {"study": study, "composite": name, "dry_run": True})
    else:
        body, status = run_study_variant(ROOT, {"study": study, "variant": name, "dry_run": True})
    assert status == 200, body
    return body["request"]["spec_id"], body["request"]["overrides"]


def _leaf(state, dotted):
    node = state
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"{dotted!r} missing at {part!r}"
        node = node[part]
    return node


def test_the_three_hemorrhage_studies_exist():
    names = sorted(p.parent.name for p in STUDIES.glob("*/study.yaml"))
    assert names == ["fluid-resuscitation", "hemorrhage-severity-sweep", "patient-cohort"]


def test_cohort_covers_every_shipped_patient():
    spec = yaml.safe_load((STUDIES / "patient-cohort" / "study.yaml").read_text())
    entries = spec["baseline"] + spec["variants"]
    state_files = sorted({**e.get("params", {}), **e.get("parameter_overrides", {})}["state_file"]
                         for e in entries)
    shipped = sorted(p.name for p in (resolve_install_dir() / "bin" / "states").glob("*@0s.json"))
    assert state_files == shipped
    assert len(shipped) == 21


@pytest.mark.parametrize("study, kind, name", list(_entries()))
def test_study_entry_runs_and_emits_its_readouts(study, kind, name):
    spec_id, overrides = _resolve(study, kind, name)
    core = build_core()
    document = build_generator(_REGISTRY[spec_id], overrides=overrides, core=core)
    sim = Composite({"state": document}, core=core)
    sim.run(1.0)
    readouts = yaml.safe_load((STUDIES / study / "study.yaml").read_text())["readouts"]
    assert readouts
    for readout in readouts:
        value = _leaf(sim.state, readout["store_path"])
        assert isinstance(value, (int, float)), (readout["store_path"], value)
    assert sim.state["vitals"]["irreversible_state"] is False


def _db(study):
    db = STUDIES / study / "runs.db"
    assert db.is_file() and db.stat().st_size > 0, f"no run record at {db}"
    return db


def _specs():
    return {p.parent.name: yaml.safe_load(p.read_text()) for p in sorted(STUDIES.glob("*/study.yaml"))}


def _declared(key):
    for study, spec in _specs().items():
        for viz in spec.get(key, []):
            yield pytest.param(study, viz, id=f"{study}/{viz['name']}")


@pytest.mark.parametrize("study, viz", list(_declared("visualizations")))
def test_visualization_renders_from_the_recorded_runs(study, viz):
    """The workbench's own render path (gather runs.db -> build_viz_composite -> one step)."""
    cls = VISUALIZATIONS[viz["address"].removeprefix("local:")]
    core = allocate_core()
    core.register_link(cls.__name__, cls)
    gathered = gather_emitter_outputs(_db(study))
    document = build_viz_composite(viz, gathered, {cls.__name__: cls})
    for port, runs in document["inputs_store"].items():
        if port in viz["config"]["inputs_map"]:
            assert runs and all(isinstance(v, (int, float)) for run in runs for v in run), port
    sim = Composite({"state": document}, core=core)
    sim.run(1)
    html = sim.state["output_store"]
    assert "Plotly.newPlot" in html, html[:300]


@pytest.mark.parametrize("study, viz", list(_declared("comparative_visualizations")))
def test_comparative_visualization_resolves_every_run(study, viz):
    """Each run is found by its sim_name (the label) and records the observable."""
    db = _db(study)
    for entry in viz["runs"]:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT run_id FROM runs_meta WHERE sim_name = ? "
                               "ORDER BY started_at DESC LIMIT 1", (entry["sim_name"],)).fetchone()
        assert row, f"no run named {entry['sim_name']!r}"
        assert len(Run(db, row[0]).observable(viz["observable_path"])) > 0
