"""The substances and tissues modules: substance quantities and tissue values (issue #35).

Oracles are independent of the modules: Pulse's own serialized state of a separate engine
(converted with Pulse's unit converter), physiology values Pulse computes elsewhere, and
compartment lists written out here from Pulse's source. Each docstring names the
proposition the test would falsify. Facts behind the checks are in
docs/plan/plan-substances-and-lymph.md (probe substances-lymph-2026-11-01).
"""

import json

import pytest

from viva_pulse.circuits import MODULES, CircuitModule, Request
from viva_pulse.circuits.substances import SUBSTANCES, TISSUES
from viva_pulse.composites import pulse_cardiovascular, pulse_whole_body_circuits
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess
from viva_pulse.runtime import ensure_pulse_importable

STATE = "StandardMale@0s.json"

# Pulse's vascular compartments (engine/PulseEngine.h, VascularCompartment). MassInBlood sums
# the leaves of this list (BloodChemistryModel.cpp:343-352); Ground serves no substance.
VASCULAR = ["Aorta", "Heart", "MyocardiumVasculature", "LeftHeart", "RightHeart", "Pericardium", "VenaCava",
            "PulmonaryArteries", "PulmonaryCapillaries", "PulmonaryVeins", "LungsVasculature", "LeftLungVasculature",
            "LeftPulmonaryArteries", "LeftPulmonaryCapillaries", "LeftPulmonaryVeins", "RightLungVasculature",
            "RightPulmonaryArteries", "RightPulmonaryCapillaries", "RightPulmonaryVeins", "KidneyVasculature",
            "LeftKidneyVasculature", "LeftRenalArtery", "LeftNephron", "LeftAfferentArteriole",
            "LeftGlomerularCapillaries", "LeftEfferentArteriole", "LeftPeritubularCapillaries", "LeftBowmansCapsules",
            "LeftTubules", "LeftRenalVein", "RightKidneyVasculature", "RightRenalArtery", "RightNephron",
            "RightAfferentArteriole", "RightGlomerularCapillaries", "RightEfferentArteriole",
            "RightPeritubularCapillaries", "RightBowmansCapsules", "RightTubules", "RightRenalVein", "BoneVasculature",
            "BrainVasculature", "FatVasculature", "GutVasculature", "SplanchnicVasculature",
            "SmallIntestineVasculature", "LargeIntestineVasculature", "LiverVasculature", "SpleenVasculature",
            "SkinVasculature", "MuscleVasculature", "LeftArmVasculature", "LeftLegVasculature",
            "RightArmVasculature", "RightLegVasculature", "Abdomen", "AbdominalCavity"]
# MassInTissue sums each tissue's extra- and intracellular fluid (SubstanceManager.cpp:1154-1166).
TISSUES_LIST = ["Bone", "Brain", "Fat", "Gut", "LeftKidney", "LeftLung", "Liver", "Muscle", "Myocardium",
                "RightKidney", "RightLung", "Skin", "Spleen"]

# Leaf-compartment entries checked against Pulse's serialized state.
# (substance, compartment, property, unit, state kind)
LEAF_ENTRIES = [
    ("Oxygen", "Aorta", "PartialPressure", "mmHg", "Liquid"),
    ("Oxygen", "Aorta", "Concentration", "g/L", "Liquid"),
    ("CarbonDioxide", "VenaCava", "Molarity", "mmol/L", "Liquid"),
    ("Sodium", "BrainTissueExtracellular", "Concentration", "g/L", "Liquid"),
    ("Sodium", "MuscleTissueIntracellular", "Mass", "mg", "Liquid"),
    ("Glucose", "LiverVasculature", "Concentration", "mg/dL", "Liquid"),
    ("Oxygen", "LeftAlveoli", "PartialPressure", "mmHg", "Gas"),
    ("CarbonDioxide", "RightAlveoli", "VolumeFraction", None, "Gas"),
    ("Nitrogen", "Trachea", "Volume", "mL", "Gas"),
]


