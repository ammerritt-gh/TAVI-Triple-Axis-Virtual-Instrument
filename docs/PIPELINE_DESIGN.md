# Pipelined Scan Execution — Design Document

*Date: 2026-05-20*
*Status: Implemented in code for the prep-thread + queue pipeline, the controller GUI-state freeze boundary, the stop-event conversion, per-stage timing capture, and the first direct-binary invocation slice behind `run_PUMA_point()`; direct compile-time measurement still remains future work and is inferred from execution timings, and the direct path has not yet been integration-validated in a live McStas environment*

> **Forward note (2026-07-02):** the configurable-instruments Phase 1
> (`docs/CONFIGURABLE_INSTRUMENTS.md` §17) lifts the functions described here
> behind an `InstrumentPlugin` contract: the controller calls
> `self.instrument.build/compute_snapshot/run_point` instead of importing
> `build_PUMA_instrument`/`compute_scan_snapshot`/`run_PUMA_point` directly, and
> `PUMARunExecutionState` becomes an alias of the shared `RunExecutionState`
> (`instruments/contract.py`). The pipeline architecture in this document —
> threads, queue, stop-event drain semantics — is unchanged by that work.

---

## 1. Goal

Keep the McStas simulation binary running at near-100% CPU utilization throughout a multi-point scan by overlapping Python preparation work with the C-level simulation. Current profiling shows that out-of-simulation Python work (angle calculation, folder creation, parameter setup, postprocessing) accounts for 50–60% of wall time on shorter scans. The pipeline hides this latency behind the simulation's wall time.

## 2. Architecture Overview

Two threads, one queue:

```
                    Queue(unbounded)
  [Prep Thread] ──────────────────────► [Simulation Thread]
  produces snapshots                    consumes snapshots
  (pure Python, GIL-bound)              calls backengine() (subprocess, GIL released)
                                        does inline postprocessing after each point
```

The prep thread runs continuously, computing parameter snapshots and pushing them onto an unbounded queue. The simulation thread pulls snapshots and executes them. This lets prep run as far ahead as it can without waiting for buffer space, so the queue can hold the full scan if prep outruns simulation. With 30 MPI threads for McStas and 32 CPU threads available, the prep thread borrowing one core intermittently has negligible impact.

Postprocessing stays inline in the simulation thread (no third stage). Postprocessing is lightweight — reading a small detector file, writing a small parameter file, emitting Qt signals — and separating it would add a thread, a second queue, and out-of-order handling complexity for negligible gain.

### Why this works (GIL verification)

McStasScript's `backengine()` calls `ManagedMcrun.run_simulation()`, which calls `subprocess.run()` (file: `.venv/Lib/site-packages/mcstasscript/helper/managed_mcrun.py`, line 292). CPython releases the GIL during `subprocess.run()` because it is a blocking wait on a child process. This means the prep thread's Python code genuinely executes in parallel with the McStas simulation. The pipeline provides real throughput gains, not just concurrency illusion.

## 3. Design Decisions (Resolved)

### 3.1 Params dict, not PUMA clone

The prep thread produces an immutable params dict — the exact kwargs for `instrument.set_parameters()` — plus metadata (output folder, scan indices, deltaE, error flags). Those parameter keys are already the exact McStas runtime names, so the same dict also backs the current direct CLI `name=value` path once direct execution is armed. The simulation thread never reads from the shared `self.PUMA` object during execution; it consumes only what the prep thread put on the queue.

Rationale: makes the prep↔sim interface contract explicit. Eliminates any possibility of the PUMA mutation race (Section 2.1 of the assessment). `copy.deepcopy(self.PUMA)` would also work but preserves an implicit contract and makes PUMA do double duty as both instrument config and per-point state carrier.

### 3.2 Error handling: log and continue

If prep hits an error (invalid angles, zero-Q, unreachable monochromator angle), it puts an error sentinel on the queue. The simulation thread logs the error, skips `backengine()` for that point, records the point as failed in the scan output, and pulls the next snapshot. This preserves the current behavior where failed points appear as NaN/zero in the scan results rather than being silently dropped.

### 3.3 Cancellation: drain semantics

`threading.Event` replaces the current `stop_flag` bool. When set:
- Prep thread checks the event before computing the next snapshot. If set, it stops producing and exits.
- Simulation thread checks the event before pulling from the queue. If set after the current point's `backengine()` finishes, it completes postprocessing for that point, then exits.
- The in-flight `backengine()` call (subprocess) runs to completion — there is no mechanism to interrupt it mid-execution, and this matches current behavior.

