# IN8 Model Status

> **Status:** live
> **Authority:** the state of the IN8 model: what is verified, approximated, and open

- Model version: **1.0.1**
- Model date: **2026-07-18**
- Runtime status: **runnable**
- Last evidence review: **2026-07-18**

Status of the IN8 model added in Phase 4 (`docs/CONFIGURABLE_INSTRUMENTS.md`
§20). The **kinematics are verified** — every item below affects intensity,
resolution, or capability, never the computed angles. Code locations:
`instruments/in8/plugin.py` (descriptor) and `instruments/in8/model.py`
(build); placeholders are marked `PLACEHOLDER` in-line.

Sources used so far: a live vTAS run (angles + senses + a3 convention), the
ILL IN8 characteristics page ("ILL"), Hiess et al. 2006 and Piovano & Ivanov
2023 in `instruments/in8/references/` ("2006"/"2023"), and the vTAS repository XML
("vTAS"). Anything marked *needs IS* wants instrument-scientist numbers or
drawings.

---

## Verified / trusted (for contrast)

| Item | Value | Source |
|---|---|---|
| Scattering senses | mono +1, sample +1, analyzer −1 | live vTAS run 2026-07-02 |
| a3 convention | Friedel/−Q branch (±90° cubic setting jumps in vTAS readouts) | live vTAS run |
| Axis limits | A1 11…90°, A2/A4 ±120° | ILL characteristics (A1); vTAS (A2/A4) |
| Arm lengths | L1–L4 = 2.28 / 2.48 / 1.05 / 0.70 m | ILL (current Thermes) |
| Crystal d-spacings | PG002 3.355 Å, Cu200 1.807 Å | vTAS crystal table |
| Detector opening | 42 × 89 mm | ILL |
| Mono PG002 face | 11×11 of 25×17 mm (≈290×202 mm), mosaic 30′ | 2006 (slabs) + 2023 (11×11) + ILL (mosaic) |
| Cu200 mosaic | 25′ horizontal × 10′ vertical | ILL characteristics |

Note on distances: vTAS says 2.5/1.35/0.65 — deliberately not used (design
decision, §20.3); if vTAS-identical resolution ever matters, that's a
3-number descriptor edit.

---

## Missing / placeholder, by section

### Source (largest intensity uncertainty)

| Item | Current | Needed |
|---|---|---|
| Virtual source height | 0.120 m guess | real HVS aperture (2006: adjustable, < 50 mm wide; height unstated). *needs IS* |
| Virtual source width per crystal | 0.030 m for all | ILL: 30 mm for PG/Cu but **25 mm for Si** — per-crystal width once Si lands |
| Spectrum | `Source_div_Maxwellian_v2` peaked at E0 | true H10 thermal spectrum (T, brightness) for absolute flux. *needs IS* |
| Upstream optics | nothing before the virtual source | beam tube Φ200 mm / in-pile geometry only matters for background realism |
| L1 precision | 2.28 m (ILL page) | 2006 paper says 2284 mm — 4 mm difference, cosmetic |

### Monochromator

| Item | Current | Needed |
|---|---|---|
| Cu200 reflectivity | constant r0 = 0.7 via `"NULL"` sentinel | measured Cu(200) reflectivity (no stock McStas .rfl). *needs IS* |
| Slab gap | 1.5 mm (derived so 11×25 mm + gaps = 290 mm) | drawing value |
| Si(111)/Si(311) faces | **absent** | bent-perfect crystals are not representable by the mosaic `Monochromator_curved` model — needs a different component (e.g. perfect-crystal + curvature). Deferred capability, not a data gap |
| Bending clamps | none | IN8 mechanical min/max radii. *needs IS* |
| Take-off range | **11…90° enforced** (ILL characteristics: 11° < 2θ_M < 90°) | reconciled 2026-09-09. The 2023 paper gives ≈10–90°; the tighter currently-published envelope is enforced rather than averaging the two into a guess. The 1° disagreement at the lower end stands open. *needs IS to settle 10° vs 11°* |

### Analyzer (Thermes)

