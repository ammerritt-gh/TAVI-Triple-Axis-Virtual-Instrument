# Handoff — scan-command programme: consumer sweep (U5)

> **Status:** live
> **Authority:** the frontier of the scan-command programme (job j92f2a0718dc1) after U1–U4; ISAR and TAS_MCP still to move

You pick up the last unit of TAVI programme **j92f2a0718dc1** ("scans that say what they do"). U1–U4 are on TAVI main (origin/main **9c8fbb30**); the TAVI parent job and its lanes are **closed**. U5 changes two *other* repositories, so it runs as **new managed jobs, one per repository**, each opened, briefed and approved on its own. The operator names the tiers; the previous session recommended **ISAR at T2** (several files, live tests against a running TAVI) and **TAS_MCP at T1** (published-name rename and one contract test). Ask the operator before opening.

Read first:
- Approved design (TAVI programme): `C:\Users\AMM\AppData\Local\ACS\state\v1\artifacts\j92f2a0718dc1\4a88519835161042f9542e36b147b621e899d0a892c1e94a2c34dbf723e49312`
- Plan, section U5 (S5.1, S5.2): `C:\Users\AMM\AppData\Local\ACS\state\v1\artifacts\j92f2a0718dc1\b04b5f575e842ba2a032760359f66c9742c3c5de98e17f5e9adeb4dd9b410ff3`
- Running notes and every ruling since the plan: `C:\Users\AMM\AppData\Local\Temp\claude\tavi-j92f2a0718dc1-morning.md`
- TAVI's client-facing contract: `docs/API_USER_GUIDE.md` (§15 is the break and the old → new tables; §7 scan grammar), `tavi/quantities.py` (the naming registry), `docs/INSTRUMENT_LAYOUT.md` (angle table, Conventions).
- Each repo's own agent instructions (`..\ISAR\AGENTS.md` / CLAUDE.md; `MCPs\TAS_MCP` likewise) and TAVI's `AGENTS.md` "dependency hub" bullet.

## What changed in TAVI that consumers meet

- **API version required:** every mutating or validating request (`PATCH /parameters`, `POST /scan`, `POST /validate`, `PUT /background`) must carry `"api_version": 2`; missing or other is HTTP 400 before any state changes. Results, SSE, `/schema` and saved outputs carry the version.
- **Canonical names everywhere public.** ILL numbering: A1 mono θ (derived, read-only), **A2 mono 2θ**, A3 sample rotation, **A4 sample 2θ**, A5 analyzer θ (derived), **A6 analyzer 2θ** — TAVI's *old* A2 was sample 2θ and old A4 analyzer 2θ, so old A-number scan text means something else now. Canonical IDs such as `sample_two_theta_deg`, `sample_rotation_deg`, `energy_transfer_mev`, `incident_wavevector_inv_angstrom`; NICOS/short aliases (`stt`, `sth`, `omega`, `psi` → sample rotation, `mtt`, `att`, `sgl`, `sgu`, `rhm`…) still accepted on input. Retired/unknown/duplicate keys are refused with 400. `chi`, `phi`, `kappa`, `A1`, `A5` refused as inputs.
- **Slits:** per-gap keys `slit.<stable_id>.horizontal_gap_mm` / `.vertical_gap_mm` (scan aliases `<id>_hgap`/`_vgap`), millimetres; old metre-valued names refused with their replacement. Slit scans run on McStas; refused on the deterministic (analytic) engine.
- **Saved state v5; outputs versioned;** pre-break output folders are refused by TAVI's loader.
- **Hard refusals** (force and allow_partial pass none): command pairs the plan cannot honour (e.g. H with A4, two names for one quantity, arc scan under a plane lock); zero, wrong-sign or longer-than-range steps; a radius range crossing zero; an API patch whose crystal 2θ disagrees with a patched energy (> 0.01°); a scan over **100,000 points**.
- **No overshoot:** a step that does not divide the range stops at the last point inside it (`0 10 4` → 0, 4, 8) and returns a soft **`warnings`** list entry on `/validate` and `/scan` (tolerance 1e-5 × intervals, so `%g`-rounded steps like `deltaE 0 10 0.0502513` still reach 10).
- **API stage solve (operator ruling):** a request whose commands select the direct-motor calculation (A3/A4/arc rocking scans, slit, radius, plain point) and whose patch names H/K/L, Q, lattice, sample or energies but no sample-stage motor gets the stage solved from the patch first; unreachable → 400; explicitly patched motors are kept.
- **Message format:** API single-command refusals now read `Command N: <message>`.
- **New point-metadata keys:** `requested_q_inv_angstrom`, `realized_q_inv_angstrom` (None unless a locked-plane Q point).
- **`ub_matrix.py` training/fitting functions changed signature** (U1 removed the `corrections` argument): `encode_training`, `decode_training`, `generate_training_exercise`, `grade_alignment`, `calculate_U_two_peaks`, `refine_U_matrix`, `alignment_residuals`, `ObservedPeak.q_mount`. The four modules ISAR vendors (`reciprocal_space`, `sample_mount`, `tas_geometry`, `ub_matrix`) otherwise kept their public signatures.

