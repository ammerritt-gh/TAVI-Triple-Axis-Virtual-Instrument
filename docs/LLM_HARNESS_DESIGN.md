# Measurement Driver — Design Document

*Status: **Draft**, 2026-07-03 — design only. No driver code exists yet. The
driver is **not** part of the TAVI tree; it is a client of TAVI's API and of
ISAR's files, and will almost certainly live in **its own repository**. Nothing
here is a commitment to land code in TAVI.*

> This document describes the **third component** of a settled three-component
> architecture (§1). Where it names TAVI symbols and endpoints (`POST /validate`,
> `GET /schema`, `GET /scan/{id}/data`, `eta`, `isolated`, `allow_partial`,
> `skipped_points`, the `tas-mcp` server) those are **real and current** — verify
> them in `docs/API_USER_GUIDE.md`. Where it names ISAR symbols and files
> (`isar run`, `report/results.csv`, `card.state.json`, `dispersion_prior`,
> `prior_for`, `isar/synth`) those are **real and current in the ISAR repo**
> (`c:\Users\AMM\Documents\Github\ISAR`) — verify them in ISAR's `DESIGN.md` and
> `docs/UNIFICATION_DESIGN.md`. Everything the *driver* itself does is a proposal.

> Companion documents. TAVI side: `docs/API_USER_GUIDE.md` (authoritative
> client-facing API reference — endpoints, the 40-field parameter table, scan
> grammar, SSE, budgets, gotchas), `docs/API_SERVER_DESIGN.md` (live API
> architecture), `docs/CONTROL_FEATURES_DESIGN.md` (future TAVI control
> primitives: goto CEN, path/point-list scans, campaigns, the resolution
> ellipsoid §5, the deterministic engine, and the virtual instrument clock).
> ISAR side: `DESIGN.md`, `docs/READING_GUIDE.md`, `docs/UNIFICATION_DESIGN.md`,
> `docs/STATS_PRIMER.md`.

---

## 0. What this is

A **measurement driver**: a purpose-built agent whose entire job is to take a
scientific goal ("map this phonon branch to this precision within this budget"),
plan and run the measurement, hand each scan to an analysis engine, and decide
what to measure next — until the goal is met or shown to be unmeetable.

This document is the driver's design. Its competence lives in *its own
structure*, not in a prompt pasted into a chat model. It is built so it can be
developed and validated against TAVI (a simulated triple-axis spectrometer where
the truth is known) and then moved to a real instrument by flipping one endpoint.

The earlier version of this file proposed an in-driver "analysis toolkit"
(`fit_peak`, `assemble_dispersion`, a statistics advisor). **That plan is
deleted.** Analysis is now owned by ISAR, a separate, validated project (§1b,
§3). The driver does no fitting and produces no numbers.

---

## 1. The three-component architecture (settled)

Autonomous measurement here is **three cooperating components**, each with a
hard boundary. This split is a decision, not an option.

### 1a. Instrument control surface — TAVI now, a real TAS later

Executes and validates; **never analyzes**. It sets parameters, checks per-point
geometric feasibility, runs scans, and hands back raw counts, a monitor
normalization, geometry validity, and a frozen parameter snapshot. It does not
fit a peak, model a background, judge whether a peak is "real", or advise a
counting time — that is the boundary `docs/CONTROL_FEATURES_DESIGN.md` §0 draws,
and TAVI holds it deliberately so a driver that learns to lean on a control-side
analysis feature does not learn a habit that fails to transfer.

Today this is TAVI over the REST+SSE API of `docs/API_USER_GUIDE.md`. Later it is
NICOS/SPICE on a real PUMA-class instrument. The driver uses the *same verbs* for
both (set → validate → scan → read), so the write path transfers by swapping the
client (§2.3).

### 1b. Analysis engine — ISAR

