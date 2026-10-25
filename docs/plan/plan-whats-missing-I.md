# Plan: circuit-level access, what's missing, and the pending upstream fixes

**Status:** scoped 2026-10-23. Run 2026-10-24 as Task 3b of the root
`agenda.md`, limited by the user to work in viva-pulse and the
vivarium-collective repos (no Kitware Pulse work).
- **Phase 1:** done; see [`plan-circuit-level-access.md`](plan-circuit-level-access.md).
- **Phase 2:** done for the vivarium-collective drafts. All still apply on each repo's current `main`, and none is filed. `pulse.md` was not re-checked.
- **Phase 3:** done; the candidates are in the root agenda.

The sections below are the 2026-10-23 snapshot. Since then:
- the CI plan has become PR #7, green, and on hold until Nov 1;
- the protobuf pin is tightened on that branch.

## Context

The user asked three questions:

1. Does wrapping Pulse through its Python bindings lose functionality? The
   bindings read "regions (compartments), not circuit nodes or paths".
2. What is still missing from viva-pulse?
3. Which fixes from earlier sessions still have to go to other repos, and to
   which repos?

Q1 is the open item 7 of the `post-initial-wrapping` agenda: "Read individual
points like LH1", rewiring, separate circuits, instant new patients.

Everything below was checked against source or a live probe on 2026-10-23:
engine `5e29e5b13`, `.venv`.

## Q1. Are we losing functionality? Yes, in four specific ways. The quoted constraint is only partly true.

**Correction to the premise (live probe).** The Python data-request API
reaches compartments only. `eDataRequest_Category`
(`../engine/src/cpp/cdm/engine/SEDataRequest.h:10-14`) has no circuit
category.

However, `PulseEngine.serialize_to_string(json)` returns the full engine state.
Its `CircuitManager` holds every circuit node and path, with live values:

- Counts: 194 fluid nodes, 323 fluid paths and 17 fluid circuits, plus 10
  thermal nodes and 16 thermal paths.
- Probe:
  - after 1 s, node `Aorta1` P = 88.6078 mmHg, exactly the `Aorta`
    compartment request;
  - 0.37 s later it reads 102.04, so the values are live;
  - `LeftHeart1/2/3` are present;
  - path `Aorta1ToBone1` reports flow 4.16 mL/s and R 13.57.
- Cost: 2.5 MB and about 32 ms per call (serialize plus parse). That is fine
  at a 1 s interval, but about 50x the step cost at a 0.02 s waveform
  interval.
- Caveat: proto3 JSON leaves out zero values (`Aorta4` has no Pressure
  `Value`). A reader must tell "zero" apart from "not set", and that is
  unresolved.

**What is actually lost:**

| Capability | From Python today | Evidence |
|---|---|---|
| Node and path **reads** | Only through full-state serialization; there is no per-node data request | above |
| Per-path **writes** (one resistance or compliance) | No. Only the 10 cardiovascular and 10 respiratory modifier multipliers, which scale groups | `viva_pulse/circuits/cardiovascular.py`, `respiratory.py` |
| **Topology** changes (adding or removing a branch) | No API. A possible route: `PBState.cpp:164-173` rebuilds the circuits from the state's `CircuitManager`, so loading an edited state may work. Not probed; the models cache named nodes and paths | `../engine/src/cpp/engine/io/protobuf/PBState.cpp` |
| **Truly separate circuits** | Respiratory yes (`ventilation_mechanics`). Cardiovascular no: Hemodynamics segfaults, and pybind has no enum value for it (`PyPulse.cpp:55-58`) | upstream drafts Pulse #1, #2 |
| The circuit solver on its own (`SEFluidCircuitCalculator`), `GetCircuits()` | C++ only, with no binding | `PyPulse.cpp` binds only the engine thunk |

**Recommended direction (for agenda item 7):**

1. Read nodes and paths via `serialize_to_string`, as an opt-in module with a
   coarse interval. This is ecosystem-native: it uses Pulse's own public API.
2. Probe value edits through an edited-state reload before designing
   anything.
3. Build a pybind extension in `../engine` (branch `viva-wrapper`) only if
   (1) and (2) fall short. It means maintaining a fork.

## Q2. What is missing from viva-pulse

**Agenda items still open (`post-initial-wrapping`):**

- Nice-to-have 3: there are no new closed-loop controllers;
  `MapFluidController` is the only one.
- Nice-to-have 4: there is no coupling to other process-bigraph models.
- Nice-to-have 6: isolated vs coupled runs exist only for respiratory.
  Cardiovascular is blocked on Hemodynamics.
- Nice-to-have 7: the scoping, which is Q1 plus new-patient stabilization
  time (unmeasured).
- Out of scope by decision: ECMO, bag-valve mask, inhaler, anesthesia machine,
  and the Hemodynamics fix.

**Pulse coverage gaps (counted from source):** Pulse ships 45 patient-action
classes (`pulse/cdm/patient_actions.py`).

- **Wired.** The patient actions are hemorrhage, compound infusion, the
  cardiovascular and respiratory modifiers, intubation and supplemental O2.
  The wrapper also drives the ventilator, the environment and thermal
  application.
