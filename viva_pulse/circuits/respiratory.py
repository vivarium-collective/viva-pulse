"""Respiratory circuit and mechanical-ventilator modules.

Pulse solves the airway as one circuit: the respiratory circuit, combined with
whichever airway device is connected (``CircuitManager::GetActiveRespiratoryCircuit``).
Diagrams: ``engine/docs/Images/Respiratory/RespiratoryCircuit.png`` and
``engine/docs/Images/MechanicalVentilator/MechanicalVentilatorCircuit.png``.
Both modules run on the WholeBody engine and on the isolated
HumanAdultVentilationMechanics engine. The latter has no blood, gas exchange or
chemoreflex, so a mechanics change there is not compensated by the respiratory
drive (compliance x0.5: tidal volume falls 43% with the rate unchanged, while
WholeBody raises the rate from 12 to 15).

``respiratory`` readings:

- ``mechanics``: Pulse's respiratory-system scalars. Pressures are cmH2O
  relative to atmosphere, and per-breath values update once per breath.
- ``lungs`` and ``pleura``: gas compartments. Their ``absolute_pressure_cmH2O``
  is **absolute** (Pulse's ambient is 1033.2 cmH2O); subtract ambient for gauge
  pressure. Values are instantaneous within a breath, so sample at Pulse's
  0.02 s timestep to resolve the cycle. Compartments are hierarchical (a lung
  contains its alveoli), so their volumes do not add up.
- Pulse models positive-pressure ventilation with its own modifiers: airway
  resistance x15, plus a compliance change (the "diseases" table in
  ``RespiratoryMethodology.md``). Ventilated readings include those modifiers.

``respiratory`` setpoints:

- The ten ``SERespiratoryMechanicsModifiers`` multipliers, sent as one
  ``SERespiratoryMechanicsModification`` with ``incremental=True``. Pulse's
  non-incremental mode restabilizes, and the VentilationMechanics engine has no
  stabilizer. Every multiplier is sent each time, because Pulse replaces the
  whole set.
- ``intubated`` (0/1), with the tube type from config ``intubation_type``.
  Intubation is one-way: Pulse's Python ``SEIntubation.is_valid()`` rejects
  type Off, so ``PulseEngine`` would silently drop an extubation. A 1 -> 0
  change therefore raises instead of leaving the store and the engine out of
  agreement.

``mechanical_ventilator`` readings: the ventilator's own monitor values. They
read 0 while it is disconnected.

``mechanical_ventilator`` setpoints: one pressure-control group (``connected``
0/1 plus its settings).

- Connected sends ``SEMechanicalVentilatorPressureControl`` in mode
  ``ventilator_mode``. Without intubation it acts as a mask.
- Disconnected sends ``SEMechanicalVentilatorConfiguration`` with
  ``connection=Off``, the idiom Pulse's own scenarios use. A pressure-control
  action carrying only ``connection=Off`` is dropped by Pulse's Python API:
  ``SEMechanicalVentilatorPressureControl.is_valid()`` requires the pressure
  settings, although the C++ engine accepts a bare Off
  (``SEMechanicalVentilatorPressureControl::IsValid``).
- ``connected`` is the module's ``airway_device``: Pulse allows one airway
  device at a time, so it cannot be 1 while supplemental oxygen is connected
  (see ``supplemental_oxygen``).
"""

from __future__ import annotations

from typing import Any

from .base import ActionBinding, CircuitModule, Request, validate_switch

BOTH_ENGINES = frozenset({"whole_body", "ventilation_mechanics"})

INTUBATION_TYPES = ("Tracheal", "Esophageal", "LeftMainstem", "RightMainstem",
                    "Oropharyngeal", "Nasopharyngeal")
VENTILATOR_MODES = ("AssistedControl", "ContinuousMandatoryVentilation")

_cmH2O = ("PressureUnit", "cmH2O")
_mL = ("VolumeUnit", "mL")
_L_per_min = ("VolumePerTimeUnit", "L_Per_min")
_per_min = ("FrequencyUnit", "Per_min")
_compliance = ("VolumePerPressureUnit", "mL_Per_cmH2O")
_resistance = ("PressureTimePerVolumeUnit", "cmH2O_s_Per_L")

