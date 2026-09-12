# IN12 Model Status

> **Status:** live
> **Authority:** the state of the IN12 model: what is verified, approximated, and open

- Model version: **1.0.1**
- Model date: **2026-09-09**
- Runtime status: **runnable**
- Last evidence review: **2026-09-09** (literature round, `references/2026-09-09__in12-literature-round__v02.md`)

Status of the IN12 model, promoted from a research package to a runnable one on
2026-09-09. **The kinematics are verified** — the scattering senses were
resolved by the literature round on the same day, so everything remaining below
affects intensity, resolution, or capability, never the computed angles.

Code locations: `instruments/in12/plugin.py` (descriptor) and
`instruments/in12/model.py` (build); placeholders are marked `PLACEHOLDER`
in-line.

Sources: Schmalzl et al. NIM A 819 (2016) 89–98 ("2016"); the current ILL IN12
pages ("ILL", re-checked 2026-09-09); W. Schmidt and B. Fåk, "New focusing
analyser on IN12", ILL Annual Report 1998 ("1998"); the public Takin resolution
preset `data/instruments/in12_pg002_pg002.taz` ("Takin"); a 2001 IN12 raw scan
header and the 2010 vTAS repository (via the research dossier). All in
`references/`, with the two 2026-09-09 rounds recorded there. Anything marked
*needs IS* wants instrument-scientist numbers or drawings.

**We never received files from the instrument team.** This model is built from
the public record alone. The public record turned out to contain more than the
first pass found — including the analyser's construction and an ILL-published
parameter preset — but the items in `SCIENTIST_REVIEW.md` are what remain.

---

## Verified / trusted

| Item | Value | Source |
|---|---|---|
| **Scattering senses** | **mono −1, sample +1, analyser −1** (the "W" configuration) | three independent lines — see below |
| Axis limits | mono 2θ −140…−10°, sample ±120°, analyser ±140° | ILL |
| Sample goniometer | ±20° | ILL |
| L1, L2 | 1.800 m each — the monochromator centre 1.8 m after the guide end, the sample the same 1.8 m beyond, the Rowland condition the assembly was built for | 2016, stated outright |
| L4 | 0.720 m | ILL; 72 cm in Takin |
| Monochromator array | PG(002), 11 × 11 over 200 mm wide × 160 mm high, mosaic 24′ (0.4° FWHM), crystals 2.0 ± 0.1 mm thick | 2016 + ILL; the 20 × 16 cm orientation independently confirmed by Takin's `mono_w`/`mono_h` |
| Analyser construction | eleven vertical lamellae, **11 mm** lamella width, variable horizontal focusing, **fixed** vertical focusing by tilting the top and bottom rows, mosaic ~0.5° | 1998 |
| Analyser face | 122 × 118 mm | ILL |
| Heusler(111) | 75 × 145 mm, d = 3.44 Å | ILL |
| Crystal d-spacings | PG(002) 3.355 Å | 2016 / Takin |
| Collimators | Gd Soller 10/20/30/40/60/80′, four positions | ILL |
| Detector | one vertical ³He tube, 12 cm high × 5 cm ⌀ | ILL; 12 × 5 cm in Takin |
| Guide exit / virtual source | 20 mm wide × 140 mm high, 1.8 m from the mono | 2016 |
| Operating envelope | λ 1.26–6.3 Å, ki 1.0–5.0 Å⁻¹, Ei 2.1–42 meV | ILL |

### The senses — resolved 2026-09-09

`(−1, +1, −1)` in the convention where +1 = left/counter-clockwise, which is
what the ILL SICS/TAS-MAD `SM`/`SS`/`SA` instrument variables mean. Three
independent lines agree:

1. ILL publishes the monochromator two-theta travel as −140°…−10°, entirely
   negative. Strong, but not proof on its own: a motor coordinate and the
   logical sense metadata need not share a sign.
2. The public Takin preset stores `mono_scatter_sense = 0`,
   `sample_scatter_sense = 1`, `ana_scatter_sense = 0` — monochromator and
   analyser on one branch, sample on the other. That is the **W configuration**,
   which ILL's own documentation names for IN12.
3. H. Trepka's 2022 Stuttgart dissertation reports an actual post-upgrade IN12
   configuration explicitly as `SM = −1, SS = +1, SA = −1`.

A fourth source only *looks* contradictory: Brüning's IN12 RESCAL table gives
`+1, −1, +1`, but legacy ResCal defines +1 = right, the reverse convention.
Normalised, it is the same geometry.

