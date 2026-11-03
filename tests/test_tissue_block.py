"""The stratified liver tissue block under Pulse (plan Design 1).

Real Pulse and real COPASI, no mocks. Oracles come from outside the block: the
upstream ``CopasiUTCProcess`` stepped by hand, Koschorreck 2008's own geometry,
or Pulse's hepatic reads emitted alongside.
"""

import json
import math

import pytest

# Import COPASI through the cell module, which keeps the process locale (see test below).
pytest.importorskip("viva_pulse.multiscale.cells")

from basico import run_steadystate, set_species  # noqa: E402
from process_bigraph import Composite, allocate_core, gather_emitter_results  # noqa: E402
from viva_copasi.processes import CopasiUTCProcess  # noqa: E402

from viva_pulse.composites import liver_tissue_replay, pulse_hepatic, pulse_liver_tissue  # noqa: E402
from viva_pulse.core import build_core  # noqa: E402
from viva_pulse.multiscale import KOSCHORRECK_2008, register_multiscale, save_hepatic_trajectory  # noqa: E402
from viva_pulse.multiscale.tissue import HEPATIC_PATHS  # noqa: E402

BOUND = ("IR", "I2R", "IRp", "I2Rp", "IRen", "I2Ren", "IRPen", "I2RPen")  # insulin-bound receptor states
RECEPTOR = BOUND + ("R", "Rp", "Ren", "RPen")


def _run(generator, duration, **params):
    core = register_multiscale(build_core())
    sim = Composite({"state": generator(core, **params)}, core=core)
    sim.run(duration)
    return gather_emitter_results(sim)[("emitter",)]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """60 s of Pulse's hepatic reads (StandardMale), saved as a replay trajectory."""
    core = build_core()
    sim = Composite({"state": pulse_hepatic(core)}, core=core)
    sim.run(60)
    rows = gather_emitter_results(sim)[("emitter",)]
    return save_hepatic_trajectory(rows, tmp_path_factory.mktemp("replay") / "hepatic.json")


def _synthetic(recorded, tmp_path, *, seconds, step_at, factor):
    """Pulse's t=0 hepatic values held constant, with liver insulin x ``factor``
    from ``step_at`` on."""
    base = json.loads(recorded.read_text())
    values = {}
    for key, series in base["values"].items():
        scale = [factor if (key.endswith("insulin_pmol_per_L") and t >= step_at) else 1.0
                 for t in range(seconds + 1)]
        values[key] = [series[0] * s for s in scale]
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps({"time": [float(t) for t in range(seconds + 1)], "values": values}))
    return path


def _standalone(drives):
    """Upstream CopasiUTCProcess, equilibrated at drives[0] with basico, then advanced
    1 s per drive value by hand. Returns the species after each second."""
    process = CopasiUTCProcess({"model_source": str(KOSCHORRECK_2008), "intervals": 1, "report_fluxes": False},
                               core=allocate_core())
    set_species(name=process.sbml_to_name["ins"], exact=True, initial_concentration=drives[0], model=process.dm)
    assert run_steadystate(model=process.dm, update_model=True) in (1, 2)
    state = process.initial_state()["species_concentrations"]
    out = []
    for drive in drives:
        delta = process.update({"species_counts": {"ins": drive}, "species_concentrations": state}, 1.0)
        state = {k: state[k] + delta["species_concentrations"][k] for k in state}
        out.append(dict(state))
    return out


def _bound(cells):
    return sum(cells[s] for s in BOUND)


# -- live Pulse ---------------------------------------------------------------------


def test_extraction_keeps_pulse_mean_and_removes_the_configured_fraction():
    """Falsifies: the strata don't average to Pulse's liver value (the block would
    invent or lose insulin), or the inlet-to-outlet drop isn't the configured
    extraction. References: Pulse's own liver insulin, emitted alongside, and E."""
    extraction = 0.4
    rows = _run(pulse_liver_tissue, 20, strata=4, extraction=extraction)
    for row in rows:
        liver_nM = row["circuits"]["hepatic"]["liver"]["insulin_pmol_per_L"] / 1000.0
        drive = [row["tissue"]["drive"][f"s{i}"]["ins"] for i in range(4)]
        assert sum(drive) / 4 == pytest.approx(liver_nM, rel=1e-12)
        # Linear in position (midpoints x = 1/8 ... 7/8): extrapolate to the inlet (x = 0) and outlet (x = 1).
        step = drive[1] - drive[0]
        inlet, outlet = drive[0] - step / 2, drive[3] + step / 2
        assert outlet / inlet == pytest.approx(1.0 - extraction, rel=1e-12)


def test_no_extraction_gives_every_stratum_pulse_value():
    """Falsifies: the default (E = 0, Pulse's own liver clears no insulin) varies across strata."""
    rows = _run(pulse_liver_tissue, 5, strata=3)
    for row in rows:
        liver_nM = row["circuits"]["hepatic"]["liver"]["insulin_pmol_per_L"] / 1000.0
        assert [row["tissue"]["drive"][f"s{i}"]["ins"] for i in range(3)] == pytest.approx([liver_nM] * 3, rel=1e-15)


