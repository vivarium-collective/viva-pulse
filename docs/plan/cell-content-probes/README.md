# Cell-content probes (2026-11-03)

Probes for the three-simulator cell (see `docs/guide/guide-multiscale-design.md`).
Run from the repo root:

```bash
PULSE_INSTALL_DIR=<repo>/.pulse-build/install PYTHONPATH=$PWD uv run --no-sync python docs/plan/cell-content-probes/<script>.py
```

König's model is fetched at a pinned commit by `viva_pulse.multiscale.models.koenig_2014()`.

## A. Loading (`probe_a_load.py`)
- 50/50 loads in fresh interpreters and 20/20 in one interpreter succeeded. The import aborts another repo saw (about 1 in 5) don't occur with this model.
- 36 reactions. Compartments: extern 10 L, cytosol 1 L, mitochondria 0.2 L. Cofactors (ATP/ADP/AMP, NAD(H), phosphate, H+, H2O, CO2, and their mitochondrial copies) are fixed boundary species.
- `ins`, `glu` and `epi` (pmol/L) are assignment rules on external glucose. `gamma` (the phosphorylation state that regulates GS, GP, PFK2, FBP2, PK and PDH) is an assignment on them.

## B. Driving (`probe_b_drive.py`)
- **Insulin is driven by switching `ins` to fixed, then setting its value**, as two separate `set_parameters` calls. In one call, COPASI keeps the rule's current value. Per tick, `setInitialValue` + `updateInitialValues` works.
- König's own insulin curve gives 152 pmol/L at Pulse's liver glucose (6.05 mM); Pulse's liver blood carries 160 pmol/L.
- **Steady state at Pulse's values exists** (basico status 1), with glycogen at 486 mM. From the file state, glycogen moves only 250 → 269 mM in an hour, so cells must start at steady state.
- **Directions** (pre-registered for the tests):
  - `gamma` falls as insulin rises (0.498, 0.304, 0.220, 0.153 at 9.7, 80, 160, 320 pmol/L);
  - steady glycogen rises with glucose (117 mM at 4 mM glucose, 494 mM at 8 mM);
  - the GAPDH flux turns from gluconeogenic (−0.021 at 4 mM, −0.017 at 6.05 mM) to glycolytic (+0.0006 at 8 mM).
- Cost: 1.07 ms per 1 s update.
- To check against the paper: cytosolic lactate settles at 2.4e-6 mM with external lactate at 1.64 mM.

## C. Thermodynamics (`probe_c_thermo.py`)
- Formulas are built from the model's own KEGG annotations. Two annotation slips are corrected (`h2o_mito` was H+ and becomes C00001; `h_mito` was CO2 and becomes C00080), and water is added to FBP2, EN and PC, which omit it.
- **27 of 36 reactions are scored. 9 are excluded:** 4 transporters (GLUT2, LACT, PYRTM, PEPTM), glycogen synthesis and breakdown (a polymer), and 3 boundary exchange fluxes.
- All of them score in 0.13 s, using eQuilibrator's bundled data only (tier `bundled`, never escalated). The `auto` tier would silently use a full 1.3 GB database when one exists on the machine.
- **Second-law conflicts at König's steady state under Pulse's liver values:** net flux runs against ΔG′ (beyond 2σ of ΔG′°) in ALD, TPI, PGK, EN, PEPCKM and LDH. The conflicts don't hinge on the assumed cell conditions: ALD, PGK, EN, PEPCKM and LDH conflict in all 18 combinations of pH 7.0–7.4, pMg 2–4 and I 0.15–0.25 M, and TPI in 15.
- **König's equilibrium constants vs eQuilibrator's K′ (1 M standard):**
  - **Close (within about 2×):** GPI, G16PI, PGM and TPI.
  - **Far:**
    - LDH (ratio 3×10⁻⁸; it matches eQuilibrator's constant for the *reverse* direction);
    - PEPCK (5.5×10⁴);
    - PGK (0.004);
    - EN (0.013; `EN_keq` equals `TPI_keq` to every digit).
  - **ALD** matches numerically in M (0.81), but the model works in mM and ALD's constant carries a concentration unit, so the model's effective equilibrium sits 1000× away.
- **Hypotheses for a modeler, not facts:** a copy slip (EN), a reversed constant (LDH, consistent with cytosolic lactate at 2.4e-6 mM), and unit slips (ALD, PEPCK). This is the thermodynamic layer earning its place: it finds where the kinetic model breaks the second law under Pulse's conditions.