- **Not wired:**
  - drugs (`SESubstanceBolus`, `SESubstanceInfusion`), so there are no
    substance or tissue concentration outputs;
  - pathologies: tension pneumothorax, ARDS, asthma, COPD, arrhythmia, brain
    injury, burns and airway obstruction;
  - CPR and exercise;
  - chronic conditions, which need a stabilization run;
  - events (`pull_active_events` is unused);
  - ECG.

**Infrastructure and process:**

- CI is red because the runners have no Pulse. The CI plan
  [`plan-ci-pulse-build.md`](plan-ci-pulse-build.md) is not started; it is
  waiting on the user.
- The release image has no Pulse.
- The RTD real-engine tutorials are planned in
  [`plan-rtd-real-engine-docs.md`](plan-rtd-real-engine-docs.md). That plan
  was written by a subagent and is unverified.
- `CONTRIBUTING.md` and `.github/workflows/release.yml` are still open, and
  the protobuf pin has not been tightened.
- **Rigor.** `/viva-harden-investigation` was abandoned with three untriaged
  gaps, recorded in `CURRENT.md`:
  - the baroreflex causal claim has no ablation;
  - saline vs blood is not root-caused;
  - the severity threshold rests on a single sample.
- One test failed once and was never reproduced:
  `tests/test_whole_body.py::test_combined_readings_equal_the_single_module_composites`.
- The repo transfer to `vivarium-collective` is done. A step-6 PR is pending
  in the "migrate-repo-org" session; that work is not part of this plan.

## Q3. Pending fixes for other repos (all drafted, none filed)

The drafts are in `upstream-issues/`, which git excludes. The user files them;
Claude never does. `gh issue list --author AlexPatrie` shows none filed.

Upstream state since drafting:

- process-bigraph (1.10.0), bigraph-schema (1.8.2) and viva-superpowers
  (0.24.0) have no newer PyPI release.
- vivarium-workbench `main` has moved `aa2b7d2b` -> `1cfcbbe7`, so its drafts
  must be re-checked before filing.

| Repo (tracker) | # | Issues |
|---|---|---|
| Kitware Pulse (gitlab.kitware.com/physiology/engine) | 7 | The Hemodynamics engine segfaults (null ECG). `PulseEngine` silently falls back to WholeBody. `process_action(s)` drops the success flag. Python can't extubate. A pressure-control Off action is rejected. A missing substance directory segfaults. `External_protobuf.cmake:88` is dead. Also ask them to merge `175f0dfe7` (`keep_event_changes`). |
| bigraph-schema | 4 | A: type defaults outrank `initial_state()` on `overwrite`/`boolean` ports. B: projection leaks undeclared keys. D: a list config is concatenated onto its default. E: an explicit 0, 0.0 or '' config value is replaced by the default. |
| process-bigraph | 1 | C: a plain `Composite` has no `global_time_precision` default (a follow-up to #222/#227). |
| viva-superpowers | 2 + 6 | `workspace_catalog.add` reads `package`, not `package_path`. The in-place scaffold drops the `requires-python` floor. Plus the 6 skill/doc mismatches listed at the end of `vivarium-workbench.md`. |
| vivarium-workbench | 6 | Observables are checked on the raw document. Auto-evaluation grades every test against every run. Rows carry an empty `agents.0` mirror. `_run_labels` is never delivered. Variant manifests lack the package version. The gate ignores pytest results. |

## Phases

### Phase 1: circuit-level access scope doc

Write `docs/plan/plan-circuit-level-access.md` and update item 7 of the
`post-initial-wrapping` agenda. Run each probe before the doc states its
result:

- **P-a: node and path reads via serialization.** Settle zero vs unset by
  comparing against compartment requests on nodes at zero pressure.
- **P-b: edit one path's resistance.** Change it in the state JSON, reload, and
  check for an effect (for example an HR/CO shift) against an unedited run.
- **P-c: add one path.** Add it in the state JSON, reload, and check whether it
  is solved.
- **P-d: new-patient stabilization.** Time `initialize_engine` for a patient
  that doesn't ship with Pulse.
- **P-e: separate cardiovascular circuit.** Confirm that its route is Pulse
  fixes #1 and #2.

### Phase 2: upstream readiness

- Re-run `repro_bigraph_schema.py` and `repro_process_bigraph.py`.
- Re-check the six workbench drafts against `1cfcbbe7`, and update line
  references that moved.
- Report which drafts are ready to file. Do not file any.

### Phase 3: missing-work list

Add the Q2 coverage gaps to the `post-initial-wrapping` agenda as candidate
items for the user to prioritize. Implement none of them.

## Constraints

- Commit only this session's files. Leave alone `docs/guide/`, `CURRENT.md`
  changes made by other sessions, and `workspace/reports/index.html`, unless
  they are ours.
- Use `uv run --no-sync`.
- No releases without asking first.
- Run an adversarial review of the scope doc before calling it done.

## Verification

- Probes P-a to P-e run against the real engine. Their scripts and outputs go
  in the scratchpad, and the doc quotes their numbers.
- The repro output matches the output recorded in the drafts.
- Each workbench draft's cited lines are re-read at `1cfcbbe7`.
- `/adversarial` on the scope doc.
