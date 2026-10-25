---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
  language: python
---

# Tutorial 1: a hemorrhage, untreated and resuscitated

```{include} _hosted.md
```

**What you will do:** bleed the StandardMale patient from the right leg for ten minutes, once
untreated and once with a closed-loop controller that infuses saline whenever mean arterial
pressure falls below 90 mmHg. Then compare the vital signs.

**What you need:** the installation from {doc}`../installation`. This tutorial runs about 40
seconds of real Pulse time.

**Words used here** (see {doc}`../glossary`): composite, setpoint, MAP.

## Build and run the two composites

`pulse_hemorrhage` wires one `PulseProcess` to an `interventions` store (the setpoints) and a
`vitals` store (the readings). `pulse_resuscitation` adds a `MapFluidController` step that
reads `vitals/mean_arterial_pressure_mmHg` and writes `interventions/iv_rate_mL_per_min`.

```{code-cell} python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_hemorrhage, pulse_resuscitation
from viva_pulse.core import build_core


def run(generator, seconds, **params):
    core = build_core()  # registers viva-pulse's processes on a fresh core
    sim = Composite({"state": generator(core, **params)}, core=core)
    sim.run(seconds)
    return gather_emitter_results(sim)[("emitter",)]


bleed = dict(compartment="RightLeg", severity=0.8)
untreated = run(pulse_hemorrhage, 600, **bleed)
treated = run(pulse_resuscitation, 600, target_map_mmHg=90.0, **bleed)
len(untreated), len(treated)
```

Each run emits one row per simulated second, plus the first row at t = 0.

## Compare the end of the two runs

```{code-cell} python
keys = ["mean_arterial_pressure_mmHg", "heart_rate_bpm", "blood_volume_mL",
        "total_hemorrhaged_volume_mL"]
print(f"{'':32s}{'start':>10s}{'untreated':>12s}{'treated':>10s}")
for key in keys:
    print(f"{key:32s}{untreated[0][key]:10.1f}{untreated[-1][key]:12.1f}{treated[-1][key]:10.1f}")
infused = sum(row["iv_rate_mL_per_min"] for row in treated[:-1]) / 60.0
first = next(row["time"] for row in treated if row["iv_rate_mL_per_min"] > 0)
print(f"\ncontroller first infuses at t = {first:.0f} s and delivers {infused:.1f} mL")
```

The bleed costs more than a quarter of the blood volume in ten minutes. Heart rate climbs as the
baroreflex compensates, and MAP holds near its start for several minutes before it falls. The
controller only starts infusing once MAP drops below its 90 mmHg target, late in the run, so
it ends with somewhat more blood volume and a higher MAP than the untreated run.

## Plot the vital signs over time

```{code-cell} python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 1, figsize=(7, 7), sharex=True)
panels = [("mean_arterial_pressure_mmHg", "MAP (mmHg)"),
          ("blood_volume_mL", "Blood volume (mL)"),
          ("iv_rate_mL_per_min", "Infusion (mL/min)")]
for ax, (key, label) in zip(axes, panels):
    for rows, name, color in ((untreated, "untreated", "#2a78d6"), (treated, "MAP-targeted saline", "#eb6834")):
        ax.plot([r["time"] / 60 for r in rows], [r[key] for r in rows], color=color, label=name, lw=2)
    ax.set_ylabel(label)
    ax.grid(color="#e1e0d9")
axes[0].legend(frameon=False)
axes[-1].set_xlabel("Time (min)")
fig.suptitle("Right-leg hemorrhage, severity 0.8, StandardMale")
fig.tight_layout()
```

## What to try next

- Change `severity`, or the bleed site (`compartment`, for example `"Aorta"`), and watch how
  quickly MAP falls. A severe aortic bleed reaches Pulse's irreversible state, after which the
  `irreversible_state` column turns `True` and the vitals stop changing.
- Raise `target_map_mmHg` or `gain` so the controller engages earlier, or set
  `compound="Blood"` to infuse whole blood.
- Run the same bleed in another patient with `state_file`, for example
  `"Underweight@0s.json"`. The {doc}`../results/pulse-hemorrhage` page does this for all 21.
  For a patient Pulse ships no state for, pass its patient file as `patient_file` instead
  (see [Any patient](../concepts/processes.md#any-patient)).
