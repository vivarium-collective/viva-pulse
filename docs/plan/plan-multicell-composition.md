# Multiscale under Pulse: evidence and history

The design itself is in [the guide](../guide/guide-multiscale-design.md): one design, four dials. This file keeps the evidence behind it, the survey of lower-scale parts, the hazards, and how the earlier numbered designs map onto the dials.

Tags: **[V]** read at the source or measured; **[A]** read by an agent, not re-verified; **[U]** unverified.

## Pulse, the top scale [V]

- **Down (reads):**
  - 32 vascular regions of pressure, volume, inflow and outflow;
  - 20 hemodynamic scalars, blood gases and thermal values;
  - substance concentrations per compartment.
- **Liver specifics:**
  - Liver vascular insulin is live: 0.93 µg/L = 160 pmol/L, about 4× aortic, because the splanchnic compartment carries the pancreatic secretion. Glucose 6.05 mM and lactate 1.64 mM are live too.
  - Liver *tissue* insulin stays at its initial value (0.412 µg/L).
  - pH is reported only in blood compartments (liver vascular 7.33); tissue pH is NaN. Core temperature 37.03 °C.
  - No Mg, ATP, NAD, pyruvate or glucagon substances. Phosphate is fixed at 1.1 mM (`BloodChemistryModel.cpp:101`).
- **Insulin removal happens only at the vena cava.** `DrugModel::CalculateSubstanceClearance` applies systemic clearance there; insulin has no hepatic (intrinsic) clearance in `Insulin.json`. So Pulse's liver extracts no insulin.
- **Flows:**
  - A compartment's `Outflow`/`AverageOutflow` sums every outgoing link, including the links into tissue (`SEFluidCompartment::CalculateOutflow_mL_Per_s`), so it is not the flow into the next vessel.
  - Pulse cycle-averages flows only for the compartments `CardiovascularModel.cpp` registers.
  - True liver-inlet path flows: hepatic artery 393 mL/min, splanchnic 51.9 mL/min (`liver-probes/probe_pathavg.py`).
- **Up (writes):** only the existing setpoints: group multipliers, hemorrhage, IV rate, thermal, oxygen.
- **Time:** 0.02 s internal step and a 1 s update. Runs are not bit-deterministic (~4e-14).
- The StandardMale state is not settled for insulin or glucose: liver insulin drifts 0.93 → 1.13 µg/L in 120 s with no perturbation. Results need a baseline run.

## Coupling mechanics (process-bigraph 1.11) [V]

- Unequal intervals work. A process reads its inputs at the start of its interval, so a slower reader sees them one interval old.
- Several writers to one `float`/`map[float]` store add their updates; with `overwrite`, the last writer wins.
- Steps run after processes, once per tick.
- Process names and store names must not collide.
- There is no `Map` construct. An ensemble is a generator that emits one instance per stratum or region.

## Lower-scale parts

| Role | Repo | Status |
|---|---|---|
| SBML kinetics | `viva-copasi` (`CopasiUTCProcess`) | [V] In use. `species_counts` and `species_concentrations` both set *concentrations*; the output is a delta; `import COPASI` resets the process locale (contained in `viva_pulse/multiscale/cells.py`). |
| SBML kinetics | `viva-tellurium` | [V] Floating species only, so it can't see all-boundary models such as Koschorreck. |
| SBML kinetics | `viva-simbio`, `viva-pysces`, `viva-amici` | [A] Alternatives, not needed so far. |
| Cell model: receptor | Koschorreck 2008, BIOMD0000000345 (CC0) | [V] In use. Rat hepatocyte; seconds, nM; all species boundary with rate rules. |
| Cell model: metabolism | König hepatic glucose (`matthiaskoenig/glucose-liver`, kinetic file) | [V] Built (metabolism=True). SBML L3V1, 36 reactions with rate laws, seconds, mM; `glc_ext`/`lac_ext` boundary; `ins`/`gamma` are rules. No license, so it is fetched, not vendored. The BioModels copies (MODEL1204270001, MODEL1209260000) have no rate laws. |
| Thermodynamics | `viva-equilibrator` (`24da6a9`) | [V] Built on equilibrator-api directly (thermo=True); the wrapper's Step isn't used. Its reaction quotient is wrong for more than one product (`processes.py:239-244`); unwired inputs get silent defaults; pMg is never set. Installs additively. |
| Spatial | `viva-pde-particle` (Jim Schaff) | [V] Later. `FVReactionDiffusion` takes `external_conc`; `SmoldynHybrid` returns `particle_counts`; it needs the `virtualcell/Smoldyn` `pyhybrid` fork built from source. |
| Spatial | `viva-smoldyn` | [V] Excluded: `inputs()` returns `{}`. |
| Tissue mechanics | `vivarium-tyssue` | [V] Driven by behaviours only; no physiological port. Relevant only to the cell-agents end of Dial 2. |
| Surrogate | `viva-torch` | [A] Dial 4; not needed. |
| Coupling precedents | `viva-sbml-decomposition` (Tellurium + COPASI on one species store), `viva-genesis` (eQuilibrator as a rate gate), `viva-membrane-actin-composite`, `viva-pde-particle` | [A] |

