# TAVI — work in flight

> **Status:** live
> **Authority:** canonical for the state of work in flight

States: `pinned` | `in progress, slice n of m` | `landed untested` | `done` | `remove`.

## Design goals

**State:** pinned

Done when: the operator has written the body of DESIGN_GOALS.md.

## Audit ledger: new instruments and crystal bending

**State:** in progress, branch 1 of 3

8 findings and opportunities are queued in the [audit ledger](docs/audits/new-instruments-crystal-bending.md), each with its evidence and, where it is a defect, an isolated reproducer.

The harvest runs as three themed branches. Branch (i) — API/GUI input validation and scan preview — landed as PR #33 (`c99b67a9`), clearing entries 1, 3, 4 and 6. Three entries were opened by work found during it: 10, a partial `slits_mm` patch raising `KeyError` at launch (the one descriptor container still without a defaults refill); 11, the module-fixed reporting mismatch that the original entry 3 had explicitly deferred and would otherwise have taken with it when deleted; and 12, the suite inheriting the operator's saved `config/parameters.json`, which made two tests pass in a fresh worktree and fail on the main checkout from identical source.

Remaining:
- Branch (ii) — shared TAS physics: entry 2, zero take-off returns flat. The operator's ruling, 2026-09-12: a zero crystal take-off angle is a legal instrument state (it is the direct-beam position), not an error, so the producer returns flat on BOTH planes rather than refusing or letting each formula find its own limit — the vertical law's limit is the tightest bend, which is nonsense for a beam that is not scattering. `set_crystal_bending`'s existing zero-take-off guard, which leaves the previous point's radius in place, must store flat instead, since zero take-off is now a solved state rather than an unsolved one.
- Branch (iii) — package hygiene: entries 5, 7, 8, 9, plus 10, 11 and 12.

Operator rulings recorded for branch (iii): samples stay instrument-independent, so the descriptor's filter-or-extend promise is deleted from `tavi/sample_library.py`, `instruments/descriptor.py` and `docs/CONFIGURABLE_INSTRUMENTS.md` §19 and enforced in package validation, rather than honoured in the builders (entry 8); and each package gets one `geometry.py` holding its arm lengths, read by both its model and its descriptor, chosen over making the descriptor the authority because the plugin must stay import-light for the registry's lazy listing (entry 9).

Done when: the ledger is empty and deleted.
