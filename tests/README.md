# TAVI Tests

Pytest suite for TAVI's non-GUI logic. Tests import `tavi/` and `instruments/`
relative to the repo root, so always run from there:

```
micromamba run -n tavi python -m pytest tests -q
```

Notes:

- The local micromamba env is currently named `tavi` (the `tavi-dev` name in
  `run-tavi-dev.bat` is stale on this machine). pytest is not part of
  `requirements.txt`; install it once into the env with
  `micromamba run -n tavi python -m pip install pytest`.
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

## Planned (Phase 1 of `docs/CONFIGURABLE_INSTRUMENTS.md`, §17.7)

The configurable-instruments work adds contract tests that lock in
"PUMA is not special":

- `test_instrument_registry.py` — registry behavior + a subprocess-based check
  that listing instruments never imports mcstasscript/PySide6.
- `test_descriptor_validation.py` — `validate_descriptor` rules against the
  PUMA/IN8 example descriptors, plus a source-scan that the builder's
  `add_parameter` names match the descriptor exactly.
- `test_puma_plugin.py` — plugin protocol conformance, default-state and
  scan-config equivalence with legacy behavior, snapshot-params ⊆ descriptor.
- `test_controller_is_instrument_agnostic.py` — source scan: no `"PUMA"`
  literal or direct PUMA import left in `TAVI_PySide6.py`.
- `test_runtime_tracker_legacy_key.py` — `"PUMA"` → `"puma"` runtimes.json
  key migration.

When those land, delete this "Planned" section and fold the files into
"Current contents".
