# TAVI - Triple-Axis Virtual Instrument

TAVI is a Python/PySide6 GUI for simulating triple-axis spectrometer experiments with McStas through McStasScript. The current application targets the PUMA TAS instrument and combines a dock-based GUI, McStasScript instrument generation, scan execution, detector data parsing, and live plotting.

---

## Quick Reference

- **Language / runtime:** Python 3.x. Existing installer docs use Python 3.11; do not introduce syntax that would require a newer version without a compatibility check.
- **Frameworks:** PySide6, McStasScript, NumPy, Matplotlib.
- **Entrypoint:** `python TAVI_PySide6.py`.
- **Developer launcher:** `run-tavi-dev.bat` runs the GUI in the local `tavi-dev` micromamba environment.
- **Dependency manager:** `pip install -r requirements.txt` for standalone Python dependencies; installer docs use micromamba for McStas and Python.
- **Config location:** `config/*.json` stores local McStas paths, GUI parameters, layout state, and runtime estimates.
- **Generated output:** simulation results are written under `output/`; McStas can generate `.c`, `.instr`, executables, and detector output files.
- **External runtime dependency:** McStas 3.4 or later plus a C/C++ compiler for instrument compilation.
- **Dependencies to change carefully:** `mcstasscript`, `PySide6`, `matplotlib`, and McStas path handling all affect launch and simulation behavior.

---

## Domain Concepts

### Triple-Axis Spectrometer Flow

TAVI models a TAS instrument with source, monochromator, sample, analyzer, and detector stages. Primary angles are A1, A2, A3, and A4; sample orientation uses omega/chi with alignment offsets psi/kappa. For physics and geometry details, read `docs/INSTRUMENT_LAYOUT.md`.

### McStasScript Instrument Generation

Each runnable package's `model.py` owns its instrument-specific state, physics,
and McStas component tree. `instruments/tas_runtime.py` owns shared TAS angle
state, snapshot preparation, feasibility, and execution. Scannable values
should generally be McStas parameters so scans do not force recompilation.
Read `docs/MCSTAS_PARAMETERS.md` before changing parameter behavior.

### GUI Controller and Docks

`TAVI_PySide6.py` contains `TAVIController`, which connects GUI widgets to backend calculations, scans, persistence, and simulation execution. `gui/main_window.py` creates the dock layout. Individual panels live in `gui/docks/` and generally inherit from `BaseDockWidget` in `gui/docks/base_dock.py`.

### Threading Boundary

Long simulations run in a Python worker thread started by `TAVIController.run_simulation_thread()`. GUI updates cross back through Qt `Signal`s. Do not call PySide6 widgets or show Matplotlib GUI windows directly from the simulation worker thread.

### Local State and Output

`config/parameters.json`, `config/view_layout.json`, and `config/runtimes.json` are user/local runtime state. `output/` contains simulation results and scan folders. Treat these as generated state unless the task explicitly asks to change defaults or fixtures.

### Custom McStas Components

`components/` contains custom and modified McStas component assets, including NMO and phonon components. Read `components/README.md` and the component-specific docs before editing `.comp`, `.h`, or generated McStas artifacts.

---

## Before You Touch X

| Task area | Read first |
|---|---|
| GUI layout, docks, menus, panel visibility | `gui/main_window.py`, `gui/docks/base_dock.py`, and one similar dock |
| Simulation orchestration or scan execution | `TAVI_PySide6.py`, especially `TAVIController` and `run_simulation()` |
| PUMA instrument geometry or McStasScript setup | `docs/INSTRUMENT_LAYOUT.md`, `docs/MCSTAS_PARAMETERS.md`, `instruments/puma/model.py` |
| Instrument plugins, registry, descriptors, IN8, adding an instrument | `docs/CONFIGURABLE_INSTRUMENTS.md`, `docs/INSTRUMENT_AUTHORING.md`, `tests/README.md` |
| McStas path detection/configuration | `tavi/mcstas_config.py`, `config/TAVI-McStas-Path-Resolution.md`, `config/mcstas_config.json` |
| Reciprocal-space or HKL/Q conversion | `tavi/reciprocal_space.py`, `tavi/ub_matrix.py`, `docs/INSTRUMENT_LAYOUT.md` |
| UB matrix or training exercises | `tavi/ub_matrix.py`, `gui/docks/ub_matrix_dock.py`, `gui/docks/misalignment_dock.py` |
| Runtime estimates | `tavi/runtime_tracker.py`, `config/runtimes.json` behavior |
| Detector parsing, saved scan files, plotting helpers | `tavi/data_processing.py`, `gui/docks/display_dock.py` |
| Remote API server, routes, auth, SSE, budgets | `tavi/api_server.py`, `tavi/scan_jobs.py`, `docs/API_SERVER_DESIGN.md`, `docs/API_USER_GUIDE.md` |
| API scan jobs, GUI-side backend/field map | `TAVI_PySide6.py` (`TaviApiBackend`, `apply_parameters`, `_api_field_map`, `submit_scan_job`), `gui/docks/api_dock.py` |
| Custom McStas components | `components/README.md` and the relevant `.comp` or header docs |
| Installation and launch scripts | `README.md`, `installer/TAVI-Installation-README.md`, `run-tavi-dev.bat` |

