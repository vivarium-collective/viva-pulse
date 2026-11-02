# Plan: per-circuit Pulse composites (hybrid native)

> On approval, copy this file to `docs/plan/plan-circuit-composites.md` (user request), copy `../engine/docs/Images/Cardiovascular/CardiovascularCircuit.png` (514x720 PNG, Apache-2.0, upstream Kitware) to `docs/images/circuit-cardio.png` (user request, sidebar 2026-10-22), sync `CURRENT.md` and memory (deferred `/checkpoint -d`, blocked by plan mode), then **stand by**.

## Checkpoint (2026-10-22, plan mode, pre-compaction)

- **Task:** user ran `/plan`. Scope a strategy for one process-bigraph composite per Pulse circuit type, and settle native bindings vs a Python-native implementation. When finalized, write the plan to `docs/plan/plan-circuit-composites.md` and stand by. Gather input with `/open-question`.
- **Status:** the plan was **approved** on 2026-10-22, after an adversarial review and revision. All questions are resolved (see "Resolved: whole-body first"). Nothing is implemented yet.
- **Standing constraints:** do NOT commit in viva-pulse without asking (`CURRENT.md`). Never `uv sync`; always `uv run --no-sync`. `../engine` is a separate repo, so ask before committing there too.
- **Next:** Phase 4.5 (needs commit OK), then Phase 0 probes P5/P3, then Phase 1.

## Context

Pulse documents its physiology as lumped-parameter circuits (diagrams in `../engine/docs/Images/<System>/*Circuit*.png`). The goal is one composite per circuit family, built from modular, efficient Process/Step/Composite units, so circuits can be studied alone or composed. viva-pulse today has `PulseProcess` (WholeBody engine, 9 vitals as float deltas, hemorrhage/IV `overwrite[float]` setpoints, `irreversible_state` latch), `MapFluidController` (Step), and generators `pulse_hemorrhage` / `pulse_resuscitation`. There are 22 real-engine tests.

**User decisions (2026-10-22):**
- Strategy: **hybrid native.**
  - Pulse's own reduced engines where they exist: cardiovascular on `HumanAdultHemodynamics`, respiratory + ventilator on `HumanAdultVentilationMechanics`.
  - Modules on the WholeBody engine for the rest.
  - Rejected: binding the bare C++ solver (the circuits are passive without the C++ model drivers, so it would mean a partial reimplementation), and a Python-native rewrite (a reproduction, unvalidated).
- Engine change: a **local patch** in `../engine`, with the option of a Kitware MR "if/when needed".
- Order: **cardiovascular first**, then respiratory + ventilator, then thermal, then ECMO + other equipment.
- Sequencing: **after Phase 4.5** (workspace promotion; it creates a commit, so it needs user OK).

## Verified facts (primary source, re-checked by me)

