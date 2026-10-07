# UB matrix audit and improvements

**Date:** 2026-09-30  
**Session:** cb41e829-2c45-4f33-8d3e-1d44ee050a80

*Cleaned transcript: tool calls, tool results, thinking and harness notices removed. Nothing else edited.*

## User

I had a recent session where the UB matrix wasn't working out... I tried it, pinning angles and such, and got nonsensical results. Can we audit this and see if there are issues to fix? Improvements to make as well to make it more intuitive and clear to a user?

## Assistant

Quick status: I'm reading the UB code path (the fit math, the geometry it relies on, and how "take position" captures angles) before running a numerical round-trip test.

Status: found one concrete suspect already (the peak-fit path ignores the flipped scattering-sense sign convention); now checking whether the vertical tilt gets applied twice in the simulation.

Status: I'm writing a numerical probe that composes the McStas rotation chain for the sample and checks whether the simulated crystal actually diffracts at the angles the UB matrix predicts.

The write gate blocks even a scratch file without a bound job, so I'll pipe the read-only probe straight into Python instead; it writes nothing.

Section 2 is decisive already. Section 1 fails even for identity, which means my model of the McStas chain is off somewhere, so I'm breaking it down per reflection before I trust it.

Two of the chain orderings fail, and so does TAVI's own internal geometry function. One last quick measurement: how large is the miss, in degrees, for the small tilts a training exercise produces?

*She sets the coffee down on the blotter, slides off the heels under the desk, and turns the monitor toward you.*

Your results weren't your fault. The UB workflow has two real bugs that produce nonsense, and a design flaw that makes the whole exercise circular. Nothing is edited yet: this session has no managed job bound, so I only read code and ran Python probes that change nothing on disk.

## Bugs (confirmed numerically)

**1. On IN8, IN12 and PANDA the fitted orientation comes out 180° wrong.**
- Those three instruments scatter to the left (`sense_sample = +1`). For that case the angle solver flips the sign of Q; see `instruments/tas_runtime.py:908`.
- The peak fit in `tavi/ub_matrix.py:113` works Q back out of the recorded angles without that flip.
- In the probe, true orientation → angles → "Take Position" → Calculate UB gave **0.00° error on PUMA and exactly 180° on all three left-scattering instruments**, for both the 2-peak and 3-peak fits.
- The existing test (`tests/test_tas_geometry.py:137`) only covers PUMA's direction, so it never saw this.

**2. Any reflection with a vertical component is driven to the wrong angles in the simulation.**
- For such a reflection TAVI treats the χ angle (`saz`) as a tilt that follows Q (`tavi/tas_geometry.py:199`).
- McStas applies the same number as a rotation about the fixed beam-frame x axis, outermost in the sample chain (`tavi/instrument_helpers.py:106`).
- TAVI's own two geometry paths also disagree with each other here (`q_sample_from_angles` vs `solve_instrument_angles`).
- Reflections in the horizontal plane match exactly. Tilted ones miss by these amounts:

| Orientation tilt | Median miss | 90th percentile |
|---|---|---|
| up to 2° | 0.6° | 2.0° |
| up to 5° | 1.5° | 4.8° |
| up to 10° | 3.0° | 9.7° |

- A crystal's mosaic spread is about 0.5°, so these peaks simply aren't there when you drive to them. After any real or training misorientation, "pinning angles" chases peaks that aren't where the UB says.
- One caveat: I rebuilt McStas's rotation rules in Python rather than running McStas. The exact in-plane match supports the reconstruction, but the fix should begin with one real McStas run on a tilted reflection.

**3. Smaller bugs:**
- Restoring a saved misalignment hash on startup crashes and prints "Failed to restore misalignment". It passes three values to a method that takes two (`TAVI_PySide6.py:5830`).
- A failure while refreshing the scattering-plane display is caught and dropped without any message (`TAVI_PySide6.py:5191`).

## Design flaw (a decision for you)

TAVI keeps a single orientation matrix (U) and uses it for two things:
- **Physical truth:** how the simulated crystal is actually mounted. It goes into McStas as the mount rotation (`TAVI_PySide6.py:2432`).
- **Your model:** the UB you fit, which turns HKL into angles.

