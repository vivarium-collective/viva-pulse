# Four ways to scaffold a multi-scale composite with viva-pulse on top

## Context

You asked for four different scaffoldings, each with viva-pulse as the highest scale, derived from the whole `vivarium-collective` org, including whether `vivarium-tyssue` fits. This replaces the earlier insulin-receptor plan; that chain survives as Design 1's first proof.

Evidence: three read-only passes over about 70 repos, an independent adversarial review (its findings are folded in below), and my own re-reads. Tags: **[V]** I read the source myself; **[A]** an agent read it, not re-verified; **[U]** unverified. A design's recommendation depends only on [V] facts; [A] facts that a design needs are listed as gates.

**Correction to my own earlier sweep:** I filtered the org listing on names starting `viva` or `pbg`, which hid about 35 repos. Added below: `mosaic-compose`, `meta-modelers-guide`, `rest-process`, `spatio-flux`, `spatial-transport`, `hra-model-access`, `glucostat`, `hypoxia-oscillations`, `CRM-FBA`, `cdFBA`, `multiscale-bioprocess`, `v2ecoli` and relatives.

## Shared ground truth

**Pulse (top scale)** [V, viva-pulse source and engine docs]
- Down: 32 vascular regions of pressure/volume/inflow/outflow, 20 hemodynamic scalars, blood gases, thermal values, and (local branch `feat/multiscale-substances`, `c405d16`) blood insulin and glucose in µg/L.
- Up: only existing setpoints: group multipliers (vascular, respiratory), hemorrhage, IV rate, thermal, oxygen. No per-path writes.
- Time: 0.02 s internal step, 1 s viva-pulse update, not bit-deterministic (~4e-14).
- **Correction on clearance:** Pulse computes *drug* clearance from per-substance rates (`DrugsMethodology.md:126-152`). Endogenous hormones are "cleared at a specified rate" and the insulin model is "under construction" (`EndocrineMethodology.md:10,46`). I had overstated this as "Pulse models hepatic and renal clearance itself". What holds: Pulse already owns whole-blood balances, so any lower-scale model that consumes a blood quantity must not also remove it from Pulse (see Double counting).

**Mechanics (process-bigraph 1.11.0)** [V]
- Unequal intervals work; a slower reader sees inputs one interval old (toy-process probe).
- `Composite` is a `Process` with `bridge.inputs/outputs`; nesting is `local:Composite`.
- Process keys and store keys must not share a name (my smoke run hit this).
- The `overwrite[float]` initial_state bug does not reproduce on 1.11.0.
- No averaging or sampling Step: `viva-basic-processes` has only `Clock` (integer step counter), `Tick` (time accumulator), `Intervention`, `MathExpression`, plotting; `viva-emitters` is analysis map-reduce [V file list and docstrings].
- **[U]:** deep-nesting lag; a `Map` of nested composites; `parallel_processes` with Pulse. (Pulse stays at the root, so "nested Pulse" is not the risk.)

**Interface principle from the org** (`meta-modelers-guide`, Agmon) [A]: declare each scale's interface as typed ports (a "draft process" contract) and give it **viability bounds**. A lower scale is valid only while its inputs stay in range. Each design below adds a check that fails loudly when a Pulse value leaves the lower model's bounds.