def test_the_block_leaves_pulse_unchanged():
    """Falsifies: attaching the block perturbs Pulse (it must be a passive readout).
    Every hepatic reading equals a Pulse run without the block."""
    with_block = _run(pulse_liver_tissue, 30, strata=2)
    core = build_core()
    sim = Composite({"state": pulse_hepatic(core)}, core=core)
    sim.run(30)
    alone = gather_emitter_results(sim)[("emitter",)]
    for a, b in zip(with_block, alone):
        for path in HEPATIC_PATHS:
            x, y = a["circuits"]["hepatic"], b["circuits"]["hepatic"]
            for key in path:
                x, y = x[key], y[key]
            assert x == pytest.approx(y, rel=1e-9, abs=1e-12), path


def test_replay_reproduces_the_live_block(tmp_path):
    """Falsifies: the replay variant is not the live block's science. Replaying the
    live run's own hepatic reads must give the same cells."""
    live = _run(pulse_liver_tissue, 20, strata=3, extraction=0.5)
    trajectory = save_hepatic_trajectory(live, tmp_path / "live.json")
    replay = _run(liver_tissue_replay, 20, trajectory_file=str(trajectory), strata=3, extraction=0.5)
    for a, b in zip(live, replay):
        assert a["tissue"]["drive"] == b["tissue"]["drive"]
        for name, cells in a["tissue"]["cells"].items():
            for species, value in cells.items():
                assert b["tissue"]["cells"][name][species] == pytest.approx(value, rel=1e-9, abs=1e-12)


# -- replay -------------------------------------------------------------------------


def test_one_stratum_equals_standalone_copasi(recorded):
    """Falsifies: the instance isn't equilibrated at its first drive, or is advanced
    with the wrong drive or units. With one stratum each cell sees Pulse's liver
    value, so the oracle is upstream CopasiUTCProcess driven by hand with
    liver pmol/L / 1000."""
    rows = _run(liver_tissue_replay, 40, trajectory_file=str(recorded), strata=1)
    drives = [row["circuits"]["hepatic"]["liver"]["insulin_pmol_per_L"] / 1000.0 for row in rows]
    oracle = _standalone(drives[:-1])
    for row, expected in zip(rows[1:], oracle):
        cells = row["tissue"]["cells"]["s0_hepatocyte"]
        for species in RECEPTOR:
            assert cells[species] == pytest.approx(expected[species], rel=1e-9, abs=1e-12), species
        assert row["tissue"]["summary"]["mean_nM"]["IRp"] == pytest.approx(cells["IRp"], rel=1e-12)


def test_insulin_step_raises_binding_after_the_step_with_a_one_interval_hold(recorded, tmp_path):
    """Pre-registered: a tenfold insulin step at t = 30 raises insulin-bound receptor,
    and nothing moves before it (cells start equilibrated). The 10% floor only
    separates a response from numerical noise (measured: x1.36 by t = 90; binding
    at 1.6 nM has a time constant of minutes). Lag: the block holds
    each drive over the interval that starts at it, so it matches a standalone run
    fed the same drives and differs from one fed the drives one second early."""
    synthetic = _synthetic(recorded, tmp_path, seconds=90, step_at=30, factor=10.0)
    rows = _run(liver_tissue_replay, 90, trajectory_file=str(synthetic), strata=1)
    bound = [_bound(row["tissue"]["cells"]["s0_hepatocyte"]) for row in rows]
    assert max(bound[1:31]) - min(bound[1:31]) < 1e-9 * bound[1]
    assert all(b > a for a, b in zip(bound[30:], bound[31:]))
    assert bound[90] > 1.1 * bound[30]

    drives = [row["circuits"]["hepatic"]["liver"]["insulin_pmol_per_L"] / 1000.0 for row in rows]
    aligned = [_bound(s) for s in _standalone(drives[:-1])]
    early = [_bound(s) for s in _standalone(drives[1:])]
    assert bound[1:] == pytest.approx(aligned, rel=1e-9)
    assert early[29] > bound[30] * 1.001  # the early run already steps over [29, 30]


def test_subpopulations_aggregate_by_weight(recorded):
    """Falsifies: a subpopulation's parameters don't reach COPASI, or the summary
    weights instances wrongly. The summary is recomputed from the emitted cells:
    weight = stratum volume (1/2) x subpopulation weight."""
    subpopulations = {"typical": {"weight": 0.75, "parameters": {}},
                      "fast_internalizing": {"weight": 0.25, "parameters": {"intk1": 0.0011}}}
    rows = _run(liver_tissue_replay, 10, trajectory_file=str(recorded), strata=2, subpopulations=subpopulations)
    weights = {"s0_typical": 0.375, "s1_typical": 0.375,
               "s0_fast_internalizing": 0.125, "s1_fast_internalizing": 0.125}
    last = rows[-1]["tissue"]
    assert last["cells"]["s0_fast_internalizing"]["IRen"] > 1.2 * last["cells"]["s0_typical"]["IRen"]
    for species in RECEPTOR:
        values = {name: last["cells"][name][species] for name in weights}
        mean = sum(weights[n] * v for n, v in values.items())
        summary = last["summary"]
        assert summary["mean_nM"][species] == pytest.approx(mean, rel=1e-12)
        assert summary["min_nM"][species] == min(values.values())
        assert summary["max_nM"][species] == max(values.values())
        sd = math.sqrt(sum(weights[n] * (v - mean) ** 2 for n, v in values.items()))
        assert summary["sd_nM"][species] == pytest.approx(sd, rel=1e-9, abs=1e-15)


