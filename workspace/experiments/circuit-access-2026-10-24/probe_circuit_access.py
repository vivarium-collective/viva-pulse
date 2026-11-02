"""Probes for agenda item 7 (circuit-level access), real Pulse, StandardMale.

Modes, each printing one JSON line:
  reads     P-a: circuit node/path values from serialize_to_string vs compartment requests;
            which properties are absent vs zero; serialization, pickling and advance costs.
  virtual   P-a: read-only compartments and links added to the state, read with ordinary
            data requests; dynamics compared with the unedited state.
  edit      P-b: one path's resistance edited in the state JSON, then reloaded.
  modifier  P-b: the same path scaled by Pulse's own configuration Modifiers at initialization.
  add       P-c: one path added to the state JSON, then reloaded.
  remove    P-c: one path removed (with its link and graph entry), in a child process.
  patient   P-d: initialize_engine wall time for a patient Pulse doesn't ship; cache round trip.
  hemo      P-e: the Hemodynamics (cardiovascular-only) engine, in a child process.
"""
import copy, json, pickle, subprocess, sys, tempfile, time
from pathlib import Path

from viva_pulse.processes import _load_engine
from viva_pulse.runtime import ensure_pulse_importable

BIN = ensure_pulse_importable("")

import PyPulse
from pulse.cdm.engine import SEDataRequest, SEDataRequestManager
from pulse.cdm.enums import eSerializationFormat
from pulse.cdm.patient import SEPatientConfiguration
from pulse.cdm.scalars import FrequencyUnit, PressureUnit, VolumePerTimeUnit, VolumeUnit
from pulse.engine.PulseEngine import PulseEngine, eModelType

STATE = BIN / "states" / "StandardMale@0s.json"
PATIENT = BIN / "patients" / "StandardMale.json"
VITALS = [("MeanArterialPressure", PressureUnit.mmHg), ("HeartRate", FrequencyUnit.Per_min),
          ("CardiacOutput", VolumePerTimeUnit.mL_Per_min), ("BloodVolume", VolumeUnit.mL)]


def vitals_requests():
    return [SEDataRequest.create_physiology_request(p, unit=u) for p, u in VITALS]


def read_vitals(engine, digits=3):
    return {p: round(v, digits) for (p, _), v in zip(VITALS, engine.pull_data()[1:])}


def engine_state(engine):
    return json.loads(engine.serialize_to_string(PyPulse.serialization_format.json))


def by_name(items, key):
    return {i[key]["Name"]: i for i in items}


def fluid(state, kind):
    key = "CircuitNode" if kind == "FluidNode" else "CircuitPath"
    return by_name(state["CircuitManager"][kind], key)


def scalar(prop, name):
    """Pulse leaves an invalid property out entirely; proto3 JSON leaves out a 0.0 Value."""
    if name not in prop:
        return None
    return next(iter(prop[name].values())).get("Value", 0.0)


def from_json(state, requests=None, log=False):
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    engine.log_to_console(log)
    if not engine.serialize_from_string(json.dumps(state), SEDataRequestManager(requests or vitals_requests()),
                                        eSerializationFormat.JSON):
        raise RuntimeError("Pulse rejected the edited state")
    engine.advance_time_s(0.0)
    return engine


