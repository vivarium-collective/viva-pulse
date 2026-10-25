"""Process-bigraph bridge to the Kitware Pulse Physiology Engine."""

from __future__ import annotations

import json
import math
from typing import Any, Callable

from process_bigraph import Process, Step

from .circuits import ENGINE_MODEL_TYPES, MODULES
from .circuits.additions import add_paths, check_additions
from .circuits.base import check_outputs
from .circuits.cardiovascular import HEMORRHAGE_COMPARTMENTS
from .patients import stabilized_state
from .states import StateSaver
from .runtime import ensure_pulse_importable

#: Output port -> (Pulse physiology property, scalar unit class, unit attribute on
#: that class); the unit slots are None for unitless values. Order is the
#: data-request order, which is the order of PulseEngine.pull_data()[1:].
VITALS: dict[str, tuple[str, str | None, str | None]] = {
    "heart_rate_bpm": ("HeartRate", "FrequencyUnit", "Per_min"),
    "mean_arterial_pressure_mmHg": ("MeanArterialPressure", "PressureUnit", "mmHg"),
    "systolic_pressure_mmHg": ("SystolicArterialPressure", "PressureUnit", "mmHg"),
    "diastolic_pressure_mmHg": ("DiastolicArterialPressure", "PressureUnit", "mmHg"),
    "oxygen_saturation": ("OxygenSaturation", None, None),
    "respiration_rate_bpm": ("RespirationRate", "FrequencyUnit", "Per_min"),
    "cardiac_output_L_per_min": ("CardiacOutput", "VolumePerTimeUnit", "L_Per_min"),
    "blood_volume_mL": ("BloodVolume", "VolumeUnit", "mL"),
    "total_hemorrhaged_volume_mL": ("TotalHemorrhagedVolume", "VolumeUnit", "mL"),
}


def _load_engine(install_dir: str, model_type: str, state_file: str, requests: list):
    """Load a stabilized Pulse state into a new engine of ``model_type``.

    ``state_file`` is a name in ``<install>/bin/states/`` or an absolute path.
    ``model_type`` is a ``pulse.engine.PulseEngine.eModelType`` member name.
    ``requests`` are ``SEDataRequest``s; ``pull_data()[1:]`` follows their order.
    The engine is advanced by 0 s so ``pull_data()`` holds the loaded state's values.
    """
    bin_dir = ensure_pulse_importable(install_dir)

    from pulse.cdm.engine import SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    state_path = _state_path(install_dir, state_file)
    engine = PulseEngine(getattr(eModelType, model_type), f"{bin_dir}/")
    engine.log_to_console(False)
    if not engine.serialize_from_file(str(state_path), SEDataRequestManager(requests)):
        raise RuntimeError(f"Pulse failed to load state {state_path}")
    engine.advance_time_s(0.0)
    return engine


def _state_path(install_dir: str, state_file: str):
    """``<install>/bin/states/<state_file>``, which must exist."""
    state_path = ensure_pulse_importable(install_dir) / "states" / state_file
    if not state_path.is_file():
        raise FileNotFoundError(f"Pulse state file not found: {state_path}")
    return state_path


def _read_state(install_dir: str, state_file: str) -> dict[str, Any]:
    """The parsed JSON of a stabilized state file."""
    return json.loads(_state_path(install_dir, state_file).read_text())


def _load_state(install_dir: str, model_type: str, state: dict[str, Any], requests: list):
    """Like ``_load_engine``, from a state given as parsed JSON (e.g. one with added compartments)."""
    bin_dir = ensure_pulse_importable(install_dir)

    from pulse.cdm.engine import SEDataRequestManager
    from pulse.cdm.enums import eSerializationFormat
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    engine = PulseEngine(getattr(eModelType, model_type), f"{bin_dir}/")
    engine.log_to_console(False)
    if not engine.serialize_from_string(json.dumps(state), SEDataRequestManager(requests),
                                        eSerializationFormat.JSON):
        raise RuntimeError("Pulse failed to load the edited state")
    engine.advance_time_s(0.0)
    return engine


