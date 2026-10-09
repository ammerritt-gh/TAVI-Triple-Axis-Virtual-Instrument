# TAVI Tests

> **Status:** live
> **Authority:** how the test suite is run and what it contends on

Pytest suite for TAVI's logic below the visible GUI, including offscreen Qt acceptance tests. Tests import `tavi/` and `instruments/`
relative to the repo root, so always run from there:

```
micromamba run -n tavi-dev python -m pytest tests -q -ra
```

From Git Bash `micromamba` is not on PATH; use the absolute launcher:

```
"/c/Users/AMM/AppData/Local/micromamba/micromamba.exe" run -n tavi-dev python -m pytest tests -q -ra
```

Notes:

- **Run one suite at a time, and never a targeted file while a full run is in
  flight.** Two concurrent runs contend for the API server port
  (`test_api_server.py`, `test_api_validation_schema.py`); it fails spuriously
  and reproduces as green when run alone.
- **Local state is isolated.** `conftest.py` sets `TAVI_CONFIG_DIR` for the
  whole session to a temp copy of `config/`; every reader/writer in the app
  resolves its config path through `tavi.local_state.config_path()`, which
  honors that override, so nothing a test does reaches the operator's real
  `config/` files. An autouse session fixture re-hashes the real `config/`
  at teardown and fails the session if anything changed anyway. A test that
  needs to write local state uses `tmp_path`.
- **A fresh `git worktree` skips a test silently.** `components/Pb_dft_phonons.dat`
  (143 MB, gitignored) is not in a new worktree, so `test_dispersion_map.py`
  skips. `-ra` above prints the skip; hardlink the file from the main checkout
  (`fsutil hardlink create <worktree>\components\Pb_dft_phonons.dat
  <main>\components\Pb_dft_phonons.dat`) to keep the count honest.

- The local micromamba env is `tavi-dev` (the one `run-tavi-dev.bat` uses).
  pytest is not part of `requirements.txt`; install it once into the env with
  `micromamba run -n tavi-dev python -m pip install -r requirements-dev.txt`.
- **No on-screen GUI, no McStas runs.** Tests must not show a window or
  compile/execute McStas instruments. Offscreen Qt widgets are allowed and
  used (`QT_QPA_PLATFORM=offscreen`; e.g. `test_dispersion_viewer.py` and the
  controller tests construct real widgets); math, parsing, registry and
  source-scan checks make up the rest.
- **The repo-root `conftest.py` keeps windows off the operator's screen, and
  must stay.** Merely *constructing* `ms.McStas_instr(...)` -- which every
  build-tree test does -- makes McStasScript shell out twice: `mcrun
  --showcfg=resourcedir` with `shell=True` when `MCSTAS` is unset, and
  `mcstas -v` unconditionally, inside a bare `except`. Windows gives a child
  of a console-less parent its own console, so each launch is a console window
  on screen, and a faulting binary adds an error dialog. That is invisible when
  you start the GUI from `run-tavi-dev.bat` (the children inherit its console)
  and very visible when an agent runs pytest from a background process:
  measured 2026-09-09, an afternoon of runs left 121 orphaned `conhost.exe`
  behind. `conftest.py` sets `MCSTAS` if absent and forces `CREATE_NO_WINDOW`
  on every subprocess for the session; `test_no_console_windows.py` fails if
  either guard is removed. **A script that drives McStasScript outside pytest
  needs the same guard** -- see `install_no_window_guard()`.
- Tests that merely need to *import* McStasScript-heavy modules (e.g. the PUMA
  instrument definition) must guard with
  `pytest.importorskip("mcstasscript")` so the suite passes in environments
  without McStasScript.

## Suite size and timing

Measured 2026-10-10 on the 9950X3D with the command above, one run at a time:
2342 passed and 2 skipped (`test_dispersion_map.py` in a fresh worktree, and
`test_documentation.py` when the shared doc checker is absent) in 229 s
(233 s wall). `test_orientation_gui.py` alone, 85 offscreen tests, takes about
16 s with its two controllers' construction; its operator acceptance test
takes about 1.6 s of that. Pass `--durations=15` to see the slowest tests.

## Current contents

- `test_tas_geometry.py` — golden tests for the general TAS geometry solvers
  (`tavi/tas_geometry.py`) and UB-matrix math (`tavi/ub_matrix.py`).

Crystal orientation (truth and belief, the sample goniometer, the plane lock,
legible alignment):

- `test_orientation.py` — numpy checks: the stage solver and its travel,
  peaks as stage records, the UB fit, the true mount and grading, the plane
  lock, the zone axis (`small_integer_indices`), the per-peak and peak-pair
  residuals (`alignment_residuals`) on cubic and monoclinic cells in both
  senses, and Refine Lattice for every crystal system, refusals included.
