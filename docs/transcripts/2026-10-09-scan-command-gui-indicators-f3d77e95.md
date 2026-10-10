# Scan command GUI indicators

**Date:** 2026-10-09  
**Session:** f3d77e95-96c0-4a1a-be24-42f101800482

*Cleaned transcript: tool calls, tool results, thinking and harness notices removed. Nothing else edited.*

## User

Okay, I've got a GUI request that we can put in. So what users are running into a lot is they're not quite understanding that when they have a scan command over command, what exactly is being overwritten and how that's working out, so if they have... So let's say they have the scan command of H over some values here. They're not quite understanding that to them you look at the HKL; HK and L all look the same, right? So it's not clear, can I scan over two different things? How does that work out? So let's do two things. First, I want to be very robust in ensuring that the scan commands are mutually exclusive, right? So we can't scan over H and then some angle that is going to cause problems with us. Right, so it's clear to a user that this scan command and scan command two don't work together because of XYZ or whatever, right? Just some way to make that nice and clear, and we should robustly control that so we don't accidentally have any instance where we scan over two linked parameters.

Okay, and the second part is then when you have that scan command, since we know all the variables that are linked to it, what we should do is clearly mark that if you are scanning over this command, first which one it is directly controlling, right? So if I have h in there, the h box and the scattering dock should have an outline over it or something, be grayed out. You know, they can mess with it. You know, we don't prevent that. But if we have a valid scan command there, and they're validated in real time, it should immediately tell us this is the one that you're scanning over, right? So what you put in there anymore doesn't matter. It doesn't have to say that in words, right? It just has to have a GUI indicator. And then, secondarily, it marks out all the other elements that are going to be scanned over as well that you can no longer do. Because now we have that full robust tree, right? So if we scan over H, then it's doing other elements, you know, sample 2 theta and things like this should also be marked out slightly different. So we know this one's the primary and these ones all feed into it here. That way we can clearly do that. And we have to be careful here because some scan commands might have two linked somehow, right? So you could have h and k and they're both affecting 2 theta and that's fine. We should clearly say you know these two are the two primaries and make them one scan command, one scan command two so one can be you know we can do some coloring or something a thick dashed border around the primary one and then that matches to the scan commands down there and then some sort of you know graying out thin darker border for any of the following parameters.

Okay, so let me reiterate: my big goal is to make it more clear to a user what's going to be scanned over, what feeds into that, and especially for a new user, making it a little more clear that this value is going to be overwritten by the scan then. So what they put in there doesn't matter. And we may need to think carefully then about how relative works out, because that does depend on the current value then.

/dialogue 
/ui-professional

## Assistant

*Pulls the scan-command folder off the shelf and nudges the chair in with a heel.*

Quick status while I gather the facts:

- **Code read (running):** a reader agent is checking how scan commands are parsed today. It's looking at what each scan variable overwrites at every point, any existing checks between command 1 and command 2, live validation, relative mode, and which widget holds each variable.
- **Panel (done):** a five-model brainstorm is back. It already agrees on one thing worth keeping: the conflict rule and the field marking should come from a single dependency model, so the two can't drift apart.

When the code read lands, I'll come back with a summary of what exists today and the first question. I won't build anything until we've settled the design.

*Taps the pen once against the folder.* Back shortly.

*Swivels the chair round, crosses her legs, and lays the notes on your side of the desk.*

You're right that this is confusing, and it's worse than confusing. TAVI can run some two-command scans that are silently wrong today.

## Where things stand

**The idea:** two parts. (1) Refuse any pair of scan commands that drive linked quantities, and say why in plain words. (2) While a valid command sits in the box, mark the input fields in the docks:
- the field the command drives directly gets a strong mark, colour-matched to command 1 or command 2;
- every field the scan will overwrite at each point gets a quieter "derived" mark.

Fields stay editable either way.

**What exists today** (I checked this in the code):
- **How a scan runs.** Each point has four main slots. The scan picks one "mode" from the variables named, in this priority order: any of H/K/L → HKL mode; else qx/qy/qz/deltaE → Q mode; else A1–A4/sgl/sgu → angle mode. In HKL mode the four slots mean H, K, L, deltaE. In angle mode the *same* slots mean A1, A2, A3, A4.
- **The bug.** `H 1 1.2 0.01` with `A4 40 50 1` passes validation. The H puts the scan in HKL mode, and the A4 values land in slot 4, which in HKL mode is **deltaE**. The run silently scans energy transfer from 40 to 50 meV and labels the data as an A4 scan. Pairing H with A1 is just as bad: A1 lands in the H slot and overwrites the H values. Mixing any target coordinate (H/K/L, Q, deltaE) with a motor angle has this problem.
- **Current conflict checks** (`TAVI_PySide6.py:4585`, `gui/docks/unified_simulation_dock.py:17`):
  - Hard refusals only for Q paired with HKL, and for an arc (sgl/sgu) inside a Q/HKL scan.
  - Soft warnings, which you can override, for a handful of hand-listed pairs: A2/2theta, A3/omega/psi, sgl/kappa.
  - The same variable in both commands is also only a soft warning.
  - Nothing catches target paired with angle.
- **There's no map of what each scan variable overwrites.** The physics lives in the per-point solver (`instruments/tas_runtime.py:1048`). The scannable-variable list is defined in three places that can drift apart: the simulation dock, the controller, and the API schema.
- **Two commands make a grid:** every value of command 1 paired with every value of command 2.
- **Relative mode:** start and stop are offsets from the driven field's *current value*. So under relative mode the primary field still matters, as the centre of the scan.
- **No theme module:** colours are hard-coded style sheets on a light background. That has to be settled before we add new marks.
- `DESIGN_GOALS.md` exists, but you haven't written its body yet, so there's nothing to check this against.

**Easy:** once one dependency table exists, both the refusal and the marking are lookups in it.

**Hard:**
- Making that table the single source for the GUI, the API and the run, so the three can't drift.
- What derived means depends on settings. A deltaE scan moves A1/A2 with fixed Kf, but the analyzer with fixed Ki. Plane lock changes what the arcs do.
- The API is used by other programs. ISAR (your sibling analysis repo) submits scans through it, and a new hard refusal will make some of its requests fail with HTTP 400.

**Proposed tier: T2.** It changes the API contract, touches four or five docks, and TAVI is a dependency hub. I'd split it into two slices:
1. the dependency table plus the refusals, which closes the bug;
2. the dock marking.

**Questions, in order:**
1. The conflict rule (below).
2. What states a field can show: driven, derived, held and used, ignored, and how relative mode changes that.
3. The look: I'll mock up two options at the smallest window size.
4. Where the table lives and whether the API publishes it.

## Question 1: what makes two scan commands compatible?

**Why now:** the refusal and the marking both read from the same table, so its structure comes first.

**Option A — groups, hard rule.** Every scan variable belongs to one group:
- **target:** H, K, L, qx, qy, qz, deltaE
- **motors:** A1–A4, 2theta, sgl, sgu
- **sample offsets:** psi, kappa, omega
- **independent:** monochromator/analyzer curvature (rhm, rvm, rha, rva) and the slits

Two commands are allowed only when:
- both come from the same group with different variables (H×K, H×deltaE, A3×A4), or
- one of them is independent.

Everything else is refused with no override. The message names the field both commands would fight over, e.g. "H sets A4 at every point, so A4 can't be scanned beside it." The existing Q×HKL ban stays inside the target group.

- *One month:* the bug is closed, the messages are clear, and the marking falls straight out of the groups.
- *Six months:* every new scan variable must be assigned a group, and that is the only upkeep.

**Option B — overlap of written fields.** Work out which fields each command writes, and refuse when the two sets overlap. This is more general, but H×K both write A3 and A4, so it needs a "solved together" exception straight away. It ends up as Option A with extra steps, and the extra steps are where drift would creep back in.

**Option C — keep the soft warnings and add the missing pairs.** This is the smallest change. But it's still a hand-written list, and an override still lets a wrong scan through, which isn't the robust control you asked for.

**My recommendation: A**, with every refusal hard, including the same variable twice. For the API, its `force` flag will no longer get these pairs through, and I'll note that in the API docs for ISAR's sake.

