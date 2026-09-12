# TAVI — work in flight

> **Status:** live
> **Authority:** canonical for the state of work in flight

States: `pinned` | `in progress, slice n of m` | `landed untested` | `done` | `remove`.

## Design goals

**State:** pinned

Done when: the operator has written the body of DESIGN_GOALS.md.

## Audit ledger: new instruments and crystal bending

**State:** in progress, branch 2 of 3

8 findings and opportunities are queued in the [audit ledger](docs/audits/new-instruments-crystal-bending.md), each with its evidence and, where it is a defect, an isolated reproducer.

The harvest runs as three themed branches.

Branch (i) — API/GUI input validation and scan preview — landed as PR #33 (`c99b67a9`), clearing entries 1, 3, 4 and 6. Three entries were opened by work found during it: 10, a partial `slits_mm` patch raising `KeyError` at launch (the one descriptor container still without a defaults refill); 11, the module-fixed reporting mismatch that the original entry 3 had explicitly deferred and would otherwise have taken with it when deleted; and 12, the suite inheriting the operator's saved `config/parameters.json`, which made two tests pass in a fresh worktree and fail on the main checkout from identical source.

Branch (ii) — shared TAS physics — landed as PR #34 (`cba504e4`), clearing entry 2. A zero crystal take-off angle now runs flat instead of raising. The operator's ruling, 2026-09-12: a zero take-off is a legal instrument state — it is the direct-beam position, an operator mistake rather than an instrument fault — so the instrument runs it and returns flat, rather than refusing the point at feasibility, which would make a legitimate direct-beam configuration unreachable. The rule lives in `ideal_curvature` (shared policy, authoritative) with a guard in the default `optical_radii` so the shipped formula stays total, and it is checked BEFORE the `focusing_known` refusal, because at zero take-off there is no focusing to model. `set_crystal_bending` now stores a zero-take-off magnitude rather than leaving the previous point's radius in place.

Remaining:
- Branch (iii) — package hygiene: entries 5, 7, 8, 9, plus 10, 11 and 12.
- Entry 13 — a fresh session, see below.

Operator rulings recorded for branch (iii): samples stay instrument-independent, so the descriptor's filter-or-extend promise is deleted from `tavi/sample_library.py`, `instruments/descriptor.py` and `docs/CONFIGURABLE_INSTRUMENTS.md` §19 and enforced in package validation, rather than honoured in the builders (entry 8); and each package gets one `geometry.py` holding its arm lengths, read by both its model and its descriptor, chosen over making the descriptor the authority because the plugin must stay import-light for the registry's lazy listing (entry 9).

Done when: the ledger is empty and deleted.

## Direct-beam energy and |Q|: a convention to choose

**State:** pinned

Ledger entry 13, split out of branch (ii) deliberately rather than patched inside it. Making a zero take-off runnable exposed that several quantities derived from it have no determined value, and the obvious remedy does not work.

The operator chose "record what is determined, omit what is not" (keep `Ei` from A1, omit `Ef`). It was implemented and then WITHDRAWN, unpushed, because an absent `Ef` propagates into `_background_q_magnitude`, which needs a number for the per-point resolution kernel on every deterministic-engine point — `float(None)` raises, so the honest recording crashes the engine on exactly the point the ruling says must run. Branch (ii) therefore merged with the pre-existing `fixed_E` fallback intact: unchanged behaviour, not a regression, and not yet improved.

Two candidate conventions are written up in entry 13 as **B** (omit what is undetermined, and teach `|Q|` and the resolution kernel to cope) and **C** (an elastic convention for a transmitting analyser: `Ef = Ei`, `deltaE = 0`). Note that the affected region is a neighbourhood of zero, not a single point — at A4 = ±1° the recorded `Ef` is already 23859 meV, because inverting Bragg near zero take-off diverges.

Done when: the operator has chosen B or C and the chosen convention has landed.
