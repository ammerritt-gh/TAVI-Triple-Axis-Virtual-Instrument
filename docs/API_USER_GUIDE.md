# TAVI Remote API — User Guide

> **Status:** live
> **Authority:** the client-facing API contract: endpoints, fields, scan syntax, events

*Last updated: 2026-10-10 (API version 2: the naming contract)*

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

**Versioning.** This guide describes **API version 2**. Every request that
writes or validates (`PATCH /parameters`, `POST /scan`, `POST /validate`,
`PUT /background`) must carry `"api_version": 2` in its JSON body; without it
(or with any other value) the server answers `400 api_version_required` and
changes nothing. Version 2 renumbered the angles the ILL way (A2 is the
monochromator 2θ, A4 the sample 2θ, A6 the analyzer 2θ) and gave every
quantity a canonical ID such as `mono_two_theta_deg`. A client written for the
old names is refused, never reinterpreted: see §15 *Breaking change*.

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
  GET  /state               -> {instrument, mode, busy, current_job, queue:[ids], parameters:{...canonical IDs; 49-51 keys depending on the instrument...}, budget}
  PATCH /parameters  body {"api_version":2,"incident_energy_mev":14.7,"h":2.0}  -> {"applied":["incident_energy_mev","h"],"errors":{}}
  POST /validate  body {"api_version":2,"parameters":{...},"force":bool,"background":{...},"engine":...,"seed":int,"noiseless":bool} -> validation + {"would_queue":bool,"blockers":[...]}  (never queues, never mutates; pass the same engine you will POST /scan with -- a direct-transmission point is infeasible for "deterministic" only)
  POST /scan  body {"api_version":2,"parameters":{...},"isolated":bool,"allow_partial":bool,"engine":"mcstas"|"deterministic","seed":int,"noiseless":bool,"background":{...}} -> 202 {job_id, state, position, eta, validation}
              engine "deterministic" = fast analytic S(Q,w) x resolution + seeded Poisson (validator); check result.metadata.cn_valid
              "background" = complete tavi.background/2 source config; REPLACES the session config for this job (never merges)
  GET/PUT /background       -> read/replace the session background config {"spec":...,"resolved":...}; PUT needs write access and "api_version":2
  GET  /scan/{id}?wait=N     -> block up to N s for terminal state; body carries "timed_out":bool
  GET  /scan/{id}/data       -> result + scan_values_1, counts (or counts_grid), skipped_points
  GET  /scan/{id}/plot.png   -> 512x512 PNG of current arrays (409 no_data if nothing renderable yet)
  GET  /journal?limit=N      -> human-readable session log (params, job lifecycle, mode/budget events)
  POST /scan/{id}/stop  |  POST /stop {"clear_queue":true}  -> drain-stop one job | stop running + clear queue

API VERSION 2: every PATCH /parameters, POST /scan, POST /validate and PUT /background body must contain
  "api_version": 2, or the answer is 400 api_version_required and nothing changes. Names are canonical IDs (aliases
  are accepted on input). The angles follow the ILL numbering: A2 = MONO 2theta (mono_two_theta_deg), A4 = SAMPLE 2theta
  (sample_two_theta_deg), A6 = ANALYZER 2theta (analyzer_two_theta_deg), A3 = sample rotation (sample_rotation_deg). Under the old
  numbering A2 was the sample 2theta and A4 the analyzer: an old script is refused, never reinterpreted.
  A request naming a retired, derived-only, read-only, unknown or duplicate key is refused whole, with nothing applied.

SCAN COMMANDS live in the parameters, NOT in the POST body directly. Set them via
  scan_command1 / scan_command2, e.g. PATCH /parameters {"api_version":2,"scan_command1":"H 1.99 2.01 0.01"}.
  SYNTAX: "VARIABLE start stop STEP". The 3rd number (last token) is the STEP SIZE, not a point count.
  "H 1.99 2.01 0.01" = 3 points (1.99, 2.00, 2.01). A step larger than the range is an error; so is a zero step or one whose sign does not match the direction. `force` does not pass any of these.
  Two non-empty commands = a 2D scan (points multiply). One command = 1D. None = single point.
  Scannable variables, by canonical ID [aliases]: h k l [H K L]; q_instrument_x_inv_angstrom q_instrument_y_inv_angstrom
  q_instrument_z_inv_angstrom [qx qy qz]; energy_transfer_mev [deltaE]; mono_two_theta_deg [A2 mtt]; sample_rotation_deg [A3 sth omega psi];
  sample_two_theta_deg [A4 stt 2theta]; analyzer_two_theta_deg [A6 att]; sample_lower_arc_deg [sgl] and sample_upper_arc_deg [sgu] (angle mode only);
  mono_horizontal_radius_m mono_vertical_radius_m analyzer_horizontal_radius_m analyzer_vertical_radius_m [rhm rvm rha rva].
  A1 and A5 are derived Bragg angles (refused; scan A2 or A6). chi, phi, kappa are refused. Slit gaps cannot be scanned.

GOLDEN WORKFLOW:
  1. GET /schema  (learn fields, allowed values, and limits for THIS instrument — do this first)
  2. GET /state   (confirm mode=="allow" and busy==false; read current parameters)
  3. PATCH /parameters to set energies/Q/lattice/scan_command1[/2] and number_neutrons
  4. POST /validate with the same parameters/background/engine you will POST /scan -> only submit if would_queue==true;
     if blockers list infeasible points, either fix them or POST /scan with "allow_partial":true
  5. POST /scan  -> capture job_id (the launch state is built from defaults + your "parameters"
     patch only, so a scan never reads or disturbs the GUI; "isolated" is an accepted no-op)
  6. GET /scan/{id}?wait=30  -> long-poll instead of tight polling; repeat while "timed_out":true
     until state is terminal: done | failed | stopped | cancelled  (running/queued are NOT terminal)
  7. GET /scan/{id}/data -> read result.scan_values_1 + result.counts; result.skipped_points lists
     any points omitted by allow_partial (never a silent gap). GET .../plot.png for a visual check.

ETA: 202 and status carry eta {estimated_seconds, confidence:none|low|medium|high, samples}.
  confidence low/none => estimate is unreliable; run one cheap scan first to calibrate history.

BUDGET LIMITS (API jobs only): <=10 queued jobs, <=200 points/scan,
  <=1e8 neutrons/point, <=1e10 total pending neutrons. Over-limit POST /scan -> HTTP 429.

RULES:
  - Send "api_version": 2 in every write/validate body. Use canonical IDs from /schema; never the pre-version-2 key names.
  - Read /schema then /state before submitting; do not submit if mode!="allow".
  - Prefer wait= long-poll over repeat GETs; never spin in a tight loop.
  - A count of null means the point was not measured / was invalid — never treat null as 0.
  - On 409 / 429 / 503, OBEY the Retry-After header: wait that many seconds before retrying,
    report the .message to the user, and do not retry in a loop.
  - When retrying a POST /scan you are unsure completed, send the SAME "Idempotency-Key: <str>"
    header — a repeat returns the original job (HTTP 200) instead of creating a duplicate.
  - TAVI GENERATES background (independently enabled/scaled catalog sources, global default OFF,
    always stamped in result.metadata.background). It never fits or subtracts one — that is your job.
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
 "queue": [], "parameters": {"incident_energy_mev": 14.7,
 "incident_wavevector_inv_angstrom": 2.662, "h": 2.0, "k": 0.0,
 "l": 0.0, "scan_command1": "", "scan_command2": "", "number_neutrons": 1000000,
 "...": "42 more fields"}, "budget": {"pending_neutrons": 0.0, "budget": 1e10,
 "queued_jobs": 0, "max_queued": 10}}
```

**3. Set parameters** — pick an incident energy and a 3-point scan over H. Every
write carries `"api_version": 2`; `Ei` is an accepted alias of the canonical
`incident_energy_mev`, and the reply always names fields canonically:

```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "Ei": 14.7, "scan_command1": "H 1.99 2.01 0.01", "number_neutrons": 100000}'
```
```json
{"applied": ["incident_energy_mev", "scan_command1", "number_neutrons"], "errors": {}}
```

**4. Submit the scan** (returns immediately; the scan runs as a queued job):

```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{"api_version": 2}'
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
 "result": {"mode": "1D", "variable_1": "h", "variable_2": null,
 "total_counts": 452.0, "max_counts": 310.0, "output_folder": "output/scan"}}