| Fact | Source |
|---|---|
| PyPulse exposes only a whole-engine handle (state load/init, actions, advance, pull_data of data requests). No circuits, nodes, paths or solver | `../engine/src/python/pybind/PulseEngines.cpp:18-44` |
| Data requests cover physiology, compartment-level (gas/liquid/thermal/tissue Pressure/Volume/InFlow/OutFlow, substances) and equipment. There is no circuit node/path category. Unsupported requests return **NaN** with an "Unhandled data request" log; they do not raise | `SEDataRequest.h:10-14`, `pulse/cdm/engine.py:507-522`; NaN behavior from the reviewer's probe |
| Four independent solves per step (blood, airway, heat, ECMO gas), coupled by explicit lagged exchange. Renal, tissue, CSF and GI share the blood solve's matrix | `CardiovascularModel.cpp:1185`, `RespiratoryModel.cpp:1082`, `EnergyModel.cpp:493`, SCC:899/1750/2096 |
| WholeBody model order: Environment, CV, Inhaler, Respiratory, Anesthesia, BVM, MechVent, GI, Hepatic, Renal, Nervous, Energy, Endocrine, Drug, BloodChem, Tissue, ECG, ECMO | `human_adult/whole_body/controller/Controller.cpp:101-118` |
| Hemodynamics engine: CardiovascularModel only. No serialization (`serialize_from_file` returns False). `Stabilize` is a no-op. Drug, Nervous and Energy are allocated but not processed; **no ECG model is allocated** | `human_adult/hemodynamics/controller/Controller.cpp` |
| Python can't select Hemodynamics: the pybind enum lacks it, and `PulseEngine.__init__` silently falls back to WholeBody. (The reviewer reports `PyPulse.model_type(2)` constructs it anyway via an int cast) | `PyPulse.cpp:55-58`, `PulseEngine.py:46-49` |
| **Hemodynamics segfaults on its first advance**: `CardiovascularModel::Arrhythmia()` calls `m_data.GetECG().IsDefibrillating()` on a null ECG model. Init itself succeeds (~1.7 s; HR 72, MAP 95.3, BV 5487) | `CardiovascularModel.cpp:2291` (also 2301/2307/2313), `common/controller/Controller.cpp:201`; crash log `~/Library/Logs/DiagnosticReports/python3.12-2026-10-22-185434.ips` (stack: AdvanceModelTime > CV PreProcess > ProcessActions > Arrhythmia > GetECG) |
| A non-incremental `SECardiovascularMechanicsModification` triggers `Stabilize(*m_Stabilizer, AdvanceUntilStable)`. `m_Stabilizer` is null except on WholeBody. On WholeBody it is a hidden restabilization with the baroreflex off, plus a MAP/SBP/DBP baseline reset. Python defaults `_incremental = False` | `common/controller/Controller.cpp:1050-1068`, `Controller.h:339`, `whole_body/controller/Controller.cpp:75`, `pulse/cdm/patient_actions.py:303` |
| `list[string]` config **merges** an override into a non-empty default: `['a','b','c']` + `['x']` gives `['a','b','c','x']`; an empty default works | reproduced in `.venv` (bigraph-schema 1.8.2) |
| VentilationMechanics initializes from `SEPatientConfiguration` with only sex set | `pulse/howto/HowTo_VentilationMechanics.py:70-74` |
| `composite_generator` `choices` is UI-only and not enforced | `process_bigraph/composite_generator.py:30-35` (reviewer) |
| `PulseEngine.process_action(s)` discard the thunk's success bool | `PulseEngine.py:214-227` (reviewer) |
| Fast rebuild after an engine edit: `VIRTUAL_ENV=$PWD/.venv cmake --build .pulse-build/Innerbuild --target install -j 12` (copies PyPulse `.so` + `pulse` pkg). Do NOT use the outer superbuild: its `PulseData` target reruns genData/genStates and overwrites `bin/states` | `src/python/CMakeLists.txt:2,39-40,50`, `cmake/external/CMakeLists.txt:116-131` (reviewer) |
| `PulseConfiguration.json` merge is cwd-relative | `common/controller/Controller.cpp:532` (reviewer) |

Consequences:
- **A circuit is never split below its solve.** Renal and tissue are sub-stores of the cardiovascular composite.
- **One Pulse engine maps to one Process.** That Process owns `advance_time_s`; there is no `shared_process`.

## Resolved: whole-body first (user, 2026-10-22)

The cardiovascular composite is built on the **WholeBody** engine first. The Hemodynamics C++ fix is an **optional later track**, outside this plan's completion criteria (user, 2026-10-23). The smallest first patch is to allocate `m_ElectroCardioGramModel = new pulse::ElectroCardioGramModel(*this);` beside the other "CV looks for data on them" allocations (hemodynamics `Controller.cpp:68-71`); more null dependencies may follow. Because the module doesn't depend on the engine, enabling `engine=hemodynamics` later needs no change to the module.

The implementation approach is confirmed with the user: process-bigraph Process and Step classes wrap the **real Pulse Python bindings** (`PulseEngine`, data requests, actions), are composed into documents, and run through `process_bigraph.Composite`. There is **no Python-native rewrite** of Pulse's physiology or solver.

## Architecture

### Circuit modules (declarative registry)

New package `viva_pulse/circuits/`:
- `base.py` holds the dataclasses:
  - `Request(port, category, name, unit, compartment=None)` maps to `pulse.cdm.engine.SEDataRequest.create_*_request`.
  - `ActionBinding(ports: dict[str, float], build(values, params) -> SEAction, validate)` is a setpoint group that becomes one action. The **whole group** is resent on any change (`Copy` replaces the full modifier set, `SEPatientActionCollection.cpp:316`). CV modifications always call `set_incremental(True)`.
  - `CircuitModule(name, model_types, outputs, bindings, params)`.
