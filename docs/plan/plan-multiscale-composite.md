# Multi-scale composite: viva-pulse as the top scale

Status: scoping draft. No code in this repo changes under this plan.

## Context

Goal: one process-bigraph composite in which viva-pulse (patient, intervention, whole-body vitals) is the highest scale, and smaller-scale models sit beneath it and exchange data through ports and stores.

The scaling chain is not fixed. Organ → cell → molecule → atom → quantum is an example vector only. The investigation in Phase 0 chooses the chain. The first deliverable is proof of one or two links below Pulse. Reuse of processes, steps and composites from other `viva-*` repositories is a strong preference.

Evidence: three read-only research passes, plus direct reads of `vivarium-collective/viva-opencor` (`viva_opencor/processes.py:228-330`), `vivarium-collective/viva-human-atlas` (`docs/blood-circulation-simulation-plan.md`, `docs/superpowers/plans/2026-08-15-kidney-model-simulation.md`), and the installed process-bigraph 1.11.0 / bigraph-schema 1.8.3 sources. Anything not read from source is marked **unverified**.

## What Pulse exposes (verified)

**Down, Pulse → lower scale** (`viva_pulse/circuits/*.py`):
- Regional `pressure_mmHg`, `volume_mL`, `inflow`/`outflow` for 32 vascular regions under `central/`, `renal/`, `peripheral/`.
- 20 `hemodynamics/` scalars (MAP, cardiac output, blood volume, cerebral blood flow).
- `oxygenation/`: SpO2, PaO2, PaCO2, FiO2.
- `thermal/`: core and skin temperature, metabolic rate, compartment heat flow.
- Optional per-node and per-path reads through the points modules.

**Up, lower scale → Pulse** (setpoints only):
- 10 incremental `*_multiplier` ports (cardiovascular) and 10 respiratory multipliers.
- Hemorrhage severity at 16 sites.
- IV rate for one compound; thermal and oxygen setpoints.
- Multipliers are group-level, never per-path. Each send replaces the whole group.

