"""Substance, tissue and lymph data requests on the real Pulse engine (issues #35, #36).

Scoping probe for docs/plan/plan-substances-and-lymph.md. Real Pulse, StandardMale@0s.json,
requests built straight through Pulse's Python API (no viva-pulse code beyond locating the
install). One JSON line per mode on stdout.

Modes:
  lymph      Lymph compartment Pressure/Volume/Inflow/Outflow (and Albumin, Sodium in it):
             unperturbed, under a RightLeg 0.8 hemorrhage, and under a 250 mL/min saline
             infusion. Is it served, is it ever non-zero, which perturbation moves it?
  reads      One request of each kind for active substances: liquid (vascular, tissue
             extra/intracellular, lymph), gas, whole-body, tissue. Compared with the
             physiology scalars that should agree (arterial PO2/PCO2, end-tidal CO2).
  mass       Whole-body MassInBody/MassInBlood/MassInTissue of Sodium against the sum of
             compartment masses over Pulse's own leaf lists (BloodChemistryModel.cpp:343-352,
             CompartmentManager.cpp:160-205, SubstanceManager.cpp:1154).
  observer   Does requesting a substance change the run? Arms: none, Sodium (active),
             Fentanyl (inactive in the state; SEDataRequestTracker.cpp:482-484 activates it).
  invalid:<case>  One bad request, run in a child process (it may crash): bad substance,
             bad compartment, bad property, incompatible unit, substance+compartment
             property other than PartitionCoefficient.
  recheck    Re-probes of the adversarial review's findings (2026-11-01): requests on
             compartments that hold no quantity for the substance (aerosol liquid Alveoli, gas
             Alveoli with a liquid substance), each in a child process; whether an unknown or
             inactive substance name ends up in the saved state; substance-dependent NaN
             (Sodium PartialPressure/Saturation); a CarbonMonoxide request's effect on the run;
             tissue fluid compartments without a substance; lymph = VenaCava1 pressure and
             lymph graph membership after 7 s.

Run (repo root): uv run --no-sync python workspace/experiments/substances-lymph-2026-11-01/probe_substances_lymph.py <mode>
"""
import json, math, subprocess, sys

from viva_pulse.runtime import ensure_pulse_importable

BIN = ensure_pulse_importable("")

from pulse.cdm.engine import SEDataRequest, SEDataRequestManager, eDataRequest_category
from pulse.cdm.patient_actions import SEHemorrhage, SESubstanceCompoundInfusion
from pulse.cdm.scalars import (AmountPerVolumeUnit, FrequencyUnit, MassPerVolumeUnit, MassUnit, PressureUnit,
                               SEScalarUnit, VolumePerTimeUnit, VolumeUnit)
from pulse.engine.PulseEngine import PulseEngine, eModelType

STATE = BIN / "states" / "StandardMale@0s.json"
R = SEDataRequest

# Pulse's vascular compartment list (engine/PulseEngine.h VascularCompartment) and tissues.
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
            "RightArmVasculature", "RightLegVasculature", "Abdomen", "AbdominalCavity", "Ground"]
TISSUES = ["Bone", "Brain", "Fat", "Gut", "LeftKidney", "LeftLung", "Liver", "Muscle", "Myocardium", "RightKidney",
           "RightLung", "Skin", "Spleen"]


def engine(requests, state=None):
    e = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    e.log_to_console(False)
    mgr = SEDataRequestManager([r for _, r in requests])
    ok = (e.serialize_from_string(json.dumps(state), mgr) if state is not None
          else e.serialize_from_file(str(STATE), mgr))
    assert ok, "load failed"
    e.advance_time_s(0.0)
    return e


def read(e, requests):
    return {name: float(v) for (name, _), v in zip(requests, e.pull_data()[1:])}


def clean(d):
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


