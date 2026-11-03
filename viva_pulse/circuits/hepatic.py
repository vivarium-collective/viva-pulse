"""Hepatic module: what a liver tissue model needs from Pulse.

- ``liver/insulin_pmol_per_L``: insulin in the liver's vascular compartment
  (``LiverVasculature``). Pulse treats it as well mixed. Liver *tissue* insulin is
  not used: Pulse holds it at its initial value (``LiverTissueExtracellular`` and
  ``LiverTissueIntracellular`` stay at 0.412 ug/L over a run while the vascular
  value moves).
- ``liver/glucose_mM``, ``liver/lactate_mM``, ``liver/epinephrine_pmol_per_L``:
  glucose, lactate and epinephrine in the same compartment, for a liver
  metabolism model.
- ``liver/tissue_mass_kg``: the liver's tissue mass.
- ``body/core_temperature_C``: core temperature, for thermodynamics.

Insulin is requested as ``Molarity``, so Pulse converts mass to amount with its
own molar mass (``substances/Insulin.json``, 5808 g/mol).

No flows are read. Pulse clears insulin at the vena cava, not in the liver
(``DrugModel::CalculateSubstanceClearance``: insulin has no intrinsic, i.e.
hepatic, clearance), so Pulse's liver has no inlet-to-outlet extraction to read.
And a portal vessel's ``AverageOutflow`` is not its flow into the liver: Pulse
sums every outgoing link, including the one into gut or spleen tissue
(``SEFluidCompartment::CalculateOutflow_mL_Per_s``).

Whole body only.
"""

from __future__ import annotations

from .base import CircuitModule, Request

HEPATIC = CircuitModule(
    name="hepatic",
    model_types=frozenset({"whole_body"}),
    outputs=(
        Request(path=("liver", "insulin_pmol_per_L"), category="liquid_compartment_substance",
                property="Molarity", unit=("AmountPerVolumeUnit", "pmol_Per_L"),
                compartment="LiverVasculature", substance="Insulin"),
        Request(path=("liver", "glucose_mM"), category="liquid_compartment_substance",
                property="Molarity", unit=("AmountPerVolumeUnit", "mmol_Per_L"),
                compartment="LiverVasculature", substance="Glucose"),
        Request(path=("liver", "lactate_mM"), category="liquid_compartment_substance",
                property="Molarity", unit=("AmountPerVolumeUnit", "mmol_Per_L"),
                compartment="LiverVasculature", substance="Lactate"),
        Request(path=("liver", "epinephrine_pmol_per_L"), category="liquid_compartment_substance",
                property="Molarity", unit=("AmountPerVolumeUnit", "pmol_Per_L"),
                compartment="LiverVasculature", substance="Epinephrine"),
        Request(path=("liver", "tissue_mass_kg"), category="tissue", property="TotalMass",
                unit=("MassUnit", "kg"), compartment="LiverTissue"),
        Request(path=("body", "core_temperature_C"), category="physiology", property="CoreTemperature",
                unit=("TemperatureUnit", "C")),
    ),
)
