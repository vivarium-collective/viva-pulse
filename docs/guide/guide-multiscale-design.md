# Multiscale design: Pulse on top, cells underneath

One design. Pulse simulates the whole body. Underneath it, an organ is split into small pieces of tissue, and each piece holds a model of one cell. Pulse's blood values drive the cells every second. The cells report what they do, and nothing flows back up to Pulse yet.

Four dials set how far the design goes. Each dial has a current setting, and a further setting can only be reached once its gate is passed.

```
Pulse whole body  →  organ tissue (strata)  →  cells          nothing flows back (yet)

DIAL 1  Coverage       [liver]  →  more organs                    gate: map Pulse compartments to organs
DIAL 2  Cell content    1 simulator  →  [2 of 3 built: kinetic + thermo]  →  + spatial (NEXT)  →  many cells as agents
DIAL 3  Direction      [one-way]  →  feedback into Pulse         gate: a modeler-approved sink ledger
DIAL 4  Execution      [live, replay]  →  surrogate              gate: runs too slow (they aren't)
```

## The layers

**Pulse.** Every second, it sends what the liver's blood carries: insulin, glucose and lactate. It also sends the liver's tissue mass and the body's core temperature.

**Organ tissue.** The liver is split into equal slices (strata) along its blood vessel, from inlet to outlet. A configured fraction of the insulin, `extraction`, is used up along the way, and the average across slices always equals Pulse's value. The default extraction is 0 (every slice equal), because Pulse's own liver removes no insulin: Pulse clears insulin at the vena cava. Glucose and lactate are the same in every slice.

**Cells.** Each slice holds one cell, built from the simulators switched on:

```
Pulse liver blood: insulin, glucose, lactate, temperature
   │
   ├─► receptor model (always)          insulin → receptor states            Koschorreck 2008, COPASI
   ├─► glucose metabolism (metabolism)  insulin + glucose + lactate → metabolites, fluxes, glucose output
   │                                                                          König 2012, COPASI
   └─► thermodynamics (thermo)          metabolites → ΔG' of 27 reactions, and where a reaction
                                        runs against thermodynamics          eQuilibrator
   next:  spatial (viva-pde-particle)   insulin diffusing to receptors on the cell surface
```

## What is built

| Setting | Code | Tests |
|---|---|---|
| Pulse liver reads | `viva_pulse/circuits/hepatic.py`, generator `pulse_hepatic` | `tests/test_hepatic.py` |
| Liver strata, receptor model per slice, started at steady state | `viva_pulse/multiscale/`, generator `pulse_liver_tissue` | `tests/test_tissue_block.py` |
| Glucose metabolism per slice (`metabolism=True`) | `cells.py`, `models.py` | same |
| Thermodynamics of the metabolism (`thermo=True`) | `thermo.py` | same |
| Replay: the same cells driven by a recorded Pulse run | generator `liver_tissue_replay` | same |
| Totals across slices: mean, spread, molecules per cell, liver amounts | `TissueAggregate` | same |

The cells never change Pulse; a test checks that Pulse's readings are identical with and without them.

## What the thermodynamics found

König's model, as published, runs six reactions against thermodynamics at Pulse's liver values, whatever cell conditions are assumed. Its own equilibrium constants explain most of it: one is copied from another reaction, one is reversed, and two look like mM/M slips.

A corrected set of three constants (`metabolism_parameters: "provisional_corrections"`, per subpopulation) clears the worst conflicts, but then the liver stops making glucose: the published calibration leans on the faulty values. Both run side by side; the published model is the default. A modeler should decide. Details: [cell-content-probes](../plan/cell-content-probes/README.md).

## Next: the spatial simulator

viva-pde-particle couples an insulin field to receptor particles. It needs Jim Schaff's Smoldyn fork, built from source in a gitignored folder inside this repo, and a one-cell proof before it joins. Receptor binding then moves from the receptor model to the spatial one, provided the total number of receptors stays conserved between the two.

## Provisional biology (a modeler should confirm)

- **The receptor model doesn't feed metabolism.** Metabolism responds to the insulin level through its own fitted curve.
- **The cell's conditions are assumed:** pH 7.2, pMg 3, ionic strength 0.25 M. Pulse reports pH only in blood and has no magnesium.
- **Glucagon comes from the metabolism model's own glucose curve,** because Pulse has no glucagon.
- **The receptor model describes rat hepatocytes;** the metabolism model describes human ones.

## Rules

- **One writer per quantity.** Two simulators never both compute the same thing.
- **One-way until Dial 3 moves.** Cell activity is a readout. It doesn't remove anything from Pulse's blood.
- **Units are stated and checked at every boundary.** Pulse reports insulin in pmol/L; the receptor model uses nM and seconds, the metabolism model mM and seconds, and eQuilibrator M.
- **Every simulator is the real tool, never a mock.** The tests compare against independent runs.

Evidence, probes and history: [plan-multicell-composition.md](../plan/plan-multicell-composition.md).