def _entry(substance, compartment, prop, unit=None, **extra):
    entry = {"substance": substance, "property": prop, **extra}
    if compartment:
        entry["compartment"] = compartment
    if unit:
        entry["unit"] = unit
    return entry


def _direct_engine(requests=()):
    """Oracle engine: the unedited state loaded straight through Pulse's API."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm.engine import SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / STATE), SEDataRequestManager(list(requests)))
    engine.advance_time_s(0.0)
    return engine


def _serialized(engine):
    import PyPulse

    return json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))


def _quantity(state, kind, compartment, substance, prop, unit):
    """A substance quantity from Pulse's serialized state, in ``unit`` (proto3 JSON omits zeros)."""
    import PyPulse

    for c in state["CompartmentManager"][f"{kind}Compartment"]:
        if c["FluidCompartment"]["Compartment"]["Name"] == compartment:
            for q in c.get("SubstanceQuantity", []):
                if q["SubstanceQuantity"]["Substance"] == substance:
                    scalar = next(iter(q[prop].values()))
                    value = float(scalar.get("Value", 0.0))
                    return PyPulse.convert(value, scalar["Unit"], unit) if unit else value
    raise KeyError((kind, compartment, substance, prop))


def _process(substance_outputs=(), tissue_outputs=(), **config):
    return PulseCircuitProcess({"modules": [m for m, entries in (("substances", substance_outputs),
                                                                  ("tissues", tissue_outputs)) if entries],
                                "substance_outputs": list(substance_outputs),
                                "tissue_outputs": list(tissue_outputs), **config}, core=build_core())


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


# -- Request and registry --------------------------------------------------------


def test_request_keys_tell_substances_apart_and_keep_existing_keys():
    """Falsifies: adding ``substance`` merged two different substance requests into one Pulse
    request, or changed the identity of a request without a substance (which would change how
    existing modules share Pulse requests)."""
    plain = Request(("a",), "liquid_compartment", "Pressure", ("PressureUnit", "mmHg"), "Aorta")
    assert plain.key()[:5] == ("liquid_compartment", "Aorta", "Pressure", ("PressureUnit", "mmHg"), None)
    oxygen = Request(("b",), "liquid_compartment", "PartialPressure", ("PressureUnit", "mmHg"), "Aorta",
                     substance="Oxygen")
    co2 = Request(("c",), "liquid_compartment", "PartialPressure", ("PressureUnit", "mmHg"), "Aorta",
                  substance="CarbonDioxide")
    assert len({plain.key(), oxygen.key(), co2.key()}) == 3


def test_modules_are_registered_whole_body_only():
    """Falsifies: a module is missing from the registry, or claims an engine whose state it can't read."""
    assert MODULES["substances"] is SUBSTANCES and MODULES["tissues"] is TISSUES
    for module in (SUBSTANCES, TISSUES):
        assert module.model_types == frozenset({"whole_body"}) and module.prepare_state


# -- construction checks (read the state file, never load the engine) --------------


