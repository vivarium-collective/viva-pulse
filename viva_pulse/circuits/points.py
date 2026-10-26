"""Point reads: single circuit nodes and paths, the points of Pulse's circuit drawings.

Pulse has no data request for a circuit node or path (``Engine.proto`` ``eCategory``).
A compartment, though, is a named set of nodes, and a link is a named path. So
before the state loads, these modules add, for every selected point:

- a node: a single-node compartment ``VivaPointNode<node>``, read for Pressure
  and, on nodes that hold volume, Volume;
- a path: dedicated compartments ``VivaPointFrom<path>`` and ``VivaPointTo<path>``
  on its source and target nodes, joined by a link ``VivaPointLink<path>`` mapped
  to the path. The target compartment's only link is that path, so its
  ``Inflow - Outflow`` is the path's signed flow (``SEFluidCompartment.hxx``).

Compartments and links only name what the circuit already holds: Pulse solves the
same circuit, and a run with every point added matches one without (bit-identical in
``workspace/experiments/circuit-access-2026-10-24``, mode ``points``; identical Pulse runs in one
process can differ by about 1e-14, so the tests compare to 1e-9).

The nodes and paths come from the loaded state's own ``CircuitManager``, so the
names are Pulse's. An empty selection (the default) reads every node and path of
the circuit as loaded. Paths that Pulse adds during a run (a hemorrhage's bleed
path, for example) aren't included.

When an airway device can be connected on the same engine, the respiratory paths
that its combined circuit drops (the airway openings) aren't read: while the
device is connected Pulse doesn't solve them, and they would hold their last flow.
"""

from __future__ import annotations

import math
from typing import Any

from .base import CircuitModule, Request

PREFIX = "VivaPoint"


def _select(kind: str, chosen: list[str], available: list[str], circuit: str) -> list[str]:
    if not chosen:
        return list(available)
    unknown = [name for name in chosen if name not in available]
    if unknown:
        raise ValueError(f"unknown {circuit} circuit {kind}s: {unknown}")
    if len(set(chosen)) != len(chosen):
        raise ValueError(f"{circuit} circuit {kind}s listed more than once: {chosen}")
    return list(chosen)


def _readable(node: dict[str, Any], prop: str) -> bool:
    """Whether a node property can be a port.

    Pulse leaves an invalid property out of the state: a non-compliant node has no
    Volume, and a request for it reads NaN. A reservoir node (``Ambient``) holds an
    infinite volume, which proto3 JSON writes as ``"Infinity"``; it never changes and is
    not a finite reading, so it is left out too.
    """
    if prop not in node:
        return False
    value = next(iter(node[prop].values())).get("Value", 0.0)
    return math.isfinite(float(value))


def _airway_device_possible(config: dict[str, Any], state: dict[str, Any]) -> bool:
    """Whether an airway device can be connected during the run: the state already has one
    (an airway mode other than Free, which proto3 JSON omits) or a module on the same
    engine can connect one."""
    from . import MODULES

    return state.get("AirwayMode", "Free") != "Free" or any(
        MODULES[name].airway_device for name in config["modules"] if name in MODULES)


