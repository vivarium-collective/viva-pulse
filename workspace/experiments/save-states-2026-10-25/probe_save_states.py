"""Saving Pulse states mid-run: what a saved state holds and whether it round-trips. Real Pulse.

StandardMale, a RightLeg hemorrhage (severity 0.5) from t = 0. Prints one JSON line:
- the time the saved state records, and the engine's own time (pull_data()[0]) when saved;
- whether the hemorrhage's run-time path and link (CardiovascularModel.cpp:1837) appear in the
  saved CircuitManager / CompartmentManager;
- round trip: save at 10 s, load it into a new engine, advance 20 s; compare every vital with the
  uninterrupted engine at 30 s (max relative difference).
"""
import json, tempfile
from pathlib import Path

from viva_pulse.processes import VITALS, _load_engine
from viva_pulse.runtime import ensure_pulse_importable

ensure_pulse_importable("")
from pulse.cdm import scalars
from pulse.cdm.engine import SEDataRequest
from pulse.cdm.patient_actions import SEHemorrhage, eHemorrhage_Compartment

requests = [SEDataRequest.create_physiology_request(p, getattr(getattr(scalars, c), u) if c else None)
            for p, c, u in VITALS.values()]


def bleeding():
    engine = _load_engine("", "HumanAdultWholeBody", "StandardMale@0s.json", requests)
    action = SEHemorrhage()
    action.set_compartment(eHemorrhage_Compartment.RightLeg)
    action.get_severity().set_value(0.5)
    engine.process_action(action)
    return engine


with tempfile.TemporaryDirectory() as tmp:
    run = bleeding()
    assert run.advance_time_s(10.0)
    saved_at = run.pull_data()[0]
    path = Path(tmp) / "bleed@10s.json"
    assert run.serialize_to_file(str(path))
    state = json.loads(path.read_text())
    paths = [p["CircuitPath"]["Name"] for p in state["CircuitManager"]["FluidPath"] if "Hemorrhage" in p["CircuitPath"]["Name"]]
    links = [l["FluidLink"]["Link"]["Name"] for l in state["CompartmentManager"]["LiquidLink"] if "Hemorrhage" in l["FluidLink"]["Link"]["Name"]]
    actions = [list(a.keys()) for a in state.get("ActionManager", {}).get("PatientAction", [])] if isinstance(state.get("ActionManager"), dict) else None

    assert run.advance_time_s(20.0)
    uninterrupted = dict(zip(VITALS, run.pull_data()[1:]))
    reloaded = _load_engine("", "HumanAdultWholeBody", str(path), requests)
    reloaded_at = reloaded.pull_data()[0]
    assert reloaded.advance_time_s(20.0)
    resumed = dict(zip(VITALS, reloaded.pull_data()[1:]))

rel = {k: abs(resumed[k] - uninterrupted[k]) / max(abs(uninterrupted[k]), 1e-12) for k in VITALS}
print(json.dumps({
    "state_simulation_time": state["SimulationTime"]["ScalarTime"].get("Value"),
    "engine_time_when_saved": saved_at, "reloaded_engine_time": reloaded_at,
    "hemorrhage_paths_in_state": paths, "hemorrhage_links_in_state": links,
    "action_manager_keys": list(state.get("ActionManager", {}).keys()) if isinstance(state.get("ActionManager"), dict) else None,
    "roundtrip_max_rel_diff": max(rel.values()), "roundtrip_worst": max(rel, key=rel.get),
    "bit_identical": all(resumed[k] == uninterrupted[k] for k in VITALS),
    "blood_lost_at_30s_mL": uninterrupted["total_hemorrhaged_volume_mL"],
}))
