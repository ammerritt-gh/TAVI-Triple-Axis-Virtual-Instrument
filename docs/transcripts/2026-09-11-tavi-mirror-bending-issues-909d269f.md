# TAVI mirror bending issues

**Date:** 2026-09-11  
**Session:** 909d269f-7f6c-4765-873c-09db834b8878

*Cleaned transcript: tool calls, tool results, thinking and harness notices removed. Nothing else edited.*

## User

I believe there were some lingering issues in TAVI from the last work on the other instruments, centered around mirror beniding? What's pinned?

## Assistant

*adjusts glasses, pulls the TAVI drawer open without being asked twice*

Mm. You remembered correctly — and it's a little worse than what's written down. Let me give you the ledger first, then the part that isn't in it.

## What's pinned (recorded deferrals)

Three places carry it, all pointing at one repair:

1. [TODO.md:128-139](TODO.md#L128-L139) — *"Instrument evidence still needing an instrument scientist"*: IN12's monochromator curvature minima (1.7 m / 0.5 m, **provisional model assumption**, binds above ~|A1| = 32°, so it changes emitted geometry); PANDA's and IN12's analyser vertical curvature *radius* (fixedness evidenced, value not); IN8's mechanical min/max radii (none applied).
2. [instruments/panda/MODEL_STATUS.md:114](instruments/panda/MODEL_STATUS.md#L114) — the Ideal-radii row, explicitly *"Deferred deliberately to one comprehensive cross-instrument repair… because the fix changes IN8's numbers too."*
3. [instruments/in8/MODEL_STATUS.md:110-116](instruments/in8/MODEL_STATUS.md#L110-L116) — the same thing filed as a *"GUI wart (code follow-up, not data)"*, plus [docs/CONFIGURABLE_INSTRUMENTS.md:1489-1493](docs/CONFIGURABLE_INSTRUMENTS.md#L1489-L1493) calling it *"mildly wrong… advisory labels."*

## Literal pinned values

| | rva source | mono clamps declared |
|---|---|---|
| PUMA | `0.8` in `scan_config` | rhm≥2.0, rvm≥0.5, rha≥2.0 |
| IN8 | `-0.31` PLACEHOLDER | none (unknown) |
| IN12 | `-ANA_FIXED_RV` = −1.40 m, declared `fixed_curvature=("rva",)` on PG(002); Heusler deliberately *not* pinned | 1.7 / 0.5 provisional |
| PANDA | `-0.60`, `fixed_curvature=("rva",)` on PG(002) | none (confirmed absent from literature) |

Those pins are sound and evidence-tagged. The clamps are the problem.

## The part the docs get wrong

`calculate_crystal_bending` — the correct, branch-signed, per-instrument physics in all four `model.py` files — **has zero production callers.** Only the model definitions, one comment at [instruments/in12/plugin.py:394](instruments/in12/plugin.py#L394), and four test files reference it. Every scan's magnitudes come from `vals['rhm'/'rvm'/'rha']`, and those are produced by PUMA's parallel-beam formula in two hard-coded copies:

- [TAVI_PySide6.py:2831-2893](TAVI_PySide6.py#L2831-L2893) — `_compute_ideal_bending_values` (GUI)
- [TAVI_PySide6.py:5137-5168](TAVI_PySide6.py#L5137-L5168) — `_ideal_bending_from_modules` (API), called from `_default_parameter_values` ([:5242](TAVI_PySide6.py#L5242)) **and** re-run on every `mtt`/`att`/`modules` patch that doesn't pin radii ([:2563-2573](TAVI_PySide6.py#L2563-L2573))

So PANDA's "**Scans and the API launch path are unaffected**" is not true. `scan_config` only applies the *sign*; the magnitude is PUMA's. Concretely: PANDA and IN12 take off negative at both crystals, every ideal radius comes out negative, every clamp fires, and the API hands the launch `(2.0, 0.5, 2.0)` → `(−2.0, −0.5, −2.0)` **at any angle**, instead of PANDA's `(3.985, 1.787, 1.651)`. IN8 gets a parallel-beam mono (should be point-source, `1/L1+1/L2`) and a clamped `rha = 2.0`. And IN12's own 1.7 m clamp never runs — PUMA's 2.0 does.

Second-order: [instruments/resolution_adapter.py:200-203](instruments/resolution_adapter.py#L200-L203) feeds those same `vals` radii into Cooper–Nathans/Popovici with `rva: None`, so the resolution ellipsoid ISAR cross-checks against inherits the same numbers and assumes a flat vertical analyser everywhere.

Mitigating: a fresh **GUI** session starts at `rhm_var = 0` (flat) with the Ideal buttons unlocked ([:3062-3073](TAVI_PySide6.py#L3062-L3073)) — so it's flat-wrong rather than PUMA-wrong until someone locks a button. The **API** has no such escape; its defaults are computed.

## Where I'd take it

This is one repair, roughly T2: delete both hard-coded copies, route them through `state.calculate_crystal_bending(1, 1, 1, mtt/2, att/2)`, and let each model own its own clamps and `rva`. It changes emitted geometry for IN8, IN12 and PANDA, so it wants angle-golden updates and a smoke run per instrument — and it flushes out the honest question of whether `rva` should stop being hard-coded in `scan_config` now that `fixed_curvature` exists to declare it.

I haven't touched anything. Say the word and I'll size it properly and open a branch — or if you'd rather I just correct the three documentation claims that call this "advisory" and "unaffected" first, that's a ten-minute slice on its own.

## User

rva isn't particularly special on its own, so we can't assume that another instrument or even another crystal on the same instrument will behave the same way. We have to be general. I'll let you plan out the repair approach then, at T2, and get feedback on it first.

## Assistant

Discovery is done and it turned up more than the docs record. Writing the plan now, then sending it to the critic and panel seats before I put it in front of you.

LLMM is down, so the panel seat is unavailable. Dispatching the plan-verifier (the descriptor is a public contract, so that pass is required) and the external reader while Codex critiques.

Plan is written and three seats are in flight. Discovery turned up two things beyond what you asked about, both in the same family — I'll fold them into the briefing rather than spend your attention twice.

Waiting on the Codex critic and the plan-verifier now; the external reader is a ~20-minute ticket. Full briefing when the first two land.

The Codex critic came back with five objections, all landing. Two of them are material — one names a regression my plan would have introduced. Folding them in while the plan-verifier finishes.

Plan-verifier returned REVISE with three blockers — including a factor-of-two trap I had walked straight into. Computing the pinned reference table it asks for.

*sets the folder down, one finger still holding the page*

Plan's ready, and it survived a rougher morning than I expected. Nothing touched in the repo — `main` is clean, no worktree yet. That waits on your yes.

## The frame

You said rva isn't special, and following that through is what makes this tractable. A TAS crystal has up to four curvature axes, and each one is independently driven, fixed, or flat — that's a property of *the assembly*, not the instrument. TAVI already half-knows this: `fixed_curvature` is declared per crystal, precisely because IN12's PG(002) analyser has a fixed vertical focus and the Heusler on the same instrument doesn't. What it carries is only *fixedness* — never the value, never the mechanical limits. So the values live scattered in four `scan_config` literals, the limits in a third place, and the actual radii come from PUMA's formula.

Two observations shrink the repair from sprawl to something small:

**One formula.** PUMA's "parallel beam" *is* the point-source formula with the object distance at infinity — `1/(1/∞ + 1/L)` = `L`, giving exactly PUMA's `2L/sin θ` and `2L·sin θ`. So one formula parameterised by an (L_in, L_out) pair per plane covers all four instruments, and PUMA's modelling claim about its guide becomes a declared infinity instead of a buried formula variant.

**One sign rule.** `Sense`'s enum value already *is* the sign of that axis' two-theta readout, and the curvature centre must sit on the take-off side. So a monochromator axis takes `sense_mono`, an analyser axis `sense_ana`. I checked it against all four: PUMA (+1,−1,+1) → positive radii, matching its unsigned passthrough; IN8 (+1,+1,−1) → mono +, ana −; IN12 and PANDA (−1,+1,−1) → all negative. It reproduces every existing sign from data already declared — and supplies the one IN8 is missing.

So: **the crystal declares policy, the model owns the optics, the sense gives the sign, and nothing else invents a radius.**

## Two more things discovery turned up, same family

**IN8's scanned `rha` is on the wrong branch.** The sign has two homes — each plugin's `scan_config` for the normal path, and a `set_crystal_bending` override for the *scanned* path, which reaches the model directly through `compute_scan_snapshot`. IN12 and PANDA have that override. IN8 doesn't. Scan IN8's `rha` and you get a positive radius on a negative take-off branch — the ~7-orders-of-magnitude defocus you measured in the Phase-4 smoke.

**Recorded curvature disagrees with what ran.** `compute_scan_snapshot` writes metadata from the pre-setter local but builds the McStas parameters from the signed state. For a scanned axis on IN12 or PANDA, the provenance record carries a positive radius while the simulation ran a negative one.

Both are live now, neither is introduced by this work, and both sit on lines the repair touches — so they get fixed in scope.

## What the seats did to it

**Codex critic: five objections, all adopted.** The one that matters: I had planned to enforce fixedness inside the ideal-radius producer. But a typed value, an API patch, and a scanned radius all reach the model *without* passing through it — today PANDA's fixed `rva` survives that only because the plugin literal overwrites it unconditionally. Deleting the literals while enforcing only at the producer would have let an explicit value defeat fixed hardware. **That's a regression I would have shipped.** Enforcement moves to `set_crystal_bending`, the one boundary all three paths cross, and lands a slice *before* the literals go. It also caught that the API delegation never receives the selected crystals, so an isolated Heusler job inherits PG's policy.

**Plan-verifier: REVISE, three blockers, all adopted.** It found that my acceptance couldn't be executed — only PANDA records ideal radii anywhere, and all three existing bending tests recompute the formula under test, so they'd pass against any policy the implementation adopted. Tests that can't fail. It also caught a trap I'd walked into: the two producers I'm deleting take **two-theta and halve it**, while `ideal_curvature` takes theta *already* halved and signed. A factor-of-two at the new call sites is exactly what a Monte-Carlo intensity check masks.

So the plan now carries a pinned reference table, derived from declared arm lengths rather than from the new code:

| | mth | ath | rhm | rvm | rha | rva |
|---|---|---|---|---|---|---|
| PUMA | +20.5835 | +20.5835 | +13.0272 | +1.6102 | +2.3034 | +0.8000 *fixed* |
| IN8 | +20.59 | −20.59 | +6.7556 | +0.8355 | −2.3885 | −0.2954 *driven* |
| IN12 | −27.9172 | −27.9172 | −3.8445 | −0.8428 | −1.9794 | −1.4000 *fixed* |
| PANDA | −37.166 | −37.166 | −3.9848 | −1.7869 | −1.6511 | −0.6000 *fixed* |

PANDA's row reproduces the (3.985, 1.787, 1.651) its MODEL_STATUS records as correct — independent confirmation the generalised formula is the same physics. A deterministic test against these literals is now the gate on the geometry-changing slice; the McStas runs are corroboration, not proof.

**Panel: unavailable** — LLMM is down (ConnectTimeout on 127.0.0.1:8766). No retry, per the degradation rule. **External reader: still out**, ticket `67197a7b83aa`, ~20 minutes; I'll fold its findings in before the first edit.

## Five commits

Descriptor + all four packages' declarations in one commit (they can't split — `CrystalSpec` is frozen/slots and two live call sites pass `fixed_curvature=`, so a declaration-only commit would leave the tree red) → model, with policy enforcement → plumbing, *this is the one that changes emitted geometry* → GUI `rva` surface → resolution adapter and the documentation corrections.

## Two decisions that are yours

**IN8's `rva = −0.31`.** It's a stated placeholder on an axis the Thermes analyser genuinely drives — variable double-focusing. The honest declaration is *driven*, which makes it track kf instead of sitting at one value. At IN8's reference setting the difference is −0.2954 against −0.31, so it barely moves at kf = 2.662 — which is unsurprising, since −0.31 was derived as the point-source value for exactly that kf. Away from it, the numbers diverge. The alternative is declaring it fixed at −0.31 with a placeholder provenance, preserving current behaviour and current wrongness. **I've planned for driven.** It's your call because it changes physical model behaviour, not code structure.

**Whether the limits ride along.** The per-axis spec I've drawn carries the mechanical min/max as well as the fixed value. A cheaper variant carries only the value and leaves the limits as module constants in the models — about one slice less work, but IN12's monochromator minima would remain inheritable by a future second monochromator crystal on a different bender. That's the Heusler failure exactly, one axis over. The critic pushed a level deeper and asked whether limits belong on the *crystal* at all, since a bender is a mount and the same crystal can sit on different ones — I think per-crystal is right for now because it's where the evidence attaches, and I've left a `curvature_limits` hook rather than building angle-dependent machinery nobody needs yet. **I've planned for the full per-axis spec.** Worth your objection if you see the mount distinction biting sooner than I do.

Third, smaller: the smoke runs are four compiled McStas runs, serial, one at a time with the console guard active. Say if that's not a budget you want spent today.

Plan's at `scratchpad\plan-bending-repair.md` if you want the whole thing rather than my summary of it. Say go and I'll open the worktree — and I'll hold the first edit until the ChatGPT reader lands, since it's the seat most likely to tell me the sign rule is a coincidence rather than a theorem.

## User

Harvest the ChatGPT review now

## Assistant

Verified the three load-bearing claims against the code before dispositioning. Two of them break parts of my plan, and one breaks something I told you.

*takes her glasses off, folds them, sets them on the page*

Harvested. It was worth the wait, and I'd rather hand you this now than after I'd written code against it. **Nothing edited. `main` is clean, no worktree.** And I'm recommending we stop and re-tier rather than proceed.

## First, a correction to what I told you

The API does **not** normally hand PANDA `(2.0, 0.5, 2.0)`. I checked and the reviewer is right: `_default_parameter_values` starts *every* instrument at PUMA's reference `mtt = att = +41.167°` and computes there. The angles are positive, so the clamps never fire. PANDA's actual API default is `(11.9463, 1.4766, 2.8373)` — I reproduced it exactly. The clamp-to-minima story is the **GUI** path with the Ideal button locked at negative angles, which is real but narrower than I said.

The truth is worse, just differently. The recompute trigger is `('mtt', 'att', 'modules')`. An ordinary H/K/L request — exactly what ISAR sends — never recomputes, and `compute_scan_snapshot` solves the real per-point angles but never revisits curvature. So **API curvature is frozen at a reference geometry that has nothing to do with the scan, and carried through the whole campaign unchanged.** Not a clamped-wrong number: a plausible-looking number computed for a different instrument's default setting.

## Two blockers that kill parts of my design

**My sign rule was wrong, and backwards.** `_solve_point_geometry` has a direct-angle mode where A1–A4 come straight from the scan values, and PANDA's declared A4 limits are `AxisLimits(-130.0, -74.332, 100.0)` — both signs legal. A legal point at A4 = +40° needs a *positive* analyser radius; multiplying by `sense_ana = −1` would defocus it. The authoritative sign is the actual local take-off angle — which is exactly what all four existing `calculate_crystal_bending` implementations already do via `sin θ`. I proposed replacing correct per-point physics with a static declaration. Dropped; sign comes from `sign(sin θ)` at the point, and `Sense` becomes an invariant check rather than the source.

**Signed values would double-sign in the resolution model.** `tavi/resolution.py:320-323` already applies the sense itself — `monorh = radius_cm(cfg.rhm) * sm`, and so on, with the comment "sign-corrected by sense". Make `vals` signed, forward all four fields, and negative-branch instruments get signed twice. So: **magnitudes everywhere in the operator/API/descriptor contract; signing only at the McStas boundary.** That also preserves what saved state and resolution provenance mean, which my version silently changed.

## Why I want to stop rather than push on

Three things surfaced that aren't implementation details — they're decisions we live with, and one of them decides how big this is.

**Does a driven axis autofocus?** "Driven" is currently collapsing three different things: an actuator exists, the operator may command or scan it, and TAVI follows the ideal radius as the angle changes. Today the third is *no* — curvature freezes at launch state while `mtt`/`att` move point by point. That's coherent if driven means "motorised, set where you put it." It's a bug if the Ideal lock is meant to mean autofocus. The physics matters more than the code here: in a fixed-kf energy scan the monochromator take-off sweeps while the analyser sits still, so the mono's ideal curvature genuinely changes across the scan and the analyser's doesn't. What do the real instruments do — does PANDA's monochromator bender track during an E-scan, or does the local contact set it once at the start of a measurement and leave it? **This sets the tier.** If curvature holds, the repair is what I planned. If it tracks, curvature becomes a per-point computed quantity and that restructures the scan snapshot, the meaning of the GUI fields, and every resolution number ISAR reads.

**Crystal or installed assembly?** Both seats independently said the same thing, and the reviewer made it concrete in a way I can't argue with: PUMA's NMO makes the monochromator flat *regardless* of which crystal is selected. No static property of a crystal can express that. Teaching `CrystalSpec` that PG(002) intrinsically has a 1.40 m vertical radius repeats the mistake I'm fixing, one level down — PG doesn't have a bender, the mount does.

**"Undeclared" can't mean "driven and unlimited."** IN12's Heusler curvature is *unknown*, not known-driven. IN12's 1.7/0.5 minima are explicitly provisional model assumptions; PANDA's limits are confirmed absent from the literature. A field named `min_radius_m` sitting in a hardware-looking declaration would launder "conservative guess" into "mechanical limit" — precisely the distinction your MODEL_STATUS files work hard to keep. It needs an explicit unknown state and an evidence class on each number.

Plus a cross-repo consequence I hadn't named: ISAR takes `bragg.dE` from TAVI's `/resolution` to choose energy windows and step sizes. Giving the resolution model a real `rva` changes those numbers, so this moves closed-loop acquisition decisions in the other repo.

Three foundational decisions, an ontology choice, and a cross-repo numerical effect. That's T3, and the honest move under the re-tier rule is to stop before the first edit rather than keep building under T2 sizing. I'd like to take it through `/dialogue` — not a menu of options, an actual discussion, starting with the autofocus question because the rest hangs off it.

## Still open from the last round, repeated in full

**IN8's `rva = −0.31`** — a stated placeholder on an axis the Thermes analyser genuinely drives. Declaring it driven makes it track kf; at IN8's reference setting that's −0.2954 against −0.31, essentially unchanged, because −0.31 was derived as the point-source value for that exact kf. Away from it they diverge. The alternative preserves current behaviour and current wrongness.

**Four compiled McStas smoke runs**, serial, console guard active — now demoted to corroboration anyway, since the reviewer gave a better deterministic gate: a PANDA API H/K/L request driven end to end through `scan_config → compute_scan_snapshot → build_point_params`, asserting the exact signed parameters.

Seats this round: critic filled (Codex, 5 objections, all adopted), plan-verifier filled (REVISE, 3 blockers, all adopted), external reader filled (2 blockers, 1 correction to my evidence, 4 objections), panel **unavailable** — LLMM is still down on 127.0.0.1:8766, so that seat never ran. Worth knowing if you want it for the T3 discussion; I'd need it back up.

The full plan with every disposition is at `scratchpad\plan-bending-repair.md`. Say the word and I'll open the dialogue.

## User

LLMM is back up to check there. My thoughts:
Scanning changes it point-by-point (when you choose to scan the mirror itself over a range). Setting it keeps the same point. But the autofocus should track while scanning too, so if it hasn't been that's a failure; it changes during the measurement.
Generally "crystal" is the crystal + mount, they come as a package; we' wouldn't swap out the literal crystal material and leave the same bending motor.
If IN8 is tracking with the motor we should represent that.

## Assistant

He's settled the ones that mattered. Running the panel now that LLMM is back, against the revised design rather than the original.

Two nays — one of them is a physics objection to your autofocus ruling, which you should see before I build on it. Reading the full answers on refusal semantics and determinism.

*picks the glasses back up, slides them on — back to business*

Panel ran: five members, three yea, two nay. The dissent earned its seat. Still **nothing edited, `main` clean, no worktree.**

## Your three rulings, recorded

Autofocus tracks during the scan — so curvature becomes a per-point quantity whenever an axis is autofocusing, and the fact that it hasn't been is a defect. `CrystalSpec` stays the owner, because a crystal here is the crystal *plus its mount* as an installed package; that closes both the critic's and the reviewer's mount objection, and I'll put a docstring on it so nobody re-litigates it in six months. IN8's `rva` becomes driven.

That gives three modes per axis, carried in launch state as **one enum** shared by the GUI, the API and the scan loop — the panel was emphatic that having replaced three incompatible policy representations I must not create a fourth. AUTOFOCUS follows, HELD stays, SCANNED is driven by the command. *Fixed* isn't a mode — it's a property of the assembly that removes the axis from operator control, which is already enforced.

## The finding that justified the whole seat

Two members found it independently, from different angles: **if a mechanical limit clips the radius for the simulation while the analytic resolution model keeps the unclipped ideal, the counts and the resolution disagree — and in a headless ISAR campaign nobody sees it.** The fit is then made against a resolution function describing an instrument that didn't run. One applied value must feed both. That trap was sitting inside my own plan, since I had the clamps in the model and the resolution adapter reading from `vals`.

With it come three more I've adopted: an out-of-travel condition has to be **machine-readable in the API response** ISAR consumes, not a GUI log; **autofocus must be prohibited outright where there's no focusing evidence** — IN12's Heusler gets a disabled widget and an API error, never a silent fall back to flat, which also answers the "undeclared mustn't mean driven" objection properly; and per-point provenance records the mode and the radius actually applied, so an autofocusing axis is auditable afterwards.

I threw two findings out. One member argued "one producer can't be a single method", then described a parameterised producer with the subclass doing the geometry mapping — which is the proposal, and its instrument facts were wrong besides (it put PANDA's virtual source on the image side). Another warned the new axis changes the resolution matrix to 4×4; it doesn't — `ResolutionConfig` already declares `rva` and the matrix is 4×4 in (Qx,Qy,Qz,E) regardless. No ISAR schema break.

## One physics objection to your ruling, which you should hear

The strongest dissent says autofocus-per-point is **flattering rather than faithful**: a real bender has finite slew and hysteresis, local contacts often set focusing once per configuration, and TAVI's current freeze is arguably closer to floor practice. The sharp version is the closed-loop one — if TAVI refocuses instantly and the resolution model assumes the ideal was achieved, ISAR's fitter gets a self-consistent but optimistic instrument, and could favour trajectories that rely on curvature slews the real hardware can't make.

My read, for what it's worth against yours: all four of these instruments have motorised double-focusing driven with ki, so tracking *is* the faithful model for a fixed-kf energy scan — the whole point of the motor is that it follows. The slew objection is real but it's about the *cost* of the movement, which is the virtual instrument clock's job and already sits on `TODO.md` under closed-loop enablers; hysteresis is below this model's fidelity everywhere else too. So I'd let your ruling stand and let the clock own the time. But you know what the local contacts actually do at PANDA and IN8, and I don't — if focusing is set once per configuration there in practice, say so and I'll make tracking the declared-per-instrument behaviour instead of the universal one.

## Tier

The re-tier I proposed last round was triggered by three unresolved foundational questions. You've answered all three, so **the trigger has cleared and this stays T2** — one repo, one branch, one PR, with the ISAR numerical effect checked rather than changed. No ceremony for its own sake.

## Where it stands

Every seat is now filled: critic (5 objections, all adopted), plan-verifier (REVISE, 3 blockers, all adopted), external reader (2 blockers, 1 correction to my evidence, 4 objections), panel (3 yea / 2 nay, dissent escalated to you above). Budget footer says rung 1, 23% used, resets Monday.

Nothing is open except that one physics question, and it doesn't block — R1 stands unless you say otherwise. Say go and I'll open the worktree and start with the descriptor-plus-declarations commit.

## User

Yeah, please don't trust some random model's peanut gallery shout versus the guy with a PhD and Nature and Science papers in neutron scattering who works on the instrument. How do they know what the local contact does? HE sits across from me in the office, so...

## Assistant

You're right, and that's a calibration error on my part — I put a model's guess about floor practice up against the person who does the work. The panel can read the code; it cannot see your office. Struck, and R1 stands without qualification.

Recorded so it doesn't recur: seats are worth reading on code, contracts and mechanisms — things that live in the repository and that they can actually see. What happens on the floor isn't in the repository, and a model guessing at it isn't evidence to weigh against you. I'll report their findings about the code and drop their opinions about practice.

The dissent is closed in the plan as REJECT-because, so a later reviewer can't reopen it. The one salvageable fragment wasn't about practice at all — the *time cost* of moving a bender belongs to the virtual instrument clock on `TODO.md`, which is separate work this plan doesn't touch.

Worth saying plainly: the panel's useful output this round was entirely mechanical — the clamp desync between the simulation and the resolution model, the out-of-travel flag needing to be machine-readable for a headless campaign, and autofocus being forbidden where there's no focusing evidence. Those are contract facts, visible in the code. That's what those seats are for.

**Plan is fully dispositioned and nothing is open.** R1–R3 are yours and binding; every seat has run; `main` is clean and no worktree exists yet.

Five commits, in order: descriptor plus all four packages' curvature declarations in one commit (they can't split — `CrystalSpec` is frozen/slots and two live call sites pass `fixed_curvature=`) → the model, with one producer, the mode enum, and sign-and-limit policy at the application boundary → the plumbing, per-point autofocus in the scan loop, both PUMA formula copies deleted, `rva` real, one applied value feeding both McStas and the resolution model → the GUI `rva` surface → the resolution adapter and the documentation corrections, including the two docs that call this advisory-only.

Say go and I'll open the worktree and start on the first commit.

## User

Let's get cracking then.

## Assistant

Opening the worktree now. EnterWorktree can't target TAVI — it's a sibling repo, not nested under the session's primary — so it's a plain `git worktree add` outside the repo tree (TAVI doesn't ignore `.claude/`, so an in-tree worktree would dirty your main checkout).

Worktree is up on `crystal-bending-generality`, Pb map hardlinked so the skip count matches. Baseline suite running. Writing the first executor packet while it does.

Session latch is closed — you've approved implementation, so opening it.

Baseline running properly now. Waiting for the counts before I hand the executor a number to match — dispatching it against an unknown baseline is how a pre-existing failure gets blamed on the new commit.

Worktree is live and the packet is written. One thing worth flagging while the baseline finishes: PUMA's `MODEL_STATUS.md:17-18` marks *every* one of its curvature numbers provisional, sourced from "Legacy model comments", with its scientist-review question on bending limits still open. So the clamps that leaked into all four instruments were never evidence in the first place — they're legacy values wearing the authority of being hard-coded. I've put that in the packet so the provenance strings say it plainly.

Baseline is **973 passed, 0 skipped, 84.9 s** — the Pb hardlink worked, no silent skips. Dispatching the executor against that number.

**Round report — implementation started.**

**State.** Worktree `TAVI-wt-bending` is open on branch `crystal-bending-generality`, cut from `main` @ `cad751c8`. Your main TAVI checkout is clean and untouched. Baseline measured on the worktree before any edit: **973 passed, 0 skipped, 84.9 s**, exit 0.

Two mechanical notes worth having: `EnterWorktree` couldn't be used because TAVI is a sibling of this session's primary repo rather than nested under it, so it's a plain `git worktree add` placed *outside* the repo tree — TAVI doesn't ignore `.claude/`, so an in-tree worktree would have shown up as untracked in your main checkout. And the 143 MB `components/Pb_dft_phonons.dat` is a gitignored build product, so I hardlinked it into the worktree; without it `test_dispersion_map.py` would have skipped silently and the lane would still have read green. That's the ISAR junction trap wearing a different hat.

**Executor is running on slice 1** — the descriptor's per-axis `CurvatureAxis`, the validator, and all four packages' declarations in one commit. It won't commit; I'll review the diff and `review_files` it before anything lands.

One thing I found while writing its brief that changes the story slightly. I'd been describing PUMA's clamps as PUMA's *numbers* — as though the sin was applying one instrument's real limits to three others. `instruments/puma/MODEL_STATUS.md:17-18` marks every one of them **provisional, sourced from "Legacy model comments"**, with its own scientist-review question on bending limits still open. So 2.0 / 0.5 / 2.0 / 0.8 were never evidence for PUMA either. They're legacy values that acquired authority by being hard-coded and then leaked outward. The provenance strings will say so, which means the repair also stops PUMA quietly asserting limits nobody has confirmed.

Still open, nothing blocking: the four McStas smoke runs at the end of slice 3, which I'll ask before spending. Everything else is decided.

## User

Those PUMA limits are authoritative at least for the PG002 ana/mono, I checked them against the  instrument docs.

## Assistant

That changes the provenance, and the executor is writing those strings right now. Correcting it before it does.

Corrected mid-flight — the executor will get it at its next tool round, before it writes PUMA's strings.

Scoping it the way you did is exactly the case for per-assembly declaration, incidentally: your check authorises `pg002` mono and `pg002` ana specifically, and PUMA's menu also carries a `pg002_test` monochromator with a fabricated d-spacing of 2.355. That one is a test fixture and must not inherit hardware authority from its neighbour. Under the old tuple there'd have been nowhere to draw that line.

Two things I'd like from you, both one-liners:

**What should the provenance cite?** Right now it'll read "confirmed against PUMA instrument documentation, verified by the operator 2026-09-11". Naming the actual document — a manual, a drawing number, an MLZ page — makes it checkable by someone who isn't you, which is the point of the field. If it's an internal doc with no clean identifier, say so and I'll leave the attribution as-is.

**Does the same check cover the arm lengths?** `MODEL_STATUS.md:14` marks PUMA's L1–L4 (2.150 / 2.290 / 0.880 / 0.750) provisional from the same "legacy model comments" source. Those feed the focusing formula directly, so if your instrument-doc check covered them too, they should stop being hedged at the same time. Not in scope for this slice's code, but it's the same documentation correction later.

`instruments/puma/MODEL_STATUS.md:17-18` and its scientist-review question 3 are now stale — I've told the executor to leave them alone and flag the contradiction rather than edit docs in a declarations commit. The status-column change lands in the documentation commit at the end, where I can do it deliberately rather than as a drive-by.

## User

I can't 100% guarantee things for PUMA are right, but I did go through them carefully against our docs and talked with the instrument scientist, so they should be good.

## Assistant

That's the right register, and it's a category the field was built for — stronger than a legacy comment, weaker than something a stranger can look up. The provenance will read: *reviewed against PUMA's internal instrument documentation and confirmed in discussion with the instrument scientist (operator, 2026-09-11); not an independently citable published source.* No overstatement, and the next person can see exactly how much weight to put on it.

Two deliberate limits on how far I've carried your answer:

**I've applied it to the bending limits and the fixed 0.8 m analyser radius only** — the things you named. PUMA's arm lengths L1–L4 stay marked provisional, because you said "those PUMA limits" and I'm not extending a check to numbers you didn't name. They feed the focusing formula directly, so if your review did cover them, tell me and they close at the same time; if it didn't, they stay hedged, which is the correct outcome.

**Nothing here is a guarantee, and the field doesn't claim one.** That matters more than it sounds: this whole repair exists because 2.0 / 0.5 / 2.0 acquired authority by being hard-coded rather than by being checked. Writing down *how* they were checked is what stops the same thing happening to the next number.

Worth noting what your check actually did to the paperwork: `instruments/puma/SCIENTIST_REVIEW.md` question 3 asks whether PUMA's bending limits are correct, and `MODEL_STATUS.md:17-18` tags those rows *needs IS*. You consulted the instrument scientist — so that tag is satisfied and those rows close, rather than sitting open indefinitely. That's the lifecycle those tables were designed for, and I'll make the status-column change in the documentation commit at the end rather than as a drive-by now.

Executor has both corrections queued and is still working slice 1. I'll review its diff, run `review_files` on it, and report before anything commits.

Both your corrections landed verbatim in the executor's work, correctly scoped — the four PUMA curvature values carry your attribution, the arm lengths stay untouched.

I sent one further fix. The executor had written `pg002_test`'s provenance as "shares PG[002]'s mount/motor", which quietly asserts a hardware fact about a crystal that has no hardware — it's a fabricated d-spacing of 2.355 that exists to exercise code paths. Small, but it's the same failure in miniature: a provenance string has to be falsifiable by someone checking a document, and "mirrors PG(002)'s declaration for test coverage" can be checked against the file while "shares its mount" can't be checked against anything. Now phrased as the modelling choice it actually is.

Executor is still working the rest of slice 1 — the validator and the IN8/IN12/PANDA declarations. I'll review the diff, run `review_files`, and report before anything commits.

Fixed and verifying. Waiting on its suite run — I'll review the diff and run the per-slice review seat before anything commits.

Executor is done. Not taking its green at face value — re-running the suite myself while I read the diff.

Three Minor findings, no blockers. One of them is wrong and I want to check the other two against the code before I act on them.

Verified independently: **976 passed, 74.7 s, exit 0** — matches the executor's claim.

Dispositioning the three findings. One is wrong, two get documented rather than coded.

Declarations read honestly — scoped provenance, the stale MODEL_STATUS rows flagged in-line rather than edited, arm lengths explicitly excluded. Waiting on the verification run before committing.

Verification run in flight. Once it's green I'll commit and push slice 1, then brief you properly before starting slice 2 — that's the one with the single producer, the mode enum, and the enforcement boundary, so it's worth a look before I hand it off.

976 passed, exit 0, all instrument packages valid — confirmed after my edits, not just the executor's. Committing.

**Slice 1 is committed and pushed.** `15748c76` on `crystal-bending-generality`, 8 files, +335/−36.

**What landed.** `CrystalSpec` now carries `curvature: Mapping[str, CurvatureAxis]` — per axis: whether an actuator exists, the radius when it doesn't, the mechanical travel when it does, whether any focusing model is established, and where every number came from. `fixed_curvature` survives as a derived property so the scan validator and GUI read it unchanged. The validator refuses a declared radius with no provenance, which is the rule that makes the field mean something rather than decorate.

All four packages declared, each carrying its real evidence class: your PUMA PG(002) review, IN12's 1.7/0.5 as a provisional model assumption, PANDA's limits as confirmed absent from the literature, IN8's as unknown. No behaviour change — `scan_config` still reads its own literals.

**Verification, run by me and not taken on report.** 976 passed, 0 skipped, exit 0, against a 973/0 pre-change baseline on the same worktree; the +3 is four new validator tests minus one replaced by a consolidated one. `instruments.package_validation` reports all four packages valid.

**The review seat found three Minor issues, no blockers.** I adopted two as documentation rather than code and rejected one:

- *Mutable dict inside a frozen dataclass* — real, but the suggested `MappingProxyType` fix would have been worse: a proxy can't be deep-copied, and launch state crosses the job-queue seam by `copy.deepcopy`. Trading a theoretical mutation for a real crash at the seam is a bad trade, so it's documented with that reasoning instead. Descriptor factories rebuild on every call and nothing hashes a `CrystalSpec`, so a stray write can't outlive its caller.
- *Alphabetical vs declaration order* — no consumer depends on order; alphabetical is the more stable guarantee. Documented so nobody starts depending on it silently.
- *"Reject radius == 0"* — **wrong, rejected.** Zero means flat, which is the repo-wide convention: `resolution.py`'s `radius_cm` maps 0 to `_FLAT_RADIUS_CM`, and McStas reads a zero radius as an unbent crystal. Applying that fix would refuse a truthful declaration of flat hardware. The reasoning is now a comment at the check so it isn't re-raised.

**One thing carried forward deliberately.** IN8 now declares `rva` driven while `scan_config` still pins the −0.31 placeholder. That divergence is intentional and recorded in the commit message; the slice that introduces the single producer resolves it. It's the one place where the declaration and the running code currently disagree, so it's worth knowing it exists rather than discovering it.

Next is slice 2 — the single producer, the three-mode enum, and policy enforcement at `set_crystal_bending`. That's the one that starts changing emitted geometry for IN8's scanned `rha`, so I'll show you the shape before handing it off rather than after.

## User

Ok, let's continue.

## Assistant

Slice 2 is where the sign rule becomes code, so let me pin the angle convention against the source before I write the brief — this is exactly where the factor-of-two trap lives.

Angle convention confirmed against source: `A1`/`A4` are **two-theta**, signed; the Bragg angle is `A/2`, and that's what the models' bending math already takes. That's the factor-of-two the plan-verifier warned about, and it's now pinned in the brief.

One thing the check changed: `scan_config` assigns radii as plain attributes, so it never passes through `set_crystal_bending`. The setter is the common boundary for the *scanned* path only until slice 3 routes the rest through it — so slice 2 fixes IN8's scanned sign and leaves the launch path on its existing literals, which keeps the two consistent.

Slice 2 is running. The brief pins three things that the tests can't catch on their own:

**The angle convention**, verified against source rather than assumed — `A1`/`A4` are two-theta, the Bragg angle is `A/2`, and the code being deleted does the halving itself while the new API takes theta already halved. That's the plan-verifier's factor-of-two trap, and it's invisible to everything except the pinned table.

**The sign comes from the local take-off angle, never the declared sense** — with the counterexample spelled out, since PANDA's `A4` range legitimately spans both signs and a point at +40° needs a positive analyser radius.

**The pinned table is the specification.** If the implementation disagrees with a row, it reports and stops rather than editing the table to match — and PANDA's row is independently corroborated by its own `MODEL_STATUS.md`, so a disagreement there means the code is wrong, not the table.

One thing I decided while writing it and want on the record: an out-of-travel radius gets **clamped and logged** in this slice. That's right for an automatically chosen ideal and wrong for an explicit command, which should become a refused point rather than being quietly rewritten — the panel was firm on that, and it's a genuine trap for a headless campaign. But the distinction needs the per-axis mode that slice 3 introduces, so this slice carries it as a commented interim with the upgrade path named, rather than pretending the question isn't there.

Expected behaviour change, and the only one: IN8's scanned `rha` flips negative. Everything else stays byte-identical because `scan_config` keeps its literals until slice 3.

Pinned table matched on first run, all four rows — that's the strongest signal yet that the generalisation is the same physics. Two of its flagged decisions need my judgement rather than a rubber stamp.

Only one production caller of that setter, always after the solve — so the degenerate-angle path is effectively unreachable and its reading is fine. The NMO gap is not fine; it's a regression staged for slice 3.

Sent it back for one addition. The rest of its work holds up.

**What I accepted.** Its degenerate-angle reading — I checked the callers, and `compute_scan_snapshot` at `tas_runtime.py:821` is the *only* production caller of that setter, always running after the geometry solve. So the zero-angle branch is unreachable outside an infeasible point whose parameters are never built. It also correctly spotted that two pre-existing idempotency tests were asserting through that degenerate path by accident, so they were testing nothing about signing; setting real angles in them makes them meaningful rather than making them pass.

**What I sent back.** It left PUMA's nested-mirror-optic case unimplemented, reasoning that nothing calls the producer live yet. True today, wrong for tomorrow: slice 3 routes the Ideal button through exactly this producer, and when an NMO is installed PUMA's ideal monochromator radii are *flat* — both `TAVI_PySide6.py:2853-2858` and `puma/model.py:190` do that today. Without NMO-awareness in the producer, slice 3 would silently hand PUMA-with-an-NMO a bent monochromator where it has always had a flat one. A `modules` parameter that nothing honours is precisely the kind of trap this repair exists to remove, so it closes now rather than becoming a bug two slices out.

Worth noting the headline result, though: **all four pinned rows matched on the first run**, PANDA's included — and PANDA's is independently corroborated by its own `MODEL_STATUS.md`. That's the generalisation confirming itself. One formula parameterised by object and image distance really does reproduce four instruments' hand-written focusing laws, including the parallel-beam case as the infinite-object limit. The IN8 sign fix also came in red-first as asked: `assert 1.65 == -1.65` before, passing after.

My independent run on slice 2 as it stood: **986 passed, 0 skipped, exit 0** — confirming the executor's count (+10 over slice 1's 976, being nine new producer tests plus the IN8 sign test). That was the pre-NMO state; the executor is now adding the PUMA nested-mirror-optic case, so I'll re-verify once it returns rather than treat this as the final number.

Waiting on it, then `review_files` and the commit.

Good catch by the executor — PUMA's own declared minima would have clamped the flat override back up to 2.0 m. But that raises a consistency question between the two places that clamp.

Found a real defect the suite doesn't catch. The flat sentinel is honoured in `ideal_curvature` (line 397) but **not** in `set_crystal_bending`'s clamp block (236-250) — so `set_crystal_bending(rhm=0.0)` on PUMA clamps a commanded flat monochromator up to 2.0 m. That path is live: PUMA with an NMO fitted and the Ideal button locked stores `rhm=0`, and `compute_scan_snapshot` feeds it straight back through the setter. Today's identity setter leaves it alone, so slice 2 would introduce exactly the regression it just fixed, one path over.

Waiting for the in-flight run to finish before I touch the tree — editing underneath a running suite just produces a result neither of us can trust. Then I'll fix the clamp inconsistency and add the test that would have caught it.

Confirmed independently: **989 passed, exit 0**. Now the clamp fix — one rule, both enforcement points.

13 passed — but a fix's test has to be shown red first, so let me prove it actually catches the bug rather than merely passing.

Red-first proven: with the zero guard removed, three tests fail including the new one; restored, all 13 pass. Running the full suite and the review seat together.

**990 passed, all packages valid, exit 0** — confirmed after the clamp fix. The review came back much heavier this time: six findings, four Major, and it directly answered the question I put to it about the two enforcement points disagreeing.

Dispositions applied, verification running. How the six findings landed:

**Fixed (3).** A fixed axis with no declared radius now raises a message naming the crystal and axis, instead of letting `copysign(None, …)` throw `TypeError` three lines later — the producer and the applier disagreed on that case and the producer was the one that crashed. A missing crystal selection now logs a warning rather than silently skipping policy enforcement. And the sign log fired on any magnitude change, so a clamp was reported as "signed from X to Y"; it now fires only on an actual sign change.

**Rejected, with the reasons written into the code (3).**

*"Use a tolerance instead of `sin(theta) == 0`."* Wrong, and it would break something real. Exact zero is the sentinel for "`set_angles` never ran" — the only case with no branch to sign onto. A tolerance would capture a legitimately small take-off angle whose branch is perfectly well defined, and bending is exactly where that matters. Its companion suggestion — fall back to the declared sense — contradicts the ruling the slice exists to enforce.

*"The two methods use different angle sources."* Real, and intentional. They answer different questions: apply-at-current-geometry versus what-would-the-ideal-be-at-these-angles. A caller asking the producer about a hypothetical point must not get an answer signed by wherever the instrument happens to be standing. Now documented so the next reviewer doesn't re-raise it.

*"PUMA's `!= "None"` NMO check is too loose."* True in isolation, but that idiom is the established one at three other sites including `puma/model.py:190`. An allow-list in one place would be a new inconsistency, and it would fail closed if a future NMO type were added — silently disabling the flat monochromator, which is the failure this override exists to prevent.

Both Major findings that survived were about the two enforcement points disagreeing — the exact thing I asked the seat to look hardest at, and the second such divergence today after the clamp bug I caught myself. That's a sign this shape genuinely wants one place, and it's worth remembering when slice 3 adds a third caller.

**Round report — slice 2 committed and pushed.**

**State.** Branch `crystal-bending-generality` at `0528b4c8`, two commits in. Your main TAVI checkout is clean, and `git merge-tree` confirms no conflict with `main`. Verified by me, not on report: **990 passed, 0 skipped, exit 0**, all four instrument packages valid.

**What landed.** `TAS_Instrument` now owns the whole curvature story. `curvature_object_distances` declares each focusing plane's object and image distance, `optical_radii` turns those into magnitudes and is the single method a differently-shaped instrument overrides, `curvature_limits` is the seam for an angle-dependent bender, and `ideal_curvature` reads the assembly's declaration — holding a fixed axis at its declared radius, clamping a driven one, and refusing an axis with no established focusing model rather than inventing a number for it. All four per-model `calculate_crystal_bending` implementations and both setter overrides are gone.

`set_crystal_bending` is now the one place policy gets applied, which matters because the scanned path reaches the instrument through it without touching `scan_config` at all. That's what fixes IN8: its scanned `rha` now lands on the negative branch, shown red first at `assert 1.65 == -1.65`.

**The result worth telling you.** One formula reproduced all four instruments' hand-written focusing laws, first run, no adjustment — including PANDA's row matching the `(3.985, 1.787, 1.651)` its own `MODEL_STATUS.md` records. The parallel-beam case really is the point-source case with the object at infinity, so PUMA now *declares* that infinity instead of hiding it in a formula variant, and IN8 and IN12 need no override whatever.

**Two bugs found that no test caught.** I caught the first: the flat sentinel was honoured where a radius is produced but not where one is stored, so PUMA with a nested mirror optic would have had its deliberately flat monochromator clamped back up to 2.0 m by PUMA's own declared minimum — the same regression the NMO override exists to prevent, one path over. Both clamp sites now share a helper. The review seat caught the second: a fixed axis with no declared radius crashed the producer with a `TypeError` from `copysign(None, …)` while the applier handled it. Both were divergences between the two enforcement points, which is precisely what I'd asked it to look hardest at.

I rejected three of its six findings with reasons written into the code, the sharpest being a proposal to replace the exact `sin(theta) == 0` check with a tolerance — that check is the sentinel for "angles never set", and a tolerance would misclassify a legitimately small take-off angle whose branch is perfectly well defined.

**Carried forward.** An out-of-travel value still clamps. That's right for an automatically chosen ideal and wrong for an explicit command, which should be refused rather than rewritten — it needs the per-axis mode, so it's a commented interim with the upgrade path named.

**Next is slice 3, the big one.** It deletes both PUMA-formula copies, routes the GUI and API through the producer, makes `rva` a real value, adds per-point autofocus so a driven axis actually tracks during a scan, and makes an out-of-travel command refuse rather than clamp. It's the slice that changes emitted geometry on all four instruments, gated by the end-to-end PANDA H/K/L test rather than by the McStas runs. That's also where I'll need your answer on spending the four smoke runs.

## User

Alright, let’s work on slice 3.

## Assistant

Slice 3 as planned needs the word "and" in its commit message — it routes every path through the producer *and* adds per-point autofocus *and* changes refusal semantics. That's three coats. Splitting it into 3a (route everything through the one producer) and 3b (autofocus, modes, refusal) — each independently revertable, and 3a's blast radius is enough for one commit to carry alone.

## User

What do you need for the smoke runs?

## Assistant

Answering the smoke-run question first, with real numbers rather than a guess — let me check what one actually needs in this worktree.

Found the recipe and — better — the recorded reference numbers, so a smoke run is a real comparison rather than just "does it execute". Let me check the console-window guard before I answer, since that's the part that has bitten you before.

Short answer: **just your wall-clock budget.** The thing I was going to ask you for turns out to be already solved in the repo.

**The console hazard is handled.** `docs/INSTRUMENT_AUTHORING.md:115-118` spells it out: a smoke script runs *outside* pytest, so it doesn't inherit the repo-root `conftest.py` guard, and it must call `install_no_window_guard()` before touching McStasScript or every instrument construction opens a console window on your screen. That's the thing that buried your desktop, and it's a documented one-line call, not something I need from you.

**A smoke run is better evidence than I'd been crediting it.** It's not just "does it execute" — there are recorded reference numbers on `main` from 2026-09-09, driven through the production path (`build` → `compute_snapshot` → `run_point`), Al (2,0,0) elastic, 1e7 neutrons, collimators open, ideal focusing:

- IN12 — `detector_I = 4.21e-07`, `detector_N = 4334`, at A1 = A4 = −55.834°
- PANDA — `detector_I = 7.99e-08`, `detector_N = 1462`
- IN8 as the control in both — `3.33e-07` / `4908`

Since a wrong-branch curvature costs about seven orders of magnitude, comparing against those is a genuine gate on slice 3a's emitted geometry, not a formality. Worth knowing: **IN12 and PANDA have recorded baselines; PUMA and IN8 have none in their own `MODEL_STATUS.md`** — IN8 only appears as the control figure inside the other two. So PUMA's run would establish a first baseline rather than confirm one, which is worth doing once anyway now that its declarations carry your review.

**What I can't tell you yet is the cost.** The worktree has no compiled binaries — `.instr`/`.c`/`.exe` are gitignored build products — so each instrument compiles from scratch through MSVC before it runs. I'd rather measure than guess: let me do **IN8 first**, since it has a control number to compare against, and report the actual wall clock. Then you can decide whether four is worth it or whether IN12 and PANDA alone (the two with baselines, and the two whose emitted radii change most) are enough.

Timing-wise it's after slice 3a lands, not now — 3a is the commit that changes emitted geometry, so running them before it would measure the old tree.

Meanwhile I'm writing the 3a packet: `scan_config` becomes a pass-through, both PUMA-formula copies delete, the GUI and API route through `ideal_curvature` with the selected crystals named, `rva` becomes a real value, and the snapshot records the radii it actually emitted. Autofocus and refusal semantics move to 3b behind it.

## User

Please go ahead and do thorough checks, they’re cheap compared to getting things wrong and finding out later. The computer is not in use so you won’t be interrupting or stealing resources.

## Assistant

That settles it — all four smoke runs, and I'll be generous with verification. One check before I write the brief: slice 3a stops `scan_config` signing, so anything reading radii off the state *before* the setter would see a magnitude where it saw a signed value.

Precondition verified: `build_point_params` has exactly one production caller (`tas_runtime.py:937`), and it runs *after* the setter signs at `:821`. The build path uses `rhmfac`, a separate factor, not the radius. So `scan_config` can safely store magnitudes.

Slice 3a is running. It's the commit that changes emitted geometry, so the brief carries three load-bearing constraints:

**The halving** — `mtt`/`att` are two-theta, `ideal_curvature` takes theta, and the two producers being deleted halve internally. Easy to carry the halving across and do it twice, or drop it entirely. Only the pinned tests would catch it.

**PUMA must be unchanged end to end.** Its optics *are* what the deleted formula computed, so PUMA is the control: if any PUMA number moves, that's a new bug rather than a fixed one, and the halving is the first suspect. PANDA, IN12 and IN8 are the ones that should move.

**Before/after radii for all four**, gathered deliberately — I need them for the commit message and to compare against the McStas baselines afterwards.

One thing I deliberately kept *out* of 3a and want on the record: `_default_parameter_values` still starts every instrument at PUMA's reference `mtt = att = 41.167°`, and an ordinary H/K/L request never retriggers the recompute. So after 3a the API computes with each instrument's own optics but still at a reference angle unrelated to the scan — better, not fixed. That's the frozen-geometry defect the external reader found, and per-point autofocus in 3b is what actually closes it. I told the executor to document that honestly in its end-to-end test rather than assert something prettier.

Given the machine is free: once 3a lands I'll run the full **serial** suite as well as the parallel one — the repo's own rule is that serial and parallel expose different ordering and shared-state bugs, and this is the slice where that's worth the ten minutes. Then all four smoke runs, IN8 first for the timing measurement.

Substantial slice, and PUMA held as the control. But one thing in its report needs checking before it reaches a commit message: the `rva` "before" column looks like it measured `vals`, not emitted parameters — and `scan_config` was overriding `vals` with its own literal at HEAD. Let me measure the real before/after rather than trust either of us.

Comparison worktree is up at slice 2. Let me measure what's actually emitted on both trees rather than reason about it.

Confirmed — the emitted `rva` before was **+0.8000 / +0.3100 / +1.4000 / +0.6000**, not 0.8 across the board. Slice 2's declaration already pinned IN12 and PANDA. Now the after tree.

Now the picture is clean and materially different from the executor's report:

| | rhm | rvm | rha | rva |
|---|---|---|---|---|
| **PUMA** | 13.0272 → 13.0272 | 1.6102 → 1.6102 | 2.3034 → 2.3034 | 0.8000 → 0.8000 |
| **IN8** | 14.1081 → **6.7576** | 1.7438 → **0.8353** | 2.3893 → 2.3893 | 0.3100 → **0.2953** |
| **IN12** | 10.2397 → **5.1199** | 1.2657 → **0.6328** | 2.6360 → 2.6360 | 1.4000 → 1.4000 |
| **PANDA** | 11.9463 → **6.8473** | 1.4766 → **1.0399** | 2.8373 → 2.8373 | 0.6000 → 0.6000 |

**The defect was confined to the monochromator.** The deleted formula already used the correct point-source form at the analyser with each instrument's own L3/L4 — it only forced parallel-beam at the monochromator, which is PUMA's assumption alone. And the fixed `rva` values were already pinned by slice 2's declarations, so they don't move here; only IN8's *driven* `rva` shifts, and by 5%.

Physically that's the right shape: parallel-beam uses L2 alone, point-source uses the harmonic mean of L1 and L2, so the radius comes down by roughly a factor of two on the three instruments with a real virtual source.

**1002 passed, exit 0** — confirmed independently. Applying the review fixes; let me check the logging convention in that module first.

All three review findings adopted, and the review itself ran **degraded — one of three proposers wedged**, so coverage was thinner than usual on the slice that matters most. I'll re-run it after this verification.

What went in:

**The GUI had no logger at all.** `TAVI_PySide6.py` imported no `logging` and had no module logger, so every `except` in it was silent by construction — against the repo's own rule that a catch always produces a log entry. Added one, and both catches now speak. The `rva` fallback distinguishes a degenerate geometry (no take-off, nothing to focus) from a *refusal* — IN12's Heusler declaring no established focusing model. The value doesn't change, it's flat either way, but flat-because-we-don't-know is a modelling gap rather than a neutral default, and it shouldn't reach a simulation unannounced.

**The bare `except Exception` now splits.** Expected refusals log at info and show "Ideal: --" as before. Anything else logs a full traceback and *still* degrades rather than taking the window down mid-session — that catch used to hide tracebacks entirely, and it now guards a call into the instrument model rather than a few lines of arithmetic, so its blast radius grew.

**`rva` joined its siblings in the pin check.** No API field sets it yet, so it's unreachable today — but pinning one radius has always pinned all four, and the slice that makes `rva` settable shouldn't have to remember to come back for it.

Clean — no findings. Same proposer wedged both times, so that's a broken route rather than flakiness; eight candidates were raised and rejected in verification this pass, so the two working seats were productive.

Worth noting: TAVI's suite runs **serially** at ~77 s (no `-n` flag), so the serial lane I was planning to add separately is the one I've been running all along.

Slice 3a is committed and pushed at `c93e2442`. Now the smoke runs — checking the console guard exists as documented before anything touches McStasScript.

**Round report — slice 3a landed, smoke runs started.**

**State.** Branch `crystal-bending-generality` at `c93e2442`, three commits in, pushed. Your main TAVI checkout is untouched. I also created a second read-only worktree, `TAVI-wt-before`, pinned at the previous commit — that's what let me measure the real before/after rather than reason about it. I'll remove it when the branch closes.

**Verified by me, not on report:** 1002 passed, 0 skipped, exit 0, all four instrument packages valid. TAVI's suite runs serially at ~77 s, so the serial lane I'd planned to add separately turns out to be the one I've been running throughout.

**The result that matters.** The defect was **confined to the monochromator**, and the numbers say so cleanly:

| | rhm | rvm | rha | rva |
|---|---|---|---|---|
| PUMA | unchanged | unchanged | unchanged | unchanged |
| IN8 | 14.1081 → **6.7576** | 1.7438 → **0.8353** | unchanged | 0.3100 → **0.2953** |
| IN12 | 10.2397 → **5.1199** | 1.2657 → **0.6328** | unchanged | unchanged |
| PANDA | 11.9463 → **6.8473** | 1.4766 → **1.0399** | unchanged | unchanged |

The deleted formula was already using the correct point-source form at the analyser with each instrument's own L3 and L4. It forced parallel beam *only* at the monochromator — which is PUMA's assumption and nobody else's. IN8, IN12 and PANDA all have a real virtual source at L1, so their monochromator radii come down by roughly the ratio of L2 to the harmonic mean of L1 and L2. PUMA unchanged everywhere is the control holding.

I had to correct the implementing agent's own table on this: it reported all four instruments' `rva` moving from 0.8, but that was the value in `vals`, not what was emitted — `scan_config`'s literal was overriding it. Measured against the previous commit, the fixed `rva` values don't move at all, because slice 2's declarations already pinned them. Only IN8's, which its hardware genuinely drives, changes.

**Review:** three findings first pass, all adopted; re-run came back clean. Both passes ran with one of three proposers wedged — same seat twice, so a broken route rather than flakiness. Worth knowing the coverage was two-thirds on the geometry-changing commit, which is partly why I did the independent before/after measurement myself.

Notable: `TAVI_PySide6.py` had no logging import at all, so every `except` in it was silent by construction, against the repo's own rule. It has a logger now.

**Running:** all four compiled McStas smoke runs, PUMA first as the control with a wall-clock report before the rest. Recorded baselines to compare against are IN12 `4.21e-07`/`4334`, PANDA `7.99e-08`/`1462`, IN8 `3.33e-07`/`4908`; PUMA has none, so its run establishes one. The check is order-of-magnitude — a wrong branch costs about seven orders, and the radii deliberately moved, so exact agreement isn't expected.

**Still open:** API curvature is computed once at PUMA's reference angle and frozen for the whole scan rather than following the take-off angles. That's the frozen-geometry defect, and per-point autofocus in 3b is what closes it.

Results are good, but a 3-second compile-plus-run for 10⁷ neutrons is fast enough that I want to confirm the runs actually happened rather than short-circuited.

Genuine artifacts — `.c` files around 630 KB, real `.exe` binaries, all timestamped in the last few minutes. So the compiles were real; this machine is just fast. Let me confirm the reported numbers against the actual detector files.

Verified against the detector files themselves, not the agent's summary — every number matches, and `Ncount: 9999990` confirms a real 10⁷ run. The 3-second runtimes are legitimate: it ran under 30 MPI processes (333,333 neutrons each), which is what your 32-thread box does with a small TAS instrument.

**All four smoke runs pass, and the result is better than "no collapse".**

| | before (main, 2026-09-09) | after | change |
|---|---|---|---|
| PUMA | *no baseline* | 2.09475e-07 / 4973 | establishes one |
| IN8 | 3.33e-07 / 4908 | **5.07902e-07 / 11455** | I ×1.53, N ×2.33 |
| IN12 | 4.21e-07 / 4334 | **5.44329e-07 / 6901** | I ×1.29, N ×1.59 |
| PANDA | 7.99e-08 / 1462 | **2.07537e-07 / 7663** | I ×2.60, N ×5.24 |

**Every instrument gained flux, and the gains are far outside Monte-Carlo noise** — the reported errors are 2–5% of the values, so these are roughly 8σ to 27σ movements, not scatter. That's the physically expected direction: the corrected monochromator now images the real virtual source at L1 onto the sample instead of assuming a beam from infinity, so it focuses more strongly (smaller radius) and delivers more neutrons. PANDA gains most, which tracks — it had both planes wrong, horizontal *and* vertical. No sign of a wrong branch anywhere; that would have cost seven orders, not gained one.

Two things from the run worth your attention:

**The harness had to work around the frozen-geometry defect to get correct focusing.** To make the ideal radii match the actual measurement point, the smoke script needed a deliberate second pass — solve the real angles, then re-patch them so the recompute fires, because it only triggers on a patched `mtt`/`att`. That is exactly the defect 3b closes, caught independently by something trying to *use* the system rather than by reading it. Without that workaround the run would have focused for the descriptor's default angle rather than the point being measured.

**My packet had PANDA's configuration wrong and the executor caught it.** I wrote "kf = 1.55 Å⁻¹ cold"; PANDA's own `MODEL_STATUS.md` records its baseline run at kf = 2.662 Å⁻¹, and I'd confirmed that myself earlier and then mis-summarised it. It followed the document over my brief, which is what I'd asked for and the right call — otherwise the comparison would have been against a different configuration and meaningless.

These numbers belong in the four `MODEL_STATUS.md` validation records, but that's the documentation commit at the end of the branch, done deliberately rather than as a drive-by — including PUMA's, which now has a first baseline it never had.

Next is 3b: the per-axis mode, per-point autofocus, and out-of-travel refusal instead of clamping.

## User

Ok, continue

## Assistant

Slice 3b. One design point I want on the record before handing it off, because it changes an API contract:

**The per-axis mode maps onto intent that already exists.** The GUI's Ideal *lock* button per axis becomes AUTOFOCUS; an unlocked typed value is HELD; a scan command naming an axis is SCANNED. That preserves what the GUI does today exactly — it still starts flat and unlocked, no surprise for you.

**The API defaults to AUTOFOCUS**, which is the change. ISAR sends H/K/L and never sets radii, so under the current default its curvature stays frozen at a reference angle for the whole campaign. R1 says the focusing tracks, so an API request that doesn't name a radius gets a tracking instrument. An explicit radius in the request makes *that axis* HELD — per-axis, rather than today's all-or-nothing pin where naming one radius freezes all four.

I'm also splitting refusal off into 3c: 3b is modes plus per-point autofocus plus a machine-readable flag when an autofocus ideal gets clamped; 3c is refusing an explicitly commanded out-of-travel value at submission, where it can be refused cleanly instead of rewritten mid-scan.

3b is running. The acceptance test I'm most interested in is the one the smoke runs handed us: **driving a plain H/K/L request through the production path without the two-pass workaround should now yield the same radii as the workaround did.** That verification script needing a manual re-patch to get correct focusing was the defect demonstrating itself, so its becoming unnecessary is the cleanest possible proof the slice worked.

I also asked it to go looking for a third instance of the pattern that's bitten twice already — a rule enforced in one place and not its twin. Slice 2 had the flat sentinel honoured where a radius is produced but not where it's stored, and a fixed axis handled by the applier but crashing the producer. Curvature becoming per-point rather than per-scan is exactly the kind of change that exposes a cache or fingerprint assuming otherwise, so it's worth looking rather than assuming.

One consequence of the API default worth flagging now rather than at review: once an unnamed axis defaults to AUTOFOCUS, **every existing API caller's emitted geometry changes** — including ISAR's campaigns, which will start running a focused instrument that tracks instead of one frozen at PUMA's reference angle. That's R1 working as intended and it should raise flux the way the smoke runs did, but it means the next ISAR campaign against this branch won't reproduce numbers from a previous one. Worth knowing before you point a campaign at it.

The per-point table is exactly the evidence I wanted, and it checks out physically. Let me verify independently and look hard at one thing in that report.

`scan_config` does propagate NMO to the point state (line 350), so per-point autofocus correctly returns flat for PUMA with a nested mirror optic. But **there's no test covering that interaction** — and it's precisely the class that has bitten twice already, now on a new path. Safe by construction, untested. Adding it.

8 passed. Let me prove the new test is actually sensitive rather than passing by luck.

The `-c` form gets mangled through micromamba's shim — using a file, which worked before.

Probe confirms the test is load-bearing: NMO from state gives **flat (0.0)**, an explicit override saying "no NMO" gives **13.03 m**. If the per-point call ever stopped seeing the NMO state, the monochromator would bend from flat to 13 metres and the test would catch it immediately.

Independent suite before my addition: **1010 passed, exit 0, packages valid** — matches the executor's claim.

Full 3/3 panel this time — the wedged route recovered. One Minor finding, and it's the **fourth** instance of the same pattern: a rule applied in one place and not its twin. I asked the seat to assume there was a third rather than assume there wasn't, and there was.

Fix applied and verifying. The pattern is now unmistakable — four times in this branch, the same shape:

1. The flat sentinel honoured where a radius is *produced* but not where it's *stored* (I caught it)
2. A fixed axis handled by the applier but crashing the producer (review caught it)
3. The two enforcement points reading different angle sources — that one turned out intentional
4. `_default_parameter_values` overwriting all four radii unconditionally while `build_api_launch_state` checks the mode per axis (review caught it)

Every one is a rule that exists in two places and got updated in one. That's the structural argument for the whole repair restated in miniature: the original defect was PUMA's formula living in two copies, and consolidating it has surfaced each remaining twin as we touch it. It's also why I've been telling the review seat to assume there's another rather than assume there isn't — that framing has now paid off twice.

The fourth one was benign today because the API defaults every axis to AUTOFOCUS, so both paths produce identical numbers. It's the divergence that matters, not the current output: the moment a caller reuses those defaults after adjusting a mode, a HELD axis gets silently overwritten.

**Round report — slice 3b committed and pushed.**

**State.** Branch `crystal-bending-generality` at `63e2422d`, four commits, pushed. Your main checkout is clean and `merge-tree` shows no conflict with `main`. Verified by me: **1011 passed, 0 skipped, exit 0**, all four packages valid.

**What landed.** A curvature axis is now in one of three modes, per axis, carried in launch state and honoured inside the per-point loop after that point's angles are solved: AUTOFOCUS recomputes from the optics at every point, HELD keeps an explicit magnitude, SCANNED follows the scan command. *Fixed* isn't a mode — it belongs to the assembly and you have no say over it.

Your GUI is unchanged: the per-axis Ideal lock maps straight onto AUTOFOCUS and HELD. The API now defaults every axis to AUTOFOCUS, since a request that names a Q and not a radius wants a focused instrument.

**The tracking, measured on a PUMA fixed-kf scan:**

| deltaE | mtt | rhm | rvm | rha | rva |
|---|---|---|---|---|---|
| −3.0 | 46.417 | 11.6221 | 1.8049 | 2.3034 | 0.8000 |
| 0.0 | 41.167 | 13.0272 | 1.6102 | 2.3034 | 0.8000 |
| +3.0 | 37.374 | 14.2948 | 1.4674 | 2.3034 | 0.8000 |
| +6.0 | 34.467 | 15.4589 | 1.3569 | 2.3034 | 0.8000 |

The monochromator tracks its own take-off across a **33% range of ideal radius**; the analyser doesn't move because fixed kf pins its take-off. I checked those against PUMA's optics by hand — at deltaE = +6, theta = 17.23°, `2·L2/sin θ` = 15.46 m, matching to four figures. Frozen at the launch value, the monochromator was mis-focused by up to a fifth at the ends of that scan.

The defect was shown red first: `rhm must track this point's own mono take-off angle; got [0.0, 0.0, 0.0]`.

**One test I added myself.** Nothing covered autofocus with a nested mirror optic fitted — the case where the monochromator must stay *flat at every point*, not just at launch. It was correct only because `scan_config` happens to propagate `NMO_installed` onto the state the per-point loop copies. I probed it to confirm the test is load-bearing: NMO from state gives 0.0, an override saying no NMO gives 13.03 m. Given that the flat override has already been broken once on a different path, an untested guard there wasn't good enough.

**Review** ran a full 3/3 panel (the wedged route recovered) and found one Minor: `_default_parameter_values` overwrote all four radii unconditionally while `build_api_launch_state` checks the mode per axis. Benign today — the defaults are all-AUTOFOCUS — but it's the fourth instance in this branch of a rule living in two places and being updated in one. Fixed.

**What's left:** 3c (refuse an explicitly commanded out-of-travel radius at submission instead of clamping it), slice 4 (the `rva` widget and API field), slice 5 (resolution adapter carries `rva`, plus the documentation corrections and recording the four smoke baselines). Then the pre-PR review and the PR.

One thing to know before pointing a campaign at this branch: with the API defaulting to AUTOFOCUS, ISAR's scans now run a tracking instrument rather than one frozen at PUMA's reference angle, so they won't reproduce numbers from a campaign run against `main`. The smoke runs suggest that means more flux, not less.

## User

Great. Let’s continue to 3c then

## Assistant

Slice 3c. Before I write the brief, two things to check in the source: how the GUI currently refuses to launch (so I reuse that rather than invent UI), and how a scan command's range is represented (so an out-of-travel *sweep* can be caught at submission too).

Both mechanisms already exist and are shared, which makes this smaller than I expected: `PrepFailure` is the GUI's abort-with-a-reason path, and `_validate_single_scan_command` — which already refuses a fixed axis — parses `variable start end step`, so an out-of-travel *sweep* is catchable at submission from the same place for both GUI and API.

3c is running, and it turned out smaller than planned because both mechanisms already exist: `PrepFailure` is the GUI's abort-with-a-reason path, and `_validate_single_scan_command` — which already refuses a scan over a fixed axis — parses `variable start end step` and is shared by the GUI dock and the API. So the out-of-travel *sweep* check lands in one genuinely shared place rather than two mirrored ones.

The rule in a line: **refuse where intent is known, clamp where it isn't.** A value someone explicitly asked for gets refused before anything runs; an autofocus ideal keeps clamping, because nobody chose that number and the bender really does stop there.

Two constraints I made load-bearing in the brief. **Zero must survive** — it means flat, and a minimum radius constrains how tightly a bender bends, not whether it may be straight; both the clamp helper and the new checker have to exempt it. And **only a commanded axis is refused** — refusing an autofocus ideal would kill a legitimate scan whose optimum simply leaves the bender's reach, which is the opposite of helpful.

I also asked for one specific test shape: the one that pins *both* submission paths refusing identically, rather than a test for each half. Given this branch has now produced four separate cases of a rule enforced in one place and not its twin, testing the pair is the only version that would actually catch the fifth.

There's a nice asymmetry falling out of the declarations, incidentally: only PUMA and IN12 declare any travel, so only they can refuse anything. IN8's and PANDA's limits are genuinely unknown and declare none — so they refuse nothing, and that's correct rather than a gap to paper over by inventing numbers.

All three call sites pass the new check — no fifth instance there. Checking that the API path resolves its own crystals rather than the dock's, since that was a standing ruling.

The API path takes its crystals as parameters and the dock path reads the dock with a comment saying why it's allowed to — the ruling holds. One thing I do want to change: the refusal sentence is the single string a human reads, and it's garbled.

Wording now reads as a sentence — and "tighter than the mechanical minimum" says what's physically wrong, which "below" doesn't. Updating the tests that assert on it.

The tests assert on content — axis, crystal, value, limit all present — not the exact sentence, so the rewording doesn't break them. That's good test design on the executor's part. Verifying.

Verification running. The refusal an operator now reads:

> `rhm on the PG[002] monochromator: commanded radius 1 m is tighter than the mechanical minimum of 2 m.`

The original said "radius 1 m is below its mechanical minimum" — which parses awkwardly and, worse, "below" is ambiguous about what's physically wrong. A *smaller* radius is a *tighter* bend, so "tighter than the minimum" tells you the bender is being asked to curve harder than it can. Same sentence reaches the API client in the error body, confirmed identical by the pair test.

Three structural things I checked rather than took on report: all three callers of the scan-command validator pass the new travel check (no fifth twin there); the shared validation path takes its crystals as *parameters* while the dock path reads the dock with a comment explaining why it's allowed to — the caller-names-the-crystals ruling holds; and the new tests assert on message *content* rather than the exact string, which is why I could improve the wording without touching them.

Pre-reword independent run confirms **1025 passed, exit 0**. Running the review seat while the post-reword verification finishes.

One item flagged for manual inspection — a claim in a comment that the reviewer couldn't verify from its packet. That's mine to check.

**1025 passed, exit 0** after the rewording. Now verifying the comment's claim rather than accepting it.

The review's one flagged item turned out to be a comment that overclaimed rather than a hole in the logic. It said a non-numeric radius "is reported elsewhere"; the reviewer couldn't verify that from its packet, so I traced it.

What's actually true: `get_gui_values()` returns `None` for *any* unparseable field, and `_collect_simulation_launch_state` bails on that at `:2700`. So a non-numeric radius can't reach a launch at all — there's genuinely no commanded value to accept or refuse, and skipping it isn't a gap. But it is *not* "reported": the operator gets a run that quietly does nothing, with no message saying why.

That's a real operator-surface gap, and it's pre-existing and not about curvature travel, so I've corrected the comment to say exactly what's true and named the gap rather than fixing it here. Widening a slice to chase an unrelated defect is how a branch stops being reviewable — but it shouldn't vanish either, so it goes in the PR as a recorded follow-up.

**Round report — slice 3c committed and pushed. The behavioural work is done.**

**State.** Branch `crystal-bending-generality` at `2f864221`, five commits, pushed. Your main checkout is clean, no conflict with `main`. Verified by me: **1025 passed, 0 skipped, exit 0**, all packages valid.

**What landed.** Refuse where intent is known, clamp where it isn't. An explicitly held radius outside travel is refused before anything runs — on the GUI's pre-launch gate and as a 400 from the API. A scan whose range leaves travel is refused by the scan-command validator, which both paths already share and which already refused scans over a fixed axis, so that check landed in one genuinely shared place rather than two mirrored ones. Commanding a fixed axis is now refused by name instead of pinned with a log entry nobody reads.

An autofocus radius still clamps and still raises its per-point flag — refusing one would kill a legitimate scan whose optimum simply leaves the bender's reach. Zero stays legal everywhere.

The sentence an operator and a campaign client both get:

> `rhm on the PG[002] monochromator: commanded radius 1 m is tighter than the mechanical minimum of 2 m.`

I reworded that from the original "radius 1 m is below its mechanical minimum" — it parsed awkwardly, and "below" doesn't say what's physically wrong, where "tighter" does. The tests assert on content rather than the exact string, so nothing had to change to accommodate it.

**Review:** full 3/3 panel, no actionable findings. One item flagged for manual inspection — a comment claiming a non-numeric radius "is reported elsewhere". I traced it: it's *blocked* (`get_gui_values()` returns `None` for any unparseable field and the launch assembly bails), but it is **not reported** — the operator gets a run that quietly does nothing. Comment corrected to say what's true; the gap itself is pre-existing, unrelated to curvature, and goes in the PR as a recorded follow-up rather than widening this slice.

**The pattern, for the record.** Five slices in, the recurring defect of this area has shown up five times: the flat sentinel honoured where a radius is produced but not stored; a fixed axis handled by the applier but crashing the producer; `_default_parameter_values` ignoring modes while its twin honoured them; and now the travel rule needing to hold in the clamp and the refusal together. Each is one rule living in two places. It's the same shape as the original defect — PUMA's formula in two copies — which is why I've been asking the review seat to assume there's another rather than assume there isn't.

**Remaining:** slice 4 (the `rva` widget and API field, making it operator-settable), slice 5 (resolution adapter carries `rva` — which moves numbers ISAR consumes — plus the documentation corrections and recording the four smoke baselines, including PUMA's first). Then the pre-PR whole-branch review, the external reader on the pushed branch, and the PR itself. Merging stays yours.

## User

Ok, we should be in a much safer place now, take slices 4 and 5 and push to the PR with reviews.

## Assistant

Both slices, then the PR. They can't run in parallel — one writer per tree — so slice 4 first.

Slice 4 has a wrinkle worth naming: `rva` is the axis where the three states actually differ. On IN12's PG(002) and PANDA it's *fixed*, so the operator gets no say and the field should show the declared radius read-only. On IN12's Heusler it's *driven but with no established focusing model* — so a typed value is legitimate while autofocus is not, meaning the field is editable but the Ideal button isn't offered. That distinction has existed in the declarations since slice 1 and this is the first slice where a human can see it.

Packet 5 while that runs. It has two very different halves — a numerical change that propagates to ISAR, and a documentation sweep — so I want the doc list to be exhaustive rather than "fix what you notice".

Packet 5 is written and waiting on slice 4 to land — one writer per tree, so they go in sequence.

Slice 5's first half is the one with reach beyond this repo. `resolution_adapter.py` has been handing the Cooper–Nathans/Popovici model `rva: None` for every instrument, which means **every analytic resolution TAVI has ever reported assumed a flat vertical analyser** — including PUMA and PANDA, where it's declared fixed-curved. Fixing that changes the resolution matrix, which changes `bragg.dE`, which is the number ISAR reads to choose energy windows and step sizes. No API shape change — `ResolutionConfig` already declares the field and the matrix is 4×4 either way — but the values move, so I've asked for the before/after `bragg.dE` on a concrete configuration to put in the commit message.

There's a trap there I flagged explicitly: `resolution.py` applies the scattering sense itself (`monorh = radius_cm(cfg.rhm) * sm`). Passing a *signed* radius would sign it twice. That was one of the ChatGPT reader's two blockers back at plan time, and this is the commit where it would actually bite.

The second half is the documentation sweep. I enumerated it rather than leaving it to judgement — six documents still describe `calculate_crystal_bending` as live code, the authoring guide still tells a new instrument author to implement it and to apply the branch sign per plugin, and PANDA's `MODEL_STATUS.md` still carries the row claiming this defect was confined to advisory labels and that "scans and the API launch path are unaffected". That claim is what sent me looking in the first place.

It also records what this branch produced: your PUMA review closing scientist-review question 3, scoped to the bending limits and *not* the arm lengths; IN8's `rva` becoming driven; and the four smoke baselines, PUMA's being the first it has ever had.

Two things to check in that report. The executor caught a real error in my packet — PUMA's `rva` is *fixed* at 0.8, not driven, and my brief contradicted itself on it. That's the second time an executor has correctly overridden my brief by reading the source. But its description of the fixed field as showing a value "signed by branch" needs verifying, because magnitudes-in-the-operator-surface is the ruling that stops double-signing in the resolution model — and slice 5 feeds exactly that into Popovici.

Something important. `_apply_rva_axis_policy` only sets enabled state — the field's *value* comes from the Ideal button, which writes `ideal_curvature`'s output. And `ideal_curvature` returns **signed** radii. Let me check whether that means `vals` now carries signed values into the resolution adapter, because that's the double-signing blocker and it would predate this slice.

Confirmed, and this one is mine. The chain:

`ideal_curvature` returns **signed** radii (IN12 `rhm = −3.8446`) → the Ideal button writes that into the field → `get_gui_values()` reads it raw into `vals` → `resolution_adapter.py:200` passes it straight to `ResolutionConfig` → `resolution.py:320` does `radius_cm(cfg.rhm) * sm`, **applying the sense a second time**. For IN12 that yields +384 cm where −384 was intended.

This is a live defect I introduced in slice 3a, when the GUI and API started taking values from the signed producer. It's exactly the blocker the external reader raised at plan time — *"operator/API/descriptor values stay magnitudes, signing happens only at the physical-model boundary"* — which I adopted as a ruling and then let the implementation violate, because I was verifying emitted McStas radii (correct) rather than the resolution path (not).

Before my branch this was consistent: the old GUI produced clamped positives, so Popovici signed once. I broke it.

Now the regression test — and it has to pin *both* contracts together, since that's the lesson this branch keeps teaching.

The existing tests assert `vals` equals the **signed** reference table — so they were pinning the bug. They need to assert magnitudes while the *emitted* test keeps the signed table. That pairing is the whole point.

Now the test that pins the pair — operator surface stays a magnitude while the emitted geometry stays signed, asserted together so neither can drift alone.

I want to flag this one clearly rather than bury it in a commit, because it's the most consequential thing found today and I put it there.

**The bug.** Since slice 3a, `vals` — the dict the GUI fields and API requests fill — has carried *signed* radii for negative-branch instruments, because the Ideal button writes `ideal_curvature`'s output straight into the field. `resolution_adapter.py` passes those to `ResolutionConfig`, and `tavi/resolution.py:320` then applies the scattering sense **again**: `monorh = radius_cm(cfg.rhm) * sm`. For IN12 that turns −384 cm into +384 cm. The analytic resolution has been describing crystals bent the wrong way on IN12 and PANDA, and on IN8's analyser.

**Why nothing caught it.** The emitted McStas geometry stayed correct the whole time — `set_crystal_bending` takes `abs()` and re-signs from the take-off angle — so every smoke run passed, every pinned emitted-radius test passed, and the simulation ran the right instrument. Only the *analytic* resolution was wrong, and that's the half a headless campaign consumes without ever seeing a radius.

**It's mine.** The external reader raised this exact hazard at plan time as one of two blockers, I adopted the ruling — operator and API values stay magnitudes, signing happens only at the physical boundary — and then verified the implementation against emitted radii rather than against the contract I'd just written down. The existing tests asserted `vals` equalled the *signed* reference table, so they were pinning the bug rather than catching it.

**The fix** is one wrapper: radii bound for the operator surface get their magnitude taken; the scan loop keeps using the signed producer directly. The two contracts are now asserted in a single test on a negative-branch instrument, so neither can drift without the other failing — which is the lesson this branch has now taught six times.

Before my branch this was consistent, incidentally: the old GUI produced clamped positives, so Popovici signed once. I introduced it in 3a and it would have shipped inside slice 5, which is precisely the commit that starts feeding `rva` into that same path.

That's worth being precise about. The failures were in `test_parameters_persistence.py` — not the curvature tests I was editing — and they pass in the clean run. The cause is almost certainly mine: I ran a targeted test file while that full suite was still in flight, and persistence tests write a shared `config/parameters.json`. The repo warns explicitly against two suites at once; I broke my own rule.

One more clean run alone to be sure it's contention and not flakiness, since this is going into a PR.

Confirming run in flight, nothing else touching the tree this time.

The arithmetic does reconcile cleanly, which is reassuring: 1025 at slice 3c, plus 14 for the executor's `rva` tests, plus 1 for the paired sign-contract test I added, gives the 1040 the clean run reported. So the two persistence failures were contention, not a real regression — but I'd rather see it twice than infer it once, particularly on the slice that touches persisted state.

Worth recording what the executor caught in my brief, too: I wrote "IN8, PUMA: driven and focusing-known" as the ordinary case, but **PUMA's `rva` is declared fixed at 0.8 m** — my own packet said so two paragraphs earlier and then contradicted itself. It read the descriptor instead of following me, built the policy declaration-driven rather than instrument-name-driven, and used IN8 for the ordinary case and PUMA for the fixed-axis refusal test. That's the second time today an executor has correctly overridden my brief by going to the source — the first being PANDA's smoke-run configuration.

Clean: **1040 passed, exit 0**, and the persistence file alone passes 20/20. Confirmed contention, not a regression.

**Slice 4 is in at `5784cf60`** — six commits on the branch, pushed, verified at 1040 passed with a clean confirming run.

Slice 5 is now running, and I sent it a correction rather than let it work from a stale brief: the packet warned it not to pass a signed radius into the resolution adapter, but that hazard is now *fixed* in the commit it's building on, so reading `vals['rva']` straight through is correct. I asked it to verify that itself against `resolution.py:320` rather than take my word — the whole reason this bug survived as long as it did is that I trusted a ruling I'd written instead of checking the code against it.

Once it lands, the remaining sequence is the pre-PR work: a whole-branch review over `base=main` with the handoff block, the external reader on the pushed branch, then `gh pr create`. Merging stays yours.

One thing I'll put in the PR body explicitly, because it's the kind of thing that matters to whoever reads this next: **this branch changes numbers ISAR consumes, in two separate ways.** Emitted curvature changed for IN8, IN12 and PANDA — all three gained flux in the smoke runs — and the analytic resolution changes for every instrument once `rva` reaches it, plus a sign correction on the negative-branch ones. A campaign run against this branch will not reproduce a campaign run against `main`, and that's intended rather than drift.

Excellent, and it corrects my briefing rather than mine correcting it. The executor measured `bragg.dE` and found it **does not change** when `rva` is wired in — only `dq_z` does — then traced the Popovici matrix to explain why: for in-plane Q the vertical block decouples from the horizontal-and-energy block, so `rva` only ever touches `dq_z`. It refused to hunt for a configuration that would show a change.

That means I over-claimed to you. Let me measure the thing that *does* move ISAR's numbers.

Now I have the honest number, and it's the one I should have measured before claiming anything. On an IN12-shaped configuration (both crystals on the negative branch):

| | dE | dq_par | dq_perp | dq_z |
|---|---|---|---|---|
| **magnitudes** (fixed) | 0.099807 | 0.018098 | 0.014839 | 0.069756 |
| **signed** (the bug) | 0.098238 | 0.010445 | 0.013597 | 0.032989 |

The double-signing cost **~1.6% on energy resolution** — so ISAR's window sizing was mildly affected — but **42% on in-plane momentum resolution and 53% out of plane**, both roughly a factor of two. That's the real shape of it: a modest error in the quantity most people look at, and a factor-of-two error in the ones they don't.

Caveat on my own number: that's an IN12-*shaped* synthetic configuration, not IN12's production descriptor values, so it demonstrates the size of the error class rather than IN12's exact numbers.

And it resolves the attribution I got wrong. Slice 5's `rva` wiring genuinely doesn't move `bragg.dE` — the executor was right and I was repeating the external reader's claim without testing it. What moves ISAR's numbers is the **sign fix in slice 4**.

Waiting on my independent run before committing slice 5 — nothing else touching the tree this time, having learned that lesson an hour ago.

Two things from the executor's report worth your attention, both of which are it being more careful than my brief:

**It found my premise wrong and said so.** I told it the `rva` wiring would move `bragg.dE`, because the external reader told me ISAR uses that value for energy-window sizing and I extrapolated. It measured, found `dE` invariant across several configurations, then traced the Popovici construction to explain why — the vertical block decouples from the horizontal-and-energy block for in-plane Q, so `rva` only reaches `dq_z`. It explicitly declined to go looking for a configuration that would show a change. That's the right instinct: the finding is that my premise didn't hold, not that the test needed reshaping until it did.

**It refused to close a question it couldn't fully answer.** PUMA's scientist-review question 3 asks about bending limits *and* slab sizes, counts and mosaics. Your check covered the bending limits; the rest was never confirmed. So it split the question — answered half, left half open — rather than marking the whole thing closed, which would have been another false claim in a document whose false claims are what started this.

It also flagged what it did *not* verify: it recorded the four smoke numbers as given rather than re-running them, and derived its test-count delta from the diff rather than re-running pytest at the old commit because the sandbox blocked a stash. Both correct to declare.

**1043 passed, exit 0** — confirmed independently (1040 + 3 new resolution tests). Running the per-slice review.

Two findings, and the Major one is the seventh instance arriving on schedule: the new resolution tests only exercise **PUMA**, whose branches are positive — the one instrument where double-signing is invisible. The bug I just fixed was only ever visible on IN12 and PANDA, so those tests couldn't catch its return.

I wrote those against helpers that don't exist in that file — let me match its actual conventions.

19 passed. Proving the new guard's test is load-bearing rather than passing by luck.

Both findings adopted, and the Major one was the right catch.

**The test gap was real.** Every test in `test_resolution_adapter.py` used PUMA, which takes off positive at both crystals — so a sign error there is *invisible* and those tests pass either way. I've added IN12, which takes off negative at both, as the instrument that can actually show it. Plus a guard at the adapter boundary: a signed radius arriving there is taken as a magnitude and says so in the config's warnings, rather than silently producing a double-signed matrix. That's a trust boundary between the operator surface and the physics model, which the repo's own rules say not to leave unvalidated.

Shown red first: disabling the guard fails `test_a_signed_radius_is_taken_as_a_magnitude_and_said_so`, restoring it passes 19/19.

**The wording fix matters more than it looks.** The PUMA note said the review covered the bending radii "only — the underlying focusing formulas and the arm lengths above remain provisional". Read quickly, that can sound like the arm lengths were *examined* and found provisional. They weren't examined at all. It now says they **were not part of this review** and were deliberately left outside its scope. In a document whose entire purpose is recording how much weight each number carries, the difference between "checked and still uncertain" and "not checked" is the whole point.

All seven commits are in and pushed. Now the pre-PR seats. Writing the handoff block first — it goes to both reviewers and becomes the PR body.

Whole-branch review across all seven commits: **41 files, +3151/−575, full 3/3 panel, one Minor finding.** No eighth twin — which, after seven, is the first genuinely reassuring signal of the day.

The finding is on the side-channel I flagged myself in slice 3b: `_last_ideal_clamped_axes` is set in `ideal_curvature` but never initialised, so it exists only after the first call. The one reader uses `getattr(..., ())` and is safe, but that's an implicit contract. One line removes it.

**Both pre-PR seats are running.**

The whole-branch reviewer came back with one Minor finding across 41 files and +3151/−575, now fixed. Notably it did **not** find an eighth twin — after seven, that's the first structurally reassuring result of the day, though I've asked the external reader to go looking anyway rather than take one tool's silence as proof.

The external reader is the same one that reviewed the *plan* before any code existed, so I gave it something unusual: its own two blockers back, with what happened to each. It was right about the sign rule — my proposal to derive the branch sign from the declared `Sense` was a step backwards from what the four per-model methods already did. And it was right about the double-signing hazard, which I adopted as a ruling and then let the implementation violate for three commits, because I verified emitted radii instead of the contract I'd just written down. Telling it that plainly seemed more useful than presenting a clean branch and hoping it finds the same thing twice.

Four things I asked it for: the eighth twin; anything caching or persisting curvature as constant across a scan, now that it's per-point; whether the documentation corrections assert anything the code doesn't do; and whether there's an API *shape* change to ISAR I've missed, as opposed to the value changes, which are intended.

It's a ~20-minute ticket. Once it lands I'll fold in anything actionable, then open the PR with the handoff block as its body. Merging stays yours — I won't touch it.

**1045 passed, exit 0**, and the whole-branch reviewer's one finding is committed at `1190c99b` — eight commits, all pushed.

The branch is now complete and verified; the only thing outstanding is the external reader's ticket. I'll wait for it rather than open the PR first, since anything it finds should land as a commit rather than as a comment on an open PR.

While it runs, the state as it stands:

**Progression, every figure from my own runs rather than an agent's report:** 973 before any change → 1045 now. Seven slices, eight commits, no skips introduced at any point.

**The four smoke runs**, verified against the detector files rather than a summary: every instrument gained flux, far outside Monte-Carlo scatter, in the direction the physics predicts once the monochromator images the real virtual source at L1 instead of assuming a beam from infinity. PANDA gained most — it had both planes wrong. PUMA has a baseline for the first time.

**Three things this branch found that weren't in its brief:** IN8's scanned `rha` had been landing on the wrong branch, costing about seven orders of magnitude; the analytic resolution had been describing crystals bent the wrong way on every negative-branch instrument for three commits, which is mine and was invisible because the simulation stayed correct; and PANDA's own `MODEL_STATUS.md` claimed the original defect was confined to advisory labels, which is the sentence that started all of this and was wrong when it was written.

**What I'd want a reader of this PR to take away** is less the code than the shape: one rule living in two places, seven times over, in an area whose original defect was one formula living in two copies. The consolidation is what surfaced each twin as we touched it.

## User

ChatGPT'

## User

I would not merge this branch as-is. I found the eighth, and unfortunately it has company. The main McStas execution path looks coherent; the remaining defects are precisely the secondary/twin consumers that did not follow the new per-point curvature contract.

1. **BLOCKER — the deterministic engine is the eighth.** `_run_scan_deterministic()` correctly calls `compute_snapshot()` for every point, and that snapshot contains the point's actual AUTOFOCUS/SCANNED curvature. It then discards those radii when building the analytic resolution and calls `resolution_config(vals, q0, w)` with the frozen launch-time `vals`. So an AUTOFOCUS energy scan uses one launch radius for the entire analytic convolution, and a direct `rhm/rvm/rha/rva` scan changes the snapshot but not the deterministic resolution at all. Because `evaluate_point()` consumes that resolution, this changes simulated counts, not merely metadata.  The smallest repair is to overlay the four point radii from `snapshot.metadata` onto a copy of `vals`, converting them back to magnitudes, before `resolution_config()`. I would make that a shared helper because finding #4 needs exactly the same operation. A regression should use two points whose AUTOFOCUS radii differ and also a direct curvature scan. **This is the one I would call your eighth defect.**

2. **BLOCKER for the ISAR contract — `GET /resolution` has essentially the same twin defect.** `compute_resolution(H,K,L,deltaE)` correctly solves the geometry of the *requested* point, but then feeds `resolution_config()` the current GUI `vals`, including whatever radius magnitudes happen to be in the GUI fields. It never applies `curvature_modes` or computes AUTOFOCUS at the requested point.  The route explicitly promises resolution at one supplied `(H,K,L,deltaE)` point and simply delegates those coordinates to this method.  That is directly relevant to ISAR: its callback asks TAVI for resolution at planner-selected `(h,k,l,deltaE)` values, and its acquisition code preferentially consumes `bragg.dE`.   So the HTTP shape survives, but the value can describe the requested kinematics with curvature from a completely different GUI point. This deserves an IN12/PANDA negative-branch regression where the query differs from the GUI point, plus a mixed-mode case proving HELD stays held while AUTOFOCUS moves.

3. **HIGH — relative GUI curvature scans evade the new “refuse, never clamp” rule.** The preflight validator checks the literal start/end values in the scan-command text against mechanical travel. It has no knowledge of `relative_mode_1/2`.  Actual scan generation adds the current value only afterward.  For example, with PUMA `rhm=2.5`, a relative `rhm -2.4 -2.0 0.2` presents literal magnitudes ≥2.0 to preflight, but actually requests 0.1–0.5 m. Those nonzero values then hit `set_crystal_bending()` and are silently clamped to 2.0 m. That is exactly the behavior this branch says has been eliminated. The repair should validate the expanded concrete values, not the pre-offset command text.

4. **HIGH — McStas background resolution widths also freeze curvature at launch.** In the normal McStas path, the point snapshot has the correct applied radii and the per-point `scan_parameters.txt` is correctly built by overlaying snapshot metadata. But when a background source needs `sigma_q` or `sigma_e`, the code instead calls `resolution_config(vals, q0, deltaE)` on the frozen launch dictionary.  Thus the neutron simulation can use the right per-point crystal geometry while a resolution-shaped background planted onto that same point uses the wrong geometry. The point-resolution-values helper from finding 1 closes this too.

5. **There is a persistence assumption worth fixing or very explicitly documenting.** The run-level parameters file is written once from `vals`, and `ScanResult.metadata` is initialized as `dict(vals)`.  `ScanJob` then deliberately exposes that complete frozen parameter set as `launch.parameters`, describing it as the “full picture” downstream consumers need.  For AUTOFOCUS, those four radii are now only launch/reference radii; they are not the radii the scan actually ran at. McStas per-point files happen to preserve the true values, but HTTP scan results do not, and the deterministic engine has no per-point files. ISAR's parser currently calls `launch.parameters`/`result.metadata` the per-scan instrument truth, although importantly it does **not currently consume those curvature fields in its CN reconstruction**, so I do not see an immediate ISAR numerical break through this persistence path.  I found no corresponding bad build-cache/fingerprint assumption: leaving curvature out of build fingerprints is correct because these are runtime McStas parameters, not build topology.  I would nevertheless persist applied point curvature somehow, or make the launch/reference semantics unmistakable before another consumer mistakes these fields for constants.

6. **Yes, there is an API-shape change beyond the intended numerical change.** On `main`, `get_gui_values()` exposed `rhm/rvm/rha` but not `rva`; on the branch it exposes all four plus the new `curvature_modes` object.  `/parameters` and `/state.parameters` return that dictionary verbatim, and scan snapshots propagate the frozen values into `launch.parameters` and `result.metadata`. However `_api_field_map()` adds `rva` but not `curvature_modes`, despite its own comment saying it mirrors `get_gui_values()` exactly.  Thus `curvature_modes` has become a public readable field which is absent from the schema/write field set. That is an additive rather than breaking change for current ISAR: its client is a loose JSON-dict wrapper, its state users read selected keys, and its resolution parser ignores unknown response members.   But it is a real public-contract asymmetry. I would either describe modes explicitly as read-only schema state or keep them out of the parameter dictionary and surface them separately.

7. **The final documentation correction contains two confidently wrong survivors.** `docs/CONFIGURABLE_INSTRUMENTS.md` still says IN8's "`scan_config` applies the branch sign to the GUI magnitudes (rha/rva negative)." That is no longer true and directly contradicts the new architecture: the shared physical-boundary setter derives the sign; GUI/API/`vals` remain magnitudes. The same section still lists "`rva magnitude 0.31`" among IN8's placeholders.  The actual descriptor declares IN8 `rva` driven, and the newly corrected MODEL_STATUS explicitly says the old fixed 0.31 placeholder is gone.   By contrast, the rewritten authoring guide is good: shared producer, physical-boundary signing, magnitude operator/API contract, curvature-axis provenance, and fixed/driven policy all match the implementation, and the provenance requirement really is enforced by descriptor validation.

For ISAR specifically, I found **no current consumer that will break merely because extra JSON keys appear**. The client and parser are permissive. The important downstream problem is instead semantic: `GET /resolution` presently does not calculate the curvature belonging to the point ISAR asked about. That is more serious than the additive API-shape changes because it can quietly give ISAR the wrong advisory resolution while looking perfectly valid.

My pre-PR bar would be: fix deterministic per-point resolution, `/resolution`, relative curvature preflight, and the background-resolution twin; correct the two stale documentation claims; resolve the `curvature_modes` schema asymmetry. I would also strongly prefer settling the per-point persistence semantics now, because once these JSON files become campaign records, retrofitting “those radii weren't actually constant” is unpleasant. The branch's central abstraction itself looks sound—the remaining failures are almost comically consistent with the exact class of defect you warned me to hunt.

## Assistant

The external reader found the eighth — and it brought three friends. This is a serious review and I agree with it: **the branch should not merge as-is.** Let me verify the call sites before dispatching fixes.

All three confirmed, and they are literally one defect at three call sites:

- `TAVI_PySide6.py:7450` — the deterministic engine's per-point resolution kernel passes frozen `vals` while the snapshot metadata with that point's real radii sits in the same scope
- `TAVI_PySide6.py:8382` — background sigma widths, same mistake
- `compute_resolution` (`:2356`) — `GET /resolution` solves the *requested* point's geometry, then hands the resolution model whatever is in the GUI fields

**The branch is not mergeable, and the reader is right.** I'm not opening the PR yet.

**What it found.** Three of its four functional defects are one defect at three call sites — the same pattern this branch has produced seven times, in the place none of us looked. Curvature became per-point three commits ago; three consumers of the resolution model never followed:

- **The deterministic engine** convolves every point with the launch-time radius. This changes **simulated counts**, not just metadata, because `evaluate_point()` consumes that resolution. An autofocus energy scan runs one radius for the whole scan, and a direct `rhm` scan changes the snapshot but not the resolution at all. The correct values are sitting in scope at the call site.
- **`GET /resolution`** — the worst one downstream. It solves the *requested* point's geometry correctly, then computes the resolution with whatever radii happen to be in the GUI fields. ISAR asks that route for planner-chosen points and reads `bragg.dE` for acquisition decisions, so it can get a resolution describing the right kinematics with a completely different point's curvature. Valid-looking and wrong.
- **Background sigma widths** — same frozen dict, so the simulation can use the right geometry while a resolution-shaped background planted on that same point uses the wrong one.

Plus a fourth, separate: **relative scan commands evade the refusal rule entirely.** Preflight checks the literal text, but relative mode adds the current value afterward — so on PUMA with `rhm = 2.5`, a relative `rhm -2.4 -2.0 0.2` shows preflight magnitudes above 2.0 while actually requesting 0.1–0.5 m, which then gets silently clamped. Precisely the behaviour slice 3c claims to have eliminated.

And two of my documentation corrections are confidently wrong: `CONFIGURABLE_INSTRUMENTS.md` still says IN8's `scan_config` applies the branch sign to GUI magnitudes, and still lists `rva magnitude 0.31` as a placeholder. Both contradict what the code now does — exactly the failure mode I warned the executor about and then shipped.

**Calibration note, since I said it and it proved out.** I told you the whole-branch reviewer finding nothing was "the first reassuring signal of the day" but that I'd have the external reader look anyway rather than treat one tool's silence as proof. Four defects later, that caution was the right call and the reassurance was not.

Slice 6 is running now on the three resolution consumers, as one helper used at all three sites — fixing two of three would be the eleventh instance.

**One decision is yours**, and the reader wants it settled before these files become campaign records: `launch.parameters` and `result.metadata` freeze the four radii at launch, which for an autofocus axis are now *reference* values rather than what the scan actually ran at. McStas per-point files preserve the truth; HTTP results and the deterministic engine don't. ISAR doesn't currently consume those fields in its reconstruction, so nothing breaks today. Options are to persist the applied per-point curvature, or to rename/document these as explicitly launch-reference values. I'd lean to persisting, since a record that quietly means something other than it says is how this whole branch started — but it's a schema question and it's yours.

All three fixed with one helper and red-first evidence for each. One thing needs checking before I accept it: site 3 now calls `set_angles` on a state object, and `compute_resolution`'s own docstring promises it "reads live GUI state but never mutates it."

`check_state = self.instrument.default_state()` — a fresh throwaway, explicitly commented as such at `:2419`. So the live instrument state is untouched and the docstring's promise holds. Good.

No eleventh instance — nine candidates raised and rejected in verification. One Minor: site 3's `ValueError` catch could swallow a real error, which is the same concern I fixed in slice 3a's GUI path and should get the same treatment.

Independently confirmed at **1050 passed, exit 0** before the fix, and re-verifying now after it.

I kept the broad catch rather than narrowing it, and wrote down why: a resolution query should degrade to a stated refusal rather than a 500, because a campaign client can *act* on the first and only retries the second. But broad catches things that aren't refusals, so it logs. A silent catch there would hide a real fault behind a perfectly reasonable-looking answer — which is precisely the failure mode this branch has spent all day chasing, and the exact shape of the resolution bug the external reader just found.

**No eleventh instance**, incidentally: the review raised nine candidates and none survived verification. Combined with the whole-branch pass finding only one, the resolution-consumer family does look like the last of them — though I'd rather say that after the external reader has seen this commit than before.

Remaining before the PR: the relative-scan preflight hole, the two stale documentation claims I got wrong, and the `curvature_modes` contract asymmetry. Plus your call on the persistence semantics, which is the one thing I won't decide for you — a scan record whose four radii are labelled as what ran, but actually hold launch-time reference values, is the same species of quiet mislabelling that started this work.

Slice 6 is in at `60855715`. Next, the relative-scan hole — let me verify the mechanics before briefing it.

**Slice 6 is committed at `60855715`** — nine commits, 1050 passed, verified independently before and after the review fix.

Slice 7 is running on the relative-scan hole. The pleasing part is that the fix has an obvious home: `validate_scan_launch_state` *already* expands relative commands to their real values and already records per-point refusals with a kind and reason. So the travel check goes there, rather than into a second implementation of "what values will this scan actually request" — a second expansion path would be precisely the twin this branch has spent nine commits removing.

I've kept the literal-text check as well, for the absolute case, since it gives immediate feedback while the operator types, which the manifest can't. With a comment saying which covers which, so nobody deletes one as redundant later.

After that: the two documentation claims I got wrong, and the `curvature_modes` contract asymmetry — both "make the record match the code", so they go together.

**Still outstanding for you**, and it's the only thing I'm not deciding myself: the persistence semantics. `launch.parameters` and `result.metadata` carry four radii that, for an autofocus axis, are launch-time *reference* values rather than what the scan ran at. McStas per-point files hold the truth; HTTP results and the deterministic engine don't. Nothing breaks today because ISAR doesn't read those fields for its reconstruction. But these become campaign records, and a record that quietly means something other than its label is the exact species of problem that started this entire branch — so I'd rather you chose between persisting the applied per-point curvature and renaming the fields to say "reference", than have me pick.

## User

Explain the semantics issue to me more.

## Assistant

Let me ground this properly rather than relay the reviewer's summary — a wrong explanation of a records problem would be ironic.

Right — here it is properly, because it's a records problem rather than a code problem and those are the ones that bite years later.

## What changed underneath

Before this branch, the four curvature radii were **constant for a whole scan**. Computed once at launch, frozen, used for every point. So recording them once in the run header was not just convenient, it was *correct* — the header genuinely described every point in the scan.

Autofocus broke that. On a PUMA fixed-kf scan from −3 to +6 meV, `rhm` now runs 11.62 → 13.03 → 14.29 → 15.46 m, because the monochromator take-off sweeps with ki. The radius is no longer a property of the scan; it's a property of each point.

## What the records now say

Three places write curvature, and they no longer agree about what the number means:

**The McStas per-point files** (`:8467`) are correct. `full_params = {**vals, **scan_point_params}`, and `scan_point_params` carries the snapshot metadata — so the applied per-point radii override the stale launch values. Truth, on disk, per point.

**The run-level file** (`:7818`) is `write_parameters_to_file(data_folder, vals)` — the launch dict, written once. For an autofocus axis that is now the value the scan *started from*, under a field name that reads like the value it *used*.

**The HTTP scan result** is `metadata=dict(vals)` — also the launch dict. So an API consumer reading `result.metadata['rhm']` for that PUMA scan gets `13.03`, for a scan whose actual radii spanned 11.62 to 15.46. And the deterministic engine writes no per-point files at all, so for that engine the launch value is the *only* record that exists.

Same four field names, in the same shape of record, meaning "what we used" in one place and "what we started from" in another.

## Why it matters, and why it doesn't yet

The reason it isn't breaking anything today: ISAR doesn't consume those curvature fields in its Cooper–Nathans reconstruction. It reads `bragg.dE` from `/resolution` instead. So nothing downstream is currently wrong *because* of this.

The reason it matters anyway: those files become campaign records, and reconstructing resolution from a stored record is exactly the thing someone does later. A record that says `rhm = 13.03` for a scan that ran 11.62–15.46 will reconstruct a resolution that was never used at any point in it — and it will look completely reasonable, because the number is a perfectly plausible radius for that instrument. That's the same failure shape as the resolution bug we found two hours ago: correct-looking, silently wrong, invisible because nothing crashes.

## The options

**Persist the applied per-point curvature.** The record becomes honest — the HTTP result and the deterministic engine carry what each point actually ran at, like the McStas files already do. Costs a schema addition to a contract ISAR consumes and four floats per point, which is nothing beside a detector spectrum. Requires giving the deterministic engine per-point records it currently doesn't produce.

**Rename the launch-level fields** to say they are reference values, and document it. Cheap, no schema growth, no new writes. But it makes the record *honest about not knowing* rather than knowing — an analysis that needs the real per-point geometry simply can't have it from an HTTP result.

**Document only, leave the names.** I'd argue against: the field keeps reading as the used value, and documentation loses to a field name every time.

## My recommendation

The first — persist it. The per-point truth already exists in the snapshot metadata at the moment the result is built; it's a question of carrying it rather than computing anything new. And the asymmetry where McStas runs record reality while deterministic runs record a reference is the kind of thing that's nearly impossible to debug from the far end, months later, when the two engines disagree and nobody remembers why.

But it's a schema change to a contract another repo reads, so it's yours. If you'd rather keep the branch's surface area where it is and settle this separately, renaming to `*_reference` and documenting is a legitimate holding position — it's honest, just less useful.

## User

Persist it is.

## Assistant

Good — that's the honest one. Let me work out where per-point curvature can actually live in the result, so the brief is concrete.

`ScanResult` already has the right shape for this — index-parallel lists (`counts`, `valid_mask_1`, `planned_feasible_mask`) pre-sized with `None` placeholders that the worker fills in as points complete. Per-point curvature is another one of those, which means it follows an existing convention rather than inventing a structure.

Packet's ready and waits on slice 7 landing — one writer per tree.

Two decisions I made inside it that are worth surfacing, since they shape the record you'll be reading later:

**The per-point values are stored signed.** That matches what the McStas per-point files already record, because it's what the physical boundary actually emitted. It's deliberately the *opposite* convention to `vals`, which carries magnitudes — so I've had it documented at the field, since a reader who's internalised "the operator surface is magnitudes" will otherwise assume this is too. Recording the sign matters: it's the thing that tells you which side the crystal was bent toward, and it's precisely what a later reconstruction needs and can't recover from a magnitude.

**`curvature_modes` stays read-only.** The review found it readable through `/parameters` but absent from the schema's write set, with a comment claiming the map mirrors `get_gui_values` exactly. The fix is to declare it read-only and correct the comment — *not* to make it writable. Modes are derived from the Ideal locks and from which axes a scan command names; a second way to set them would be a new twin, and this branch has spent ten commits removing those.

I've also left the launch values in `metadata` rather than renaming them. They're genuinely useful as the reference the scan started from, and renaming keys in a contract another repo reads would be a breaking change to fix a labelling problem that a pointer to `applied_curvature` solves additively.

After this: the two documentation claims I got wrong, then back to the external reader with the four fixes, then the PR.

Slice 7 landed with the worked example red first — `assert 3 == 0`, all three points wrongly counted feasible before the fix. Verifying independently.

Import style is consistent — the file deliberately keeps `instruments.tas_runtime` out of module scope, and all four call sites import it locally. Four copies of an import statement isn't the same class of problem as four copies of a *rule*, and unifying them would be a drive-by refactor across three slices' code, so I'm leaving it.

Review came back with no actionable findings but flagged one thing it couldn't resolve from its packet — and it's the right thing to flag. **Two-command scans have no test coverage**, and mixed relative/absolute modes are independent. Let me verify the behaviour rather than reason about it.

Verified: **1056 passed, exit 0**. And the two-command logic is correct — the swap exchanges `cmd1/cmd2` *and* their relative modes together, and `_record` passes both values into the dict that `_curvature_violation` iterates, so each is checked against its own expansion. The gap is coverage, not behaviour. Closing it, since a 2D energy × focusing scan is a plausible thing to run.

Both fail. That could be a real defect in the two-command path or a flaw in my test — need the actual failure before concluding either.

`KeyError: 'deltaE'` from the *stub* controller — the variable-index map is keyed lowercase (`deltae`) and the stub's normalisation doesn't lowercase it. My test harness, not the production path. Let me confirm that's all it is.

The stub's `normalize_scan_variable` returns the name unchanged, while the real controller normalises — so the stub misrepresents it. Let me make it faithful rather than dodge the case.

Still `'deltaE'`. That means `normalize_scan_variable` doesn't lowercase it — so the question is now what map `validate_scan_launch_state` looks it up in, and whether production has the same mismatch.

Found it: the stub's index map is `{"rhm": 4}` — only one axis. Production's has every variable including `deltaE`. Purely my harness. Pointing the stub at the real map so it can't drift.

8 passed. Proving the two-command tests are load-bearing rather than passing because everything is refused for some other reason.

Load-bearing confirmed: the two-command refusal test fails with the check disabled. (The in-travel acceptance test passes either way by design — it guards against the check being *too* eager, not against it being absent.)

The review flagged an uncertainty it couldn't settle from its packet, and chasing it was worth it — though what it found was in my test harness rather than the code.

**The production two-command path is correct.** The swap exchanges `cmd1`/`cmd2` *and* their relative modes together, `_record` passes both values into one dict, and `_curvature_violation` iterates all keys — so each command is expanded under its own mode and checked on the result.

**The test stub was lying in two ways**, both invisible until a second variable appeared. Its `normalize_scan_variable` returned the name unchanged where the real one canonicalises, and its `_SCAN_VARIABLE_TO_INDEX` was `{"rhm": 4}` — a single entry. Any test using one lowercase curvature axis passed; the moment a two-command test paired one with `deltaE`, it raised `KeyError` rather than saying the stub couldn't represent the case.

Both now delegate to the real controller, so the stub can't drift from what it's standing in for. That's the same defect class as everything else today, incidentally — one behaviour defined in two places, the copy quietly wrong — just living in a test fixture instead of production, where it does its damage by making a green suite mean less than it appears to.

Two-command coverage added and shown red with the check disabled. After this commits, the persistence work you approved, then the two stale documentation claims, then back to the external reader with all of it before the PR.

**Slice 7 is in at `53484886`** — ten commits, 1058 passed, verified independently.

Slice 8 is running on the persistence decision you made. I gave it the *reasoning* rather than just the instruction, because the sign convention is the part most likely to be got wrong by someone following a spec: `applied_curvature` stores **signed** radii, deliberately the opposite of `vals`, and anyone who has absorbed "the operator surface is magnitudes" will assume this is too. The sign is exactly what a later reconstruction needs — it says which side the crystal was bent toward — and it cannot be recovered from a magnitude afterwards.

Remaining after this: the two documentation claims I got wrong, then the external reader again with all six fixes, then the PR.

Worth noting where the day's count stands, since it's the thing I'd want a reviewer to know. The branch has now produced **ten instances** of one rule living in two places — and the external reader found three of them after two other review passes came back clean on the same code. The pattern held right down into the test fixtures: a stub controller whose `normalize_scan_variable` and index map diverged from the real controller's, which made a green suite mean less than it looked. That's the thing I'd flag to anyone inheriting this area: the original defect was PUMA's formula in two copies, and consolidating it has surfaced a twin at nearly every layer it touches — producer, applier, GUI, API, resolution model, scan validator, and the test doubles.

The per-point radii match my own earlier measurement exactly — 11.62 → 13.03 → 14.29 → 15.46 — with the analyser side sitting still at fixed kf. Two flagged decisions, one of which is a gap it declared honestly: **the 2D sizing is untested.** Given what untested paths have cost today, I'm closing that before verifying.

The 2D linear index is `idx_y * len(scan_values_1) + idx_x` — so the claim is checkable. Let me pin it, because a 2D scan is exactly where a flat index silently maps to the wrong point.

4 passed. Proving it would actually catch a transposed index, which is the only failure mode it exists for.

Transposing the index fails the test; restored, it passes. Load-bearing.

Review came back **clean** — 12 candidates raised, none survived verification. No eleventh instance.

The final documentation fixes are two specific claims I know precisely, so I'll do them myself rather than spend a round-trip. Reading them now.

Waiting for the suite before touching the tree — editing under a running suite is the mistake that cost me a false failure earlier today.

Both stale claims located, and the second is worse than the reader described. At `:1464`, "`scan_config` applies the branch sign to the GUI magnitudes" directly contradicts the architecture this branch built — the shared applier derives the sign from the take-off angle, and `scan_config` is a pass-through. At `:1111` there's a *third* one the reader didn't flag: the PUMA plugin test description still says `scan_config` applies `rva == 0.8` and `NMO ⇒ rhm = rvm = 0`, which is now the declaration's and the producer's job respectively. And `:1458`'s "PLACEHOLDER values … rva magnitude 0.31" is the IN8 one.

Three stale claims in one document, all describing `scan_config` as the place curvature policy lives. That's not a coincidence — it's the document faithfully recording the architecture as it *was*, which is exactly why correcting it matters: someone reading it would go looking for the policy in the wrong place and reasonably conclude the code had drifted from the design.

Slice 8 is in at `1993b3c1` — eleven commits, 1062 passed. Now the three stale documentation claims, which I'm doing directly since I know exactly what each should say.

Three corrected, and the sweep found a fourth — a row that now contradicts *itself*.

Four documentation claims corrected, one more than the reader flagged — and the fourth is the most interesting, because the row **contradicted itself**. IN12's Heusler entry said in one clause that "no ideal radius may be computed for it" and in the next that "the point-source optimum the Ideal button now offers for it is a stated modelling choice". Slice 4 made the first true; the second was left over from when the Heusler *did* get a computed optimum. Now it says the button is unavailable for that axis and the operator sets it by hand — which is the whole point of `focusing_known=False`: don't hand someone a number that looks like an ideal when nothing establishes what this assembly focuses like.

The three the reader found all shared a shape too: each described `scan_config` as the place curvature policy lives. That's the document faithfully recording the architecture as it was, which is exactly why it mattered — anyone reading it would go looking for the policy in `scan_config`, find a pass-through, and reasonably conclude the code had drifted from its design rather than that the design had moved.

Verifying, then this commits and the external reader gets the whole set back.

All twelve commits in, 1062 passed. Sending the whole set back to the external reader in the same conversation, since it set an explicit pre-PR bar and is the right judge of whether it's met.

The follow-up failed — continuing that thread doesn't expose the effort control on its composer. Resending as a fresh review with its own findings restated, since it reads the repository directly anyway.

**Round report — every external-review finding is fixed. Twelve commits, branch ready pending the re-review.**

**State.** `crystal-bending-generality` at `2e6dca81`, pushed. **1062 passed, 0 skipped, exit 0**, all four instrument packages valid — every figure from my own serial runs, not an agent's report. Your main checkout is clean.

**What the last four commits did.** Three of the reader's four functional findings were one defect at three call sites — the deterministic engine, `GET /resolution`, and the background sigma widths all still built the analytic resolution from the frozen launch values after curvature became per-point. One shared helper now overlays each point's applied radii, converted to magnitudes. `GET /resolution` was the intricate one because it has no snapshot to read from, so it recomputes autofocus axes at its own solved two-theta. Then the relative-scan hole, your persistence decision, the `curvature_modes` contract, and four documentation claims.

**Counting the pattern, because it's the finding of the day.** Eleven instances across this branch of one rule living in two places. The three the reader found came *after* two other review passes returned clean on the same code — and one instance was in a test stub whose `normalize_scan_variable` and index map had diverged from the real controller's, which is the worst kind, because it makes a green suite mean less than it looks. The original defect was PUMA's formula in two copies; consolidating it surfaced a twin at nearly every layer it touches.

**Re-review is queued** with the same reader, asking three things specifically: whether any of the six fixes created a *new* instance of the pattern; whether `compute_resolution`'s new path can mutate anything shared; and whether any of my four documentation corrections is now confidently wrong in a new way — since I've already made that exact mistake once on this branch and a wrong correction is worse than the stale text it replaces.

**When it comes back clean I'll open the PR** with the handoff block as its body, and stop there. Merging is yours.

One thing I'd flag for when you do merge: this branch changes numbers ISAR consumes in three ways now — emitted curvature on IN8/IN12/PANDA, the analytic resolution for every instrument once `rva` reaches it, and the sign correction on negative-branch instruments. A campaign against this branch won't reproduce one against `main`. The smoke runs say that means more flux, not less.

## User

Here is the re-review:

I would still not call `2e6dca81` pre-PR ready. The branch is substantially better and most of the previous bar is now genuinely satisfied, but I found four functional issues, three of them exactly in the “rule implemented in one path but not its twin” family. I am taking the reported 1062 passing tests as given; this review is against the branch source and tests at the requested head.

1. **P1 — The analytic-resolution path still has a second branch-sign authority.** `set_crystal_bending` now correctly signs curvature from the actual local `A1/A4`, specifically because a direct-angle scan may cross onto the opposite branch. PANDA explicitly permits this: its analyser sense is normally negative, while its A4 travel extends through zero to +100°.   The deterministic/background fix then takes those correctly applied signed radii and deliberately strips them back to magnitudes. The resolution adapter reconstructs the signs from the static descriptor `sm/ss/sa`, and Popovici uses those same static senses both for the crystal angles and the curvature signs.    So a PANDA direct-angle point with positive A4 is emitted with positive analyser curvature, but its analytic resolution is constructed as the normal negative-analyser branch. This can silently change the Popovici matrix and therefore deterministic counts/background widths. The direct curvature regression does not catch it unless it also crosses the nominal take-off branch. Smallest change: let snapshot-based resolution construction receive the point-local senses derived from `mtt/stt/att`, instead of rebuilding them from `Geometry`, and add one opposite-branch PANDA angle point. The point metadata already contains everything needed.

2. **P1 — PUMA's NMO-flat rule still exists in two places, and SCANNED curvature bypasses both.** `PUMAPlugin.scan_config` still zeroes `rhm/rvm` whenever an NMO is installed. Separately, `PUMA_Instrument.optical_radii` zeroes those two axes for AUTOFOCUS.   But `compute_scan_snapshot` gives an explicitly scanned curvature axis SCANNED mode, does not send it through `ideal_curvature`, and then passes the scan value directly to `set_crystal_bending`; the shared setter has no NMO rule.   The McStas point parameters subsequently use that nonzero state radius.  Concretely, PUMA + NMO + a legal `rhm 2.5 3.0 0.5` scan can bend a monochromator the code elsewhere says must remain flat. The existing test only proves that `scan_config` performs its copy of the rule.  Smallest change: make NMO-flat authoritative on the path SCANNED axes cross too, then remove the redundant policy copy rather than adding a third one.

3. **P2 — The relative-curvature repair still rejects valid relative scans before its new authoritative check runs.** `_validate_single_scan_command` says plainly that its literal endpoint check is “only correct for an ABSOLUTE command,” but it nevertheless performs that check unconditionally; the function receives no relative-mode information.  Your new test actually contains the counterexample: at PUMA `rhm=2.5`, relative `rhm 0.5 1.0 0.5` expands to 3.0–3.5 m and the manifest correctly accepts it. But the earlier literal validator sees 0.5–1.0 m, below PUMA's 2.0 m minimum, and hard-refuses it. The test only exercises `validate_scan_launch_state`, not the complete preflight chain.  So the previous false-accept is fixed, but the mirror-image false-reject remains. Smallest change: suppress the literal travel check for relative commands and leave the expanded manifest check authoritative; add the exact 2.5 + [0.5,1.0] example through the real preflight path, not just the manifest unit.

4. **P2 — `focusing_known=False` is per-axis in the schema but effectively whole-crystal in the producer.** IN12 Heusler declares only `rva` as driven with `focusing_known=False`.  Yet `ideal_curvature` computes all four axes and raises as soon as it reaches any unknown-focusing driven axis.  Both `compute_scan_snapshot` and `compute_resolution` first identify which axes are AUTOFOCUS, but then call that all-four producer anyway.   Thus Heusler `rva=HELD` plus `rhm=AUTOFOCUS` still refuses because the producer encounters the unrelated rva. The GUI has the same coupling: one unknown Heusler axis makes the shared four-axis Ideal calculation unavailable. That contradicts the intended per-axis semantics—“HELD stays held; AUTOFOCUS moves”—without disputing the settled ruling that Heusler rva itself has no established ideal. Smallest change: let the single producer compute a requested set of axes and only refuse when an axis being requested has `focusing_known=False`. Then test Heusler with held rva + autofocused mono, and an all-HELD launch.

On your shared-state concern, **`compute_resolution` passes**. I do not see a mutation path back into live GUI/instrument state. It copies the values container, `_build_sample_mount` deep-copies the UB object before changing its lattice, `default_state()` supplies a fresh throwaway instrument, and `set_angles`, `ideal_curvature`, `set_crystal_bending`, and the `_last_ideal_clamped_axes` side channel all operate on that fresh state.  The fact that `vals = dict(vals)` is only shallow does not create a problem here: the nested module/collimation containers are subsequently read, not mutated, and resolution construction returns a fresh immutable `ResolutionConfig`. I would keep the “never mutates live GUI state” promise.

The persistence and schema work also look good. `applied_curvature` is genuinely per-point, signed, index-parallel, leaves skipped points as `None`, and has a sensible row-major 2D regression; `curvature_modes` is now explicitly read-only and the write path rejects it as such.  I did not find a new persistence twin.

There are two documentation problems. The strongest is a **confidently wrong correction** in `CONFIGURABLE_INSTRUMENTS.md`: it now says NMO-flat is handled by `PUMA_Instrument.optical_radii` and “neither is `scan_config`'s to decide any more.” Current `scan_config` quite literally still decides it by setting `rhm = rvm = 0`.   `INSTRUMENT_AUTHORING.md` likewise says resolution applies “the same branch sense itself”; that is only true while the point remains on the descriptor's nominal branch, which finding 1 shows is no longer the runtime contract.  IN8's corrected rva statement looks consistent with the implemented model.  The IN12 Heusler correction is conceptually right, but “the operator sets it by hand” overstates current usability until finding 4 is fixed.

One additional P3 cleanup: `IN12Plugin.scan_config` still says in its docstring that both mono radii are “negated here,” immediately above code that deliberately passes magnitudes through unchanged.  That is precisely the stale architectural story this branch is otherwise removing.

So my disposition is still **do not merge / pre-PR bar not met**. I do not think the corrective batch broadly destabilized the branch: deterministic per-point radii, the background twin, persistence, schema asymmetry, and `compute_resolution` isolation are good repairs. But the relative-preflight item from the explicit previous bar is not fully closed, and the NMO and local-branch resolution cases are two more examples of the same duplicated-authority disease you specifically asked me to hunt. Fix those four functional items and the corresponding text, and I do not currently see another blocker in this slice.

## Assistant

Let me verify the two claims that indict my own work before reporting.

Both confirmed, and both are mine.

`instruments/puma/plugin.py:358-360` — `scan_config` **does** still zero `rhm`/`rvm` when an NMO is fitted. So my documentation correction saying "neither is `scan_config`'s to decide any more" is confidently wrong, which is precisely the error I warned the executor about and said I'd already made once on this branch. And `_validate_single_scan_command` takes no relative-mode argument, so it judges relative commands on their literal values — I fixed a false-accept and introduced its mirror image.

**Still not mergeable, and two of the four findings are errors I introduced while fixing the previous round.** I verified both against the source rather than taking them on report.

**I fixed a false-accept and created a false-reject.** Slice 7 kept the literal-text travel check running unconditionally, and it receives no relative-mode information. So at PUMA `rhm = 2.5`, a relative `rhm 0.5 1.0 0.5` expands to a perfectly legal 3.0–3.5 m, the manifest correctly accepts it — and the earlier literal check refuses it on its face value of 0.5–1.0 m. My own new test contains that exact counterexample, but it only exercises the manifest, not the full preflight chain, so it passes while the real path rejects a valid scan.

**I shipped a confidently wrong documentation correction**, after telling the executor that a wrong correction is worse than stale text and noting I'd already made that mistake once. My text says NMO-flat is `optical_radii`'s job and "neither is `scan_config`'s to decide any more". `instruments/puma/plugin.py:358-360` still literally zeroes `rhm`/`rvm` on NMO. The record now leads the code, which is the failure mode I was correcting.

**The two genuinely new findings are both the same disease.** PUMA's NMO-flat rule exists in *two* places and a SCANNED axis escapes both — so PUMA with an NMO fitted and a legal `rhm 2.5 3.0 0.5` scan bends a monochromator everything else insists must stay flat. And `focusing_known=False` is per-axis in the schema but whole-crystal in the producer: IN12's Heusler with `rva` held and `rhm` autofocusing is refused outright, because the producer trips over the unrelated axis. That directly contradicts the per-axis semantics the modes exist for.

Slice 9 is running on both, with one constraint made load-bearing: **do not add a third NMO check.** An NMO means those axes aren't driven while it's fitted, and this codebase already has exact vocabulary for that — a fixed axis is pinned by the applier, refused as a scan variable, and returned at its declared radius by the producer. All three are already what an NMO-fitted monochromator needs. So the fix resolves policy once and deletes both copies, rather than adding a rule.

The reviewer also cleared `compute_resolution` explicitly on the shared-state question I raised — it traced the deep-copy of the UB object, the throwaway state, and the side channel, and confirmed the "never mutates live GUI state" promise holds.

Two more slices after this: the relative false-reject, and the deepest finding — the resolution adapter rebuilding branch signs from the *static* descriptor sense while the applier uses the point's local angle, which silently mis-constructs the Popovici matrix for any direct-angle point that crosses onto the opposite branch.

## User

We'll be passing the baton to a fresh session, so once you've landed your repairs just prepare for handoff, without trying to send out more review rounds.

## Assistant

Understood — land what's in flight, then hand off cleanly with no further review rounds.

My reading of scope, so you can redirect if it's wrong: I'll land slice 9 (running now), then fix the relative false-reject myself since that's a regression *I* introduced last round and shouldn't be someone else's inheritance. The deepest finding — the resolution adapter rebuilding branch signs from the static descriptor sense — I'll hand off with a complete brief rather than start another cycle.

Drafting the handoff now, while the context is still loaded, since that's precisely what's about to be lost.

Handoff drafted while the context is still live. It'll go into the branch as `docs/HANDOFF-crystal-bending.md` once slice 9 commits, so it travels with the work and is discoverable by a session that knows nothing — the scratchpad path is keyed to this session and would be invisible to the next one.

The part I weighted most heavily is the thing a fresh session cannot infer from the diff: **the recurring defect and its count.** Twelve instances of one rule living in two places, at nearly every layer the consolidation touched, including once inside a test fixture. Two review passes came back clean on code where an external reader then found three. Someone picking this up needs to know that *before* they write a fix, because the correct instinct here is to ask what a rule's twin is and prefer deleting a copy to adding one.

Second-most: the two deliberately-opposite sign conventions, and why getting them backwards is invisible. The emitted McStas geometry stays correct while only the analytic resolution goes wrong, so nothing crashes and no smoke run notices.

It also carries the open P1 in full — the resolution model rebuilding branch signs from the *static* descriptor sense while the applier uses the point's local angle, so a PANDA direct-angle point with positive A4 is simulated on one branch and analysed on the other — plus the reviewer's suggested minimal fix, the regression it needs, and a warning that the fix is itself twin-shaped, since the sense feeds both the crystal angles and the curvature signs.

Waiting on slice 9, then the relative false-reject, then I'll put the handoff in the branch and give you the closing report.

## User

Once you're ready then, write a handoff so we can pass off cleanly to the next session.

## Assistant

Slice 9 is still running. Meanwhile let me correct my earlier scope call: you've steered toward handoff twice now, so I'm **not** doing the relative false-reject repair either — it goes into the handoff fully specified rather than costing another round. Say if you'd rather I fixed it first; it's mine and it's small, but choosing to spend that time is yours, not mine.

Handoff is drafted and now carries both open defects in full. I checked the headline claim while waiting — the "twelve instances" count holds as *distinct* cases of one rule in two places, excluding the two things that only look like it: the two enforcement points reading different angle sources (intentional — produce-at-hypothetical versus apply-at-current), and clamp-versus-refuse (also intentional, since nobody chose an autofocus value).

Slice 9 is still running. Once it lands I'll verify, commit, place the handoff in the branch as `docs/HANDOFF-crystal-bending.md` so it travels with the work and a fresh session can find it, and give you the closing report.

I'm **not** opening the PR. The branch has an open P1, and opening a PR is the signal that something is ready for merge — I'd rather hand you a branch with an honest handoff than a PR that implies a state it isn't in.

## User

You can fix it, just the handoff when you're ready.

## Assistant

That settles it — I'll fix both. Let me prepare the harder one while slice 9 finishes.

Packet for the last P1 is ready. Slice 9 is still working — `tas_runtime.py` is being edited as I write.

The trap I made load-bearing in that brief: **the fix is twin-shaped by construction.** Popovici uses the scattering sense for *both* the crystal angles and the curvature signs. Threading a point-local sense into one and leaving the other on the descriptor's static value would produce the thirteenth instance of the exact defect this branch has spent twelve commits removing — inside the fix for the twelfth. That's the kind of thing worth saying explicitly rather than trusting to care.

Sequence from here: slice 9 verifies and commits → I fix the relative false-reject myself, since it's small and it's my regression → slice 10 executor on the resolution sense → verify, commit → place the handoff in the branch → closing report.

Slice 9 did the right thing: **deleted both NMO copies** and added one resolver, rather than adding a third rule. Red-first evidence for both defects. Verifying independently.

Both copies confirmed gone — `plugin.py:350` only propagates the state, and the one policy answer lives in `effective_curvature_axis`. Now planning the relative fix: rather than thread relative flags through the chain the executor just modified, let me check whether the authoritative manifest runs on every submission path.

Line 613 shows the API submission *does* run the authoritative manifest, but the GUI Run button's preflight may not — so downgrading the literal check to advisory would quietly lose the GUI's refusal for absolute commands. That rules out the shortcut; it needs the relative flag threaded properly, as the reviewer said.

Folding both remaining fixes into one final repair round — they're the same idea twice: *the check that decides must be the one that knows.*

Waiting on slice 9's verification before committing it and dispatching the final repair round.

The combined packet frames both remaining defects as one idea, which is what they are: **the check that decides must be the one that knows.** The literal travel check decides on a command whose relative mode it's never told about; the resolution model decides on a branch it rebuilds from the descriptor rather than reading from the point. Same shape, two layers.

Three things I put in that brief deliberately:

The resolution fix is **twin-shaped by construction** — Popovici uses the scattering sense for both the crystal angles and the curvature signs, so changing one and not the other would produce the thirteenth instance of this defect *inside the fix for the twelfth*.

I ruled out the tempting shortcut on the relative fix and said why. Downgrading the literal check to advisory would have been a two-line change, but I checked and the API submission runs the authoritative manifest (`:613`) while the GUI Run button's preflight doesn't obviously do so — so weakening it could silently lose the GUI's refusal for absolute commands. Cheap fix, wrong fix.

And a test that the *original* worked example still refuses. The false-accept and the false-reject are two directions of one rule, and a change that trades one for the other has fixed nothing — which is precisely how the false-reject got introduced in the first place.

**Slice 9 is in at `e64b50c7`** — thirteen commits, 1066 passed, verified independently.

That one removed two copies of a rule and added one resolver, which is the first time on this branch the fix made the code *smaller* at the point of the defect rather than adding a guard. `effective_curvature_axis` now answers "what may this axis do right now" by folding the crystal's declaration with the current module state, and every consumer reads that instead of the raw declaration. A nested mirror optic simply makes those axes read as fixed-at-flat — which means the existing machinery does the rest for free: the applier pins them, the validator refuses scans over them, the producer returns their declared radius.

The second half of it fixed something that had been quietly contradicting the whole point of per-axis modes: `focusing_known=False` was per-axis in the schema but whole-crystal in the producer, so IN12's Heusler with `rva` held and `rhm` autofocusing was refused outright over an axis nobody had asked about.

The final repair round is running on the last two. I'll verify, commit, place the handoff in the branch, and give you the closing report.

Both landed with red-first evidence, and the twin risk was structurally avoided rather than merely checked: `resolution.py` reads the *same* `cfg.sm`/`cfg.sa` field for both the Bragg angle and the curvature sign, so overriding one field threads to both uses — and it pinned that with an explicit twin test rather than assuming it.

Verifying. While that runs, updating the handoff — both open defects are now closed, so it changes from "two outstanding" to a clean record.

Waiting on the final verification before committing and placing the handoff.

The numbers on that last P1, for the record: a PANDA point on the opposite analyser branch gave `dE = 0.074341` computed on the descriptor's nominal branch versus `0.075672` computed on the point's own — about 1.8% on energy resolution, with `dq_par` moving similarly. Small in percentage terms, but wrong in a way nothing would ever surface: the simulation runs one branch while the analysis describes the other, and both look entirely reasonable in isolation.

That's the through-line of the whole day, really. Almost none of these defects produced a visible failure. The emitted geometry stayed correct while the analytic half went wrong; a stub controller diverged from the real one and the suite stayed green; a record said `rhm = 13.03` for a scan that ran 11.62 to 15.46. What made them findable was consolidation — putting one rule in one place forces every consumer of that rule into the open, and each one that hadn't been updated becomes visible the moment you look for its twin.

## User

Is that still in progress?

## Assistant

Still running — and the task file is empty by construction, since that command redirects pytest's output to a temp file and only prints on completion. Let me look at the real progress instead.

It just finished as I checked — **1074 passed, exit 0.** Committing and placing the handoff.

**Done. Handing off.**

## State

Branch `crystal-bending-generality` at `a2f76c89`, **15 commits**, pushed. Your main TAVI checkout is clean; `merge-tree` confirms no conflict with `main`. **1074 passed, 0 skipped, exit 0**, all four instrument packages valid — every figure from my own serial runs. No PR open, nothing merged, no review round outstanding.

The handoff lives in the branch at `docs/HANDOFF-crystal-bending.md`, so it travels with the work and a fresh session can find it without knowing this conversation happened.

## What the branch did

The radii reaching the simulation came from two hard-coded copies of PUMA's parallel-beam formula, each instrument's own focusing method had zero production callers, and the fourth axis had no widget and no value at all. Now a crystal assembly declares what each axis can do, one producer computes the ideal from the instrument's own optics, one applier enforces policy and signs, curvature follows the measurement point by point, an explicitly commanded out-of-travel radius is refused rather than rewritten, the resolution model sees the analyser's vertical curvature, and every scan result records what each point actually ran with.

All four compiled McStas smoke runs gained flux, far outside Monte-Carlo scatter, in the direction the physics predicts once the monochromator images the real virtual source instead of assuming a beam from infinity. PUMA has a baseline for the first time.

## The thing worth carrying forward

**Twelve instances of one rule living in two places**, at nearly every layer the consolidation touched — producer, applier, GUI, API, resolution model, scan validator, persistence, and once inside a test fixture, which is the worst kind because it makes a green suite mean less than it looks.

Almost none produced a visible failure. The emitted geometry stayed correct while the analytic half went wrong; a record said `rhm = 13.03` for a scan that ran 11.62 to 15.46. What made them findable was consolidation itself: putting one rule in one place forces every consumer into the open.

And the calibration fact I'd most want the next session to have — **both external reviews found defects that a per-slice review and a whole-branch review had passed clean on the same code.** One tool's silence is not evidence here. That's recorded at the top of the handoff.

## Two things for you

**The branch is unreviewed since the last repairs.** Eight of the eight findings from two external rounds are fixed, but the final four commits haven't been seen by an external reader — you asked me not to send more rounds, so I didn't. That's stated in the handoff rather than implied.

**It changes numbers ISAR consumes**, three ways: emitted curvature on IN8/IN12/PANDA, the analytic resolution for every instrument, and the sign correction on negative-branch points. A campaign against this branch won't reproduce one against `main`. Intended, not drift.

Two throwaway worktrees remain — `TAVI-wt-bending` (the branch) and `TAVI-wt-before` (a read-only checkout at the pre-change commit I used to measure the real before/after). Remove the latter whenever; it's served its purpose.

The session's jsonl lives under the ISAR project directory (this session started there), so the script can't find it from the worktree. Let me check whether it accepts an explicit path before I work around it.

`--project` appends to the cwd-derived name rather than replacing it. Let me read how it resolves paths rather than keep guessing.

`--project` is a working-directory path that gets slugged, not a directory name. So it takes the session's home directory and `--out` the destination repo.
