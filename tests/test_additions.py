"""Circuit additions: a cardiovascular path added, with its compartment link, before the state loads.

The oracle is a separate engine loaded from a state the test edits itself, spelled out
independently of ``viva_pulse.circuits.additions``: the link goes only into the two graphs
Pulse uses for its own links (the module puts it into every graph holding both
compartments). A second oracle adds the path without a link. Probe
``path-additions-2026-10-25`` measured both: without the link, substances don't follow the
path and the vitals become artifacts (HR 177 vs 135 at 60 s). Each docstring names the
proposition the test would falsify.
"""

import json

import pytest

from viva_pulse.circuits import MODULES
from viva_pulse.composites import pulse_cardiovascular
from viva_pulse.core import build_core
from viva_pulse.processes import PulseCircuitProcess, PulseProcess
from viva_pulse.runtime import ensure_pulse_importable

SHUNT = {"Shunt": {"source": "Aorta1", "target": "VenaCava1", "resistance_mmHg_s_per_mL": 0.5}}
SECONDS = 30
HEMODYNAMICS = {"mean_arterial_pressure_mmHg": ("MeanArterialPressure", "PressureUnit", "mmHg"),
                "heart_rate_bpm": ("HeartRate", "FrequencyUnit", "Per_min"),
                "cardiac_output_L_per_min": ("CardiacOutput", "VolumePerTimeUnit", "L_Per_min")}


def _oracle(link):
    """Pulse's vitals after SECONDS from StandardMale with the shunt edited in by hand."""
    bin_dir = ensure_pulse_importable()
    from pulse.cdm import scalars
    from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
    from pulse.cdm.enums import eSerializationFormat
    from pulse.engine.PulseEngine import PulseEngine, eModelType

    state = json.loads((bin_dir / "states" / "StandardMale@0s.json").read_text())
    value = {"ScalarPressureTimePerVolume": {"Value": 0.5, "Unit": "mmHg s/mL"}}
    state["CircuitManager"]["FluidPath"].append(
        {"CircuitPath": {"Name": "OracleShunt", "SourceNode": "Aorta1", "TargetNode": "VenaCava1"},
         "Resistance": value, "NextResistance": value, "ResistanceBaseline": value})
    for circuit in state["CircuitManager"]["FluidCircuit"]:
        if circuit["Circuit"]["Name"] in ("Cardiovascular", "FullCardiovascular"):
            circuit["Circuit"]["Path"].append("OracleShunt")
    if link:
        state["CompartmentManager"]["LiquidLink"].append({"FluidLink": {"Link": {
            "Name": "OracleShuntLink", "Path": "OracleShunt",
            "SourceCompartment": "Aorta", "TargetCompartment": "VenaCava"}}})
        for graph in state["CompartmentManager"]["LiquidGraph"]:
            if graph["FluidGraph"]["Graph"]["Name"] in ("ActiveCardiovascular", "Cardiovascular"):
                graph["FluidGraph"]["Graph"]["Link"].append("OracleShuntLink")
    requests = [SEDataRequest.create_physiology_request(prop, getattr(getattr(scalars, cls), unit))
                for prop, cls, unit in HEMODYNAMICS.values()]
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
    engine.log_to_console(False)
    assert engine.serialize_from_string(json.dumps(state), SEDataRequestManager(requests),
                                        eSerializationFormat.JSON)
    assert engine.advance_time_s(SECONDS)
    return dict(zip(HEMODYNAMICS, engine.pull_data()[1:]))


def _accumulate(store, deltas):
    for key, delta in deltas.items():
        if isinstance(delta, dict):
            _accumulate(store[key], delta)
        elif not isinstance(delta, bool):
            store[key] += delta


def _run_circuit(**config):
    process = PulseCircuitProcess({"modules": ["cardiovascular", "cardiovascular_points"],
                                   "cardiovascular_point_nodes": ["Aorta1"],
                                   "cardiovascular_point_paths": ["VivaAddedShunt"], **config}, core=build_core())
    state = process.initial_state()
    setpoints = {"cardiovascular": {port: default for binding in MODULES["cardiovascular"].bindings
                                    for port, default in binding.ports.items()}}
    for _ in range(SECONDS):
        _accumulate(state, process.update({"setpoints": setpoints}, 1.0))
    return state


@pytest.fixture(scope="module")
def shunted():
    return _run_circuit(circuit_additions=SHUNT)


def test_the_shunt_runs_as_a_linked_path(shunted):
    """Falsifies: the path is added without its link (substances don't follow it; the vitals
    match the path-only oracle instead), not added at all, or added differently from Pulse's
    own representation of a linked path."""
    linked, path_only = _oracle(link=True), _oracle(link=False)
    hemodynamics = shunted["cardiovascular"]["hemodynamics"]
    for port in HEMODYNAMICS:
        assert hemodynamics[port] == pytest.approx(linked[port], rel=1e-9), port
    # The two oracles are far apart, so agreement with the linked one is evidence.
    assert abs(path_only["heart_rate_bpm"] - linked["heart_rate_bpm"]) > 10


