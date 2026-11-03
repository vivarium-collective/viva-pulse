"""The substances module reads blood insulin and glucose from the real whole-body engine.

Real Pulse, no mocks. The first emitted row must equal Pulse's own loaded-state
value (the delta-seeded store contract), and the readings must stay finite and
physiologically plausible over a run.
"""

import math

from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites.circuits import circuit_emitter, circuit_node
from viva_pulse.core import build_core

# Pulse's own loaded-state readings (StandardMale@0s.json), measured at t=0 by the
# L1 probe (scratchpad phase0/l1_substance_probe.py): ug/L for insulin and glucose.
LOADED_INSULIN_UG_PER_L = 0.4758
LOADED_GLUCOSE_UG_PER_L = 944145.1268


def _run(duration):
    core = build_core()
    doc = {
        "pulse": circuit_node(["substances"]),
        "emitter": circuit_emitter(),
    }
    sim = Composite({"state": doc}, core=core)
    sim.run(duration)
    return gather_emitter_results(sim)[("emitter",)]


def test_first_row_carries_loaded_substance_values():
    rows = _run(5.0)
    first = rows[0]["circuits"]["substances"]
    assert math.isclose(first["insulin"]["blood_concentration_ug_per_L"],
                        LOADED_INSULIN_UG_PER_L, rel_tol=1e-3)
    assert math.isclose(first["glucose"]["blood_concentration_ug_per_L"],
                        LOADED_GLUCOSE_UG_PER_L, rel_tol=1e-3)


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
