"""Registry of Pulse circuit modules available to ``PulseCircuitProcess``."""

from .base import ENGINE_MODEL_TYPES, ActionBinding, CircuitModule, Request
from .cardiovascular import CARDIOVASCULAR
from .hepatic import HEPATIC
from .points import CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS
from .respiratory import MECHANICAL_VENTILATOR, RESPIRATORY
from .substances import SUBSTANCES
from .supplemental_oxygen import SUPPLEMENTAL_OXYGEN
from .thermal import THERMAL

#: Every circuit module, by name: the values ``PulseCircuitProcess`` accepts in ``config.modules``.
MODULES: dict[str, CircuitModule] = {
    m.name: m for m in (CARDIOVASCULAR, RESPIRATORY, MECHANICAL_VENTILATOR, THERMAL, SUPPLEMENTAL_OXYGEN,
                        SUBSTANCES, HEPATIC, CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS)
}

__all__ = ["ENGINE_MODEL_TYPES", "ActionBinding", "CircuitModule", "MODULES", "Request"]