---

## Project Structure

```text
TAVI/
|-- TAVI_PySide6.py              # Main GUI entrypoint and controller
|-- gui/
|   |-- main_window.py           # QMainWindow, dock creation, layout persistence
|   |-- docks/                   # PySide6 dock panels for instrument, sample, simulation, display, output
|   `-- dialogs/                 # Modal dialogs, currently diagnostic configuration
|-- instruments/
|   |-- tas_runtime.py           # Shared TAS state, snapshot, feasibility, execution
|   |-- puma/                    # Runnable PUMA plugin, model, review package
|   |-- in8/                     # Runnable IN8 plugin, model, review package
|   |-- panda/                   # Research-only instrument package
|   `-- in12/                    # Research-only instrument package
|-- tavi/                        # Core Python helpers and domain logic
|-- components/                  # Custom McStas components, headers, and related data
|-- config/                      # Local JSON config and McStas path notes
|-- docs/                        # TAS/McStas design notes
|-- installer/                   # Windows installation documentation/scripts
|-- archive/                     # Older/reference code, not the active implementation path
`-- output/                      # Generated simulation output
```

---

## Architecture

### Data Flow

```text
PySide6 docks and dialogs
    |
    v
TAVIController in TAVI_PySide6.py
    |
    +--> tavi/ helpers for HKL/Q, UB matrix, scan parsing, runtime estimates
    |
            +--> active InstrumentPlugin
                    +--> package model/build
                    `--> shared tas_runtime snapshot/run
            |
            v
      McStasScript / McStas compile and run
            |
            v
      output/ scan folders and detector files
            |
            v
      tavi.data_processing + gui.docks.display_dock
```

### Key Design Decisions

1. **The GUI is dock-based PySide6.** New panels should follow the existing `BaseDockWidget` and stable `objectName()` pattern so layout persistence keeps working.
2. **`TAVIController` coordinates UI and backend state.** Keep orchestration in the controller unless an existing helper module already owns the calculation.
3. **PUMA instrument construction belongs in `instruments/puma/model.py`.** Do not duplicate McStasScript component setup in GUI code.
4. **Scannable McStas values should remain parameters when practical.** This preserves scan speed by avoiding unnecessary recompilation.
5. **Runtime config and output are local generated state.** Do not treat user paths, saved layouts, runtime estimates, or scan output as stable project fixtures unless a task explicitly says so.

---

## Module Ownership

### `TAVI_PySide6.py`

**Owns:** application launch, `TAVIController`, signal wiring, scan orchestration, GUI state collection/persistence, and message-center updates.

**Does not own:** reusable numerical helpers, persistent component definitions, or dock widget layout internals.

### `gui/`

**Owns:** PySide6 widgets, dock layout, menus, dialogs, local UI validation display, and plot UI.

**Does not own:** McStas instrument construction, TAS physics calculations, file parsing policy, or scan execution loops.

### `instruments/`

**Owns:** the registry/contract, shared TAS runtime, and one package per instrument. Runnable packages own their descriptor/plugin, instrument-specific state and physics, McStas tree, evidence record, and scientist review surface. Research packages contain evidence and review documents but are not registered.

**Does not own:** PySide6 widget access or GUI layout state.

### `tavi/`

**Owns:** reusable non-GUI Python helpers: reciprocal-space conversion, UB matrix calculations, scan parsing utilities, runtime tracking, data processing, and McStas path detection.

**Does not own:** dock layout, direct widget updates, or PUMA-specific component layout unless already part of a helper contract.

### `components/`