def _check_whole_body_start(config: dict, schema: dict) -> None:
    """A whole-body engine starts from ``state_file`` or from ``patient_file``, not both.

    bigraph-schema replaces an explicit value equal to the default with the
    default, so only a non-default value counts as set. The default patient,
    StandardMale, ships a state anyway.
    """
    if all(config[key] != schema[key]["_default"] for key in ("state_file", "patient_file")):
        raise ValueError(f"state_file {config['state_file']!r} and patient_file "
                         f"{config['patient_file']!r} are both set; a whole-body engine starts "
                         "from one of them")
    bad = {name: m for name, m in config["circuit_modifiers"].items()
           if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m <= 0}
    if bad:
        raise ValueError(f"circuit_modifiers must be finite numbers > 0, got {bad}")
    check_additions(config["circuit_additions"])
    if config["circuit_modifiers"] and config["state_file"] != schema["state_file"]["_default"]:
        raise ValueError(f"circuit_modifiers apply when Pulse stabilizes a patient, so they need "
                         f"patient_file; state_file {config['state_file']!r} is a stabilized state")


def _whole_body_state(config: dict, schema: dict) -> str:
    """The state a whole-body engine loads: ``state_file``, or, when ``patient_file``
    or ``circuit_modifiers`` is set, the patient's stabilized state (an absolute
    path into the cache; see ``viva_pulse.patients``)."""
    if (config["patient_file"] == schema["patient_file"]["_default"]
            and not config["circuit_modifiers"]):
        return config["state_file"]
    return str(stabilized_state(config["patient_file"], config["install_dir"],
                                dict(config["circuit_modifiers"])))


def _actions_by_key(any_action: dict) -> dict[tuple, dict]:
    """Each action of a serialized ``AnyAction`` list, keyed (category, type, identity).

    Pulse keeps one active action of each type, except hemorrhages (one per compartment) and
    compound infusions (one per compound) (``SEPatientActionCollection.h:166, 263``), which
    the identity names.
    """
    actions = {}
    for item in any_action.get("AnyAction", []):
        ((category, body),) = item.items()
        ((kind, fields),) = body.items()
        actions[(category, kind, fields.get("Compartment") or fields.get("SubstanceCompound"))] = fields
    return actions


def _serialized(actions: list) -> dict[tuple, dict]:
    from pulse.cdm.enums import eSerializationFormat
    from pulse.cdm.io.engine import serialize_actions_to_string

    return _actions_by_key(json.loads(serialize_actions_to_string(actions, eSerializationFormat.JSON)))


def _active_actions(engine) -> tuple[dict[tuple, dict], str]:
    """The loaded engine's active actions (a saved mid-run state carries them) and its airway
    mode. Empty and Free for an engine Pulse can't serialize (VentilationMechanics, which
    starts from a patient)."""
    import PyPulse

    state = engine.serialize_to_string(PyPulse.serialization_format.json)
    if not state:
        return {}, "Free"
    state = json.loads(state)
    return _actions_by_key(state.get("ActiveActions", {})), state.get("AirwayMode", "Free")


def _loaded_controls(active: dict[tuple, dict], baseline: dict[str, float], build) -> bool:
    """Whether the loaded state has an action active that this setpoint group sends.

    A process sends an action only when its setpoint changes, assuming nothing is active
    at load. A state saved mid-run breaks that: its bleed, infusion, ventilator or
    modifiers are still active, so a branch setting one back to baseline would send
    nothing while Pulse keeps applying it. Such a group is unknown (``None``) until its
    first update, which sends it whatever its value (resending the active values doesn't
    change the run: a mid-bleed checkpoint continued at the same severity agrees with the
    uninterrupted run as closely as a plain reload, 1.8e-8; for the ventilator, multipliers,
    oxygen and heating, a resend and no resend were measured identical). ``build(values)`` is called at
    the baseline and with every zero-baseline port at 1, because an action can change type
    with its value (a connected ventilator) or not serialize at baseline (an Off intubation).

    An active action of the same type that the group can't address (a hemorrhage in another
    compartment, an infusion of another compound) raises: the group's setpoint couldn't
    stop it, and its store would say nothing is happening.
    """
    if not active:
        return False
    switched = {port: 1.0 if value == 0.0 else value for port, value in baseline.items()}
    sends = _serialized([build(baseline), build(switched)]).keys()
    kinds = {(category, kind) for category, kind, _ in sends}
    other = sorted(f"{kind} ({identity})" for category, kind, identity in active.keys() - sends
                   if (category, kind) in kinds)
    if other:
        raise ValueError(f"the loaded state has active {other}, which this process's setpoints "
                         f"can't reach (it sends {sorted(f'{k} ({i})' for _, k, i in sends)}); "
                         "configure the process for them (e.g. hemorrhage_compartment, iv_compound)")
    return bool(active.keys() & sends)


