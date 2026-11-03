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
from ..multiscale.models import KOENIG_PARAMETER_SETS, koenig_2014
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
                       "description": "Cell subpopulations in every stratum: name -> {weight, parameters, "
                                      "metabolism_parameters}. Weights sum to 1; parameters override fixed "
                                      "quantities of the Koschorreck 2008 model; metabolism_parameters names a "
                                      "König parameter set (published, provisional_corrections)"},
    "thermo": {"type": "boolean", "default": False,
               "description": "Add eQuilibrator thermodynamics of the metabolism cells' reactions (needs metabolism)"},
    "thermo_pH": {"type": "float", "default": 7.2, "description": "Cell pH for thermodynamics (provisional; Pulse "
                                                                  "reports pH only in blood)"},
    "thermo_pMg": {"type": "float", "default": 3.0, "description": "Cell pMg for thermodynamics (provisional; Pulse "
                                                                   "has no magnesium)"},
    "thermo_ionic_strength_M": {"type": "float", "default": 0.25,
                                "description": "Cell ionic strength for thermodynamics, M (provisional)"},
    "metabolism": {"type": "boolean", "default": False,
                   "description": "Add König's hepatic glucose metabolism (COPASI) to every cell, driven by "
                                  "Pulse's liver glucose, lactate and the stratum's insulin"},
    "equilibrate": {"type": "boolean", "default": True,
                    "description": "Start each instance at COPASI's steady state for its first drive"},
    "interval": _INTERVAL,
}


def _instances(strata, subpopulations):
    """Instance store name -> (stratum, weight, parameters, König set name); validated when the document is built."""
    strata_positions(strata)
    if not subpopulations:
        raise ValueError("subpopulations must name at least one subpopulation")
    weights = {}
    for name, spec in subpopulations.items():
        unknown = set(spec) - {"weight", "parameters", "metabolism_parameters"}
        if unknown:
            raise ValueError(f"subpopulation {name!r}: unexpected keys {sorted(unknown)}")
        if spec.get("metabolism_parameters", "published") not in KOENIG_PARAMETER_SETS:
            raise ValueError(f"subpopulation {name!r}: unknown metabolism_parameters "
                             f"{spec['metabolism_parameters']!r}; choose from {sorted(KOENIG_PARAMETER_SETS)}")
        weights[name] = float(spec.get("weight", 0.0))
    if min(weights.values()) <= 0 or not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"subpopulation weights must be positive and sum to 1, got {weights}")
    return {f"s{i}_{name}": (i, weights[name] / strata, dict(subpopulations[name].get("parameters") or {}),
                             subpopulations[name].get("metabolism_parameters", "published"))
            for i in range(strata) for name in subpopulations}


