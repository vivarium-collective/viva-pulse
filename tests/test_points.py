"""Point reads: every node and path of the cardiovascular and respiratory circuit drawings.

The oracle is a separate engine loaded from the unedited state file, whose node
and path values come from Pulse's own serialized CircuitManager, converted with
Pulse's own unit converter. It shares nothing with the modules' compartment and
link mapping, and it has no added compartments, so agreement also shows that the
added compartments leave the simulation unchanged. Each docstring names the
proposition the test would falsify.
"""

import json
import math

import pytest

from viva_pulse.circuits import MODULES
from viva_pulse.circuits.points import CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS
from viva_pulse.composites import (pulse_cardiovascular, pulse_mechanical_ventilation, pulse_respiratory,
                                   pulse_whole_body_circuits)
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess
from viva_pulse.runtime import ensure_pulse_importable

STATE = "StandardMale@0s.json"
# module -> (Pulse circuit, {port: (Pulse property, unit string)})
CIRCUITS = {
    "cardiovascular_points": ("FullCardiovascular", {"pressure_mmHg": ("Pressure", "mmHg"),
                                                     "volume_mL": ("Volume", "mL"),
                                                     "flow_mL_per_min": ("Flow", "mL/min")}),
    "respiratory_points": ("Respiratory", {"absolute_pressure_cmH2O": ("Pressure", "cmH2O"),
                                           "volume_mL": ("Volume", "mL"),
                                           "flow_L_per_min": ("Flow", "L/min")}),
}


def _oracle_state(advance_s):
    """Pulse's own serialized state after ``advance_s`` seconds from the unedited state file."""
    bin_dir = ensure_pulse_importable()
    import PyPulse
    from pulse.cdm.engine import SEDataRequestManager
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_file(str(bin_dir / "states" / STATE), SEDataRequestManager([]))
    engine.advance_time_s(0.0)
    engine.advance_time_s(advance_s)
    return json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))


def _raw(item, prop):
    """proto3 JSON omits a zero Value and writes an infinite one as "Infinity"."""
    return float(next(iter(item[prop].values())).get("Value", 0.0))


def _oracle_value(item, prop, unit):
    import PyPulse

    return PyPulse.convert(_raw(item, prop), next(iter(item[prop].values()))["Unit"], unit)


def _topology(state, circuit):
    return next(c["Circuit"] for c in state["CircuitManager"]["FluidCircuit"] if c["Circuit"]["Name"] == circuit)


def _compare(points, state, module):
    """Every emitted point of ``module`` against the oracle state; returns the number compared."""
    circuit, ports = CIRCUITS[module]
    nodes = {n["CircuitNode"]["Name"]: n for n in state["CircuitManager"]["FluidNode"]}
    paths = {p["CircuitPath"]["Name"]: p for p in state["CircuitManager"]["FluidPath"]}
    compared = 0
    for group, items in (("nodes", nodes), ("paths", paths)):
        for name, values in points[group].items():
            for port, value in values.items():
                prop, unit = ports[port]
                expected = _oracle_value(items[name], prop, unit)
                assert value == pytest.approx(expected, rel=1e-9, abs=1e-9), (module, group, name, port)
                compared += 1
    return compared


@pytest.mark.parametrize("generator, params, module", [
    (pulse_cardiovascular, {}, "cardiovascular_points"),
    (pulse_respiratory, {"model_type": "whole_body"}, "respiratory_points"),
])
def test_every_point_equals_pulses_own_circuit_values(run_composite, generator, params, module):
    """Falsifies: a point is mapped to the wrong node or path, read in the wrong unit or with the
    wrong flow sign, a circuit node or path is missing, or the added compartments change the run."""
    _, rows = run_composite(generator, 3.0, point_reads=True, **params)
    state = _oracle_state(3.0)
    circuit, _ = CIRCUITS[module]
    topology = _topology(state, circuit)
    points = rows[-1]["circuits"][module]
    assert set(points["nodes"]) == set(topology["Node"])
    assert set(points["paths"]) == set(topology["Path"])
    nodes = {n["CircuitNode"]["Name"]: n for n in state["CircuitManager"]["FluidNode"]}
    # Volume is read where Pulse holds a finite one: not on non-compliant nodes (no Volume
    # in the state) nor on the infinite Ambient reservoir.
    with_volume = {name for name in topology["Node"]
                   if "Volume" in nodes[name] and math.isfinite(float(_raw(nodes[name], "Volume")))}
    assert {name for name, values in points["nodes"].items() if "volume_mL" in values} == with_volume
    assert all("pressure_mmHg" in v or "absolute_pressure_cmH2O" in v for v in points["nodes"].values())
    assert _compare(points, state, module) == len(topology["Node"]) + len(with_volume) + len(topology["Path"])


def test_path_flow_is_signed(run_composite):
    """Falsifies: flow is read as an unsigned compartment Inflow, so a path flowing against its
    drawn direction (air leaving the lungs on exhalation) would read zero or positive."""
    _, rows = run_composite(pulse_respiratory, 6.0, model_type="whole_body", point_reads=True)
    flows = [row["circuits"]["respiratory_points"]["paths"]["TracheaToRightConductingAirways"]["flow_L_per_min"] for row in rows]
    assert min(flows) < -1.0 and max(flows) > 1.0


ACTIONS = {"hemorrhage_severity": 0.5, "intubated": 1.0, "connected": 1.0}