@pytest.mark.parametrize("entries, message", [
    ([_entry("Oxygenn", "Aorta", "PartialPressure", "mmHg")], "unknown substance 'Oxygenn'"),
    ([_entry("Fentanyl", "Aorta", "Concentration", "ug/L")], "Fentanyl is not active"),
    ([_entry("Globulin", None, "BloodConcentration", "g/L")], "Globulin is not active"),
    ([_entry("Oxygen", "Aortaa", "PartialPressure", "mmHg")], "unknown compartment 'Aortaa'"),
    # Each of these segfaults Pulse at load if sent (probe recheck): no quantity of the substance.
    ([_entry("Sodium", "Alveoli", "Concentration", "g/L")], "holds no Sodium"),
    ([_entry("Sodium", "Trachea", "PartialPressure", "mmHg")], "holds no Sodium"),
    ([_entry("Oxygen", "Alveoli", "PartialPressure", "mmHg", kind="liquid")],
     "holds no Oxygen as a liquid compartment; it does as a gas compartment"),
    # These read NaN (a bare state entry), 0 forever, or infinity.
    ([_entry("Oxygen", "Ground", "Concentration", "g/L")], "Ground serves no Oxygen quantity"),
    ([_entry("Oxygen", "LeftAlveoliLeak", "PartialPressure", "mmHg")], "LeftAlveoliLeak serves no Oxygen"),
    ([_entry("Albumin", "Lymph", "Concentration", "g/L")], "lymph carries no flow"),
    ([_entry("Sodium", "Pericardium", "Mass", "mg")], "Pulse moves no substances into or out of it"),
    ([_entry("Oxygen", "MechanicalVentilatorConnection", "PartialPressure", "mmHg")], "equipment compartment"),
    ([_entry("Oxygen", "ExtracorporealMembraneOxygenationDeviceBag", "Concentration", "g/L")],
     "equipment compartment"),
    ([_entry("Oxygen", "Ambient", "Volume", "mL")], "infinite reservoir"),
    ([_entry("Oxygen", "BrainTissueExtracellular", "Saturation")], "Saturation is a property of blood"),
    ([_entry("Calcium", "Aorta", "Molarity", "mEq/L")], "mEq/L is not offered"),
    ([_entry("Sodium", None, "PlasmaConcentration", "g/L")], "PlasmaConcentration is not offered"),
    ([_entry("Sodium", None, "TissueConcentration", "g/L")], "not offered here"),
    ([_entry("Oxygen", "Alveoli", "Concentration", "g/L")], "not offered here"),
    ([_entry("Sodium", "Aorta", "PartialPressure", "mmHg")], "Sodium is not a gas"),
    ([_entry("Sodium", None, "EndTidalPressure", "mmHg")], "Sodium is not a gas"),
    ([_entry("Sodium", "Aorta", "Saturation")], "have a Saturation"),
    ([_entry("Oxygen", "Aorta", "PartialPressure")], "needs a unit"),
    ([_entry("Oxygen", "Aorta", "Saturation", "%")], "is unitless"),
    ([_entry("Oxygen", "Aorta", "PartialPressure", "mm Hg")], "is not a Pressure unit"),
    ([_entry("Sodium", "Aorta", "Concentration", "mmHg")], "is not a MassPerVolume unit"),
    ([_entry("Oxygen", "Aorta", "PartialPressure", "mmHg", compartmnet="VenaCava")], "unknown keys"),
    ([{"substance": "Oxygen", "compartment": "Aorta", "unit": "mmHg"}], "missing ['property']"),
    ([_entry("Oxygen", "Aorta", "PartialPressure", "mmHg", kind="plasma")], "kind must be liquid or gas"),
    ([_entry("Sodium", None, "MassInBlood", "mg", kind="liquid")], "kind applies only with a compartment"),
    ([_entry("Oxygen", "Aorta", "PartialPressure", "mmHg")] * 2, "both write Oxygen/Aorta/partial_pressure_mmHg"),
])
def test_bad_substance_entries_raise_naming_the_entry(entries, message):
    """Falsifies: a bad entry reaches Pulse, where it would read NaN, create or activate a substance
    that then lands in saved states, or segfault, instead of failing at construction with the entry
    named."""
    with pytest.raises(ValueError, match="substance_outputs\\[") as error:
        _process(substance_outputs=entries)
    assert message in str(error.value)


def test_an_empty_list_is_refused():
    """Falsifies: a module selected with nothing to read is built silently (it still reads the
    state at construction, for no output)."""
    with pytest.raises(ValueError, match="substance_outputs is empty"):
        PulseCircuitProcess({"modules": ["substances"]}, core=build_core())


def test_kind_selects_the_compartment_that_holds_the_substance():
    """Falsifies: an explicit kind that matches the compartment holding the substance is refused,
    or ignored (the request then goes to the other kind)."""
    process = _process(substance_outputs=[_entry("Oxygen", "Alveoli", "Volume", "mL", kind="gas")])
    (request,) = [r for r in process._requests]
    assert (request.category, request.compartment, request.substance) == ("gas_compartment", "Alveoli", "Oxygen")


