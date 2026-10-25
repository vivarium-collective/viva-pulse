# Processes

viva-pulse has three process-bigraph components. Register them on a core with
`viva_pulse.core.build_core()`, which registers them explicitly, because process-bigraph's
automatic discovery can miss editable installs.

## `PulseProcess`: whole-body vital signs

Loads a stabilized Pulse state (default `StandardMale@0s.json`) the first time it's used, then
advances the engine by `interval` seconds per update. To start from a patient Pulse ships no
state for, set `patient_file` instead of `state_file` (see [Any patient](#any-patient)).

- **Inputs** `hemorrhage_severity` and `iv_rate_mL_per_min` are setpoints, sent to Pulse as
  actions only when they change. The bleed site is the `hemorrhage_compartment` config and the
  infused fluid the `iv_compound` config (a compound Pulse ships, such as `Saline` or `Blood`;
  an unknown one fails when the engine loads).
- **Outputs** are nine vital signs plus an `irreversible_state` flag.

The vital-sign outputs are delta ports. `initial_state()` seeds each store with the reading
Pulse loaded, and every update emits the change since the last one, so the store always
equals Pulse's own value. This is deliberate: process-bigraph discards `initial_state()`
values on `overwrite[float]` and `boolean` output ports, which would make the first row zero.

Once Pulse reports an irreversible state, the process stops advancing the engine and its
updates return nothing, so the vitals keep their last reading while time continues.

## `PulseCircuitProcess`: circuits, region by region

One real Pulse engine exposing the circuit modules named in `config.modules` (see
{doc}`circuits`).

- Each module's readings form a nested subtree of delta ports, for example
  `cardiovascular/central/aorta/pressure_mmHg`.
- Its setpoints sit under the single input port `setpoints`, for example
  `setpoints/cardiovascular/hemorrhage_severity`. Each defaults to its baseline (multipliers
  1.0, no bleed), so an omitted setpoint never becomes 0.
- Identical requests from several modules share one Pulse request. A request Pulse can't serve
  returns NaN, so the process fails the load, or the update where it appears, instead of
  emitting NaN.
- `model_type` picks the engine. `whole_body` loads a `state_file`, or any patient through
  `patient_file` (see [Any patient](#any-patient)); setting both raises an error.
  `ventilation_mechanics` (airway only) has no state files: it starts from a `patient_file`
  and settles, in one-second steps, until every requested value is defined. A `state_file`
  on it raises an error.

Inputs and outputs use different top-level names on purpose: process-bigraph projects
`initial_state()` through input wires too, so a shared name would copy readings into the
setpoint store.

## Any patient

Pulse ships stabilized states for 21 of its patients. Any other Pulse patient file runs on
the whole-body engine through `patient_file`, on `PulseProcess`, on `PulseCircuitProcess`
with `model_type: whole_body`, and on every composite that takes `state_file`. Leave
`state_file` at its default; setting both raises an error.

- A bare name (`"Gus.json"`) is a file in `<install>/bin/patients/`. Anything containing a path
  separator is a path, relative to the working directory, so a patient in a subdirectory of
  `bin/patients/` needs its full path. A missing file raises `FileNotFoundError`. (On
  `ventilation_mechanics`, `patient_file` is resolved under `bin/patients/` as before.)
- The first run stabilizes the patient with Pulse's own `initialize_engine` (about 13 s) and
  saves the result as a state file. Every later run of the same patient loads that file
  (about 0.04 s). {mod}`viva_pulse.patients` does this.
- The cache key covers the patient file's contents, the Pulse install (version, git hash, a
  digest of the `PyPulse` binary and a digest of the data files Pulse reads at
  initialization) and the engine type. Editing the patient file, changing Pulse's code or its
  data files makes a new state.
- The cache lives in `$VIVA_PULSE_CACHE_DIR` if set, otherwise in `states/` under the user
  cache directory (`~/Library/Caches/viva-pulse` on macOS, `~/.cache/viva-pulse` on Linux).
  Deleting it is always safe.
- A run from the cache matches an engine stabilized directly from the same patient to within
  1e-6 relative after 30 s. It is not bit-identical, because the state round-trips through
  JSON.
- `patient_file` defaults to `StandardMale.json`. bigraph-schema treats a value equal to the
  default as unset, so `patient_file="StandardMale.json"` uses `state_file`; StandardMale
  ships a state anyway.

## Circuit modifiers

`circuit_modifiers` changes a circuit value before the patient is stabilized. It is Pulse's own
configuration `Modifiers`, accepted on the whole-body engine wherever `patient_file` is. It maps a path or node
name to a multiplier on the resistance or compliance of that path, or the volume of that node,
as Pulse initializes it:

```python
doc = pulse_cardiovascular(core, circuit_modifiers={"Aorta1ToBone1": 5.0})
```

- The result is a different patient, not a perturbation. Stabilization re-tunes the rest of
  the circulation to hold the patient's baselines. `Aorta1ToBone1` ×5 ends at ×4.35 after
  re-tuning, with cardiac output about 10% higher and MAP unchanged. To change values during a
  run, use the multiplier setpoints instead.
- Pulse ships modifiers of its own (24 by default). A multiplier scales Pulse's value for that
  name (1 where it has none), and Pulse's other modifiers are kept.
- Names are paths or nodes of the respiratory circuit or the active cardiovascular circuit
  (`FullCardiovascular`). Pulse rejects anything else, and the load fails naming the modifiers. Multipliers must be finite and greater than 0.
- The modified patient is stabilized once and cached like any patient, with the modifiers in
  the cache key. The first run takes about 25 s: the unmodified patient is stabilized first,
  for Pulse's own modifiers. It starts from `patient_file` (default StandardMale), so a non-default
  `state_file` together with modifiers raises an error. Whole-body only.

## Circuit additions

`circuit_additions` adds resistance paths to the cardiovascular circuit of the loaded state,
for example an arteriovenous shunt. It is accepted wherever `circuit_modifiers` is:

```python
doc = pulse_cardiovascular(core, circuit_additions={
    "Shunt": {"source": "Aorta1", "target": "VenaCava1", "resistance_mmHg_s_per_mL": 0.5}})
```

- An addition is a perturbation of the loaded patient, not a new patient: nothing is
  re-stabilized, and the body responds over time. This shunt carries about 150 mL/s, and at
  60 s MAP is 73 mmHg (from 95), HR 135 bpm (from 72) and CO 10.5 L/min (from 5.8).
- Pulse solves a path in its circuits but moves substances only over its compartment graph,
  so each addition also gets a compartment link. Without it, blood would move along the path
  without its substances (arterial PO2 334 mmHg).
- Accepted: a resistance path (finite, > 0) between two `FullCardiovascular` nodes in
  different vascular compartments, meaning in both Pulse's `Cardiovascular` and
  `ActiveCardiovascular` graphs, except `AbdominalCavity`. Anything else (`Ground`, tissue
  fluid, lymph, renal and urinary compartments, one compartment) raises when the process is
  built. Path removal is never supported (Pulse crashes).
- In the state, the addition `Shunt` becomes path and link `VivaAddedShunt`, so a name Pulse
  creates at run time (e.g. `AortaHemorrhage`) can't take it over. With `point_reads` it is
  read like any other path; it reads 0 at load, before the first solve.
- The joined compartments' regional flows include the added path. Its resistance is fixed:
  the resistance multipliers and vascular tone don't scale it. A hemorrhage on a compartment
  the path feeds is larger, because Pulse sizes a bleed from the compartment's inflow.
- Whole-body only. It combines with `patient_file` and `circuit_modifiers`. The process reads
  that state when it is built.

## `MapFluidController`: a closed-loop Step

A proportional controller. It sets the IV infusion rate to
`gain_mL_per_min_per_mmHg × (target_map_mmHg − MAP)`, clipped to
`[0, max_rate_mL_per_min]`. It is a process-bigraph `Step` that reads one store and writes
another, so the same pattern gives any closed-loop controller: read a circuit's outputs, write
its setpoints. {doc}`../tutorials/01-hemorrhage-and-resuscitation` runs it.
