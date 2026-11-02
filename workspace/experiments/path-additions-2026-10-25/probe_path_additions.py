"""Does substance transport follow a path added to the circuit? Real Pulse, StandardMale.

Follow-up to mode `add` of ../circuit-access-2026-10-24: an added path is solved but has no
compartment link, so the compartment graph doesn't see it. Pulse moves substances over the
ActiveCardiovascular liquid graph (CardiovascularModel.cpp:1186). Three arms, the same
Aorta1 -> VenaCava1 shunt (R 0.5 mmHg s/mL) as mode `add`:

  unedited    no shunt;
  path_only   the path, in every circuit holding both nodes (as mode `add`);
  path_link   the path plus a LiquidLink Aorta -> VenaCava mapped to it, in every liquid
              graph holding both compartments (ActiveCardiovascular, Cardiovascular, Renal);
  path_link_cv  the same, in ActiveCardiovascular and Cardiovascular only: the graphs Pulse
              puts its own Aorta1ToBone1 link in.

Readout: plasma sodium concentration in Aorta and VenaCava. Sodium is nearly uniform in
plasma, so if blood volume moves along the path but sodium mass doesn't, the two compartments
diverge (Aorta concentrates, VenaCava dilutes). Oxygen partial pressure in VenaCava shows
whether arterial blood actually reaches the vein. Prints one JSON line per arm.

Run: uv run --no-sync python -m <this module> (from the repo root, with PULSE_INSTALL_DIR set
when run from a worktree).
"""
import json, sys

from viva_pulse.runtime import ensure_pulse_importable

BIN = ensure_pulse_importable("")

import PyPulse
from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
from pulse.cdm.enums import eSerializationFormat
from pulse.cdm.scalars import (FrequencyUnit, MassPerVolumeUnit, PressureUnit, VolumePerTimeUnit,
                               VolumeUnit)
from pulse.engine.PulseEngine import PulseEngine, eModelType

STATE = BIN / "states" / "StandardMale@0s.json"
PATH, LINK = "VivaProbeShunt", "VivaProbeShuntLink"
# The graphs Pulse puts its own Aorta1ToBone1 link (AortaToBone) in.
CARDIOVASCULAR_GRAPHS = {"ActiveCardiovascular", "Cardiovascular"}
SOURCE, TARGET = ("Aorta1", "Aorta"), ("VenaCava1", "VenaCava")
REQUESTS = [
    ("MAP", SEDataRequest.create_physiology_request("MeanArterialPressure", PressureUnit.mmHg)),
    ("HR", SEDataRequest.create_physiology_request("HeartRate", FrequencyUnit.Per_min)),
    ("CO", SEDataRequest.create_physiology_request("CardiacOutput", VolumePerTimeUnit.mL_Per_min)),
    ("BV", SEDataRequest.create_physiology_request("BloodVolume", VolumeUnit.mL)),
    ("Na_aorta", SEDataRequest.create_liquid_compartment_substance_request(
        "Aorta", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L)),
    ("Na_venacava", SEDataRequest.create_liquid_compartment_substance_request(
        "VenaCava", "Sodium", "Concentration", MassPerVolumeUnit.g_Per_L)),
    ("PO2_aorta", SEDataRequest.create_liquid_compartment_substance_request(
        "Aorta", "Oxygen", "PartialPressure", PressureUnit.mmHg)),
    ("PO2_venacava", SEDataRequest.create_liquid_compartment_substance_request(
        "VenaCava", "Oxygen", "PartialPressure", PressureUnit.mmHg)),
]


def edited(arm):
    state = json.loads(STATE.read_text())
    if arm == "unedited":
        return state, [], []
    value = {"ScalarPressureTimePerVolume": {"Value": 0.5, "Unit": "mmHg s/mL"}}
    cm = state["CircuitManager"]
    cm["FluidPath"].append({"CircuitPath": {"Name": PATH, "SourceNode": SOURCE[0], "TargetNode": TARGET[0]},
                            "Resistance": value, "NextResistance": value, "ResistanceBaseline": value})
    circuits = [c["Circuit"]["Name"] for c in cm["FluidCircuit"]
                if {SOURCE[0], TARGET[0]} <= set(c["Circuit"].get("Node", []))]
    for c in cm["FluidCircuit"]:
        if c["Circuit"]["Name"] in circuits:
            c["Circuit"]["Path"].append(PATH)
    graphs = []
    if arm in ("path_link", "path_link_cv"):
        comp = state["CompartmentManager"]
        comp["LiquidLink"].append({"FluidLink": {"Link": {
            "Name": LINK, "Path": PATH, "SourceCompartment": SOURCE[1], "TargetCompartment": TARGET[1]}}})
        for g in comp["LiquidGraph"]:
            graph = g["FluidGraph"]["Graph"]
            if {SOURCE[1], TARGET[1]} <= set(graph.get("Compartment", [])) and (
                    arm == "path_link" or graph["Name"] in CARDIOVASCULAR_GRAPHS):
                graph.setdefault("Link", []).append(LINK)
                graphs.append(graph["Name"])
    return state, circuits, graphs


def run(arm):
    state, circuits, graphs = edited(arm)
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    engine.log_to_console(False)
    if not engine.serialize_from_string(json.dumps(state), SEDataRequestManager([r for _, r in REQUESTS]),
                                        eSerializationFormat.JSON):
        raise RuntimeError(f"Pulse rejected the {arm} state")
    samples, t = {}, 0.0
    for until in (0.0, 10.0, 30.0, 60.0):
        assert engine.advance_time_s(until - t); t = until
        values = engine.pull_data()[1:]
        samples[f"{until:g}s"] = {name: round(v, 4) for (name, _), v in zip(REQUESTS, values)}
    final = json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))
    link = next((l for l in final["CompartmentManager"]["LiquidLink"]
                 if l["FluidLink"]["Link"]["Name"] == LINK), None)
    kept = {g["FluidGraph"]["Graph"]["Name"] for g in final["CompartmentManager"]["LiquidGraph"]
            if LINK in g["FluidGraph"]["Graph"].get("Link", [])}
    return {"arm": arm, "circuits": circuits, "graphs": graphs, "samples": samples,
            "link_flow_mL_per_s_at_60s": link and link["FluidLink"].get("Flow", {}).get("ScalarVolumePerTime", {}).get("Value"),
            "graphs_holding_link_after_run": sorted(kept)}


if __name__ == "__main__":
    for arm in (sys.argv[1:] or ["unedited", "path_only", "path_link", "path_link_cv"]):
        print(json.dumps(run(arm)), flush=True)