def test_kind_decides_a_name_that_is_both_kinds():
    """Falsifies: with a name that is a liquid and a gas compartment both holding the substance
    (possible once an aerosol activates the airway's liquid copies), kind is ignored, or the
    entry goes through without one. No shipped state has such a name, so one is made: the
    state's liquid Trachea gets an oxygen quantity and joins a transport graph."""
    state = json.loads((ensure_pulse_importable() / "states" / STATE).read_text())
    cm = state["CompartmentManager"]
    trachea = next(c for c in cm["LiquidCompartment"] if c["FluidCompartment"]["Compartment"]["Name"] == "Trachea")
    trachea["SubstanceQuantity"] = [{"SubstanceQuantity": {"Substance": "Oxygen"},
                                     "Mass": {"ScalarMass": {"Value": 1.0, "Unit": "mg"}}}]
    next(g for g in cm["LiquidGraph"] if g["FluidGraph"]["Graph"]["Name"] == "Renal")["FluidGraph"]["Graph"][
        "Compartment"].append("Trachea")
    config = {"substance_outputs": [_entry("Oxygen", "Trachea", "PartialPressure", "mmHg")]}
    with pytest.raises(ValueError, match="both a liquid and a gas compartment holding Oxygen"):
        SUBSTANCES.prepare_state(config, state)
    for kind in ("gas", "liquid"):
        config = {"substance_outputs": [_entry("Oxygen", "Trachea", "PartialPressure", "mmHg", kind=kind)]}
        (request,) = SUBSTANCES.prepare_state(config, state)
        assert request.category == f"{kind}_compartment"


def test_substances_and_points_on_one_process():
    """Falsifies: the points module's state edits (added compartments) confuse the substance checks,
    or a substance entry can name a compartment the points module added (it holds no substances)."""
    entries = [_entry("Oxygen", "Aorta", "PartialPressure", "mmHg")]
    process = PulseCircuitProcess({"modules": ["cardiovascular_points", "substances"],
                                   "cardiovascular_point_nodes": ["Aorta1"], "cardiovascular_point_paths": [],
                                   "substance_outputs": entries}, core=build_core())
    assert process.outputs()["substances"]["Oxygen"]["Aorta"] == {"partial_pressure_mmHg": "overwrite[float]"}
    with pytest.raises(ValueError, match="VivaPointNodeAorta1 .*holds no Oxygen"):
        PulseCircuitProcess({"modules": ["cardiovascular_points", "substances"],
                             "cardiovascular_point_nodes": ["Aorta1"], "cardiovascular_point_paths": [],
                             "substance_outputs": [_entry("Oxygen", "VivaPointNodeAorta1", "PartialPressure",
                                                          "mmHg")]}, core=build_core())


def test_non_string_values_are_refused():
    """Falsifies: list[map[string]] lets a non-string through (bigraph-schema doesn't check it)."""
    with pytest.raises(ValueError, match="unit must be a non-empty string"):
        _process(substance_outputs=[{"substance": "Sodium", "property": "MassInBlood", "unit": 3}])


@pytest.mark.parametrize("entry, message", [
    ({"compartment": "Aorta", "property": "Volume", "unit": "mL"}, "not a tissue or tissue fluid compartment"),
    ({"compartment": "BrainTissueIntracellular", "property": "Pressure", "unit": "mmHg"}, "not offered"),
    ({"compartment": "BrainTissue", "property": "Volume", "unit": "mL"}, "not offered"),
    ({"compartment": "BrainTissue", "property": "MatrixVolume", "unit": "kg"}, "is not a Volume unit"),
    ({"compartment": "BrainTissue", "property": "MatrixVolume", "unit": "mL", "substance": "Sodium"}, "unknown keys"),
])
def test_bad_tissue_entries_raise_naming_the_entry(entry, message):
    """Falsifies: a tissue entry Pulse can't serve (NaN) or misreads reaches the engine."""
    with pytest.raises(ValueError, match="tissue_outputs\\[0\\]") as error:
        _process(tissue_outputs=[entry])
    assert message in str(error.value)