**Where I'd like your push:** the sample offsets (psi, kappa, omega) beside a target scan. The code currently calls H×psi "a supported combination" with an overridable warning. Physically it rocks the crystal mount while still asking for the same H. Each point stays honest, because the angles are re-solved for the new mount. Is that a scan your users actually want (allow it, perhaps with a note), or is it a trap they fall into (refuse it)? Everything else in A I'm fairly sure of. This one is your instrument judgement.

*Slides the pen across the desk and leans back, heels crossed at the ankle.* Your call on the rule, and on psi.

## User

And basically we're saying that we don't try and think ahead of time which things don't work together. We just take any two scan commands and this works then for any parameter we put in, and then we just say if those two impact each other they conflict, so that's like the first test, I guess. A, I don't think, is right. I mean, you could try H and checking curvature or slits or something, right? That's completely valid. There's nothing wrong with it. I don't think it'll come up often, but it's definitely something where we don't want to have a user come in and say, "I want to do these two scans. They should be allowed. Let's do them." I don't know. Then B was my initial impression, but you're right that we need this all together exception. Is there a way to do this, right? To check it in a very general sense. But I also feel like whatever we build now is basically going to be, as well, what's feeding into that GUI indicator for all the other elements that are going to be changing as well anyway, right? I will in general agree that the refusals are going to be hard here, and even the force flag is not going to make it work. We shouldn't be able to drive instruments into impossible configurations, not just physically impossible, but theoretically impossible.

Let me open up a high tier here:
/t3

## Assistant

*Flips the calendar page over to a fresh sheet and writes T3 across the top.*

I've opened the T3 job, **j92f2a0718dc1**, and bound this session to it. It's at heavy design depth, so before I put the next question to you, the job's second-opinion model (the partner, a separate Codex session) answers it blind. It's working on the general compatibility rule now, without seeing my lean.

**One correction for the record:** Option A did allow H with curvature or a slit. Those were in the "independent" group. Your real objection stands, though: A still meant someone assigning every variable to a group by hand, and you want one general test instead.

**Decision: scan-pair refusals are hard** (2026-10-09)

