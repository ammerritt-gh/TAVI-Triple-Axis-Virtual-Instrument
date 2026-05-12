# Pipelined Scan Execution — Design Document

*Date: 2026-05-12*
*Status: Ready to implement*

---

## 1. Goal

Keep the McStas simulation binary running at near-100% CPU utilization throughout a multi-point scan by overlapping Python preparation work with the C-level simulation. Current profiling shows that out-of-simulation Python work (angle calculation, folder creation, parameter setup, postprocessing) accounts for 50–60% of wall time on shorter scans. The pipeline hides this latency behind the simulation's wall time.

## 2. Architecture Overview

Two threads, one queue:

```
                    Queue(maxsize=2)
  [Prep Thread] ──────────────────────► [Simulation Thread]
  produces snapshots                    consumes snapshots
  (pure Python, GIL-bound)              calls backengine() (subprocess, GIL released)
                                        does inline postprocessing after each point
```

The prep thread runs continuously, computing parameter snapshots and pushing them onto a bounded queue. The simulation thread pulls snapshots and executes them. `Queue(maxsize=2)` provides natural backpressure — the prep thread blocks when two snapshots are buffered, which is fine; it resumes as soon as the simulation thread pulls one. With 30 MPI threads for McStas and 32 CPU threads available, the prep thread borrowing one core intermittently has negligible impact.

Postprocessing stays inline in the simulation thread (no third stage). Postprocessing is lightweight — reading a small detector file, writing a small parameter file, emitting Qt signals — and separating it would add a thread, a second queue, and out-of-order handling complexity for negligible gain.

### Why this works (GIL verification)

McStasScript's `backengine()` calls `ManagedMcrun.run_simulation()`, which calls `subprocess.run()` (file: `.venv/Lib/site-packages/mcstasscript/helper/managed_mcrun.py`, line 292). CPython releases the GIL during `subprocess.run()` because it is a blocking wait on a child process. This means the prep thread's Python code genuinely executes in parallel with the McStas simulation. The pipeline provides real throughput gains, not just concurrency illusion.

## 3. Design Decisions (Resolved)

### 3.1 Params dict, not PUMA clone

The prep thread produces an immutable params dict — the exact kwargs for `instrument.set_parameters()` — plus metadata (output folder, scan indices, deltaE, error flags). The simulation thread never reads from the shared `self.PUMA` object during execution; it consumes only what the prep thread put on the queue.

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

### 3.5 Queue size: maxsize=2

Two buffered snapshots. The prep thread runs freely, computing as fast as it can; the queue blocks it when two snapshots are waiting. This ensures the simulation thread always has a snapshot ready when it finishes a point, even if one prep cycle is unusually slow. Memory cost is negligible (two small dicts).

## 4. Refactoring Plan

### Step 1: Split `run_PUMA_instrument()`

Split into two functions in `instruments/PUMA_instrument_definition.py`:

**`build_PUMA_instrument(puma_config, diagnostic_mode, diagnostic_settings)`**

- Takes PUMA instrument configuration (arm lengths, crystal types, NMO setting, sample type, collimator selection, source type, diagnostic settings) — everything that affects which components are included.
- Calls `ms.McStas_instr(...)`, adds all parameters via `add_parameter()`, adds all components via `add_component()`, calls `instrument.settings(..., force_compile=True)`.
- Returns the compiled instrument object.
- Called **once** at scan start, before any simulation.

**`run_PUMA_point(instrument, params_snapshot, output_folder, run_number)`**

- Takes the compiled instrument object, a params dict (the `set_parameters()` kwargs), the output folder path, and the run number.
- Calls `instrument.settings(output_path=output_folder, ..., force_compile=False)`.
- Calls `instrument.set_parameters(**params_snapshot)`.
- Calls `instrument.backengine()`.
- Returns `(data, error_flag_array)`.
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

A function (method on TAVIController or a standalone helper) that takes the current scan point data and returns a dict:

```python
def compute_scan_snapshot(scan_point, scan_mode, puma, vals):
    """Compute the complete params snapshot for one scan point.
    
    Returns:
        dict with keys:
            'params': dict — the set_parameters() kwargs
            'output_folder': str — scan folder path
            'deltaE': float — energy transfer for this point
            'scan_indices': tuple — (idx_1d,) or (idx_x, idx_y)
            'error_flags': list — from calculate_angles(), empty if OK
            'metadata': dict — scan_mode, qx/qy/qz or H/K/L, angles, 
                                bending, orientation values for logging
                                and scan_parameters.txt
    """
```

This function is pure — it reads from `scan_point` (the array of scan values), `puma` config (for `calculate_angles()`), and `vals` (frozen GUI state). It does not mutate `puma` or any shared state. All the angle calculation, bending calculation, orientation parameter resolution, E0_param computation, and folder path generation happens here.

The prep thread calls this function in a loop, one call per scan point, and puts the result on the queue.

### Step 3: Implement the pipeline

Modifications to `TAVIController.run_simulation()`:

```
run_simulation(data_folder):
    # --- Existing setup (unchanged) ---
    # get_gui_values(), configure PUMA, parse scan commands,
    # build scan_parameter_input list, initialize display dock, etc.
    
    # --- NEW: Build instrument once ---
    instrument = build_PUMA_instrument(self.PUMA, diagnostic_mode, 
                                       self.diagnostic_settings)
    
    # --- NEW: Create pipeline primitives ---
    snapshot_queue = queue.Queue(maxsize=2)
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
        
        # Log scan parameters (thread-safe signal emission)
        self.message_printed.emit(snapshot['log_message'])
        
        # Blocks if queue is full (maxsize=2); resumes when
        # simulation thread pulls a snapshot
        snapshot_queue.put(snapshot)
    
    # Signal end-of-input
    snapshot_queue.put(None)  # Sentinel
```