The drain model means: stop accepting new prep work, finish the in-flight simulation, postprocess it, stop. Maximum cancellation latency is one simulation duration (typically under 5 minutes). Emergency kills are handled externally (process termination), not by this pipeline.

### 3.4 Build/run split: included in this refactor

`run_PUMA_instrument()` is split into two functions as part of this change, not deferred. This eliminates ~780 lines of redundant per-point component tree construction and makes the params-dict interface natural.

### 3.5 Queue size: unbounded

No artificial queue cap. The prep thread can compute and enqueue the full scan ahead of the simulation thread, which removes queue backpressure from prep timing. Memory cost is still modest for the current snapshot payloads, and the code keeps the existing stop-event drain behavior if cancellation is requested.

## 4. Refactoring Plan

### Step 1: Split `run_PUMA_instrument()`

Split into two functions in `instruments/PUMA_instrument_definition.py`:

**`build_PUMA_instrument(puma_config, diagnostic_mode, diagnostic_settings, number_neutrons)`**

- Takes PUMA instrument configuration (arm lengths, crystal types, NMO setting, sample type, collimator selection, source type, diagnostic settings) — everything that affects which components are included.
- Calls `ms.McStas_instr(...)`, adds all parameters via `add_parameter()`, adds all components via `add_component()`, and returns the reusable instrument object.
- The current implementation does not force a standalone compile step here; McStasScript still writes and compiles lazily on the first `backengine()` call.
- If diagnostic settings include "Show Instrument Diagram", the caller emits `instrument_diagram_requested` with the instrument object once after this function returns.
- Called **once** at scan start, before any simulation.

**`run_PUMA_point(instrument, params_snapshot, output_folder, number_neutrons, execution_state, mpi_count=30)`**

- Takes the reusable instrument object, the per-point snapshot dict, the output folder path, and the neutron count.
- This is the active per-point execution seam, called from `TAVIController.run_simulation()`.
- The live code also passes a scan-local `PUMARunExecutionState` that tracks whether direct execution is armed, the resolved binary path/cwd, and the resolved MPI launcher argv.
- Calls `instrument.settings(output_path=output_folder, ncount=number_neutrons, mpi=30, force_compile=not execution_state.first_backengine_succeeded, increment_folder_name=False)`.
    - The first point that reaches `backengine()` in a scan therefore forces compilation/materialization so build-time settings are refreshed before later points reuse the materialized binary/direct path.
    - **Critical**: `increment_folder_name=False` is required because `ManagedMcrun` defaults to `True`, which would silently create `scan_0000_0` instead of `scan_0000` if the folder already exists, resulting in postprocessing reading from the wrong folder.
- Calls `instrument.set_parameters(**params_snapshot['params'])`.
- Calls `instrument.backengine()`. The first executed point still relies on this path to materialize the executable and preserve McStasData behavior used elsewhere in the controller.
- The landed direct-binary fast path also lives behind this seam and only activates after the first `backengine()` call succeeded, the execution state is armed, and the expected binary exists on disk.
- Returns `(data, error_flag_array, execution_info)`. `execution_info` carries controller-facing logging/timing metadata including execution mode, direct return code, binary path, launcher argv, and whether the previous `backengine()` point armed direct execution. The instrument object is still not returned.
- Called **once per scan point** by the simulation thread.

**Classification of PUMA attributes:**

Build-time (affect component tree / require recompilation):
- Arm lengths (L1–L4) — hard-coded in PUMA_Instrument.__init__, don't change
- Crystal types (monocris, anacris) — determine reflection file references in component setup
- NMO_installed — controls whether NMO components are added
- sample_key — selects which sample component (Phonon_simple, Single_crystal, Phonon_DFT, etc.)
- Collimator selection (alpha_1, alpha_2 list, alpha_3, alpha_4) — alpha_2 controls which collimator components are present
- V_selector_installed — controls whether velocity selector component is added
- source_type, source_dE — affect source component configuration
- diagnostic_mode, diagnostic_settings — control which monitor components are added

