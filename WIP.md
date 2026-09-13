# TAVI — work in flight

> **Status:** live
> **Authority:** canonical for the state of work in flight

States: `pinned` | `in progress, slice n of m` | `landed untested` | `done` | `remove`.

## Design goals

**State:** pinned

Done when: the operator has written the body of DESIGN_GOALS.md.

## Audit ledger: new instruments and crystal bending

**State:** pinned

4 entries remain in the [audit ledger](docs/audits/new-instruments-crystal-bending.md) (9, 11, 12 from the harvest; 14 opened by branch (iv); 15, also opened by branch (iv), cleared by REL-5), each with its evidence and, where it is a defect, an isolated reproducer. Four themed branches have landed; what is left is pinned for a fresh session, which is why this is `pinned` rather than in progress.

### What landed

Branch (i) — API/GUI input validation and scan preview — PR #33 (`c99b67a9`), clearing entries 1, 3, 4 and 6.

Branch (ii) — shared TAS physics — PR #34 (`cba504e4`), clearing entry 2. A zero crystal take-off angle now runs flat instead of raising. Operator's ruling, 2026-09-12: a zero take-off is a legal instrument state — the direct-beam position, an operator mistake rather than an instrument fault — so the instrument runs it and returns flat, rather than refusing the point at feasibility, which would make a legitimate direct-beam configuration unreachable. The rule lives in `ideal_curvature` (shared policy, authoritative) with a guard in the default `optical_radii` so the shipped formula stays total, and is checked BEFORE the `focusing_known` refusal, because at zero take-off there is no focusing to model. `set_crystal_bending` now stores a zero-take-off magnitude rather than leaving the previous point's radius.

Branch (iii) — package hygiene, mechanical half — PR #35 (`a9520d16`), clearing entries 10, 7, 8 and 5.

Branch (iv) — direct transmission — PR #37 (`0c41b52c`), clearing entry 13. Operator's rulings, 2026-09-13: a zero two-theta on any axis is a legal direct-transmission point, never infeasible for a McStas or GUI scan; energy flows downstream only, so a transmitting crystal's Ei or Ef is recorded absent (`null`), never invented — "Ef = Ei" and "Ei = Ef" were rejected as shoehorning a white-beam situation into the Bragg paradigm (Takin and vTAS model no such state either); the analytic engine assumes non-degenerate geometry and enforces it, skipping any marked point and reporting it infeasible at validation for `deterministic` jobs; the sample axis (forward scattering, ruling 7) records its determined energies and |Q|, is marked, and is refused by the analytic engine alone because Cooper-Nathans has no resolution function there; exact zero for the crystals, a 1e-5° float-noise tolerance for a *solved* sample angle only; `Q = 0` in the Q-space modes stays refused as `zero_q`. The record is `metadata['transmission']`, `ScanResult.transmission_points`, and `skipped_points` kind `transmission`; `POST /validate` accepts `engine`/`seed`/`noiseless`; `GET /resolution` refuses forward scattering. Decision record in `docs/CONFIGURABLE_INSTRUMENTS.md` §22.4.

REL-5 (changelog and release program, executor session, 2026-09-13) clears entry 15: `CLAUDE.md` is now tracked so a fresh clone or worktree passes `tests/test_documentation.py`.

Six entries were cleared across the four branches and six were opened by work that found them, so the ledger went 9 → 5, not 9 → 0.

### What was missed, and why each remaining entry is pinned

The operator stopped the third branch halfway and asked whether the process was earning its keep. The measured answer was: real defects fixed and verified, 84 tests added, but a full seat round spent on deleting twelve dead assignments. The remaining three entries were pinned rather than rushed, because each has blast radius that the mechanical half did not. Everything discovery turned up on them is recorded here so a fresh session starts from evidence.

**Entry 9 — one geometry authority per package.** The entry understates the problem. PUMA has **three** copies of its arm lengths, not two: `instruments/puma/plugin.py:239-242` passes raw literals (`2.150, 2.290, 0.880, 0.750`) into its descriptor `Geometry(...)`, separate from its own `_L1.._L4` at `:135`, while IN8, IN12 and PANDA pass their constants through. A naive registry-wide parity assertion would also break PANDA: `instruments/panda/MODEL_STATUS.md:123-126` says its `l1_source_mono = 5.00` is a virtual-source coordinate and explicitly *not* the source-to-monochromator distance, and `instruments/validation.py:164-168` already exempts that field for exactly that reason. So a parity test must assert L2/L3/L4 equal and compare L1 only where the package declares it a true source-mono distance. Operator's ruling, 2026-09-12: one `geometry.py` per package read by both model and descriptor, chosen over making the descriptor the authority because the plugin must stay import-light for the registry's lazy listing. The model's `L1..L4` stay mutable runtime state SEEDED from the constants, never aliased — IN12's L3 is documented "genuinely variable".

**Entry 11 — module-fixed reporting mismatch.** Never independently reproduced. It was inherited from deleted entry 3's carve-out and re-raised by PR #33's pre-PR review. Reproduce it first and stop if it does not reproduce as described; do not fix a phantom.

