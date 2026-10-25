# viva-pulse

[![Documentation](https://readthedocs.org/projects/viva-pulse/badge/?version=latest)](https://viva-pulse.readthedocs.io/en/latest/)

A [process-bigraph](https://github.com/vivarium-collective/process-bigraph) wrapper that drives the **real** [Kitware Pulse Physiology Engine](https://gitlab.kitware.com/physiology/engine) (whole-body adult model). Pulse runs as a time-stepped `Process`. Interventions are input ports, vital signs are output ports, and simulations are ordinary `process_bigraph.Composite` documents. Nothing is reimplemented or mocked: every number comes from Pulse's C++ engine through its own Python bindings.

## Status

- **Available:**
  - processes: `PulseProcess`, `PulseCircuitProcess`, `MapFluidController`;
  - composites: `pulse_hemorrhage`, `pulse_resuscitation`, and the per-circuit composites `pulse_cardiovascular`, `pulse_respiratory`, `pulse_mechanical_ventilation`, `pulse_thermal`, `pulse_supplemental_oxygen`, and `pulse_whole_body_circuits`, which runs every module on one engine.
  - workbench studies: the investigation `pulse-hemorrhage` (a severity sweep, a fluid-resuscitation comparison and all 21 shipped patients); see [Studies in the workbench](#studies-in-the-workbench).

  All are tested against the real engine.
- **Not covered:** ECMO, the bag-valve mask, inhalers and the anesthesia machine. See [docs/plan/plan-circuit-composites.md](docs/plan/plan-circuit-composites.md).

## Requirements

Pulse has no PyPI release, so it is built from source.

- A Pulse source checkout at `../engine`, pinned to engine commit `5e29e5b13` (Pulse 4.4.0).
- CMake ≥ 3.31, a C++20 compiler, and a JDK (Pulse's data generation uses Java).
- [uv](https://docs.astral.sh/uv/) and CPython 3.12. `PyPulse` must be compiled against the same Python that runs this package.

## Setup

```bash
uv venv --seed --python 3.12 .venv      # --seed: the Pulse build pip-installs protobuf into this venv

# Configure and build Pulse into .pulse-build/install (gitignored). Takes a while the first time.
VIRTUAL_ENV=$PWD/.venv cmake --fresh -S ../engine -B .pulse-build \
  -DCMAKE_BUILD_TYPE:STRING=Release -DPulse_PYTHON_HOME_DIR=$PWD/.venv \
  -DPython3_FIND_VIRTUALENV=ONLY \
  -DPulse_JAVA_API=ON -DPulse_PYTHON_API=ON -DPulse_GEN_DATA=ON
VIRTUAL_ENV=$PWD/.venv cmake --build .pulse-build -j 12

uv pip install -r ../engine/requirements.txt
uv pip install -e '.[dev]'
```

`-DPython3_EXECUTABLE` is ignored by Pulse's CMake; the venv is selected with `-DPulse_PYTHON_HOME_DIR` together with `VIRTUAL_ENV`. Build pins and known workarounds are in [.build-progress.md](.build-progress.md).

**Never run `uv sync`.** The venv is assembled by hand, and a sync would resolve protobuf away from the version Pulse generated its bindings with. It would also remove the dev and engine requirements. Run everything with `uv run --no-sync`.

### Finding the Pulse install

`viva_pulse.runtime` uses the first of these that is set:
1. the `install_dir` process config;
2. `$PULSE_INSTALL_DIR`;
3. `.pulse-build/install`.

An explicitly given location that is not a valid install raises `PulseNotFoundError`; it never falls back to another location.

## Usage

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites.hemorrhage import pulse_resuscitation
from viva_pulse.core import build_core

core = build_core()   # registers viva-pulse's processes explicitly
doc = pulse_resuscitation(core, compartment="RightLeg", severity=0.8, target_map_mmHg=90.0)
sim = Composite({"state": doc}, core=core)
sim.run(600)          # 600 simulated seconds -> 601 emitted rows (first at t=0)
rows = gather_emitter_results(sim)[("emitter",)]
```

### Composites

| Generator | What it runs |
|---|---|
| `pulse_hemorrhage` | Untreated hemorrhage at a chosen compartment and severity. Emits vital signs every second. |
| `pulse_resuscitation` | The same hemorrhage plus a closed-loop IV fluid controller that targets mean arterial pressure. |
| `pulse_cardiovascular` | The cardiovascular circuit, including its renal and tissue branches. Emits pressure, volume, inflow and outflow for 32 vascular regions, plus 20 hemodynamic values. Driven by Pulse's resistance and compliance multipliers and a hemorrhage. |
| `pulse_respiratory` | The respiratory (airway) circuit, either alone in Pulse's ventilation-mechanics engine (default) or coupled in the whole-body engine. Emits 24 breathing-mechanics values plus pressure, volume, inflow and outflow for 8 lung and pleural regions. Driven by Pulse's 10 respiratory resistance and compliance multipliers and intubation. |
| `pulse_mechanical_ventilation` | The same, with a pressure-control mechanical ventilator connected, plus the ventilator's 18 monitor values. Defaults follow Kitware's HowTo: intubated, AC mode, 19/5 cmH2O, 12 breaths/min. Settings, including `connected`, can change mid-run. |
| `pulse_thermal` | The temperature circuit: core and skin joined to clothing, enclosure and ambient air. Emits core and skin temperature, sweat rate, metabolic rate, 8 heat-loss values, the environmental conditions as Pulse applies them, and temperature (7 regions) and heat flow (8 regions) for the thermal regions. Driven by the environment (air, radiant and breathed-air temperature, humidity, air speed, clothing) and by active heating, active cooling or an applied skin temperature. |
| `pulse_supplemental_oxygen` | Supplemental oxygen through a nasal cannula, simple mask or non-rebreather mask, from a wall supply, combined with the respiratory circuit. Emits breathing mechanics, lung regions, inspired oxygen fraction and arterial blood gases. Oxygen can be switched on and off, and its flow changed, mid-run. |
| `pulse_whole_body_circuits` | Every module on one whole-body engine: cardiovascular, respiratory, mechanical ventilator, thermal and supplemental oxygen, 269 readings per row. Takes every module's parameters; the ventilator and oxygen start disconnected. Shows effects that cross circuits, such as oxygen slowing the heart. |

All use `fidelity="real-bridge"`.

- **Point reads.** `point_reads=True` on `pulse_cardiovascular`, `pulse_respiratory`, `pulse_mechanical_ventilation` (these two with `model_type="whole_body"`) or `pulse_whole_body_circuits` adds every node and path of the circuit drawings. Each node, e.g. `LeftHeart1`, gets its pressure and, where it holds one, its volume. Each path, e.g. `Aorta1ToBone1`, gets its signed flow. They appear under `circuits/cardiovascular_points/` and `circuits/respiratory_points/`. In every shipped state, the cardiovascular circuit has 124 nodes and 212 paths, and the respiratory one 24 nodes and 34 paths. Two exceptions:
  - Paths Pulse adds during a run, such as a hemorrhage's bleed path, aren't included.
  - With a ventilator or oxygen module on the same engine, the two airway openings are left out, because Pulse stops solving them while a device is connected.

- **Whole-body runs** load Pulse's stabilized state files (`<install>/bin/states/*.json`, default `StandardMale@0s.json`).
- **Any other patient** runs on the whole body through `patient_file` instead of `state_file` (see [Any patient](#any-patient)). Setting both raises an error.
- **Ventilation-mechanics runs** have no state files. They start from a patient file (`<install>/bin/patients/*.json`, default `StandardMale.json`), then settle before t=0 until every requested value is defined, which takes about one breath. A `state_file` on ventilation-mechanics raises an error instead of being ignored.
- Setpoints apply from the first update. In `pulse_mechanical_ventilation`, the patient settles breathing spontaneously, so row 0 shows the ventilator monitor at 0 even though `interventions` say `connected=1`. The monitor values appear once the first ventilated breath completes, a few seconds in.
- In `AssistedControl` mode, a ventilator rate above the patient's own can lock Pulse into auto-triggering (about 50 breaths/min with high intrinsic PEEP). This is Pulse's own behavior and reproduces through its API alone. Use `ContinuousMandatoryVentilation` when the set rate must hold.

### Processes

- **`PulseProcess`**:
  - Loads a stabilized Pulse state (`state_file`, or any patient through `patient_file`) and advances the engine by `interval` seconds per update.
  - Inputs `hemorrhage_severity` and `iv_rate_mL_per_min` are setpoints, sent to Pulse as actions only when they change.
  - Outputs are nine vital signs plus an `irreversible_state` flag. Vitals are `float` ports carrying deltas, seeded with the loaded readings, so each store always equals Pulse's own value. The reason for this design is in `.build-progress.md`.
- **`PulseCircuitProcess`**: one real Pulse engine exposing the circuit modules named in `config.modules` (see `viva_pulse/circuits/`).
  - Each module's readings are a nested subtree of `float` delta ports. For example, `cardiovascular/central/aorta/pressure_mmHg` is wired to `circuits/cardiovascular/...`.
  - Its setpoints sit under the `setpoints` input port and are wired to `interventions/<module>/...`. Each defaults to its baseline (multipliers 1.0, hemorrhage 0.0) and is sent to Pulse only when it changes.
  - Identical requests from several modules share one Pulse request. A request Pulse cannot serve fails the load, or the update where it appears, instead of emitting NaN.
  - `model_type` selects the engine: `whole_body`, or `ventilation_mechanics`, which has the airway only (no blood or chemoreflex). Each module declares which engines it supports; `thermal`, `supplemental_oxygen` and the two `*_points` modules run on `whole_body` only.
  - The `cardiovascular_points` and `respiratory_points` modules read single circuit nodes and paths. By default they read every one. The config lists `cardiovascular_point_nodes` / `cardiovascular_point_paths` (and the `respiratory_` pair) narrow that to the names given. Pulse has no data request for a node or path, so before loading, the process adds a compartment for each node and a link for each path to the state, and reads them with ordinary requests. The simulation is unchanged (bit-identical with and without them).
  - Pulse allows one airway device at a time. A second one connecting makes every engine step fail, so the process raises instead: when the ventilator and oxygen are both connected, or when one connects in the same update the other disconnects. To switch devices, disconnect one update before connecting the other.
- **`MapFluidController`**: a proportional `Step` that maps mean arterial pressure to IV infusion rate.

### Any patient

Pulse ships stabilized states for 21 of its patients. To run any other patient on the whole-body engine, pass a Pulse patient file as `patient_file` (to `PulseProcess`, to `PulseCircuitProcess` with `model_type: whole_body`, or to any composite that takes `state_file`), and leave `state_file` at its default:

```python
doc = pulse_hemorrhage(core, patient_file="my_patients/Athlete.json", severity=0.5)
```

- A bare name (`"Gus.json"`) is a file in `<install>/bin/patients/`; anything containing a path separator is a path, relative to the working directory, so a patient in a subdirectory of `bin/patients/` needs its full path. A missing file raises `FileNotFoundError`. (On ventilation-mechanics, `patient_file` is resolved as before: a name or a path under `bin/patients/`, or an absolute path.)
- The first run stabilizes the patient with Pulse's own `initialize_engine` (about 13 s) and saves the result as a state file. Every later run of the same patient loads that file (about 0.04 s).
- The cache is keyed by the patient file's contents, the Pulse install (version, git hash, a digest of the `PyPulse` binary and a digest of the data files Pulse reads at initialization) and the engine type. Editing the patient file, changing Pulse's code or its data files makes a new state.
- The cache lives in `$VIVA_PULSE_CACHE_DIR` if set, otherwise in the user cache directory (`platformdirs.user_cache_path("viva-pulse")/states`, e.g. `~/Library/Caches/viva-pulse/states` on macOS). Deleting it is always safe.
- A run from the cache matches an engine stabilized directly from the same patient to within 1e-6 relative after 30 s. It is not bit-identical, because the state round-trips through JSON.
- `patient_file` defaults to `StandardMale.json`, and bigraph-schema treats a value equal to the default as unset, so `patient_file="StandardMale.json"` uses `state_file`. StandardMale ships a state anyway.

### Circuit modifiers

`circuit_modifiers` changes a circuit value before the patient is stabilized. It is Pulse's own configuration `Modifiers`. It maps a path or node name to a multiplier on the resistance or compliance of that path, or the volume of that node, as Pulse initializes it. It is accepted on the whole-body engine by the same processes and composites as `patient_file`:

```python
doc = pulse_cardiovascular(core, circuit_modifiers={"Aorta1ToBone1": 5.0})
```

- The result is a different patient, not a perturbation. Stabilization re-tunes the rest of the circulation to hold the patient's baselines. `Aorta1ToBone1` ×5 ends at ×4.35 after re-tuning, with cardiac output about 10% higher and MAP unchanged. To change values during a run, use the multiplier setpoints instead.
- Pulse already ships modifiers of its own (24 by default). A multiplier scales Pulse's value for that name (1 where it has none), and Pulse's other modifiers are kept.
- Names are paths or nodes of the respiratory circuit or the active cardiovascular circuit (`FullCardiovascular`). Pulse rejects anything else, and the load fails naming the modifiers. Multipliers must be finite and greater than 0.
- The modified patient is stabilized once and cached like any patient (see [Any patient](#any-patient)), with the modifiers in the cache key. The first run takes about 25 s: the unmodified patient is stabilized first, for Pulse's own modifiers. It starts from `patient_file` (default StandardMale), so a non-default `state_file` together with modifiers raises an error. It is whole_body only.

## Pulse circuits

Pulse models physiology as lumped-parameter circuits. `pulse_cardiovascular` exposes the cardiovascular circuit below. Its `central`, `renal` and `peripheral` sub-stores follow the diagram's branches.

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_cardiovascular
from viva_pulse.core import build_core

core = build_core()
sim = Composite({"state": pulse_cardiovascular(core, systemic_resistance_multiplier=2.0)}, core=core)
sim.run(60)
cv = gather_emitter_results(sim)[("emitter",)][-1]["circuits"]["cardiovascular"]
cv["central"]["aorta"]["pressure_mmHg"]
cv["hemodynamics"]["heart_rate_bpm"]   # about 43 bpm: the baroreflex answers doubled systemic resistance
```

Region readings are instantaneous within each heartbeat. Use `interval=0.02` (Pulse's timestep) to resolve waveforms; the default 1 s sampling aliases the cardiac cycle. Because process-bigraph accumulates time as floats, an interval that isn't exact in binary, such as 0.02, can lose the last update of a run: `run(2.0)` at 0.02 s emits rows up to t=1.98. Python can only reach regions (Pulse compartments), not individual circuit nodes or paths, because Pulse's bindings expose no node-level data requests.

![Pulse cardiovascular circuit](docs/images/circuit-cardio.png)

*Pulse cardiovascular circuit diagram. Copyright Kitware, Inc. and Contributors, Apache License 2.0, from `engine/docs/Images/Cardiovascular/CardiovascularCircuit.png`.*

### Respiratory circuit, alone or coupled

`pulse_respiratory` runs the same module on either engine. That shows how much of a response comes from the airway circuit itself and how much from the rest of the body:

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_respiratory
from viva_pulse.core import build_core

for engine in ("ventilation_mechanics", "whole_body"):
    core = build_core()
    doc = pulse_respiratory(core, model_type=engine,
                            left_compliance_multiplier=0.5, right_compliance_multiplier=0.5)
    sim = Composite({"state": doc}, core=core)
    sim.run(60)
    mechanics = gather_emitter_results(sim)[("emitter",)][-1]["circuits"]["respiratory"]["mechanics"]
    print(engine, round(mechanics["tidal_volume_mL"]), round(mechanics["respiration_rate_bpm"], 1))
# ventilation_mechanics 270 12.0   <- stiffer lungs, no compensation
# whole_body 388 15.0              <- the chemoreflex raises the breathing rate
```

Lung and pleural region pressures (`absolute_pressure_cmH2O`) are absolute, with Pulse's ambient at 1033.2 cmH2O. The `mechanics` pressures are relative to atmosphere. Intubation is one-way, because Pulse's Python API drops extubation actions; setting `intubated` from 1 back to 0 raises an error rather than leaving the store and the engine out of sync.

### Thermal circuit

`pulse_thermal` runs on the whole-body engine, where skin blood flow, shivering and sweating couple the temperature circuit to the rest of the body:

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_thermal
from viva_pulse.core import build_core

cold = dict(ambient_temperature_C=-10.0, mean_radiant_temperature_C=-10.0,
            respiration_ambient_temperature_C=-10.0, air_velocity_m_per_s=5.0)
for label, params in (("standard", {}), ("cold", cold)):
    core = build_core()
    sim = Composite({"state": pulse_thermal(core, interval=60.0, **params)}, core=core)
    sim.run(600)
    energy = gather_emitter_results(sim)[("emitter",)][-1]["circuits"]["thermal"]["energy"]
    print(label, round(energy["skin_temperature_C"], 1), round(energy["core_temperature_C"], 2))
# standard 31.1 37.07   <- the stabilized state still drifts: skin starts at 32.4
# cold 19.1 36.88
```

- **Time scale.** Skin responds within minutes; core temperature takes tens of minutes. Thirty simulated minutes take about a minute to run.
- **Compare against an unperturbed run.** Pulse's stabilized states aren't thermally settled: skin temperature drifts from 32.4 to 30.0 °C over 30 minutes with nothing changed.
- **Environment setpoints.** They change only the conditions they name; the atmosphere and ambient gases stay as they are. Pulse keeps the temperature of the air breathed separate from the ambient temperature, so set `respiration_ambient_temperature_C` as well for a change of air. Defaults are Pulse's `Standard.json` environment, which every shipped state uses; a state with a different environment fails the load, because the first change would reset it.
- **Heating and cooling.** Pulse delivers `power × area_fraction` as heat, so at the default fraction of 1.0 the power is the heat delivered. Returning every power to 0 with the applied temperature off removes the application. The applied temperature acts over the clothing, blended with the ambient temperature by its area fraction.
- **Regions.** `active` is the applied-temperature node; it carries heat only while an applied temperature is on. The reference nodes aren't exposed: `ExternalGround` reads absolute zero and `InternalGround` has no temperature.

![Pulse environment (external thermal) circuit](docs/images/circuit-environment.png)

*Pulse environment circuit, the external half of the temperature circuit. Copyright Kitware, Inc. and Contributors, Apache License 2.0, from `engine/docs/Images/Environment/EnvironmentCircuit.png`.*

### Every circuit on one engine

`pulse_whole_body_circuits` puts every module on one whole-body engine, so an intervention in one circuit shows up in the others:

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_whole_body_circuits
from viva_pulse.core import build_core

for label, params in (("room air", {}),
                      ("non-rebreather", dict(oxygen_connected=1.0, oxygen_device="NonRebreatherMask",
                                              oxygen_flow_L_per_min=10.0))):
    core = build_core()
    sim = Composite({"state": pulse_whole_body_circuits(core, interval=30.0, **params)}, core=core)
    sim.run(120)
    circuits = gather_emitter_results(sim)[("emitter",)][-1]["circuits"]
    print(label,
          round(circuits["supplemental_oxygen"]["oxygenation"]["arterial_oxygen_pressure_mmHg"]),
          round(circuits["cardiovascular"]["hemodynamics"]["heart_rate_bpm"], 1),
          round(circuits["respiratory"]["mechanics"]["respiration_rate_bpm"], 1))
# room air 91 71.9 12.0
# non-rebreather 563 65.9 14.2   <- more oxygen in the blood, a slower heart, faster breathing
```

- **Same readings as the single-module composites.** At baseline, each module's readings equal those from its own composite; the tests check this.
- **Supplemental oxygen comes from a wall supply.** Pulse also models a finite bottle that runs down, but every setpoint change resends the action, which would refill it, so the bottle isn't exposed.
- **Device readings aren't exposed.** Some return NaN while the device is off, so the oxygen module reports oxygen delivery through the inspired fraction and the arterial blood gases.

## Studies in the workbench

This repo is a [vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench) workspace, so its composites appear in the workbench's catalog and run as studies. The workbench is installed in `.venv` (pinned in `pyproject.toml`) and must be served from there, because runs execute in the server's environment and only `.venv` can import PyPulse:

```bash
.venv/bin/vwb serve --detach          # prints the dashboard URL; state in .pbg/server/
URL=$(jq -r .url .pbg/server/server-info)
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"investigation": "pulse-hemorrhage"}' $URL/api/investigation-run-unblocked    # every run, ~10 min
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"study": "patient-cohort"}' $URL/api/study-tests-run                           # a study's criteria
```

The investigation `pulse-hemorrhage` (`workspace/investigations/`) has three studies (`workspace/studies/`). Every run is recorded in the study's `runs.db`: its parameters, the git commit, the Python version, and the readouts at every simulated second. Each study's pass criteria are the pytest files in its `tests/` directory, fixed before the canonical runs. They were written after direct pilot runs, recorded in `workspace/experiments/_runs.yaml`; the pilots overlap some canonical configurations, and Pulse is deterministic, so those criteria are regression checks rather than predictions.

| Study | What it varies | Result (StandardMale unless stated, right-leg bleed, 10 min) |
|---|---|---|
| `hemorrhage-severity-sweep` | Severity 0, 0.2, 0.4, 0.6, 0.8, 1.0 | Blood lost 0 / 386 / 823 / 1241 / 1577 / 1793 mL, heart rate 71 / 76 / 88 / 98 / 107 / 110 per min. MAP stays within 1.1 mmHg of its start (95.3) up to severity 0.4, then falls to 87.9 / 84.1 / 78.1 mmHg. |
| `fluid-resuscitation` | Untreated; MAP-targeted infusion of saline or whole blood | Both treated arms end with 78 mL more blood volume and 2.2 mmHg more MAP than untreated. The controller only starts at 508 s and delivers 79.6 mL, so saline and whole blood can't be told apart within 10 minutes. |
| `patient-cohort` | All 21 patient states shipped with Pulse | Every patient loses blood volume and MAP and raises heart rate. Absolute loss (1094 to 1755 mL) varies much less than starting blood volume (2.9 to 7.1 L), so smaller patients lose a larger fraction: 23.8% (Overweight) to 38.1% (Underweight), Spearman ρ = −0.91 against starting blood volume. |

- **Sweeps are one variant per value.** The workbench runs `kind: sweep` only through its v2ecoli workflow, so each severity (and each patient) is its own variant.
- **Figures.** `viva_pulse/visualizations/` adds the severity response and the cohort scatter. The labelled time courses (per arm, per patient) are the studies' `comparative_visualizations`, rendered at the end of an investigation run into each study's `viz/`.
- **Known workbench limits** (drafted for upstream): `check-observables` and the report lint flag every `vitals.*` readout as not emittable, because they inspect the generator's document before the process fills `vitals/`; `tests/test_studies.py` checks the readouts against the running composite instead. The workbench's computed gate also reads only YAML behavior tests, so it shows these studies as blocked even though every pytest criterion passes.

## Documentation

The user documentation (Sphinx, in `documentation/`) covers installation, the processes and circuits, four tutorials, running studies in the workbench, the study results, and the API reference. Its tutorials run against the real engine while it builds, so every number on its pages is current. It is published at [viva-pulse.readthedocs.io](https://viva-pulse.readthedocs.io/en/latest/), where the tutorials show their code only (Read the Docs can't build Pulse). Build it locally to run them and open it in your browser:

```bash
make docs        # installs the docs group if needed, does a fresh build (about a minute), opens it
```

## Tests

```bash
uv run --no-sync pytest -q
```

The full suite takes about 225 s, most of it simulated time in the thermal, whole-body and resuscitation tests. Every engine-dependent test drives the real Pulse build; nothing is mocked. Where a test needs an expected value, it loads its own engine directly through Pulse's Python API.

---
## Regarding...

### ...Using the Python binding

The existing Pulse python binding (`src/python/*`) is a light wrapper, not a 1:1 binding. There are two layers:
  
1. The compiled part (PyPulse, built with pybind11) is thin. It exposes one engine handle with about 15 methods (src/python/pybind/PulseEngines.cpp:18-44):
   load or save state, initialize, process actions, advance time, pull data, and logs/events. Everything crossing that boundary is a JSON or protobuf string,
   or a flat array of numbers. None of the C++ internals are reachable as objects: no circuits, nodes, paths, compartments, models or solver.
2. The pulse Python package is a pure-Python copy of Pulse's data model, not of the engine. It has classes for actions, patients, configurations, data requests
   and scalars with units. Your Python objects get serialized to the same protobuf format and handed to the C++ engine. That copy is broad but incomplete.
   Anesthesia-machine and inhaler actions are missing, for example, as is the circuit-override action.

So Python can do what a scenario file can: load a patient, apply actions, step time, and read named values (whole-body vitals, region pressures, volumes, flows
and substances). It can't reach inside the engine. Single nodes and paths are still readable, because a state file names Pulse's compartments and links, and a
compartment can hold one node and a link one path; the `*_points` modules add those before loading (see "Point reads" above). What stays out of reach
without new pybind bindings in ../engine is changing the model itself: rewiring circuits, or running the cardiovascular circuit on its own. The scope is in
`docs/plan/plan-circuit-level-access.md`.

## ...Electrical circuits

An easy way to visualize this is the water pipe analogy:
- **Voltage** is the water pressure pushing through the pipe.
- **Current** is the actual volume of water flowing per second.
- **A Resistor** is a narrow restriction or squeeze in the pipe.

---

## License

viva-pulse is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)). Pulse is distributed by Kitware, Inc. under the Apache License 2.0; see `../engine/LICENSE` and `../engine/NOTICE`.

