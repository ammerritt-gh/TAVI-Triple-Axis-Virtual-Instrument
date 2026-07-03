# LLM Measurement Harness — Design Document

*Status: **Draft**, 2026-07-03 — design only, no code exists yet.*

> **Nothing in this document is implemented.** Every module, tool, schema, and
> data structure named below is proposed future work. Where it references TAVI
> symbols and endpoints (`POST /validate`, `GET /schema`, `eta`, `ScanResult`,
> `allow_partial`, `skipped_points`, the `tas-mcp` server) those are real and
> current — verify their exact behavior in `docs/API_USER_GUIDE.md`. Everything
> the *harness* itself does is a proposal.
>
> **Code location is deferred.** The harness is almost certainly a **separate
> repository** from TAVI, not a package inside it. TAVI is the instrument-and-
> control-system product; the harness is a client of TAVI's API and, later, of
> real-instrument data files. Keeping it in its own repo is what enforces the
> boundary this document is built around (see §1). Nothing here should be read
> as a commitment to land code in the TAVI tree.

> Companion documents: `docs/API_USER_GUIDE.md` (authoritative client-facing API
> reference — endpoints, the 40-field parameter table, scan grammar, SSE,
> budgets, gotchas), `docs/API_SERVER_DESIGN.md` (the live API architecture),
> `docs/CONTROL_FEATURES_DESIGN.md` (proposed future TAVI control primitives:
> goto CEN, path scans, campaigns, recipes), `docs/INSTRUMENT_LAYOUT.md`
> (TAS/PUMA geometry), `docs/MCSTAS_PARAMETERS.md` (build-time vs run-time).

---

## 0. What this is

A **measurement harness** for a purpose-built LLM *measurement driver* that runs
experiments. The harness gives the LLM the analysis and decision tooling that
TAVI **deliberately does not provide**, and forces the LLM through a structured
pre-flight before it is allowed to touch the instrument.

There are two LLM user classes, and the harness is designed for the second:

1. **General-purpose assistant.** A human pastes the §2 operator block from
   `docs/API_USER_GUIDE.md` into a chat model and asks it to drive TAVI. It
   needs tools but has no fixed loop. This is the *supported-but-not-the-target*
   case; the MCP tool surface (§5) serves it directly.
2. **Purpose-built measurement driver.** A dedicated agent whose entire job is
   to plan, measure, analyze, and decide-next until an experimental goal is met.
   This driver's competence lives in *its harness*, not in a prompt. **This is
   the design target.** Everything below — the mandatory planning gate (§2), the
   analysis toolkit (§3), the decision-loop recipes (§4) — exists so this driver
   can be built, validated against TAVI, and then transferred to a real
   instrument unchanged.

TAVI (a simulated triple-axis spectrometer) is **one data source**. A real
instrument (ILL, FRM-II/MLZ, HFIR) is another. The harness is the layer that
makes those two interchangeable to the driver above it.

---

## 1. Principles

**P1 — Analysis lives at the user end; the instrument provides raw counts,
monitor, and metadata only.** This is the core project principle, stated in
`docs/CONTROL_FEATURES_DESIGN.md` §0: *TAVI is instrument plus control system,
never analyst.* TAVI (and a real TAS control system) will hand back per-point
counts, a monitor normalization, geometry validity, and a frozen parameter
snapshot. It will **not** fit a peak, model a background, judge whether a peak is
"real", or advise a counting time. All of that is the harness's job. Even the one
"analysis-looking" primitive TAVI may grow — `goto CEN/COM/MAX`
(`CONTROL_FEATURES_DESIGN.md` §1) — is a *control action* (drive a motor to a
scan-derived value), not a scientific conclusion, and the harness must not
confuse the two.

**P2 — The same harness tools consume TAVI JSON or real-instrument data.** Every
analysis tool operates on a **normalized scan-data model**, never on a
TAVI-specific payload directly. Adapters translate a source into that model:

```
NormalizedScan
  scan_variable : str            # e.g. "H", "deltaE", "path", or an angle name
  points        : list[float]    # the scanned x values, one per point
  counts        : list[float|None]  # detector counts; None = unmeasured/invalid
  errors        : list[float|None]  # per-point counting error (√N or provided)
  monitor       : list[float|None]  # monitor counts for normalization (may be None)
  metadata      : dict           # frozen parameters, units, source id, timestamps,
                                  #   valid_mask, mode (1D/2D/single), instrument id
```