def test_amounts_follow_the_paper_geometry(recorded):
    """Falsifies: a unit or volume error in the per-cell and whole-liver amounts.
    Koschorreck 2008: 40 nM of receptor is 1e5 receptors per 20 um hepatocyte,
    and receptors are conserved; hepatocytes fill 78% of a liver of density
    1051 g/L. Pulse's liver weighs 1.8 kg."""
    rows = _run(liver_tissue_replay, 5, trajectory_file=str(recorded), strata=1)
    summary = rows[-1]["tissue"]["summary"]
    receptors = sum(summary["molecules_per_cell"][s] for s in RECEPTOR)
    assert receptors == pytest.approx(1.0e5, rel=0.01)
    cell_L = math.pi / 6 * (20e-6) ** 3 * 1000.0
    cells = 0.78 * (1.8 / 1.051) / cell_L
    assert summary["cell_count"] == pytest.approx(cells, rel=1e-9)
    total = sum(summary["tissue_total_nmol"][s] for s in RECEPTOR)
    assert total == pytest.approx(cells * 1.0e5 / 6.02214076e23 * 1e9, rel=0.01)


# -- validation (no engine) ----------------------------------------------------------


@pytest.mark.parametrize("params, match", [
    ({"strata": 0}, "strata"),
    ({"extraction": 1.5}, "extraction"),
    ({"extraction": -0.1}, "extraction"),
    ({"subpopulations": {"a": {"weight": 0.5}}}, "sum to 1"),
    ({"subpopulations": {"a": {"weight": 1.0, "rate": 2}}}, "unexpected keys"),
    ({"subpopulations": {}}, "at least one"),
    ({"stratum": 2}, "unexpected"),
])
def test_generator_validates_when_building(params, match):
    with pytest.raises((ValueError, TypeError), match=match):
        pulse_liver_tissue(None, **params)


def test_importing_the_cell_module_keeps_the_text_encoding():
    """Falsifies: loading the tissue block turns the process's default text encoding
    into ASCII (a bare COPASI import does: it sets the locale to "C"), which broke
    later non-ASCII file reads in the same process, e.g. the docs test."""
    import os
    import subprocess
    import sys

    probe = ("import locale; before = locale.getpreferredencoding(False); import {}; "
             "print(before, locale.getpreferredencoding(False))")
    env = {**os.environ, "LC_ALL": "", "LANG": "en_US.UTF-8"}
    outputs = {}
    for module in ("COPASI", "viva_pulse.multiscale.cells"):
        result = subprocess.run([sys.executable, "-c", probe.format(module)], capture_output=True, text=True,
                                env=env, timeout=120, check=True)
        outputs[module] = result.stdout.split()[-2:]
    assert outputs["COPASI"] == ["UTF-8", "US-ASCII"]  # the defect being contained
    assert outputs["viva_pulse.multiscale.cells"] == ["UTF-8", "UTF-8"]


def test_unknown_cell_parameter_fails_at_construction():
    from viva_pulse.multiscale.cells import EquilibratedCopasiProcess
    with pytest.raises(ValueError, match="not fixed global quantities"):
        EquilibratedCopasiProcess({"model_source": str(KOSCHORRECK_2008), "parameters": {"kon": 1.0}},
                                  core=allocate_core())


def test_missing_drive_fails_instead_of_running_on_the_file_value():
    from viva_pulse.multiscale.cells import EquilibratedCopasiProcess
    process = EquilibratedCopasiProcess({"model_source": str(KOSCHORRECK_2008), "driven": ["ins"]},
                                        core=allocate_core())
    with pytest.raises(ValueError, match="missing"):
        process.update({"species_counts": {}, "species_concentrations": {}}, 1.0)


def test_insulin_above_the_cell_model_bound_raises(recorded, tmp_path):
    """Falsifies: a drive outside the cell model's trusted range passes silently. The
    synthetic trajectory multiplies insulin past the bound at t = 3."""
    over = _synthetic(recorded, tmp_path, seconds=10, step_at=3, factor=1e4)
    with pytest.raises(ValueError, match="above the cell model's bound"):
        _run(liver_tissue_replay, 10, trajectory_file=str(over), max_insulin_nM=100.0)


def test_replay_rejects_a_trajectory_with_other_paths(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"time": [0.0, 1.0], "values": {"liver/insulin_pmol_per_L": [1.0, 1.0]}}))
    with pytest.raises(ValueError, match="trajectory paths differ"):
        _run(liver_tissue_replay, 1, trajectory_file=str(path))
