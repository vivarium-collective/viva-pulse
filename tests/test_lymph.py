"""Pulse 4.4.0's lymph is wired into the circuit but carries no flow (issue #36).

viva-pulse reports no lymph outputs because of it (docs/plan/plan-substances-and-lymph.md,
probe substances-lymph-2026-11-01). These tests guard that decision: they fail if a Pulse
upgrade switches lymph on, so the docs and the cardiovascular module get revisited. Each
docstring names the proposition the test would falsify.
"""

import json

import pytest

from viva_pulse.composites.circuits import circuit_emitter, circuit_node
from viva_pulse.circuits.cardiovascular import CARDIOVASCULAR
from viva_pulse.runtime import ensure_pulse_importable

TISSUES = ["Bone", "Brain", "Fat", "Gut", "LeftKidney", "LeftLung", "Liver", "Muscle", "Myocardium",
           "RightKidney", "RightLung", "Skin", "Spleen"]
LYMPH_PATHS = [f"{t}T1ToLymph" for t in TISSUES] + ["LymphToVenaCava1"]


def _state():
    return json.loads((ensure_pulse_importable() / "states" / "StandardMale@0s.json").read_text())


def test_lymph_paths_are_zero_flow_sources_outside_every_transport_graph():
    """Falsifies: Pulse's state gives a tissue-to-lymph path a nonzero flow source or any other
    element, or puts Lymph in a liquid graph (then substances would move through it)."""
    state = _state()
    paths = {p["CircuitPath"]["Name"]: p for p in state["CircuitManager"]["FluidPath"]}
    for tissue in TISSUES:
        path = paths[f"{tissue}T1ToLymph"]
        elements = set(path) - {"CircuitPath"}
        assert elements <= {"Flow", "NextFlow", "FlowSource", "NextFlowSource", "FlowSourceBaseline"}, (tissue, elements)
        assert all(float(next(iter(path[k].values())).get("Value", 0.0)) == 0.0
                   for k in elements if "FlowSource" in k), tissue
    graphs = state["CompartmentManager"]["LiquidGraph"]
    assert not [g["FluidGraph"]["Graph"]["Name"] for g in graphs
                if "Lymph" in g["FluidGraph"]["Graph"].get("Compartment", [])]


def test_no_lymph_flows_during_a_hemorrhage():
    """Falsifies: lymph carries flow during a hemorrhage (which shifts tissue fluid), or the Lymph
    node's pressure is anything but the vena cava's. Read through cardiovascular_points, whose
    values equal Pulse's own circuit values (tests/test_points.py)."""
    from process_bigraph import Composite, gather_emitter_results

    from viva_pulse.core import build_core

    core = build_core()
    setpoints = {port: value for binding in CARDIOVASCULAR.bindings for port, value in binding.ports.items()}
    setpoints["hemorrhage_severity"] = 0.8
    document = {
        # The cardiovascular module drives the hemorrhage; the points read lymph on the same engine.
        "pulse": circuit_node(["cardiovascular", "cardiovascular_points"],
                              cardiovascular_point_nodes=["Lymph", "VenaCava1"],
                              cardiovascular_point_paths=LYMPH_PATHS),
        "interventions": {"cardiovascular": setpoints},
        "circuits": {},
        "emitter": circuit_emitter(),
    }
    sim = Composite({"state": document}, core=core)
    sim.run(120)
    rows = gather_emitter_results(sim)[("emitter",)]
    blood_volume = [r["circuits"]["cardiovascular"]["hemodynamics"]["blood_volume_mL"] for r in rows]
    assert blood_volume[-1] < blood_volume[0] - 300  # the hemorrhage did shift fluid
    for row in rows:
        points = row["circuits"]["cardiovascular_points"]
        for path in LYMPH_PATHS:
            assert abs(points["paths"][path]["flow_mL_per_min"]) < 1e-6, (row["time"], path)
        assert points["nodes"]["Lymph"]["pressure_mmHg"] == pytest.approx(
            points["nodes"]["VenaCava1"]["pressure_mmHg"], rel=1e-12)
