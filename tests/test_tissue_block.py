"""The stratified liver tissue block under Pulse (docs/guide/guide-multiscale-design.md).

Real Pulse and real COPASI, no mocks. Oracles come from outside the block: the
upstream ``CopasiUTCProcess`` stepped by hand, Koschorreck 2008's own geometry,
or Pulse's hepatic reads emitted alongside.
"""

import json
import math

import pytest

# Import COPASI through the cell module, which keeps the process locale (see test below).
pytest.importorskip("viva_pulse.multiscale.cells")

from basico import load_model, run_steadystate, run_time_course, set_parameters, set_species  # noqa: E402
from process_bigraph import Composite, allocate_core, gather_emitter_results  # noqa: E402
from viva_copasi.processes import CopasiUTCProcess  # noqa: E402

from viva_pulse.composites import liver_tissue_replay, pulse_hepatic, pulse_liver_tissue  # noqa: E402
from viva_pulse.core import build_core  # noqa: E402
from viva_pulse.multiscale import KOSCHORRECK_2008, register_multiscale, save_hepatic_trajectory  # noqa: E402
from viva_pulse.multiscale.models import KOENIG_PARAMETER_SETS, koenig_2014  # noqa: E402
from viva_pulse.patients import CACHE_ENV_VAR  # noqa: E402
from viva_pulse.multiscale.tissue import HEPATIC_PATHS  # noqa: E402

BOUND = ("IR", "I2R", "IRp", "I2Rp", "IRen", "I2Ren", "IRPen", "I2RPen")  # insulin-bound receptor states
RECEPTOR = BOUND + ("R", "Rp", "Ren", "RPen")


@pytest.fixture(autouse=True, scope="module")
def _model_cache(tmp_path_factory):
    """König's model is downloaded into a temporary cache, never the user's (needs network once)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(CACHE_ENV_VAR, str(tmp_path_factory.mktemp("viva-pulse-cache")))
        yield


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


def _constant(recorded, tmp_path, *, seconds, name="constant.json", **values):
    """Pulse's t=0 hepatic values held for ``seconds``, with ``values`` (path with '/' as '__') replacing some."""
    base = json.loads(recorded.read_text())
    overrides = {key.replace("__", "/"): value for key, value in values.items()}
    series = {key: [overrides.get(key, s[0])] * (seconds + 1) for key, s in base["values"].items()}
    path = tmp_path / name
    path.write_text(json.dumps({"time": [float(t) for t in range(seconds + 1)], "values": series}))
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
    """Falsifies: attaching the block, with every cell simulator on, perturbs Pulse (it
    must be a passive readout). Every hepatic reading equals a Pulse run without it."""
    with_block = _run(pulse_liver_tissue, 30, strata=2, extraction=0.5, metabolism=True, thermo=True)
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


# -- metabolism (König, COPASI) -------------------------------------------------------


def _metabolism(row):
    return row["tissue"]["metabolism"]


def test_metabolism_cell_equals_direct_copasi(recorded):
    """Falsifies: the metabolism cell isn't König's model driven by Pulse's liver glucose,
    lactate, insulin and epinephrine (wrong species, units, timing, or a hormone left to
    König's own rule). Oracle: König loaded directly through basico, insulin and
    epinephrine switched to fixed, equilibrated at the first drive, then advanced 1 s
    per drive by hand."""
    rows = _run(liver_tissue_replay, 15, trajectory_file=str(recorded), metabolism=True)
    liver = [row["circuits"]["hepatic"]["liver"] for row in rows]
    drives = [(x["glucose_mM"], x["lactate_mM"], x["insulin_pmol_per_L"], x["epinephrine_pmol_per_L"]) for x in liver]
    dm = load_model(str(koenig_2014()))
    set_parameters(name="ins", exact=True, status="fixed", model=dm)
    set_parameters(name="epi", exact=True, status="fixed", model=dm)

    def drive(glc, lac, ins, epi):
        set_species(name="glc_ext", exact=True, initial_concentration=glc, model=dm)
        set_species(name="lac_ext", exact=True, initial_concentration=lac, model=dm)
        set_parameters(name="ins", exact=True, initial_value=ins, model=dm)
        set_parameters(name="epi", exact=True, initial_value=epi, model=dm)

    drive(*drives[0])
    assert run_steadystate(model=dm, update_model=True) in (1, 2)
    for row, step in zip(rows[1:], drives[:-1]):
        drive(*step)
        tc = run_time_course(duration=1.0, intervals=1, model=dm, update_model=True, use_sbml_id=True)
        cells = _metabolism(row)["cells"]["s0_hepatocyte"]
        # rel 1e-6 = COPASI's default integration tolerance: the cell and the oracle set initial
        # values through different calls, which moves the integrator's path at that level.
        for species in ("glc", "glc6p", "glyglc", "pyr", "lac", "oaa"):
            assert cells[species] == pytest.approx(float(tc[species].iloc[-1]), rel=1e-6, abs=1e-12), species
        assert _metabolism(row)["quantities"]["s0_hepatocyte"]["gamma"] == pytest.approx(
            dm.getModel().getModelValue("gamma").getValue(), rel=1e-6)