**Entry 12 — test isolation of `config/parameters.json`.** The widest blast radius of the three: it changes the starting state of every test that constructs a controller. Discovery established that there is no existing seam for this file (four bare relative literals at `TAVI_PySide6.py:5432`, `:5434`, `:5446`, `:5601`, and `:5446` is where save *creates* the directory); that `tests/test_editable_number_format.py:67` pins one of those literals as *source text* and will break; and that `tests/test_rva_gui_axis_policy.py:301` isolates its own save/load by **changing the working directory**, which an absolute override would silently bypass. A green suite after such a change proves only that it passes with a clean file — the acceptance needs a run against a deliberately hostile `config/parameters.json` (`"rhm_ideal_locked": true` is the measured trigger). `config/instrument_selection.json` is a second saved-state channel through the same mechanism and is not closed by this entry.

**Entry 14 — the analytic engine ignores the hidden misalignment.** Opened by branch (iv) at the operator's prompt. The deterministic engine converts each point's Q to HKL through a sample mount built from the launch values alone (`TAVI_PySide6.py` `_sample_q_to_hkl` → `_build_sample_mount(vals)`), while McStas receives `mis_omega_param`/`mis_chi_param` from the instrument state (`set_misalignment`). In a training exercise with a hidden misalignment the two engines disagree by the hidden offset and the analytic one is the wrong one. Structurally confirmed 2026-09-13, not reproduced: write the reproducer first.

**Entry 15 — cleared by REL-5 (2026-09-13):** `CLAUDE.md` is tracked; see What landed.

Not in the ledger, named but not filed: the `collimation` container shares a value-validation gap with the other descriptor-driven containers — the API parses it with a dictionary-type check and never checks a slot's value against its declared allowed set; `p_float` still accepts `"nan"` for some thirty numeric API fields; `k2angle(0, d)` divides by zero with a RuntimeWarning in the forward direction, which no caller reaches from a marked point; runtime skips write `skipped_points` kind `infeasible` while validation-time entries use `physical_infeasible`/`geometry_solver_error` (documented as is; harmonising is a small contract change); `POST /validate` answers `would_queue: true` for a partially infeasible body that `POST /scan` refuses without `allow_partial` (pre-existing convention, same for ordinary infeasible points); and ISAR does not read `result.transmission_points`, so a McStas transmission point stays a valid analysis point there — an ISAR board item, TAVI's side is done.

Done when: the ledger is empty and deleted.

## Bounded snapshot queue option

**State:** pinned

The scan pipeline's snapshot queue is unbounded (operator ruling 2026-09-12, recorded under Decisions in [docs/PIPELINE_DESIGN.md](docs/PIPELINE_DESIGN.md)). If running the whole scan ahead of execution ever shows a measured cost, a configuration key selecting a bounded prep queue is the remedy.

Done when: a config key selects a bounded prep queue, or the operator drops this item.

## Config file reference

**State:** pinned

`config/parameters.json`, `config/api_config.json`, `config/mcstas_config.json` and `config/instrument_selection.json` are operator-facing and no document describes their shape; the 2026-09-12 documentation audit's fresh reader could not answer "what is in the config files" from the documents.

Done when: one document, reached from [docs/READING_GUIDE.md](docs/READING_GUIDE.md), describes each file's keys, defaults and who writes it.

## Documentation baseline

**State:** done

The first documentation audit and setup pass under the shared standard (profile Complex) landed as PR #36 (`d05f4053`): banners, the map [docs/READING_GUIDE.md](docs/READING_GUIDE.md), the deviation block, [DESIGN_GOALS.md](DESIGN_GOALS.md) as a skeleton, four dissolutions, and the corrections the audit found. The stamp is on the map; the next regular audit is weekly and the first deep audit falls due 2026-10-12.

## Release 1.3: prerequisites

**State:** pinned

The changelog pipeline is in (PR #38, 77f73e46, 2026-09-13): `tavi.__version__`,
`changelog.d/` with `release.toml` and thirty fragments since v1.2.0.

Ruling 2026-09-13 (Agentic-Control-Scheme `44b373a`): the release tool does not
handle installers. A release is the version bump, the changelog, the PR, the tag
and the GitHub release with its notes; an installer is a post-tag artifact,
written after the tag exists and uploaded separately (recipe: installer design
document §22 "Release recipe").

Before `/release 1.3.0`:

- The operator reads the preview
  (`python <ACS>\bin\changelog.py preview --version 1.3.0 --root .`) and
  reworded fragments are edited to match.
- Audit ledger entry 14 (the analytic engine ignores a hidden misalignment) is
  open; the analytic-engine fragment says "approximate" until it closes.
- The operator's final audit.

After the tag:

- The Windows 1.3 installer, with the phonon-map step
  (`components/Pb_dft_phonons.dat` via `tools/make_pb_assets.py`), cold-tested,
  committed, and uploaded (recipe: installer design document §22 "Release
  recipe").
- A macOS installer, optional, same route.

The two fragmentless commits are resolved: the GUI hints commit has a fragment
(this commit); the env-setup repair is developer tooling, none.

Done when: v1.3.0 is published with its changelog and notes, the Windows
installer uploaded, and this entry is deleted.

## Audit ledger: release 1.3

**State:** pinned

The [release 1.3 audit](docs/audits/release-1-3.md) records two independently confirmed blockers in GUI energy-derived branches and API angle defaults, with the existing optional and post-release work kept separate.

Done when: the ledger is empty and deleted.
