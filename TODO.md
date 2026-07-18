# TAVI — ongoing TODO

Living list. Grouped by theme, roughly dependency-ordered within each group.
Design references: `docs/CLOSED_LOOP_DESIGN.md` (system capstone — read first),
`docs/CONTROL_FEATURES_DESIGN.md` (feature designs + roadmap §9),
`docs/LLM_HARNESS_DESIGN.md` (measurement driver), `docs/API_USER_GUIDE.md`
(live API reference). Last updated: 2026-07-03.

## Closed-loop enablers (drive the ISAR/driver integration)

- [x] **Resolution ellipsoids** — `tavi/resolution.py` (Cooper–Nathans **and Popovici**,
      numpy only), plugin `resolution_config()` adapters (PUMA + IN8), `GET /resolution`,
      Utilities → Resolution calculator dialog with projection ellipses. Prerequisite
      of the deterministic engine.
      → CONTROL_FEATURES §5. Cross-check target: ISAR's `cn_energy_fwhm` must agree.
      Done: milestones 1–5 (resolution module, adapters, API, GUI dialog).
- [x] **Deterministic engine mode** — analytic S(Q,ω) ⊗ CN/Popovici + seeded Poisson
      behind the same API/queue/SSE; `engine`/`seed`/`noiseless` provenance on jobs;
      ONE ground-truth sample config shared with the McStas component. Depends on
      resolution module.
      → CONTROL_FEATURES §6, CLOSED_LOOP §6 (fidelity ladder tier 1).
      Done: milestone 6 (`tavi/deterministic_engine.py`), milestone 7 (POST /scan
      `engine`/`seed`/`noiseless` + `GET /schema` `engines` + `_launch_summary`
      provenance + `_run_scan_deterministic` worker branch), milestone 8 (GUI engine
      selector, API guide, this list). Deterministic result stamps `cn_valid` +
      `invalidations`; brightness is a documented per-sample calibration.
- [ ] **Virtual instrument clock** — per-axis velocities in the descriptor; per-job
      `experimental_time` = counting + axes-movement (angle-map metric); session total
      in /state and journal. Needed for honest driver benchmarking.
      → CONTROL_FEATURES §7.
- [ ] **Point-list (non-uniform) scans** — `scan_points` body form; reject duplicates,
      auto-sort with validation note. Small, independent.
      → CONTROL_FEATURES §8.
- [ ] **Expose sample selection via the API** — currently GUI-only; blocked the first
      closed-loop phonon run until manually switched. Field in `_api_field_map` +
      schema `allowed` values from the sample library.
      → CLOSED_LOOP §7 payload gaps.
- [ ] **Per-scan truth in the data payload** — sample temperature, mono/ana/sample
      mosaics, scattering senses, vertical collimations. Each currently a card
      constant on the ISAR side; payload truth makes the CN resolution trustworthy
      per scan. → CLOSED_LOOP §7 payload gaps, ISAR `tavi.policy.toml` comments.
- [ ] **σ-calibration campaign support (closed-loop Phase 0)** — known-ω scans across
      q and ncount against the analytic Phonon_DFT truth (acoustic E = 6·sin(πq/2));
      mostly a driver/ISAR exercise, but TAVI hosts the runs. ~1e8 neutrons/point.
      → CLOSED_LOOP §5, §8.

## Control features (designed, not started)

Roadmap order per CONTROL_FEATURES §9:

- [ ] **goto CEN/COM/MAX** — `tavi/scan_fits.py`, `POST /goto`, display-dock buttons.
      Highest-value, self-contained. → CONTROL_FEATURES §1.
- [ ] **Path (vector) scans** — `scan_path` body + GUI "Path" mode + point generator;
      `display_dock._get_axis_label` needs a path/|q| case. → CONTROL_FEATURES §2.
- [ ] **Batch submission + campaigns** — `POST /scans`, `Campaign`/`CampaignRegistry`,
      campaign endpoints, grouped job table. → CONTROL_FEATURES §3.
- [ ] **Measurement intents (recipes)** — rocking curve, θ–2θ, const-Q E-scan.
      Lowest priority; needs §1–§3. → CONTROL_FEATURES §4.

## API polish (small, found in live testing)

- [ ] **Reject unknown top-level POST body keys (400)** — currently silently ignored;
      an LLM sending `scan_commands` instead of `parameters.scan_command1` validates
      the GUI's current state instead of erroring. Known footgun.
- [ ] **Quiet journal noise from isolation restore** — isolated submissions log
      duplicate "api: set …" parameter entries (apply + restore both record).
- [ ] **429 Retry-After from real queue drain** — currently the ETA estimate when
      available, constant 30 s otherwise; revisit once campaigns land.

## GUI

- [ ] **Scroll-lock the two QDoubleSpinBox in `ub_matrix_dock`** — same accidental
      wheel-capture issue fixed for combo boxes (`NoScrollComboBox`); deferred by
      scope at the time.

## Housekeeping

- [ ] **Test-runner note** — full `pytest tests/` crashes the interpreter
      (mcstasscript import, fault 0xc06d007f). API test-file allowlist:
      `test_api_server.py test_scan_jobs.py test_runtime_tracker_*.py
      test_api_validation_schema.py test_api_journal_plot_isolation.py
      test_instrument_selection.py` (+ matplotlib files need the env's
      `Library\bin` on PATH). Document in CLAUDE.md / a tests README.


Others:
- vTAS style graphical interface [STARTED]
  - Resolution function display
  - E-mode
- HKL cut-along-areas with saved data?
