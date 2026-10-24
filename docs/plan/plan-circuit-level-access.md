# Plan: circuit-level access (agenda item 7)

**Status:** scoped 2026-10-24 (Phase 1 of [plan-whats-missing-I.md](plan-whats-missing-I.md)), after an adversarial review whose findings were each re-probed before being applied. Nothing is implemented. Each capability below is a separate decision for the user.

Item 7 of the `post-initial-wrapping` agenda asks for four capabilities:
- read individual points of a circuit drawing (for example `LeftHeart1`), not just regions;
- change a circuit's wiring;
- run circuits as truly separate models;
- start from any patient instantly.

Every result below comes from a real-engine run of
[`probe_circuit_access.py`](../../workspace/experiments/circuit-access-2026-10-24/probe_circuit_access.py).
Its output is [`probes.jsonl`](../../workspace/experiments/circuit-access-2026-10-24/probes.jsonl), and the run is recorded in `workspace/experiments/_runs.yaml` (id `circuit-access-2026-10-24`).
- Engine: Pulse `REL_4_4_0` (`5e29e5b13`), state `StandardMale@0s.json`.
- Environment: `.venv`, protobuf 7.35.0 (upb).
- Wall times are from an Apple M3 Max.
- Flows are means over 25-30 s, sampled every 0.1 s (several cardiac cycles), because instantaneous flow swings about 40% with cardiac phase.

To reproduce:

```
for m in reads virtual edit modifier add remove patient hemo; do
  uv run --no-sync python workspace/experiments/circuit-access-2026-10-24/probe_circuit_access.py $m
done
```

## Results

### Reading nodes and paths (P-a)

| Question | Answer | Mode |
|---|---|---|
| Can data requests read a single node or path? | **Yes, with no engine change.** Pulse has no circuit request category (`Engine.proto:47-64`). But a compartment is only a named set of nodes, and a link is a named path. Single-node compartments (`V<node>`) and one link appended to the state's `CompartmentManager` before loading are served by ordinary `create_liquid_compartment_request`s. Pressures for LeftHeart1/2/3, Aorta1/2 and Bone1, the link's flow (target `Inflow`), and the node volume all equal the serialized node and path values, with a difference of **0.0** at 0.5, 1.37 and 30 s. Vitals at 30 s are **bit-identical** to the unedited state. `pull_data` costs about 0 ms. | `virtual` |
| Can the full state be read instead? | Yes, exactly, through `serialize_to_string` (JSON). Node pressures equal compartment requests for 12 single-node compartments, 10 of them nonzero (max difference 0.0). It costs **29 ms** per call for a 2.5 MB state. One advance takes 26.6 ms per 1 s step and 0.51 ms per 0.02 s step. | `reads` |
| Is a missing `Value` zero or unset? | A property that is present without a `Value` is 0.0, because proto3 JSON leaves zeros out (`Properties.proto:85-90`). An invalid property is left out entirely: `PBProperty::Unload` returns null when `!IsValid()` (`PBProperties.cpp:1315-1321`). The census follows. | `reads` |
| Which properties exist? | **Per node and per path, not uniform.** 12 of 194 nodes have no `Pressure`: the 10 ECMO nodes plus `NasalCannula` and `NasalCannulaOxygenSource`. **25 of the 52 cardiovascular nodes have no `Volume`** (non-compliant nodes, e.g. LeftHeart2/3, Aorta2-4, every tissue `*2`). All cardiovascular paths have `Flow`, while 74 of 323 paths overall don't. | `reads` |
| Binary state or pickling? | **Both fail from Python.** The binding returns a `std::string` (`PhysiologyEngineThunk.h:32`, bound at `PulseEngines.cpp:25`), and pybind11 decodes it as UTF-8. So binary `serialize_to_string` and `pickle.dumps(engine)` (`PulseEngine.__getstate__`, `PulseEngine.py:120-121`) both raise `UnicodeDecodeError`. | `reads` |

### Changing values (P-b)

