# TAVI — ongoing TODO

Living list. Grouped by theme, roughly dependency-ordered within each group.
Design references: `docs/CLOSED_LOOP_DESIGN.md` (system capstone — read first),
`docs/CONTROL_FEATURES_DESIGN.md` (feature designs + roadmap §9),
`docs/LLM_HARNESS_DESIGN.md` (measurement driver), `docs/API_USER_GUIDE.md`
(live API reference). Last updated: 2026-07-28.

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

- [x] **Test-runner note** - done 2026-09-09. The interpreter crash on a full
      `pytest tests/` (fault 0xc06d007f, a delay-load failure in matplotlib and
      Qt native code) is *not* a broken environment: it is what happens when the
      env's interpreter is invoked **directly**, which leaves `Library\bin` off
      PATH. Run the suite through the activation the launcher uses --
      `micromamba run -n tavi-dev python -m pytest tests -q` -- and it passes
      whole in ~70 s. No allowlist needed. Run one suite at a time: two
      concurrent runs contend for the API server port and fail
      `test_api_server.py` / `test_api_validation_schema.py` spuriously.
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
