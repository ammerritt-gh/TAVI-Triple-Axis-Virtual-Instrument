# The Closed Loop — simulation, analysis, and autonomous measurement

*Status: **Draft**, 2026-07-03. This is the **capstone / umbrella document** for a
three-project system. The integration seam is **LIVE** — the first closed-loop
measurement ran today (§7). The measurement **driver** that would close the loop
autonomously **does not exist yet** (it is designed, not built). Nothing here
commits code to any of the three repositories; it records the system-level
reasoning that the three per-project designs assume but do not restate.*

> **What this document is for.** The companion designs each state *decisions* for
> their own component. This document preserves the *why* — the arguments and the
> evidence behind the split, the boundary, and the roadmap — so a new collaborator
> (or a future session) can reconstruct not just what was decided but why the
> alternatives were rejected. Read it first; then read the companions (map at the
> end, §9).
>
> **The three repositories.**
> - **TAVI** (`c:\Users\AMM\Documents\Github\TAVI`) — a McStas-backed virtual
>   triple-axis spectrometer plus a REST+SSE control API. The *instrument*.
> - **ISAR** (`c:\Users\AMM\Documents\Github\ISAR`, machine name `isar`) — an
>   automated reduction/triage fitter. The *analysis*. Every number the system
>   reports comes from ISAR.
> - **A measurement driver** (future, its own repo) — the only component with
>   agency. It decides what to measure next and when to stop. The *loop*.
>   **Superseded 2026-07-06:** lives in the ISAR repo as `isar/drive/` (an
>   `isar drive` CLI subcommand), not a separate repo; see the §8 open-question
>   note below.
>
> **Companion documents.** TAVI side: `docs/LLM_HARNESS_DESIGN.md` (the driver's
> own design — component 3), `docs/CONTROL_FEATURES_DESIGN.md` (the TAVI-side
> primitives the loop needs: §5 resolution, §6 deterministic engine, §7 virtual
> clock, §8 point-list scans), `docs/API_USER_GUIDE.md` / `docs/API_SERVER_DESIGN.md`
> (the live control surface). ISAR side: `DESIGN.md`, `docs/READING_GUIDE.md`,
> `docs/UNIFICATION_DESIGN.md`, `docs/STATS_PRIMER.md`. This document
> cross-references those by name and section rather than restating them.

---

## 0. The goal, in one sentence

**LLM-directed measurement — on a simulation *or* a real instrument — with in-situ
analysis at speed, where the system dynamically measures where scientific utility
is highest instead of running a fixed macro.**

The MVP that makes this concrete: *"measure an acoustic phonon dispersion from A to
B and fix the energy within ±0.1 meV."* A conventional experiment runs a
pre-planned grid of constant-Q energy scans and analyzes afterward. The closed loop
instead measures densely where the dispersion bends or the uncertainty is still
high, sparsely where ω(q) has already converged, and stops when the objective —
stated in the *user's* terms, not a model's internal variance — is met or shown to
be unmeetable.

**TAVI is the testbed and, crucially, the only tier where the loop is scoreable**
(§4): it is the one place the true answer is known while the measurement is still a
realistic, noisy, resolution-broadened observation. The whole architecture is built
so the same driver that develops against TAVI transfers, unchanged in its logic, to
a real triple-axis instrument.

---

## 1. The three-component split, and why (the core argument)

Autonomous measurement here is **three cooperating components, each with a hard
boundary**. This is a decision, not an option, and the rest of the document is
downstream of it.

| Component | Repo | Role | Agency |
|---|---|---|---|
| **Instrument** | TAVI now; NICOS/real TAS later | Executes and validates a scan. **Never analyzes.** | none — it does what it is told and reports geometry validity + raw counts |
| **Analysis** | ISAR | Turns counts into numbers, deterministically, with a verdict and provenance on every one. | none in the number path (its **P1**: *LLM proposes, deterministic code disposes*) |
| **Driver** | future, own repo | Decides what to measure next and when to stop, **from computed quantities only**. | the only component with agency |

