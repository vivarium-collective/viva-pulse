"""Composite generators: registration, wiring, and real-engine runs."""

import pytest
from process_bigraph.composite_generator import _REGISTRY

from viva_pulse.composites import pulse_hemorrhage, pulse_resuscitation
from viva_pulse.processes import VITALS


@pytest.mark.parametrize("name", ["pulse_hemorrhage", "pulse_resuscitation"])
def test_generator_is_registered(name):
    assert [eid for eid in _REGISTRY if eid.endswith(f".{name}")], list(_REGISTRY)[:5]


def test_first_emitted_row_carries_loaded_vitals(run_composite):
    """Falsifies: the t=0 row doesn't carry the loaded state. Before 1.10.1 (#268),
    process-bigraph dropped initial_state() on overwrite[float] ports and it was all zeros."""
    _, rows = run_composite(pulse_hemorrhage, 1.0)
    first = rows[0]
    assert first["time"] == 0.0
    assert first["heart_rate_bpm"] == pytest.approx(72.0, abs=1.0)
    assert first["blood_volume_mL"] == pytest.approx(5487.0, abs=10.0)
    assert first["irreversible_state"] is False


def test_hemorrhage_composite_stores_track_the_engine(run_composite):
    """Falsifies: the stores don't hold Pulse's reading while it changes: an update
    emitting deltas into the overwrite ports, or absolute readings into additive ones."""
    sim, rows = run_composite(pulse_hemorrhage, 120.0)
    assert len(rows) == 121
    truth = sim.state["pulse"]["instance"]._read_vitals()
    for k in VITALS:
        assert rows[-1][k] == pytest.approx(truth[k], abs=1e-6)
    assert rows[-1]["total_hemorrhaged_volume_mL"] > 300.0


def test_resuscitation_controller_engages_and_preserves_volume(run_composite):
    _, untreated = run_composite(pulse_hemorrhage, 600.0)
    _, treated = run_composite(pulse_resuscitation, 600.0)
    # The controller stays off while MAP is above target, then infuses.
    assert treated[0]["iv_rate_mL_per_min"] == 0.0
    assert max(r["iv_rate_mL_per_min"] for r in treated) > 0.0
    assert treated[-1]["blood_volume_mL"] > untreated[-1]["blood_volume_mL"] + 50.0
    assert treated[-1]["mean_arterial_pressure_mmHg"] > untreated[-1]["mean_arterial_pressure_mmHg"]


def test_lethal_hemorrhage_reaches_irreversible_state_and_stops(run_composite):
    _, rows = run_composite(pulse_hemorrhage, 180.0, compartment="Aorta", severity=1.0)
    dead = [i for i, r in enumerate(rows) if r["irreversible_state"]]
    assert dead, "Pulse never reported an irreversible state"
    frozen = rows[dead[0]:]
    assert all(r["blood_volume_mL"] == frozen[0]["blood_volume_mL"] for r in frozen)
