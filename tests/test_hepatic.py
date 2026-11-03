"""The hepatic module reads liver insulin and tissue mass from the real whole-body engine.

Real Pulse, no mocks. The oracle is a second engine loaded straight through
Pulse's API, with every request spelled out here rather than taken from the module.
"""

import json
import math

import pytest

from viva_pulse.composites import pulse_hepatic
from viva_pulse.runtime import ensure_pulse_importable

# (output path) -> (Pulse request kind, compartment, substance, property, unit class, unit)
ORACLE = {
    ("liver", "insulin_pmol_per_L"): ("cmpt_sub", "LiverVasculature", "Insulin", "Molarity",
                                      "AmountPerVolumeUnit", "pmol_Per_L"),
    ("liver", "glucose_mM"): ("cmpt_sub", "LiverVasculature", "Glucose", "Molarity",
                              "AmountPerVolumeUnit", "mmol_Per_L"),
    ("liver", "lactate_mM"): ("cmpt_sub", "LiverVasculature", "Lactate", "Molarity",
                              "AmountPerVolumeUnit", "mmol_Per_L"),
    ("liver", "tissue_mass_kg"): ("tissue", "LiverTissue", None, "TotalMass", "MassUnit", "kg"),
    ("body", "core_temperature_C"): ("physiology", None, None, "CoreTemperature", "TemperatureUnit", "C"),
    ("check", "glucose_mg_per_dL"): ("cmpt_sub", "LiverVasculature", "Glucose", "Concentration",
                                     "MassPerVolumeUnit", "mg_Per_dL"),
    # Not a module output: the same insulin as a mass concentration, to check the unit.
    ("check", "insulin_ug_per_L"): ("cmpt_sub", "LiverVasculature", "Insulin", "Concentration",
                                    "MassPerVolumeUnit", "ug_Per_L"),
}


def _direct_engine(paths):
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = []
    for path in paths:
        kind, compartment, substance, prop, unit_cls, unit_name = ORACLE[path]
        unit = getattr(getattr(scalars, unit_cls), unit_name)
        if kind == "cmpt_sub":
            requests.append(SEDataRequest.create_liquid_compartment_substance_request(
                compartment, substance, prop, unit=unit))
        elif kind == "physiology":
            requests.append(SEDataRequest.create_physiology_request(prop, unit=unit))
        else:
            requests.append(SEDataRequest.create_tissue_request(compartment, prop, unit=unit))
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"),
                                      SEDataRequestManager(requests))
    engine.advance_time_s(0.0)
    return [float(v) for v in engine.pull_data()[1:]]


def _at(tree, path):
    for key in path:
        tree = tree[key]
    return tree


def test_first_row_equals_a_direct_engine(run_composite):
    """Falsifies: a hepatic reading is mapped to the wrong compartment, substance,
    property or unit (each spelled independently in ORACLE). Liver insulin in
    pmol/L must also equal Pulse's own mass concentration over its molar mass."""
    paths = list(ORACLE)
    oracle = dict(zip(paths, _direct_engine(paths)))
    _, rows = run_composite(pulse_hepatic, 1)
    hepatic = rows[0]["circuits"]["hepatic"]
    for path, expected in oracle.items():
        assert math.isfinite(expected), path
        if path[0] != "check":
            assert _at(hepatic, path) == pytest.approx(expected, rel=1e-9), path
    substances = ensure_pulse_importable() / "substances"

    def g_per_mol(name):
        return json.loads((substances / f"{name}.json").read_text(encoding="utf-8"))["MolarMass"]["ScalarMassPerAmount"]["Value"]

    pmol_per_L = oracle[("check", "insulin_ug_per_L")] * 1e-6 / g_per_mol("Insulin") * 1e12
    assert hepatic["liver"]["insulin_pmol_per_L"] == pytest.approx(pmol_per_L, rel=1e-9)
    mM = oracle[("check", "glucose_mg_per_dL")] * 10.0 / g_per_mol("Glucose")  # mg/dL -> mg/L -> mmol/L
    assert hepatic["liver"]["glucose_mM"] == pytest.approx(mM, rel=1e-9)