The instrument boundary is TAVI's established no-analysis principle
(`CONTROL_FEATURES_DESIGN.md` §0); the analysis boundary is ISAR's P1
(`DESIGN.md` §2). The driver is designed in `LLM_HARNESS_DESIGN.md`.

### 1a. The alternative everyone builds first — and why it loses

The default architecture is **monolithic**: one LLM that looks at the counts, fits
them in its head (or with an inline tool), decides the phonon is at 5.2 meV, and
picks the next scan. It is the obvious thing, and it is wrong for this problem for
three independent reasons, each sufficient on its own.

**(a) The error economics are asymmetric and compounding.** A wrong *control*
decision wastes one scan: it is visible in the session journal, bounded to that
scan's cost, and recoverable on the next iteration. A wrong *analysis* number is
categorically worse — it poisons the dispersion prior, which then misdirects every
subsequent point-selection decision, and it does so *silently*. In an autonomous
loop there is no human downstream to catch the bad number before it propagates.
ISAR's P1 exists for exactly this failure, and it applies **more** strongly under
autonomy than under the human-in-the-loop triage ISAR was originally scoped for
(`DESIGN.md` §1) — the safety net ISAR assumed (a human reviews every batch) is
precisely what the driver removes. So the constraint that keeps a model out of the
number path must be *stronger* here, not relaxed.

**(b) Reproducibility.** A monolithic agent replayed over the same beamtime yields
a *different* dispersion each run: remote models drift, and temperature ≠ 0 makes
even the same model non-deterministic. ISAR's propose-then-freeze design
(`DESIGN.md` §2, P1) makes every number re-derivable forever from frozen config,
with no model in the runtime path. Reproducibility is non-negotiable for a
scientific instrument; once you accept it for the analysis, the split falls out of
it — you *cannot* have a reproducible number and a language model computing it.

**(c) Independent validation transfer.** ISAR's analysis is validated against **79
human-checked real fits** (the FeSeS gold standard, `DESIGN.md` §11,
`READING_GUIDE.md`) — a body of evidence about how its fitter behaves on real data
from real instruments. A monolithic agent trained/tuned against TAVI carries *none*
of that to a real instrument; its competence is entangled with the simulator it
learned on. The split lets each half carry its own validation across the sim→real
boundary: ISAR's fitter is already validated on real IN8/S30 data, and the driver's
*decision* logic is validated against TAVI's known truth (§4). Neither has to be
re-earned when the loop moves to the beamline.

### 1b. The two LLM roles are different species

The split is also forced by the fact that the **two places a language model could
sit have opposite failure economics**:

- **ISAR's LLM** (config authoring, IC proposals, residual diagnosis) must **never
  distort a number** — for physics, a confident wrong answer is *worse than no
  automation* (`DESIGN.md` §11). Its discipline is therefore **propose-and-freeze**:
  the model's output is a *proposal* that a deterministic path disposes of, and
  nothing it says reaches a reported number without passing through frozen,
  re-runnable code.
- **The driver's LLM** (goal→spec, stopping, exception handling) merely **wastes
  beam when it is wrong**, and wrongness is visible and bounded (§1a-a). Its
  discipline is therefore **act-with-gates**: it may act, provided its actions pass
  feasibility/budget validation and it can never conclude a number.

Merging them into one agent forces the strictest constraint (propose-and-freeze,
never distort a number) onto a role that does not need it, and simultaneously
loosens the number-path guarantee onto a role that cannot tolerate the loss. They
are genuinely different jobs with different safe designs. Keeping them in separate
components is what lets each be built correctly.

---

## 2. The boundary rules (verbatim-worthy)

Three rules define the seams. They are stated here as the system-level invariants;
the companions encode them locally.

1. **TAVI never analyzes.** It sets parameters, checks per-point geometric
   feasibility, runs scans, and returns raw counts, a monitor normalization,
   geometry validity, and a frozen parameter snapshot. Scan-derived *motion*
   (goto-CEN, centre-of-mass, a rocking-curve recenter) is **control, not analysis**
   — every real TAS control system computes it, and `CONTROL_FEATURES_DESIGN.md` §0
   draws exactly this line. TAVI holds it deliberately so a driver cannot learn to
   lean on a control-side fit that will not exist on the real instrument.