# port -> (SERespiratorySystem property, unit)
_MECHANICS = {
    "respiration_rate_bpm": ("RespirationRate", _per_min),
    "tidal_volume_mL": ("TidalVolume", _mL),
    "inspiratory_tidal_volume_mL": ("InspiratoryTidalVolume", _mL),
    "expiratory_tidal_volume_mL": ("ExpiratoryTidalVolume", _mL),
    "total_lung_volume_mL": ("TotalLungVolume", _mL),
    "total_pulmonary_ventilation_L_per_min": ("TotalPulmonaryVentilation", _L_per_min),
    "total_alveolar_ventilation_L_per_min": ("TotalAlveolarVentilation", _L_per_min),
    "inspiratory_flow_L_per_min": ("InspiratoryFlow", _L_per_min),
    "expiratory_flow_L_per_min": ("ExpiratoryFlow", _L_per_min),
    "inspiratory_expiratory_ratio": ("InspiratoryExpiratoryRatio", None),
    "peak_inspiratory_pressure_cmH2O": ("PeakInspiratoryPressure", _cmH2O),
    "mean_airway_pressure_cmH2O": ("MeanAirwayPressure", _cmH2O),
    "total_peep_cmH2O": ("TotalPositiveEndExpiratoryPressure", _cmH2O),
    "intrinsic_peep_cmH2O": ("IntrinsicPositiveEndExpiratoryPressure", _cmH2O),
    "intrapleural_pressure_cmH2O": ("IntrapleuralPressure", _cmH2O),
    "intrapulmonary_pressure_cmH2O": ("IntrapulmonaryPressure", _cmH2O),
    "transpulmonary_pressure_cmH2O": ("TranspulmonaryPressure", _cmH2O),
    "respiratory_muscle_pressure_cmH2O": ("RespiratoryMusclePressure", _cmH2O),
    "respiratory_compliance_mL_per_cmH2O": ("RespiratoryCompliance", _compliance),
    "lung_compliance_mL_per_cmH2O": ("LungCompliance", _compliance),
    "chest_wall_compliance_mL_per_cmH2O": ("ChestWallCompliance", _compliance),
    "inspiratory_resistance_cmH2O_s_per_L": ("InspiratoryRespiratoryResistance", _resistance),
    "expiratory_resistance_cmH2O_s_per_L": ("ExpiratoryRespiratoryResistance", _resistance),
    "fraction_inspired_oxygen": ("FractionOfInspiredOxygen", None),
}

# group -> {store name: Pulse gas compartment (engine/PulseEngine.h PulmonaryCompartment)}
_COMPARTMENTS = {
    "lungs": {
        "trachea": "Trachea",
        "anatomic_dead_space": "AnatomicDeadSpace",
        "left_lung": "LeftLungPulmonary",
        "right_lung": "RightLungPulmonary",
        "left_alveoli": "LeftAlveoli",
        "right_alveoli": "RightAlveoli",
    },
    "pleura": {
        "left_pleural_cavity": "LeftPleuralCavity",
        "right_pleural_cavity": "RightPleuralCavity",
    },
}

_COMPARTMENT_PROPERTIES = {
    "absolute_pressure_cmH2O": ("Pressure", _cmH2O),
    "volume_mL": ("Volume", _mL),
    "inflow_L_per_min": ("Inflow", _L_per_min),
    "outflow_L_per_min": ("Outflow", _L_per_min),
}