**Usable lower-scale parts**
| Tier | Repo | Drive point | Tag |
|---|---|---|---|
| SBML ODE | `viva-copasi` | `CopasiUTCProcess` input `species_counts` (`species_concentrations` is silently ignored); state continues; wire its own output store back as `species_concentrations` | [V]; unit meaning of `species_counts` [U] |
| SBML ODE | `viva-simbio` | `SimbioProcess` inputs `concentrations`, `parameters`; returns a delta | [V] |
| SBML ODE | `viva-pysces`, `viva-amici` | pysces `species` port; amici = CVODES, compiles C++ per model, the stiff-model fallback | [A] |
| SBML ODE | `viva-tellurium` | floating species only; blind to all-boundary models | [V] |
| CellML | `viva-opencor` | `state` override; rejects untyped CellML (Guyton 2008 fails) | [V] |
| Tissue mechanics | `vivarium-tyssue` + fork `vivatyssue` | `behaviors`; `update_parameter` adds a delta to any mesh column per cell uid; no physiological port; fork pinned, Python 3.12 | [V] |
| Cell population | `viva-chaste` (`spring_stiffness`), `viva-cpm` (`fates`), `viva-artistoo` (`temperature`, `target_volume`) | knobs only | [A] |
| Transport PDE | `viva-fenics` (`source`), `viva-pde-particle` (`external_conc`) | generic toolkits | [A] |
| Metabolism | `viva-cobra`, `cdFBA`, `CRM-FBA` | accept any SBML; shipped models are microbial | [A] |
| Plumbing | `viva-torch` (surrogate, fixed timestep, interpolates only), `viva-uq` (PCE/Sobol on any composite), `rest-process` (REST server for a process: remote or isolated lower scale) | [A] |
| Index | `viva-human-atlas` (2,554 models by organ; vasculature graph) | [A] |
| Pattern sources | `mosaic-compose` (planned, nothing wired: PKPD/whole-body compartments + GEMs + microbiome + ABM coupled through hormone homeostasis, gut/liver/vaginal), `meta-modelers-guide`, `viva-membrane-actin-composite`, `viva-composite-nfsim-caspule`, `viva-pde-particle` hybrid | [A] (mosaic-compose README [V]) |

**Excluded** [A]: bacterial or microbial (`v2ecoli`, `viva-mgen`, `viva-oxidizeme`, `viva-nfsim`, `viva-comets`, `viva-mcom`, `viva-ketchup`, `multiscale-bioprocess`, `spatio-flux`), atomistic MD (`viva-lammps`, `viva-openmm`, `viva-martini`, `viva-caspule`, `viva-lumenoid`), no input port (`viva-smoldyn`, `viva-vcell-fvsolver`, `viva-readdy`), abstract (`viva-dynamic-networks`, `viva-reactive-system`, `viva-pennylane-*`). **Unread** [U]: `glucostat`, `hypoxia-oscillations`, `spatial-transport`, `hra-model-access`, `viva-sbml-decomposition` internals, `viva-compiler`, `viva-expressions`, `viva-casebook`, `viva-genesis`, `viva-existential`, `viva-bbe-systems`.

## Hazards that apply to every design

- **Double counting.** If a lower-scale model consumes or produces a blood quantity that Pulse also balances, whose sink is it? Rule: while coupling is one-way, the lower scale never changes Pulse, so it is a *readout*, not feedback. A return path requires an explicit sink ledger agreed by a modeler. In Design 1's proof, receptor binding does **not** reduce Pulse's insulin; say so in the output.
- **All four designs start one-way.** Pulse accepts only multipliers, hemorrhage, IV, thermal, oxygen. No receptor-level quantity maps to any of them. Return paths are Design 2's reason to exist and a later phase elsewhere.
- **Units.** Pulse µg/L versus models in nM, molecules, or unitless SBML. The insulin conversion is a stated assumption until a modeler confirms it.
- **Time scale.** Pulse's insulin is a glucose-driven synthesis rate sampled every 1 s; SBML models may be stiff; a held input between slow updates aliases faster events. Choose hold vs interpolation explicitly; set `global_time_precision`; use `Clock` for every-N scheduling; an accumulator Step is new code, not an org utility.

## The four designs