- Registry `MODULES` holds `vitals`, `hemorrhage`, `infusion` (moved from `processes.py`, which keeps re-exporting `VITALS` / `HEMORRHAGE_COMPARTMENTS`), and `cardiovascular`. Later modules: `respiratory_mechanics` (built as `respiratory`, see Phase 2 notes), `mechanical_ventilator`, `thermal`, `ecmo`, `bag_valve_mask`, `supplemental_oxygen`, `anesthesia_machine`, `inhaler`.
- `model_types` gates validity:
  - `infusion` is `{whole_body}` only, because DrugModel is not processed on Hemodynamics.
  - The `vitals` module, which includes SpO2 and RR, is `{whole_body}` only.

### Processes

- Extract a small base (lazy engine, request dedupe by (category, compartment, property, unit), delta outputs seeded by `initial_state()`, `irreversible_state` latch, act-on-change bindings).
- **`PulseProcess` stays the unchanged WholeBody legacy subclass.** Same ports and config, and it keeps `_read_vitals()`, which `tests/test_composites.py:29` uses. The 22 tests are the guard.
- New sibling **`PulseCircuitProcess`** with config:
  - `model_type` (`whole_body` | `hemodynamics` | `ventilation_mechanics`), validated in `__init__`
  - `modules: list[string]` with `_default: []`; empty raises
  - `state_file` (WholeBody) / `patient_file` (Hemodynamics, VM: `initialize_engine`); a state file on an engine without serialization raises
  - module params merged into `config_schema` from `MODULES` at import
- Ports are **nested per module**: `outputs() -> {module: {port: "float"}}`, wired to `circuits/<module>`; setpoints go to `interventions/<module>`. One `pull_data()` per update. Actions go through `process_actions` only on change, and the result is checked (needs the `PulseEngine.py` return-bool patch).
- After the first advance, any NaN in a requested value raises, naming the request. Silent NaN ports are not allowed.
- Output contract unchanged. `float` deltas are kept on purpose (`.build-progress.md`: upstream drops `initial_state()` on `overwrite[float]`/`boolean`).
- Controllers stay separate Steps (pattern: `MapFluidController`).

### Composites

- New `viva_pulse/composites/circuits.py` gets a wiring helper (module port lists to nested store paths, plus `RAMEmitter` over the `circuits` subtree).
- `composites/hemorrhage.py` is **left untouched**.
- `pulse_cardiovascular`:
  - Parameters: `engine` (validated in the Process), `interval` (1.0 s for trends, 0.02 s for per-beat waveforms), the CV multipliers, hemorrhage site and severity.
  - `fidelity="real-bridge"`, `core_extensions=[register_processes]`.

## Phase 0: probes + engine track

Probe scripts live in the scratchpad and run with `uv run --no-sync`. **Every Hemodynamics probe and test runs in a subprocess**, because a segfault kills the interpreter or pytest. Results are recorded in `.build-progress.md`.

- P5: process-bigraph accepts nested per-module output ports with delta seeding through `initial_state()` (first emitted row equals the loaded values), plus the import-time `config_schema`.
- P3 (WholeBody): which CV/renal/tissue liquid compartments return non-NaN **after advancing**. The CV module's request list is fixed to these.
- Engine track (**optional, deferred until after Phase 1**), gated, local branch in `../engine`:
  1. Python: `PyPulse.cpp` enum value `human_adult_hemodynamics`; `PulseEngine.__init__` maps it, and unknown types raise; `process_action(s)` return the thunk bool.
  2. C++: allocate the ECG model in hemodynamics `Allocate`. Rebuild with the Innerbuild install command above. Probe advancing in a subprocess, and repeat patch then probe until a 600 s run is clean.
  3. P1: HR, MAP and CO stay physiological over 600 s; drift is reported.
  4. P4: hemorrhage lowers BV; multipliers (incremental) move MAP; infusion is inert, confirming the gate.
  5. P2 regression discriminator: `serialize_from_file("StandardMale@0s.json")` returns **False** on Hemodynamics and True on WholeBody.
  6. If it doesn't converge, stop and report to the user.
  Commits in `../engine` need user OK. The pin (branch + commit) goes in `.build-progress.md`. MR deferred.

## Phase 1: cardiovascular on whole_body (one PR)

