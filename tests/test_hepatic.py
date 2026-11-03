"""The hepatic module reads the liver's blood supply from the real whole-body engine.

Real Pulse, no mocks. The oracle is a second engine loaded straight through
Pulse's API, with every request spelled out here rather than taken from the module.
"""

import math

import pytest

from viva_pulse.composites import pulse_hepatic
from viva_pulse.runtime import ensure_pulse_importable

# (output path) -> (Pulse request kind, compartment, substance, property, unit class, unit)
ORACLE = {
    ("liver", "insulin_pmol_per_L"): ("cmpt_sub", "LiverVasculature", "Insulin", "Molarity",
                                      "AmountPerVolumeUnit", "pmol_Per_L"),
    ("liver", "average_inflow_mL_per_min"): ("cmpt", "LiverVasculature", None, "AverageInflow",
                                             "VolumePerTimeUnit", "mL_Per_min"),
    ("liver", "tissue_mass_kg"): ("tissue", "LiverTissue", None, "TotalMass", "MassUnit", "kg"),
    ("sources", "aorta", "insulin_pmol_per_L"): ("cmpt_sub", "Aorta", "Insulin", "Molarity",
                                                 "AmountPerVolumeUnit", "pmol_Per_L"),
    ("sources", "splanchnic", "insulin_pmol_per_L"): ("cmpt_sub", "SplanchnicVasculature", "Insulin",
                                                      "Molarity", "AmountPerVolumeUnit", "pmol_Per_L"),
    ("sources", "splanchnic", "average_outflow_mL_per_min"): ("cmpt", "SplanchnicVasculature", None,
                                                              "AverageOutflow", "VolumePerTimeUnit",
                                                              "mL_Per_min"),
    ("sources", "spleen", "average_outflow_mL_per_min"): ("cmpt", "SpleenVasculature", None,
                                                          "AverageOutflow", "VolumePerTimeUnit",
                                                          "mL_Per_min"),
}
PORTAL = ("large_intestine", "small_intestine", "splanchnic", "spleen")


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
        elif kind == "cmpt":
            requests.append(SEDataRequest.create_liquid_compartment_request(compartment, prop, unit=unit))
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
    property or unit (each spelled independently in ORACLE)."""
    paths = list(ORACLE)
    oracle = _direct_engine(paths)
    _, rows = run_composite(pulse_hepatic, 1)
    hepatic = rows[0]["circuits"]["hepatic"]
    for path, expected in zip(paths, oracle):
        assert math.isfinite(expected), path
        assert _at(hepatic, path) == pytest.approx(expected, rel=1e-9), path


def test_cycle_averaged_inlet_is_smooth_and_above_the_liver_value(run_composite):
    """Falsifies: the flows are instantaneous rather than cycle-averaged. Sampled once
    a second, instantaneous flows made the flow-weighted inlet concentration jump
    0.96-1.60 x the liver value tick to tick (measured over 120 s). With Pulse's
    cardiac-cycle averages it moved 1.16-1.21 x, at most 0.003 per tick, and stayed
    above the liver value, as an organ that clears insulin requires."""
    _, rows = run_composite(pulse_hepatic, 60)
    ratios = []
    for row in rows:
        h = row["circuits"]["hepatic"]
        q_in = h["liver"]["average_inflow_mL_per_min"]
        portal = [(h["sources"][s]["insulin_pmol_per_L"], h["sources"][s]["average_outflow_mL_per_min"])
                  for s in PORTAL]
        q_artery = q_in - sum(q for _, q in portal)
        assert q_artery > 0.1 * q_in
        c_in = (sum(c * q for c, q in portal) + h["sources"]["aorta"]["insulin_pmol_per_L"] * q_artery) / q_in
        ratios.append(c_in / h["liver"]["insulin_pmol_per_L"])
    assert min(ratios) > 1.0
    assert max(abs(b - a) for a, b in zip(ratios, ratios[1:])) < 0.01
