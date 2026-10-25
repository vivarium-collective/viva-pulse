"""Registry of Pulse circuit modules available to ``PulseCircuitProcess``."""

from .base import ENGINE_MODEL_TYPES, ActionBinding, CircuitModule, Request
from .cardiovascular import CARDIOVASCULAR
from .points import CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS
from .respiratory import MECHANICAL_VENTILATOR, RESPIRATORY
from .supplemental_oxygen import SUPPLEMENTAL_OXYGEN
from .thermal import THERMAL

#: Every circuit module, by name: the values ``PulseCircuitProcess`` accepts in ``config.modules``.
MODULES: dict[str, CircuitModule] = {
    m.name: m for m in (CARDIOVASCULAR, RESPIRATORY, MECHANICAL_VENTILATOR, THERMAL, SUPPLEMENTAL_OXYGEN,
                        CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS)
}

__all__ = ["ENGINE_MODEL_TYPES", "ActionBinding", "CircuitModule", "MODULES", "Request"]