- **Question, as put:** "with every refusal hard, including the same variable twice"
- **On the table:** hard refusal with no override; soft warning that `force` can clear (today's behaviour for most pairs)
- **Ruling:** "I will in general agree that the refusals are going to be hard here, and even the force flag is not going to make it work."
- **Ruled by:** operator
- **Why:** "We shouldn't be able to drive instruments into impossible configurations, not just physically impossible, but theoretically impossible."
- **Constrains:** the API's `force` flag no longer clears scan-pair conflicts. ISAR (your sibling analysis repo) will get an HTTP 400 for those pairs.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**Also settled in what you said:** one model feeds both the refusal and the dock marking, and it must be general, with no hand-kept list of bad pairs.

**Still open:** what that general test actually is. I have a candidate, but I'll hold it until the partner's blind answer is in, then bring you both.

*Uncaps the pen and waits, one heel slipped half out of its shoe.* Back when the partner reports.

*Sets the partner's printout beside mine, squares the edges, and taps them once on the desk.*

The partner's blind answer is in. We agree on the core, and it caught two things I had wrong. Corrections first.

## Corrections and new facts

- **TAVI's angle names aren't the textbook ones.** In TAVI, A1 is the monochromator 2θ, **A2 is the sample 2θ**, A3 is the sample rotation, and **A4 is the analyzer 2θ** (`gui/docks/unified_simulation_dock.py:58`). So an H scan at fixed energy transfer moves A2, A3, the solved tilt arcs (sgl/sgu) and qx/qy/qz. It also sets A1 and A4 at every point, but they come out at the same value each time. Last turn I said "H recomputes A3 and A4"; that was wrong.
- **Slit scans are offered but can't run.** The four slit variables are in the accepted list and the help dialog. But the code that writes scan values into each point (`TAVI_PySide6.py:8160`) has no entry for them, so a slit scan most likely fails at launch.
- **`omega` doesn't do what its description says.** The help calls it an alias for A3, but the scan actually writes the psi correction (an offset applied to A3). So scanning omega beside psi is the same quantity twice.
- **The root cause of the H×A4 bug is structural.** The code decides the scan mode in one place. It then writes each command's values into a fixed position in the point that ignores the mode. The mode and the write position were never checked against each other. Adding another conflict check on top wouldn't close it; that link has to be fixed.

## Question 2: what does the general test check, and how deep does the model go?

**Why now:** this is the foundation. The refusal, the dock marking and the run all depend on it. The look and the field states come later.

**The test both of us arrived at independently.** Two commands may combine only if all of these hold:
1. **One calculation takes both as independent inputs.** Each kind of point calculation (from HKL, from Q, from motor angles) has a set of inputs it accepts directly, plus inputs every calculation accepts: curvature, slits, and the psi/kappa corrections.
2. **They are different quantities** once aliases are resolved, so A2 with 2theta is refused.
3. **Nothing else owns either one.** For example, the plane lock owns the tilt arcs, and a fixed-curvature setting owns its crystal.

That handles your cases:
- **H with K:** one calculation takes both. Allowed.
- **H with A4:** no calculation takes both. Refused, with a message naming the reason.
- **H with a curvature or a slit:** allowed.
- **Scanning a curvature that is normally autofocused:** the scan already takes priority over autofocus (`instruments/tas_runtime.py:1232`). Allowed.
- **H with psi:** allowed, because psi is a correction applied after the solve.
- **Same variable twice:** refused.

The "derived" marking comes from the same model: whatever the chosen calculation solves at each point. A pair that shares derived fields, like H×K, is not a conflict, so no exception is needed.

**Where we differ is how deep the model goes.**

**Option 1 — a declared table of calculations that the run itself reads.** One Qt-free module lists each calculation:
- its inputs;
- what it solves, depending on settings (fixed Ki or fixed Kf decides whether A1 or A4 moves with deltaE; autofocus adds curvatures; the plane lock removes the arcs).

The GUI check, the API check and the code that builds each point all read this one table. So a pair the table refuses *cannot* be built, which fixes the H×A4 bug at its root. The existing solver keeps its code. A test then runs the real solver over a sample of points and confirms its outputs match the table's "solves" list, so if the marking ever drifts from the physics, a test fails.
- *One month:* the bug is closed, slits are either wired up or withdrawn, and the marking reads straight from the table.
- *Six months:* a new scan variable means one table entry plus its link into the point builder. If someone forgets the entry, the variable is refused outright, never silently misrouted.

**Option 2 — rebuild the solver as named rules (the partner's preference).** Each step of the calculation declares its own inputs and outputs. The run executes the rules, and the fixed-position point layout disappears. Drift becomes impossible by construction, on both the input and the output side.
- The cost: a refactor of the shared runtime (`instruments/tas_runtime.py`), the controller's run path, all four instrument plugins and the API's point validation. ISAR copies some of TAVI's geometry modules and drives its API, so it is in the blast radius too.
- *Six months:* the cleanest base. But months one to three go to a rewrite of code that works today, apart from this bug.

**Rejected by both of us:** probing the solver as a black box (nudge each input, see which outputs move) as the *definition* of linkage. It misses outputs that are set but stay constant, like A4 in an H scan, and it misreads inputs that are solved together, like H and K. It survives in Option 1 only as the drift test.

**The partner's surviving objection, in its own words:** "A separate descriptive graph beside the existing procedural solver would become another drifting list." My answer: under Option 1 the table controls the input side of the run directly, and only the "what gets overwritten" side is descriptive. That side is guarded by a test, not by construction. The partner would say a test samples points and can miss a branch; that's true.

**My recommendation: Option 1.** It gives you the hard guarantee where it matters (a wrong scan can't be built) and leaves working physics code alone. The refactor in Option 2 is a separate decision for a day when the solver needs one anyway.

**Where I'd like your push:** is a drift *test* on the marking side good enough for you? Or does "robustly" mean the marking must come out of the solver itself, the way Option 2 does it? That's the real difference between the options, and it's your call on how much rewrite this feature deserves.

*Leans back and smooths the hem over her knee.* Your ruling on the depth, and whether the test is enough.

## User

Read @C:/Users/AMM/Documents/Github/Science/TAVI/ChatGPT_Angles_Handoff.md (and let's not commit it, it's a temporary handoff). So I think it's at this point to some issues with the angles here. For one, there's some confusion with them in that we use A1 through 4 and this differs from the LLMM. And a big fear of mine is that if users or anybody comes in, they're going to see angles different. And so exactly is what you saw here, that you got the right angles wrong here because I did something different here. So we should think about this a little more carefully, ensure that our angles are set up appropriately. Because this is I think gonna trip us up more in the future. It'll only be worse.

I am more inclined to option two. This is the cleanest space, right? It is, and nobody's relying on it right now, so if we're going to be working on it, now is a better and safer time than later if people are hoping it really works.

## Assistant

*Pins the angle handoff to the corkboard next to the calendar, well away from the out-tray, so it doesn't get committed by accident.*

I've read it. The handoff file stays out of git.

## What you've settled, and what changed

**Decision: the general model is the solver itself** (2026-10-09)

- **Question, as put:** "what does the general test check, and how deep does the model go?"
- **On the table:**
  - **Option 1:** a declared table of calculations that the run reads, plus a drift test on the marking side. The working solver code stays as it is.
  - **Option 2:** rebuild the solver as named rules, each declaring its inputs and outputs. The run executes those rules. The refusal and the field marking come from the solver itself, and the fixed-slot point layout is retired.
- **Ruling:** "I am more inclined to option two. This is the cleanest space, right? It is, and nobody's relying on it right now, so if we're going to be working on it, now is a better and safer time than later"
- **Ruled by:** operator
- **Why:** it is the cleanest base, and refactoring is cheaper before anyone depends on the result.
- **Constrains:** the refactor reaches `instruments/tas_runtime.py`, the controller's run path, the four instrument plugins and the API's point checks. Every scan variable needs a canonical name before the rules can use it.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**One fact to weigh against "nobody's relying on it":** two of your other programs do depend on TAVI, even if no outside users do.
- ISAR keeps adapted copies of four of TAVI's geometry modules and drives its API.
- TAS_MCP imports the `tavi` package.

That doesn't change the ruling. It means the refactor ends with a pass through both of them, which is already TAVI's rule for anything they touch.

**The new topic, angle names:** you're right that it has to come first. The rule-based solver needs a canonical name for every quantity, and naming them twice is how this mess started. I checked the handoff's key findings against the code. TAVI's A1/A2/A4 mean something different from the ILL convention:
- **TAVI A2** is the sample 2θ; **ILL A2** is the monochromator take-off angle.
- **TAVI A4** is the analyzer 2θ; **ILL A4** is the sample 2θ.

The scan variable `omega` is advertised as an alias for A3, but it actually scans the psi correction. With the handoff's example numbers, `omega 35` puts the real turntable at 65° where `A3 35` puts it at 35°. The handoff found the Bragg arithmetic itself correct; the trouble is in the labels and the `omega` contract.

The one thing that makes renaming dangerous: under ILL numbering, `A2` and `A4` would **flip meaning**. An old saved scan command `A2 40 50 1` would run as a monochromator scan without any error. Whatever we decide, an old name must never quietly take on a new meaning.

## Scope has grown; I need your agreement before the next question

What started as a GUI clarity feature is now a programme of slices that build on one another:

1. **Angle convention:** one public naming scheme for scan commands, GUI labels, API fields and saved files. Fixes `omega`. Old names are refused or translated, never silently reinterpreted.
2. **Rule-based solver:** canonical variables, rules that declare their inputs and outputs, and the run executing them. The H×A4 bug dies here by construction, and slit scans either get wired up or are withdrawn.
3. **Hard pair refusal:** computed from the rules, the same in the GUI and the API, with no `force` override.
4. **Dock marking:** primary and derived fields, colour-matched to scan command 1 and 2, with relative mode accounted for.
5. **Consumer sweep:** ISAR and TAS_MCP.

T3 still fits, as one design you approve once, with each slice landing on its own.

**Question: should I continue the design discussion at this wider scope?** Alongside it, I recommend a **stopgap today**: a small separate fix that hard-refuses any pair mixing a target coordinate (H, K, L, Q, deltaE) with a motor angle. It's about ten lines. It closes the silent wrong-scan bug now, and slice 3 replaces it later.

The second-opinion model (the partner) is already answering the angle-naming question blind. Once it's back and I have your answer on scope, I'll put the naming question to you as an open discussion, not a multiple choice, because it's foundational.

*Turns the coffee cup so the handle faces you.* Wider scope yes or no, and the stopgap yes or no.

## User

There's no issue here, right? It's more that I haven't had any pair mixing issues in months, right? And users haven't had these issues. This isn't something; it's more me just kind of tuning things up after some recent tutorials with students, right? And they didn't have any issues with it. So there's no rush here. We don't need to get a stopgap in.

## Assistant

*Lets the pen drop back into the cup.* Then there's no fire to put out.

**Yes, you're right.** It's a latent defect, not a live one. It only fires if someone pairs a target coordinate with a motor angle (H with A4, deltaE with A1, and so on). None of your users or students have typed that, and nothing in day-to-day use goes near it. It's still worth closing, but the programme can do it properly in slice 3, so no stopgap.

**Decision: no stopgap for the pair bug** (2026-10-09)

- **Question, as put:** whether to land a separate ten-line hard refusal of target×motor pairs now, ahead of the programme.
- **On the table:** stopgap now (closes the latent bug immediately, then gets replaced in slice 3); no stopgap (the bug stays latent until the rule-based refusal lands).
- **Ruling:** "So there's no rush here. We don't need to get a stopgap in."
- **Ruled by:** operator
- **Why:** nobody has hit it in months, including recent student tutorials. This programme is tuning, not a fix under pressure.
- **Constrains:** the H×A4 class of bug stays open until slice 3 lands.

**Still open:** whether to continue the design at the wider scope. That's five slices, in this order:
1. **Angle naming:** one public naming scheme.
2. **Rule-based solver:** the solver rebuilt as named rules that declare their inputs and outputs.
3. **Hard pair refusal:** computed from those rules.
4. **Dock marking:** primary and derived fields marked in the docks.
5. **Consumer sweep:** ISAR and TAS_MCP.

All of it stays one T3 design, with each slice landing on its own. I'd rather have your yes than read it into "no rush". The partner's blind answer on angle naming is still running. Once it's back, the naming question comes to you as an open discussion.

*Uncrosses and recrosses her legs, the other way this time.* Is the wider scope yes or no?

## User

Yes, wider scope.

## Assistant

*Adds a line to the folder tab: five slices, one design.*

**Decision: wider scope** (2026-10-09)

- **Question, as put:** "should I continue the design discussion at this wider scope?"
- **On the table:**
  - **Wider:** one T3 design covering five slices: angle naming, the rule-based solver, the hard pair refusal, the dock marking, and the sweep of ISAR and TAS_MCP.
  - **Narrow:** the GUI marking and pair refusal only, on top of today's solver.
- **Ruling:** "Yes, wider scope."
- **Ruled by:** operator
- **Why:** the angle names and the solver structure come before the feature you asked for, and both are cheaper to change now, before anyone depends on them.
- **Constrains:** the next question is angle naming. Everything else in the design builds on the names it settles.

The partner's blind answer on angle naming is still running. When it lands, I'll bring you the naming discussion with both views side by side.

*Reaches for the ringing phone, holds up one finger: don't go far.*

*Hangs up the phone, kicks off one heel under the desk, and turns your way properly.*

The partner is back. This one is foundational, so I'll lay it out as a discussion rather than a multiple choice.

## Angle naming: where the partner and I agree

We reached most of this independently:

1. **One public numbered convention: ILL/MAD A1–A6.** That's the vocabulary IN8 and IN12 users bring, and PSI's control software (SICS) uses it too.
   - A1 = mono θ, A2 = mono 2θ
   - A3 = sample rotation, A4 = sample 2θ
   - A5 = analyzer θ, A6 = analyzer 2θ

   It's the same for every instrument, with no per-instrument switch.
2. **The physical name always shows beside the number,** e.g. "A4 — Sample 2θ (°)". A bare number is exactly what tripped me up last round.
3. **Internally the solver uses physical names, not numbers,** e.g. `sample_two_theta`. The numbers are a display and command vocabulary on top. That keeps another numbering collision from ever reaching the solver.
4. **A1 and A5 (the crystal θ angles) are derived readouts only.** TAVI's models lock each crystal to half its take-off angle, and that's physically right for a nominal instrument. A scan of A1 is refused, with a message pointing to A2. Rocking a crystal independently would be a new physics feature, not part of this.
5. **`omega` means the sample rotation, everywhere, and `psi` means only the correction.** That fixes the case where `omega 35` puts the turntable at 65°.
6. **The arithmetic doesn't change.** The θ/2θ factors, signs and zero points are already right, and the existing sign tests stay as evidence. Signs and zeros get their own documented convention, separate from the names.
7. **An old name never silently takes on a new meaning.** Old `A2` was sample 2θ; new `A2` is mono 2θ. Anything stored under the old meaning gets converted, never reread.

## Where we differ: how heavy the migration is

The partner wants a formal contract boundary. The API publishes a convention version in `/schema`, a machine request without the new version is rejected, saved files get a schema bump with a backup of the original, and historical scan folders are read through a legacy interpreter.

My view, given your scope rule (single user, hobby and research, manual recovery is fine):
- **Saved parameters:** convert `config/parameters.json` once, keeping a backup copy.
- **API:** no version handshake. ISAR is its only machine client, and it gets updated in the consumer sweep (slice 5).
- **Old scan folders:** stay as they are, with one line in the docs saying output before date X uses the old numbering.

That's a fraction of the code. What it gives up: an old ISAR build, or a stale script pointed at the new TAVI, would quietly send A2 meaning sample 2θ and get mono 2θ. The partner's version catches that. Mine relies on you updating ISAR in the same programme.

## Where I'm least sure, and need your knowledge

TAVI's home instrument is **PUMA, at the MLZ in Garching**, and so is PANDA. MLZ instruments run on NICOS, and the partner found published PUMA notation where **`psi` is the sample rotation and `phi` is the sample 2θ**. If your students learned on MLZ instruments, then "psi" already means something different to them than TAVI's psi (a correction to the turntable). That's the same kind of trap as A2/A4, just with Greek letters.

So, the questions I'd like you to talk through rather than pick from:

- **Which conventions do your students and colleagues actually walk in with?** ILL A-numbers, NICOS names (`mth`/`mtt`/`psi`/`phi`/`ath`/`att`), or a mix? If NICOS is home turf, I'd consider accepting the NICOS names as aliases too. But that collides with `psi`, and the correction would need a new name (`a3_offset`, say).
- **Is my lighter migration enough, or do you want the partner's guard?** That's whether a stale client gets refused or misread.

*Taps the PUMA line on the printout with a fingernail.* Tell me about your students.

## User

4. If we're doing this, we should do it right, and it might be the case that in the future someone wants to test aligning a monochromator; so we allow the angles to be used, although we don't need to open them up right now.

TAVI is really beyond a single-user hobby project. We should mark that by the way in the agents file. Even though most of our projects are like that, this is one where we do need to be more professional about it. This is something that could be deployed at different facilities and people are going to rely on, right? It's not enterprise software, but it is important that we be formal about it and that we basically don't leave people who depend on it for their work, pulling the rug out from underneath them.

I am having ChatGPT come up with a good reference for angles across facilities, that we can try to match broadly.

## Assistant

*Straightens in the chair and does up the cuff she'd left unbuttoned. If TAVI is going out to facilities, the desk can look the part too.*

That changes the yardstick, and I'm glad you said it now.

## What you settled, and what changed

**Facilities, not a hobby.** I tried to add a short *Audience and stability* section to `AGENTS.md`. It says that in TAVI, public contracts change formally: scan names, API, saved files, outputs, and the modules ISAR and TAS_MCP consume. That means a documented migration, a clear refusal instead of a silent reinterpretation, and nobody's saved work stranded. The job's write guard refused the edit, because no repo writes are allowed while the design is still being discussed. So the section is now part of the design and lands with the first slice. Nothing is lost.

**Crystal θ angles.** The clerk (the checker that matches each recorded ruling to your exact words) found my summary a little stretched, so this stays open until you confirm my reading:

- **Your words:** "we allow the angles to be used, although we don't need to open them up right now."
- **My reading:** A1 and A5 (the monochromator and analyzer crystal θ) become real quantities in the new solver. By default each is computed as half its take-off angle. The structure leaves room for a future rule that rocks a crystal on its own, for alignment practice, and nobody gets that ability yet. Until then, a scan of A1 is refused with "independent crystal rocking is not modelled yet", rather than "this isn't a thing".

**Is that what you meant?**

**Migration weight.** "Don't pull the rug out" reads to me as the partner's formal guard, not my lighter version:
- the API publishes a naming-convention version, and a request built for the old names is refused with a migration message;
- saved parameters are converted, with the original kept;
- old scan folders stay readable under their old meaning.

I'm recording that as your lean until you say it outright. **Formal migration, yes?**

**The cross-facility reference from ChatGPT.** Good idea. It also answers my question about which conventions your students walk in with, including whether NICOS names like `psi` for the sample rotation collide with TAVI's `psi`. The final names wait for it. Everything we've agreed holds either way: one public numbered convention, physical names inside the solver, `omega` meaning one thing, and old meanings converted or refused, never reread.

## While we wait

The partner is answering the next question blind: which states a dock field can show. The candidates:
- the field being scanned (primary), with relative mode as a variant;
- derived and actually changing;
- derived but constant;
- held at the value you typed;
- ignored by this kind of scan;
- owned by a lock or a policy.

The question is which of those deserve a mark at all. That question doesn't depend on the names, so we can take it next. I'll bring it with both views once the partner lands.

*Settles back, one stockinged foot hooked round the chair leg.* Two short answers, please: the crystal-θ reading, and the formal migration.

*Fans three index cards across the blotter, one per kind of mark, and leaves a fourth face down.*

The partner is back on the field states. We agree on almost all of it, so here's the shared proposal and the two points where I need you.

## Question: what each dock field shows while a scan command is live

**The idea behind it:** the marks answer one question per field: *does the scan use what I typed, replace it, or ignore it?* There's deliberately no separate mark for every flavour of dependency.

| What the field is | What it means to the user | Mark |
|---|---|---|
| **Scanned (primary)** | This command supplies the values; what you typed isn't used. | Thick dashed outline plus a small **1** or **2** badge, in that command's accent colour. The command box carries the same badge. |
| **Scanned, relative** | This command steps *from* what you typed, so your value matters. | Same outline; the badge reads **1 +Δ**. |
| **Overwritten (derived)** | The calculation sets this at every point. | Thin, quiet outline with a small badge saying which command drives it: **1**, **2**, or **1+2** when both do (H and K both feed the sample angles). |
| **Held** | The scan uses your value as a fixed coordinate (K and L during an H scan). | No mark. This is the normal case. |
| **Unused** | This kind of scan doesn't read the field at all (H/K/L during an angle scan). | One quiet "not used by this scan" note on the group, not on every field. |
| **Lock- or policy-owned** | Plane lock, autofocus curvature. | Keeps its existing indication. It gets the overwritten mark only where the solver actually assigns it per point. |

Details we agree on:
- **Colour is never the only channel.** The numbers 1 and 2, dashed versus thin, and +Δ all carry the meaning on their own.
- **A small legend** sits beside the scan commands: *dashed = scanned · thin = overwritten · +Δ = steps from your value*. Hover tooltips carry the detail.
- **No separate style for derived fields that stay constant.** During an H scan, the analyzer 2θ is still set at every point; it just comes out the same. Its tooltip says so.
- **While you type:** if a command is half-typed or invalid, its overwritten marks are withdrawn rather than guessed at. A line reads "effects preview unavailable", and stale marks never linger. A conflicting pair shows no derived marks at all.
- **The marks never move the layout,** and never override the existing error and focus styling.
- **Small correction to my earlier wording:** in relative mode your value is the scan's *base*, not necessarily its centre. Offsets 0 to 2 start there; offsets −1 to 1 centre on it.

## Where I want your push

**1. Your "greyed out" idea.** We both recommend **against** greying overwritten fields. On every desktop, grey text means "disabled, you can't edit this". But you were clear that the fields stay editable, and greying also makes the values harder to read. The thin outline plus badge says "the scan sets this" without saying "hands off". This argues against your own suggestion, so it's your call.

**2. What the marks show while a scan is running.** Here the partner and I differ.
- **Partner:** during a run, the marks freeze on the *running* scan, with a note "running scan shown; edits apply to next run".
- **Me:** the marks always describe what's in the command boxes, i.e. the *next* run. The running scan already has its own home in the plot and the progress bar. Two meanings for one mark is the confusion we're trying to remove.

The partner's version is better if students watch the docks to understand what's being scanned *right now*. Mine is simpler if they mostly set up the next scan while one runs.

## Still waiting on your word from last turn

- **Crystal θ (A1/A5):** they become real quantities, computed as half the take-off angle by default. There's room for a future crystal-rocking rule; nobody gets it now; a scan of A1 is refused with "not modelled yet". Is that what you meant?
- **Formal migration:** the API refuses requests that use the old names, saved files are converted with the original kept, and old outputs stay readable. Yes?

The final angle names still wait on ChatGPT's cross-facility reference. Once the marks are settled, I'll make a picture: two mockups at TAVI's smallest window size, so you react to something you can see, not a table.

*Turns over the fourth card: blank, waiting for your hand.*

## User

We now have @C:/Users/AMM/Documents/Github/Science/TAVI/ChatGPT_Angles_Conventions.md and @C:/Users/AMM/Documents/Github/Science/TAVI/Scattering_Angle_Conventions.xlsx .

1. Okay, we don't need to be grayed out. I think just some sort of outline around it might be helpful.
2. We take yours so the next scan that it would be right, so if they click go, what would be marked out exactly?

The A1 and A5, yes, they're real quantities that we can use in the future.

On a formal migration, let's see right now. Okay, I'm gonna say right now that nobody uses it, right? So this isn't an issue that we need to really build in legacy migration stuff. It's just that we need to be careful about it right now and not put ourselves in a situation where we expect to be able to change things here and there and have people's work suddenly break, right? Like, let's say somebody writes out an instrument, it shouldn't be the case that it breaks from underneath them. But right now we're okay.

## Assistant

*Slides the conventions spreadsheet into its own folder, pulls a fresh legal pad onto her knee, and writes four entries in a neat column.*

## Your question: what gets marked

**Yes, exactly that.** The marks are a live preview of what pressing Run would do with whatever is in the command boxes at that moment:

- **Valid commands:** a dashed outline with a **1** or **2** badge on each field a command scans, and a thin outline on every field the calculation will overwrite at each point.
- **Relative mode:** the badge shows **+Δ**, meaning "steps from your value".
- **A half-typed, invalid or conflicting command:** no overwritten marks at all, because Run would refuse it. The scan-command area says why.
- **While a scan runs:** the marks still describe the next run, since that's what Go would do.

## Recorded

**Decision: marks preview the next run** (2026-10-09)
- **Question, as put:** "What the marks show while a scan is running."
- **On the table:** frozen on the running scan (the partner's view); always the next run from the command boxes (mine).
- **Ruling:** "We take yours so the next scan that it would be right"
- **Ruled by:** operator
- **Constrains:** the running scan's identity lives in the plot and progress bar, never in the dock marks.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**Decision: no greying** (2026-10-09)
- **Ruling:** "Okay, we don't need to be grayed out. I think just some sort of outline around it might be helpful."
- **Ruled by:** operator on dropping the greying. The clerk rated "outline" as a lean ("might be helpful"), so the outline treatment is my default until you see the mockups.

**Decision: crystal θ angles are real quantities** (2026-10-09)
- **Ruling:** "The A1 and A5, yes, they're real quantities that we can use in the future."
- **Ruled by:** operator. Computing them as half the take-off angle by default, with a future crystal-rocking rule, is my default, not your words. It's how the instrument models already behave.

**Decision: clean break now, stable from here on** (2026-10-09)
- **Question, as put:** "Formal migration"
- **On the table:** a versioned API, converted saved files and legacy readers (the partner's view); no legacy machinery.
- **Ruling:** "So this isn't an issue that we need to really build in legacy migration stuff. It's just that we need to be careful about it right now and not put ourselves in a situation where we expect to be able to change things here and there and have people's work suddenly break"
- **Ruled by:** operator
- **Why:** nobody uses it yet, so breaking it now costs nothing. Breaking it later would.
- **Constrains:** old names are simply replaced, with no converters. But what this programme publishes must hold still afterwards. That includes the contract an outside author writes an instrument against (the plugin and descriptor interface), since the new solver rules become part of it.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**The note for `AGENTS.md`** (it lands with the first slice) now says this: TAVI is software facilities rely on. Public contracts are designed to stay stable, and a later change ships with a migration path and a clear refusal, never a silent reinterpretation.

## The conventions survey: what stood out

- **MLZ and ILL agree on the six physical roles.** Their names differ, and the two sets don't collide: ILL uses `A1`–`A6`, and PUMA/PANDA (MLZ instruments on NICOS) use `mth mtt sth stt ath att`. TAVI could plausibly accept both.
- **Real collisions:**
  - At MLZ, **ψ is the sample rotation**; in TAVI, `psi` is a correction to the turntable. Old LLB used ψ for the sample 2θ.
  - SPICE's `a1`/`a2` (analyzer) and the old Japanese `A1`/`A2` clash with ILL's A1/A2.
  - So TAVI's `psi` and `kappa` probably need neutral names.
- **The survey's main recommendation:** physical geometry inside, facility labels at the edge. That matches the direction we've already agreed.
- **The bigger proposal:** a common laboratory frame and mounting model (+z along the beam, +y up, a NeXus-style chain of stages). That would change TAVI's geometry contract, not just its names. I'm asking whether it belongs in this programme or in a later one.

The partner is now drafting the naming contract blind from the survey: canonical names, accepted alias families, GUI labels, the lab-frame question, and the stable instrument-author surface. When it lands I'll bring the naming discussion with both views.

*Caps the pen and tucks it behind her ear.* Back with names.

*Lays the partner's draft beside the survey and draws a single line down the middle of the legal pad: agree on the left, differ on the right.*

The partner has drafted the naming contract. The left column is long and the right one is short, so this should go quickly.

## Where we agree

**1. Canonical names are physical and carry their units.** The solver, the saved files and API output use these; you mostly never type them. Proposed spellings:
- **The six TAS angles:** `mono_theta_deg`, `mono_two_theta_deg`, `sample_rotation_deg`, `sample_two_theta_deg`, `analyzer_theta_deg`, `analyzer_two_theta_deg`
- **Tilt arcs:** `sample_lower_arc_deg`, `sample_upper_arc_deg`
- **Corrections (today's psi and kappa):** `sample_rotation_offset_deg`, `sample_lower_arc_offset_deg`
- **Energies:** `incident_energy_mev`, `final_energy_mev`, `energy_transfer_mev`
- **Curvature:** `mono_horizontal_radius_m` and its siblings
- **Slits:** `slit.post_mono.horizontal_gap_mm` and so on, now in millimetres to match what the GUI shows
- **Unchanged:** `h k l`

The crystal θ names already exist. Today they are computed as half the take-off angle; a future crystal-rocking rule would change *how they're produced*, never their name.

**2. Scan commands and the API accept aliases.** The aliases are translated to the canonical names before any check runs, and output always uses the canonical name.
- **ILL:** `A1`–`A6`
- **MLZ/NICOS:** `mth mtt sth stt ath att`
- **The usual short forms:** `H K L`, `deltaE`, `Ei Ef`, `qx qy qz`, `sgl sgu`, `rhm` and the other curvature names

The ILL and MLZ sets don't collide even ignoring case, so both work bare. `omega` always means the sample rotation, and `2theta` the sample 2θ. Two commands that resolve to the same quantity are refused. Scanning A1 or A5 gets "derived-only for now".

**3. Bare `psi`, `phi` and `kappa` are refused** with a message naming the right word. At MLZ, ψ means the sample rotation and φ the sample 2θ; in TAVI, psi is a correction. Whatever we pick, one group of users would read it wrong.

**4. GUI labels are the same for every instrument.** Physical words plus the ILL number, e.g. "Sample 2θ — A4 (°)", with the MLZ name in the tooltip. There's no per-instrument mode that changes what a typed command means, so a command pasted from IN8 into PUMA does the same thing.

**5. The aliases translate names, not readings.** An MLZ `sth` value isn't interchangeable with TAVI's A3 until zero points and signs are converted. We won't advertise importing facility data until that conversion exists.

**6. The mounting-model change waits for its own programme.** TAVI already uses the survey's frame (+z along the beam, +y up, right-handed). What would actually change is:
- the *default crystal mount*, which today puts the first reflection along +x and the survey wants along +z;
- the Q components the GUI and API publish, which have z vertical.

Changing those changes readouts and UB records, which is a scientific change rather than a naming one, and ISAR would feel it throughout its geometry. For now we document the frames exactly as they are.

**7. The stable contract for instrument authors** gets:
- a version number, with a mismatched plugin refused at load;
- canonical quantity names;
- the rule interface (declared inputs, outputs and refusals);
- stable slit IDs;
- a reserved namespace for instrument-specific extras, so an author can't redefine `A4`.

The internals stay private. Today's authoring guide publishes the old positional scan slots, and those get replaced in the same break.

## Where we differ: other facilities' dialects

- **Partner:** support SPICE (ORNL) and the old Japanese JRR-3 names as well, behind prefixes: `spice:a1`, `jrr3:C1`, plus `mlz:psi` and `tavi:psi`.
- **Me:** don't build that yet. None of your users has asked for it. Prefixes are a little language people have to learn, and the alias resolver can take a new family the day someone needs one, without breaking anything. For psi, a clear refusal ("TAVI calls this `sample_rotation_offset`; MLZ ψ is A3") teaches more than a prefix does.

My recommendation is my side: ILL and MLZ bare, nothing else for now, and refusals that explain.

## Where I want your read

1. **Do MLZ students want MLZ labels on PUMA and PANDA** (`sth` / `stt` in the dock), rather than the ILL numbers with MLZ in the tooltip? We both chose uniform labels so a command means one thing everywhere. But your students live in NICOS, and you know whether "A4" will feel foreign to them.
2. **Are the canonical spellings acceptable?** They're long by design: they get written into files and other people's code, never typed into a scan box. If you'd prefer them shorter, say so now; after this break they're frozen.
3. **Does the mounting model stay out of this programme?**

*Leans forward on her elbows, the cuff falling back from her wrist.* Talk me through your students.

## User

Okay, nobody is used to Tavi. Tavi is not a convention that we need to worry about right now, so if we need to change something for Tavi, that's okay. Nobody has asked for anything from any other facility, and TAVI is not built right now to go against any other facility. So your questions here like, do the students want this or that? They don't have any idea. Like, they have no experience. They're completely fresh to it. We should try and adopt a convention that when scientists, mostly who instrument scientists who work on this stuff, look at it, they're gonna be able to make sense of it and not get confused.

2. Yes
3. What do you mean by the mounting model?

So I generally agree we can match IL and Nikos. Those are good things to match too. So the big questions then are psi, chi, and kappa, things like this, omega, any of those.

## Assistant

*Strikes a neat line through one question on the pad and taps the pen against the next.*

Fair point. I was asking about habits your students don't have yet.

*Withdrawn: whether MLZ students want MLZ labels on PUMA and PANDA, because the students have no habits yet. The test is whether an instrument scientist can read it without confusion.*

## Recorded

**Decision: who the names are for** (2026-10-09)
- **Ruling:** "We should try and adopt a convention that when scientists, mostly who instrument scientists who work on this stuff, look at it, they're gonna be able to make sense of it and not get confused."
- **Ruled by:** operator
- **Why:** "nobody is used to Tavi", so TAVI's own current names carry no weight.
- **Constrains:** every name is chosen for an instrument scientist's reading.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**Decision: canonical spellings accepted** (2026-10-09)
- **Ruling:** "2. Yes", to "Are the canonical spellings acceptable?"
- **Ruled by:** operator
- **Constrains:** `sample_two_theta_deg` and its siblings are frozen after this break.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**Decision: match ILL and NICOS** (2026-10-09)
- **Ruling:** "So I generally agree we can match IL and Nikos. Those are good things to match too."
- **Ruled by:** operator. Accepting both bare in scan commands, with no other facility dialects for now, is my default. You said nobody has asked for others.

## Your question: what I meant by "the mounting model"

It's how TAVI describes a crystal sitting on the sample table, and so which way it points when every motor reads zero. The survey proposes a common standard for that. TAVI already follows most of it: the beam travels along +z and "up" is +y. It differs in two places:
- **The default mount:** when you tell TAVI "this plane is horizontal", it lays your first reflection along one direction; the survey would lay it along another.
- **The published Q components:** the GUI and API report qx, qy, qz with z vertical, while inside TAVI y is vertical.

Changing either changes the *numbers* a user sees (A3 readings, Q components, saved UB matrices), not just the labels. So it's a geometry change, not a naming one. My recommendation is to document both exactly as they are now and leave any change for its own discussion. I'm not attached to this; it was a "keep the scope honest" note.

## The real question now: the Greek letters

Each one means different things in different places, so here's what each means where, and what I'd do.

- **omega (ω).** In TAS and diffraction practice an "omega scan" is a rocking scan of the sample rotation, so ω means A3. SPEC's four-circle software defines OMEGA differently, but a TAS scientist will read A3. **Keep `omega` as a name for the sample rotation (A3).** Today TAVI's `omega` scan secretly moves the psi correction instead; that is fixed by this.
- **psi (ψ).**
  - At MLZ (NICOS), ψ is the sample rotation.
  - In SPEC, ψ is an azimuth around Q.
  - At old LLB, ψ was the sample 2θ.
  - In TAVI, it's a zero correction to the turntable, which matches nobody.

  Whatever bare `psi` means, someone misreads it. **Refuse bare `psi`**, with a message along the lines of: "ψ means different things at different facilities: for the sample rotation use A3 or sth; for TAVI's turntable correction use a3_offset."
- **phi (φ).** At MLZ, φ is the sample 2θ; on a four-circle, φ is the innermost sample rotation. **Refuse bare `phi`**, with the same kind of message.
- **chi (χ).** On every four-circle and Euler cradle, χ is a tilt circle. TAVI's sample stage has arcs instead (sgl/sgu, the ILL and SPICE names, which are already correct), and TAVI already refuses `chi` with a pointer to the arcs. **Keep that.**
- **kappa (κ).** In diffraction, κ is the tilted axis of a kappa goniometer. TAVI uses it for the lower-arc zero correction, which a diffractionist would misread. **Rename it.**

**What the two corrections get called instead.** These are TAVI's training feature: a zero error the student finds and corrects. What a real instrument has here is a **zero offset** on a motor. I'd name them **`a3_offset`** and **`sgl_offset`** for typing, with canonical names `sample_rotation_offset_deg` and `sample_lower_arc_offset_deg`. Any instrument scientist reads "A3 offset" at once.

I believe ILL's MAD software calls its zeros `ZA3` and `ZGL`. I haven't verified that, or its sign convention, so I wouldn't adopt it unchecked. If it checks out, it could be an extra name for the same thing.

**Where I want your push:** refusing bare `psi` is the strict choice. The looser option is to accept it as the MLZ meaning (sample rotation), since we're matching NICOS. I lean strict because ψ is so overloaded. But you know better than I do whether an MLZ scientist would find a refusal pedantic, or just honest.

*Turns the pad around so the Greek column faces you.*

## User

Good, so we have a lot of disagreement here on Greek letters. Yeah, generally omega is the rocking scan, the sample rotation. And of course for MLZ then psi, in NICOS, is the sample rotation.  Let's let omega OR psi be the sample rotation. Chi is good, and clear. So we have phi and kappa, but those are clear for diffraction; we shouldn't mess with them then and keep it in those terms. Why MLZ uses phi for 2theta I have no idea. We drop the TAVI kappa as not used anymore, and the psi as omega correction.

The directions of y and z and such might be related to McStas and how it lays out its geometry. So it's not necessarily the case that everything's gonna work out quite so simply there.

## Assistant

*Rubs out half a column with the side of her hand, rewrites it cleanly, and hums at the result.*

That's a clean settlement, and it leaves one thread I need to check before moving on.

## Recorded

**Decision: Greek names** (2026-10-09)
- **Question, as put:** what bare `omega`, `psi`, `phi`, `chi` and `kappa` mean to TAVI.
- **On the table:** refuse every overloaded letter (my strict lean); accept the meanings a TAS or diffraction scientist expects.
- **Ruling:** "Let's let omega OR psi be the sample rotation. Chi is good, and clear. So we have phi and kappa, but those are clear for diffraction; we shouldn't mess with them then and keep it in those terms."
- **Ruled by:** operator
- **Constrains:**
  - `omega` and `psi` both name the sample rotation (A3), alongside `A3` and `sth`.
  - `chi` keeps its four-circle meaning and its existing refusal, which points to the arcs `sgl`/`sgu`. TAVI has no χ circle.
  - `phi` and `kappa` are reserved for their diffraction meanings. TAVI has neither axis, so a bare `phi` or `kappa` is refused with that explanation.
  - MLZ's φ for sample 2θ is not adopted; sample 2θ is `A4`/`stt`/`2theta`. So our NICOS match covers the motor names (`mth mtt sth stt ath att`) plus ψ, but not φ.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**On the y/z directions and McStas:** agreed. McStas has its own layout (z along the beam, y up), and TAVI's component placement follows it, so "just swap the Q axes" isn't simple. That's one more reason the mounting model stays out of this programme. Here we only document the frames exactly as they are.

## One thread before we move on

"We drop the TAVI kappa as not used anymore, and the psi as omega correction." I can read that two ways, and they're very different amounts of work:

**(a) Drop the names only.** The two zero corrections stay as features under new names, `a3_offset` and `sgl_offset`. They're part of the UB training today:
- the misalignment exercise hides a zero error on A3 and on the lower arc;
- the student corrects it through these fields;
- every recorded peak stores the corrections in force, and the UB fit reads them back (`docs/INSTRUMENT_LAYOUT.md:71-97`).

**(b) Drop the corrections as features.** The training exercise then has no way to correct a zero except through the UB matrix itself, and the peak records, the fit and the sample dock all lose a field. That's arguably what a real instrument does: you fix a motor's zero in the motor, not in a separate correction slot. But it's a real change to the training workflow, and I'd want to see whether the exercise still teaches what you want.

"Not used anymore" sounds like (b), at least for kappa. Is that what you meant, for both? Or just retiring the Greek names?

*Holds the eraser poised over the corrections row, waiting for your word.*

## User

(b), And this is something we're going to have to look at the training workflow because we have basically two parallel ones, and the earlier one was this Kappa Psi offset correction. That's something we'll have to look at more closely.

## Assistant

*Pulls the training binder down from the high shelf, rising onto her toes to reach it, and blows the dust off the spine.*

**Decision: retire the zero corrections** (2026-10-09)
- **Question, as put:** "Drop the corrections as features."
- **On the table:**
  - **(a) Rename only:** the corrections become `a3_offset` and `sgl_offset`, and the training workflow is unchanged.
  - **(b) Retire them:** the turntable and lower-arc corrections go, along with their place in peak records, the UB fit and the sample dock.
- **Ruling:** "(b), And this is something we're going to have to look at the training workflow because we have basically two parallel ones"
- **Ruled by:** operator
- **Why:** the corrections belong to the older of two parallel training workflows.
- **Constrains:**
  - The new solver has no correction quantities.
  - The training workflow needs a decision before the solver is cut.
  - Any exercise that relies on the corrections has to change or go.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

I've sent a reader agent through the training code and its git history to find out:
- what the two workflows are, as a student experiences them;
- which one is older, and whether it is still wired up end to end;
- everything the corrections touch: GUI, solver, scan slots, API, saved files, peak records, tests, and ISAR and TAS_MCP;
- whether removing the corrections leaves any exercise unsolvable.

When it lands I'll lay out both workflows for you plainly. Then we'll decide whether the older one is retired inside this programme or gets its own job.

*Sets the binder down between us, open to the first tab.*

*Flips through the binder's first two tabs, frowning faintly at the second.*

The reader is back. Here's the short version; the full question comes once the partner weighs in.

**The two workflows:**
- **Older: the Misalignment dock** (January 2026). A teacher hides a zero error on the turntable (A3) and on the lower tilt arc (sgl), and shares a code. The student corrects it with the psi/kappa fields or by fitting a UB matrix. It is still fully wired up.
- **Newer: the UB Matrix dock** (from March, reworked 1 October). It can hide a mount orientation and, optionally, the same zero errors. The student records peaks and fits the UB matrix.
- **Both use one grader:** worst miss ≤ 0.5° counts as aligned, ≤ 2° as close.
- ISAR and TAS_MCP don't touch the corrections at all, so retiring them stays inside TAVI.

**There's one physics catch I want checked before I put it to you.** Retiring the corrections doesn't remove the *hidden zero errors*; those come from the teacher's settings. A UB fit can absorb a hidden mount orientation exactly. But I believe it can't fully absorb a motor zero error once the arcs are tilted, because the error sits *between* motors in the chain rather than at the crystal. If that's right, a student could do everything correctly and still miss by more than 0.5°. That would be an exercise that teaches the wrong lesson.

On a real instrument, a motor zero is fixed in the motor itself (NICOS calls it "adjust"). That's arguably what psi/kappa were, under confusing names.

I've asked the partner to check the geometry blind and say what real instruments do. Then I'll bring you the training question with options: what to retire, what the exercise keeps, and whether it lives in this programme or its own job.

*Marks the page with a paper clip and leaves the binder open on your side.*

*Takes the paper clip off the binder and taps it on the page.* The catch is real, though the partner drew its edge more precisely than I did.

## The geometry, in plain words

The sample stage is a chain of three motors: the turntable (A3) carries the lower arc (sgl), which carries the upper arc (sgu), which carries the crystal. A UB fit can absorb a hidden error only if that error looks like one fixed crystal orientation across every motor setting the student uses. Whether it does depends on whether the motors *further along the chain* move:
- **A turntable zero error** is absorbed exactly only if both arcs stay fixed.
- **A lower-arc zero error** is absorbed exactly only if the upper arc stays fixed.
- **A hidden mount orientation** (the crystal glued on crooked) is always absorbed exactly. Correcting it is exactly what a UB fit is for.

So once the psi/kappa corrections are gone, a hidden *motor zero* error can leave a residual the student has no control to remove. A student can do everything correctly and still miss the 0.5° bar. Worse, the newer UB exercise also injects zero errors, and does so **by default** (`gui/docks/ub_matrix_dock.py:606`). Retiring only the old dock wouldn't close the problem.

**How real instruments fix a motor zero:** NICOS `adjust`, MAD's `ZA3`/SetZero and SPICE `setpos` all *relabel* the motor's current reading without moving anything. TAVI's psi/kappa did something different: they moved the simulated crystal while the readout stayed put. Renaming psi/kappa as "calibration" would not give you the real thing.

## Question: what happens to the alignment training

**Why now:** the solver slice deletes the corrections, so the training has to be in a coherent state the day that lands.

**Option 1 — mount-only training now; real zero calibration later as its own job.** *(The partner and I both recommend this.)*
- **Retired:** the Misalignment dock exercise.
- **The UB exercise:** stops generating hidden motor-zero errors and keeps the hidden mount orientation, peak recording, UB fitting and the grader.
- **Old exercise codes:** an old shared code that contains zero errors is refused with a clear message, not loaded with its errors silently dropped.

What the student learns is exactly what a UB matrix is for: find how the crystal is mounted.
- *One month:* one clean, always-solvable exercise.
- *Later:* a proper motor-zero calibration job could add `adjust`-style zeroing on every axis, an exercise built around it, and the peak-record rules that go with it.

**Option 2 — build real zero calibration inside this programme.** This keeps the old lesson and makes it realistic. But it adds a new state contract (what a zero does to old peaks, its limits, how it's graded) to a programme that is already broad. It's worth it only if the zero-error lesson has to be there for your next tutorial.

**Option 3 — keep zero errors but restrict the exercise to fixed arcs.** The maths holds, but students learn an alignment that breaks as soon as the solver tilts the arcs differently, and the restriction has to govern both what they measure and how they're graded. We both reject this one.

**Where I want your push:** does the motor-zero lesson matter to you as teaching content, beyond being the older exercise? If it does, Option 1 still holds, but the calibration job goes straight onto the board as the next thing after this programme rather than "someday". If you actually use it in tutorials, tell me, because then the timing changes.

*Unbends the paper clip into a straight line and sets it down.*

## User

1 is fine, and we pin it for followup in a new session once this one lands.

## Assistant

*Lays two glossy prints side by side on the blotter and steps back so you can see both.*

**Decision: alignment training** (2026-10-09)
- **Question, as put:** "Option 1 — mount-only training now; real zero calibration later as its own job."
- **On the table:**
  1. Mount-only training now, with calibration as a later job.
  2. Real zero calibration built inside this programme.
  3. Keep the zero errors and restrict exercises to fixed arcs.
- **Ruling:** "1 is fine, and we pin it for followup in a new session once this one lands."
- **Ruled by:** operator
- **Constrains:**
  - The Misalignment dock exercise is retired.
  - The UB exercise stops generating hidden motor-zero errors.
  - An old exercise code containing zero errors is refused with a message.
  - A motor-zero calibration job goes on the board (`WIP.md`) when this programme lands. I can't write the board during the design stage.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

## Mockups of the field marks

These are rendered with real Qt widgets, not drawn by hand. Open them side by side:
- `C:\Users\AMM\AppData\Local\Temp\claude\tavi_marks_option_A.png`
- `C:\Users\AMM\AppData\Local\Temp\claude\tavi_marks_option_B.png`

**The example scan:**
- **Command 1:** `H 0.9 1.1 0.02`, absolute, in blue.
- **Command 2:** `deltaE -1 1 0.25`, relative, in orange, with Kf fixed.

**Same in both mockups:**
- The angle labels use the new names (e.g. "Sample 2θ — A4").
- **Scanned:** H (blue, **1**) and ΔE (orange, **2 +Δ**).
- **Set by the scan at every point:**
  - qx, qy, qz, from H (**1**);
  - mono θ and mono 2θ, from ΔE, because Kf is fixed (**2**);
  - sample rotation, sample 2θ and both arcs, from both (**1+2**).
- **Unmarked, used as typed:** K, L, fixed E, and the analyzer angles (held by the fixed-Kf setting, not by either command).
- A two-line legend under the commands says what each mark means, and that this previews the *next* Run.

**The difference between them:**
- **A, the outline on the field itself.** Scanned fields get a dashed border in the command's colour. Overwritten fields get a darker border with a heavier bottom edge. It's the closest to what you asked for and reads at a glance, but the "overwritten" look is subtle next to a plain field.
- **B, a bar beside the field.** The field itself stays untouched, and a coloured or grey bar sits just left of it. It's quieter and never interferes with the existing error colouring, but the mark is a step away from the value.

My pick is **A**, with the overwritten border made a touch darker than in the mockup. It answers "this box won't be used" right on the box. B's bars also drifted away from their fields in this rendering, which is a hint of how fragile that layout would be in the real docks.

*Taps the corner of print A with one fingernail.* Which one, and does anything in it read wrong to you?

## User

I think A is better.

## Assistant

Now the partner drafts the review lenses blind from the settled design.

*Pins print A to the corkboard and drops print B in the recycling.*

**Decision: the look of the field marks** (2026-10-09)
- **Question, as put:** "Which one, and does anything in it read wrong to you?"
- **On the table:** A, an outline on the field itself; B, a bar beside the field, with the field left unchanged.
- **Ruling:** "I think A is better."
- **Ruled by:** operator
- **Constrains:** the scanned field gets a dashed outline in its command's colour, plus a 1 or 2 badge. Each overwritten field gets a darker, thinner outline plus a 1, 2 or 1+2 badge.
- **Checked:** clerk 2026-10-09, backed, session f3d77e95

**The design is settled.** I've written it up the way the process wants it: what TAVI looks like now versus what you hoped to see, in prose, with nothing about how the work gets done. It's at `C:\Users\AMM\AppData\Local\Temp\claude\tavi-j92f2a0718dc1-design.md`.

**Next step: the review questions.** Every reviewer in this job will have to answer a fixed set of questions, which the process calls "lenses". I've drafted my list:
- refused pairs can't be built;
- the physics is unchanged after the rename;
- relative-scan bases;
- the naming contract;
- the instrument-author contract and the consumer sweep;
- the training change;
- the marks' behaviour;
- the marks' geometry and accessibility.

The partner is drafting its list blind. Once it's in, I'll merge the two and register the design. Then you get it to approve with `/approve`, which binds the design and its review questions together.

**Two things for you to decide before you approve:**
1. **This is a big programme.** It covers the naming break, a solver rebuild, four instruments, the API, ISAR and TAS_MCP. Do you want to type `/ChatGPT-Pro` for an outside deep review of the design before approval?
2. **Do you want a transcript?** This conversation produced a lot of rulings. I can save it with `/transcribe`; I'll only offer once.

*Smooths her skirt as she sits back down, legs crossed at the knee, and waits for the partner's list.*

*Squares the stack of pages and clips the review questions to the front.*

I merged the two lists of review questions ("lenses", the fixed questions every reviewer in this job must answer). The partner's version was more thorough than mine, so I took its nine and added two points of mine:
- the existing sign-convention tests must pass without being regenerated;
- the marks must be checked at the smallest and largest window sizes, with their colours coming from a theme module rather than hard-coded values.

**The nine questions cover:**
- refused pairs can't be built and accepted pairs are honoured exactly;
- the physics is unchanged across all four instruments;
- relative-scan bases are captured once;
- the naming contract is consistent everywhere;
- the instrument-author contract;
- ISAR and TAS_MCP really work against the new names;
- the training change;
- the marks show exactly the next run;
- the marks look like option A without harming layout or the existing error styling.

The design and these questions are now registered on the job. Before the design can be presented, the process compresses this conversation into a short transcript for the planning stage, and that's running now. Once it lands, I'll present the design, and you approve it with `/approve`.

Two questions from last time are still open:
1. Do you want a `/ChatGPT-Pro` outside review of the design before you approve?
2. Do you want this conversation saved with `/transcribe`? I'm only offering once.

*Uncrosses her ankles under the desk and reaches for her coffee while the copier runs.*

*Slides the bound brief across the desk, turned to face you, the pen laid on top.*

The design is presented and ready for your `/approve`. Nothing has been built yet.

## Where things stand

**Job:** j92f2a0718dc1, T3, heavy design depth, stage `discuss`, waiting on you.

**The design**, in its own words: "Scans that say what they do, in names an instrument scientist reads." It's the now-versus-hoped text shown above, and it's stored with the job.

**The rulings it rests on** (all 2026-10-09; each is quoted from you and was checked by the clerk unless marked otherwise):
1. **Hard refusals.** Scan pairs that can't be honoured are refused, and `force` can't override that.
2. **The solver is the model.** It is rebuilt as named rules, and the run executes exactly the plan that judged the pair.
3. **No stopgap.** The H×A4 bug stays latent until the solver work closes it.
4. **Wider scope.** One design covers naming, the solver, refusal, marks and the consumer sweep.
5. **Clean break now, stable afterwards.** No legacy converters, since nobody uses the old names. After this break, the published contracts hold still, including the instrument-author contract.
6. **Names are for instrument scientists.**
   - ILL A1–A6, with physical labels on every instrument, and NICOS motor names accepted alongside.
   - `omega` and `psi` both mean the sample rotation. `chi`, `phi` and `kappa` keep their diffraction meanings and are refused.
   - The long canonical names are accepted.
7. **The crystal θ angles (A1/A5) are real quantities,** usable in the future. That they are derived by default is my default, not your words.
8. **The zero corrections are retired.** The alignment training becomes mount-only, and motor-zero calibration is a follow-up job.
9. **Field marks:**
   - they preview the next Run;
   - no greying;
   - option A, the outline on the field itself, with the dashed primary, the quieter overwritten outline, and 1, 2, 1+2 and +Δ badges.

**My defaults** (not your rulings; any of them can be overridden):
- slit scans get wired up rather than withdrawn;
- the mark colours start a small theme module;
- the mounting model and lab frame are deferred and documented as they are now;
- `AGENTS.md` gets its "Audience and stability" section in the first slice.

**Nine review questions** ride with the design: the solver honours what it accepts, physics unchanged, relative bases, the naming contract, the author contract, ISAR/TAS_MCP, training, marks behaviour, and marks look and geometry.

**Housekeeping:**
- The mockup you picked, plus the script that rendered it, are also saved in the job's own folder: `C:\Users\AMM\AppData\Local\ACS\state\v1\artifacts\j92f2a0718dc1\`. The review question about the marks' look still points at the temporary copy.
- The two ChatGPT angle files stay uncommitted.

## Next steps

1. **You:** type `/approve` if this design is right, or tell me what's wrong with it first.
2. Planning then runs: it breaks the work into slices with their own review seats. I'll come back with the plan before anything is built.

**Still open from earlier:**
- **`/ChatGPT-Pro`:** do you want an outside review of the design before approving? It's a big programme, so it's a fair moment for one.
- **`/transcribe`:** this was a rulings-heavy conversation worth saving. This is my one offer.

*Leans back in the chair, heels crossed on the footrest, and waits.*
