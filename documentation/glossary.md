# Glossary

composite
: A process-bigraph simulation document: stores that hold values, and processes wired to
  them. Built here by a composite generator such as `pulse_hemorrhage`.

composite generator
: A Python function, registered with `@composite_generator`, that returns a composite
  document from keyword parameters. The workbench lists every registered generator in its
  catalog.

store
: A place in the composite that holds a value, such as `vitals/heart_rate_bpm`.

port
: A named input or output of a process. Wires connect ports to stores.

setpoint
: An input store that holds the value an intervention should have, such as
  `hemorrhage_severity`. viva-pulse sends it to Pulse as an action only when it changes.

circuit module
: A declarative description of one Pulse circuit family (cardiovascular, respiratory,
  mechanical ventilator, thermal, supplemental oxygen): which Pulse values become its
  outputs and which Pulse actions its setpoints drive.

region
: A Pulse compartment, such as the aorta or the left lung. viva-pulse reads pressure,
  volume and flow per region.

engine
: One running instance of Pulse. `whole_body` is the full adult model;
  `ventilation_mechanics` has the airway only, with no blood or reflexes.

state file
: A stabilized whole-body patient saved by Pulse (`<install>/bin/states/*@0s.json`). Loading
  one is instant. Pulse ships 21.

irreversible state
: Pulse's signal that the patient can't recover. viva-pulse stops advancing the engine after
  it, so the vital-sign stores keep their last reading.

study
: A workbench research unit: a baseline composite, variants of it, its runs and its pass
  criteria. An **investigation** groups studies under one question.

MAP
: Mean arterial pressure, in mmHg.
