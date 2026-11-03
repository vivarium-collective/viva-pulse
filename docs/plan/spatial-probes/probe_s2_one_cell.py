"""Probe S2: insulin from blood to receptor particles on one hepatocyte membrane patch.

Physics (provisional, mine): a 10 x 10 x 1 um patch of the space of Disse, blood on
the x = 0 face; 8000 immobile receptors (1e5 per 20 um hepatocyte, ~80/um2, over the
patch); insulin a diffusing field (150 um2/s) held near Pulse's liver value at the
blood face by an exchange term; binding/unbinding with Koschorreck 2008's constants
(kins 1e-3 nM^-1 s^-1, kins1d 4e-4 s^-1). Units: field uM, particles counts.

The blood face is fed through viva-pde-particle's own `external_conc` input: blood
insulin `Ib` and a face mask `M` are external species of the FV engine (terms
I += k_ex Ib and I -= k_ex I M), i.e. the place a Pulse-driven step would write.

Question: is binding reaction-limited (spatial adds little; well-mixed Koschorreck is
adequate) or supply-limited (spatial matters)? Reference: well-mixed binding at the
blood value, B(t) = B_eq (1 - exp(-t/tau)), B_eq = N Ib/(Ib + Kd), tau = 1/(kon Ib + koff).
"""
import math
import time

import numpy as np
from process_bigraph import Composite
from viva_pde_particle.composites.examples import square_grid
from viva_pde_particle.composites.hybrid import build_hybrid_document
from viva_pde_particle.core import build_core
from viva_pde_particle.model.hybrid_model import HybridModel, Reaction, Species

UM_PER_NM = 1e-3
IB = 0.16 * UM_PER_NM            # Pulse liver insulin, StandardMale t = 0 (160 pmol/L)
KON = 1e-3 / UM_PER_NM            # 1 uM^-1 s^-1
KOFF = 4e-4                       # s^-1
N_R = 8000
D_INSULIN = 150.0                 # um2/s
K_EX = 10.0                       # 1/s, blood-face exchange (explicit: k_ex * dt < 1)
DT = 0.05                         # s


def build(seed):
    grid = square_grid(10.0, 11, 1.0)
    model = HybridModel(grid, [Species("R", 0.0, particle=True, initial=N_R),
                               Species("IR", 0.0, particle=True, initial=0),
                               Species("I", D_INSULIN, initial=IB)],
                        [Reaction("bind", {"R": 1, "I": 1}, {"IR": 1}, k=KON),
                         Reaction("unbind", {"IR": 1}, {"R": 1, "I": 1}, k=KOFF)])
    doc = build_hybrid_document(model, dt=DT, seed=seed)
    face = np.zeros(grid.shape)
    face[0, ...] = 1.0
    doc["pde"]["config"]["pde"]["terms"] += [
        {"species": "I", "coeff": 1, "k": K_EX, "reactants": {"Ib": 1}, "reaction": "blood_in"},
        {"species": "I", "coeff": -1, "k": K_EX, "reactants": {"I": 1, "M": 1}, "reaction": "blood_out"},
    ]
    doc["particle_conc"]["Ib"] = IB * face
    doc["particle_conc"]["M"] = face
    return doc


def run(seed, minutes):
    core = build_core()
    sim = Composite({"state": build(seed)}, core=core)
    bound, insulin_min = [], []
    t0 = time.perf_counter()
    for _ in range(minutes):
        sim.run(60.0)
        bound.append(float(np.asarray(sim.state["particle_totals"]["IR"]).sum()))
        insulin_min.append(float(np.asarray(sim.state["fields"]["I"]).min()))
    return bound, insulin_min, time.perf_counter() - t0


KD = KOFF / KON
TAU = 1.0 / (KON * IB + KOFF)
B_EQ = N_R * IB / (IB + KD)
print(f"Kd {KD / UM_PER_NM:.2f} nM, tau {TAU:.0f} s, equilibrium bound {B_EQ:.0f} of {N_R}")
demand = N_R * KON * IB                                               # molecules/s at t = 0
supply = D_INSULIN * (10.0 * 1.0) * IB / 10.0 * 1e-6 * 1e-15 * 6.02214076e23  # um2/s * um2 * uM / um -> molecules/s
print(f"Damkohler (binding demand / diffusive supply) ~ {demand:.2f} / {supply:.1f} = {demand / supply:.3f}")

bound, imin, wall = run(seed=1, minutes=60)
again, _, _ = run(seed=1, minutes=2)
print(f"repeatable with the same seed: {again == bound[:2]}; cost {wall / 3600 * 1e3:.2f} ms per simulated second")
for m in (1, 5, 10, 20, 30, 45, 60):
    t = 60.0 * m
    expected = B_EQ * (1 - math.exp(-t / TAU))
    sd = math.sqrt(max(expected * (1 - expected / N_R), 1.0))
    print(f"t {m:3d} min: bound {bound[m - 1]:6.0f}  well-mixed {expected:6.0f}  (z {(bound[m - 1] - expected) / sd:+.1f})"
          f"  min insulin {imin[m - 1] / IB:.3f} x blood")
