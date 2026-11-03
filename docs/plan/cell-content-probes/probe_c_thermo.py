"""Probe C: which of König's reactions eQuilibrator can score, from the model's own KEGG annotations.

Conditions are the provisional cell values (pH 7.2, ionic strength 0.25 M, pMg 3)
at Pulse's core temperature; eQuilibrator uses its bundled data only (the "auto"
tier would switch to a full database when one is on the machine). Concentrations
are probe B's steady state at Pulse's liver values.
"""
import re
import time
import xml.etree.ElementTree as ET

import viva_pulse.multiscale.cells  # noqa: F401  imports COPASI with the locale kept
from basico import get_species, load_model, run_steadystate, set_parameters, set_species
from equilibrator_api import ComponentContribution, Q_
from equilibrator_cache.api import create_compound_cache_from_zenodo

from viva_pulse.multiscale.models import koenig_2014

SBML = "{http://www.sbml.org/sbml/level3/version1/core}"
path = koenig_2014()
root = ET.parse(path).getroot()
model = root.find(f"{SBML}model")

kegg = {}
for sp in model.iter(f"{SBML}species"):
    ids = re.findall(r"kegg\.compound[/:](C\d{5})", ET.tostring(sp, encoding="unicode"))
    kegg[sp.get("id")] = sorted(set(ids))
ANNOTATED = {k: list(v) for k, v in kegg.items()}
# Corrections: two mitochondrial annotations are swapped to the wrong compounds,
# and three reactions omit the water they consume or release.
KEGG_CORRECTIONS = {"h2o_mito": ["C00001"], "h_mito": ["C00080"]}
H2O_PATCHES = {"FBP2": "lhs", "EN": "rhs", "PC": "lhs"}
kegg.update(KEGG_CORRECTIONS)
compartment = {sp.get("id"): sp.get("compartment") for sp in model.iter(f"{SBML}species")}
print("species without exactly one KEGG id:", {k: v for k, v in kegg.items() if len(v) != 1})
print("mitochondrial water/proton as annotated:", {k: ANNOTATED[k] for k in ("h2o", "h", "h2o_mito", "h_mito")}, "-> corrected")

# steady state at Pulse's liver values (probe B): concentrations in mM
dm = load_model(str(path))
set_species(name="glc_ext", exact=True, initial_concentration=6.05, model=dm)
set_species(name="lac_ext", exact=True, initial_concentration=1.64, model=dm)
set_parameters(name="ins", exact=True, status="fixed", model=dm)
set_parameters(name="ins", exact=True, initial_value=160.0, model=dm)
assert run_steadystate(model=dm, update_model=True) == 1
species = get_species(model=dm)
conc_mM = {species.loc[n, "sbml_id"]: float(species.loc[n, "concentration"]) for n in species.index}
from basico import get_reactions
reactions = get_reactions(model=dm)
flux = {reactions.loc[n, "sbml_id"] if "sbml_id" in reactions.columns else n: float(reactions.loc[n, "flux"]) for n in reactions.index}

cc = ComponentContribution(ccache=create_compound_cache_from_zenodo(tier="bundled"))
cc.p_h, cc.ionic_strength, cc.p_mg = Q_(7.2), Q_("0.25 M"), Q_(3.0)
cc.temperature = Q_("310.18 K")  # Pulse core temperature 37.03 C

def side(refs):
    return [(r.get("species"), float(r.get("stoichiometry", 1))) for r in refs]

def dg_prime(formula, participants):
    """dG' of the formula with each participant's steady-state concentration (mM -> M); water and H+ are left to eQuilibrator."""
    reaction = cc.parse_reaction_formula(formula)
    for s in participants:
        cpd = cc.get_compound(f"kegg:{kegg[s][0]}")
        if not (cc.ccache.is_water(cpd) or cc.ccache.is_proton(cpd)):
            reaction.set_abundance(cpd, Q_(conc_mM[s] * 1e-3, "M"))
    return cc.dg_prime(reaction)


def conflict(f, dg):
    """Net flux must run down the free-energy gradient (flux * dG' <= 0); flagged beyond 2 sigma."""
    return f is not None and abs(f) > 1e-12 and f * dg.value.m_as("kJ/mol") > 0 \
        and abs(dg.value.m_as("kJ/mol")) > 2 * dg.error.m_as("kJ/mol")