def test_driven_insulin_alone_moves_gamma(recorded, tmp_path):
    """Falsifies: König's own insulin rule (a function of glucose) still drives gamma.
    Glucose is held constant and only Pulse's insulin steps x4 at t = 10, so gamma
    may change only through the driven insulin: flat before, lower after (probe B:
    gamma falls as insulin rises)."""
    synthetic = _synthetic(recorded, tmp_path, seconds=20, step_at=10, factor=4.0)
    rows = _run(liver_tissue_replay, 20, trajectory_file=str(synthetic), metabolism=True)
    gamma = [_metabolism(row)["quantities"]["s0_hepatocyte"]["gamma"] for row in rows]
    assert max(gamma[1:11]) - min(gamma[1:11]) < 1e-9
    assert gamma[11] < gamma[10] - 0.01


def test_parameter_sets_reach_copasi_and_aggregate_by_weight(recorded):
    """Falsifies: a subpopulation's König parameter set doesn't reach COPASI, or the
    metabolism summary weights instances wrongly. Pre-registered from probe D: with
    the provisional corrections cytosolic lactate sits near the external 1.6 mM, as
    published it stays below 1e-3 mM."""
    subpopulations = {"published": {"weight": 0.25},
                      "corrected": {"weight": 0.75, "metabolism_parameters": "provisional_corrections"}}
    rows = _run(liver_tissue_replay, 3, trajectory_file=str(recorded), metabolism=True, subpopulations=subpopulations)
    m = _metabolism(rows[-1])
    assert m["cells"]["s0_corrected"]["lac"] > 1.0 > 1e-3 > m["cells"]["s0_published"]["lac"]
    for species in ("lac", "glyglc", "glc6p"):
        expected = 0.25 * m["cells"]["s0_published"][species] + 0.75 * m["cells"]["s0_corrected"][species]
        assert m["cells_summary"]["mean_mM"][species] == pytest.approx(expected, rel=1e-12)
    assert m["fluxes_summary"]["mean_mmol_per_s"]["GLUT2"] == pytest.approx(
        0.25 * m["fluxes"]["s0_published"]["GLUT2"] + 0.75 * m["fluxes"]["s0_corrected"]["GLUT2"], rel=1e-12)


def test_each_stratum_drives_its_own_metabolism_cells(recorded):
    """Falsifies: König cells read the wrong stratum's insulin, or the liver mean, or not
    Pulse's epinephrine. With two strata and extraction 0.5 the strata differ; each
    cell's insulin (pmol/L) after an update must be its own stratum's drive (nM x 1000)
    from the start of that interval, and its epinephrine Pulse's liver value."""
    rows = _run(liver_tissue_replay, 4, trajectory_file=str(recorded), strata=2, extraction=0.5, metabolism=True)
    for before, after in zip(rows[1:], rows[2:]):
        drive = before["tissue"]["drive"]
        assert drive["s0"]["ins"] > 1.1 * drive["s1"]["ins"]
        for stratum in ("s0", "s1"):
            quantities = _metabolism(after)["quantities"][f"{stratum}_hepatocyte"]
            assert quantities["ins"] == pytest.approx(drive[stratum]["ins"] * 1000.0, rel=1e-12)
            assert quantities["epi"] == pytest.approx(
                before["circuits"]["hepatic"]["liver"]["epinephrine_pmol_per_L"], rel=1e-12)


