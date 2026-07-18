# Control Features — Design Document

*Date: 2026-07-03*
*Status: **Draft**, updated 2026-07-06 — §5 (resolution ellipsoids: `tavi/resolution.py`, Cooper–Nathans and Popovici, `GET /resolution`) and §6 (deterministic engine: `tavi/deterministic_engine.py`, `POST /scan` with `engine: "deterministic"`) are now implemented and live. §1–4 (goto/path/campaigns), §7 (virtual clock), and §8 (point-list scans) remain proposed future work; where those sections reference new symbols (e.g. `tavi/scan_fits.py`, `POST /goto`, `CampaignRegistry`) they do not exist yet.*

> Companion documents: `docs/API_SERVER_DESIGN.md` (the live remote-API architecture this builds on), `docs/API_USER_GUIDE.md` (client-facing endpoint/field reference), `docs/PIPELINE_DESIGN.md` (per-point prep/run pipeline), `docs/INSTRUMENT_LAYOUT.md` (TAS geometry, angles, scan modes), `docs/MCSTAS_PARAMETERS.md` (build-time vs run-time parameter split).

---

## 0. Framing — what belongs in TAVI, and what does not

TAVI is an **instrument plus control system**, not a data analyst. This is the line every feature below is designed against:

- **Scan-derived motion is control-system territory and belongs in TAVI.** Every real triple-axis control system — SPEC/`spec` at older reactor sources, SPICE at HFIR, NICOS at FRM-II/MLZ — lets the operator run a scan and then *drive a motor to a value derived from that scan* (peak center, centre-of-mass, maximum). That is a control action ("go to the top of the peak"), not a scientific conclusion. TAVI simulates the same instrument those control systems drive, so it should offer the same control primitives.
- **Scientific interpretation is the client's job.** Dispersion fitting, background modelling, deciding whether a peak is "real", statistical advice on counting time — none of that lives in TAVI. It lives in the client: a human at the GUI, or a purpose-built LLM measurement driver talking to the API.
- **The payoff is transfer.** A driver (human or LLM) written against TAVI's control surface uses the *same verbs* it would use against a real PUMA/NICOS instrument: set parameters, scan a variable, go to the center, scan again. If TAVI stays honest about the control/analysis boundary, that driver moves to the real instrument unchanged. The moment TAVI starts making scientific decisions, the driver learns habits that do not transfer.

**Every feature in this document is designed for two surfaces at once:** a GUI control for the human operator and an API endpoint for the programmatic/LLM client. Neither is an afterthought. Where the two surfaces differ, both are specified.

### Primitives already available (from the API work landing now)

These are referenced throughout and are either live or actively being implemented (see `docs/API_SERVER_DESIGN.md`):

- **Scan commands** of the form `VARIABLE start stop STEP` — one variable per command, last token is **step size not point count** (`parse_scan_steps`, `tavi/utilities.py`). Up to two commands compose a 2D grid scan.
- **Serial job queue.** Every run (GUI Run button or `POST /scan`) becomes a `ScanJob` (`tavi/scan_jobs.py`) consumed by one worker thread — runs never race.
- **Per-job parameter isolation.** A job carries a frozen `launch_state` dict; the worker never reads live widgets.
- **Always-on submission validation.** Parse, budget (`BudgetLimits.check_submission`), per-point feasibility (`calculate_angles` error flags), and ETA are checked at submit time; over-limit or infeasible submissions are rejected by default, with an `allow_partial` escape hatch.
- **`ScanResult`** holds the accumulating per-point counts as JSON-safe lists; `snapshot()` gives HTTP threads a consistent read.

---

## 1. Scan-derived motion primitives — "goto CEN"

The headline feature.

### 1.1 What real control systems do

The idiom is universal across TAS control software:

- **`spec`**: `scan qh 1 0.02 21 …` to collect a peak, then the fit variables `cen` / `com` / `fwhm` are populated, and `umv qh cen` (or a `fit` + `mv`) drives the motor to the fitted center.
- **SPICE (HFIR)**: `scan`/`rscan` then `fitpk` exposes centre and the operator drives to it.
- **NICOS (FRM-II/MLZ)**: `cscan`/`scan`, then `center = fit.center` and `maw(h, center)` moves there. NICOS ships fit backends but the *move* is the control action.

In all three the boundary is the same as ours: the control system **computes a scan-derived motion** (a geometry/statistics reduction of the scan it just ran) and **drives to it**. It does **not** decide what the peak *means*. TAVI mirrors exactly this: it may compute COM/CEN/MAX from a completed scan because control systems do; it does not interpret the data scientifically.

### 1.2 Motivation

- **Human (GUI):** After a rocking curve or `H` scan, the operator wants to sit on the peak to optimize the next measurement. Today they must read the value off the plot by eye and retype it into the widget. A "Go to CEN" button removes the transcription and the guesswork.
- **LLM/API client:** A measurement driver's core loop is *scan → find peak → recenter → scan finer*. Without a server-side motion primitive the LLM must pull the full counts array, fit it itself (re-implementing the control system's job, and doing it differently than the real instrument would), and PATCH the value back. A `POST /goto` gives it the same verb the real instrument exposes, so the loop transfers.

### 1.3 The fit helper — `tavi/scan_fits.py` (new, Qt-free, numpy only)

A small pure module in `tavi/`, no Qt and no controller import (same ownership rule as `tavi/scan_jobs.py`). It reduces a 1D scan's `(x, counts, valid_mask)` to a single scalar target:

```python
# tavi/scan_fits.py
@dataclass
class MotionResult:
    target: str            # 'cen' | 'com' | 'max'
    value: float | None    # fitted variable value, or None if refused
    ok: bool
    reason: str            # '' on success; human-readable refusal otherwise
    diagnostics: dict      # fwhm, amplitude, r2, n_valid, ... (advisory only)

def compute_motion(x: Sequence[float],
                   counts: Sequence[float | None],
                   valid_mask: Sequence[bool],
                   target: str) -> MotionResult: ...
```

Reductions (numpy only, no scipy dependency):

- **`max`**: the `x` at the maximum finite count. Cheapest, always defined if any valid point has counts > 0.
- **`com`**: counts-weighted centroid `Σ(x·c) / Σ(c)` over valid, finite, non-negative points. This is a *statistic of the scan*, not a model.
- **`cen`**: center of a least-squares Gaussian-on-a-constant-background fit (`amp·exp(-(x-μ)²/2σ²) + bg`), solved by a small numpy Levenberg–Marquardt / `polyfit`-on-log seed then a few Gauss–Newton steps to avoid a scipy dependency. `μ` is the returned value; `σ`→FWHM and `r²` go in `diagnostics` for the caller to judge (TAVI does not judge them).

Input handling: `None` counts (unmeasured/invalid points from `ScanResult.counts`) and points where `valid_mask` is False are dropped before fitting. NaN is treated as missing.