2. **All numbers come from ISAR.** Not "should" — the driver produces no ω₀, no
   width, no amplitude, no integrated intensity for the record. Those come back from
   ISAR's `results.csv` with a verdict attached, or they do not exist.

3. **The driver may LOOK at data to decide what to measure next; it may never
   CONCLUDE from its look.**

   > *Looking is control ("the peak is at the scan edge — widen the window").
   > Concluding is analysis ("ω₀ = 5.2 ± 0.1 meV"). The first is the driver's; the
   > second is ISAR's, always.*

Rule 3 is the one that resolves the **real cost of the split**. The honest objection
to a three-component design is that the driver, cut off from the data, acts only on
compressed summaries (a `results.csv` verdict string) and is therefore *blind on
exactly the ambiguous, flagged cases where a look would help most*. Rule 3 gives the
cost back without breaching the boundary: the driver *may* pull a raw counts array
or a `GET /scan/{id}/plot.png` to see that a peak fell off the window edge and
re-center — a LOOK. It may not compute a center from that look and enter it as a
result — a CONCLUSION. The distinction is not "can it see the data" (it can) but
"what may it derive that persists" (nothing; only ISAR's numbers persist).

---

## 3. Where the LLM actually sits — and where it does not

A recurring worry is that "LLM-directed measurement" means the model picks
measurement points by fiat. **It does not, and the design is explicitly built so it
cannot.** With ISAR in the loop we know exactly what the current data tells us
(per-scan ω₀ with a MINOS interval), we can forward-predict what a proposed new scan
would add (via a model over ω(q)), and we can therefore pick the measurement with
the greatest **statistically-backed** information return per unit cost. That
selection is a **deterministic acquisition function** (`LLM_HARNESS_DESIGN.md` §2.2),
with no model in it.

The LLM exerts **high-level control** — the parts that need judgment and world
knowledge, none of which is point selection:

- **Goal → objective spec.** Translate *"map the acoustic branch A→B, resolve ω₀ to
  ±0.1 meV, overnight"* into a machine objective: the reciprocal-space path, the
  per-point tolerance on σ(ω₀), and the time/neutron budget.
- **The stopping criterion.** Decide the objective is **met** (calibrated σ(ω₀) ≤
  tolerance everywhere along the path) or **unmeetable** (below resolution here;
  budget exhausted with the path still under-determined; the sample/config cannot
  deliver the statistics).
- **Exception handling.** The peak missed the window; ISAR returned `flagged`/`held`;
  the budget is nearly spent; a TAVI validation rejected a point; the σ-calibration
  drifted. Each is a branch it reasons about, not a crash.
- **Warm-start layouts** from physics (a known zone-center energy, an expected sound
  velocity, symmetry), so the campaign does not start cold.
- **Renegotiation** when an assumption breaks (the dispersion is steeper than
  expected; a second branch appears) — back to the user with a concrete choice, not
  silent budget burn.

### 3a. Anchor in the literature — and the gap the LLM fills

**Teixeira Parente et al. 2022** (*Front. Mater.* 8:772014, "Benchmarking Autonomous
Scattering Experiments Illustrated on TAS"; a copy lives in the ISAR repo's `docs/`)
defines autonomous scattering exactly this way: a **deterministic acquisition**
strategy choosing where to measure. Their group's ARIANE approach drives a TAS with
a log-Gaussian-process model of the intensity map. The paper **explicitly names the
untested gap**:

> *"an autonomous stopping criterion is not tested although we consider it a crucial
> part of a fully autonomous approach."*

**The LLM supervisor *is* the stopping criterion.** The existing autonomous methods
optimize *where to measure* but never settle *when to stop*; the driver makes
stopping a first-class, testable output, and "done" is defined in the user's terms
(σ(ω₀) ≤ tolerance along the path), not the model's internal variance.

Two further points where our design departs from ARIANE, both deliberate:

- **The acquisition unit on a TAS is a SCAN, not a point.** A scan is a (Q position,
  E window, counting time) triple. ARIANE reasons point-wise over an intensity map;
  ours must reason **scan-wise**, which makes *"the predicted peak fell outside the
  chosen energy window"* a **first-class recovery case**, not a failure — and this
  is not hypothetical: it happened on the very first live run (§7). The recovery
  (widen / re-center on the observed intensity / escalate) is a LOOK under §2 rule 3.
- **A different benefit measure.** ARIANE scores against *model-free intensity-map
  variance*. Ours scores against **fit-parameter uncertainty** — σ(ω₀) along the
  dispersion, from ISAR — which is *model-based*. Both are valid benefit measures,
  and (this is the payoff of §4) **TAVI can score both**, so our choice can be
  compared to theirs on the same instrument.

---

## 4. Why TAVI is the only place the loop can be scored

This is the **benchmark-generator claim**, and it is why TAVI is not merely a
convenient sandbox but a genuinely new capability.

The 2022 paper **excluded noise and background from its benchmark**, by necessity: a
benefit measure needs a *deterministic true intensity function* to score against,
and realistic noise seemed to preclude having one. You could have known truth *or*
realistic measurement, not both.

**TAVI dissolves the dilemma.** Ground truth is *what is built into the sample
configuration*; the noisy measurement is a **seeded, reproducible Monte Carlo
realization** on top of it. So known truth, realistic counting statistics, and real
(Monte-Carlo) resolution **coexist** — the exact combination the paper says cannot.
This is what makes the loop scoreable: on TAVI you can measure how far the driver's
recovered dispersion is from the answer *while the measurement is still a realistic
noisy observation*.

**Two scoreable benefit measures, deliberately distinct:**

- **Map-error** — the paper's metric: a τ-clipped, weighted L² error of the
  reconstructed intensity map against truth. Measures *coverage efficiency*.
- **Physics-error** — dispersion RMS: the driver's final ω₀(q) curve (from ISAR's
  `dispersion_prior`) against the true dispersion. Measures *scientific correctness*.

**Cost measure:** counting time + axes-movement time — the paper's angle-map metric.
This is exactly why TAVI needs a **virtual instrument clock**
(`CONTROL_FEATURES_DESIGN.md` §7): an acquisition function that ignores movement
cost happily zig-zags across the accessible region, looking efficient by point count
while wasting beam. Only a movement-aware clock catches it.

Scores are reported **at cost milestones in the paper's Table-1 format**, adopting
the paper's **BASE conventions** (`jugit.fz-juelich.de/ainx/base`) where practical,
so results are directly comparable to published autonomous-TAS methods.

> **Caveat on comparability.** Our escalation strategy uses **variable counting
> time** (cheap quick-look → production count), which the 2022 paper lists under
> "future extensions." So published comparability is *approximate*, not exact — an
> honest asterisk on any Table-1 comparison.

**Bonus: TAVI can calibrate and validate ISAR itself.** ISAR computes analytic
Cooper–Nathans resolution in its `tavi` parser; TAVI plans a `GET /resolution`
endpoint (`CONTROL_FEATURES_DESIGN.md` §5) computing the same matrix from the live
configuration — a **mutual cross-check**. And a simulated Bragg width (McStas) vs.
the predicted Cooper–Nathans width is **continuous validation of both** the matrix
code and the McStas model (`CONTROL_FEATURES_DESIGN.md` §5.6).

---

## 5. σ-calibration is milestone 0 — the load-bearing empirical risk

Before any adaptive campaign runs, the driver must **calibrate ISAR's error bars.**
This is non-negotiable and comes first, and it is the single biggest empirical risk
in the whole system.

**The problem.** ISAR's intervals are **statistical-only and measured overtight**:
on ISAR's gold set the human's value lands inside ISAR's 68% interval only **~20% of
the time**, and ISAR's own docs say plainly *"don't weight by ISAR's σ"*
(`READING_GUIDE.md`, `STATS_PRIMER.md`). The central value is good — a median |Δ| ~
0.16 meV from the human — but the *width* misses systematics (background shape,
resolution, energy-zero drift).

**Why it is load-bearing.** The MVP convergence criterion (σ(ω₀) ≤ 0.1 meV) *and*
the acquisition function both **consume σ(ω₀)**. Driving on a miscalibrated σ gives
you two failures at once: **premature convergence** (a too-tight σ declares the
objective met before it is) and **mis-ranked beam allocation** (the acquisition
function ranks the wrong scans as most informative). Every later convergence
decision depends on this being fixed.

**How TAVI resolves it** (only TAVI can): run known-ω scans where the ground truth is
the McStas sample configuration → measure the **empirical coverage** of ISAR's
stated 68%/95% intervals → derive an **inflation factor / calibration curve** the
driver applies to every ISAR interval before the convergence test. In simulation
some real-data systematics (energy-zero drift, unknown resolution) are absent or
*exactly known*, so the residual miscalibration is actually measurable — you can
separate "the bar is optimistic" from "the center is pulled." This campaign
**doubles as a deliverable to ISAR**, whose `UNIFICATION_DESIGN.md` §10 step 5
explicitly *defers* the full statistical coverage run as a multi-minute job; the
milestone-0 campaign produces exactly that coverage measurement on data with known
truth, which ISAR cannot get from real beamtime.

> **Companion trap — encode this.** ISAR's `prior_for(...)` floors its returned
> `sigma` at **0.3 meV by design** (it is an IC-seeding prior; `sigma = max(0.3
> meV, resid std)`, `UNIFICATION_DESIGN.md` §5). The acquisition engine's
> convergence test must consume the **per-scan `interval_lo`/`interval_hi` from
> `results.csv`**, **never** the prior's floored sigma. A 0.1 meV objective is
> **unreachable by construction** if the driver reads the prior sigma as its
> measured uncertainty — it can never drop below 0.3 meV. The prior is for
> *seeding*; the interval is for *deciding done*.

> **Related scope limit.** Γ (linewidth) is **always provisional on TAS** until
> ISAR grows its 4-D resolution engine (`tas4d`, deferred — `DESIGN.md` §13 Q3,
> `UNIFICATION_DESIGN.md` §12, R8). ISAR's 1-D resolution cannot separate
> instrumental width from intrinsic damping. **The MVP objective therefore targets
> ω₀ only.** A linewidth-mapping objective is not currently achievable and must not
> be promised.

---

## 6. Fidelity ladder + integration mechanics

### 6a. The fidelity ladder

Three execution tiers sit behind **one control surface**, so the driver develops on
the cheapest tier, validates on the realistic one, and deploys on the real one by
flipping a single switch. This is the transfer thesis (§1a-c) applied to *execution
speed*, not just verbs.

| Tier | What it is | Turnaround | Driver role |
|---|---|---|---|
| **1. Deterministic TAVI engine** | analytic S(q,ω) ⊗ Cooper–Nathans + seeded Poisson (`CONTROL_FEATURES_DESIGN.md` §6) — the 2022 paper's exactly-evaluable setting, realized inside the same tool | ms/point | **develop** the acquisition loop |
| **2. TAVI Monte Carlo** | full McStas | s–min/point | **validate** on realistic counts + resolution |
| **3. Real instrument** | PUMA / NICOS, via an adapter | live beamtime | **deploy** |

Below tier 1 sits ISAR's own **`isar/synth`** module (DHO + seeded Poisson, no
instrument at all) for offline acquisition-engine development with zero network and
zero McStas — the statistical core is provable before any instrument is involved
(`LLM_HARNESS_DESIGN.md` §9.1 step 1).