Per-point (McStas parameters, set via `set_parameters()`):
- A1_param, A2_param, A3_param, A4_param
- E0_param
- saz_param
- rhm_param, rvm_param, rha_param, rva_param
- vbl_hgap_param, pbl_hgap_param, pbl_vgap_param, dbl_hgap_param
- chi_param, kappa_param, mis_chi_param, psi_param, mis_omega_param
- chi_total, omega_offset_total

This classification already exists implicitly — `add_parameter()` calls define the per-point set, `add_component()` calls with conditionals define the build-time set. The refactor makes it explicit at the function boundary.

**Note on lines 925–934:** The `add_parameter("chi_param", value=...)` calls with explicit values are misleading. These values are overwritten by `set_parameters()` before `backengine()` runs. After the split, `build_PUMA_instrument` should declare these parameters without default values (or with zero/placeholder defaults), since their actual values come from the params snapshot. This removes the false impression that the build-time values matter.

### Step 2: Define the params snapshot

A function in `instruments/PUMA_instrument_definition.py` that takes the current scan point data and returns a dict:

```python
def compute_scan_snapshot(scan_item, scan_index, scan_mode, puma, vals, data_folder, ...):
    """Compute the complete params snapshot for one scan point.
    
    Returns:
        dict with keys:
            'params': dict — the set_parameters() kwargs (set to None for error sentinels)
            'output_folder': str — scan folder path
            'deltaE': float — energy transfer for this point
            'scan_index': int — position in the filtered scan list
            'error_flags': list — from calculate_angles(), empty if OK
            'metadata': dict — scan_mode, qx/qy/qz or H/K/L, angles, 
                                bending, orientation values for logging
                                and scan_parameters.txt
            'indices': dict — idx_1d / idx_x / idx_y for display updates
            'log_message': str — human-readable scan parameter summary
    """
```

This function is pure — it reads from `scan_point` (the array of scan values), `puma` config (for `calculate_angles()`), and `vals` (frozen GUI state). It does not mutate `puma` or any shared state. All the angle calculation, bending calculation, orientation parameter resolution, E0_param computation, and folder path generation happens here.

The prep thread calls this function in a loop, one call per scan point, and puts the result on the queue.

**Error sentinels**: If `calculate_angles()` returns non-empty `error_flags`, the snapshot is still produced but with `params` set to `None`. The simulation thread checks `if snapshot['params'] is None` to skip `backengine()` and record the point as failed. This preserves the current behavior where unreachable scan points appear as NaN/zero in results.

**Log message emission**: `compute_scan_snapshot()` prepares `snapshot['log_message']`, but the simulation thread emits it immediately after dequeuing the snapshot and before running the current point. Messages therefore stay aligned with the point that is starting simulation, not with prep-thread lead time.

**rva handling**: `rva` defaults to `self.PUMA.rva` for ordinary scans, but the snapshot logic still honors `rva` when it is one of the active scan variables.

**GUI access boundary**: ALL GUI reads must complete before the prep thread starts. Store local variables from `self.window.*` accessors — including `compact_save_check.isChecked()`, `relative_1_button.isChecked()`, `relative_2_button.isChecked()` — before calling `prep_thread.start()`. The prep thread must never access `self.window` or any Qt widget.

**Current status**: `run_simulation_thread()` now calls `save_parameters()` on the GUI thread, freezes launch state via `_collect_simulation_launch_state()`, and sets display scan metadata from the frozen launch values before starting the worker. `run_simulation()` consumes that frozen `launch_state`, uses the scan-local `scan_puma_config` instead of mutating `self.PUMA` during startup, no longer reads live Qt widgets for scan setup, and no longer depends on live `self.diagnostic_settings` during the run. Actual output-folder updates and pre-scan estimate updates are routed back to the main thread through `actual_output_folder_updated` and `pre_scan_estimate_updated`.

### Step 3: Implement the pipeline

Modifications to `TAVIController.run_simulation_thread()` and `run_simulation()`:

```
run_simulation_thread():
    # --- GUI-thread launch freeze ---
    # save_parameters(), get_gui_values(), copy diagnostic settings,
    # build scan-local PUMA config, set display metadata, start worker
    # with frozen launch_state

run_simulation(launch_state):
    # --- Worker-thread setup from frozen launch state ---
    # choose output folder, write parameters, parse scan commands from
    # launch_state['vals'], build scan_parameter_input list, etc.
    
    # --- NEW: Build instrument once ---
    instrument = build_PUMA_instrument(self.PUMA, diagnostic_mode, 
                                       self.diagnostic_settings)
    
    # --- NEW: Create pipeline primitives ---
    snapshot_queue = queue.Queue()
    stop_event = threading.Event()
    
    # --- NEW: Start prep thread ---
    prep_thread = threading.Thread(
        target=self._prep_worker,
        args=(scan_parameter_input, scan_mode, self.PUMA, vals,
              data_folder, snapshot_queue, stop_event),
        daemon=True
    )
    prep_thread.start()
    
    # --- Simulation loop (runs in existing worker thread) ---
    for i in range(total_scans):
        if stop_event.is_set():
            break
        
        # Pull next snapshot (blocks until prep thread delivers)
        snapshot = snapshot_queue.get()
        
        if stop_event.is_set():
            break
        
        # --- Simulation ---
        if not snapshot['error_flags']:
            data, error_flags = run_PUMA_point(
                instrument, snapshot['params'],
                snapshot['output_folder'], i
            )
        else:
            data = math.nan
            error_flags = snapshot['error_flags']
            # Log the error
            self.message_printed.emit(
                f"Point {i}: skipped, error flags: {error_flags}"
            )
        
        # --- Inline postprocessing (unchanged logic) ---
        # read_1Ddetector_file(), write_parameters_to_file(),
        # emit scan_point_updated signals, record timing, etc.
        # Uses snapshot['metadata'] for logging and parameter file.
    
    # --- Cleanup ---
    prep_thread.join(timeout=5)
    # ... existing completion logic ...
```

The prep worker:

```
def _prep_worker(self, scan_parameter_input, scan_mode, puma, vals,
                 data_folder, snapshot_queue, stop_event):
    """Prep thread: compute snapshots and feed the queue."""
    for i, scan_item in enumerate(scan_parameter_input):
        if stop_event.is_set():
            break
        
        snapshot = compute_scan_snapshot(
            scan_item, scan_mode, puma, vals, data_folder, i
        )
        
        # Enqueues without waiting so prep can run ahead of simulation
        # and fill the queue with the full scan if it finishes first
        snapshot_queue.put(snapshot)
    
    # Signal end-of-input
    snapshot_queue.put(None)  # Sentinel
```

### Step 4: Adapt progress and timing

