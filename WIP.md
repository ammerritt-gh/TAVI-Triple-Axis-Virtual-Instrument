# TAVI — work in flight

> **Status:** live
> **Authority:** canonical for the state of work in flight

States: `pinned` | `in progress, slice n of m` | `landed untested` | `done` | `remove`.

## Design goals

**State:** pinned

Done when: the operator has written the body of DESIGN_GOALS.md.

## Audit ledger: new instruments and crystal bending

**State:** pinned

4 entries remain in the [audit ledger](docs/audits/new-instruments-crystal-bending.md), each with its evidence and, where it is a defect, an isolated reproducer. The three themed branches the harvest was planned as have all landed; what is left is pinned for a fresh session or waiting on an operator decision, which is why this is `pinned` rather than in progress.

### What landed

Branch (i) — API/GUI input validation and scan preview — PR #33 (`c99b67a9`), clearing entries 1, 3, 4 and 6.

Branch (ii) — shared TAS physics — PR #34 (`cba504e4`), clearing entry 2. A zero crystal take-off angle now runs flat instead of raising. Operator's ruling, 2026-09-12: a zero take-off is a legal instrument state — the direct-beam position, an operator mistake rather than an instrument fault — so the instrument runs it and returns flat, rather than refusing the point at feasibility, which would make a legitimate direct-beam configuration unreachable. The rule lives in `ideal_curvature` (shared policy, authoritative) with a guard in the default `optical_radii` so the shipped formula stays total, and is checked BEFORE the `focusing_known` refusal, because at zero take-off there is no focusing to model. `set_crystal_bending` now stores a zero-take-off magnitude rather than leaving the previous point's radius.

Branch (iii) — package hygiene, mechanical half — PR #35 (`a9520d16`), clearing entries 10, 7, 8 and 5.

Five entries were cleared across the three branches and four were opened by work that found them, so the ledger went 9 → 4, not 9 → 0.

### What was missed, and why each remaining entry is pinned

The operator stopped the third branch halfway and asked whether the process was earning its keep. The measured answer was: real defects fixed and verified, 84 tests added, but a full seat round spent on deleting twelve dead assignments. The remaining three entries were pinned rather than rushed, because each has blast radius that the mechanical half did not. Everything discovery turned up on them is recorded here so a fresh session starts from evidence.

**Entry 9 — one geometry authority per package.** The entry understates the problem. PUMA has **three** copies of its arm lengths, not two: `instruments/puma/plugin.py:239-242` passes raw literals (`2.150, 2.290, 0.880, 0.750`) into its descriptor `Geometry(...)`, separate from its own `_L1.._L4` at `:135`, while IN8, IN12 and PANDA pass their constants through. A naive registry-wide parity assertion would also break PANDA: `instruments/panda/MODEL_STATUS.md:123-126` says its `l1_source_mono = 5.00` is a virtual-source coordinate and explicitly *not* the source-to-monochromator distance, and `instruments/validation.py:164-168` already exempts that field for exactly that reason. So a parity test must assert L2/L3/L4 equal and compare L1 only where the package declares it a true source-mono distance. Operator's ruling, 2026-09-12: one `geometry.py` per package read by both model and descriptor, chosen over making the descriptor the authority because the plugin must stay import-light for the registry's lazy listing. The model's `L1..L4` stay mutable runtime state SEEDED from the constants, never aliased — IN12's L3 is documented "genuinely variable".

**Entry 11 — module-fixed reporting mismatch.** Never independently reproduced. It was inherited from deleted entry 3's carve-out and re-raised by PR #33's pre-PR review. Reproduce it first and stop if it does not reproduce as described; do not fix a phantom.

**Entry 12 — test isolation of `config/parameters.json`.** The widest blast radius of the three: it changes the starting state of every test that constructs a controller. Discovery established that there is no existing seam for this file (four bare relative literals at `TAVI_PySide6.py:5423`, `:5425`, `:5436`, `:5593`, and `:5436` is where save *creates* the directory); that `tests/test_editable_number_format.py:67` pins one of those literals as *source text* and will break; and that `tests/test_rva_gui_axis_policy.py:301` isolates its own save/load by **changing the working directory**, which an absolute override would silently bypass. A green suite after such a change proves only that it passes with a clean file — the acceptance needs a run against a deliberately hostile `config/parameters.json` (`"rhm_ideal_locked": true` is the measured trigger). `config/instrument_selection.json` is a second saved-state channel through the same mechanism and is not closed by this entry.

Not in the ledger, named but not filed: the `collimation` container shares a value-validation gap with the other descriptor-driven containers — the API parses it with a dictionary-type check and never checks a slot's value against its declared allowed set.

Done when: the ledger is empty and deleted.

## Direct-beam energy and |Q|: a convention to choose

**State:** pinned

Ledger entry 13, split out of branch (ii) deliberately rather than patched inside it. Making a zero take-off runnable exposed that several quantities derived from it have no determined value, and the obvious remedy does not work.

The operator chose "record what is determined, omit what is not" (keep `Ei` from A1, omit `Ef`). It was implemented and then WITHDRAWN, unpushed, because an absent `Ef` propagates into `_background_q_magnitude`, which needs a number for the per-point resolution kernel on every deterministic-engine point — `float(None)` raises, so the honest recording crashes the engine on exactly the point the ruling says must run. Branch (ii) therefore merged with the pre-existing `fixed_E` fallback intact: unchanged behaviour, not a regression, and not yet improved.

Two candidate conventions are written up in entry 13 as **B** (omit what is undetermined, and teach `|Q|` and the resolution kernel to cope) and **C** (an elastic convention for a transmitting analyser: `Ef = Ei`, `deltaE = 0`). Note that the affected region is a neighbourhood of zero, not a single point — at A4 = ±1° the recorded `Ef` is already 23859 meV, because inverting Bragg near zero take-off diverges.

Done when: the operator has chosen B or C and the chosen convention has landed.