def _block(source, *, strata, extraction, max_insulin_nM, subpopulations, metabolism, thermo, thermo_conditions,
           equilibrate, interval):
    instances = _instances(strata, subpopulations)
    check_extraction(extraction)
    if thermo and not metabolism:
        raise ValueError("thermo needs metabolism: it scores the metabolism cells' reactions")
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
        for name, (stratum, _, parameters, _set) in instances.items()
    }
    if metabolism:
        cells.update(_metabolism(instances, equilibrate, interval))
    if thermo:
        cells.update(_thermo(instances, thermo_conditions))
    return {
        **source,
        "gradient": {
            "_type": "step",
            "address": "local:HepaticGradient",
            "config": {"strata": strata, "extraction": extraction, "max_nM": max_insulin_nM,
                       "metabolism": metabolism},
            "inputs": {"hepatic": ["circuits", "hepatic"]},
            "outputs": {"drive": ["tissue", "drive"],
                        **({"metabolism_drive": ["tissue", "metabolism", "drive"]} if metabolism else {})},
        },
        **cells,
        "aggregate": {
            "_type": "step",
            "address": "local:TissueAggregate",
            "config": {"instances": {name: weight for name, (_, weight, _, _) in instances.items()},
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


def _metabolism(instances, equilibrate, interval):
    """König metabolism cells (one per stratum and subpopulation) and their aggregates."""
    weights = {name: weight for name, (_, weight, _, _) in instances.items()}
    nodes = {
        f"metab_{name}": {
            "_type": "process",
            "address": "local:EquilibratedCopasiProcess",
            "interval": interval,
            "config": {"model_source": str(koenig_2014()), "intervals": 1, "report_fluxes": False,
                       "parameters": dict(KOENIG_PARAMETER_SETS[set_name]), "driven": ["glc_ext", "lac_ext"],
                       "driven_parameters": ["ins"], "equilibrate": equilibrate, "emit_fluxes": True,
                       "emit_quantities": ["gamma"]},
            "inputs": {"species_counts": ["tissue", "metabolism", "drive", f"s{stratum}", "species"],
                       "parameter_drive": ["tissue", "metabolism", "drive", f"s{stratum}", "parameters"],
                       "species_concentrations": ["tissue", "metabolism", "cells", name]},
            "outputs": {"species_concentrations": ["tissue", "metabolism", "cells", name],
                        "fluxes": ["tissue", "metabolism", "fluxes", name],
                        "quantities": ["tissue", "metabolism", "quantities", name]},
        }
        for name, (stratum, _, _, set_name) in instances.items()
    }
    for store, unit in (("cells", "mM"), ("fluxes", "flux"), ("quantities", "value")):
        nodes[f"aggregate_metabolism_{store}"] = {
            "_type": "step",
            "address": "local:TissueAggregate",
            "config": {"instances": weights, "unit": unit, "amounts": False},
            "inputs": {"cells": ["tissue", "metabolism", store]},
            "outputs": {f"{stat}_{unit}": ["tissue", "metabolism", f"{store}_summary", f"{stat}_{unit}"]
                        for stat in ("mean", "sd", "min", "max")},
        }
    return nodes


def _thermo(instances, conditions):
    """eQuilibrator dG' over every metabolism cell, and its summaries across the liver."""
    weights = {name: weight for name, (_, weight, _, _) in instances.items()}
    nodes = {"thermo_readout": {
        "_type": "step",
        "address": "local:MetabolismThermo",
        "config": {"model_source": str(koenig_2014()), "instances": list(weights), **conditions},
        "inputs": {"cells": ["tissue", "metabolism", "cells"], "fluxes": ["tissue", "metabolism", "fluxes"],
                   "temperature_C": ["circuits", "hepatic", "body", "core_temperature_C"]},
        "outputs": {"dg_kJ_per_mol": ["tissue", "thermo", "dg_kJ_per_mol"],
                    "conflicts": ["tissue", "thermo", "conflicts"],
                    "standard_kJ_per_mol": ["tissue", "thermo", "standard_kJ_per_mol"],
                    "conditions": ["tissue", "thermo", "conditions"]},
    }}
    for store, unit in (("dg_kJ_per_mol", "kJ_per_mol"), ("conflicts", "fraction")):
        nodes[f"aggregate_thermo_{store}"] = {
            "_type": "step",
            "address": "local:TissueAggregate",
            "config": {"instances": weights, "unit": unit, "amounts": False},
            "inputs": {"cells": ["tissue", "thermo", store]},
            "outputs": {f"{stat}_{unit}": ["tissue", "thermo", f"{store}_summary", f"{stat}_{unit}"]
                        for stat in ("mean", "sd", "min", "max")},
        }
    return nodes


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
                       max_insulin_nM=100.0, subpopulations=None, metabolism=False, thermo=False, thermo_pH=7.2,
                       thermo_pMg=3.0, thermo_ionic_strength_M=0.25, equilibrate=True, interval=1.0, **overrides):
    _reject_unknown(overrides)
    return _block({"pulse": circuit_node(["hepatic"], state_file=state_file, interval=interval)},
                  strata=strata, extraction=extraction, max_insulin_nM=max_insulin_nM,
                  subpopulations=DEFAULT_SUBPOPULATIONS if subpopulations is None else subpopulations,
                  metabolism=metabolism, thermo=thermo,
                  thermo_conditions={"p_h": thermo_pH, "p_mg": thermo_pMg, "ionic_strength_M": thermo_ionic_strength_M},
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
                        subpopulations=None, metabolism=False, thermo=False, thermo_pH=7.2, thermo_pMg=3.0,
                        thermo_ionic_strength_M=0.25, equilibrate=True, interval=1.0, **overrides):
    _reject_unknown(overrides)
    if not trajectory_file:
        raise ValueError("trajectory_file is required")
    replay = {"_type": "process", "address": "local:HepaticReplay", "interval": interval,
              "config": {"trajectory_file": str(trajectory_file)},
              "outputs": {"hepatic": ["circuits", "hepatic"]}}
    return _block({"replay": replay}, strata=strata, extraction=extraction, max_insulin_nM=max_insulin_nM,
                  subpopulations=DEFAULT_SUBPOPULATIONS if subpopulations is None else subpopulations,
                  metabolism=metabolism, thermo=thermo,
                  thermo_conditions={"p_h": thermo_pH, "p_mg": thermo_pMg, "ionic_strength_M": thermo_ionic_strength_M},
                  equilibrate=equilibrate, interval=interval)
