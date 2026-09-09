# PANDA Model Status

- Model version: **1.0.0**
- Model date: **2026-09-09**
- Runtime status: **runnable**
- Last evidence review: **2026-09-09**

The 0.1.0 research package became a runnable TAVI instrument on 2026-09-09.
Nothing in the historical `vpanda.instr` was accepted merely because it is
executable; every value below names the source it came from and, where sources
disagree, which one won.

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
| Scattering senses | (−1, +1, −1) | `vPANDA` `scatsense_*`; dossier reports the 2014 model reaching the same effective tuple | provisional — no NICOS confirmation |
| L1 (guide exit → mono) | 5.00 m | `vPANDA` model coordinate | good, but see "Reference planes" below |
| L2 (mono → sample) | 2.10 m | `vPANDA` + 2016 guide study "available distance" | conflicting — 2007 and 2014 models say 2.15 m |
| Virtual source → mono | 2.82 m | `vPANDA` (`ms1` at guide exit +2.180 m, mono at +5.000 m) | good |
| L3 (sample → ana) | 1.05 m | dossier, high confidence across sources | good |
| L4 (ana → det) | 0.95 m | dossier, high confidence across sources | good |
| Mono PG(002) | d = 3.355 Å, 11 × 11 of 20 × 18 mm, 2 mm gap, 20′ mosaic | consistent across every PANDA McStas generation | good |
| Mono Cu(111) | d = 2.087 Å | MLZ quotes 2.08 Å; 2.087 Å is the crystallographic value for a = 3.6149 Å | good |
| Cu(111) array, mosaic, r0 | 11 × 11 of 20 × 18 mm, 30′, r0 = 0.7 | **PLACEHOLDER** — copied from the PG holder; no source describes the Cu array | missing |
| Analyzer PG(002) | 11 × 5 = 55 of 13 × 25 mm, 3 mm gap, 20′ mosaic | 2014 team model + PANDA teaching notes | good — supersedes `vPANDA`'s 13 × 6 = 78, judged inherited from 2007 |
| Sample two-theta travel | 5° < A2 < 125° | MLZ page, verbatim | good |
| Analyzer two-theta travel | −130° < A4 < 100° | MLZ page, verbatim (a signed range, not a magnitude) | good |
| Mono two-theta travel | −132° < A1 < −20° | 2007 table's PG(002) `20° < 2Θ_M < 132°`, carried onto the negative branch | provisional — the MLZ page publishes no mono travel |
| Collimation | `ca1` 20′/40′/60′/open; `ca2`–`ca4` 15′/40′/60′/open | dossier + `vPANDA` `switch` blocks | good |
| Apertures `ms1`/`ss1`/`ss2` | 40 mm; 40 × 80 mm; 40 × 80 mm | `vPANDA` defaults | provisional — motorized limits unknown |
| Detector | 1″ ³He, 25 × 100 mm | MLZ page (focusing mode) + teaching notes (~100 mm active height) | good |
| Source aperture | 107 × 138 mm | `vPANDA` `NL_SR2_3` exit face | good |
| Analyzer vertical curvature | fixed at −0.60 m | dossier: conventional analyzer vertical curvature "apparently fixed"; value is the point-focus radius for the standard cold setting kf = 1.55 Å⁻¹ | provisional |
| Bending minimum radii | none applied | PANDA's mechanical limits are unknown; PUMA clamps, PANDA cannot | missing |

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
| BAMBUS | Multi-detector; TAVI's detector contract is a single 1-D monitor writing `detector.dat`. Deferred exactly as IN8's FlatCone/IMPS are. MLZ lists it as under commissioning. |
| Heusler monochromator/analyzer, spin flippers, guide fields | TAVI models no spin-dependent transport. A Heusler entry would emit an unpolarized beam under a polarizing label — worse than its absence. |
| Si(111) monochromator | A bent-perfect crystal; `Monochromator_curved`'s mosaic model misrepresents it. Same call as IN8's Si faces. |
| Upstream sapphire filter | `Al2O3_sapphire.trm` is in the PANDA team's repository, not in `components/` and not stock McStas data. Adding a transmission table we cannot source would be worse than omitting a component that only attenuates. |
| Analyzer-side PG / cold-Be / BeO filters | They suppress higher-order contamination, which `Monochromator_curved`'s single-Q reflection does not produce. Modeling one would only attenuate the primary beam. |
| Proposed 1.48 m, m = 6 elliptic mono→sample guide | The 2016 study is prospective ("shall", "expected"); no later official source confirms installation. The dossier says it must not be enabled by default. |
| Fixed beam-defining apertures `sk1`–`sk5` | Not motorized and not scannable; they shape flux, never angles. `ca1`–`ca4`, `ms1`, `ss1`, `ss2` are the operational apertures and are all present. |
| 2″ ³He detector (collimated configuration) | Only the 1″ focusing-mode tube is selectable. A detector choice would need a descriptor-level module, which no current task requires. |
| Cold-source vs thermal-source operation | MLZ publishes separate ki ranges for the two. The model carries one Maxwellian source; `axis_limits` and the crystal menu span both. The "without cold source" spectrum is not represented. |

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
- **Not yet performed:** a compiled McStas run. Step 8 of
  `docs/INSTRUMENT_AUTHORING.md` (compile and run one elastic Bragg point at
  1e7 neutrons and confirm the detector counts) is outstanding — that is the
  check that caught IN8's bending-sign error, and PANDA's senses put *both*
  crystals on the negative branch, which no TAVI instrument has exercised
  before.