def median_ms(fn, n):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return round(sorted(ts)[n // 2] * 1e3, 2)


def path_summary(engine, path, window_s=5.0, dt=0.1):
    """Mean path flow over the last ``window_s`` seconds (several cardiac cycles), plus resistance."""
    flows = []
    for _ in range(round(window_s / dt)):
        engine.advance_time_s(dt)
        p = fluid(engine_state(engine), "FluidPath").get(path)
        if p is None:
            return {"flow_mean_mL_per_s": None, "resistance": None}
        flows.append(scalar(p, "Flow"))
    return {"flow_mean_mL_per_s": round(sum(flows) / len(flows), 3), "resistance": round(scalar(p, "Resistance"), 3)}


def trace(engine, path, until_s=30.0):
    """Vitals and the path at 30 s, the path averaged over 25-30 s."""
    engine.advance_time_s(until_s - 5.0)
    summary = path_summary(engine, path)
    return {**read_vitals(engine), **summary}


def reads():
    base = json.loads(STATE.read_text())
    cv_nodes = set(by_name(base["CircuitManager"]["FluidCircuit"], "Circuit")["Cardiovascular"]["Circuit"]["Node"])
    single = {}
    for c in base["CompartmentManager"]["LiquidCompartment"]:
        comp = c["FluidCompartment"]["Compartment"]
        if len(comp.get("Node", [])) == 1 and comp["Node"][0] in cv_nodes:
            single[comp["Name"]] = comp["Node"][0]
    names = sorted(single)
    requests = [SEDataRequest.create_liquid_compartment_request(n, "Pressure", PressureUnit.mmHg) for n in names]
    engine = _load_engine("", "HumanAdultWholeBody", STATE.name, requests)
    engine.advance_time_s(1.0)
    measured = engine.pull_data()[1:]
    state = engine_state(engine)
    nodes, paths = fluid(state, "FluidNode"), fluid(state, "FluidPath")
    diffs = {n: abs(scalar(nodes[single[n]], "Pressure") - v) for n, v in zip(names, measured)}

    def census(items, prop, among=None):
        out = {"absent": [], "zero": [], "valued": 0}
        for name, item in items.items():
            if among is not None and name not in among:
                continue
            value = scalar(item, prop)
            if value is None:
                out["absent"].append(name)
            elif value == 0.0:
                out["zero"].append(name)
            else:
                out["valued"] += 1
        return out

    cv_paths = set(by_name(state["CircuitManager"]["FluidCircuit"], "Circuit")["Cardiovascular"]["Circuit"]["Path"])
    aorta = [scalar(nodes["Aorta1"], "Pressure")]
    engine.advance_time_s(0.37)
    aorta.append(scalar(fluid(engine_state(engine), "FluidNode")["Aorta1"], "Pressure"))
    failures = {}
    for label, fn in [("binary_serialization", lambda: engine.serialize_to_string(PyPulse.serialization_format.binary)),
                      ("pickle", lambda: pickle.dumps(engine))]:
        try:
            fn()
            failures[label] = "ok"
        except Exception as e:
            failures[label] = f"{type(e).__name__}: {str(e)[:80]}"
    return {**failures, "compared": len(names), "nonzero_compared": sum(v != 0.0 for v in measured),
            "max_abs_diff_mmHg": max(diffs.values()),
            "zero_nodes_vs_request": {single[n]: float(v) for n, v in zip(names, measured) if v == 0.0},
            "pressure_all_nodes": census(nodes, "Pressure"),
            "volume_cardiovascular_nodes": census(nodes, "Volume", cv_nodes),
            "flow_cardiovascular_paths": census(paths, "Flow", cv_paths),
            "flow_all_paths_absent": len(census(paths, "Flow")["absent"]),
            "aorta1_0.37s_apart": aorta,
            "state_MB": round(len(engine.serialize_to_string(PyPulse.serialization_format.json)) / 1e6, 2),
            "serialize_parse_ms": median_ms(lambda: engine_state(engine), 21),
            "advance_0.02s_ms": median_ms(lambda: engine.advance_time_s(0.02), 51),
            "advance_1s_ms": median_ms(lambda: engine.advance_time_s(1.0), 21)}


def add_virtual(state, nodes, link=None):
    """Append read-only single-node compartments (``V<node>``) and optionally a link on a path."""
    cm = state["CompartmentManager"]
    for n in nodes:
        cm["LiquidCompartment"].append({"FluidCompartment": {"Compartment": {"Name": f"V{n}", "Node": [n]}}})
    if link:
        path, source, target = link
        cm["LiquidLink"].append({"FluidLink": {"Link": {"Name": f"V{path}", "Path": path,
                                                        "SourceCompartment": f"V{source}",
                                                        "TargetCompartment": f"V{target}"}}})
    return state


def virtual():
    nodes = ["LeftHeart1", "LeftHeart2", "LeftHeart3", "Aorta1", "Aorta2", "Bone1"]
    link = ("Aorta1ToBone1", "Aorta1", "Bone1")
    state = add_virtual(json.loads(STATE.read_text()), nodes, link)
    requests = vitals_requests()
    requests += [SEDataRequest.create_liquid_compartment_request(f"V{n}", "Pressure", PressureUnit.mmHg) for n in nodes]
    requests += [SEDataRequest.create_liquid_compartment_request("VBone1", "Inflow", VolumePerTimeUnit.mL_Per_s),
                 SEDataRequest.create_liquid_compartment_request("VAorta1", "Volume", VolumeUnit.mL)]
    engine, now, checks = from_json(state, requests), 0.0, []
    for t in (0.5, 1.37, 30.0):
        engine.advance_time_s(t - now)
        now = t
        values = engine.pull_data()[1 + len(VITALS):]
        s = engine_state(engine)
        sn, sp = fluid(s, "FluidNode"), fluid(s, "FluidPath")
        expected = [scalar(sn[n], "Pressure") for n in nodes]
        expected += [scalar(sp[link[0]], "Flow"), scalar(sn["Aorta1"], "Volume")]
        checks.append({"t": t, "max_abs_diff": max(abs(a - b) for a, b in zip(values, expected)),
                       "LeftHeart2_mmHg": round(values[1], 3), "Aorta1ToBone1_flow": round(values[-2], 4)})
    plain = from_json(json.loads(STATE.read_text()))
    plain.advance_time_s(30.0)
    return {"nodes": nodes, "link": link[0], "checks": checks,
            "vitals_30s_virtual": read_vitals(engine, 9), "vitals_30s_unedited": read_vitals(plain, 9),
            "identical": read_vitals(engine, 12) == read_vitals(plain, 12),
            "pull_data_cost_ms": median_ms(lambda: engine.pull_data(), 51)}


POINT_CIRCUITS = {"FullCardiovascular": ("Liquid", "liquid", "mmHg", "mL", "mL/min"),
                  "Respiratory": ("Gas", "gas", "cmH2O", "mL", "L/min")}


def add_points(state):
    """Every node of the two circuits as a single-node compartment, and every path as a link between
    a dedicated source and target compartment, so target Inflow - Outflow is that path's signed flow."""
    cm, comp = state["CircuitManager"], state["CompartmentManager"]
    circuits = by_name(cm["FluidCircuit"], "Circuit")
    nodes, paths = fluid(state, "FluidNode"), fluid(state, "FluidPath")
    existing = {c["FluidCompartment"]["Compartment"]["Name"] for k in ("LiquidCompartment", "GasCompartment")
                for c in comp[k]}
    plan = []
    for circuit, (kind, *_) in POINT_CIRCUITS.items():
        c = circuits[circuit]["Circuit"]

        def compartment(name, node):
            assert name not in existing, name
            existing.add(name)
            comp[f"{kind}Compartment"].append({"FluidCompartment": {"Compartment": {"Name": name, "Node": [node]}}})

        for n in c["Node"]:
            compartment(f"VivaPoint{n}", n)
            plan.append(("node", circuit, n, "Volume" in nodes[n]))
        for p in c["Path"]:
            src, tgt = paths[p]["CircuitPath"]["SourceNode"], paths[p]["CircuitPath"]["TargetNode"]
            compartment(f"VivaPointSrc{p}", src)
            compartment(f"VivaPointTgt{p}", tgt)
            comp[f"{kind}Link"].append({"FluidLink": {"Link": {"Name": f"VivaPoint{p}", "Path": p,
                                                               "SourceCompartment": f"VivaPointSrc{p}",
                                                               "TargetCompartment": f"VivaPointTgt{p}"}}})
            plan.append(("path", circuit, p, None))
    return plan


def points():
    from pulse.cdm import scalars
    extra = [SEDataRequest.create_physiology_request("OxygenSaturation"),
             SEDataRequest.create_physiology_request("TidalVolume", unit=VolumeUnit.mL),
             SEDataRequest.create_physiology_request("RespirationRate", unit=FrequencyUnit.Per_min)]
    unit = {"mmHg": scalars.PressureUnit.mmHg, "cmH2O": scalars.PressureUnit.cmH2O, "mL": VolumeUnit.mL,
            "mL/min": VolumePerTimeUnit.mL_Per_min, "L/min": VolumePerTimeUnit.L_Per_min}
    state = json.loads(STATE.read_text())
    t = time.perf_counter()
    plan = add_points(state)
    edit_s = time.perf_counter() - t
    requests, reads = [], []
    for what, circuit, name, has_volume in plan:
        _, cat, p_u, v_u, f_u = POINT_CIRCUITS[circuit]
        make = getattr(SEDataRequest, f"create_{cat}_compartment_request")
        if what == "node":
            reads.append((what, circuit, name, "Pressure", p_u, len(requests)))
            requests.append(make(f"VivaPoint{name}", "Pressure", unit[p_u]))
            if has_volume:
                reads.append((what, circuit, name, "Volume", v_u, len(requests)))
                requests.append(make(f"VivaPoint{name}", "Volume", unit[v_u]))
        else:
            reads.append((what, circuit, name, "Flow", f_u, len(requests)))
            requests.append(make(f"VivaPointTgt{name}", "Inflow", unit[f_u]))
            requests.append(make(f"VivaPointTgt{name}", "Outflow", unit[f_u]))
    n_vitals = len(VITALS) + len(extra)
    t = time.perf_counter()
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    engine.log_to_console(False)
    assert engine.serialize_from_string(json.dumps(state), SEDataRequestManager(vitals_requests() + extra + requests),
                                        eSerializationFormat.JSON)
    engine.advance_time_s(0.0)
    load_s = time.perf_counter() - t
    worst, checks, now = {}, [], 0.0
    for t_s in (0.5, 1.37, 30.0):
        engine.advance_time_s(t_s - now)
        now = t_s
        values = engine.pull_data()[1 + n_vitals:]
        s = engine_state(engine)
        sn, sp = fluid(s, "FluidNode"), fluid(s, "FluidPath")
        nan = 0
        for what, circuit, name, prop, u, i in reads:
            got = values[i] - values[i + 1] if prop == "Flow" else values[i]
            if got != got:
                nan += 1
                continue
            item = (sn if what == "node" else sp)[name]
            if prop not in item:
                continue
            raw = next(iter(item[prop].values()))
            value = float(raw.get("Value", 0.0))  # proto3 JSON writes an infinite double as "Infinity"
            key = (circuit, what, prop)
            if value in (float("inf"), float("-inf")):
                err = 0.0 if got == value else float("inf")
            else:
                expected = PyPulse.convert(value, raw["Unit"], u)
                err = abs(got - expected) / max(1.0, abs(expected))
            worst[key] = max(worst.get(key, 0.0), err)
        checks.append({"t": t_s, "nan_reads": nan})
    plain = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    plain.log_to_console(False)
    plain.serialize_from_file(str(STATE), SEDataRequestManager(vitals_requests() + extra))
    plain.advance_time_s(0.0)
    plain.advance_time_s(30.0)
    a, b = engine.pull_data()[1:1 + n_vitals], plain.pull_data()[1:1 + n_vitals]
    no_volume = add_virtual(json.loads(STATE.read_text()), ["LeftHeart2"])
    e2 = from_json(no_volume, [SEDataRequest.create_liquid_compartment_request("VLeftHeart2", "Volume", VolumeUnit.mL)])
    return {"compartments_added": sum(2 if w == "path" else 1 for w, *_ in plan),
            "reads": {c: {"nodes": sum(1 for w, cc, *_ in plan if cc == c and w == "node"),
                          "node_volumes": sum(1 for w, cc, _, v in plan if cc == c and w == "node" and v),
                          "paths": sum(1 for w, cc, *_ in plan if cc == c and w == "path")} for c in POINT_CIRCUITS},
            "requests": len(requests), "state_edit_s": round(edit_s, 3), "load_s": round(load_s, 3),
            "max_rel_err": {" ".join(k): v for k, v in sorted(worst.items())}, "checks": checks,
            "vitals_bit_identical_30s": list(a) == list(b),
            "vitals_30s": {"with_points": [float(x) for x in a], "unedited": [float(x) for x in b]},
            "pull_data_ms": median_ms(lambda: engine.pull_data(), 51),
            "advance_0.02s_ms_with_points": median_ms(lambda: engine.advance_time_s(0.02), 51),
            "advance_0.02s_ms_unedited": median_ms(lambda: plain.advance_time_s(0.02), 51),
            "volume_request_on_node_without_volume": float(e2.pull_data()[1])}


def edit(path="Aorta1ToBone1", factor=5.0):
    base = json.loads(STATE.read_text())
    out = {"path": path, "factor": factor}
    for label, keys in [("unedited", []), ("resistance_only", ["Resistance", "NextResistance"]),
                        ("with_baseline", ["Resistance", "NextResistance", "ResistanceBaseline"])]:
        state = copy.deepcopy(base)
        p = fluid(state, "FluidPath")[path]
        for k in keys:
            p[k]["ScalarPressureTimePerVolume"]["Value"] *= factor
        engine = from_json(state)
        engine.advance_time_s(1.0)
        r1 = scalar(fluid(engine_state(engine), "FluidPath")[path], "Resistance")
        out[label] = {"resistance_1s": round(r1, 3), "at_30s": trace(engine, path, 30.0)}
    return out


def initialized(modifiers=None):
    """initialize_engine(StandardMale) with configuration Modifiers, through the binding (see below)."""
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    engine.log_to_console(False)
    if modifiers:
        # The Python PulseConfiguration has no Modifiers field, so the JSON goes straight to the
        # binding's set_configuration_override, the call PulseEngine.set_configuration_override makes.
        cfg = json.dumps({"Modifiers": {k: {"Value": v} for k, v in modifiers.items()}})
        if not engine._PulseEngine__pulse.set_configuration_override(cfg, PyPulse.serialization_format.json):
            return None, "override rejected"
    config = SEPatientConfiguration()
    config.set_data_root_dir(f"{BIN}/")
    config.set_patient_file(str(PATIENT))
    ok = engine.initialize_engine(config, SEDataRequestManager(vitals_requests()))
    return (engine if ok else None), ok


def modifier(path="Aorta1ToBone1", factor=5.0):
    # PulseConfiguration::Merge replaces the Modifiers map wholesale, so a correct override starts
    # from Pulse's defaults, which every shipped state records in Configuration.Modifiers.
    defaults = {k: v.get("Value", 0.0) for k, v in json.loads(STATE.read_text())["Configuration"]["Modifiers"].items()}
    scaled = {**defaults, path: defaults.get(path, 1.0) * factor}
    out = {"path": path, "factor": factor, "default_modifiers": len(defaults), "default_for_path": defaults.get(path)}
    for label, mods in [("unmodified", None), ("defaults_resent", defaults), ("modified", scaled),
                        ("modified_alone", {path: factor}), ("unknown_name", {**defaults, "NoSuchPath": factor})]:
        engine, ok = initialized(mods)
        if engine is None:
            out[label] = {"initialize_ok": ok}
            continue
        p = fluid(engine_state(engine), "FluidPath")[path]
        out[label] = {"initialize_ok": ok, "resistance_baseline": round(scalar(p, "ResistanceBaseline"), 3),
                      "at_0s": read_vitals(engine), "at_30s": trace(engine, path, 30.0)}
    return out


def add(name="VivaProbeShunt", source="Aorta1", target="VenaCava1", resistance=0.5):
    state = json.loads(STATE.read_text())
    value = {"ScalarPressureTimePerVolume": {"Value": resistance, "Unit": "mmHg s/mL"}}
    state["CircuitManager"]["FluidPath"].append(
        {"CircuitPath": {"Name": name, "SourceNode": source, "TargetNode": target},
         "Resistance": value, "NextResistance": value, "ResistanceBaseline": value})
    circuits = []
    for c in state["CircuitManager"]["FluidCircuit"]:
        if {source, target} <= set(c["Circuit"].get("Node", [])):
            c["Circuit"]["Path"].append(name)
            circuits.append(c["Circuit"]["Name"])
    engine = from_json(state)
    at_30s = trace(engine, name, 30.0)
    links = sum(l["FluidLink"]["Link"].get("Path") == name
                for l in engine_state(engine)["CompartmentManager"]["LiquidLink"])
    return {"path": name, "circuits": circuits, "at_30s": at_30s, "compartment_links": links,
            "unedited_at_30s": trace(from_json(json.loads(STATE.read_text())), name, 30.0)}


def remove_child(path, scope):
    state = json.loads(STATE.read_text())
    cm, comp = state["CircuitManager"], state["CompartmentManager"]
    cm["FluidPath"] = [p for p in cm["FluidPath"] if p["CircuitPath"]["Name"] != path]
    for c in cm["FluidCircuit"]:
        if path in c["Circuit"].get("Path", []):
            c["Circuit"]["Path"].remove(path)
    if scope == "with_link":
        links = {l["FluidLink"]["Link"]["Name"] for l in comp["LiquidLink"] if l["FluidLink"]["Link"].get("Path") == path}
        comp["LiquidLink"] = [l for l in comp["LiquidLink"] if l["FluidLink"]["Link"]["Name"] not in links]
        for g in comp["LiquidGraph"]:
            graph = g["FluidGraph"]["Graph"]
            graph["Link"] = [l for l in graph.get("Link", []) if l not in links]
        print("removed links", sorted(links), flush=True)
    print("loading", flush=True)
    engine = from_json(state, log=True)
    print("loaded", flush=True)
    engine.advance_time_s(0.02)
    print("advanced", read_vitals(engine), flush=True)


def remove(path="Aorta1ToBone1"):
    out = {"path": path}
    for scope in ("path_only", "with_link"):
        child = subprocess.run([sys.executable, __file__, "remove-child", path, scope], capture_output=True, text=True)
        lines = child.stdout.splitlines() + child.stderr.splitlines()
        out[scope] = {"child_exit": child.returncode,
                      "progress": [l for l in lines if l.startswith(("removed", "loading", "loaded", "advanced"))],
                      "errors": [l.strip()[:160] for l in lines if "[ERROR]" in l or "[FATAL]" in l][:3]}
    return out


def patient():
    spec = json.loads(PATIENT.read_text())
    spec["Name"] = "VivaProbePatient"
    spec["Age"]["ScalarTime"]["Value"] = 30.0
    spec["Weight"]["ScalarMass"]["Value"] = 190.0
    spec["HeartRateBaseline"]["ScalarFrequency"]["Value"] = 64.0
    with tempfile.TemporaryDirectory() as tmp:
        patient_file = Path(tmp) / "VivaProbePatient.json"
        patient_file.write_text(json.dumps(spec))
        t = time.perf_counter()
        _load_engine("", "HumanAdultWholeBody", STATE.name, vitals_requests())
        shipped_s = time.perf_counter() - t
        config = SEPatientConfiguration()
        config.set_data_root_dir(f"{BIN}/")
        config.set_patient_file(str(patient_file))
        engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
        engine.log_to_console(False)
        t = time.perf_counter()
        ok = engine.initialize_engine(config, SEDataRequestManager(vitals_requests()))
        init_s = time.perf_counter() - t
        saved = Path(tmp) / "VivaProbePatient@0s.json"
        t = time.perf_counter()
        saved_ok = engine.serialize_to_file(str(saved))
        save_s = time.perf_counter() - t
        t = time.perf_counter()
        reloaded = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
        reloaded.log_to_console(False)
        reload_ok = reloaded.serialize_from_file(str(saved), SEDataRequestManager(vitals_requests()))
        reloaded.advance_time_s(0.0)
        reload_s = time.perf_counter() - t
        engine.advance_time_s(60.0)
        reloaded.advance_time_s(60.0)
        cold, warm = engine.pull_data()[1:], reloaded.pull_data()[1:]
        return {"shipped_load_s": round(shipped_s, 3), "initialize_ok": ok, "initialize_s": round(init_s, 1),
                "save_ok": saved_ok, "save_s": round(save_s, 3), "reload_ok": reload_ok, "reload_s": round(reload_s, 3),
                "cold_60s": read_vitals(engine), "reloaded_60s": read_vitals(reloaded),
                "max_rel_diff_60s": max(abs(a - b) / abs(a) for a, b in zip(cold, warm))}


def hemo_child():
    # PulseEngine has no Hemodynamics mapping and the pybind enum has no member for it,
    # so the engine is built through the binding with an int cast (upstream draft Pulse #2).
    engine = PulseEngine(eModelType.HumanAdultWholeBody, f"{BIN}/")
    engine.log_to_console(False)
    engine._PulseEngine__pulse = PyPulse.Engine(PyPulse.model_type(2), f"{BIN}/")
    config = SEPatientConfiguration()
    config.set_data_root_dir(f"{BIN}/")
    config.set_patient_file(str(PATIENT))
    print("initialized", engine.initialize_engine(config, SEDataRequestManager(vitals_requests()[:1])), flush=True)
    engine.advance_time_s(0.02)
    print("advanced", flush=True)


def hemo():
    child = subprocess.run([sys.executable, __file__, "hemo-child"], capture_output=True, text=True)
    lines = [l for l in child.stdout.splitlines() if l.startswith(("initialized", "advanced"))]
    return {"pybind_model_types": list(PyPulse.model_type.__members__), "child_exit": child.returncode,
            "child_progress": lines}


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "hemo-child":
        hemo_child()
    elif mode == "remove-child":
        remove_child(sys.argv[2], sys.argv[3])
    else:
        modes = {"reads": reads, "virtual": virtual, "points": points, "edit": edit, "modifier": modifier, "add": add,
                 "remove": remove, "patient": patient, "hemo": hemo}
        print(json.dumps({"probe": mode, **modes[mode]()}, default=float))
