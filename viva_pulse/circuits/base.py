"""Declarative description of one Pulse circuit family as process-bigraph ports.

A ``CircuitModule`` names the Pulse data requests that become its output ports
and the Pulse actions that its setpoint input ports drive. It computes nothing:
``PulseCircuitProcess`` turns the selected modules into ports, requests and
actions against one real Pulse engine.

Pulse's Python package is importable only after ``ensure_pulse_importable()``,
so units and actions are resolved lazily, at engine-load time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

ENGINE_MODEL_TYPES = ("whole_body", "hemodynamics", "ventilation_mechanics")

# Top-level port names of PulseCircuitProcess that a module name must not shadow.
RESERVED_NAMES = frozenset({"setpoints", "irreversible_state"})


@dataclass(frozen=True)
class Request:
    """One Pulse data request, emitted at ``path`` inside its module's port tree.

    ``category`` is ``"physiology"``, ``"environment"``, ``"liquid_compartment"``,
    ``"gas_compartment"``, ``"thermal_compartment"`` or ``"mechanical_ventilator"``.
    ``unit`` is ``(unit class in pulse.cdm.scalars, unit attribute)``, or None for
    unitless. Compartment property names are Pulse's own spelling: ``Pressure``,
    ``Volume``, ``Inflow``, ``Outflow`` (``SEDataRequestTracker.cpp``), and
    ``Temperature``, ``Heat``, ``HeatTransferRateIn``, ``HeatTransferRateOut``
    for thermal compartments (``SEThermalCompartment.cpp``).

    With ``minus`` set, the output is ``property - minus`` on the same compartment,
    read as two Pulse requests: a compartment whose only link is one circuit path
    has ``Inflow - Outflow`` equal to that path's signed flow.
    """

    path: tuple[str, ...]
    category: str
    property: str
    unit: tuple[str, str] | None
    compartment: str | None = None
    minus: str | None = None

    def key(self) -> tuple:
        """Identity of the underlying Pulse request; equal keys share one request."""
        return (self.category, self.compartment, self.property, self.unit, self.minus)

    def to_pulse(self) -> list:
        """The Pulse data requests this output reads: one, or two with ``minus``."""
        return [self._pulse(self.property)] + ([self._pulse(self.minus)] if self.minus else [])

    def _pulse(self, property: str):
        from pulse.cdm import scalars
        from pulse.cdm.engine import SEDataRequest

        unit = getattr(getattr(scalars, self.unit[0]), self.unit[1]) if self.unit else None
        if self.category == "physiology":
            return SEDataRequest.create_physiology_request(property, unit=unit)
        if self.category == "environment":
            return SEDataRequest.create_environment_request(property, unit=unit)
        if self.category == "liquid_compartment":
            return SEDataRequest.create_liquid_compartment_request(
                self.compartment, property, unit=unit)
        if self.category == "gas_compartment":
            return SEDataRequest.create_gas_compartment_request(
                self.compartment, property, unit=unit)
        if self.category == "thermal_compartment":
            return SEDataRequest.create_thermal_compartment_request(
                self.compartment, property, unit=unit)
        if self.category == "mechanical_ventilator":
            return SEDataRequest.create_mechanical_ventilator_request(property, unit=unit)
        raise ValueError(f"unsupported data request category {self.category!r}")


@dataclass(frozen=True)
class ActionBinding:
    """A group of setpoint ports forwarded to Pulse as one action.

    ``ports`` maps each port name to its baseline value (the value at which no
    action is needed). Whenever any port in the group changes, ``build`` is
    called with every port's current value plus the process config and returns
    the Pulse action to send. ``validate`` raises ``ValueError`` on bad values;
    ``check_transition(previous, values)`` raises ``ValueError`` on a change
    Pulse cannot make (e.g. one its Python API silently drops).
    """

    ports: dict[str, float]
    build: Callable[[dict[str, float], dict[str, Any]], Any]
    validate: Callable[[dict[str, float], dict[str, Any]], None] | None = None
    check_transition: Callable[[dict[str, float], dict[str, float]], None] | None = None


def check_outputs(module: str, outputs: tuple[Request, ...]) -> None:
    """Output paths must be unique, and none may be a prefix of another."""
    paths = [r.path for r in outputs]
    if len(set(paths)) != len(paths):
        raise ValueError(f"{module}: duplicate output paths")
    for a in paths:
        for b in paths:
            if a != b and b[: len(a)] == a:
                raise ValueError(f"{module}: output path {a} is a prefix of {b}")


def validate_switch(port: str, value: float) -> None:
    """A 0/1 setpoint."""
    if value not in (0.0, 1.0):
        raise ValueError(f"{port} must be 0 or 1, got {value}")


@dataclass(frozen=True)
class CircuitModule:
    """One circuit family: its outputs, its setpoint bindings, its config params.

    ``model_types`` lists the Pulse engines (``ENGINE_MODEL_TYPES``) on which
    every request and action of this module is supported. ``params`` are
    ``config_schema`` entries that ``PulseCircuitProcess`` exposes, and
    ``check_config`` validates them, raising ``ValueError``. ``check_loaded``
    receives the module's readings (nested like its outputs) once the engine is
    loaded, and raises ``ValueError`` if the loaded state contradicts the
    module's setpoint baselines. ``airway_device`` names the module's 0/1
    setpoint that is 1 while its equipment occupies Pulse's airway: Pulse
    allows one airway device at a time and stalls when a second one connects.

    A module whose outputs depend on the loaded state sets ``prepare_state``
    instead of ``outputs``. ``PulseCircuitProcess`` reads the whole_body state
    file before loading it and calls ``prepare_state(config, state)`` with the
    parsed state JSON. The callable may add compartments and links to the state
    (Pulse's own way of naming circuit nodes and paths for data requests) and
    returns the module's outputs. The edited state is what the engine loads.
    """

    name: str
    model_types: frozenset[str]
    outputs: tuple[Request, ...] = ()
    bindings: tuple[ActionBinding, ...] = ()
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    check_config: Callable[[dict[str, Any]], None] | None = None
    check_loaded: Callable[[dict[str, Any]], None] | None = None
    airway_device: str | None = None
    prepare_state: Callable[[dict[str, Any], dict[str, Any]], tuple[Request, ...]] | None = None

    def __post_init__(self):
        if self.name in RESERVED_NAMES:
            raise ValueError(f"circuit module name {self.name!r} is reserved")
        unknown = self.model_types - set(ENGINE_MODEL_TYPES)
        if unknown:
            raise ValueError(f"{self.name}: unknown model types {sorted(unknown)}")
        if self.prepare_state is not None:
            if self.outputs:
                raise ValueError(f"{self.name}: a module with prepare_state declares no static outputs")
            if self.model_types != {"whole_body"}:
                raise ValueError(f"{self.name}: prepare_state edits a state file, which only whole_body loads")
        check_outputs(self.name, self.outputs)
        ports = [p for b in self.bindings for p in b.ports]
        if len(set(ports)) != len(ports):
            raise ValueError(f"{self.name}: duplicate setpoint ports")
        if self.airway_device is not None and self.airway_device not in ports:
            raise ValueError(f"{self.name}: airway_device {self.airway_device!r} is not a setpoint port")
