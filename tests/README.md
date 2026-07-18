# TAVI Tests

Pytest suite for TAVI's non-GUI logic. Tests import `tavi/` and `instruments/`
relative to the repo root, so always run from there:

```
micromamba run -n tavi-dev python -m pytest tests -q
```

Notes:

- The local micromamba env is `tavi-dev` (the one `run-tavi-dev.bat` uses).
  pytest is not part of `requirements.txt`; install it once into the env with
  `micromamba run -n tavi-dev python -m pip install -r requirements-dev.txt`.
- **No GUI, no McStas runs.** Tests must not launch PySide6 widgets or compile/
  execute McStas instruments. Pure math, parsing, registry, and source-scan
  checks only.
- Tests that merely need to *import* McStasScript-heavy modules (e.g. the PUMA
  instrument definition) must guard with
  `pytest.importorskip("mcstasscript")` so the suite passes in environments
  without McStasScript.

## Current contents

- `test_tas_geometry.py` — golden tests for the general TAS geometry solvers
  (`tavi/tas_geometry.py`) and UB-matrix math (`tavi/ub_matrix.py`).

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
  vTAS-verified IN8 reference cases (senses +1/+1/−1; live run 2026-07-02).
- `test_in8_plugin.py` — IN8 plugin conformance: runnable descriptor,
  scan-config mapping (single-select collimation, branch-signed bending),
  crystal lookup incl. the Cu200 `"NULL"` reflectivity sentinel, fingerprint
  sensitivity, snapshot params == `_IN8_PARAMS`.
- `test_in8_build_tree.py` — object-level IN8 build-tree tests (construction
  only, no compile): backbone beam order, parameter set, monitor
  gating/settings, collimator selection, crystal properties per descriptor,
  detector contract, Mono/Maxwellian source wiring, shared-library sample
  emission, no PUMA-only components.
- `test_descriptor_validation.py` / `test_instrument_registry.py` updated:
  IN8 is runnable-valid (rejection paths keep synthetic broken descriptors);
  the lazy-import test lists in8 and bans `instruments.in8.model`.
