"""Cardiovascular circuit module.

Pulse's cardiovascular circuit (diagram: ``docs/images/circuit-cardio.png``,
from ``engine/docs/Images/Cardiovascular/CardiovascularCircuit.png``) is solved
as one matrix together with the renal and tissue sub-circuits
(``CardiovascularModel::Process``), so all three are one module here. They are
grouped into sub-stores that follow the diagram's branches:

- ``hemodynamics``: Pulse's cardiovascular system scalars (``SECardiovascularSystem``).
  The mean/systolic/diastolic values are per-beat; the rest are instantaneous.
- ``central``: heart, great vessels and pulmonary circulation compartments.
- ``renal``: kidney vasculature compartments.
- ``peripheral``: the organ and limb branches.

Every compartment reports ``pressure_mmHg``, ``volume_mL``,
``inflow_mL_per_min`` and ``outflow_mL_per_min``. These are **instantaneous**
values that vary within each heartbeat. Sample at Pulse's own 0.02 s timestep
to see waveforms; slower sampling aliases the cardiac cycle. ``Pericardium`` is
a pressure/volume space with no blood path, so it has no flows (Pulse returns
NaN for them).

Lymph is not read, because Pulse 4.4.0 simulates none. Its ``FullCardiovascular``
circuit has a ``Lymph`` node, 13 ``<Tissue>T1ToLymph`` paths and ``LymphToVenaCava1``,
but each tissue-to-lymph path is a flow source with baseline 0 that nothing in the
engine ever sets (``SetupCircuitsAndCompartments.cpp``), the node has no volume, and
``Lymph`` is in no liquid graph, so no fluid or substance moves through it; its
pressure equals ``VenaCava1``'s. Pulse inherited this stub from BioGears in 2017
(BioGears later built an active lymph model). ``cardiovascular_points`` reads all of
it (``nodes/Lymph``, ``paths/*ToLymph``, ``paths/LymphToVenaCava1``), and
``tests/test_lymph.py`` fails if a Pulse upgrade switches it on (probe
``substances-lymph-2026-11-01``, plan ``docs/plan/plan-substances-and-lymph.md``).

Setpoints: Pulse's ``SECardiovascularMechanicsModifiers`` multipliers (1.0 =
unmodified) and a hemorrhage. The multipliers are sent as one
``SECardiovascularMechanicsModification`` with ``incremental=True``. Pulse's
non-incremental mode reruns stabilization with the baroreflex off and resets
the patient's pressure baselines (``Controller::ProcessAction``). Each send
replaces the whole modifier set (``SEPatientActionCollection``), so every
multiplier is always sent.
"""

from __future__ import annotations

from typing import Any

from .base import ActionBinding, CircuitModule, Request

HEMORRHAGE_COMPARTMENTS = (
    "Aorta", "Brain", "Muscle", "LargeIntestine", "LeftArm", "LeftKidney",
    "LeftLeg", "Liver", "RightArm", "RightKidney", "RightLeg", "Skin",
    "SmallIntestine", "Splanchnic", "Spleen", "VenaCava",
)

_mmHg = ("PressureUnit", "mmHg")
_mL = ("VolumeUnit", "mL")
_mL_per_min = ("VolumePerTimeUnit", "mL_Per_min")
_L_per_min = ("VolumePerTimeUnit", "L_Per_min")
_per_min = ("FrequencyUnit", "Per_min")
_resistance = ("PressureTimePerVolumeUnit", "mmHg_min_Per_L")

# port -> (SECardiovascularSystem property, unit)
_HEMODYNAMICS = {
    "heart_rate_bpm": ("HeartRate", _per_min),
    "mean_arterial_pressure_mmHg": ("MeanArterialPressure", _mmHg),
    "systolic_pressure_mmHg": ("SystolicArterialPressure", _mmHg),
    "diastolic_pressure_mmHg": ("DiastolicArterialPressure", _mmHg),
    "arterial_pressure_mmHg": ("ArterialPressure", _mmHg),
    "pulse_pressure_mmHg": ("PulsePressure", _mmHg),
    "cardiac_output_L_per_min": ("CardiacOutput", _L_per_min),
    "stroke_volume_mL": ("HeartStrokeVolume", _mL),
    "ejection_fraction": ("HeartEjectionFraction", None),
    "central_venous_pressure_mmHg": ("CentralVenousPressure", _mmHg),
    "mean_central_venous_pressure_mmHg": ("MeanCentralVenousPressure", _mmHg),
    "pulmonary_arterial_pressure_mmHg": ("PulmonaryArterialPressure", _mmHg),
    "pulmonary_mean_arterial_pressure_mmHg": ("PulmonaryMeanArterialPressure", _mmHg),
    "pulmonary_capillary_wedge_pressure_mmHg": ("PulmonaryCapillariesWedgePressure", _mmHg),
    "systemic_vascular_resistance_mmHg_min_per_L": ("SystemicVascularResistance", _resistance),
    "pulmonary_vascular_resistance_mmHg_min_per_L": ("PulmonaryVascularResistance", _resistance),
    "blood_volume_mL": ("BloodVolume", _mL),
    "total_hemorrhaged_volume_mL": ("TotalHemorrhagedVolume", _mL),
    "cerebral_blood_flow_mL_per_min": ("CerebralBloodFlow", _mL_per_min),
    "mean_skin_flow_mL_per_min": ("MeanSkinFlow", _mL_per_min),
}

