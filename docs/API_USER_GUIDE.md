# TAVI Remote API — User Guide

*Last updated: 2026-07-03*

This guide is written for **both humans and LLM agents**. Every example is exact
and self-contained; you can paste any section into an LLM's context and it will
have what it needs to drive the instrument. There are no forward references to
source code.

---

## 1. What it is

TAVI's remote API lets an external program (a script, a notebook, `curl`, or an
LLM agent) drive a running TAVI GUI over a local HTTP port. You can read the full
instrument state, change any parameter, submit scan jobs, stream live per-point
results, and fetch complete scan arrays. Everything a remote client does is
mirrored into the GUI (widgets visibly update, the plot follows remote scans),
and the local user can restrict or disable remote control at any time from the
**Remote API** dock.

The transport is plain HTTP/REST with JSON bodies, plus Server-Sent Events (SSE)
for live streaming. No client library is required.

**Base URL:** `http://127.0.0.1:8642/api/v1`

All paths below are relative to that base URL. The server listens on loopback
(`127.0.0.1`) by default, so only programs on the same machine can reach it
unless the operator changes the bind host.

---

## 2. For LLM agents — paste-in operator block

The block below is a complete, self-contained operator brief. A human can paste
it (alone) into any LLM to get a working TAVI operator. It is deliberately
compact.

```
You control a TAVI triple-axis neutron spectrometer simulator through a local REST API.
BASE URL: http://127.0.0.1:8642/api/v1   (JSON in, JSON out; add header
  "Authorization: Bearer <token>" only if the operator gave you a token)

KEY ENDPOINTS (all paths relative to BASE URL):
  GET  /schema              -> live self-description: fields, allowed values, limits, grammar, examples
  GET  /state               -> {instrument, mode, busy, current_job, queue:[ids], parameters:{...40 fields...}, budget}
  PATCH /parameters  body {"Ei":14.7,"H":2.0}  -> {"applied":["Ei","H"],"errors":{}}
  POST /validate  body {same as /scan}  -> validation + {"would_queue":bool,"blockers":[...]}  (never queues, never mutates)
  POST /scan  body {"parameters":{...},"isolated":bool,"allow_partial":bool,"engine":"mcstas"|"deterministic","seed":int,"noiseless":bool} -> 202 {job_id, state, position, eta, validation}
              engine "deterministic" = fast analytic S(Q,w) x resolution + seeded Poisson (validator); check result.metadata.cn_valid
  GET  /scan/{id}?wait=N     -> block up to N s for terminal state; body carries "timed_out":bool
  GET  /scan/{id}/data       -> result + scan_values_1, counts (or counts_grid), skipped_points
  GET  /scan/{id}/plot.png   -> 512x512 PNG of current arrays (409 no_data if nothing renderable yet)
  GET  /journal?limit=N      -> human-readable session log (params, job lifecycle, mode/budget events)
  POST /scan/{id}/stop  |  POST /stop {"clear_queue":true}  -> drain-stop one job | stop running + clear queue

SCAN COMMANDS live in the parameters, NOT in the POST body directly. Set them via
  scan_command1 / scan_command2, e.g. PATCH /parameters {"scan_command1":"H 1.99 2.01 0.01"}.
  SYNTAX: "VARIABLE start stop STEP". The 3rd number (last token) is the STEP SIZE, not a point count.
  "H 1.99 2.01 0.01" = 3 points (1.99, 2.00, 2.01). A step larger than the range is an error.
  Two non-empty commands = a 2D scan (points multiply). One command = 1D. None = single point.
  Scannable variables: H K L, qx qy qz, deltaE, A1 A2 A3 A4, omega, 2theta, chi kappa psi, rhm rvm rha rva.

GOLDEN WORKFLOW:
  1. GET /schema  (learn fields, allowed values, and limits for THIS instrument — do this first)
  2. GET /state   (confirm mode=="allow" and busy==false; read current parameters)
  3. PATCH /parameters to set energies/Q/lattice/scan_command1[/2] and number_neutrons
  4. POST /validate with the same body you will POST /scan -> only submit if would_queue==true;
     if blockers list infeasible points, either fix them or POST /scan with "allow_partial":true
  5. POST /scan  -> capture job_id (add "isolated":true to run at one-off parameters WITHOUT
     disturbing the GUI or other queued work; the inline patch is baked into this job only)
  6. GET /scan/{id}?wait=30  -> long-poll instead of tight polling; repeat while "timed_out":true
     until state is terminal: done | failed | stopped | cancelled  (running/queued are NOT terminal)
  7. GET /scan/{id}/data -> read result.scan_values_1 + result.counts; result.skipped_points lists
     any points omitted by allow_partial (never a silent gap). GET .../plot.png for a visual check.

ETA: 202 and status carry eta {estimated_seconds, confidence:none|low|medium|high, samples}.
  confidence low/none => estimate is unreliable; run one cheap scan first to calibrate history.

BUDGET LIMITS (API jobs only): <=10 queued jobs, <=200 points/scan,
  <=1e8 neutrons/point, <=1e10 total pending neutrons. Over-limit POST /scan -> HTTP 429.

RULES:
  - Read /schema then /state before submitting; do not submit if mode!="allow".
  - Prefer wait= long-poll over repeat GETs; never spin in a tight loop.
  - A count of null means the point was not measured / was invalid — never treat null as 0.
  - On 409 / 429 / 503, OBEY the Retry-After header: wait that many seconds before retrying,
    report the .message to the user, and do not retry in a loop.
  - When retrying a POST /scan you are unsure completed, send the SAME "Idempotency-Key: <str>"
    header — a repeat returns the original job (HTTP 200) instead of creating a duplicate.
  - Lost track of state? GET /journal to recover what happened this session.
  - Errors come as {"error":{"code":...,"message":...,"details":...}}. Read .message.
```

---

## 3. Quick start (copy-paste)

These five commands take a fresh client from a liveness check to a finished
3-point scan. Real outputs are shown.

**1. Check the server is alive** (no auth required):

```bash
curl http://127.0.0.1:8642/api/v1/health
```
```json
{"status": "ok", "instrument": "puma", "mode": "allow"}
```

**2. Read the current state** (instrument, mode, busy flag, all parameters):

```bash
curl http://127.0.0.1:8642/api/v1/state
```
```json
{"instrument": "puma", "mode": "allow", "busy": false, "current_job": null,
 "queue": [], "parameters": {"Ei": 14.7, "Ki": 2.662, "H": 2.0, "K": 0.0,
 "L": 0.0, "scan_command1": "", "scan_command2": "", "number_neutrons": 1000000,
 "...": "35 more fields"}, "budget": {"pending_neutrons": 0.0, "budget": 1e10,
 "queued_jobs": 0, "max_queued": 10}}
```

**3. Set parameters** — pick an incident energy and a 3-point scan over H:

```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"Ei": 14.7, "scan_command1": "H 1.99 2.01 0.01", "number_neutrons": 100000}'
```
```json
{"applied": ["Ei", "scan_command1", "number_neutrons"], "errors": {}}
```

**4. Submit the scan** (returns immediately; the scan runs as a queued job):

```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{}'
```
```json
{"job_id": "j-0001", "state": "queued", "position": 0}
```

**5. Poll until done, then fetch the data:**

```bash
curl http://127.0.0.1:8642/api/v1/scan/j-0001
```
```json
{"job_id": "j-0001", "source": "api", "state": "done",
 "submitted_at": 1751500000.0, "started_at": 1751500001.0, "finished_at": 1751500040.0,
 "progress": {"done": 3, "total": 3}, "error": null,
 "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "H", "variable_2": null,
 "total_counts": 452.0, "max_counts": 310.0, "output_folder": "output/scan"}}
```
```bash
curl http://127.0.0.1:8642/api/v1/scan/j-0001/data
```
```json
{"job_id": "j-0001", "source": "api", "state": "done", "progress": {"done": 3, "total": 3},
 "error": null, "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "H", "variable_2": null,
 "total_counts": 452.0, "max_counts": 310.0, "output_folder": "output/scan",
 "scan_values_1": [1.99, 2.0, 2.01], "scan_values_2": null,
 "valid_mask_1": [true, true, true], "valid_mask_2d": null,
 "counts": [82.0, 310.0, 60.0], "counts_grid": null,
 "metadata": {"...": "frozen parameter snapshot"}}}
```