IN12 is the first TAVI instrument with `sense_mono = −1`, so it is also the
first exerciser of that path through the shared angle solver, forward and
inverse.

---

## Missing / placeholder, by section

### Source (largest intensity uncertainty)

| Item | Current | Needed |
|---|---|---|
| Model boundary | effective source AT the H144 exit; 115 m of guide not modeled | a real H144 model or an MCPL file at the exit. 2016 says the guide was calculated in McStas and the primary spectrometer in SIMRES plus in-house routines, so models existed — **none is public**. *needs IS* |
| Spectrum | `Source_div_Maxwellian_v2` peaked at E0, dE = 2 meV | the true cold-source spectrum at the H144 exit for absolute flux. 2016 measured ~30 % more capture flux than the contemporary McStas cold-source description predicted. *needs IS* |
| Guide geometry | not modeled, but the public record supports what would be modeled: ~115 m from the vertical cold source, last ~80 m at R = −2000 m in 45 × 105 mm with an m = 2.4 outer wall, final 8 m widening 105 → 140 mm vertically and focusing 45 → 20 mm horizontally at up to m = 3.2 | the upstream 6 m at R = 2700 m and ~21 m at R = 4000 m belong to the **common H14 system** before the four branches split, not to H144 specifically |
| Velocity selector | **absent** | >36 m upstream, outside the model boundary. Its higher-order suppression is replaced by pinning both crystals to `order=1` (see *Higher orders* below), not inherited from a narrow band this model does not have. Only Astrium, >36 m, in/out, and the 2.23–6.3 Å design range are confirmed; the rotor blade count, helix angle, Δλ/λ, transmission, speed range and rpm↔λ calibration are **all unconfirmed for the IN12 unit** and must not be copied from other Astrium selectors |
| Polarising cavity, guide fields, flippers | **absent** | ~35 m upstream, and TAVI models no polarisation |

### Monochromator

| Item | Current | Needed |
|---|---|---|
| Slab width/height | 16.8 × 13.2 mm, derived as face/11 minus a 1.5 mm gap | actual crystal dimensions. *needs IS* — published nowhere |
| Slab gap | 1.5 mm PLACEHOLDER | drawing value |
| Crystal backing | not modeled | 2016's 2.3 mm B₄C + 3 mm Al could not be re-confirmed; only matters for transmission/background realism |
| Mosaic | 24′ isotropic | 2016 gives 0.4° FWHM without splitting horizontal and vertical. Takin's 33′ is an *effective* resolution parameter, not metrology — do not adopt it as the crystal mosaic |
| Curvature limits | 1.7 m horizontal / 0.5 m vertical minima, **enforced as a provisional model assumption** and labelled as such in `model.py` | **unconfirmed.** ILL says only that both axes are variable; Takin's saved 1.20 m vertical radius is one setting, not a limit. The vertical clamp is load-bearing (it binds above roughly \|A1\| = 32°), so this is an unsourced number affecting emitted geometry. Kept rather than deleted because removing it asserts unbounded bending, which is equally unsourced and less conservative. *needs IS* |
| Motor sign convention | both radii negated onto the −1 take-off branch | the *motor* convention should be checked at more than one real setting. *needs IS* |

### Analyser

