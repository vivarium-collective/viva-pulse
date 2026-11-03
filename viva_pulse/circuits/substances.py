"""Substance module: blood concentrations of selected substances, read from Pulse.

Pulse tracks every substance in the patient (``SESubstance``) and exposes its
whole-body values through substance data requests. This module reports the
blood concentration of each substance it names. Readings: one per substance,
at ``<substance>/blood_concentration_ug_per_L``.

Provisional. Arnab's open issue #35 defines the final scope, including the
decisions this module does not make: how requests for a substance that is not
yet active are reported, unit validation, and whether ``PulseProcess`` gets the
same config. The two substances here are active from the loaded state's start.

The module is declarative and computes nothing. Pulse's own units do the
conversion: requested in ``ug_Per_L`` (``MassPerVolumeUnit``).

Whole body only: the substance requests need the whole-body engine.
"""

from __future__ import annotations

from .base import CircuitModule, Request

# (output name, Pulse substance name)
_SUBSTANCES = (
    ("insulin", "Insulin"),
    ("glucose", "Glucose"),
)


def _outputs() -> tuple[Request, ...]:
    return tuple(
        Request(
            path=(name, "blood_concentration_ug_per_L"),
            category="substance",
            property="BloodConcentration",
            unit=("MassPerVolumeUnit", "ug_Per_L"),
            substance=substance,
        )
        for name, substance in _SUBSTANCES
    )


SUBSTANCES = CircuitModule(
    name="substances",
    model_types=frozenset({"whole_body"}),
    outputs=_outputs(),
)
