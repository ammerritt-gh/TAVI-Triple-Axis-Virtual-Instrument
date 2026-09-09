# PANDA Model Status

- Model version: **1.0.0**
- Model date: **2026-09-09**
- Runtime status: **runnable**
- Last evidence review: **2026-09-09**

The 0.1.0 research package became a runnable TAVI instrument on 2026-09-09.
Nothing in the historical `vpanda.instr` was accepted merely because it is
executable; every value below names the source it came from and, where sources
disagree, which one won.

A literature verification pass on 2026-09-09 (see "Verification performed")
checked every provisional value against the published record. It confirmed some,
left more unsupported, and turned up one fact that reframes the whole table —
**PANDA's monochromator has been replaced.** Read the next section first.

## The model describes pre-shutdown PANDA

FRM II has produced no neutrons since 17 March 2020, and the MLZ User Office
states "No neutrons in 2026". PANDA is not taking user data; it is being
prepared for renewed operation. (The March 2020 stop was a COVID-19 closure —
the C-14 exceedance and the later cold-source failure were found while the
reactor was already down, and are why it has stayed down. A May 2026 conference
abstract mentions a restart in early 2027 in thermal mode; that is a planning
statement, not a committed date, and is recorded here as such.)

That matters for this model because the 2024–25 restart reports describe
**a new double-focusing PG(002) monochromator** and a new sample table. Every
monochromator number in the table below — the 11 × 11 array, the 20 × 18 mm
pieces, the 20′ mosaic, the 20°–132° travel, and the 2.10 m monochromator–sample
distance — comes from sources describing the instrument *before* that
replacement. They are the best published values and they are internally
consistent, but none of them has been confirmed against the hardware that will
come back online.

**So: this package models pre-shutdown PANDA.** That is the right target — it is
what the literature documents and what the historical McStas models were
validated against — but the monochromator section will need revisiting once the
new unit is described anywhere public. Question 1 of `SCIENTIST_REVIEW.md` is
now that question.

## Source hierarchy

The dossier's hierarchy is followed as written: current MLZ technical data
first, then later physical/teaching documentation, then the 2014 team McStas
model, then the 2016 optimization study for optional geometry, then Peter
Link's 2007 model for otherwise-undocumented primary geometry, then `vPANDA`
for parameter names and relative placement after correcting inherited errors.
Nothing above "current control-system limits and PANDA staff confirmation" has
been obtained — that whole top tier is still open, which is why the axis
conventions and the mechanical bending limits remain unconfirmed.

## What the model asserts, and on what evidence