### Design 1 — Stratified tissue block under Pulse (one-way, revised)
```
Pulse (root, 1 s)
  │  liver mean concentration, five inflows, tissue mass      one-way, downward
  ▼
TISSUE BLOCK (liver as the worked instance)
  N = tissue mass ÷ per-cell mass                     (anatomy, not the cell model)
  S strata in series, inlet → outlet, local c_s = c_Pulse × g_s
  constraint: volume-weighted mean of g_s = 1          (Pulse stays the authority for the mean)
  each stratum holds classes c (fractions f_c) × parameter sets q (weights w_q)
  output = N × Σ_s Σ_c f_c Σ_q w_q · y(s,c,q)  + spread diagnostics
Nothing flows back to Pulse.
```
- Overcomes "all cells alike" in two ways. Same blood conditions: a mean-preserving gradient across strata. Same behaviour: classes with fractions and per-class parameter spread.
- Pulse already exchanges blood with liver tissue (`SetupCircuitsAndCompartments.cpp:2563-2581`), so the block distributes Pulse's mean; it does not recompute depletion independently.
- The gradient shape and class fractions are modeler inputs [U]. The spread is an assumption, so it shows representability, not validation.
- Time: transport as a Step chain resolves within one tick [reviewer-read, re-read before coding]; transport↔kinetics keeps one interval of splitting lag, so mass balance holds to O(interval).
- Gates: tissue `TotalMass` [U]; the five inflow concentrations and link flows [U]; per-cell mass and exchange-flux definition [U]; simbio `parameters` and concentration handling [U]; runtime of S × C × Q solves [U].
- Fails when: the mean-consistency check fails, or the block's uptake disagrees with Pulse's own liver exchange, or runtime is prohibitive.

#### Design 1 as built (2026-11-03, branch `feat/multiscale`)
Code: `viva_pulse/circuits/hepatic.py`, `viva_pulse/multiscale/`, `viva_pulse/composites/tissue.py` (`pulse_liver_tissue`, `liver_tissue_replay`); tests `tests/test_hepatic.py`, `tests/test_tissue_block.py`.

| Gate | Result | Evidence |
|---|---|---|
| Tissue `TotalMass` | 1.8 kg, constant | live request `LiverTissue/TotalMass` |
| Five inflow concentrations and flows | Not used. Pulse's liver extracts no insulin: insulin is cleared at the vena cava (`DrugModel::CalculateSubstanceClearance`; no hepatic clearance in `Insulin.json`). A portal vessel's `AverageOutflow` also counts its flow into gut or spleen tissue (splanchnic 61.4 vs path 51.9 mL/min). True path flows put the inlet about 2.7% above the liver value, which is well-mixed lag while insulin rises, and 1 s means of them keep ±1% beat ripple. A first build used `AverageOutflow`, and the adversarial review caught it: its gradient was about 5x too steep. | engine source; path-flow probe at 0.02 s |
| Per-cell mass, exchange flux | Per-cell amount from the paper's geometry: 20 µm sphere, 40 nM = 10⁵ receptors per cell; hepatocytes 78% of liver volume; density 1051 g/L. Gives 3.19×10¹¹ cells. No exchange flux: one-way. | Koschorreck 2008 text and Table 1 |
| Cell-model parameters and concentrations | viva-copasi, not simbio. `species_counts` sets *concentrations* and wins when non-empty, so it is not a units question. Per-subpopulation parameters are set on fixed global quantities. | `viva_copasi/processes.py:853-856` |
| Runtime of S × C × Q solves | 0.38 ms per instance-second; not a gate | probe |

Corrections to the design above:
- **Driver.** The cells read Pulse's *vascular* liver insulin. Liver tissue insulin is frozen at its initial value in Pulse (0.412 µg/L), and whole-blood `BloodConcentration` (0.48 µg/L) is not what the liver sees (0.93 µg/L, portal).
- **Units.** Koschorreck 2008 is in seconds and nM. Pulse reports `Molarity` in pmol/L with its own molar mass. The Phase 0 smoke run fed pmol/L as nM, 1000× too high.
- **Gradient.** A configured hepatic `extraction` E: `c(x) = mean (1 − E x)/(1 − E/2)` at the strata midpoints, so outlet/inlet = 1 − E and the mean is Pulse's value. The default, E = 0, is uniform, which is what Pulse's own liver implies. Linear shape and E are provisional. Classes × parameter sets are one flat list of weighted subpopulations.
- **Viability bound.** A stratum above `max_insulin_nM` (default 100 nM, the highest level Koschorreck 2008 validates against) raises.
- **Uptake vs Pulse's liver exchange.** Not applicable: Pulse's liver exchange of insulin is zero by construction.
- **Output formula.** Strata carry a volume weight: output = N × Σ_s v_s Σ_p π_p y(s,p), with v_s = 1/S.
- **Start.** Cells start at COPASI's steady state for their first drive. From the file's insulin-free state they need 30–60 min to settle, longer than a typical run.
- **Next-step 1.** Done: the synthetic step control, the lag check against aligned and one-second-early standalone runs, and the stated passive readout (Pulse is unchanged with the block attached).
- **Open.** The biology (profile shape, a rat model for a human liver, subpopulation spread) is a modeler's call. StandardMale insulin drifts upward unperturbed (0.93 → 1.13 µg/L in 120 s), so a result needs a baseline run.

