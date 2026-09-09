# IN12 Model Status

- Model version: **1.0.0**
- Model date: **2026-09-09**
- Runtime status: **runnable**
- Last evidence review: **2026-09-09**

Status of the IN12 model, promoted from a research package to a runnable one on
2026-09-09. Unlike IN8, **the kinematics are NOT verified**: IN8's senses were
settled by a live vTAS run, and no equivalent readback exists for IN12. The
sense assignment is the one place where this model can be wrong about *angles*,
not merely intensity. Everything else below affects intensity, resolution, or
capability.

Code locations: `instruments/in12/plugin.py` (descriptor) and
`instruments/in12/model.py` (build); placeholders are marked `PLACEHOLDER`
in-line.

Sources: the current ILL IN12 characteristics and instrument-layout pages
("ILL", re-checked 2026-09-09 —
`references/2026-09-09__ill-in12-web-status__v01.md`), Schmalzl et al. NIM A 819
(2016) 89–98 ("2016" — `references/2016-01-01__schmalzl-in12-upgrade__v01.md`),
a historical 2001 IN12 raw scan header and the 2010 vTAS instrument repository
(both via `references/2026-07-18__in12-research-dossier__v01.md`). Anything
marked *needs IS* wants instrument-scientist numbers or drawings.

**We never received files from the instrument team.** This model is built from
public documentation alone; the whole of `SCIENTIST_REVIEW.md` is still open.

---

## Verified / trusted

| Item | Value | Source |
|---|---|---|
| Axis limits | mono 2θ −140…−10°, sample ±120°, analyser ±140° | ILL (re-confirmed 2026-09-09) |
| Arm lengths | L1 = 1.80, L3 ≈ 1.30, L4 = 0.72 m | ILL |
| L2 | 1.80 m | 2016 (matched to L1 for Rowland focusing); **no live ILL page states it** |
| Monochromator array | PG(002), 11 × 11 over 200 × 160 mm, mosaic 24′ (0.4° FWHM) | 2016 + ILL (array and face re-confirmed 2026-09-09; mosaic is 2016 only) |
| Mono curvature limits | horizontal ≥ 1.7 m to flat; vertical ≥ 0.5 m to flat | 2016 |
| Analyser faces | PG(002) 122 × 118 mm; Heusler(111) 75 × 145 mm, d = 3.44 Å | ILL |
| Crystal d-spacings | PG(002) 3.355 Å | 2016 / 2001 scan header |
| Collimators | Gd Soller 10/20/30/40/60/80′, mountable at four positions | ILL |
| Detector | one vertical ³He tube, 12 cm high × 5 cm ⌀ | ILL |
| Guide exit / virtual source | 20 mm wide × 140 mm high, 1.8 m from the mono | 2016 |
| Operating envelope | λ 1.26–6.3 Å, ki 1.0–5.0 Å⁻¹, Ei 2.1–42 meV | ILL |

---

## The sense assignment — the one open kinematic risk

| Sense | Value | Evidence | Confidence |
|---|---|---|---|
| Monochromator | **−1** | ILL publishes the mono two-theta range as −140°…−10°, entirely negative; the 2012 upgrade put the new monochromator on the clockwise branch | strong |
| Sample | **+1** | a 2001 IN12 raw scan header (`SS = +1`) | weak — predates the upgrade, and a 2010 vTAS repository entry says −1 instead |
| Analyser | **−1** | the same 2001 header (`SA = −1`), plus the 2012 upgrade retaining the secondary spectrometer | moderate |

IN12 is the first TAVI instrument with `sense_mono = −1`, so it is also the
first exerciser of that path through the shared angle solver.

**What would settle it:** one current NOMAD or raw IN12 scan header showing all
six angles, or a live vTAS run against the IN12 entry — exactly how IN8's senses
were fixed on 2026-07-02. Until then, treat IN12 angle *signs* as provisional
and the magnitudes as sound (they depend only on d-spacings and arm geometry).

---

## Missing / placeholder, by section

### Source (largest intensity uncertainty)

| Item | Current | Needed |
|---|---|---|
| Model boundary | effective source AT the H144 exit; 115 m of guide not modeled | a real H144 model or an MCPL file at the exit. The 2016 upgrade study used one; it is not public and was not found. *needs IS* |
| Spectrum | `Source_div_Maxwellian_v2` peaked at E0, dE = 2 meV | the true H1 cold-source spectrum at the H144 exit for absolute flux. Note 2016 measured ~30 % more capture flux than the contemporary McStas cold-source description predicted. *needs IS* |
| Velocity selector | **absent** | it sits >36 m upstream, outside the model boundary. With the source emitting a narrow band around E0 there are no higher orders for it to suppress, so modelling it would only attenuate. Revisit if a real guide/spectrum model lands |
| Polarising cavity, guide fields, flippers | **absent** | ~35 m upstream, and TAVI models no polarisation at all |

### Monochromator

