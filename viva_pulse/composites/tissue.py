"""Pulse over a stratified liver tissue block of COPASI cell models (docs/guide/guide-multiscale-design.md).

Store layout:
- ``circuits/hepatic/``: the liver's blood supply, from Pulse or a replay;
- ``tissue/drive/s<i>``: the insulin each stratum's cells see (``{"ins": nM}``);
- ``tissue/cells/s<i>_<subpopulation>``: each instance's species (nM);
- ``tissue/summary/<statistic>``: weighted statistics and amounts per species;
- a ``RAMEmitter`` at ``emitter`` recording ``circuits``, ``tissue`` and time.

The t = 0 row holds the cell model file's state; instances are equilibrated to
their drive in the first update, so cell readings start at t = 1.

One-way: nothing the cells do reaches Pulse.
"""

from __future__ import annotations

import math

from process_bigraph.composite_generator import composite_generator

from ..core import register_processes
from ..multiscale import KOSCHORRECK_2008, register_multiscale
from ..multiscale.tissue import check_extraction, strata_positions
from .circuits import _INTERVAL, _STATE_FILE, _reject_unknown, circuit_node

DEFAULT_SUBPOPULATIONS = {"hepatocyte": {"weight": 1.0, "parameters": {}}}
SUMMARY = ("mean_nM", "sd_nM", "min_nM", "max_nM", "molecules_per_cell", "tissue_total_nmol", "cell_count")

_BLOCK_PARAMETERS = {
    "strata": {"type": "integer", "default": 1,
               "description": "Equal-volume strata along the sinusoid, inlet first; 1 = every cell sees "
                              "Pulse's liver value"},
    "extraction": {"type": "float", "default": 0.0,
                   "description": "Fraction of the liver's incoming insulin removed by the outlet (0-1), linear "
                                  "along the sinusoid, mean held at Pulse's value. 0 = uniform, as in Pulse, whose "
                                  "liver clears no insulin. Provisional: a modeler's choice"},
    "max_insulin_nM": {"type": "float", "default": 100.0,
                       "description": "Fail if any stratum's insulin exceeds this; 100 nM is the highest level "
                                      "Koschorreck 2008 validates against (provisional)"},
    "subpopulations": {"type": "map", "default": DEFAULT_SUBPOPULATIONS,
                       "description": "Cell subpopulations in every stratum: name -> {weight, parameters}. "
                                      "Weights sum to 1; parameters override fixed quantities of the "
                                      "Koschorreck 2008 model (provisional)"},
    "equilibrate": {"type": "boolean", "default": True,
                    "description": "Start each instance at COPASI's steady state for its first drive"},
    "interval": _INTERVAL,
}


def _instances(strata, subpopulations):
    """Instance store name -> (stratum, weight, parameters); validated when the document is built."""
    strata_positions(strata)
    if not subpopulations:
        raise ValueError("subpopulations must name at least one subpopulation")
    weights = {}
    for name, spec in subpopulations.items():
        unknown = set(spec) - {"weight", "parameters"}
        if unknown:
            raise ValueError(f"subpopulation {name!r}: unexpected keys {sorted(unknown)}")
        weights[name] = float(spec.get("weight", 0.0))
    if min(weights.values()) <= 0 or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"subpopulation weights must be positive and sum to 1, got {weights}")
    return {f"s{i}_{name}": (i, weights[name] / strata, dict(subpopulations[name].get("parameters") or {}))
            for i in range(strata) for name in subpopulations}