| Question | Answer | Mode |
|---|---|---|
| Does an edit of a path's current resistance in the state stick? | **No.** Every step, the circuit calculator resets each path's Next values to its baselines (`SECircuitCalculator.cpp:1144-1150`). So `Aorta1ToBone1` x5 on `Resistance` and `NextResistance` reads 13.57 again after 1 s. | `edit` |
| Editing the baseline in the state? | **Sticks, as a perturbation of an already stabilized patient.** `ResistanceBaseline` x5 gives R 67.82 at 1 s and 65.26 at 30 s; something still rescales it, likely the baroreflex (`CardiovascularModel.cpp:672` puts this path in the systemic resistance set). Mean bone flow falls 4.65 -> 1.11 mL/s. The run is a transient, not a steady state: HR 72.04 -> 68.29, MAP 95.26 -> 95.81 over 30 s. | `edit` |
| Pulse's own per-path modifiers? | **Work, as a re-stabilized patient.** `PulseConfiguration` has `Modifiers` (`Configuration.proto:201`), applied before stabilization by `ModifyCircuits` (`Controller.cpp:558-563`). Pulse already ships 24 defaults, including 1.02 on `Aorta1ToBone1`. | `modifier` |

Details of the modifier route:
- **The override replaces the map wholesale** (`PulseConfiguration::Merge`, `PulseConfiguration.cpp:430-435`), so it must carry Pulse's defaults. Every shipped state records them in `Configuration.Modifiers`.
  - Resending those defaults reproduces the unmodified initialization exactly.
  - Sending `{Aorta1ToBone1: 5}` alone drops the other 23: CO falls 5779 -> 4189 mL/min.
- With the defaults plus `Aorta1ToBone1` x5 (1.02 -> 5.1), initialization succeeds. Stabilization then re-tunes the circulation to the patient's baselines:
  - the path's baseline ends at 58.97 (x4.35, not x5);
  - MAP stays 95.29;
  - CO rises 5779 -> 6356 mL/min;
  - the steady state holds at 30 s.
- An unknown path name fails `initialize_engine`. Pulse validates names itself.
- Gap: the Python `PulseConfiguration` exposes only 4 fields and no `Modifiers`. The probe passes the JSON to the binding's `set_configuration_override` through `PulseEngine`'s private handle (`_PulseEngine__pulse`).

### Changing wiring (P-c)

| Question | Answer | Mode |
|---|---|---|
| Can a path be added? | **Yes, and the solver uses it.** The new path `Aorta1 -> VenaCava1` (R 0.5 mmHg·s/mL) was added to the `Cardiovascular` and `FullCardiovascular` circuits. It carries a mean flow of 122.2 mL/s, and the body responds as to an arteriovenous shunt: at 30 s, MAP 95.26 -> 68.33, HR 72.04 -> 168.48, CO 5.78 -> 10.22 L/min, blood volume unchanged. **No compartment link maps it** (0 links), so compartment-level flows, and anything built on the compartment graph, don't see it. | `add` |
| Can a path be removed? | **No: it segfaults.** Removing `Aorta1ToBone1` alone loads with a logged, non-fatal error (`Link is mapped to circuit path, Aorta1ToBone1, but provided circuit manager did not have that path`, `PBCompartment.cpp:378-382`). Removing its link `AortaToBone` and the graph entries too loads with no error. Both crash on the first 0.02 s advance (exit -11): the models hold the path by name, and `SECircuit::GetPath` returns null (`SECircuit.cpp:254-262`). | `remove` |

### New patients (P-d) and separate circuits (P-e)

| Question | Answer | Mode |
|---|---|---|
| How long does a new patient take? | **13.2 s**, not minutes. That is `initialize_engine` for an unshipped patient: StandardMale with age 30, 190 lb, HR baseline 64. Saving it takes 0.024 s (`serialize_to_file`) and reloading 0.040 s; a shipped state loads in 0.043 s. After 60 s the cold and reloaded engines agree to a relative difference of 3.7e-10 (not bit-identical). Patients with chronic conditions stabilize longer; that wasn't measured. | `patient` |
| Is a cardiovascular-only engine reachable? | **No; the route is Pulse drafts #1 and #2.** Python's `eModelType` has `HumanAdultHemodynamics`, but the pybind enum and `PulseEngine.__init__` don't map it. Through an int cast it initializes, then segfaults on its first 0.02 s advance (exit -11), the null-ECG crash in draft #1. Respiratory is already separate (`ventilation_mechanics`). | `hemo` |

## What this means for each capability

### 1. Read individual points: feasible now, native, free

**Design.** A circuit module whose outputs are ordinary `Request`s on read-only compartments and links that the process adds to the state before loading.