| Item | Current | Needed |
|---|---|---|
| Slab width/height | 16.8 × 13.2 mm, derived as face/11 minus a 1.5 mm gap | actual crystal dimensions. *needs IS* — nothing published |
| Slab gap | 1.5 mm PLACEHOLDER | drawing value |
| Crystal thickness/backing | not modeled (2016 gives 2.0 mm PG on 2.3 mm B₄C + 3 mm Al) | only matters for transmission/background realism |
| Mosaic | 24′ isotropic | 2016 gives 0.4° FWHM without splitting horizontal/vertical |
| Curvature sign convention | both radii negated onto the −1 take-off branch | 2016 says both axes are continuously motorised; the *motor* sign convention should be checked at more than one real setting. *needs IS* |

### Analyser

| Item | Current | Needed |
|---|---|---|
| PG subdivision | 11 columns × 1 row of 9.7 × 118 mm, gap 1.5 mm | confirmation that the retained secondary still has 11 blades in one row, and their real size/gap. *needs IS* |
| PG mosaic | 30′, the 2001 header's `ETAA` | a post-upgrade measurement (historical sources say 30–35′) |
| Vertical curvature | flat (`rva = 0`) | ILL lists it as fixed, not zero; a one-row assembly has no vertical focusing to drive, so flat is the honest model, but the fixed value is unknown |
| Horizontal curvature limits | none | allowed radius range. *needs IS* |
| Heusler(111) geometry | PLACEHOLDER 5 columns × 1 row of 13.8 × 145 mm, mosaic 30′, constant r0 = 0.3 via the `"NULL"` sentinel | blade count, size, gap, mosaic, reflectivity. **Sources conflict on its focusing axis**: the 2016 paper describes a vertically focusing Heusler in one place and a "tall, horizontally focusing" one in another. *needs IS* |
| Polarisation | not modeled | TAVI has no polarisation channel; Heusler here is a d-spacing only |

### Collimation, slits, filters

| Item | Current | Needed |
|---|---|---|
| α1 Soller | at L1/2, length 0.2 m, 30 × 150 mm | real position/length/aperture; ILL says a Soller *can* sit in the guide-exit section but nothing is permanently installed. *needs IS* |
| α2/α3/α4 Sollers | PLACEHOLDER positions, lengths and apertures | " |
| Soller clear apertures | assumed | published blade lengths and apertures |
| Pre-sample slit `sbl` | 30 × 60 mm at L2 − 0.25 | real diaphragm positions and openings. *needs IS* |
| Detector slit `dbl` | 50 mm wide at L4 − 0.03 | " |
| Cooled Be filter | **absent** | McCode's `Be.trm` is a transmission curve measured on IN12 at 80 K and is available — but with a narrow-band source there are no higher orders to remove, so a filter would only attenuate. Add it if a broadband source model lands. The 2026-09-09 check could not confirm the filter is in current routine use |

### Detector

| Item | Current | Needed |
|---|---|---|
| Detector model | ideal `Monitor`, 50 × 120 mm | real ³He tube pressure/efficiency if absolute rates matter (PUMA and IN8 have the same idealisation) |

### Diagnostic monitors

Six monitors (source E/PSD, sample PSD/DSD/E, detector PSD) at arbitrary
beam-order positions — debugging aids, not surveyed hardware. Extend/move
freely.

### Deferred capabilities (design decisions, not data gaps)

- **IN12-UFO** — fifteen individually positioned analyser channels onto a 2-D
  detector. ILL's own layout page still says IN12 "will be equipped with" it,
  and no 2020–2026 publication reports it commissioned (checked 2026-09-09).
  Multi-analyser secondary spectrometers are out of scope for v1 regardless
  (`docs/CONFIGURABLE_INSTRUMENTS.md` §14), the same call made for IN8's
  FlatCone/IMPS. If it is ever built, it belongs in a separate descriptor.
- **Variable L3** — ILL calls the sample–analyser arm variable but publishes no
  limits, so it is fixed at 1.30 m. Making it scannable is a descriptor change
  once the range is known.
- **Polarisation analysis (Cryopad, longitudinal)** — TAVI has no polarisation
  channel.
- **The Endurance guide programme** (completed November 2024) touched the guide
  hall carrying H144. No IN12-specific before/after figures were found, so it is
  unknown whether the flux numbers above are pre- or post-Endurance.

---

## Priority guess for the next data pass

1. **One modern raw scan header** — settles all three senses, the only
   angle-affecting unknown. Everything else is intensity or resolution.
2. Monochromator and analyser slab dimensions and gaps (resolution and peak
   intensity; currently derived, not measured).
3. The H144 exit spectrum or an MCPL file (dominates absolute flux).
4. Analyser mosaic and horizontal curvature range.
5. Collimator and diaphragm geometries (only matters once collimated modes are
   used — every slot defaults to open).
6. Heusler blade geometry and its focusing axis.