- `circuits/cardiovascular.py`:
  - Outputs: HR, MAP, SBP, DBP, CO, stroke volume, CVP, pulmonary arterial pressure, SVR, BV, and the P3-verified compartment Pressure/Volume/InFlow, with renal and tissue as nested sub-stores.
  - Bindings: `SECardiovascularMechanicsModifiers` multipliers (`pulse/cdm/physiology.py:59+`, default 1.0, incremental) and hemorrhage.
  - Docstring cites `../engine/docs/Images/Cardiovascular/CardiovascularCircuit.png`.
- Tests, real engine, nothing mocked. Each test names the proposition it falsifies:
  - Registry (no engine): unique ports per module, defaults pass validators, unsupported module/engine combinations raise, an empty `modules` raises.
  - First emitted row equals the loaded values (nested ports).
  - Arterial resistance multiplier 2.0 gives a higher MAP than 1.0 after N s.
  - Hemorrhage lowers BV and raises HR (baroreflex on, whole_body).
  - No NaN in any requested value after 1 s.
  - The existing 22 tests pass unchanged.
- Follow-up PR, when the engine track passes:
  - `engine=hemodynamics` is enabled.
  - New tests: the P2 regression test (fails on the unpatched `PulseEngine.py`), a subprocess "advance 600 s without crash" test (fails without the ECG fix), and isolated vs coupled (HR flat on Hemodynamics, rising on whole_body under the same hemorrhage).

## Later phases (one PR each)

| Phase | Module(s) | Engine | Inputs | Notes |
|---|---|---|---|---|
| 2 | `respiratory_mechanics`, `mechanical_ventilator` | ventilation_mechanics (+ whole_body) | `SERespiratoryMechanicsConfiguration`; ventilator PC/VC/CPAP | **First probe that VM advances cleanly** (subprocess). Reference `HowTo_VentilationMechanics.py`. Diagrams `Respiratory/RespiratoryCircuit.png`, `MechanicalVentilator/MechanicalVentilatorCircuit.png` |
| 3 | `thermal` | whole_body | `SEChangeEnvironmentalConditions`, `SEThermalApplication` | Internal + External form one solve. Diagrams `Energy/internalThermal.png`, `Environment/EnvironmentCircuit.png` |
| 4 | **Out of scope** (user, 2026-10-23): `ecmo`, `bag_valve_mask`, `anesthesia_machine`, `inhaler`. `supplemental_oxygen` moved to Phase 5 | whole_body | equipment configs | Anesthesia machine and inhaler have no Python action classes (engine-side, scoped at that phase). At most one airway device is active (`CircuitManager.cpp:191-216`) |
| 5 | `supplemental_oxygen`, `pulse_whole_body_circuits` | whole_body | union | All modules on one engine. Completes this plan (user, 2026-10-23). See Phase 5 notes |

## Sequencing and hygiene

1. Phase 4.5 from `CURRENT.md` comes first (commit needs user OK).
2. Each phase is one branch, one PR, tests and a version bump, then a tag and release (BOJ 1 and 2). Every commit and push needs user OK.
3. `CURRENT.md` is updated at each checkpoint.

## Verification

- `uv run --no-sync pytest -q` (timeout 600000 ms): everything passes against the real engine, with Hemodynamics tests isolated in subprocesses.
- Phase 0 probe outputs recorded in `.build-progress.md`.
- `/viva-run pulse_cardiovascular` smoke run once the workspace exists.
- `/adversarial` review of each phase's diff.

## Critical files

- Modify: `viva_pulse/processes.py` (base extraction, new sibling), `viva_pulse/core.py`, `CLAUDE.md`, `.build-progress.md`, `CURRENT.md`
- Add: `viva_pulse/circuits/{__init__,base,vitals,hemorrhage,infusion,cardiovascular}.py`, `viva_pulse/composites/circuits.py`, `tests/test_circuits.py`, `docs/plan/plan-circuit-composites.md`
- Untouched: `viva_pulse/composites/hemorrhage.py`, the existing tests
- Engine (local branch): `src/python/pybind/PyPulse.cpp`, `src/python/pulse/engine/PulseEngine.py`, `src/cpp/engine/human_adult/hemodynamics/controller/Controller.cpp`

## Phase 1 implementation notes (2026-10-22): deviations from the plan above

