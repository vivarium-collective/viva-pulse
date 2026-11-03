Composite generators
====================

Each generator is a ``@composite_generator``: call it with a core and keyword
parameters to get a composite document, or pick it from the workbench catalog by its
id (``viva_pulse.composites.<module>.<name>``). Their descriptions and parameter
tables come from the generator registry and are listed on :doc:`../concepts/composites`;
this page gives the call signatures.

.. automodule:: viva_pulse.composites.hemorrhage
   :members: pulse_hemorrhage, pulse_resuscitation
   :undoc-members:

.. automodule:: viva_pulse.composites.circuits
   :members: pulse_cardiovascular, pulse_respiratory, pulse_mechanical_ventilation, pulse_thermal, pulse_supplemental_oxygen, pulse_substances, pulse_hepatic, pulse_whole_body_circuits, circuit_node, circuit_emitter
   :undoc-members:

.. automodule:: viva_pulse.composites.tissue
   :members: pulse_liver_tissue, liver_tissue_replay
   :undoc-members:
