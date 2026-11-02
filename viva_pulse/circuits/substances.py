"""Substance and tissue readings: modules whose outputs come from their config.

Pulse tracks every active substance in every compartment, and composition values
for every tissue, but requesting them all would be tens of thousands of outputs. So
these modules read only the entries listed in their config:

- ``substances`` (config ``substance_outputs``): a substance's quantity in a liquid
  or gas compartment (``Concentration``, ``PartialPressure``, ...), or a whole-body
  value with no compartment (``MassInBlood``). Ports
  ``<Substance>/<Compartment>/<port>`` or ``<Substance>/body/<port>``, e.g.
  ``Oxygen/Aorta/partial_pressure_mmHg``.
- ``tissues`` (config ``tissue_outputs``): a tissue compartment's composition
  (``BrainTissue`` ``MatrixVolume``: constants), or the volume, pressure and flows of
  a tissue fluid compartment (``BrainTissueExtracellular``, ``...Intracellular``),
  which change during a run. Ports ``<Compartment>/<port>``.

Each entry is a map of strings: ``substance`` (``substances`` only), ``compartment``
(optional for whole-body values), ``property``, ``unit`` (Pulse's spelling, e.g.
``mmHg``, ``g/L``, ``ug/L``, ``mmol/L``; omitted for unitless properties) and, rarely,
``kind`` (``liquid`` or ``gas``) for a name that is both. The port name is the
property in snake_case plus the unit, with ``/`` written ``_per_``.

Both modules read the starting state (``prepare_state``) and check every entry
against it before the engine loads, because Pulse itself is unforgiving:

- a request for a substance in a compartment that holds no quantity of it (liquid
  ``Alveoli``, the aerosol copy of the airway; or Sodium in gas ``Alveoli``)
  dereferences a null pointer and segfaults (probe ``substances-lymph-2026-11-01``);
- any other unknown name reads NaN, and Pulse creates and activates a substance of
  that name, which is then saved into states;
- a request for an inactive substance (a drug before any dose) activates it.

So entries must name an active substance of the state (no viva-pulse input can dose
a drug yet), a compartment holding a quantity of it, and a property that substance
has. Every leaf of the compartment must be in a transport graph (the circulation,
kidneys included, or the airway) or be a tissue fluid, with a filled-in entry for the
substance: that refuses ``Ground`` and the airway leaks and needles (NaN), equipment
compartments (0 or NaN while the device is off), ``Lymph`` (inactive in Pulse 4.4.0,
see the ``cardiovascular`` module) and ``Pericardium`` (no transport; it still counts
inside ``Heart``). ``Saturation`` is offered in blood only, an infinite ``Volume``
(``Ambient``) not at all, and ``mEq`` units not at all (Pulse converts an equivalent as a
mole).
Whole-body ``PlasmaConcentration`` is not offered: Pulse computes it as the mass in
blood over the plasma volume and calls the result erroneous (``DrugModel.cpp``).
Hemoglobin's ``BloodConcentration`` is total hemoglobin over all its bound forms,
while its masses are the free form only.

The modules edit nothing, so the simulation is the same with or without them.
"""

from __future__ import annotations

import re
from typing import Any

from .base import CircuitModule, Request