def test_metabolism_input_outside_konigs_range_raises(recorded, tmp_path):
    """Falsifies: König runs blind on a glucose below the 2-14 mM its authors analysed."""
    low = _constant(recorded, tmp_path, seconds=3, name="hypo.json", liver__glucose_mM=1.0)
    with pytest.raises(ValueError, match="outside the range"):
        _run(liver_tissue_replay, 3, trajectory_file=str(low), metabolism=True)


def test_higher_glucose_stores_more_glycogen(recorded, tmp_path):
    """Pre-registered from probe B: König's steady glycogen rises with external glucose
    (117 mM at 4 mM glucose, 494 mM at 8 mM, insulin 160 pmol/L)."""
    glycogen = {}
    for glucose in (4.0, 8.0):
        trajectory = _constant(recorded, tmp_path, seconds=3, name=f"glc{glucose}.json",
                               liver__glucose_mM=glucose, liver__insulin_pmol_per_L=160.0)
        rows = _run(liver_tissue_replay, 3, trajectory_file=str(trajectory), metabolism=True)
        glycogen[glucose] = _metabolism(rows[-1])["cells"]["s0_hepatocyte"]["glyglc"]
    assert glycogen[8.0] > 2 * glycogen[4.0]


# -- thermodynamics (eQuilibrator) ----------------------------------------------------

THERMO = {"metabolism": True, "thermo": True}


def _equilibrator(conditions):
    from equilibrator_api import ComponentContribution, Q_
    from equilibrator_cache.api import create_compound_cache_from_zenodo
    cc = ComponentContribution(ccache=create_compound_cache_from_zenodo(tier="bundled"))
    cc.p_h, cc.p_mg = Q_(conditions["p_h"]), Q_(conditions["p_mg"])
    cc.ionic_strength = Q_(f"{conditions['ionic_strength_M']} M")
    cc.temperature = Q_(f"{conditions['temperature_K']} K")
    return cc, Q_


def test_thermo_equals_equilibrator_with_hand_written_formulas(recorded):
    """Falsifies: wrong formulas (parse, KEGG corrections, water patches), wrong units
    (mM -> M) or wrong arithmetic. Oracle: eQuilibrator's own dg_prime with
    set_abundance, on formulas written here by hand, at the conditions the step reports."""
    rows = _run(liver_tissue_replay, 3, trajectory_file=str(recorded), **THERMO)
    thermo, cells = rows[-1]["tissue"]["thermo"], _metabolism(rows[-1])["cells"]["s0_hepatocyte"]
    core_C = rows[-1]["circuits"]["hepatic"]["body"]["core_temperature_C"]
    assert thermo["conditions"]["temperature_K"] == round(core_C + 273.15, 2)  # Pulse's temperature, in K
    cc, Q_ = _equilibrator(thermo["conditions"])
    # rid -> {kegg id: species id}, water/H+ written but not given an abundance
    by_hand = {
        "GK": ("kegg:C00031 + kegg:C00002 = kegg:C00092 + kegg:C00008",
               {"C00031": "glc", "C00002": "atp", "C00092": "glc6p", "C00008": "adp"}),
        "LDH": ("kegg:C00022 + kegg:C00004 = kegg:C00186 + kegg:C00003",
                {"C00022": "pyr", "C00004": "nadh", "C00186": "lac", "C00003": "nad"}),
        "EN": ("kegg:C00631 = kegg:C00074 + kegg:C00001", {"C00631": "pg2", "C00074": "pep"}),
        # one molecule to two: the mM -> M conversion doesn't cancel
        "ALD": ("kegg:C00354 = kegg:C00118 + kegg:C00111", {"C00354": "fru16bp", "C00118": "grap", "C00111": "dhap"}),
        "PDH": ("kegg:C00022 + kegg:C00010 + kegg:C00003 = kegg:C00024 + kegg:C00011 + kegg:C00004 + kegg:C00080",
                {"C00022": "pyr_mito", "C00010": "coa_mito", "C00003": "nad_mito", "C00024": "acoa_mito",
                 "C00011": "co2_mito", "C00004": "nadh_mito"}),
    }
    for rid, (formula, species) in by_hand.items():
        reaction = cc.parse_reaction_formula(formula)
        for kegg_id, sid in species.items():
            reaction.set_abundance(cc.get_compound(f"kegg:{kegg_id}"), Q_(cells[sid] * 1e-3, "M"))
        expected = cc.dg_prime(reaction).value.m_as("kJ/mol")
        assert thermo["dg_kJ_per_mol"]["s0_hepatocyte"][rid] == pytest.approx(expected, abs=1e-6), rid
    assert not cc.ccache.is_escalated


