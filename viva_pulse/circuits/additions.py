"""Paths added to the cardiovascular circuit of a whole-body state before it loads.

An added path is a perturbation of the loaded patient: the body responds to it
over time (an arteriovenous shunt drops MAP and raises HR and CO), and Pulse does
not re-stabilize. Pulse solves a path added to its circuits, but it moves
substances only over the compartment graph (``CardiovascularModel.cpp:1186``), so
a path alone carries blood volume without its substances and corrupts
concentrations (probe ``path-additions-2026-10-25``: arterial PO2 334 mmHg). Each
addition is therefore a path plus a liquid link mapped to it:

- the path goes into every fluid circuit that holds both its nodes;
- the link joins the nodes' liquid compartments and goes into every liquid graph
  that holds both of them.

Only what the probe covered is accepted: resistance paths between nodes of the
active cardiovascular circuit (``FullCardiovascular``) in two different vascular
compartments. Vascular means in both Pulse's ``Cardiovascular`` graph and the
``ActiveCardiovascular`` transport graph, except ``AbdominalCavity`` (the peritoneal
space an internal hemorrhage fills). That leaves out ``Ground``, tissue fluid, lymph,
the pericardium, and the renal, urinary and gut-lumen compartments. Anything else
raises.

In the state, an addition named ``Shunt`` becomes path and link ``VivaAddedShunt``.
Pulse creates paths and links at run time (``<node>Hemorrhage``, pulmonary leaks,
ECMO), and its create calls return an existing object of the same name, so a user
name could otherwise be taken over by one of them.

Compartment flows come from links, so the joined compartments' regional flows
include the added path. Its resistance is fixed: Pulse's resistance multipliers and
vascular tone scale only its own paths.
"""

from __future__ import annotations

import math
from typing import Any

#: The circuit both nodes of an added path must belong to (the active cardiovascular circuit).
CIRCUIT = "FullCardiovascular"

#: The graph Pulse moves blood substances over, and its vascular graph.
TRANSPORT_GRAPH, VASCULAR_GRAPH = "ActiveCardiovascular", "Cardiovascular"

#: In both graphs, but not vascular.
NOT_VASCULAR = {"AbdominalCavity"}

#: Prefix of an added path's (and link's) name in the state.
PREFIX = "VivaAdded"

#: The fields of one addition, keyed by the new path's name.
FIELDS = ("source", "target", "resistance_mmHg_s_per_mL")


def check_additions(additions: dict[str, Any]) -> None:
    """Check each addition's fields, without the state: complete, node names, a finite
    resistance > 0, and different nodes."""
    for name, addition in additions.items():
        if not isinstance(addition, dict) or set(addition) != set(FIELDS):
            raise ValueError(f"circuit addition {name!r} must have exactly the fields {list(FIELDS)}, "
                             f"got {addition!r}")
        resistance = addition["resistance_mmHg_s_per_mL"]
        if (isinstance(resistance, bool) or not isinstance(resistance, (int, float))
                or not math.isfinite(resistance) or resistance <= 0):
            raise ValueError(f"circuit addition {name!r}: resistance_mmHg_s_per_mL must be a finite "
                             f"number > 0, got {resistance!r}")
        if addition["source"] == addition["target"]:
            raise ValueError(f"circuit addition {name!r} joins node {addition['source']!r} to itself")


def add_paths(state: dict[str, Any], additions: dict[str, Any]) -> None:
    """Add each path and its link to the parsed state, in place (see the module docstring)."""
    check_additions(additions)
    circuits, compartments = state["CircuitManager"], state["CompartmentManager"]
    nodes = set(next(c["Circuit"] for c in circuits["FluidCircuit"]
                     if c["Circuit"]["Name"] == CIRCUIT).get("Node", []))
    owner = {node: c["FluidCompartment"]["Compartment"]["Name"]
             for c in compartments["LiquidCompartment"]
             for node in c["FluidCompartment"]["Compartment"].get("Node", [])}
    graphs = {g["FluidGraph"]["Graph"]["Name"]: set(g["FluidGraph"]["Graph"].get("Compartment", []))
              for g in compartments["LiquidGraph"]}
    vascular = (graphs[TRANSPORT_GRAPH] & graphs[VASCULAR_GRAPH]) - NOT_VASCULAR
    taken = ({p["CircuitPath"]["Name"] for p in circuits["FluidPath"]}
             | {link["FluidLink"]["Link"]["Name"] for link in compartments["LiquidLink"]})

    for key, addition in additions.items():
        name = f"{PREFIX}{key}"
        source, target = addition["source"], addition["target"]
        if name in taken:
            raise ValueError(f"circuit addition {key!r}: {name!r} is already a path or link name in the state")
        missing = [node for node in (source, target) if node not in nodes]
        if missing:
            raise ValueError(f"circuit addition {key!r}: {missing} not nodes of {CIRCUIT}")
        outside = [f"{node} ({owner.get(node, 'no compartment')})" for node in (source, target)
                   if owner.get(node) not in vascular]
        if outside:
            raise ValueError(f"circuit addition {key!r}: {outside} not in a vascular compartment, "
                             f"so blood substances could not follow the path")
        if owner[source] == owner[target]:
            raise ValueError(f"circuit addition {key!r}: both nodes are in compartment "
                             f"{owner[source]!r}; paths within one compartment are not supported")

        value = {"ScalarPressureTimePerVolume": {"Value": float(addition["resistance_mmHg_s_per_mL"]),
                                                 "Unit": "mmHg s/mL"}}
        circuits["FluidPath"].append({
            "CircuitPath": {"Name": name, "SourceNode": source, "TargetNode": target},
            "Resistance": value, "NextResistance": value, "ResistanceBaseline": value})
        for circuit in circuits["FluidCircuit"]:
            if {source, target} <= set(circuit["Circuit"].get("Node", [])):
                circuit["Circuit"].setdefault("Path", []).append(name)

        compartments["LiquidLink"].append({"FluidLink": {"Link": {
            "Name": name, "Path": name,
            "SourceCompartment": owner[source], "TargetCompartment": owner[target]}}})
        for graph in compartments["LiquidGraph"]:
            graph = graph["FluidGraph"]["Graph"]
            if {owner[source], owner[target]} <= set(graph.get("Compartment", [])):
                graph.setdefault("Link", []).append(name)
        taken.add(name)