def test_point_reads_leave_the_simulation_unchanged(run_composite, assert_rows_close):
    """Falsifies: the added compartments and links perturb Pulse, including when actions make it
    rebuild its compartment links (a hemorrhage, an airway change to the ventilator): any reading
    of any module differs. Also falsifies: pulse_whole_body_circuits ignores point_reads."""
    _, plain = run_composite(pulse_whole_body_circuits, 8.0, **ACTIONS)
    _, points = run_composite(pulse_whole_body_circuits, 8.0, point_reads=True, **ACTIONS)
    modules = set(plain[-1]["circuits"]) - {"irreversible_state"}
    assert set(points[-1]["circuits"]) - {"irreversible_state"} == modules | {"cardiovascular_points",
                                                                              "respiratory_points"}
    for module in modules:
        # To 1e-9, not exactly: identical Pulse runs in one process can differ by ~1e-14.
        assert_rows_close([r["circuits"][module] for r in points], [r["circuits"][module] for r in plain])


def test_no_frozen_airway_flow_while_ventilated(run_composite):
    """Falsifies: with the ventilator connected, a path Pulse no longer solves (an airway opening)
    is still reported and holds its last flow while breathing goes on."""
    _, rows = run_composite(pulse_mechanical_ventilation, 8.0, model_type="whole_body", point_reads=True)
    paths = rows[0]["circuits"]["respiratory_points"]["paths"]
    assert not {"EnvironmentToMouth", "EnvironmentToNasalCavity"} & set(paths)
    frozen = [name for name in paths
              if len({r["circuits"]["respiratory_points"]["paths"][name]["flow_L_per_min"] for r in rows[2:]}) == 1
              and rows[-1]["circuits"]["respiratory_points"]["paths"][name]["flow_L_per_min"] != 0.0]
    assert not frozen
    with pytest.raises(ValueError, match="stop being solved while an airway device is connected"):
        PulseCircuitProcess({"modules": ["mechanical_ventilator", "respiratory_points"],
                             "respiratory_point_paths": ["EnvironmentToMouth"]}, core=build_core())


def test_a_selection_reads_only_the_named_points():
    """Falsifies: the node/path lists are ignored, or a node without volume gets a (NaN) volume port."""
    process = PulseCircuitProcess({"modules": ["cardiovascular_points"],
                                   "cardiovascular_point_nodes": ["LeftHeart1", "LeftHeart2"],
                                   "cardiovascular_point_paths": ["Aorta1ToBone1"]}, core=build_core())
    assert process.outputs()["cardiovascular_points"] == {
        "nodes": {"LeftHeart1": {"pressure_mmHg": "float", "volume_mL": "float"},
                  "LeftHeart2": {"pressure_mmHg": "float"}},
        "paths": {"Aorta1ToBone1": {"flow_mL_per_min": "float"}},
    }
    state = process.initial_state()["cardiovascular_points"]
    assert state["nodes"]["LeftHeart2"]["pressure_mmHg"] > 0


@pytest.mark.parametrize("config, message", [
    ({"cardiovascular_point_nodes": ["LH1"]}, "unknown FullCardiovascular circuit nodes: ['LH1']"),
    ({"cardiovascular_point_paths": ["NoSuchPath"]}, "unknown FullCardiovascular circuit paths"),
    ({"cardiovascular_point_nodes": ["Aorta1", "Aorta1"]}, "listed more than once"),
])
def test_bad_selections_raise(config, message):
    """Falsifies: a misspelled or repeated point is silently dropped or duplicated."""
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        PulseCircuitProcess({"modules": ["cardiovascular_points"], **config}, core=build_core())


def test_points_need_the_whole_body_engine():
    """Falsifies: point reads are accepted on an engine that loads no state file to edit."""
    with pytest.raises(ValueError, match="does not support model_type 'ventilation_mechanics'"):
        PulseCircuitProcess({"modules": ["respiratory_points"], "model_type": "ventilation_mechanics"},
                            core=build_core())
    with pytest.raises(ValueError, match="point_reads needs model_type 'whole_body'"):
        pulse_respiratory(build_core(), point_reads=True)


@pytest.mark.parametrize("kind, entry, config, message", [
    ("LiquidCompartment", {"FluidCompartment": {"Compartment": {"Name": "VivaPointNodeAorta1", "Node": ["Aorta1"]}}},
     {"cardiovascular_point_nodes": ["Aorta1"]}, "already has a compartment named 'VivaPointNodeAorta1'"),
    ("LiquidLink", {"FluidLink": {"Link": {"Name": "VivaPointLinkAorta1ToBone1", "Path": "Aorta1ToBone1",
                                           "SourceCompartment": "Aorta", "TargetCompartment": "BoneVasculature"}}},
     {"cardiovascular_point_paths": ["Aorta1ToBone1"]}, "already has a link named 'VivaPointLinkAorta1ToBone1'"),
])
def test_a_name_collision_with_the_state_raises(kind, entry, config, message):
    """Falsifies: a point compartment or link silently replaces or duplicates one already in the state."""
    bin_dir = ensure_pulse_importable()
    state = json.loads((bin_dir / "states" / STATE).read_text())
    state["CompartmentManager"][kind].append(entry)
    # The config a process passes: every declared key, as bigraph-schema fills it.
    config = PulseCircuitProcess({"modules": ["cardiovascular_points"], **config}, core=build_core()).config
    with pytest.raises(ValueError, match=message):
        CARDIOVASCULAR_POINTS.prepare_state(config, state)


def test_point_modules_are_registered_whole_body_only():
    """Falsifies: the modules are missing from the registry or claim an engine they can't run on."""
    for module in (CARDIOVASCULAR_POINTS, RESPIRATORY_POINTS):
        assert MODULES[module.name] is module
        assert module.model_types == {"whole_body"}
        assert module.outputs == ()
