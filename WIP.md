# TAVI — work in flight

> **Status:** live
> **Authority:** canonical for the state of work in flight

States: `pinned` | `in progress, slice n of m` | `landed untested` | `done` | `remove`.

## Design goals

**State:** pinned

Done when: the operator has written the body of DESIGN_GOALS.md.

## Remote Windows Monte Carlo installation failure

**State:** landed untested

The launcher repair shipped in **v1.3.2** (2026-10-07; PR #51, which carried
PR #46's commits merged with main, plus the review fixes). Version 1.3.1 was
skipped by operator ruling. Every micromamba call selects the environment by
an explicit prefix. A cold install from the `v1.3.2` tag passed on the
development machine: one Monte Carlo point, `mcrun` reading the `_tavi-env`
per-user config and ignoring a stale `_tavi` one, and an uninstall from the
launcher menu. The release page carries `TAVI-Repair-Launchers.bat`. The record
and the items still open are in
[the installer 1.3.2 handoff](docs/HANDOFF-installer-1-3-1.md).

The evidence and the ruled-out causes stay in
[the spaced-profile handoff](docs/HANDOFF-spaced-profile-install.md); its
§7.2, §7.3, §7.4 and §7.5 defects are still unfixed and still listed there.

The remote acceptance is unchanged and is what closes this entry: the affected
user runs her ordinary shortcut and her usual Monte Carlo run after the field
repair (`installer/TAVI-Repair-Launchers.bat`, which rebinds an existing
1.3.0 installation's launchers without reinstalling). No new probe, no
repeated revised diagnostics.

<details>
<summary>The investigation that led here (2026-09-17, still accurate)</summary>

The spaced-profile build-4 installation passes the example instrument's serial
and MPI tests, but its TAVI Monte Carlo failure is not yet identified. The
[handoff](docs/HANDOFF-spaced-profile-install.md) records the evidence and the
one-transfer USB constraint. The support recorder in `tools/support/` captures
an actual GUI failure, including the first-point McStasScript command and raw
output. The strongest current candidate is the generated launcher's missing
environment root: `run -n tavi` can reopen the old profile environment while the
Doctor selects the relocated one. This mechanism reproduced locally; the remote
launch environment is unknown. The recorder explicitly selects the repaired
prefix, so it may mask this launcher fault. Hold the recorder; another Doctor run
is not needed before repairing the launcher. The handoff's fresh-session brief
and §12 give the later fix scope (Run, shell and repair/update), existing-install
repair and local/remote acceptance. Memory has no positive evidence and is lower
priority; the output-path defect is pinned separately below.
Installer build-4 and old Doctor edits remain separate uncommitted work.
</details>

Done when: corrected launchers select the intended environment and the affected
user's ordinary Monte Carlo run succeeds, or evidence establishes and resolves
another cause. Do not require a new report or request repeated revised probes.
Still owed: the affected user's run after `TAVI-Repair-Launchers.bat` from the
v1.3.2 release page (or a fresh v1.3.2 install).

## Monte Carlo output folders containing spaces

**State:** pinned

McStasScript's unquoted `-d` output path breaks the first-point run when the full
save path contains spaces. Reproduced with the actual GUI Run button; see the
[remote-install handoff §10](docs/HANDOFF-spaced-profile-install.md#10-one-transfer-support-recorder-and-local-findings-2026-09-17).
The operator believes the affected user's save folder had no spaces, so this is
a separate confirmed defect, not the assumed explanation of her installation.

Done when: first-point Monte Carlo runs succeed for both spaced and space-free
output paths through the actual GUI.

## Audit ledger: new instruments and crystal bending

**State:** pinned

3 entries remain in the [audit ledger](docs/audits/new-instruments-crystal-bending.md) (9, 11, 12 from the harvest; 14 opened by branch (iv) and cleared by U1 of the scan-command programme; 15, also opened by branch (iv), cleared by REL-5), each with its evidence and, where it is a defect, an isolated reproducer. Four themed branches have landed; what is left is pinned for a fresh session, which is why this is `pinned` rather than in progress.

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

**Entry 14 — cleared by U1 of job j92f2a0718dc1 (PR #55, 2026-10-09):** the corrections and hidden zero errors are retired, training is mount-only, and a test shows both engines present the same (H, K, L) at the same commanded point; the ledger entry is deleted.

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

## Audit ledger: release 1.3

**State:** pinned

The [release 1.3 audit](docs/audits/release-1-3.md) recorded two independently confirmed blockers in GUI energy-derived branches and API angle defaults; both landed in PR #39 (`54b35951`, 2026-09-14) with per-instrument acceptance tests, plus three API-launch repairs the external reader found on top (energy patches re-derive their crystal angle, a fixed-energy patch moves both energy sides, a non-positive derived energy is refused). The ledger now holds only the optional and post-release pointers to existing entries.

Done when: the ledger is empty and deleted.

## MPI rank default fails on small Linux hosts

**State:** landed untested

Open MPI on Linux refuses more ranks than cores, so the old fixed 30 failed at the first point on ordinary laptops (issue #45); MS-MPI on Windows oversubscribes silently. PR #47 (`613d16fd`, 2026-09-30) made the count a setting: default 4 on every platform (operator ruling, not core-count-aware), set from Config → MPI processes…, stored in `config/settings.json`, frozen per scan and used by every run, record and estimate. Deferred from that job: saving over a corrupt `settings.json` drops its other keys (matters once a second setting lands); the `estimate_scan_seconds` docstring does not mention the same-count filter.

Released in v1.3.2 (2026-10-07). Both installers on the release page are pinned to it, and `POSIX-install-TAVI-v1.3.2.sh` runs a fatal `mcrun -c --mpi=2` compile check. That check has passed `bash -n` and a read only: no Linux or macOS machine (or WSL) was available.

Done when: the POSIX v1.3.2 installer has run on a Linux machine and its MPI check passes there.

## Dev environment still compiles with MSVC

**State:** pinned

`tavi-dev` (`setup-tavi-dev.bat`, `run-tavi-dev.bat`) still relies on Visual Studio and the `vcvars` hook; the installed `tavi` env uses conda-forge GCC since PR #43. Moving the dev env the same way (add `gcc_win-64=16.2.0 msmpi`, write the five overrides into its own `mccode_config.json` after unlinking) removes the split and the noisy activation. The `-B` sysroot quirk and the NCrystal `.lib` path are the overrides most likely to go stale on a McStas or GCC bump. Seen in the v1.3.2 cold install (2026-10-07): the *installed* env also runs a package activation script on every `micromamba run` that calls this machine's Visual Studio `vcvars64.bat` and sets `CC=cl.exe`; McStas still compiled with GCC, and nothing failed. Not yet known on a machine without Visual Studio.

Done when: `setup-tavi-dev.bat` builds the env with GCC and the suite's McStas-touching tests pass without Visual Studio present.

## Crystal orientation: hands-on proofing

**State:** pinned

The crystal-orientation programme (PRs #48–#50: two-arc sample stage, true mount
kept apart from the operator's UB, lock plane, per-peak residuals, Refine Lattice
by crystal system) ships in v1.3.2 on the suite and an offscreen acceptance test
only. Operator, 2026-10-07: "It's fine for now, but pin that we need to proof it
and ensure it's working well." Not yet named: what the proofing run covers. ISAR's
vendored copies of the four geometry modules have not been synced with this work
(16 TAVI commits since 2026-09-29, none in `ISAR/isar/geometry/`).

Done when: the operator has run a hands-on alignment pass (find peaks, Calculate
UB, read residuals, lock a plane, a training exercise) on the real GUI and the
defects it finds are fixed or filed, and ISAR's geometry copy is synced.

## Compact window: blocks, column width, 2/3/4-column layouts

**State:** landed untested

PR #54 (`383a6779`, 2026-10-08) made form groups ~300 px blocks that stack in
View → Column Width → Narrow and pair up in Wide, added View → Layout 2/3/4
columns (first start picks by screen width and height; a 2560 screen opens the
operator's own 3-column arrangement, Wide), put Q beside HKL with Fixed Mode
separate, ordered the Instrument dock by use with Focusing, Modules and Source
folded, moved Save/Load/Defaults to File and Clear Runtime Data (current
instrument only) to Config, and raised the layout file to version 3 (old files
renamed `.bak`). Checked only offscreen in Fusion; the real Windows 11 look has
not been seen. Left for the operator: Reciprocal Space, opened in 3 columns on a
1400–1520 px screen, docks behind the plot and widens the window past the screen
(fix would open it floating there, which moves its documented place); merging
the small Scattering dock into another is deferred by the operator; on-sight
wording (lattice units in the title, "Along x:"/"In plane:", plain Q/HKL
headers) and the 980 px height threshold for 3 columns are open to change.

Done when: the operator has used the new window live on the 27" monitor and the
12" laptop and the defects he finds are fixed or filed, and the Reciprocal Space
placement is ruled.

## Scan commands that say what they do (job j92f2a0718dc1)

**State:** landed untested

U1–U4 landed 2026-10-09/10 (PRs #55–#58, main `9c8fbb30`): psi/kappa
corrections, hidden zero errors and the Misalignment dock retired (training is
mount-only); one naming registry (`tavi/quantities.py`, ILL A1–A6, NICOS
aliases), `api_version: 2` required, saved state v5, versioned outputs; one
point plan (`instruments/rules.py`) compiled at launch, hard pair refusals,
slit scans, no overshoot (warning), a 100,000-point maximum, plugin contract
v1; live field marks with legend. A 55-case solver baseline gates the physics;
the one deliberate change is PUMA's velocity selector. Checked by the suite and
offscreen Qt only. U5 (ISAR, TAS_MCP) runs as separate jobs:
[consumer-sweep handoff](docs/HANDOFF-scan-command-consumers.md).

Left for the operator's GUI tuning pass: "fixed Kf" badges on free-side fields;
radius marks hidden while Crystal Focusing is folded; the legend below the fold
at 1108×851; a badge's upper-half hover can show a neighbour's tooltip; the
inline θ readouts show "A1"/"A5" only as tooltip.

Done when: the operator has used the marks and the new names live and the
defects found are fixed or filed, and U5 has landed.

## ISAR client and parser on TAVI's new contract

**State:** pinned

Since U2 of job j92f2a0718dc1 landed, TAVI main requires `api_version: 2` on
every write (PATCH /parameters, POST /scan, POST /validate, PUT /background)
and names every quantity by canonical ID (ILL A1–A6 numbering; per-gap
`slit.<stable_id>.*_gap_mm`; saved state v5; versioned outputs, pre-break
folders refused), so ISAR's TAVI client and result parser break against main
until U5's sweep: `isar/drive/instrument/tavi_client.py`,
`request_realization.py` (~202-219), `isar/parsers/tavi.py` (missing H/K/L/ΔE
defaults ~218-225, unknown scan variable → angle axis ~383-400,
`energy_transfer_mev`), `isar/drive/acquisition/grid_adapters.py:45` (still
predicts overshoot), their tests, `live` tests, closed-loop callers and
fixtures. TAS_MCP's published names are the second half of U5.

Done when: U5 (S5.1) has landed in ISAR and its live tests pass against TAVI main.

## Motor-zero calibration exercise

**State:** pinned

U1 retired the hidden motor-zero errors and made UB training mount-only.
Operator, 2026-10-09: "we pin it for followup in a new session once this one
lands." A calibration exercise (finding motor zeros) is the follow-up.

Done when: a calibration exercise is designed with the operator and landed, or
the operator drops it.

## Controller internal keys to canonical IDs

**State:** pinned

The controller's launch keys (`mtt`/`stt`/`omega`/`att`/`rhm`…) and the legacy
point-metadata keys still use TAVI's old internal names; they are documented in
plugin contract v1 (`docs/INSTRUMENT_AUTHORING.md`). Operator, 2026-10-10: "7a
is fine. I'm not worried about breaking saved scans."

Done when: they use canonical IDs and `CONTRACT_VERSION` is bumped.

## Small API and housekeeping follow-ups

**State:** pinned

- PATCH /parameters on a radius the installed crystal fixes (e.g. rva on PUMA
  PG(002), fixed 0.8 m) reports applied and silently snaps back; refuse the
  write naming the hardware (API behaviour change). goto CEN already refuses.
- `tests/test_documentation.py` skips because the shared doc checker path is
  stale (`Agentic-Control-Scheme\bin\doc_check.py`), so the doc check never
  runs in the suite.
- Bare `except` blocks in `_update_scan_estimates` and `_count_scan_points` set
  a count of 0 or 1 without logging; a refused >1000-point scan still prints
  "validation deferred until simulation starts".
- PUMA's selector frequency in a direct-motor scan with a transmitting
  monochromator still comes from the typed energy fields.
- Flake watch: `test_mark_updates_leave_focus_selection_style_and_names_alone`
  failed once on focus in a combined targeted run.

Done when: each is fixed or dropped by the operator.
