"""One cell-population instance: an SBML model in COPASI, driven every tick.

Needs the ``multiscale`` extra (viva-copasi). Imported only by
:func:`viva_pulse.multiscale.register_multiscale`, so viva-pulse itself stays
importable without COPASI.
"""

from __future__ import annotations

import locale

# Importing COPASI (python-copasi 4.48) sets the whole process locale to "C", and
# Python's default text encoding becomes ASCII for everything after it: any
# open()/read_text() without an encoding then fails on non-ASCII files. Restore the
# character-type category. COPASI's number parsing depends on LC_NUMERIC, which
# Python keeps at "C" anyway. Only the first import changes the locale.
_ctype = locale.setlocale(locale.LC_CTYPE)
from basico import get_parameters, run_steadystate, set_parameters, set_species  # noqa: E402
from viva_copasi.processes import CopasiUTCProcess  # noqa: E402

locale.setlocale(locale.LC_CTYPE, _ctype)

# basico.run_steadystate status codes that mean a steady state was reached.
_STEADY = (1, 2)


class EquilibratedCopasiProcess(CopasiUTCProcess):
    """``CopasiUTCProcess`` with a parameter set, a required drive and an equilibrated start.

    - ``parameters``: values for fixed global quantities, set once after loading
      (one subpopulation's parameter set). A name that is not a fixed global
      quantity of the model raises.
    - ``driven``: species that must arrive on ``species_counts`` every update. The
      parent reads ``species_counts`` as concentrations and, when it is empty,
      silently runs on the model's own value instead.
    - ``driven_parameters``: global quantities set from the ``parameter_drive``
      input every update. One that the model computes by a rule is switched to
      fixed at load (COPASI: status first, then value; one combined call keeps the
      rule's value). Each must arrive every update.
    - ``equilibrate``: on the first update, set the drive and solve COPASI's steady
      state before advancing, so the cells start where they would sit at that
      drive instead of in the model file's initial state. A failed solve raises.
    - ``emit_fluxes``: also output each reaction's flux by SBML id (COPASI's
      flux in the model's amount per time).
    - ``emit_quantities``: also output these global quantities' current values.

    The first emitted row (t = 0) is the model file's state; the equilibrated
    state appears from the first update on.

    The parent's ``time`` port is not an output: it is a ``list[float]`` that grows
    by every interval's time points.
    """

    config_schema = {
        **CopasiUTCProcess.config_schema,
        "parameters": {"_type": "map[float]", "_default": {}},
        "driven": {"_type": "list[string]", "_default": []},
        "driven_parameters": {"_type": "list[string]", "_default": []},
        "equilibrate": {"_type": "boolean", "_default": True},
        "emit_fluxes": {"_type": "boolean", "_default": False},
        "emit_quantities": {"_type": "list[string]", "_default": []},
    }

    def initialize(self, config=None):
        super().initialize(config)
        table = get_parameters(model=self.dm)
        names = set() if table is None else set(table.index)
        fixed = set() if table is None else set(table.index[table["type"] == "fixed"])
        overrides = self.config.get("parameters") or {}
        unknown = sorted(set(overrides) - fixed)
        if unknown:
            raise ValueError(f"not fixed global quantities of the model: {unknown}")
        for name, value in overrides.items():
            set_parameters(name=name, exact=True, initial_value=float(value), model=self.dm)
        unknown = sorted(set(self.config.get("driven") or []) - set(self.species_ids))
        if unknown:
            raise ValueError(f"driven species not in the model: {unknown}")
        driven_parameters = list(self.config.get("driven_parameters") or [])
        quantities = list(self.config.get("emit_quantities") or [])
        unknown = sorted(set(driven_parameters + quantities) - names)
        if unknown:
            raise ValueError(f"not global quantities of the model: {unknown}")
        model = self.dm.getModel()
        for name in driven_parameters:
            if name not in fixed:
                set_parameters(name=name, exact=True, status="fixed", model=self.dm)
        self._driven_parameters = {name: model.getModelValue(name) for name in driven_parameters}
        self._quantities = {name: model.getModelValue(name) for name in quantities}
        self._equilibrated = False

    def inputs(self):
        ports = super().inputs()
        if self.config.get("driven_parameters"):
            ports["parameter_drive"] = "map[float]"
        return ports

    def outputs(self):
        ports = {"species_concentrations": "map[float]"}
        if self.config.get("emit_fluxes"):
            ports["fluxes"] = "overwrite[map[float]]"
        if self.config.get("emit_quantities"):
            ports["quantities"] = "overwrite[map[float]]"
        return ports

    def initial_state(self):
        """Species, and fluxes and quantities when emitted, at the model file's state (t = 0)."""
        state = super().initial_state()
        if self.config.get("emit_fluxes") or self._quantities:
            model = self.dm.getModel()
            model.applyInitialValues()  # computes fluxes and assignments at the file state
            state.update(self._readouts(model))
        return state

    def _readouts(self, model):
        out = {}
        if self.config.get("emit_fluxes"):
            out["fluxes"] = {model.getReaction(i).getSBMLId(): float(model.getReaction(i).getFlux())
                             for i in range(model.getReactions().size())}
        if self._quantities:
            out["quantities"] = {name: float(value.getValue()) for name, value in self._quantities.items()}
        return out

    def _set_parameters(self, drive):
        missing = [name for name in self._driven_parameters if name not in drive]
        if missing:
            raise ValueError(f"driven parameters missing from parameter_drive: {missing}")
        model = self.dm.getModel()
        for name, value in self._driven_parameters.items():
            value.setInitialValue(float(drive[name]))
            model.updateInitialValues(value.getInitialValueReference())

    def update(self, inputs, interval):
        drive = inputs.get("species_counts") or {}
        missing = [s for s in self.config.get("driven") or [] if s not in drive]
        if missing:
            raise ValueError(f"driven species missing from species_counts: {missing}")
        if self._driven_parameters:
            self._set_parameters(inputs.get("parameter_drive") or {})
        if self.config.get("equilibrate", True) and not self._equilibrated:
            for sbml_id, value in drive.items():
                set_species(name=self.sbml_to_name[sbml_id], exact=True,
                            initial_concentration=float(value), model=self.dm)
            status = run_steadystate(model=self.dm, update_model=True)
            if status not in _STEADY:
                raise RuntimeError(f"COPASI found no steady state at drive {drive} (status {status})")
            self._equilibrated = True
        result = {"species_concentrations": super().update(inputs, interval)["species_concentrations"]}
        result.update(self._readouts(self.dm.getModel()))
        return result