#: Liquid-compartment substance properties -> Pulse unit class (None: unitless).
LIQUID_PROPERTIES = {
    "Concentration": "MassPerVolumeUnit",
    "Mass": "MassUnit",
    "MassCleared": "MassUnit",
    "MassDeposited": "MassUnit",
    "MassExcreted": "MassUnit",
    "Molarity": "AmountPerVolumeUnit",
    "PartialPressure": "PressureUnit",
    "Saturation": None,
}
#: Gas-compartment substance properties.
GAS_PROPERTIES = {"PartialPressure": "PressureUnit", "Volume": "VolumeUnit", "VolumeFraction": None}
#: Whole-body ``SESubstance`` properties that Pulse keeps current for every active substance
#: (BloodChemistryModel) or every gas (RespiratoryModel).
BODY_PROPERTIES = {
    "MassInBody": "MassUnit",
    "MassInBlood": "MassUnit",
    "MassInTissue": "MassUnit",
    "BloodConcentration": "MassPerVolumeUnit",
    "EndTidalFraction": None,
    "EndTidalPressure": "PressureUnit",
}
#: ``SETissueCompartment`` properties: composition constants. (``AcidicPhospohlipidConcentration``
#: is left out: Pulse's Python API has no MassPerMass unit class to request it in.)
TISSUE_PROPERTIES = {
    "MatrixVolume": "VolumeUnit",
    "TotalMass": "MassUnit",
    "NeutralLipidsVolumeFraction": None,
    "NeutralPhospholipidsVolumeFraction": None,
    "TissueToPlasmaAlbuminRatio": None,
    "TissueToPlasmaAlphaAcidGlycoproteinRatio": None,
    "TissueToPlasmaLipoproteinRatio": None,
}
#: Tissue fluid properties. The extracellular space is mapped to circuit nodes, so it has a
#: pressure and flows (over its links to the blood and to lymph); the intracellular space has
#: no node, only a volume (its pressure and flows read NaN).
TISSUE_FLUID_PROPERTIES = {
    "Extracellular": {"Volume": "VolumeUnit", "Pressure": "PressureUnit",
                      "Inflow": "VolumePerTimeUnit", "Outflow": "VolumePerTimeUnit"},
    "Intracellular": {"Volume": "VolumeUnit"},
}
#: Properties only gases have, and the substances that bind to hemoglobin.
GAS_ONLY = {"PartialPressure", "EndTidalFraction", "EndTidalPressure"}
SATURATING = {"Oxygen", "CarbonDioxide", "CarbonMonoxide"}
#: Liquid graphs Pulse moves blood and its substances over (the circulation, kidneys included).
#: Equipment compartments (ECMO, bag-valve mask, the aerosol copies of the airway) are outside them.
CIRCULATION_GRAPHS = ("ActiveCardiovascular", "Cardiovascular", "Renal")
#: Graphs of blood proper, where hemoglobin binds gases (Saturation).
BLOOD_GRAPHS = ("ActiveCardiovascular", "Cardiovascular")
#: The gas graph holding the airway; device compartments are outside it.
AIRWAY_GRAPH = "Respiratory"
#: Liquid compartments outside every transport graph that still hold substances: refused on
#: their own, with the reason. Pericardium is part of a parent (Heart) and counts there.
NO_TRANSPORT = {
    "Lymph": "Pulse 4.4.0's lymph carries no flow and no substances (see the cardiovascular module)",
    "Pericardium": "Pulse moves no substances into or out of it (it is in no transport graph), so its "
                   "quantities stay at their loaded values",
}
#: Molarity units Pulse would convert as if an equivalent were a mole (wrong for ions of valence 2).
EQUIVALENT_UNITS = ("mEq/L", "mEq/mL")


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _unit_suffix(unit: str) -> str:
    return "_" + unit.replace("/", "_per_").replace("^", "").replace(" ", "_")


def _port(prop: str, unit: str | None) -> str:
    return _snake(prop) + (_unit_suffix(unit) if unit else "")


def _unit(entry: str, prop: str, unit_class: str | None, unit: str | None) -> tuple[str, str] | None:
    """The (unit class, attribute) Pulse request unit for ``unit``, validated."""
    if unit_class is None:
        if unit is not None:
            raise ValueError(f"{entry}: {prop} is unitless; remove unit {unit!r}")
        return None
    if unit is None:
        raise ValueError(f"{entry}: {prop} needs a unit")
    from pulse.cdm import scalars

    cls = getattr(scalars, unit_class)
    for attr in dir(cls):
        value = getattr(cls, attr)
        if isinstance(value, cls) and value.get_string() == unit:
            return (unit_class, attr)
    choices = sorted(getattr(cls, a).get_string() for a in dir(cls) if isinstance(getattr(cls, a), cls))
    raise ValueError(f"{entry}: {unit!r} is not a {unit_class.removesuffix('Unit')} unit; Pulse's are {choices}")


def _entries(config: dict[str, Any], key: str, required: set[str], optional: set[str]) -> list[dict[str, str]]:
    if not config[key]:
        raise ValueError(f"{key} is empty: list what to read, or leave the module out")
    entries = []
    for i, entry in enumerate(config[key]):
        name = f"{key}[{i}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{name} must be a map, got {entry!r}")
        unknown = set(entry) - required - optional
        if unknown:
            raise ValueError(f"{name}: unknown keys {sorted(unknown)}; allowed: {sorted(required | optional)}")
        missing = required - set(entry)
        if missing:
            raise ValueError(f"{name}: missing {sorted(missing)}")
        for k, v in entry.items():
            if not isinstance(v, str) or not v:
                raise ValueError(f"{name}: {k} must be a non-empty string, got {v!r}")
        entries.append(entry)
    return entries


def _check_unique(outputs: list[Request], labels: list[str]) -> None:
    seen: dict[tuple, str] = {}
    for request, label in zip(outputs, labels):
        if request.path in seen:
            raise ValueError(f"{label} and {seen[request.path]} both write {'/'.join(request.path)}")
        seen[request.path] = label