```
```bash
curl http://127.0.0.1:8642/api/v1/scan/j-0001/data
```
```json
{"job_id": "j-0001", "source": "api", "state": "done", "progress": {"done": 3, "total": 3},
 "error": null, "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "h", "variable_2": null,
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
2. **Set parameters.** `PATCH /parameters` with `"api_version": 2` and the
   fields you want to change. Linked fields recompute automatically (set
   `incident_energy_mev` and `incident_wavevector_inv_angstrom` updates; set `h`
   and the three `q_instrument_*_inv_angstrom` fields update via the UB
   matrix). The scan itself is defined by the `scan_command1` and (optionally)
   `scan_command2` parameters.
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
id (or `null`), the list of queued job ids, the complete parameter dict (49 to
51 keys depending on the instrument, 45 to 47 of them writable — see §6), the configured limits (if any), current budget usage, and the
session's background configuration (the same object `GET /background` returns).
```json
{"instrument": "puma", "mode": "allow", "busy": true, "current_job": "j-0003",
 "queue": ["j-0004", "j-0005"], "parameters": {"incident_energy_mev": 14.7, "...": "..."},
 "limits": {"max_queued": 10, "max_points": 200, "max_neutrons_per_point": 1e8,
 "queue_neutron_budget": 1e10},
 "budget": {"pending_neutrons": 3.0e8, "budget": 1e10, "queued_jobs": 2, "max_queued": 10},
 "background": {"spec": {"catalog_version": 2, "enabled": false,
   "sources": {"environment_flat": {"enabled": true, "scale": 1.0},
    "...": "five more sources: slope/elastic/tail enabled, aluminum/cosmic disabled; all at scale 1.0"}},
  "resolved": {"...": "see GET /background"}}}
```

### GET /parameters
Just the parameter dict (the same object that appears under `parameters` in
`/state`). See §6 for every field.

### PATCH /parameters
Partial parameter write. Body is a JSON object of `field: value` pairs plus the
required `"api_version": 2` (§1). Returns the list of applied fields and a
per-field error map. A field is named by its canonical ID (§6); the aliases in
the §6 table (`Ei`, `H`, `A4`, `stt` ...) are accepted too, in any letter case,
and the reply always names a field canonically.
```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "incident_energy_mev": 14.7, "h": 2.0}'
```
```json
{"applied": ["incident_energy_mev", "h"], "errors": {}}
```
- No `api_version`, or a value other than the integer `2` (`1`, `3`, `"2"`,
  `2.0` and `true` all fail) → `400 api_version_required`. The message names
  the change and points to §15; nothing is applied, queued or replaced.
```json
{"error": {"code": "api_version_required",
 "message": "This request needs \"api_version\": 2 (got missing). TAVI's names changed: angle numbering now follows the ILL (A2 mono 2theta, A4 sample 2theta, A6 analyzer 2theta) and quantities have canonical IDs such as mono_two_theta_deg. Read the Breaking change section of the API guide, then add the field to the body.",
 "details": {"required_api_version": 2}}}
```
- A **key-level** problem refuses the **whole request** with `400
  invalid_parameters` and applies nothing (`details.applied` is `[]`): an
  unknown field; a retired name (`chi`, `phi`, `kappa`, `slits_mm`, the
  metre-valued slit names such as `vbl_hgap`, the unit-less `lattice_a` ...);
  a derived-only quantity (`A1`, `A5`, `applied_*_radius_m`); a read-only
  field; a slit gap this instrument does not have; or one quantity named twice
  (`A4` together with `stt`, `A3` with `omega`). Each error is keyed by the
  name **as you sent it** and says what to send instead:
```json
{"error": {"code": "invalid_parameters", "message": "One or more fields failed",
 "details": {"applied": [], "errors": {
  "A1": "independent crystal rocking is not modelled yet; set A2 (mono 2θ)",
  "chi": "chi is a four-circle tilt axis that TAVI does not model; its sample tilt arcs are sgl and sgu",
  "slits_mm": "slits_mm is retired: set each gap by its own key, slit.<stable_id>.horizontal_gap_mm or .vertical_gap_mm (millimetres)",
  "bogus_field": "unknown field"}}}}
```
```json
{"error": {"code": "invalid_parameters", "message": "One or more fields failed",
 "details": {"applied": [], "errors": {
  "stt": "sample_two_theta_deg is assigned twice, as 'A4' and 'stt'; send it once",
  "A4": "sample_two_theta_deg is assigned twice, as 'A4' and 'stt'; send it once"}}}}
```
- A **value** problem (not a number, outside an arc's travel ...) is reported
  per field: that field is skipped and the other valid fields still apply.
  `details.applied` lists what did:
```json
{"error": {"code": "invalid_parameters", "message": "One or more fields failed",
 "details": {"applied": ["k"], "errors": {"h": "invalid value: could not convert string to float: 'abc'"}}}}
```
- While a scan is running or queued, a write is rejected with `409 busy` unless
  you pass `?force=1` (e.g. `PATCH /parameters?force=1`).
- In **read-only** mode, any write returns `403 read_only`.
- Within one field, a bad value is skipped entirely, never half-applied.
- The mounted **sample** is one of these fields: set `"sample": "<id>"` (e.g.
  `"Al_phonon_DFT"`, `"Pb_phonon_DFT"`, `"Al_bragg"`, or `"none"`). Allowed ids come from the sample
  library and are listed under the `sample` field of `GET /schema`; an unknown id
  → `400 invalid_parameters`. Selecting a sample adopts its lattice, so pass any
  explicit `lattice_*_angstrom` / `lattice_*_deg` overrides in the *same* patch (they win). The chosen
  sample travels into each job's `launch.parameters` (as `sample`/`sample_key`).

### POST /scan
Submit a scan job. The body carries the required `"api_version": 2` (§1; a
missing or other value is `400 api_version_required` before anything runs). The
job runs the scan currently defined by the
`scan_command1` / `scan_command2` parameters. An optional inline `parameters`
object is applied **first** (same rules as `PATCH /parameters`), then the scan
commands are validated, budgets are checked, and the job is queued.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.99 2.01 0.01"}}'
```
```json
{"job_id": "j-0004", "state": "queued", "position": 0,
 "eta": {"estimated_seconds": 42.0, "confidence": "high", "samples": 11},
 "validation": {"points": 3, "per_command": [{"variable": "h", "count": 3,
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
  Pass `"force": true` in the body to override the *soft* scan-command
  warnings (a very long scan). A hard rejection -- an unknown or refused
  variable (`A1`, `A5`, `chi`, a slit gap ...), a malformed command, a zero or
  wrong-sign step, a step longer than the range, a Q variable
  paired with an HKL one, an angle (`A2`, `A3`, `A4`, `A6`, an arc, or an alias
  such as `mtt`, `omega`, `stt`, `2theta`) paired with a Q, HKL or `deltaE`
  variable, or two commands that write one scan slot (the same variable twice,
  or two spellings of one quantity: `A3` with `omega`, `A4` with `stt`, `A2`
  with `mtt`) -- is refused regardless, exactly as the GUI Run
  button refuses it. `A3` beside `A4` is two different slots and is accepted.
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
- **Unknown top-level body key → `400 bad_request`.** The `POST /scan` body
  accepts only `api_version`, `parameters`, `force`, `allow_partial`, `isolated`, `engine`,
  `seed`, `noiseless`, and `background`; any other top-level key is rejected (the error names
  the offending key and lists the allowed set). This is a guard against typos
  such as sending `scan_command1` at the top level instead of nesting it under
  `parameters` — which would otherwise silently run the GUI's current scan.
  (`POST /validate` and `POST /stop` are equally strict about their own keys.)
  Parameter names still go **inside** `parameters`.

**`allow_partial`** (optional boolean, default `false`). When `true`, a scan with
some infeasible points is still queued: only the feasible points run, and
`result.skipped_points` lists each omitted point as `{"index", "values",
"reason"}`. When `false` (the default), a single infeasible point rejects the
whole submission with `400 infeasible_points`. `allow_partial` skips
geometrically infeasible points and, for analytic-engine (`deterministic`)
jobs, direct-transmission points, listed in `skipped_points` with kind
`transmission`.

**`isolated`** (optional boolean, default `false`). Accepted and echoed in the
202 payload and the job snapshot for backward compatibility, but now a **no-op**:
`POST /scan` and `POST /validate` always build their launch state from
instrument defaults overlaid with the request's `parameters` patch, reading **no
live GUI widgets**. A submission therefore never disturbs the operator's setup or
other queued work, and text a human left in a scan-command widget (never
submitted) can never bleed into an API scan. The only endpoint that mutates GUI
state is `PATCH /parameters`; the only shared context between an API scan and the
GUI is the loaded instrument.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"h": 3.0, "scan_command1": "K -0.1 0.1 0.02"}}'
```
A scan submitted without a non-empty `scan_command1` (or a lone `scan_command2`,
which is swapped in) is rejected with `400 missing_required`, since the launch
state no longer inherits whatever command was sitting in the GUI.

**`engine`** (optional string, default `"mcstas"`). Selects the execution
backend for this job. `GET /schema` advertises the allowed list under `engines`.

- **`"mcstas"`** — the full Monte-Carlo simulation. This is the default and the
  reference; nothing changes for existing clients.
- **`"deterministic"`** — a **fast analytic check**. For a `Phonon_DFT`
  sample it reads the same configured regular H-K-L dispersion grid and LAU/LAZ
  reflection table as McStas, evaluates every branch in the file, and combines
  separately calibrated phonon and elastic channels after resolution
  convolution. `Single_crystal` is Bragg-only. Milliseconds per point instead
  of seconds-to-minutes. It
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
  -d '{"api_version": 2, "parameters": {"scan_command1": "deltaE 0.5 3.0 0.125"},
       "engine": "deterministic", "seed": 1, "noiseless": false}'
```

**`background`** (optional object, default `null`). A complete per-scan
background configuration for **this job only**. It **replaces** the session
configuration (`GET`/`PUT /background`) wholesale — it never merges with it —
and applies to both engines. Omit it (or send `null`) to run the session
configuration.

The object has exactly the v2 request fields described under `PUT /background`:
required `catalog_version`, required global `enabled`, and required `sources`.
Each included source has exactly `enabled` and `scale`; omitted catalog sources
normalize to disabled at scale `1.0`.

```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"scan_command1": "deltaE 0.5 3.0 0.125"},
       "engine": "deterministic",
       "background": {"catalog_version": 2, "enabled": true,
                      "sources": {
                        "environment_flat": {"enabled": true, "scale": 1.0},
                        "sample_elastic": {"enabled": true, "scale": 0.5}}}}'
```

The configuration is resolved against catalog version 2 before the job is
queued, so an unknown source, catalog mismatch, invalid enable, or non-finite or
negative scale is a submission-time `400 invalid_background`, never a job that
fails halfway. The error `details` carries `{"background": <the background
block described under POST /validate>}`.

`POST /validate` runs exactly the same check (see below), so a body that
validates cannot later be refused for a background reason.

A campaign that must not depend on this server's mutable defaults should stamp
the normalized source configuration, including `catalog_version`, on every
scan. A catalog retune must bump that version, so a resumed campaign refuses
before spending rather than silently changing planted truth.

**Provenance.** The chosen engine is recorded on the job: the `launch` summary
(`GET /scan/{id}`, `/data`, and the saved JSON) carries `"engine"`, plus `"seed"`
and `"noiseless"` when the deterministic engine ran, plus `"background"` (the
requested spec) and `"background_source"` (`"config_default"` or
`"per_scan_override"`) once the launch state carries them. A deterministic job's
`result.metadata` is additionally stamped with `engine`, `seed`, `method`,
`cn_valid`, and `invalidations` (see below). `metadata.analytic_model` records
the channel names, branch/reflection counts, configured and resolved filenames,
SHA-256 hashes, channel calibrations, reflection mode, and the Γ policy
`"zero_energy_policy": "match_phonon_dft_skip"`.

**Honesty stamps.** Theoretical resolution is only valid when the analytic
assumptions hold. Configurations that break them (e.g. nested-mirror optics
replacing the collimator divergence model) do **not** silently fall back: the
engine still runs, but stamps `metadata.cn_valid = false` and lists each reason
in `metadata.invalidations`. Treat those results as a fidelity gap, not an error
— always check `cn_valid` before trusting deterministic intensities.

**Calibration caveat.** Absolute deterministic counts depend on separate
**calibrated phonon and elastic constants** in the selected sample specification,
*not* a first-principles normalization. Peak positions, relative intensities
across a scan, and widths are meaningful; the absolute count scale is an
approximation. For absolute counts, run McStas.

The deterministic engine requires a sample with a registered analytic ground
truth. An unknown sample fails the job cleanly with reason `no analytic ground
truth for sample 'X'` (a failed job with a message, never a crash).

Analytic support is intentionally limited to valid regular-grid `Phonon_DFT`
maps and Bragg-only `Single_crystal` samples. A grid may contain any positive
number of contiguous, zero-indexed branches; adding a branch to the file does
not require rebuilding the analytic engine. Optional column 7 supplies a
per-point linewidth (FWHM), otherwise the component's global `phonon_gamma` is
used. Missing rows, duplicate cells, irregular dimensions, non-finite values,
non-contiguous branches, or a missing configured dispersion/reflection file
fail the deterministic job visibly. This is not a general analytic-model
registry: unrelated continua, diffuse scattering, and magnetic component types
remain unsupported.

The maintained implementation reference is
[`ANALYTIC_ENGINE.md`](ANALYTIC_ENGINE.md). The TAVI-owned component and shared
dispersion-file contract are documented in
[`components/PHONON_DFT.md`](../components/PHONON_DFT.md).

### POST /validate
Dry-run the exact checks `POST /scan` performs — scan-command parsing, per-point
feasibility, budget, background resolution, and ETA — **without queueing
anything and without mutating any parameter**. It needs the same
`"api_version": 2` as a write (a validation under the wrong names would
answer for a different job than the one you submit). Its accepted body fields are
the required `api_version` and optional `parameters`, `force`, `background`, `engine`, `seed`, and
`noiseless` — the same engine/noise selection `POST /scan` accepts, so a dry
run answers for the exact job the client will submit; `allow_partial` and
queue-only controls remain `POST /scan`-only. Any inline
`parameters` patch is applied to a private copy of the default launch state, so
`/validate` never changes the GUI. Non-mutating, it is **allowed in read-only
mode**.
```bash
curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.9 2.1 0.05"}}'
```
Returns the `validation` object (§5 *Validation object*) plus two extra fields:
- `would_queue` — `true` if `POST /scan` with the same body would be accepted.
- `blockers` — a list of human strings for each reason it would be rejected
  (empty when `would_queue` is `true`), e.g. `"infeasible_points: 2 point(s)
  unreachable"` or `"scan_validation: ..."` or `"limit_exceeded: ..."`.
```json
{"points": 5, "per_command": [{"variable": "h", "count": 5,
  "values": [1.9, 1.95, 2.0, 2.05, 2.1]}],
 "cost": {"pending_neutrons": 0.0, "budget": 1e10, "queued_jobs": 0,
  "max_queued": 10, "points": 5, "neutrons_per_point": 100000.0,
  "job_neutrons": 500000.0},
 "eta": {"estimated_seconds": 70.0, "confidence": "high", "samples": 11},
 "infeasible": [],
 "background": {"background_schema": "tavi.background/2",
  "enabled": true, "delivery_source": "config_default",
  "catalog_version": 2,
  "profile_fingerprint": "5861d4af84059711", "effective_fingerprint": "b07c96a008338129",
  "sources": {"environment_flat": {
    "enabled": true, "scale": 1.0, "category": "environment",
    "label": "Flat floor", "shape": "flat",
    "base_numerics": {"rate": 6.0e-10},
    "units": {"rate": "counts per monitor count"}},
   "...": "the other five normalized catalog sources"}},
 "would_queue": true, "blockers": []}
```

**Background parity.** `/validate` resolves the background exactly as `POST
/scan` would — same catalog and source settings — and reports it in a
`background` block (also present in the
`POST /scan` 202 `validation` object):

| Field | Meaning |
|---|---|
| `background_schema` | Wire identity (`"tavi.background/2"`); absent when resolution failed. |
| `enabled` | Global background switch (`null` if the spec did not resolve). |
| `catalog_version` | Catalog numerics pinned by the request. |
| `delivery_source` | `"config_default"` or `"per_scan_override"`. |
| `sources` | Complete normalized mapping containing enable/scale plus category, label, description, scale meaning, shape, base numerics, and units; absent when resolution failed. |
| `profile_fingerprint` | Identity of all remembered source settings. |
| `effective_fingerprint` | Identity of only the sources that can plant counts. |
| `error` | Present only on a refusal: `{"id", "message"}`. |

One background blocker can appear in `blockers`, matching the code `POST /scan`
returns as a `400`: `invalid_background: <reason>`.

### GET /background
The session's configured background sources. Read-only, no side effects,
**allowed in read-only mode**.

TAVI *generates* background: configured sources are planted into the counts of
every scan by both engines and stamped into the scan's metadata. TAVI never
*analyses* a background — it does not fit, subtract, or infer one.
Configuration is **default-off**: a new session remembers the realistic source
mixture behind a disabled global switch and produces counts identical to
background-free TAVI.

```bash
curl http://127.0.0.1:8642/api/v1/background
```
```json
{"spec": {"catalog_version": 2, "enabled": true,
          "sources": {
            "environment_flat": {"enabled": true, "scale": 1.0},
            "environment_slope": {"enabled": true, "scale": 1.0},
            "environment_cosmic_spikes": {"enabled": false, "scale": 1.0},
            "instrument_aluminum_powder": {"enabled": false, "scale": 1.0},
            "sample_elastic": {"enabled": true, "scale": 1.0},
            "sample_elastic_tail": {"enabled": true, "scale": 1.0}}},
 "resolved": {
   "background_schema": "tavi.background/2", "catalog_version": 2,
   "enabled": true, "delivery_source": "config_default",
   "sources": {
     "environment_flat": {
       "category": "environment", "label": "Flat floor",
       "enabled": true, "scale": 1.0, "shape": "flat",
       "base_numerics": {"rate": 6.0e-10},
       "units": {"rate": "counts per monitor count"}},
     "...": "one normalized entry per catalog source"},
   "profile_fingerprint": "5861d4af84059711",
   "effective_fingerprint": "b07c96a008338129"}}
```

- `spec` is the request spec as stored (what you would `PUT` back).
- `resolved` is the same base block that lands in scan metadata. A Monte Carlo
  scan that constructs background RNG additionally records `background_seed`.
  Sparse non-zero cosmic realizations appear under `realized_events`.
- Each source reports its fixed catalog definition beside the remembered enable
  and scale. Multiply its shape rate by `scale` for the planted rate.
- Omitted sources in an input normalize to disabled at scale `1.0`, so GET
  always returns a complete, stable configuration.
- Disabled configurations still report all source settings and both
  fingerprints, because absence of planted background is provenance too.

### PUT /background
Replace the session background configuration **wholesale** (it never merges
with the stored one). Write-gated, and the body carries the required
`"api_version": 2` (§1). Returns the same `{"spec", "resolved"}`
object as `GET /background`.

```bash
curl -X PUT http://127.0.0.1:8642/api/v1/background \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "catalog_version": 2, "enabled": true,
       "sources": {
         "instrument_aluminum_powder": {"enabled": true, "scale": 0.5},
         "environment_cosmic_spikes": {"enabled": true, "scale": 2.5}}}'
```

Rules:
- Top-level fields are exactly `api_version` (the API version, §1; not part of the stored
  spec), `catalog_version`, `enabled`, and `sources`. The `background` object
  inside a `POST /scan` / `POST /validate` body has no `api_version` of its own.
- `catalog_version` is required and must equal `2`; this pins the catalog
  numerics used by long-running consumers.
- Source entries contain exactly `enabled` and `scale`. Unknown ids or fields
  are rejected rather than ignored.
- Scales must be finite numbers `>= 0`. A source checkbox is the ordinary
  off-switch, but scale zero is valid and plants nothing.
- `enabled: false` still validates and fingerprints every remembered source
  setting.
- Source category, label, description, shape, base numerics, and units come
  from `GET /schema`; callers cannot override them.
- A per-scan configuration uses this same object and replaces the session
  configuration wholesale.

Errors:
- Missing required fields, a catalog mismatch, an unknown source id, an unknown
  nested source field, or an invalid enable/scale value → `400
  invalid_background`. An unknown top-level field is rejected earlier as `400
  bad_request`. Every remote v1 form (preset, override, raw term list, or global
  scale) therefore fails. On `PUT`, the stored configuration is left untouched.
- Read-only mode → `403 read_only`.
- Backend handler unavailable (should not occur in a shipped build) →
  `501 not_implemented`.
- Any other HTTP method on this path → `405 method_not_allowed`.

The GUI surface is a global checkbox under the engine selector plus a
**Background configuration…** button. Its modal dialog groups independent
enable/scale controls under Environment, Instrument, and Sample. Aluminum's
single control scales all six synthetic lines; cosmic scale changes incidence,
not event amplitude, and its tooltip notes that events remain in noiseless
deterministic scans. Dialog edits apply only on **Apply**, **Cancel** discards
them, and the dialog remains available while the global switch is off.
For the physical meaning, equations, calibration, and limitations of the
catalog sources, see [`BACKGROUND_MODEL.md`](BACKGROUND_MODEL.md).

Only current catalog-v2 state is restored from local parameter persistence.
Legacy preset forms, older catalog versions, and malformed saved background
state are visibly reset to the safe new-session defaults with the global
background switch off. Remote older-catalog and preset-style requests are
rejected as well; no request-side migration is performed.

### GET /resolution
Theoretical triple-axis **resolution** (Cooper–Nathans / Popovici) at one
`(h, k, l, energy_transfer_mev)` point, computed from the current instrument configuration.
Read-only, never mutates, so — like `/state`, `/schema` and `/validate` — it is
**allowed in read-only mode**. A GET has no body, so it needs no
`api_version`. All query params are optional:

| Param | Meaning | Default |
|-------|---------|---------|
| `h`, `k`, `l` (aliases `H`, `K`, `L`) | Reciprocal-lattice point (r.l.u.) | current GUI values |
| `energy_transfer_mev` (alias `deltaE`) | Energy transfer (meV) | current GUI value |
| `method` | `auto`, `cooper_nathans`, or `popovici` | `auto` |

The query keys are read through the same name registry as writes (any letter
case). Any other key is `400 bad_request` rather than silently ignored, so a
typo cannot resolve at the GUI's own point: an unknown name (`?foo=1`), a
quantity that is not a resolution field (`?Ei=14`), a cache-busting
parameter (`?_=1`), or two spellings of one quantity (`?H=1&h=1`).

`method=auto` picks **Popovici** when the instrument config carries spatial
information (mono/analyzer curvatures — `rhm`/`rvm`/`rha` — make the config
"spatial"), otherwise **Cooper–Nathans**. When Popovici runs with defaulted
spatial dimensions, that is intended: the `warnings` and `config.provenance`
carry the honesty (which dimensions were defaulted). A non-numeric `h`/`k`/`l`/
`energy_transfer_mev` → `400 bad_request`; an unrecognized `method` → `400 bad_request`.

```bash
curl "http://127.0.0.1:8642/api/v1/resolution?h=2&k=0&l=0&energy_transfer_mev=1.5&method=cooper_nathans"
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
- A geometry that solves to a zero sample two-theta (forward scattering) is
  refused the same way: `{"ok": false, "reason": "direct transmission
  (sample): the analytic engine makes no claim"}` — Cooper–Nathans has no
  resolution function there.

### GET /schema
Machine-readable self-description of the API, generated at request time from live
instrument data (no hand-maintained duplicate). Read-only, no side effects,
**allowed in read-only mode**.
```json
{"api_version": 2, "instrument": "puma",
 "fields": [{"name": "incident_energy_mev", "type": "number", "units": "meV"},
   {"name": "K_fixed", "type": "string", "allowed": ["Ki Fixed", "Kf Fixed"]},
   {"name": "monocris", "type": "string", "allowed": ["pg002", "pg002_test"]},
   {"...": "one entry per writable parameter"}],
 "scan_variables": ["mono_two_theta_deg", "sample_rotation_deg",
   "sample_two_theta_deg", "analyzer_two_theta_deg", "sample_lower_arc_deg",
   "sample_upper_arc_deg", "h", "k", "l", "q_instrument_x_inv_angstrom",
   "q_instrument_y_inv_angstrom", "q_instrument_z_inv_angstrom",
   "energy_transfer_mev", "mono_horizontal_radius_m", "mono_vertical_radius_m",
   "analyzer_horizontal_radius_m", "analyzer_vertical_radius_m"],
 "engines": ["mcstas", "deterministic"],
 "scan_body_fields": [
   {"name": "engine", "type": "string", "allowed": ["mcstas", "deterministic"],
    "default": "mcstas"},
   {"name": "seed", "type": "integer", "default": null},
   {"name": "noiseless", "type": "boolean", "default": false},
   {"name": "background", "type": "object", "default": null}],
 "background": {"background_schema": "tavi.background/2",
   "catalog_version": 2,
   "categories": ["environment", "instrument", "sample"],
   "sources": {
     "environment_flat": {
       "category": "environment", "label": "Flat floor",
       "description": "Featureless ambient counting floor...",
       "scale_meaning": "Scale multiplies the ambient floor rate.",
       "shape": "flat", "base_numerics": {"rate": 6.0e-10},
       "units": {"rate": "counts per monitor count"}},
     "...": "environment_slope, environment_cosmic_spikes, instrument_aluminum_powder, sample_elastic, sample_elastic_tail"},
   "request": {
     "catalog_version": "required integer matching catalog_version",
     "enabled": "required boolean global gate",
     "sources": {"<source id>": {
       "enabled": "required boolean",
       "scale": "required finite number >= 0"}},
     "omitted_sources": "disabled at scale 1.0",
     "replacement_semantics": "wholesale; never merges"},
   "spec_fields": ["catalog_version", "enabled", "sources"]},
 "scan_command_grammar": "VARIABLE start stop STEP. The third number (the last
   token) is the STEP SIZE, not the number of points. ...",
 "limits": {"max_queued": 10, "max_points": 200, "max_neutrons_per_point": 1e8,
   "queue_neutron_budget": 1e10},
 "endpoints": [{"method": "GET", "path": "/schema", "description": "..."}],
 "examples": ["align-on-bragg-peak", "elastic-h-scan", "constant-q-energy-scan",
   "quick-look-vs-production"]}
```
Each field carries `name` (the canonical ID, §6), `type`, `units` (where
known), and `allowed` (the permitted values for choice fields — crystal ids,
`K_fixed` modes, source types). `api_version` is the version the server
speaks (§1). `scan_variables` lists canonical IDs; the aliases accepted in a
scan command (§7) are not repeated there. The slit gaps appear as
`slit.<stable_id>.horizontal_gap_mm` / `.vertical_gap_mm` fields, only for the
active instrument's own slits.
`engines` is the list of execution backends selectable via the `POST /scan`
`engine` body field; `scan_body_fields` documents the optional top-level scan
body fields (`engine`, `seed`, `noiseless`, `background`) beyond `parameters`.
`examples` names the worked examples elsewhere in this guide.

The `background` block is the full self-description of the background
generator (`GET`/`PUT /background`): category order and every stable source id
with its label, tooltip description, scale meaning, shape, base numerics, and
units. `catalog_version` is bumped whenever any source definition or numeric
changes; campaign clients pin it in every request so catalog drift refuses
before acquisition.

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
Job status. Returns the job snapshot (it carries `"api_version": 2`, as does every
SSE event): state, source (`gui`/`api`), timestamps,
`progress: {done, total}`, error (or `null`), a small `launch` summary, a
`result` summary (count totals and output folder — no arrays here), and an `eta`
object (see *ETA object* below).
```json
{"job_id": "j-0003", "source": "api", "state": "running",
 "submitted_at": 1751500000.0, "started_at": 1751500001.0, "finished_at": null,
 "progress": {"done": 1, "total": 3}, "error": null,
 "launch": {"scan_command1": "H 1.99 2.01 0.01", "scan_command2": "", "number_neutrons": 100000},
 "result": {"mode": "1D", "variable_1": "h", "variable_2": null,
 "total_counts": 82.0, "max_counts": 82.0, "output_folder": "output/scan"},
 "eta": {"estimated_seconds": 8.0, "confidence": "medium", "samples": 4}}
```
`result` is `null` for a job that has not yet started building its scan geometry
(e.g. still `queued`). Unknown id → `404 unknown_job`. Once the job has geometry,
`result.skipped_points` lists any points omitted because they were infeasible and
the job was submitted with `allow_partial` (empty `[]` for a normal job) — each
entry is `{"index", "values", "kind", "reason"}`. `kind` is
`physical_infeasible`, `geometry_solver_error`, or `curvature_out_of_travel`
for an ordinary infeasible point; a direct-transmission point (see below)
carries kind `transmission`.

**Direct transmission (a zero two-theta).** A zero take-off on the
monochromator, sample, or analyser is a legal geometry (nothing crashes or
diverges), but the instrument selects no energy there: TAVI records the
absent side's `incident_energy_mev`/`incident_wavevector_inv_angstrom` or
`final_energy_mev`/`final_wavevector_inv_angstrom`, and `energy_transfer_mev`
when either is absent, as `null` rather than inventing a value, both in the API result and in the
saved per-point `scan_parameters.txt` (written as the literal `None`).
`result.transmission_points` is the per-point trace, one `{"index", "axes"}`
entry per marked point (`axes` drawn from `mono`/`sample`/`ana`) — the only
place a marked point shows up for either engine, since `result` metadata is
the launch state. The analytic (`deterministic`) engine makes no claim at
such a point and skips it (`null` in `result.counts`, an entry in
`skipped_points` with kind `transmission`); a McStas run executes it as the
instrument model builds it. See §12 *Gotchas* for how a McStas run behaves
near, not just at, zero.

**Validation object.** The `validation` block embedded in a `POST /scan` 202
response (and returned by `POST /validate`) has:
`{"points": <int total>, "per_command": [{"variable", "count", "values":[...]},
...], "cost": {budget usage + "points"/"neutrons_per_point"/"job_neutrons"},
"eta": {ETA object}, "infeasible": [{"index", "values", "reason"}, ...]}`.
`infeasible` is empty when every point's scattering triangle closes; each entry
names a point that is geometrically unreachable and why (e.g. `"scattering
triangle does not close"`, `"analyzer angle out of range"`). It also carries a
`background` block (see `POST /validate`) describing the profile this job will
plant. `POST /validate` adds `would_queue` (bool) and `blockers` (list of
strings).

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
 "result": {"mode": "1D", "variable_1": "h", "variable_2": null,
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
downstream analysis (e.g. reconstructing the theoretical resolution offline).
Every quantity in these two objects is named by its canonical ID (§6; the slit
gaps as `slit.<stable_id>.<axis>_gap_mm`), and `result.metadata` carries
`"api_version": 2`:

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

**Crystal curvature.** A monochromator or analyzer crystal has up to four
bending-radius axes: `mono_horizontal_radius_m`, `mono_vertical_radius_m`,
`analyzer_horizontal_radius_m`, `analyzer_vertical_radius_m`. In this section
`rhm`/`rvm`/`rha`/`rva` are the accepted short aliases of these four IDs, in
that order; a reply always uses the long IDs. Two contracts apply, and mixing
them up is the single easiest mistake a client can make here:

- Every field you **send** (`rhm`/`rvm`/`rha`/`rva` in a `PATCH /parameters`
  or `POST /scan` patch) is a **magnitude in metres**. `0` always means FLAT
  and is always legal — a minimum radius bounds how tightly a bender may
  bend, never whether it may be straight.
- `result.applied_curvature` (below) is **signed**: which side the crystal
  actually bent toward, under the derived-only IDs `applied_mono_horizontal_radius_m`
  and its three siblings (writing one is refused). Never send a value from
  there back as an `rhm`/etc. input expecting it to mean the same thing — an
  input is a magnitude, an output is signed geometry.

*Naming a radius HOLDS that axis.* Patching `rhm`/`rvm`/`rha`/`rva` pins that
one axis to the value you sent for the rest of the request; every axis you do
not name stays AUTOFOCUS (recomputed from the instrument's optics before
every point) unless a scan command names it (see below). Naming one radius
never affects the other three — each axis's mode is independent.

*Held radius vs. mechanical travel.* A HELD radius (or every value a scan
range would actually run, absolute or relative) is checked against the
axis's declared travel at submission, before anything runs. Out of travel is
refused, never silently clamped, as:
```json
{"error": {"code": "curvature_out_of_travel",
  "message": "rhm on the PG[002] monochromator: commanded radius 1 m is tighter than the mechanical minimum of 2 m."}}
```
(PUMA's `rhm` has a 2 m mechanical minimum; commanding `1` is refused.) A
driven axis with no declared minimum/maximum refuses nothing — **IN8 and
PANDA declare no mechanical travel on any axis**, because neither is
published, and inventing a limit would be the defect. A commanded radius
must always be a finite number, on every axis, regardless of declared
travel: `NaN` and `+/-inf` are refused as `invalid_parameters` (the
`rhm`/`rvm`/`rha`/`rva` fields reject a non-finite value when the request is
parsed, before any travel is consulted), which is deliberately a different
code from `curvature_out_of_travel` — "your numeric value is invalid" and
"this radius conflicts with the hardware's travel" are different problems
with different fixes. A **fixed** axis
(`CurvatureAxis.driven=False` — PUMA's `rva` at a fixed 0.8 m, or PUMA's
`rhm`/`rvm` once a nested mirror optic (NMO) module is fitted, which pins
both to flat) accepts **only** its declared radius and refuses every other
value, `0` included when the declared radius is nonzero:
```json
{"error": {"code": "curvature_out_of_travel",
  "message": "rva on the PG[002] analyser is fixed at 0.8 m and cannot be commanded to 0.5 m."}}
```

*`curvature_modes`* (`GET /parameters` / `GET /state`) is **read-only derived
state** — one of `"autofocus"`, `"held"`, `"scanned"` per axis, keyed by the
four requested-radius IDs. Writing it is
refused outright, before any of the checks above run:
```json
{"error": {"code": "invalid_parameters", "message": "One or more fields failed",
  "details": {"errors": {"curvature_modes": "read-only field"}}}}
```
It derives from what you sent, never from a separate setting: an axis you
did not name and no scan command names is AUTOFOCUS; an axis you named a
radius for (and no scan command names) is HELD; an axis a scan command's
first token names is SCANNED regardless of anything else, because
`compute_scan_snapshot` drives it point by point. An **AUTOFOCUS** axis with
no established focusing model for the mounted crystal (IN12's Heusler
analyzer: `rva` is driven, but its focusing law is unpublished) cannot be
answered and is refused —
```json
{"error": {"code": "invalid_curvature",
  "message": "heusler111 declares rva focusing_known=False: no established focusing model to compute an ideal radius from."}}
```
— *unless* the request names `rva` explicitly (HELD) or scans it (SCANNED):
neither asks the missing optics model for an answer, so both are accepted.

*`result.applied_curvature`* is the per-point record of what each point
**actually** ran with — not what the scan launched with. Curvature stopped
being constant across a whole scan once autofocus started tracking the
measurement (a fixed-`Kf` scan can sweep `mono_horizontal_radius_m` from e.g. 11.6 m to 15.5 m
point to point), so `result.metadata`'s four requested-radius IDs are only the
**launch reference the scan started from** — the number the request patched
or the launch-time ideal — never what any individual point ran with. Shape:
a flat list, index-parallel with `counts` (row-major for a 2D scan: index
`iy * len(scan_values_1) + ix`, matching how `counts_grid` is addressed as
`counts_grid[iy][ix]`), one `{"applied_mono_horizontal_radius_m": ..., "applied_mono_vertical_radius_m": ..., "applied_analyzer_horizontal_radius_m": ..., "applied_analyzer_vertical_radius_m": ...}`
dict per point, **SIGNED** — the same convention the McStas per-point files
and `set_crystal_bending` use. `None` at an index means that point was
skipped or never measured, exactly like `counts`/`counts_grid` — never a
flat `0.0` standing in for "not run". The sign is derived from **the point's
own actual take-off angle** (the sign of sin A1, with A1 = A2/2, for the
monochromator radii; the sign of sin A5, with A5 = A6/2, for the analyzer radii) — never from the instrument's declared
scattering sense, because a direct-angle scan can legitimately put a crystal
on the opposite kinematic branch (PANDA's declared `A6` range spans both
signs), where the wrong sign would cost the resolution model roughly seven
orders of magnitude. Worked example (PUMA, `Kf`-fixed 14.7 meV, H=1 K=0 L=0,
`"scan_command1": "deltaE -3 6 3"`, 4 points; exact values from
`tests/test_applied_curvature.py`'s
`test_deterministic_engine_applied_curvature_tracks_each_point`): the mono horizontal radius
differs at every point (the mono take-off tracks the sweeping `Ki` as
`deltaE` moves) while the analyzer radii stay constant (`Kf`, and so the
analyzer take-off, never moves; the vertical one sits at PUMA's fixed 0.8 m) —
```json
"applied_curvature": [
  {"applied_mono_horizontal_radius_m": 11.622126892276503, "applied_mono_vertical_radius_m": 1.8048675766859756, "applied_analyzer_horizontal_radius_m": 2.303415039562502, "applied_analyzer_vertical_radius_m": 0.8},
  {"applied_mono_horizontal_radius_m": 13.027208057840836, "applied_mono_vertical_radius_m": 1.6101992005397268, "applied_analyzer_horizontal_radius_m": 2.303415039562502, "applied_analyzer_vertical_radius_m": 0.8},
  {"applied_mono_horizontal_radius_m": 14.294840540011975, "applied_mono_vertical_radius_m": 1.4674105626632215, "applied_analyzer_horizontal_radius_m": 2.303415039562502, "applied_analyzer_vertical_radius_m": 0.8},
  {"applied_mono_horizontal_radius_m": 15.458873902922761, "applied_mono_vertical_radius_m": 1.3569164307649897, "applied_analyzer_horizontal_radius_m": 2.303415039562502, "applied_analyzer_vertical_radius_m": 0.8}
]
```
(all positive here because this scan never crosses to the opposite take-off
branch; `result.metadata["mono_horizontal_radius_m"]` for this same launch is the single launch
reference value, unaffected by any of the four points above.)

*Copying a returned result back as the next request's parameters is **not**
an exact replay.* Three reasons: (1) `result.metadata`'s radii are the
launch reference, not any one point's actual radii — there is no single
number in a multi-point AUTOFOCUS/SCANNED scan that reproduces the whole
run; (2) `curvature_modes` cannot be written, so a captured SCANNED/AUTOFOCUS
state cannot be restored directly — naming an explicit radius from
`applied_curvature` instead re-HOLDS that axis, which is a different mode
than the original run had; (3) an AUTOFOCUS axis recomputes its ideal radius
from the instrument's current optics at submission time, so the same request
replayed after a descriptor or module-state change (a different NMO
selection, an updated crystal declaration) legitimately produces a different
number, not a bug.

**Background block in `result.metadata`.** Every finished scan — from either
engine, and **even when no background was planted** — carries a `background`
object stamped by the one shared helper, so background provenance never depends
on which engine ran:

| Key | Meaning |
|-----|---------|
| `background_schema` | Wire identity of the contract (`"tavi.background/2"`). |
| `catalog_version` | Catalog definition used to resolve the source ids and numerics. |
| `enabled` | Global background switch. All normalized source settings remain present when false. |
| `delivery_source` | `"config_default"` or `"per_scan_override"`. |
| `sources` | Complete mapping of source id to category, label, description, scale meaning, shape, base numerics, units, enable, and scale. `GET /schema` advertises the same catalog definitions independently of scan state. |
| `profile_fingerprint` | Identity of the catalog, global enable, and every normalized remembered source setting. |
| `effective_fingerprint` | Identity of only the catalog physics that can plant counts. Use this as the pooling key. |
| `background_seed` | Base seed used to derive dedicated background streams. Present on McStas scans when an active mean or event source has positive exposure, and on deterministic scans when an active cosmic-event source has positive exposure. Equal to the body `seed` when one was given, else a stable hash of the job id. |

On the deterministic engine the background mean is added to the signal mean
before the Poisson draw, and `noiseless: true` returns the exact means
*including* background. On the McStas engine the background is an additive
Poisson overlay drawn on top of the ray-traced counts, always drawn
(`noiseless` is a deterministic-engine concept). McStas intensity columns are
independent of counts and are left untouched.

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
   {"ts": "2026-07-03T14:05:01", "kind": "parameter", "text": "api: set h, scan_command1"},
   {"ts": "2026-07-03T14:05:01", "kind": "job", "text": "j-0004: queued (source: api)"},
   {"ts": "2026-07-03T14:05:02", "kind": "job", "text": "j-0004: started"},
   {"ts": "2026-07-03T14:05:44", "kind": "job",
    "text": "j-0004: h scan 1.990 to 2.010, 5 pts, max 31 counts at h=2.000"}],
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
| 400 | `bad_request` | Malformed JSON body, non-object body, a PATCH field whose value is not a scalar/object, or an unknown query key on `GET /resolution`. |
| 400 | `api_version_required` | A `PATCH /parameters`, `POST /scan`, `POST /validate` or `PUT /background` body had no `"api_version": 2` (or another value). Nothing was applied, queued or replaced. `details.required_api_version` is `2`; see §15. |
| 400 | `invalid_parameters` | A `PATCH /parameters` (or inline `parameters` on `POST /scan`) named an unknown, retired, derived-only, read-only, absent or duplicate key (the whole request is refused, `applied` is empty), or had a bad value (that field is skipped). `details` lists `applied` and `errors`, keyed by the names you sent. |
| 400 | `scan_validation` | `POST /scan` scan command(s) failed validation (unknown variable, conflict, zero or wrong-sign step, step larger than range). `"force": true` overrides only the soft warnings; hard rejections stand. |
| 400 | `invalid_background` | A background configuration (`PUT /background`, or the `background` field of `POST /scan` / `POST /validate`) failed to resolve — for example a missing/mismatched `catalog_version`, unknown source id or nested field, non-boolean enable, or invalid scale. On `PUT` the stored configuration is untouched; on `POST /scan` `details.background` is the validation background block. Unknown top-level fields are `bad_request`. |
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

Every quantity is named by its **canonical ID**, which is what `GET`, the
job snapshot, `result.metadata`, the SSE events and the saved scan files
emit. The *Aliases* column lists the other spellings a **request** accepts, in
any letter case (an alias never appears in a reply). An alias is not a
convenience that may change meaning later: `A2` is the monochromator 2θ, `A4`
the sample 2θ and `A6` the analyzer 2θ (§15). `A1` and `A5` are derived Bragg
angles and are not fields.

A PUMA `GET /state` returns 50 parameter keys (`GET /parameters` the same 49
without `lock_stale`); 46 are writable via `PATCH /parameters`. IN8 and IN12
have 49 keys and 45 writable, PANDA 51 and 47: the difference is the slit gaps,
which are the active instrument's own. `curvature_modes`, `mount_plane_u`,
`mount_plane_v` and `lock_stale` are read-only. In the text below, short names
such as `sgl` and `sgu` stand for their canonical IDs (`sample_lower_arc_deg`,
`sample_upper_arc_deg`).
Many fields are **linked**: writing one triggers the same recompute the GUI does when a
user presses Enter, so dependent fields update automatically.

| Canonical ID | Aliases (input only) | Type | Units | Meaning / linked recompute |
|---|---|---|---|---|
| `orientation_mode` | — | string | — | `"free"` (the arcs are solved per Q) or `"locked"` (a scattering plane is locked: the arcs stay put and every Q is solved at the locked tilts; a Q out of the plane is refused naming the plane and the angle). Writing `"locked"` locks `lock_plane` from the same request, or the default plane (the mounting plane, else the first two UB peaks, else (1 0 0)/(0 1 0)), where the current UB levels it; a plane the arcs cannot level within travel is refused with the reason. Writing `"free"` releases. While locked, a write of `sgl` or `sgu` is refused, in `PATCH` and in a scan's `parameters` alike (`400`, naming the lock: release first), and a scan starts from the locked arcs; a request combining `orientation_mode` or `lock_plane` with `sgl` or `sgu` is refused whichever way it switches (send two). A lock request (`orientation_mode: "locked"` or `lock_plane`) must stand alone: with any other field (a lattice parameter, say, which would change the UB the lock is computed from) it is a `400` and nothing applies; send two PATCHes instead. Releasing (`"free"`) may carry other fields, except `sgl` and `sgu`; a refused release applies none of them. Not settable in a scan's `parameters`: a scan runs in the session's mode. See the User Guide's *Lock plane*. |
| `lock_plane` | — | object or null | r.l.u. | The locked plane's two vectors, `{"u": [h, k, l], "v": [h, k, l]}`; `null` when free. Writing it alone locks that plane (as `orientation_mode: "locked"` with it); while a different plane is locked it is refused (release first). |
| `lock_stale` | — | boolean or null | — | **Read-only, in `GET /state` only** (not `GET /parameters`, not a scan result's `parameters`). `true` when the current UB (U and lattice fields) no longer levels the locked plane at the locked tilts within 0.05°; `null` when free. The UB dock's STALE mark reads the same function. |
| `mono_two_theta_deg` | `A2`, `mtt` | number | degrees | Monochromator scattering angle 2θ (ILL **A2**, NICOS `mtt`). Recomputes energies/Q. Signed by the instrument's mono sense (`docs/INSTRUMENT_LAYOUT.md`, *Main Rotation Angles*). |
| `sample_rotation_deg` | `A3`, `sth`, `omega`, `psi` | number | degrees | Sample rotation about the vertical axis, the turntable (ILL **A3**, NICOS `sth`); not a Bragg angle. `omega` and `psi` name this one field. |
| `sample_two_theta_deg` | `A4`, `stt`, `2theta` | number | degrees | Sample scattering angle 2θ (ILL **A4**, NICOS `stt`). Signed by the instrument's sample sense. |
| `analyzer_two_theta_deg` | `A6`, `att` | number | degrees | Analyzer scattering angle 2θ (ILL **A6**, NICOS `att`). Signed by the instrument's analyzer sense. |
| `sample_lower_arc_deg` | `sgl` | number | degrees | Lower sample tilt arc readout: turns about the horizontal axis perpendicular to the beam at A3 = 0 (stage x), riding on the turntable. Solved from Q/HKL; set it for angle-mode scans. Writing it reads Q back through both arcs. A value outside the arc's travel (PUMA and IN12 ±20°, PANDA ±15°) returns `400 invalid_parameters` naming the arc, the angle and its travel, the words an angle-mode point past travel is refused with. A non-finite value (`inf`, `nan`) returns the same 400 on every instrument (`sgl must be a finite angle, not inf`). |
| `sample_upper_arc_deg` | `sgu` | number | degrees | Upper sample tilt arc readout: turns about the beam axis at A3 = 0 (stage z), riding on `sgl`. Same rules as `sgl`. |
| `incident_wavevector_inv_angstrom` | `Ki` | number | Å⁻¹ | Incident wavevector. Linked with `incident_energy_mev`. |
| `incident_energy_mev` | `Ei` | number | meV | Incident energy. Linked with `incident_wavevector_inv_angstrom`. |
| `final_wavevector_inv_angstrom` | `Kf` | number | Å⁻¹ | Final wavevector. Linked with `final_energy_mev`. |
| `final_energy_mev` | `Ef` | number | meV | Final energy. Linked with `final_wavevector_inv_angstrom`. |
| `K_fixed` | — | string | — | Energy mode. Exactly `"Ki Fixed"` or `"Kf Fixed"`. |
| `fixed_E` | — | number | meV | The fixed energy value used by the current `K_fixed` mode. |
| `q_instrument_x_inv_angstrom` | `qx` | number | Å⁻¹ | Q component in the public instrument frame (x and y horizontal, z vertical). Linked: `h`/`k`/`l` → the three `q_instrument_*` fields via UB. |
| `q_instrument_y_inv_angstrom` | `qy` | number | Å⁻¹ | Q component, public instrument frame (y horizontal). |
| `q_instrument_z_inv_angstrom` | `qz` | number | Å⁻¹ | Q component, public instrument frame (z vertical). |
| `h` | `H` | number | r.l.u. | Miller index h. Linked: `h`/`k`/`l` → the three `q_instrument_*` fields via UB matrix. |
| `k` | `K` | number | r.l.u. | Miller index k. |
| `l` | `L` | number | r.l.u. | Miller index l. |
| `energy_transfer_mev` | `deltaE` | number | meV | Energy transfer, positive = neutron energy loss. Recomputes angles/energies. |
| `lattice_a_angstrom` | `a` | number | Å | Lattice constant a. Recomputes UB → Q/HKL. |
| `lattice_b_angstrom` | `b` | number | Å | Lattice constant b. |
| `lattice_c_angstrom` | `c` | number | Å | Lattice constant c. |
| `lattice_alpha_deg` | `alpha` | number | degrees | Lattice angle α. |
| `lattice_beta_deg` | `beta` | number | degrees | Lattice angle β. |
| `lattice_gamma_deg` | `gamma` | number | degrees | Lattice angle γ. |
| `sample` | — | string | — | Sample id from the shared sample library; the allowed values are the `sample` field's `allowed` list in `GET /schema`. Writable. |
| `mount_plane_u` | — | array or null | r.l.u. | **Read-only.** The (h k l) the sample is mounted with along the mount x axis, as described in the Sample dock's optional mounting plane; `null` when the mount is not from a plane (the standard setting, or after a sample change cleared the description). A write returns `400 invalid_parameters` with `"read-only field"`. |
| `mount_plane_v` | — | array or null | r.l.u. | **Read-only.** The (h k l) described in the horizontal plane with `mount_plane_u`; `null` with it. |
| `monocris` | — | string | — | Monochromator crystal id. PUMA: `"pg002"` or `"pg002_test"`. |
| `anacris` | — | string | — | Analyzer crystal id. PUMA: `"pg002"`. |
| `mono_horizontal_radius_m` | `rhm` | number | m | Monochromator horizontal bending radius, magnitude. `0` = flat. See §5 *Crystal curvature* below. |
| `mono_vertical_radius_m` | `rvm` | number | m | Monochromator vertical bending radius, magnitude. `0` = flat. |
| `analyzer_horizontal_radius_m` | `rha` | number | m | Analyzer horizontal bending radius, magnitude. `0` = flat. |
| `analyzer_vertical_radius_m` | `rva` | number | m | Analyzer vertical bending radius, magnitude. `0` = flat. |
| `curvature_modes` | — | object | — | **Read-only.** `{"mono_horizontal_radius_m"/"mono_vertical_radius_m"/"analyzer_horizontal_radius_m"/"analyzer_vertical_radius_m": "autofocus"\|"held"\|"scanned"}`. Derived, never writable — see §5 *Crystal curvature*. |
| `source_type` | — | string | — | Source model id. PUMA: `"Maxwellian"` or `"Mono"`. |
| `source_dE` | — | number | meV | Source energy spread (only meaningful for the `"Mono"` source). |
| `modules` | — | object | — | Experimental modules. See below. |
| `collimation` | — | object | — | Collimator selections. See below. |
| `slit.<stable_id>.horizontal_gap_mm` | `<stable_id>_hgap` | number | mm | Horizontal gap of one slit of the **active instrument**, full width in millimetres. One key per gap; see *Slit gaps* below for the IDs. |
| `slit.<stable_id>.vertical_gap_mm` | `<stable_id>_vgap` | number | mm | Vertical gap of a slit that has one (a pre-sample or sample-exit slit); same rules. |
| `number_neutrons` | — | integer | count | Neutrons simulated per point. Positive integer; also accepts a numeric string like `"1e8"`. |
| `scan_command1` | — | string | — | First scan command (§7). Empty string = no scan on this axis. |
| `scan_command2` | — | string | — | Second scan command (§7). Both set = 2D scan. |
| `diagnostic_mode` | — | boolean | — | Enable per-point diagnostic capture. |

**Slit gaps.** `slit.<stable_id>.horizontal_gap_mm` (and `.vertical_gap_mm`
where the slit has a height) replace the old `slits_mm` object: one key per gap,
always in millimetres, and only the active instrument's own appear in `GET`,
`/schema` and `result.metadata`. Naming a slit the instrument lacks is refused.

| Instrument | `<stable_id>` with horizontal gap | also a vertical gap |
|---|---|---|
| PUMA | `post_mono`, `pre_sample`, `detector` | `pre_sample` |
| IN8, IN12 | `pre_sample`, `detector` | `pre_sample` |
| PANDA | `virtual_source`, `pre_sample`, `sample_exit` | `pre_sample`, `sample_exit` |

A slit gap is a settable parameter, not a scan variable: a scan command naming
one is refused with `slit scans arrive with the point plan`.

**Retired and refused names.** These are refused as request keys (`400
invalid_parameters`, the whole request, nothing applied) with a message that
says what to send instead: `chi`, `phi` and `kappa` (TAVI has no such axes; its
sample tilt arcs are `sgl` and `sgu`); `slits_mm` and the old metre-valued slit
names (`vbl_hgap`, `pbl_hgap`, `pbl_vgap`, `dbl_hgap`, `sbl_wgap`, `sbl_hgap`,
`ms1_wgap`, `ss1_wgap`, `ss1_hgap`, `ss2_wgap`, `ss2_hgap`); the unit-less
`lattice_a` ... `lattice_gamma` (use `lattice_a_angstrom` ...
`lattice_gamma_deg`); the derived `A1`, `mono_theta_deg`, `A5`,
`analyzer_theta_deg` (set A2 or A6) and the four `applied_*_radius_m` (derived
by the take-off branch). `psi` is **no longer retired**: the old ψ correction is
gone, and the name is now just another alias of `sample_rotation_deg`, the
turntable itself. The corrections no longer exist as quantities, and none of
these names appears in `/schema` or in the parameter dict.

**Dict-valued fields** — when writing these, send an object keyed by slot id.
Missing keys fall back to instrument defaults.

- `modules` — `{module_id: value}`. On PUMA: `nmo` takes a string from
  `"None" | "Vertical" | "Horizontal" | "Both"`; `v_selector` takes a boolean.
  Example: `{"modules": {"nmo": "None", "v_selector": false}}`.
- `collimation` — `{slot_id: selection}`. On PUMA the slots are `alpha_1`,
  `alpha_2`, `alpha_3`, `alpha_4`. Single-select slots take a string (e.g.
  `"40"`); the multi-select slot (`alpha_2`) takes a list of strings (e.g.
  `["30", "40"]`). Example: `{"collimation": {"alpha_1": "40", "alpha_2": ["40"], "alpha_3": "30", "alpha_4": "30"}}`.
  `"0"` means an open position (no collimator installed); the GUI shows it as
  Open. Values sent and returned are unchanged.
- Slit gaps are not dict-valued: each is its own key (see *Slit gaps*). Example:
  `{"slit.post_mono.horizontal_gap_mm": 88, "slit.pre_sample.vertical_gap_mm": 100}`.
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

- A **step larger than the range** (e.g. `"H 1.99 2.01 0.1"`), a **zero step**, or a
  step whose **sign does not match** the direction from start to end is a hard
  refusal (`400 scan_validation`); `"force": true` does not pass it. A step that
  does not divide the range runs to the point nearest the end, which can lie up to
  half a step past it (`"A3 0 10 4"` runs 0, 4, 8, 12).
- **1D scan:** set `scan_command1`, leave `scan_command2` empty (`""`).
- **2D scan:** set **both** commands. The point count is the product of the two
  (a 3-point × 4-point scan runs 12 points). The 2D result uses `counts_grid`.
- **Single point:** leave both commands empty. The scan runs one point at the
  current parameter values.

**Scannable variable names** (case-insensitive; a canonical ID or any alias
works, and the name is resolved to the canonical ID on submit):

| Canonical ID | Aliases | Scans over |
|---|---|---|
| `h` `k` `l` | `H` `K` `L` | Miller indices (reciprocal-lattice units) |
| `q_instrument_x_inv_angstrom` `q_instrument_y_inv_angstrom` `q_instrument_z_inv_angstrom` | `qx` `qy` `qz` | Q components (public instrument frame, z vertical) |
| `energy_transfer_mev` | `deltaE` | energy transfer (meV) |
| `mono_two_theta_deg` | `A2` `mtt` | monochromator 2θ (angle mode) |
| `sample_rotation_deg` | `A3` `sth` `omega` `psi` | the sample rotation, the turntable itself (angle mode; `omega 35 36 1` turns it to 35° and 36°) |
| `sample_two_theta_deg` | `A4` `stt` `2theta` | sample 2θ (angle mode) |
| `analyzer_two_theta_deg` | `A6` `att` | analyzer 2θ (angle mode) |
| `sample_lower_arc_deg` `sample_upper_arc_deg` | `sgl` `sgu` | the goniometer arcs, in angle mode only (with the angles above or alone). Beside a Q, HKL or `deltaE` command they are refused: a Q/HKL scan solves the arcs at every point. |
| `mono_horizontal_radius_m` `mono_vertical_radius_m` `analyzer_horizontal_radius_m` `analyzer_vertical_radius_m` | `rhm` `rvm` `rha` `rva` | crystal bending radii |
| *refused* | `A1` `A5` (`mono_theta_deg`, `analyzer_theta_deg`) | derived Bragg angles: the error says `independent crystal rocking is not modelled yet; scan A2 (mono 2θ)` (or A6) |
| *refused* | `chi` `phi` `kappa` | TAVI has no such axes; the error names the arcs `sgl`/`sgu` where that is the answer |
| *refused* | `slit.<stable_id>.<axis>_gap_mm` | `slit scans arrive with the point plan` |
| *refused* | `Ei` `Ki` `Ef` `Kf`, `a` ... `gamma`, `applied_*_radius_m` | settable or derived, but not scannable |

An unknown name is refused with the list of valid ones. Whatever spelling a
command uses, replies name the canonical ID: `per_command[].variable`,
`result.variable_1` / `variable_2`, the keys of `skipped_points[].values` and of
`validation.infeasible[].values`, and the SSE events. `launch.scan_command1` /
`scan_command2` echo the command text exactly as you sent it.

The grammar did not change. The numbering did: **`A2` is the monochromator 2θ,
`A4` the sample 2θ and `A6` the analyzer 2θ** (before API version 2, `A2` was
the sample 2θ and `A4` the analyzer 2θ: §15). Two commands on one quantity
(`A4` with `stt`, `A3` with `omega`, `A2` with `mtt`), and an angle beside a Q,
HKL or `deltaE` command, are refused; `force` clears neither.

Examples:
```json
{"scan_command1": "H 1.9 2.1 0.01"}                       // 21-point 1D scan over H
{"scan_command1": "deltaE 0 10 0.5"}                       // energy scan, 0..10 meV
{"scan_command1": "H 1.9 2.1 0.02", "scan_command2": "deltaE 0 8 1"}  // 2D H–E map
{"scan_command1": "A3 34 36 0.5"}                           // turn the sample: sample_rotation_deg
{"scan_command1": "A4 -75 -65 2.5"}                         // sample 2θ (the old A2)
{"scan_command1": "A2 40 44 1", "scan_command2": "A6 40 44 1"}  // mono 2θ × analyzer 2θ map
{"scan_command1": "", "scan_command2": ""}                 // single point at current settings
```
The angle examples are angle-mode scans: they move the named axes and hold the
rest, so the scattering triangle is whatever those angles make it.

---

## 8. Live streaming (SSE)

`GET /events` opens a long-lived `text/event-stream`. Each event is
`event: <name>` followed by `data: <json>`. Keepalive comments (`: keepalive`)
arrive about every 15 seconds. At most **8** SSE clients may connect at once;
beyond that `GET /events` returns `503 too_many_clients`.

```bash
curl -N http://127.0.0.1:8642/api/v1/events
```

Every event payload also carries `"api_version": 2` (left out of the examples
below). A typical 3-point 1D scan produces this sequence (auth header omitted; add
`-H "Authorization: Bearer <token>"` if a token is set):

```
: connected

event: job_queued
data: {"job_id": "j-0001", "source": "api", "position": 0}

event: job_started
data: {"job_id": "j-0001", "source": "api"}

event: scan_initialized
data: {"job_id": "j-0001", "mode": "1D", "variable_1": "h", "variable_2": null,
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
| `parameters_changed` | `fields` (list of applied canonical field IDs), `source` (`api`). Emitted on every successful write. |
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
- **The radii (`rhm`/`rvm`/`rha`/`rva`, canonically `mono_horizontal_radius_m` ...)
  are magnitudes going in, signed coming out.** A
  value you send is a bending-radius magnitude in metres (`0` = flat); the
  per-point radii in `result.applied_curvature` (`applied_mono_horizontal_radius_m` ...)
  are signed by the point's
  actual take-off branch. Copying a signed `applied_curvature` value into the
  matching requested-radius field is fine numerically (inputs take `abs()`) but also **HOLDS** that
  axis — not the same mode the original point ran in. See §5 *Crystal
  curvature*.
- **A scan through a zero two-theta runs under McStas, not just at the exact
  point.** Only the exact zero is marked direct transmission (§5 *Direct
  transmission*); its neighbours keep their honest Bragg inversion, which
  diverges near zero take-off — PG(002) at 1° two-theta records an `Ef` of
  roughly 24 eV. No threshold or ceiling is applied to that neighbourhood.
  The instrument's declared axis limits still apply and are a different
  refusal: IN8's A2 (mono 2θ) runs 11°–90°, so an A2 = 0 point there is
  `physical_infeasible` (out of range) for every engine, exactly as on the
  real instrument -- direct transmission is only reachable where a limit
  allows it (A6, the analyzer 2θ, on IN8, for example).

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
elastic Bragg peak near **H = 2** and inspecting where the intensity peaks. A
scan is always built from defaults + your patch, so it never disturbs the
operator's live setup (the `isolated` flag below is an accepted no-op).

Set the elastic condition and center, then dry-run the tight scan:
```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "incident_energy_mev": 14.7, "energy_transfer_mev": 0,
       "h": 2.0, "k": 0.0, "l": 0.0}'
# -> {"applied": ["incident_energy_mev", "h", "k", "l", "energy_transfer_mev"], "errors": {}}

curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.98 2.02 0.005", "number_neutrons": 200000}}'
```
```json
{"points": 9, "per_command": [{"variable": "h", "count": 9,
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
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.98 2.02 0.005", "number_neutrons": 200000}, "isolated": true}'
# -> 202 {"job_id": "j-0007", "state": "queued", "position": 0, "isolated": true,
#         "eta": {"estimated_seconds": 96.0, "confidence": "high", "samples": 12},
#         "validation": {"points": 9, "infeasible": [], ...}}

curl "http://127.0.0.1:8642/api/v1/scan/j-0007?wait=120"
```
```json
{"job_id": "j-0007", "state": "done", "isolated": true,
 "progress": {"done": 9, "total": 9}, "timed_out": false,
 "result": {"mode": "1D", "variable_1": "h", "total_counts": 5120.0, "max_counts": 2010.0}}
```
```bash
curl http://127.0.0.1:8642/api/v1/scan/j-0007/data
```
```json
{"job_id": "j-0007", "state": "done",
 "result": {"variable_1": "h", "scan_values_1": [1.98, 1.985, 1.99, 1.995, 2.0,
   2.005, 2.01, 2.015, 2.02],
   "counts": [95.0, 210.0, 640.0, 1480.0, 2010.0, 1500.0, 690.0, 205.0, 90.0]}}
```
**Gotchas.**
- **TAVI does not fit peaks.** The `counts` array peaks at `H = 2.0` here, but
  finding the center (centroid, Gaussian fit, whatever) is the *client's* job —
  no endpoint returns a fitted peak position.
- The operator's live `scan_command1` and `number_neutrons` widgets are untouched
  after the run — the scan's launch state is built from defaults + the request
  patch and never reads or writes GUI widgets.

### 13.2 elastic-h-scan

**Goal.** A plain elastic (ΔE = 0) line scan across the (2 0 0) Bragg position
at a sensible production neutron count, reading the `validation` block echoed in
the 202 to confirm the point list before the scan runs.

```bash
curl -X PATCH http://127.0.0.1:8642/api/v1/parameters \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "incident_energy_mev": 14.7, "energy_transfer_mev": 0,
       "k": 0.0, "l": 0.0,
       "scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 1000000}'
# -> {"applied": ["incident_energy_mev", "k", "l", "energy_transfer_mev", "scan_command1", "number_neutrons"], "errors": {}}

curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{"api_version": 2}'
```
```json
{"job_id": "j-0008", "state": "queued", "position": 0,
 "eta": {"estimated_seconds": 470.0, "confidence": "high", "samples": 12},
 "validation": {"points": 11, "per_command": [{"variable": "h", "count": 11,
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
- `energy_transfer_mev: 0` is what makes this *elastic*; omit it and you inherit whatever
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
  -d '{"api_version": 2, "incident_energy_mev": 14.7, "h": 2.0, "k": 0.0, "l": 0.0,
       "scan_command1": "deltaE 0 20 2", "number_neutrons": 1000000}'

curl -X POST http://127.0.0.1:8642/api/v1/validate \
  -H "Content-Type: application/json" -d '{"api_version": 2}'
```
```json
{"points": 11, "per_command": [{"variable": "energy_transfer_mev", "count": 11,
  "values": [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]}],
 "cost": {"points": 11, "neutrons_per_point": 1000000.0, "job_neutrons": 11000000.0, "...": "..."},
 "eta": {"estimated_seconds": 480.0, "confidence": "medium", "samples": 5},
 "infeasible": [
   {"index": 9, "values": {"energy_transfer_mev": 18}, "reason": "scattering triangle does not close"},
   {"index": 10, "values": {"energy_transfer_mev": 20}, "reason": "scattering triangle does not close"}],
 "would_queue": false,
 "blockers": ["infeasible_points: 2 point(s) unreachable"]}
```
A plain `POST /scan` with this body would return `400 infeasible_points`. You
have two choices: shorten the scan (e.g. `"deltaE 0 16 2"`), or keep the range
and skip the two unreachable points with `allow_partial`:
```bash
curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" -d '{"api_version": 2, "allow_partial": true}'
# -> 202 {"job_id": "j-0009", "state": "queued", "position": 0,
#         "validation": {"points": 11, "infeasible": [ ...index 9,10... ]}}

curl http://127.0.0.1:8642/api/v1/scan/j-0009/data
```
```json
{"job_id": "j-0009", "state": "done",
 "result": {"variable_1": "energy_transfer_mev",
   "scan_values_1": [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
   "counts": [1820.0, 640.0, 210.0, 95.0, 60.0, 44.0, 30.0, 22.0, 15.0, null, null],
   "skipped_points": [
     {"index": 9, "values": {"energy_transfer_mev": 18}, "reason": "scattering triangle does not close"},
     {"index": 10, "values": {"energy_transfer_mev": 20}, "reason": "scattering triangle does not close"}]}}
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
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 50000}}'
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
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 5000000}}'
# -> {"points": 11, "eta": {"estimated_seconds": 2350.0, "confidence": "medium", "samples": 3},
#     "would_queue": true, "blockers": []}

curl -X POST http://127.0.0.1:8642/api/v1/scan \
  -H "Content-Type: application/json" \
  -d '{"api_version": 2, "parameters": {"scan_command1": "H 1.9 2.1 0.02", "number_neutrons": 5000000}}'
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
    "text": "j-0010: h scan 1.900 to 2.100, 11 pts, max 44 counts at h=2.000"},
   {"ts": "2026-07-03T15:21:10", "kind": "job", "text": "j-0011: queued (source: api)"},
   {"ts": "2026-07-03T15:58:00", "kind": "job",
    "text": "j-0011: h scan 1.900 to 2.100, 11 pts, max 4380 counts at h=2.000"}],
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
- `docs/ANALYTIC_ENGINE.md` — deterministic model behavior, calibration,
  provenance, and limitations.
- `components/PHONON_DFT.md` — the custom component and shared dispersion-file
  contract.
- `docs/INSTRUMENT_LAYOUT.md` — TAS/PUMA geometry, the angle table (ILL A1–A6) and the conventions behind every sign and frame, and scan modes.
- `docs/MCSTAS_PARAMETERS.md` — which parameters are build-time vs run-time.
- `User_Guide.md` — the interactive GUI workflow.

---

## 15. Breaking change: API version 2

API version 2 is a deliberate break, made once so the angle numbers mean what
they mean at every neutron facility. Nothing is converted and nothing is
guessed: an old client is **refused**, never reinterpreted.

### What changed

1. **ILL angle numbering, A1–A6.** The angles are numbered in beam order, with
   each crystal's θ and 2θ as a pair: A1 monochromator θ (derived), **A2
   monochromator 2θ**, A3 sample rotation, **A4 sample 2θ**, A5 analyzer θ
   (derived), **A6 analyzer 2θ**. The angle table, with signs and zeros, is in
   `docs/INSTRUMENT_LAYOUT.md`.
2. **Canonical IDs.** Every quantity has one canonical ID (`mono_two_theta_deg`,
   `h`, `incident_energy_mev` ...) with its unit in the name. Requests accept
   the registry's aliases; replies, saved files and output files use the
   canonical ID only. The IDs are the first column of §6.
3. **`api_version: 2` is required** in the body of every `PATCH /parameters`,
   `POST /scan`, `POST /validate` and `PUT /background`. Without it, or with any
   other value, the answer is `400 api_version_required` and nothing happens.
   `GET` routes and the two stop routes take no body version.
4. **Key-level refusals.** A request that names a retired, derived-only,
   read-only, unknown or absent-slit key, or one quantity twice, is refused
   whole (`400 invalid_parameters`, nothing applied); a bad *value* is still
   reported per field. `GET /resolution` refuses query keys it does not know.
5. **Slit gaps** are one key each, `slit.<stable_id>.horizontal_gap_mm` /
   `.vertical_gap_mm`, replacing the `slits_mm` object.
6. **Saved state version 5.** `config/parameters.json` blocks carry the canonical
   IDs and `_schema` 5. A file of any other version is refused whole: at
   start-up it is set aside as `parameters.json.bak` (`.bak2` ...) and defaults
   load, with one message in the message centre; *File > Load Parameters* of such
   a file changes nothing.
7. **Versioned outputs.** Every `scan_parameters.txt` (the scan's and each
   point's) now starts with the line `api_version: 2` and is keyed by canonical
   IDs; the axis label of `1D_scan_data.txt` / `2D_scan_data.txt` is the
   canonical ID. A scan folder written before the break (no `api_version`
   line, or another value) is refused when loaded, with a message naming the
   folder; the folder itself is never modified.
8. **`psi`** is no longer a retired name: it is an alias of
   `sample_rotation_deg`, the turntable. The ψ and κ corrections stay gone.

### Old to new: the angles

The numbers moved. Renaming an `A2` or `A4` in place **changes the axis you
control**, so map by meaning, never by number:

| Old TAVI number | What it was | Old keys and aliases | New ILL number | Canonical ID |
|---|---|---|---|---|
| A1 | monochromator 2θ | `mtt` | **A2** | `mono_two_theta_deg` |
| A2 | sample 2θ | `stt`, `2theta` | **A4** | `sample_two_theta_deg` |
| A3 | sample rotation | `omega` | A3 (unchanged) | `sample_rotation_deg` |
| A4 | analyzer 2θ | `att` | **A6** | `analyzer_two_theta_deg` |
| (none) | lower sample arc | `sgl` | (no ILL number) | `sample_lower_arc_deg` |
| (none) | upper sample arc | `sgu` | (no ILL number) | `sample_upper_arc_deg` |
| (none) | monochromator θ | (not a field) | A1, derived | `mono_theta_deg` |
| (none) | analyzer θ | (not a field) | A5, derived | `analyzer_theta_deg` |

The NICOS-style names (`mtt`, `stt`, `att`, `omega`, `sgl`, `sgu`) kept their
physical meaning and are still accepted, so they are the safe spelling for a
script that has to run on both sides of the break. A client that merely adds
`"api_version": 2` and keeps sending `"A2": 40` meaning the sample 2θ now
moves the monochromator: adding the version is the client saying it has
read this section.

### Old to new: everything else

| Old key | Canonical ID |
|---|---|
| `Ki`, `Ei`, `Kf`, `Ef` | `incident_wavevector_inv_angstrom`, `incident_energy_mev`, `final_wavevector_inv_angstrom`, `final_energy_mev` |
| `qx`, `qy`, `qz` | `q_instrument_x_inv_angstrom`, `q_instrument_y_inv_angstrom`, `q_instrument_z_inv_angstrom` |
| `H`, `K`, `L` | `h`, `k`, `l` |
| `deltaE` | `energy_transfer_mev` |
| `lattice_a`, `lattice_b`, `lattice_c` | `lattice_a_angstrom`, `lattice_b_angstrom`, `lattice_c_angstrom` |
| `lattice_alpha`, `lattice_beta`, `lattice_gamma` | `lattice_alpha_deg`, `lattice_beta_deg`, `lattice_gamma_deg` |
| `rhm`, `rvm`, `rha`, `rva` | `mono_horizontal_radius_m`, `mono_vertical_radius_m`, `analyzer_horizontal_radius_m`, `analyzer_vertical_radius_m` |
| `applied_curvature` entries `rhm` ... `rva` | `applied_mono_horizontal_radius_m` ... `applied_analyzer_vertical_radius_m` |
| `slits_mm`, PUMA `vbl_hgap` | `slit.post_mono.horizontal_gap_mm` |
| `slits_mm`, PUMA `pbl` `[w, h]` | `slit.pre_sample.horizontal_gap_mm`, `slit.pre_sample.vertical_gap_mm` |
| `slits_mm`, PUMA/IN8/IN12 `dbl_hgap` | `slit.detector.horizontal_gap_mm` |
| `slits_mm`, IN8/IN12 `sbl` `[w, h]` | `slit.pre_sample.horizontal_gap_mm`, `slit.pre_sample.vertical_gap_mm` |
| `slits_mm`, PANDA `ms1` | `slit.virtual_source.horizontal_gap_mm` |
| `slits_mm`, PANDA `ss1` `[w, h]` | `slit.pre_sample.horizontal_gap_mm`, `slit.pre_sample.vertical_gap_mm` |
| `slits_mm`, PANDA `ss2` `[w, h]` | `slit.sample_exit.horizontal_gap_mm`, `slit.sample_exit.vertical_gap_mm` |
| `chi`, `kappa`, `phi` | no equivalent; refused (the arcs are `sgl`, `sgu`) |

Values and units are unchanged (slit gaps stay in millimetres). Replies,
`result.metadata`, `launch.parameters` and the SSE events name only canonical
IDs, so a client that reads `state["parameters"]["mtt"]` must read
`state["parameters"]["mono_two_theta_deg"]` instead.

### What an old client sees

- A write or validate without `"api_version": 2`: `400 api_version_required`,
  with the message "This request needs "api_version": 2 ... Read the Breaking
  change section of the API guide". Nothing is applied, queued or replaced.
- A write that adds the version but names `chi`, `kappa`, `slits_mm`,
  `lattice_a` or another retired key: `400 invalid_parameters`, the whole request
  refused, the message naming the replacement.
- `GET /resolution` with a key it does not know (including a cache-buster):
  `400 bad_request`.
- A pre-break `parameters.json`: set aside as a backup, defaults load. A
  pre-break scan folder: refused on load, left untouched.

There is no converter and no compatibility mode, on purpose: a quiet
translation of `A2` would be exactly the silent change of axis the version
exists to prevent.
