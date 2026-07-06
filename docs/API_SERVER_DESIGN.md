# Remote API Server — Design Document

*Date: 2026-07-03*
*Status: Implemented (2026-07-03) — all 5 phases landed and live-verified against a running PUMA GUI (health/state/parameters, PATCH with linked recompute, POST /scan with 1D/2D scans and budget 429s, stop/drain, and SSE streaming all exercised).*

> **Forward note (2026-07-03):** user-facing documentation now lives in
> `docs/API_USER_GUIDE.md`. That guide is the authoritative reference for
> clients (humans and LLM agents) — exact endpoints, request/response JSON,
> the full 40-field parameter table, scan-command syntax, SSE events, budgets,
> and gotchas. This document remains the design/architecture record.
>
> **Post-design fixes (not in the original body):**
> - `set`/`frozenset` values are JSON-serialized as sorted lists (both the API
>   server and `scan_jobs` sanitizers) so multi-select collimation survives
>   `json.dumps`.
> - `job_queued` is published *before* the job is enqueued, guaranteeing clients
>   see `job_queued` ahead of `job_started` for a job the idle worker picks up
>   immediately.
> - Routine client disconnects (killed `curl`, closed SSE tab) are handled
>   quietly via `_TaviHTTPServer.handle_error`, logged as a note instead of
>   dumping a socket traceback to stderr.
> - `GET /scan/{id}/data` returns the job snapshot with the `result` arrays
>   expanded (completeness is read from the job `state`); there is no separate
>   top-level `complete` flag as sketched in §6.1.

---

## 1. Goal

