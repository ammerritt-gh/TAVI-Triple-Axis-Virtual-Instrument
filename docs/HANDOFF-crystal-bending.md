# Handoff — crystal-bending generality

> **Status:** live
> **Branch:** `crystal-bending-generality`, not merged, no PR open yet
> **State (corrected):** the eight defects from the two external reviews were
> closed at `2e5282d0`, but that was not the end of the list. A landing
> session afterward, working from `docs/PLAN-crystal-bending-landing.md`,
> found and fixed thirteen more (`D13`-`D25`, listed there) reading the same
> code with the same "one path, not its twin" question in mind. Every one of
> D13-D25 is fixed on the branch as of `534c2140`; see that plan's defect
> ledger for the commit that fixed each. "No review round outstanding" was
> true of the two external rounds and is no longer the state of the branch —
> read the plan's own seat dispositions before treating this branch as
> closed.
> **Worktree:** `C:\Users\AMM\Documents\Github\Science\TAVI-wt-bending`

## What this branch is

A monochromator or analyser crystal has up to four curvature axes (`rhm`/`rvm`
on the monochromator, `rha`/`rva` on the analyser). Before this branch the radii
that actually reached the simulation came from **two hard-coded copies of PUMA's
parallel-beam focusing formula**, plus PUMA's minimum-radius clamps, in the GUI
controller and the widget-free API equivalent. Each instrument's own focusing
method had **zero production callers**. The fourth axis, `rva`, had no widget and
no key in the values dict, so three call sites read PUMA's fixed 0.8 m as a
universal default.

Now: a crystal assembly declares what each axis can do; one producer
(`TAS_Instrument.ideal_curvature`) computes an ideal radius from the
instrument's own optics; one applier (`set_crystal_bending`) enforces policy and
signs; a per-axis mode (AUTOFOCUS / HELD / SCANNED) travels in launch state and
is honoured per point; an explicitly commanded out-of-travel radius is refused at
submission rather than clamped; the analytic resolution model receives `rva`; and
each scan result records the curvature each point actually ran with.

## The one thing to know before touching this area

**The recurring defect is a rule implemented in one path and not its twin.** It
was found **twelve times** through the two external reviews, at nearly every
layer the consolidation touches: the producer, the applier, the GUI, the API,
the resolution model, the scan validator, the persistence layer, and once
inside a *test fixture* — a stub controller whose `normalize_scan_variable`
and variable-index map had silently diverged from the real controller's,
which made a green suite mean less than it appeared to.