def test_ports_follow_the_documented_layout():
    """Falsifies: port names or nesting differ from the documented
    <Substance>/<Compartment or body>/<property>_<unit> and <Compartment>/<property>_<unit>."""
    process = _process(
        substance_outputs=[_entry("Oxygen", "Aorta", "PartialPressure", "mmHg"),
                           _entry("Oxygen", "Aorta", "Saturation"),
                           _entry("Sodium", None, "MassInBody", "mg"),
                           _entry("Glucose", "LiverVasculature", "Concentration", "mg/dL")],
        tissue_outputs=[{"compartment": "BrainTissue", "property": "TotalMass", "unit": "kg"},
                        {"compartment": "BrainTissueExtracellular", "property": "Outflow", "unit": "mL/min"}])
    outputs = process.outputs()
    assert outputs["substances"] == {
        "Oxygen": {"Aorta": {"partial_pressure_mmHg": "overwrite[float]", "saturation": "overwrite[float]"}},
        "Sodium": {"body": {"mass_in_body_mg": "overwrite[float]"}},
        "Glucose": {"LiverVasculature": {"concentration_mg_per_dL": "overwrite[float]"}}}
    assert outputs["tissues"] == {
        "BrainTissue": {"total_mass_kg": "overwrite[float]"},
        "BrainTissueExtracellular": {"outflow_mL_per_min": "overwrite[float]"}}


def test_generators_add_the_modules_only_when_asked():
    """Falsifies: the default composites start reading the state at construction (the modules are
    added although no entry is given), or an entry list never reaches the process config."""
    core = build_core()
    for generator in (pulse_cardiovascular, pulse_whole_body_circuits):
        plain = generator(core)["pulse"]["config"]
        assert not {"substances", "tissues"} & set(plain["modules"])
        assert "substance_outputs" not in plain and "tissue_outputs" not in plain
        entries = [_entry("Sodium", None, "MassInBlood", "mg")]
        config = generator(core, substance_outputs=entries)["pulse"]["config"]
        assert "substances" in config["modules"] and "tissues" not in config["modules"]
        assert config["substance_outputs"] == entries


def test_nan_message_names_the_substance(monkeypatch):
    """Falsifies: a NaN substance reading is reported without the substance, so the user can't tell
    which of several requests on one compartment failed."""
    module = CircuitModule(name="probe_nan", model_types=frozenset({"whole_body"}), outputs=(
        Request(("x",), "liquid_compartment", "PartialPressure", ("PressureUnit", "mmHg"), "Aorta",
                substance="Sodium"),))
    monkeypatch.setitem(MODULES, "probe_nan", module)
    process = PulseCircuitProcess({"modules": ["probe_nan"]}, core=build_core())
    with pytest.raises(ValueError, match=r"liquid_compartment:Aorta\.Sodium\.PartialPressure"):
        process.initial_state()


# -- real engine: values -------------------------------------------------------------


def test_leaf_quantities_equal_pulses_own_state(run_composite):
    """Falsifies: an entry is read from the wrong compartment, substance or property, in the wrong
    unit, or as liquid when it is gas (or the reverse). Oracle: a separate engine's serialized
    state at load and after the same 30 s, converted with Pulse's own converter."""
    entries = [_entry(s, c, p, u) for s, c, p, u, _ in LEAF_ENTRIES]
    _, rows = run_composite(pulse_cardiovascular, 30.0, substance_outputs=entries)
    engine = _direct_engine()
    loaded = _serialized(engine)
    engine.advance_time_s(30.0)
    for row, state in ((rows[0], loaded), (rows[-1], _serialized(engine))):
        _check_leaves(row["circuits"]["substances"], state)


def _check_leaves(readings, state):
    for substance, compartment, prop, unit, kind in LEAF_ENTRIES:
        name = prop[0].lower() + "".join("_" + ch.lower() if ch.isupper() else ch for ch in prop[1:])
        name += ("_" + unit.replace("/", "_per_")) if unit else ""
        expected = _quantity(state, kind, compartment, substance, prop, unit)
        assert readings[substance][compartment][name] == pytest.approx(expected, rel=1e-9, abs=1e-12), \
            (substance, compartment, prop)


