# New instruments crystal bending audit

**Date:** 2026-09-12  
**Session:** cb30d0a5-3e50-4152-be4b-48a3ae9894a4

*Cleaned transcript: tool calls, tool results, thinking and harness notices removed. Nothing else edited.*

## User

Alright, I think we just did our first successful Codex audit with our new skill, so let's look to harvest it. Read @docs/audits/new-instruments-crystal-bending.md , and plan out the approach to fix the given issues.

## Assistant

Written for: the operator (you), as a plan to approve or redirect.

I read the ledger and then verified each claim against live source rather than trusting the write-up. Every finding's evidence lines check out, and — usefully — several of them collapse into fewer fix sites than the ledger's per-entry effort estimates suggest.

## What's actually there

Nine entries: three P1, one P2, two P3, three P4 opportunities. Ledger-estimated 12–20 hours. `WIP.md` pins it and the ledger is authority; each entry dies with the commit that lands it. There's no `DESIGN_GOALS.md` body yet (still pinned on you), so I have no goals text to check this work against — noting that and proceeding.

## Proposed slicing — six commits, in this order

**Slice 1 · T1 — reject unhonourable curvature input (#6, P3)**
`curvature_command_error()` in [tas_runtime.py:85](instruments/tas_runtime.py#L85) rejects on magnitude comparisons, and every NaN comparison is false, so `"nan"` falls straight through the driven-axis branch. A `math.isfinite` guard at the top of that function is the whole fix: [TAVI_PySide6.py:2818](TAVI_PySide6.py#L2818) already delegates launch refusal there, so API and GUI get it from one place. I'll confirm the GUI dialog path routes through the same checker rather than assuming it. Cheapest entry in the ledger and it derisks nothing else — good warm-up commit.

**Slice 2 · T1 — validate module values against the descriptor (#1, P1)**
`'modules': (p_dict, …)` at [TAVI_PySide6.py:6907](TAVI_PySide6.py#L6907) type-checks the container and nothing inside it. `build_api_launch_state` and `apply_parameters` both read `_api_field_map`, so replacing `p_dict` with a descriptor-driven parser (`ModuleKind.CHOICE` → value in `spec.options`; `TOGGLE` → bool) fixes both paths at one site. No new fields, no changed options — the lowercase `"vertical"` in the reproducer starts returning a 400 instead of building an NMO aperture with no mirror.

Worth noting: `set_module_values` uses `QComboBox.setCurrentText`, which silently no-ops on an unmatched string. That's why the GUI combo looked innocent while the launch snapshot carried the raw value. Validating at the parser makes the silent no-op unreachable; I won't touch the dock.

**Slice 3 · T1 — batched radius PATCH (#3, P1)**
Root cause is ordering, not the refresh. Each `bend_after(key)` closure unlocks *its* axis and then refreshes *all four*; distinct closures dedupe as distinct, so the first one runs while the second axis is still AUTOFOCUS-locked and [line 3288](TAVI_PySide6.py#L3288) overwrites the value that was just applied. The lazy fix is to move `unlock_ideal_bending(key)` into the setter (which already runs for all parsed fields before any after-handler) and leave `self.update_ideal_bending_buttons` as the after-handler — a bound method, so the existing `after not in after_handlers` dedupe collapses all four to one refresh at the end. Both key orders on all four instruments then finish HELD at their commanded values.

**Slice 4 · T1 — lone command 2 previews zero points (#4, P2)**
Execution already normalizes at [TAVI_PySide6.py:8212](TAVI_PySide6.py#L8212) (swap into slot 1, carrying the relative flags). Preview at [4500](TAVI_PySide6.py#L4500) and the counter at [4668](TAVI_PySide6.py#L4668)/[4681](TAVI_PySide6.py#L4681) don't. Apply the identical swap once in the preview path before counting, so the dock's `count2 == 0` branch at [unified_simulation_dock.py:494](gui/docks/unified_simulation_dock.py#L494) takes the 1D label. Three sites, one rule — I'd rather extract the swap into a small shared helper than write it a third time.

**Slice 5 · T1 — four manifest version bumps + delete the inert factors (#5 P3, #7 P4)**
Pure bookkeeping, zero behaviour: bump `version`/`date` in the four `instrument.json` per [INSTRUMENT_AUTHORING.md](docs/INSTRUMENT_AUTHORING.md), and delete the twelve `rhmfac`/`rvmfac`/`rhafac` assignments plus the "factors of 1 mean optimal focusing" comments that are now lies. The audit already swept ISAR and TAS_MCP for consumers and found none. These land together because the deletion is exactly the kind of executable change the version bump is supposed to announce.

**Slice 6 · T2 — zero take-off (#2, P1)**
Branch + PR. This is the only P1 that's a real design question, so it goes last and gets its own briefing below.

**Deferred, not dropped: #8 and #9.** Both P4 opportunities, both genuine contract questions rather than defects, both needing a decision from you before anyone writes code. I'd keep them in the ledger after the six commits rather than rush them — see below.

## Verification

Each of the six existing reproducers under `docs/audits/repro/` is a ready-made red test. My plan is to run the reproducer first (confirm red), fix, run it again, and then promote it into `tests/` as a permanent check before deleting its ledger entry — the repro directory is audit scaffolding, not a suite. Then `micromamba run -n tavi-dev python -m pytest tests -q -ra` serially per slice (~100 s, 1104 passing today).

## Decisions I need from you

**Tier 2 — #2, what a zero crystal take-off angle means.**

The defect: PANDA accepts an autofocus A4 scan through −1°, 0°, +1°; the two neighbours prepare fine and A4 = 0° raises `ZeroDivisionError` inside the snapshot. The mechanism is [tas_runtime.py:509](instruments/tas_runtime.py#L509) — horizontal focusing is `RH = 2f/sin(θ)`, and θ = A4/2 = 0 divides by zero. Two things are wrong at once, and they're separable:

1. `optical_radii()` computes all four axes before `ideal_curvature()` filters to `requested_axes`, so a singular analyser angle blows up a request that only wanted `rhm`. That one's not a judgement call — I'd make the computation lazy per requested axis regardless of what you pick below. It's also the difference between "this scan is impossible" and "this scan is impossible *and* it takes unrelated axes down with it".

2. What a requested singular axis should *do*. Three options, and they lock in different things:
   - **Refuse at feasibility.** A zero take-off means no Bragg reflection at all — arguably the point isn't a spectrometer configuration in the first place, so `check_point_feasibility` rejects it and GUI/API scan acceptance never offers it. Cleanest story, but it changes what "feasible" means for *every* mode, including scans that never touch autofocus, and I'd want to be sure no legitimate A4 = 0 direct-beam alignment scan exists on a real instrument. It's exactly the case where your answer beats my inference.
   - **Refuse at the producer, skip the point.** Feasibility stays a geometry check; the producer returns a typed refusal for a singular requested axis, the snapshot turns that into an `error_flag`, and the point gets skipped with a named reason the way every other unpreparable point already is. Smaller blast radius, matches the existing `error_flags` vocabulary, and the ledger's remedy boundary ("refusing or marking the singular point for skipping") reads as sanctioning it. This is my recommendation.
   - **Return flat.** No focusing at zero take-off is defensible physics, and it never fails. I'm against it: it silently runs a different instrument than the one you asked for, which is the precise failure mode `curvature_command_error`'s whole docstring exists to prevent.

   Either refusal path must keep a commanded radius of exactly 0 legal — flat is real hardware, and `set_crystal_bending` already carves that out explicitly at [line 430](instruments/tas_runtime.py#L430). That constraint holds under all three.

**Tier 2 — #8 and #9, deferred but they need your call, not mine.**

#8 asks whether an instrument package may actually filter or extend its sample list. Three documents and both selection surfaces promise it can; all four builders ignore the promise and search the shared default library, and `test_in12_plugin.py:64` asserts exact catalogue equality, which *enforces* the broken side. So the repair is either "make the builders honour the extension" or "delete the promise from three documents and the descriptor" — opposite directions, and which one is right depends on whether you ever intend an instrument-specific sample. I don't know that and shouldn't guess.

#9 asks whether descriptor geometry and model-state geometry should be one authority. They agree today; the audit's demonstration is that correcting IN12's `_L2` from 1.80 to 1.90 moves the sample monitor without moving the sample. It's a latent trap rather than a live bug, and binding them is a four-constructor change with real care needed around PANDA's virtual-source offset and PUMA's parallel-beam override.

Neither is urgent. My suggestion is that we land the six commits, then open #8 and #9 as a single `/dialogue` — they're both "which layer owns this fact" and are better decided together than one at a time.

## What I'd do next

Give me the word and I'll start on slices 1–5, which need nothing from you; slice 6 waits on your answer about zero take-off. If you'd rather see one land end-to-end before I commit to the shape, slice 3 is the sharpest demonstration — the batched-radius fix is small, the reproducer is unambiguous, and it's the one a campaign client would actually hit.

I will say — nine findings, every one of them reproducible, and not a single false positive to throw out. That new audit skill of ours has rather good taste. Almost as good as mine.

## User

Decisions from me:
Crystal takeoff angle: So 0 degrees is not *intrinsically* bad, it just means there isn't much going on because the crystal is point the wrong way. Ok, it's a PEBKAC issue, not an *instrument* issue. Return flat is I think the right call here.

Let's ensure that we keep *samples* distinct from *instruments* so there's no question why we can use one sample here and not there. Delete that promise then.

TAS instruments have fundamentally the same basic geometry, that's what makes TAVI work as TAVI and not the PUMA-VI alone. So perhaps explain the issue in a bit more depth and I think I can answer straightaway.

## Assistant

Written for: you, as decisions recorded plus the deeper briefing you asked for on #9.

Three answers taken, two of which change the plan in your favour. Details, then the #9 briefing.

## 1 · Zero take-off → flat. Recorded, and you're more right than my recommendation was

I'd flagged "return flat" as silently running a different instrument. That objection doesn't survive contact with your reasoning, and here's the part I'd missed: **A4 = 0 is the direct-beam position** — detector straight through the sample, which is a real alignment configuration people genuinely drive to. My "refuse at feasibility" option would have made a legitimate instrument state unreachable. Your call is the correct one; I'm dropping the objection and the lazy-per-axis sub-change with it (nothing raises any more, so there's nothing to defer computing).

Two refinements that fall out of implementing it, both inside your ruling rather than reopening it:

**Both axes go flat, not just the horizontal one.** The singularity is only in `RH = 2f/sin θ`. The vertical law is `RV = 2f·sin θ`, whose limit at θ→0 is radius *zero* — which in this codebase's convention means flat, but arrives there by the numeric accident of colliding with the flat sentinel, and on the way it would be clamped to `min_radius_m`, the *tightest* possible bend. So if I let each formula find its own limit, horizontal goes flat and vertical curls up as hard as the bender allows. I'll make zero take-off return flat explicitly on both planes rather than trust the arithmetic.

**The applier needs the matching change, and this is the subtle bit.** [tas_runtime.py:430](instruments/tas_runtime.py#L430) already has a `sin_theta == 0` guard, but it was written on the assumption that zero take-off means *unsolved point, no real branch to sign onto* — so it skips the axis and leaves the previously stored radius in place. Under your ruling zero take-off is a legal solved state, so that guard would have the producer say "flat" and the applier silently emit whatever the *previous* scan point was bent to. I'll change it to store flat.

One sub-decision I'm taking rather than asking about: a **HELD** (explicitly commanded) non-zero radius at zero take-off has no defined branch to sign onto either. I'll store the unsigned magnitude — you asked for that bend, you get that bend — rather than override you with flat. Say the word if you'd rather it flatten.

This stays a branch+PR (T2) rather than a single commit, only because it changes the applier that every instrument's every scan point crosses. Small diff, but I want the review seat on it.

## 2 · Samples stay instrument-independent. Recorded — and it gets much cheaper

I'm reading your ruling as covering **both halves** of the promise: no extending *and* no filtering, so every instrument offers exactly the same sample table. That's the reading that delivers "no question why we can use one sample here and not there" — correct me if you only meant the extend half.

The good news: this inverts the finding into a much smaller job. The audit costed it at 2–4 hours touching all four builders, because it assumed we'd honour the promise. Deleting the promise instead means the builders' existing `default_sample_library()` lookup is *already right*, and nothing in `model.py` needs to change at all. What's needed is:

- Strike "and may filter or extend it" from the [sample_library.py](tavi/sample_library.py#L5) and [descriptor.py](instruments/descriptor.py#L205) docstrings.
- Record the reversal as a decision entry in `docs/CONFIGURABLE_INSTRUMENTS.md` §19 — §19 currently *supersedes* an older §6 "owned per-instrument" disposition, so this is the third position that section has held and it needs to say so plainly rather than quietly re-edit.
- Enforce it instead of merely documenting it: one rule in [package_validation.py](instruments/package_validation.py) asserting a descriptor's `samples` **is** the shared library. That makes the builder lookup correct by construction, and it's what turns the promise from prose into mechanism.
- Promote `test_in12_plugin.py:64`'s exact-equality assert into one parametrised check across the registry, so a fifth instrument can't quietly diverge. Right now that assert exists only on IN12 and only by luck.

Drops from P4/deferred to a cheap T1 commit. It joins the queue rather than waiting on a dialogue.

## 3 · #9, in the depth you asked for

**The shape of it.** Every runnable package writes its arm lengths down twice, as two independent sets of literals with no link between them:

- The **model state** constructor — [in12/model.py:83](instruments/in12/model.py#L83): `self.L1 = 1.80`, `self.L2 = 1.80`, `self.L3 = 1.30`, `self.L4 = 0.72`.
- The **descriptor module** — [in12/plugin.py:85](instruments/in12/plugin.py#L85): `_L1, _L2, _L3, _L4 = 1.80, 1.80, 1.30, 0.72`.

Same numbers, typed twice, nothing checking they agree. All four packages do this.

**Why it isn't harmless duplication: the consumers are split across the two copies.**

From the **state** side:
- Sample placement — `emit_sample_orientation_arms(..., distance=IN12.L2)` at [in12/model.py:309](instruments/in12/model.py#L309). This is where the sample physically *is*.
- Autofocus object distances — `curvature_object_distances()` at [tas_runtime.py:482](instruments/tas_runtime.py#L482) reads `self.L1..L4`. This is what the mono focuses *onto*.

From the **descriptor** side:
- Diagnostic monitor positions — [in12/plugin.py:226](instruments/in12/plugin.py#L226): `MonitorSpec("Sample EMonitor @ Sample", ..., (0.0, 0.0, _L2 - 0.01), "sample_arm")`, and its PSD and divergence siblings at `_L2 - 0.03` and `_L2 - 0.02`.

Look at those offsets — 1, 2, 3 cm. Those monitors are *conceptually defined relative to the sample*: "just upstream of where the beam hits the crystal". But they're expressed as a copy of the sample's distance minus a small number, rather than as a relationship to the sample itself. That's the whole bug in one line.

**The failure mode.** A scientist corrects IN12's `_L2` from 1.80 to 1.90 m. This is not hypothetical maintenance — `MODEL_STATUS.md` documents IN12's L3 as *"genuinely variable"*, ILL gives it as "about 1.3 m" against a public Takin preset's 1.46 m, and the 2016 upgrade paper is what fixed L1 = L2 for Rowland focusing in the first place. These numbers are exactly the kind that get revised.

Result: the sample energy monitor moves to 1.89 m. The sample stays at 1.80 m. The monochromator still focuses onto 1.80 m. The monitor is still *before* the sample in component order, so McStas builds and runs without a murmur — but it now sits 9 cm **downstream** of the sample, measuring the incident-beam spectrum at a point past where the scattering already happened. Silently wrong diagnostics, no error, no warning, and the review that accepted the arm-length correction had no reason to think about monitors at all.

**And the test that should catch it doesn't.** [test_in12_plugin.py:144](tests/test_in12_plugin.py#L144) is named `test_default_state_matches_descriptor_geometry`. It asserts `(state.L1, state.L2, state.L3, state.L4) == (1.80, 1.80, 1.30, 0.72)` — against a *third* set of fresh literals. It never touches the descriptor. Under the correction above it fails, but for the wrong reason and pointing at the wrong file; and if someone had updated both the model and the test without the descriptor, it would pass green while the two authorities disagreed. A test named for parity that cannot observe parity.

**Now, the part your remark speaks to directly.** You're right that TAS instruments share fundamentally the same geometry, and I want to be precise about what "same" means here, because it decides the answer:

- The **structure** is shared and already correctly factored. There are always four arms; `TAS_Instrument` owns the `L1..L4` attributes; `curvature_object_distances()` consumes them generically; PANDA's virtual-source split and PUMA's parallel-beam plane are *overrides of that one method*, not different arm lengths. That genericity is real and this finding doesn't threaten it.
- The **values** are irreducibly per-instrument — 1.80 on IN12 is not 2.30 on PUMA — so there is no shared constant to hoist. The duplication is *within* each package, not across them.

So the question isn't "can we share this across instruments" (the structure already is), it's **which layer inside a package owns its four numbers**. Three candidates:

**(a) The descriptor owns them; the model seeds from it.** The descriptor is the declarative instrument definition — it's where the sourcing comments live (`"H144 guide exit (virtual source)"`, `"ILL-current value"`), and it's the surface a scientist reviews. The model constructor reads those values into its mutable state. Natural direction.

**(b) The model owns them; the descriptor imports from the model.** Wrong direction, and structurally blocked: `model.py` imports `mcstasscript`, which is heavy, and the registry's lazy-listing guarantee requires the plugin to stay import-light. That's precisely why every plugin imports its model *inside functions* today ([puma/plugin.py:331](instruments/puma/plugin.py#L331) and friends). Making the descriptor depend on the model at module level would drag McStasScript into listing every instrument. Ruled out on mechanism, not taste.

**(c) A tiny package-owned constants module both read** — `instruments/<pkg>/geometry.py`, stdlib-free, no imports at all. The plugin imports it (stays light), the model imports it (already heavy, costs nothing), zero cycle risk in either direction. It's essentially (a) with the constants lifted out of the plugin so the dependency arrow never has to point *at* the plugin.

**My recommendation is (c)**, as (a)'s intent with (b)'s constraint respected. One file per package, four lines, sourcing comments move with them.

One thing to note either way: the model's `L1..L4` must stay **mutable runtime state** — they're seeded from the constant, not aliased to it — because L3 in particular is an adjustable arm, not a fixed one. Binding them to one authority means one *initialisation* authority, not freezing the geometry.

And the parity test gets rewritten to actually compare state against descriptor, parametrised over the registry so all four instruments are covered by one check rather than IN12 alone.

**Scope if you approve:** four `geometry.py` files, four constructors seeding from them, four descriptor modules importing them, one real parametrised parity test. Unchanged: PANDA's virtual-source offset, PUMA's parallel-beam override, analytic-resolution spatial defaults (explicitly outside this finding). T1 — mechanical once the shape is settled, and the parity test is the thing that makes it stick.

## Revised queue

| # | Slice | Tier | Blocked on |
|---|---|---|---|
| 1 | Non-finite curvature rejected (#6) | T1 | — |
| 2 | Module values validated against descriptor (#1) | T1 | — |
| 3 | Batched radius PATCH (#3) | T1 | — |
| 4 | Lone command 2 previews correctly (#4) | T1 | — |
| 5 | Manifest version bumps + delete inert factors (#5, #7) | T1 | — |
| 6 | Sample contract: delete the extension promise (#8) | T1 | — |
| 7 | Zero take-off returns flat (#2) | T2 | — |
| 8 | One geometry authority per package (#9) | T1 | your answer above |

Eight slices, nothing left deferred, and no `/dialogue` needed — you answered both design questions in a paragraph, which is rather the point of asking you instead of guessing. Every slice deletes its ledger entry as it lands; when the ledger is empty the file and its `WIP.md` pin go with it.

Say go and I'll start at the top. Slices 1–6 need nothing further from you; 7 is ready to write; 8 waits only on your pick between (a) and (c).

## User

#9 is a weird question for me because I wrote model.py for PUMA, that is the original file I made at the heart of TAVI, so it's strange to see how AI agents built out, around it, and basically deprecated it. That's fine, but (c) is then better: one clear spot where we put the constants, avoiding any import issues.

## Assistant

Recorded: **(c)** — one `instruments/<pkg>/geometry.py` per package, no imports, both layers read it.

On the odd feeling: I'd push back gently on "deprecated." What happened to `model.py` wasn't deprecation, it was a split along a seam that only became visible once there were four instruments. The generic half — angle state, snapshots, feasibility, the curvature producer — became `tas_runtime.py` and is now what *every* instrument runs on, including PUMA. The PUMA-specific half — the component tree, the NMO optics, the parallel-beam focusing override that no other instrument has — stayed exactly where you put it, and it's still the thing that builds PUMA. The file didn't get replaced; the part of it that was secretly general got promoted. That's usually the compliment a first implementation gets.

Worth being clear-eyed about it for #9's sake though: pulling `L1..L4` out into `geometry.py` is one more piece leaving `model.py`, and it's a piece you wrote as literals with the physical meaning in the comment. Those comments move with the numbers, not away from them — the sourcing note is the valuable half.

Starting slice 1 now: **T1** — non-finite curvature rejected at the shared command checker. One reversible commit, one file's guard plus a promoted test, no risk trigger (it's a correctness guard on a local single-user API, not a trust boundary). Loading the tier skill.

**T1 slice 1 — quick plan.** Researched; no risk trigger (see below). Ending the turn here for your yes before any edit.

**The change.** One guard at the top of `curvature_command_error()` ([tas_runtime.py:65](instruments/tas_runtime.py#L65)):

```python
if not math.isfinite(magnitude):
    return f"{axis}{where}: commanded radius must be a finite number, not {magnitude!r}."
```

That's the whole fix. Three call sites consult this function and all three inherit it:
- [TAVI_PySide6.py:2818](TAVI_PySide6.py#L2818) — API launch (the reproducer's path)
- [TAVI_PySide6.py:4165](TAVI_PySide6.py#L4165) — GUI held-radius refusal
- [tas_runtime.py:145](instruments/tas_runtime.py#L145) — scan-range endpoints

So "covering both paths" needs no second edit; the shared checker already *is* the boundary. That's the root-cause fix rather than a guard per caller.

**Why NaN escapes today.** The driven branch is three magnitude comparisons and every one is false against NaN: `value == 0.0` no, `value < min_m` no, `value > max_m` no → returns `None` = accepted. Worth noting the fixed-axis branch already refuses it by accident (`value != fixed` is true for NaN), and `inf` is already refused *when* `max_radius_m` is set — so the hole is specifically a driven axis, and for `inf` a driven axis with no declared maximum. The `isfinite` guard closes both uniformly.

**Issues named.**

1. **Error code.** I'll reuse the existing `curvature_out_of_travel` rather than mint a new one. A NaN isn't literally "out of travel", so the code reads slightly off — but a new code is an API surface addition, and the ledger's remedy boundary says no schema change. Message clarity over code taxonomy. Flagging it because it's a small wart I'm choosing deliberately.
2. **`p_float` is not being touched.** [TAVI_PySide6.py:6784](TAVI_PySide6.py#L6784) will still parse `"nan"` into a float for *every* numeric field — `mtt`, `Ki`, `source_dE` and the rest. That's a wider hole the audit explicitly did not claim and did not verify. Fixing it here would be scope creep into 30-odd fields with unknown downstream behaviour. Named, not fixed, and I'd suggest it earns its own ledger entry rather than riding along.
3. **Doc line.** §5 *Crystal curvature* in `docs/API_USER_GUIDE.md` documents the refusal messages verbatim ([line 866](docs/API_USER_GUIDE.md#L866)), and the guide already requires "finite" of background scales, so the vocabulary exists. One sentence lands with the code, not after it.

**Tests — deliberately lighter than the reproducer.** The repro builds four real offscreen controllers and costs ~3.3 s to prove a defect that lives in a pure function. Promoting it verbatim buys near-nothing per second spent. Instead:
- Unit cases in the existing [tests/test_curvature_command_refusal.py](tests/test_curvature_command_refusal.py) — `nan`, `inf`, `-inf`, on a driven axis with and without a declared maximum, plus a fixed axis. Microseconds.
- One API-level test on a single instrument asserting `build_api_launch_state({"rhm": "nan", ...})` raises `ApiError` 400 — proving the checker is actually *reached* from the launch path, which the unit tests can't.

That's the real failure plus the real wiring, without paying four times for the same assertion. The original reproducer is deleted with its ledger entry, as the ledger's own rule says.

**Done-criteria:** both new tests shown red with the guard reverted; `pytest tests -q -ra` serial, green, ~100 s; entry 6 struck from `docs/audits/new-instruments-crystal-bending.md`; `WIP.md` count adjusted 9 → 8.

**Risk trigger: none.** Not a trust boundary (a correctness guard on a localhost single-user API; auth is untouched), no data/schema/migration, nothing destructive, no release. The nearest call is "public contract" — behaviour at the API does change from accept to 400 — but accepting NaN was never promised, the refusal category and its error code already exist and are documented, and the guide edit ships in the same commit. T1 stands.

**Goals check:** there's no `DESIGN_GOALS.md` body yet (still pinned on you in `WIP.md`), so there's no stated goal to check this against. `WIP.md`'s ledger entry is the governing item and this is slice 1 of emptying it.

Say go and I'll send the plan to the Codex critic seat, then execute.

T2 taken. Before discovery goes anywhere: a bare `/t2` after that plan has three plausible readings, and they lead to very different work, so I'm not going to guess.

Most likely, I think, is that you read my own "the nearest call is *public contract*" line and decided that *is* the trigger. If so you're right and my T1 verdict was the wrong side of a close call — an API going from accept to 400 is a contract change whether or not the old behaviour was ever promised.

But `/t2` could equally mean "stop pushing eight commits at `main`, branch the whole harvest." Those are different-sized jobs, so:

Three themed branches it is. Branch (i) first: **API/GUI input and preview correctness** — slices 1, 2, 3, 4.

T2 step 1 is read-only discovery, so no worktree and no edits this turn. Finishing the reading on slice 4, which is the one I'd looked at least closely.

Discovery done, read-only — no worktree opened, no edits, no mutating commands this turn. Ending here per the tier's step 1 so you can correct the assumptions before I open a branch.

## Branch (i) — API/GUI input and preview correctness · slices 1–4

**One material discovery that changes slice 4.** The lone-command-2 swap isn't missing from one place — it already exists **twice**, written out identically with the same explanatory comment, at [TAVI_PySide6.py:7224](TAVI_PySide6.py#L7224) (shared scan expansion) and [TAVI_PySide6.py:8215](TAVI_PySide6.py#L8215) (execution). The preview is simply the third caller that never got a copy. So the fix isn't "add the rule to preview", it's "extract the rule that's already duplicated, call it three times" — which removes an existing duplication rather than creating a third one. That's a better slice than the one I described to you earlier.

**Confirmed mechanisms, all four:**

1. **Non-finite curvature** — single `math.isfinite` guard in `curvature_command_error()`; three call sites inherit it ([2818](TAVI_PySide6.py#L2818) API launch, [4165](TAVI_PySide6.py#L4165) GUI refusal, [tas_runtime.py:145](instruments/tas_runtime.py#L145) scan endpoints). Fixed axes already refuse NaN by accident; the hole is a driven axis, and for `inf` a driven axis with no declared maximum.
2. **Module values** — replace `p_dict` with a descriptor-driven parser in `_api_field_map`. Both `apply_parameters` and `build_api_launch_state` read that one map, so one edit covers both. `ModuleKind.CHOICE` → value ∈ `spec.options`, `TOGGLE` → bool.
3. **Batched radius PATCH** — move `unlock_ideal_bending(key)` from the after-handler into the setter. Setters all run before any after-handler, and `update_ideal_bending_buttons` is a bound method so the existing `after not in after_handlers` dedupe collapses four refreshes into one at the end.
4. **Lone command 2** — extract the swap helper, call it in `_update_scan_estimates` before `_determine_scan_mode`, the `count1`/`count2` parse, the >1000-point deferred branch, and `_count_valid_scan_points`.

## Assumptions I need you to confirm or knock down

**A. The risk trigger is "public contract", and it fires for slices 1 and 2 only.** Both change API accept→400. Slices 3 and 4 fix wrong answers without changing any accepted input. Per the tier that adds a **plan-verifier** pass before approval and a **verifier** pass after slices 1–2 land — not instead of the ordinary seats, on top of them.

**B. I intend to run the security-reviewer seat, and I think it's mostly theatre here.** The tier lists "validation or hardening" as a security trigger, and slices 1–2 are literally input validation, so the rule reads as firing. Against that: this is a localhost single-user API with an optional bearer token, and the floor's own User Scope section says prioritise usefulness over adversarial hardening. It's a cheap read-only pass so I'll run it narrowly scoped rather than argue myself out of a rule — but say the word and I'll skip it and record the skip.

**C. Three things stay out of scope and I want them visibly declined, not silently dropped:**
- `p_float` will still accept `"nan"` for ~30 other numeric API fields (`mtt`, `Ki`, `source_dE`, …). Wider than anything the audit verified; I think it earns its own ledger entry rather than riding along here.
- `_count_valid_scan_points` ignores relative-mode entirely — it builds absolute scan points from `vals`, so a *relative* scan's validity preview is already approximate, independent of the command-2 bug. The audit didn't claim it and I'm not fixing it in this branch, but you should know it's there.
- `set_module_values` uses `QComboBox.setCurrentText`, which silently no-ops on an unmatched string. Slice 2 makes that unreachable from the API; the dock itself stays untouched.

**D. Test weight.** The six reproducers are heavy (each builds up to four real offscreen controllers, 1.5–3.3 s). I'll promote each defect to the cheapest layer that actually observes it — unit tests at `curvature_command_error` and the module parser, one API-level test per slice proving the boundary is reached, real offscreen widgets only where the finding *is* a widget finding (slices 3 and 4, which genuinely are). Current suite is 1104 tests / ~100 s and I don't intend to move that number much.

**E. Goals.** Still no `DESIGN_GOALS.md` body — nothing to check against, `WIP.md`'s ledger entry is the governing item.

## First reversible slice

Slice 1 as scoped above: the `isfinite` guard, its unit + API tests shown red with the guard reverted, the one-sentence addition to §5 of `docs/API_USER_GUIDE.md`, and entry 6 struck from the ledger. Self-contained, revertible alone, and it's the cheapest way to confirm the branch's shape is right before the other three land on top.

Confirm A–E (or correct them) and I'll open the worktree, write the branch plan, and put it through the critic, the five-model panel, the security seat and the plan-verifier before bringing it back to you for the gate.

## User

I don't think there are any security risks here, so we don't need a verifier there. Confirm the rest, go ahead. Start your work (plan->execution) and only stop if there's a blocker; don't feel like you're bothering me if you have genuine physics or design questions though, I'm happy to answer.

## Assistant

Confirmed: A, C, D, E as stated; **B dropped** — no security-reviewer, no security seat. Recording that as your call: this is correctness validation on a localhost single-user API, not a trust boundary.

Taking your "plan → execution, don't stop" as waiving the tier's plan-approval gate. I'll still run every seat and disposition their findings before the first edit; I just won't hand the plan back for a yes. Opening the worktree now.

Worktree open on `worktree-audit-input-preview`. Writing the plan packet, then firing every seat at once.

Panel is back: **4 yea, 1 nay** — and the nay (slice 3's ordering hazards) was **cut off mid-sentence**. That's exactly the seat whose argument matters most, so I'm re-asking it directly. Checking the Codex seat actually launched, too — `Start-Process` returning proves nothing.

Two members were truncated, not one — member 5's "one genuine risk I want to flag" is cut off too. Re-asking both.

Member 5's risk is a hypothesis about code it hasn't read; member 4 burned its budget on visible reasoning and its one checkable claim looks wrong. Both need verifying against source rather than adopting. Member 2 independently raised the same concrete check as member 4's unfinished point — sweep every caller of the radius setters. Doing that now.

Plan-verifier returned **REVISE** with three blockers, all of them real and all confirmed against source. Verifying the two remaining panel hypotheses before I disposition them.

Codex critique has landed. Reading it.

Codex critic: **NO OBJECTIONS** (real run — 110 KB log). Every panel hypothesis now verified against source. Folding the three plan-verifier blockers in.

Plan revised and recorded. Executing slice 1 — one executor, one writer in the tree.

Slice 1 landed: `50967e80`, reproducer red→green, six new tests shown red with the guard reverted, suite 1109 passed / 1 skipped (the expected dispersion-map skip). Reading the actual diff and running the review smoke.

Smoke: **CLEAN**, 0 actionable. Diff verified by eye — guard sits after `where` is built and before the fixed/driven split, exactly as specified. Pushing slice 1 and starting slice 2.

Slice 2 landed: `40966c7f`, both defects reproduced red first, 1137 passed / 1 skipped. It also surfaced a **new** finding: `slits_mm` has *both* holes — no value validation *and* no descriptor refill, so a partial `slits_mm` patch should KeyError at launch exactly like defect B did. Reading the diff and running the smoke.

Smoke: **CLEAN**. Diff verified — the refill mirrors collimation exactly, and `p_modules` returns only the supplied ids so the two refill paths stay consistent. Pushing and starting slice 3.

Slice 3 landed: `99bb8004`, all eight reproducer cases red→green, 1157 passed / 1 skipped. It also verified the panel's re-entrancy claim was wrong, as expected. Diff review and smoke.

Smoke: **CLEAN**. Diff is exactly the intended shape — 25 lines, unlock moved into a `set_bend` factory with the reasoning recorded in a comment. Pushing and starting the last slice.

No response requested.

## User

The window got accidentally closed, please continue.

## Assistant

Resumed. Before anything else — checking what state the interrupted slice 4 left the tree in.

Slice 4's executor got most of the way before the interruption — `TAVI_PySide6.py` modified, ledger entry 4 and its reproducer deleted, a new test file written, nothing committed. Reading what it actually produced before deciding whether to keep or redo it.

The interrupted executor had actually finished the writing — clean single-method extraction, both pre-existing inline copies replaced, preview normalised before every downstream consumer. What's missing is the evidence, and an agent's unreported "done" is not evidence. I'll run the red/green verification myself rather than take it on trust.

Fix reverted cleanly. Running the reproducer and the new tests against the unfixed code.

Reproducer red, exactly as the ledger describes: label `0 × 3 = 0 points`, preview `(0, 0)` vs execution `(3, 0)`. Now the new tests against the same unfixed code.

All six red. Restoring the fix and re-running.

Green — and note the label is now `3 points (3 valid / 0 invalid)`, the one-dimensional form, with no dock edit. That confirms the dock takes its existing 1-D branch on its own. Re-deleting the reproducer and running the full suite.

The extraction broke nine existing tests — in precisely the file that covers one of the two call sites it replaced. Not behaviour-preserving. Looking at the actual failure.

That's the noisy vcvars hook the repo docs warn about — calling the env's python directly for clean output.

Found it, and it's a real design error in the extraction — not a test problem.

`test_curvature_relative_scan_travel.py` deliberately calls `validate_scan_launch_state` **unbound**, passing a minimal duck-typed stand-in as `self`, so the method can be tested GUI-free. Making the helper a `@staticmethod` on the controller meant that method now reaches for `self._normalize_scan_commands`, which the stand-in doesn't have. The extraction was placed on the wrong object. Checking where the repo keeps its scan-parsing helpers.

`tavi/utilities.py` is the repo's own home for scan-parsing helpers (`parse_scan_steps` lives there, and AGENTS.md assigns "scan parsing utilities" to `tavi/`). That's the right home — Qt-free, and it removes the `self` dependency that broke the duck-typed seam. Moving it there.

A native matplotlib crash in an unrelated plot test — an artifact of invoking `python.exe` directly without the env activation that sets up the DLL paths. The `micromamba run` form completed the whole suite earlier. Using that for the full run.

Green: **1163 passed, 1 skipped** — the expected dispersion-map skip, and the nine broken tests now pass, which is what proves the relocation fixed the seam. Committing.

Committed `4e74b341`; five ledger entries remain (2, 5, 7, 8, 9) exactly as planned. Running the slice smoke, pushing, and harvesting the plan-time external reader, which has had well over its 25 minutes.

All four slices are on the branch and pushed; slice 4's smoke is **CLEAN** too. Now the pre-PR whole-subsystem reviewer and the plan-time external reader.

The external reader's **P1 is already closed** — it reviewed the plan at the branch point, and slice 2 fixed exactly that (defect B, the modules refill), with the valid-partial-choice test it asks for. Independent convergence with the plan-verifier.

Its **P3 is a real gap I left open.** Ledger entry 6's remedy boundary said "reject non-finite commanded curvature at the shared validation **and application** boundaries" — slice 1 did only the validation half. `set_crystal_bending()` still takes `abs(value)`, passes NaN through the clamps, signs it and stores it, so a direct caller bypassing the submission gates still creates non-finite state. That's a few lines inside the slice's own boundary, so it gets fixed in scope rather than deferred.

The method's own docstring says it is "the backstop for ... any caller that reaches this setter directly without going through a submission gate" — so the reader's finding is the code's own stated contract going unmet. Adding the guard.

Heredoc refused by the worktree guard — using the file tools instead.

All twelve red without the guard. Restoring it and running the full suite.

Repair verified: 12 red without the guard, **1175 passed / 1 skipped** with it. Committing and pushing, then the pre-PR whole-subsystem reviewer.

Reviewer seat is out. While it runs, checking the main checkout's state for the eventual merge ask.

Main clean, merge-tree conflict-free. Checking whether the reviewer has produced output yet.

Reviewer still working (log growing, no verdict file yet). Preparing the PR body meanwhile.

Status while the pre-PR reviewer finishes — you came back to a closed window, so here's the full state.

## Where branch (i) stands

Five commits on `worktree-audit-input-preview`, all pushed. Main is clean at `7e089a09` and `merge-tree` shows the branch merges without conflict.

| | Commit | What |
|---|---|---|
| 1 | `50967e80` | Non-finite curvature radius refused (entry 6) |
| 2 | `40966c7f` | API module values validated against the descriptor (entry 1) |
| 3 | `99bb8004` | Batched radius PATCH no longer loses a value (entry 3) |
| 4 | `4e74b341` | Lone second scan command previews as the 1-D scan it runs (entry 4) |
| 5 | `4f13cf8c` | Non-finite refused at the *application* boundary too (repair) |

Suite: **1175 passed, 1 skipped**, 105 s — the skip being `test_dispersion_map`, expected in a fresh worktree. Baseline on main was 1104, so the branch adds 71 tests. Every slice had its reproducer run red first and its new tests shown red with the fix reverted. The ledger is down from nine entries to five (2, 5, 7, 8, 9 remain).

## What happened after the window closed

Slice 4's executor had finished writing before it died but never reported, so I ran the verification myself rather than trust unreported work. That was worth doing — **the full suite caught nine broken tests**. The executor had made the extracted helper a `@staticmethod` on `TAVIController`, and `test_curvature_relative_scan_travel.py` deliberately calls `validate_scan_launch_state` *unbound*, passing a duck-typed stand-in as `self`, so it can be tested GUI-free. A controller method breaks that seam. I moved the helper to `tavi/utilities.py` beside `parse_scan_steps` — which is also where your own `AGENTS.md` says scan-parsing helpers belong — and all nine cleared.

## Seats

- **Critic (Codex):** returned — NO OBJECTIONS.
- **Panel (5 models):** returned, 4 yea / 1 nay. Two members were truncated mid-argument; I re-asked both. The nay's one checkable claim (that the re-entrancy guard blocks sequential handlers) was **false** — the guard is per-call in a try/finally. Member 5's hypothesised instrument-resolution laxity was also false: the API exposes no instrument-selection field. Both recorded as REJECT-because. What the panel *did* earn was the setter-caller sweep, which two members reached independently.
- **Plan-verifier:** returned REVISE with three blockers, all real, all adopted — the partial-dict module contract (which turned out to hide a latent launch `KeyError`), a worktree test baseline that would have read a correct run as a deviation, and `WIP.md` being a main-only file I'd have wrongly touched on the branch.
- **External reader (ChatGPT, extra-high):** returned. Its P1 was already closed by slice 2. Its **P3 was a genuine gap I'd left**: entry 6's remedy named validation *and application* boundaries, and I'd done only validation. That's commit 5.
- **Per-slice smoke:** four runs, all CLEAN.
- **Pre-PR reviewer (Codex):** **pending** — running now.

## One new finding worth your attention

Slice 2's executor found that **`slits_mm` has both of the holes we just fixed for `modules`** — no value validation *and* no descriptor refill — while the PUMA plugin indexes `slits_mm['pbl']`, `['vbl_hgap']` and `['dbl_hgap']` directly. So a partial `slits_mm` patch should `KeyError` at launch exactly as `modules` did. Not fixed (out of scope), but it wants a ledger entry. `collimation` has the value-validation hole but not the refill one.

## Next, without stopping

Reviewer verdict → repairs if any → open the PR → external reader at the PR, waited for. Then the merge ask, which is yours — merging is never standing.

Two things I'd flag for when you're back properly: the `slits_mm` finding above, and that branch (ii) is the zero-take-off physics we discussed, which is ready to start once this merges.

Two findings. Neither gets adopted before I read the code it names.

Verified both. Dispositions:

**P1 — DEFER, with the ledger's own words.** The audit's entry 3 explicitly says its finding covers "legal driven axes, **distinct from the deferred module-fixed reporting mismatch**" — so the module-fixed case the reviewer describes was carved out by the audit itself as separate work. It's also pre-existing, not introduced: `_sync_curvature_fields`' non-driven branch has always synced unconditionally, regardless of lock state. And my slice-3 change strictly *improves* the driven case (an unlocked axis is now skipped where it used to be overwritten). It wants a new ledger entry, not a fix in this branch.

**P2 — FIX, in scope.** This one is real and it makes the branch's own claim false on one path. `p_float` is `float(v)`, so a PATCH of `{"rhm": "nan"}` writes NaN straight into the widget; `compute_resolution` then reads GUI values into a config by direct assignment, never touching `curvature_command_error`. Launch refuses it and PATCH accepts it — exactly the GUI/API inconsistency entry 6's remedy names. The narrow fix is a finite check on the four radius fields' parser, which does *not* drag in the other ~30 numeric fields.

That reroutes launch's NaN refusal to the earlier parse boundary, which will change the error code the slice-1 test pinned. Running to see exactly what moves.

One test, exactly as expected. Updating it and adding the PATCH-path case the reviewer actually found.

36 passed. Showing the new PATCH tests red without the parser change.

1178 passed / 1 skipped. Committing the repair.

Six commits, pushed, repair smoke **CLEAN**. Updating the PR body and opening the PR.

PR **#33** is open. Sending the external reader at it — this seat is never skipped on a Claude host, and it's waited for.

PR **#33** is open and the external reader is out on it. Timer armed; I'll harvest in ten-minute waits (extra-high runs 15–25 minutes).

**https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/33**

## What changed since my last report

The pre-PR reviewer returned two findings. I verified both against source before dispositioning, and they split:

**P1 — deferred, on the audit's own authority.** The reviewer flagged that a mixed PATCH naming a crystal, a module *and* a radius can still end with the radius overwritten. True, but: `_sync_curvature_fields`' non-driven branch has always synced a module-fixed axis unconditionally, so it's pre-existing; my slice-3 change strictly *improves* the driven case; and the ledger's own entry 3 explicitly scopes itself to "legal driven axes, **distinct from the deferred module-fixed reporting mismatch**." The audit carved this out itself. It wants a new entry, not a fix here.

**P2 — fixed, commit `dc06e1ff`.** This one was real and made the branch's own claim false. The radius fields parsed through a bare `float()`, so a PATCH of `{"rhm": "nan"}` wrote NaN into the widget, and `compute_resolution` (behind `GET /resolution`) picks GUI values up by direct assignment without ever crossing the command checker — while commit 5's backstop can only refuse a non-finite it's *handed*, not undo one already sitting in the field. Launch refused it; PATCH accepted it.

The four radius fields now require a finite value at parse time. A side effect worth naming: launch now refuses a non-finite radius as `invalid_parameters` rather than `curvature_out_of_travel`. That's earlier, more precise, and it happens to deliver exactly the discrimination the external reader argued for in its plan review — "your number is invalid" vs "this radius conflicts with the hardware's travel" — without minting a new error code. Documented in `API_USER_GUIDE.md` §5 in the same commit.

## Branch state

Six commits, all pushed. Suite **1178 passed / 1 skipped** (the expected worktree dispersion-map skip); baseline on main was 1104, so +74 tests. Ledger down to five entries. Main clean, merge-tree conflict-free.

| Seat | |
|---|---|
| Critic (Codex) | returned — no objections |
| Panel (5 models) | returned — 4 yea / 1 nay; both truncated members re-asked, two claims refuted against source |
| Plan-verifier | returned REVISE — 3 blockers, all adopted |
| Per-slice smoke | 6 runs, all CLEAN |
| Pre-PR reviewer (Codex) | returned — 1 fixed, 1 deferred with rationale |
| External reader (ChatGPT) | **pending** on PR #33 |

## Two things for your queue

**A new ledger entry is owed** covering `slits_mm` (both the value-validation and refill holes — a partial `slits_mm` patch should `KeyError` at launch exactly as `modules` did) and the module-fixed reporting mismatch the reviewer re-found. I'll draft it at closeout unless you'd rather it wait.

**Merging is yours** — never standing. I'll bring you the merge ask once the reader returns.

Still working. Re-arming; I won't touch the branch while the reader is reviewing that head.

External reader still running at the 10-minute mark — normal for extra-high, which typically lands at 15–25 minutes. Second wait armed to 17:47.

Nothing else is in flight, and I'm deliberately not touching the branch while the reader is reviewing that exact head — a moved head would invalidate its review. So this is a genuine quiet hold rather than work I could be parallelising.

State is unchanged from my last report: PR [#33](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/33), six commits, 1178 passed / 1 skipped, ledger down to five entries, main clean and merging without conflict. Every seat has returned except this one.

I'll harvest again when the timer fires and bring you the merge ask — with the reader's findings dispositioned — as soon as it's back.

Reader's back: **no P0/P1**, one P2 and two P3s, and it confirms both of its earlier findings genuinely close. Verifying each before I act.

All confirmed. `float("nan")` passes the validator's `except ValueError` (it converts fine), then `parse_scan_steps` raises `ValueError`/`OverflowError` uncaught. Checking the two remaining sites.

Both confirmed, and `p_bool` is as described — `isinstance(v, int)` → `bool(v)`, so `2` becomes `True`.

Dispositions: **#1 FIX**, **#2 FIX**, **#3 REJECT-because** (that leniency is `p_bool`'s existing contract for *every* boolean field in the API — `diagnostic_mode` included — so tightening only TOGGLE would create a fresh inconsistency; tightening API-wide is its own decision). I'll pin the leniency with a test so it's deliberate rather than accidental.

45 passed. Red check on the two actual fixes (the `p_bool` test is a pin, so it passes either way by design).

8 red without the fixes, **1187 passed / 1 skipped** with them. Committing.

Smoke came back **INCOMPLETE** — a verifier timeout, which per house rules means I triage its two unverified candidates by hand rather than trust or ignore them.

Both candidates rejected, with evidence:

- **`float(vals.get(axis, 0.0))` cannot raise on text.** `get_gui_values()` already does `float(edit.text() or 0)` for all four radii inside its own `try`, so `vals['rhm']` is *always* a float by the time my check sees it. Non-numeric text fails there, and `compute_resolution`'s existing `if not vals: raise ApiError(400)` catches that before my line.
- **The `ValueError` catch preceding the finite check is the intended ordering.** Unparseable text and parseable-but-non-finite are different problems; they get different messages deliberately.

Updating the PR with the moved head.

Every seat has returned. Round report and merge ask.

# Branch (i) — ready to merge

**PR [#33](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/33)** · `worktree-audit-input-preview` → `main` · 7 commits · head `8ceff839`

**`main: clean`** — working tree empty, HEAD `7e089a09`, `merge-tree` returns a bare tree SHA (no conflict). Merging is yours; it's never standing.

## What this does

Harvests four of the nine audit ledger entries — the input-validation and scan-preview ones. The ledger drops from nine entries to five (2, 5, 7, 8, 9 remain).

| | Commit | |
|---|---|---|
| 1 | `50967e80` | Non-finite commanded radius refused (entry 6) |
| 2 | `40966c7f` | API module values validated against the descriptor (entry 1) |
| 3 | `99bb8004` | Batched radius PATCH no longer loses a value (entry 3) |
| 4 | `4e74b341` | Lone second scan command previews as the 1-D scan it runs (entry 4) |
| 5 | `4f13cf8c` | …refused at the *application* boundary too (external-reader repair) |
| 6 | `dc06e1ff` | …refused at *parse* time, so PATCH matches launch (pre-PR-reviewer repair) |
| 7 | `8ceff839` | …refused in scan bounds and typed GUI radii (external-reader repairs) |

Commits 1, 5, 6 and 7 are one invariant chased to four genuinely separate boundaries — the API parser, scan-command validation, the shared command checker, and the application setter. Each one was found by a *different* seat after the previous had declared victory, which is the honest summary of why the branch is seven commits and not four.

**Suite: 1187 passed, 1 skipped**, 110 s. The skip is `test_dispersion_map` — expected in a fresh worktree (gitignored `Pb_dft_phonons.dat`). Main's baseline was 1104, so +83 tests. Every slice had its reproducer red first and its new tests red with the fix reverted.

## Seats

| Seat | Outcome |
|---|---|
| Critic (Codex) | returned — no objections |
| Panel (5 models) | returned — 4 yea / 1 nay; both truncated members re-asked; two claims refuted against source |
| Plan-verifier | returned REVISE — 3 blockers, all adopted |
| Per-commit smoke | 7 runs — 6 CLEAN, 1 INCOMPLETE (verifier timeout) triaged by hand, both candidates rejected with evidence |
| Pre-PR reviewer (Codex) | returned — 1 fixed, 1 deferred |
| External reader (ChatGPT, ×2) | returned — plan findings both closed; PR findings 1 fixed, 1 fixed, 1 rejected |

## Decisions this round

- **Reader P2 (non-finite scan bound → 500) — fixed.** It also proved commit 1's coverage claim was false for exactly the cases that matter, so the claim and the code now agree.
- **Reader P3 (typed GUI `nan` reaching the resolution config) — fixed** at `compute_resolution`, in the refusal vocabulary it already had. The GUI fields stay unrestricted: this codebase tolerates junk in fields and refuses at gates, and a widget validator would fight the live refresh.
- **Reader P3 (`p_bool` accepts any int) — rejected, behaviour pinned.** That leniency is `p_bool`'s contract for every boolean in the API. Tightening only TOGGLE swaps one inconsistency for another; tightening API-wide is your call, not a side effect of this branch.
- **Codex P1 (module-fixed axis overwrite) — deferred.** Pre-existing, and the ledger's own entry 3 explicitly carved it out as "the deferred module-fixed reporting mismatch."

## Open, repeated in full

**1. A new ledger entry is owed**, covering two things found *during* this branch and deliberately not fixed:
- `slits_mm` has both holes commit 2 fixed for `modules` — no value validation *and* no descriptor refill — while the PUMA plugin indexes `slits_mm['pbl']`, `['vbl_hgap']`, `['dbl_hgap']` directly, so a partial `slits_mm` patch should `KeyError` at launch.
- The module-fixed reporting mismatch above.
- (`collimation` has the value-validation hole but not the refill one; `p_float` still accepts `"nan"` for ~30 other numeric fields.)

I'll draft it at closeout unless you want it sooner.

**2. Branch (ii) is ready to start once this merges** — zero take-off returns flat, on both axes, with the `set_crystal_bending` guard changed so a legal zero take-off stores flat instead of leaving the previous point's radius. Your ruling, recorded.

**3. `WIP.md`'s count 9 → 5** lands on `main` at closeout, after your merge — it's a main-only file and was deliberately untouched on the branch.

Merge when you're ready and I'll close out.

## User

Merge it then and continue.

## Assistant

Merging. Checking how this repo has merged PRs before so I match its history style rather than impose one.

Repo convention is merge commits preserving individual commits — matching that.

Merged as `c99b67a9`. Closing out.

The tool sees seven unmerged commits because the *local* main hasn't pulled the merge yet. Fetching first so removal is provably safe.

Main is at `c99b67a9` and `--merged main` lists the branch, so all seven commits are reachable. Safe to remove.

Git has deregistered the worktree but the directory lingers and the shell keeps snapping back to it. Clearing it and the merged branch.

Branch deleted locally and on the remote; worktree deregistered. The directory itself is held open by the shell's cwd — moving the shell out and clearing it.

Directory is held open by the session's shell — harmless leftover bytes; git no longer knows about it and the branch is gone locally and remotely. Not worth fighting the shell over.

Now closeout. Before I write the new ledger entries, I want to verify the `slits_mm` claim myself rather than enter an unverified finding into a ledger whose whole authority is that its entries are real.

Structurally confirmed — only `collimation` and `modules` get refills, and all four plugins index slit keys directly. Reproducing it for real before I write it up.

Reproduced on all four instruments — `KeyError` at launch for a partial `slits_mm`. Now writing it up. Reading the ledger's entry format to match it.

Now the board — the main-only update I deliberately kept off the branch.

Two failures on `main` that were green in the worktree. That difference matters more than the failures themselves — investigating before anything else.

That's the direct-`python.exe` native crash again, not the real failure. Re-running under `micromamba run`, which is the only reliable form here.

Real failures now. Both are the same thing: `is_bending_locked('rhm')` is `True` on main where the tests expect it unlocked — and `_held_curvature_issues` only inspects *held* (unlocked) axes, so it returns `[]`.

Nothing I changed touches lock initialisation. My hypothesis is local persisted state: `config/parameters.json`, which `AGENTS.md` calls user/local runtime state, exists in the main checkout and not in a fresh worktree.

Confirmed: `config/parameters.json` is gitignored (absent in a fresh worktree, present here) and carries `"rhm_ideal_locked": true`. Proving the dependency by moving it aside.

Proven: both tests pass with `config/parameters.json` absent and fail with it present. Restoring your saved GUI state immediately.

Restored, with a backup kept at `%TEMP%\parameters.json.bak`. Reading the two tests to size the fix.

Both tests set the field text but never establish the *lock* state they depend on — the second even asserts `is_bending_locked("rhm") is False` as a precondition it never creates. Checking whether the repo already has an isolation mechanism before I pick a fix.

Root cause found, and it's broader than two tests: [TAVI_PySide6.py:5592](TAVI_PySide6.py#L5592) reads `config/parameters.json` by **relative path** at controller construction, so *every* test that builds a real controller silently inherits your last-saved GUI state. There's no conftest isolation for it.

I'll fix the immediate blocker properly (a test must establish its own preconditions) and log the systemic half, which is a bigger change that would need care around `test_parameters_persistence.py`.

**1188 passed, 0 failed, 0 skipped** on main with your real config in place. Adding the systemic half to the ledger, then committing closeout.

Branch (i) is merged and closed out. Round report.

# Closeout — branch (i) landed

`main` at **`2d6708c7`**, clean, pushed. PR [#33](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/33) merged as `c99b67a9`; worktree removed, branch deleted locally and on the remote.

**Suite on main: 1188 passed, 0 failed, 0 skipped**, 101 s — measured *with* your real `config/parameters.json` in place, which turned out to matter.

## What landed

Seven commits clearing ledger entries 1, 3, 4 and 6, plus two closeout commits. The four bugs: a non-finite curvature radius reaching McStas, unvalidated module options building inconsistent PUMA optics, a batched radius PATCH silently discarding one radius, and a lone second scan command previewing as zero points.

Four of the seven commits were one invariant — "a non-finite radius is refused" — chased to four genuinely separate boundaries, each found by a *different* seat after the previous had declared it done: the API parser, scan-command validation, the shared command checker, and the application setter. That's the honest shape of the work.

## The thing worth your attention

After merging I ran the suite on `main` and got **two failures that had been green in the worktree, from identical source**.

Cause: [TAVI_PySide6.py:5592](TAVI_PySide6.py#L5592) reads `config/parameters.json` by *relative* path during controller construction. That file is gitignored — so it exists on your machine and never in a fresh clone or worktree. Yours has `"rhm_ideal_locked": true`, and both tests asserted against the Ideal-lock state without ever establishing it (one even asserts `is_bending_locked("rhm") is False` as a precondition it never creates).

I proved it rather than guessed: moved your `parameters.json` aside → both pass; restored it → both fail. Same commit, same environment. Your file is restored (4595 bytes), with a backup at `%TEMP%\parameters.json.bak`.

The direction is what makes this a defect rather than a nuisance: **the unset machine is the one that passes**. A fresh-clone or CI run is the *weaker* evidence, and a real regression can hide behind saved state in either direction. Every test that builds a real controller inherits whatever GUI state you last saved.

I fixed the two tests (`b10bb84f`) and logged the systemic half as entry 12 — isolating `config/` for the test session needs care around `test_parameters_persistence.py`, which exercises that path deliberately, so it wants its own slice rather than a closeout drive-by.

## Ledger: 9 → 8

Four cleared, three opened, all recorded with honest verification status:

- **10 · P2** — a partial `slits_mm` patch raises `KeyError` at launch. `collimation` and (since #33) `modules` refill omitted ids from the descriptor; `slits_mm` is the container left out, and all four plugins index its keys directly. I wrote and ran a reproducer: fails on all four instruments.
- **11 · P3** — the module-fixed reporting mismatch. The original entry 3 named this as deferred and scoped itself away from it, so deleting entry 3 would have erased the only record. Carried forward marked **not independently reproduced** — traced only.
- **12 · P2** — the config-inheritance gap above.

## Next

Branch (ii) — entry 2, zero take-off returns flat — is ready to start, with your ruling recorded on the board so it survives this session: a zero crystal take-off is the legal direct-beam position, flat on **both** planes (the vertical law's limit is the tightest bend, which is nonsense for a beam that isn't scattering), and `set_crystal_bending`'s zero-take-off guard must store flat rather than leave the previous point's radius.

Your branch-(iii) rulings are recorded too — samples stay instrument-independent with the extension promise deleted and enforced in package validation, and one `geometry.py` per package.

Say the word and I'll open branch (ii).

## User

Go ahead, still in auto mode

## Assistant

Starting branch (ii). Discovery first — re-reading entry 2 and the code, since line numbers shifted with the merge.

Important discovery immediately: the reproducer **asserts the wrong acceptance** for your ruling. It expects `snapshot.error_flags` at A4=0 — i.e. "refused or skipped" — which was the audit's assumed remedy. Your ruling is that the point is legal and returns flat, so it must succeed with *no* error flags. The replacement test encodes your behaviour, not the audit's assumption.

Also worth pinning: A4 is the **analyser** two-theta here, so the singular crystal is the analyser — `rha`/`rva` go flat while `rhm`/`rvm` autofocus normally.

Key finding that shrinks the job: **I was wrong about the vertical axis.** I told you it would clamp to the tightest bend at zero take-off. It doesn't — `2·f·sin(0)` is exactly `0.0`, and `_clamp_curvature_magnitude` has an explicit exact-zero FLAT exemption, so vertical already yields flat. Only the horizontal branch actually divides by zero. Your ruling is unchanged; the fix is just smaller than I described.

Checking for other places that could go singular at zero take-off, and confirming the reproducer still fails.

Discovery complete. Only two singular sites exist in the curvature path — the division at `tas_runtime.py:526` and the applier's guard at `:449`. `neutron_conversions.py` already guards `!= 0`; the `reciprocal_space.py` divisions are lattice angles, unrelated. Feasibility needs **no** change: under your ruling the two sides agree by making the snapshot succeed, not by making feasibility refuse.

Opening the worktree.

Two nays, both substantive. Verifying their checkable claims against source before dispositioning — and reading the Codex critique.

All three checkable claims resolve against source:

- `compute_scan_snapshot` does `copy.deepcopy(state)` at line 1008 — the caller's state is never mutated, so the "operator's 5000 mm is gone" path is **refuted**.
- `magnitude = abs(value)` then `copysign(magnitude, sin_theta)` — the sign *always* comes from the branch, never the input. A negative HELD radius is already normalised today, by design, and the API guide documents magnitude-in/signed-out. The "silent sign flip" is **refuted**.
- `curvature_modes` is stamped per point into snapshot metadata, so a consumer can already tell "flat because autofocus at zero take-off" from "flat because commanded" from "fixed flat". The tagged-union refactor is **unnecessary** — the discriminator exists alongside the value.

Codex critic: **NO OBJECTIONS**.

The layering objection does stand, though. Checking whether it's speculative before deciding how far to take it.

No instrument overrides `optical_radii` today — two override `curvature_object_distances`, one `effective_curvature_axis`. So the "future override forgets" case is speculative, but the docstring *advertises* that method as the override point, so the contract argument holds regardless.

**Adopting the layering objection in modified form:** the authoritative rule goes in `ideal_curvature` (shared policy, correct layer), with a guard also in the default `optical_radii` so the shipped formula stays total. Two small guards, no refactor.

Executed: `9ad848c0`, **1197 passed / 1 skipped**, reproducer red first, 10 new tests red with the fix reverted. The executor also corrected my packet on a real point — PANDA's `rva` is a *fixed* axis, so only the driven `rha` goes flat; my packet had asked it to assert both. Reading the diff myself.

Diff is exactly as specified — and the flat magnitude survives the clamp via the exact-zero exemption, so no false "clamped" provenance is recorded either. Smoke and push.

Smoke **CLEAN**, branch pushed. Launching the pre-PR whole-subsystem reviewer.

Branch (ii) is built, pushed and up as a PR. Two seats still out.

## PR [#34](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/34) — a zero crystal take-off runs flat

One commit, `9ad848c0`, clearing ledger entry 2. **1197 passed, 1 skipped** (the expected fresh-worktree skip); baseline was 1187, so +10 tests. Reproducer red first, all 10 new tests red with the fix reverted.

**The fix, three parts at two layers:** the authoritative rule in `ideal_curvature` (shared policy), a guard in the default `optical_radii` so the shipped formula stays total, and the applier's zero-take-off guard changed from "leave the previous point's radius" to "store the magnitude" — because under your ruling a zero take-off is a *solved* state, so inheriting the neighbour's bend would have meant the producer saying flat while the applier emitted something else.

## Two corrections to things I told you earlier

**The vertical axis was never at risk.** I told you it would clamp to the tightest bend at zero take-off. It doesn't: `2·f·sin(0)` is exactly `0.0`, and `_clamp_curvature_magnitude` has an explicit exact-zero FLAT exemption, so it was already flat. Only the horizontal branch actually divided by zero. The guard still covers both axes deliberately — so the intent reads as "no take-off, no focusing" rather than resting on that coincidence — but the defect was half the size I described.

**PANDA's `rva` is a fixed axis.** My executor packet asked for a test asserting both `rha` and `rva` go flat; the executor caught that `rva` is `driven=False` on PANDA and PUMA, so it ignores take-off angle entirely by existing design. Only driven axes go flat. It adjusted the tests and said so rather than quietly dropping the assertion — the right call.

## Panel: 3 yea, 2 nay — one nay adopted, one refuted

The layering nay was right and I changed the design for it: a degenerate-geometry rule is *shared policy*, not instrument-specific optics, and `optical_radii` is the documented override point. Hence the two-layer split rather than the single guard I'd planned.

The rest didn't survive checking against source:
- "Storing a positive sign silently flips a negative commanded radius" — the applier already does `abs(value)` and takes the sign only from the branch. Magnitude-in/signed-out is the documented contract.
- "The old guard protected a HELD radius from being clobbered across a scan" — `compute_scan_snapshot` deep-copies the state, so per-point application never touches your GUI fields.
- "Overloading `0.0` needs a tagged union before this lands" — `curvature_modes` is already stamped per point and discriminates the three meanings alongside the value.

Codex critic: no objections. Per-commit smoke: CLEAN.

## Outstanding

| Seat | |
|---|---|
| Critic, panel, smoke | returned |
| Pre-PR reviewer (Codex) | **pending** |
| External reader (ChatGPT) | **pending** on PR #34, timer armed |

One process note for the record: the external reader ran **once** on this branch, at the PR, rather than also at plan time — by the time the plan was settled there was already a pushed head worth pointing it at, which is the more useful target.

I'll disposition both when they land and bring you the merge ask. Merging stays yours.

Both seats converged **independently** on the same P1 — that's the strongest signal I've had all session. Verifying it and the reader's second finding.

**P1 #1 confirmed** — the `focusing_known` raise sits *before* my zero check, and IN12's Heusler `rva` is `driven=True, focusing_known=False` with A4 travel through zero. So the original accepted-then-unrunnable shape survives for a supported crystal. Fixing it: at zero take-off there is no focusing to model, so the *absence* of a focusing model is irrelevant — flat is fixed by geometry, not by the model.

Both confirmed precisely: `angle2k(0, d)` returns `0`, then `if ki <= 0 or kf <= 0: return None` discards the **whole** `(Ei, Ef)` pair — including the perfectly well-defined `Ei` from A1. Fixing #1 now.

`rva` now returns flat for IN12's Heusler instead of raising. Adding the regression test for it.

11 passed. Showing the new test red with the reorder reverted, then the full suite.

Fixed and pushed as `9c208274`; suite **1198 passed / 1 skipped**. Re-sending the external reader at the moved head, since a P1 repair warrants it.

I need a physics decision from you before branch (ii) can merge. Everything that doesn't depend on it is done.

## State: PR [#34](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/34), two commits

Both review seats independently found the same P1, which is the strongest signal I've had: **the zero-take-off rule was unreachable for the one axis that most needed it.** IN12's Heusler analyser declares `rva` as driven with `focusing_known=False` — no established focusing model, so `ideal_curvature` normally refuses to invent a radius — and its A4 travel includes zero. My check sat *after* that refusal, so at A4 = 0 with `rva` autofocusing, the point was still accepted and still unrunnable, just raising `ValueError` instead of `ZeroDivisionError`. The exact defect this branch exists to remove, alive for a supported crystal.

Fixed in `9c208274` by checking geometry first: at zero take-off there's no focusing to model, so having no model is irrelevant — flat is fixed by the geometry. Away from zero the refusal is untouched, and the test pins both directions so it can't quietly become "invent a radius anyway". Suite **1198 passed / 1 skipped**.

## The decision — what a direct-beam point should record

**What it is.** At A4 = 0 the analyser selects no energy. `angle2k(0, d)` returns `0`, and `nominal_energies_from_angles` guards with `if ki <= 0 or kf <= 0: return None` — so it discards the **entire** `(Ei, Ef)` pair, including `Ei`, which A1 determines perfectly well. With `_angle_energies` left `None`, `deltaE` falls back to the frozen launch value and `E0_param` falls back to `fixed_E` arithmetic.

**The concrete failure.** Run an A4 scan through zero with a Mono source and an A1 whose Bragg-selected `Ei` differs from `fixed_E`. The ±1° neighbours run at their angle-derived source energy; the zero point suddenly drives the McStas source from `fixed_E` and records an invented fixed-mode `(Ei, Ef)`. It looks like an ordinary scan datum and isn't.

**Why it's yours and why now.** Before this branch the point raised, so the fallback never executed — making the point runnable is what exposed it. That makes it *introduced* by this branch, so I won't defer it silently. And the question underneath is physics, not code: the external reviewer put it well — direct-beam counts are inherent in your ruling, but *this particular invented energy* is not.

**The crux I can't settle myself.** At A4 = 0 the analyser arm points straight through, so it transmits rather than diffracts. `Ei` is well-defined from A1. `Ef` is not selected by anything. So what should the point record?

- **(a) Record what's determined, omit what isn't** — keep `Ei` from A1, drive `E0_param` from it, leave `Ef` and `deltaE` unset for that point. Most honest, and it keeps the zero point's source energy continuous with its neighbours. Needs the energy helper to return a partial result and its consumers to tolerate a missing `Ef`. **My recommendation.**
- **(b) Treat the detector as seeing `Ei`** — i.e. `Ef = Ei`, `deltaE = 0`, on the reasoning that an unanalysed direct beam arrives at the incident energy. Defensible, and it keeps every field populated — but it asserts an `Ef` the instrument never selected.
- **(c) Leave the `fixed_E` fallback as it stands.** Cheapest, and wrong: the point runs at a different source energy from its neighbours for no physical reason.

Refusing or flagging the point is *not* on this list — that's the option your ruling already rejected.

**What it locks in:** how TAVI records a *partially determined* point. Any future degenerate geometry will hit the same seam, so whichever way you go becomes the pattern.

I've re-sent the external reader at the moved head to check my `focusing_known` reorder didn't introduce anything; that's running now. Nothing else is blocked — this decision is the only thing standing between branch (ii) and a merge ask.

The re-check came back clean, so every seat on branch (ii) has now returned.

## External reader at `9c208274`: no findings

P1 #1 **fully closed** — it verified the zero-take-off branch now wins for every requested driven axis before `focusing_known` is consulted, that non-zero take-off still reaches the unchanged refusal, and that fixed (`driven=False`) axes sit on the separate preceding branch and are unaffected. It also looked for a second production path that could reintroduce the refusal and found none: `compute_scan_snapshot` reaches autofocus only through `ideal_curvature`, and `set_crystal_bending` doesn't independently reject `focusing_known=False`.

No additional defect in the two commits beyond the acknowledged energy issue, which it left alone as asked.

| Seat | |
|---|---|
| Critic (Codex) | returned — no objections |
| Panel (5 models) | returned — 3 yea / 2 nay; one nay adopted (the layering split), the rest refuted against source |
| Per-commit smoke | returned — CLEAN |
| Pre-PR reviewer (Codex) | returned — 1 P1, fixed |
| External reader (ChatGPT, ×2) | returned — 2 P1s; one fixed and re-verified clean, one **pending your decision** |

## Still blocked on you, repeated in full

**What a direct-beam point should record when the analyser selects no energy.**

At A4 = 0 the analyser transmits rather than diffracts. `angle2k(0, d)` returns `0`, and `nominal_energies_from_angles` guards with `if ki <= 0 or kf <= 0: return None` — discarding the *whole* `(Ei, Ef)` pair, including the `Ei` that A1 determines perfectly well. `deltaE` then falls back to the frozen launch value and `E0_param` to `fixed_E` arithmetic.

Concretely: an A4 scan through zero with a Mono source and an A1 whose Bragg-selected `Ei` differs from `fixed_E` runs its ±1° neighbours at their angle-derived source energy, then runs the zero point from `fixed_E` and records an invented fixed-mode `(Ei, Ef)` that looks like an ordinary datum.

This is *introduced* by this branch — before it, the point raised and the fallback never executed — so I'm not deferring it silently.

- **(a) Record what's determined, omit what isn't** — `Ei` from A1 drives `E0_param`; `Ef` and `deltaE` left unset for that point. Honest, and keeps the source energy continuous across the scan. **My recommendation.**
- **(b) `Ef = Ei`, `deltaE = 0`** — an unanalysed direct beam arrives at the incident energy. Keeps every field populated, but asserts an `Ef` the instrument never selected.
- **(c) Leave the `fixed_E` fallback** — cheapest, and the zero point runs at a different source energy from its neighbours for no physical reason.

Refusing or flagging the point isn't on the list; that's what your ruling rejected.

Whichever you pick becomes the pattern for any future degenerate geometry, which is the part that makes it worth your minute rather than my guess.

Nothing else is outstanding — the branch is otherwise ready, and I'll take it to the merge ask as soon as you call this.

## User

(a) is good. Ok, merge then and continue on to slice 3 after.

## Assistant

(a) it is. That's a fix to land *before* merging — you picked a repair over "leave it", and I said this wouldn't be merged with the defect silently deferred. Implementing it first, then merging.

Reading the consumers before I design the partial result.

`build_point_params` is abstract and takes `deltaE`, so each instrument feeds it into real McStas parameters — a bare `None` there would break the run. That sharpens what (a) means in practice, and it's worth being precise about:

The defect the reviewer actually named is the **source energy** jumping to `fixed_E`. Driving `E0_param` from A1's `Ei` removes that discontinuity. The other dishonest half is the *metadata* asserting a fixed-mode `(Ei, Ef)` the instrument never selected. Both get fixed. The `deltaE` that flows into McStas keeps the frozen launch value — it's not determined by the instrument at A4 = 0 either way, and it's a declared input rather than a number invented from `fixed_E`.

The executor found a **real downstream break** and stopped rather than papering over it — exactly right. Verifying it myself, because it's the crux of whether this branch is safe.

Confirmed exactly: in angle mode `qx/qy/qz` are `None`, so it falls to `lab_q_from_stt(float(Ki), float(Kf), float(stt))` and `float(None)` raises. Checking what the callers do with the result.

`q0` doesn't only feed background — it feeds `resolution_config`, the per-point resolution kernel, and it's computed for **every** point in the deterministic engine. So this isn't a background-only edge case. Proving the break rather than asserting it.

Stopping before the merge. The situation changed materially after your decision, and merging on the old instruction would be wrong.

## (a) is right for *recording*, but it breaks a *computation*

I implemented it, and it works for what you chose: `Ei` from A1 drives `E0_param`, `Ef`/`Kf` recorded as `None` rather than invented. 1209 passed.

Then the executor traced a consumer I hadn't, and I've now proven it:

```
_background_q_magnitude({'qx': None, ..., 'Ki': 2.66, 'Kf': None, 'stt': 30.0})
  → TypeError: float() argument must be ... not 'NoneType'
```

In angle mode `qx/qy/qz` are `None` by construction, so that helper computes `|Q|` from `Ki`/`Kf`/`stt` — and `q0` doesn't only feed background, it feeds `resolution_config`, the **per-point resolution kernel**, computed for *every* point in the deterministic engine.

So as landed, (a) makes the deterministic engine raise `TypeError` on exactly the point your ruling says must run. That's strictly worse than before, and no test caught it because nothing exercises angle mode at zero take-off through that path.

I have **not pushed** it. Origin is at `9c208274` — curvature flat, `focusing_known` reorder, external reader clean. The energy commit `48a4da9e` is local only.

## Why I'm stopping rather than patching again

Three fixes on this branch, each exposing the next: curvature flat → `focusing_known` ordering → energy recording → now `|Q|` and the resolution kernel. Your own floor calls that the signal to stop and discuss rather than write a fourth patch. The underlying reason is real: making a previously-impossible point *possible* means every derived quantity needs an answer, and at a transmitting analyser several genuinely don't have one.

## Three ways forward

**A — Merge `9c208274` now, and open the energy question as its own ledger entry.** *(My recommendation.)* That commit closes ledger entry 2 exactly as written: the curvature divide-by-zero is gone, scans crossing zero run. The direct-beam point keeps its **pre-existing** `fixed_E` energy fallback — unchanged behaviour, not a regression, just not yet improved. The energy/`|Q|` convention becomes its own decision with its own evidence, rather than a cascade buried inside a curvature fix. One coherent change per branch.

**B — Finish (a) properly.** Teach `|Q|` and the resolution kernel to handle an undetermined `Kf`: the zero point then runs with no resolution kernel and no `|Q|`-keyed background. Honest, but it's real new machinery, and it produces a simulation datum with no resolution attached — which may be worse for a consumer than a clearly-labelled convention.

**C — Adopt an elastic convention for a transmitting analyser.** At A4 = 0 the analyser diffracts nothing and transmits, so the detector genuinely does see neutrons at the incident energy: `Ef = Ei`, `deltaE = 0`, `|Q| = 2·ki·sin(θs)`. Everything downstream works with no `None` anywhere. You rejected `Ef = Ei` as a *recording*, and I agreed — but as a stated *computational convention*, documented at the point of use, it has a physical story behind it rather than being an accident of `fixed_E` arithmetic.

**What I'd do:** A now, then C or B as a separate, properly-scoped slice once you've decided which story you want a direct-beam datum to tell. That also unblocks slice 3, which you asked me to move on to.

Say which and I'll act — including merging immediately if you want A.

## User

A sounds good, then pin B and C as bigger problems we'll have to cover in a fresh session.

## Assistant

A it is. Saving the unpushed energy work to the scratchpad before dropping it, so nothing is lost, then merging.

Merged as `cba504e4`. Pulling main and clearing the worktree.

Both commits are reachable from `main` (`--merged main` confirms it), so nothing is lost.

Cleanup done: main at `cba504e4`, only the main checkout registered, branch gone locally and on the remote, tree clean.

Now the closeout. Writing a reproducer that proves the defect that *remains* on main after option A, so entry 13 is a verified entry like the rest.

Reproduced — and it's worse than the reviewer described. The neighbours record `Ef = 23859 meV` at ±1°, because inverting Bragg near zero take-off diverges. So the problem is a *neighbourhood*, not a point:

```
A4=-1.0: E0_param=20.0000  Ei=20.0000  Ef=23859.5294
A4= 0.0: E0_param=14.6800  ← jumps to fixed_E
A4=+1.0: E0_param=20.0000  Ei=20.0000  Ef=23859.5294
```

That materially strengthens the case for pinning B/C as a design question rather than a patch.

Branch (ii) merged and closed out. Main at `d73e913b`, clean.

# Round report — branch (ii) done, B and C pinned

**PR [#34](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/34) merged** as `cba504e4`. Worktree removed, branch deleted locally and on the remote.

## What landed

Two commits clearing ledger entry 2. A zero crystal take-off now runs flat instead of raising, with the rule in `ideal_curvature` (shared policy) plus a guard in the default `optical_radii` so the shipped formula stays total — and checked *before* the `focusing_known` refusal, because at zero take-off there's no focusing to model. `set_crystal_bending` now stores a zero-take-off magnitude instead of leaving the previous point's radius.

Suite on the branch: 1198 passed / 1 skipped.

Both review seats independently found the same P1 — that my zero check sat behind the `focusing_known` refusal, so IN12's Heusler `rva` still hit the original accepted-then-unrunnable failure. Fixed, and the external reader re-verified it clean at the moved head with no new findings.

## What I did *not* merge, and why

Your choice (a) — record `Ei`, omit the undetermined `Ef` — was implemented, tested green at 1209, and then **withdrawn unpushed**. An absent `Ef` propagates into `_background_q_magnitude`, which needs a number for the per-point resolution kernel on *every* deterministic-engine point. I proved it:

```
_background_q_magnitude({... 'Ki': 2.66, 'Kf': None, 'stt': 30.0})
  → TypeError: float() argument must be ... not 'NoneType'
```

The honest recording would crash the engine on exactly the point your ruling says must run. So branch (ii) merged with the pre-existing `fixed_E` fallback intact — unchanged behaviour, not a regression, just not yet improved.

The parked work is saved as a patch in the session scratchpad; it's reconstructible from entry 13 regardless.

## Entry 13, pinned for a fresh session

Written up with a committed reproducer, plus a `## Direct-beam energy and |Q|` section on the board so it survives this session. The reproducer shows something worth your attention when you come back to it:

```
A4=-1.0: E0_param=20.0000  Ei=20.0000  Ef=23859.5294
A4= 0.0: E0_param=14.6800  ← jumps to fixed_E
A4=+1.0: E0_param=20.0000  Ei=20.0000  Ef=23859.5294
```

The neighbours are already recording `Ef = 23859 meV`, because inverting Bragg near zero take-off diverges. **The affected region is a neighbourhood of zero, not a point** — which neither of us knew when you picked (a), and which whichever convention you choose will have to cover.

Both candidates (B: omit and teach `|Q|` to cope; C: elastic convention for a transmitting analyser) are written into entry 13 with their tradeoffs.

## Ledger: 8 entries

Branch (iii) — package hygiene — is what's left as ordinary work: entries 5, 7, 8, 9, 10, 11, 12. Your rulings for it are recorded on the board (samples stay instrument-independent with the extension promise deleted and enforced in validation; one `geometry.py` per package).

I'll start branch (iii) next unless you want to redirect. Given it's seven entries of mostly-mechanical hygiene with two design rulings already made, I'd expect it to run more like branch (i) than branch (ii) — though I said something similar about this one.

## User

Continue with branch 3 then

## Assistant

Branch (iii): seven entries — 5, 7, 8, 9, 10, 11, 12. Discovery first, and this is exactly the shape the shared reader exists for rather than my reading a dozen files myself.

Backslash paths didn't resolve. Retrying with `workdir` and relative paths.

Reader isn't receiving the paths — two attempts, both "no paths supplied", so it's a client-side serialisation problem rather than something I can fix by rephrasing. Falling back to targeted reads; noting the seat as unavailable.

Entry 7 confirmed precisely: twelve assignments, three per instrument, and **nothing in live code reads any of them** — the only other mentions are the audit, a design-doc history note, and a transcript. Gathering the rest.

Important correction to my own earlier assumption, and to the ledger's remedy note: `test_parameters_persistence.py` builds a bare controller via `__new__` and exercises pure-Python helpers on in-memory dicts. Let me confirm it does no real file I/O, because that changes how safe entry 12's fix is.

Confirmed, and it corrects something I wrote into the ledger myself: `test_parameters_persistence.py` does **no real file I/O** — it uses `inspect.getsource()` to assert on source text plus in-memory dicts. So entry 12's remedy note ("preserve its deliberate exercise of the real read/write path") is wrong, and the fix is safer than I recorded. I'll correct that as part of the work.

There's also no existing seam: `"config/parameters.json"` is a bare literal at four sites, so this needs one.

Opening the worktree for branch (iii).

Council call failed on argument validation — same serialisation symptom as the reader, and both were my longest payloads. Retrying with a more compact question.

Same symptom: the second array argument is being dropped into the question. Both failures are large payloads, so testing whether it's size by going much shorter.

Not size — it's persistent, and earlier calls in this session worked. Running the diagnostic the tool docs prescribe, and reading the Codex critique.

LLMM itself is healthy — 19/27 serviceable, all five council seats mapped, budget rung 1. So this is argument marshalling on array-typed parameters between client and server, not the service. One minimal probe to confirm before I record the seat.

Arrays work — it's payload size. Retrying the real panel with the full question and terse lens labels.

Confirmed: total payload size, driven by the question length. Compressing hard.

Five attempts; the seat refuses any substantial payload while a minimal probe succeeds, so it's a client-side marshalling limit rather than the service. Recording the panel as **unavailable** and substituting a fresh critic subagent for the adversarial function.

Branch (iii) is planned and under review by two seats. Worth flagging one thing about your infrastructure before I go further.

## A bug in the personal-assistant MCP server

The `council` and `reader` tools are **refusing any substantial payload**. Both fail identically: a Pydantic validation error saying the array argument (`lenses` / `paths`) is missing, while the error's own `input_value` shows that array's text appended into the `question` field. So the two arguments are being merged during marshalling.

It's size-dependent, and the threshold is low. A minimal probe succeeded:

```
council(question="Probe: is the lenses array reaching the server?", lenses=["a","b","c","d","e"])
→ 5/5 members responded
```

…while the same call with a ~300-word question and five one-line lenses fails every time. Five attempts, three different question lengths. `list_models` confirms the service is healthy — 19/27 serviceable, all five council seats mapped, budget rung 1 — so this is client↔server argument marshalling, not LLMM.

Practical effect: **the panel is unusable for real questions**, which is exactly when it's worth calling. Worth a look when you next touch that server; I've recorded the seat as unavailable for this branch and substituted a fresh critic subagent covering the same five angles.

## Branch (iii) plan — seven slices

Worktree open on `worktree-audit-package-hygiene` from `d73e913b`. Order is code first, metadata last, so the version bump can describe what actually landed:

1. `slits_mm` refill — the third descriptor container, same shape as the two already fixed
2. Config-dir seam + conftest temp dir — stops tests inheriting your saved GUI state
3. Module-fixed reporting mismatch — **reproduce first**, stop if it doesn't
4. Delete twelve inert focusing factors
5. Delete the sample filter-or-extend promise, enforce the opposite in validation
6. One `geometry.py` per package
7. Bump the four manifests 1.0.0 → 1.0.1

Two discoveries that shrink the work:

**Entry 7 verified precisely** — twelve assignments, three per instrument, and nothing in live code reads any of them. The only other mentions are the audit, a design-doc history note, and a transcript. Also: `rvafac` doesn't exist; only three per instrument, so the ledger's "twelve" is right.

**Entry 12 is safer than I recorded, and I need to correct myself.** I wrote into the ledger that `test_parameters_persistence.py` "deliberately exercises the real read/write path" — taken from `AGENTS.md`'s contention warning without checking. It doesn't: it builds a bare controller via `__new__` and asserts on `inspect.getsource()` text and in-memory dicts. It never opens the file. I'll fix that remedy note in the same commit.

There's no existing seam for the config path — four bare `"config/parameters.json"` literals — so slice 2 creates one: an env var defaulting to today's behaviour, chosen because `conftest.py` already sets `MCSTAS` that way and imports neither PySide6 nor McStasScript, which patching a module constant would force.

I'll disposition both seats' findings and then execute. Nothing needs you right now.

That critique is worth more than the panel would have been — 22 objections, most verified against code, and **three of my plan's premises are simply wrong**. Checking the Codex seat, then revising.

Both seats verified. Every premise-breaking claim confirmed:

- **PUMA has a *third* geometry copy** — raw literals `2.150, 2.290, 0.880, 0.750` in its `Geometry(...)`, while the other three pass `_L1.._L4`. My plan said two copies.
- **`test_editable_number_format.py:67` pins the literal source text** `'open("config/parameters.json", "r", encoding="utf-8")'` — slice 2 breaks it.
- **A slit-defaults builder already exists inline** at `_default_parameter_values`; my "write a twin" would have made a fourth copy.

Codex added three more, including one I'd have walked straight into: `test_rva_gui_axis_policy.py` isolates its save/load by **changing cwd**, which an absolute config override bypasses — and slice 2's site list missed `:5436`, where save *creates* the config dir.

Plan revised with all 25 findings dispositioned. Before I start executing — this is the moment to tell you something rather than quietly carry on.

## My plan for branch (iii) had three wrong premises

The critic seat caught them, and I verified each in source:

1. **PUMA has three geometry copies, not two.** Its descriptor passes raw literals `2.150, 2.290, 0.880, 0.750` in `Geometry(...)`, entirely separate from its own `_L1.._L4`. IN8, IN12 and PANDA pass their constants through. A "one authority" commit built on my premise would have left PUMA with a fourth copy — the exact defect the slice exists to remove.
2. **The slit-defaults builder already exists**, inline in `_default_parameter_values`, including the tuple-vs-scalar shape the plugins depend on. My "write a twin of the collimation helper" would have added a fourth copy of that shape rather than removing duplication.
3. **The sample exact-equality assert is in four test files, not one.** So the parametrized check is a consolidation, not new coverage — which changes what it's for.

Codex added three more, including two I'd have walked into: my slice-2 site list missed `:5436`, where *save* creates the config directory, and `test_rva_gui_axis_policy.py` isolates its save/load by **changing cwd** — which an absolute config override silently bypasses.

And one methodological correction I'd have got wrong on principle: **"show the test red with the fix reverted" cannot apply to the sample and geometry parity checks**, because both invariants already hold. They're *preservation* checks. The right evidence is proving the new validator rejects a deliberately divergent descriptor, and establishing the parity test's sensitivity by perturbing a geometry value on purpose.

## What that tells me

Seven slices planned off one discovery pass was too thin. I'm not splitting the branch — the critic's structural worry was that slice 2's changed test baseline could mask a later slice's regression, and re-pinning the baseline at *every* slice fixes that directly, far cheaper than three more seat rounds. I've set a numeric split trigger (>400 changed lines outside tests) instead of deciding by feel mid-branch.

## Also worth your attention

Slice 2's acceptance now requires a run against a **deliberately hostile** `config/parameters.json` — with `"rhm_ideal_locked": true`, the flag that actually caused the failure. A green suite on a clean file proves nothing about isolation, which is the whole point of the slice. And `config/instrument_selection.json` is a second saved-state channel this slice does *not* close; I'll name it rather than silently widen scope.

Executing now, slice by slice, re-pinning the baseline at each. Nothing needs you until the merge ask.

## User

Is it actually working?

## Assistant

Fair question, and it deserves data rather than reassurance. Let me check rather than tell you.

Honest answer: **the fixes are working; the rate isn't good, and the ledger is barely shrinking.**

## What's actually delivered

Session start `7e089a09` → main now `d73e913b`. Tests **1104 → 1188** (+84). Two PRs merged, five audit entries cleared, every one with a reproducer run red before and green after — not "the agent said it passed".

The five real defects: NaN reaching McStas parameters; unvalidated module options building PUMA with an aperture and no mirror; a batched PATCH silently discarding a commanded radius on all four instruments; a scan previewing zero points while execution ran it; a zero take-off crashing autofocus.

The review seats have genuinely earned their cost. Not as ceremony — they caught:
- a helper I placed on the wrong object, breaking **nine existing tests** (found only by running the full suite, which the worktree wouldn't have shown)
- a P1 found **independently by two seats** — my zero-take-off rule sitting behind a refusal that made it unreachable for the one axis that needed it
- **three wrong premises** in the branch-(iii) plan an hour ago, including PUMA's third geometry copy

Left to me alone, all of those would have shipped.

## What isn't working

**The ledger went 9 → 8.** Five entries cleared, four opened. The new ones are real — `slits_mm` KeyError on all four instruments, the suite inheriting your saved GUI state, the direct-beam energy cascade — and they were invisible before. But if you were expecting a burn-down, it isn't one. Fixing things in this codebase keeps finding more things.

**Entry 13 beat us.** You chose (a), it cascaded into the resolution kernel, and it's parked. That's an honest loss, not a win dressed up.

**The ceremony-to-code ratio is poor.** Branch (ii) was about 45 lines of real change wrapped in a critic, a panel, a smoke, a reviewer and two external-reader rounds. Justified there — it was shared physics every scan point crosses. Not obviously justified for deleting twelve dead assignments.

**I've been wrong out loud several times** — the vertical-axis clamping, the persistence test, three plan premises. Corrected each time, but you're reading my claims and some were wrong.

**And branch (iii) has zero commits.** I said "executing now" and then the turn ended without executing. That's on me.

## What I'd change

Match the process to the risk instead of running the full T2 rig on everything. Of the seven remaining slices:

- **Mechanical** — delete twelve dead assignments, bump four manifests, strike a docstring promise. These want execute-test-commit, not a seat round each.
- **Real blast radius** — the config-dir seam (changes the starting state of every controller test) and the geometry authority (four packages, PANDA's virtual-source exception). These keep the full treatment.

That's roughly half the remaining ceremony for the same safety, because the safety was never coming from the ceremony — it was coming from running the full suite and reading the diff.

Want me to proceed on that basis, or would you rather stop here and take stock of the ledger before more of it gets harvested?

## User

Ok, let's take the mechanical items and pin the real changes for a fresh session.

## Assistant

Right. Classifying honestly, then landing only the low-judgement half.

**Landing now (mechanical):** slice 1 (`slits_mm` refill — a crash fix, but the critic already specified the exact extraction, and there's a committed reproducer), slice 4 (delete twelve dead assignments), slice 5 (strike the sample promise, enforce the opposite), slice 7 (bump four manifests).

**Pinning for a fresh session (real blast radius):** slice 2 (config seam — changes the starting state of every controller test), slice 3 (module-fixed reporting — not reproduced, needs investigation first), slice 6 (geometry authority — three copies in PUMA, PANDA's virtual-source exception).

Reduced seats to match: per-commit smoke plus one pre-PR review. No panel (broken anyway), no external reader — recorded as your deliberate call, not an oversight.

Four commits landed. The executor also caught an error of mine: my stated baseline of 1187 was stale — I'd carried it from before PR #34 merged. 1198 is correct. Reading the diff myself.

Diff is exactly as specified — the inline builder extracted rather than twinned, and the validator rule sits inside the runtime-only descriptor block. Smoke and push.

Smoke INCOMPLETE again (verifier malformed) — and four of its five "findings" are actually confirmations misfiled as defects. Only one is a real claim, and it's the one that matters: that the validator rule could fire in the `check_runtime=False` path.

Refuted: the rule sits inside `if check_runtime:` (line 186), nested two levels into the `runnable & registered` loop. It cannot fire when `check_runtime=False`, and the three synthetic-package tests that pass that flag are green. The smoke's one real candidate is ungrounded; the other four were confirmations, not defects.

PR **#35** is up and ready for you.

# Merge ask — the mechanical half

**[PR #35](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/pull/35)** · four commits · `main: clean`, merge-tree conflict-free.

Suite run **after every commit** so any change is attributable to one: 1198 → 1206 passed, 1 skipped throughout (the expected fresh-worktree skip). Zero failures at any point.

| | |
|---|---|
| `86005891` | `slits_mm` refill — fixes a `KeyError` at launch on all four instruments |
| `9833b161` | Twelve inert focusing factors deleted |
| `89c81444` | Sample filter/extend promise withdrawn, opposite enforced in validation |
| `4f90baff` | Four manifests bumped 1.0.0 → 1.0.1 |

The one that mattered most was slice 1, and only because the critic caught it: the obvious move was to write a twin of the collimation helper, which would have added a **fourth** copy of the tuple-vs-scalar shape the plugins depend on. The executor extracted the existing inline builder instead.

## Corrections

**My stated test baseline was wrong** — I told the executor 1187, carried over from before PR #34 merged. Actual is 1198. It flagged the discrepancy rather than silently proceeding, which is what you'd want.

The smoke came back INCOMPLETE again (verifier malformed output — second time today), with one real candidate: that the new validator rule might fire in the `check_runtime=False` path and break synthetic-package tests. **Refuted** — the rule sits inside `if check_runtime:`, nested two levels into the `runnable & registered` loop, and the three tests passing that flag are green. Its other four "findings" were confirmations misfiled as defects.

## Pinned for a fresh session

Three entries, left untouched with their ledger entries intact:

- **12 · config-dir seam** — changes the starting state of every controller-constructing test. Needs the hostile-`parameters.json` acceptance run, a test-id diff, and care around `test_rva_gui_axis_policy.py`, which isolates itself by changing cwd.
- **11 · module-fixed reporting** — not reproduced; needs investigation before any fix.
- **9 · geometry authority** — PUMA has *three* copies, not two, and PANDA's `l1_source_mono` is a virtual-source coordinate that a naive parity test would break.

Plus **13**, the direct-beam energy convention, awaiting your B-or-C call.

## Ledger after this merges

9 at session start → **4 remaining**. Five cleared today across three PRs, four opened by work that found them.

Merge when ready and I'll close out — board updated, the three pinned items written up with everything discovery turned up so a fresh session starts from evidence rather than from scratch.

## User

Merged. /transcribe first.

## Assistant

`transcribe` exists — it just wasn't in the injected listing. You typed it explicitly, so invoking it.

Session file isn't under the main project dir — the session has moved through three worktrees. Locating it.