## S5.1 ISAR (`C:\Users\AMM\Documents\Github\Science\ISAR`)

Move to canonical names, `api_version: 2` and the new refusals:
- `isar/drive/instrument/tavi_client.py` (send `api_version`; canonical keys).
- `request_realization.py` (~202–219), the request writer.
- `isar/parsers/tavi.py`: check the result's version marker and refuse a pre-break result rather than mapping old keys; missing H/K/L/ΔE default to zero (~218–225) and an unknown scan variable becomes an angle axis (~383–400) — both become refusals or canonical lookups; know the `energy_transfer_mev` axis name.
- `isar/drive/acquisition/grid_adapters.py:45` still predicts the retired overshoot expansion; fixture `tests/drive/test_grid_adapters.py:80-82` pins 0, 0.4, 0.8, 1.2 → must match TAVI's no-overshoot rule. Also confirm ISAR never requests > 100,000 points, never sends a radius range crossing zero or a 2θ disagreeing with a patched energy (a grep found none today).
- `isar/drive/acquisition/scan_grid.py:136-139` (step widening at the point cap) — confirm its `%g` steps still reach the end under TAVI's tolerance.
- `isar/geometry/`: re-sync only the `ub_matrix.py` functions listed above, if ISAR carries them, each with its provenance header.
- Its tests, `live` tests, closed-loop callers and fixtures.
- Evidence: ISAR's suite, and its live tests against a TAVI started from main at 9c8fbb30 or later (else marked unrun).

## S5.2 TAS_MCP (`C:\Users\AMM\Documents\Github\MCPs\TAS_MCP`)

Its `tavi` imports keep working (signatures kept apart from the training functions). Tool schemas and outputs that publish TAVI quantities move to canonical names (`sample_two_theta_deg`, `sample_rotation_deg` for `stt_deg`/`sth_deg`, `analyzer_two_theta_deg` for `ana_two_theta_deg`, `energy_transfer_mev` for `energy_transfer_meV`, …), with an audit list of every published name and any deliberately kept; a contract test calls one representative tool and checks its output names; its suite runs.

## TAVI board items owed (WIP.md, main)

The previous session's closeout handles TAVI's own board. U5's jobs should, at their landing, close or update:
- **ISAR client and parser on TAVI's new contract** (`pinned`) — closed by S5.1.
- TAS_MCP published names — S5.2.

## Already settled — do not re-litigate

Operator rulings 2026-10-09/10: hard refusals; ILL/NICOS names; `omega` and `psi` = sample rotation; clean break, stable after; ISAR break window U2→U5 accepted; no overshoot (warning); plane lock followed; API stage solve (a); 100k point cap; internal controller keys stay until a follow-up (amendment 7a, "I'm not worried about breaking saved scans").
