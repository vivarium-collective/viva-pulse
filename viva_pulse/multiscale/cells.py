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
    - ``equilibrate``: on the first update, set the drive and solve COPASI's steady
      state before advancing, so the cells start where they would sit at that
      drive instead of in the model file's initial state. A failed solve raises.

    The first emitted row (t = 0) is the model file's state; the equilibrated
    state appears from the first update on.

    Only ``species_concentrations`` is an output. The parent's ``time`` port is a
    ``list[float]`` that grows by every interval's time points, and fluxes are
    not used here.
    """

    config_schema = {
        **CopasiUTCProcess.config_schema,
        "parameters": {"_type": "map[float]", "_default": {}},
        "driven": {"_type": "list[string]", "_default": []},
        "equilibrate": {"_type": "boolean", "_default": True},
    }

    def initialize(self, config=None):
        super().initialize(config)
        overrides = self.config.get("parameters") or {}
        if overrides:
            table = get_parameters(model=self.dm)
            fixed = set() if table is None else set(table.index[table["type"] == "fixed"])
            unknown = sorted(set(overrides) - fixed)
            if unknown:
                raise ValueError(f"not fixed global quantities of the model: {unknown}")
            for name, value in overrides.items():
                set_parameters(name=name, exact=True, initial_value=float(value), model=self.dm)
        unknown = sorted(set(self.config.get("driven") or []) - set(self.species_ids))
        if unknown:
            raise ValueError(f"driven species not in the model: {unknown}")
        self._equilibrated = False

    def update(self, inputs, interval):
        drive = inputs.get("species_counts") or {}
        missing = [s for s in self.config.get("driven") or [] if s not in drive]
        if missing:
            raise ValueError(f"driven species missing from species_counts: {missing}")
        if self.config.get("equilibrate", True) and not self._equilibrated:
            for sbml_id, value in drive.items():
                set_species(name=self.sbml_to_name[sbml_id], exact=True,
                            initial_concentration=float(value), model=self.dm)
            status = run_steadystate(model=self.dm, update_model=True)
            if status not in _STEADY:
                raise RuntimeError(f"COPASI found no steady state at drive {drive} (status {status})")
            self._equilibrated = True
        return {"species_concentrations": super().update(inputs, interval)["species_concentrations"]}

    def outputs(self):
        return {"species_concentrations": "map[float]"}
