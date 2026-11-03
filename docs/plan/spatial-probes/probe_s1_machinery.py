"""Probe S1: does Jim Schaff's hybrid (FV PDE field + Smoldyn particles) run here, repeatably?

Runs viva-pde-particle's own `bimolecular_hybrid` example (A particle + B field -> C
field) twice with the same seed, once with another seed, using the Smoldyn fork
compiled in .smoldyn-build/ (virtualcell/Smoldyn pyhybrid 9152dc2).
"""
import time

import numpy as np
from process_bigraph import Composite
from viva_pde_particle.composites.examples import bimolecular_hybrid
from viva_pde_particle.core import build_core


def totals(tree):
    """Sum of every numeric array in the state, keyed by its path (particles and fields)."""
    out = {}
    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + (k,))
        elif isinstance(node, (np.ndarray, list)) and len(node) and np.asarray(node).dtype.kind in "fi":
            out["/".join(path)] = float(np.asarray(node, dtype=float).sum())
    walk(tree, ())
    return out


def run(seed, seconds=2.0):
    core = build_core()
    doc = bimolecular_hybrid(core, n_particles=5000, seed=seed)
    sim = Composite({"state": doc}, core=core)
    t0 = time.perf_counter()
    sim.run(seconds)
    stores = {k: v for k, v in sim.state.items() if not isinstance(v, dict) or "_type" not in v}
    return totals(stores), time.perf_counter() - t0


a, b, c = run(1), run(1), run(2)
print("seed 1:", {k: round(v, 6) for k, v in a[0].items()}, f"{a[1]:.1f} s")
print("seed 1 again, identical:", a[0] == b[0])
print("seed 2, differs:", a[0] != c[0])