def _initialize_engine(install_dir: str, model_type: str, patient_file: str, requests: list):
    """Initialize a new engine of ``model_type`` from ``<install>/bin/patients/<patient_file>``.

    For engines that cannot load a state file (VentilationMechanics), the data
    root is set on the patient configuration explicitly. Pulse takes it from
    there, not from the engine constructor, and its default ``./`` leaves the
    substances unloaded, which segfaults in ``InitializeSubstances``.
    """
    bin_dir = ensure_pulse_importable(install_dir)

    from pulse.cdm.engine import SEDataRequestManager
    from pulse.cdm.patient import SEPatientConfiguration
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    patient_path = bin_dir / "patients" / patient_file
    if not patient_path.is_file():
        raise FileNotFoundError(f"Pulse patient file not found: {patient_path}")

    configuration = SEPatientConfiguration()
    configuration.set_data_root_dir(f"{bin_dir}/")
    configuration.set_patient_file(str(patient_path))
    engine = PulseEngine(getattr(eModelType, model_type), f"{bin_dir}/")
    engine.log_to_console(False)
    if not engine.initialize_engine(configuration, SEDataRequestManager(requests)):
        raise RuntimeError(f"Pulse failed to initialize {model_type} from {patient_path}")
    engine.advance_time_s(0.0)
    return engine