The number-producer. **ISAR** (`c:\Users\AMM\Documents\Github\ISAR`, machine name
`isar`) is a validated, deterministic triage fitter: DHO-on-background convolved
with resolution, AIC/BIC (never raw χ²) model selection for peak count, per-scan
MINOS uncertainty, a **verdict** on every scan (`resolved` / `flagged` /
`declined`, the last covering `junk`/`held`/`underpowered`/`no_signal`), a
computed confidence, a running dispersion prior, and provenance on every result.
Its own core principle **P1 — "LLM proposes, deterministic code disposes"** keeps
any model out of the runtime path of a number that matters; it is validated two
ways, including against a human gold standard (`docs/READING_GUIDE.md`,
`DESIGN.md` §11, §2).

ISAR is a *separate project with its own life*. The driver invokes it and reads
its files; it does not reach inside it.

### 1c. The driver — this document

The layer between a human's goal and the other two components. It plans, selects
points statistically, drives the instrument through its client, invokes ISAR,
reads ISAR's verdicts and prior, and decides the next measurement. It is
**decision-only**.

### The boundary rule (verbatim)

> **The driver may LOOK at data — plots, raw counts, a quick-look PNG — to decide
> what to measure next. It may never CONCLUDE from its look. Every number comes
> only from ISAR.**

Looking is control feedback ("the peak is at the edge, widen the window");
concluding is science ("ω₀ = 5.2 ± 0.1 meV"). The first is the driver's; the
second is ISAR's, always.

---

## 2. The driver's three parts

### 2.1 LLM supervisor

The only place a language model sits. It never picks routine points and never
produces a number. It does the things that need judgment and world knowledge:

- **Goal → objective spec.** Translate a natural-language goal ("map the acoustic
  phonon dispersion from A to B, resolve ω₀ to ±0.1 meV") into a machine
  objective: the reciprocal-space **path**, the per-point **tolerance** on ω₀, and
  the **time / neutron budget**. This spec is what the acquisition engine (§2.2)
  and the stopping criterion consume.
- **The stopping criterion.** The supervisor holds the decision that the
  objective is **met** (calibrated σ(ω₀) ≤ tolerance everywhere along the path) or
  **unmeetable** (the target is below the instrument's resolution here; the budget
  is exhausted with the path still under-determined; the sample/config cannot
  deliver the statistics). This is the piece the field is missing: Teixeira
  Parente et al. (2022), the benchmarking study of autonomous TAS approaches,
  **explicitly names the stopping criterion as the untested gap** — the existing
  autonomous methods optimize *where to measure* but never settle *when to stop*.
  The driver makes stopping a first-class, testable output.
- **Exception handling.** The supervisor owns the non-routine: a peak that fell
  outside the chosen energy window, an ISAR `flagged`/`held` verdict, budget
  exhaustion, a TAVI validation rejection, a σ-calibration that drifts. Each is a
  branch it reasons about, not a crash.
- **Warm-start layouts.** From physics knowledge (a known zone-center energy, an
  expected sound velocity, symmetry) it proposes an initial scan layout so the
  campaign does not start cold.
- **Renegotiation.** When an assumption breaks (the dispersion is steeper than
  expected; there is an unresolved second branch), it goes back to the user with a
  concrete choice rather than silently burning budget.

### 2.2 Deterministic acquisition engine

The statistical heart. No LLM. It holds a model over ISAR's accumulated per-scan
results — e.g. a Gaussian process or local linear fit of ω₀(q) with predictive
uncertainty — and an **acquisition function** that chooses the next measurement
to maximize information per unit cost.

**The acquisition unit is a SCAN, not a point.** A proposal is a complete scan
request:

- a **Q position** (or a short segment) along the objective path;
- an **energy window** — center = predicted ω(q), half-width = predicted ω
  uncertainty **plus a margin**, so the peak lands inside;
- a **neutron count** — chosen from the target σ(ω₀) and the observed count rate
  (escalating from a cheap quick-look to a production count).

**"Peak outside the chosen window" is a first-class outcome, not a failure.** The
recovery policy is explicit: widen the window, re-center on the observed
intensity (a LOOK, not a conclusion — §1), or escalate to the supervisor if it
keeps missing. Because ISAR *declines* a scan with no usable peak rather than
inventing one, a missed window shows up as a `declined`/`no_signal` verdict the
engine can branch on.

**Cost is movement-aware when the clock exists.** Cost = counting time + spectro­
meter axis-movement time. The counting term is always available; the movement
term becomes available when TAVI grows the **virtual instrument clock**
(`docs/CONTROL_FEATURES_DESIGN.md`). Until then the engine uses counting time
alone and treats movement as free; the acquisition function is written so the
movement term slots in without restructuring.

### 2.3 Instrument client

The plumbing. Two halves, both mechanical.

- **TAVI API consumer.** `GET /schema` (learn the fields for *this* instrument
  rather than hard-coding), `GET /state` (confirm `mode == "allow"`),
  `POST /validate` (dry-run feasibility + budget + ETA), `POST /scan` with
  **`isolated: true`** (run at one-off parameters without disturbing the GUI or
  other work), `GET /scan/{id}?wait=N` (long-poll to a terminal state), and
  `GET /scan/{id}/data` (the counts arrays, with `null` for unmeasured/invalid
  points — never `0`). It honors `Retry-After` on 409/429/503 and reuses an
  `Idempotency-Key` on uncertain retries. The whole surface is in
  `docs/API_USER_GUIDE.md`; the client is a thin wrapper, nothing more.
- **ISAR invoker.** Save each finished scan to the ISAR workspace's data
  directory as a JSON scan file the `tavi` parser plugin understands (§4), run
  `isar run --workspace <dir>` (idempotent — it re-fits only new/changed scans),
  and read the outputs (§4). No query API is called; ISAR is driven by files and
  a subprocess.

The client also composes with the existing **`tas-mcp`** MCP server for
client-side TAS math (`hkl_to_q`, `check_feasibility`, `accessible_range`) as a
cheap pre-`/validate` sanity pass. It does **not** re-implement that math, and
TAVI's `POST /validate` is always the authoritative feasibility verdict.

---

## 3. Analysis is ISAR's — the boundary

The old in-driver toolkit (`fit_peak`, `peak_stats`, `advise_counts`,
`estimate_background`, `assemble_dispersion`) is **superseded and deleted.** Every
one of those tasks is an ISAR responsibility, and ISAR has a validated
implementation of them (DHO fit, model selection, per-scan interval, dispersion
collation into the prior). Re-implementing them in the driver would duplicate
ISAR, and worse, would put an unvalidated fitter in the loop.

So the driver-side logic is decision-only, and the boundary is the rule stated in
§1, restated because it is the load-bearing invariant of the whole design:

> **The driver may LOOK at data to decide what to measure next; it may never
> CONCLUDE from its look. Numbers only ever come from ISAR.**

Concretely: the acquisition engine may read a raw counts array or a
`GET /scan/{id}/plot.png` to detect "the peak is at the scan edge" and re-center
the window. It may **not** compute a center, a width, an amplitude, an integrated
intensity, or an ω₀ for the record. Those come back from ISAR's `results.csv`
with a verdict attached, or they do not exist.

---

## 4. ISAR file contract

ISAR exposes **no query API**. Its stable interface is its files, written once per
`isar run` into the workspace `report/` and `card.state.json`. The driver reads
these; it never imports ISAR internals.

- **`report/results.csv`** — the machine-readable product, one row per
  scan × detector. Columns the driver consumes: `omega0`, `omega0_err`,
  `interval_lo` / `interval_hi` (the per-scan MINOS interval), `gamma` +
  **`gamma_provisional`** (**always `true` on TAS** — ISAR's 1-D resolution cannot
  separate instrumental width from intrinsic damping, so the driver targets
  **ω₀, never Γ**, on TAVI/PUMA data), `verdict`, `disposition`, `confidence`,
  `prior_omega`/`prior_sigma`/`prior_n`/`prior_source`, `resolution_version`, and
  `reasons`.
- **`report/report.json`** — a light run summary (counts by verdict, gaps),
  cheaper to poll than parsing the CSV when the driver only needs progress.
- **`card.state.json`** — the accumulated experiment state: `dispersion_prior`
  (a list of `PriorPoint` dicts: `{scan_id, sample, t_bin, component, q_value, q,
  omega0, sigma, modality, verdict}`) and `resolution_versions`. This is the
  running physics model the acquisition engine mirrors.

**Session gates are driver planning constraints.** ISAR holds a measurement it
cannot yet trust: `held_for_calibration` (no resolution/energy-zero version
exists yet) and `held_for_sample` (no sample context). When the driver sees these
statuses it must **schedule the missing context scans first** — a resolution/Bragg
scan, or a sample-defining alignment — before ISAR will fit the phonon scans. The
bootstrap order is ISAR's, and the driver respects it.

> **WARNING, encode this.** ISAR's `prior_for(...)` floors its returned `sigma` at
> **0.3 meV by design** (it is an IC-seeding prior; `sigma = max(0.3 meV, resid
> std)`, `UNIFICATION_DESIGN.md` §5). The acquisition engine's convergence test
> must consume the **per-scan `interval_lo`/`interval_hi` from `results.csv`**,
> **never** the prior's floored sigma. A 0.1 meV objective is **unreachable by
> construction** if the driver reads the prior sigma as its measured uncertainty —
> it can never drop below 0.3. The prior is for *seeding*; the interval is for
> *deciding done*.

**TAVI enters ISAR through a dedicated `tavi` parser plugin** (live in ISAR:
`isar/parsers/tavi.py` + `isar/parsers/cards/tavi.policy.toml`, following
ISAR's P3 "per-experiment parser → normalized scan → instrument-agnostic
core"). Real-instrument parsing catalogues (IN8, S30, and
future facility formats) stay **separate** from the TAVI plugin: TAVI writes its
own JSON scan format and **never emits fake facility files**. When the driver
moves to a real instrument, that instrument gets its own ISAR plugin; the TAVI
plugin is not reused to masquerade as real data.

---

## 5. σ-calibration is milestone 0

**Before any adaptive campaign runs, the driver must calibrate ISAR's error
bars.** This is non-negotiable and comes first.

ISAR's intervals are **statistical-only and measured overtight**: on ISAR's gold
set the human's value lands inside ISAR's 68% interval only **~20% of the time**,
and ISAR's own docs say plainly *"don't weight by ISAR's σ"* (`READING_GUIDE.md`,
`STATS_PRIMER.md`). The central value is good (median |Δ| ~0.16 meV from the
human); the *width* misses systematics (background shape, resolution, energy-zero
drift).