- **No base class.** `PulseProcess` and `PulseCircuitProcess` share a module-level `_load_engine()` helper rather than a common base class. It's lighter, and `PulseProcess`'s ports and config are byte-for-byte unchanged.
- **Only the `cardiovascular` module exists.**
  - `vitals` and `infusion` modules were not created. `PulseProcess` keeps `VITALS`, and nothing else needs those modules yet.
  - `HEMORRHAGE_COMPARTMENTS` moved to `circuits/cardiovascular.py`; `processes.py` re-exports it.
  - The sub-stores are `hemodynamics`, `central`, `renal` and `peripheral`, following the diagram's branches; the plan's "tissue" became `peripheral`.
- **Setpoints have their own input namespace.** All module setpoints sit under one input port, `setpoints/<module>/...`. The reason: process-bigraph projects `initial_state()` through input wires as well as output wires, so a module name shared between inputs and outputs leaked readings into `interventions/`. The registry reserves `setpoints` and `irreversible_state` as module names.
- **Compartment flow properties are spelled `Inflow`/`Outflow`.** The earlier survey's `InFlow` returns NaN for every compartment.
- **Action results are not checked.** `PulseEngine.process_action` discards the engine's success flag. Checking it needs the `PulseEngine.py` change from the deferred engine track, so it stays a known limitation until then.
- **No `vitals` NaN gating across engines yet.** The only engine is `whole_body`, so `model_types` checks are in place but have nothing to gate.
- **Two test substitutions.**
  - The multiplier test uses **systemic** resistance x2 (HR 72 -> 43 at 60 s, SVR and CO), not "arterial x2 raises MAP". Arterial x2 has no measurable effect in Pulse, and the baroreflex holds MAP almost constant (95.3 -> 97.1).
  - The hemorrhage test checks **mass balance** (blood-volume deficit equals volume lost) instead of "HR rises". HR rises only 72.0 -> 74.6 in 120 s at RightLeg 0.8.
- **NaN guard timing.** NaN is checked at load (t = 0) **and after every update**. Readings are deltas, so a single NaN would poison its store for the rest of the run.
- **The generator parameter is `model_type`, not `engine`.** It matches the process config key.
- **Validation happens up front.** `PulseCircuitProcess` validates every changed setpoint group before sending any action. `pulse_cardiovascular` also runs the module's validators when it builds the document.
- **The irreversible latch is unobservable from outside.** Pulse refuses to advance once irreversible (`Controller.cpp:790`), so the process's own latch can't be seen in the outputs; the test pins the output contract only. `PulseProcess` has the same property.
- **Adversarial review (2026-10-23).** It found no blockers, and all ten findings were addressed. The new tests were each shown to fail on a deliberately broken copy of the code.

## Phase 2 implementation notes (2026-10-23): respiratory + mechanical ventilator

- **Modules.** `respiratory` (24 mechanics scalars, 8 gas compartments) and `mechanical_ventilator` (18 monitor values, one pressure-control setpoint group). Both run on **both** engines.
- **Generators.** `pulse_respiratory` and `pulse_mechanical_ventilation`. Both default to `ventilation_mechanics`, the isolated airway.
- **Ventilation-mechanics engine.**
  - It starts from a patient file, with the data root set on `SEPatientConfiguration`; without that it segfaults.
  - It then **settles** before t=0, because it does no stabilization and `PeakInspiratoryPressure` is NaN until the first breath.
  - The plan's open item "probe that ventilation-mechanics advances cleanly" is done (P6/P7 in `.build-progress.md`).
- **Two Pulse Python/C++ mismatches, handled explicitly.**
  - `SEIntubation.is_valid()` rejects Off, so **extubation is impossible from Python**. Our 1 -> 0 change raises, through a new `ActionBinding.check_transition`.
  - `SEMechanicalVentilatorPressureControl.is_valid()` rejects a bare `connection=Off`, so we disconnect with `SEMechanicalVentilatorConfiguration{Off}`.
