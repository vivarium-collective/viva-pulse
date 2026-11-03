"""Thermodynamics of the liver metabolism cells: eQuilibrator ΔG' of König's reactions.

Reaction formulas come from the model's own KEGG annotations, with the fixes
the probes found (``docs/plan/cell-content-probes``, probe C):

- two mitochondrial annotations point at the wrong compounds;
- three reactions omit the water they consume or release;
- nine reactions are not scored: transport between compartments, glycogen
  (a polymer) and boundary exchange fluxes.

Every reaction is either scored or excluded with a reason; anything else raises.

ΔG' = ΔG'° + RT Σ ν ln(c / 1 M) over all participants except water and H+
(eQuilibrator's convention), with the cell's concentrations (mM in the model).
ΔG'° comes from eQuilibrator's component contribution at the configured pH,
pMg and ionic strength, which are provisional: Pulse reports pH only in blood
and has no magnesium or ionic strength. Temperature is Pulse's core temperature,
rounded to 0.01 K (ΔG'° is recomputed when it changes). RT uses eQuilibrator's own
gas constant (8.31e-3 kJ/mol/K, ``equilibrator_cache.thermodynamic_constants.R``),
so ΔG' equals its ``dg_prime``.

A reaction whose net flux runs against its ΔG' by more than 2σ of ΔG'° is
flagged: the kinetic model breaks the second law there.

eQuilibrator runs on its bundled data only (tier ``bundled``); a lookup that
would reach for the full 1.3 GB database raises. ``equilibrator_api`` is
imported on construction, so viva-pulse imports without the ``multiscale`` extra.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from process_bigraph import Step

KOENIG_KEGG_CORRECTIONS = {"h2o_mito": "C00001", "h_mito": "C00080"}  # annotated as H+ and CO2
KOENIG_H2O_PATCHES = {"FBP2": "lhs", "EN": "rhs", "PC": "lhs"}
KOENIG_EXCLUDED = {
    "GLUT2": "transport (extern -> cytosol)",
    "LACT": "transport (extern -> cytosol)",
    "PYRTM": "transport (cytosol -> mitochondria)",
    "PEPTM": "transport (mitochondria -> cytosol)",
    "GS": "glycogen is a polymer",
    "GP": "glycogen is a polymer",
    "OAAFLX": "boundary exchange flux",
    "ACOAFLX": "boundary exchange flux",
    "CITFLX": "boundary exchange flux",
}

_SBML = "{http://www.sbml.org/sbml/level3/version1/core}"


@dataclass(frozen=True)
class ScoredReaction:
    formula: str  # eQuilibrator formula, "1 kegg:C... + ... = ..."
    participants: tuple[tuple[str, str, float], ...]  # (species id, KEGG id, signed stoichiometry), as annotated


def koenig_reactions(path: str | Path) -> dict[str, ScoredReaction]:
    """The scored reactions of König's model; every other reaction must be in ``KOENIG_EXCLUDED``."""
    model = ET.parse(path).getroot().find(f"{_SBML}model")
    if model is None:
        raise ValueError(f"{path} has no SBML level 3 model")
    kegg = {}
    for species in model.iter(f"{_SBML}species"):
        ids = sorted(set(re.findall(r"kegg\.compound[/:](C\d{5})", ET.tostring(species, encoding="unicode"))))
        kegg[str(species.get("id"))] = ids
    for sid, cid in KOENIG_KEGG_CORRECTIONS.items():
        kegg[sid] = [cid]
    scored, seen = {}, set()
    for reaction in model.iter(f"{_SBML}reaction"):
        rid = str(reaction.get("id"))
        seen.add(rid)
        if rid in KOENIG_EXCLUDED:
            continue

        def side(tag):
            return [(str(r.get("species")), float(r.get("stoichiometry", 1)))
                    for r in reaction.findall(f"{_SBML}{tag}/{_SBML}speciesReference")]

        lhs, rhs = side("listOfReactants"), side("listOfProducts")
        if any(len(kegg[s]) != 1 for s, _ in lhs + rhs):
            raise ValueError(f"{rid}: a participant lacks exactly one KEGG id")
        left = [f"{n:g} kegg:{kegg[s][0]}" for s, n in lhs]
        right = [f"{n:g} kegg:{kegg[s][0]}" for s, n in rhs]
        patch = KOENIG_H2O_PATCHES.get(rid)
        (left if patch == "lhs" else right if patch == "rhs" else []).append("1 kegg:C00001")
        scored[rid] = ScoredReaction(" + ".join(left) + " = " + " + ".join(right),
                                     tuple((s, kegg[s][0], -n) for s, n in lhs) + tuple((s, kegg[s][0], n) for s, n in rhs))
    unknown = set(KOENIG_EXCLUDED) - seen
    if unknown:
        raise ValueError(f"excluded reactions not in the model: {sorted(unknown)}")
    return scored