def lymph():
    mL_min = VolumePerTimeUnit.mL_Per_min
    reqs = [("pressure", R.create_liquid_compartment_request("Lymph", "Pressure", PressureUnit.mmHg)),
            ("volume", R.create_liquid_compartment_request("Lymph", "Volume", VolumeUnit.mL)),
            ("inflow", R.create_liquid_compartment_request("Lymph", "Inflow", mL_min)),
            ("outflow", R.create_liquid_compartment_request("Lymph", "Outflow", mL_min)),
            ("albumin_g_per_L", R.create_liquid_compartment_substance_request("Lymph", "Albumin", "Concentration",
                                                                             MassPerVolumeUnit.g_Per_L)),
            ("sodium_g_per_L", R.create_liquid_compartment_substance_request("Lymph", "Sodium", "Concentration",
                                                                            MassPerVolumeUnit.g_Per_L)),
            ("blood_volume", R.create_physiology_request("BloodVolume", VolumeUnit.mL))]
    out = {}
    for arm in ("unperturbed", "hemorrhage", "infusion"):
        e = engine(reqs)
        if arm == "hemorrhage":
            h = SEHemorrhage(); h.set_compartment("RightLeg"); h.get_severity().set_value(0.8)
            e.process_action(h)
        if arm == "infusion":
            i = SESubstanceCompoundInfusion(); i.set_compound("Saline")
            i.get_rate().set_value(250, VolumePerTimeUnit.mL_Per_min); i.get_bag_volume().set_value(5000, VolumeUnit.mL)
            e.process_action(i)
        rows, t = {}, 0
        rows[0] = clean(read(e, reqs))
        for target in (1, 10, 60, 300):
            e.advance_time_s(float(target - t)); t = target
            rows[target] = clean(read(e, reqs))
        out[arm] = rows
    return out


def reads():
    reqs = [
        ("po2_aorta_mmHg", R.create_liquid_compartment_substance_request("Aorta", "Oxygen", "PartialPressure", PressureUnit.mmHg)),
        ("arterial_po2_mmHg", R.create_physiology_request("ArterialOxygenPressure", PressureUnit.mmHg)),
        ("pco2_aorta_mmHg", R.create_liquid_compartment_substance_request("Aorta", "CarbonDioxide", "PartialPressure", PressureUnit.mmHg)),
        ("arterial_pco2_mmHg", R.create_physiology_request("ArterialCarbonDioxidePressure", PressureUnit.mmHg)),
        ("o2_sat_aorta", R.create_liquid_compartment_substance_request("Aorta", "Oxygen", "Saturation")),
        ("spo2", R.create_physiology_request("OxygenSaturation")),
        ("na_aorta_g_per_L", R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L)),
        ("na_aorta_mmol_per_L", R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Molarity", AmountPerVolumeUnit.mmol_Per_L)),
        ("na_brain_ec_g_per_L", R.create_liquid_compartment_substance_request("BrainTissueExtracellular", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L)),
        ("na_brain_ic_g_per_L", R.create_liquid_compartment_substance_request("BrainTissueIntracellular", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L)),
        ("glucose_muscle_ic_mg", R.create_liquid_compartment_substance_request("MuscleTissueIntracellular", "Glucose", "Mass", MassUnit.mg)),
        ("o2_alveoli_pp_mmHg", R.create_gas_compartment_substance_request("Alveoli", "Oxygen", "PartialPressure", PressureUnit.mmHg)),
        ("o2_alveoli_fraction", R.create_gas_compartment_substance_request("Alveoli", "Oxygen", "VolumeFraction")),
        ("o2_alveoli_volume_mL", R.create_gas_compartment_substance_request("Alveoli", "Oxygen", "Volume", VolumeUnit.mL)),
        ("co2_end_tidal_mmHg", R.create_substance_request("CarbonDioxide", "EndTidalPressure", PressureUnit.mmHg)),
        ("etco2_physiology_mmHg", R.create_physiology_request("EndTidalCarbonDioxidePressure", PressureUnit.mmHg)),
        ("na_plasma_g_per_L", R.create_substance_request("Sodium", "PlasmaConcentration", MassPerVolumeUnit.g_Per_L)),
        ("na_blood_g_per_L", R.create_substance_request("Sodium", "BloodConcentration", MassPerVolumeUnit.g_Per_L)),
        ("na_tissue_g_per_L", R.create_substance_request("Sodium", "TissueConcentration", MassPerVolumeUnit.g_Per_L)),
        ("na_cleared_mg", R.create_substance_request("Sodium", "SystemicMassCleared", MassUnit.mg)),
        ("brain_matrix_mL", R.create_tissue_request("BrainTissue", "MatrixVolume", VolumeUnit.mL)),
        ("brain_total_mass_g", R.create_tissue_request("BrainTissue", "TotalMass", MassUnit.g)),
        ("brain_neutral_lipids", R.create_tissue_request("BrainTissue", "NeutralLipidsVolumeFraction")),
    ]
    e = engine(reqs)
    out = {"t0": clean(read(e, reqs))}
    e.advance_time_s(10.0)
    out["t10"] = clean(read(e, reqs))
    return out


