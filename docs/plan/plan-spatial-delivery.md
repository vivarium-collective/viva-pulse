# Where delivery limits: scoping the spatial layer (2026-11-03)

Scoping only; no code. Part of the one design in [the guide](../guide/guide-multiscale-design.md) (Dial 2, cell content).

## Why this scoping exists

Probe S2 ([spatial-probes](spatial-probes/README.md)) put insulin delivery and receptor binding on one hepatocyte membrane patch. Binding there is limited by the reaction, not by delivery: the Damköhler number (uptake over delivery) is about 0.09. So a spatial model reproduces the well-mixed receptor model. A spatial layer earns its place only where the Damköhler number nears 1, that is, where cells take a solute up about as fast as it arrives.

The number is uptake rate × transit time for flow, or uptake demand over diffusive supply for diffusion. Small (≪ 1): uniform, well-mixed is fine. About 1 or more: gradients matter.

## Candidate questions

| Where | Solute | Damköhler | Fit |
|---|---|---|---|
| Membrane patch (S2) | insulin | 0.09 [V, measured] | No: well-mixed suffices |
| **Along the sinusoid, portal inlet to central outlet** | **insulin** | Physiological first-pass extraction ~0.5 [U, literature to cite] means a Damköhler near 0.7. In Pulse it is 0: Pulse's liver extracts none [V] | **Yes, if a modeler sets what removes insulin** |
| Along the sinusoid | oxygen | Periportal-to-pericentral O2 gradient (zonation) [U] | Plausible; no cell model consumes O2 yet |
| Along the sinusoid | glucose | Net hepatic extraction is a few % [U] | No: small |
| Intracellular, low copy number | signalling molecules | not a delivery question | Particles would matter for noise, not for delivery |

The sinusoid is the place. It is also what the strata already stand for: the configured `extraction` is a hand-set stand-in for this transport. Computing it would replace a provisional profile with mechanism.

## The physics a sinusoid model needs

- **Flow, not only diffusion.** Blood crosses the lobule in seconds, so the Péclet number (flow over diffusion) is in the hundreds [U]. Pulse gives the time scale: its liver vascular volume over its liver inflow is 540 mL / 22.5 mL/s, about 24 s for the whole liver's vasculature, including large vessels [V, Pulse readings].
- **A sink.** Pulse removes insulin only at the vena cava, so something in the tissue has to take it up. Options:
  - (a) Koschorreck receptor internalization and degradation, already in the cell model, but slow (~2e-4 /s) and calibrated in rat;
  - (b) a modeler-set clearance per stratum.
  Either way this is a modeling decision.
- **One writer, and the Pulse ledger.** Insulin taken up in the tissue would not leave Pulse's blood: the double-counting hazard. That's fine while it is a readout (Dial 3 stays one-way), but the output must say the tissue's extraction is not applied to Pulse. Feeding it back is the Dial 3 question.

## Tools (read at source)

- **spatial-transport `DynamicAdvection`** [V, `spatial_transport/processes/advection.py`]: upwind advection between compartments of a graph.
  - The per-edge velocity is an input, so Pulse's liver flow can drive it.
  - Mass moves as additive counts, so cells can subtract their uptake from the same store.
  - Boundaries are only "default" or "periodic": there is no inflow condition, so an inlet step must supply the first compartment, at Pulse's inlet concentration × flow.
  - Compatibility with process-bigraph 1.11 is [U]: the repo last changed 2026-07-30 and needs ≥ 1.5.
- **viva-pde-particle** [V]: diffusion and reactions in closed boxes, no flow. Right for membrane-scale questions, wrong for the sinusoid.
- **spatio-flux `DiffusionAdvection`** [A]: 2D fields with flow; a second option if a lobule cross-section is wanted.

## Proposed next probe (S3), if chosen

A chain of S compartments (the strata) along one sinusoid, run by `DynamicAdvection`:
- **Inlet supply:** Pulse's liver insulin × flow (velocity from Pulse's inflow and an assumed sinusoid cross-section).
- **Uptake per compartment:** option (a) or (b) above.

Checks:
1. With no uptake, every compartment equals the inlet (mass conserved).
2. With first-order uptake k, the profile matches the analytic exp(−k x / v).
3. The extraction this gives versus the physiological ~50%: does the receptor model's own uptake come anywhere close?
4. Install and compatibility of spatial-transport with process-bigraph 1.11, in `.venv`, additively.

If S3 holds, the configured `extraction` becomes an option next to a computed one.

## Decisions this needs

- **Engineering (yours):** whether to run S3, and whether to add spatial-transport to `.venv`.
- **Modeling (a modeler's):** what removes insulin in the liver (receptor-mediated degradation vs a set clearance), the sinusoid geometry (length, cross-section, velocity), and whether oxygen should be the next solute.
