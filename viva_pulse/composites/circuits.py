"""Per-circuit composites driving the real Pulse engine.

Store layout:
- ``interventions/<module>/``: setpoints;
- ``circuits/<module>/``: the module's Pulse readings;
- ``circuits/irreversible_state``;
- a ``RAMEmitter`` step at ``emitter`` that emits both subtrees every update.
"""

from process_bigraph.composite_generator import composite_generator

from ..circuits import MODULES
from ..circuits.cardiovascular import CARDIOVASCULAR, HEMORRHAGE_COMPARTMENTS, MULTIPLIERS
from ..circuits.respiratory import (
    INTUBATION_TYPES, MECHANICAL_VENTILATOR, MULTIPLIERS as RESPIRATORY_MULTIPLIERS, RESPIRATORY,
    VENTILATOR_BASELINE, VENTILATOR_MODES)
from ..circuits.supplemental_oxygen import OXYGEN_BASELINE, OXYGEN_DEVICES, SUPPLEMENTAL_OXYGEN
from ..circuits.thermal import ENVIRONMENT_BASELINE, THERMAL, THERMAL_APPLICATION_BASELINE
from ..core import register_processes


def circuit_node(modules, *, model_type="whole_body", state_file="StandardMale@0s.json",
                 patient_file="StandardMale.json", circuit_modifiers=None,
                 circuit_additions=None, interval=1.0, **params):
    """A ``PulseCircuitProcess`` node wired to the standard store layout."""
    return {
        "_type": "process",
        "address": "local:PulseCircuitProcess",
        "config": {"model_type": model_type, "modules": list(modules),
                   "state_file": state_file, "patient_file": patient_file,
                   "circuit_modifiers": dict(circuit_modifiers or {}),
                   "circuit_additions": dict(circuit_additions or {}), **params},
        "interval": interval,
        "inputs": {"setpoints": ["interventions"]},
        "outputs": {**{name: ["circuits", name] for name in modules},
                    "irreversible_state": ["circuits", "irreversible_state"]},
    }


def circuit_emitter():
    """A ``RAMEmitter`` recording the ``circuits`` and ``interventions`` subtrees and time."""
    return {
        "_type": "step",
        "address": "local:RAMEmitter",
        "config": {"emit": {"circuits": "node", "interventions": "node", "time": "float"}},
        "inputs": {"circuits": ["circuits"], "interventions": ["interventions"],
                   "time": ["global_time"]},
    }


def _setpoints(module, overrides, config):
    """The module's setpoint values: baselines updated from ``overrides`` (popped),
    each group validated with the same check the process applies at run time, so
    a bad parameter fails when the document is built."""
    values = {}
    for binding in module.bindings:
        group = {port: float(overrides.pop(port, default)) for port, default in binding.ports.items()}
        if binding.validate:
            binding.validate(group, config)
        values.update(group)
    return values


def _reject_unknown(overrides):
    if overrides:
        raise TypeError(f"unexpected parameters: {sorted(overrides)}")


def _multiplier_parameters(names, system):
    return {f"{name}_multiplier": {"type": "float", "default": 1.0,
                                   "description": f"Pulse {system} {name.replace('_', ' ')} multiplier (1.0 = unmodified)"}
            for name in names}


_INTERVAL = {"type": "float", "default": 1.0,
             "description": "Seconds per update; 0.02 (Pulse's timestep) resolves per-beat/per-breath "
                            "waveforms. A non-binary-exact interval can lose the final update of a run "
                            "to float time accumulation."}
_STATE_FILE = {"type": "string", "default": "StandardMale@0s.json",
               "description": "Stabilized Pulse patient state in <install>/bin/states (whole_body only; "
                              "set this or patient_file, not both)"}
_PATIENT_FILE = {"type": "string", "default": "StandardMale.json",
                 "description": "Patient in <install>/bin/patients (on whole_body, also a path). "
                                "ventilation_mechanics starts from it; on whole_body it replaces "
                                "state_file, stabilized once (about 13 s) and then cached"}
_CIRCUIT_MODIFIERS = {"type": "map", "default": {},
                      "description": "Circuit path or node name -> multiplier on the resistance, "
                                     "compliance or volume Pulse initializes it with (whole_body only). "
                                     "The patient is stabilized with them (about 25 s the first time, "
                                     "then cached), so the rest of the body adapts: a different "
                                     "patient, not a perturbation"}