**Owns:** custom McStas component source files, headers, reference data, and component documentation.

**Does not own:** Python GUI logic or user-generated scan output.

### `config/` and `output/`

**Owns:** local runtime state and generated simulation data.

**Does not own:** source-of-truth application defaults unless a file is explicitly documented as such.

---

## Established Patterns

- **Dock widgets inherit from `BaseDockWidget`.** See `gui/docks/base_dock.py` and existing docks in `gui/docks/`.
- **Persistent docks use stable object names.** See `gui/main_window.py` layout save/restore logic and each dock's `setObjectName()`.
- **Controller-to-UI updates use Qt signals.** See `TAVIController` signals for progress, counts, scan updates, diagnostic plotting, and runtime updates.
- **Simulation output is per-run/per-point folder data.** Use existing helpers in `tavi/data_processing.py` and path utilities in `tavi/utilities.py`.
- **McStas path configuration is centralized.** Use `tavi/mcstas_config.py` when working on detection/configuration rather than hardcoding new paths elsewhere.
- **User-facing operational feedback goes to the message center or status bar.** Existing code uses `print_to_message_center()`, Qt status messages, and some console `print()` output in lower-level modules.

---

## Anti-Patterns

### Universal Anti-Patterns

- **Silent exception swallowing.** If an exception is caught, make the failure visible through the existing message center, status bar, or console pattern used by that layer.
- **File I/O without explicit intent.** Use explicit paths and preserve local/generated config semantics; prefer `encoding="utf-8"` for new text-file code.
- **Unscoped refactors.** This repo contains large legacy and active files; keep changes close to the requested behavior.
- **Dependency upgrades without runtime checks.** McStasScript, PySide6, Matplotlib, and McStas version changes can break launch or simulation.

### TAVI-Specific Anti-Patterns

- **Direct UI calls from simulation threads.** Use Qt signals to cross from worker threads to the GUI thread.
- **Matplotlib GUI operations in the worker thread.** Emit the existing diagnostic/display signals and handle plotting on the main thread.
- **Duplicating PUMA instrument construction outside `instruments/puma/model.py`.**
- **Changing scannable values from McStas parameters to declared/internal values without reading `docs/MCSTAS_PARAMETERS.md`.**
- **Treating generated `config/`, `output/`, or McStas build artifacts as ordinary source files.**
- **Editing `archive/` as if it were the active implementation path without confirming the task explicitly targets archived code.**

---

## Verification

For documentation-only changes, run a placeholder/generic-text search and review the diff.

For Python changes, use the smallest relevant checks available:

1. **Syntax / parse check:** `python -m py_compile TAVI_PySide6.py gui/main_window.py` plus any changed Python files.
2. **Import / load check:** import changed non-GUI helper modules when they do not require launching the GUI or McStas.
3. **Test run:** `micromamba run -n tavi-dev python -m pytest tests -q` from the repo root, with `MCSTAS` set to the tavi-dev env's `share\mcstas\resources` (as `run-tavi-dev.bat` does — without it the build-tree tests error out). pytest comes from `requirements-dev.txt`, not `requirements.txt`. Read `tests/README.md` first: no GUI, no McStas compiles/runs in tests. Status 2026-07-12: 488 passed, 2 failed — the two `test_controller_is_instrument_agnostic.py` source-scans, a pre-existing regression (a `"PUMA"` literal and a direct PUMA import are back in `TAVI_PySide6.py`).
4. **Integration check:** for GUI or simulation changes, launch `python TAVI_PySide6.py` in an environment with McStas/McStasScript available and exercise the changed path. Avoid long simulations unless the task requires them.

---

## Reference Documents

- `README.md` - project overview, requirements, installation, and run instructions.
- `User_Guide.md` - user-facing workflow guide.
- `docs/INSTRUMENT_LAYOUT.md` - TAS/PUMA geometry, angles, sample orientation, and scan modes.
- `docs/MCSTAS_PARAMETERS.md` - McStasScript parameter behavior and recompilation guidance.
- `docs/PIPELINE_DESIGN.md` - pipelined scan execution design and implementation status (May 2026).
- `docs/API_SERVER_DESIGN.md` - remote API server design and architecture (implemented 2026-07-03).
- `docs/API_USER_GUIDE.md` - remote API user guide for humans and LLM agents (endpoints, fields, scan syntax, SSE).
- `components/README.md` - custom McStas component overview.
- `config/TAVI-McStas-Path-Resolution.md` - McStas path-resolution notes.
- `installer/TAVI-Installation-README.md` - Windows installation and launcher details.
- `.github/instructions/copilot-instructions.md` - tactical code-style and local-convention rules.