def test_parent_compartment_is_the_aggregate_of_its_children(run_composite):
    """Falsifies: a parent compartment (Heart) is read as one child, or not as Pulse's aggregate.
    Oracle: concentration = summed child masses over summed child volumes, children taken from
    the state file and read through a separate engine."""
    state = json.loads((ensure_pulse_importable() / "states" / STATE).read_text())
    heart = next(c for c in state["CompartmentManager"]["LiquidCompartment"]
                 if c["FluidCompartment"]["Compartment"]["Name"] == "Heart")
    children = heart["FluidCompartment"]["Compartment"]["Child"]
    from pulse.cdm.engine import SEDataRequest
    from pulse.cdm.scalars import MassUnit, VolumeUnit

    requests = [SEDataRequest.create_liquid_compartment_substance_request(c, "Oxygen", "Mass", MassUnit.mg)
                for c in children]
    requests += [SEDataRequest.create_liquid_compartment_request(c, "Volume", VolumeUnit.mL) for c in children]
    engine = _direct_engine(requests)
    engine.advance_time_s(10.0)
    values = [float(v) for v in engine.pull_data()[1:]]
    mass, volume = sum(values[:len(children)]), sum(values[len(children):])
    _, rows = run_composite(pulse_cardiovascular, 10.0,
                            substance_outputs=[_entry("Oxygen", "Heart", "Concentration", "mg/mL")])
    got = rows[-1]["circuits"]["substances"]["Oxygen"]["Heart"]["concentration_mg_per_mL"]
    assert got == pytest.approx(mass / volume, rel=1e-9)


def test_gas_parent_compartment_is_the_sum_of_its_children(run_composite):
    """Falsifies: a parent gas compartment (Alveoli) is read as one of its children. Oracle: the
    oxygen volume of its children (from the state file), read through a separate engine."""
    state = json.loads((ensure_pulse_importable() / "states" / STATE).read_text())
    alveoli = next(c for c in state["CompartmentManager"]["GasCompartment"]
                   if c["FluidCompartment"]["Compartment"]["Name"] == "Alveoli")
    children = alveoli["FluidCompartment"]["Compartment"]["Child"]
    assert len(children) == 2
    from pulse.cdm.engine import SEDataRequest
    from pulse.cdm.scalars import VolumeUnit

    engine = _direct_engine([SEDataRequest.create_gas_compartment_substance_request(c, "Oxygen", "Volume",
                                                                                    VolumeUnit.mL)
                             for c in children])
    engine.advance_time_s(7.0)
    expected = sum(float(v) for v in engine.pull_data()[1:])
    _, rows = run_composite(pulse_cardiovascular, 7.0, substance_outputs=[_entry("Oxygen", "Alveoli", "Volume", "mL")])
    assert rows[-1]["circuits"]["substances"]["Oxygen"]["Alveoli"]["volume_mL"] == pytest.approx(expected, rel=1e-9)


def test_blood_gases_agree_with_pulses_physiology(run_composite):
    """Falsifies: aortic oxygen and carbon dioxide are read as something other than the arterial
    blood gases Pulse reports (PaO2, PaCO2, SpO2), or end-tidal CO2 differs from Pulse's own.
    Unperturbed: the physiology values are taken at another point in the step (1e-7 apart)."""
    entries = [_entry("Oxygen", "Aorta", "PartialPressure", "mmHg"),
               _entry("CarbonDioxide", "Aorta", "PartialPressure", "mmHg"),
               _entry("Oxygen", "Aorta", "Saturation"),
               _entry("CarbonDioxide", None, "EndTidalPressure", "mmHg")]
    _, rows = run_composite(pulse_whole_body_circuits, 20.0, substance_outputs=entries)
    from pulse.cdm.engine import SEDataRequest
    from pulse.cdm.scalars import PressureUnit

    engine = _direct_engine([SEDataRequest.create_physiology_request("EndTidalCarbonDioxidePressure",
                                                                     PressureUnit.mmHg)])
    end_tidal = [float(engine.pull_data()[1])]
    engine.advance_time_s(20.0)
    end_tidal.append(float(engine.pull_data()[1]))
    for row, etco2 in zip((rows[0], rows[-1]), end_tidal):
        sub = row["circuits"]["substances"]
        oxygenation = row["circuits"]["supplemental_oxygen"]["oxygenation"]
        assert sub["Oxygen"]["Aorta"]["partial_pressure_mmHg"] == pytest.approx(
            oxygenation["arterial_oxygen_pressure_mmHg"], rel=1e-6)
        assert sub["CarbonDioxide"]["Aorta"]["partial_pressure_mmHg"] == pytest.approx(
            oxygenation["arterial_carbon_dioxide_pressure_mmHg"], rel=1e-6)
        assert sub["Oxygen"]["Aorta"]["saturation"] == pytest.approx(oxygenation["oxygen_saturation"], rel=1e-6)
        assert sub["CarbonDioxide"]["body"]["end_tidal_pressure_mmHg"] == pytest.approx(etco2, rel=1e-9)