_CIRCUIT_ADDITIONS = {"type": "map", "default": {},
                      "description": "New path name -> {source, target, resistance_mmHg_s_per_mL}: a "
                                     "resistance path between two FullCardiovascular nodes in "
                                     "different compartments, added with its compartment link so "
                                     "substances follow (whole_body only). A perturbation: the body "
                                     "responds over time"}
_POINT_READS = {"type": "boolean", "default": False,
                "description": "Also read every node and path of the circuit drawing (whole_body only), "
                               "under circuits/<circuit>_points/"}


def _with_points(modules, point_reads, model_type):
    """``modules`` plus each one's ``<name>_points`` module when ``point_reads`` is set."""
    if not point_reads:
        return list(modules)
    if model_type != "whole_body":
        raise ValueError(f"point_reads needs model_type 'whole_body', got {model_type!r}")
    return [*modules, *(f"{name}_points" for name in modules if f"{name}_points" in MODULES)]


_CARDIOVASCULAR_PARAMETERS = {
    **_multiplier_parameters(MULTIPLIERS, "cardiovascular"),
    "hemorrhage_compartment": {"type": "string", "default": "RightLeg",
                               "choices": list(HEMORRHAGE_COMPARTMENTS),
                               "description": "Hemorrhage site"},
    "hemorrhage_severity": {"type": "float", "default": 0.0,
                            "description": "Hemorrhage severity in [0, 1]; 0 = no bleed"},
}


@composite_generator(
    name="pulse_cardiovascular",
    description="The Pulse cardiovascular circuit (with its renal and tissue branches) in the real "
                "whole-body engine: per-compartment pressures, volumes and flows plus hemodynamic "
                "vitals, driven by circuit resistance/compliance multipliers and a hemorrhage.",
    parameters={
        "model_type": {"type": "string", "default": "whole_body", "choices": ["whole_body"],
                       "description": "Pulse engine running the circuit"},
        "state_file": _STATE_FILE,
        "patient_file": _PATIENT_FILE,
        "circuit_modifiers": _CIRCUIT_MODIFIERS,
        "circuit_additions": _CIRCUIT_ADDITIONS,
        "interval": _INTERVAL,
        "point_reads": _POINT_READS,
        **_CARDIOVASCULAR_PARAMETERS,
    },
    core_extensions=[register_processes],
    default_n_steps=600,
    fidelity="real-bridge",
)
def pulse_cardiovascular(core=None, *, model_type="whole_body", state_file="StandardMale@0s.json",
                         patient_file="StandardMale.json", circuit_modifiers=None,
                         circuit_additions=None, interval=1.0, point_reads=False,
                         hemorrhage_compartment="RightLeg", **overrides):
    config = {"hemorrhage_compartment": hemorrhage_compartment}
    CARDIOVASCULAR.check_config(config)
    setpoints = _setpoints(CARDIOVASCULAR, overrides, config)
    _reject_unknown(overrides)
    return {
        "pulse": circuit_node(_with_points(["cardiovascular"], point_reads, model_type), model_type=model_type,
                              state_file=state_file, patient_file=patient_file,
                              circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions, interval=interval,
                              hemorrhage_compartment=hemorrhage_compartment),
        "interventions": {"cardiovascular": setpoints},
        "circuits": {},
        "emitter": circuit_emitter(),
    }


_RESPIRATORY_PARAMETERS = {
    "model_type": {"type": "string", "default": "ventilation_mechanics",
                   "choices": ["ventilation_mechanics", "whole_body"],
                   "description": "ventilation_mechanics = the airway circuit alone (no blood, no "
                                  "chemoreflex); whole_body = coupled to the rest of the body"},
    "patient_file": _PATIENT_FILE,
    "circuit_modifiers": _CIRCUIT_MODIFIERS,
    "circuit_additions": _CIRCUIT_ADDITIONS,
    "state_file": _STATE_FILE,
    "interval": _INTERVAL,
    "point_reads": _POINT_READS,
    **_multiplier_parameters(RESPIRATORY_MULTIPLIERS, "respiratory"),
    "intubation_type": {"type": "string", "default": "Tracheal", "choices": list(INTUBATION_TYPES),
                        "description": "Tube placement used when intubated = 1"},
}


