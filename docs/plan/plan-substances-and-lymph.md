# Plan: substance and tissue outputs (#35) and the lymphatic compartment (#36)

**Status:** **approved** 2026-11-01 with every recommended option (D1a-D6a, section 5), after an adversarial review (section 8) whose findings were each re-probed before being applied. **Implemented** on branch `feat/substances-and-lymph` (diff reviewed, section 10; full suite on Linux, section 9). Awaiting the Mac test run and the user's go-ahead to push.

Issues: [#35](https://github.com/vivarium-collective/viva-pulse/issues/35) (expose substance and tissue quantities) and [#36](https://github.com/vivarium-collective/viva-pulse/issues/36) (report the lymphatic compartment). The user asked for both on one branch and one PR (2026-11-01).

Every result below comes from [`probe_substances_lymph.py`](../../workspace/experiments/substances-lymph-2026-11-01/probe_substances_lymph.py). Its output is [`probes.jsonl`](../../workspace/experiments/substances-lymph-2026-11-01/probes.jsonl), one line per mode, and the run is recorded in `workspace/experiments/_runs.yaml` (id `substances-lymph-2026-11-01`).
- Engine: Pulse `REL_4_4_0` (`5e29e5b13`), state `StandardMale@0s.json`.
- **Platform: Linux x86_64**, not the usual macOS arm64 build. The user's Mac was reachable only through a small Linux VM that can't run the Mac build, so the same engine pin was built in a cloud workspace (JDK 21, CMake 4.0.3, GCC 13, CPython 3.12.12, protobuf 7.35.0, process-bigraph 1.10.1 and bigraph-schema 1.8.3, as on the Mac). Two downloads were blocked there: Eigen 5.0.1 came from the Mac build tree (`.pulse-build/External/Eigen3/install`, header-only) and pybind11 3.0.4 from PyPI (`-DUSE_SYSTEM_Eigen3=ON`, `-DUSE_SYSTEM_pybind11=ON`).
- Canary: StandardMale reads HR 72.05, MAP 95.25 and BV 5487.3 at load and after 10 s, the macOS anchors.
- The full suite must also pass on the Mac before the PR (section 7).

To reproduce: `for m in lymph reads mass observer invalid recheck; do uv run --no-sync python workspace/experiments/substances-lymph-2026-11-01/probe_substances_lymph.py $m; done`

## 1. Findings: lymph (#36)

| Question | Answer | Source |
|---|---|---|
| Is the `Lymph` compartment served? | Yes. Pressure, Volume, Inflow and Outflow requests all return numbers. | mode `lymph` |
| Does lymph carry flow? | **No. Pulse 4.4.0's lymphatics carry no flow.** Inflow and Outflow stay below 1.7e-9 mL/min (solver noise) at every sample (0, 1, 10, 60, 300 s) in all three arms: unperturbed, a RightLeg 0.8 hemorrhage (blood volume 5487 -> 4656 mL) and a 250 mL/min saline infusion (5487 -> 6749 mL). The serialized `LymphToVenaCava1` flow is about 4e-12 mL/s; the 13 tissue-to-lymph paths have no flow value at all (zero). | mode `lymph`; serialized circuit |
| Why? | Each `<Tissue>T1ToLymph` path is a **flow source with baseline 0** (`GetFlowSourceBaseline().SetValue(0.0, ...)`), and nothing in the engine ever sets it: the only references to the lymph paths are in circuit setup. | `SetupCircuitsAndCompartments.cpp:2104-2118, 2254-2255, 2301-2302, 2348-2349, ...`; `grep` over `src/cpp/engine` |
| What is its pressure? | The vena cava's. `LymphToVenaCava1` has no resistance (setup comment: "if it goes to lymph then it goes to vena cava"), so the `Lymph` node's pressure equals `VenaCava1`'s exactly (4.798676 at load, 4.637747 at 7 s). The 3.56-6.62 mmHg range in the arms is central venous pressure. | `SetupCircuitsAndCompartments.cpp:2110-2111`; modes `lymph`, `recheck` |
| Volume? | 0.0: the node's `VolumeBaseline` is 0. | `SetupCircuitsAndCompartments.cpp:2107`; mode `lymph` |
| Substances? | Every substance quantity in `Lymph` reads 0 (Albumin and Sodium concentration). `Lymph` is in **none** of the 9 liquid graphs, so Pulse's transport never moves substances into it. | modes `lymph`, `recheck` |
| Is lymph mass counted in whole-body totals? | No. `MassInBody` sums Pulse's vascular leaf compartments plus the tissues' extra- and intracellular ones; `Lymph` is in neither list. | `BloodChemistryModel.cpp:343-352`; `PulseEngine.h` `VascularCompartment` |

**History.** The stub predates Pulse: the first Pulse commit (`b8d1dd54f`, 2017-04-19, "Initial Organization", forked from BioGears) already has the lymph node and the zero flow sources in `engine/cpp/Controller/BioGears.cpp`, and nothing in that commit's tissue or cardiovascular systems uses them. BioGears built an active lymph model later, in Oct-Nov 2018 (`biogears/core` commits `82bcfed2` to `0cb04d07`; `7cd52e31`: "Extracellular to Lymph paths added to all tissues (pressure sources) ... lymph flow of 3.6 L/day"), as part of a redesigned tissue circuit with oncotic pressure sources, pre-lymphatic nodes and valves, a 2 L lymph compliance and albumin convection; BioGears 8.2.0 still has it. Pulse never took it up. Pulse's methodology calls its lymph "not a physiological model ... only ... an accessory return for interstitial fluid" (`CardiovascularMethodology.md:31`).

**This corrects issue #36 itself**, which said Pulse "moves substances along the lymph links" and asked for a test that lymph flow responds to a perturbation. In this engine version neither is possible: the lymphatic system is wired into the circuit but switched off. viva-pulse doesn't hide a live model; what it can tell users is that Pulse's lymph is present and inactive.

## 2. Findings: substances and tissues (#35)

| Question | Answer | Source |
|---|---|---|
| Do the four request types work from Python? | Yes. Liquid-compartment substance (vascular, tissue extracellular and intracellular), gas-compartment substance, whole-body substance and tissue requests all load and return numbers for valid combinations. | mode `reads` |
| Do they agree with the physiology values? | Aorta oxygen partial pressure equals `ArterialOxygenPressure` to 1e-7 relative (91.35530 vs 91.35529 mmHg: the physiology value is taken at another point in the step), and the same for CO2. Aorta oxygen `Saturation` equals `OxygenSaturation` to 1.4e-9. Whole-body CarbonDioxide `EndTidalPressure` equals `EndTidalCarbonDioxidePressure` exactly. Measured unperturbed only. | mode `reads` |
| Do whole-body masses add up? | Yes, to about 1e-7. Sodium `MassInBlood` (18091.149 mg) equals the sum of `Mass` over Pulse's vascular leaf compartments (18091.152 mg; 1.4e-7), and `MassInTissue` the sum over the 13 tissues' extra- and intracellular compartments (6.5e-8). `MassInBody` = blood + tissue. `Ground` is in Pulse's vascular list but reads NaN. | mode `mass`; `BloodChemistryModel.cpp:343-352`, `SubstanceManager.cpp:1154-1166` |
| Which whole-body properties are meaningful? | `MassInBody`, `MassInBlood`, `MassInTissue` and `BloodConcentration` (BloodChemistryModel, every active substance); `EndTidalFraction`/`EndTidalPressure` for gases. `PlasmaConcentration` is **mass in blood / plasma volume**, which Pulse's own comment calls "obviously erroneous ... a known issue": Sodium reads 6.16 g/L against a blood concentration of 3.30 g/L. `TissueConcentration` and `SystemicMassCleared` are NaN for Sodium (set only for drugs with pharmacokinetics). | mode `reads`; `DrugModel.cpp:617-640`; `SubstanceManager.cpp:1012` |
| Hemoglobin | `BloodConcentration` of Hemoglobin is **total** hemoglobin over all its species (149.7 g/L), set separately (`BloodChemistryModel.cpp` ~line 358); `MassInBlood` (107.3 g) is the free, deoxygenated species only. | mode `recheck`; source |
| Which properties a substance has depends on its state | Sodium `PartialPressure`, `Saturation` and `EndTidalPressure` read NaN; CarbonDioxide `Saturation` reads 0.027. Partial pressures and end-tidal values exist for gases (`Substance[].State` = Gas), saturation only for the hemoglobin-binding gases (O2, CO2, CO). | mode `recheck` |
| Which substances are active? | 22 of the 45 in every shipped state: the gases, hemoglobin species, electrolytes, glucose, lactate, albumin, insulin, the catecholamines and a few metabolites. The 23 inactive ones are the drugs and agents (Fentanyl, Propofol, ...) plus CarbonMonoxide, Carboxyhemoglobin, Globulin and the particulates. Every state lists them in `ActiveSubstance` and carries all 45 definitions in `Substance`. Globulin is inactive, yet Pulse sets its `BloodConcentration` every step (22.1 g/L). | serialized states; mode `recheck`; `BloodChemistryModel.cpp` ~line 356 |
| What does a request for an inactive substance do? | Pulse **activates** it (`AddActiveSubstance`, `SEDataRequestTracker.cpp:482-484`), and the activation persists into saved states (`ActiveSubstance` gains it). A Fentanyl request left HR, MAP, PaO2 and blood volume bit-identical after 60 s; a CarbonMonoxide request (which also activates Carboxyhemoglobin) changed PaO2 by 1.6e-12 relative at 5 s. Its compartment concentration reads 0.0; a whole-body request reads **NaN at load** and 0.0 after one step. | modes `observer`, `recheck` |
| Does an active-substance request change the run? | No: bit-identical with and without a Sodium request. | mode `observer` |
| Misspelled names? | No crash, but **not harmless**. An unknown substance, compartment or property reads NaN, as do a gas request on a liquid-only compartment, an unknown whole-body property, a whole-body request with a compartment, and an unknown tissue property. `SESubstanceManager::GetSubstance` creates a substance for an unknown name, and the request activates it: the saved state then holds 47 substance definitions, including `Sodiumm` and `Oxygenn`. A whole-body request for an unknown name reads NaN at load and 0.0 after a step. | modes `invalid`, `recheck`; `SESubstanceManager.cpp:49-58` |
| A compartment with no quantity for the substance | **Segfaults** at load (exit -11): liquid `Alveoli` with Oxygen or Sodium, and gas `Alveoli` with Sodium. The tracker dereferences `GetSubstanceQuantity(*sub)`, which is null when the compartment holds no quantity for that substance: liquid substances are never added to gas compartments, and the aerosol liquid compartments hold no non-aerosol substances. **45 names** (Alveoli, Trachea, Stomach, ...) exist both as an aerosol liquid compartment and as a gas compartment. | mode `recheck`; `SEDataRequestTracker.cpp:432-447, 480-505`; `SEFluidCompartment.hxx:405-413`; `CompartmentManager.cpp:458-481` |
| Wrong unit? | Raises at load: `RuntimeError: mmHg is not a valid MassPerVolume unit` (also for a nonsense unit). Python's `<UnitClass>.from_string` is an exact, case-sensitive table (`g/l`, `ml` are rejected). | mode `invalid`; `pulse/cdm/scalars.py` |
| Property types | `SELiquidSubstanceQuantity`: Concentration (MassPerVolume); Mass, MassCleared, MassDeposited, MassExcreted (Mass); Molarity (AmountPerVolume); PartialPressure (Pressure); Saturation (unitless). `SEGasSubstanceQuantity`: PartialPressure, Volume, VolumeFraction. `SESubstance`, `SETissueCompartment`: as above. | `cdm/compartment/substances/*.h`, `cdm/substance/SESubstance.{h,cpp}`, `cdm/compartment/tissue/SETissueCompartment.h` |
| Tissue compartments | `SETissueCompartment` values are composition constants (BrainTissue `MatrixVolume` 316.1 mL, `TotalMass` 1450 g, lipid fraction 0.051, identical at 0 and 10 s). The **dynamic** tissue values are on the tissue fluid compartments: `BrainTissueExtracellular` Volume 234.9 mL and Pressure 9.12 mmHg change over time; intracellular Volume (899 mL) didn't move in 10 s. No module exposes tissue fluid compartments today. | modes `reads`, `recheck` |
| Parent compartments | Requests on parents return aggregates (Heart O2, Alveoli O2 partial pressure), but the serialized state carries no value for a parent's substance quantity unless that property was requested, so Pulse's saved state is no oracle for parents. | review finding 2, re-checked in the state file |
| Port type | Settled already: every `PulseCircuitProcess` output is an `overwrite[float]` carrying Pulse's absolute reading (process-bigraph 1.10.1, CLAUDE.md). Concentrations and masses fit that unchanged. The issue's delta/overwrite question predates that change. | `processes.py` `PulseCircuitProcess.outputs` |
| Names and kinds can be checked before loading | The state lists every liquid, gas and tissue compartment, each compartment's `SubstanceQuantity` entries, every substance (`Substance[].Name`, equal to the file stem, with `State`) and the active ones (`ActiveSubstance`). | serialized state |

## 3. Design

### 3.1 Lymph (#36)

Depends on decision D1. The recommended option:
- **No new output ports.** Ports that read 0 forever, plus a pressure that duplicates the vena cava node, would suggest a modeled quantity that isn't there.
- **Document it** in the `cardiovascular` module docstring, `README.md` ("Pulse circuits"), `documentation/concepts/circuits.md` and the `pulse_cardiovascular` / `pulse_whole_body_circuits` descriptions: Pulse 4.4.0 wires a lymph node and 13 tissue-to-lymph paths into `FullCardiovascular`, but the paths are zero flow sources that nothing drives, so lymph carries no flow or substances and its pressure is the vena cava's. `cardiovascular_points` already reads all of it (`nodes/Lymph`, `paths/<Tissue>T1ToLymph`, `paths/LymphToVenaCava1`).
- **A guard test** that fails if a Pulse upgrade switches lymph on, so the docs and this decision get revisited: under a RightLeg hemorrhage (a perturbation the composite can apply), every lymph path flow stays below 1e-6 mL/min and the `Lymph` node's pressure equals `VenaCava1`'s, read through `cardiovascular_points` and checked against Pulse's own serialized circuit (the existing points oracle).
- **Draft an upstream note** in `upstream-issues/pulse.md` (never filed by Claude, per `CURRENT.md`) asking Kitware whether the lymph flow sources are intentionally inert.
- Draft a reply to #36 with these findings, for the user to post.

### 3.2 Substances and tissues (#35)

**`Request`** (`circuits/base.py`) gains `substance: str | None = None`, included in `key()`. `_pulse()` adds:
- `liquid_compartment` / `gas_compartment` with a substance -> `create_liquid_compartment_substance_request` / `create_gas_compartment_substance_request`;
- a new category `substance` -> `create_substance_request`;
- a new category `tissue_compartment` -> `create_tissue_request`.

Existing requests keep their keys, so existing outputs are unchanged. `PulseCircuitProcess._pull`'s NaN message gains the substance name.

**Two new modules, whole_body only**, each with outputs from its config, built by the `prepare_state` hook the point modules already use. The hook reads the starting state, so every name is checked against the patient's own state at construction, with errors that name the entry, instead of NaN, a polluted state or a segfault at load. Neither edits the state.

- **`substances`**, config `substance_outputs: list[map[string]]` (default `[]`). Entry keys: `substance`, optional `compartment`, `property`, optional `unit`. Ports `<Substance>/<Compartment>/<port>` or, without a compartment, `<Substance>/body/<port>`; in a composite `circuits/substances/Oxygen/Aorta/partial_pressure_mmHg`.
- **`tissues`**, config `tissue_outputs: list[map[string]]` (default `[]`). Entry keys: `compartment`, `property`, optional `unit`. The compartment is a tissue (`BrainTissue`, composition constants) or a tissue fluid compartment (`BrainTissueExtracellular`/`Intracellular`, with liquid-compartment properties Volume, Pressure, Inflow, Outflow), per decision D6. Ports `<Compartment>/<port>`, e.g. `circuits/tissues/BrainTissueExtracellular/volume_mL`.

**Checks at construction** (both modules), each naming the entry:
- only the documented keys, all strings; required keys present;
- the substance is one of the state's `Substance` names and in `ActiveSubstance` (decision D2);
- the compartment exists and **holds a `SubstanceQuantity` for that substance in the state**. That decides its kind (liquid or gas), excludes the aerosol liquid copies, gas compartments for liquid substances, `Ground` and `Lymph`, and so prevents the segfault. If both kinds hold one (possible after an inhaler activates an aerosol), the entry must say `kind`;
- gas compartments are limited to the state's `Respiratory` gas graph, so device compartments (which read 0 or NaN while the device is disconnected) are refused;
- the property is in a table keyed by request kind and, for partial pressure, saturation and end-tidal values, by the substance's `State` and binding (section 2); `PlasmaConcentration` per decision D4;
- the unit parses with that property's `<UnitClass>.from_string`; omitted only for unitless properties;
- no duplicate port paths. The same quantity in two units (`mg` and `g`) gives two ports and is allowed; both share nothing but the Pulse value.

Port names: property in snake_case plus `_<unit>`, the unit with `/` -> `_per_`, `^` and spaces removed (`ug/L` -> `ug_per_L`, `g/cm^3` -> `g_per_cm3`); unitless properties have no suffix. Substance and compartment names are Pulse's own (all alphanumeric).

**Composites.** `pulse_cardiovascular` and `pulse_whole_body_circuits` gain `substance_outputs` and `tissue_outputs` parameters (type `list`, default empty). A module is added only when its list is non-empty, the way `point_reads` adds point modules, so the default composites don't start reading the state at construction. Because the checks need the state, a bad entry fails when the `Composite` (not the document) is built; the parameter descriptions say so. `tests/test_whole_body.py::test_whole_body_composite_includes_every_whole_body_module` identifies point modules by `prepare_state`; it changes to identify them by name. `PulseProcess` is unchanged (decision D3).

**Not in scope** (the issue's own "out of scope"): drug actions (`SESubstanceBolus`, `SESubstanceInfusion`) as setpoints, and presets (D5).

## 4. Revised acceptance criteria

#36:
- [ ] The lymph decision (D1) is implemented, and the docs state that Pulse 4.4.0 simulates no lymph flow and where lymph values can be read.
- [ ] Guard test: under a RightLeg hemorrhage, lymph path flows stay below 1e-6 mL/min and the `Lymph` node's pressure equals `VenaCava1`'s (oracle: Pulse's serialized circuit).

#35:
- [ ] `Request` supports liquid, gas, whole-body and tissue requests; every existing request key is unchanged (test).
- [ ] The `substances` and `tissues` modules emit configured quantities for vascular, tissue fluid and pulmonary gas compartments, the whole body and tissues, on `whole_body`.
- [ ] Construction raises, naming the entry, for: a misspelled substance, compartment, property or unit; an unknown or non-string key; a compartment without a quantity for the substance (the segfault cases); a device gas compartment; a property the substance doesn't have; a missing unit; a duplicate port; and (per D2) an inactive substance.
- [ ] Real-engine tests with independent oracles:
  - every substance output on a **leaf** compartment equals Pulse's own serialized `SubstanceQuantity` value, converted with `PyPulse.convert` (the points tests' oracle), at load and after 30 s; parent compartments (`Heart`, `Alveoli`) against aggregates of their children read through a separate direct engine;
  - Aorta O2 and CO2 partial pressures equal `ArterialOxygenPressure` / `ArterialCarbonDioxidePressure`, and Aorta O2 saturation equals SpO2, within 1e-6 (unperturbed; the gap is re-measured under a hemorrhage before any perturbed comparison);
  - Sodium `MassInBlood` and `MassInTissue` equal the sums over Pulse's vascular leaf and tissue compartments within 1e-6, with the compartment lists written out from `PulseEngine.h`, not taken from the module;
  - adding substance and tissue outputs leaves the other outputs unchanged (rows equal a run without them to 1e-9);
  - a quantity moves under a perturbation the composite can apply: Sodium and Hemoglobin `MassInBlood` fall under a RightLeg hemorrhage;
  - a state saved during a run with substance outputs gains no `ActiveSubstance` entries.
- [ ] Each new test fails on a deliberately broken copy of the code (mutation checks, listed here when done).
- [ ] README, `documentation/concepts/circuits.md`, `documentation/api/circuits.rst` and `CLAUDE.md` list the modules, their config and port layout, the meaningful whole-body properties, the hemoglobin and `PlasmaConcentration` caveats, and the lymph finding.

## 5. Decisions for the user

**Taken (user, 2026-11-01):** D1a, D2a, D3a, D4a, D5a, D6a. Before choosing D1 the user asked why lymph is inactive and what porting BioGears' lymph would take; the answers (Pulse inherited the stub from BioGears in 2017, BioGears built its lymph model in Oct-Nov 2018 as part of a tissue-fluid redesign, so a port is an engine project) are in section 1 and the upstream note. The user then asked for a separate scoping plan for a BioGears Python API (`viva-biogears`) after this branch.

- **D1. Lymph outputs.** (a, recommended) No new ports; document that Pulse's lymph is inactive, add the guard test, draft an upstream note and a reply on #36. (b) Add `circuits/cardiovascular/lymph/{pressure_mmHg, inflow_mL_per_min, outflow_mL_per_min}` as the issue proposed, documented as "0 in Pulse 4.4.0". (c) (a)'s docs and guard plus (b)'s ports.
- **D2. Inactive substances.** (a, recommended) Refuse them at construction ("Fentanyl is not active in this state"). Nothing in viva-pulse can dose a drug yet, so they would read 0 forever; a request activates them, the activation is saved into states, and for some (CarbonMonoxide) it perturbs the run slightly; a whole-body request for one fails the load anyway (NaN at load). Revisit with drug actions. Globulin is refused too, though Pulse computes its blood concentration. (b) Allow them for compartment requests (reading 0 until something adds the substance), refusing whole-body ones, and document the activation.
- **D3. `PulseProcess`.** (a, recommended) Substance and tissue outputs only on `PulseCircuitProcess` (the modules and the two generators). (b) Also on `PulseProcess`.
- **D4. `PlasmaConcentration`.** (a, recommended) Leave it out: Pulse computes it as mass in blood over plasma volume and calls it erroneous; `BloodConcentration` and compartment concentrations remain. (b) Allow it with a documented caveat.
- **D5. Presets** (e.g. blood gases in every vascular compartment). (a, recommended) Not now; the config list covers it. (b) Add one `blood_gases` preset.
- **D6. Tissue fluid compartments.** (a, recommended) Include them in `tissue_outputs` (Volume, Pressure, Inflow, Outflow of `<Tissue>TissueExtracellular`/`Intracellular`), since they hold the dynamic tissue values (edema, fluid shifts) and no module exposes them. (b) Tissue constants only, as the issue proposed.

## 6. Docs and records to update

- `README.md` (Processes, Pulse circuits), `documentation/concepts/circuits.md`, `documentation/api/circuits.rst`, `CLAUDE.md` (architecture: `Request.substance`, the modules, the lymph finding), `CURRENT.md` (session state), `.build-progress.md` (the Linux build, its workarounds and canary values).
- This plan: status line, mutation checks and results when it ships.
- `upstream-issues/pulse.md`: the lymph note (D1a). Possibly also the null dereference for a compartment without the substance, and unknown names creating substances.

## 7. Validation

- Real-engine tests only, nothing mocked; each docstring names the proposition it would falsify.
- Mutation checks on copies of the code in a scratch directory, listed here when done.
- An adversarial review of the diff before the PR, recorded here like section 8.
- The full suite runs on the Linux build with no skips (baseline before any change recorded in section 9). Before the PR is opened, the user runs `uv run --no-sync pytest -q -rs` on the Mac build and the result (count, skips) is recorded here, because some tests' anchors are macOS values.

### Implementation notes (2026-11-01)

- Found while implementing: a tissue's **intracellular** fluid has no circuit node, so only its `Volume` is served (pressure and flows read NaN); the extracellular fluid has Volume, Pressure, Inflow and Outflow. `AcidicPhospohlipidConcentration` is left out, because Pulse's Python API has no MassPerMass unit class to request it in. `Ground` and `Lymph` hold substance-quantity entries in the state, so they are refused by name rather than by the holds-the-substance check.
- Gas compartments: members of the state's `Respiratory` gas graph, plus parents whose leaves all are (so `Alveoli` is allowed; device compartments are not).

- 2026-11-02, found when the user asked how to read every substance: building one entry for every valid combination (12,133 outputs on StandardMale) failed at load with NaN for `Ureters` saturation, and saturation read 0 in urine, chyme and the abdominal cavity, all of which are in the circulation graphs. `Saturation` is now allowed only where every leaf holds hemoglobin in the state (90 oxygen and CO2 entries, none 0 or NaN); tests for `LeftTubules` and `Ureters`, M14 re-run and caught. With that, all 12,133 entries load; a 30 s `pulse_whole_body_circuits` run takes 7.6 s with them against 3.0 s without (build 12.6 s), and 6,551 of them read 0 (mostly clearance masses).

### Mutation checks (2026-11-01)

Each mutation was applied to a scratch copy of the code and the named tests were run (script `mutate.py` in the session scratchpad); every one is caught. M1-M12 were run first; after the diff review's fixes the set was re-run with M13-M16 added.

| # | Mutation | Caught by |
|---|---|---|
| M1 | liquid substance request ignores the substance | `test_leaf_quantities_equal_pulses_own_state` |
| M2 | `Request.key()` drops the substance | `test_request_keys_tell_substances_apart_and_keep_existing_keys` (and the blood-gas test) |
| M3 | no check that the compartment holds the substance | `test_bad_substance_entries_raise_naming_the_entry` |
| M4 | `Lymph`/`Pericardium` not refused | same |
| M5 | inactive substances allowed | same |
| M6 | requested unit ignored (first unit of the class) | `test_leaf_quantities_equal_pulses_own_state` |
| M7 | whole-body request reads `MassInTissue` whatever the property | `test_whole_body_masses_are_the_compartment_sums` |
| M8 | tissue request reads `TotalMass` whatever the property | `test_tissue_values_equal_pulses_own_state` |
| M9 | equipment compartments allowed (liquid or gas) | `test_bad_substance_entries_raise_naming_the_entry` |
| M10 | substance missing from the NaN message | `test_nan_message_names_the_substance` |
| M11 | generators always add the modules | `test_generators_add_the_modules_only_when_asked` |
| M12 | `Saturation` allowed for any substance | `test_bad_substance_entries_raise_naming_the_entry` |
| M13 | bare state entries allowed (`Ground`, airway leaks) | `test_bad_substance_entries_raise_naming_the_entry` |
| M14 | `Saturation` allowed outside blood | same |
| M15 | `kind` ignored | `test_kind_decides_a_name_that_is_both_kinds` (added after M15 first survived `test_kind_selects_the_compartment_that_holds_the_substance`, which can't tell: no shipped state has a name of both kinds holding a substance) |
| M16 | a parent read as its first leaf | `test_parent_compartment_is_the_aggregate_of_its_children`, `test_gas_parent_compartment_is_the_sum_of_its_children` |
| L1-L3 | the lymph guard on a state with a nonzero `BoneT1ToLymph` flow source, a resistance on `BrainT1ToLymph`, or `Lymph` in a liquid graph | `test_lymph_paths_are_zero_flow_sources_outside_every_transport_graph` (each mutated state fails it; the unmutated one passes) |

## 8. Adversarial review of this plan (2026-11-01)

A separate agent, given the plan, the code, Pulse's source and the build (not this plan's reasoning), reported 3 blockers, 7 should-fix and 7 minor findings. Each blocker and the factual ones were re-probed (mode `recheck`) before being applied.

| # | Finding | Re-probed | Resolution |
|---|---|---|---|
| 1 | Entries passing the planned checks segfault the engine: a compartment holding no quantity for the substance (aerosol liquid `Alveoli`; gas `Alveoli` with Sodium). 45 names exist in both kinds. | yes, exit -11 x3 | Check the compartment's `SubstanceQuantity` list in the state; kind from that; `kind` key if both (3.2). |
| 2 | Pulse's saved state is no oracle for parent compartments. | yes (state file) | Leaf compartments against the state; parents against child aggregates (4). |
| 3 | The composite can't apply a saline infusion, which two planned tests used. | yes (`grep`) | Use the hemorrhage setpoint instead (3.1, 4). |
| 4 | Lymph flows are ~1e-9, not exactly 0. | yes | Table corrected; guard tolerance 1e-6 mL/min. |
| 5 | Valid properties depend on the substance (Sodium partial pressure NaN). | yes | Property table keyed by substance state (2, 3.2). |
| 6 | `_pull`'s NaN message omits the substance. | yes (`processes.py:636-640`) | Add it (3.2). |
| 7 | `list[map[string]]` doesn't type-check entries; a misspelled key silently changes meaning. | not re-run (schema behaviour shown by reviewer) | Reject unknown keys and non-strings (3.2). |
| 8 | `test_whole_body.py:89-96` equates `prepare_state` with point modules. | yes (read) | Change the test to use names (3.2). |
| 9 | Unknown names create and activate substances, saved into states. | yes, 47 definitions | Recorded (2); name checks are the guard. |
| 10 | Dynamic tissue fluid values can't be configured. | yes (Volume/Pressure served, change) | Decision D6. |
| 11 | Inactive-substance evidence overgeneralized (CO perturbs 1.6e-12; activation persists; Globulin computed). | yes | Recorded in 2 and D2. |
| 12 | Hemoglobin `BloodConcentration` vs `MassInBlood` differ in meaning. | yes | Recorded (2); documented. |
| 13 | Device gas compartments read 0 or NaN while disconnected. | not re-run | Gas compartments limited to the `Respiratory` graph (3.2). |
| 14 | 1e-6 tolerances measured unperturbed only. | n/a | Re-measure under hemorrhage before using (4). |
| 15 | Lymph = VenaCava1 at 7 s and graph membership weren't in the probe output. | added to mode `recheck` | Done. |
| 16 | Unit strings are exact; `^` unhandled in port names. | n/a | Port rule handles `^` (3.2). |
| 17 | Generator parameter type and late validation unspecified; doubled port names. | n/a | Specified (3.2); module ports drop the module name. |

## 10. Adversarial review of the diff (2026-11-01)

A separate agent reviewed the diff (code, tests, docs) with the plan, Pulse's source and the build. No blocker; every reported value below was reproduced by its probes and the fixes are tested.

| # | Finding | Resolution |
|---|---|---|
| 1 | The airway leaks and needles pass and read NaN (bare state entries, like `Ground`) | Leaves need a filled-in state entry; tests for `Ground` and `LeftAlveoliLeak` |
| 2 | ECMO liquid compartments pass and read 0 | Liquid leaves must be in a circulation graph or be tissue fluid; test |
| 3 | `Pericardium` passes but nothing moves in or out of it | Refused by name with the reason; allowed inside `Heart`; docs say so; test |
| 4 | `Ambient` `Volume` emits infinity | Refused (infinite reservoir); test |
| 5 | `mEq` units give mmol values (Calcium 1.196 in both) | `mEq` refused; test |
| 6 | Wrong message when `kind` excludes the holding kind | Message names the kind that holds it; test |
| 7 | `Saturation` outside blood reads 0; clearance masses mostly 0 | `Saturation` limited to blood graphs (test); docs note where clearance masses move |
| 8 | An empty list builds a module with no outputs | Raises; test |
| 9 | Generators converted entries with `dict()` before validation | Pass lists through unchanged |
| 10 | Tests promised more than they checked (row 0, gas parent, points+substances, kind success) | Added: row 0 in the leaf test, `Alveoli` oxygen volume against its children, points and substances on one process, a synthetic both-kinds state for `kind` |
| 11 | README and concepts overclaimed what is refused | Rewritten to the actual rules |

## 9. Baseline before changes

Unmodified branch (`origin/main` `0b0bd07`), Linux build, 2026-11-01: **316 passed, 1 skipped** in 29 min 44 s (2 shared cores). The skip is the allowlisted `test_composite_state_artifacts` ("workspace commits no composite-state artifacts"). No engine test skipped, so the macOS anchors (HR 72, MAP 95.3, BV 5487) hold on Linux.

With this change (same build, 2026-11-01): **373 passed, 1 skipped** (the same allowlisted skip) in 29 min 39 s: the 316 existing tests plus 57 new ones (`tests/test_substances.py` 55, `tests/test_lymph.py` 2), including the strict docs build with the new API page. **Still to do before the PR:** the same suite on the Mac build, recorded here.