**Ground truth lives in ONE sample configuration** consumed by both TAVI engines, so
tier-1 development and tier-2 validation measure the *same* physics — the one
non-negotiable of the deterministic-engine design (`CONTROL_FEATURES_DESIGN.md`
§6.3). Currently that config is **`Phonon_DFT`** (`tavi/sample_library.py`,
`components/Al_test_phonons_centered.dat`): an analytic acoustic branch
`E = 6·sin(π·q/2)` meV and an optic branch `E = 6 + 2·sin(π·q/2)` meV, at `T = 200 K`
with `phonon_gamma = 0.2`.

### 6b. The integration seam (user decisions)

- **Real-instrument parser catalogues stay SEPARATE from TAVI's.** ISAR has a
  dedicated **`tavi` parser plugin** — its *third* instrument card, now **live**
  (`isar/parsers/tavi.py`, `isar/parsers/cards/tavi.policy.toml`, `tests/test_tavi.py`)
  — that reads the saved `GET /scan/{id}/data` JSON. TAVI writes its own JSON scan
  format and **never emits fake facility files**. When the loop moves to a real
  instrument, that instrument gets its *own* ISAR plugin; the TAVI plugin is never
  reused to masquerade as real data. The sim-to-real claim is **ISAR's own P3**
  (`DESIGN.md` §2): same instrument-agnostic core, different parser plugin — S30,
  IN8, and now TAVI as the third worked column of `DESIGN.md` §6's card table.