| Item | Current | Needed |
|---|---|---|
| PG subdivision | **11 columns × 3 rows**, lamella width 11 mm (published), row height and 0.1 mm gap derived from the 122 × 118 mm face | 1998 gives the lamella width and says the fixed vertical focus comes from tilting the **top and bottom rows**, which needs at least three. Three is the natural reading; the true row count, crystal thickness and inter-crystal gaps are **not published**. *needs IS* |
| Vertical curvature | fixed at **1.40 m**, branch-signed, and declared `"rva": CurvatureAxis(driven=False, fixed_radius_m=ANA_FIXED_RV, ...)` **on the PG(002) analyser** so a scan over it is refused rather than silently defeating the pin. Declared on the crystal, not the instrument: the 1998 evidence is about this assembly, and the Heusler option below has no established focusing behaviour to inherit it | 1998 confirms the vertical focus is fixed but gives no radius; 1.40 m is Takin's `pop_ana_curvv`, a resolution preset rather than a mechanical drawing. It is deliberately far from the point-source Rowland radius for L3/L4 (~0.43 m) — which is what "fixed" means. *needs IS* for the mechanical value |
| Mosaic | 30′ | 1998's ~0.5°. The 2001 header says 35′ and Takin uses an effective 33′; treat 30′ as nominal, not as a post-upgrade measurement |
| Horizontal curvature limits | none | allowed radius range. *needs IS* |
| Heusler(111) geometry | PLACEHOLDER 5 columns × 1 row of 13.8 × 145 mm, mosaic 30′, constant r0 = 0.3 via the `"NULL"` sentinel | blade count, size, gap, mosaic, reflectivity — none published. Its **focusing axis is configuration-dependent, not a source conflict**: published IN12 experiments describe a horizontally focusing Heusler (2014, 2025) and a vertically focusing one (2024). Whether that is one reconfigurable assembly or two is unknown. *needs IS* |
| Heusler vertical focus | **not** PG's fixed 1.40 m -- the Heusler declares `"rva": CurvatureAxis(driven=True, focusing_known=False)`, so `rva` is driven like `rha` (GUI magnitude on the take-off branch; flat when unset) and stays scannable, though no ideal radius may be computed for it | PG(002)'s fixed vertical focus is 1998 evidence about **that** assembly. `scan_config` used to pin `-ANA_FIXED_RV` for every analyser, so selecting the Heusler silently inherited PG's radius. The Ideal button no longer offers it a point-source optimum either: `focusing_known=False` means no established focusing model, so the button is unavailable for this axis and the operator sets it by hand -- a per-axis refusal, not a whole-crystal one: `rhm`/`rvm`/`rha` still compute their own Ideal normally with the Heusler installed, because `ideal_curvature` is asked only for the axes a caller actually wants and refuses solely a *requested* axis with no focusing model, rather than the whole calculation tripping over this one unrelated axis. *needs IS* |
| Polarisation | not modeled | TAVI has no polarisation channel; Heusler here is a d-spacing only |

### Distances

| Item | Current | Needed |
|---|---|---|
| L3 sample→analyser | **1.30 m**, the nominal value of a genuinely **variable** arm | ILL calls it "a variable sample-to-analyser distance of about 1.3 m"; Takin's preset uses **1.46 m**. Read 1.30 m as one setting, not as the arm length. The travel limits are unpublished — with them, L3 could become a descriptor-level choice. *needs IS* |

### Higher orders

The default source is the **broadband Maxwellian** branch, where `dE` sets
normalization rather than a sampling cutoff, so this model does **not** inherit
the real instrument's narrow incident band. `Monochromator_curved` at its
default `order=0` reflects at every multiple of the supplied reciprocal-lattice
vector, so a λ/2 component at four times the nominal energy would reach the
sample with nothing in the tree to stop it.

Both crystals are therefore pinned to **`order=1`**: this is an *idealized,
order-clean* cold TAS. The alternative — an effective filtered spectrum plus
the real secondary filtering (the Be filter, and a selector transmission
function) — is a different model, not a refinement of this one. No
contamination fraction has been measured here.

### Collimation, slits, filters

| Item | Current | Needed |
|---|---|---|
| α1 Soller | at L1/2, length 0.2 m, 30 × 150 mm | real position/length/aperture; ILL says a Soller *can* sit in the guide-exit section but nothing is permanently installed. *needs IS* |
| α2/α3/α4 Sollers | PLACEHOLDER positions, lengths and apertures | " |
| Pre-sample slit `sbl` | 30 × 60 mm at L2 − 0.25 | real diaphragm positions and openings. *needs IS* |
| Detector slit `dbl` | 50 mm wide at L4 − 0.03 | " |
| Cooled Be filter | **absent** | still in use post-upgrade, but there is no single position: published experiments put it in the **incident** beam (with the selector out) and **between sample and analyser**. It has no higher orders to remove here because `order=1` already excludes them (see *Higher orders* below). McCode's `Be.trm` — header: "Be transmission, as measured on IN12. T=80 K", B. Fåk — is what an order-transporting model would need |

### Detector

| Item | Current | Needed |
|---|---|---|
| Detector model | ideal `Monitor`, 50 × 120 mm | ³He pressure, gas mixture, wall construction and efficiency curve are all unpublished; matters only for absolute rates (PUMA and IN8 share this idealisation) |
| Beam monitor | not modeled | IN12 installed a new ²³⁵U incident-beam monitor in 2016, replacing a ³He one |

### Diagnostic monitors

Six monitors (source E/PSD, sample PSD/DSD/E, detector PSD) at arbitrary
beam-order positions — debugging aids, not surveyed hardware. Extend/move
freely.

### Deferred capabilities (design decisions, not data gaps)