def test_every_reaction_is_scored_or_excluded():
    """Falsifies: a reaction silently dropped. The model's reactions are read through COPASI."""
    from viva_pulse.multiscale.thermo import KOENIG_EXCLUDED, koenig_reactions
    dm = load_model(str(koenig_2014()))
    model = dm.getModel()
    ids = {model.getReaction(i).getSBMLId() for i in range(model.getReactions().size())}
    scored = koenig_reactions(koenig_2014())
    assert set(scored) | set(KOENIG_EXCLUDED) == ids and not set(scored) & set(KOENIG_EXCLUDED)
    assert len(scored) == 27


def test_second_law_flags_published_and_corrected(recorded):
    """Pre-registered from probes C-D (pH 7.2, pMg 3, I 0.25 M): König as published runs
    ALD, TPI, PGK, EN, PEPCKM and LDH against thermodynamics; the provisional corrections
    clear ALD, EN and LDH."""
    subpopulations = {"published": {"weight": 0.5},
                      "corrected": {"weight": 0.5, "metabolism_parameters": "provisional_corrections"}}
    rows = _run(liver_tissue_replay, 3, trajectory_file=str(recorded), subpopulations=subpopulations, **THERMO)
    flags = rows[-1]["tissue"]["thermo"]["conflicts"]
    published = {r for r, f in flags["s0_published"].items() if f}
    corrected = {r for r, f in flags["s0_corrected"].items() if f}
    assert {"ALD", "TPI", "PGK", "EN", "PEPCKM", "LDH"} <= published
    assert not {"ALD", "EN", "LDH"} & corrected
    assert rows[-1]["tissue"]["thermo"]["conflicts_summary"]["mean_fraction"]["LDH"] == pytest.approx(0.5)


# -- validation (no engine) ----------------------------------------------------------


@pytest.mark.parametrize("params, match", [
    ({"strata": 0}, "strata"),
    ({"extraction": 1.5}, "extraction"),
    ({"extraction": -0.1}, "extraction"),
    ({"subpopulations": {"a": {"weight": 0.5}}}, "sum to 1"),
    ({"subpopulations": {"a": {"weight": 1.0, "rate": 2}}}, "unexpected keys"),
    ({"subpopulations": {}}, "at least one"),
    ({"stratum": 2}, "unexpected"),
    ({"thermo": True}, "thermo needs metabolism"),
    ({"subpopulations": {"a": {"weight": 1.0, "metabolism_parameters": "provisional_corrections"}}},
     "needs metabolism"),
    ({"subpopulations": {"a": {"weight": 1.0, "metabolism_parameters": "refit"}}}, "unknown metabolism_parameters"),
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


def test_thermo_needs_explicit_cell_conditions():
    from viva_pulse.multiscale.thermo import MetabolismThermo
    with pytest.raises(ValueError, match="missing"):
        MetabolismThermo({"model_source": str(koenig_2014()), "instances": ["a"], "p_h": 7.2}, core=build_core())


def test_driven_parameter_must_exist_and_arrive():
    from viva_pulse.multiscale.cells import EquilibratedCopasiProcess
    with pytest.raises(ValueError, match="not global quantities"):
        EquilibratedCopasiProcess({"model_source": str(koenig_2014()), "driven_parameters": ["insulin"]},
                                  core=allocate_core())
    process = EquilibratedCopasiProcess({"model_source": str(koenig_2014()), "driven_parameters": ["ins"]},
                                        core=allocate_core())
    with pytest.raises(ValueError, match="parameter_drive"):
        process.update({"species_counts": {}, "parameter_drive": {}, "species_concentrations": {}}, 1.0)


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
