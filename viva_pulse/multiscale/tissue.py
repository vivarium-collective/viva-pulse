"""The stratified tissue block under Pulse (plan Design 1), liver as the instance.

Pulse treats the liver's blood as one well-mixed compartment. The block spreads
that value along the sinusoid, inlet to outlet, over ``strata`` equal-volume
strata, and runs a population of cell models in each:

- ``HepaticGradient``: local insulin per stratum. Linear in position x (0 at the
  inlet, 1 at the outlet), equal to Pulse's flow-weighted inlet concentration at
  x = 0, with a volume-weighted mean equal to Pulse's liver value:
  ``c(x) = mean + (inlet - mean) * (1 - 2x)``, sampled at each stratum's midpoint.
  One stratum gives every cell the liver value. A negative stratum raises.
- ``TissueAggregate``: weighted statistics of the cell instances, per-cell
  molecule counts and liver totals.
- ``HepaticReplay``: replays a recorded hepatic trajectory in Pulse's place, so
  the block runs without the engine (plan: offline replay variant).

Nothing flows back to Pulse: receptor binding here does not remove insulin from
Pulse's blood. The block is a readout of Pulse, not feedback into it.

The linear profile and the subpopulation parameter sets are provisional
modelling choices, not validated physiology.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from process_bigraph import Process, Step

from ..circuits.hepatic import HEPATIC, PORTAL_SOURCES
from ..processes import _nest

#: Koschorreck & Gilles 2008 (BMC Syst Biol 2:43), BioModels BIOMD0000000345 (CC0):
#: hepatocyte insulin receptor binding, phosphorylation and internalization in rat.
#: Seconds and nM (paper Table 1).
KOSCHORRECK_2008 = Path(__file__).parent / "models" / "BIOMD0000000345.xml"

AVOGADRO = 6.02214076e23  # 1/mol, exact (SI 2019)
HEPATIC_PATHS = tuple(r.path for r in HEPATIC.outputs)


def strata_positions(strata: int) -> list[float]:
    """Midpoints of ``strata`` equal-volume strata on [0, 1], inlet first."""
    if strata < 1:
        raise ValueError(f"strata must be at least 1, got {strata}")
    return [(i + 0.5) / strata for i in range(strata)]


def inlet_nM(hepatic: dict) -> float:
    """Flow-weighted insulin entering the liver, in nM, from the hepatic reads.

    The hepatic artery's flow is the liver inflow minus the portal outflows; it
    carries aortic blood.
    """
    q_in = hepatic["liver"]["average_inflow_mL_per_min"]
    portal = [(hepatic["sources"][s]["insulin_pmol_per_L"], hepatic["sources"][s]["average_outflow_mL_per_min"])
              for s in PORTAL_SOURCES]
    q_artery = q_in - sum(q for _, q in portal)
    if q_in <= 0 or q_artery < 0:
        raise ValueError(f"liver inflow {q_in} mL/min is below the portal outflows "
                         f"{sum(q for _, q in portal)} mL/min")
    supplied = sum(c * q for c, q in portal) + hepatic["sources"]["aorta"]["insulin_pmol_per_L"] * q_artery
    return supplied / q_in / 1000.0


class HepaticGradient(Step):
    """Pulse's hepatic reads -> the insulin each stratum's cells see (see module docstring)."""

    config_schema = {
        "strata": {"_type": "integer", "_default": 1},
        "species": {"_type": "string", "_default": "ins"},
    }

    def initialize(self, config=None):
        self._x = strata_positions(int(self.config["strata"]))

    def inputs(self):
        return {"hepatic": _nest([(path, "float") for path in HEPATIC_PATHS])}

    def outputs(self):
        return {"drive": {f"s{i}": "overwrite[map[float]]" for i in range(len(self._x))},
                "inlet_nM": "overwrite[float]",
                "mean_nM": "overwrite[float]"}

    def update(self, state, interval=None):
        hepatic = state["hepatic"]
        mean = hepatic["liver"]["insulin_pmol_per_L"] / 1000.0
        inlet = inlet_nM(hepatic)
        local = [mean + (inlet - mean) * (1.0 - 2.0 * x) for x in self._x]
        if min(local) < 0.0:
            raise ValueError(f"stratum insulin below zero ({min(local)} nM): the inlet {inlet} nM is more "
                             f"than twice the liver mean {mean} nM, outside the linear profile")
        species = self.config["species"]
        return {"drive": {f"s{i}": {species: c} for i, c in enumerate(local)},
                "inlet_nM": inlet, "mean_nM": mean}


class TissueAggregate(Step):
    """Weighted statistics over the cell instances, plus per-cell and whole-liver amounts.

    ``instances`` maps each instance's store name to its weight: its stratum's
    volume fraction times its subpopulation's weight. The weights must sum to 1.
    Cell concentrations are per hepatocyte volume (nM), so with the cell
    geometry below:

    - ``molecules_per_cell`` = mean x cell volume x Avogadro;
    - ``cell_count`` = cell volume fraction x tissue volume / cell volume;
    - ``tissue_total_nmol`` = cell_count x per-cell amount.

    Defaults are Koschorreck 2008's: a hepatocyte is a 20 um sphere (40 nM =
    1e5 receptors per cell), hepatocytes fill 78% of the liver, liver density
    1051 g/L (the model's ``rholiver``). They describe rat liver.
    """

    config_schema = {
        "instances": "map[float]",
        "exclude": {"_type": "list[string]", "_default": []},
        "cell_diameter_um": {"_type": "float", "_default": 20.0},
        "cell_volume_fraction": {"_type": "float", "_default": 0.78},
        "tissue_density_kg_per_L": {"_type": "float", "_default": 1.051},
    }

    def initialize(self, config=None):
        weights = dict(self.config["instances"])
        if not weights or min(weights.values()) < 0 or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError(f"instance weights must be non-negative and sum to 1, got {weights}")
        self._weights = weights
        self._cell_volume_L = math.pi / 6.0 * (self.config["cell_diameter_um"] * 1e-5) ** 3

    def inputs(self):
        return {"cells": "map[map[float]]", "tissue_mass_kg": "float"}

    def outputs(self):
        stat = "overwrite[map[float]]"
        return {"mean_nM": stat, "sd_nM": stat, "min_nM": stat, "max_nM": stat,
                "molecules_per_cell": stat, "tissue_total_nmol": stat, "cell_count": "overwrite[float]"}

    def update(self, state, interval=None):
        cells = state["cells"]
        if set(cells) != set(self._weights):
            raise ValueError(f"cell stores {sorted(cells)} != configured instances {sorted(self._weights)}")
        exclude = set(self.config.get("exclude") or [])
        species = sorted(set().union(*(cells[i].keys() for i in cells)) - exclude)
        tissue_volume_L = state["tissue_mass_kg"] / self.config["tissue_density_kg_per_L"]
        cell_count = self.config["cell_volume_fraction"] * tissue_volume_L / self._cell_volume_L
        out = {k: {} for k in ("mean_nM", "sd_nM", "min_nM", "max_nM", "molecules_per_cell", "tissue_total_nmol")}
        for s in species:
            values = [(w, cells[i][s]) for i, w in self._weights.items()]
            mean = sum(w * y for w, y in values)
            out["mean_nM"][s] = mean
            out["sd_nM"][s] = math.sqrt(max(sum(w * (y - mean) ** 2 for w, y in values), 0.0))
            out["min_nM"][s] = min(y for _, y in values)
            out["max_nM"][s] = max(y for _, y in values)
            per_cell = mean * 1e-9 * self._cell_volume_L * AVOGADRO
            out["molecules_per_cell"][s] = per_cell
            out["tissue_total_nmol"][s] = cell_count * mean * self._cell_volume_L  # nM x L = nmol
        return {**out, "cell_count": cell_count}


def hepatic_trajectory(rows: list[dict]) -> dict:
    """A replayable trajectory from emitter rows that carry ``circuits/hepatic`` and ``time``."""
    trajectory = {"time": [float(row["time"]) for row in rows], "values": {}}
    for path in HEPATIC_PATHS:
        series = []
        for row in rows:
            node = row["circuits"]["hepatic"]
            for key in path:
                node = node[key]
            series.append(float(node))
        trajectory["values"]["/".join(path)] = series
    return trajectory


def save_hepatic_trajectory(rows: list[dict], path: str | Path) -> Path:
    """Write :func:`hepatic_trajectory` of ``rows`` as JSON; returns the path."""
    path = Path(path)
    path.write_text(json.dumps(hepatic_trajectory(rows)))
    return path


class HepaticReplay(Process):
    """Emits a recorded hepatic trajectory in place of Pulse (same ports, same values).

    ``trajectory_file`` is JSON from :func:`save_hepatic_trajectory`: ``time`` on a
    uniform grid starting at 0, and one series per hepatic output path. The
    process interval must be a whole number of grid steps. Running past the end
    raises.
    """

    config_schema = {"trajectory_file": "string"}

    def initialize(self, config=None):
        trajectory = json.loads(Path(self.config["trajectory_file"]).read_text())
        times = trajectory["time"]
        values = trajectory["values"]
        expected = {"/".join(p) for p in HEPATIC_PATHS}
        if set(values) != expected:
            raise ValueError(f"trajectory paths differ from the hepatic outputs: "
                             f"missing {sorted(expected - set(values))}, extra {sorted(set(values) - expected)}")
        if len(times) < 2 or times[0] != 0.0 or any(len(v) != len(times) for v in values.values()):
            raise ValueError("trajectory needs a time series from 0 with one value per time for every path")
        self._dt = times[1] - times[0]
        if any(not math.isclose(t, i * self._dt, rel_tol=0, abs_tol=1e-9) for i, t in enumerate(times)):
            raise ValueError("trajectory times must be a uniform grid")
        self._times = times
        self._series = {tuple(k.split("/")): v for k, v in values.items()}
        self._index = 0

    def outputs(self):
        return {"hepatic": _nest([(path, "overwrite[float]") for path in HEPATIC_PATHS])}

    def initial_state(self):
        return {"hepatic": self._at(0)}

    def _at(self, index):
        return _nest([(path, self._series[path][index]) for path in HEPATIC_PATHS])

    def update(self, state, interval):
        steps = interval / self._dt
        if not math.isclose(steps, round(steps), abs_tol=1e-9) or round(steps) < 1:
            raise ValueError(f"interval {interval} is not a whole number of trajectory steps ({self._dt})")
        self._index += round(steps)
        if self._index >= len(self._times):
            raise ValueError(f"trajectory ends at t={self._times[-1]}")
        return {"hepatic": self._at(self._index)}