def mass():
    state = json.loads(STATE.read_text())
    children = {c["FluidCompartment"]["Compartment"]["Name"]: c["FluidCompartment"]["Compartment"].get("Child", [])
                for c in state["CompartmentManager"]["LiquidCompartment"]}
    leaves = [c for c in VASCULAR if c in children and not children[c]]
    tissue = [f"{t}Tissue{k}" for t in TISSUES for k in ("Extracellular", "Intracellular")]
    reqs = [("body", R.create_substance_request("Sodium", "MassInBody", MassUnit.mg)),
            ("blood", R.create_substance_request("Sodium", "MassInBlood", MassUnit.mg)),
            ("tissue", R.create_substance_request("Sodium", "MassInTissue", MassUnit.mg))]
    reqs += [(f"v:{c}", R.create_liquid_compartment_substance_request(c, "Sodium", "Mass", MassUnit.mg)) for c in leaves]
    reqs += [(f"t:{c}", R.create_liquid_compartment_substance_request(c, "Sodium", "Mass", MassUnit.mg)) for c in tissue]
    reqs += [("lymph", R.create_liquid_compartment_substance_request("Lymph", "Sodium", "Mass", MassUnit.mg))]
    e = engine(reqs)
    out = {"leaves": leaves}
    for t in (0, 10):
        if t:
            e.advance_time_s(10.0)
        v = read(e, reqs)
        # Ground is in Pulse's vascular list but serves no substance quantity (NaN); skipped.
        out[f"nan_t{t}"] = [k for k, x in v.items() if math.isnan(x)]
        sv = sum(x for k, x in v.items() if k.startswith("v:") and not math.isnan(x))
        st = sum(x for k, x in v.items() if k.startswith("t:"))
        out[f"t{t}"] = {"body": v["body"], "blood": v["blood"], "tissue": v["tissue"], "sum_vascular": sv,
                        "sum_tissue": st, "lymph": v["lymph"],
                        "rel_blood": (sv - v["blood"]) / v["blood"], "rel_tissue": (st - v["tissue"]) / v["tissue"]}
    return out


def observer():
    base = [("hr", R.create_physiology_request("HeartRate", FrequencyUnit.Per_min)),
            ("map", R.create_physiology_request("MeanArterialPressure", PressureUnit.mmHg)),
            ("po2", R.create_physiology_request("ArterialOxygenPressure", PressureUnit.mmHg)),
            ("bv", R.create_physiology_request("BloodVolume", VolumeUnit.mL))]
    extra = {"none": [],
             "sodium": [("x", R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L))],
             "fentanyl": [("x", R.create_liquid_compartment_substance_request("Aorta", "Fentanyl", "Concentration", MassPerVolumeUnit.ug_Per_L))],
             "fentanyl_body": [("x", R.create_substance_request("Fentanyl", "PlasmaConcentration", MassPerVolumeUnit.ug_Per_L))]}
    out = {}
    for arm, more in extra.items():
        reqs = base + more
        e = engine(reqs)
        first = clean(read(e, reqs))
        e.advance_time_s(60.0)
        out[arm] = {"t0": first, "t60": clean(read(e, reqs))}
    ref = out["none"]["t60"]
    out["max_rel_diff_vs_none"] = {arm: max(abs(out[arm]["t60"][k] - ref[k]) / abs(ref[k]) for k in ref)
                                  for arm in extra if arm != "none"}
    return out