@composite_generator(
    name="pulse_respiratory",
    description="The Pulse respiratory (airway) circuit, alone in the VentilationMechanics engine or "
                "coupled in the whole-body engine: breathing mechanics plus per-compartment lung and "
                "pleural pressures, volumes and flows, driven by resistance/compliance multipliers "
                "and intubation.",
    parameters={
        **_RESPIRATORY_PARAMETERS,
        "intubated": {"type": "float", "default": 0.0, "description": "1 = intubated, 0 = not"},
    },
    core_extensions=[register_processes],
    default_n_steps=120,
    fidelity="real-bridge",
)
def pulse_respiratory(core=None, *, model_type="ventilation_mechanics", patient_file="StandardMale.json",
                      circuit_modifiers=None, circuit_additions=None,
                      state_file="StandardMale@0s.json", interval=1.0, point_reads=False,
                      intubation_type="Tracheal", **overrides):
    config = {"intubation_type": intubation_type}
    RESPIRATORY.check_config(config)
    setpoints = _setpoints(RESPIRATORY, overrides, config)
    _reject_unknown(overrides)
    modules = _with_points(["respiratory"], point_reads, model_type)
    return {
        "pulse": circuit_node(modules, model_type=model_type, state_file=state_file,
                              patient_file=patient_file, circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions, interval=interval,
                              intubation_type=intubation_type),
        "interventions": {"respiratory": setpoints},
        "circuits": {},
        "emitter": circuit_emitter(),
    }


@composite_generator(
    name="pulse_mechanical_ventilation",
    description="A patient on a pressure-control mechanical ventilator in the real Pulse engine: the "
                "respiratory circuit combined with the ventilator circuit, emitting breathing "
                "mechanics, lung compartments and the ventilator's monitor values. Defaults follow "
                "Pulse's HowTo_VentilationMechanics (intubated; PC-AC 19/5 cmH2O, 12 bpm).",
    parameters={
        **_RESPIRATORY_PARAMETERS,
        "intubated": {"type": "float", "default": 1.0, "description": "1 = intubated (tube), 0 = mask"},
        "ventilator_mode": {"type": "string", "default": "AssistedControl", "choices": list(VENTILATOR_MODES),
                            "description": "Pressure-control mode"},
        **{port: {"type": "float", "default": (1.0 if port == "connected" else value),
                  "description": f"Ventilator {port.replace('_', ' ')}"}
           for port, value in VENTILATOR_BASELINE.items()},
    },
    core_extensions=[register_processes],
    default_n_steps=120,
    fidelity="real-bridge",
)
def pulse_mechanical_ventilation(core=None, *, model_type="ventilation_mechanics",
                                 patient_file="StandardMale.json",
                                 circuit_modifiers=None, circuit_additions=None, state_file="StandardMale@0s.json",
                                 interval=1.0, point_reads=False, intubation_type="Tracheal",
                                 ventilator_mode="AssistedControl", **overrides):
    overrides.setdefault("intubated", 1.0)
    overrides.setdefault("connected", 1.0)
    config = {"intubation_type": intubation_type, "ventilator_mode": ventilator_mode}
    RESPIRATORY.check_config(config)
    MECHANICAL_VENTILATOR.check_config(config)
    respiratory = _setpoints(RESPIRATORY, overrides, config)
    ventilator = _setpoints(MECHANICAL_VENTILATOR, overrides, config)
    _reject_unknown(overrides)
    return {
        "pulse": circuit_node(_with_points(["respiratory", "mechanical_ventilator"], point_reads, model_type),
                              model_type=model_type,
                              state_file=state_file, patient_file=patient_file,
                              circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions, interval=interval,
                              **config),
        "interventions": {"respiratory": respiratory, "mechanical_ventilator": ventilator},
        "circuits": {},
        "emitter": circuit_emitter(),
    }


_THERMAL_DESCRIPTIONS = {
    "ambient_temperature_C": "Air temperature around the body (not the air breathed; see "
                             "respiration_ambient_temperature_C)",
    "mean_radiant_temperature_C": "Mean radiant temperature of the surroundings",
    "respiration_ambient_temperature_C": "Temperature of the air breathed; drives respiration heat loss",
    "relative_humidity": "Relative humidity in [0, 1]",
    "air_velocity_m_per_s": "Air speed over the body",
    "clothing_resistance_clo": "Clothing thermal resistance (1 clo = 0.155 m^2 K/W)",
    "active_heating_W": "Active heating power; Pulse delivers power x area fraction",
    "active_heating_area_fraction": "Fraction of skin area under active heating, in (0, 1]",
    "active_cooling_W": "Active cooling power; Pulse removes power x area fraction",
    "active_cooling_area_fraction": "Fraction of skin area under active cooling, in (0, 1]",
    "applied_temperature_on": "1 = apply applied_temperature_C over the clothing, 0 = off",
    "applied_temperature_C": "Applied temperature, used when applied_temperature_on = 1",
    "applied_temperature_area_fraction": "Fraction in (0, 1] by which Pulse blends the applied "
                                         "temperature with the ambient temperature",
}


