# Liver probes (2026-11-03)

Real-engine probes behind the liver tissue block. Run from the repo root, so
`viva_pulse` resolves to this checkout:

```bash
PULSE_INSTALL_DIR=<repo>/.pulse-build/install PYTHONPATH=$PWD uv run --no-sync python docs/plan/liver-probes/<script>.py
```

| Script | What it showed |
|---|---|
| `probe_liver.py` | Pulse's liver compartments are `<Organ>Vasculature` / `LiverTissue*`; liver tissue insulin stays at its initial value; liver mass 1.8 kg |
| `probe_inlet.py` | a flow-weighted liver inlet from *instantaneous* compartment flows jumps 0.96-1.60 x the liver value tick to tick |
| `probe_pathavg.py` | true liver-inlet path flows at Pulse's 0.02 s step: hepatic artery 393, splanchnic 51.9 mL/min; inlet only ~2.7% above the liver value |
| `probe_copasi.py` | Koschorreck receptor states need 30-60 min to settle at 0.16 nM insulin; 0.38 ms per COPASI update |
| `probe_ss.py` | COPASI's steady state equals a 2 h time course (status 2, equilibrium) |