INVALID = {
    "substance": lambda: R.create_liquid_compartment_substance_request("Aorta", "Oxygenn", "PartialPressure", PressureUnit.mmHg),
    "compartment": lambda: R.create_liquid_compartment_substance_request("Aortaa", "Oxygen", "PartialPressure", PressureUnit.mmHg),
    "property": lambda: R.create_liquid_compartment_substance_request("Aorta", "Oxygen", "PartialPresure", PressureUnit.mmHg),
    "unit": lambda: R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Concentration", PressureUnit.mmHg),
    "unit_string": lambda: R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Concentration", SEScalarUnit("furlong")),
    "gas_in_liquid": lambda: R.create_gas_compartment_substance_request("Aorta", "Oxygen", "PartialPressure", PressureUnit.mmHg),
    "body_property": lambda: R.create_substance_request("Sodium", "Concentration", MassPerVolumeUnit.g_Per_L),
    "body_with_compartment": lambda: R(eDataRequest_category.Substance, compartment="BrainTissue", substance="Sodium",
                                       property="MassInBody", unit=MassUnit.mg),
    "tissue_property": lambda: R.create_tissue_request("BrainTissue", "Volume", VolumeUnit.mL),
}


def invalid_child(case):
    reqs = [("hr", R.create_physiology_request("HeartRate", FrequencyUnit.Per_min)), ("bad", INVALID[case]())]
    try:
        e = engine(reqs)
    except Exception as exc:  # noqa: BLE001 - recorded, not handled
        return {"load": f"raised {type(exc).__name__}: {exc}"}
    first = clean(read(e, reqs))
    ok = e.advance_time_s(1.0)
    return {"load": "ok", "t0": first, "advance_ok": bool(ok), "t1": clean(read(e, reqs))}


KIND = {
    "liquid_alveoli_o2": lambda: R.create_liquid_compartment_substance_request("Alveoli", "Oxygen", "PartialPressure", PressureUnit.mmHg),
    "liquid_alveoli_na": lambda: R.create_liquid_compartment_substance_request("Alveoli", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L),
    "gas_alveoli_na": lambda: R.create_gas_compartment_substance_request("Alveoli", "Sodium", "PartialPressure", PressureUnit.mmHg),
    "gas_alveoli_o2": lambda: R.create_gas_compartment_substance_request("Alveoli", "Oxygen", "PartialPressure", PressureUnit.mmHg),
    "liquid_aorta_o2": lambda: R.create_liquid_compartment_substance_request("Aorta", "Oxygen", "PartialPressure", PressureUnit.mmHg),
}
INVALID.update(KIND)