class PulseProcess(Process):
    """Time-stepped bridge to the real Pulse whole-body adult engine.

    The engine is loaded from a stabilized Pulse state file and advanced by
    ``interval`` seconds on every update. ``state_file`` names a state Pulse
    ships; setting ``patient_file`` instead (a name in ``<install>/bin/patients/``
    or a path) starts from that patient, stabilized once and then cached (see
    ``viva_pulse.patients``). Setting both raises. ``circuit_modifiers`` stabilizes
    that patient with Pulse's configuration Modifiers (see ``stabilized_state``).
    Interventions arrive as setpoints on the input ports and are forwarded to
    Pulse as patient actions only when their value changes.

    Inputs
    ------
    hemorrhage_severity : overwrite[float]
        Hemorrhage severity in [0, 1] at ``config.hemorrhage_compartment``;
        0 stops the bleed.
    iv_rate_mL_per_min : overwrite[float]
        Infusion rate of ``config.iv_compound`` (e.g. Saline, Blood); 0 stops it.

    Outputs
    -------
    Vital signs (see ``VITALS``) as ``float``. Pulse reports absolute values;
    ``initial_state()`` seeds each store with the loaded state's reading and
    every update emits ``current - previous``, so the store always equals
    Pulse's own value and composes additively with sibling writers.
    ``irreversible_state`` turns True once Pulse reports an irreversible
    state; the engine is not advanced after that, so the vitals stores keep
    the last reading Pulse produced.
    """

    config_schema = {
        "state_file": {"_type": "string", "_default": "StandardMale@0s.json"},
        "patient_file": {"_type": "string", "_default": "StandardMale.json"},
        "circuit_modifiers": {"_type": "map[float]", "_default": {}},
        "circuit_additions": {"_type": "map", "_value": {"source": "string", "target": "string",
                                                         "resistance_mmHg_s_per_mL": "float"},
                              "_default": {}},
        "save_state_times_s": {"_type": "list[float]", "_default": []},
        "save_state_dir": {"_type": "string", "_default": ""},
        "save_state_name": {"_type": "string", "_default": "state"},
        "install_dir": {"_type": "string", "_default": ""},
        "hemorrhage_compartment": {"_type": "string", "_default": "RightLeg"},
        "iv_compound": {"_type": "string", "_default": "Saline"},
        "iv_bag_volume_L": {"_type": "float", "_default": 10.0},
    }

    def __init__(self, config=None, core=None):
        super().__init__(config=config, core=core)
        _check_whole_body_start(self.config, self.config_schema)
        if self.config["hemorrhage_compartment"] not in HEMORRHAGE_COMPARTMENTS:
            raise ValueError(
                f"hemorrhage_compartment must be one of {HEMORRHAGE_COMPARTMENTS}, "
                f"got {self.config['hemorrhage_compartment']!r}"
            )
        self._engine = None
        self._saver = (StateSaver(self.config["save_state_times_s"], self.config["save_state_dir"],
                                  self.config["save_state_name"])
                       if self.config["save_state_times_s"] else None)
        self._state = None
        if self.config["circuit_additions"]:
            self._state = _read_state(self.config["install_dir"],
                                      _whole_body_state(self.config, self.config_schema))
            add_paths(self._state, self.config["circuit_additions"])
        self._alive = True
        self._applied: dict[str, float | None] = {"hemorrhage_severity": 0.0, "iv_rate_mL_per_min": 0.0}
        self._previous: dict[str, float] = {}

    def inputs(self):
        return {
            "hemorrhage_severity": "overwrite[float]",
            "iv_rate_mL_per_min": "overwrite[float]",
        }

    def outputs(self):
        ports: dict[str, Any] = {name: "float" for name in VITALS}
        ports["irreversible_state"] = "boolean"
        return ports

    def initial_state(self):
        return {
            "hemorrhage_severity": 0.0,
            "iv_rate_mL_per_min": 0.0,
            **self._previous_readings(),
            "irreversible_state": False,
        }

    # -- engine lifecycle -------------------------------------------------

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        bin_dir = ensure_pulse_importable(self.config["install_dir"])
        # Pulse segfaults on the first infusion of a compound it has no data for.
        compounds = bin_dir / "substances" / "compounds"
        if not (compounds / f"{self.config['iv_compound']}.json").is_file():
            raise ValueError(
                f"iv_compound {self.config['iv_compound']!r} is not a Pulse compound; available: "
                f"{sorted(p.stem for p in compounds.glob('*.json'))}"
            )

        from pulse.cdm import scalars
        from pulse.cdm.engine import SEDataRequest

        requests = []
        for prop, unit_cls, unit_name in VITALS.values():
            unit = getattr(getattr(scalars, unit_cls), unit_name) if unit_cls and unit_name else None
            requests.append(SEDataRequest.create_physiology_request(prop, unit=unit))

        if self._state is not None:
            self._engine = _load_state(self.config["install_dir"], "HumanAdultWholeBody", self._state, requests)
            self._state = None  # loaded; the parsed state is no longer needed
        else:
            self._engine = _load_engine(self.config["install_dir"], "HumanAdultWholeBody",
                                        _whole_body_state(self.config, self.config_schema), requests)
        active, _ = _active_actions(self._engine)
        for port, baseline in self._applied.items():
            if _loaded_controls(active, {port: baseline}, lambda values: self._action(port, values[port])):
                self._applied[port] = None
        if self._saver:
            self._saver(self._engine)
        return self._engine

    def _read_vitals(self) -> dict[str, float]:
        values = self._ensure_engine().pull_data()
        return {name: float(v) for name, v in zip(VITALS, values[1:])}

    def _previous_readings(self) -> dict[str, float]:
        if not self._previous:
            self._previous = self._read_vitals()
        return dict(self._previous)

    def _action(self, port: str, value: float):
        """The Pulse action for one setpoint."""
        from pulse.cdm.patient_actions import SEHemorrhage, SESubstanceCompoundInfusion
        from pulse.cdm.scalars import VolumePerTimeUnit, VolumeUnit

        if port == "hemorrhage_severity":
            action = SEHemorrhage()
            action.set_compartment(self.config["hemorrhage_compartment"])
            action.get_severity().set_value(value)
            return action
        action = SESubstanceCompoundInfusion()
        action.set_compound(self.config["iv_compound"])
        action.get_rate().set_value(value, VolumePerTimeUnit.mL_Per_min)
        action.get_bag_volume().set_value(self.config["iv_bag_volume_L"], VolumeUnit.L)
        return action

    def _apply_interventions(self, engine, state):
        severity = float(state["hemorrhage_severity"])
        if severity != self._applied["hemorrhage_severity"]:
            if not 0.0 <= severity <= 1.0:
                raise ValueError(f"hemorrhage_severity must be in [0, 1], got {severity}")
            self._send(engine, "hemorrhage_severity", severity)

        rate = float(state["iv_rate_mL_per_min"])
        if rate != self._applied["iv_rate_mL_per_min"]:
            if rate < 0.0:
                raise ValueError(f"iv_rate_mL_per_min must be >= 0, got {rate}")
            self._send(engine, "iv_rate_mL_per_min", rate)

    def _send(self, engine, port: str, value: float) -> None:
        engine.process_action(self._action(port, value))
        self._applied[port] = value

    def update(self, state, interval):
        engine = self._ensure_engine()
        if not self._alive:
            return {}
        previous = self._previous_readings()
        self._apply_interventions(engine, state)
        if not engine.advance_time_s(float(interval)):
            self._alive = False
            return {"irreversible_state": True}
        if self._saver:
            self._saver(engine)
        current = self._read_vitals()
        self._previous = current
        return {name: current[name] - previous[name] for name in VITALS}