def test_the_shunt_carries_flow_and_is_point_readable(shunted):
    """Falsifies: point reads don't cover an added path, or the path carries no flow."""
    flow = shunted["cardiovascular_points"]["paths"]["VivaAddedShunt"]["flow_mL_per_min"]
    assert flow > 100 * 60  # about 150 mL/s in the probe


def test_pulse_process_runs_the_shunt(shunted):
    """Falsifies: PulseProcess drops circuit_additions."""
    process = PulseProcess({"circuit_additions": SHUNT}, core=build_core())
    vitals = process.initial_state()
    for _ in range(SECONDS):
        for name, delta in process.update({"hemorrhage_severity": 0.0, "iv_rate_mL_per_min": 0.0}, 1.0).items():
            if name != "irreversible_state":
                vitals[name] += delta
    assert vitals["heart_rate_bpm"] == pytest.approx(
        shunted["cardiovascular"]["hemodynamics"]["heart_rate_bpm"], rel=1e-9)


def test_a_composite_runs_the_shunt(run_composite):
    """Falsifies: circuit_additions stops at the generator."""
    _, rows = run_composite(pulse_cardiovascular, SECONDS, circuit_additions=SHUNT)
    last = rows[-1]["circuits"]["cardiovascular"]["hemodynamics"]
    assert last["heart_rate_bpm"] == pytest.approx(_oracle(link=True)["heart_rate_bpm"], rel=1e-9)


def _addition(**fields):
    return {"Added": {**SHUNT["Shunt"], **fields}}


@pytest.mark.parametrize("additions, message", [
    ({"Added": {"source": "Aorta1", "target": "VenaCava1"}}, "exactly the fields"),
    (_addition(resistance_mmHg_s_per_mL=0.0), "finite number > 0"),
    (_addition(resistance_mmHg_s_per_mL=-1.0), "finite number > 0"),
    (_addition(resistance_mmHg_s_per_mL=float("nan")), "finite number > 0"),
    (_addition(resistance_mmHg_s_per_mL=True), "finite number > 0"),
    (_addition(target="Aorta1"), "to itself"),
    (_addition(target="NoSuchNode"), "not nodes of FullCardiovascular"),
    (_addition(target="RightAortaConnection"), "no compartment"),
    (_addition(target="Ground"), "not in a vascular compartment"),
    (_addition(target="BoneT2"), "not in a vascular compartment"),  # tissue fluid
    (_addition(target="Lymph"), "not in a vascular compartment"),
    (_addition(target="Pericardium1"), "not in a vascular compartment"),
    (_addition(target="AbdominalCavity1"), "not in a vascular compartment"),
    (_addition(target="Bladder"), "not in a vascular compartment"),
    (_addition(target="SmallIntestineC1"), "not in a vascular compartment"),
    (_addition(target="Aorta2"), "both nodes are in compartment 'Aorta'"),
])
def test_unsupported_additions_raise_at_construction(additions, message):
    """Falsifies: an addition the probe didn't cover (a node outside the vascular compartments,
    where the link would join no transport graph or a non-blood space; one compartment; a
    nonphysical resistance) loads, where it would corrupt substances or the state."""
    with pytest.raises(ValueError, match=message):
        PulseCircuitProcess({"modules": ["cardiovascular"], "circuit_additions": additions},
                            core=build_core())


def test_additions_on_ventilation_mechanics_raise():
    """Falsifies: additions are silently ignored on the engine that loads no state."""
    with pytest.raises(ValueError, match="whole_body only"):
        PulseCircuitProcess({"model_type": "ventilation_mechanics", "modules": ["respiratory"],
                             "circuit_additions": SHUNT}, core=build_core())


def test_a_name_pulse_creates_at_run_time_cannot_take_over_the_link():
    """Falsifies: an addition keeps the user's name in the state. Pulse names a hemorrhage's
    link <compartment>Hemorrhage and its create call returns an existing link of that name, so
    an addition called AortaHemorrhage would be remapped onto the bleed and lose its transport
    (HR 159 vs 84 at 30 s in review). Runs with both names must be identical."""
    def heart_rate(key):
        process = PulseCircuitProcess({"modules": ["cardiovascular"], "hemorrhage_compartment": "Aorta",
                                       "circuit_additions": {key: SHUNT["Shunt"]}}, core=build_core())
        state = process.initial_state()
        setpoints = {"cardiovascular": {**{port: default for binding in MODULES["cardiovascular"].bindings
                                           for port, default in binding.ports.items()},
                                        "hemorrhage_severity": 0.5}}
        for _ in range(SECONDS):
            _accumulate(state, process.update({"setpoints": setpoints}, 1.0))
        return state["cardiovascular"]["hemodynamics"]["heart_rate_bpm"]

    assert heart_rate("AortaHemorrhage") == heart_rate("Shunt")
