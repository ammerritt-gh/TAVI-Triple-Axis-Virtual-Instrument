# PUMA Model Status

- Model version: **1.0.0**
- Model date: **2026-07-18**
- Runtime status: **runnable**
- Last evidence review: **2026-07-18**

Status words mean: **verified** has direct evidence or a locked comparison;
**provisional** is implemented but needs confirmation; **conflicting** has
credible disagreement; **missing** is not modeled or lacks usable evidence.

| Area | TAVI model | Evidence | Status | Action |
|---|---|---|---|---|
| Arm lengths | L1-L4 = 2.150 / 2.290 / 0.880 / 0.750 m | Legacy TAVI model and layout notes | provisional | Confirm against an instrument drawing. |
| Scattering senses | mono +1, sample -1, analyser +1 | Historical TAVI behavior and sign goldens | provisional | Confirm against physical PUMA readbacks. |
| Crystals | PG(002); test mono variant changes d-spacing | Live descriptor | provisional | Confirm slab counts, gaps, mosaic, and test-crystal meaning. |
| Monochromator focusing | Parallel-beam formula; minimum RH 2.0 m and RV 0.5 m | Legacy model comments | provisional | Confirm formula assumptions and mechanical limits. |
| Analyser focusing | Point-source formula; RH minimum 2.0 m; RV fixed 0.8 m | Legacy model comments | provisional | Confirm current analyser mechanics. |
| Collimation and slits | Four positions, with stacked alpha-2 options | Live descriptor/model | provisional | Confirm available blades, locations, apertures, and defaults. |
| NMO | Optional vertical/horizontal experimental model | Central NMO component and local geometry comments | provisional | Confirm geometry, coatings, and intended commissioning state. |
| Velocity selector | Optional test component | TAVI user guide says it does not exist on PUMA | conflicting | Keep visibly experimental; confirm whether it should remain. |
| Detector | One ideal 25.4 mm by 1 m Monitor | Live model | provisional | Replace with measured detector geometry/efficiency if needed. |
| Source spectrum | Mono or simplified Maxwellian source | Live model | provisional | Obtain a measured or facility-approved spectrum. |

The current code, not this table, remains executable truth. Accepted evidence
must update both the code and this record in the same reviewed change.