**Corrected: the count is now twenty-five, not twelve.** A landing session
found thirteen more (`D13`-`D25`, `docs/PLAN-crystal-bending-landing.md`)
asking the identical question of the same code, in three further layers the
original twelve had not yet shown: a *test itself* asserting the wrong
behaviour, not merely a fixture silently diverging from production
(`D22` pinned the GUI preflight's blindness to a relative out-of-travel
command as if it were correct); a partial twin inside one overlay function
rather than across two functions (`D23` — the resolution-model overlay copied
a point's radii but not its own Ei/Ki/Ef/Kf, so the two halves of "this
point's state" disagreed with each other inside the same call); and a check
that exists and is correct but that production never actually reaches with
the input that matters (`D14` — `validate_scan_launch_state`'s
`_curvature_violation` was "authoritative" only for callers that force
`relative=False`, so a relative GUI scan never reached it in practice). This
was not a coincidence the first twelve times and is not one now: it is the
shape of the original defect (one formula in two copies) reproducing itself
wherever the consolidation lands, including into weaker forms once the
literal duplicate-code instances had been swept up. **Assume a
twenty-sixth exists.** Two review passes returned clean on code where an
external reader then found three, and a landing session found thirteen more
after that.

Practical consequence: when you fix something here, ask what its twin is before
you write the fix, and prefer deleting a copy to adding a rule.

## Two contracts that are deliberately different

Getting these backwards is how the worst bug on this branch happened.

- **Operator / API / descriptor values are MAGNITUDES.** How tightly the crystal
  is bent is what a person types and an API client sends.
- **Emitted McStas geometry and `ScanResult.applied_curvature` are SIGNED.**
  Which side it bends toward is instrument geometry, derived at the physical
  boundary from the *actual local take-off angle* — never from the declared
  scattering sense, because a direct-angle scan can legitimately put a crystal on
  the opposite branch (PANDA's declared A4 range spans both signs) where the
  wrong sign costs ~7 orders of magnitude.

`tavi/resolution.py` applies the scattering sense *itself*
(`monorh = radius_cm(cfg.rhm) * sm`), so a signed radius reaching it is signed
twice. That was live for three commits and cost ~1.6% on energy resolution and
roughly a factor of two on both momentum components, while the emitted McStas
geometry stayed correct — so nothing visible broke and no test caught it.

## Review history, and what each round found

The branch went through two external pre-PR reviews, plus a per-slice review on
every commit and one whole-branch pass. That history is the most useful thing
here, because of *what* the later rounds found.

**First external review** — would not merge. Four functional findings, three of
which were one defect at three call sites: the deterministic engine, the
`GET /resolution` backend, and the McStas background sigma widths all still
built the analytic resolution from the frozen launch values after curvature had
become per-point. Plus relative scans evading the out-of-travel refusal.

**Second external review** — would still not merge. Four more, three again the
same class: PUMA's nested-mirror-optic rule living in two places with a SCANNED
axis escaping both; `focusing_known=False` being per-axis in the schema but
whole-crystal in the producer; and the resolution model rebuilding branch signs
from the static descriptor while the applier used the point's own angle. Plus a
regression the *previous* round's fix had introduced — the false-accept repair
had created its mirror-image false-reject.

All eight are fixed (as are `D13`-`D25`, found afterward — see the corrected
`State:` line above). **Both external readers found defects that a per-slice
review and a whole-branch review had passed clean on the same code.** That is
the single most transferable fact in this document: in this area, one tool's
silence is not evidence. The landing session's own thirteen are the same
lesson from a different angle: they were found by *rereading the existing
code against the plan's defect-hunting question*, not by a new tool — nothing
about the review machinery changed, only the willingness to keep asking.

## Verification

TAVI's suite runs **serially** in ~85 s. `micromamba` is not on PATH:

    cd "C:/Users/AMM/Documents/Github/Science/TAVI-wt-bending"
    "/c/Users/AMM/AppData/Local/micromamba/micromamba.exe" run -n tavi-dev \
        python -m pytest tests -q
    "/c/Users/AMM/AppData/Local/micromamba/micromamba.exe" run -n tavi-dev \
        python -m instruments.package_validation

A direct interpreter invocation crashes on a delay-load failure in matplotlib and
Qt native code — that is not a broken environment. **Never run two suites at
once, and never run a targeted file while a full run is in flight:** the
persistence tests share a config file and fail spuriously. That cost an hour of
false diagnosis on this branch.

The worktree lacks the gitignored 143 MB `components/Pb_dft_phonons.dat`; it is
hardlinked from the main checkout, without which `test_dispersion_map.py` skips
*silently* and the lane still reads green.

## Compiled McStas smoke runs

Step 8 of `docs/INSTRUMENT_AUTHORING.md`, production path, Al (2,0,0) elastic,
1e7 neutrons, collimators open, ideal focusing. **Call
`install_no_window_guard()` from any script outside pytest** or every instrument
construction opens a console window on the operator's screen — this has buried
his desktop before. Results on this branch, 2026-09-11, each verified against the
detector files:

| | before | after |
|---|---|---|
| PUMA | none | 2.09475e-07 / 4973 (first baseline) |
| IN8 | 3.33e-07 / 4908 | 5.07902e-07 / 11455 |
| IN12 | 4.21e-07 / 4334 | 5.44329e-07 / 6901 |
| PANDA | 7.99e-08 / 1462 | 2.07537e-07 / 7663 |

**Corrected (H1):** "every instrument gained flux" overstates PUMA, which has
no *before* number in the table above — the parallel-beam assumption this
branch replaces was PUMA's own pre-existing formula, so there is nothing on
PUMA to compare "after" against; its row is a first baseline, not a measured
gain. IN8, IN12, and PANDA each have a real before/after pair, and all three
gained flux there, far outside Monte-Carlo scatter, in the direction expected
once the monochromator images the real virtual source at L1 instead of
assuming a beam from infinity. Each takes ~3 s on this machine with 30 MPI
processes.

## Settled rulings — do not re-open

- Curvature policy belongs on `CrystalSpec`: here a "crystal" is the crystal
  **plus its mount**, as an installed package. Two reviews raised a mount/assembly
  objection; the operator closed it on that ground.
- **Autofocus tracks during the measurement.** Operator ruling: scanning drives
  an axis point by point, setting holds it, autofocus follows. That it had not
  been doing so was a failure, not a design choice.
- IN8's `rva` is **driven** — its Thermes analyser is variable double-focusing and
  the hardware tracks it.
- **Zero means flat**, always legal, never clamped up to a minimum. An unbent
  crystal is real hardware; a minimum radius bounds how tightly a bender may
  bend, not whether it may be straight.
- IN8 and PANDA declare **no** mechanical travel and therefore refuse nothing.
  Theirs are genuinely unknown — PANDA's confirmed absent from the literature —
  and inventing limits would be the defect.
- PUMA's bending limits and its fixed 0.8 m analyser radius were **reviewed
  against internal instrument documentation and confirmed with the instrument
  scientist** (operator, 2026-09-11). Not independently citable, not a guarantee,
  and explicitly **not** covering PUMA's arm lengths, which stay provisional.
- `curvature_modes` is **read-only** on the API. Modes derive from the Ideal locks
  and from which axes a scan command names; a second way to set them would be
  another twin.

## Deferred on purpose

- A non-numeric radius typed into a GUI field blocks the run but tells the
  operator nothing — the run quietly does nothing. Pre-existing, unrelated to
  curvature.
- IN12's provisional 1.7 / 0.5 m monochromator minima, and PANDA's and IN12's
  analyser vertical *radius*, remain unsourced and still need an instrument
  scientist. Recorded as such, not closed.
- No angle-dependent bender travel. `curvature_limits` is the seam; nothing needs
  it yet.

## Downstream

This branch changes numbers the sibling campaign repo (ISAR) consumes, three
ways: emitted curvature on IN8/IN12/PANDA; the analytic resolution for every
instrument once `rva` reaches it; and the sign correction on negative-branch
instruments. A campaign run against this branch will **not** reproduce one run
against `main`. That is intended, not drift. The reader confirmed no API *shape*
break — ISAR's client is a permissive JSON wrapper and its parser ignores unknown
members.
