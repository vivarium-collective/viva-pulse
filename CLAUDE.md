# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`viva-pulse` is a process-bigraph wrapper that drives the **real** Kitware Pulse Physiology Engine (whole-body adult model). Pulse has no PyPI release: it is built from source (sibling checkout `../engine`, which has its own CLAUDE.md) through its CMake superbuild into `.pulse-build/` (gitignored). Build pins, the exact configure command, and known build workarounds are in [.build-progress.md](.build-progress.md); read it before touching the build.

Session state (active work, next steps, user instructions such as "do not commit") lives in [CURRENT.md](CURRENT.md).

## Commands

The venv is `.venv` (uv-created, CPython 3.12.12, the same Python `PyPulse` was compiled against).

```bash
uv run --no-sync pytest -q                                              # full suite, ~5 min, real engine (incl. the docs build)
uv run --no-sync pytest -q tests/test_processes.py::test_zero_severity_does_not_bleed   # one test
```

User docs: `make docs` (fresh `sphinx-build -W` of `documentation/` in `.venv`, then opens the browser). The docs group is installed with `uv pip install --group docs` (the target does this). Tutorials and the results page are MyST-NB notebooks executed on every build against the real engine and the committed `runs.db` files; `tests/test_docs.py` runs the same strict build. Internal developer docs (plans, agendas, decisions) stay in `docs/`. Keep the user docs current with every user-visible change.

Always pass `--no-sync`, and never run `uv sync`. The venv was assembled by hand, not from a lockfile: the Pulse build installed protobuf 7.35.0 to match its generated `_pb2` code, and `../engine/requirements.txt` was installed into it. With no `uv.lock` present, a sync would write a lock and resolve protobuf to a newer version (7.36.x at the time of writing). `uv sync` is also exact, so it would remove pytest (only in the `[dev]` extra) and the engine requirements.

The workbench (vivarium-workbench, pinned to a `main` commit in `[tool.uv.sources]`) is installed in `.venv` and must be served from there: `.venv/bin/vwb serve --detach`. Runs execute in the serving interpreter's environment, and only `.venv` can import PyPulse; the global `~/.local/bin/vwb` (py3.14, no Pulse) cannot run these composites. Server state is in `.pbg/server/` (gitignored); restart it (`.venv/bin/vwb server-restart`) after changing `viva_pulse/visualizations/`, because its env worker caches imported classes.

Rebuilding Pulse (only after changing `../engine`): run the configure + build pair in `.build-progress.md` from the repo root. `--fresh` discards the CMake cache. `-DPython3_EXECUTABLE` is ignored by Pulse's CMake; the venv is selected with `-DPulse_PYTHON_HOME_DIR` plus `VIRTUAL_ENV`. `README.md` carries the user-facing setup, usage and composite list (`pyproject.toml` and the `PulseNotFoundError` message point to it); keep it current with every user-visible change. `.build-progress.md` remains the authority for build pins and workarounds.

The per-circuit composite plan (approved 2026-10-22) is [docs/plan/plan-circuit-composites.md](docs/plan/plan-circuit-composites.md).

## Architecture