def _block(source, *, strata, extraction, max_insulin_nM, subpopulations, equilibrate, interval):
    instances = _instances(strata, subpopulations)
    check_extraction(extraction)
    cells = {
        f"cell_{name}": {
            "_type": "process",
            "address": "local:EquilibratedCopasiProcess",
            "interval": interval,
            "config": {"model_source": str(KOSCHORRECK_2008), "intervals": 1, "report_fluxes": False,
                       "parameters": parameters, "driven": ["ins"], "equilibrate": equilibrate},
            "inputs": {"species_counts": ["tissue", "drive", f"s{stratum}"],
                       "species_concentrations": ["tissue", "cells", name]},
            "outputs": {"species_concentrations": ["tissue", "cells", name]},
        }
        for name, (stratum, _, parameters) in instances.items()
    }
    return {
        **source,
        "gradient": {
            "_type": "step",
            "address": "local:HepaticGradient",
            "config": {"strata": strata, "extraction": extraction, "max_nM": max_insulin_nM},
            "inputs": {"hepatic": ["circuits", "hepatic"]},
            "outputs": {"drive": ["tissue", "drive"]},
        },
        **cells,
        "aggregate": {
            "_type": "step",
            "address": "local:TissueAggregate",
            "config": {"instances": {name: weight for name, (_, weight, _) in instances.items()},
                       "exclude": ["ins"]},
            "inputs": {"cells": ["tissue", "cells"],
                       "tissue_mass_kg": ["circuits", "hepatic", "liver", "tissue_mass_kg"]},
            "outputs": {key: ["tissue", "summary", key] for key in SUMMARY},
        },
        "interventions": {},
        "circuits": {},
        "tissue": {},
        "emitter": {
            "_type": "step",
            "address": "local:RAMEmitter",
            "config": {"emit": {"circuits": "node", "tissue": "node", "time": "float"}},
            "inputs": {"circuits": ["circuits"], "tissue": ["tissue"], "time": ["global_time"]},
        },
    }


@composite_generator(
    name="pulse_liver_tissue",
    description="Real whole-body Pulse over a stratified liver tissue block: Pulse's liver insulin, spread "
                "inlet-to-outlet over equal-volume strata by a configured extraction, drives Koschorreck 2008 "
                "hepatocyte insulin-receptor models in COPASI, one per stratum and subpopulation. One-way: the "
                "cells never change Pulse.",
    parameters={"state_file": _STATE_FILE, **_BLOCK_PARAMETERS},
    core_extensions=[register_processes, register_multiscale],
    default_n_steps=600,
    fidelity="real-bridge",
)
def pulse_liver_tissue(core=None, *, state_file="StandardMale@0s.json", strata=1, extraction=0.0,
                       max_insulin_nM=100.0, subpopulations=None, equilibrate=True, interval=1.0, **overrides):
    _reject_unknown(overrides)
    return _block({"pulse": circuit_node(["hepatic"], state_file=state_file, interval=interval)},
                  strata=strata, extraction=extraction, max_insulin_nM=max_insulin_nM,
                  subpopulations=DEFAULT_SUBPOPULATIONS if subpopulations is None else subpopulations,
                  equilibrate=equilibrate, interval=interval)


@composite_generator(
    name="liver_tissue_replay",
    description="The liver tissue block of pulse_liver_tissue driven by a recorded hepatic trajectory instead "
                "of the engine (save one with viva_pulse.multiscale.save_hepatic_trajectory).",
    parameters={"trajectory_file": {"type": "string", "default": "",
                                    "description": "JSON hepatic trajectory (time from 0 on a uniform grid)"},
                **_BLOCK_PARAMETERS},
    core_extensions=[register_processes, register_multiscale],
    default_n_steps=600,
    fidelity="real-bridge",
)
def liver_tissue_replay(core=None, *, trajectory_file="", strata=1, extraction=0.0, max_insulin_nM=100.0,
                        subpopulations=None, equilibrate=True, interval=1.0, **overrides):
    _reject_unknown(overrides)
    if not trajectory_file:
        raise ValueError("trajectory_file is required")
    replay = {"_type": "process", "address": "local:HepaticReplay", "interval": interval,
              "config": {"trajectory_file": str(trajectory_file)},
              "outputs": {"hepatic": ["circuits", "hepatic"]}}
    return _block({"replay": replay}, strata=strata, extraction=extraction, max_insulin_nM=max_insulin_nM,
                  subpopulations=DEFAULT_SUBPOPULATIONS if subpopulations is None else subpopulations,
                  equilibrate=equilibrate, interval=interval)