# Engines PulseCircuitProcess can load, mapped to eModelType member names. WholeBody
# loads a stabilized state file; VentilationMechanics (no state files) initializes
# from a patient file. HumanAdultHemodynamics segfaults on its first advance (no
# ECG model) and is not selectable from Python; see docs/plan/plan-circuit-composites.md.
SUPPORTED_MODEL_TYPES = {
    "whole_body": "HumanAdultWholeBody",
    "ventilation_mechanics": "HumanAdultVentilationMechanics",
}
_INITIALIZED_FROM_PATIENT = {"ventilation_mechanics"}


def _circuit_config_schema() -> dict[str, Any]:
    schema: dict[str, Any] = {
        "model_type": {"_type": "string", "_default": "whole_body"},
        "modules": {"_type": "list[string]", "_default": []},
        "state_file": {"_type": "string", "_default": "StandardMale@0s.json"},
        "patient_file": {"_type": "string", "_default": "StandardMale.json"},
        "circuit_modifiers": {"_type": "map[float]", "_default": {}},
        "circuit_additions": {"_type": "map", "_value": {"source": "string", "target": "string",
                                                         "resistance_mmHg_s_per_mL": "float"},
                              "_default": {}},
        "save_state_times_s": {"_type": "list[float]", "_default": []},
        "save_state_dir": {"_type": "string", "_default": ""},
        "save_state_name": {"_type": "string", "_default": "state"},
        "max_settle_s": {"_type": "float", "_default": 30.0},
        "install_dir": {"_type": "string", "_default": ""},
    }
    for module in MODULES.values():
        for key, spec in module.params.items():
            if key in schema:
                raise ValueError(f"circuit module {module.name!r} redefines config key {key!r}")
            schema[key] = spec
    return schema