| Item | Current | Needed |
|---|---|---|
| PG002 subdivision | 9×7 of 20×20 mm guessed (≈184×143 vs 180×140 real) | actual slab count/size. *needs IS* |
| Mosaic | 30′ assumed (copied from mono) | measured analyzer mosaic |
| rva magnitude | driven (operator ruling, 2026-09-11: the Thermes analyser is variable double-focusing and the hardware tracks it with a motor). AUTOFOCUS now computes it from the same point-source formula as rha, tracking kf like rha does; the old fixed 0.31 placeholder is gone | none pending on drivenness/tracking; the analyzer subdivision/mosaic guesses above still need IS |
| Cu200 / Si111 analyzers | absent | ILL lists both; same blockers as the mono equivalents |

### Collimation and slits (all geometry is placeholder)

| Item | Current | Needed |
|---|---|---|
| α2 Soller | at L2/2, length 0.2 m, 50×150 mm | real position/length/aperture. *needs IS* |
| α3 Soller | at 0.7 m after sample, 0.2 m, 50×250 mm | " |
| α4 Soller | at 0.3 m after analyzer, 0.15 m, 50×100 mm | " |
| α1 Soller | present; at L1/2, length 0.2 m, aperture = HVS envelope | ILL describes collimators before *and* after the mono (and before and after the analyser), so the slot exists; its position/length/aperture are placeholders. *needs IS* |
| Pre-sample slit `sbl` | 40×100 mm at L2 − 0.35 | real position + default gaps |
| Detector slit `dbl` | 40 mm wide at L4 − 0.03 | " |

### Filters

| Item | Current | Needed |
|---|---|---|
| PG filter | ONE 5 cm `Filter_graphite` at 0.5 m after the sample, 0.3×0.3 m, always in beam | 2023: TWO ~5 cm PG filters; positions, apertures, and in/out switching (should probably become a descriptor module) |
| Be filter | absent | ILL lists a Be-filter mode (fixed Ef = 4.5 meV, transfers to 120 meV) — separate capability |

### Detector

| Item | Current | Needed |
|---|---|---|
| Detector model | ideal `Monitor`, 42×89 mm | real single 3He tube efficiency/pressure if absolute rates matter (PUMA has the same idealization) |

### Diagnostic monitors

Six monitors (source E/PSD, sample PSD/DSD/E, detector PSD) at arbitrary
beam-order positions — debugging aids, not surveyed hardware. Extend/move
freely.

### Deferred capabilities (design decisions, not data gaps)

- **FlatCone** (31 Si(111) analyzers, fixed kf = 3 Å⁻¹, 31 detectors) and
  **IMPS** (9 analyzer blades) — multiplexed secondary spectrometers,
  explicitly out of scope for v1 (`docs/CONFIGURABLE_INSTRUMENTS.md` §14);
  vTAS carries IN8-IMPS as a separate instrument block if ever needed.
- Brillouin low-angle vacuum box, sample environments — not modeled.

---

## Validation record

- **Compiled McStas smoke run: passed** (2026-09-11, on the `crystal-bending-
  generality` tree). Driven through the production path (`build` →
  `compute_snapshot` → `run_point`): Al (2,0,0) elastic at kf = 2.662 Å⁻¹,
  1e7 neutrons, all Soller collimators open, ideal focusing.
  `detector_I = 5.07902e-07`, `detector_N = 11455`. The previous recorded run
  at this same configuration (cited as the cross-instrument control in
  IN12's and PANDA's own Validation records) gave `3.33e-07` / `4908` — this
  run gained flux, the expected direction for this branch: the corrected
  monochromator images the real virtual source at L1 onto the sample instead
  of assuming a beam from infinity, so it focuses more strongly. The reported
  error is ~2-5% of the value, well outside Monte-Carlo scatter. This is
  gross-geometry and execution evidence, not a flux calibration.

---

## Priority guess for the next data pass

1. Virtual source aperture + spectrum (dominates absolute intensity).
2. Analyzer subdivision + mosaic (resolution); rva now tracks kf.
3. Collimator geometries (only matters once collimated modes are used —
   default is open/double-focused).
4. Second PG filter + filter switching.
5. Cu200 reflectivity (only when the Cu branch is used; the mosaic is now
   ILL's published 25′×10′).