def test_whole_body_masses_are_the_compartment_sums(run_composite):
    """Falsifies: MassInBlood / MassInTissue / MassInBody are read as anything but Pulse's totals
    over its vascular leaves and tissue fluids. Oracle: the sums through a separate engine, over
    compartment lists written out from Pulse's source (Ground excluded: it reads NaN)."""
    state = json.loads((ensure_pulse_importable() / "states" / STATE).read_text())
    children = {c["FluidCompartment"]["Compartment"]["Name"]: c["FluidCompartment"]["Compartment"].get("Child")
                for c in state["CompartmentManager"]["LiquidCompartment"]}
    leaves = [c for c in VASCULAR if not children[c]]
    fluids = [f"{t}Tissue{side}" for t in TISSUES_LIST for side in ("Extracellular", "Intracellular")]
    from pulse.cdm.engine import SEDataRequest
    from pulse.cdm.scalars import MassUnit

    requests = [SEDataRequest.create_liquid_compartment_substance_request(c, "Sodium", "Mass", MassUnit.mg)
                for c in leaves + fluids]
    engine = _direct_engine(requests)
    engine.advance_time_s(20.0)
    values = [float(v) for v in engine.pull_data()[1:]]
    blood, tissue = sum(values[:len(leaves)]), sum(values[len(leaves):])
    entries = [_entry("Sodium", None, p, "mg") for p in ("MassInBlood", "MassInTissue", "MassInBody")]
    _, rows = run_composite(pulse_cardiovascular, 20.0, substance_outputs=entries)
    body = rows[-1]["circuits"]["substances"]["Sodium"]["body"]
    # 1e-6: Pulse totals these earlier in the step than the compartment masses (measured 1.4e-7).
    assert body["mass_in_blood_mg"] == pytest.approx(blood, rel=1e-6)
    assert body["mass_in_tissue_mg"] == pytest.approx(tissue, rel=1e-6)
    assert body["mass_in_body_mg"] == pytest.approx(body["mass_in_blood_mg"] + body["mass_in_tissue_mg"], rel=1e-12)


