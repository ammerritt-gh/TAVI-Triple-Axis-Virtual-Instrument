# TAVI — ongoing TODO

Living list. Grouped by theme, roughly dependency-ordered within each group.
Design references: `docs/CLOSED_LOOP_DESIGN.md` (system capstone — read first),
`docs/CONTROL_FEATURES_DESIGN.md` (feature designs + roadmap §9),
`docs/LLM_HARNESS_DESIGN.md` (measurement driver), `docs/API_USER_GUIDE.md`
(live API reference). Last updated: 2026-09-10.

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
- [x] **Independent background-source generation** — `tavi/background.py`
      (`tavi.background/2`, catalog version 2) owns six fixed sources across the
      Environment, Instrument, and Sample categories. Mean sources include a
      composite six-line aluminum powder model; sparse cosmic events use their
      own source-keyed stream and are added after counting noise. Every source has
      its own enable and finite non-negative scale. Surfaces: normalized
      `GET`/wholesale `PUT
      /background`; wholesale per-scan replacement on `POST /scan` and `POST
      /validate`; the complete catalog in `GET /schema`; shared v2 metadata and
      profile/effective fingerprints; a global GUI checkbox beside the engine
      selector plus a modal grouped source editor; and `parameters.json`
      persistence that visibly resets incompatible old state to safe defaults.
      New sessions
      prepare the four pre-existing smooth sources at scale 1 behind a disabled
      global gate; aluminum and cosmic sources start unchecked at scale 1.
      → CONTROL_FEATURES §6.7, ANALYTIC_ENGINE *Background generation*, API guide
      `GET`/`PUT /background`. Campaign clients pin `catalog_version` and stamp
      the complete source request on every scan.
- [ ] **Ray-traced background for McStas** — environment/shielding scattering
      simulated rather than added analytically. Catalog version 2 contains only
      analytic sources; this needs component work plus a cost story (it is
      ray-tracing time, not a per-point closed form).
      → CONTROL_FEATURES §6.5 fidelity-gap row.
- [x] **Historical v1 live McStas background check** — on 2026-07-27, before the
      v2 source contract replaced presets, a paired live PUMA run verified the
      additive Poisson overlay, dedicated seed, provenance, disabled-path
      behavior, and untouched intensity columns. This is implementation history,
      not a current request example; the maintained contract is v2 above.
- [x] **Catalog pinning and canonical source state** — v2 requests require
      `catalog_version`; omitted sources normalize to disabled at scale 1; and
      `GET`/`PUT /background` plus `/validate` return complete normalized state.
      A catalog-numeric change must increment `CATALOG_VERSION`, so campaign
      clients can refuse drift before acquisition.
- [ ] **Tune catalog numerics against real fitting campaigns.** The six
      scale-1 base definitions are a reference mixture rather than a measured
      universal background. Use campaign evidence to retune their relative
      strengths and shapes, then bump `CATALOG_VERSION` so stored requests fail
      clearly instead of silently changing planted truth.
- [ ] **Virtual instrument clock** — per-axis velocities in the descriptor; per-job
      `experimental_time` = counting + axes-movement (angle-map metric); session total
      in /state and journal. Needed for honest driver benchmarking.
      → CONTROL_FEATURES §7.
- [ ] **Point-list (non-uniform) scans** — `scan_points` body form; reject duplicates,
      auto-sort with validation note. Small, independent.
      → CONTROL_FEATURES §8.
- [x] **Expose sample selection via the API** — done 2026-07-06: `"sample"` is a
      `PATCH /parameters` / `POST /scan` field with `allowed` ids from the sample
      library in `GET /schema` (API guide, *Parameters*). The library now also
      carries `Pb_phonon_DFT` (2026-09-05, real fcc dispersion from Rolf Heid's
      DFT grid; `components/PHONON_DFT.md`).
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

- [ ] **goto CEN/COM/MAX** — GUI half done 2026-07-26: `tavi/scan_fits.py` and the
      Fitting dock (`gui/docks/fitting_dock.py`) with goto COM/MAX/CEN and revert.
      Still open: `POST /goto` for API clients. → CONTROL_FEATURES §1.
- [ ] **Path (vector) scans** — `scan_path` body + GUI "Path" mode + point generator;
      `display_dock._get_axis_label` needs a path/|q| case. → CONTROL_FEATURES §2.
- [ ] **Batch submission + campaigns** — `POST /scans`, `Campaign`/`CampaignRegistry`,
      campaign endpoints, grouped job table. → CONTROL_FEATURES §3.
- [ ] **Measurement intents (recipes)** — rocking curve, θ–2θ, const-Q E-scan.
      Lowest priority; needs §1–§3. → CONTROL_FEATURES §4.

## API polish (small, found in live testing)