- **The driver↔ISAR interface is FILES, not an API.** ISAR exposes no query API. Its
  stable interface is `report/results.csv`, `report/report.json`, and
  `card.state.json` (`dispersion_prior`) written once per `isar run`. The file
  contract is the stable interface; a query API is revisited only if/when the driver
  exists and the per-loop re-read cost earns it (`LLM_HARNESS_DESIGN.md` §9.2).

- **ISAR's session gates are driver planning constraints.** `held_for_calibration`
  (no resolution/energy-zero version yet) and `held_for_sample` (no sample context)
  mean the driver must **schedule the missing context scans first** — a Bragg /
  elastic resolution scan, a sample-defining alignment — before ISAR will fit the
  phonon scans. The bootstrap order is ISAR's (`DESIGN.md` §4,
  `UNIFICATION_DESIGN.md` §2.5); the gates force exactly what a competent
  experimentalist does anyway.

- **Cadence note (one honest rub).** ISAR is **batch-idempotent**: every `isar run`
  re-parses everything and re-fits only new/held/changed scans
  (`UNIFICATION_DESIGN.md` §0.5). This is fine at simulation scale. At real-instrument
  scale (thousands of scans) it is the one place the file-driven, re-parse-everything
  cadence rubs against a per-scan adaptive loop. Revisit when the driver runs on a
  real instrument, not before.