---

## 4. Typical workflow

1. **Read state.** `GET /state`. Confirm `mode` is `allow` (writes are allowed)
   and inspect `busy` / `queue` to see if a scan is already running.
2. **Set parameters.** `PATCH /parameters` with the fields you want to change.
   Linked fields recompute automatically (set `Ei` and `Ki` updates; set `H` and
   `qx`/`qy`/`qz` update via the UB matrix). The scan itself is defined by the
   `scan_command1` and (optionally) `scan_command2` parameters.
3. **Submit.** `POST /scan`. The server validates the scan commands, checks every
   point's geometric feasibility, and enforces budgets, then queues the job and
   returns a `job_id` plus a `validation` object. A bad scan command returns
   `400 scan_validation`; an unreachable point returns `400 infeasible_points`
   (or is skipped with `"allow_partial": true`). To preview all of this without
   queueing, use `POST /validate` first.
4. **Track progress.** Either **poll** `GET /scan/{id}` on an interval, or
   **stream** `GET /events` (SSE) for live `point` / `progress` events.
5. **Fetch data.** `GET /scan/{id}/data` returns the scan arrays. It works
   mid-run (partial arrays with `null` for not-yet-measured points) and after
   completion (full arrays). Distinguish the two by the job `state`.

---

## 5. Endpoint reference

Every route is under `/api/v1`. Error responses always use the envelope
`{"error": {"code": <string>, "message": <string>, "details": <optional>}}`.
If a token is configured, every endpoint **except** `/health` requires the header
`Authorization: Bearer <token>`.

### GET /health
Liveness probe. No auth required, even when a token is set.
```json
{"status": "ok", "instrument": "puma", "mode": "allow"}
```

### GET /state
Full snapshot: instrument id, access mode, busy flag, the currently running job
id (or `null`), the list of queued job ids, the complete parameter dict (all 40
fields — see §6), the configured limits (if any), and current budget usage.
```json
{"instrument": "puma", "mode": "allow", "busy": true, "current_job": "j-0003",
 "queue": ["j-0004", "j-0005"], "parameters": {"Ei": 14.7, "...": "..."},
 "limits": {"max_queued": 10, "max_points": 200, "max_neutrons_per_point": 1e8,
 "queue_neutron_budget": 1e10},
 "budget": {"pending_neutrons": 3.0e8, "budget": 1e10, "queued_jobs": 2, "max_queued": 10}}
```

### GET /parameters
Just the parameter dict (the same object that appears under `parameters` in
`/state`). See §6 for every field.

### PATCH /parameters
Partial parameter write. Body is a JSON object of `field: value` pairs. Returns
the list of applied fields and a per-field error map.
```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" -d '{"Ei": 14.7, "H": 2.0}'
```
```json
{"applied": ["Ei", "H"], "errors": {}}
```
- Unknown field or bad value → `400 invalid_parameters`, and the body discloses
  exactly which fields were applied and which failed:
```json
{"error": {"code": "invalid_parameters", "message": "One or more fields failed",
 "details": {"applied": [], "errors": {"bogus_field": "unknown field"}}}}
```
- While a scan is running or queued, a write is rejected with `409 busy` unless
  you pass `?force=1` (e.g. `PATCH /parameters?force=1`).
- In **read-only** mode, any write returns `403 read_only`.
- Each field is validated first and applied all-or-nothing: a field with a bad
  value is skipped entirely and reported in `errors`; valid fields still apply.

### POST /scan
Submit a scan job. The job runs the scan currently defined by the
`scan_command1` / `scan_command2` parameters. An optional inline `parameters`
object is applied **first** (same rules as `PATCH /parameters`), then the scan
commands are validated, budgets are checked, and the job is queued.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.99 2.01 0.01"}}'
```
```json
{"job_id": "j-0004", "state": "queued", "position": 0,
 "eta": {"estimated_seconds": 42.0, "confidence": "high", "samples": 11},
 "validation": {"points": 3, "per_command": [{"variable": "H", "count": 3,
   "values": [1.99, 2.0, 2.01]}], "cost": {"pending_neutrons": 0.0,
   "budget": 1e10, "queued_jobs": 0, "max_queued": 10, "points": 3,
   "neutrons_per_point": 100000.0, "job_neutrons": 300000.0},
   "eta": {"estimated_seconds": 42.0, "confidence": "high", "samples": 11},
   "infeasible": []}}