# group -> {store name: Pulse compartment name (engine/PulseEngine.h VascularCompartment)}
_COMPARTMENTS = {
    "central": {
        "aorta": "Aorta",
        "heart": "Heart",
        "left_heart": "LeftHeart",
        "right_heart": "RightHeart",
        "myocardium": "MyocardiumVasculature",
        "pericardium": "Pericardium",
        "vena_cava": "VenaCava",
        "pulmonary_arteries": "PulmonaryArteries",
        "pulmonary_capillaries": "PulmonaryCapillaries",
        "pulmonary_veins": "PulmonaryVeins",
    },
    "renal": {
        "left_kidney": "LeftKidneyVasculature",
        "right_kidney": "RightKidneyVasculature",
        "left_renal_artery": "LeftRenalArtery",
        "right_renal_artery": "RightRenalArtery",
        "left_glomerular_capillaries": "LeftGlomerularCapillaries",
        "right_glomerular_capillaries": "RightGlomerularCapillaries",
        "left_renal_vein": "LeftRenalVein",
        "right_renal_vein": "RightRenalVein",
    },
    "peripheral": {
        "brain": "BrainVasculature",
        "muscle": "MuscleVasculature",
        "skin": "SkinVasculature",
        "fat": "FatVasculature",
        "bone": "BoneVasculature",
        "liver": "LiverVasculature",
        "spleen": "SpleenVasculature",
        "splanchnic": "SplanchnicVasculature",
        "small_intestine": "SmallIntestineVasculature",
        "large_intestine": "LargeIntestineVasculature",
        "left_arm": "LeftArmVasculature",
        "right_arm": "RightArmVasculature",
        "left_leg": "LeftLegVasculature",
        "right_leg": "RightLegVasculature",
    },
}

_COMPARTMENT_PROPERTIES = {
    "pressure_mmHg": ("Pressure", _mmHg),
    "volume_mL": ("Volume", _mL),
    "inflow_mL_per_min": ("Inflow", _mL_per_min),
    "outflow_mL_per_min": ("Outflow", _mL_per_min),
}

_NO_FLOW = {"Pericardium"}

MULTIPLIERS = (
    "arterial_compliance", "arterial_resistance",
    "pulmonary_compliance", "pulmonary_resistance",
    "systemic_compliance", "systemic_resistance",
    "venous_compliance", "venous_resistance",
    "heart_rate", "stroke_volume",
)


def _outputs() -> tuple[Request, ...]:
    requests = [Request(("hemodynamics", port), "physiology", prop, unit)
                for port, (prop, unit) in _HEMODYNAMICS.items()]
    for group, compartments in _COMPARTMENTS.items():
        for name, compartment in compartments.items():
            for port, (prop, unit) in _COMPARTMENT_PROPERTIES.items():
                if compartment in _NO_FLOW and prop in ("Inflow", "Outflow"):
                    continue
                requests.append(Request((group, name, port), "liquid_compartment", prop, unit,
                                        compartment=compartment))
    return tuple(requests)


def _validate_multipliers(values: dict[str, float], config: dict[str, Any]) -> None:
    for port, value in values.items():
        if not value > 0.0:
            raise ValueError(f"{port} must be > 0, got {value}")


def _build_multipliers(values: dict[str, float], config: dict[str, Any]):
    from pulse.cdm.patient_actions import SECardiovascularMechanicsModification

    action = SECardiovascularMechanicsModification()
    action.set_incremental(True)
    modifiers = action.get_modifiers()
    for name in MULTIPLIERS:
        getattr(modifiers, f"get_{name}_multiplier")().set_value(values[f"{name}_multiplier"])
    return action


def _validate_hemorrhage(values: dict[str, float], config: dict[str, Any]) -> None:
    severity = values["hemorrhage_severity"]
    if not 0.0 <= severity <= 1.0:
        raise ValueError(f"hemorrhage_severity must be in [0, 1], got {severity}")


def _build_hemorrhage(values: dict[str, float], config: dict[str, Any]):
    from pulse.cdm.patient_actions import SEHemorrhage

    action = SEHemorrhage()
    action.set_compartment(config["hemorrhage_compartment"])
    action.get_severity().set_value(values["hemorrhage_severity"])
    return action


def _check_config(config: dict[str, Any]) -> None:
    if config["hemorrhage_compartment"] not in HEMORRHAGE_COMPARTMENTS:
        raise ValueError(f"hemorrhage_compartment must be one of {HEMORRHAGE_COMPARTMENTS}, "
                         f"got {config['hemorrhage_compartment']!r}")


CARDIOVASCULAR = CircuitModule(
    name="cardiovascular",
    model_types=frozenset({"whole_body"}),
    outputs=_outputs(),
    bindings=(
        ActionBinding(ports={f"{name}_multiplier": 1.0 for name in MULTIPLIERS},
                      build=_build_multipliers, validate=_validate_multipliers),
        ActionBinding(ports={"hemorrhage_severity": 0.0},
                      build=_build_hemorrhage, validate=_validate_hemorrhage),
    ),
    params={"hemorrhage_compartment": {"_type": "string", "_default": "RightLeg"}},
    check_config=_check_config,
)