Note the two TAVI-side prerequisites for tier 1: `GET /resolution`
(`CONTROL_FEATURES_DESIGN.md` §5) is the convolution kernel, and the deterministic
engine (§6 there) is its consumer. Both are designed, neither is built — the driver
develops against tier 1 *as those land*.

---

## 7. Evidence — the first closed-loop measurements (2026-07-03, all live)

This is the system's first empirical record. Everything below actually ran today, on
the TAVI `Phonon_DFT` sample through the live ISAR `tavi` plugin. Preserved verbatim
because these are the facts a future session should not have to rediscover.

**The seam is proven end to end.** TAVI scans → saved `GET /scan/{id}/data` JSON →
`isar init` auto-detects the TAVI format → `isar run` → `results.csv` with per-scan
Cooper–Nathans resolution and honest verdicts. The conservative triage behaved
exactly as designed against degenerate data: zero-count quick-looks (1e5–1e6
neutrons) produced `no_signal`/`abstain` verdicts — *"no excursion above
background"* — and a 3-count blip was correctly rejected as an unbreakable model
fork. Nothing was invented from noise.

**The phonon recipe.** ~**1e8 neutrons/point** is required for a real signal;
quick-looks at ≤1e6 see nothing. For calibration of expectations: real TAS scans run
~1 min/point, and simulation is comparable or faster.

**An integration bug, found only by running it.** A zero sample mosaic (`ETAS = 0`,
the card default) divided by zero inside `cn_resolution_matrix` and *silently*
produced a 0.6 meV fallback width. Fixed: the plugin now omits a non-positive `ETAS`
so Cooper–Nathans reuses `ETAM`; the real width is 1.37 meV. (This is exactly the
class of silent-corruption bug the whole provenance discipline exists to surface.)