### Design 2 — Peer bus with a return path (two-way)
```
Pulse ──▶ blood bus (stores) ◀── organ / cell / tissue peers write exchange deltas
   ▲                                              │
   └──────── aggregator Step (sink ledger) ◀──────┘   → Pulse setpoints
```
- Differs from Design 1 in topology and in the return path: peers share stores, and an aggregator converts summed exchange into a Pulse setpoint. Precedents: `viva-human-atlas` blood-circulation plan, v2ecoli reactor↔cell coupler, membrane-actin `wiring.py` [A]; `mosaic-compose` frames the same idea as hormone homeostasis [V README].
- Gates: a modeler-approved sink ledger and a defensible mapping to a Pulse multiplier; per-leaf port schemas so a structured bus does not drop leaves [A].
- Fails when: the aggregator is a guess. It is the most scientifically loaded design.

### Design 3 — Per-region ensemble
```
Pulse region ──▶ Map{ region → lower-scale composite }     (organ index: compartment → UBERON → organ → models)
```
- One model instance per Pulse region or organ, via the `viva-human-atlas` index [A]; results aggregate by region.
- **tyssue's place:** a tissue instance for an epithelium (its `hra_colon_surface` and `hra_crypt_field` composites exist [A]). Pulse reaches it only through a hand-written adapter that emits `update_parameter` behaviors [V]. That mapping is unassessed, not "most speculative"; I have not read enough to rank it. Pulse has no colon compartment [U], and the fork pin is the only install evidence [V].
- Gates: the compartment→organ mapping (Pulse names are unmapped) [U]. The `Map` gate is resolved: process-bigraph 1.11 has no `Map` construct (no such class in the installed package, 2026-11-03), so an ensemble is a generator that emits one instance per region in a flat document. Design 1's `pulse_liver_tissue` already does this per stratum and subpopulation.
- Fails when: instance count makes cost prohibitive, or the region→tissue mapping has no physical basis.

### Design 4 — Surrogate-compressed
```
offline: lower model ──sampler──▶ dataset ──train──▶ viva-torch NeuralProcess
online:  Pulse ──drivers──▶ NeuralProcess (same timestep)  + periodic full-model spot check
```
- Compress a slow or stiff scale into a surrogate that rides Pulse's clock; the full model remains the reference.
- Gates: Pulse driver trajectories that cover the training range, which needs a perturbation (meal) not yet wired [V]; surrogate interpolates only and has a fixed timestep [A]; cost of the full model is unmeasured, so this is an answer to a problem not yet shown.
- Fails when: operating conditions leave the sampled range.

### Design 5 — Whole-body of modular eukaryotic cells (hybrid agent-based)
```
Pulse (root, 1 s) ──regional drivers──▶ cell populations per region (agent-based)
                                           each cell = composite of parts:
                                             tyssue      cell shape, tissue mechanics
                                             Smoldyn     molecule positions (sub-cellular)
                                             SBML        metabolism and signalling
                                           cells read and write a shared local environment
                                   ◀──aggregated per-region readouts── (rule to be defined)
```
- The scenario: Pulse supplies regional conditions (pressure, flow, gases, glucose, insulin, temperature). Each region hosts a population of modular eukaryotic cells built from the parts above. The cells' collective behaviour is read back as per-region quantities Pulse can use. This is Design 3's per-region structure with cells as the unit instead of organs, plus a sub-cellular layer.
- Parts and their status:
  - tyssue: cell shape and tissue mechanics [V]. It has no interior and no physiological port, so drive is by behaviours only [V].
  - Smoldyn: molecule positions. `viva-smoldyn` takes no inputs as written [A, subagent survey]. `viva-pde-particle` runs Smoldyn as a hybrid engine, which is the precedent for driving it [A].
  - SBML: metabolism and signalling via `viva-copasi`, `viva-simbio`, `viva-tellurium` [V for copasi and simbio inputs].
  - Environment: a shared field, from `viva-pde-particle` or `viva-fenics` [A].