- [x] **Reject unknown top-level POST body keys (400)** — done 2026-07-06
      (`SCAN_BODY_KEYS` in `tavi/api_server.py`; unknown keys → `400 bad_request`).
- [ ] **Quiet journal noise from isolation restore** — isolated submissions log
      duplicate "api: set …" parameter entries (apply + restore both record).
- [ ] **429 Retry-After from real queue drain** — currently the ETA estimate when
      available, constant 30 s otherwise; revisit once campaigns land.
- [ ] **Curvature follow-ups from PR #32** (ledger and reasons at the end of
      `docs/PLAN-crystal-bending-landing.md`): `curvature_modes` in launch
      metadata never says `scanned` for a scan-named axis (only the per-point
      snapshot does; `applied_curvature` carries the truth); `PATCH /parameters`
      on a module-fixed axis (PUMA rhm with an NMO) reports the requested value
      while the field syncs to the resolved 0; the "40-field" parameter-table
      count is stale (43) in four documents.

## GUI

- [ ] **Scroll-lock the two QDoubleSpinBox in `ub_matrix_dock`** — same accidental
      wheel-capture issue fixed for combo boxes (`NoScrollComboBox`); deferred by
      scope at the time.
- [ ] **A zero or wrong-sign scan step is not a hard Run gate** — the validator
      returns `(var, message)` and `_scan_command_issues` files it as neither
      hard nor soft (only "⚠" messages are soft); the dock annotation shows it,
      Run does not refuse it. Pre-existing, found in PR #32's pre-PR review.
- [ ] **Non-numeric radius in a GUI field silently blocks the run** —
      `get_gui_values()` returns None and the launch bails with no message.
- [ ] **Ideal labels index `ideal['rhm'/'rvm'/'rha']` unconditionally** — a
      future driven mono/rha axis with `focusing_known=False` (today only
      IN12's Heusler rva) would KeyError in `update_ideal_bending_buttons`.

## Housekeeping

- [x] **Test-runner note** - done 2026-09-09. The interpreter crash on a full
      `pytest tests/` (fault 0xc06d007f, a delay-load failure in matplotlib and
      Qt native code) is *not* a broken environment: it is what happens when the
      env's interpreter is invoked **directly**, which leaves `Library\bin` off
      PATH. Run the suite through the activation the launcher uses --
      `micromamba run -n tavi-dev python -m pytest tests -q` -- and it passes
      whole in ~70 s. No allowlist needed. Run one suite at a time, and never a targeted
      file while a full run is in flight: concurrent runs contend for the
      API server port (`test_api_server.py` / `test_api_validation_schema.py`)
      and for the shared `config/parameters.json`
      (`test_parameters_persistence.py`) and fail spuriously. In Git Bash
      `micromamba` is not on PATH; the absolute launcher is in
      `tests/README.md`, as is the worktree hardlink for the Pb map that
      `test_dispersion_map.py` otherwise skips silently.
      Written up in `AGENTS.md` step 3 and `tests/README.md`.

- [ ] **Instrument evidence still needing an instrument scientist** - each is
      labelled in the owning `MODEL_STATUS.md`, none blocks use:
      IN8's monochromator take-off lower limit (ILL's current page says 11 deg,
      the 2023 Thermes paper ~10 deg; the tighter one is enforced);
      IN12's monochromator curvature minima (1.7 m / 0.5 m, enforced as a
      *provisional model assumption* - the vertical clamp binds above roughly
      |A1| = 32 deg, so it is an unsourced number affecting emitted geometry);
      PANDA's and IN12's analyser vertical curvature *radius* (the fixedness is
      evidenced, the value is not); IN8's Cu(200) reflectivity; and every
      instrument's source spectrum - the Maxwellian is now correctly sampled
      but is still not a measured SR-2 / H144 / H10 spectrum.

- [ ] **Small twins left after PR #32** - `tests/test_api_over_limit_latch.py`'s
      `_ManifestController` still re-implements `normalize_scan_variable` as
      identity; IN12's `ana_vertical_is_fixed()` reads raw `fixed_curvature`
      with zero callers; `curvature_limits`' docstring advertises an
      angle-dependent extension `effective_curvature_axis` cannot serve
      without the angle (the seam for angle-dependent bender travel).
- [ ] **PUMA's own evidence review** - PANDA and IN12 got one; PUMA's arm
      lengths, crystal menu and source spectrum are marked provisional in its
      own `MODEL_STATUS.md` and disagree with the current MLZ description.
      Deliberately out of scope for the 2026-09-09 instrument pass, which
      treated PUMA's declared values as authoritative.


Others:
- vTAS style graphical interface [STARTED]
  - Resolution function display
  - E-mode
- HKL cut-along-areas with saved data?
