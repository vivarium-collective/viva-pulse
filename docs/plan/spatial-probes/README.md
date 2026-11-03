# Spatial probes (2026-11-03)

Jim Schaff's viva-pulse-independent hybrid (viva-pde-particle `7043882`: FV PDE fields + Smoldyn particles) on this Mac.
- **The fork:** virtualcell/Smoldyn `pyhybrid` (`9152dc2`) is shallow-cloned and compiled with cmake into the gitignored `.smoldyn-build/`. Options are those of Jim's `scripts/build_smoldyn.sh`, without pixi or ninja.
- **The install:** the fork and viva-pde-particle go additively into `.venv`, with a freeze kept for rollback.

Run from the repo root: `PYTHONPATH=$PWD uv run --no-sync python docs/plan/spatial-probes/<script>.py`.

## S1. Machinery (`probe_s1_machinery.py`)
viva-pde-particle's own `bimolecular_hybrid` example runs (2 simulated s in 0.1 s). It is identical with the same seed and differs with another.

## S2. One hepatocyte membrane patch (`probe_s2_one_cell.py`; physics provisional, mine)
- **Setup:** a 10 x 10 x 1 um patch of the space of Disse, blood on one face.
  - 8000 immobile receptor particles (1e5 per hepatocyte, scaled to the patch).
  - Insulin is a diffusing field (150 um2/s), held near Pulse's liver value (0.16 nM) at the blood face. The hold uses `external_conc` terms (`Ib`, mask `M`), the input a Pulse-driven step would write.
  - Binding uses Koschorreck 2008's own constants (Kd 0.4 nM, tau 1786 s).
- **Result over 1 h:**
  - Bound receptors track the well-mixed binding curve within about 2 SD (z ≥ −1.9). They lag by at most ~10% early and match at 60 min (1981 vs 1981).
  - The lowest insulin near the receptors is 0.95 x the blood value at 1 min and 0.99 x at 60 min.
  - Repeatable with a fixed seed. Cost: 10 ms per simulated second per patch.
- **Why:** the Damköhler number (binding demand over diffusive supply) is about 0.09, so binding is reaction-limited. Both demand and supply scale with insulin, so the number doesn't depend on the insulin level. It depends on receptor density, k_on, distance and diffusion. These receptors don't internalize insulin; Koschorreck's internalization (~2e-4 /s) would add only a small steady demand.
- **Consequence:** at this scale, a spatial binding layer reproduces the well-mixed receptor model. Moving binding into it would cost a lot and change almost nothing. Spatial matters where the Damköhler number nears 1: larger distances, slower diffusion, or denser or faster sinks.