- `test_orientation_gui.py` — offscreen Qt on two module-scoped controllers,
  IN8 (unlimited arcs) and IN12 (±20° arcs), so no test builds a window of its
  own: hidden truth untouched by every belief write, saved state, the lock in
  the GUI, the API and the runtime (a locked point runs at the lock's exact
  arc settings), the plane panel's labels, the residual table and its lifetime,
  Refine Lattice through its button, a sample swap moving the UB onto the new
  lattice, and grading reflections following the described mount. Two tests
  are the operator's done-test for alignment: the cold path driven through
  the real widgets (the UB Matrix dock opened by the Sample dock's button,
  the Fitting tab selected, rocking scans on the deterministic engine, goto CEN, a
  mis-index flagged and corrected, a lock and a locked three-point run,
  checked point by point), and the post-fit leak check (two hidden truths,
  the same actions and a wrong fit, identical widget texts and `/state`).

Contract tests for the configurable-instruments Phase 1
(`docs/CONFIGURABLE_INSTRUMENTS.md` §17.7 — "PUMA is not special"):

- `test_instrument_registry.py` — registry behavior + a subprocess-based check
  that listing instruments never imports mcstasscript/PySide6/the heavy PUMA
  module.
- `test_instrument_packages.py` — package metadata/doc/reference validation,
  runnable-versus-research registration, and manifest/descriptor identity.
- `test_descriptor_validation.py` — `validate_descriptor` rules against the
  PUMA descriptor and the IN8 example, plus a source-scan that the builder's
  `add_parameter` names match the descriptor exactly.
- `test_puma_plugin.py` — plugin protocol conformance, default-state and
  scan-config equivalence with legacy behavior, snapshot params == descriptor
  params, shared `RunExecutionState`, binary-name derivation.
- `test_controller_is_instrument_agnostic.py` — source scan: no `"PUMA"`
  literal or direct PUMA import left in `TAVI_PySide6.py`, and the plugin
  seam (`self.instrument.build/compute_snapshot/run_point/...`) is present.
- `test_runtime_tracker_legacy_key.py` — `"PUMA"` → `"puma"` runtimes.json
  key migration.

Phase-2 additions (`docs/CONFIGURABLE_INSTRUMENTS.md` §18):

- `test_parameters_persistence.py` — per-instrument `parameters.json` block
  selection and container round-trips (built on a bare `TAVIController` via
  `__new__`; skips without PySide6/mcstasscript).
- Anti-drift source-scans in `test_descriptor_validation.py`: descriptor
  monitor ids == build() diagnostic gates, sample ids == build() ladder.
- Crystal-adapter golden-dict parity and `build_fingerprint` tests in
  `test_puma_plugin.py`.

Phase-3 additions (`docs/CONFIGURABLE_INSTRUMENTS.md` §19):

- `test_puma_build_tree.py` — object-level build-tree tests replacing the two
  anti-drift source-scans (monitor gates, sample ladder): builds the instrument
  through the full plugin path and inspects `component_list`. Construction
  only — creating a `McStas_instr` and adding components never compiles or
  runs McStas, so this stays within the no-compile rule (it does need a
  configured mcstasscript, which the tavi-dev env provides).
- `test_sample_library.py` — the shared, instrument-independent sample library
  (`tavi/sample_library.py`): shape, legacy `Al_Bragg` component name, per-
  sample lattice constants, and that the PUMA descriptor mounts the library.

Cross-scan binary reuse (`docs/CONFIGURABLE_INSTRUMENTS.md` §18.5):

- `test_binary_reuse.py` — the controller's Qt-free reuse decision helpers
  (`_can_reuse_binary` / `_updated_binary_cache`): fingerprint match, binary
  existence, diagnostic-mode opt-out, cache replacement rules.
- `test_mcstas_config.py` — MPIRUN resolution from flat and nested
  `mccode_config.json` schemas plus launcher-argv normalization (the nested
  schema had silently disabled direct McStas execution).

Phase-4 additions (`docs/CONFIGURABLE_INSTRUMENTS.md` §20 — IN8, senses):

- `test_sign_conventions.py` — golden sign-convention tests: PUMA's baked
  angle branch frozen (elastic/inelastic/skew-Q/out-of-plane/Kf-fixed +
  reverse recovery), sense-threading equivalence and flip tests, and the
  vTAS-verified IN8 reference cases (senses +1/+1/−1; live run 2026-07-02),
  plus the IN12 and PANDA cases. Both sets are **self-generated** — nobody ran
  either instrument for us — and they freeze the sign structure of the two
  negative-monochromator geometries (senses −1/+1/−1): IN12's senses were
  settled from the published record (`instruments/in12/MODEL_STATUS.md`);
  PANDA's follow vPANDA's declarations and are not yet control-system
  verified. Their job is to catch a regression in the `sense_mono = −1` path,
  forward and through both inverse branches.
- `test_in8_plugin.py` — IN8 plugin conformance: runnable descriptor,
  scan-config mapping (single-select collimation, branch-signed bending),
  crystal lookup incl. the Cu200 `"NULL"` reflectivity sentinel, fingerprint
  sensitivity, snapshot params == `_IN8_PARAMS`.
