"""Probe D: three provisional corrections to König's equilibrium constants (mine, not a modeler's).

- EN_keq: copied from TPI_keq in the published file; replaced by eQuilibrator's
  K' at the provisional cell conditions (pH 7.2, pMg 3, I 0.25 M, 310.18 K).
- LDH_keq: the published value is the reverse-direction constant (the rate law
  is pyr + NADH -> lac + NAD with v ~ S - P/Keq); inverted.
- ALD_keq: declared mM, but the value matches eQuilibrator's K' in M; scaled x1000.
PEPCK_keq (55x off even after units) and PGK_keq (260x off) are left as published.

Checks: the corrected values are fixed global quantities, a steady state still
exists at Pulse's liver values, and which second-law conflicts remain.
"""
import viva_pulse.multiscale.cells  # noqa: F401  imports COPASI with the locale kept
from basico import get_parameters, get_reactions, get_species, load_model, run_steadystate, set_parameters, set_species

from viva_pulse.multiscale.models import koenig_2014

CORRECTIONS = {"EN_keq": 4.346, "LDH_keq": 1 / 0.000278321076004752, "ALD_keq": 9.76298897362969e-5 * 1000}


def steady(corrections, glc=6.05, lac=1.64, ins=160.0):
    dm = load_model(str(koenig_2014()))
    table = get_parameters(model=dm)
    for name, value in corrections.items():
        assert table.loc[name, "type"] == "fixed", name
        set_parameters(name=name, exact=True, initial_value=value, model=dm)
    set_species(name="glc_ext", exact=True, initial_concentration=glc, model=dm)
    set_species(name="lac_ext", exact=True, initial_concentration=lac, model=dm)
    set_parameters(name="ins", exact=True, status="fixed", model=dm)
    set_parameters(name="ins", exact=True, initial_value=ins, model=dm)
    status = run_steadystate(model=dm, update_model=True)
    sp, rx = get_species(model=dm), get_reactions(model=dm)
    conc = {sp.loc[n, "sbml_id"]: float(sp.loc[n, "concentration"]) for n in sp.index}
    flux = {rx.loc[n, "sbml_id"] if "sbml_id" in rx.columns else n: float(rx.loc[n, "flux"]) for n in rx.index}
    return status, conc, flux


for label, corr in (("published", {}), ("corrected", CORRECTIONS)):
    status, conc, flux = steady(corr)
    print(f"{label}: status {status}; glycogen {conc['glyglc']:.1f} mM; cytosolic lac {conc['lac']:.3g} mM; "
          f"pyr {conc['pyr']:.3g}; GLUT2 flux {flux.get('GLUT2', float('nan')):.4g} (glucose output if < 0)")
    for glc in (4.0, 8.0):
        s, c, f = steady(corr, glc=glc)
        print(f"   glucose {glc}: status {s}, glycogen {c['glyglc']:.1f}, GAPDH flux {f.get('GAPDH', float('nan')):.4g}")
