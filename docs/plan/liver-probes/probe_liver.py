"""Gate probe for Design 1: what Pulse serves about the liver (real engine, StandardMale)."""
import math
from viva_pulse.runtime import ensure_pulse_importable

bin_dir = ensure_pulse_importable()
from pulse.cdm import scalars as s
from pulse.cdm.engine import SEDataRequest as R, SEDataRequestManager
from pulse.engine.PulseEngine import PulseEngine, eModelType

ugL = s.MassPerVolumeUnit.ug_Per_L
mLmin = s.VolumePerTimeUnit.mL_Per_min
reqs = {}
for c in ("LiverVasculature", "LargeIntestineVasculature", "SmallIntestineVasculature", "SplanchnicVasculature", "SpleenVasculature", "Aorta", "VenaCava"):
    reqs[f"{c}/Insulin"] = R.create_liquid_compartment_substance_request(c, "Insulin", "Concentration", unit=ugL)
    reqs[f"{c}/Inflow"] = R.create_liquid_compartment_request(c, "Inflow", unit=mLmin)
    reqs[f"{c}/Outflow"] = R.create_liquid_compartment_request(c, "Outflow", unit=mLmin)
reqs["LiverVasculature/Volume"] = R.create_liquid_compartment_request("LiverVasculature", "Volume", unit=s.VolumeUnit.mL)
for c in ("LiverTissueExtracellular", "LiverTissueIntracellular"):
    reqs[f"{c}/Insulin"] = R.create_liquid_compartment_substance_request(c, "Insulin", "Concentration", unit=ugL)
    reqs[f"{c}/Volume"] = R.create_liquid_compartment_request(c, "Volume", unit=s.VolumeUnit.mL)
reqs["LiverTissue/TotalMass"] = R.create_tissue_request("LiverTissue", "TotalMass", unit=s.MassUnit.kg)
reqs["blood/Insulin"] = R.create_substance_request("Insulin", "BloodConcentration", unit=ugL)
reqs["blood/Glucose"] = R.create_substance_request("Glucose", "BloodConcentration", unit=s.MassPerVolumeUnit.mg_Per_dL)

names = list(reqs)
e = PulseEngine(eModelType.HumanAdultWholeBody, f"{bin_dir}/")
e.log_to_console(False)
assert e.serialize_from_file(str(bin_dir / "states" / "StandardMale@0s.json"), SEDataRequestManager(list(reqs.values())))
e.advance_time_s(0.0)
rows = [e.pull_data()]
for _ in range(3):
    e.advance_time_s(20.0)
    rows.append(e.pull_data())
for i, n in enumerate(names, start=1):
    vals = [r[i] for r in rows]
    print(f"{n:28s}", " ".join(f"{v:12.6g}" for v in vals), " NaN!" if any(math.isnan(v) for v in vals) else "")
