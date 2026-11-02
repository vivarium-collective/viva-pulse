"""Hemorrhage and fluid-resuscitation composites driving the real Pulse engine."""

from process_bigraph.composite_generator import composite_generator

from ..core import register_processes
from ..processes import VITALS

_VITAL_PATHS = {name: ["vitals", name] for name in VITALS}


def _pulse_node(state_file, patient_file, circuit_modifiers, circuit_additions, compartment, compound):
    return {
        "_type": "process",
        "address": "local:PulseProcess",
        "config": {
            "state_file": state_file,
            "patient_file": patient_file,
            "circuit_modifiers": dict(circuit_modifiers or {}),
            "circuit_additions": dict(circuit_additions or {}),
            "hemorrhage_compartment": compartment,
            "iv_compound": compound,
        },
        "interval": 1.0,
        "inputs": {
            "hemorrhage_severity": ["interventions", "hemorrhage_severity"],
            "iv_rate_mL_per_min": ["interventions", "iv_rate_mL_per_min"],
        },
        "outputs": {**_VITAL_PATHS, "irreversible_state": ["vitals", "irreversible_state"]},
    }


def _emitter():
    emit = {name: "float" for name in VITALS}
    emit.update({"irreversible_state": "boolean", "iv_rate_mL_per_min": "float", "time": "float"})
    inputs = {name: ["vitals", name] for name in VITALS}
    inputs.update({
        "irreversible_state": ["vitals", "irreversible_state"],
        "iv_rate_mL_per_min": ["interventions", "iv_rate_mL_per_min"],
        "time": ["global_time"],
    })
    return {
        "_type": "step",
        "address": "local:RAMEmitter",
        "config": {"emit": emit},
        "inputs": inputs,
    }


_COMMON_PARAMETERS = {
    "state_file": {"type": "string", "default": "StandardMale@0s.json",
                   "description": "Stabilized Pulse patient state in <install>/bin/states"},
    "patient_file": {"type": "string", "default": "StandardMale.json",
                     "description": "Any patient instead of state_file: a name in <install>/bin/patients "
                                    "or a path; stabilized once (about 13 s), then cached"},
    "circuit_modifiers": {"type": "map", "default": {},
                          "description": "Circuit path or node name -> multiplier on the value Pulse "
                                         "initializes it with; the patient is stabilized with them "
                                         "(about 25 s the first time, then cached)"},
    "circuit_additions": {"type": "map", "default": {},
                          "description": "New path name -> {source, target, resistance_mmHg_s_per_mL}: "
                                         "a cardiovascular path added with its compartment link, as "
                                         "a perturbation of the loaded patient"},
    "compartment": {"type": "string", "default": "RightLeg",
                    "description": "Hemorrhage site (Pulse eHemorrhage_Compartment)"},
    "severity": {"type": "float", "default": 0.8,
                 "description": "Hemorrhage severity in [0, 1]"},
}


@composite_generator(
    name="pulse_hemorrhage",
    description="Untreated hemorrhage in the real Pulse whole-body adult engine; emits vital signs every second.",
    parameters=_COMMON_PARAMETERS,
    core_extensions=[register_processes],
    default_n_steps=600,
    fidelity="real-bridge",
)
def pulse_hemorrhage(core=None, *, state_file="StandardMale@0s.json", patient_file="StandardMale.json",
                     circuit_modifiers=None, circuit_additions=None, compartment="RightLeg", severity=0.8):
    return {
        "pulse": _pulse_node(state_file, patient_file, circuit_modifiers, circuit_additions, compartment,
                             "Saline"),
        "interventions": {"hemorrhage_severity": severity, "iv_rate_mL_per_min": 0.0},
        "vitals": {},
        "emitter": _emitter(),
    }


@composite_generator(
    name="pulse_resuscitation",
    description="Hemorrhage in the real Pulse engine with a closed-loop MAP-targeted IV fluid controller.",
    parameters={
        **_COMMON_PARAMETERS,
        "compound": {"type": "string", "default": "Saline",
                     "description": "Infused compound (Pulse compound name, e.g. Saline, Blood)"},
        "target_map_mmHg": {"type": "float", "default": 90.0,
                            "description": "Controller MAP target"},
        "gain": {"type": "float", "default": 25.0,
                 "description": "Controller gain, mL/min per mmHg below target"},
        "max_rate_mL_per_min": {"type": "float", "default": 250.0,
                                "description": "Infusion rate ceiling"},
    },
    core_extensions=[register_processes],
    default_n_steps=600,
    fidelity="real-bridge",
)
def pulse_resuscitation(core=None, *, state_file="StandardMale@0s.json", patient_file="StandardMale.json",
                        circuit_modifiers=None, circuit_additions=None, compartment="RightLeg",
                        severity=0.8, compound="Saline",
                        target_map_mmHg=90.0, gain=25.0, max_rate_mL_per_min=250.0):
    doc = pulse_hemorrhage(core, state_file=state_file, patient_file=patient_file,
                           circuit_modifiers=circuit_modifiers, circuit_additions=circuit_additions,
                           compartment=compartment,
                           severity=severity)
    doc["pulse"] = _pulse_node(state_file, patient_file, circuit_modifiers, circuit_additions,
                               compartment, compound)
    doc["controller"] = {
        "_type": "step",
        "address": "local:MapFluidController",
        "config": {
            "target_map_mmHg": target_map_mmHg,
            "gain_mL_per_min_per_mmHg": gain,
            "max_rate_mL_per_min": max_rate_mL_per_min,
        },
        "inputs": {"mean_arterial_pressure_mmHg": ["vitals", "mean_arterial_pressure_mmHg"]},
        "outputs": {"iv_rate_mL_per_min": ["interventions", "iv_rate_mL_per_min"]},
    }
    return doc