def test_tissue_values_equal_pulses_own_state(run_composite):
    """Falsifies: a tissue composition value or a tissue fluid volume is read from the wrong
    compartment or property. Oracle: a separate engine's serialized state."""
    import PyPulse

    entries = [{"compartment": "BrainTissue", "property": "MatrixVolume", "unit": "mL"},
               {"compartment": "MuscleTissue", "property": "NeutralLipidsVolumeFraction"},
               {"compartment": "MuscleTissueExtracellular", "property": "Volume", "unit": "mL"},
               {"compartment": "MuscleTissueIntracellular", "property": "Volume", "unit": "mL"}]
    _, rows = run_composite(pulse_cardiovascular, 10.0, tissue_outputs=entries)
    engine = _direct_engine()
    engine.advance_time_s(10.0)
    state = _serialized(engine)
    got = rows[-1]["circuits"]["tissues"]
    tissue = next(t for t in state["CompartmentManager"]["TissueCompartment"]
                  if t["Compartment"]["Name"] == "BrainTissue")
    scalar = tissue["MatrixVolume"]["ScalarVolume"]
    assert got["BrainTissue"]["matrix_volume_mL"] == pytest.approx(
        PyPulse.convert(scalar["Value"], scalar["Unit"], "mL"), rel=1e-12)
    muscle = next(t for t in state["CompartmentManager"]["TissueCompartment"]
                  if t["Compartment"]["Name"] == "MuscleTissue")
    assert got["MuscleTissue"]["neutral_lipids_volume_fraction"] == pytest.approx(
        muscle["NeutralLipidsVolumeFraction"]["Scalar0To1"]["Value"], rel=1e-12)
    liquids = {c["FluidCompartment"]["Compartment"]["Name"]: c["FluidCompartment"]
               for c in state["CompartmentManager"]["LiquidCompartment"]}
    for side in ("Extracellular", "Intracellular"):
        volume = liquids[f"MuscleTissue{side}"]["Volume"]["ScalarVolume"]
        assert got[f"MuscleTissue{side}"]["volume_mL"] == pytest.approx(
            PyPulse.convert(volume["Value"], volume["Unit"], "mL"), rel=1e-9)


def test_readings_leave_the_simulation_unchanged(run_composite, assert_rows_close):
    """Falsifies: requesting substance or tissue values perturbs Pulse (any cardiovascular reading
    differs from a run without them), including during a hemorrhage."""
    _, plain = run_composite(pulse_cardiovascular, 20.0, hemorrhage_severity=0.5)
    _, read = run_composite(pulse_cardiovascular, 20.0, hemorrhage_severity=0.5,
                            substance_outputs=[_entry(s, c, p, u) for s, c, p, u, _ in LEAF_ENTRIES]
                            + [_entry("Sodium", None, "MassInBody", "mg")],
                            tissue_outputs=[{"compartment": "LiverTissueExtracellular", "property": "Pressure",
                                             "unit": "mmHg"}])
    assert_rows_close([r["circuits"]["cardiovascular"] for r in read],
                      [r["circuits"]["cardiovascular"] for r in plain])


def test_a_hemorrhage_drains_substances_from_the_blood(run_composite):
    """Falsifies: the readings don't follow the simulation (constant, or read once): a RightLeg
    0.8 hemorrhage must lower the sodium and hemoglobin in the blood against an unperturbed run."""
    entries = [_entry("Sodium", None, "MassInBlood", "g"), _entry("Hemoglobin", None, "MassInBlood", "g"),
               _entry("Sodium", "RightLegVasculature", "Mass", "mg")]
    _, base = run_composite(pulse_cardiovascular, 60.0, substance_outputs=entries)
    _, bleed = run_composite(pulse_cardiovascular, 60.0, substance_outputs=entries, hemorrhage_severity=0.8)
    for substance in ("Sodium", "Hemoglobin"):
        before = base[-1]["circuits"]["substances"][substance]["body"]["mass_in_blood_g"]
        after = bleed[-1]["circuits"]["substances"][substance]["body"]["mass_in_blood_g"]
        assert after < 0.98 * before, substance
    assert bleed[-1]["circuits"]["substances"]["Sodium"]["RightLegVasculature"]["mass_mg"] \
        < base[-1]["circuits"]["substances"]["Sodium"]["RightLegVasculature"]["mass_mg"]


def test_reading_activates_no_substance(run_composite):
    """Falsifies: a run with substance readings leaves extra active substances in the engine, which
    would then be saved into states (Pulse activates whatever it is asked about)."""
    sim, _ = run_composite(pulse_cardiovascular, 2.0,
                           substance_outputs=[_entry(s, c, p, u) for s, c, p, u, _ in LEAF_ENTRIES])
    loaded = json.loads((ensure_pulse_importable() / "states" / STATE).read_text())["ActiveSubstance"]
    after = _serialized(sim.state["pulse"]["instance"]._engine)["ActiveSubstance"]
    assert sorted(after) == sorted(loaded)