**This module never moves anything.** It returns a number and a verdict; the *move* is done by the controller applying a parameter change (§1.5). That keeps the analysis/control boundary crisp even inside TAVI.

### 1.4 GUI surface

In `gui/docks/display_dock.py`, below the 1D plot, a row of three buttons: **Go to CEN**, **Go to COM**, **Go to MAX**, enabled only when the displayed scan is 1D and complete. The dock already holds the scan geometry it needs (`_variable_name_1`, the plotted `x`/counts via `set_scan_data`, and `_get_axis_label`). On click:

1. Call `compute_motion(x, counts, valid_mask, target)`.
2. On `ok`, emit a new controller-bound signal `goto_requested(variable_name, value)`; the controller writes the value into the scanned variable's widget through the **existing** `_api_field_map` / `apply_parameters` path (§1.5) so the move is visible and triggers the same recompute the user's Enter key would. Overlay a vertical marker on the plot at the fitted `x`.
3. On refusal, show the `reason` in the message center / status bar and **do not move** — draw no marker, change no widget.

The display dock stays within its ownership: it computes nothing itself and touches no widget outside its own plot; the actual parameter write is the controller's job.

### 1.5 API surface

```
POST /api/v1/goto
  { "scan_id": "j-0004", "target": "cen" }        # target ∈ cen|com|max
→ 200
  { "moved": true,
    "variable": "H",
    "from": 2.00, "to": 2.013,
    "target": "cen",
    "diagnostics": { "fwhm": 0.031, "r2": 0.98, "n_valid": 19 } }
```

Flow, entirely reusing existing machinery:

1. Look up the job's `ScanResult` (`JobRegistry.get(scan_id)`); 404 if unknown, 409 if the job is not a completed 1D scan.
2. Run `compute_motion` on `result.scan_values_1` / `result.counts` / `result.valid_mask_1` (all already JSON-safe lists).
3. On success, apply the value as a parameter change through the **same** GUI-thread bridge used by `PATCH /parameters` — build a one-field patch `{result.variable_1: value}` and call `apply_parameters` via `ApiBridge.call_on_gui`. This makes the widget update visible to the human and reuses per-field recompute + validation. Publish a `parameters_changed` SSE event tagged `source: "goto"`.
4. Return what moved and to where. On refusal return **200 with `"moved": false`** and the `reason` (a refusal is a valid answer, not an HTTP error), so a driver can branch on `moved` without exception handling.

Read-only mode: `POST /goto` is a write and is gated exactly like `PATCH`/`POST /scan` (403 in read-only, since it moves a motor).

### 1.6 Failure modes — never move silently

`compute_motion` returns `ok=False` with a specific `reason` (and the controller/GUI refuse to move) in every degenerate case:

| Situation | Detection | Behavior |
|---|---|---|
| Flat / zero counts | max count ≤ 0, or variance ≈ 0 | Refuse: "no peak — counts are flat/zero". |
| Too few valid points | `n_valid < 3` (or `< 5` for `cen`) | Refuse: "not enough valid points to locate a peak". |
| Multiple comparable peaks | ≥2 local maxima within X% of the global max | Refuse for `cen`/`com`: "multiple peaks — ambiguous center". `max` still allowed (it is unambiguous by definition) with a `diagnostics` warning. |
| Peak at a scan edge | argmax at index 0 or n−1, or fitted `μ` outside `[x_min, x_max]` | Refuse: "peak at scan edge — extend the scan". Do not extrapolate outside the measured range. |
| Gaussian fit non-convergence | LM/Gauss–Newton fails or `r² < threshold` | For `cen`: refuse "fit did not converge — try COM or MAX". `com`/`max` unaffected. |

The refusal reason is designed to tell a client *what to do next* (extend the scan, use a different reduction) — which is control feedback, not scientific interpretation.

**Touched modules:** `tavi/scan_fits.py` (new); `gui/docks/display_dock.py` (buttons, marker, `goto_requested` signal); `TAVI_PySide6.py` (`goto_requested` slot reusing `apply_parameters`; `POST /goto` route in the backend); `tavi/api_server.py` (route registration). No change to `instruments/`.

**Open questions:** Should COM use a background-subtracted window rather than the whole scan? What multi-peak threshold is right for TAS lineshapes? Should `cen` fall back to `com` automatically, or always refuse and let the client choose (current lean: refuse — automatic fallback hides which reduction was used, which harms transfer)?

**Dependencies:** the live `ScanResult`/`JobRegistry` model and the `apply_parameters`/`ApiBridge` write path. No new third-party dependency (numpy only).

---

## 2. Path (vector) scans

### 2.1 The gap

A scan command varies **exactly one** index of the 11-element `scan_point_template` (`TAVI_PySide6.py` ~:4116; the `variable_to_index` map ~:4109). So a straight line in reciprocal space where **H and K change together** — any zone/dispersion direction that is not axis-aligned, e.g. `(1,0,0)→(1,1,0)` or an off-axis `(0.5,0.5,0)→(1.5,1.5,0)` — is **inexpressible today**. The operator can only fake it with a coarse 2D grid and discard the off-diagonal points. Constant-energy cuts along an arbitrary Q-line, the bread-and-butter of dispersion mapping, cannot be scanned in one command.

### 2.2 Motivation

- **Human (GUI):** "Scan from `(1 0 0)` to `(1 1 0)` in 21 points at ΔE = 0" is the natural way a scientist thinks about a dispersion cut. Forcing them to express it as two coupled commands (which the syntax forbids) or a grid is a real workflow gap.
- **LLM/API client:** A driver mapping a dispersion wants to request a Q-line directly and get counts vs. position along it. Emulating this with grids and post-filtering is exactly the kind of client-side reconstruction that does not transfer to a real instrument, which *does* have a native Q-line scan.

### 2.3 Design — a first-class scan mode, new point-generator only

A path scan is a **new point-generator, not new physics.** The per-point machinery is untouched: `compute_scan_snapshot(scan_item, …)` in `instruments/tas_runtime.py` already accepts a fully-populated 11-element `scan_point` and computes angles from `scan_point[:4]`. It does not care whether one index varies or four do. **The path scan only changes how the `scan_parameter_input` list of `(scan_point, idx)` tuples is built** (`TAVI_PySide6.py` ~:4159–4174).

Definition of a path scan:

- **Endpoints:** `from = (H,K,L[,E])` and `to = (H,K,L[,E])` in the current scan mode's coordinates (`rlu` or `momentum`).
- **Point count:** `N` points (a path is naturally expressed as a count, not a step size — this is the one place the "STEP not count" rule is deliberately inverted, and the UI/docs must call that out).
- **Scanned variable:** **path fraction** `f ∈ [0, 1]`, linearly interpolated: `p_i = from + f_i·(to − from)`, `f_i = i/(N−1)`.

The generator:

```python
# proposed: TAVIController._build_path_scan_points(from_hkl, to_hkl, n, template)
for i in range(n):
    f = i / (n - 1)
    scan_point = template[:]                     # copies bending + chi/kappa/psi
    scan_point[0] = from_h + f * (to_h - from_h)  # H  (or qx)
    scan_point[1] = from_k + f * (to_k - from_k)  # K  (or qy)
    scan_point[2] = from_l + f * (to_l - from_l)  # L  (or qz)
    scan_point[3] = from_e + f * (to_e - from_e)  # ΔE (optional)
    scan_parameter_input.append((scan_point, i))
```

This is the **single insertion point**: it replaces the single-command branch (`~:4159`) when the scan mode is "path", producing the identical tuple shape the existing loop feeds to `compute_scan_snapshot`. Per-point feasibility (`check_state.calculate_angles`, the loop at :4176) runs unchanged and fills `valid_mask_1d` — a path may leave the accessible region partway along, and that is reported per point exactly as today. The scanned "variable_name" reported to the display and `ScanResult` is a synthetic `"path"` (or `"|q|"`, see §2.5).

**Verified against the snapshot code:** `compute_scan_snapshot` reads `scans[:4]` for Q/HKL/E and `scans[4:11]` for bending/orientation; it never assumes only one of them changes. So no change to `instruments/puma/model.py` is required — the brief's "new point-generator, not new physics" holds exactly.

### 2.4 Surfaces

**GUI (`gui/docks/unified_simulation_dock.py`):** a scan-mode selector gains a **"Path"** option. Selecting it swaps the two scan-command rows for a path row: `From (H K L)`, `To (H K L)`, optional `From E / To E`, and `Points N`. Sketch:

```
Scan mode: ( ) Command   (•) Path
  From:  [1.0] [0.0] [0.0]   E [0.0]
  To:    [1.0] [1.0] [0.0]   E [0.0]
  Points: [21]
```

**API** — a `scan_path` request body alongside the existing `scan_commands`, on the **same** `POST /scan` endpoint:

```
POST /api/v1/scans/... (or POST /scan)
  { "scan_path": { "from": [1,0,0], "to": [1,1,0],
                   "from_E": 0.0, "to_E": 0.0, "points": 21 },
    "parameters": { "Ei": 14.7 } }
```

`scan_path` and `scan_commands` are mutually exclusive per job (400 if both are present). The frozen `launch_state` gains a `scan_kind: "path"` marker plus the endpoints so the worker's generator selects the path branch.

### 2.5 Validation, output, and plotting

- **Validation:** budget point-count uses `N` directly (no `parse_scan_steps` needed). Per-point feasibility runs along the path as above; with `allow_partial=false` an infeasible point rejects the submission, listing the first infeasible fraction. The existing conflict checks (`_check_scan_parameter_conflict`) do not apply (there is one synthetic variable).
- **Output / `ScanResult`:** a path scan is a **1D** result (`mode='1D'`, `variable_1='path'`). `scan_values_1` is the path fraction array `[0 … 1]` (or `|q|`, below). Everything downstream — `counts`, `valid_mask_1`, SSE `scan_initialized`/`point` events — is unchanged.
- **Plotting / files:** `write_1D_scan` (`TAVI_PySide6.py:4904`) sorts by x via `argsort`. Path fraction is monotonic, so sorting is a no-op and correct. `display_dock._get_axis_label` (:672) has **no case for `"path"`** and would fall through to the raw name — a small addition is needed so the axis reads "Path fraction" or, better, `|Q| (Å⁻¹)` computed as cumulative `‖p_i − p_0‖` in reciprocal-space units. **Open question:** default x-axis — path fraction (simple, unit-free) vs. `|q|` (physically meaningful but requires the metric from `ub_matrix`/`reciprocal_space`). Lean: store both in `ScanResult.metadata`, plot `|q|` when the sample mount is available, fall back to fraction.

**Touched modules:** `TAVI_PySide6.py` (path point-generator, `scan_kind` in `launch_state`, `POST /scan` body parsing); `gui/docks/unified_simulation_dock.py` (mode selector + path row); `gui/docks/display_dock.py` (`_get_axis_label` path/`|q|` case); `tavi/api_server.py` (accept `scan_path`); `docs/API_USER_GUIDE.md` (document the count-not-step inversion). No change to `instruments/`.

**Failure modes:** degenerate `from == to` (refuse: zero-length path); `N < 2` (refuse); path leaves accessible region (per-point invalid, reported; whole-path-invalid → refuse with the fraction of the first failure).

**Open questions:** support curved paths (list of waypoints) later, or lines only for v1 (lean: lines only)? Should E interpolate independently of Q (yes — enables sloped constant-Q-ish cuts)? How does a path scan compose into a *2D* scan (path × E grid)? — deferred.

**Dependencies:** none beyond the existing generator and `ScanResult`. `|q|` axis depends on `tavi/reciprocal_space.py` / `tavi/ub_matrix.py` for the metric.

---

## 3. Batch submission + campaign grouping

### 3.1 Motivation

- **Human (GUI):** An overnight plan is a *set* of related scans (a rocking curve at each of ten Q-points; an energy scan at each temperature). The operator wants to queue them as a named group and watch the group's progress, not track ten loose jobs.
- **LLM/API client:** A driver planning a measurement session wants to submit an ordered list atomically, get back stable ids, and later pull one **combined** payload for its own analysis — without N round-trips and without stitching N `/scan/{id}/data` responses by hand.

### 3.2 API surface

```
POST /api/v1/scans
  { "campaign": { "name": "dispersion GM line" },
    "jobs": [
      { "scan_commands": ["H 1.0 1.4 0.02"], "parameters": { "deltaE": 0.0 } },
      { "scan_path": { "from": [1,0,0], "to": [1,1,0], "points": 21 } },
      { "scan_commands": ["deltaE 0 8 0.5"], "parameters": { "H": 1.2 } }
    ] }
→ 202
  { "campaign_id": "c-0007",
    "job_ids": ["j-0011", "j-0012", "j-0013"],
    "budget": { "points": 82, "neutrons": 8.2e9, "accepted": true } }
```

- Each job carries its **own isolated `parameters` patch**, frozen into its own `launch_state` at submit time (reusing per-job isolation). Job `i+1` does **not** inherit job `i`'s parameter writes — isolation is the whole point.
- Jobs enqueue in list order onto the existing serial queue; they interleave with any GUI jobs already queued (the queue stays global and serial — campaigns are a grouping label, not a separate queue).

```
GET /api/v1/campaign/{id}          → manifest
  { "campaign_id": "c-0007", "name": "...", "created_at": ...,
    "state": "running",            # aggregate, see §3.4
    "jobs": [ { "job_id": "j-0011", "state": "done",  "frozen_parameters": {...} },
              { "job_id": "j-0012", "state": "running", ... },
              { "job_id": "j-0013", "state": "queued",  ... } ] }

GET /api/v1/campaign/{id}/data     → combined payload
  { "campaign_id": "c-0007",
    "jobs": [ { "job_id": "j-0011", ...full /scan/{id}/data body... }, ... ] }
```