| Area | Value in TAVI | Source | Confidence |
|---|---|---|---|
| Scattering senses | (−1, +1, −1) | `vPANDA` `scatsense_*` + the 2014 team model. The teaching notes independently give PANDA's convention as 0° along the incident beam, **positive counter-clockwise**, with 2Θ_S positive — which supports `sense_sample = +1`, and the MLZ page's signed analyser range (−130° to 100°) is consistent with the analyser sitting on the negative branch. | provisional — no source states the full tuple. Treat as the component-tree convention the team models use, NOT a documented motor-sign tuple. The analyser's own travel crosses zero, so `sense_ana = −1` is the normal geometry, not a universal motor sign. |
| L1 (guide exit → mono) | 5.00 m | `vPANDA` model coordinate | good, but see "Reference planes" below |
| L2 (mono → sample) | 2.10 m | `vPANDA` + 2016 guide study "available distance" | conflicting — 2007 and 2014 models say 2.15 m |
| Virtual source → mono | 2.82 m | `vPANDA` (`ms1` at guide exit +2.180 m, mono at +5.000 m) | good |
| L3 (sample → ana) | 1.05 m | dossier, high confidence across sources | good |
| L4 (ana → det) | 0.95 m | dossier, high confidence across sources | good |
| Mono PG(002) | d = 3.355 Å, 11 × 11 of 20 × 18 mm, 2 mm gap, 20′ mosaic | The 11 × 11 = 121 count is confirmed by the teaching material ("121 monochromator (55 analyzer) crystals"); the rest is consistent across every PANDA McStas generation. | **pre-restart** — 121 crystals well supported for the old unit; piece size, gap and mosaic are simulation values with no measurement behind them. The monochromator has since been replaced. |
| Mono Cu(111) | d = 2.087 Å | MLZ quotes 2.08 Å; 2.087 Å is the crystallographic value for a = 3.6149 Å | good |
| Cu(111) array, mosaic, r0 | 11 × 11 of 20 × 18 mm, 30′, r0 = 0.7 | **PLACEHOLDER** — copied from the PG holder. The unit itself is real (MLZ 2021: Cu-111 monochromator from IPC/Göttingen under commissioning; 2024: "can be used"), but no source gives its piece count, dimensions, gaps, mosaic or reflectivity. | missing — every geometric number here is invented |
| Analyzer PG(002) | 11 × 5 = 55 of 13 × 25 mm, 3 mm gap, 20′ mosaic | The **55-crystal count is confirmed** by the teaching material, in more than one revision, and supersedes `vPANDA`'s 13 × 6 = 78. No restart report says the conventional analyser was replaced. | count good; the 11 × 5 arrangement, the 13 × 25 mm pieces and the 3 mm gap are the 2014 model's implementation detail and are **unverified** |
| Sample two-theta travel | 5° < A2 < 125° | MLZ page, verbatim | good |
| Analyzer two-theta travel | −130° < A4 < 100° | MLZ page, verbatim (a signed range, not a magnitude) | good |
| Mono two-theta travel | −132° < A1 < −20° | `20° < 2Θ_M < 132°` for PG(002) appears in the 2007 table, the **2015 JLSRF instrument paper**, and a 2011 instrument compilation — better established than first assumed. Carried onto the negative branch. | **pre-restart** — three independent sources agree through 2015, but the MLZ page omits it and the monochromator is new |
| Collimation | `ca1` 20′/40′/60′/open; `ca2`–`ca4` 15′/40′/60′/open | dossier + `vPANDA` `switch` blocks | good |
| Apertures `ms1`/`ss1`/`ss2` | 40 mm; 40 × 80 mm; 40 × 80 mm | `vPANDA` defaults | provisional — motorized limits unknown |
| Detector | 1″ ³He, 25 × 100 mm | The **1″-focusing / 2″-collimated choice is confirmed** by the MLZ page and by peer-reviewed PANDA experiment descriptions. | type good; **25 mm × 100 mm, 10 bar and ~90% efficiency are detector-model assumptions** — no PANDA-specific source found, and "1 inch" names the tube, not the active gas diameter |
| Source aperture | 107 × 138 mm | `vPANDA` `NL_SR2_3` exit face | good |
| Analyzer vertical curvature | fixed at −0.60 m | **Fixed vertical / variable horizontal is confirmed** by two peer-reviewed PANDA papers, one of which ties the fixed vertical geometry to the vertically oriented 1″ ³He detector, and by the MLZ page advertising only variable horizontal focusing. | the *fixedness* is now well supported; the **radius is not** — no source gives it, and −0.60 m is our point-focus value for kf = 1.55 Å⁻¹ |
| Bending minimum radii | none applied | No published minimum or maximum radius for either crystal was found. The 2007 reporting confirms driven focusing existed, but gives no travel. Applying no clamp is the deliberate choice: inventing one would be worse, and the monochromator is new anyway. | missing — confirmed absent from the literature, not merely unlocated |

## `vPANDA` defects, and how each was handled

The 0.1.0 status recorded seven interface and geometry defects in the retained
snapshot; the dossier's audit lists thirteen. Disposition of every one:

| Defect | Disposition |
|---|---|
| Sapphire filter thickness 0.86 m (should be ~0.07 m) | **avoided** — no sapphire filter is modeled at all (see gaps) |
| Focusing defaults are zero | **fixed** — focusing radii are computed per point and are never zero |
| Analyzer array 13 × 6 is stale | **fixed** — 11 × 5 |
| The Pb sample is a test object, not hardware | **fixed** — samples come from the shared library, none is baked in |
| Detector represented only by PSD monitors | **fixed** — a `Monitor` at the 1″ tube aperture is the primary detector |
| Fallback ΔE derived from `kf − ki`, singular at elastic | **avoided** — TAVI's shared solver owns the kinematics |
| Scattering senses not consistently propagated | **fixed** — the shared `calculate_angles` applies them at every axis |
| `atx` unused; defaulted `kf` shadows explicit `ki`; placeholder parameter units | **avoided** — none of `vPANDA`'s parameter interface is carried over |
| Cu(111)/Si(111)/Heusler monochromators absent | **partly fixed** — Cu(111) added; Si(111) and Heusler deferred, below |
| Analyzer-side filters absent | **still absent** — deliberate, below |
| Polarization absent | **still absent** — deliberate, below |
| 2026 filename misleading as a hardware date | **recorded** — `references/SOURCES.md` states the capture date is not a hardware date |

## Deliberate gaps

Each of these is hardware PANDA has, or evidence PANDA published, that this
model does not represent. None is an oversight.

| Gap | Why |
|---|---|
| BAMBUS | Multi-detector; TAVI's detector contract is a single 1-D monitor writing `detector.dat`. Deferred exactly as IN8's FlatCone/IMPS are. It is further along than the 2015 concept paper suggests — a BMBF final report describes it as built and dry-commissioned: 100 channels, 40° total 2θ coverage, 2° cassettes, E_f = 3.0/3.5/4.0/4.5/5.0 meV, a cooled 14 cm Be filter, per-energy Rowland distances of ~950–1400 mm, and 99 of 100 detectors installed. Neutron commissioning is what remains, and it cannot happen without beam. Public sources disagree on whether the analyser holds 500 or 250 PG crystals; that conflict is unresolved and is not resolved here. |
| Heusler monochromator/analyzer, spin flippers, guide fields | TAVI models no spin-dependent transport. A Heusler entry would emit an unpolarized beam under a polarizing label — worse than its absence. |
| Si(111) monochromator | A bent-perfect crystal; `Monochromator_curved`'s mosaic model misrepresents it. Same call as IN8's Si faces. |
| Upstream sapphire filter | `Al2O3_sapphire.trm` is in the PANDA team's repository, not in `components/` and not stock McStas data. Adding a transmission table we cannot source would be worse than omitting a component that only attenuates. |
| Analyzer-side PG / cold-Be / BeO filters | They suppress higher-order contamination, and this model has none to suppress **because both crystals are pinned to `order=1`**, not because a single-Q reflection cannot produce it. `Monochromator_curved` at its default `order=0` reflects at every multiple of the supplied reciprocal-lattice vector, and the default source is the broadband Maxwellian branch (where `dE` sets normalization, not a sampling cutoff), so nothing else in the tree would exclude a λ/2 component at four times the nominal energy. The model is therefore an **idealized, order-clean conventional TAS**. The alternative — an effective filtered spectrum plus the real secondary filtering — is a different model, not a refinement of this one. Contamination fractions are unmeasured here. |
| Proposed 1.48 m, m = 6 elliptic mono→sample guide | The 2016 study is prospective ("shall", "expected") and no post-2016 source says the specific m = 6, 1.48 m design was fabricated or installed. Note the distinction that verification drew: PANDA **has** used sample-focusing guide optics experimentally (e.g. earlier small-sample work on NiS₂), so "PANDA has used a focusing guide" is true while "the 2016 guide is standard hardware" is not. |
| Fixed beam-defining apertures `sk1`–`sk5` | Not motorized and not scannable; they shape flux, never angles. `ca1`–`ca4`, `ms1`, `ss1`, `ss2` are the operational apertures and are all present. |
| 2″ ³He detector (collimated configuration) | Only the 1″ focusing-mode tube is selectable. A detector choice would need a descriptor-level module, which no current task requires. |
| Cold-source vs thermal-source operation | MLZ publishes separate ki ranges for the two. The model carries one Maxwellian source; `axis_limits` and the crystal menu span both. The "without cold source" spectrum is not represented. |
| Ideal focusing radii in the GUI/API | The Ideal button and the API's widget-free equivalent never call `calculate_crystal_bending`: both hard-code PUMA's parallel-beam formula and PUMA's minimum-radius clamps. PANDA's negative angles make every ideal radius negative, so the clamps always fire and the button offers (2.0, 0.5, 2.0) instead of (3.985, 1.787, 1.651). **Scans and the API launch path are unaffected** — they take the radii from `scan_config`, which is correct. Deferred deliberately to one comprehensive cross-instrument repair (`TODO.md` → Instrument models), because the fix changes IN8's numbers too. |

