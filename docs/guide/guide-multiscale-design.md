# Multiscale design: Pulse on top, cells underneath

One design. Pulse simulates the whole body. Underneath it, an organ is split into small pieces of tissue, and each piece holds a model of one cell. Pulse's blood values drive the cells every second. The cells report what they do, and nothing flows back up to Pulse yet.

Four dials set how far the design goes. Each dial has a current setting, and a further setting can only be reached once its gate is passed.

```
Pulse whole body  →  organ tissue (strata)  →  cells          nothing flows back (yet)

DIAL 1  Coverage       [liver]  →  more organs                    gate: map Pulse compartments to organs
DIAL 2  Cell content    1 simulator (built)  →  [3 simulators] NEXT  →  many cells as agents
DIAL 3  Direction      [one-way]  →  feedback into Pulse         gate: a modeler-approved sink ledger
DIAL 4  Execution      [live, replay]  →  surrogate              gate: runs too slow (they aren't)
```

## The layers

**Pulse.** It sends what the liver's blood carries, read from Pulse every second: insulin, and the liver's tissue mass.

**Organ tissue.** The liver is split into equal slices (strata) along its blood vessel, from inlet to outlet. A configured fraction of the insulin, `extraction`, is used up along the way. The average across slices always equals Pulse's value. The default extraction is 0 (every slice equal), because Pulse's own liver removes no insulin: Pulse clears insulin at the vena cava.

**Cells.** One cell model per slice.

## What is built

| Setting | Code | Tests |
|---|---|---|
| Pulse liver reads | `viva_pulse/circuits/hepatic.py`, generator `pulse_hepatic` | `tests/test_hepatic.py` |
| Liver strata, one cell model each (insulin receptor, Koschorreck 2008, in COPASI), started at steady state | `viva_pulse/multiscale/`, generator `pulse_liver_tissue` | `tests/test_tissue_block.py` |
| Replay: the same cells driven by a recorded Pulse run | generator `liver_tissue_replay` | same |
| Totals across slices: mean, spread, molecules per cell, whole-liver amounts | `TissueAggregate` | same |

The cells never change Pulse; a test checks that Pulse's readings are identical with and without them.

## Next: a cell made of three simulators

```
Pulse liver blood: insulin, glucose, lactate, temperature
   │
   ├─► receptor model (built)          insulin → receptor states
   ├─► liver glucose metabolism        insulin + glucose + lactate → metabolites, glucose output
   │      (König, COPASI)
   └─► thermodynamics (eQuilibrator)   metabolite levels → how far each reaction is from equilibrium
   later:  spatial (viva-pde-particle) insulin diffusing to receptors on the cell surface
```

- **Stage A:** metabolism plus thermodynamics, next to the receptor model.
- **Stage B:** the spatial simulator, once its engine (a Smoldyn fork) is built and proven on one cell. Receptor binding then moves from the receptor model to the spatial one.

Biology choices that are provisional (a modeler should confirm them):
- **The receptor model doesn't feed metabolism.** The metabolism model responds to the insulin level directly through a fitted curve; linking it to receptor signalling would need that curve refitted.
- **The cell's pH, magnesium and ionic strength are assumed:** pH 7.2, pMg 3, ionic strength 0.25 M. Pulse reports pH only in blood and has no magnesium.
- **Glucagon comes from the metabolism model's own glucose curve,** because Pulse has no glucagon.
- **The receptor model describes rat hepatocytes.**

## Rules

- **One writer per quantity.** Two simulators never both compute the same thing.
- **One-way until Dial 3 moves.** Cell activity is a readout. It doesn't remove anything from Pulse's blood.
- **Units are stated and checked at every boundary.** Pulse reports insulin in pmol/L; the receptor model works in nM and seconds.
- **Every simulator is the real tool, never a mock.** The tests compare against independent runs.

Evidence, probes and history: [plan-multicell-composition.md](../plan/plan-multicell-composition.md).