def recheck():
    import PyPulse
    out = {}
    for case in KIND:
        p = subprocess.run([sys.executable, __file__, f"invalid:{case}"], capture_output=True, text=True, timeout=300)
        line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else None
        out[f"kind:{case}"] = {"exit": p.returncode, "result": json.loads(line)["result"] if line else None}
    # names that end up active / defined in the saved state
    names = [("unknown_body", R.create_substance_request("Sodiumm", "MassInBody", MassUnit.mg)),
             ("unknown_cmpt", R.create_liquid_compartment_substance_request("Aorta", "Oxygenn", "PartialPressure", PressureUnit.mmHg)),
             ("inactive", R.create_liquid_compartment_substance_request("Aorta", "Fentanyl", "Concentration", MassPerVolumeUnit.ug_Per_L))]
    e = engine(names)
    first = clean(read(e, names))
    e.advance_time_s(1.0)
    st = json.loads(e.serialize_to_string(PyPulse.serialization_format.json))
    out["names"] = {"t0": first, "t1": clean(read(e, names)), "n_substance_defs": len(st["Substance"]),
                    "active_added": [n for n in st["ActiveSubstance"] if n in ("Sodiumm", "Oxygenn", "Fentanyl")]}
    dep = [("na_pp", R.create_liquid_compartment_substance_request("Aorta", "Sodium", "PartialPressure", PressureUnit.mmHg)),
           ("na_sat", R.create_liquid_compartment_substance_request("Aorta", "Sodium", "Saturation")),
           ("co2_sat", R.create_liquid_compartment_substance_request("Aorta", "CarbonDioxide", "Saturation")),
           ("na_endtidal", R.create_substance_request("Sodium", "EndTidalPressure", PressureUnit.mmHg)),
           ("globulin_blood", R.create_substance_request("Globulin", "BloodConcentration", MassPerVolumeUnit.g_Per_L)),
           ("hb_blood_conc", R.create_substance_request("Hemoglobin", "BloodConcentration", MassPerVolumeUnit.g_Per_L)),
           ("hb_mass_blood", R.create_substance_request("Hemoglobin", "MassInBlood", MassUnit.g)),
           ("brain_ec_volume", R.create_liquid_compartment_request("BrainTissueExtracellular", "Volume", VolumeUnit.mL)),
           ("brain_ec_pressure", R.create_liquid_compartment_request("BrainTissueExtracellular", "Pressure", PressureUnit.mmHg)),
           ("brain_ic_volume", R.create_liquid_compartment_request("BrainTissueIntracellular", "Volume", VolumeUnit.mL))]
    e = engine(dep)
    first = clean(read(e, dep))
    e.advance_time_s(10.0)
    out["dependent"] = {"t0": first, "t10": clean(read(e, dep))}
    base = [("po2", R.create_physiology_request("ArterialOxygenPressure", PressureUnit.mmHg)),
            ("hr", R.create_physiology_request("HeartRate", FrequencyUnit.Per_min))]
    runs = {}
    for arm, more in {"none": [], "co": [("x", R.create_gas_compartment_substance_request("Alveoli", "CarbonMonoxide", "PartialPressure", PressureUnit.mmHg))]}.items():
        e = engine(base + more)
        e.advance_time_s(5.0)
        runs[arm] = read(e, base + more)
    out["co_observer"] = {"runs": clean(runs["co"]), "rel_po2": (runs["co"]["po2"] - runs["none"]["po2"]) / runs["none"]["po2"],
                          "rel_hr": (runs["co"]["hr"] - runs["none"]["hr"]) / runs["none"]["hr"]}
    e = engine([])
    e.advance_time_s(7.0)
    st = json.loads(e.serialize_to_string(PyPulse.serialization_format.json))
    nodes = {n["CircuitNode"]["Name"]: n for n in st["CircuitManager"]["FluidNode"]}
    pr = lambda n: nodes[n]["Pressure"]["ScalarPressure"].get("Value", 0.0)
    out["lymph_t7"] = {"lymph_mmHg": pr("Lymph"), "venacava1_mmHg": pr("VenaCava1"),
                       "graphs_with_lymph": [g["FluidGraph"]["Graph"]["Name"] for g in st["CompartmentManager"]["LiquidGraph"]
                                             if "Lymph" in g["FluidGraph"]["Graph"].get("Compartment", [])],
                       "n_graphs": len(st["CompartmentManager"]["LiquidGraph"])}
    return out


def invalid_all():
    out = {}
    for case in INVALID:
        p = subprocess.run([sys.executable, __file__, f"invalid:{case}"], capture_output=True, text=True, timeout=300)
        line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else None
        out[case] = {"exit": p.returncode, "result": json.loads(line)["result"] if line else None,
                     "stderr_tail": p.stderr.strip().splitlines()[-3:]}
    return out


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode.startswith("invalid:"):
        result = invalid_child(mode.split(":", 1)[1])
    else:
        result = {"lymph": lymph, "reads": reads, "mass": mass, "observer": observer, "invalid": invalid_all,
                  "recheck": recheck}[mode]()
    print(json.dumps({"mode": mode, "result": result}))
