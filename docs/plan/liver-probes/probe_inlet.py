"""Is a flow-weighted liver inlet concentration usable at 1 s sampling? Real engine, 120 s."""
import statistics as st
from viva_pulse.runtime import ensure_pulse_importable
bin_dir = ensure_pulse_importable()
from pulse.cdm import scalars as s
from pulse.cdm.engine import SEDataRequest as R, SEDataRequestManager
from pulse.engine.PulseEngine import PulseEngine, eModelType
ugL, mLmin = s.MassPerVolumeUnit.ug_Per_L, s.VolumePerTimeUnit.mL_Per_min
src = ["LargeIntestineVasculature", "SmallIntestineVasculature", "SplanchnicVasculature", "SpleenVasculature"]
reqs = [R.create_liquid_compartment_substance_request("LiverVasculature", "Insulin", "Concentration", unit=ugL),
        R.create_liquid_compartment_request("LiverVasculature", "Inflow", unit=mLmin),
        R.create_liquid_compartment_substance_request("Aorta", "Insulin", "Concentration", unit=ugL)]
for c in src:
    reqs += [R.create_liquid_compartment_substance_request(c, "Insulin", "Concentration", unit=ugL),
             R.create_liquid_compartment_request(c, "Outflow", unit=mLmin)]
reqs.append(R.create_physiology_request("CardiacOutput", unit=s.VolumePerTimeUnit.L_Per_min))
e = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/"); e.log_to_console(False)
assert e.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"), SEDataRequestManager(reqs))
e.advance_time_s(0.0)
ratios, qfrac, cmean = [], [], []
for t in range(121):
    if t: e.advance_time_s(1.0)
    d = e.pull_data()[1:]
    c_liver, q_in, c_ao = d[0], d[1], d[2]
    portal = [(d[3 + 2*i], d[4 + 2*i]) for i in range(4)]
    q_portal = sum(q for _, q in portal)
    q_ha = q_in - q_portal
    c_in = (sum(c*q for c, q in portal) + c_ao*q_ha) / q_in
    ratios.append(c_in / c_liver); qfrac.append(portal[2][1] / q_in); cmean.append(c_liver)
    if t % 20 == 0:
        print(f"t={t:3d} c_liver={c_liver:.4f} q_in={q_in:7.1f} q_ha={q_ha:7.1f} c_in={c_in:.4f} inlet/mean={c_in/c_liver:.4f} CO={d[-1]:.3f}")
def summ(name, xs): print(f"{name}: mean={st.mean(xs):.4f} sd={st.pstdev(xs):.4f} min={min(xs):.4f} max={max(xs):.4f}")
summ("inlet/mean", ratios); summ("Q_splanchnic/Q_liver", qfrac); summ("c_liver", cmean)