def _compartments(state: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    return {c["FluidCompartment"]["Compartment"]["Name"]: c for c in state["CompartmentManager"][f"{kind}Compartment"]}


def _quantity(compartment: dict[str, Any] | None, substance: str) -> dict[str, Any] | None:
    """The state's entry for ``substance`` in ``compartment``, if it has one."""
    if compartment is None:
        return None
    return next((q for q in compartment.get("SubstanceQuantity", [])
                 if q["SubstanceQuantity"]["Substance"] == substance), None)


def _leaves(compartments: dict[str, dict[str, Any]], name: str) -> list[str]:
    children = compartments[name]["FluidCompartment"]["Compartment"].get("Child", [])
    return [name] if not children else [leaf for child in children for leaf in _leaves(compartments, child)]


def _graph_members(state: dict[str, Any], kind: str, names: tuple[str, ...]) -> set[str]:
    return set().union(*(set(g["FluidGraph"]["Graph"].get("Compartment", []))
                         for g in state["CompartmentManager"][f"{kind}Graph"]
                         if g["FluidGraph"]["Graph"]["Name"] in names))


def _refusal(kind: str, compartment: str, sub: str, compartments: dict[str, dict[str, Any]],
             readable: set[str]) -> str | None:
    """Why ``compartment`` can't be read for ``sub``, or None.

    Readable means: every leaf is in ``readable`` (a transport graph, or a tissue fluid) and holds a
    filled-in entry for the substance. A bare entry (only the substance's name: ``Ground``, the
    airway leaks and needles) reads NaN. A parent may include ``Pericardium`` (``Heart`` does).
    """
    if compartment in NO_TRANSPORT:
        return NO_TRANSPORT[compartment]
    leaves = _leaves(compartments, compartment)
    for leaf in leaves:
        if leaf in NO_TRANSPORT and leaf != compartment:
            continue
        entry = _quantity(compartments[leaf], sub)
        if entry is None or len(entry) == 1:
            what = compartment if leaf == compartment else f"{compartment}'s part {leaf}"
            return f"{what} serves no {sub} quantity in this state (Pulse reads NaN)"
        if leaf not in readable:
            what = compartment if leaf == compartment else f"{compartment}'s part {leaf}"
            return (f"{what} is an equipment compartment, which reads 0 or NaN while the device is off"
                    if kind == "gas" or "Tissue" not in leaf else f"{what} is outside the circulation")
    return None


def _substance_outputs(config: dict[str, Any], state: dict[str, Any]) -> tuple[Request, ...]:
    entries = _entries(config, "substance_outputs", {"substance", "property"}, {"compartment", "unit", "kind"})
    substances = {s["Name"]: s for s in state["Substance"]}
    active = set(state["ActiveSubstance"])
    liquids, gases = _compartments(state, "Liquid"), _compartments(state, "Gas")
    tissue_fluids = {f"{t['Compartment']['Name']}{side}" for t in state["CompartmentManager"]["TissueCompartment"]
                     for side in ("Extracellular", "Intracellular")}
    readable = {"liquid": _graph_members(state, "Liquid", CIRCULATION_GRAPHS) | tissue_fluids,
                "gas": _graph_members(state, "Gas", (AIRWAY_GRAPH,))}
    blood = _graph_members(state, "Liquid", BLOOD_GRAPHS)
    outputs, labels = [], []
    for i, entry in enumerate(entries):
        name = f"substance_outputs[{i}]"
        sub, prop, unit = entry["substance"], entry["property"], entry.get("unit")
        if sub not in substances:
            raise ValueError(f"{name}: unknown substance {sub!r}; Pulse's are {sorted(substances)}")
        if sub not in active:
            raise ValueError(f"{name}: {sub} is not active in this state, and nothing in viva-pulse can "
                             f"add it yet (a request would activate it); active: {sorted(active)}")
        is_gas = substances[sub].get("State") == "Gas"
        if "compartment" not in entry:
            if "kind" in entry:
                raise ValueError(f"{name}: kind applies only with a compartment")
            table, category, compartment, store = BODY_PROPERTIES, "substance", None, "body"
            if prop == "PlasmaConcentration":
                raise ValueError(f"{name}: PlasmaConcentration is not offered: Pulse computes it as the mass "
                                 f"in blood over the plasma volume (DrugModel.cpp); use BloodConcentration")
        else:
            compartment = entry["compartment"]
            pools = {"liquid": liquids, "gas": gases}
            if compartment not in liquids and compartment not in gases:
                raise ValueError(f"{name}: unknown compartment {compartment!r}")
            holding = [k for k in ("liquid", "gas") if _quantity(pools[k].get(compartment), sub) is not None]
            if "kind" in entry:
                if entry["kind"] not in ("liquid", "gas"):
                    raise ValueError(f"{name}: kind must be liquid or gas, got {entry['kind']!r}")
                if entry["kind"] not in holding:
                    other = [k for k in holding if k != entry["kind"]]
                    raise ValueError(f"{name}: {compartment} holds no {sub} as a {entry['kind']} compartment"
                                     + (f"; it does as a {other[0]} compartment" if other else ""))
                holding = [entry["kind"]]
            if not holding:
                where = " and ".join(f"a {k} compartment" for k in ("liquid", "gas") if compartment in pools[k])
                raise ValueError(f"{name}: {compartment} ({where}) holds no {sub} in this state")
            if len(holding) > 1:
                raise ValueError(f"{name}: {compartment} is both a liquid and a gas compartment holding {sub}; "
                                 f"add kind: liquid or gas")
            kind = holding[0]
            refusal = _refusal(kind, compartment, sub, pools[kind], readable[kind])
            if refusal:
                raise ValueError(f"{name}: {refusal}")
            if prop == "Volume" and kind == "gas":
                volume = next(iter(gases[compartment]["FluidCompartment"].get("Volume", {"_": {}}).values()))
                if volume.get("Value") == "Infinity":
                    raise ValueError(f"{name}: {compartment} is an infinite reservoir; its Volume is infinite")
            if prop == "Saturation" and kind == "liquid" and not set(_leaves(liquids, compartment)) <= blood:
                raise ValueError(f"{name}: Saturation is a property of blood; {compartment} is not in the "
                                 f"blood circulation (it reads 0 there)")
            table = LIQUID_PROPERTIES if kind == "liquid" else GAS_PROPERTIES
            category, store = f"{kind}_compartment", compartment
        if prop not in table:
            raise ValueError(f"{name}: {prop!r} is not offered here; choose from {sorted(table)}")
        if prop in GAS_ONLY and not is_gas and table is not GAS_PROPERTIES:
            raise ValueError(f"{name}: {sub} is not a gas, so it has no {prop}")
        if prop == "Saturation" and sub not in SATURATING:
            raise ValueError(f"{name}: only {sorted(SATURATING)} have a Saturation")
        if unit in EQUIVALENT_UNITS:
            raise ValueError(f"{name}: {unit} is not offered: Pulse converts an equivalent as a mole, which is "
                             f"wrong for ions of valence 2 (Calcium); use mmol/L")
        outputs.append(Request((sub, store, _port(prop, unit)), category, prop,
                               _unit(name, prop, table[prop], unit), compartment, substance=sub))
        labels.append(name)
    _check_unique(outputs, labels)
    return tuple(outputs)


def _tissue_outputs(config: dict[str, Any], state: dict[str, Any]) -> tuple[Request, ...]:
    entries = _entries(config, "tissue_outputs", {"compartment", "property"}, {"unit"})
    tissues = [t["Compartment"]["Name"] for t in state["CompartmentManager"]["TissueCompartment"]]
    fluids = {f"{t}{side}" for t in tissues for side in ("Extracellular", "Intracellular")}
    liquids = _compartments(state, "Liquid")
    outputs, labels = [], []
    for i, entry in enumerate(entries):
        name = f"tissue_outputs[{i}]"
        compartment, prop, unit = entry["compartment"], entry["property"], entry.get("unit")
        if compartment in tissues:
            table, category = TISSUE_PROPERTIES, "tissue_compartment"
        elif compartment in fluids and compartment in liquids:
            side = "Extracellular" if compartment.endswith("Extracellular") else "Intracellular"
            table, category = TISSUE_FLUID_PROPERTIES[side], "liquid_compartment"
        else:
            raise ValueError(f"{name}: {compartment!r} is not a tissue or tissue fluid compartment; "
                             f"tissues are {sorted(tissues)}, each with <tissue>Extracellular and "
                             f"<tissue>Intracellular")
        if prop not in table:
            raise ValueError(f"{name}: {prop!r} is not offered for {compartment}; choose from {sorted(table)}")
        outputs.append(Request((compartment, _port(prop, unit)), category, prop,
                               _unit(name, prop, table[prop], unit), compartment))
        labels.append(name)
    _check_unique(outputs, labels)
    return tuple(outputs)


_LIST = {"_type": "list[map[string]]", "_default": []}

SUBSTANCES = CircuitModule(
    name="substances",
    model_types=frozenset({"whole_body"}),
    params={"substance_outputs": dict(_LIST)},
    prepare_state=_substance_outputs,
)

TISSUES = CircuitModule(
    name="tissues",
    model_types=frozenset({"whole_body"}),
    params={"tissue_outputs": dict(_LIST)},
    prepare_state=_tissue_outputs,
)