@composite_generator(
    name="pulse_thermal",
    description="The Pulse temperature circuit (internal core/skin joined to clothing, enclosure "
                "and ambient air) in the real whole-body engine: core and skin temperature, sweat, "
                "metabolic rate, heat-loss rates and per-compartment temperatures and heat flows, "
                "driven by the environmental conditions and by active heating, cooling or an "
                "applied skin temperature.",
    parameters={
        "model_type": {"type": "string", "default": "whole_body", "choices": ["whole_body"],
                       "description": "Pulse engine running the circuit"},
        "state_file": _STATE_FILE,
        "patient_file": _PATIENT_FILE,
        "circuit_modifiers": _CIRCUIT_MODIFIERS,
        "circuit_additions": _CIRCUIT_ADDITIONS,
        "interval": _INTERVAL,
        **{port: {"type": "float", "default": value, "description": _THERMAL_DESCRIPTIONS[port]}
           for port, value in {**ENVIRONMENT_BASELINE, **THERMAL_APPLICATION_BASELINE}.items()},
    },
    core_extensions=[register_processes],
    default_n_steps=1800,
    fidelity="real-bridge",
)
def pulse_thermal(core=None, *, model_type="whole_body", state_file="StandardMale@0s.json",
                  patient_file="StandardMale.json", circuit_modifiers=None,
                  circuit_additions=None, interval=1.0, **overrides):
    setpoints = _setpoints(THERMAL, overrides, {})
    _reject_unknown(overrides)
    return {
        "pulse": circuit_node(["thermal"], model_type=model_type, state_file=state_file,
                              patient_file=patient_file, circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions, interval=interval),
        "interventions": {"thermal": setpoints},
        "circuits": {},
        "emitter": circuit_emitter(),
    }


_OXYGEN_DEVICE_PARAMETER = {
    "oxygen_device": {"type": "string", "default": "NasalCannula", "choices": list(OXYGEN_DEVICES),
                      "description": "Supplemental oxygen device used when oxygen_connected = 1"},
}
_OXYGEN_FLOW_PARAMETER = {
    "oxygen_flow_L_per_min": {"type": "float", "default": OXYGEN_BASELINE["oxygen_flow_L_per_min"],
                              "description": "Oxygen flow from a wall supply (Pulse's device defaults: "
                                             "nasal cannula 3.5, simple mask 7.5, non-rebreather 10)"},
}


@composite_generator(
    name="pulse_supplemental_oxygen",
    description="Supplemental oxygen (nasal cannula, simple mask or non-rebreather mask) in the real "
                "whole-body engine: the device circuit combined with the respiratory circuit, emitting "
                "breathing mechanics, lung compartments, inspired oxygen and arterial blood gases.",
    parameters={
        "model_type": {"type": "string", "default": "whole_body", "choices": ["whole_body"],
                       "description": "Pulse engine running the circuits"},
        "state_file": _STATE_FILE,
        "patient_file": _PATIENT_FILE,
        "circuit_modifiers": _CIRCUIT_MODIFIERS,
        "circuit_additions": _CIRCUIT_ADDITIONS,
        "interval": _INTERVAL,
        **_OXYGEN_DEVICE_PARAMETER,
        "oxygen_connected": {"type": "float", "default": 1.0,
                             "description": "1 = oxygen device on, 0 = off"},
        **_OXYGEN_FLOW_PARAMETER,
    },
    core_extensions=[register_processes],
    default_n_steps=300,
    fidelity="real-bridge",
)
def pulse_supplemental_oxygen(core=None, *, model_type="whole_body", state_file="StandardMale@0s.json",
                              patient_file="StandardMale.json", circuit_modifiers=None,
                              circuit_additions=None, interval=1.0,
                              oxygen_device="NasalCannula", **overrides):
    overrides.setdefault("oxygen_connected", 1.0)
    config = {"oxygen_device": oxygen_device, "intubation_type": "Tracheal"}
    SUPPLEMENTAL_OXYGEN.check_config(config)
    oxygen = _setpoints(SUPPLEMENTAL_OXYGEN, overrides, config)
    _reject_unknown(overrides)
    return {
        "pulse": circuit_node(["respiratory", "supplemental_oxygen"], model_type=model_type,
                              state_file=state_file, patient_file=patient_file,
                              circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions, interval=interval,
                              oxygen_device=oxygen_device),
        "interventions": {"respiratory": _setpoints(RESPIRATORY, {}, config),
                          "supplemental_oxygen": oxygen},
        "circuits": {},
        "emitter": circuit_emitter(),
    }