def _point_module(name: str, circuit: str, fluid: str, ports: dict[str, tuple[str, tuple[str, str]]]):
    """A module reading the nodes and paths of Pulse fluid circuit ``circuit``.

    ``fluid`` is ``"Liquid"`` or ``"Gas"`` (the state's compartment and link kinds).
    ``ports`` maps ``pressure``/``volume``/``flow`` to (port name, unit).
    """
    nodes_key, paths_key = f"{name.removesuffix('_points')}_point_nodes", f"{name.removesuffix('_points')}_point_paths"
    category = f"{fluid.lower()}_compartment"

    def prepare_state(config: dict[str, Any], state: dict[str, Any]) -> tuple[Request, ...]:
        circuits = {c["Circuit"]["Name"]: c["Circuit"] for c in state["CircuitManager"]["FluidCircuit"]}
        nodes = {n["CircuitNode"]["Name"]: n for n in state["CircuitManager"]["FluidNode"]}
        paths = {p["CircuitPath"]["Name"]: p["CircuitPath"] for p in state["CircuitManager"]["FluidPath"]}
        topology = circuits[circuit]
        readable_paths = list(topology["Path"])
        if _airway_device_possible(config, state):
            # A device's combined circuit (one holding every node of this circuit) leaves
            # some of its paths out (the airway openings); while the device is connected
            # Pulse doesn't solve them and they keep their last flow, so they aren't read.
            dropped = {p for c in circuits.values() if c is not topology
                       and set(topology["Node"]) <= set(c.get("Node", []))
                       for p in topology["Path"] if p not in c.get("Path", [])}
            readable_paths = [p for p in readable_paths if p not in dropped]
            chosen = [p for p in config[paths_key] if p in dropped]
            if chosen:
                raise ValueError(f"{circuit} paths {chosen} stop being solved while an airway device is "
                                 f"connected, and this engine can connect one; they can't be read")
        selected_nodes = _select("node", list(config[nodes_key]), topology["Node"], circuit)
        selected_paths = _select("path", list(config[paths_key]), readable_paths, circuit)

        compartments = state["CompartmentManager"][f"{fluid}Compartment"]
        taken = {c["FluidCompartment"]["Compartment"]["Name"]
                 for kind in ("LiquidCompartment", "GasCompartment") for c in state["CompartmentManager"][kind]}
        taken |= {l["FluidLink"]["Link"]["Name"]
                  for kind in ("LiquidLink", "GasLink") for l in state["CompartmentManager"][kind]}

        def add(compartment: str, node: str) -> None:
            if compartment in taken:
                raise ValueError(f"the state already has a compartment named {compartment!r}")
            taken.add(compartment)
            compartments.append({"FluidCompartment": {"Compartment": {"Name": compartment, "Node": [node]}}})

        outputs = []
        for node in selected_nodes:
            compartment = f"{PREFIX}Node{node}"
            add(compartment, node)
            for prop, (port, unit) in (("Pressure", ports["pressure"]), ("Volume", ports["volume"])):
                if _readable(nodes[node], prop):
                    outputs.append(Request(("nodes", node, port), category, prop, unit, compartment))
        flow = ports["flow"]
        for path in selected_paths:
            source, target = f"{PREFIX}From{path}", f"{PREFIX}To{path}"
            add(source, paths[path]["SourceNode"])
            add(target, paths[path]["TargetNode"])
            link = f"{PREFIX}Link{path}"
            if link in taken:
                raise ValueError(f"the state already has a link named {link!r}")
            taken.add(link)
            state["CompartmentManager"][f"{fluid}Link"].append({"FluidLink": {"Link": {
                "Name": link, "Path": path, "SourceCompartment": source, "TargetCompartment": target}}})
            outputs.append(Request(("paths", path, flow[0]), category, "Inflow", flow[1], target, minus="Outflow"))
        return tuple(outputs)

    return CircuitModule(
        name=name,
        model_types=frozenset({"whole_body"}),
        params={nodes_key: {"_type": "list[string]", "_default": []},
                paths_key: {"_type": "list[string]", "_default": []}},
        prepare_state=prepare_state,
    )


#: Every node and path of the active cardiovascular circuit (``FullCardiovascular``,
#: which includes the renal and tissue branches: 124 nodes, 212 paths).
CARDIOVASCULAR_POINTS = _point_module("cardiovascular_points", "FullCardiovascular", "Liquid", {
    "pressure": ("pressure_mmHg", ("PressureUnit", "mmHg")),
    "volume": ("volume_mL", ("VolumeUnit", "mL")),
    "flow": ("flow_mL_per_min", ("VolumePerTimeUnit", "mL_Per_min")),
})

#: Every node and path of the respiratory (airway) circuit: 24 nodes, 34 paths. Pressures
#: are absolute (ambient is 1033.2 cmH2O), as in the ``respiratory`` module.
RESPIRATORY_POINTS = _point_module("respiratory_points", "Respiratory", "Gas", {
    "pressure": ("absolute_pressure_cmH2O", ("PressureUnit", "cmH2O")),
    "volume": ("volume_mL", ("VolumeUnit", "mL")),
    "flow": ("flow_L_per_min", ("VolumePerTimeUnit", "L_Per_min")),
})