- **Renamed port.** The gas-compartment pressure port is `absolute_pressure_cmH2O`; Pulse's ambient is 1033.2 cmH2O.
- **Measured contrast (test anchor).** Lung compliance x0.5 cuts tidal volume 471 -> 270 mL isolated (rate unchanged), but 510 -> 388 mL coupled (chemoreflex raises the rate 12 -> 15). These figures are from the generators (StandardMale patient file, settled, 60 s). The P7 probe figures in `.build-progress.md` differ because that probe used a different patient set-up and timing.
- **Deviations from the Phase 2 row of the plan table.**
  - The module is named `respiratory`, not `respiratory_mechanics`: it covers the gas compartments and intubation as well as the mechanics.
  - Its inputs are the `SERespiratoryMechanicsModification` multipliers (incremental, full group), not `SERespiratoryMechanicsConfiguration`. That matches Phase 1's cardiovascular multipliers. Checked at source: `RespiratoryModel.cpp:4619` applies the multipliers from baseline every step, and a non-incremental send restabilizes (`Controller.cpp:1073`) with a null `m_Stabilizer` on ventilation_mechanics.
  - Only pressure control is built, in AC and CMV modes. Volume control and CPAP are follow-ups (below).
- **Start files.** A non-default `state_file` on ventilation_mechanics, or `patient_file` on whole_body, raises. Before this it was silently ignored.
- **Row 0 is not ventilated.** Setpoints apply from the first update (the Phase 1 contract), so `pulse_mechanical_ventilation` settles with spontaneous breathing. Its ventilator monitor reads 0 until the first ventilated breath completes.
- **AssistedControl auto-triggering (Pulse behavior).** At a set rate of 16 bpm (spontaneous 12), AC mode can lock into about 48-52 bpm with intrinsic PEEP 12-14 cmH2O. Which engine locks depends on the breath phase at connect. Driving Pulse directly with no wrapper reproduces it (whole_body: RR 51.7, PEEP 13.8). CMV honours all settings on both engines, so the settings test uses CMV.
- **Adversarial review (2026-10-23).** It found no blockers and nine findings, all addressed:
  - start-file check;
  - recorded deviations;
  - the settings test now uses non-default PIP, PEEP, rate, inspiratory period and FiO2, and is shown to fail when each is hard-coded;
  - new tests: reconnect, settle exhaustion, missing patient file, and start file ignored by the engine;
  - documented: `max_settle_s` can't be 0 (superseded 2026-10-25: bigraph-schema 1.8.3 keeps an explicit 0.0, meaning no settling), and row 0 is pre-ventilation;
  - figures reconciled; runtime updated.

  The two research sections below are kept here, with their verification status, as planning input.

## Phase 3 implementation notes (2026-10-23): thermal

- **Module.** `thermal`, whole_body only, with 44 outputs:
  - `energy`: core and skin temperature, sweat rate and total metabolic rate;
  - `heat_loss`: five loss rates and three transfer coefficients;
  - `environment`: seven conditions, read back from the engine as `EnvironmentalConditions-<Property>` environment requests;
  - `compartments`: temperature for 7 thermal compartments, stored heat for 2, heat flow in/out for 8.