The driver's MVP convergence criterion is `σ(ω₀) ≤ tolerance`. Feeding it a
too-tight σ would declare convergence early and wrongly. So **milestone 0**:

1. Run a set of known-ω scans on TAVI, where the **ground truth is the McStas
   sample configuration** — TAVI is the only tier where the true ω₀ is actually
   known.
2. Pass them through ISAR and measure the **empirical coverage** of ISAR's
   intervals (what fraction of true values fall inside the stated 68%/95%
   intervals).
3. Derive an **inflation factor** (or a calibration curve vs. count rate / verdict
   / prior population) that the driver applies to every ISAR interval before the
   convergence test.

This calibration is per instrument configuration; the supervisor re-runs it (or
reuses a stored one) when the configuration changes. It **doubles as a deliverable
for ISAR itself**: ISAR's `UNIFICATION_DESIGN.md` §10 explicitly *defers* the full
statistical coverage validation as a slow run, and the driver's milestone-0
campaign produces exactly that coverage measurement on data with known truth —
something ISAR cannot get from real beamtime.

---

## 6. Fidelity ladder

The driver develops, validates, and deploys across three tiers that share one
interface, so promotion is flipping one endpoint/mode switch, not a rewrite.

| Tier | What it is | Turnaround | Role |
|---|---|---|---|
| **1. Deterministic TAVI engine** | analytic S(q,ω) ⊗ Cooper–Nathans resolution + seeded Poisson noise (designed in `docs/CONTROL_FEATURES_DESIGN.md`; **same TAVI API**) | milliseconds | **develop** the acquisition loop |
| **2. TAVI Monte Carlo** | full McStas simulation | seconds–minutes | **validate** against realistic counts/resolution |
| **3. Real instrument** | PUMA / NICOS | live beamtime | **deploy** |