**Not wired:** substance and tissue concentrations (issue #35) and lymph (#36). Glucose, lactate and drug concentrations are not available as boundary variables until those land.

**Time:** Pulse steps at 0.02 s internally. viva-pulse updates at 1.0 s by default. Thermal dynamics run over minutes. Pulse runs about 35× real time and is not bit-deterministic (about 4e-14 relative), so tests need tolerances.

**Gap below the organ is real:** Pulse's tissue model is "low-resolution, mid-fidelity", and energy is bulk glucose (`engine/docs/Methodology/TissueMethodology.md:9,13`; `EnergyMethodology.md:138`).

## Mechanics (process-bigraph 1.11.0)

- Unequal intervals are supported. The scheduler advances by the smallest time-to-next-event, using a heap when rates differ (`composite.py:3330-3446`, `:1341-1349`).
- A `Composite` is a `Process` subclass with `bridge.inputs/outputs` (`composite.py:1307`). Nesting uses `address: 'local:Composite'`; example at `processes/growth_division.py:99-117`. Each outer tick runs the inner composite for the outer interval.
- Stash model: a process reads inputs at the start of its interval, and its delta lands at the end. A slow reader therefore sees one-interval-old inputs. `run(T)` shorter than the largest interval is chunking-dependent.
- No built-in averaging or sampling across rates. Aggregation needs an explicit accumulator Step.
- When intervals sit on mixed decimal grids, time-precision rounding is disabled. Set `global_time_precision` explicitly.
- **Unverified on 1.11.0:** the `overwrite[float]` `initial_state` discard (documented in this repo's CLAUDE.md for 1.10); a native Pulse engine inside a nested Composite; whether `parallel_processes` is safe with the Pulse bridge.

## Reusable lower-scale parts (`vivarium-collective` on GitHub)

None of these are installed in the viva-pulse venv.

| Scale | Repository | What it provides | Read status |
|---|---|---|---|
| Organ/cell, CellML | `viva-opencor` | `OpenCORProcess` (input `state: maybe[map[float]]` overrides state each step; outputs `overwrite[map[float]]`), `OpenCORUTCStep`, steady-state Step. Variables keyed `component/variable`. | `processes.py:228-330` read |
| Organ/cell, SBML | `viva-copasi`, `viva-tellurium`, `viva-biomodels` | UTC Step/Process over any SBML; BioModels retrieval; multi-engine comparison | README only; Process ports **unverified** |
| Model catalog by organ | `viva-human-atlas` | `datasets/model_hra_map.json`: 2,554 models (1,096 BioModels, 480 PhysioNet, 978 Physiome) mapped to HRA organs | Docs read; code **unverified** |
| Circulation | `viva-human-atlas` `docs/blood-circulation-simulation-plan.md` | Planned `BloodTransportProcess` with a placeholder constant-output heart. Pulse could replace the heart with real hemodynamics. | Design doc read |
| Tissue/cell population | `viva-chaste`, `vivarium-tyssue` / `vivatyssue`, `viva-cpm` | Cell-based tissue mechanics | README only |
| Spatial/reaction-diffusion | `viva-smoldyn`, `viva-readdy`, `viva-vcell-fvsolver`, `viva-fenics`, `viva-pde-particle` | Subcellular stochastic and PDE solvers | Names only |
| Metabolism | `viva-cobra`, `viva-ketchup`, `viva-equilibrator` | FBA and kinetic metabolism | Names only |
| Molecular/atomic | `viva-lammps`, `viva-openmm`, `viva-martini`, `viva-caspule` | Molecular dynamics | Names only |
| Quantum | `viva-pennylane-*` | Quantum ML experiments, not physiology | Names only |
| Plumbing | `viva-torch` (neural surrogate of any Process/Composite), `viva-uq`, `viva-emitters`, `viva-basic-processes`, `viva-simularium` | Surrogates for time-scale gaps; uncertainty on coupled outputs | `viva-torch` README read |
| Not usable as physiology | `v2ecoli`, `viva-mgen`, `viva-oxidizeme` | Bacterial or *Mycoplasma* cells | Architecture patterns only |

Pattern to study first: `viva-membrane-actin-composite` and `viva-composite-nfsim-caspule` are existing two-wrapper closed-loop composites.

## Choosing the scaling chain

The chain is an output of Phase 0. Each candidate link is scored on four checkable criteria:

1. **Boundary observable exists** on the Pulse side (list above) and the lower model has a matching input.
2. **Runnable offline** through an existing viva-* wrapper, with no new simulator.
3. **Falsifiable response:** a Pulse intervention (for example hemorrhage severity 0 → 0.4) must change the lower-scale output in a direction the model's physiology predicts. The prediction is written down before the run.
4. **Usable time-scale ratio:** the outer interval is at or above the inner stiffness limit, or a surrogate is available.

Candidate first links (none committed):
- **Kidney (leading hypothesis).** Pulse renal pressures and flows are exposed. Hemorrhage lowers renal perfusion, a clear drive signal. Quasi-steady renal dynamics avoid a millisecond scheduling problem. `viva-human-atlas` already plans kidney runs. Open: which kidney model takes pressure or flow as input.
- **Heart → cardiomyocyte (time-scale stress test).** Aortic pressure and heart rate drive a CellML cell model through `OpenCORProcess`, with ms–s dynamics inside a 1 s outer tick. Open: whether the cell model has a defensible path back to the cardiovascular multipliers.
- **Metabolic (glucose, lactate).** Blocked until #35 lands. Next link, not first.

Second click down happens only after the first link passes: organ-level model → cell- or subcellular-level wrapper (`viva-opencor` cell model, `viva-copasi` pathway, or `viva-smoldyn`), using the same adapter pattern. Molecular, atomic and quantum scales are catalogued here, not planned.

Start one-way: Pulse drives, lower scale is observed. Two-way coupling is a later phase, because Pulse accepts only group multipliers, and every feedback loop is a modeling claim.

## Coupling contract (design)

- Pulse vitals stores hold absolute values (delta-seeded, `processes.py:149-156`), so lower-scale inputs can wire to them directly.
- One thin adapter `Step` per link does unit conversion (mmHg ↔ model units; mL/min ↔ model flow) and name mapping (`component/variable`). It computes no physiology, matching this repo's rule that modules compute nothing.
- Lower-scale outputs go to a store separate from its inputs. `OpenCORProcess` uses the name `state` for both input and output; wiring them to one store would write readings back as inputs. This is the same failure `test_stores_hold_only_their_own_ports` guards against in viva-pulse.
- Lower-scale composites are wrapped as `local:Composite` with explicit bridges, each at its own interval. Fast-to-slow links use an explicit accumulator Step. `global_time_precision` is set explicitly.
- Packaging: a new workspace repository (for example `viva-multiscale`) depends on viva-pulse as a library. OpenCOR and COPASI dependencies stay out of viva-pulse core, because viva-matrix pins viva-pulse without extras. Creating that repository is outward-facing and needs Alex's go-ahead at that step.

## Phases

**Phase 0 — probes.** Smallest real end-to-end runs, no mocks, in a scratch environment:
1. Install `viva-opencor` and `viva-copasi` on Python 3.12. The `libopencor` wheel on this platform is **unverified**.
2. Load one real kidney CellML/SBML model and one cardiomyocyte CellML model through `OpenCORProcess`; confirm variable names and input override behavior.
3. Test whether the `overwrite[float]` `initial_state` discard reproduces on process-bigraph 1.11.0.
4. Run a Pulse process and an `OpenCORProcess` in one Composite at different intervals; confirm the one-interval lag and chunking behavior.
5. Query Pulse renal compartments for non-NaN `Inflow`, `Volume` and `Pressure`, and probe tissue and substance requests (the #35/#36 question).
6. Query `datasets/model_hra_map.json` for kidney and heart models that are runnable and take a flow or pressure input.

Output: a short probe report and a filled scoring table. The chain decision comes from these.

**Phase 1 — first link, one-way.** Real Pulse process → adapter → chosen lower-scale process. Driver: hemorrhage-severity sweep. Prediction written first. Parallel zero-severity baseline.

**Phase 2 — second click down.** Same adapter pattern, one level further, only if Phase 1 passes. Add a `viva-torch` surrogate only if a measured run-time gap requires it.

**Phase 3 — optional closed loop.** Lower-scale output drives a Pulse setpoint, only where Phase 0 found a defensible mapping.

## Verification

- No mocks of the layers under test. Every test drives the real Pulse build and the real lower-scale engine.
- Invariance: with the adapter disconnected, Pulse readings match a standalone Pulse run within tolerance, and lower-scale readings match a standalone run of that model.
- Response: lower-scale output changes monotonically with hemorrhage severity in the pre-registered direction, and does not change at severity 0.
- Lag and chunking: tests pin the one-interval lag and `run(T)` versus repeated `run(dt)`.
- Name-collision guard: fails if a lower-scale output lands in an input store.
- `/adversarial` review of this document and of any code. Any physiological claim is checked by a modeler before it is stated as fact in a repository.
- Every claim in this document cites a file and line, or is marked unverified.

## Out of scope

Atomic and quantum coupling; changes to the Pulse engine; the substance and tissue wiring itself (#35, #36 stay separate); any claim that a lower-scale result is clinically valid.

## Biological decisions required

Estimates only. Every item is a modeling call. It needs a modeler's decision before any code depends on it. Each item lists the decision and what it blocks.

| # | Decision | Blocks | Estimate |
|---|---|---|---|
| B1 | Phase 1 scale: kidney (organ) or cardiomyocyte (cell) as the first link | Phase 0 scoring, Phase 1 | Organ-level link is the leading hypothesis; cell-level is the time-scale stress test |
| B2 | Which kidney model (Physiome/PMR or BioModels), and its species (human vs other) | Phase 0 probe 2, Phase 1 | Needs a human model with a pressure or flow input; none confirmed yet |
| B3 | Which Pulse output feeds the kidney model: renal artery pressure, glomerular capillary pressure, or renal flow | Adapter design | Unknown; the choice changes units and meaning |
| B4 | Whether renal output (for example GFR or sodium excretion) may feed back to Pulse, or stays one-way | Phase 3 scope | Assumed one-way for now; feedback is a modeling claim |
| B5 | Which cardiomyocyte model (species, ionic model) and whether aortic pressure or heart rate is the right driver, versus afterload | Phase 1 (if cell-level chosen) | Unknown |
| B6 | Whether a quasi-steady assumption holds for the kidney at a 1 s outer tick | Interval choice | Unknown; needs a timescale argument from the model |
| B7 | Expected direction and rough magnitude of renal response to hemorrhage (for example renal flow falls, GFR falls, sodium handling changes) | Pre-registered prediction for Phase 1 | Direction is standard physiology; magnitude needs a source |
| B8 | Hemorrhage severity range for the sweep (the 0 → 0.4 example is a placeholder, not a physiological choice) | Phase 1 sweep design | Placeholder only |
| B9 | Acceptance tolerance: what counts as "monotonic in the predicted direction" and "no change at severity 0" | Verification section | Needs an expert-chosen threshold |
| B10 | Phase 2 target: which subcellular or cell-level process comes after the first link (for example tubular transport, Ca²⁺ handling) | Phase 2 | Not chosen; depends on B1 |
| B11 | Whether a `viva-torch` surrogate stands in for a cell model, and what error is acceptable | Phase 2 | Validity call, not an engineering one |

## Critical files

- Read: `viva_pulse/processes.py`, `viva_pulse/circuits/{cardiovascular,thermal,points}.py`, `viva_pulse/composites/circuits.py`, `viva_pulse/core.py`, `docs/plan/plan-circuit-composites.md`
- Reference: `vivarium-collective/viva-opencor` (`viva_opencor/processes.py`), `vivarium-collective/viva-human-atlas` (`docs/blood-circulation-simulation-plan.md`)