- `viva_pulse/runtime.py` resolves the Pulse install prefix (`install_dir` config > `$PULSE_INSTALL_DIR` > `.pulse-build/install`) and puts `bin/` (holds `PyPulse*.so`; also the engine's data root, incl. `bin/states/*.json`) and `python/` (the `pulse` package) on `sys.path`. An explicitly given location that is invalid raises `PulseNotFoundError`; it never falls back.
- `viva_pulse/processes.py`
  - `PulseProcess` loads a stabilized state file lazily on first use, then advances Pulse by `interval` seconds per update. Its inputs (`hemorrhage_severity`, `iv_rate_mL_per_min`) are `overwrite[float]` setpoints, forwarded to Pulse as patient actions only when they change.
  - The outputs are the `VITALS` table (port name -> Pulse property, unit). Vitals are plain `float` ports carrying **deltas** (`current - previous`), seeded with absolute readings by `initial_state()`, so the store always equals Pulse's own value. This is deliberate: process-bigraph 1.10 / bigraph-schema 1.8.2 discard `initial_state()` values on `overwrite[float]` and `boolean` output ports (repro in `.build-progress.md`). Don't "simplify" the vitals to `overwrite[float]`; `tests/test_composites.py::test_first_emitted_row_carries_loaded_vitals` guards this.
  - `iv_compound` must name a file in `<install>/bin/substances/compounds/`; it is checked when the engine loads, because Pulse segfaults on the first infusion of an unknown compound.
  - `irreversible_state` flips to True when `advance_time_s` fails. After that the engine is not advanced again and the update returns `{}`.
  - `MapFluidController` is a proportional MAP -> IV-rate `Step` that writes the `overwrite[float]` setpoint.
  - `PulseCircuitProcess` is the per-circuit sibling of `PulseProcess`. It shares `_load_engine()` and the same delta/latch output contract.
    - `config.modules` selects entries of `viva_pulse.circuits.MODULES`. The default is `[]` and an empty list raises: a non-empty `list[string]` default would *merge* with overrides.
    - Output ports nest per module, e.g. `cardiovascular/central/aorta/pressure_mmHg`.
    - Setpoints live under the single input port `setpoints/<module>/...`. Each port's schema `_default` is its baseline, so an omitted setpoint is never 0.0.
    - Input and output top-level names must stay disjoint. process-bigraph projects `initial_state()` through input wires too, and a shared name copied readings into `interventions/` (`test_stores_hold_only_their_own_ports` guards this).
    - `SUPPORTED_MODEL_TYPES`:
      - `whole_body` loads `state_file` (`_load_engine`), or, when `patient_file` is non-default, that patient's cached stabilized state (`_whole_body_state`, see `viva_pulse/patients.py` below). Both non-default raises in `__init__` (`_check_whole_body_start`; `PulseProcess` takes the same `patient_file` with the same rule). Only a non-default value counts as set, because bigraph-schema replaces an explicit value equal to the default with the default; the default patient, StandardMale, ships a state anyway.
        - `circuit_additions` (typed map: new path name -> `source`/`target`/`resistance_mmHg_s_per_mL`, on both whole-body processes and every generator): `viva_pulse/circuits/additions.py` `add_paths` edits the parsed state before load. Each path goes into every fluid circuit holding both nodes, plus a same-named `LiquidLink` into every liquid graph holding both compartments, because Pulse transports substances only over the graph (probe `path-additions-2026-10-25`: a path alone corrupts concentrations). Only resistance paths between `FullCardiovascular` nodes in two different vascular compartments are accepted: in both the `Cardiovascular` and `ActiveCardiovascular` graphs, minus `AbdominalCavity`. That excludes `Ground`, tissue fluid, lymph, the pericardium and the renal/urinary/chyme compartments, whose links would miss the transport graph or join a non-blood space. State names are `VivaAdded<key>`: Pulse's runtime creates (`<cmpt>Hemorrhage`, leaks, ECMO) return an existing link of the same name and would take the addition over. Joined compartments' regional flows include the path. Applied in `__init__` (needs the install), before point modules' `prepare_state`, so point reads cover added paths. It is a perturbation (no re-stabilization). Tests: `tests/test_additions.py` (oracle: an independently edited direct engine; a path-only oracle shows the difference).
        - `circuit_modifiers` (`map[float]`, on both whole-body processes and every generator taking `state_file`) also routes through `_whole_body_state`: the patient (default StandardMale) is stabilized with them. With a non-default `state_file` it raises; on ventilation_mechanics it raises.
      - `ventilation_mechanics` (airway only, no blood) starts from `patient_file` (`_initialize_engine`). It must set `SEPatientConfiguration.set_data_root_dir(<install>/bin/)`: Pulse takes the data root from the patient config, which defaults to `./`, and without it substance loading segfaults. It then runs `_settle()`: that engine does no stabilization, so it advances in 1 s steps until every request is non-NaN (at most `max_settle_s`; bigraph-schema turns an explicit 0.0 into the default, so settling can't be switched off).
      - A non-default `state_file` on ventilation_mechanics raises in `__init__`.
    - `ActionBinding.check_transition(previous, values)` rejects changes Pulse can't make. Extubation (intubated 1 -> 0) is one: Pulse's Python `SEIntubation.is_valid()` rejects type Off, so `PulseEngine` would silently drop it.
    - Hemodynamics (cardiovascular-only) segfaults and is not supported.
- `viva_pulse/circuits/`: a declarative registry; modules compute nothing.
  - `base.py` defines `Request` (one Pulse data request at a port path), `ActionBinding` (a group of setpoints resent whole as one action) and `CircuitModule`.
  - `cardiovascular.py` covers the cardiovascular circuit plus its renal and tissue branches, which share one Pulse solve. It has 146 outputs:
    - 20 system scalars under `hemodynamics/`;
    - Pressure/Volume/Inflow/Outflow for 32 regions under `central/`, `renal/` and `peripheral/`.
  - Its setpoints are the 10 `SECardiovascularMechanicsModifiers` multipliers, always sent with `incremental=True` (non-incremental reruns stabilization and resets baselines), plus hemorrhage.
  - Pulse spells compartment flows `Inflow`/`Outflow`; `InFlow` returns NaN.
  - `respiratory.py` has two modules, both on both engines:
    - `respiratory`: 24 `SERespiratorySystem` scalars under `mechanics/`, plus gas compartments under `lungs/` and `pleura/`. Their `absolute_pressure_cmH2O` is absolute (ambient 1033.2). Setpoints: 10 `SERespiratoryMechanicsModifiers` multipliers (incremental, full group) and `intubated`.
    - `mechanical_ventilator`: 18 ventilator monitor values, which read 0 while disconnected. Setpoints: one pressure-control group. `connected=0` sends `SEMechanicalVentilatorConfiguration{connection: Off}`, because Pulse's Python drops a bare pressure-control action with Off (its `is_valid` requires the pressure settings, though C++ accepts it).
  - `thermal.py`: the `thermal` module, whole_body only.
    - 44 outputs:
      - `energy/`: 4 `SEEnergySystem` scalars;
      - `heat_loss/`: 8 `SEEnvironment` loss rates and coefficients;
      - `environment/`: 7 conditions read back as `EnvironmentalConditions-<Property>` environment requests;
      - `compartments/`: thermal-compartment Temperature, Heat, HeatTransferRateIn/Out.
    - Only `InternalCore` and `InternalSkin` serve Heat, and `InternalGround` returns NaN for Temperature. `Active` (the applied-temperature node, while off) and `ExternalGround` read 0 K, so those temperatures are not exposed.
    - Setpoint groups:
      - `environment`: one `SEChangeEnvironmentalConditions`. It merges (Append); baselines are `environments/Standard.json`, which every shipped state uses. It includes the breathed-air temperature (`RespirationAmbientTemperature`, which drives respiration heat loss), which Pulse keeps separate from the ambient temperature. `CircuitModule.check_loaded` makes a state with another environment fail the load, because the first change would reset it.
      - `thermal_application`: one `SEThermalApplication`. Pulse replaces it whole; zero power with the applied temperature off removes it. The applied temperature is blended with ambient by its area fraction.
    - The StandardMale state is not thermally settled (skin 32.4 -> 30.0 °C over 30 min unperturbed), so tests compare against a parallel baseline run.
  - `supplemental_oxygen.py`: the `supplemental_oxygen` module, whole_body only.
    - 4 outputs under `oxygenation/`: FiO2, SpO2, PaO2, PaCO2. Device gas compartments are not exposed: the nasal cannula's pressure is NaN while it is off.
    - Setpoints `oxygen_connected` and `oxygen_flow_L_per_min`; device type from config `oxygen_device`.
    - Sent as `SESupplementalOxygen`: device `None` when disconnected (Pulse removes it), with wall supply (volume `inf`). A finite bottle would refill on every resend.
  - `points.py`: `cardiovascular_points` (circuit `FullCardiovascular`, 124 nodes, 212 paths) and `respiratory_points` (`Respiratory`, 24 nodes, 34 paths). whole_body only.
    - Pulse has no node/path data request. The module's `prepare_state(config, state)` (a `CircuitModule` hook used instead of static `outputs`) adds to the parsed state JSON:
      - a single-node compartment `VivaPointNode<node>` per node;
      - per path, compartments `VivaPointFrom/To<path>` joined by a link `VivaPointLink<path>`.
    - `PulseCircuitProcess` reads the state in `__init__` (`_read_state`) and loads the edited copy (`_load_state`, `serialize_from_string`).
    - Path flow is `Inflow - Outflow` of the dedicated target compartment (`Request.minus`: two Pulse requests, one output). Compartment flows come only from links, so the endpoint compartments' nodes don't affect it.
    - Selection: config `<circuit>_point_nodes` / `_point_paths`, empty = all. bigraph-schema leaves an unsupplied `[]`-default list out of `config`, so read them with `.get`.
    - Volume only where the state holds a finite one: non-compliant nodes have none, and `Ambient`'s is infinite (inf - inf would turn the delta store NaN).
    - Exact and bit-identical to runs without points (probe mode `points`; also with a hemorrhage and the ventilator, `test_point_reads_leave_the_simulation_unchanged`). Generators take `point_reads`.
    - Airway devices: every combined device circuit drops `EnvironmentToMouth`/`EnvironmentToNasalCavity` (the cannula drops only the nasal one; `SetupCircuitsAndCompartments.cpp:4362`), and a dropped path keeps its last flow. So when a module with `airway_device` is on the process, or the state's `AirwayMode` isn't Free, `respiratory_points` leaves out the circuit's paths that are missing from any circuit holding all its nodes. Naming one raises.
    - Points are the circuit as loaded; paths Pulse adds at run time (hemorrhage, `CardiovascularModel.cpp:1837`) aren't covered. All 21 shipped states have the same topology.
    - Construction reads the starting state (`_whole_body_state`: `state_file`, or the patient's cached state, stabilizing it if needed) when a points module is selected, so the install must exist at `__init__`. `tests/test_patients.py::test_point_reads_run_on_the_patient` guards that the points and the engine use the patient's state.
  - **One airway device.** Two connected devices (ventilator plus oxygen) make every advance fail ("Can only change airway mode from the Free mode"). `CircuitModule.airway_device` names each module's 0/1 connect port; `PulseCircuitProcess._check_airway` raises when two are connected, or when one connects in the update another disconnects (Pulse can process the new device first). Probe P9.
  - A request Pulse can't serve returns NaN, so the process fails the load instead of emitting it.
- `viva_pulse/patients.py`: `stabilized_state(patient_file)` returns the path of a whole-body state for any patient file, stabilizing at most once.
  - A bare name resolves to `<install>/bin/patients/<name>`; anything with a path separator is a path (relative to the working directory). Missing raises `FileNotFoundError`.
  - Cache key: sha256 over the patient file's bytes, `install_identity()` (Pulse's own `version()` and `git_hash()` plus the sha256 of the loaded `PyPulse` binary, which statically links Pulse, so any code change shows, plus the sha256 of the data files initialization reads, `DATA_DIRS`) and the model type. File `<stem>-<key>@0s.json` in `$VIVA_PULSE_CACHE_DIR`, else `platformdirs.user_cache_path("viva-pulse")/states`.
  - `stabilized_state(patient_file, modifiers=...)`: Pulse's configuration `Modifiers` (multipliers on a path's resistance/compliance baseline or a node's volume baseline, respiratory or active cardiovascular circuit, `ModifyCircuits`, applied before stabilization). Pulse's override replaces its modifier map wholesale (`PulseConfiguration::Merge`), so the final map is Pulse's own modifiers read from the patient's unmodified cached state, each requested name scaled (1 where absent), computed only on a miss. The key adds the requested map (as floats, sorted), which with the install identity fixes the override, so a hit never reads the unmodified state. A cold modified run stabilizes twice (about 25 s). `_check_whole_body_start` rejects multipliers that aren't finite numbers > 0 (Pulse stabilizes 0 and -1 into a nonphysical patient). The Python `PulseConfiguration` has no `Modifiers`, so `_stabilize` drives the `PyPulse.Engine` binding directly (`set_configuration_override` JSON). Never call `keep_log_messages(True)` on it: in this build it intermittently corrupts the heap during initialization (malloc SIGTRAP in `TuneCircuit`, 3/12 runs with vs 0/12 without). Tests: `tests/test_modifiers.py`.
  - A miss stabilizes the hashed bytes (a temporary copy) with `initialize_engine` (about 13 s), saves with `serialize_to_file` to a temporary file in the cache directory, reloads it as a check, then `os.replace`s it into place. Every Pulse bool return is checked. A hit loads in about 0.04 s.
  - Cached vs directly stabilized agree to 1e-6 relative after 30 s (tested), not bit-identically (JSON round trip). Tests set `VIVA_PULSE_CACHE_DIR` so they never touch the user cache.
- `viva_pulse/core.py`: `build_core()` registers the processes explicitly on an `allocate_core()` core, because discovery can miss editable installs. Tests and any `studies/*/sims/run.py` should use it.
- `viva_pulse/composites/hemorrhage.py`: `@composite_generator`s `pulse_hemorrhage` and `pulse_resuscitation` (`fidelity="real-bridge"`, `core_extensions=[register_processes]`). Store layout: `interventions/` (setpoints), `vitals/` (engine outputs), and a `RAMEmitter` step at `emitter`. `PulseProcess` runs at `interval: 1.0`, so a run of `N` simulated seconds emits `N + 1` rows, the first at t=0.
- `viva_pulse/composites/circuits.py`: `circuit_node()` / `circuit_emitter()` wiring helpers, `_setpoints()` (module baselines plus overrides, validated when the document is built), and the generators `pulse_cardiovascular`, `pulse_respiratory`, `pulse_mechanical_ventilation`, `pulse_thermal`, `pulse_supplemental_oxygen` and `pulse_whole_body_circuits`.
  - `pulse_whole_body_circuits` runs every whole-body module (`WHOLE_BODY_MODULES`) on one engine. Its flat parameters rely on setpoint and config names being unique across modules; a test enforces this. The two respiratory generators default to `ventilation_mechanics`. Store layout: `interventions/<module>/`, `circuits/<module>/`, `circuits/irreversible_state`, and `emitter`, which emits both subtrees.

## Workbench studies

The investigation `pulse-hemorrhage` (`workspace/investigations/`) groups three studies (`workspace/studies/<slug>/`, flat, as the workbench's own `/api/study-create` writes them): `hemorrhage-severity-sweep`, `fluid-resuscitation` and `patient-cohort`.
- Create and edit studies through the workbench API (`/viva-study`, `/viva-investigation`); narrative and pre-registration fields are YAML-direct, as the skills specify.
- Run them with `POST /api/investigation-run-unblocked {"investigation": "pulse-hemorrhage"}`. It queues `baseline[0]` plus every variant, so a study keeps one baseline and expresses other arms as variants; a variant may name its own `composite`. It passes no step count, so each baseline carries `n_steps: 600` in its params.
- The workbench runs `kind: sweep` only through v2ecoli-workflow, so a sweep is one variant per grid point (and the cohort one variant per `state_file`).
- The record is each study's `runs.db` (committed): `runs_meta` has the manifest (params, git sha, Python, package version), `history` the readouts. Only `readouts[].store_path` paths are recorded.
- Pass criteria are pytest files in `<study>/tests/` (run by `POST /api/study-tests-run`), using the shared `workspace/studies/conftest.py::latest` fixture (latest completed run per label). The auto-evaluator grades every YAML behavior test against every run, so per-arm and cross-run criteria can't live there.
- `check-observables` reports every `vitals.*` readout `not_in_structure`: it walks the generator's raw document, where `vitals/` is empty until the process's output wires fill it. `tests/test_studies.py` checks the readouts against the realized composite instead. Don't pre-fill `vitals/` in the document: document values override `initial_state()`.
- Figures: `viva_pulse/visualizations/` holds `Visualization` subclasses (the `as_visualization` decorator is deprecated in process-bigraph 1.10), registered by the env worker. A port gets one list per run in `runs.db`; a run's identity never reaches a Visualization (the workbench builds per-run parameter strings under `_run_labels`, but wires only declared ports, and an underscore port is a schema key), so labelled overlays use the study's `comparative_visualizations` (matched by `runs_meta.sim_name`), rendered at the end of an investigation run.
- The server rewrites study YAML (PyYAML default width) and adds derived blocks (`simulation_set`, `pipeline_gate`, `runs`, `last_test_run`) after runs and test runs.
- Rendered figures (`<study>/viz/`) are gitignored and regenerated: custom figures after each run (or `POST /api/investigation-render-viz {"name": <study>}`), comparative ones only at the end of an investigation run. `key_figures` and `embed_visualizations` point there.
- The workbench's computed gate (`pipeline_gate.gate_evaluator: blocked`, investigation `computed_verdict_status: in-progress`) can't see the pytest results, so it diverges from the authored `gate_status: passed` / `verdict_status: passed`. The authored values rest on the `/api/study-tests-run` results.
- The criteria were written after direct pilot runs (`workspace/experiments/_runs.yaml`, script and outputs under `workspace/experiments/pilot-2026-10-23/`). Pulse is deterministic, so criteria on pilot configurations are regression checks; each study's `preregistered.pilot` says which.
- Workbench issues found here are drafted in `upstream-issues/vivarium-workbench.md`.

## Tests

Nothing is mocked. Tests that need the engine drive the real Pulse build. The validation, controller and registry tests don't load the engine at all. `tests/conftest.py::run_composite` builds a generator's document on a fresh `build_core()` and returns `(sim, emitter rows)`. Engine loads are cheap (well under a second); the suite's runtime comes from simulated time, mostly the two 600 s runs in `test_resuscitation_controller_engages_and_preserves_volume` and the thermal tests (`tests/test_thermal.py`, about 60 s; Pulse runs about 35x real time and thermal effects need minutes of simulated time), and the three cold patient stabilizations in `tests/test_patients.py` (about 50 s together; the module shares one cache directory). In `tests/test_circuits.py` the expected values come from one of three places:
- a separate engine loaded directly through Pulse's API, with requests spelled out independently in `ORACLE` (`_direct_engine`);
- the actions active in Pulse's own serialized state (`_active_actions`);
- measured physiological effect thresholds, e.g. systemic resistance x2 drops HR by more than 15 bpm.

The new tests were checked against deliberately broken copies of the code in the scratchpad: per-group validation, and never forwarding a return to baseline.