Excluded [A]: microbial (`v2ecoli`, `viva-mgen`, `viva-comets` and others), atomistic MD (`viva-lammps`, `viva-openmm` and others), and simulators with no input port (`viva-vcell-fvsolver`, `viva-readdy` walls only).

## Hazards

- **Double counting:** while coupling is one-way, cells never change Pulse. Feedback (Dial 3) needs a ledger, approved by a modeler, saying which model owns each sink.
- **One writer per quantity:** inside a cell, two simulators never compute the same thing. When the spatial simulator owns binding, the receptor model must read it, not recompute it.
- **Units at every boundary:** Pulse reports pmol/L and mmol/L; Koschorreck uses nM; König uses mM (insulin in pmol/L); eQuilibrator expects M. A 1000× slip happened once (the Phase 0 smoke run).
- **Time scales:** receptors settle over 30–60 min; Pulse ticks every second. Cells start at steady state for their first drive.

## The earlier numbered designs, mapped to the dials

| Old name | Dial setting |
|---|---|
| Design 1, stratified tissue block | Coverage = liver; cell content = 1 simulator; one-way. Built. |
| Design 2, peer bus with a return path | Direction = feedback. |
| Design 3, per-region ensemble | Coverage = more organs. |
| Design 4, surrogate | Execution = surrogate. |
| Design 5, modular-cell populations | Cell content = cell agents (with mechanics), plus feedback. |
| "Offline replay" variant | Execution = replay. Built. |
| "Design 6", three-simulator cell | Cell content = 3 simulators. Next. |

## Liver, one-simulator cell: as built (2026-11-03)

Code: `viva_pulse/circuits/hepatic.py`, `viva_pulse/multiscale/`, `viva_pulse/composites/tissue.py`. Tests: `tests/test_hepatic.py`, `tests/test_tissue_block.py`. Probes: `docs/plan/liver-probes/`.

- **Driver:** liver vascular insulin, read as `Molarity` in pmol/L, so Pulse uses its own molar mass.
- **Strata:** a configured `extraction` E. `c(x) = mean (1 − E x)/(1 − E/2)` at the strata midpoints, so outlet/inlet = 1 − E and the mean is Pulse's value. The default E = 0 matches Pulse.
  - A first build derived E from portal `AverageOutflow`, which counts tissue links. It was about 5× too steep; the adversarial review caught it.
- **Bound:** `max_insulin_nM`, default 100, the highest level Koschorreck 2008 validates against.
- **Cells:** start at COPASI's steady state for their first drive.
  - Parameter overrides apply to fixed quantities only.
  - The drive is required.
  - Species are output, plus reaction fluxes and chosen quantities when asked (metabolism cells).
- **Amounts:** use the paper's hepatocyte, a 20 µm sphere (40 nM = 10⁵ receptors per cell) making up 78% of liver volume, at a density of 1051 g/L. That gives 3.19×10¹¹ cells in Pulse's 1.8 kg liver.
- **Checks:**
  - A synthetic insulin step raises binding only after the step.
  - A one-interval hold, checked against aligned and shifted standalone runs.
  - Pulse is unchanged with the cells attached.
  - Replay equals live.
  - COPASI costs 0.38 ms per instance-second.
