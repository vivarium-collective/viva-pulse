# Multiscale design: Pulse on top, cells underneath

One design. Pulse simulates the whole body. Under it, the liver is divided into zones along the path blood takes through it, and each zone holds models of liver cells. Every second, Pulse's liver blood values drive the cells, and the cells report what they do. Nothing flows back to Pulse yet.

Four dials set how far the design goes. Each shows its current setting in brackets; a further setting is reached only once its gate is passed.

```
Pulse whole body  →  liver zones (strata)  →  cell models          nothing flows back (yet)

DIAL 1  Coverage       [liver]  →  more organs              gate: map Pulse compartments to organs
DIAL 2  Cell content   1 simulator  →  [kinetic + thermo]  →  + spatial (probe S3 next)  →  many cells as agents
DIAL 3  Direction      [one-way]  →  feedback into Pulse    gate: a modeler-approved account of what cells remove
DIAL 4  Execution      [live, replay]  →  surrogate         gate: runs too slow (they aren't)
```

## The layers

**Pulse.** Pulse holds the liver's blood as one well-mixed pool. Every second it reports that pool's insulin, glucose, lactate and epinephrine, the liver's tissue mass, and the body's core temperature.

**Liver zones (strata).** Blood crosses the liver along sinusoids, from the portal inlet (periportal) to the central vein (pericentral). The block divides that path into equal-volume zones, inlet first, and takes Pulse's single value as the average along it. Insulin can fall in a straight line from inlet to outlet: the outlet has lost the fraction `extraction` of what entered, and the zone average still equals Pulse's value. The default is 0 (every zone equal), because Pulse's liver removes no insulin: Pulse clears insulin at the vena cava. Real livers take up roughly half the insulin that reaches them (literature figure, citation pending), so a non-zero `extraction` is closer to physiology, but it is a number set by hand. Glucose, lactate and epinephrine are the same in every zone.

**Cell models.** Each zone runs one model instance per cell subpopulation (by default one, `hepatocyte`). The models are deterministic ODEs, so one instance stands for every cell of its kind in that zone. A subpopulation has its own parameter values and a weight, its share of the cells. Each instance starts at the steady state for its first inputs (solved by COPASI), not at the model file's values, because some pools, such as glycogen, take hours to settle. The simulators that can be switched on:

```
Pulse's liver blood: insulin, glucose, lactate, epinephrine; core temperature
   │
   ├─► receptor model (always)           insulin → receptor binding, phosphorylation, internalization
   │                                      Koschorreck & Gilles 2008 (rat), in COPASI
   ├─► glucose metabolism                 insulin, epinephrine, glucose, lactate → metabolite levels, reaction rates
   │   (metabolism=True)                  König, Bulik & Holzhütter 2012 (human), in COPASI
   └─► thermodynamics (thermo=True)      metabolite levels, temperature → ΔG' of 27 reactions, and which run uphill
                                          eQuilibrator
```

**Totals.** Every readout is also summarized across the liver: the weighted mean, SD, minimum and maximum over all instances. For the receptor model there are also molecules per cell and whole-liver amounts, from Pulse's liver mass and the cell size and cell share in the receptor model's paper.

## What is built

| Setting | Code | Tests |
|---|---|---|
| Pulse liver reads | `viva_pulse/circuits/hepatic.py`, generator `pulse_hepatic` | `tests/test_hepatic.py` |
| Liver zones with a receptor model per instance, started at steady state | `viva_pulse/multiscale/`, generator `pulse_liver_tissue` | `tests/test_tissue_block.py` |
| Subpopulations with their own parameters and weights | `subpopulations` parameter | same |
| Glucose metabolism per instance (`metabolism=True`) | `cells.py`, `models.py` | same |
| Thermodynamics of the metabolism (`thermo=True`) | `thermo.py` | same |
| Replay: the same cells driven by a recorded Pulse run, without the engine | generator `liver_tissue_replay` | same |
| Totals across the liver | `TissueAggregate` | same |

The cells never change Pulse: a test runs Pulse with every cell simulator on and with none, and its readings match.

## What the thermodynamics found