- **IN12-UFO** — fifteen individually positioned analyser channels onto a 2-D
  detector. It reached real neutron commissioning: the 2016 CRG annual report
  describes commissioning work and corrected mechanical-stability and
  background problems, a 2018 JCNS contribution calls it "currently in a
  commissioning phase", and a 2023 ECNS instrument-status contribution
  describes it in the present tense as interchangeable with the standard
  secondary spectrometer. What could **not** be found is any peer-reviewed
  paper stating its data were taken with UFO, or evidence of routine user
  operation. ILL's surviving "will be equipped with" web wording is therefore
  stale rather than accurate. Excluding it from the conventional
  single-detector model is still correct — multi-analyser secondaries are out
  of scope for v1 (`docs/CONFIGURABLE_INSTRUMENTS.md` §14), the same call made
  for IN8's FlatCone/IMPS — but do not describe it as never built. If it is
  ever modeled it belongs in a separate descriptor.
- **Polarisation analysis (Cryopad, longitudinal)** — still actively supported
  on the instrument, including Mezei-flipper analysis with horizontal or
  vertical high fields. TAVI has no polarisation channel.
- **A second bent-perfect Si(111) monochromator** was proposed in 2023 and a
  September 2024 presentation planned installation in that reactor shutdown.
  The ILL characteristics page still lists only PG(002) and no commissioning
  report was found — **status unknown**. Bent-perfect crystals are not
  representable by the mosaic `Monochromator_curved` model anyway (the same
  blocker as IN8's Si faces).
- **The Endurance guide programme** (completed November 2024) does not appear
  to have touched H144: the completion material names the H15 project, and the
  Endurance brochure's mention of IN12 and a renovated H144 places that in the
  preceding **Millennium** programme (2008–2012). The current ILL page still
  publishes the 2016 flux and resolution figures unchanged.

---

## Validation record

- **Compiled McStas smoke run: passed** (2026-09-09, on the final tree). Step 8
  of `docs/INSTRUMENT_AUTHORING.md`, driven through the production path
  (`build` → `compute_snapshot` → `run_point`): Al (2,0,0) elastic at
  kf = 2.000 Å⁻¹ (E = 8.289 meV), 1e7 neutrons, every Soller open, ideal
  focusing. `detector_I = 4.21e-07`, `detector_N = 4334`, at
  A1 = A4 = −55.834°, A2 = 101.737°.
  The identical point through IN8 on the same tree gives `3.33e-07` / `4908` at
  its own thermal setting — the same order of magnitude, which is the check
  that matters here: a wrong-branch curvature costs ~7 orders of magnitude, so
  IN12's all-negative focusing (`sense_mono = sense_ana = −1`) is not
  defocusing. This is gross-geometry and execution evidence, not a flux
  calibration; the two instruments are at different energies on different
  sources and the numbers are not comparable beyond their order.
  The smoke also certifies what the Python suite cannot: the emitted tree, with
  withdrawn collimators and `order=1` on both crystals, still generates a
  `.instr` that compiles and counts.
- **Compiled McStas smoke run: passed** (2026-09-11, re-run on the
  `crystal-bending-generality` tree, same configuration: Al (2,0,0) elastic
  at kf = 2.000 Å⁻¹, 1e7 neutrons, all Soller collimators open, ideal
  focusing). `detector_I = 5.44329e-07`, `detector_N = 6901` — up from the
  2026-09-09 run above, the expected direction: the corrected monochromator
  images the real virtual source at L1 onto the sample instead of assuming a
  beam from infinity, so it focuses more strongly. The reported error is
  ~2-5% of the value, well outside Monte-Carlo scatter. This is
  gross-geometry and execution evidence, not a flux calibration.
- **Not yet done:** any independent resolution or intensity benchmark at
  matched settings. Until one exists this is a runnable, documented model of
  the post-upgrade conventional configuration, not a quantitatively validated
  reference.


## Priority for the next data pass

Now that the senses are settled, everything remaining is intensity or
resolution:

1. **The H144 exit spectrum**, or an MCPL file — dominates absolute flux, and
   nothing public exists.
2. Monochromator slab dimensions and gaps, and the mechanical curvature limits.
3. The analyser's true row count, crystal thickness, gaps, and an authoritative
   fixed vertical radius.
4. The sample→analyser travel range, which would make L3 a real descriptor
   choice rather than one frozen setting.
5. Collimator and diaphragm geometries — only matters once collimated modes are
   used, since every slot defaults to open.
6. Heusler blade geometry and how both focusing modes are obtained.