### Step 4: Adapt progress and timing

The simulation loop already owns progress emission (it runs after each point's postprocessing). The only change: the first-point timing now reflects `run_PUMA_point()` without compilation overhead, since `build_PUMA_instrument()` happens before the loop. Compilation time should be reported separately ("Compiling instrument..." message before the loop starts).

The `RuntimeTracker` records should separate compilation time from per-point time. The `first_scan_time` field currently includes compilation; after this refactor, `first_scan_time` is a true per-point time and compilation is a separate field.

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
│   ├── Owns the instrument object after build_PUMA_instrument()
│   ├── Pulls snapshots from queue
│   ├── Calls run_PUMA_point() → subprocess.run() (GIL released)
│   ├── Does inline postprocessing
│   └── Emits Qt signals for UI updates
│
└── Prep Thread (new, daemon, started by simulation thread)
    ├── Computes param snapshots from scan_parameter_input
    ├── Pushes snapshots onto Queue(maxsize=2)
    └── Exits when all points computed or stop_event set
```

Three threads total (main + simulation + prep). The prep thread is a daemon started by the simulation thread and joined when the scan completes or is cancelled. The simulation thread is the existing worker thread started by `run_simulation_thread()`.

## 6. Data Flow

```
Scan start
│
├─ GUI thread: get_gui_values() → frozen vals dict
├─ GUI thread: parse scan commands → scan_parameter_input list
│
▼ (enters simulation thread)
│
├─ build_PUMA_instrument(PUMA, diag, settings) → compiled instrument
│  (one-time, includes compilation, ~10-30s)
│
├─ Start prep thread
│
│   Prep thread                          Simulation thread
│   ───────────                          ─────────────────
│   for each scan_item:                  for i in range(total_scans):
│     snapshot = compute_scan_snapshot()    snapshot = queue.get()  ◄── blocks until ready
│     queue.put(snapshot)  ──────────►     run_PUMA_point(instrument, snapshot)
│       (blocks if queue full)             postprocess(snapshot, data)
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

Could occur if: prep thread waits on `queue.put()` (queue full) while simulation thread waits on something the prep thread holds. This cannot happen in this design — the simulation thread only waits on `queue.get()`, and the prep thread holds no locks. The queue itself is the only synchronization primitive.

### 8.4 Subprocess failure (McStas crash)

`subprocess.run()` returns a non-zero exit code or the output folder doesn't contain detector files. This is already handled by the current code (error flags, NaN data). No change needed — `run_PUMA_point()` returns the error, postprocessing records it.

### 8.5 Stale instrument object

The instrument object from `build_PUMA_instrument()` is used by the simulation thread for all points. If something mutates it unexpectedly (McStasScript internal state corruption), subsequent points could fail. Mitigation: `run_PUMA_point()` only calls `settings()`, `set_parameters()`, and `backengine()` on the instrument — no component tree modification. McStasScript's `backengine()` is designed to be called repeatedly on the same instrument object with different parameters and output paths.

## 9. Files Changed

| File | Changes |
|------|---------|
| `instruments/PUMA_instrument_definition.py` | Split `run_PUMA_instrument()` into `build_PUMA_instrument()` + `run_PUMA_point()`. Add `compute_scan_snapshot()`. Clean up `add_parameter` default values on lines 925–934. |
| `TAVI_PySide6.py` | Refactor `run_simulation()` to use pipeline (build once, prep thread, snapshot queue, simulation loop). Replace `stop_flag` bool with `threading.Event`. Extract prep logic from the scan loop into snapshot computation. Update timing to separate compilation from per-point. |
| `tavi/runtime_tracker.py` | Add `compilation_time` field to runtime records (separate from `first_scan_time`). |
| `CLAUDE.md` | Update architecture section to document pipeline pattern, snapshot contract, threading model. |

## 10. What This Does NOT Change

- **DisplayDock**: results still arrive in order (simulation thread processes points sequentially). No out-of-order handling needed.
- **Signal semantics**: `scan_point_updated_1d/2d`, `scan_completed`, `progress_updated` are emitted from the simulation thread exactly as before, at the same logical points.
- **Output file format**: `scan_parameters.txt`, detector files, `.instr` copy — all unchanged.
- **Diagnostic mode**: instrument diagram request still works (instrument object is available in the simulation thread). Diagnostic monitors are build-time decisions, frozen at `build_PUMA_instrument()`.
- **Single-point scans**: work identically; the prep thread computes one snapshot and exits.

## 11. Sequencing

1. Split `run_PUMA_instrument()` → `build_PUMA_instrument()` + `run_PUMA_point()`. Test that sequential (non-pipelined) scans still work with the new functions.
2. Implement `compute_scan_snapshot()`. Test that it produces correct params dicts by comparing against the current inline computation.
3. Replace `stop_flag` with `threading.Event`. Verify stop behavior unchanged.
4. Implement the pipeline (prep thread, queue, modified simulation loop). Test with short and long scans.
5. Update `RuntimeTracker` to separate compilation time.
6. Update `CLAUDE.md`.

Steps 1–3 are independently testable and low-risk. Step 4 is the integration point. Each step should leave the codebase in a working state.