Allow external programs to drive TAVI over a local network port: read the current instrument setup and state, set parameters, submit scan commands, and retrieve scan data both live (per-point streaming) and after completion (full arrays). The API must coexist with interactive GUI use — the user sees what remote programs do, can restrict or disable remote control, and is protected from abusive submissions (e.g. a week's worth of queued scans) by in-program limits.

## 2. Requirements and Decisions

These were resolved during design review:

| Question | Decision |
|---|---|
| Protocol | HTTP/REST with JSON bodies plus Server-Sent Events (SSE) for live streaming. Stdlib only (`http.server.ThreadingHTTPServer`) — no new dependencies. Any language or plain `curl` can be a client. |
| Control scope | Full parameter set: everything `get_gui_values()` covers (energies, Q/HKL, angles, lattice, crystals, collimation, slits, neutron count, scan commands). API writes update the GUI widgets visibly so the user sees what the remote program did. |
| Data delivery | Both: (a) live per-point SSE events mirroring the `scan_point_updated_*` signals, and (b) a JSON endpoint returning full arrays, valid mid-run (partial) and after completion. |
| Busy policy | Job queue with sequential execution. GUI-initiated runs become jobs too, which also fixes an existing bug where double-clicking Run spawns concurrent scans (no busy flag exists today). |
| GUI surface | A new API dock (`BaseDockWidget` pattern): server status, access-mode toggle, job queue table, budget readout, activity log. |
| Access modes | Three modes, default **Allow control**: full API. **Read-only**: GET and SSE only, writes rejected with 403. **Off**: server not listening. Live-switchable from the dock, persisted in config. |
| Abuse limits | Defaults: max 10 queued jobs, max 200 points per scan, max 1e8 neutrons per point, total pending-queue neutron budget of 1e10 (sum of points × neutrons over queued jobs). Over-limit submissions get HTTP 429 with the reason and current usage. Limits apply to API-sourced jobs only; GUI jobs bypass them (local user is trusted) but still queue serially. All values overridable in `config/api_config.json`. |
| Security | Bind `127.0.0.1` by default. Optional bearer token. Loud warning in the message center for non-loopback binds. No TLS (loopback scope). |

## 3. Current-State Facts the Design Builds On

All line references in `TAVI_PySide6.py` unless noted (as of 2026-07-03, `main` @ 7117b541):

- **Scan start path:** `run_simulation_thread()` (:2833) runs on the GUI thread — validates via `_preflight_scan_validation()` (:2869; its helpers `_validate_single_scan_command` :1463 and `_check_scan_parameter_conflict` :1532 are pure, the `QMessageBox` lives in the caller), persists via `save_parameters()`, freezes `launch_state = _collect_simulation_launch_state()` (:638, wrapping `get_gui_values()` :564, ~35 flat fields including `scan_command1/2`), then spawns a bare `threading.Thread(target=run_simulation)`.
- **`run_simulation(launch_state)` (:3001) never touches widgets.** It is fully driven by the frozen dict and communicates only via Qt signals (`scan_initialized`, `scan_point_updated_1d/2d` :3463/:3469, `scan_completed`, `progress_updated`, `counts_updated`, `actual_output_folder_updated`, `message_printed`; defined :48–73). This means an API-submitted job can reuse it verbatim once `launch_state` is frozen on the GUI thread.
- **Prep pipeline:** `_prep_worker` (:2945) plus `queue.Queue`, shared `self.stop_event` (:88) with drain semantics — see `docs/PIPELINE_DESIGN.md`. Unchanged by this design.
- **Scan arrays are function-local.** `scan_x_values`/`scan_counts` (:3225) and `counts_grid` (:3222) are discarded after each run; only disk files (`1D_scan_data.txt`, `2D_scan_data.txt`, per-point `detector.dat`) and `display_dock._scan_data` retain them. Counts contain NaN for invalid points.
- **Parameter setter surface:** `load_parameters()` (:2567) shows every widget setter (`setText`, `set_mono_id`, `set_module_values`, `set_collimation_values`, `set_slit_values_mm`, `set_number_neutrons`, `K_fixed_combo.setCurrentText`) and the dependency-ordering rationale (~:2677). Per-field recompute handlers: `on_Ki_changed` :1069, `on_Ei_changed` :1097, `on_Q_changed` :1253, `on_HKL_changed` :1293, `on_lattice_changed` :1331.
- **No busy flag exists.** The Run button is never disabled; a second click spawns a concurrent `run_simulation` thread racing on `config/parameters.json`, the output folder, and display signals.
- **Known dead code:** `gui/main_window.py:395` sets `controller.stop_flag = True` in `closeEvent`, but that attribute was replaced by `stop_event` — window close does not stop a running scan. Fixed as part of this work.
- **No networking/IPC code exists anywhere in the repo.** CLI is argparse with a single `--instrument` flag (`main()` :3703–3758).
- **Config pattern:** plain `json.load` of `config/*.json` (see `tavi/mcstas_config.py` `_load_local_config`); this design follows the pattern but avoids that module's import-time side effect.

## 4. Architecture Overview

Three layers, strictly separated:

```
 External client                     GUI thread                        Worker threads
 ───────────────                     ──────────                        ──────────────
 curl / script ──HTTP──► ApiRequestHandler        ApiBridge slot ◄─Signal── (queued conn)
                         (per-request thread,     runs fn, sets Event
                          tavi/api_server.py)          │
                              │                        │ read/set widgets,
                              │  backend callbacks     │ freeze launch_state,
                              ├────────────────────────┘ apply_parameters()
                              │
                              ├──► JobRegistry / job queue ──► Job worker thread
                              │         (tavi/scan_jobs.py)     run_simulation(launch_state, job)
                              │                                      │
                              ◄──SSE── SseBroker ◄───publish─────────┘
```

1. **HTTP layer** — `tavi/api_server.py`, pure stdlib, zero Qt imports. `ThreadingHTTPServer` with `daemon_threads = True` running in one daemon thread; each request gets its own thread. The server receives a duck-typed `backend` object (plain callables) at construction, so the module is unit-testable without Qt or the controller.
2. **GUI bridge** — `ApiBridge(QObject)` in `TAVI_PySide6.py`, created on the GUI thread. One primitive: `call_on_gui(fn, timeout=5.0)`. It wraps `fn` in a `_GuiCall` (callable, `threading.Event`, result, error) and emits it over a Signal; because the emitter is a worker thread, Qt delivers it as a queued connection to a GUI-thread slot, which executes `fn` and sets the event. On timeout the HTTP handler returns 503 `gui_busy`.
3. **Job worker** — one persistent daemon thread in the controller consuming a `queue.Queue` of `ScanJob`s and calling `run_simulation(launch_state, job)` per job. Replaces the current ad-hoc per-run thread.

SSE publishing bypasses Qt entirely: the `SseBroker` is pure Python with per-client bounded queues, called from the job worker thread right beside the existing signal emits.

### 4.1 Why not `QMetaObject.invokeMethod(BlockingQueuedConnection)`

It has no timeout. If the GUI thread is blocked in a modal dialog (validation `QMessageBox`, file picker, diagnostic config dialog), every API request thread would deadlock forever. The Event-based bridge converts that situation into a clean HTTP 503. Exceptions raised by `fn` propagate to the HTTP handler and become structured 400/500 JSON — no silent swallowing.

### 4.2 Why GUI runs become jobs

Routing the GUI Run button through the same job queue as API submissions gives one busy-handling mechanism, one place per-job GUI prep happens, and fixes the concurrent-run hole for free. The button keeps its existing validation dialog and is disabled/relabeled while a job is running or queued (via a new `job_state_changed` signal).

## 5. Module Layout

| File | Status | Contents |
|---|---|---|
| `tavi/api_server.py` | new | `TaviApiServer` (wraps `ThreadingHTTPServer`), `ApiRequestHandler` (route table, JSON helpers, bearer-token auth, access-mode gating), `SseBroker`, `load_api_config()`. No Qt, no controller import. |
| `tavi/scan_jobs.py` | new | `ScanJob` dataclass, `JobState` enum, `ScanResult` dataclass, `JobRegistry` (dict + lock, JSON-safe `snapshot()` views), `BudgetLimits` and queue-budget accounting. Pure data + locking. |
| `gui/docks/api_dock.py` | new | `ApiDock(BaseDockWidget)`: status, mode combo, job table, budget readout, activity log. |
| `TAVI_PySide6.py` | modified | `ApiBridge`/`_GuiCall`; job queue, worker thread, `submit_scan_job()`; `_api_field_map` + `apply_parameters()`; `run_simulation(job=...)` result sink; `_validate_scan_commands_text` refactor; server lifecycle + `shutdown()`; `--api-port`/`--no-api` CLI flags; new signals `job_state_changed(str, str)` and `api_activity(str)`. |
| `gui/main_window.py` | modified | Create/register `ApiDock` (pattern at :70–105 and :180–204, stable `objectName`); fix `closeEvent` :395. |
| `config/api_config.json` | new, optional | `{"enabled": true, "mode": "allow", "host": "127.0.0.1", "port": 8642, "token": null, "limits": {"max_queued": 10, "max_points": 200, "max_neutrons_per_point": 1e8, "queue_neutron_budget": 1e10}}`. Absent file means defaults (enabled, allow, loopback). |

Ownership follows CLAUDE.md: the controller orchestrates; `tavi/` holds reusable non-Qt code; no widget access off the GUI thread.

## 6. REST Surface

All endpoints under `/api/v1`. Errors are `{"error": {"code": str, "message": str, "details": ...}}`. If a token is configured, all endpoints except `/health` require `Authorization: Bearer <token>`.

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/health` | Liveness | `{"status":"ok","instrument":"puma","mode":"allow"}`; no auth |
| GET | `/state` | Full snapshot | instrument id, mode, busy, current job, queue ids, budget usage, full `get_gui_values()` dict |
| GET | `/parameters` | Parameters only | the `get_gui_values()` dict, read via bridge |
| PATCH | `/parameters` | Partial set | body e.g. `{"Ei": 14.7, "scan_command1": "H 1.9 2.1 0.01"}` → `{"applied": [...], "errors": {}}`. 400 with per-field errors; 409 while a scan is running (unless `?force=1`); 403 in read-only mode |
| POST | `/scan` | Submit job | optional inline `"parameters"` patch applied first → 202 `{"job_id":"j-0004","state":"queued","position":1}`. 400 `scan_validation`; 429 `limit_exceeded` with reason and usage; 403 in read-only mode |
| GET | `/scan/{id}` | Job status | state, source, timestamps, `progress: {done, total}`, count totals, output folder, error |
| GET | `/scan/{id}/data` | Scan arrays | same shape mid-run and final, distinguished by `complete` flag; see §6.1 |
| POST | `/scan/{id}/stop` | Cancel one job | queued → cancelled; running → stop event set (drain semantics); done → 409 |
| POST | `/stop` | Stop current | body `{"clear_queue": true}` also cancels queued jobs |
| GET | `/jobs` | Recent jobs | list of job summaries |
| GET | `/events` | SSE stream | `text/event-stream`; see §9 |

### 6.1 `/scan/{id}/data` payload

```json
{"job_id": "j-0003", "state": "running", "complete": false, "mode": "1D",
 "variable_1": "H", "variable_2": null,
 "scan_values_1": [1.9, 1.92, "..."], "scan_values_2": null,
 "valid_mask_1": [true, "..."], "valid_mask_2d": null,
 "counts": [123.0, null, "..."],
 "counts_grid": null,
 "total_counts": 123.0, "max_counts": 123.0,
 "output_folder": "output/my_scan_3",
 "metadata": {"...": "frozen launch vals snapshot"}}
```

For 2D scans `counts` is null and `counts_grid` is a list of rows. Unmeasured or invalid points are `null` — NaN must never appear in the JSON (`json.dumps(..., allow_nan=False)` behind a sanitizer), because bare `NaN` is invalid JSON and breaks strict parsers.

## 7. Job Queue and Budgets

### 7.1 Data structures (`tavi/scan_jobs.py`)

- `JobState`: `QUEUED / RUNNING / DONE / FAILED / CANCELLED / STOPPED`.
- `ScanJob`: `job_id` (`j-%04d`), `source` (`"gui"` or `"api"`), frozen `launch_state` dict, state, timestamps, `progress_done/total`, `error`, `result: ScanResult | None`, a `threading.Lock`. `snapshot(include_data=False)` returns a deep-copied JSON-safe dict under the lock.
- `ScanResult`: mode, variable names, scan value arrays, valid masks, `counts` (pre-sized list written by index) or `counts_grid`, count totals, output folder, metadata. Plain lists, not ndarrays, so `json.dumps` works directly.
- `JobRegistry`: id → job dict behind a lock; recent-jobs listing.
- `BudgetLimits`: the four limits plus an accounting helper. On API submission the server computes points (via `parse_scan_steps` from `tavi/utilities.py` on the scan commands in the frozen `launch_state`) × `number_neutrons`, and enforces: queue depth ≤ `max_queued`, points ≤ `max_points`, neutrons per point ≤ `max_neutrons_per_point`, and Σ(points × neutrons) over pending jobs ≤ `queue_neutron_budget`. GUI-source jobs skip the checks and do not consume budget.

### 7.2 Controller integration

- `__init__` gains `_job_registry`, `_job_queue`, and starts the worker thread.
- Worker loop: pop job → skip if `CANCELLED` → **clear the shared `self.stop_event`** (after pop, before `RUNNING`, so a Stop pressed between jobs cannot leak into the next one) → run `run_simulation(launch_state, job)` → final state. The single shared `stop_event` is kept (prep worker and consumer already reference it); per-job events are unnecessary because only one job runs at a time.
- `run_simulation_thread()` keeps its GUI prep and validation dialog, then calls `submit_scan_job(source='gui')` instead of spawning a thread.
- Per-job GUI prep (progress-bar reset, `display_dock.set_scan_metadata`) moves to a GUI-thread slot on `job_state_changed → running`, so API-submitted jobs get identical GUI treatment (the plot follows remote scans too).
- Stop semantics: GUI Stop button and `POST /stop` both set the stop event and mark the active job `STOPPED`; `clear_queue` additionally marks queued jobs `CANCELLED` so the worker skips them.

### 7.3 Retaining scan data

`run_simulation` gains a `job` parameter:

- After scan-geometry construction (~:3127/:3178), initialize `job.result` under `job.lock` with pre-sized `counts` (`[None] * n`) or `counts_grid`.
- At each point, beside the existing `scan_point_updated_1d/2d` emits (:3463/:3469) and the invalid-point branches, write `counts[idx]` / `counts_grid[iy][ix]`, totals, and `progress_done` under the lock, and publish the `point` SSE event.
- At completion set the final job state (`DONE`/`STOPPED`/`FAILED` from the existing error message), `finished_at`, and keep `self.last_scan_result = job.result`.
- Thread safety: only the worker thread writes; HTTP threads read via `snapshot()`, which deep-copies under the lock. Existing file-writing lists stay untouched (scoped change).

## 8. Parameter Writes → GUI Sync

A declarative field map in the controller mirrors `get_gui_values()` exactly:

```python
# field name -> FieldSpec(parse, widget_setter, after_handler)
'Ei':        FieldSpec(float, instrument_dock.Ei_edit.setText, on_Ei_changed)
'H':         FieldSpec(float, scattering_dock.H_edit.setText, on_HKL_changed)
'monocris':  FieldSpec(crystal-id check, set_mono_id, update_monocris_info)
'modules':   dict-valued, set_module_values, ...
'scan_command1': FieldSpec(str, scan_command_1_edit.setText, validate_scan_commands)
# ... energies, angles, lattice, kappa/psi, collimation, slits, number_neutrons, source, diagnostic_mode
```

`apply_parameters(patch) -> (applied, errors)` runs on the GUI thread via the bridge:

1. Parse and validate every field first; unknown key or bad value → collect in `errors`, skip that field entirely (no partial application within a field).
2. Apply in dependency order: lattice → energy mode (`K_fixed`, `fixed_E`, Ki/Ei/Kf/Ef) → Q/HKL → angles → the rest. Same rationale as the ordering in `load_parameters` (~:2677).
3. Fire each field's `after` handler once (deduplicated) — the `on_*` handlers read widget text, so setText-then-call is exactly the user's Enter-key path. Update the `_previous_values` tracking so later focus events do not refire.
4. Log to the message center and API dock (`API: set Ei=14.7, H=2.0`); publish a `parameters_changed` SSE event.
5. Return per-field results; any errors → HTTP 400 that honestly discloses the partial `applied` list.

## 9. SSE Design

`SseBroker` (in `tavi/api_server.py`):

- `subscribe()` → (client id, `queue.Queue(maxsize=1000)`); `publish(event, data)` puts pre-serialized `event: {name}\ndata: {json}\n\n` frames with `put_nowait`; on `queue.Full` the client is dropped (slow consumer) and a note goes to the message center via callback.
- The `GET /events` handler sends `Content-Type: text/event-stream`, `Cache-Control: no-cache`, then loops `q.get(timeout=15)`; timeout writes a `: keepalive\n\n` comment. `BrokenPipeError`/`ConnectionResetError`/`OSError` → `finally: unsubscribe`. Concurrent SSE clients capped (~8) → 503 beyond. Shutdown pushes a sentinel to every client queue so handler loops exit.
- Event types (all carry `job_id` where applicable): `job_queued`, `job_started`, `job_finished {state, error}`, `scan_initialized {mode, variables, values, masks}`, `point {index | ix, iy, value, counts}`, `point_invalid`, `progress {done, total, elapsed, remaining}`, `parameters_changed {fields, source}`, `message {text}`.
- Controller helper `_publish_api_event(event, data)` no-ops when the server is off; called from the worker thread beside the corresponding Qt signal emits. Pure Python — no Qt marshalling.

## 10. What the User Sees — API Dock

`gui/docks/api_dock.py`, `BaseDockWidget` subclass with stable `objectName("api_dock")`, registered in `gui/main_window.py` alongside the other docks:

- **Status line:** listening URL and state (listening / off / bind failed).
- **Mode combo:** Allow control / Read-only / Off. Live switch — Off calls `api_server.stop()`; the other two gate write endpoints in the request handler. Choice persists to `config/api_config.json`.
- **Job table:** id, source (gui/api), state, progress, per-row Cancel button routed through the same path as `POST /scan/{id}/stop`.
- **Budget readout:** pending-queue neutron usage vs budget, queue depth vs cap.
- **Activity log:** scrolling list fed by the `api_activity` signal (submissions, parameter writes, rejections, client drops).

The dock never reads worker state directly — all updates arrive via `job_state_changed` and `api_activity` signals, per the threading rules. API activity also mirrors to the existing message center.

## 11. Lifecycle and Configuration

- `load_api_config()` reads `config/api_config.json` tolerantly (absent file = defaults). CLI flags `--api-port N` (implies enabled) and `--no-api` in `main()` override the file.
- Controller `__init__`: if enabled, build `ApiBridge`, backend callbacks, `TaviApiServer(host, port, token, mode, limits, backend)`, then `start()`. Bind failure (`OSError`, port in use) → message-center warning, GUI continues without API. Success logs the listening URL. Non-loopback host → security warning recommending a token.
- `TAVIController.shutdown()`: set stop event, mark active/queued jobs stopped/cancelled, `api_server.stop()` (`httpd.shutdown()` plus broker sentinels), brief worker join. Called from the quit path and from the fixed `closeEvent` (which today references the nonexistent `stop_flag` and therefore does nothing).

## 12. Validation Reuse

`_preflight_scan_validation()` (:2869) splits into a pure `_validate_scan_commands_text(cmd1, cmd2) -> str` (parameterized on strings; its helpers are already pure) plus a thin GUI wrapper that reads the widgets. The GUI path is behaviorally unchanged (`QMessageBox` stays in `run_simulation_thread`). The API path calls the text version on the GUI thread via the bridge after applying any inline parameter patch; a non-empty result → 400 `scan_validation` unless the request set `"force": true`.

## 13. Implementation Phases

Each phase lands and is verifiable independently:

1. **Job queue + busy fix (no networking).** `tavi/scan_jobs.py`; controller worker thread, `submit_scan_job()`, `job_state_changed`; rewire `run_simulation_thread`; `run_simulation(job=)` result sink; Run-button disable while busy; `closeEvent` fix.
2. **Server core + read endpoints.** `tavi/api_server.py` (server, routing, auth, config); `ApiBridge`; lifecycle + CLI flags; `GET /health /state /parameters /scan/{id} /scan/{id}/data /jobs`.
3. **Write endpoints + limits.** Validation refactor; field map + `apply_parameters`; `PATCH /parameters`, `POST /scan` with budget enforcement (429), stop endpoints; read-only gating (403).
4. **SSE.** `SseBroker`, `GET /events`, `_publish_api_event` call sites.
5. **API dock + polish.** `gui/docks/api_dock.py`, main-window registration, mode persistence; unit tests under `tests/` for routing, broker, job snapshots, and budget math (fake backend, no Qt).

## 14. Verification

- `python -m py_compile` on all changed files; `python -c "import tavi.api_server, tavi.scan_jobs"` (must import without Qt).
- Launch the GUI (`run-tavi-dev.bat`) and exercise with `curl`:
  - `/health`, `/state`, `/parameters` while idle and mid-scan.
  - `PATCH /parameters` with `{"Ei": 14.0}` → Ei and linked Ki widgets visibly update; a bad field → 400 with per-field error.
  - `POST /scan` twice → second job queues; `/scan/{id}` shows progress; `/scan/{id}/data` mid-run (partial, `complete: false`) and after completion.
  - `curl -N .../events` during a scan → `scan_initialized`, `point`, `progress`, `job_finished`; killing curl mid-scan leaves the server healthy.
  - Over-limit submission (e.g. 500 points) → 429 with reason and usage.
  - Dock mode Read-only → writes get 403; Off → connection refused.
  - GUI double-click Run → second run queues instead of racing; Stop works; closing the window during a scan actually stops it.
- Use short, low-neutron scans for integration checks per CLAUDE.md.

## 15. Risks and Edge Cases

- **Modal dialogs block the GUI thread** → bridge timeout returns 503 `gui_busy` instead of deadlocking request threads (the reason `BlockingQueuedConnection` was rejected).
- **Long scans vs HTTP timeouts:** every endpoint returns immediately (job model); only SSE is long-lived, kept alive with 15 s keepalive comments.
- **NaN in counts** must be sanitized to `null`; `allow_nan=False` enforces this.
- **`config/parameters.json` races:** `save_parameters()` stays GUI-thread-only — both GUI and API submission paths reach it on the GUI thread — so no concurrent writes are introduced.
- **Stop leaking between queued jobs:** the worker clears the shared stop event after popping a job and before marking it running.
- **App exit with SSE clients or a running scan:** daemon threads, broker shutdown sentinels, and the `closeEvent` fix together guarantee clean exit.
- **Security:** loopback bind by default; optional bearer token; explicit warning for non-loopback binds; TLS out of scope for loopback use.