# port -> (SEMechanicalVentilator property, unit)
_VENTILATOR = {
    "airway_pressure_cmH2O": ("AirwayPressure", _cmH2O),
    "peak_inspiratory_pressure_cmH2O": ("PeakInspiratoryPressure", _cmH2O),
    "plateau_pressure_cmH2O": ("PlateauPressure", _cmH2O),
    "mean_airway_pressure_cmH2O": ("MeanAirwayPressure", _cmH2O),
    "total_peep_cmH2O": ("TotalPositiveEndExpiratoryPressure", _cmH2O),
    "intrinsic_peep_cmH2O": ("IntrinsicPositiveEndExpiratoryPressure", _cmH2O),
    "tidal_volume_mL": ("TidalVolume", _mL),
    "inspiratory_tidal_volume_mL": ("InspiratoryTidalVolume", _mL),
    "expiratory_tidal_volume_mL": ("ExpiratoryTidalVolume", _mL),
    "respiration_rate_bpm": ("RespirationRate", _per_min),
    "total_pulmonary_ventilation_L_per_min": ("TotalPulmonaryVentilation", _L_per_min),
    "inspiratory_flow_L_per_min": ("InspiratoryFlow", _L_per_min),
    "expiratory_flow_L_per_min": ("ExpiratoryFlow", _L_per_min),
    "peak_inspiratory_flow_L_per_min": ("PeakInspiratoryFlow", _L_per_min),
    "dynamic_compliance_mL_per_cmH2O": ("DynamicRespiratoryCompliance", _compliance),
    "static_compliance_mL_per_cmH2O": ("StaticRespiratoryCompliance", _compliance),
    "inspiratory_expiratory_ratio": ("InspiratoryExpiratoryRatio", None),
    "leak_fraction": ("LeakFraction", None),
}

MULTIPLIERS = (
    "left_compliance", "right_compliance",
    "left_inspiratory_resistance", "left_expiratory_resistance",
    "right_inspiratory_resistance", "right_expiratory_resistance",
    "upper_inspiratory_resistance", "upper_expiratory_resistance",
    "respiration_rate", "tidal_volume",
)

# Pulse's HowTo_VentilationMechanics.py pressure-control settings.
VENTILATOR_BASELINE = {
    "connected": 0.0,
    "inspiratory_pressure_cmH2O": 19.0,
    "peep_cmH2O": 5.0,
    "respiration_rate_bpm": 12.0,
    "inspiratory_period_s": 1.0,
    "slope_s": 0.2,
    "fraction_inspired_oxygen": 0.21,
}


def _respiratory_outputs() -> tuple[Request, ...]:
    requests = [Request(("mechanics", port), "physiology", prop, unit)
                for port, (prop, unit) in _MECHANICS.items()]
    for group, compartments in _COMPARTMENTS.items():
        for name, compartment in compartments.items():
            for port, (prop, unit) in _COMPARTMENT_PROPERTIES.items():
                requests.append(Request((group, name, port), "gas_compartment", prop, unit,
                                        compartment=compartment))
    return tuple(requests)


def _validate_multipliers(values: dict[str, float], config: dict[str, Any]) -> None:
    for port, value in values.items():
        if not value > 0.0:
            raise ValueError(f"{port} must be > 0, got {value}")


def _build_multipliers(values: dict[str, float], config: dict[str, Any]):
    from pulse.cdm.patient_actions import SERespiratoryMechanicsModification

    action = SERespiratoryMechanicsModification()
    action.set_incremental(True)
    modifiers = action.get_modifiers()
    for name in MULTIPLIERS:
        getattr(modifiers, f"get_{name}_multiplier")().set_value(values[f"{name}_multiplier"])
    return action


def _validate_intubation(values: dict[str, float], config: dict[str, Any]) -> None:
    validate_switch("intubated", values["intubated"])


def _build_intubation(values: dict[str, float], config: dict[str, Any]):
    from pulse.cdm.patient_actions import SEIntubation, eIntubationType

    action = SEIntubation()
    kind = config["intubation_type"] if values["intubated"] == 1.0 else "Off"
    action.set_type(eIntubationType[kind])
    return action


def _check_intubation_transition(previous: dict[str, float] | None, values: dict[str, float]) -> None:
    # previous is None when the loaded state already has an intubation active.
    if (previous is None or previous["intubated"] == 1.0) and values["intubated"] == 0.0:
        raise ValueError(
            "extubation (intubated 1 -> 0) is not possible through Pulse's Python API: "
            "SEIntubation.is_valid() rejects type Off, so PulseEngine drops the action, "
            "although the C++ engine accepts it (SEIntubation::IsValid)")


def _check_respiratory_config(config: dict[str, Any]) -> None:
    if config["intubation_type"] not in INTUBATION_TYPES:
        raise ValueError(f"intubation_type must be one of {INTUBATION_TYPES}, got {config['intubation_type']!r}")