```
`position` is the number of jobs still ahead of this one in the queue at the
moment of the response — `0` means it is next to run (or already running).
`eta` is a best-effort time estimate for the whole scan (see §5 *ETA object*).

**Always-on validation (API submissions only).** Every `POST /scan` is fully
validated *before* it is queued, and the checks are echoed back in a
`validation` object (see §5 *Validation object*). This covers scan-command
parsing (explicit point values per command), budget/cost, per-point geometric
**feasibility** (does the scattering triangle close for every point?), and an
ETA. The GUI Run button is **never** subject to this — humans are always allowed
to submit.

- Invalid scan command → `400 scan_validation` with a human-readable message.
  Pass `"force": true` in the body to bypass scan-command validation.
- Any **geometrically infeasible** point → `400 infeasible_points`; the error
  `details` is the full `validation` object (so you can see which points and
  why). To queue anyway and simply **skip** the unreachable points, resubmit
  with `"allow_partial": true` in the body — the job runs the feasible points
  and records every omission under `result.skipped_points` (see §5 *GET
  /scan/{id}*). Skipped points are never silent gaps.
- Over a budget limit → `429 limit_exceeded` (see §9). The response carries a
  `Retry-After` header (see §5 *Retry-After*):
```json
{"error": {"code": "limit_exceeded",
 "message": "2e+08 neutrons/point exceeds the limit of 1e+08",
 "details": {"usage": {"pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0, "max_queued": 10}}}}
```
- In read-only mode → `403 read_only`.

**`allow_partial`** (optional boolean, default `false`). When `true`, a scan with
some infeasible points is still queued: only the feasible points run, and
`result.skipped_points` lists each omitted point as `{"index", "values",
"reason"}`. When `false` (the default), a single infeasible point rejects the
whole submission with `400 infeasible_points`.

**`isolated`** (optional boolean, default `false`). When `true`, the inline
`parameters` patch is applied only to the **frozen launch state** of *this* job:
the live GUI widgets are snapshotted before the patch, the job is queued with the
patched values baked in, and the widgets are then **restored** — so a running
operator's setup is left exactly as it was. Use this to run a one-off scan at
different parameters without disturbing the GUI or other queued work. The 202
payload and the job snapshot both carry `"isolated": true/false`.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"H": 3.0, "scan_command1": "K -0.1 0.1 0.02"}, "isolated": true}'
```
Regardless of `isolated`, a submission that is **rejected** (bad parameter,
invalid scan command, infeasible point, over budget) never leaves an inline
`parameters` patch applied — the pre-patch values are always restored on failure.
Only a *successful* `isolated:false` submit keeps its patch applied globally (the
default, backward-compatible behavior).

**`engine`** (optional string, default `"mcstas"`). Selects the execution
backend for this job. `GET /schema` advertises the allowed list under `engines`.

- **`"mcstas"`** — the full Monte-Carlo simulation. This is the default and the
  reference; nothing changes for existing clients.
- **`"deterministic"`** — a **fast analytic check**: the same ground-truth
  S(Q,ω) that parameterizes the McStas sample component, convolved with the
  theoretical Cooper–Nathans / Popovici resolution ellipsoid, plus seeded
  Poisson counting. Milliseconds per point instead of seconds-to-minutes. It
  runs through the identical job/queue/SSE pipeline: the same `scan_initialized`,
  `point`, `point_invalid`, and `progress` events, the same `result.counts` /
  `counts_grid` arrays, the same feasibility skipping. Use it to sanity-check
  that a scan makes sense (peaks where the dispersion predicts, resolution is
  reasonable) before committing McStas time.

An unknown engine → `400 bad_request` whose `details.allowed` is the valid list.

Two deterministic-only body fields:

- **`seed`** (optional integer). RNG seed for the Poisson noise. When omitted,
  the seed is a **stable hash of the job id**, so a given job reproduces
  bit-identically on re-run. Each point draws from `default_rng((seed, point_index))`
  so a skipped point never shifts a later point's noise. Echoed in provenance.
- **`noiseless`** (optional boolean, default `false`). When `true`, the engine
  returns the exact analytic **means** with no Poisson draw — useful for
  comparing shapes without counting statistics. Ignored by the McStas engine.

```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "deltaE 0.5 3.0 0.125"},
       "engine": "deterministic", "seed": 1, "noiseless": false}'
```

**Provenance.** The chosen engine is recorded on the job: the `launch` summary
(`GET /scan/{id}`, `/data`, and the saved JSON) carries `"engine"`, plus `"seed"`
and `"noiseless"` when the deterministic engine ran. A deterministic job's
`result.metadata` is additionally stamped with `engine`, `seed`, `method`,
`cn_valid`, and `invalidations` (see below).

**Honesty stamps.** Theoretical resolution is only valid when the analytic
assumptions hold. Configurations that break them (e.g. nested-mirror optics
replacing the collimator divergence model) do **not** silently fall back: the
engine still runs, but stamps `metadata.cn_valid = false` and lists each reason
in `metadata.invalidations`. Treat those results as a fidelity gap, not an error
— always check `cn_valid` before trusting deterministic intensities.

**Brightness caveat.** Absolute deterministic counts depend on a **calibrated**
brightness constant per sample model (anchored to a single McStas reference
point), *not* a first-principles normalization. Peak positions, relative
intensities across a scan, and widths are meaningful; the absolute count scale is
an approximation. For absolute counts, run McStas.

The deterministic engine requires a sample with a registered analytic ground
truth. An unknown sample fails the job cleanly with reason `no analytic ground
truth for sample 'X'` (a failed job with a message, never a crash).

### POST /validate
Dry-run the exact checks `POST /scan` performs — scan-command parsing, per-point
feasibility, budget, and ETA — **without queueing anything and without mutating
any parameter**. The body is identical to `POST /scan` (optional `parameters`,
`force`, `allow_partial`). Any inline `parameters` patch is applied to a private
copy of the GUI state and rolled back before returning, so (unlike `POST /scan`)
`/validate` never leaves parameter changes behind. Non-mutating, so it is
**allowed in read-only mode**.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.9 2.1 0.05"}}'
```
Returns the `validation` object (§5 *Validation object*) plus two extra fields:
- `would_queue` — `true` if `POST /scan` with the same body would be accepted.
- `blockers` — a list of human strings for each reason it would be rejected
  (empty when `would_queue` is `true`), e.g. `"infeasible_points: 2 point(s)
  unreachable"` or `"scan_validation: ..."` or `"limit_exceeded: ..."`.
```json
{"points": 5, "per_command": [{"variable": "H", "count": 5,
  "values": [1.9, 1.95, 2.0, 2.05, 2.1]}],
 "cost": {"pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0,
  "max_queued": 10, "points": 5, "neutrons_per_point": 100000.0,
  "job_neutrons": 500000.0},
 "eta": {"estimated_seconds": 70.0, "confidence": "high", "samples": 11},
 "infeasible": [], "would_queue": true, "blockers": []}
```

### GET /resolution
Theoretical triple-axis **resolution** (Cooper–Nathans / Popovici) at one
`(H, K, L, deltaE)` point, computed from the current instrument configuration.
Read-only, never mutates, so — like `/state`, `/schema` and `/validate` — it is
**allowed in read-only mode**. All query params are optional:

| Param | Meaning | Default |
|-------|---------|---------|
| `H`, `K`, `L` | Reciprocal-lattice point (r.l.u.) | current GUI values |
| `deltaE` | Energy transfer (meV) | current GUI value |
| `method` | `auto`, `cooper_nathans`, or `popovici` | `auto` |

`method=auto` picks **Popovici** when the instrument config carries spatial
information (mono/analyzer curvatures — `rhm`/`rvm`/`rha` — make the config
"spatial"), otherwise **Cooper–Nathans**. When Popovici runs with defaulted
spatial dimensions, that is intended: the `warnings` and `config.provenance`
carry the honesty (which dimensions were defaulted). A non-numeric `H`/`K`/`L`/
`deltaE` → `400 bad_request`; an unrecognized `method` → `400 bad_request`.

```bash
curl "http://127.0.0.1:8642/api/v1/resolution?H=2&K=0&L=0&deltaE=1.5&method=cooper_nathans"
```

Successful response (serialized resolution result):
```json
{"ok": true, "reason": null, "method": "cooper_nathans", "cn_valid": true,
 "warnings": [], "invalidations": [], "r0": null,
 "matrix": [[...4x4 FWHM-normalized precision matrix...]],
 "fwhm": {"dq_par": 0.031, "dq_perp": 0.022, "dq_z": 0.05, "dE": 0.91},
 "bragg": {"dq_par": 0.012, "dq_perp": 0.010, "dq_z": 0.02, "dE": 0.40},
 "principal_axes": {"eigenvalues": [...], "fwhm": [...], "eigenvectors": [...]},
 "vanadium_fwhm_meV": 0.91,
 "projections": {"q_par_q_perp": {...}, "q_par_E": {...}, "q_perp_E": {...}},
 "basis": ["dQ_par", "dQ_perp", "dQ_z", "dE"],
 "config": {"...echoed config incl. provenance...",
   "provenance": {"senses": {"sm": 1, "ss": -1, "sa": 1}, "...": "..."}},
 "provenance": {"matrix_convention": "FWHM-normalized precision; R~exp(-1/2 x^T M x)"}}
```

- `cn_valid` is `false` (with a populated `invalidations` list) when a component
  breaks the analytic model — e.g. PUMA's nested mirror optics (NMO). The result
  is still returned; `invalidations` names why the numbers are not trustworthy.
- `warnings` lists softer caveats (open collimation substituted, velocity selector
  installed, monochromatic source, Popovici dimensions defaulted, …).
- **Refusal convention:** an infeasible geometry (scattering triangle cannot
  close, analyzer angle out of range, …) or an instrument without resolution
  support returns **HTTP 200** with `{"ok": false, "reason": "..."}` — the same
  refusal-string vocabulary as `/validate`, *not* an error envelope. Always check
  `ok` before reading `matrix`/`fwhm` (which are `null` on a refusal).

### GET /schema
Machine-readable self-description of the API, generated at request time from live
instrument data (no hand-maintained duplicate). Read-only, no side effects,
**allowed in read-only mode**.
```json
{"instrument": "puma",
 "fields": [{"name": "Ei", "type": "number", "units": "meV"},
   {"name": "K_fixed", "type": "string", "allowed": ["Ki Fixed", "Kf Fixed"]},
   {"name": "monocris", "type": "string", "allowed": ["pg002", "pg002_test"]},
   {"...": "one entry per writable parameter"}],
 "scan_variables": ["H", "K", "L", "qx", "qy", "qz", "deltaE", "A1", "A2",
   "A3", "A4", "omega", "2theta", "chi", "kappa", "psi", "rhm", "rvm", "rha", "rva"],
 "engines": ["mcstas", "deterministic"],
 "scan_body_fields": [
   {"name": "engine", "type": "string", "allowed": ["mcstas", "deterministic"],
    "default": "mcstas"},
   {"name": "seed", "type": "integer", "default": null},
   {"name": "noiseless", "type": "boolean", "default": false}],
 "scan_command_grammar": "VARIABLE start stop STEP. The third number (the last
   token) is the STEP SIZE, not the number of points. ...",
 "limits": {"max_queued": 10, "max_points": 200, "max_neutrons_per_point": 1e8,
   "queue_neutron_budget": 1e10},
 "endpoints": [{"method": "GET", "path": "/schema", "description": "..."}],
 "examples": ["align-on-bragg-peak", "elastic-h-scan", "constant-q-energy-scan",
   "quick-look-vs-production"]}
```
Each field carries `name`, `type`, `units` (where known), and `allowed` (the
permitted values for choice fields — crystal ids, `K_fixed` modes, source types).
`engines` is the list of execution backends selectable via the `POST /scan`
`engine` body field; `scan_body_fields` documents the optional top-level scan
body fields (`engine`, `seed`, `noiseless`) beyond `parameters`.
`examples` names the worked examples elsewhere in this guide.

**Idempotency-Key** (optional request header). Send an `Idempotency-Key: <string>`
header to make retries safe. The first request with a given key queues a job as
usual (`202`); any later request with the **same** key returns that job's current
status with **HTTP 200** (not `202`) and does **not** create a duplicate job. Keys
are remembered for the 256 most recently used values. No header → every request
creates a new job.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -H "Idempotency-Key: run-2026-07-03-a" -d '{}'
```

### GET /scan/{id}
Job status. Returns the job snapshot: state, source (`gui`/`api`), timestamps,
`progress: {done, total}`, error (or `null`), a small `launch` summary, a
`result` summary (count totals and output folder — no arrays here), and an `eta`
object (see *ETA object* below).
```json
{"job_id": "j-0003", "source": "api", "state": "running",
 "submitted_at": 1751500000.0, "started_at": 1751500001.0, "finished_at": null,
 "progress": {"done": 1, "total": 3}, "error": null,
 "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "H", "variable_2": null,
 "total_counts": 82.0, "max_counts": 82.0, "output_folder": "output/scan"},
 "eta": {"estimated_seconds": 8.0, "confidence": "medium", "samples": 4}}
```
`result` is `null` for a job that has not yet started building its scan geometry
(e.g. still `queued`). Unknown id → `404 unknown_job`. Once the job has geometry,
`result.skipped_points` lists any points omitted because they were infeasible and
the job was submitted with `allow_partial` (empty `[]` for a normal job) — each
entry is `{"index", "values", "reason"}`.

**Validation object.** The `validation` block embedded in a `POST /scan` 202
response (and returned by `POST /validate`) has:
`{"points": <int total>, "per_command": [{"variable", "count", "values":[...]},
...], "cost": {budget usage + "points"/"neutrons_per_point"/"job_neutrons"},
"eta": {ETA object}, "infeasible": [{"index", "values", "reason"}, ...]}`.
`infeasible` is empty when every point's scattering triangle closes; each entry
names a point that is geometrically unreachable and why (e.g. `"scattering
triangle does not close"`, `"analyzer angle out of range"`). `POST /validate`
adds `would_queue` (bool) and `blockers` (list of strings).

**Long-poll — `?wait=N`.** Add `?wait=N` (seconds, float allowed, clamped to 120)
to block until the job reaches a terminal state (`done`/`failed`/`stopped`/
`cancelled`) or the wait expires, instead of returning immediately. The response
body is the same snapshot plus a `"timed_out"` boolean — `true` only when the
wait expired while the job was still running/queued. If the job is already
terminal it returns at once. Omitting `wait` gives the plain immediate response
(no `timed_out` field).
```bash
# Block up to 30 s for the job to finish, then return its final status.
curl "http://127.0.0.1:8642/api/v1/scan/j-0003?wait=30"
```
Concurrent waiters are capped (16); beyond that the endpoint returns
`429 too_many_waiters` with a `Retry-After` header.

**ETA object.** `eta` is a best-effort estimate derived from recorded run
history for the active instrument: `{"estimated_seconds": <float|null>,
"confidence": "none"|"low"|"medium"|"high", "samples": <int>}`. `estimated_seconds`
is `null` when there is no usable history. Per-point time is scaled to the job's
neutron count; a queued job's estimate covers compile + all points, a running
job's covers the remaining points. `confidence` reflects the sample count
(`none`=0, `low`=1–2, `medium`=3–9, `high`=10+).

**Retry-After.** `409`, `429`, and `503` responses include a `Retry-After: <int
seconds>` header hinting when to retry: `503 gui_busy` → `2`; `429` → an estimate
of queue drain time when available, else `30`; `409` → `5`.

### GET /scan/{id}/data
Same snapshot as `GET /scan/{id}`, but the `result` object additionally carries
the full arrays. There is **no** top-level `complete` flag — infer completeness
from the job `state` (`running` = partial, a terminal state = final).
```json
{"job_id": "j-0003", "source": "api", "state": "running", "progress": {"done": 1, "total": 3},
 "error": null, "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "H", "variable_2": null,
 "total_counts": 82.0, "max_counts": 82.0, "output_folder": "output/scan",
 "scan_values_1": [1.99, 2.0, 2.01], "scan_values_2": null,
 "valid_mask_1": [true, true, true], "valid_mask_2d": null,
 "counts": [82.0, null, null], "counts_grid": null,
 "metadata": {"...": "frozen parameter snapshot"}}}
```
For a **2D** scan, `counts` is `null` and `counts_grid` is a list of rows
(`counts_grid[row][col]`), with `variable_2`, `scan_values_2`, and `valid_mask_2d`
populated. Not-yet-measured or invalid points are `null`, never `NaN`. Unknown
id → `404 unknown_job`.

**Resolution parameters in `launch.parameters` / `result.metadata`.** Every job's
frozen parameter snapshot (exposed as `launch.parameters` on `GET /scan/{id}` and
as `result.metadata` here) carries a flat set of resolution/geometry fields for
downstream analysis (e.g. reconstructing the theoretical resolution offline):

| Key | Meaning |
|-----|---------|
| `eta_m`, `eta_a`, `eta_s` | Mono / analyzer / sample horizontal mosaic (arcmin, FWHM). `eta_s` reuses `eta_m` when the sample carries no mosaic. |
| `sense_m`, `sense_s`, `sense_a` | Scattering senses at mono / sample / analyzer (`+1` / `-1`). |
| `beta_1`…`beta_4` | Vertical divergences (arcmin, FWHM). |
| `sample_key` | Selected sample id (or `null`). |
| `temperature` | Sample temperature (`SampleSpec.properties['T']`) if defined, else `null`. |

These are populated from the same instrument descriptor + sample library the
theoretical-resolution adapter reads; they are absent only for an instrument that
does not implement resolution support.

### GET /scan/{id}/plot.png
A rendered PNG image (512×512 px) of the job's current result arrays. **1D**
scans render as an errorbar plot (√counts uncertainty, markers + line); **2D**
scans render as a heatmap with a colorbar. Not-yet-measured, invalid, or skipped
points are simply absent. The response `Content-Type` is `image/png`. Rendered
server-side (matplotlib Agg, no browser needed), so it works from `curl`, a
notebook `<img>`, or an LLM tool.
```bash
curl -s http://127.0.0.1:8642/api/v1/scan/j-0003/plot.png -o scan.png
```
Available while the job is still running (a partial plot) and after it finishes.
**Allowed in read-only mode.** Unknown id → `404 unknown_job`; a job with no
renderable data yet (e.g. still `queued`, or every point missing) → `409 no_data`.

### POST /scan/{id}/stop
Cancel or stop one job. A `queued` job becomes `cancelled` immediately; a
`running` job is stopped with **drain semantics** — the in-flight point finishes,
then the job becomes `stopped` and its partial data stays retrievable via
`/scan/{id}/data`. Returns the job snapshot.
- Stopping an already-finished job → `409 job_finished`.
- Read-only mode → `403 read_only`. Unknown id → `404 unknown_job`.

### POST /stop
Stop the currently running job. Body `{"clear_queue": true}` also cancels every
queued job.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/stop \
  -H "Content-Type: application/json" -d '{"clear_queue": true}'
```
```json
{"stopped": "j-0003", "cancelled": ["j-0004", "j-0005"]}
```
`stopped` is `null` if nothing was running. Read-only mode → `403 read_only`.

### GET /jobs
Recent job snapshots (newest first), each in the same summary shape as
`GET /scan/{id}` (no arrays).
```json
[{"job_id": "j-0003", "source": "api", "state": "done", "progress": {"done": 3, "total": 3},
  "error": null, "launch": {"...": "..."}, "result": {"...": "..."}}]
```

### GET /journal
A human/LLM-readable session narrative: a rolling log of what has happened this
session — parameter changes, job lifecycle (queued/started/finished with a
one-line result summary, or stopped/failed with a reason), access-mode changes,
and budget rejections. Backed by a ring buffer of the 1000 most recent entries.
Read-only, no side effects, **allowed in read-only mode**.
```bash
curl "http://127.0.0.1:8642/api/v1/journal?limit=20"
```
```json
{"entries": [
   {"ts": "2026-07-03T14:05:01", "kind": "parameter", "text": "api: set H, scan_command1"},
   {"ts": "2026-07-03T14:05:01", "kind": "job", "text": "j-0004: queued (source: api)"},
   {"ts": "2026-07-03T14:05:02", "kind": "job", "text": "j-0004: started"},
   {"ts": "2026-07-03T14:05:44", "kind": "job",
    "text": "j-0004: H scan 1.990 to 2.010, 5 pts, max 31 counts at H=2.000"}],
 "total_recorded": 4}
```
`?limit=N` (default `100`, capped at `1000`) returns the newest `N` entries with
the **newest last**. `total_recorded` counts every entry ever recorded this
session (including any already evicted from the ring buffer), so a poller can
detect gaps. `kind` is one of `parameter`, `job`, `mode`, `budget`. A
non-integer `limit` → `400 bad_request`.

### GET /events
Server-Sent Events stream. See §8.

### Error code reference

| HTTP | code | When |
|---|---|---|
| 400 | `bad_request` | Malformed JSON body, non-object body, or a PATCH field whose value is not a scalar/object. |
| 400 | `invalid_parameters` | A `PATCH /parameters` (or inline `parameters` on `POST /scan`) had an unknown field or a bad value. `details` lists `applied` and `errors`. |
| 400 | `scan_validation` | `POST /scan` scan command(s) failed validation (unknown variable, conflict, step larger than range). Bypass with `"force": true`. |
| 400 | `infeasible_points` | `POST /scan` had one or more geometrically infeasible points (scattering triangle does not close, angle out of range). `details` is the full `validation` object. Queue anyway (skipping them) with `"allow_partial": true`. |
| 401 | `unauthorized` | A token is configured and the `Authorization: Bearer <token>` header is missing or wrong. |
| 403 | `read_only` | A write endpoint was called while the server is in read-only mode. |
| 404 | `not_found` | Unknown URL path. |
| 404 | `unknown_job` | `/scan/{id}...` referenced a job id that does not exist. |
| 405 | `method_not_allowed` | Wrong HTTP method for a known path. |
| 409 | `busy` | `PATCH /parameters` while a scan is running/queued without `?force=1`. |
| 409 | `job_finished` | Tried to stop a job already in a terminal state. |
| 409 | `no_data` | `GET /scan/{id}/plot.png` for a job with no renderable data yet (still queued, or every point missing). |
| 429 | `limit_exceeded` | `POST /scan` exceeded a budget limit. `details.usage` shows current usage. Carries `Retry-After`. |
| 429 | `too_many_waiters` | `GET /scan/{id}?wait=N` was refused because the long-poll waiter cap (16) is reached. Carries `Retry-After`. |
| 500 | `internal_error` | Unexpected server-side error. |
| 501 | `not_implemented` | Endpoint's backend handler is unavailable (should not occur in the shipped build). |
| 503 | `gui_busy` | The GUI thread did not respond within ~5 s (e.g. a modal dialog is open). Back off and retry. |
| 503 | `too_many_clients` | `GET /events` was refused because the SSE client cap (8) is reached. |

---

## 6. Parameter field reference

All 40 fields returned by `GET /parameters` and writable via `PATCH /parameters`.
Many are **linked**: writing one triggers the same recompute the GUI does when a
user presses Enter, so dependent fields update automatically.

| Field | Type | Units | Meaning / linked recompute |
|---|---|---|---|
| `mtt` | number | degrees | Monochromator take-off angle (A2). Recomputes energies/Q. |
| `stt` | number | degrees | Sample scattering angle (A4). |
| `omega` | number | degrees | Sample rotation (A3; same physical angle as sample θ). |
| `chi` | number | degrees | Sample tilt. |
| `att` | number | degrees | Analyzer take-off angle. |
| `Ki` | number | Å⁻¹ | Incident wavevector. Linked: `Ki` ↔ `Ei`. |
| `Ei` | number | meV | Incident energy. Linked: `Ei` ↔ `Ki`. |
| `Kf` | number | Å⁻¹ | Final wavevector. Linked: `Kf` ↔ `Ef`. |
| `Ef` | number | meV | Final energy. Linked: `Ef` ↔ `Kf`. |
| `K_fixed` | string | — | Energy mode. Exactly `"Ki Fixed"` or `"Kf Fixed"`. |
| `fixed_E` | number | meV | The fixed energy value used by the current `K_fixed` mode. |
| `qx` | number | Å⁻¹ | Q component (instrument frame). Linked: `H`/`K`/`L` → `qx`/`qy`/`qz` via UB. |
| `qy` | number | Å⁻¹ | Q component (instrument frame). |
| `qz` | number | Å⁻¹ | Q component (instrument frame). |
| `H` | number | r.l.u. | Miller index H. Linked: `H`/`K`/`L` → `qx`/`qy`/`qz` via UB matrix. |
| `K` | number | r.l.u. | Miller index K. |
| `L` | number | r.l.u. | Miller index L. |
| `deltaE` | number | meV | Energy transfer. Recomputes angles/energies. |
| `lattice_a` | number | Å | Lattice constant a. Recomputes UB → Q/HKL. |
| `lattice_b` | number | Å | Lattice constant b. |
| `lattice_c` | number | Å | Lattice constant c. |
| `lattice_alpha` | number | degrees | Lattice angle α. |
| `lattice_beta` | number | degrees | Lattice angle β. |
| `lattice_gamma` | number | degrees | Lattice angle γ. |
| `kappa` | number | degrees | Sample alignment offset κ. |
| `psi` | number | degrees | Sample alignment offset ψ. |
| `monocris` | string | — | Monochromator crystal id. PUMA: `"pg002"` or `"pg002_test"`. |
| `anacris` | string | — | Analyzer crystal id. PUMA: `"pg002"`. |
| `rhm` | number | — | Monochromator horizontal bending radius (signed). |
| `rvm` | number | — | Monochromator vertical bending radius (signed). |
| `rha` | number | — | Analyzer horizontal bending radius (signed). |
| `source_type` | string | — | Source model id. PUMA: `"Maxwellian"` or `"Mono"`. |
| `source_dE` | number | meV | Source energy spread (only meaningful for the `"Mono"` source). |
| `modules` | object | — | Experimental modules. See below. |
| `collimation` | object | — | Collimator selections. See below. |
| `slits_mm` | object | — | Slit openings in mm. See below. |
| `number_neutrons` | integer | count | Neutrons simulated per point. Positive integer; also accepts a numeric string like `"1e8"`. |
| `scan_command1` | string | — | First scan command (§7). Empty string = no scan on this axis. |
| `scan_command2` | string | — | Second scan command (§7). Both set = 2D scan. |
| `diagnostic_mode` | boolean | — | Enable per-point diagnostic capture. |

**Dict-valued fields** — when writing these, send an object keyed by slot id.
Missing keys fall back to instrument defaults.

- `modules` — `{module_id: value}`. On PUMA: `nmo` takes a string from
  `"None" | "Vertical" | "Horizontal" | "Both"`; `v_selector` takes a boolean.
  Example: `{"modules": {"nmo": "None", "v_selector": false}}`.
- `collimation` — `{slot_id: selection}`. On PUMA the slots are `alpha_1`,
  `alpha_2`, `alpha_3`, `alpha_4`. Single-select slots take a string (e.g.
  `"40"`); the multi-select slot (`alpha_2`) takes a list of strings (e.g.
  `["30", "40"]`). Example: `{"collimation": {"alpha_1": "40", "alpha_2": ["40"], "alpha_3": "30", "alpha_4": "30"}}`.
- `slits_mm` — `{slit_id: width}` or `{slit_id: [width, height]}` in mm. On PUMA
  the slots are `vbl_hgap` (width only), `pbl` (`[width, height]`), and
  `dbl_hgap` (width only). Example: `{"slits_mm": {"vbl_hgap": 88, "pbl": [100, 100], "dbl_hgap": 50}}`.
  Note: multi-select collimation values are returned by `GET /parameters` as a
  sorted JSON list.

---

## 7. Scan commands

A scan is defined entirely by the `scan_command1` and `scan_command2` parameters.
Set them with `PATCH /parameters` (or the inline `parameters` block on
`POST /scan`), then submit the scan.

**Syntax:** `VARIABLE start stop STEP`

> **The third number (the last token) is the STEP SIZE, not the number of points.** This is the
> most common mistake. `"H 1.99 2.01 0.01"` produces **3** points: 1.99, 2.00,
> 2.01. To get N points, use a step of `(stop − start) / (N − 1)`.

- A **step larger than the range** (e.g. `"H 1.99 2.01 0.1"`) is a validation
  error (`400 scan_validation`).
- **1D scan:** set `scan_command1`, leave `scan_command2` empty (`""`).
- **2D scan:** set **both** commands. The point count is the product of the two
  (a 3-point × 4-point scan runs 12 points). The 2D result uses `counts_grid`.
- **Single point:** leave both commands empty. The scan runs one point at the
  current parameter values.

**Scannable variable names** (case-insensitive; canonicalized on submit):

| Variable(s) | Scans over |
|---|---|
| `H` `K` `L` | Miller indices (reciprocal-lattice units) |
| `qx` `qy` `qz` | Q components (instrument frame) |
| `deltaE` | energy transfer (meV) |
| `A1` `A2` `A3` `A4` | raw instrument angles |
| `omega` | sample rotation (alias of A3) |
| `2theta` | sample two-theta (alias of A2's index) |
| `chi` `kappa` `psi` | sample tilt / alignment offsets |
| `rhm` `rvm` `rha` `rva` | crystal bending radii |

Examples:
```json
{"scan_command1": "H 1.9 2.1 0.01"}                       // 21-point 1D scan over H
{"scan_command1": "deltaE 0 10 0.5"}                       // energy scan, 0..10 meV
{"scan_command1": "H 1.9 2.1 0.02", "scan_command2": "deltaE 0 8 1"}  // 2D H–E map
{"scan_command1": "", "scan_command2": ""}                 // single point at current settings
```

---

## 8. Live streaming (SSE)

`GET /events` opens a long-lived `text/event-stream`. Each event is
`event: <name>` followed by `data: <json>`. Keepalive comments (`: keepalive`)
arrive about every 15 seconds. At most **8** SSE clients may connect at once;
beyond that `GET /events` returns `503 too_many_clients`.

```bash
curl -N http://127.0.0.1:8642/api/v1/events
```

A typical 3-point 1D scan produces this sequence (auth header omitted; add
`-H "Authorization: Bearer <token>"` if a token is set):

```
: connected

event: job_queued
data: {"job_id": "j-0001", "source": "api", "position": 0}

event: job_started
data: {"job_id": "j-0001", "source": "api"}

event: scan_initialized
data: {"job_id": "j-0001", "mode": "1D", "variable_1": "H", "variable_2": null,
       "scan_values_1": [1.99, 2.0, 2.01], "scan_values_2": null,
       "valid_mask_1": [true, true, true], "valid_mask_2d": null}

event: point
data: {"job_id": "j-0001", "index": 0, "value": 1.99, "counts": 82.0}

event: progress
data: {"job_id": "j-0001", "done": 1, "total": 3, "elapsed": 12.4}

event: point
data: {"job_id": "j-0001", "index": 1, "value": 2.0, "counts": 310.0}

event: progress
data: {"job_id": "j-0001", "done": 2, "total": 3, "elapsed": 24.9}

event: point
data: {"job_id": "j-0001", "index": 2, "value": 2.01, "counts": 60.0}

event: progress
data: {"job_id": "j-0001", "done": 3, "total": 3, "elapsed": 37.1}

event: job_finished
data: {"job_id": "j-0001", "state": "done", "error": null}
```

**Event payload reference:**

| Event | Payload fields |
|---|---|
| `job_queued` | `job_id`, `source`, `position` (jobs ahead in queue). Always emitted before `job_started`. |
| `job_started` | `job_id`, `source`. |
| `scan_initialized` | `job_id`, `mode` (`1D`/`2D`/`single`), `variable_1`, `variable_2`, `scan_values_1`, `scan_values_2`, `valid_mask_1`, `valid_mask_2d`. |
| `point` | 1D/single: `job_id`, `index`, `value`, `counts`. 2D: `job_id`, `ix`, `iy`, `value_1`, `value_2`, `counts`. |
| `point_invalid` | Same shape as `point` but with no `counts` (the point was geometrically unreachable). |
| `progress` | `job_id`, `done`, `total`, `elapsed` (seconds). |
| `parameters_changed` | `fields` (list of applied field names), `source` (`api`). Emitted on every successful write. |
| `job_finished` | `job_id`, `state` (terminal), `error` (or `null`). |

Any float that would be `NaN` is serialized as `null` in every event.

**Reconnecting:** If the server's access mode is switched to **Off**, all SSE
streams are closed. After the operator switches back to **Allow control** (or
**Read-only**), reconnect with a fresh `GET /events`. Also reconnect if your
client is dropped for being a slow consumer (the server drops clients whose
buffer fills). There is no event replay — on reconnect, call `GET /scan/{id}/data`
to catch up on any points you missed.

---

## 9. Job lifecycle

Every scan — whether submitted through the API or the GUI Run button — runs as a
job through a single serial worker. Jobs execute one at a time.

```
                submit
                  |
                  v
   +---------> queued ------------------+
   |             |                       | POST /scan/{id}/stop
   |             | worker picks it up    | (or POST /stop clear_queue)
   |             v                       v
   |          running -----------> stopped   (drain: current point finishes)
   |          /  |  \
   |  success/   |   \ error
   |        /    |    \
   |       v     |     v
   |     done    |   failed
   |             |
   |    POST /scan/{id}/stop or /stop
   |             |
   +-------------+
```

- **queued** — waiting for the worker. Not yet running.
- **running** — actively simulating points.
- **done** — completed normally.
- **failed** — raised an error; see the `error` field.
- **stopped** — a running job was stopped; partial data is retained.
- **cancelled** — a queued job was cancelled before it started running.

`done`, `failed`, `stopped`, and `cancelled` are **terminal** — poll until the
state is one of these. Stopping uses **drain semantics**: the in-flight point
completes, then the job stops, so results already collected remain available via
`GET /scan/{id}/data`.

Stop endpoints:
- `POST /scan/{id}/stop` — stop or cancel one specific job.
- `POST /stop` — stop the running job; add `{"clear_queue": true}` to also cancel
  everything still queued.

---

## 10. Limits and budgets

To protect the instrument from abusive submissions, API-sourced scans are subject
to budget limits. **GUI-initiated runs are exempt** (the local user is trusted),
though they still queue serially.

| Limit | Default | Meaning |
|---|---|---|
| `max_queued` | 10 | Maximum number of jobs allowed in the queue at once. |
| `max_points` | 200 | Maximum points in a single scan. |
| `max_neutrons_per_point` | 1e8 | Maximum neutrons per point. |
| `queue_neutron_budget` | 1e10 | Maximum total pending neutrons: Σ(points × neutrons) over all pending API jobs. |

An over-limit `POST /scan` is rejected with `429 limit_exceeded`; the message
states the reason and `details.usage` reports current usage:
```json
{"error": {"code": "limit_exceeded",
 "message": "2e+08 neutrons/point exceeds the limit of 1e+08",
 "details": {"usage": {"pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0, "max_queued": 10}}}}
```

**Changing the limits (operator).** Edit `config/api_config.json` and restart
TAVI. Example:
```json
{"enabled": true, "mode": "allow", "host": "127.0.0.1", "port": 8642, "token": null,
 "limits": {"max_queued": 10, "max_points": 200,
            "max_neutrons_per_point": 1e8, "queue_neutron_budget": 1e10}}
```
If the file is absent, all defaults apply (enabled, `allow` mode, `127.0.0.1:8642`,
no token).

---

## 11. Access modes and security

The operator controls remote access from the **Remote API** dock (a mode combo).

| Mode | Behavior |
|---|---|
| **Allow control** (`allow`) | Full API: reads, writes, scan submission, streaming. |
| **Read-only** (`readonly`) | `GET` and SSE only. Every write (`PATCH`, `POST`) returns `403 read_only`. |
| **Off** | The server stops listening entirely; connections are refused and all SSE streams close. |

The mode can be switched live from the dock and is persisted to
`config/api_config.json`. The dock also shows the listening URL, the job queue
table (with per-row Cancel), the budget readout, and an activity log of API
actions.

**Authentication.** If a `token` is set in `config/api_config.json`, every
endpoint except `/health` requires the header `Authorization: Bearer <token>`:
```bash
curl -H "Authorization: Bearer my-secret-token" \
  http://127.0.0.1:8642/api/v1/state
```
A missing or wrong token returns `401 unauthorized`. With no token configured
(the default), no header is needed.

**Network exposure.** The server binds `127.0.0.1` (loopback) by default, so only
the local machine can reach it. There is no TLS. If the operator changes `host`
to a non-loopback address to allow remote machines, they should also set a token;
TAVI prints a security warning for non-loopback binds.

**CLI flags** (operator, at launch):
- `--api-port N` — enable the API on port N (overrides the config port).
- `--no-api` — disable the API server regardless of config.

---

## 12. Gotchas

These are real, verified behaviors worth knowing:

1. **A failed `POST /scan` still applies its inline `parameters` patch.**
   Submission is patch-first: the inline `parameters` block is applied to the GUI
   before scan-command validation and budget checks run. So if the submission is
   then rejected (`400 scan_validation` or `429 limit_exceeded`), the parameter
   changes have **already taken effect**. Re-read `GET /state` after a rejected
   submission rather than assuming nothing changed.

2. **Switching the access mode to Off closes all SSE streams.** Any client
   streaming `GET /events` is disconnected when the operator selects Off. After
   Off → Allow control (or Read-only), clients must reconnect with a fresh
   `GET /events`; there is no automatic resume.

3. **`position` counts jobs ahead in the queue, not a job index.** In the
   `POST /scan` response and the `job_queued` event, `position` is how many jobs
   are ahead of this one. `0` means it is next to run — even if a different job is
   currently executing.

4. **Mid-scan stop is drain, not abort.** `POST /scan/{id}/stop` (or `POST /stop`)
   on a running job lets the in-flight point finish before the job becomes
   `stopped`. The partial data collected so far stays retrievable via
   `GET /scan/{id}/data`. Do not expect an instantaneous halt.

Additional notes:
- **`null` counts mean unmeasured or invalid — never `0`.** Any not-yet-run point
  and any geometrically invalid point serializes as `null`. Treat `null` as "no
  measurement", not zero counts.
- **`503 gui_busy`** means the GUI thread was tied up (often a modal dialog open
  on the operator's screen). Back off a moment and retry.

---

## 13. Worked examples

Four end-to-end recipes. Each shows the requests in order, abbreviated but
realistic responses, and the gotchas that bite first. These are the same names
`GET /schema` advertises in its `examples` array
(`align-on-bragg-peak`, `elastic-h-scan`, `constant-q-energy-scan`,
`quick-look-vs-production`). All use PUMA at `Ei = 14.7 meV` with `pg002`
crystals; a (2 0 0)-type Bragg peak stands in for a "known" reflection.

### 13.1 align-on-bragg-peak

**Goal.** Confirm the sample is aligned by scanning tightly across a known
elastic Bragg peak near **H = 2** and inspecting where the intensity peaks. Run
it *without* disturbing the operator's live setup, so use `isolated: true`.

Set the elastic condition and center, then dry-run the tight scan:
```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"Ei": 14.7, "deltaE": 0, "H": 2.0, "K": 0.0, "L": 0.0}'
# -> {"applied": ["Ei", "deltaE", "H", "K", "L"], "errors": {}}

curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.98 2.02 0.005", "number_neutrons": 200000}}'
```
```json
{"points": 9, "per_command": [{"variable": "H", "count": 9,
  "values": [1.98, 1.985, 1.99, 1.995, 2.0, 2.005, 2.01, 2.015, 2.02]}],
 "cost": {"points": 9, "neutrons_per_point": 200000.0, "job_neutrons": 1800000.0,
  "pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0, "max_queued": 10},
 "eta": {"estimated_seconds": 96.0, "confidence": "high", "samples": 12},
 "infeasible": [], "would_queue": true, "blockers": []}
```
`would_queue` is `true`, so submit the identical body as an **isolated** job and
long-poll for the result:
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.98 2.02 0.005", "number_neutrons": 200000}, "isolated": true}'
# -> 202 {"job_id": "j-0007", "state": "queued", "position": 0, "isolated": true,
#         "eta": {"estimated_seconds": 96.0, "confidence": "high", "samples": 12},
#         "validation": {"points": 9, "infeasible": [], ...}}

curl "http://127.0.0.1:8642/api/v1/scan/j-0007?wait=120"
```
```json
{"job_id": "j-0007", "state": "done", "isolated": true,
 "progress": {"done": 9, "total": 9}, "timed_out": false,
 "result": {"mode": "1D", "variable_1": "H", "total_counts": 5120.0, "max_counts": 2010.0}}
```
```bash
curl http://127.0.0.1:8642/api/v1/scan/j-0007/data
```
```json
{"job_id": "j-0007", "state": "done",
 "result": {"variable_1": "H", "scan_values_1": [1.98, 1.985, 1.99, 1.995, 2.0,
   2.005, 2.01, 2.015, 2.02],
   "counts": [95.0, 210.0, 640.0, 1480.0, 2010.0, 1500.0, 690.0, 205.0, 90.0]}}
```
**Gotchas.**
- **TAVI does not fit peaks.** The `counts` array peaks at `H = 2.0` here, but
  finding the center (centroid, Gaussian fit, whatever) is the *client's* job —
  no endpoint returns a fitted peak position.
- Because the job was `isolated: true`, the operator's live `scan_command1` and
  `number_neutrons` widgets are untouched after the run — the patch lived only in
  this job's frozen launch state.

### 13.2 elastic-h-scan

**Goal.** A plain elastic (ΔE = 0) line scan across the (2 0 0) Bragg position
at a sensible production neutron count, reading the `validation` block echoed in
the 202 to confirm the point list before the scan runs.

```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"Ei": 14.7, "deltaE": 0, "K": 0.0, "L": 0.0,
       "scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 1000000}'
# -> {"applied": ["Ei", "deltaE", "K", "L", "scan_command1", "number_neutrons"], "errors": {}}

curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{}'
```
```json
{"job_id": "j-0008", "state": "queued", "position": 0,
 "eta": {"estimated_seconds": 470.0, "confidence": "high", "samples": 12},
 "validation": {"points": 11, "per_command": [{"variable": "H", "count": 11,
   "values": [1.9, 1.92, 1.94, 1.96, 1.98, 2.0, 2.02, 2.04, 2.06, 2.08, 2.1]}],
   "cost": {"points": 11, "neutrons_per_point": 1000000.0, "job_neutrons": 11000000.0,
    "pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0, "max_queued": 10},
   "eta": {"estimated_seconds": 470.0, "confidence": "high", "samples": 12},
   "infeasible": []}}
```
The `validation.per_command[0].values` list is the exact 11 points that will run
(step **0.02** over the 0.2-wide range → 11 points, not 21). Then wait for it:
```bash
curl "http://127.0.0.1:8642/api/v1/scan/j-0008?wait=120"
# -> {"state": "running", "progress": {"done": 3, "total": 11}, "timed_out": true, ...}
curl "http://127.0.0.1:8642/api/v1/scan/j-0008?wait=120"
# -> {"state": "done", "progress": {"done": 11, "total": 11}, "timed_out": false, ...}
```
**Gotchas.**
- `deltaE: 0` is what makes this *elastic*; omit it and you inherit whatever
  energy transfer was set previously.
- A `wait=` poll returns `"timed_out": true` while the job is still running —
  just call it again with the same `?wait=N`; it is not an error.

### 13.3 constant-q-energy-scan

**Goal.** Hold **Q** fixed at (2 0 0) and scan energy transfer `deltaE` upward.
Low-energy points are reachable, but the highest-energy points fall outside the
analyzer's range — a case where validation flags infeasible points and you must
choose whether to skip them.

```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"Ei": 14.7, "H": 2.0, "K": 0.0, "L": 0.0,
       "scan_command1": "deltaE 0 20 2", "number_neutrons": 1000000}'

curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" -d '{}'
```
```json
{"points": 11, "per_command": [{"variable": "deltaE", "count": 11,
  "values": [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]}],
 "cost": {"points": 11, "neutrons_per_point": 1000000.0, "job_neutrons": 11000000.0, "...": "..."},
 "eta": {"estimated_seconds": 480.0, "confidence": "medium", "samples": 5},
 "infeasible": [
   {"index": 9, "values": {"deltaE": 18}, "reason": "scattering triangle does not close"},
   {"index": 10, "values": {"deltaE": 20}, "reason": "scattering triangle does not close"}],
 "would_queue": false,
 "blockers": ["infeasible_points: 2 point(s) unreachable"]}
```
A plain `POST /scan` with this body would return `400 infeasible_points`. You
have two choices: shorten the scan (e.g. `"deltaE 0 16 2"`), or keep the range
and skip the two unreachable points with `allow_partial`:
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{"allow_partial": true}'
# -> 202 {"job_id": "j-0009", "state": "queued", "position": 0,
#         "validation": {"points": 11, "infeasible": [ ...index 9,10... ]}}

curl http://127.0.0.1:8642/api/v1/scan/j-0009/data
```
```json
{"job_id": "j-0009", "state": "done",
 "result": {"variable_1": "deltaE",
   "scan_values_1": [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
   "counts": [1820.0, 640.0, 210.0, 95.0, 60.0, 44.0, 30.0, 22.0, 15.0, null, null],
   "skipped_points": [
     {"index": 9, "values": {"deltaE": 18}, "reason": "scattering triangle does not close"},
     {"index": 10, "values": {"deltaE": 20}, "reason": "scattering triangle does not close"}]}}
```
**Gotchas.**
- Skipped points are **never silent**: they appear as `null` in `counts` *and*
  are itemized in `result.skipped_points`. Never read a `null` as zero intensity.
- `allow_partial` only skips *geometrically infeasible* points. A bad scan
  command (`400 scan_validation`) or a budget overrun (`429`) still rejects the
  whole submission.

### 13.4 quick-look-vs-production

**Goal.** Run the same H scan twice — first a fast low-`number_neutrons`
quick-look to see the shape, then a high-count production run — and use the `eta`
`confidence` to decide when the estimate is trustworthy. On a cold instrument
with no run history, the first estimate is worthless; the quick-look calibrates
it.

Quick look (few neutrons, cold history):
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 50000}}'
```
```json
{"job_id": "j-0010", "state": "queued", "position": 0,
 "eta": {"estimated_seconds": null, "confidence": "none", "samples": 0},
 "validation": {"points": 11, "infeasible": []}}
```
`confidence: "none"` and `estimated_seconds: null` mean *no usable history* — do
not trust any time estimate yet. Let it finish (it is cheap), which records
timing samples:
```bash
curl "http://127.0.0.1:8642/api/v1/scan/j-0010?wait=60"
# -> {"state": "done", "progress": {"done": 11, "total": 11}, "timed_out": false,
#     "result": {"total_counts": 210.0, "max_counts": 44.0}}   # noisy: statistics are poor
```
Now validate the production run — the ETA has history and scales to the higher
neutron count:
```bash
curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 5000000}}'
# -> {"points": 11, "eta": {"estimated_seconds": 2350.0, "confidence": "medium", "samples": 3},
#     "would_queue": true, "blockers": []}

curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 5000000}}'
# -> 202 {"job_id": "j-0011", "eta": {"estimated_seconds": 2350.0, "confidence": "medium", "samples": 3}}
```
Read the two runs back from the journal to tie them together:
```bash
curl "http://127.0.0.1:8642/api/v1/journal?limit=6"
```
```json
{"entries": [
   {"ts": "2026-07-03T15:20:05", "kind": "job", "text": "j-0010: queued (source: api)"},
   {"ts": "2026-07-03T15:20:42", "kind": "job",
    "text": "j-0010: H scan 1.900 to 2.100, 11 pts, max 44 counts at H=2.000"},
   {"ts": "2026-07-03T15:21:10", "kind": "job", "text": "j-0011: queued (source: api)"},
   {"ts": "2026-07-03T15:58:00", "kind": "job",
    "text": "j-0011: H scan 1.900 to 2.100, 11 pts, max 4380 counts at H=2.000"}],
 "total_recorded": 24}
```
**Gotchas.**
- `confidence` follows the sample count: `none` (0 samples) → `low` (1–2) →
  `medium` (3–9) → `high` (10+). Treat `low`/`none` estimates as
  "don't-know"; a single cheap scan is the cheapest way to calibrate.
- The two runs share the same journal, so a poller (or a human) can correlate the
  quick-look and the production job by their `job_id`s and result summaries.

---

## 14. Related documents

- `docs/API_SERVER_DESIGN.md` — the design and architecture behind this API.
- `docs/INSTRUMENT_LAYOUT.md` — TAS/PUMA geometry, angles, and scan modes.
- `docs/MCSTAS_PARAMETERS.md` — which parameters are build-time vs run-time.
- `User_Guide.md` — the interactive GUI workflow.