ΔG' is a reaction's Gibbs energy change at the cell's actual concentrations. A net flux can only run in the direction that makes ΔG' negative. A reaction runs uphill when its flux goes the other way. The thermodynamics layer flags it when it runs uphill and ΔG' is more than twice the uncertainty of eQuilibrator's estimate, so the result isn't within error. It scores 27 of the model's 36 reactions. The other 9 move metabolites between compartments, build or break down glycogen (a polymer, which eQuilibrator can't score), or exchange with the model's boundary.

At Pulse's liver values, König's model as published runs six reactions uphill: aldolase, triose-phosphate isomerase, phosphoglycerate kinase, enolase, mitochondrial PEP carboxykinase and lactate dehydrogenase. Five do so in all 18 cell conditions tried (pH 7.0–7.4, pMg 2–4, ionic strength 0.15–0.25 M); triose-phosphate isomerase does in 15. The model's own equilibrium constants look like the cause:

- enolase's constant equals triose-phosphate isomerase's to every digit, so it looks copied;
- lactate dehydrogenase's matches the reverse direction;
- aldolase's and PEP carboxykinase's look like mM/M unit slips.

These are hypotheses for a modeler, not established facts.

A provisional set of three corrected constants (enolase, lactate dehydrogenase, aldolase) clears the robust conflicts; it is selected per subpopulation with `metabolism_parameters: "provisional_corrections"`. With it, though, the liver stops producing glucose: the published calibration appears to lean on the inconsistent values, so consistent thermodynamics would need a refit. Both sets run side by side, and the published model is the default. Details: [cell-content-probes](../plan/cell-content-probes/README.md).

## Where a spatial model would matter

A spatial model changes the answer only where cells take a substance up about as fast as it arrives. The ratio of uptake to delivery is the Damköhler number. Well below 1, concentrations stay even and a well-mixed model is enough. Near 1 or above, gradients form.

**At the cell surface it doesn't matter (probe S2).** viva-pde-particle (Jim Schaff's) couples a diffusing insulin field to receptor particles in Smoldyn. Its Smoldyn fork is compiled in a gitignored folder of this repo. On a hepatocyte-sized patch of the space of Disse, at Pulse's insulin level, the Damköhler number is about 0.09. Binding is limited by the receptors, not by delivery, and the spatial model reproduces the well-mixed receptor model: at most about 10% behind early on, the same by 60 minutes. Details: [spatial-probes](../plan/spatial-probes/README.md).

**Along the sinusoid it should matter.** Blood passes the cells in seconds while they take insulin up. A liver that removes half its insulin in one pass has a Damköhler number near 0.7 (ln 2, for first-order uptake). That gradient is what `extraction` sets by hand today. Computing it needs flow (advection), which viva-pde-particle doesn't model and spatial-transport's `DynamicAdvection` does. Scoped in [plan-spatial-delivery](../plan/plan-spatial-delivery.md).

## Next: probe S3 (approved, not yet run)

The probe models the zones as a chain of compartments along one sinusoid. `DynamicAdvection` carries insulin along it, fed at the inlet with Pulse's liver insulin times flow. Checks:

1. With no uptake, every zone equals the inlet (mass is conserved).
2. With first-order uptake at rate k, the profile matches the exact solution c(x) = c_in · exp(−k x / v), where v is the blood velocity. The hand-set profile is a straight line; uptake in flowing blood bends it into this exponential.
3. Whether the receptor model's own insulin uptake comes anywhere near the physiological ~50%.
4. What it costs, and whether spatial-transport runs on this repo's process-bigraph.

If the probe holds, a computed gradient becomes an option next to the hand-set `extraction`. What removes insulin in the liver, and the sinusoid's length, width and blood speed, are a modeler's choices.

## Provisional biology (a modeler should confirm)

- **The insulin gradient across zones is set by hand** (a straight line, `extraction`, default 0), and Pulse's single liver value is taken as its average.
- **The receptor model doesn't feed the metabolism model.** Metabolism responds to insulin through its own fitted curve.
- **Glucagon comes from the metabolism model's own glucose curve,** because Pulse has no glucagon. Insulin and epinephrine come from Pulse.
- **The cell's conditions are assumed:** pH 7.2, pMg 3, ionic strength 0.25 M. Pulse reports pH only in blood and has no magnesium.
- **Each model runs only inside the range it was built for, and stops instead of guessing outside it:**
  - metabolism: glucose 2–14 mM, with insulin and epinephrine within its hormone curves;
  - receptors: insulin up to 100 nM.
- **Mixed species:** the receptor model, and the cell size behind the liver totals, describe rat; the metabolism model describes human.

## Rules

- **One writer per quantity.** Two simulators never compute the same thing.
- **One-way until Dial 3 moves.** Cell activity is a readout. It doesn't remove anything from Pulse's blood.
- **Units are explicit at every boundary.** Pulse reports insulin in pmol/L. The receptor model uses nM and seconds, the metabolism model mM and seconds, and eQuilibrator M.
- **Every simulator is the real tool, never a mock.** Tests compare each one against an independent direct run.

Evidence and history: [plan-multicell-composition.md](../plan/plan-multicell-composition.md).