def _nest(leaves: list[tuple[tuple[str, ...], Any]]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for path, value in leaves:
        node = tree
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return tree


class PulseCircuitProcess(Process):
    """Bridge to one real Pulse engine, exposing the selected circuit modules.

    ``config.modules`` names entries of ``viva_pulse.circuits.MODULES``. Each
    module contributes a port subtree named after it:

    - outputs: the module's Pulse data requests as ``float`` ports, at the
      module's nested paths (e.g. ``cardiovascular/central/aorta/pressure_mmHg``);
    - inputs, under the single ``setpoints`` port: the module's setpoints as
      ``overwrite[float]`` ports whose schema default is the baseline value,
      forwarded to Pulse as actions only on change (e.g.
      ``setpoints/cardiovascular/hemorrhage_severity``).

    Inputs and outputs use disjoint top-level port names on purpose:
    process-bigraph projects ``initial_state()`` through the input wires as
    well as the output wires, so a shared name would copy readings into the
    setpoint store.

    Outputs follow ``PulseProcess``'s contract. ``initial_state()`` seeds each
    store with the loaded state's reading and every update emits
    ``current - previous``, so the store always equals Pulse's own value.
    ``irreversible_state`` turns True once Pulse reports an irreversible state;
    the engine is not advanced after that. Identical requests from different
    modules share one Pulse request. A request that Pulse cannot serve (it
    returns NaN) raises at load or at the update where it appears, naming the
    request. A module's ``check_loaded`` sees its readings at load and can reject
    a state that contradicts its setpoint baselines. All changed setpoint groups
    are validated before any action is sent, as is the airway rule: at most one
    module's ``airway_device`` connected, and none connecting in the update in
    which another disconnects.

    WholeBody loads a stabilized ``state_file``, or, when ``patient_file`` is
    set instead, that patient's state, stabilized once and then cached (see
    ``viva_pulse.patients``); setting both raises. ``circuit_modifiers`` (circuit
    path or node name -> multiplier) stabilizes the patient with Pulse's
    configuration Modifiers, also cached; whole_body only. VentilationMechanics has no
    state files, so it initializes from ``patient_file`` and then settles (see
    ``_settle``) before t = 0; setting ``state_file`` on it raises, instead of
    being silently ignored.
    Setpoints, including connecting a ventilator, apply from the first update,
    so row 0 always shows the engine as loaded or settled.

    A module with ``prepare_state`` (the ``*_points`` modules) makes construction
    read and edit ``state_file``, so such a process needs the Pulse install when it
    is built, not only at its first update.
    """

    config_schema = _circuit_config_schema()

    def __init__(self, config=None, core=None):
        super().__init__(config=config, core=core)
        model_type = self.config["model_type"]
        if model_type not in SUPPORTED_MODEL_TYPES:
            known = "known" if model_type in ENGINE_MODEL_TYPES else "unknown"
            raise ValueError(f"model_type {model_type!r} ({known}) is not supported; "
                             f"supported: {sorted(SUPPORTED_MODEL_TYPES)}")
        if model_type not in _INITIALIZED_FROM_PATIENT:
            _check_whole_body_start(self.config, self.config_schema)
        elif self.config["state_file"] != self.config_schema["state_file"]["_default"]:
            raise ValueError(f"state_file {self.config['state_file']!r} is not used by model_type "
                             f"{model_type!r}, which starts from patient_file")
        elif self.config["circuit_modifiers"]:
            raise ValueError(f"circuit_modifiers are supported on whole_body only, not {model_type!r}")
        elif self.config["circuit_additions"]:
            raise ValueError(f"circuit_additions are supported on whole_body only, not {model_type!r}")
        elif self.config["save_state_times_s"]:
            raise ValueError(f"save_state_times_s is supported on whole_body only, not {model_type!r} "
                             "(Pulse doesn't serialize it)")
        self._saver = (StateSaver(self.config["save_state_times_s"], self.config["save_state_dir"],
                                  self.config["save_state_name"])
                       if self.config["save_state_times_s"] else None)
        names = list(self.config["modules"])
        if not names:
            raise ValueError(f"modules must name at least one of {sorted(MODULES)}")
        unknown = [n for n in names if n not in MODULES]
        if unknown:
            raise ValueError(f"unknown circuit modules {unknown}; available: {sorted(MODULES)}")
        if len(set(names)) != len(names):
            raise ValueError(f"modules listed more than once: {names}")
        self._modules = [MODULES[n] for n in names]
        for module in self._modules:
            if model_type not in module.model_types:
                raise ValueError(f"circuit module {module.name!r} does not support model_type "
                                 f"{model_type!r} (supports {sorted(module.model_types)})")
            if module.check_config:
                module.check_config(self.config)

        # Added paths, and modules whose outputs depend on the state, edit a parsed copy
        # of it, which is then what the engine loads (see CircuitModule.prepare_state).
        # Paths are added first, so point reads cover them.
        self._state = None
        outputs = {module.name: module.outputs for module in self._modules}
        if self.config["circuit_additions"] or any(module.prepare_state for module in self._modules):
            self._state = _read_state(self.config["install_dir"], _whole_body_state(self.config, self.config_schema))
            add_paths(self._state, self.config["circuit_additions"])
            for module in self._modules:
                if module.prepare_state:
                    outputs[module.name] = module.prepare_state(self.config, self._state)
                    check_outputs(module.name, outputs[module.name])

        self._requests = []
        index: dict[tuple, int] = {}
        self._slots: list[tuple[tuple[str, ...], int]] = []
        for module in self._modules:
            for request in outputs[module.name]:
                key = request.key()
                if key not in index:
                    index[key] = len(self._requests)
                    self._requests.append(request)
                self._slots.append(((module.name, *request.path), index[key]))

        self._applied = {(module.name, i): dict(binding.ports)
                         for module in self._modules for i, binding in enumerate(module.bindings)}
        self._engine = None
        self._alive = True
        self._previous: list[float] = []

    def inputs(self):
        return {"setpoints": {module.name: {port: {"_type": "overwrite[float]", "_default": default}
                                            for binding in module.bindings
                                            for port, default in binding.ports.items()}
                              for module in self._modules if module.bindings}}

    def outputs(self):
        ports = _nest([(path, "float") for path, _ in self._slots])
        ports["irreversible_state"] = "boolean"
        return ports

    def initial_state(self):
        # Setpoint baselines come from the input schema ``_default``s.
        readings = self._readings()
        state = _nest([(path, readings[i]) for path, i in self._slots])
        state["irreversible_state"] = False
        return state

    # -- engine lifecycle -------------------------------------------------

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        ensure_pulse_importable(self.config["install_dir"])
        model_type = self.config["model_type"]
        requests = [pulse for request in self._requests for pulse in request.to_pulse()]
        if model_type in _INITIALIZED_FROM_PATIENT:
            engine = _initialize_engine(self.config["install_dir"], SUPPORTED_MODEL_TYPES[model_type],
                                        self.config["patient_file"], requests)
            self._settle(engine)
        elif self._state is not None:
            engine = _load_state(self.config["install_dir"], SUPPORTED_MODEL_TYPES[model_type],
                                 self._state, requests)
            self._state = None  # loaded; the parsed state is no longer needed
        else:
            engine = _load_engine(self.config["install_dir"], SUPPORTED_MODEL_TYPES[model_type],
                                  _whole_body_state(self.config, self.config_schema), requests)
        active, airway_mode = _active_actions(engine)
        for module in self._modules:
            for i, binding in enumerate(module.bindings):
                if _loaded_controls(active, dict(binding.ports), lambda values: binding.build(values, self.config)):
                    self._applied[(module.name, i)] = None
        # Equipment this process doesn't control holds the airway: connecting a device of
        # ours would make every advance fail, so refuse the state if we have one.
        devices = [(module, i) for module in self._modules if module.airway_device
                   for i, binding in enumerate(module.bindings) if module.airway_device in binding.ports]
        if airway_mode != "Free" and devices and all(self._applied[(m.name, i)] is not None for m, i in devices):
            raise ValueError(f"the loaded state's airway is held by equipment this process doesn't "
                             f"control (airway mode {airway_mode}), and Pulse allows one airway device; "
                             f"connecting {[m.name for m, _ in devices]} would stall it")
        values = self._pull(engine)
        loaded = _nest([(path, values[i]) for path, i in self._slots])
        for module in self._modules:
            if module.check_loaded:
                module.check_loaded(loaded[module.name])
        self._engine = engine
        self._previous = values
        if self._saver:
            self._saver(engine)
        return engine

    def _settle(self, engine) -> None:
        """Advance a patient-initialized engine until every request has a value.

        These engines do no stabilization (``Stabilize`` is a no-op), so
        per-breath values such as PeakInspiratoryPressure are NaN until the
        first breath completes. This settling plays the role that Pulse's
        stabilization plays for WholeBody state files. It runs before t = 0, in
        1 s steps, for at most ``max_settle_s``. A request still NaN after that
        is unserved, and ``_pull`` reports it. bigraph-schema replaces an
        explicit ``max_settle_s`` of 0.0 with the default, so settling cannot
        be switched off.
        """
        settled = 0.0
        while settled < self.config["max_settle_s"]:
            if not any(math.isnan(float(v)) for v in engine.pull_data()[1:]):
                return
            if not engine.advance_time_s(1.0):
                raise RuntimeError("Pulse reached an irreversible state while settling")
            settled += 1.0

    def _pull(self, engine) -> list[float]:
        """Current readings in request order; NaN (a request Pulse cannot serve)
        raises, because a NaN delta would poison its store for the rest of the run."""
        raw = iter(float(v) for v in engine.pull_data()[1:])
        values = []
        for request in self._requests:
            value = next(raw)
            if request.minus:
                value -= next(raw)
            values.append(value)
        unserved = [r for r, v in zip(self._requests, values) if math.isnan(v)]
        if unserved:
            raise ValueError("Pulse returned NaN for: " + ", ".join(
                f"{r.category}:{r.compartment + '.' if r.compartment else ''}{r.property}"
                + (f"-{r.minus}" if r.minus else "") for r in unserved))
        return values

    def _readings(self) -> list[float]:
        self._ensure_engine()
        return list(self._previous)

    def _tree(self, value: Callable[[int], float]) -> dict[str, Any]:
        return _nest([(path, value(i)) for path, i in self._slots])

    def _apply_setpoints(self, engine, state):
        # Validate every changed group before sending any action, so an invalid
        # setpoint never leaves the engine with only part of an update applied.
        changed = []
        for module in self._modules:
            for i, binding in enumerate(module.bindings):
                values = {port: float(state["setpoints"][module.name][port]) for port in binding.ports}
                previous = self._applied[(module.name, i)]
                if values != previous:
                    if binding.validate:
                        binding.validate(values, self.config)
                    if binding.check_transition:
                        binding.check_transition(previous, values)
                    changed.append(((module.name, i), binding, values))
        self._check_airway(state)
        for key, binding, values in changed:
            engine.process_action(binding.build(values, self.config))
            self._applied[key] = values

    def _check_airway(self, state):
        """Pulse allows one airway device at a time; a second one stalls the engine
        ("Can only change airway mode from the Free mode"). A device may connect only
        if no other device was connected before this update: in a one-update swap
        Pulse can process the new device before the old one's disconnect."""
        devices = []
        for module in self._modules:
            if module.airway_device is None:
                continue
            port = module.airway_device
            i = next(i for i, b in enumerate(module.bindings) if port in b.ports)
            applied = self._applied[(module.name, i)]
            # An unknown device (its action active in the loaded state) counts as connected.
            devices.append((module.name, applied is None or applied[port] == 1.0,
                            float(state["setpoints"][module.name][port]) == 1.0))
        now = [name for name, _, connected in devices if connected]
        if len(now) > 1:
            raise ValueError(f"only one airway device can be connected at a time, got {now}")
        before = [name for name, connected, _ in devices if connected]
        for name in now:
            others = [other for other in before if other != name]
            if name not in before and others:
                raise ValueError(f"{name} cannot connect in the same update that {others[0]} "
                                 f"disconnects; disconnect {others[0]} one update earlier")

    def update(self, state, interval):
        engine = self._ensure_engine()
        if not self._alive:
            return {}
        previous = self._readings()
        self._apply_setpoints(engine, state)
        if not engine.advance_time_s(float(interval)):
            self._alive = False
            return {"irreversible_state": True}
        if self._saver:
            self._saver(engine)
        current = self._pull(engine)
        self._previous = current
        return self._tree(lambda i: current[i] - previous[i])


class MapFluidController(Step):
    """Proportional fluid-resuscitation controller on mean arterial pressure.

    Sets the IV infusion rate in proportion to how far MAP is below
    ``target_map_mmHg``, clipped to ``[0, max_rate_mL_per_min]``. It writes a
    setpoint, so its output port is ``overwrite[float]``.
    """

    config_schema = {
        "target_map_mmHg": {"_type": "float", "_default": 90.0},
        "gain_mL_per_min_per_mmHg": {"_type": "float", "_default": 25.0},
        "max_rate_mL_per_min": {"_type": "float", "_default": 250.0},
    }

    def inputs(self):
        return {"mean_arterial_pressure_mmHg": "float"}

    def outputs(self):
        return {"iv_rate_mL_per_min": "overwrite[float]"}

    def update(self, state, interval=None):
        deficit = self.config["target_map_mmHg"] - float(state["mean_arterial_pressure_mmHg"])
        rate = self.config["gain_mL_per_min_per_mmHg"] * deficit
        rate = min(max(rate, 0.0), self.config["max_rate_mL_per_min"])
        return {"iv_rate_mL_per_min": rate}