---

## Pipelined Scan Execution

Pipelined scan execution is implemented in the live codebase. `TAVIController.run_simulation()` uses a prep thread plus `Queue(maxsize=2)` to overlap snapshot preparation with simulation, while postprocessing remains inline in the simulation thread.

Instrument-specific construction lives in each runnable package's `model.py`.
Shared `compute_scan_snapshot()`, `check_point_feasibility()`, and
`run_tas_point()` live in `instruments/tas_runtime.py`; plugins are the
controller-facing API.

The current pipeline passes snapshot dicts through the queue so the simulation thread consumes per-point data prepared ahead of time instead of reading mutable shared scan state directly.

`docs/MCSTAS_PARAMETERS.md` is the authoritative reference for what is build-time (requires recompilation) vs run-time (safe to change between points via `set_parameters()`).

Cancellation uses drain semantics through `self.stop_event` (`threading.Event`): the prep thread stops queueing new work, and the simulation thread exits after the current point finishes postprocessing.

`tavi/runtime_tracker.py` now persists a heuristic `compilation_time` field for new runs, but compile-time estimates still come from first-point timing rather than an independently measured compile phase.

See `docs/PIPELINE_DESIGN.md` for the current design notes and implementation status.

---

## Remote API Server

A stdlib-only HTTP/REST + SSE server lets external clients (scripts, notebooks, `curl`, LLM agents) drive a running TAVI GUI over a local port. It is implemented and live-verified. The server layer (`tavi/api_server.py`) has zero Qt imports and is driven by a duck-typed backend; the job/result/budget data model lives in `tavi/scan_jobs.py` (also Qt-free). The GUI-side glue — `TaviApiBackend`, `ApiBridge`, `apply_parameters()`, `_api_field_map`, `submit_scan_job()` — lives in `TAVI_PySide6.py`, and the operator surface (status, mode toggle, job table, budget, activity log) is `gui/docks/api_dock.py`.

Every scan (GUI Run button or API) runs as a `ScanJob` through one serial worker thread, so runs never race. Writes cross to the GUI thread via `ApiBridge.call_on_gui` (timeout → HTTP 503 `gui_busy`); SSE publishing bypasses Qt entirely. Access modes (Allow control / Read-only / Off), the optional bearer token, and budget limits live in `config/api_config.json` (absent = defaults: enabled, allow, `127.0.0.1:8642`, no token). CLI flags `--api-port N` and `--no-api` override the config.

`docs/API_USER_GUIDE.md` is the authoritative client-facing reference (endpoints, the 40-field parameter table, scan-command syntax `VARIABLE start stop STEP` where the last token is STEP SIZE not point count, SSE events, budgets, gotchas). `docs/API_SERVER_DESIGN.md` is the design/architecture record.

API scan submissions are always validated before queueing (parse, budget, per-point feasibility via `check_point_feasibility()` in the instrument plugins, ETA): infeasible points reject the job with HTTP 400 unless `allow_partial: true`, which skips them at run time and lists them as `skipped_points` in the result. GUI Run-button scans are never blocked by this validation. Further client-facing endpoints: `POST /validate` (checks without queueing), `GET /schema` (live self-description), `GET /scan/{id}?wait=N` (long-poll), `GET /scan/{id}/plot.png` (512x512 Agg render, `tavi/plot_render.py`), `GET /journal` (session narrative, `tavi/journal.py`), plus `eta` objects with confidence tiers from `tavi/runtime_tracker.py`, `Retry-After` headers, `Idempotency-Key` dedupe, and `isolated: true` per-job parameter isolation. TAVI deliberately does no data analysis (fits, statistics) — that belongs to the client. `docs/CLOSED_LOOP_DESIGN.md` is the capstone design for the three-component closed-loop system (TAVI instrument / ISAR analysis engine at `..\ISAR` / future measurement driver — read it first); `docs/LLM_HARNESS_DESIGN.md` is the measurement-driver design and `docs/CONTROL_FEATURES_DESIGN.md` the future TAVI control features (goto CEN, path scans, campaigns, deterministic engine, virtual clock).

---

*Last updated: 2026-07-18 (unified runnable and research instrument packages;
shared TAS runtime extracted from the former PUMA module).*
