## Current Session

Goal: `/viva-expert ./` (run from `~/uchc/twin/engine`) — heavy single-tool
mode, REAL bridge to the Kitware Pulse Physiology Engine. Wrapper repo is
this directory (user-chosen). Build pins, phase ledger, probe results and
workarounds: [.build-progress.md](.build-progress.md) — read it first.

**Active agenda:** `agenda.md` (repo root, name `post-initial-wrapping`), swapped in on
2026-10-23. The completed `circuit-composites` agenda is archived at
`docs/agenda/circuit-composites/agenda.md`. Both are git-excluded (the `agenda.md`
line in `.git/info/exclude` matches every `agenda.md`).

**Standing user instructions (2026-10-22):**
- **Releases need an explicit go-ahead each time** (user, 2026-10-23: "wait for my
  explicit go ahead on a release after asking me"). Ask, then wait; don't watch
  image builds unless asked. Merge permission "when ready and safe" (2026-10-23)
  still covers merges. Anything else still needs asking. Never
  push to `main` directly, **except Phase 5**: the user said to "commit and do all
  the full phase 5 work directly on main" (2026-10-23). The tag and GitHub Release
  still follow.
- Ignore the concurrent gnn session (user, 2026-10-23). The untracked
  `docs/guide/` in this repo is not this session's: leave it out of commits.
- Keep README.md current with every user-visible change.
- Never `uv sync`; always `uv run --no-sync`.
- `../engine` is a separate repo: on branch `viva-wrapper`, with untracked
  `.skills/` and `CLAUDE.md` that this session did not create. Untouched
  this session; ask before committing there.
- Keep `agenda.md` up to date (user, 2026-10-23): progress per phase,
  `last-addressed`, `status`, and the constraints below.

**Decisions (user, 2026-10-23, via `/open-question`):**
- The Hemodynamics engine fix is out of scope for the agenda; it stays an
  optional follow-up.
- Upstream issues are drafted, never filed by Claude, in `upstream-issues/`
  at the repo root, kept out of git via `.git/info/exclude`.
- The CI plan is implemented after Phase 5, in its own PR, **but not until the user asks** (2026-10-23), with both open
  choices taken: tighten the pin to `protobuf>=7.35,<7.36`, and replace
  `workspace-ci.yml` with the Pulse-building workflow.

### Session 2026-11-01: issues #35 and #36 (branch `feat/substances-and-lymph`)

- **User request (2026-11-01):** address #35 (substance and tissue outputs) and #36 (lymph) on one new branch, one PR, following the repo's planning, documentation and validation protocol. Plan: [docs/plan/plan-substances-and-lymph.md](docs/plan/plan-substances-and-lymph.md), approved with D1a-D6a.
- **Engine for this session:** the Mac's shell was a small Linux VM that can't run the macOS build, so Pulse `5e29e5b13` was built on Linux x86_64 in a cloud workspace (see `.build-progress.md`, "Linux build (2026-11-01)"). All probes and tests ran there. **Before the PR, the full suite must pass on the Mac** (`uv run --no-sync pytest -q -rs`); record the count and skips in the plan's section 9. Linux result: 373 passed, 1 allowlisted skip (baseline 316 + 1).
- **Findings that change the issues:** Pulse 4.4.0 has no active lymph (zero flow sources, inherited from BioGears' 2017 code); several Pulse substance requests segfault or create substances (plan section 2).
- **Done on the branch:** `Request.substance` and two categories; modules `substances` and `tissues`; generator parameters `substance_outputs` / `tissue_outputs`; `tests/test_substances.py`, `tests/test_lymph.py`; docs (README, `documentation/concepts/circuits.md`, API page, `CLAUDE.md`); probe and `_runs.yaml` entry; upstream note `upstream-issues/pulse.md` (drafted, not filed); a reply to #36 drafted for the user.
- **Next (user, 2026-11-01):** after this branch, a scoping plan for `viva-biogears` (draft written 2026-11-01, kept outside this repo: `~/projects/biogears/core/Claude outputs/plan-viva-biogears.md`), a Python API for BioGears 8.x (a separate repo; recommended as its own `pybiogears` package built against an installed BioGears).
- Not pushed; no PR opened. Ask before pushing.

### State (2026-10-23, after release)

- **Released v0.2.0.**
  - PR #1 merged as `edf9745`, with merge permission granted by the user on
    2026-10-23.
  - Annotated tag `v0.2.0` on `edf9745`, plus a GitHub Release.
  - The merged `main` was re-verified locally before tagging: 61 passed,
    1 skipped; workspace lint OK.
- **PR #2 merged as `8d7ed88`:** [docs/plan/plan-ci-pulse-build.md](docs/plan/plan-ci-pulse-build.md),
  the scoped plan for building Pulse in CI. Both of its decisions are taken
  (see Decisions above); it's implemented after Phase 5.
- **v0.2.1 released (`55e9762`, PR #3):** `requires-python` is now `>=3.11`.
  The v0.2.0 image build failed because `bigraph-viz>=2.0.3`, added by the
  scaffold, needs Python >= 3.11, so `uv sync`/`uv lock` could not resolve.
  Regression test: `tests/test_packaging.py` runs `uv lock` on a copy of the
  project; verified to fail with `>=3.10`. Local suite: 62 passed, 1 skipped.
- **Branches:** only `main`; merged branches are deleted locally and on the
  remote.
- **Remote:** `origin` = private GitHub repo. `eagmon` has a pending invitation
  with write access.
- **CI is red, as accepted.**
  - `workspace-ci`: every gate passes except the tests (as of v0.3.0: 43 fail,
    all with `PulseNotFoundError`; 50 pass).
  - The Pages workflows run on manual trigger only (`772fa2a`).
  - Tags trigger the template `build-and-push.yml`. It builds a Python 3.13
    workbench image with **no Pulse**, which can't run Pulse composites (see the
    CI plan).
    - v0.2.0: failed at dependency resolution (fixed in v0.2.1).
    - v0.2.1: succeeded.
    - v0.3.0: succeeded (run 39903606704). Check later builds with
      `gh run list --workflow build-and-push.yml`.

### Phase 5 released (2026-10-23): v0.5.0, the agenda is complete

- **Built** (now committed as `9adeca1`).
  - `circuits/supplemental_oxygen.py`.
  - `CircuitModule.airway_device`; the ventilator declares `connected`.
  - `PulseCircuitProcess._check_airway`.
  - Generators `pulse_supplemental_oxygen` and `pulse_whole_body_circuits` (`WHOLE_BODY_MODULES`).
  - `tests/test_whole_body.py` (24 tests).
  - Version 0.5.0.
- **Verified.**
  - Probe P9 (`.build-progress.md`).
  - Suite: 148 passed, 1 skipped (224 s).
  - Lint OK.
  - Mutants P1-P11 all caught: device, flow, finite tank, disconnect, airway check, swap rule, ventilator undeclared, build-time check, a module dropped, PaO2 unit, slot mapping.
- **Docs updated.** README (verified whole-body example), CLAUDE.md, plan Phase 5 notes, `.build-progress.md`. The user's own README edits ("Regarding..." restructure, electrical-circuit analogy) ride along.
- **Adversarial review skipped** at the user's request ("let's just get this agenda finished", 2026-10-23); the review subagent was stopped.
- **Released.**
  - Commit `9adeca1` on `main`, pushed.
  - Annotated tag `v0.5.0` and a GitHub Release (created before the user's new release rule).
  - The image build was not checked: the user said to stop following releases.
- **The agenda `circuit-composites` is complete** (`agenda.md` status: complete).

### Phase 3 released (2026-10-23): v0.4.0 (thermal)

- **Built.**
  - `circuits/thermal.py`: the `thermal` module, whole_body only, 44 outputs.
    Setpoint groups: `environment` (6 setpoints, including the breathed-air
    temperature) and `thermal_application` (7).
  - `Request` gained the `environment` and `thermal_compartment` categories.
  - `CircuitModule.check_loaded`: a state with a non-Standard environment fails the load.
  - Shared `validate_switch` in `base.py`.
  - `pulse_thermal` generator (with `model_type`).
  - `tests/test_thermal.py` (31 tests).
  - `docs/images/circuit-environment.png`.
  - Version 0.4.0.
- **Verified.**
  - Thermal tests: 31 passed (66 s).
  - Full suite: 124 passed, 1 skipped (165 s).
  - Lint OK.
  - Mutants M1-M9 plus the reviewer's R1-R9: all caught.
- **Adversarial review done.** Nine findings, all fixed; the plan's Phase 3 notes list them.
- **Released.**
  - Commit `bdc8e3e`, PR #5, merged as `4ae29e4`; the branch is deleted.
  - The merged `main` was re-verified locally: 124 passed, 1 skipped; lint OK.
  - Annotated tag `v0.4.0` and a GitHub Release.
  - Image build `39917947030` succeeded.
  - PR CI: every gate passes except the tests (51 failed plus 4 errors, all `PulseNotFoundError`; 69 passed).

### Phase 2 released (2026-10-23): v0.3.0

- **Built.** `circuits/respiratory.py` (modules `respiratory` and
  `mechanical_ventilator`, both on both engines); the ventilation-mechanics
  start-up in `PulseCircuitProcess` (`_initialize_engine` with the data root,
  then `_settle`); `ActionBinding.check_transition`; the generators
  `pulse_respiratory` and `pulse_mechanical_ventilation`; the shared
  `_setpoints` helper; `tests/test_respiratory.py`; version 0.3.0.
- **Tests.** Suite: 93 passed, 1 skipped (~100 s); lint OK. Mutation checks:
  the disconnect test fails on a bare pressure-control Off action; the settle
  test fails without `_settle`.
- **Docs updated:** README (respiratory example verified), CLAUDE.md, the
  plan's Phase 2 notes plus methodology follow-ups plus the CDM-types verdict,
  `.build-progress.md` (P6/P7, including the corrected disconnect finding).
- **Adversarial review done (2026-10-23):** no blockers, nine findings, all fixed
  (see the plan's Phase 2 notes). It also turned up a Pulse behavior: AssistedControl
  above the spontaneous rate can auto-trigger at about 50 bpm.
- **Released.** PR #4 (commit `f56d6ae`, merge `d4608ea`), annotated tag `v0.3.0`, GitHub
  Release. The merged `main` was re-verified locally: 93 passed, 1 skipped; lint OK. PR CI:
  every gate passes except the tests (43 fail, all `PulseNotFoundError`).
- **Research reports received** (summarized in the plan doc):
  - Methodology review: follow-ups listed in the plan.
  - CDM types: recommend not registering them. Optionally annotate ports with
    `float[unit]` later; that claim is not re-verified.

### Phase 1 design (as built; details in `CLAUDE.md` Architecture)

- `PulseCircuitProcess` (`viva_pulse/processes.py`):
  - one real engine (`SUPPORTED_MODEL_TYPES`: `whole_body`, plus `ventilation_mechanics` since Phase 2);
  - `config.modules` (default `[]`, empty raises) selects
    `viva_pulse.circuits.MODULES`;
  - outputs nest per module as `float` deltas, plus `irreversible_state`;
  - inputs sit under the single port `setpoints/<module>/...` as
    `overwrite[float]`, each with `_default` = baseline;
  - deduped requests; act-on-change actions; a NaN guard fails the load and
    names the unserved request;
  - shares `_load_engine()` with `PulseProcess`, whose ports and config are
    unchanged.
- `circuits/cardiovascular.py` has 146 outputs:
  - 20 `SECardiovascularSystem` scalars under `hemodynamics/`;
  - Pressure/Volume/Inflow/Outflow for 32 compartments under `central/` (10),
    `renal/` (8) and `peripheral/` (14), minus Pericardium flows.
  - Setpoints: 10 multipliers sent as one `SECardiovascularMechanicsModification`
    with `incremental=True` and the full group resent; plus `hemorrhage_severity`
    with config `hemorrhage_compartment`.
- `composites/circuits.py`: `circuit_node()`, `circuit_emitter()` and
  `@composite_generator pulse_cardiovascular`. Stores: `interventions/<module>`,
  `circuits/<module>`, `circuits/irreversible_state`, `emitter`.

### Bugs found and fixed this session (each is non-obvious)

1. **Spelling:** Pulse's compartment flow properties are `Inflow`/`Outflow`. An
   Explore subagent's `InFlow` returned NaN for every compartment. Found by
   probe P3, then read in `SEDataRequestTracker.cpp`.
2. **Store leak:** process-bigraph projects `initial_state()` through **input**
   wires as well as output wires. When the input and output ports shared the
   module name, readings leaked into `interventions/cardiovascular`.
   - Fix: a disjoint `setpoints` input namespace; `RESERVED_NAMES` in
     `circuits/base.py`.
   - Regression test: `test_stores_hold_only_their_own_ports`, verified to fail
     on a scratch reconstruction of the old design.
3. **Test arithmetic:** my compartment count was off (31 vs the real 32).

### Verified engine facts used by Phase 1 (also in `.build-progress.md`)

- Measured effects at 60 s from baseline:
  - systemic resistance x2: HR 72 -> 43, CO 5.78 -> 4.00 L/min, MAP 95.3 -> 97.1
    (the baroreflex defends MAP);
  - x0.5: HR 113, CO 8.11;
  - arterial resistance x2: no measurable change;
  - HR multiplier 1.3: HR 85.7.
- Baseline drift over 60 s: MAP 95.25 -> 95.26.
- Hemorrhage, RightLeg 0.8, 120 s: BV deficit 355 mL vs 360 mL reported lost;
  RightLeg volume 215.5 -> 146.1 mL; HR only +2.6 bpm by then.
- Compartment values are instantaneous within each heartbeat; 1 s sampling
  aliases them, and `interval=0.02` resolves waveforms.
- Non-incremental CV modification triggers a hidden restabilization
  (`Controller.cpp:1050-1068`).
- Hemodynamics engine: segfaults on its first advance (null ECG model, crash log
  `~/Library/Logs/DiagnosticReports/python3.12-2026-10-22-185434.ips`), and
  Python silently falls back to WholeBody (`PulseEngine.py:46-49`). Fixing it
  is an optional, deferred local `../engine` track.

### Task 1: workbench studies (2026-10-23, done on `main`, user-approved; not released)

- **Setup.** vivarium-workbench `main` (`aa2b7d2b`, 0.4.1) in `.venv`, pinned in `[tool.uv.sources]`; protobuf stayed 7.35.0, python-dateutil 3.0.0 -> 2.9.0.post0 (botocore caps it). Server served from `.venv` (`.venv/bin/vwb serve --detach`; it was left running).
- **Commits on `main`:** `89d2579` criteria + specs, `5754940` run configuration + figures + version 0.6.0, `99d742b` canonical runs + findings + review fixes, then the rendered report.
- **Runs.** `/api/investigation-run-unblocked`, 30/30 completed, manifests at `5754940`, Python 3.12.12; records in each study's committed `runs.db` (16 MB total). Criteria 7/7, 7/7, 23/23. Full suite 188 passed, 1 skipped; workspace lint OK.
- **Results:** README "Studies in the workbench". Saline vs whole blood indistinguishable in 10 min (controller engages at 508 s, delivers 79.6 mL); follow-up proposed in the study.
- **Honesty notes.** Criteria were written after direct pilots (`workspace/experiments/_runs.yaml`) that overlap some canonical configurations (severity 0.2/0.8, the whole cohort); each study's `preregistered.pilot` says so.
- **Adversarial review** done: no blockers; all should-fixes applied (fixture ties labels to params/commit/irreversibility, numeric figure guard, read-only db, `iv_compound` check, pilot disclosure, number fixes).
- **Report.** Rendered with `force`: 18 `readout_contract` overrides logged to `.pbg/report-lint-overrides.json` (gitignored), all the documented `vitals.*` false positive. The dashboard's study cards show "Tests 0/2" (gate ignores pytest results; upstream issue 6).
- **Open.**
  - Once (of four full-suite runs) `test_whole_body.py::test_combined_readings_equal_the_single_module_composites` failed at rel 1e-4, while another engine-heavy process (the reviewer's suites) ran concurrently. Not reproduced since (isolated, file, two full runs). Unexplained; watch for it.
  - Workbench issues: 6 drafted in `upstream-issues/vivarium-workbench.md` (user files them).
  - **Release v0.6.0 needs the user's explicit go-ahead.** Not pushed yet unless stated in the session summary.

### Standing by

The circuit-composites agenda is complete. **The remaining work is noted in
`agenda.md` under "Remaining work: pick up later"**, which travels with that
agenda when it's archived to `docs/agenda/circuit-composites/agenda.md`. Each item
waits for the user:
- the CI-plan PR (not until asked);
- the 14 upstream issue drafts in `upstream-issues/` (the user files them);
- the earlier backlog: `CONTRIBUTING.md`, `.github/workflows/release.yml`, and a
  workbench investigation over `pulse_hemorrhage`/`pulse_resuscitation`
  (`vwb scaffold-investigation --name pulse --studies
  viva_pulse.composites.hemorrhage.pulse_hemorrhage,viva_pulse.composites.hemorrhage.pulse_resuscitation`;
  `expected_behavior` from the reference results below; `studies/*/sims/run.py`
  with `build_core()`; Plotly viz after loading the `dataviz` skill);
- unverified: the v0.5.0 image build (`gh run list --workflow build-and-push.yml`).

Out of scope (decided): Phase 4 (ECMO and airway equipment; its plan notes,
including the edge-triggered binding idea, are in the plan doc) and the
Hemodynamics engine fix.

### Earlier verified state (pre-circuit work)

- Pulse superbuild in `.pulse-build/` (gitignored); Pulse 4.4.0 @ engine commit
  `5e29e5b13`; `PyPulse` built for the `.venv` CPython 3.12.12.
- Phase 4.5 (2026-10-22): `vwb scaffold-workspace --in-place` produced commit
  `afac8be` (51 template files, including template tests
  `test_composite_state_artifacts.py` and `test_core_registration.py`).
  `scripts/lint-workspace.py` reports `workspace lint: OK`.
  - Only `pyyaml` and `jsonschema[format-nongpl]` were installed from the new
    pyproject deps; protobuf stays 7.35.0. A full install would downgrade
    python-dateutil and pull vivarium-workbench 0.3.92.
  - Catalog entry fixed to `package: viva_pulse` (forget + add).
- Reference results (StandardMale, RightLeg 0.8, 600 s): untreated HR
  72->107, MAP 95->84, BV 5487->3936 mL, 1577 mL lost. With controller
  (target 90): MAP 86.3, BV 4014. Aorta 1.0 is irreversible at t=68 s.

### Open items to report upstream

Drafted (2026-10-23), each re-verified against source or by a fresh repro, in
`upstream-issues/` (git-excluded; the user files them):
- `pulse.md`: 7 issues. `keep_event_changes` is already fixed upstream
  (`175f0dfe7`, not on stable), so it isn't drafted.
- `bigraph-schema.md`: 4 issues (A, B, D, E). The owner was verified; B is
  the leak of undeclared keys, since seeding a declared input is intended.
- `process-bigraph.md`: 1 issue (C), a follow-up to #222/#227 (precision
  auto-default only on `CompositeSpec`).
- `viva-superpowers.md`: 2 issues. The tracker is viva-superpowers, not
  vivarium-workbench; both are still present in 0.24.0.
- Correction to the notes below: the `bigraph-viz` Python-floor problem is
  viva-superpowers' in-place scaffold dropping the template's own
  `requires-python >=3.11`; it isn't in viva-template.

- process-bigraph 1.10 / bigraph-schema 1.8.2 drop `initial_state()` values
  for `overwrite[float]` and `boolean` output ports (repro in
  `.build-progress.md`), and also project `initial_state()` through input
  wires (bug 2 above).
- viva-superpowers `workspace_catalog.add` reads workspace.yaml `package`, but
  the template writes `package_path`.
- viva-template's in-place scaffold adds `bigraph-viz>=2.0.3` (needs Python
  >= 3.11) without checking the host project's `requires-python`. That made
  viva-pulse unresolvable until v0.2.1.
- process-bigraph accumulates time as floats, so `interval=0.02` with
  `run(2.0)` drops the final update (rows end at t=1.98).
- Pulse (Kitware):
  - the Hemodynamics engine has a null ECG dereference;
  - `PulseEngine.py` silently falls back to WholeBody for Hemodynamics;
  - `process_action(s)` discards the engine's success flag;
  - `set_event_handler` calls an unbound `keep_event_changes`.
  - Python/C++ validity mismatches: Python `SEIntubation.is_valid()` rejects
    type Off (so no extubation from Python); Python
    `SEMechanicalVentilatorPressureControl.is_valid()` rejects a bare
    `connection=Off`. C++ accepts both.
  - The data root for `initialize_engine` comes from `SEPatientConfiguration`
    (default `./`), not from the `PulseEngine` constructor, so the
    VentilationMechanics HowTo only works from `install/bin`. From anywhere
    else it segfaults in `InitializeSubstances`.