**A physics-gate lesson (a driver rule fell out of it).** A Stokes-only energy window
(0 → 4 meV) at T = 200 K was **rejected** — *"no admissible structure converged."* At
kT ≫ ħω the Bose-tied anti-Stokes peak is strong, and a window that excludes it
leaves ISAR's physics-gated structure enumeration nothing admissible to fit. **Driver
rule, now explicit: E windows must span both sides of the elastic line when
kT ≳ ħω.**

**The card-correction channel was exercised.** A stand-in temperature of 300 K was
corrected to the sample's true 200 K plus a seeded expectation (ω₀ = 1.5 ± 0.5) via a
card edit, which triggered a guideline-hash re-fit of *exactly* the affected scans
(`UNIFICATION_DESIGN.md` §2.2, §6) — the correction channel working as designed.

**The measurement.** Q = (2.15, 0, 0), energy scan −3 → 4 meV, 1e8 n/pt: anti-Stokes
at −1.5 meV, an elastic line, and a Stokes peak of 61 counts at +1.5 meV. ISAR
returned **ω₀ = 1.494 ± 0.035 meV**, verdict `model_incomplete`, disposition
`flagged`, confidence 0.93 — *a usable number, honestly marked imperfect.* The
imperfection is real and diagnosable: the measured anti-Stokes/Stokes intensity ratio
is ≈ 0.52 versus the Bose-tied expectation ≈ 0.92 — a resolution-volume / focusing
asymmetry that a 1-D resolution simply cannot model (ISAR's documented TAS ceiling
until `tas4d`). **`flagged` is the correct verdict**, not a defect.

**The punchline — the coverage problem, live.** The analytic truth at q = 0.15 is
`E = 6·sin(π·0.15/2) = 1.400 meV`. ISAR's central value is therefore **+0.094 meV
off, with a ±0.035 meV statistical bar** — the truth lands **outside** the 68%
interval on the very first scored measurement. This is a one-measurement live
illustration of exactly the coverage problem that **milestone 0 (§5) exists to
quantify**. It is one data point, not yet a statistic; *how much of the 0.094 meV is
bar-optimism versus a genuine resolution pull on the center* is precisely what the
σ-calibration campaign separates.

**TAVI payload gaps found (feed these to TAVI follow-ups).** The `tavi` plugin
currently fills these from card constants because the API does not expose them, and
each is a candidate for per-scan truth in the payload: **sample temperature**,
**mono/ana/sample mosaics** (`ETAM`/`ETAA`/`ETAS`), **scattering senses**
(`SM`/`SS`/`SA`), **vertical collimations** (`BET1..4`), and **sample selection**.
(The horizontal collimations `ALF1..4` *are* in the payload as
`collimation.alpha_1..4` and are used directly.)

---

## 8. Roadmap (dependency-ordered) and open questions

The driver's own phased roadmap is `LLM_HARNESS_DESIGN.md` §9; the TAVI-side
primitives it consumes are ordered in `CONTROL_FEATURES_DESIGN.md` §9. This is the
**system-level** ordering across all three repos.

**Phase 0 — σ-calibration campaign (§5).** Known-ω scans across q and `number_neutrons`
→ empirical coverage curve → inflation factor. First, because every later convergence
decision depends on it — and it also pins down the resolution-pull question raised by
the §7 punchline. Deliverable to ISAR as well.

**Phase 1 — acquisition engine.** Developed offline against ISAR's `isar/synth`, then
against the TAVI **deterministic tier** (tier 1). Needs TAVI `GET /resolution`
(`CONTROL_FEATURES_DESIGN.md` §5) → the deterministic engine (§6 there). The
statistical core is provable before any instrument is involved.

**Phase 2 — instrument client + MCP tool surface.** The TAVI API consumer and the
ISAR file readers, exposed as MCP tools (instrument tools + `get_dispersion_prior` /
`get_scan_verdicts` / `run_isar_batch`). **Compose with the existing `tas-mcp`**
server for client-side TAS math; do not duplicate it.