The simulation loop already owns progress emission (it runs after each point's postprocessing). In the current implementation, first-point timing still includes the lazy McStas compile that occurs on the first `run_PUMA_point()` call. Compilation time is therefore still inferred from first-point timing rather than measured independently.

The `RuntimeTracker` (`tavi/runtime_tracker.py`) now persists a heuristic `compilation_time` field for new records, derived from `first_scan_time - avg_subsequent_time` on multi-point scans. The live code still relies on first-point timing because McStas compilation occurs lazily inside the first `run_PUMA_point()` call. Current behavior:

1. **`compilation_time` field** exists on `ScanRecord` with a default of `0.0` for backward compatibility with existing `runtimes.json` records.

2. **`add_record()`** accepts an optional `compilation_time` parameter and stores it in new records.

3. **`get_estimates()`** uses `compilation_time` directly when it is present and positive. Older records still fall back to `first_scan_time - avg_subsequent_time`.

4. **Single-point scans** are recorded in the simple Option A model with `compilation_time = 0.0` and use first-point timing as their run-time contribution. This keeps the current setup simple, but it is still heuristic rather than a true compile/run separation.

5. **Queue progress vs runtime estimates are now tracked separately**: `progress_updated(processed_points, total_scans)` still reports controller progress across all queued snapshots, including invalid/skipped points. Runtime-facing estimates use the executable subset instead: the pre-scan historical estimate is based on the validated `estimated_runtime_points` count, the live remaining-time label is driven by `remaining_runtime_points` plus `executed_scan_times`, and `RuntimeTracker.add_record()` stores `num_points=len(executed_scan_times)`. Queued-invalid points still appear in progress, but they no longer inflate remaining-time estimates or stored runtime history.

6. **Per-stage timing capture is now recorded for each run**: the prep thread records `prep_duration_s` from snapshot preparation start until the snapshot is successfully queued; the simulation thread records `simulation_duration_s` around `run_PUMA_point()`; and the controller records `postprocessing_duration_s` from the end of `run_PUMA_point()` until point bookkeeping, file writes, and UI signal emission complete. These per-point records are written to `stage_timing_summary.json` in the run output folder, along with run-level averages. Compile timing is still inferred rather than directly measured: when there are at least two successful simulated points, the summary records `compile_duration_s = first_simulation_duration - avg(subsequent_simulation_durations)`.

### Step 5: Update stop mechanism

Replace `self.stop_flag` (bool) with `self.stop_event` (threading.Event):

- `stop_simulation()` calls `self.stop_event.set()` instead of `self.stop_flag = True`.
- Prep thread checks `stop_event.is_set()` before each snapshot computation.
- Simulation thread checks `stop_event.is_set()` before each `queue.get()`.
- Reset with `self.stop_event.clear()` at the start of `run_simulation_thread()`.

## 5. Thread Topology

```
Main Thread (Qt event loop)
│
├── Simulation Thread (existing threading.Thread from run_simulation_thread)
│   ├── Starts with frozen launch_state captured on the GUI thread
│   ├── Owns the instrument object after build_PUMA_instrument()
│   ├── Pulls snapshots from queue
│   ├── Calls run_PUMA_point() → subprocess.run() (GIL released)
│   ├── Does inline postprocessing
│   └── Emits Qt signals for UI updates
│
└── Prep Thread (new, daemon, started by simulation thread)
    ├── Computes param snapshots from scan_parameter_input
    ├── Pushes snapshots onto an unbounded Queue()
    └── Exits when all points computed or stop_event set
```

Three threads total (main + simulation + prep). The prep thread is a daemon started by the simulation thread and joined when the scan completes or is cancelled. The simulation thread is the existing worker thread started by `run_simulation_thread()`.

## 6. Data Flow

```
Scan start
│
├─ GUI thread: save_parameters()
├─ GUI thread: _collect_simulation_launch_state() → frozen vals,
│               diagnostic settings, scan-local PUMA config,
│               relative-mode flags, compact-save flag
├─ GUI thread: set display metadata from frozen launch values
│
▼ (enters simulation thread with launch_state)
│
├─ parse scan commands from frozen launch values → scan_parameter_input list
│
├─ build_PUMA_instrument(PUMA, diag, settings) → reusable instrument object
│  (one-time; McStas compilation remains lazy and occurs on the first run_PUMA_point()/backengine() call)
│
├─ Start prep thread
│
│   Prep thread                          Simulation thread
│   ───────────                          ─────────────────
│   for each scan_item:                  for i in range(total_scans):
│     snapshot = compute_scan_snapshot()    snapshot = queue.get()  ◄── blocks until ready
│     queue.put(snapshot)  ──────────►     run_PUMA_point(instrument, snapshot)
│                                         postprocess(snapshot, data)
│                                          emit signals
│   queue.put(None)  ──── sentinel ──►   break on None
│
▼
Scan complete → emit scan_completed, record timing
```

## 7. Snapshot Format

```python
snapshot = {
    # For instrument.set_parameters()
    'params': {
        'A1_param': float,
        'A2_param': float,
        'A3_param': float,
        'A4_param': float,
        'E0_param': float,
        'saz_param': float,
        'rhm_param': float,
        'rvm_param': float,
        'rha_param': float,
        'rva_param': float,
        'vbl_hgap_param': float,
        'pbl_hgap_param': float,
        'pbl_vgap_param': float,
        'dbl_hgap_param': float,
        'chi_param': float,
        'kappa_param': float,
        'mis_chi_param': float,
        'psi_param': float,
        'mis_omega_param': float,
        'chi_total': float,
        'omega_offset_total': float,
    },

    # Pipeline metadata
    'output_folder': str,       # e.g. "output/scan_003/scan_0017"
    'scan_index': int,          # position in scan_parameter_input
    'deltaE': float,            # energy transfer for this point
    'error_flags': list,        # [] if OK, ['mtt', 'stt', ...] if error
    
    # For postprocessing / logging (written to scan_parameters.txt)
    'metadata': {
        'scan_mode': str,       # 'momentum', 'rlu', 'angle', 'orientation'
        'qx': float | None,
        'qy': float | None,
        'qz': float | None,
        'H': float | None,
        'K': float | None,
        'L': float | None,
        'mtt': float,
        'stt': float,
        'sth': float,
        'att': float,
        'rhm': float,
        'rvm': float,
        'rha': float,
        'rva': float,
        'omega': float,
        'chi': float,
        'psi': float,
        'kappa': float,
        'E0_param': float,
        'Ei': float,
        'Ki': float,
        'Ef': float,
        'Kf': float,
    },
    
    # For display dock indexing
    'indices': {
        'idx_1d': int,          # -1 if 2D scan
        'idx_x': int,           # -1 if 1D scan
        'idx_y': int,           # -1 if 1D scan
    },
    
    # For message center
    'log_message': str,
}
```

## 8. Failure Modes and Mitigations

### 8.1 Prep thread crashes

If `compute_scan_snapshot()` raises an unhandled exception, the prep thread dies and the simulation thread blocks forever on `queue.get()`.

Mitigation: wrap the prep worker body in try/except. On exception, put an error sentinel on the queue and set `stop_event`. The simulation thread sees the sentinel, logs the error, and exits cleanly.

### 8.2 Simulation thread crashes

If `run_PUMA_point()` or postprocessing raises an unhandled exception, the simulation thread dies while the prep thread may still be running (blocked on `queue.put()`).

Mitigation: wrap the simulation loop in try/except/finally. In the finally block, set `stop_event` (unblocks prep thread's `stop_event.is_set()` check) and join the prep thread. The prep thread sees the event and exits.

### 8.3 Queue deadlock

With the current unbounded `Queue()`, there is no queue-full backpressure path to deadlock on. The simulation thread only waits on `queue.get()`, and the prep thread holds no locks while preparing snapshots, so the queue remains the only synchronization primitive.

### 8.4 Subprocess failure (McStas crash)

Per-point execution now runs through a mixed path behind `run_PUMA_point()`: first-point materialization still goes through `instrument.backengine()`, while later eligible points may run the compiled binary directly. A non-zero direct process return code or missing `detector.dat` is treated as a per-point execution failure, and stdout/stderr is surfaced through the existing message-center logging path before the point is marked failed. Live integration validation of this direct path is still pending.

### 8.5 Stale instrument object

The instrument object from `build_PUMA_instrument()` is used by the simulation thread for all points. If something mutates it unexpectedly (McStasScript internal state corruption), subsequent points could fail. Mitigation: `run_PUMA_point()` only calls `settings()`, `set_parameters()`, and `backengine()` on the instrument — no component tree modification. McStasScript's `backengine()` is designed to be called repeatedly on the same instrument object with different parameters and output paths.

## 9. Files Changed

| File | Changes |
|------|---------|
| `instruments/PUMA_instrument_definition.py` | Split `run_PUMA_instrument()` into `build_PUMA_instrument()` + `run_PUMA_point()`. Add `compute_scan_snapshot()` and the per-point snapshot contract used by the queue. |
| `TAVI_PySide6.py` | Refactor `run_simulation()` to use the prep thread, snapshot queue, and simulation loop. Replace `stop_flag` bool with `threading.Event`. Add `_prep_worker()` and emit per-point log messages from the simulation thread when each point starts. |
| `tavi/mcstas_config.py` | Add centralized MPI launcher resolution for direct execution, with McStasScript configuration / `mccode_config.json` fallback and preference for a direct `mpiexec` binary over wrapper batch launchers when available. |
| `tavi/runtime_tracker.py` | Add a heuristic `compilation_time` field to `ScanRecord` and `add_record()`, and update `get_estimates()` to prefer it when present. |
| `CLAUDE.md` | Update architecture section to document pipeline pattern, snapshot contract, threading model. |

## 10. What This Does NOT Change

- **DisplayDock**: results still arrive in order (simulation thread processes points sequentially). No out-of-order handling needed.
- **Signal semantics**: `scan_point_updated_1d/2d`, `scan_completed`, `progress_updated` are emitted from the simulation thread exactly as before, at the same logical points.
- **Output file format**: `scan_parameters.txt`, detector files, `.instr` copy — all unchanged.
- **Diagnostic mode**: instrument diagram request is emitted once after `build_PUMA_instrument()`. Diagnostic monitors are build-time decisions, frozen at `build_PUMA_instrument()`. The direct-binary slice keeps diagnostic plotting on the retained first-point `backengine()` McStasData; later direct-invocation points do not replace that retained diagnostic data.
- **Single-point scans**: work identically; the prep thread computes one snapshot and exits.
- **Progress signal semantics**: `progress_updated` still reports queued controller progress in command order, including skipped points. The timing labels and runtime history now use only executable points, so queue progress and runtime estimates are intentionally distinct.

## 11. Sequencing

1. Split `run_PUMA_instrument()` → `build_PUMA_instrument()` + `run_PUMA_point()`. Implemented.
2. Implement `compute_scan_snapshot()`. Implemented.
3. Replace `stop_flag` with `threading.Event`. Implemented.
4. Implement the pipeline (prep thread, queue, modified simulation loop). Implemented.
5. Update `RuntimeTracker` to separate compilation time. Implemented in heuristic Option A form.
6. Land the first direct-binary invocation slice behind `run_PUMA_point()`. Implemented in code, pending live-environment validation.
7. Update `CLAUDE.md`. Implemented.

## Implementation Notes

### 2026-05-12

- `build_PUMA_instrument()` and `run_PUMA_point()` are now implemented in code, and `TAVIController.run_simulation()` uses a prep thread plus an unbounded `Queue()` to overlap snapshot preparation with simulation.
- `compute_scan_snapshot()` is now the active per-point API for snapshot generation, and `self.stop_flag` has been replaced by `self.stop_event` (`threading.Event`) in the simulation control path.
- Scan parameter log messages are prepared inside `compute_scan_snapshot()` but emitted by the simulation thread when the current point begins, so message order matches executed points rather than prep-thread lead time.
- The simulation thread and prep thread now both consume a frozen scan-local PUMA configuration created at scan start, so mid-run GUI mutations of `self.PUMA` do not affect the in-flight run.
- `run_simulation_thread()` now freezes launch state on the GUI thread before the worker starts, calls `save_parameters()` before thread launch, and sets display scan metadata from the frozen launch values. Main-thread folder-label and pre-scan-estimate updates are routed through controller signals during the run.
- The live run path now enqueues every requested scan point in command order. The display is initialized optimistically, and impossible points are marked invalid dynamically when the simulation thread processes a snapshot with error flags.
- Queue progress and timing estimates now diverge by design: `processed_points / total_scans` still reflects all queued snapshots, while the pre-scan estimate, remaining-time estimate, and stored runtime history are driven by executable-point counts (`estimated_runtime_points`, `remaining_runtime_points`, and `executed_scan_times`).
- Stage timing data is now captured per run: prep time is measured in `_prep_worker()`, simulation time is measured around `run_PUMA_point()`, postprocessing time is measured in the simulation thread after `run_PUMA_point()` returns, and a `stage_timing_summary.json` file is written under the output folder with per-point timings plus run-level averages. Compile timing in that summary remains inferred from first-versus-steady-state simulation durations rather than directly observed from a separate compile callback.
- Controller logging now records when a first successful `backengine()` point arms direct execution and when later points run in direct mode.
- The per-point timing records written to `stage_timing_summary.json` now include `execution_mode`, `direct_returncode`, and `direct_binary_path` alongside the stage durations.
- McStasScript compilation still happens lazily on the first `backengine()` call. `build_PUMA_instrument()` builds the reusable instrument object once, but it does not perform a standalone compile step because `mcstasscript` writes and compiles the instrument from `backengine()`, not from `settings()`.
- `tavi/runtime_tracker.py` now records a heuristic `compilation_time` field for new runs. Compile remains bundled into the first executed point, so this is still an inferred estimate rather than an independently measured compile phase.
- The first direct-binary slice is now live behind `run_PUMA_point()`: it reuses `params_snapshot['params']` for CLI `name=value` arguments, resolves the MPI launcher from McStasScript's configured McStas state after setup with fallback to the same `mccode_config.json` used by `mcrun.py`, resolves the binary to an absolute path after first successful materialization, uses the binary directory as subprocess `cwd`, switches only when first-point `backengine()` succeeded and the direct-run-ready state plus binary-exists check are both satisfied, retains first-point diagnostic McStasData for diagnostic mode, and treats non-zero direct exits or missing `detector.dat` as ordinary per-point failures while surfacing stdout/stderr through the message center.
- This direct-execution path is documented from the code, but it has not yet been integration-validated in a live McStas environment, so runtime behavior should still be treated as provisional until that smoke test is completed.

Steps 1–4, the controller GUI-state freeze boundary, the stop-event conversion, and the first direct-binary execution slice are now in the live codebase. Runtime tracking is implemented in a simple heuristic form; explicit compile-time measurement and live-environment validation of the direct path still require follow-up.