class MetabolismThermo(Step):
    """ΔG' of every scored reaction in every metabolism cell, and second-law flags (module docstring).

    Config ``p_h``, ``p_mg`` and ``ionic_strength_M`` have no defaults: the cell's
    conditions are a modelling choice, never a silent fallback.
    """

    config_schema = {
        "model_source": "string",
        "instances": "list[string]",
        "p_h": "maybe[float]",
        "p_mg": "maybe[float]",
        "ionic_strength_M": "maybe[float]",
    }

    def initialize(self, config=None):
        missing = [k for k in ("p_h", "p_mg", "ionic_strength_M") if self.config.get(k) is None]
        if missing:
            raise ValueError(f"cell conditions must be given, missing: {missing}")
        try:
            from equilibrator_api import ComponentContribution, Q_
            from equilibrator_cache.api import create_compound_cache_from_zenodo
            from equilibrator_cache.thermodynamic_constants import R
        except ImportError as error:
            raise ImportError("thermodynamics needs eQuilibrator: install viva-pulse's `multiscale` extra") from error
        self._q = Q_
        self._r = R.m_as("kJ / mol / K")
        self._cc = ComponentContribution(ccache=create_compound_cache_from_zenodo(tier="bundled"))
        self._cc.p_h = Q_(float(self.config["p_h"]))
        self._cc.p_mg = Q_(float(self.config["p_mg"]))
        self._cc.ionic_strength = Q_(f"{float(self.config['ionic_strength_M'])} M")
        self._reactions = koenig_reactions(self.config["model_source"])
        self._parsed, self._quotient = {}, {}
        for rid, reaction in self._reactions.items():
            parsed = self._cc.parse_reaction_formula(reaction.formula)
            if not parsed.is_balanced():
                raise ValueError(f"{rid} is not balanced: {reaction.formula}")
            self._parsed[rid] = parsed
            self._quotient[rid] = [(sid, nu) for sid, cid, nu in reaction.participants
                                   if not self._is_water_or_proton(cid)]
        if self._cc.ccache.is_escalated:
            raise RuntimeError("eQuilibrator reached for its full database; only bundled data is allowed")
        self._standard = {}  # temperature (0.01 K) -> {rid: (dG'0, sd)}

    def _is_water_or_proton(self, kegg_id):
        compound = self._cc.get_compound(f"kegg:{kegg_id}")
        return self._cc.ccache.is_water(compound) or self._cc.ccache.is_proton(compound)

    def inputs(self):
        return {"cells": "map[map[float]]", "fluxes": "map[map[float]]", "temperature_C": "float"}

    def outputs(self):
        return {"dg_kJ_per_mol": "overwrite[map[map[float]]]", "conflicts": "overwrite[map[map[float]]]",
                "standard_kJ_per_mol": "overwrite[map[float]]", "conditions": "overwrite[map[float]]"}

    def standard(self, temperature_K: float) -> dict[str, tuple[float, float]]:
        """ΔG'° and its standard deviation (kJ/mol) per scored reaction at ``temperature_K`` (rounded to 0.01 K)."""
        key = round(temperature_K, 2)
        if key not in self._standard:
            self._cc.temperature = self._q(f"{key} K")
            values = {}
            for rid, parsed in self._parsed.items():
                dg0 = self._cc.standard_dg_prime(parsed)
                values[rid] = (dg0.value.m_as("kJ/mol"), dg0.error.m_as("kJ/mol"))
            if self._cc.ccache.is_escalated:
                raise RuntimeError("eQuilibrator reached for its full database; only bundled data is allowed")
            self._standard[key] = values
        return self._standard[key]

    def update(self, state, interval=None):
        temperature_K = round(state["temperature_C"] + 273.15, 2)
        standard = self.standard(temperature_K)
        rt = self._r * temperature_K
        cells, fluxes = state["cells"], state["fluxes"]
        instances = list(self.config["instances"])
        if set(cells) != set(instances):
            raise ValueError(f"cell stores {sorted(cells)} != configured instances {sorted(instances)}")
        dg_out, conflict_out = {}, {}
        for name in instances:
            dg_out[name], conflict_out[name] = {}, {}
            for rid, terms in self._quotient.items():
                logq = 0.0
                for sid, nu in terms:
                    c = cells[name][sid]
                    if c <= 0:
                        raise ValueError(f"{name}: {sid} = {c} mM; ΔG' needs positive concentrations")
                    logq += nu * math.log(c * 1e-3)  # mM -> M
                dg0, sd = standard[rid]
                dg = dg0 + rt * logq
                if rid not in fluxes[name]:
                    raise ValueError(f"{name}: no flux for {rid}; the second-law check needs every scored reaction")
                flux = fluxes[name][rid]
                dg_out[name][rid] = dg
                conflict_out[name][rid] = 1.0 if (flux * dg > 0 and abs(dg) > 2 * sd) else 0.0
        return {"dg_kJ_per_mol": dg_out, "conflicts": conflict_out,
                "standard_kJ_per_mol": {rid: v for rid, (v, _) in standard.items()},
                "conditions": {"p_h": float(self.config["p_h"]), "p_mg": float(self.config["p_mg"]),
                               "ionic_strength_M": float(self.config["ionic_strength_M"]),
                               "temperature_K": temperature_K}}
