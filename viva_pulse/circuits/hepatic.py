"""Hepatic module: what the liver's blood supply carries, read from Pulse.

The reads a liver tissue model needs from the whole body:

- ``liver/insulin_pmol_per_L``: insulin in the liver's vascular compartment. Pulse
  treats it as well mixed. Liver *tissue* insulin is not used: Pulse holds it at
  its initial value (``LiverTissueExtracellular`` and ``LiverTissueIntracellular``
  stay at 0.412 ug/L over a run while the vascular value moves).
- ``liver/average_inflow_mL_per_min``: blood entering the liver, averaged over the
  last cardiac cycle.
- ``liver/tissue_mass_kg``: the liver's tissue mass.
- ``sources/<name>/insulin_pmol_per_L`` for the five vessels that feed the liver,
  and ``sources/<name>/average_outflow_mL_per_min`` for the four portal ones
  (gut, splanchnic, spleen). Pulse's splanchnic compartment carries the
  pancreatic secretion. The fifth source, the hepatic artery, carries aortic
  blood; its flow is the liver inflow minus the portal outflows (Pulse has no
  link-flow request).

Flows are Pulse's cardiac-cycle averages (``AverageInflow``, ``AverageOutflow``),
which Pulse keeps for exactly these compartments (``CardiovascularModel.cpp``,
``SampleCompartment``). Instantaneous ``Inflow``/``Outflow`` sampled once a second
land on random points of the beat; a flow-weighted inlet concentration built
from them swung 0.96-1.60 x the liver value from one second to the next.

Insulin is requested as ``Molarity``, so Pulse converts mass to amount with its
own molar mass (``substances/Insulin.json``, 5808 g/mol).

Whole body only.
"""

from __future__ import annotations

from .base import CircuitModule, Request

_PMOL_PER_L = ("AmountPerVolumeUnit", "pmol_Per_L")
_ML_PER_MIN = ("VolumePerTimeUnit", "mL_Per_min")

#: Output name -> Pulse vascular compartment, for the four portal vessels.
PORTAL_SOURCES = {
    "large_intestine": "LargeIntestineVasculature",
    "small_intestine": "SmallIntestineVasculature",
    "splanchnic": "SplanchnicVasculature",
    "spleen": "SpleenVasculature",
}


def _insulin(path, compartment):
    return Request(path=path, category="liquid_compartment_substance", property="Molarity",
                   unit=_PMOL_PER_L, compartment=compartment, substance="Insulin")


def _outputs() -> tuple[Request, ...]:
    outputs = [
        _insulin(("liver", "insulin_pmol_per_L"), "LiverVasculature"),
        Request(path=("liver", "average_inflow_mL_per_min"), category="liquid_compartment",
                property="AverageInflow", unit=_ML_PER_MIN, compartment="LiverVasculature"),
        Request(path=("liver", "tissue_mass_kg"), category="tissue", property="TotalMass",
                unit=("MassUnit", "kg"), compartment="LiverTissue"),
        _insulin(("sources", "aorta", "insulin_pmol_per_L"), "Aorta"),
    ]
    for name, compartment in PORTAL_SOURCES.items():
        outputs.append(_insulin(("sources", name, "insulin_pmol_per_L"), compartment))
        outputs.append(Request(path=("sources", name, "average_outflow_mL_per_min"),
                               category="liquid_compartment", property="AverageOutflow",
                               unit=_ML_PER_MIN, compartment=compartment))
    return tuple(outputs)


HEPATIC = CircuitModule(
    name="hepatic",
    model_types=frozenset({"whole_body"}),
    outputs=_outputs(),
)