WHOLE_BODY_MODULES = (CARDIOVASCULAR, RESPIRATORY, MECHANICAL_VENTILATOR, THERMAL, SUPPLEMENTAL_OXYGEN)


@composite_generator(
    name="pulse_whole_body_circuits",
    description="Every circuit module on one real whole-body Pulse engine: cardiovascular (with renal "
                "and tissue branches), respiratory, mechanical ventilator, thermal and supplemental "
                "oxygen, so effects that cross circuits appear in one run. All setpoints start at "
                "their baselines; the ventilator and oxygen start disconnected, and only one of them "
                "can be connected at a time.",
    parameters={
        "model_type": {"type": "string", "default": "whole_body", "choices": ["whole_body"],
                       "description": "Pulse engine running the circuits"},
        "state_file": _STATE_FILE,
        "patient_file": _PATIENT_FILE,
        "circuit_modifiers": _CIRCUIT_MODIFIERS,
        "circuit_additions": _CIRCUIT_ADDITIONS,
        "interval": _INTERVAL,
        "point_reads": _POINT_READS,
        **_CARDIOVASCULAR_PARAMETERS,
        **{k: v for k, v in _RESPIRATORY_PARAMETERS.items()
           if k not in ("model_type", "patient_file", "circuit_modifiers", "circuit_additions",
                         "state_file", "interval", "point_reads")},
        "intubated": {"type": "float", "default": 0.0, "description": "1 = intubated, 0 = not"},
        "ventilator_mode": {"type": "string", "default": "AssistedControl", "choices": list(VENTILATOR_MODES),
                            "description": "Pressure-control mode"},
        **{port: {"type": "float", "default": value, "description": f"Ventilator {port.replace('_', ' ')}"}
           for port, value in VENTILATOR_BASELINE.items()},
        **{port: {"type": "float", "default": value, "description": _THERMAL_DESCRIPTIONS[port]}
           for port, value in {**ENVIRONMENT_BASELINE, **THERMAL_APPLICATION_BASELINE}.items()},
        **_OXYGEN_DEVICE_PARAMETER,
        "oxygen_connected": {"type": "float", "default": 0.0,
                             "description": "1 = oxygen device on, 0 = off"},
        **_OXYGEN_FLOW_PARAMETER,
    },
    core_extensions=[register_processes],
    default_n_steps=600,
    fidelity="real-bridge",
)
def pulse_whole_body_circuits(core=None, *, model_type="whole_body", state_file="StandardMale@0s.json",
                              patient_file="StandardMale.json",
                              circuit_modifiers=None, circuit_additions=None, interval=1.0, point_reads=False,
                              hemorrhage_compartment="RightLeg", intubation_type="Tracheal",
                              ventilator_mode="AssistedControl", oxygen_device="NasalCannula", **overrides):
    config = {"hemorrhage_compartment": hemorrhage_compartment, "intubation_type": intubation_type,
              "ventilator_mode": ventilator_mode, "oxygen_device": oxygen_device}
    for module in WHOLE_BODY_MODULES:
        if module.check_config:
            module.check_config(config)
    interventions = {module.name: _setpoints(module, overrides, config) for module in WHOLE_BODY_MODULES}
    _reject_unknown(overrides)
    connected = [module.name for module in WHOLE_BODY_MODULES
                 if module.airway_device and interventions[module.name][module.airway_device] == 1.0]
    if len(connected) > 1:
        raise ValueError(f"only one airway device can be connected at a time, got {connected}")
    return {
        "pulse": circuit_node(_with_points([module.name for module in WHOLE_BODY_MODULES], point_reads, model_type),
                              model_type=model_type, state_file=state_file, patient_file=patient_file,
                              circuit_modifiers=circuit_modifiers,
                              circuit_additions=circuit_additions,
                              interval=interval, **config),
        "interventions": interventions,
        "circuits": {},
        "emitter": circuit_emitter(),
    }