scored, excluded = {}, {}
t0 = time.perf_counter()
for rxn in model.iter(f"{SBML}reaction"):
    rid = rxn.get("id")
    lhs = side(rxn.findall(f"{SBML}listOfReactants/{SBML}speciesReference"))
    rhs = side(rxn.findall(f"{SBML}listOfProducts/{SBML}speciesReference"))
    comps = {compartment[s] for s, _ in lhs + rhs}
    if any(len(kegg[s]) != 1 for s, _ in lhs + rhs):
        excluded[rid] = "a participant without exactly one KEGG id"; continue
    if {kegg[s][0] for s, _ in lhs} & {kegg[s][0] for s, _ in rhs}:
        excluded[rid] = f"same compound on both sides (transport or polymer), compartments {sorted(comps)}"; continue
    left = [f"{n:g} kegg:{kegg[s][0]}" for s, n in lhs] + (["1 kegg:C00001"] if H2O_PATCHES.get(rid) == "lhs" else [])
    right = [f"{n:g} kegg:{kegg[s][0]}" for s, n in rhs] + (["1 kegg:C00001"] if H2O_PATCHES.get(rid) == "rhs" else [])
    formula = " + ".join(left) + " = " + " + ".join(right)
    reaction = cc.parse_reaction_formula(formula)
    if not reaction.is_balanced():
        excluded[rid] = f"unbalanced as annotated: {formula}"; continue
    dg0 = cc.standard_dg_prime(reaction)
    dg = dg_prime(formula, [s for s, _ in lhs + rhs])
    scored[rid] = (formula, dg0.value.m_as("kJ/mol"), dg0.error.m_as("kJ/mol"), dg.value.m_as("kJ/mol"), sorted(comps),
                   flux.get(rid), [s for s, _ in lhs + rhs])
elapsed = time.perf_counter() - t0
print(f"scored {len(scored)}, excluded {len(excluded)}, of {len(scored) + len(excluded)}; {elapsed:.2f} s; escalated: {cc.ccache.is_escalated}")
conflicts = []
for rid, (formula, dg0, sd, dg, comps, f, parts) in scored.items():
    flagged = conflict(f, dg_prime(formula, parts))
    conflicts += [rid] if flagged else []
    print(f"  {rid:10s} dG'0 {dg0:8.2f} ± {sd:5.2f}  dG' {dg:8.2f} kJ/mol  flux {f: .3e}  {'CONFLICT' if flagged else ''} {comps}  {formula}")
print("flux opposes dG' (beyond 2 sigma):", conflicts)
for rid, why in excluded.items():
    print(f"  EXCLUDED {rid:10s} {why}")


# Sensitivity: do the conflicts depend on the provisional conditions?
print("conflicts across conditions:")
for ph in (7.0, 7.2, 7.4):
    for pmg in (2.0, 3.0, 4.0):
        for ionic in (0.15, 0.25):
            cc.p_h, cc.p_mg, cc.ionic_strength = Q_(ph), Q_(pmg), Q_(f"{ionic} M")
            found = [rid for rid, (formula, *_, f, parts) in scored.items() if conflict(f, dg_prime(formula, parts))]
            print(f"  pH {ph} pMg {pmg} I {ionic}: {found}")

# König's own equilibrium constants vs eQuilibrator's K' = exp(-dG'0/RT) at the provisional conditions.
# König's concentrations are mM; eQuilibrator's standard state is 1 M.
import math
cc.p_h, cc.p_mg, cc.ionic_strength = Q_(7.2), Q_(3.0), Q_("0.25 M")
keq = {p.get("id")[:-4]: float(p.get("value")) for p in model.iter(f"{SBML}parameter") if p.get("id", "").endswith("_keq")}
RT = 8.314462618e-3 * 310.18
print("Keq: König (as written) vs eQuilibrator K' (1 M standard):")
for rid, (formula, *_rest) in scored.items():
    if rid in keq:
        k_eq = math.exp(-cc.standard_dg_prime(cc.parse_reaction_formula(formula)).value.m_as("kJ/mol") / RT)
        print(f"  {rid:8s} König {keq[rid]:10.4g}  eQuilibrator {k_eq:10.4g}  ratio {keq[rid] / k_eq:10.4g}")
dupes = [(a, b) for a in keq for b in keq if a < b and keq[a] == keq[b]]
print("identical Keq values across reactions:", dupes)