The driver is written once against the tier-1 endpoint, validated on tier 2 (same
TAVI API, different `mode`/endpoint), and deployed on tier 3 by swapping the
instrument client (§2.3) and the ISAR parser plugin (§4). **Ground truth — an
acoustic branch, an optic branch, a Bragg peak, all tunable — lives in ONE McStas
sample configuration consumed by both TAVI engines**, so tier-1 development and
tier-2 validation measure the *same* physics.

---

## 7. Benchmark generator

TAVI closes the gap the Teixeira Parente et al. (2022) benchmarking paper openly
admits. That study **excluded noise and background** because a benchmark needs
deterministic, known truth, and realistic noise seemed to preclude it. TAVI
provides both at once: **known truth** (the McStas sample config, §6) **plus
seeded, reproducible noise plus Monte Carlo resolution**. A driver campaign on
TAVI is therefore scoreable in a way real beamtime never is.

Two scores, deliberately distinct:

- **Map-error** — the paper's benefit measure: a τ-clipped, weighted L² error of
  the reconstructed intensity map against truth. Measures *coverage efficiency*.
- **Physics-error** — dispersion RMS: the driver's final ω₀(q) curve (from ISAR's
  prior) against the true dispersion. Measures *scientific correctness*.

Both are reported **at cost milestones** in the paper's Table-1 format, with
**cost = counting time + axis-movement time** (their metric — hence the
dependency on TAVI's virtual instrument clock, `docs/CONTROL_FEATURES_DESIGN.md`).
Adopt the paper's BASE conventions where practical, so results are directly
comparable to the published autonomous-TAS methods.

---

## 8. MVP loop — worked example

**Goal (operator, natural language):** *"Map the acoustic phonon dispersion from A
to B and resolve ω₀ to ±0.1 meV, overnight."* This replaces the old fixed-grid
example: the point of the driver is that the grid is **not** fixed — it adapts.

1. **Objective spec (LLM supervisor).** Path A→B, tolerance σ(ω₀) ≤ 0.1 meV,
   budget = 8 h counting (+ movement when the clock exists). Opens a session log.
2. **σ-calibration (milestone 0, §5).** If no calibration exists for this
   configuration: run known-ω scans, measure ISAR interval coverage, derive the
   inflation factor. Skip if already done for this config.
3. **Warm-start layout (LLM supervisor).** From the known zone-center energy and an
   estimated sound velocity, lay out a coarse initial set of constant-Q energy
   scans along A→B.
4. **Adaptive loop** — repeat:
   1. **Acquisition proposes a scan (§2.2):** a Q on the path, an energy window
      = predicted ω ± margin, a neutron count from the target σ.
   2. **Feasibility sanity:** `tas-mcp` `check_feasibility` (cheap, offline), then
      TAVI **`POST /validate`** (authoritative — feasibility, budget, ETA), then
      **`GET /resolution`** for the advisory step width (from
      `docs/CONTROL_FEATURES_DESIGN.md` §5; steps ≪ resolution FWHM waste points,
      steps ≫ it undersample).
   3. **Run:** `POST /scan` with `isolated: true`, long-poll `GET /scan/{id}?wait=N`
      to terminal, `GET /scan/{id}/data`.
   4. **Analyze:** save the scan JSON to the ISAR workspace, `isar run --workspace`,
      read `report/results.csv` and `card.state.json`.
   5. **Update (acquisition):** fold the new `omega0` + calibrated interval into
      the ω(q) model; update predictive uncertainty along the path.
   6. **Check (LLM supervisor):** objective met along the path? Any anomaly — peak
      outside window (recover: widen/re-center), ISAR `flagged`/`held` (schedule
      context or escalate), budget nearly spent (renegotiate)?
5. **Stop (LLM supervisor).** When the **calibrated** σ(ω₀) ≤ 0.1 meV everywhere
   along A→B, declare the objective **met**. If the budget exhausts first, or the
   target is below resolution here, declare it **unmeetable** with reasons.
6. **Deliverable.** ISAR's `dispersion_prior` (the mapped branch) + ISAR's run
   report + the driver's session log (what it measured, why, and how it decided to
   stop).