`frozen_parameters` exposes the per-job launch snapshot so a client (or a later human review) can see exactly what each member ran with.

### 3.3 Data model — `tavi/scan_jobs.py`

A new `Campaign` dataclass + `CampaignRegistry` (mirroring `ScanJob`/`JobRegistry`): `campaign_id` (`c-%04d`), `name`, `created_at`, ordered `job_ids`, and an aggregate `state` derived on read. Each `ScanJob` gains an optional `campaign_id` field so the reverse lookup and the GUI grouping are cheap. All JSON-safe via a `snapshot()` like the existing ones. Pure data + locking, no Qt — same ownership as the rest of the module.

### 3.4 Budgeting and partial failure

- **Budget across a campaign:** `BudgetLimits.check_submission` is currently per-job. Batch submission must check the **whole campaign** against `queue_neutron_budget` (sum of every member's points×neutrons, added to the already-pending cost from `compute_budget_usage`) and against `max_queued` (queue depth after adding all members) **before enqueuing any of them** — a campaign is accepted or rejected atomically, so a client never ends up with half a plan queued. `allow_partial` on the campaign lets over-budget campaigns enqueue only the prefix that fits (documented, opt-in).
- **Partial failure semantics:** members are independent jobs on a serial queue. If `j-0012` FAILS (infeasible geometry, McStas error), the worker moves on to `j-0013` — **one job failing does not cancel the rest.** The campaign's aggregate `state` reflects the mix: `running` while any member is queued/running; on completion `done` if all done, `failed` if all failed, and a distinct **`partial`** if the members ended in a mix of `done`/`failed`/`stopped`/`cancelled`. The manifest always lists each member's own terminal state so the client sees precisely what happened.
- **Stop:** `POST /campaign/{id}/stop` cancels all still-queued members and stops the running one (reusing per-job stop + `clear_queue` semantics).

### 3.5 GUI surface

The API dock's job table (`gui/docks/api_dock.py`) gains a **campaign grouping**: rows nest under a campaign header showing the campaign name, aggregate state, and a group progress (`done/total members`). A group-level Cancel routes through `POST /campaign/{id}/stop`. GUI-initiated runs remain un-grouped (no campaign) unless a future "GUI batch" UI is added — out of scope here.

**Touched modules:** `tavi/scan_jobs.py` (`Campaign`, `CampaignRegistry`, `ScanJob.campaign_id`, campaign-wide budget helper); `TAVI_PySide6.py` (`POST /scans` handler building N isolated `launch_state`s + campaign registration; campaign stop); `tavi/api_server.py` (`/scans`, `/campaign/{id}`, `/campaign/{id}/data`, `/campaign/{id}/stop` routes); `gui/docks/api_dock.py` (grouped table).

**Failure modes:** empty `jobs` list (400); a single member failing validation → whole campaign rejected with the offending index (atomic, unless `allow_partial`); campaign budget exceeded (429 with per-member cost breakdown).

**Open questions:** should `/campaign/{id}/data` stream (SSE/NDJSON) for large campaigns rather than one big JSON body? Do campaigns need a "stop-on-first-failure" mode (some plans are dependent chains)? Should GUI batch submission exist, and if so how does an operator author an ordered list in the GUI?

**Dependencies:** the live job queue and budget model; independent of §1 and §2 (though a campaign member may *be* a path scan from §2).

---

## 4. Measurement intents as control recipes

**Explicitly lower priority. Depends on §1–§3.**

### 4.1 Motivation

Common measurements are fixed compositions of the primitives above. Naming them server-side lets a thin client (human macro button, or LLM issuing one call) invoke a standard *control procedure* without re-deriving it each time — and, crucially, invoke the **same named procedure it would on a real instrument**, so the recipe transfers.

These are **control recipes, not analysis.** A recipe strings together goto-CEN + validation + a standard scan pattern. It never fits a dispersion, never models background, never decides if a result is "good". Those remain the client's job.

### 4.2 Proposed recipes (all composed from §1–3)

| Recipe | Composition | Control content only |
|---|---|---|
| **Rocking curve** | scan `omega` (or `A3`) ±range about current setting; optional auto goto-CEN | Peak-finding on the sample rotation — pure alignment. |
| **θ–2θ** | coupled scan of `A1` and `A2` (a §2 path in angle space, `A2 = 2·A1`) | Standard powder/alignment line; a path scan over angle indices. |
| **Const-Q energy scan** | `scan deltaE start stop step` at a fixed HKL (a plain 1D command, pre-templated) | Convenience wrapper — no new mechanism. |

### 4.3 Surface

```
POST /api/v1/recipe
  { "recipe": "rocking_curve", "variable": "omega",
    "range": 2.0, "points": 21, "goto_cen": true }
→ submits a ScanJob (or small campaign) and, if goto_cen, chains a POST /goto
  on completion; returns the job/campaign id(s).
```

GUI: a "Recipes" menu or a small panel of macro buttons ("Rocking curve", "Const-Q E-scan") pre-filling the scan panel from the current instrument state, so the human sees and can tweak the composed scan before running.

A recipe is implemented **purely as an orchestration** over `submit_scan_job`, the §2 path generator, and `POST /goto` — no new physics, no new per-point code. If a recipe cannot be expressed as such a composition, it does not belong here (it is analysis, and belongs in the client).

**Touched modules:** `TAVI_PySide6.py` (recipe → scan/campaign composition); `tavi/api_server.py` (`/recipe` route); `gui/` (recipe buttons). Optionally a `tavi/recipes.py` holding the pure "recipe → scan spec" expansion (Qt-free, testable).

**Open questions:** are recipes worth server-side codification at all, or should the client compose primitives itself (keeps TAVI thinner, but loses transfer of the *named* procedure)? How much parameterization before a recipe becomes free-form (and thus out of scope)? Chaining goto-CEN into a recipe blurs the boundary — should the *move* always be a separate explicit call the client makes?

**Dependencies:** §1 (goto), §2 (path/coupled scans), §3 (campaigns for multi-step recipes). Do not start before those land.

---

## 5. Resolution ellipsoids — analytical instrument resolution at any (Q, E)

### 5.1 Why this is on the control side of the boundary

The instrumental resolution function is a **property of the instrument configuration** — collimations, crystal mosaics, Bragg angles, Ki/Kf, scattering senses — not a property of any measured data. Computing it interprets nothing: it answers "what volume of (Q, E) space does this spectrometer accept right now?", the same way `calculate_angles` answers "can the spectrometer reach this point?". Every serious TAS workflow runs this calculation offline (Cooper–Nathans in ResLib/ResCal, Popovici in Takin); TAVI can be the rare tool that serves it **live, from the actual current configuration**, to both surfaces. What remains firmly the client's job is *using* it scientifically — deconvolving lineshapes, convolving model S(Q,ω) — none of which enters TAVI.

**This same Cooper–Nathans matrix is the analytic core of the deterministic engine mode (§6):** a deterministic intensity model convolves a ground-truth S(Q,ω) against exactly this resolution matrix. §5 is therefore a hard prerequisite of §6 — building the resolution calculation once serves both the overlay/readout here and the fast execution backend there.

### 5.2 Motivation

- **Human (GUI):** The first question every measured linewidth raises is "is that physics or the instrument?" An overlay ellipse on the scan plot and a live ΔE/Δq readout answer it at a glance, and make TAVI a genuinely instructive training tool — students *see* focused vs. defocused configurations before burning simulation time.
- **LLM/API client:** A driver planning scans needs resolution to choose step sizes (steps ≪ FWHM waste points; steps ≫ FWHM undersample) and to judge feasibility of an objective ("the 0.2 meV splitting you were asked to resolve is 15× smaller than the 3 meV energy resolution here — change the configuration or report impossible"). Without it the LLM guesses or the harness reimplements Cooper–Nathans against parameters it must scrape.
- **TAVI itself:** the analytic widths are a continuous cross-check of the Monte Carlo — a simulated Bragg scan whose fitted FWHM disagrees badly with the Cooper–Nathans prediction flags an instrument-definition bug. Cheap, always-on validation of the simulation.

### 5.3 The calculation — `tavi/resolution.py` (new, Qt-free, numpy only)

Cooper–Nathans first (matrix algebra only, well-published, numpy-sufficient); Popovici (adds spatial effects: source/sample/detector sizes, focusing curvatures) as a later upgrade behind the same interface — worth doing eventually because TAVI *knows* `rhm`/`rvm`/`rha` bending radii, which Cooper–Nathans ignores.

```python
# tavi/resolution.py
@dataclass
class ResolutionResult:
    ok: bool
    reason: str                  # refusal reason when not ok
    matrix: list[list[float]]    # 4x4 M in (Q_parallel, Q_perp, Q_z, E) basis; ellipsoid: x^T M x = 2 ln 2
    r0: float                    # normalization/intensity prefactor
    fwhm: dict                   # {"dE": ..., "dq_par": ..., "dq_perp": ..., "dq_z": ...} incoherent widths
    bragg: dict                  # coherent (Bragg) widths for the same axes
    basis: dict                  # unit vectors of Q_par/Q_perp in sample HKL, so clients can rotate

def cooper_nathans(cfg: ResolutionConfig) -> ResolutionResult: ...
```

`ResolutionConfig` is a plain dataclass of physical inputs: `ki, kf, a1..a4` (or the (Q, E) point they derive from — reuse `_solve_point_geometry` so an infeasible point refuses with the same reason strings as §validation), horizontal/vertical collimations α₁–α₄ / β₁–β₄, mono/ana mosaics (η_M, η_A) and d-spacings, scattering senses. The instrument plugin supplies a `resolution_config(state)` adapter mapping its live state (collimation selection, `monocris_info` d-spacing, senses from the descriptor) onto this dataclass — the math module stays instrument-agnostic, mirroring how `check_point_feasibility` wraps `_solve_point_geometry`.

### 5.4 Surfaces

**API:**

```
GET /api/v1/resolution?H=1.0&K=1.0&L=0&deltaE=5.0
→ 200  { "ok": true, "matrix": [[...]x4], "r0": ...,
         "fwhm": { "dE": 0.94, "dq_par": 0.012, "dq_perp": 0.031, "dq_z": 0.058 },
         "bragg": {...}, "basis": {...},
         "config": { "collimation": "60-40-40-60", "eta_m": 30.0, ... } }
```

Read-only (allowed in read-only mode — it moves nothing). Omitted H/K/L/deltaE default to the current GUI values; supplied ones are evaluated **without** touching widgets (pure computation on a copied state, like `POST /validate`). Infeasible point → `"ok": false` with the standard feasibility reason. The echoed `config` block makes results reproducible and debuggable.

Optional validation tie-in (advisory only, never blocking): the §validation response and `POST /validate` may attach `resolution.fwhm` per scan so a client sees step-size-vs-resolution at plan time. Warnings ("scan step 0.001 rlu is 12× finer than dq_par") are `diagnostics`, not blockers — resolution is information, and only budgets/feasibility reject.

**GUI:** two touchpoints. (1) A live readout — ΔE and Δq FWHMs for the current (Q, E) — in the instrument or sample dock, updating with the same recompute hooks that already refresh angles. (2) An overlay toggle on the display dock's 1D plot: the projected resolution FWHM drawn as a horizontal bar (or Gaussian outline) at the scan's center point, using the scanned variable's projection from `basis`. A 2D (Q,E) ellipse overlay on 2D scans later.

**Plot endpoint:** `GET /scan/{id}/plot.png?resolution=1` adds the same overlay to the API-rendered PNG — one flag, reuses the GUI's projection helper in `tavi/plot_render.py`.

### 5.5 Failure modes

| Situation | Behavior |
|---|---|
| (Q, E) point infeasible | Refuse with the existing feasibility reason ("scattering triangle does not close…") — same strings as validation, so clients handle one vocabulary. |
| Collimation "open"/undefined for a segment | Use the descriptor's documented effective divergence (guide critical angle or a stated default); echo the value used in `config` — never silently assume. |
| Mosaic not part of instrument state | v1: descriptor-level constants per crystal (PG(002) ~30′ etc.), echoed in `config`. Open question below. |
| Matrix not positive-definite (degenerate geometry, e.g. A4 → 0) | Refuse: "resolution undefined at this geometry". |

### 5.6 Verification

The rare feature that verifies *itself against the rest of TAVI*: simulate an elastic Bragg scan at moderate statistics, fit the width (client-side or by eye), compare with the Cooper–Nathans Bragg width — agreement within Monte Carlo error validates both the matrix code and the McStas model; disagreement localizes a bug. Unit tests: published Cooper–Nathans reference configurations (e.g. the worked examples in Shirane, Shapiro & Tranquada) reproduced to numerical tolerance — fully offline, numpy-only, no McStas.

**Touched modules:** `tavi/resolution.py` (new, pure math); instrument plugins (`resolution_config(state)` adapter + descriptor mosaic/divergence constants); `tavi/api_server.py` (`/resolution` route, `?resolution=1` plot flag); `TAVI_PySide6.py` (backend method, GUI readout wiring); `gui/docks/display_dock.py` (overlay toggle); `tavi/plot_render.py` (overlay drawing).

**Open questions:** Cooper–Nathans only for v1, or jump to Popovici since bending radii are already in the state (lean: CN v1, Popovici behind the same interface once CN is validated against McStas)? Where do mosaics live long-term — descriptor constants vs. editable instrument-state fields (they are physical knobs on a real instrument)? Vertical resolution: full 4×4 from the start, or 3×3 in-plane first (lean: full 4×4 — the vertical term is cheap and often surprisingly large)? Should the harness's statistics advisor consume `r0` for count-rate prediction — and does exposing `r0` cross the analysis line (lean: no — it is part of the instrument response, same as fwhm)?

**Dependencies:** `_solve_point_geometry` / feasibility vocabulary (live), descriptor access to collimation/crystal data (live). Independent of §1–§4 — landable at any point in the roadmap; naturally consumed by §4 recipes and the harness's planning layer (`docs/LLM_HARNESS_DESIGN.md`).

---

## 6. Deterministic engine mode — analytic S(Q,ω) as a drop-in execution backend

These three sections (§6–§8) come from the **TAVI × ISAR integration design** — an external automated analysis engine plus an autonomous measurement driver sitting on TAVI's control surface. The benchmarking framework of *Teixeira Parente et al., 2022* (Front. Mater. 8:772014), which pairs an exactly-evaluable intensity function with a movement-aware cost metric, motivates both this engine and the clock in §7.

### 6.1 What it is

A **selectable execution backend**: instead of compiling and running McStas, the worker evaluates an **analytic intensity model** and reports counts through the identical result pipeline. The model is S(Q,ω) built from the **same sample configuration that parameterizes the McStas sample** — an acoustic-phonon branch, an optic-phonon branch, and a Bragg peak, each tunable — convolved with the Cooper–Nathans resolution matrix from `tavi/resolution.py` (§5), plus seeded Poisson counting noise (or noiseless, a flag). Everything above the per-point evaluation is unchanged: **same scan commands, same path/point-list generators (§2, §8), same serial job queue, same SSE events, same `ScanResult`, same plots and PNG endpoint.** A job simply records which backend produced it — `engine: "deterministic" | "mcstas"` in its launch summary and result provenance — so a client can tell tiers apart. Cost per point drops from seconds-to-minutes (McStas) to **milliseconds** (a matrix convolution).

**§5 (resolution) is promoted to an explicit prerequisite: it is this engine's core.** The Cooper–Nathans matrix that §5 computes for the overlay/readout is exactly the kernel a deterministic S(Q,ω) is convolved against. §6 cannot land before §5 is validated.

### 6.2 Motivation

- **Human (GUI, teaching):** Instant feedback. A student sweeps a dispersion, sees the peak move, and re-scans in seconds instead of waiting on Monte Carlo — the physics intuition lands before any simulation time is burned. Lean **yes** on a GUI exposure: a single engine toggle is a large time-saver for training and demos.
- **LLM/API client:** A **fidelity ladder** for autonomous-driver development. The *same* driver code — same endpoints, same verbs — runs against deterministic → Monte Carlo → (eventually) a real instrument behind one switch. A driver's acquisition loop is debugged and benchmarked at millisecond cost on the deterministic tier, then promoted to McStas unchanged. This is the transfer principle of §0 applied to *execution speed*, not just verbs.
- **Benchmarking (ISAR):** The Teixeira Parente setting — an exactly-evaluable intensity function against which an acquisition strategy's regret is measured — is realized *inside the same tool* that also does full MC. Ground truth and simulation share one instrument and one sample, so a strategy validated on the analytic tier is testing the same physics it will later measure.

### 6.3 Key design constraint — one ground-truth sample config

**Both engines must consume a single source-of-truth sample configuration.** The deterministic S(Q,ω) evaluator and the McStas sample component are parameterized from the *same* dispersion/peak parameters, so a deterministic scan and an MC scan of the same setup are comparing like with like. If the two drifted apart, cross-tier comparison (the whole point of the ladder) would be meaningless. This is the one non-negotiable in the design: the sample model is authored once and projected into both backends.

### 6.4 Surfaces

**API** — engine selection rides existing bodies; no new endpoint required for v1:

```
POST /scan  { "engine": "deterministic", "parameters": {...}, "scan_command1": "..." }
→ 202  { "job_id": "j-0021", "engine": "deterministic", "eta": {"estimated_seconds": 0.1, ...}, ... }
GET /scan/j-0021/data → result carries "engine": "deterministic" in metadata/provenance.
```

`engine` defaults to `"mcstas"` (backward-compatible). `GET /schema` advertises the allowed engines for the instrument. `GET /state` reports the session default engine.

**GUI** — a small **Engine** selector (Deterministic / McStas) in the simulation dock or a menu, mirrored into the API's session default. Selecting Deterministic makes the Run button return near-instantly.

### 6.5 Failure modes

| Situation | Behavior |
|---|---|
| Sample feature the analytic model cannot express (incoherent background, multiple scattering, phonon linewidth from anharmonicity) | Documented **fidelity gap, not an error** — the deterministic result is honestly labelled as an idealized model. Provenance (`engine: "deterministic"`) is the client's signal not to expect MC-level realism. |
| Resolution matrix undefined (degenerate geometry, A4 → 0) | Refuse with the **same reason strings as §5** ("resolution undefined at this geometry") — one vocabulary across resolution and deterministic execution. |
| (Q, E) point infeasible | Same feasibility refusal as MC — geometry is checked identically; the engine switch changes only how counts are produced, never whether a point is reachable. |

### 6.6 Boundary note

The deterministic engine stays firmly on the **control side** of §0. It evaluates the *instrument-plus-sample model* — a property of the configured spectrometer and its ground-truth sample — and interprets **no measured data**. It is the simulation backend, not an analyst: it produces counts, exactly as McStas does, and makes no scientific decision about them.

**Touched modules:** `tavi/resolution.py` (§5, prerequisite — the convolution kernel); a new pure evaluator, likely `tavi/deterministic_engine.py` (Qt-free, numpy-only S(Q,ω) + Poisson noise); instrument plugins (a second execution path alongside `run_PUMA_point`, plus the shared sample-config projection); `TAVI_PySide6.py` (engine selection in `launch_state`, worker dispatch on `engine`, provenance in the result); `tavi/scan_jobs.py` (`engine` field on `ScanJob`); `tavi/api_server.py` (accept `engine`, advertise in `/schema`); `gui/docks/unified_simulation_dock.py` (engine selector).

**Open questions:** Where does the analytic S(Q,ω) evaluator live — a `tavi/` helper consumed by a second instrument-plugin execution path (keeps the math instrument-agnostic, mirroring `resolution.py`), or inside each plugin? Engine switch **per-session** (a mode) vs **per-job** (an `engine` field, more flexible, chosen above as the lean)? Should the GUI expose it at all (lean **yes** — the teaching payoff is large)? How is the shared sample config authored and versioned so both engines provably read the same numbers?

**Dependencies:** **§5 (resolution) is a hard prerequisite** — its Cooper–Nathans matrix is the convolution kernel. Otherwise independent of §1–§4. Naturally consumed by the autonomous driver in `docs/LLM_HARNESS_DESIGN.md`, which uses the fidelity ladder directly.

---

## 7. Virtual instrument clock — simulated experimental time

### 7.1 What it is

TAVI jobs currently cost **wall-clock compute** (the `eta` from `tavi/runtime_tracker.py`). A real experiment costs **beam time**: counting time plus the time to move the spectrometer's axes between points. The clock adds a second, physically meaningful cost — **simulated experimental time** — computed per job from the angles TAVI already knows, and exposes it alongside the existing wall-clock ETA.

The physics is free. `compute_scan_snapshot` already computes **every axis angle at every point** (A2/mtt, A3/omega, A4/stt, analyzer att, plus bending/orientation) via `calculate_angles`. So:

- **Counting time** = points × a counting-time model (see open questions).
- **Movement time** follows the **Teixeira Parente metric**: along the ordered scan path, each step's move time is `max over axes of |Δangle_axis| / velocity_axis` (the axes move in parallel, so the slowest axis sets the step), summed over the path. This needs **no new physics** — only per-axis angular velocities and a difference of angles TAVI already produces.

Per-axis velocities are added to the **instrument descriptor** (deg/s per axis). Experimental time = Σ counting + Σ movement.

### 7.2 Motivation

- **Human (GUI, teaching):** Students *see* that a badly ordered scan list wastes an hour of "beam" — a Q-list that zig-zags across the accessible region spends most of its budget moving motors, not counting. A live "experimental time" readout next to the wall-clock ETA makes the cost of poor planning concrete in a way pure compute time never does.
- **LLM/API client (benchmarking):** **Honest cost accounting** for autonomous-driver benchmarking. An acquisition function that ignores movement cost happily zig-zags — it looks efficient by point count but wastes beam. Only a **movement-aware clock** catches that, which is precisely the metric Teixeira Parente et al. use to score strategies. Exposing experimental time lets a driver optimize the real objective (information per beam-hour), not a proxy.

### 7.3 Surfaces

**API** — `experimental_time` rides existing responses, never replacing the wall-clock `eta`:

```
POST /validate / POST /scan → validation gains:
  "experimental_time": { "seconds": 742.0, "counting": 660.0, "movement": 82.0,
                         "velocities_known": true }
GET /state → "session_experimental_time": 5310.0   (cumulative, this session)
GET /journal → entries note per-job experimental time.
```

**GUI** — a readout in the simulation or API dock showing the pending scan's experimental time (counting + movement breakdown) beside the wall-clock ETA, and a cumulative session total, refreshed by the same hooks that already recompute the ETA.

### 7.4 Failure modes

| Situation | Behavior |
|---|---|
| Per-axis velocities not defined for the instrument | Fall back to a **descriptor default** with a provenance flag (`"velocities_known": false`); report movement time as an estimate, never silently omit it or assume zero. |
| Points with infeasible geometry (no angles) | Excluded from the movement sum (no defined move to/from an unreachable setting); counting time counts only feasible/run points, consistent with `skipped_points`. |
| Single point / single-command with one axis moving | Movement term is well-defined (or zero for a single point); the metric degenerates cleanly. |

### 7.5 Boundary note

The clock computes a **property of the instrument and the planned scan path** — how long this spectrometer would take to execute this motion — from geometry alone. It interprets no data. It sits on the control side of §0, exactly like feasibility and resolution.

**Touched modules:** instrument descriptors (per-axis angular velocities, counting-rate model constants); `tavi/runtime_tracker.py` or a small new `tavi/experiment_clock.py` (Qt-free: consumes the per-point angle sequence from the snapshot pipeline, returns counting/movement seconds); `TAVI_PySide6.py` (compute at validate/submit, thread into results, accumulate session total); `tavi/api_server.py` (`experimental_time` in validation, `session_experimental_time` in `/state`); `tavi/journal.py` (per-job note); `gui/` (readout).

**Open questions:** Counting-time model — proportional to `number_neutrons`? A configurable count-rate (neutrons/s) so simulated experimental time maps to a nominal flux? A fixed per-point monitor-count model like a real experiment? Should the **budget system** optionally budget *experimental time* (a beam-time allocation) rather than, or in addition to, neutrons — closer to how real allocations work and more meaningful for a driver optimizing beam-hours?

**Dependencies:** the per-point angle sequence from `compute_scan_snapshot`/`calculate_angles` (live) and descriptor velocity fields (new). Independent of §1–§6; small and landable early.

---

## 8. Point-list (non-uniform) scans

### 8.1 The gap

The `VARIABLE start stop STEP` grammar produces **uniform grids only**. A single point already works (the degenerate command with both commands empty). But an **arbitrary list of values** — dense near a feature, sparse in the tails — is inexpressible. Every real counting-time saving in a well-planned scan lives in *non-uniform* sampling, and it cannot be requested today without submitting many one-point jobs.

### 8.2 Motivation

- **Human (GUI, later):** A scientist who already knows roughly where a peak sits wants to pack points around it and skip the flat background — fewer points, same information. The uniform grid forces a wasteful choice between "coarse everywhere" and "fine everywhere".
- **LLM/API client:** **Adaptive within-scan sampling is where real counting-time savings live.** A driver's acquisition function naturally emits a non-uniform grid — dense near a predicted peak, sparse elsewhere. Downstream energy-scan fitters (DHO, damped-harmonic-oscillator fits) accept arbitrary x-arrays, so there is no reason to force the acquisition onto a uniform grid. This is the point-generation counterpart to path scans (§2): both feed the same pipeline, both express a scan the string grammar cannot.

### 8.3 Design — a value-list point generator

An explicit **value-list form**, mutually exclusive with `scan_commands`/`scan_path`:

```
POST /scan
  { "scan_points": { "variable": "deltaE",
                     "values": [2.0, 3.5, 4.0, 4.25, 4.5, 5.5] },
    "parameters": { "H": 1.0, "K": 0.0, "L": 0.0 } }
```

Implementation is **another point-generator branch feeding the existing snapshot pipeline** — the *same insertion point* as path scans (§2), and even simpler: no interpolation, just place each listed value into the scanned index of the 11-element `scan_point` template and emit `(scan_point, i)` tuples. Validation, budget, and per-point feasibility run **unchanged** (each listed value is one point, checked exactly as a grid point is). The result is a **1D** `ScanResult` with `variable_1` = the named variable and `scan_values_1` = the (sorted) value list; `counts`, `valid_mask_1`, and every SSE event are identical to a command scan.

`scan_points`, `scan_commands`, and `scan_path` are mutually exclusive per job (400 if more than one is present). The frozen `launch_state` gains a `scan_kind: "points"` marker plus the value list so the worker selects the branch. GUI exposure comes later (an editable value table); the API is the v1 surface.

### 8.4 Failure modes

| Situation | Detection | Behavior |
|---|---|---|
| Empty `values` | `len(values) == 0` | Refuse (400): "point-list scan needs at least one value". |
| Duplicate values | repeated entries | **Reject** duplicates (400) rather than silently collapsing — a duplicate is almost always a client bug, and skipping it silently would hide it. |
| Unsorted values | not monotonic | **Auto-sort** ascending and note it in the validation response (`"sorted": true`), so `write_1D_scan`'s `argsort` and the plot see a monotonic x with no surprise. |
| A listed value geometrically infeasible | `calculate_angles` error flags | Per-point, exactly as today: reject the submission unless `allow_partial`, then skip and list under `skipped_points`. |

### 8.5 Boundary note

A point-list is a **scan geometry**, not an analysis. TAVI executes the values it is handed; deciding *which* values to sample (adaptive placement around a predicted peak) is the client's/driver's job — the acquisition function lives in `docs/LLM_HARNESS_DESIGN.md`, not here. TAVI only runs the list.

**Touched modules:** `TAVI_PySide6.py` (value-list point-generator branch at the shared §2 insertion point, `scan_kind: "points"` in `launch_state`, `POST /scan` body parsing); `tavi/scan_jobs.py` (`scan_kind`/value-list in the frozen state); `tavi/api_server.py` (accept `scan_points`, mutual-exclusion check); `docs/API_USER_GUIDE.md` (document the form). Later: `gui/docks/unified_simulation_dock.py` (value table). No change to `instruments/`.

**Open questions:** Should a point-list compose into a 2D scan (value-list × command, or value-list × value-list)? Should the auto-sort be suppressible (a client that *wants* acquisition order preserved for movement-time accounting — note the interaction with §7's movement metric, which is path-order-dependent)?

**Dependencies:** none. Independent of §2 path scans but **shares the generator insertion point** (`TAVI_PySide6.py` ~:4159); landable before or after §2 with no ordering constraint. Small.

---

## 9. Dependency-ordered roadmap

Each item is independently landable and verifiable, in order:

1. **Scan-derived motion (§1).** `tavi/scan_fits.py` + `POST /goto` + display-dock buttons. Depends only on the live `ScanResult`/`apply_parameters` machinery. Highest value, smallest surface, self-contained. Verify: run a 1D scan, click "Go to CEN", confirm the scanned widget moves to the fitted center and refuses cleanly on a flat scan; `curl POST /goto` returns `moved`/`from`/`to`.
2. **Path scans (§2).** New point-generator + `scan_path` body + "Path" GUI mode + `_get_axis_label` case. Depends on the existing generator/`compute_scan_snapshot` (no physics change). Verify: `(1 0 0)→(1 1 0)` in 21 points produces a 1D counts-vs-fraction result matching a hand-built grid diagonal; infeasible points reported per point.
3. **Batch + campaigns (§3).** `Campaign`/`CampaignRegistry`, `POST /scans`, campaign endpoints, campaign-wide budget, grouped job table. Depends on the live serial queue and budget model; independent of §1–2 but naturally consumes path scans as members. Verify: submit a 3-job campaign, force one member infeasible, confirm the other two run and the campaign ends `partial`.
4. **Point-list scans (§8).** Value-list point-generator branch + `scan_points` body + mutual-exclusion check. Shares the §2 insertion point; **no dependency on §2** — landable independently and early. Small. Verify: `{"scan_points": {"variable": "deltaE", "values": [2, 3.5, 4, 4.25, 4.5, 5.5]}}` produces a 1D result at exactly those x-values; a duplicate rejects, an unsorted list auto-sorts with a note.
5. **Virtual instrument clock (§7).** Per-axis velocities in the descriptor + `tavi/experiment_clock.py` + `experimental_time` in validation/results + cumulative session total. Independent of §1–§6; small (no new physics — reuses per-point angles). Landable early. Verify: a compact scan and a zig-zag Q-list of equal point count report clearly different movement times; velocities-unknown falls back with `"velocities_known": false`.
6. **Resolution ellipsoids (§5).** `tavi/resolution.py` + plugin `resolution_config` adapters + `GET /resolution` + GUI readout/overlay. Independent of items 1–5 and landable in parallel with any of them; the pure-math module plus published-reference unit tests can land well before the GUI overlay. **Prerequisite of §6.** Verify: reproduce a published Cooper–Nathans configuration to tolerance offline, then compare a simulated elastic Bragg width against the predicted Bragg width.
7. **Deterministic engine (§6).** `tavi/deterministic_engine.py` + shared sample-config projection + `engine` field through `launch_state`/worker dispatch + provenance. **Depends on §5** (its Cooper–Nathans matrix is the convolution kernel); otherwise independent. Verify: a deterministic scan of the same setup as an MC scan returns in milliseconds with a peak at the same position, tagged `engine: "deterministic"`; the two agree within Monte Carlo error where the analytic model is faithful.
8. **Recipes (§4).** Orchestration layer over §1–§3. Lowest priority; do not start until §1–§3 are live and stable. Verify: `rocking_curve` with `goto_cen` runs the scan then recenters.

Throughout: preserve the analysis/control boundary of §0. If a proposed addition requires TAVI to *interpret* data rather than *compute a motion or a scan geometry*, it belongs in the client, not here. Resolution (§5) sits on the control side deliberately: it is a property of the instrument configuration, computed from no data. The deterministic engine (§6) likewise stays on the control side — it evaluates the instrument-plus-sample model and produces counts, exactly as McStas does, interpreting no measured data; the clock (§7) computes a property of the planned motion, not of any result.

---

## 10. Notes where the codebase shaped this design

- **`compute_scan_snapshot` is already path-ready.** It consumes a fully-populated 11-element `scan_point` (`scans[:4]` for Q/HKL/E) and never assumes a single varying index, so path scans need **no** change to `instruments/puma/model.py` — only the point-generator in `TAVI_PySide6.py` (~:4159) changes. This confirms the brief's "new point-generator, not new physics".
- **The scan-command grammar is the real constraint**, not the physics: `_validate_single_scan_command` (:2090) and `parse_scan_steps` (`tavi/utilities.py:91`) hard-code "one variable, four tokens, last = step". Path scans deliberately sidestep this grammar with a structured `scan_path` body rather than extending the string syntax (which cannot express coupled variables cleanly).
- **1D output sorts by x** (`write_1D_scan` via `argsort`, :4900) — fine for monotonic path fraction, but `display_dock._get_axis_label` (:672) has **no `"path"` case** and would mislabel the axis; a small addition is required (flagged in §2.5).
- **`ScanResult.counts` uses `None` for unmeasured/invalid points**, so `compute_motion` must drop `None`/NaN before fitting — designed in (§1.3).
- **`goto` reuses `apply_parameters`, not a new setter.** Because the field map already covers every scannable variable and fires the right recompute handler, a goto move is just a one-field patch — no new widget-writing code, and the move is visible to the human exactly like a manual edit.
