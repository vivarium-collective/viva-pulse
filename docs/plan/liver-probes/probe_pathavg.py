"""True liver inlet from path flows sampled at Pulse's 0.02 s step; ripple left by 1 s window means."""
import statistics as st
from process_bigraph import Composite, gather_emitter_results
from viva_pulse.composites.circuits import circuit_emitter, circuit_node
from viva_pulse.core import build_core

PMAP = {"aorta": "Aorta1ToLiver1", "large_intestine": "LargeIntestine1ToPortalVein1",
        "small_intestine": "SmallIntestine1ToPortalVein1", "splanchnic": "Splanchnic1ToPortalVein1",
        "spleen": "Spleen1ToPortalVein1"}
core = build_core()
doc = {"pulse": circuit_node(["hepatic", "cardiovascular_points"], cardiovascular_point_nodes=["Liver1"],
                             cardiovascular_point_paths=list(PMAP.values()), interval=0.02),
       "interventions": {}, "circuits": {}, "emitter": circuit_emitter()}
sim = Composite({"state": doc}, core=core)
sim.run(60)
rows = gather_emitter_results(sim)[("emitter",)]
print("rows", len(rows), "last t", rows[-1]["time"])
paths = rows[1]["circuits"]["cardiovascular_points"]["paths"]
port = next(iter(paths["Aorta1ToLiver1"]))
def flows(r): return {s: r["circuits"]["cardiovascular_points"]["paths"][p][port] for s, p in PMAP.items()}
def conc(r): return {s: r["circuits"]["hepatic"]["sources"][s]["insulin_pmol_per_L"] for s in PMAP}
def inlet(rs):
    q = {s: st.mean(flows(r)[s] for r in rs) for s in PMAP}
    c = conc(rs[-1])
    return sum(c[s] * q[s] for s in PMAP) / sum(q.values()), q
step = rows[1:]
per_window = []
for k in range(60):
    w = step[k * 50:(k + 1) * 50]
    c_in, q = inlet(w)
    per_window.append(c_in / w[-1]["circuits"]["hepatic"]["liver"]["insulin_pmol_per_L"])
c_all, q_all = inlet(step)
print("60 s mean path flows mL/min", {s: round(v, 1) for s, v in q_all.items()}, "sum", round(sum(q_all.values()), 1))
print("liver AverageInflow (last)", round(step[-1]["circuits"]["hepatic"]["liver"]["average_inflow_mL_per_min"], 1))
print("1 s windows inlet/liver: mean %.4f sd %.4f min %.4f max %.4f" % (st.mean(per_window), st.pstdev(per_window), min(per_window), max(per_window)))
print("max tick-to-tick change %.4f" % max(abs(b - a) for a, b in zip(per_window, per_window[1:])))