- Each named node becomes a single-node compartment, and each named path a link between two such compartments.
- Port layout (ports, under the module; the store is `circuits/<module>/`):
  - `<module>/nodes/<Node>/pressure_mmHg`;
  - `<module>/nodes/<Node>/volume_mL`, on compliant nodes only;
  - `<module>/paths/<Path>/flow_mL_per_s`.
- It reuses the existing request, unit, delta and NaN-fails-load machinery unchanged, and works at any interval.
- Names and per-property availability come from the loaded state's `CircuitManager` (25 of 52 cardiovascular nodes have no volume), never from a hand-written list.
- Before loading, the added compartment names are checked for collisions with Pulse's own.
- Serialization stays a discovery tool for listing nodes, paths and topology, not the per-step read path.

**To verify during implementation:**
- what a `Volume` request returns on a node without volume (it must fail the load, as NaN does);
- link flow on a path whose source and target nodes belong to different circuits.

**Open decision.** Node selection: an explicit list, or curated groups per drawing.

**Constraint.** This needs the state to be edited before load, so it applies to `whole_body` (state files). `ventilation_mechanics` initializes from a patient file and would need the same compartments added to its initialization route, which hasn't been probed.

### 2. Change values: two native routes with different meanings

| Route | Meaning | Mechanics | Status |
|---|---|---|---|
| Configuration `Modifiers` at initialization | A different patient, re-stabilized with the change. Pulse re-tunes other paths to hold the patient's baselines (x5 requested gave x4.35 and CO +10%). | Initialize with Pulse's defaults plus the scaled entries. Cache the result as in capability 4, keyed on the modifiers too. Pulse validates the names. | Works. Python lacks a `Modifiers` field, so it goes through the binding's JSON `set_configuration_override` (a Pulse-side gap, external). |
| Baseline edit in the state before load | A perturbation of the stabilized patient, observed while the body responds. | Multiply `ResistanceBaseline` / `ComplianceBaseline`, plus current and Next, in the state JSON, then `serialize_from_string`. | Works for the one systemic path probed. A compliance path and a non-systemic path are not yet probed. |

The choice between them is the user's: "what if this patient had it" or "what happens when it changes".
- Mid-run changes would need a state round trip per change (29 ms to serialize plus a reload). Their interaction with later modifier actions isn't probed.
- The existing `SECardiovascularMechanicsModifiers` setpoints already cover group-level changes during a run.

### 3. Change wiring: additions partly, removals never

- **Additions** are solved, but the compartment graph doesn't see them. A complete addition would also need a `LiquidLink` and a `LiquidGraph` entry. Whether substance transport then follows has not been probed. Recommendation: allow additions only together with a link, after a transport probe.
- **Removals** must be refused before loading. A removal crashes even when the link and graph entries are removed too. The models hold paths by name across many sources (7 physiology models call `GetPath`, besides the equipment models). So the only safe rule is to never remove a path that ships with Pulse.

### 4. Truly separate circuits: blocked outside this repo

- A separate cardiovascular circuit needs Pulse fixes #1 (null ECG) and #2 (no pybind enum value or `PulseEngine` mapping). Both are in `upstream-issues/pulse.md`, and both are external work.
- Respiratory is already separate.
- On whole_body the circuits share one engine by design: four solves coupled by lagged exchange (`plan-circuit-composites.md`).

### 5. Any patient instantly: feasible now, native

**Design.** On whole_body, accept a `patient_file` (today it's rejected there).

- On first use, `initialize_engine` stabilizes it (about 13 s here).
- The result is saved with `serialize_to_file` to a cache keyed by the patient file's content hash, any configuration modifiers, and the Pulse version.
- Every later load takes about 0.04 s.

**Open decisions.**
- Where the cache lives: user cache directory or workspace.
- Whether to allow patient files outside `bin/patients/`.

**Test.** A cold and a cached engine, compared after an advance, within a stated relative tolerance (the probe saw 3.7e-10 at 60 s), with every load's return value asserted.

## Recommended order

1. Point reads (1): native, free, and covered by existing contracts.
2. Instant patients (5): small and independent. It is also the base for the modifier route (2).
3. Value changes (2), after the user picks the meaning.
4. Path additions (3), only after the link and transport probe. Removals stay refused.

Separate cardiovascular (4) waits on Kitware.

New Pulse findings, not yet drafted (external, for the user to decide on):
- binary `serialize_to_string` and pickling a `PulseEngine` raise `UnicodeDecodeError`;
- the Python `PulseConfiguration` doesn't expose `Modifiers` or `Overrides`.