Because they're the same object, clicking Calculate UB physically re-mounts the simulated crystal to match your fit. A wrong UB can never look wrong, and training mode has nothing hidden to find:
- **The answer is shown.** Loading a training exercise writes the teacher's U into the visible UB display.
- **Correct work gets penalised.** The training check wants both U = teacher's U *and* ψ (the in-plane angle offset) = −(hidden in-plane misalignment). A correct fit folds that offset into U, which is how a real instrument behaves.

The fix I'd propose: add a separate "true mount" (set by a training hash or a sample-mount setting, and hidden in training) that only the simulation reads. The UB stays your model and only drives HKL → angles. Then a wrong UB finally *misses peaks*, as on a real instrument. This changes the shape of the program (the saved-state format, the API sample state, and how training works), so I'd like to talk it through with you rather than hand you a menu. In particular: should a normal, non-training session start with truth = identity and let you set it, or should truth follow the UB until you "lock" it?

## Clarity improvements (smaller, independent)

- **Show residuals after Calculate UB.** For each peak, show the |Q| mismatch and the angle between observed and predicted Q. Also check the angle between the two peaks against the angle between their HKLs, which catches a mis-indexed peak (every serious TAS package does this). Today you get no diagnostics at all.
- **"Take Position" should record the ψ/κ offsets** (the operator's in-plane and out-of-plane alignment corrections) or say it ignores them.
- **"Refine Lattice" only refines one overall scale factor** (the crystal system is never passed in). The button should say so.
- **Relabel the scattering-plane panel.** "χ tilt" is really the elevation of the c* axis, not a misalignment, and the plane normal should be shown as small integer Miller indices.

## Next step

I'd suggest **T2** (a managed job with several commits and review). Order: bug 1 plus a test for both scattering directions; one real McStas check, then fix bug 2; the residual display. The truth/model separation should be its own **T3** after we've discussed it. To start, open with `acs-job open --repo TAVI --tier T2 --goal "..."` or say `/t2`.

Housekeeping: the startup hook flagged `AGENTS.md:321`. That memory line (the ChatGPT external-review one) is 235 characters, over the 160 limit. Want me to run `/memory-harvest`?

*She taps the 180° row on the screen with one nail, then leans back and crosses her ankles.*

The job is open and bound (`j1e557308ac1c`). The goals file has no body yet, so there's nothing for this work to strain against. Starting the design discussion now.

*She flips to a fresh page in the steno pad and tucks a forelock behind her ear.*

The job is open and bound to this session: `j1e557308ac1c`, tier T2, and it lands once the evidence checks pass. Before anything is built, we agree the design, one question at a time.

## Standing

**The idea.** Make UB alignment trustworthy and readable. That means:
- a peak fit that works on every instrument;
- a crystal in the simulation that actually diffracts at the angles TAVI drives to;
- a UB result that tells you when your inputs are inconsistent.

**What exists.**
- **Fit maths.** The peak fit (`tavi/ub_matrix.py`) is correct in itself. It is fed Q with the wrong sign on IN8, IN12 and PANDA, the three instruments that scatter to the left.
- **The dock.** The UB dock and the training exercise work mechanically.
- **The goals file.** `DESIGN_GOALS.md` has no body yet, so there's nothing for this work to strain against.

**Easy:**
- **The sign fix.** TAVI knows which way the instrument scatters, so the fit only has to use that sign.
- **The restore crash.** One wrong call.
- **Residual display.** It needs numbers the fit already computes.

**Hard:** the tilt. TAVI's angle maths and the McStas sample chain disagree about what χ physically *is*. Whichever we pick also affects:
- sibling repo ISAR, which carries its own copy of `tas_geometry.py` and `ub_matrix.py`;
- TAS_MCP (the TAS feasibility tool server), which imports the `tavi` package;
- the API's angle readouts.

**Order of questions:**
1. What χ physically is (below).
2. Whether TAVI should tilt the sample for every scan point, or set the scattering plane once like a real TAS.
3. How far "Refine Lattice" should go.

I'll decide small details myself and record them. One example: each recorded peak remembers the scattering direction it was measured with, so old saved peaks aren't misread.

**Out of scope, as proposed:** separating "how the crystal is really mounted" from "your UB". That comes later as its own design discussion.

**Tier:** T2 still fits.

## Question 1: what is χ?

**Why now.** Every other fix builds on this: the angle solver, the fit, the readouts, ISAR's copy. Choosing wrong means redoing all of them.

**The situation in plain words.** A triple-axis sample sits on a turntable (A3, called ω in TAVI) that spins about the vertical. To reach a reflection that points slightly up or down, the crystal must be tilted too. TAVI's χ describes that tilt in three different ways:
- **The simulation.** The McStas model tilts about an axis fixed to the incoming beam, and the tilt sits *underneath* the turntable, so turning A3 swings the already-tilted crystal around.
- **The angle solver.** It treats χ as "how far Q points above the horizontal". That tilt follows Q around, and no real goniometer does it.
- **The docs.** They describe χ as a tilt about the horizontal X axis, which is closest to the simulation.

For reflections in the horizontal plane the tilt is zero, which is why everything validated so far (including the live vTAS cross-check) still holds. Any tilted reflection misses.

**Option A: keep the simulation's geometry and fix the solver to match it.**
- **Locks in:** a tilt stage that doesn't ride on the turntable, which is unlike a real instrument.
- **At one month:** peaks land where predicted. The McStas tree is unchanged, so no validated run is touched.
- **At six months:** anyone who knows real instruments finds χ behaving oddly. A pure A3 rocking scan on a tilted crystal traces a cone rather than a flat circle, and teaching material won't carry over to a real beamline.

**Option B: move the tilt on top of the turntable, as on a real TAS, and solve that.**
- **Where the change lands:** one shared helper builds the sample chain for all four instruments (`emit_sample_orientation_arms`), so the reorder happens in one place. Hidden misalignments and the κ alignment correction ride on the turntable with it.
- **At one month:** same correctness as A. χ now means what a beamline scientist expects, and an A3 scan is a clean rotation of the tilted crystal.
- **At six months:** we are building with the real instrument. The UB fit, training and any later work on the true-mount separation all speak the language of real goniometer arcs.
- **Cost:** it's a change to the simulated instrument. It is invisible for untilted work, but any tilted scan run before now gives different results.

I left out making the simulation follow the solver's Q-following tilt, because no goniometer can do that.

**My recommendation: B.** The point of the UB workflow is practising real alignment, and A would teach a geometry that doesn't exist. The chain is built in one shared place, and nothing validated so far uses a tilt.

**Where I'd like you to push:**
- Do PUMA, IN8, IN12 or PANDA in your mind have a specific goniometer, such as two crossed arcs (upper and lower)? If so, one tilt axis is itself a simplification. Is one arc enough for this job, or should the model carry two?
- Is there any tilted-scan result anywhere, in ISAR tests or old output, that you'd hate to see change?

*She caps her pen and taps it once against her lower lip, waiting.*

## User

B

## Assistant

*She writes a single decisive "B" in the margin and underlines it twice.*

**Decision: the tilt rides on the turntable** (2026-09-30)

- **Question, as put:** "what χ physically is". Option A kept the simulation's beam-fixed tilt underneath the turntable and fixed the solver to match. Option B moves the tilt on top of the turntable, as on a real TAS, and solves that.
- **On the table:** A (McStas tree unchanged, but a geometry no real instrument has); B (matches real beamlines, and changes the shared sample chain for all four instruments)
- **Ruling:** "B"
- **Ruled by:** operator
- **Why:** the UB workflow exists to practise real alignment, and nothing validated so far uses a tilt.
- **Constrains:** the sample chain in `emit_sample_orientation_arms`, the angle solver, the fit, and ISAR's copy of the geometry.

**Good news.** TAVI already has a solver for exactly this geometry, `solve_sample_angles` (turntable outermost, tilt on top). It's just not the one the controller calls.

**A finding the ruling exposes.** With a **single** tilt arc, a reflection that lies almost along the arc's own axis can only be levelled by a huge swing. In TAVI's setup that axis is a*, so the whole (h,0,0) row lies along it. A 2° misorientation of (2,0,0) can call for a tilt anywhere up to about 90°. The crystal flips over to fix a hair's-width error, every other reflection leaves the plane, and a scan from (h,0,0) towards (h,k,0) can make the tilt jump between points. Real instruments avoid this with **two crossed arcs** (the upper and lower goniometer). That turns my earlier pushback question into the next real decision.

## Question 2: how does the sample reach a reflection?

**Why now.** It decides how many tilt axes the simulation has, what happens when you ask for a Q that points above or below the horizontal, and whether API clients see a behaviour change.

**The situation in plain words.** Today TAVI re-solves the tilt at every scan point, so any Q is reachable, including ones pointing up or down (a non-zero vertical component `qz`). A real TAS doesn't work that way. You align the crystal once: the goniometer arcs bring your chosen scattering plane (two reciprocal-lattice directions, for example (1,0,0) and (0,1,0)) level. From then on only the turntable and the arms move. A Q outside that plane is simply out of reach.

**Option A: one arc, re-solved every point (today's behaviour, now in the correct geometry).**
- **At one month:** smallest change, and every Q stays reachable.
- **At six months:** the (h,0,0) problem above. Big, jumpy tilts near a*, which look broken to anyone watching the angles and teach nothing real.

**Option B: two crossed arcs, set once from the UB so your chosen plane is horizontal. Per point, only A3, the scattering angles and the energies move. Q out of the plane is refused as infeasible, with a clear reason.**
- **Locks in:** "orient to a plane" becomes an explicit step. The UB dock gains an action that picks the two in-plane vectors and sets the arcs. The alignment corrections (κ, ψ) and the hidden misalignments become offsets on real axes.
- **At one month:** the workflow matches a beamline. Find two peaks, compute UB, the plane levels, then scan.
- **At six months:** we build on the real instrument model.
- **Cost:** Q with a vertical component, which is accepted today, is refused everywhere, including the API. ISAR's closed loop and TAS_MCP would see a refusal where they now get a solution. The job also grows: it stays T2, but it becomes the bigger half of the work.

**Option C: two crossed arcs, re-solved every point with the smallest total tilt.**
- **At one month:** no refusals, small sane angles, and API behaviour unchanged.
- **At six months:** stable, but arcs that move at every point are still not how anyone measures. The UB never gets the "set the plane" role it has on a real instrument.

**My recommendation: B.** You asked for the workflow to be intuitive to a user, and the intuition users bring is the beamline's: align, fix the plane, measure in it. C is the safe fallback if refusing out-of-plane Q would break something you rely on.

**Where I'd like you to push:**
- Does anything you use (ISAR's loop, your own API scripts) deliberately ask for Q with a vertical component?
- Is "out of the plane is refused" acceptable to you, or should the arcs make small out-of-plane corrections?

**Still open, in order after this:**
- **ISAR follow-up.** ISAR keeps its own copy of `tas_geometry.py` and `ub_matrix.py`. Because it's a second repository, I'll propose updating it as a separate follow-up job rather than growing this one.
- **Refine Lattice.** Should it become a real per-crystal-system least-squares fit, or just be honestly relabelled as a single scale factor?

*She slides the pad across the desk toward you, pen resting on the "B".*

## User

IXS instruments generally have much larger chi tilt angles available; aligning to "a plane" for a TAS is a convention of how we run instruments and experiments and choose to align samples, but isn't a real restriction of a virtual instrument. We can "set a plane" but this is really working with the limits of the tilt of the instrument.

## Assistant

*She pauses mid-note, then strikes a neat line through half the page. A small, conceded smile.*

Fair point. I was treating a habit of how we run experiments as if it were a law of the instrument.

**What I heard:**
- **Settled:** the virtual instrument has no plane restriction. What limits it is how far the tilt stage can travel, and that differs by instrument (IXS, inelastic X-ray scattering, instruments go much further than a typical TAS).
- **Settled:** setting a plane still exists, but as a working convention you may choose, inside those limits.
- **Open:** what the tilt stage looks like, and where its limits come from.

*Withdrawn: "how does the sample reach a reflection" (plane-locked versus re-solved each point), because the real constraint is the tilt range, not a plane.*

**Facts checked:**
- Each instrument's descriptor already declares limits for A1, A2 and A4 through an existing mechanism (`AxisLimits`), but none for any tilt.
- IN12's model record documents a ±20° sample goniometer. The other three instruments don't document one.

## Question 2 (reframed): what is the tilt stage, and how is it limited?

**Why now.** Once limits are what decide "reachable or not", the stage's shape matters a lot. The same small misalignment can be a 2° correction on one design and a 90° swing on another.

**The situation in plain words.** Recall the single-arc problem: a reflection lying almost along the arc's own axis (in TAVI, the whole (h,0,0) row) can only be levelled by a huge swing. Put a ±20° limit on that arc and a crystal that is only 2° off would have (2,0,0) refused as out of reach. To a user that looks like a bug. Two crossed arcs can level any small misalignment with small angles, whichever way the error points.

**Option A: one arc, with a declared range per instrument.**
- **At one month:** smallest change.
- **At six months:** with realistic limits, whole rows of reflections become unreachable for trivial misalignments. With huge limits, the stage swings wildly instead. Either way the (h,0,0) behaviour looks wrong.

**Option B: two crossed arcs (lower and upper, as on real TAS goniometers), each with a declared range per instrument.**
- **How a point is solved:** TAVI picks the smallest total tilt that reaches the requested Q within those limits, and refuses with a clear reason only when no setting fits.
- **"Hold plane":** an optional mode freezes the arcs where the UB levels your chosen plane, so only the turntable and arms move.
- **Locks in:** two tilt readouts instead of one χ, and the κ correction and hidden χ misalignment become offsets on real arcs.
- **At one month:** small misalignments are always small corrections, and IXS-style wide ranges are just larger limits.
- **At six months:** we build on a stage that matches real hardware, and the training exercise has real axes to correct.

**Option C: one arc on top of a full Eulerian cradle (an unlimited, four-circle-style stage).** Maximum reach, but the least like any TAS. I mention it only because you raised the virtual-versus-real point. I don't recommend it.

**My recommendation: B.** It's the only option where a 2° error stays a 2° fix under any realistic limit. The existing limits mechanism takes the ranges, so nothing new is invented for that.

**Where I'd like you to push:** the default range for instruments that don't document one. My suggestion: use the ±20° IN12 documents wherever a range is known, and something generous but finite (say ±45°) elsewhere, marked in each instrument's model record as an assumption. Or would you rather have no limit by default and let each instrument opt in?

**Still open, after this:**
- **ISAR follow-up.** Update ISAR's copy of the geometry as a separate job, since it's a second repository.
- **Refine Lattice.** A real per-crystal-system fit, or honestly relabelled as one scale factor?

*She taps the two crossed lines she's sketched in the margin, one arc laid over the other.*

## User

Let me think. C is the *correct* way right, and we just lock of axes then for the real instrument, is that not so?

## Assistant

*She turns her chair a quarter toward you, one heel hooked on the base, and thinks it through out loud with you.*

Almost. The instinct is right, but "locking axes" doesn't quite land on the real instrument.

**What's right:**
- **Orienting a crystal takes three rotations.** Any stage that can do three independent rotations can put the crystal in any orientation. An Eulerian cradle is one such stage: the turntable ω, a tilt χ, and a spin φ about the tilted axis.
- **It's the general case.** Every real stage is a particular choice of three axes plus travel limits. In that sense a virtual instrument should, at its core, allow *any* orientation.

**Where locking goes wrong:**
- **Locking φ doesn't give you a TAS goniometer.** It leaves one tilt arc, which is exactly the (h,0,0) failure: that row sits along the arc's own axis, so it can't be levelled without a huge swing.
- **Keeping φ free and limiting χ to ±20° does match a TAS in reach.** Any small misalignment levels. But the readouts differ: φ swings by up to 180° to aim the tilt while ω compensates, whereas a TAS's two crossed arcs both stay small.
- **So the two give the same orientations, not the same angles.** B isn't C with axes locked. They are two different descriptions of the same set of reachable orientations.

**That points to a cleaner split than any of my three options:**
- **The core is general.** For each scan point, TAVI computes one full orientation of the crystal (turntable × stage × mount) and hands the simulation that single rotation. The simulation no longer bakes in a fixed hierarchy of tilt arms; one sample arm takes a per-point rotation, as the mount already does.
- **Realism lives in each instrument's goniometer description.** That means which axes it has and their limits: two crossed arcs at ±20° for IN12 as documented, a wide-range cradle for an IXS-like instrument later. The description turns the rotation into angles you read and scan, and refuses what the travel can't reach.
- **"Hold plane" works on any stage.** It freezes the stage wherever it levels your chosen plane.

The default description for all four TAS instruments would be two crossed arcs. An Eulerian cradle becomes just another description anyone can add, without touching the simulation or the solver core.

**The question, restated:** do you want this split (a general orientation core, with a per-instrument goniometer description and limits on top, defaulting to two crossed arcs), rather than hard-wiring any one stage into the McStas tree?

**Where I'd like you to push:** the cost. It's one more concept than "just add a second arc": a small goniometer-model interface in the instrument descriptor. The one-month win is that the simulation tree never changes again when a stage changes. The risk is that I'm building a slot for Eulerian cradles nobody asks for. If you'd rather keep this job to two hard-wired arcs and leave the generalisation for when it's needed, say so. That's the lazier path and a perfectly defensible one.

*She leans back, pen resting against her collarbone, and waits for your call.*

## User

An eulerian cradle would be useful for e.g. a simple laue machine doing diffraction or something, letting us carry the same work forward. But yes, the general idea is we build the full setup, then for a TAS we go to two arcs, and for a "real" experiment we lock a plane and stay in that without changing tilt angles ever again during the experiment.

## Assistant

*She writes it out in full, then sets the pen down deliberately, the way she does when a meeting has just changed size.*

**Decision: a general orientation core, with per-instrument goniometers** (2026-09-30)

- **Question, as put:** "do you want this split (a general orientation core, with a per-instrument goniometer description and limits on top, defaulting to two crossed arcs), rather than hard-wiring any one stage into the McStas tree?"
- **On the table:** hard-wire two arcs into the McStas tree (smallest change; any new stage means a new tree); general core plus goniometer descriptions (one more concept; stages become data)
- **Ruling:** "yes, the general idea is we build the full setup, then for a TAS we go to two arcs, and for a "real" experiment we lock a plane and stay in that without changing tilt angles ever again during the experiment."
- **Ruled by:** operator
- **Why:** it carries the same work forward to other instrument types. You named a simple Laue diffraction machine with an Eulerian cradle as a real future use.
- **Constrains:**
  - The simulation takes one general per-point orientation.
  - Each instrument declares its goniometer and limits; the four TAS instruments get two crossed arcs.
  - "Lock plane" is a mode in which the tilts stay fixed for the whole experiment.
  - The Eulerian cradle is a named future stage, not speculative.

## I have to stop here: this has outgrown T2

**What we set out to do:** fix a sign, a tilt convention and a crash, and add residuals. A few commits.

**What we've now designed:**
- **Orientation core:** a new general orientation core, plus a goniometer description in the instrument contract that every plugin implements.
- **Simulation change:** the McStas sample chain changes for all four instruments.
- **Solver:** a new solver working within stage limits.
- **Lock plane:** a mode that ties the UB to the stage angles.
- **Training:** the exercise re-expressed on real arcs.
- **ISAR:** its geometry copy has to follow, and that's a second repository.

**Tied in:** the "true mount versus your UB" separation I'd deferred. Lock plane *uses* your UB to set the arcs, while the simulation needs the true mount, so the two are no longer separable.

By the floor's own sizing, that's T3: architecture, with a second repository in view. It's really a small programme.

**What I'd propose:**
1. **Now, as a small separate job (T1):**
   - **The sign fix.** The fit must use the scattering direction whatever geometry we end up with, so this fix survives the redesign.
   - **The restore crash.**

   IN8, IN12 and PANDA users hit the sign bug today, and neither fix has a design question.
2. **Close this T2 and reopen as a T3 programme** covering the orientation core, the goniometer descriptions, lock plane, true mount versus model, the UB legibility work and the ISAR follow-up. The design talk continues from exactly where we are, with both decisions above carried over. It lands as slices, each with its own short brief.

**Your call, since the tier is yours to name:** agree to (1) plus (2), keep everything in one bigger job, or trim the scope back so it fits T2.

*She glances at the clock on the wall (past midnight, by the look of her), then back to you, eyebrow raised just slightly.*

## User

One job, /t3

## User

I have to step away soon so I can't run two sequential jobs.

## Assistant

The operator has to leave soon, so this stays one T3 job. I'll move the T2 over and put the last foundational question now.

*She has the new folder labelled before you've finished the sentence, and speaks quickly now that there's a clock on it.*

It's one job:
- **Moved over:** the T2 job `j1e557308ac1c` is cancelled with nothing landed, and T3 job `jc834f74810e2` is open and bound to this session.
- **Carried forward:** both decisions (the tilt rides on the turntable; a general core with per-instrument goniometers).
- **Timing:** only one foundational question is left. If you answer it before you go, I can write the design, present it, and you `/approve` it. Planning and building then run while you're away. Nothing builds without that approval.

**Heavy-depth steps skipped:**
- **Opening brainstorm** (the five-model panel on the problem): skipped, because the foundation was already argued and ruled before the tier changed.
- **Partner's blind answer** on this question: skipped for your time. I'll run the partner on the lens list afterwards instead.

## Last question: what is the "true" crystal orientation?

**Why now.** Lock plane uses *your* UB to set the arcs, while the simulation needs the crystal's *real* orientation. Today both are one matrix, so Calculate UB physically re-mounts the simulated crystal. A wrong UB never looks wrong, and training shows you the answer.

**The fix:** keep two things:
- **the true mount**, which only the simulation reads;
- **your UB**, which only turns HKL into angles.

Get the UB wrong and peaks go missing, as on a real beamline. What's open is what the true mount is in an ordinary session.

**Option A: the true mount is the sample as you described it, and your UB starts equal to it.**
- A normal session is perfectly aligned from the start, so anyone who just wants to simulate a phonon never has to align anything.
- Only a training exercise or a loaded misalignment moves the truth away from the description, and it stays hidden.

**Option B: every session gets a small random misorientation, so you always align first.**
- Most realistic.
- It puts an alignment hurdle in front of every simulation, including the API and ISAR's closed loop, which would first have to learn to align.

**My recommendation: A.** Alignment practice becomes something you opt into, and nothing that runs today has to learn a new step.

**One default I've taken myself (reversible; say if you disagree):** "Refine Lattice" becomes a real least-squares fit that respects the crystal system (cubic refines *a*; tetragonal *a* and *c*; and so on), instead of one overall scale factor.

A one-word answer is enough.

*She holds the pen poised over the last blank line, glancing at you over the rim of her cup.*

## User

A, no mandatory misalignment. Mark this down as a stupid question too, if you're offering something like this we need some tuning.

## Assistant

The runtime blocks repo writes during the design stage, so I'm holding that memory line for closeout. Next I'm writing the design and lenses outside the repo.

Compacting the design transcript (a required step before presenting) through the Codex launcher.

*She winces, just perceptibly, and writes it down in ink rather than pencil.*

**Decision: the true mount defaults to the sample as described** (2026-09-30)

- **Question, as put:** what is the true mount in an ordinary session: the sample as described, with the UB starting equal to it (A), or a random misorientation every session (B)?
- **On the table:** A (aligned by default; misalignment is opt-in and hidden); B (every session needs an alignment first)
- **Ruling:** "A, no mandatory misalignment."
- **Ruled by:** operator
- **Why:** alignment practice is opt-in; nothing that runs today gains a step.
- **Constrains:** the simulation reads a true mount separate from the UB. Training and loaded misalignments move the true mount, hidden.

You're right about the question: B forced a step onto every session and was never a real contender. I'll record your correction as a memory line in `AGENTS.md`: "never table an option that forces a new step on every session". The job's runtime blocks repo writes until the design is approved, so the line goes in at closeout.

**Where it stands:**
- **Registered:** the design and its six review lenses, under job `jc834f74810e2`.
- **Presenting:** it can't be presented until the conversation transcript is compacted. That step is running now, takes a few minutes, and I'll present the moment it lands.
- **Your part:** read the design below, then type **`/approve`** once I say it's presented. If you have to leave first, approve when you're back; nothing builds before then.
- **Seats skipped at heavy depth:** the opening brainstorm and the partner's blind drafts of the questions and lenses. Both were skipped for your time.

## The design, as registered

**What I see now.** I try to align a crystal the way I would on a beamline: find a couple of Bragg peaks, pin their angles, compute a UB matrix, and the results are nonsense.
- On IN8, IN12 and PANDA the orientation comes out turned half a circle.
- Anything that needs the sample tilted even a little doesn't diffract where TAVI says it will, so peaks I'm told to find aren't there.
- When the UB is wrong I can't tell, because computing it quietly re-mounts the simulated crystal to agree with me.
- The training exercise shows the hidden answer in the UB display and marks a correct fit as wrong.
- Nothing tells me whether my peaks were consistent, and "Refine Lattice" is a single scale factor wearing a grander name.

**What I hoped to see.** A virtual instrument that orients a crystal the way real hardware does, and is honest about it.
- **The true orientation belongs to the instrument, not to me.** By default it is the sample exactly as I described it, perfectly aligned, and my UB starts equal to it, so simulating a phonon never needs an alignment step.
- **A misalignment is hidden, and my UB is only my belief.** A training exercise or a loaded misalignment moves the truth without showing me. Get the UB wrong and the peaks go missing, as they would on the beamline.
- **The stage can reach any orientation the physics allows.** Each instrument describes the stage it really has and how far it can travel. A TAS has two crossed tilt arcs riding on the turntable; a diffraction machine can one day carry an Eulerian cradle and reuse the same work.
- **Out of reach means outside that stage's travel.** The reason is stated plainly, never an arbitrary rule.
- **For a real experiment, I lock a scattering plane from my UB.** The tilts then stay put, and only the turntable and the arms move.
- **Aligning is legible.** After computing a UB, I see how far each peak sits from its prediction, and whether the angle between my peaks matches the angle between their indices, so a mis-indexed peak shows itself.
- **Labels and refinement are honest.** The labels say what the numbers are, and lattice refinement respects the crystal system.
- **One orientation model everywhere.** It serves every instrument, both scattering directions, the API and ISAR's copy of the geometry, so what TAVI predicts, what the simulation does and what ISAR plans all agree.

## The six review lenses (the reviewers' questions, bound with the design)

1. **Round trip:** on every instrument and both scattering directions, do the solved angles put the reflection exactly on the scattering vector in the emitted McStas chain? Does a UB fitted from those angles recover the one used?
2. **Truth versus belief:** is there any path (the API, restoring saved state, loading training, Calculate UB) where your UB writes the true mount, or where the truth shows during training?
3. **Stage limits:** does every out-of-travel refusal come from the same feasibility path the real scan uses, naming the axis and its limit? Does lock plane never move a tilt?
4. **Design fit:** is the goniometer description pure data, so an Eulerian cradle is a new description and not new code? Are today's in-plane angles, including the IN8 cross-check against vTAS, reproduced exactly?
5. **Consumers:** are ISAR's geometry copy, TAS_MCP, the API schema and old saved files all carried over, with old peaks still loading?
6. **GUI:** in the real widgets rendered offscreen, can an operator, mouse-only and cold, align, read the residuals, lock a plane and run a training exercise without ever seeing the answer?

*She squares the pages against the desk and sets them in front of you, pen laid neatly across the top.*

*The phone buzzes once; she silences it without looking and slides a single sheet across the desk.*

The design is presented and waiting for you to approve it.

- **Job:** `jc834f74810e2`, T3 (TAVI crystal orientation). It's at the design stage, and nothing is built or changed in the repo.
- **What's presented:** the design and six review lenses, exactly as in my last message, unchanged. The conversation transcript has been compacted and recorded, so planning can start from it.
- **Your one action:** type **`/approve`**. At a terminal, `acs-job approve-by-hand --job jc834f74810e2` does the same.

**After you approve, while you're away:** planning starts from the design, the compacted transcript and the full transcript. That includes my audit numbers:
- the 180° fit error on IN8, IN12 and PANDA;
- the 1.5–3° tilt misses;
- the restore crash.

Building happens in its own worktree beside the repo (`TAVI-jobs\<slug>`); I'll name the exact path in the next report. It lands through a pull request once the tests and lenses pass.

**Held for closeout:** your correction as a memory line in `AGENTS.md`. The runtime blocks repo writes until the design is approved.

**Resolved:** the overlong memory line the startup check flagged at `AGENTS.md:321` has since been shortened, so `/memory-harvest` isn't needed.

*She caps the pen, leaves it balanced on the sheet where your signature goes, and waits by the door with her coat over one arm.*