- **Generator.** `pulse_thermal`, with default `n_steps` 1800.
- **New request categories.** `environment` and `thermal_compartment`, added to `Request.to_pulse`.
- **Probe P8 (`.build-progress.md`) set the request list.**
  - Pulse returns stored heat only for `InternalCore`/`InternalSkin`, and NaN for `InternalGround`'s temperature.
  - `ExternalGround` (the circuit's absolute-zero reference) and `Active` (the applied-temperature node, while off) read 0 K. Their temperatures are not exposed.
  - `Active` keeps its heat flows, which carry the applied-temperature heat.
- **Setpoints.**
  - `environment`: `SEChangeEnvironmentalConditions`, merge type Append (the proto default). Fields the action doesn't carry stay as they are (verified: atmospheric pressure kept).
  - `thermal_application`: `SEThermalApplication`, which Pulse replaces whole on each action. Heating and cooling are `power x area_fraction` (verified: 500 W at 0.4 equals 200 W at 1.0 exactly). Zero power with the applied temperature off deactivates it (verified in Pulse's serialized active actions).
  - Environment baselines are `Standard.json`, which all 21 shipped states use (a test checks every state). A state with another environment fails the load (`CircuitModule.check_loaded`), because the group is always sent whole.
  - Breathed air: Pulse computes respiration heat loss from `RespirationAmbientTemperature` (`EnvironmentModel.cpp:764`), which does not follow `AmbientTemperature`, so it is its own setpoint. Breathing -10 °C air raises respiration loss 8.06 -> 13.34 W.
  - The applied temperature is a source on the clothing node, set to `applied * fraction + ambient * (1 - fraction)` (`EnvironmentModel.cpp:449-458`).
- **The state isn't thermally settled.** Unperturbed StandardMale skin goes 32.36 -> 29.95 °C in 30 min, and core 37.03 -> 37.09 °C. Every effect test compares against a parallel unperturbed run.
- **Measured through the generator** (Δ against the unperturbed run):

  | Intervention | Effect |
  |---|---|
  | -10 °C with a 5 m/s wind | skin -3.2 °C at 120 s; core -0.18 °C at 600 s; shivering raises metabolic rate after 900 s |
  | 200 W heating | skin +0.61 °C at 120 s |
  | 200 W cooling | skin -0.62 °C at 120 s |
  | applied 10 °C over the whole skin | skin -2.16 °C at 120 s, with 656 W into `active` |
  | 40 °C at 0.8 humidity (probe only) | skin +2.0 °C at 300 s; sweat 0.33 -> 2.17 g/min over 30 min |

- **Cost.** Pulse runs at about 35x real time, so 30 simulated minutes take about 52 s. The thermal tests take about 60 s, and the suite about 160 s.
- **Deviation from the plan table.** Its row lists only the two actions. The module also exposes the read-back environmental conditions, so a setpoint change is visible once applied.
- **Adversarial review (2026-10-23).** It found no NaN under extreme conditions, and nine findings, all addressed:
  - setpoint coverage: two new tests check that every environment setpoint reads back, and that every thermal-application field reaches Pulse's serialized active action. The reviewer's seven surviving mutants (clothing, humidity, radiant temperature, applied temperature in K, area fractions, a swapped read-back) now fail;
  - the breathed-air temperature setpoint;
  - the load check for non-Standard environments;
  - the applied-temperature blend described correctly;
  - the ground-node wording;
  - docstring numbers and the sweat figure;
  - a shared `validate_switch`;
  - a `model_type` parameter on `pulse_thermal`.

## Phase 5 implementation notes (2026-10-23): supplemental oxygen + every module on one engine

- **Scope (user, 2026-10-23).** Phase 4 is out of scope except supplemental oxygen, which moved here. Phase 5 completes this plan. The user asked for it to be committed directly on `main`.
- **`supplemental_oxygen` module** (whole_body only).
  - Readings: FiO2, SpO2, PaO2, PaCO2.
  - Setpoints: `oxygen_connected`, `oxygen_flow_L_per_min`. The device (nasal cannula, simple mask, non-rebreather) is config `oxygen_device`, following the `ventilator_mode`/`intubation_type` pattern.
  - Disconnecting sends device `None`, which Pulse removes. The supply is a wall supply (`inf` volume): Pulse's finite bottle drains (1 L at 6 L/min runs out in 10 s) and would refill on every resend.
  - Device gas compartments are not exposed: the nasal cannula's pressure is NaN while it is off, and the volumes are constant.
- **The one-airway-device rule.** Pulse refuses a second airway device ("Can only change airway mode from the Free mode, Disable other equipment first"), and every later advance fails, which would latch `irreversible_state`.
  - A one-update ventilator -> oxygen swap also fails, because Pulse processes the oxygen action before the ventilator's disconnect. An oxygen -> ventilator swap happens to work, but one rule covers both.
  - `CircuitModule.airway_device` plus `PulseCircuitProcess._check_airway` reject two connected devices, and a device connecting in the update another disconnects. A staged handover (disconnect, then connect one update later, even 0.02 s) works.
- **Generators.** `pulse_supplemental_oxygen` (respiratory plus oxygen) and `pulse_whole_body_circuits` (every whole-body module, 269 readings, flat parameters; names are unique across modules, which a test enforces).
- **Measured** (StandardMale, 120 s, Δ against an unperturbed run):

  | Intervention | Effect |
  |---|---|
  | nasal cannula 3.5 / simple mask 7.5 / non-rebreather 10 L/min | PaO2 240 / 393 / 563 mmHg (room air 91); FiO2 0.51 / 0.59 / 0.96 |
  | non-rebreather (cross-circuit) | heart rate 71.9 -> 65.9, breathing rate 12.0 -> 14.2 |
  | systemic resistance x2 (cross-circuit) | breathing rate 12.0 -> 10.6, tidal volume 512 -> 457 mL |
  | ventilator PEEP 10 (CMV) | no measurable change in cardiac output at 120 s, so not used as a test |

- **Combined-run oracle.** At baseline every module's readings in `pulse_whole_body_circuits` equal its single-module composite to 1e-9: Pulse's dynamics don't depend on which values are requested.
- **Cost.** 120 simulated seconds take about 4 s; the suite takes about 225 s.
- **No adversarial review.** Unlike phases 1-3, this phase shipped without one: the user called it off to finish the agenda (2026-10-23). Verification is the probe, 24 real-engine tests and 11 mutation checks.

## Follow-ups from the Pulse methodology review (2026-10-23)

These come from a review of `pulse.kitware.com/_system_methodology.html` against the pinned `engine/docs/Methodology`. "Verified" means I checked it at source; the rest must be checked when implemented.

**Phase 2 extensions (respiratory)**
- **Validation scenarios.** Use Kitware's ventilation-mechanics bench scenarios (`engine/data/human/adult/scenarios/miscellaneous/ventilation_mechanics/*.json`, run on HumanAdultVentilationMechanics) as study and validation anchors. Assert against Pulse's own outputs; the bench values are context, with TV errors of 11-36% in PC/CPAP modes.
- **Whole-body ventilator studies.** Use the `Ventilated@0s.json` patient, which matches the validation tables. The PC-CMV validation runs tune the inspiratory pressure to a target TV, so reproducing them needs a TV-targeting controller Step (the `MapFluidController` pattern) or a volume-control mode.
- **More respiratory actions.** Exacerbation actions (ARDS, COPD, pneumonia, impaired alveolar exchange, pulmonary shunt), airway obstruction, bronchoconstriction, tension pneumothorax (plus needle decompression and occlusive dressing), dyspnea and supplemental O2. Also VC-AC/VC-CMV/CPAP modes; only PC/VC-CMV, PC/VC-AC and CPAP are validated.
- **One-shot commands.** Ventilator hold, a BVM squeeze, and conscious-respiration sequences need an **edge-triggered** binding, not the level-setpoint pattern. Design it before the BVM work in Phase 4.
- **Positive-pressure ventilation modifiers.** These are documented in the module docstring: airway resistance x15 (**verified**, `RespiratoryMethodology.md` "diseases" table) plus a compliance change.

**Phase 3/4**
- **Thermal.** Core temperature is about 37.0 °C; Pulse defines hypothermia below 35 °C and hyperthermia above 38.8 °C. The thermal circuit couples to the cardiovascular one through skin blood flow. Runs are hour-scale, so tests will be slow.
- **ECMO.** Its blood loop joins the cardiovascular solve, so it must share the cardiovascular Process. Always set the sweep gas flow explicitly, because the engine default is unrealistic. Validate the mode parameters before sending them; mixing diffusion and rate parameters causes an engine Fatal.

**Retroactive (cardiovascular)**
- **Resting-state test.** Check against the published bands (MAP 70-105, HR 60-100, mean CVP 2-6 mmHg, stroke volume 55-93 mL), averaged over whole beats.
- **Documentation.** Compartments are hierarchical (`heart` contains the chambers), so their values don't add up. HR changes take effect at the next beat. MAP collapse does not force `irreversible_state`.

## CDM-mapped bigraph types: scoped, recommend not now (2026-10-23)

A research agent reviewed `pulse.kitware.com/_c_d_m_tables.html` and bigraph-schema 1.8.2. Its claims come from its own probes, which were not re-run by me; re-verify before acting on them. It concluded:

- **Don't register CDM-mapped types.** The CDM tables give dimension classes, not units. Our units are fixed in one place, each module's `Request` table.
- **bigraph-schema's built-in `range` and `enum` are wrong for our setpoints.** `range` clamps silently (a severity of 2.0 would become 1.0 with no error), and `enum` isn't enforced at run time. Our explicit validators are stricter.
- **The workbench never reads port units.**
- **Optional small step for later:** annotate output ports with the built-in `float[<Pulse unit>]`. Built-in pint conversion at wire boundaries was probed on the real engine, with bit-identical rows and a correct kPa conversion. Do it when a non-Pulse model is wired to Pulse stores, or when the workbench starts reading units.
