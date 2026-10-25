Circuit modules
===============

The declarative registry ``PulseCircuitProcess`` builds its ports from. A module
computes nothing: it names Pulse data requests (outputs) and the Pulse actions its
setpoints drive (inputs).

.. automodule:: viva_pulse.circuits
   :members: MODULES

.. automodule:: viva_pulse.circuits.base
   :members: Request, ActionBinding, CircuitModule

.. automodule:: viva_pulse.circuits.cardiovascular

.. automodule:: viva_pulse.circuits.respiratory

.. automodule:: viva_pulse.circuits.thermal

.. automodule:: viva_pulse.circuits.supplemental_oxygen

.. automodule:: viva_pulse.circuits.points

.. automodule:: viva_pulse.circuits.additions
   :members: add_paths, check_additions, CIRCUIT, FIELDS