def _validate_ventilator(values: dict[str, float], config: dict[str, Any]) -> None:
    validate_switch("connected", values["connected"])
    rate = values["respiration_rate_bpm"]
    period = values["inspiratory_period_s"]
    slope = values["slope_s"]
    if not rate > 0.0:
        raise ValueError(f"respiration_rate_bpm must be > 0, got {rate}")
    if not 0.0 < period <= 60.0 / rate:
        raise ValueError(f"inspiratory_period_s must be in (0, 60/respiration_rate_bpm], got {period}")
    if not 0.0 <= slope <= period:
        raise ValueError(f"slope_s must be in [0, inspiratory_period_s], got {slope}")
    if not 0.0 <= values["peep_cmH2O"] <= values["inspiratory_pressure_cmH2O"]:
        raise ValueError("need 0 <= peep_cmH2O <= inspiratory_pressure_cmH2O, got "
                         f"{values['peep_cmH2O']} and {values['inspiratory_pressure_cmH2O']}")
    if not 0.0 < values["fraction_inspired_oxygen"] <= 1.0:
        raise ValueError(f"fraction_inspired_oxygen must be in (0, 1], got {values['fraction_inspired_oxygen']}")


def _build_ventilator(values: dict[str, float], config: dict[str, Any]):
    from pulse.cdm.mechanical_ventilator import eSwitch
    from pulse.cdm.mechanical_ventilator_actions import (
        SEMechanicalVentilatorConfiguration, SEMechanicalVentilatorPressureControl,
        eMechanicalVentilator_PressureControlMode)
    from pulse.cdm.scalars import FrequencyUnit, PressureUnit, TimeUnit

    if values["connected"] == 0.0:
        action = SEMechanicalVentilatorConfiguration()
        action.get_settings().set_connection(eSwitch.Off)
        return action
    action = SEMechanicalVentilatorPressureControl()
    action.set_connection(eSwitch.On)
    action.set_mode(eMechanicalVentilator_PressureControlMode[config["ventilator_mode"]])
    action.get_inspiratory_pressure().set_value(values["inspiratory_pressure_cmH2O"], PressureUnit.cmH2O)
    action.get_positive_end_expired_pressure().set_value(values["peep_cmH2O"], PressureUnit.cmH2O)
    action.get_respiration_rate().set_value(values["respiration_rate_bpm"], FrequencyUnit.Per_min)
    action.get_inspiratory_period().set_value(values["inspiratory_period_s"], TimeUnit.s)
    action.get_slope().set_value(values["slope_s"], TimeUnit.s)
    action.get_fraction_inspired_oxygen().set_value(values["fraction_inspired_oxygen"])
    return action


def _check_ventilator_config(config: dict[str, Any]) -> None:
    if config["ventilator_mode"] not in VENTILATOR_MODES:
        raise ValueError(f"ventilator_mode must be one of {VENTILATOR_MODES}, got {config['ventilator_mode']!r}")


RESPIRATORY = CircuitModule(
    name="respiratory",
    model_types=BOTH_ENGINES,
    outputs=_respiratory_outputs(),
    bindings=(
        ActionBinding(ports={f"{name}_multiplier": 1.0 for name in MULTIPLIERS},
                      build=_build_multipliers, validate=_validate_multipliers),
        ActionBinding(ports={"intubated": 0.0}, build=_build_intubation,
                      validate=_validate_intubation, check_transition=_check_intubation_transition),
    ),
    params={"intubation_type": {"_type": "string", "_default": "Tracheal"}},
    check_config=_check_respiratory_config,
)

MECHANICAL_VENTILATOR = CircuitModule(
    name="mechanical_ventilator",
    model_types=BOTH_ENGINES,
    outputs=tuple(Request((port,), "mechanical_ventilator", prop, unit)
                  for port, (prop, unit) in _VENTILATOR.items()),
    bindings=(
        ActionBinding(ports=dict(VENTILATOR_BASELINE),
                      build=_build_ventilator, validate=_validate_ventilator),
    ),
    params={"ventilator_mode": {"_type": "string", "_default": "AssistedControl"}},
    check_config=_check_ventilator_config,
    airway_device="connected",
)
