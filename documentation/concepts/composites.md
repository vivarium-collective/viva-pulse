---
file_format: mystnb
kernelspec:
  name: python3
  display_name: Python 3
---

# Composites

A composite generator is a function, registered with process-bigraph's
`@composite_generator`, that builds a runnable composite document from keyword parameters.
The workbench's catalog lists every registered generator by its id,
`viva_pulse.composites.<module>.<name>`.

Every composite has the same shape:

- `interventions/`: setpoint stores (what you set);
- `vitals/` or `circuits/<module>/`: Pulse's readings (what you read);
- `emitter`: a `RAMEmitter` step that records the readings every update.

Run one like this:

```python
from process_bigraph import Composite, gather_emitter_results

from viva_pulse.composites import pulse_hemorrhage
from viva_pulse.core import build_core

core = build_core()
sim = Composite({"state": pulse_hemorrhage(core, severity=0.5)}, core=core)
sim.run(60)                                        # 60 simulated seconds -> 61 rows
rows = gather_emitter_results(sim)[("emitter",)]
```

All of them use `fidelity="real-bridge"`: they drive the real engine.

## The catalog

The table below is generated, while these docs build, from the generator registry itself, so
it always matches the code.

```{code-cell} python
:tags: [remove-input]
from IPython.display import Markdown
from process_bigraph.composite_generator import _REGISTRY

import viva_pulse.composites  # registers the generators

def _cell(text):
    # Escape what Markdown would read as table syntax or an HTML tag (e.g. "<install>").
    return (str(text).replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")
            .replace("\n", " "))


entries = sorted((e for e in _REGISTRY.values() if e.id.startswith("viva_pulse.")),
                 key=lambda e: e.id)
rows = ["| Generator | What it runs | Default steps |", "|---|---|---|"]
for e in entries:
    rows.append(f"| `{e.name}` | {_cell(e.description)} | {e.default_n_steps} |")
Markdown("\n".join(rows))
```

## Parameters

Each generator's parameters, with their defaults, also straight from the registry.

```{code-cell} python
:tags: [remove-input]
sections = []
for e in entries:
    sections.append(f"**`{e.name}`**\n")
    sections.append("| Parameter | Type | Default | Meaning |\n|---|---|---|---|")
    for name, spec in e.parameters.items():
        sections.append(f"| `{name}` | {spec.get('type', '')} | `{spec.get('default')}` | "
                        f"{_cell(spec.get('description', ''))} |")
    sections.append("")
Markdown("\n".join(sections))
```

## Things to know

- **Whole-body runs** load one of Pulse's stabilized state files (`<install>/bin/states/*.json`,
  default `StandardMale@0s.json`). Pulse ships 21. Any other patient runs through
  `patient_file` instead, stabilized once and then cached (see
  [Any patient](processes.md#any-patient)).
- **Ventilation-mechanics runs** start from a patient file (`<install>/bin/patients/*.json`)
  and settle before t = 0, which takes about one breath.
- **Setpoints apply from the first update.** Row 0 always shows the engine as loaded or
  settled.
- **`pulse_whole_body_circuits`** takes every module's parameters at once. That works because
  setpoint and config names are unique across modules; a test enforces this.
