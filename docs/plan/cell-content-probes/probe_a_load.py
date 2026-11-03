"""Probe A: does König's hepatic glucose model load reliably in COPASI, and what does it hold?

viva-sbml-decomposition saw COPASI's SBML import abort about 1 in 5 times, so
load it 50 times in fresh interpreters and 20 times in one interpreter (each
stratum loads its own copy).
"""
import subprocess
import sys

import viva_pulse.multiscale.cells  # noqa: F401  imports COPASI with the locale kept
from basico import get_compartments, get_parameters, get_species, load_model

from viva_pulse.multiscale.models import koenig_2014

path = str(koenig_2014())
code = ("import viva_pulse.multiscale.cells; from basico import load_model; "
        f"print(load_model({path!r}).getModel().getNumReactions())")
fresh = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180) for _ in range(50)]
bad = [(r.returncode, r.stderr[-200:]) for r in fresh if r.returncode != 0 or r.stdout.split()[-1:] != ["36"]]
print(f"fresh-interpreter loads: {50 - len(bad)}/50 ok", bad[:3])

for _ in range(20):
    dm = load_model(path)
print("same-interpreter loads: 20/20 ok, reactions", dm.getModel().getNumReactions())

species = get_species(model=dm)
print("species by compartment:", species.groupby("compartment").size().to_dict())
print("boundary species:", sorted(species.index[species["type"] == "fixed"]))
params = get_parameters(model=dm)
for name in ("ins", "glu", "epi", "gamma"):
    row = params.loc[name]
    print(f"{name}: type={row['type']} unit={row['unit']} value={row['value']:.4g} expression={row['expression'][:90]}")
print("compartments:", get_compartments(model=dm)[["type", "initial_size", "unit"]].to_dict("index"))
