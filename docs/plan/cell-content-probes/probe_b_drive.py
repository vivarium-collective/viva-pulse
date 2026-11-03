"""Probe B: drive König's model with Pulse's liver blood values.

Insulin becomes a fixed, externally set quantity (its assignment rule is
switched off); external glucose and lactate are set from Pulse. Checks the
steady state, what glycogen does, the cost of a 1 s update, and the response
directions the later tests pre-register.
"""
import time

import viva_pulse.multiscale.cells  # noqa: F401  imports COPASI with the locale kept
from basico import get_parameters, get_reactions, get_species, load_model, run_steadystate, run_time_course
from basico import set_parameters, set_species

from viva_pulse.multiscale.models import koenig_2014

PULSE = {"glc_ext": 6.05, "lac_ext": 1.64, "ins": 160.0}  # StandardMale liver blood, t=0 (mM, mM, pmol/L)


def driven(glc=PULSE["glc_ext"], lac=PULSE["lac_ext"], ins=PULSE["ins"]):
    """Model with glucose/lactate set, König's own insulin read after one simulated
    second (assignments are recomputed only while simulating), then insulin fixed."""
    dm = load_model(str(koenig_2014()))
    set_species(name="glc_ext", exact=True, initial_concentration=glc, model=dm)
    set_species(name="lac_ext", exact=True, initial_concentration=lac, model=dm)
    run_time_course(duration=1.0, intervals=1, model=dm, update_model=False)
    own_ins = float(get_parameters(model=dm).loc["ins", "value"])
    # Two calls: with status and value in one call, COPASI keeps the rule's current value.
    set_parameters(name="ins", exact=True, status="fixed", model=dm)
    set_parameters(name="ins", exact=True, initial_value=ins, model=dm)
    return dm, own_ins


def after_one_second(dm):
    run_time_course(duration=1.0, intervals=1, model=dm, update_model=True)
    return dm


def gamma(dm):
    return float(get_parameters(model=dm).loc["gamma", "value"])


def net_glycogen(dm):
    r = get_reactions(model=dm)
    return {k: round(float(r.loc[k, "flux"]), 6) for k in r.index if any(s in k.upper() for s in ("GS", "GP", "GLY"))}


dm, own = driven()
p = get_parameters(model=dm)
print(f"König's own insulin at glucose 6.05 mM: {own:.1f} pmol/L; driven: type={p.loc['ins', 'type']} initial={p.loc['ins', 'initial_value']}")
print("reactions:", list(get_reactions(model=dm).index))
status = run_steadystate(model=dm, update_model=True)
sp = get_species(model=dm)
print("steady-state status", status, "| gamma", round(float(get_parameters(model=dm).loc['gamma', 'value']), 4))
print("cytosol species:", ", ".join(f"{n}={float(sp.loc[n, 'concentration']):.4g}" for n in sp.index if sp.loc[n, "compartment"] == "cyto" and sp.loc[n, "type"] != "fixed")[:900])
print("glycogen-related fluxes at the solve:", net_glycogen(dm))

dm, _ = driven()
tc = run_time_course(duration=3600, intervals=6, model=dm, update_model=True)
glycogen = [c for c in tc.columns if "gly" in c.lower()]
print("1 h from the file state, glycogen columns:", glycogen, tc[glycogen].iloc[[0, 3, 6]].round(4).to_dict("list") if glycogen else None)

dm, _ = driven()
t0 = time.perf_counter()
for _ in range(300):
    run_time_course(duration=1.0, intervals=1, model=dm, update_model=True)
print(f"cost: {(time.perf_counter() - t0) / 300 * 1e3:.2f} ms per 1 s update")

for ins in (9.7, 80.0, 160.0, 320.0):
    dm = after_one_second(driven(ins=ins)[0])
    print(f"ins {ins} pmol/L: gamma {gamma(dm):.4f}, ins in model {float(get_parameters(model=dm).loc['ins', 'value']):.1f}")
for glc in (4.0, 8.0):
    dm, _ = driven(glc=glc)
    run_steadystate(model=dm, update_model=True)
    sp = get_species(model=dm)
    print(f"glucose {glc} mM (ins 160): steady glycogen {float(sp.loc['glyglc', 'concentration']):.1f} mM, fluxes {net_glycogen(dm)}")
dm, _ = driven()
after_one_second(dm)
sp = get_species(model=dm)
print("after 1 s at Pulse values: lac_ext", float(sp.loc['lac_ext', 'concentration']), "cytosolic lac", float(sp.loc['lac', 'concentration']))