**Phase 3 — LLM supervisor + MVP adaptive dispersion campaign** on the Monte Carlo
tier (tier 2), scored against a uniform-grid baseline. This is where goal→spec, the
stopping criterion, and exception handling first run end to end on realistic data.

**Phase 4 — benchmark publication-grade scoring + real-instrument (NICOS) adapter.**
The two-score benchmark (§4) in Table-1 format, then the adapter that swaps the
instrument client for tier 3.

### Open questions (system-level)

- **Acquisition model** — Gaussian process over ω(q) (smooth, principled uncertainty,
  a kernel to choose) vs. local linear fits (cheap, matches ISAR's own prior builder,
  weaker far from data). Lean: start local, move to GP if path curvature demands it.
- **Multi-branch assignment near crossings.** Per-scan fits are ISAR's; **branch
  *assignment* is a driver concern** — ISAR does not label which branch a peak belongs
  to. How does the acquisition engine keep two ω(q) models separate near an
  acoustic/optic crossing?
- **Campaign batching vs. one-at-a-time** — one scan per loop (maximally adaptive) vs.
  a small batch (fewer ISAR invocations, staler decisions).
- **When ISAR grows a query API** — the file contract is stable and restart-safe, but
  re-running `isar run` every loop has a fixed cost; at what campaign size does a
  query interface earn its keep?
- **Where the driver repo lives.** *Superseded 2026-07-06:* the driver lives
  in the ISAR repo as `isar/drive/` (an `isar drive` CLI subcommand). The
  analysis boundary is enforced by rule: `isar.drive` consumes analysis only
  via the `isar run` subprocess and the file contract (`report/results.csv`,
  `report.json`, `card.state.json`), never by importing fit internals.
- **How the virtual clock's counting-time model maps to real count rates** — the
  simulator's `number_neutrons` is a budget, not a flux; the mapping to a nominal
  neutron/s on a real instrument is an open modelling choice
  (`CONTROL_FEATURES_DESIGN.md` §7.5).

---

## 9. Read this, then that — a map across both repos

A new collaborator should read in this order:

1. **This document** (`docs/CLOSED_LOOP_DESIGN.md`) — the whole system: why three
   components, the boundary, why TAVI can score the loop, and the first evidence.
2. **`docs/LLM_HARNESS_DESIGN.md`** — the driver (component 3) in detail: the three
   parts, the ISAR file contract, milestone 0, the MVP worked example.
3. **ISAR `docs/READING_GUIDE.md`** — the front door to the analysis component: what
   ISAR is, what it deliberately is not, and how it is validated. Then ISAR's
   **`DESIGN.md`** §1–§2 (purpose, the six core principles incl. P1/P3) and
   **`docs/STATS_PRIMER.md`** (why the σ caveat of §5 exists).
4. **`docs/CONTROL_FEATURES_DESIGN.md`** — the TAVI-side primitives the loop needs:
   §0 (the control/analysis boundary), §5 (resolution), §6 (deterministic engine),
   §7 (virtual clock), §8 (point-list scans).
5. **`docs/API_USER_GUIDE.md`** §1–§2 — the live control surface the driver drives
   (endpoints, the parameter table, scan grammar, the paste-in operator block).
6. Reference as needed: ISAR `docs/UNIFICATION_DESIGN.md` (how ISAR assembles into a
   runnable `isar` CLI, the card/ledger/`results.csv` contract, R8 on TAS Γ),
   `docs/API_SERVER_DESIGN.md` (the API architecture), and the Teixeira Parente et al.
   2022 paper in the ISAR `docs/` (the benchmark framing of §3a and §4).

---

*Draft — 2026-07-03. The seam is live (§7); the driver is designed
(`docs/LLM_HARNESS_DESIGN.md`) but not built. This document records the reasoning;
the companions record the decisions. Keep them in sync — when a decision here is
superseded, update the companion and note it here.*
