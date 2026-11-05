# Pulse (Kitware) issues found from viva-pulse

Drafted, not filed: the user decides what to send (CURRENT.md). Engine `REL_4_4_0` (`5e29e5b13`).
Evidence: probe `workspace/experiments/substances-lymph-2026-11-01/`, plan
`docs/plan/plan-substances-and-lymph.md`.

## Lymph carries no flow: is it intended?

The `Lymph` node, 13 `<Tissue>T1ToLymph` paths and `LymphToVenaCava1` are created in
`SetupCircuitsAndCompartments.cpp` (2104-2118, 2254-2255, 2301-2302, ...), but each tissue-to-lymph
path is a flow source whose baseline is set to 0 and never changed anywhere in `src/cpp/engine`.
The node's volume baseline is 0 and `Lymph` is in no liquid graph. Result: lymph flow stays at
solver noise (< 2e-9 mL/min) even during a RightLeg 0.8 hemorrhage or a 250 mL/min saline infusion,
no substance reaches `Lymph`, and its pressure equals `VenaCava1`'s.
`CardiovascularMethodology.md:31` describes lymph as "an accessory return for interstitial fluid".

The stub dates from Pulse's first commit (`b8d1dd54f`, from BioGears). BioGears later implemented
an active lymph model (Oct-Nov 2018: pre-lymphatic nodes with pressure sources and valves per
tissue, a 2 L lymph compliance, return resistance for about 3.5 mL/min, albumin convection), still in
BioGears 8.2.0. Questions: is lymph meant to stay inactive? Would a contribution along BioGears'
lines be considered?

## A substance request on a compartment without that substance segfaults

`SEEngineTracker::TrackRequest` (`SEDataRequestTracker.cpp` ~432-505) calls
`GetSubstanceQuantity(*sub)->GetScalar(...)`, which dereferences null when the compartment holds no
quantity of the substance. Reproduced from Python (exit -11) with: liquid `Alveoli` + Oxygen,
liquid `Alveoli` + Sodium, gas `Alveoli` + Sodium. 45 names exist as both an aerosol liquid
compartment and a gas compartment, which makes this easy to hit. Suggest returning false with an
error, as for an unknown compartment.

## Requesting data for an unknown substance creates it

`SESubstanceManager::GetSubstance` (non-const, `SESubstanceManager.cpp:49-58`) creates a substance
for an unknown name, and the request then activates it (`AddActiveSubstance`). A misspelled name
(`Oxygenn`) reads NaN, and the saved state then holds 47 substance definitions including it.
Requests for a known but inactive substance also activate it, which persists into saved states.

## Whole-body `PlasmaConcentration`

`DrugModel::CalculatePlasmaSubstanceConcentration` divides the substance mass in all of the blood by
the plasma volume (the code comment calls it "obviously erroneous ... a known issue"). For Sodium it
reads 6.16 g/L against a blood concentration of 3.30 g/L.