- `test_in8_build_tree.py` — object-level IN8 build-tree tests (construction
  only, no compile): backbone beam order, parameter set, monitor
  gating/settings, collimator selection, crystal properties per descriptor,
  detector contract, Mono/Maxwellian source wiring, shared-library sample
  emission, no PUMA-only components.
- `test_in12_plugin.py` — IN12 plugin conformance, same shape as IN8's plus
  what is specific to IN12: the provisional senses (−1, +1, −1), the entirely
  negative monochromator travel that evidences them, the derived slab sizes
  reconstructing the published crystal faces, the fourth (α1) collimation slot,
  the Heusler(111) analyser's `"NULL"` sentinel, the eleven-lamellae-in-three-
  rows analyser reconstructing its published face, the analyser's fixed vertical
  radius (asserted *not* to be tracking the arms, since "fixed" is the point),
  and the vertical bending clamp at the published 0.5 m minimum.
- `test_in12_build_tree.py` — object-level IN12 build-tree tests (construction
  only, no compile): beam order including the guide-exit collimator, four
  collimator selections, guide-exit source aperture, one-row analyser, 3He
  detector contract, and the absence of any filter or PUMA-only optics.
- `test_panda_plugin.py` — PANDA plugin conformance: runnable descriptor,
  the negative-monochromator senses (−1/+1/−1), the four-slot collimation
  (an `alpha_1` slot, as IN8 and IN12 now have), the 55-crystal analyzer,
  the Cu111 `"NULL"` sentinel, all-negative branch-signed bending, the split
  monochromator object distance, published axis limits, fingerprint
  sensitivity, snapshot params == `_PANDA_PARAMS`.
- `test_panda_build_tree.py` — object-level PANDA build-tree tests
  (construction only, no compile): backbone beam order, parameter set, monitor
  gating/settings, all four collimators tracking selection, the scannable
  virtual-source/`ss1`/`ss2` apertures, crystal properties per descriptor, the
  1″ ³He detector contract, source wiring at the guide exit, shared-library
  sample emission, no PUMA/IN8-only components.
- `test_descriptor_validation.py` / `test_instrument_registry.py` updated:
  IN8 and IN12 are runnable-valid (rejection paths keep synthetic broken
  descriptors); the lazy-import test lists in8/in12/panda and bans their
  `model` modules. `test_instrument_registry.py` imports `instruments.builtin`
  at module scope so its snapshot/restore fixture cannot wipe the built-in
  registrations for later test files.
Naming contract (API version 2; the angle table in `docs/INSTRUMENT_LAYOUT.md`,
the break in `docs/API_USER_GUIDE.md` §15). The trap these tests guard is that
A2 and A4 swapped meanings, so they assert which axis moves, not just that a
name is accepted:

- `test_quantities.py` — the registry `tavi/quantities.py`: collisions between
  IDs and aliases, `resolve()` per context (scan and write), every refusal text,
  `normalize_write_names`, `public_values`, the NICOS name of every angle.
- `test_scan_names.py` — scan commands through the registry on all four
  instruments: A2, A3, A4, A6, `sgl`, `sgu` and every alias each move only the
  named angle (a table of slots), A1/A5/`chi`/slits refused, unknown names get
  suggestions, and the conflict pairs (`A4` with `stt`, `A3` with `omega`, `H`
  with `A4` ...) refuse, `force` or not.
- `test_angle_labels.py` — offscreen: the Instrument dock's angle labels are the
  registry labels with the NICOS name in the tooltip, and the A1/A5 readouts
  are read-only halves of their 2θ fields.
- `test_api_version.py` — Qt-free, a fake backend over HTTP: every write and
  validate route refuses a missing or wrong `api_version` before the backend is
  called; GETs need none.
- `test_api_canonical_names.py` — offscreen, a real controller, server and
  GUI-thread bridge: replies carry canonical IDs only, `A4` writes the sample
  2θ and `A2` the monochromator's, retired/derived/duplicate keys refuse the
  whole request with state unchanged, a job reports canonical IDs and the
  version, and `/resolution` answers at the requested point.
- `test_api_partial_slits.py` — per-gap slit keys on all four instruments.
- `test_output_versioning.py` (with the fixtures `tests/data/old_omega_scan/`
  and `tests/data/old_a2_scan/`, built from the shape the old TAVI wrote) —
  `scan_parameters.txt` starts with `api_version: 2` and holds canonical keys;
  a pre-break folder is refused on load and left untouched.
- `test_saved_parameters.py` — also pins `parameters.json` version 5, its
  canonical keys and the per-gap slit keys.
- `test_documentation.py` — runs the shared documentation checker
  (`Agentic-Control-Scheme/bin/doc_check.py`) over this repository so a
  missing banner, an unreachable document or a broken link fails the suite.
  The checker path comes from `DOC_CHECK`, falling back to the maintainer's
  checkout; where neither exists the test skips with the reason printed.