- **`counts` uses `None`, never `0`, for an unmeasured or geometrically invalid
  point.** This mirrors the API guarantee (`API_USER_GUIDE.md` §12: *"null counts
  mean unmeasured or invalid — never 0"*). Any tool that sums, fits, or weights
  counts MUST drop `None`/`NaN` first.
- **Adapters, not tools, know the source.** The **TAVI API adapter** exists
  today's-API-shaped: it reads `GET /scan/{id}/data` and maps `result.scan_values_1
  → points`, `result.counts → counts`, `result.valid_mask_1 → metadata.valid_mask`,
  `result.metadata → metadata`. For 2D it maps `counts_grid`. **File-based
  adapters** for real instruments (ILL ASCII/`.dat`, NICOS data files, HFIR SPICE
  files) come later and produce the *identical* `NormalizedScan`. Errors are √N
  when the source gives only counts; a real file's provided errors win.

**P3 — Sim-to-real transfer is the design test for every tool.** Before any tool
is added, ask: *"Would this work unchanged on an ILL or FRM-II data file?"* If a
tool needs a TAVI-only field (a McStas output folder, a `job_id`, an SSE event),
that dependency must live in the *adapter*, not the tool. A driver validated
against TAVI must move to real data by swapping the adapter and nothing else.
This is why analysis is offloaded from TAVI in the first place: a driver that
learned to lean on a TAVI-side analysis feature would learn a habit that does not
transfer.

---

## 2. Planning layer — mandatory pre-flight

The single most important structural feature. Weak LLMs ignore prompt
instructions but **cannot skip a tool precondition.** So the checklist is not
prose in a system prompt — it is a **gate enforced by tool schemas**: the
`run_scan` tool *refuses to execute* without an attached, passed plan.

This is **defense in depth**, deliberately mirroring TAVI's server-side
always-on validation (`API_USER_GUIDE.md` §5: every `POST /scan` is validated
before it queues). TAVI validates on the server because it cannot trust clients;
the harness validates on the client because it cannot trust the LLM. A scan that
the harness lets through still faces TAVI's `POST /scan` validation — two
independent gates.

### 2.1 The plan object

Before any submission the driver must fill and pass a `ScanPlan`:

```
ScanPlan
  plan_id        : str            # minted by the harness on a PASSED validate_plan
  scans          : list[ScanSpec] # each: parameters patch + scan_command(s)
  time_budget_s  : float          # declared by the operator up front, once per session
  checklist:
    valid        : bool  # (a) every scan passed POST /validate, would_queue == true
    time_sane    : bool  # (b) Σ eta.estimated_seconds × confidence-factor ≤ remaining budget
    data_expected: bool  # (c) expected signal reasoned about; every point feasible
                         #     OR allow_partial set with the gap consciously acknowledged
  notes          : str            # the driver's justification, logged to the session log
```

`validate_plan` returns a `plan_id` **only if all three checklist booleans are
true.** `run_scan(plan_id=...)` looks the id up and refuses (`plan_required`
error) if it is missing, unknown, or stale. No plan → no scan.

### 2.2 The three checks

**(a) VALID? — `POST /validate` every planned scan.** For each `ScanSpec`, the
harness calls TAVI `POST /validate` (non-mutating, allowed even in read-only
mode; `API_USER_GUIDE.md` §5). It requires `would_queue == true` and an empty
`blockers` list. `infeasible` points are surfaced to check (c). This costs
nothing — no job is queued, no parameter is left behind (`/validate` rolls back
its inline `parameters` patch).

**(b) TIME-SANE? — `eta` × confidence against the session budget.** The operator
declares `time_budget_s` up front. For each scan the harness reads `eta:
{estimated_seconds, confidence, samples}` from the `/validate` response. It
discounts by confidence (`API_USER_GUIDE.md` §5 *ETA object*: `none`=0 samples,
`low`=1–2, `medium`=3–9, `high`=10+):

- `high` → trust `estimated_seconds` as-is.
- `medium` → inflate by a safety factor; allowed.
- `low`/`none` → **the plan does not pass on ETA alone.** The harness requires a
  cheap **calibration scan** first (a short, low-`number_neutrons`, few-point
  scan at a known-strong position) to build up `samples` for the instrument's
  run-history, after which `eta.confidence` rises and the real plan can be
  re-validated. This directly exploits TAVI's history-based ETA: confidence is a
  function of sample count, so one cheap run converts `none`/`low` into
  `medium`/`high`.

The running sum of discounted ETAs must fit the **remaining** session budget
(the harness tracks spend in its session log, §4.3).

**(c) DATA-EXPECTED? — expected-signal reasoning.** The driver must record, per
scan, an expectation for the signal: at the count *rate* observed in prior
results (pulled from the harness session log and `GET /journal`), how many counts
does it expect at the peak, and is that enough for the error target it cares
about (cross-checked with `advise_counts`, §3)? And: **is every point feasible?**
If `/validate` reported `infeasible` points, the driver must either fix the plan
or *consciously* set `allow_partial: true` and record the acknowledged gap in
`notes`. A silent infeasible point never passes — this mirrors TAVI's own
`skipped_points` honesty (`API_USER_GUIDE.md` §5: *"Skipped points are never
silent gaps"*).

### 2.3 Why a gate, not guidance

The gate is the whole point. A capable model would follow a prompted checklist;
a weak or context-truncated model would not. By making `plan_id` a required,
schema-level argument of `run_scan` that can only be obtained from a passed
`validate_plan`, the harness makes the checklist **unskippable by
construction** — the same reason TAVI validates server-side instead of trusting
the client. If the driver tries to `run_scan` without a plan, the tool errors
before any HTTP call is made.

---

## 3. Analysis toolkit

Pure, offline-testable functions (numpy/scipy) that operate **only** on the
`NormalizedScan` model of §1, so each one satisfies the P3 transfer test. Every
tool below was **deliberately excluded from TAVI** — the note in each row says
why.

| Tool | What it does | Why excluded from TAVI |
|---|---|---|
| `fit_peak` | Gaussian / Lorentzian / pseudo-Voigt fit; returns center, amplitude, FWHM, background, **each with a fitted error**, plus goodness-of-fit (χ²/dof, R²). | Fitting a lineshape is scientific interpretation. TAVI's `goto CEN` computes a *center to move to* (`CONTROL_FEATURES_DESIGN.md` §1.3) but returns no model, no error bars, no lineshape choice — because choosing Gaussian vs. Lorentzian *is* the analysis. |
| `peak_stats` | COM, CEN, MAX, FWHM, integrated intensity (trapezoid over `points`), directly from the arrays. | COM/CEN/MAX exist in TAVI **only as motion targets** (`goto`), not as reported quantities. Integrated intensity is a physics result — never a control action. |
| `point_errors` | Per-point relative error √N/N (or from `errors`) and a "which points are under-counted" flag. | TAVI reports raw counts; turning counts into a statistical statement is analysis. |
| `advise_counts` | "At the observed rate `r` counts/s, you need ≥ N neutrons/point for X% relative error at the peak." Inverts Poisson statistics. | A counting-time recommendation is a scientific/statistical judgement. TAVI's `eta` estimates *time*, never *how much you should count* — that would be advising the experiment. |
| `estimate_background` | Fit/estimate a flat or linear background from the scan wings (edge points), return level + error. | Background modelling is explicitly named as client-side in `CONTROL_FEATURES_DESIGN.md` §0. |
| `assemble_dispersion` | Collect peak centers (from `fit_peak`) across a *set* of const-Q energy scans into an E(q) curve with errors; carry per-point provenance. | Dispersion assembly is the canonical "deciding what the data means" task — the exact thing TAVI refuses to do (`CONTROL_FEATURES_DESIGN.md` §0). |

Design notes:

- **All consume `NormalizedScan`.** `assemble_dispersion` consumes a *list* of
  them plus the q-value each was taken at (from `metadata`), so it works the same
  whether the scans came from TAVI `GET /scan/{id}/data` or a directory of ILL
  files.
- **Errors propagate.** `fit_peak` returns parameter covariances; `assemble_
  dispersion` carries the center errors into the E(q) curve. A real experiment is
  useless without error bars, so the toolkit produces them from the first tool.
- **numpy/scipy only**, no TAVI import. `fit_peak` uses `scipy.optimize.curve_
  fit`; `advise_counts` is closed-form Poisson. This keeps the toolkit unit-
  testable against synthetic data with no instrument present (§7 phase 1).
- **Refusals, not guesses.** Like TAVI's `goto` (`CONTROL_FEATURES_DESIGN.md`
  §1.6), each tool returns a structured refusal (`ok=false`, `reason`) for flat
  data, too-few points, edge peaks, or non-convergence — the driver branches on
  it rather than trusting a bad fit.

---

## 4. Decision loop

The driver's core competence is *measure → analyze → decide-next*. The harness
supplies the recipes; the LLM supplies the goal.

### 4.1 Patterns

- **Alignment loop.** `run_scan` a rocking curve → `fit_peak` → if `ok` and the
  center is off, patch the variable to the fitted center (via TAVI `PATCH
  /parameters`, or a future `POST /goto`) → re-scan a **narrower** window around
  it. Repeat until the center is stable within its own error bar.
- **Convergence criterion.** After each production scan, `fit_peak` gives the
  amplitude/center error. Stop when the error is below the operator's target;
  otherwise `advise_counts` says how many more neutrons/point are needed and the
  driver escalates `number_neutrons`.
- **Window expansion.** If `fit_peak` (or `peak_stats`) reports the peak at a
  **scan edge** (argmax at index 0 or n−1), the harness widens `start`/`stop` and
  re-plans — never extrapolates outside the measured range. (Same edge rule TAVI
  uses to *refuse* a `goto`.)
- **Escalating neutron counts.** Every new position starts with a cheap
  **quick-look** scan (low `number_neutrons`, coarse step) to confirm signal and
  seed the ETA history (§2.2b), then a **production** scan at the count
  `advise_counts` requires. This makes the mandatory calibration step (§2.2b)
  double as reconnaissance.

### 4.2 Every decision routes back through the gate

A "decide-next" step that produces a new scan **must** build a fresh `ScanPlan`
and pass `validate_plan` before `run_scan` — the loop cannot bypass §2. Recentre,
narrow, expand, escalate: each is a new submission and each re-validates.

### 4.3 State recovery

A context-limited LLM will lose its working memory mid-campaign. Two mechanisms
let it resume:

- **TAVI `GET /journal`** — the server-side session narrative (parameter writes,
  submissions, results). The harness can replay it to reconstruct what was
  already measured on the instrument side.
- **Harness-side session log** — a local append-only record of: the declared
  `time_budget_s` and spend so far, every `plan_id` and its checklist, every
  `job_id` submitted and its adapter-normalized result, and every analysis
  verdict (`fit_peak` centers, convergence decisions). On resume, the driver
  reads its own log + `GET /journal` and continues from the last completed step
  rather than restarting the campaign.

The two are complementary: `GET /journal` is the *instrument's* truth (survives a
full harness restart); the session log is the *driver's* reasoning (what it
concluded and why), which the instrument never sees.

---

## 5. Tool surface (MCP)

An **MCP server** exposing ~10–14 typed tools in two groups. Tool schemas are the
enforcement mechanism for §2.

**Instrument tools** (thin wrappers over `docs/API_USER_GUIDE.md` endpoints, via
the TAVI API adapter):

| Tool | Wraps | Notes |
|---|---|---|
| `get_state` | `GET /state` | Mode, busy, queue, all 40 parameters, budget. |
| `get_schema` | `GET /schema` | Live self-description: field names/types/units, `scan_variables`, grammar, `limits`. The driver reads this instead of hard-coding fields. |
| `validate_plan` | `POST /validate` per scan + local checklist | **Mints `plan_id`.** Fails closed. |
| `run_scan` | `POST /scan` | **Requires `plan_id`** from a passed `validate_plan`. Passes `Idempotency-Key` for safe retries. |
| `wait_for_scan` | `GET /scan/{id}?wait=N` | Long-poll to terminal state; honors `Retry-After` and the 16-waiter cap (`429 too_many_waiters`). |
| `get_data` | `GET /scan/{id}/data` | Returns a `NormalizedScan` (adapter converts arrays; `null` preserved). |
| `get_plot` | `GET /scan/{id}/plot.png` | 512×512 quick-look image for the driver/human. |
| `stop` | `POST /scan/{id}/stop` or `POST /stop` | Drain semantics. |

**Analysis tools** (pure, on `NormalizedScan`; §3):

`fit_peak`, `advise_counts`, `assemble_dispersion`, `estimate_background`
(plus `peak_stats`, `point_errors` as lightweight helpers).

### 5.1 Relationship to `tas-mcp` — compose, don't duplicate

A local `tas-mcp` MCP server already provides TAS *math*: `hkl_to_q`,
`q_to_hkl`, `check_feasibility`, `accessible_range`, `d_spacing`,
`bragg_two_theta`, `scattering_plane_check`, orientation helpers. The harness
**uses `tas-mcp` for pre-submission physics sanity** (is this Q in the scattering
plane? does the triangle plausibly close? what is the accessible range along this
line?) and **does not re-implement any of it.**

The division of labor is strict:

- `tas-mcp` — *client-side physics preview*. Cheap, offline, advisory. Used
  inside §2's plan building to prune obviously-impossible scans before spending a
  `/validate` round-trip.
- TAVI `POST /validate` — **authoritative** feasibility. Its `infeasible` verdict
  (real instrument geometry, angle limits, crystal choice) always wins. `tas-mcp`
  narrows the search; TAVI decides.

So a plan flows: `tas-mcp` feasibility sweep → drop the hopeless points → `POST
/validate` the survivors → trust TAVI's answer.

---

## 6. Worked example — acoustic phonon dispersion

**Benchmark task:** *"Map the dispersion of an acoustic phonon between Q-points X
and Y. Analysis is offloaded; TAVI only measures."* This is deliberately the task
TAVI cannot do itself — it measures counts; the harness turns them into E(q).

End-to-end through the harness:

1. **Declare the session time budget.** Operator sets `time_budget_s` (say, an
   8-hour overnight = 28800 s). The harness opens a session log.
2. **Plan the cut.** The driver lays out 10–15 **constant-Q energy scans**
   (`scan_command1: "deltaE …"`) at Q-points evenly spaced along the line X→Y.
   (A future TAVI **path scan**, `CONTROL_FEATURES_DESIGN.md` §2, would express
   this line in one request — see below.)
3. **Physics pre-sweep (`tas-mcp`).** For each Q-point: `hkl_to_q` →
   `check_feasibility` / `accessible_range` to drop points that are kinematically
   closed at the chosen fixed energy *before* any TAVI call.
4. **Validate (TAVI).** `POST /validate` each surviving scan (or evaluate them in
   a batch loop). Collect `would_queue`, `eta`, and any `infeasible` points.
5. **Calibrate for ETA confidence.** The first plan's ETAs come back
   `low`/`none` (no history). The gate (§2.2b) forces one cheap calibration
   scan at the strongest Q-point; after it runs, `eta.confidence` climbs to
   `medium`/`high` and the driver re-validates the full plan against the budget.
6. **Submit.** For each validated scan, `run_scan(plan_id=…)` with `isolated:
   true` per-job isolation and an `Idempotency-Key`. Points that `tas-mcp`/
   `/validate` flagged as closed are handled with `allow_partial: true`, the gap
   consciously recorded — they will surface honestly in `result.skipped_points`.
7. **Collect.** `wait_for_scan` (long-poll) then `get_data` → a `NormalizedScan`
   per Q-point.
8. **Analyze.** `estimate_background` then `fit_peak` (Gaussian-on-background) per
   scan → a peak center (energy) with error at each Q.
9. **Assemble.** `assemble_dispersion` stitches the per-Q centers into an E(q)
   curve with error bars; kinematically closed Q-points appear as honest **gaps**,
   not zeros.

| Step | Tool used | What TAVI does | What the harness does | What the LLM decides |
|---|---|---|---|---|
| Budget | (harness) | — | Open session log | Declare `time_budget_s` |
| Plan | `get_schema`, `tas-mcp` | Serves field/grammar schema | Build 10–15 `ScanSpec`s | Q-spacing, fixed-E mode |
| Pre-sweep | `tas-mcp check_feasibility` | — | Prune closed points | Which points to keep |
| Validate | `validate_plan`→`POST /validate` | Parse, feasibility, ETA, budget | Run checklist, mint `plan_id` | Accept / re-plan |
| Calibrate | `run_scan` (cheap) | Run one short scan | Seed ETA history, log rate | Where/how cheap |
| Submit | `run_scan` (`isolated`) | Queue, validate, run points | Track `job_id`s | `allow_partial` on gaps |
| Collect | `wait_for_scan`, `get_data` | Return counts arrays | Normalize (`null`-safe) | When enough counts |
| Fit | `fit_peak`, `estimate_background` | **nothing** | Peak center + error per Q | Lineshape, refit/refuse |
| Assemble | `assemble_dispersion` | **nothing** | E(q) curve with errors + gaps | Is the dispersion mapped? |

**How future TAVI features would shorten this — without the harness depending on
them.** From `docs/CONTROL_FEATURES_DESIGN.md`:

- **Path scans (§2)** would collapse steps 2–3's hand-laid Q-grid into a single
  Q-line request — but the harness still assembles E(q) client-side, so the
  design works today with per-Q energy scans and *automatically improves* if a
  path-scan `scan_kind` lands (the adapter would emit the same `NormalizedScan`
  with `scan_variable="path"`).
- **Campaigns (§3)** would let step 6 submit all 10–15 scans atomically as one
  named group with one combined `GET /campaign/{id}/data` pull, replacing N
  round-trips — but the harness's session log already tracks the set, so campaign
  support is an optimization, not a prerequisite.
- **Recipes (§4)** could name "const-Q E-scan" server-side — but the harness
  composes it from primitives regardless.

The harness is designed to **compose whatever primitives exist** and degrade
gracefully to the ones that exist today. That is the same "compose, don't
duplicate" stance it takes toward `tas-mcp` (§5.1).

---

## 7. Open questions and phased roadmap

### 7.1 Open questions

- **Normalized model coverage.** Is a flat `NormalizedScan` enough, or does a 2D
  map (`counts_grid`) need a distinct model? Lean: one model with an optional
  `points_2` / `counts` matrix, so `fit_peak` stays 1D-only and a 2D fit is a
  separate future tool.
- **Monitor normalization policy.** Counts-per-monitor vs. counts-per-time —
  which does the toolkit normalize to, and does the adapter or the tool decide?
  This must be settled *before* real-instrument adapters, because ILL and NICOS
  files disagree on convention.
- **Where does `plan_id` live** — in-memory in the MCP server (lost on restart)
  or persisted alongside the session log (survives, enabling §4.3 resume)? Lean:
  persisted.
- **Confidence-factor calibration.** What safety multipliers turn
  `eta.confidence` into the §2.2b time discount? Needs empirical tuning against
  TAVI run history before it can be trusted on a real instrument.
- **How much `tas-mcp` overlap is safe.** `tas-mcp` and TAVI `/validate` can
  disagree (different geometry assumptions). The harness must always defer to
  TAVI, but should it *warn* when they diverge (a sign the `tas-mcp` session is
  mis-configured)?
- **Real-instrument write path.** TAVI has a clean `PATCH /parameters` + `POST
  /scan`. A real NICOS/SPICE instrument does not speak this API. Does the harness
  target a translation shim per instrument, or only *read* real data files and
  *drive* only TAVI-compatible endpoints? (The read path transfers first; the
  write path is instrument-specific.)

### 7.2 Roadmap (dependency-ordered, each independently testable)

1. **Data model + analysis toolkit.** `NormalizedScan`, the TAVI API adapter,
   and §3's pure tools (`fit_peak`, `peak_stats`, `point_errors`, `advise_counts`,
   `estimate_background`, `assemble_dispersion`). **Testable entirely offline
   against synthetic scans** — no instrument, no MCP, no network. This is where
   the P3 transfer test is first proven: feed the tools a synthetic scan and a
   fake "ILL-style" dict and confirm identical output. Highest value, smallest
   surface.
2. **MCP instrument tools.** `get_state`, `get_schema`, `run_scan`,
   `wait_for_scan`, `get_data`, `get_plot`, `stop`, `validate_plan` over the live
   TAVI API. Verify against a running PUMA GUI with short, low-neutron scans.
3. **Planning-layer gate.** The `ScanPlan` schema and the `plan_id` precondition
   on `run_scan`. Verify that `run_scan` without a passed plan **refuses**, and
   that a `low`/`none` ETA forces a calibration scan.
4. **Decision-loop recipes.** Alignment loop, convergence, window expansion,
   escalation, and §4.3 state recovery. Verify the full §6 worked example
   end-to-end against TAVI, then re-run the analysis half against a directory of
   canned real-instrument files to prove transfer.

Throughout, preserve P1–P3: if a proposed harness feature would push analysis
back into TAVI, or would only work on TAVI's JSON and not a real data file, it is
mis-placed.