- Gates:
  - Smoldyn wrapper with an input port, or a documented way to drive it from the hybrid [U].
  - Cell-to-cell and cell-to-environment interfaces, each a modelling decision.
  - An aggregation rule from cell state to per-region readouts. No org precedent [U].
  - Human parameters for every part. Many do not exist [U].
  - A population size, which is a large multiple of Design 3's instance count [U].
- Strengths:
  - The most faithful picture of the scenario, with mechanism at every scale below Pulse.
  - Each part is a separate, swappable composite, so parts can be validated one at a time.
- Weaknesses:
  - The most unvalidated layer of any design. Whole-body readouts constrain only the top, so several cell models could fit the same organ data.
  - The most expensive to run and the largest number of unresolved interfaces.
  - It would be a research programme, not a first proof.
- Fails when: any part cannot be parameterised for human cells, or the aggregation rule has no physical basis, or the population cost exceeds what the readouts need.

### Variant that applies to any design — offline replay
Run Pulse once, record the driver trajectory, and replay it into the lower scale. This removes Pulse and the nesting lag from the lower-scale development loop. For one-way coupling it is equivalent to Design 1's science at lower cost, so it is the cheapest way to *develop* any lower scale. It cannot test a return path.

## Comparison
| | Return path | Encapsulation | Time-scale handling | New code | Main gate |
|---|---|---|---|---|---|
| 1 Stratified tissue block | none | per stratum | one-tick Step chain, one-interval splitting lag | medium | tissue mass [U], inflow data [U], simbio parameters [U] |
| 2 Peer bus | yes (aggregator) | none | per-store intervals | medium | sink ledger, modeler-approved mapping |
| 3 Per-region ensemble | per instance | per instance | per instance | large | Map of composites [U], compartment mapping [U] |
| 4 Surrogate | none | black box | solved by surrogate | medium | training coverage, meal driver |
| 5 Modular-cell populations | yes (aggregation rule) | per cell, per part | per part, per region | very large | Smoldyn input port [A], aggregation rule [U], human parameters [U] |

## Recommendation

Begin with **Design 1 plus the replay variant**: it is the only design whose gating facts are all checkable now, and the replay variant lets the lower scale be developed without Pulse in the loop. The reason is risk, not that a flat smoke run already exists. Treat Design 2 as the next step *only after* a modeler approves a sink ledger, because it is the only design with feedback. Treat Design 3 (including tyssue) as an experiment gated on a `Map`-of-composites probe and a compartment mapping. Treat Design 4 as a response to a measured cost, not an assumed one. All biology mappings are a modeler's call.

## Next steps once approved (all local)
1. Make Design 1's first proof honest: a synthetic insulin step as a control, a lag check against a shifted standalone run, and a stated "passive readout" note in its output.
2. Probe the [U] gates: bridge wiring with a Pulse root, `Map` of nested composites, `species_counts` units.
3. Run the adversarial review of `feat/multiscale-substances` (required by the global rule).
4. Read the unread repos that a chosen design needs.

## Verification
Per design: a real-engine run with a pre-written directional prediction, a parity test (adapters disconnected equals standalone runs), and a viability-bounds check. `/adversarial` on the plan and any code. Every [A] fact a design needs is re-read before code is written.

## Critical files
- viva-pulse: `viva_pulse/processes.py`, `viva_pulse/circuits/{base,substances}.py`, `viva_pulse/composites/circuits.py`
- Local: branches `feat/multiscale-plan` (`66e3082`), `feat/multiscale-substances` (`c405d16`); smoke run `scratchpad/phase0/smoke/smoke_run.py`
- Org: `viva-copasi` `viva_copasi/processes.py`, `viva-simbio` `viva_simbio/processes.py`, `vivarium-tyssue` `vivarium_tyssue/{processes/eulersolver.py,data_types.py}`, `viva-human-atlas` `docs/blood-circulation-simulation-plan.md`, `mosaic-compose` README, `meta-modelers-guide` README
