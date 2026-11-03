"""The substances module reads blood insulin and glucose from the real whole-body engine.

Real Pulse, no mocks. The first emitted row must equal a second engine loaded
straight through Pulse's API, with the requests spelled out here, and the
readings must stay finite and physiologically plausible over a run.
"""

import math

import pytest
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites.circuits import circuit_emitter, circuit_node
from viva_pulse.core import build_core
from viva_pulse.runtime import ensure_pulse_importable


def _run(duration):
    core = build_core()
    doc = {
        "pulse": circuit_node(["substances"]),
        "emitter": circuit_emitter(),
    }
    sim = Composite({"state": doc}, core=core)
    sim.run(duration)
    return gather_emitter_results(sim)[("emitter",)]


def _direct_engine():
    """Oracle: blood insulin and glucose (ug/L) of an engine loaded through Pulse's API."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.cdm.scalars import MassPerVolumeUnit
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    requests = [SEDataRequest.create_substance_request(name, "BloodConcentration", unit=MassPerVolumeUnit.ug_Per_L)
                for name in ("Insulin", "Glucose")]
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"),
                                      SEDataRequestManager(requests))
    engine.advance_time_s(0.0)
    return [float(v) for v in engine.pull_data()[1:]]


def test_first_row_equals_a_direct_engine():
    """Falsifies: a substance reading maps to the wrong substance, property or unit."""
    insulin, glucose = _direct_engine()
    first = _run(1.0)[0]["circuits"]["substances"]
    assert first["insulin"]["blood_concentration_ug_per_L"] == pytest.approx(insulin, rel=1e-9)
    assert first["glucose"]["blood_concentration_ug_per_L"] == pytest.approx(glucose, rel=1e-9)


def test_readings_finite_and_plausible_over_a_run():
    rows = _run(60.0)
    assert len(rows) == 61
    for row in rows:
        sub = row["circuits"]["substances"]
        insulin = sub["insulin"]["blood_concentration_ug_per_L"]
        glucose = sub["glucose"]["blood_concentration_ug_per_L"]
        assert math.isfinite(insulin) and math.isfinite(glucose)
        # ~0.5 ug/L insulin is about 80 pmol/L; ~94 mg/dL glucose is ~944,000 ug/L.
        assert 0.05 < insulin < 5.0
        assert 300_000 < glucose < 1_600_000