**The adaptive behavior to show:** the driver measures **densely where the
dispersion bends or σ is still high**, and **sparsely where ω(q) has already
converged**; it starts each new Q with a cheap **quick-look** (low neutrons, to
seed the count rate and the ETA history) and escalates to a **production** count
only where the tolerance demands it. A missed energy window at a steep segment is
a normal event that triggers a widen-and-retry, not a stall.

---

## 9. Phased roadmap and open questions

### 9.1 Roadmap (dependency-ordered, each independently testable)

0. **σ-calibration campaign (§5).** Known-ω scans on TAVI → ISAR interval coverage
   → inflation factor. First, because every later convergence decision depends on
   it, and it is a deliverable for ISAR too.
1. **Acquisition engine (§2.2).** Developed **offline against ISAR's `isar/synth`
   module** (DHO + seeded Poisson, a millisecond fake instrument — no TAVI, no
   McStas, no network), then against the **deterministic TAVI tier** (tier 1, §6).
   The statistical core is provable before any instrument is involved.
2. **Instrument client + MCP tool surface (§2.3).** The TAVI API consumer and the
   ISAR invoker, exposed as MCP tools: instrument tools plus ISAR file readers
   (`get_dispersion_prior`, `get_scan_verdicts`, `run_isar_batch`). **Compose with
   the existing `tas-mcp`; do not duplicate** its TAS math.
3. **LLM supervisor + full MVP campaign (§2.1, §8)** on the **Monte Carlo tier**
   (tier 2). This is where goal→spec, the stopping criterion, and exception
   handling first run end-to-end on realistic data.
4. **Benchmark scoring + real-instrument adapter (§7).** The two-score benchmark
   in Table-1 format, then the NICOS adapter that swaps the instrument client for
   tier 3.

### 9.2 Open questions

- **Acquisition model choice.** Gaussian process over ω(q) (smooth, principled
  uncertainty, but a kernel to choose and cost) vs. local linear fits (cheap,
  matches ISAR's own prior builder, but weaker far from data). Lean: start local,
  move to GP if the path curvature demands it.
- **Multi-branch handling.** Near an acoustic/optic crossing, ISAR fits *per
  scan* and does not assign a peak to a branch — **branch assignment is a driver
  concern**. How does the acquisition engine keep two ω(q) models separate when
  the scans do not label which branch each peak belongs to?
- **Campaign batching vs. one-at-a-time.** Propose and submit one scan per loop
  (simple, maximally adaptive) or a small batch per loop (fewer ISAR invocations,
  better use of TAVI campaigns from `docs/CONTROL_FEATURES_DESIGN.md`, but staler
  decisions)?
- **When does ISAR need a query API?** The file contract (§4) is stable and
  restart-safe, but re-running `isar run` and re-reading CSVs every loop has a
  fixed cost. At what campaign size does a lightweight ISAR query interface earn
  its keep over files?
