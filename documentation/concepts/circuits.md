# Circuits

`PulseCircuitProcess` exposes Pulse's circuits through **circuit modules**, defined in
`viva_pulse.circuits`. A module computes nothing. It names the Pulse values that become its
output ports and the Pulse actions its setpoints drive.

| Module | Engines | Readings | Setpoints |
|---|---|---|---|
| `cardiovascular` | whole_body | 20 hemodynamic values; pressure, volume, inflow and outflow for 32 regions under `central/`, `renal/`, `peripheral/` | 10 resistance and compliance multipliers; a hemorrhage |
| `respiratory` | both | 24 breathing-mechanics values; lung and pleural regions | 10 resistance and compliance multipliers; intubation |
| `mechanical_ventilator` | both | 18 ventilator monitor values | one pressure-control group, including `connected` |
| `thermal` | whole_body | energy, heat loss, the environment as applied, thermal regions | the environment; active heating, cooling or an applied temperature |
| `supplemental_oxygen` | whole_body | inspired oxygen fraction, SpO2, PaO2, PaCO2 | `oxygen_connected`, `oxygen_flow_L_per_min` |
| `cardiovascular_points` | whole_body | pressure (and volume, where held) for each of the 124 nodes of the cardiovascular drawing, signed flow for each of its 212 paths | none |
| `respiratory_points` | whole_body | the same for the 24 nodes and 34 paths of the respiratory drawing | none |

Every module's setpoints are applied as Pulse actions. Multipliers are always sent as an
incremental change of the whole group, because a non-incremental change makes Pulse
re-stabilize and reset its baselines.

## The cardiovascular circuit

The `central`, `renal` and `peripheral` stores follow the diagram's branches.

```{image} ../../docs/images/circuit-cardio.png
:alt: Pulse cardiovascular circuit
```

*Pulse cardiovascular circuit. Copyright Kitware, Inc. and Contributors, Apache License 2.0,
from `engine/docs/Images/Cardiovascular/CardiovascularCircuit.png`.*

Region readings are instantaneous within each heartbeat. The default one-second sampling
aliases the cardiac cycle; use `interval=0.02` (Pulse's timestep) to resolve waveforms, as
{doc}`../tutorials/02-cardiovascular-circuit` does.

## Points: single nodes and paths

The region modules read compartments, which group several circuit nodes (the aorta region is
nodes `Aorta1` to `Aorta4`). The `*_points` modules read the drawing itself: every node, such
as `LeftHeart1`, and every path between two nodes, such as `Aorta1ToBone1`.

| Module | Pulse circuit | Node ports | Path ports |
|---|---|---|---|
| `cardiovascular_points` | `FullCardiovascular` (with the renal and tissue branches) | `nodes/<node>/pressure_mmHg`, `nodes/<node>/volume_mL` | `paths/<path>/flow_mL_per_min` |
| `respiratory_points` | `Respiratory` (the airway) | `nodes/<node>/absolute_pressure_cmH2O`, `nodes/<node>/volume_mL` | `paths/<path>/flow_L_per_min` |

- **Selecting points.** By default, every node and path of the circuit is read. The config
  lists `cardiovascular_point_nodes` and `cardiovascular_point_paths` (and the `respiratory_`
  pair) narrow the selection to the names given. Names are Pulse's own, taken from the loaded
  state. An unknown or repeated name raises an error.
- **Volume** is read only where Pulse holds a finite one. Non-compliant nodes such as
  `LeftHeart2` have no volume, and the `Ambient` reservoir's volume is infinite.
- **Flow is signed.** It is positive in the path's drawn direction (source node to target node)
  and negative against it, for example in the airway during exhalation.
- **The circuit as loaded.** Paths that Pulse adds during a run, such as a hemorrhage's bleed
  path, aren't included. Every shipped state has the same circuits (124 and 24 nodes).
- **Airway devices.** When the engine can connect one (a ventilator or supplemental oxygen
  module on the same process), the airway openings `EnvironmentToMouth` and
  `EnvironmentToNasalCavity` aren't read. While a device is connected, Pulse replaces them with
  the device's own connection and stops solving them, so they would hold their last flow. Naming
  one of them then raises an error.
- **Construction reads the state file.** A process with a point module parses `state_file` when
  it is built, so it needs the Pulse install from that point on.
- **Engine.** Points need `model_type: whole_body`, because they work by editing the state file
  before it loads.
- **In a composite.** Set `point_reads=True` on `pulse_cardiovascular`, `pulse_respiratory` or
  `pulse_mechanical_ventilation` (both with `model_type="whole_body"`), or on
  `pulse_whole_body_circuits`. This reads every point, under `circuits/<circuit>_points/`.

Pulse has no data request for a node or path. A compartment, though, is a named group of
nodes, and a link is a named path. So before loading, the module adds, for every point:
- a single-node compartment for each node;
- a link for each path, between two compartments of its own.

Ordinary data requests then read them. A compartment whose only link is the path has
`Inflow - Outflow` equal to that path's flow. Pulse solves the same circuit either way: a run
reading every point is bit-identical to one without, and every reading matches Pulse's own
saved circuit values.

## The thermal circuit

```{image} ../../docs/images/circuit-environment.png
:alt: Pulse environment circuit
```

*Pulse environment circuit, the external half of the temperature circuit. Copyright Kitware,
Inc. and Contributors, Apache License 2.0, from
`engine/docs/Images/Environment/EnvironmentCircuit.png`.*

Skin responds within minutes; core temperature takes tens of minutes. Pulse's stabilized
states aren't thermally settled (skin drifts from 32.4 to 30.0 °C over 30 minutes with nothing
changed), so compare a thermal intervention against an unperturbed run.

## Rules that come from Pulse

- **One airway device at a time.** With the ventilator and supplemental oxygen both connected,
  every engine step fails, so the process raises an error instead. To switch devices,
  disconnect one in an update before connecting the other.
- **Intubation is one-way.** Pulse's Python API drops extubation, so setting `intubated` back
  to 0 raises an error rather than leaving the store and the engine disagreeing.
- **The ventilator in `AssistedControl` mode** can lock into auto-triggering at a rate above
  the patient's own. Use `ContinuousMandatoryVentilation` when the set rate must hold.
- **Supplemental oxygen comes from a wall supply.** A finite bottle would refill every time a
  setpoint change resends the action.
- **Hemodynamics, Pulse's cardiovascular-only engine, isn't supported**: it crashes on its
  first step. So the cardiovascular circuit runs inside the whole body only.