## Reference planes — the one unresolved geometry question

The published source–monochromator distance is ~7.8 m across the 2007, 2015
and 2016 papers. The McStas models place the monochromator at ~8.81 m of model
coordinate (≈3.81 m to the guide exit plus 5.00 m). The dossier records the
discrepancy as unexplained and warns against silently adopting 8.81 m.

TAVI does not adopt either: it starts the model at the guide-exit reference
plane and sets `l1_source_mono = 5.00 m`. Everything upstream is beam
transport this model does not simulate. This is safe for angles (distances
never enter them) and for the horizontal focusing (which images `ms1` at
2.82 m, not the source), but it does mean **`l1_source_mono` is not the
published source–monochromator distance and must not be read as one.**
Question 1 in `SCIENTIST_REVIEW.md` is what would close this.

## Verification performed

- Descriptor passes `validate_descriptor(runnable=True)`.
- `python -m instruments.package_validation` passes for this package.
- Plugin conformance, build-tree and angle-golden tests:
  `tests/test_panda_plugin.py`, `tests/test_panda_build_tree.py`,
  `tests/test_sign_conventions.py`.
- **Literature verification pass** (2026-09-09, external search seat): every
  provisional value above checked against the published record. Confirmed the
  55-crystal analyser, the 121-crystal monochromator, fixed vertical analyser
  focusing, the 1″/2″ detector choice, the 20°–132° monochromator travel
  through 2015, and 7.8 m source→mono as recently as a 2023 upgrade
  contribution. Found **no source** for: the full scattering-sense tuple, the
  7.8 m / 8.81 m reference-plane reconciliation, a 2.15 → 2.10 m mechanical
  change, any Cu(111) crystal geometry, a measured PG mosaic, the analyser's
  fixed vertical radius, any bending limit, or the detector's active height and
  fill pressure. Surfaced the monochromator replacement.
- **Compiled McStas smoke run: passed** (2026-09-09). Step 8 of
  `docs/INSTRUMENT_AUTHORING.md`, driven through the production path
  (`build` → `compute_snapshot` → `run_point`): Al (2,0,0) elastic at
  kf = 2.662 Å⁻¹, 1e7 neutrons, all collimators open, ideal focusing.
  `detector_I = 2.63e-07`, `detector_N = 12105`. The identical point through
  IN8 as a control gives `4.65e-07` / `5324` — the same order of magnitude,
  which is the check that matters: a wrong-branch curvature costs ~7 orders of
  magnitude, so PANDA's all-negative focusing is not defocusing.
  Al (1,1,1) is *not* a usable smoke point despite being reachable at the cold
  kf = 1.55 setting — it is out of the horizontal scattering plane for the
  default cubic mount and returns `I = 0`, `N = 18`. Al (2,0,0) at that kf has
  Q = 3.103 Å⁻¹, just past 2k = 3.10, and is unreachable. Hence kf = 2.662 for
  the smoke.
