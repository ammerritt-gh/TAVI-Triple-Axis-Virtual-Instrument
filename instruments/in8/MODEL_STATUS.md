# IN8 Model Status

- Model version: **1.0.0**
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
| Axis limits | A1 −40…110°, A2/A4 ±120° | vTAS (2023 gives take-off 10–90° — see below) |
| Arm lengths | L1–L4 = 2.28 / 2.48 / 1.05 / 0.70 m | ILL (current Thermes) |
| Crystal d-spacings | PG002 3.355 Å, Cu200 1.807 Å | vTAS crystal table |
| Detector opening | 42 × 89 mm | ILL |
| Mono PG002 face | 11×11 of 25×17 mm (≈290×202 mm), mosaic 30′ | 2006 (slabs) + 2023 (11×11) + ILL (mosaic) |

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
| Cu200 mosaic | isotropic 25′ | anisotropic 25′(h) × 10′(v) — `Monochromator_curved` takes one mosaic; either accept or use mosaich/mosaicv if the component supports it. *needs IS for measured values* |
| Cu200 reflectivity | constant r0 = 0.7 via `"NULL"` sentinel | measured Cu(200) reflectivity (no stock McStas .rfl). *needs IS* |
| Slab gap | 1.5 mm (derived so 11×25 mm + gaps = 290 mm) | drawing value |
| Si(111)/Si(311) faces | **absent** | bent-perfect crystals are not representable by the mosaic `Monochromator_curved` model — needs a different component (e.g. perfect-crystal + curvature). Deferred capability, not a data gap |
| Bending clamps | none | IN8 mechanical min/max radii. *needs IS* |
| Take-off range | vTAS −40…110° | 2023 paper: 10–90° mechanical for Thermes — reconcile which envelope to enforce |

### Analyzer (Thermes)

| Item | Current | Needed |
|---|---|---|
| PG002 subdivision | 9×7 of 20×20 mm guessed (≈184×143 vs 180×140 real) | actual slab count/size. *needs IS* |
| Mosaic | 30′ assumed (copied from mono) | measured analyzer mosaic |
| rva magnitude | fixed 0.31 (point-source value at kf 2.662) in `scan_config` | Thermes is variable double-focusing — should track kf like rha does; small code change once real behavior is known |
| Cu200 / Si111 analyzers | absent | ILL lists both; same blockers as the mono equivalents |

### Collimation and slits (all geometry is placeholder)

| Item | Current | Needed |
|---|---|---|
| α2 Soller | at L2/2, length 0.2 m, 50×150 mm | real position/length/aperture. *needs IS* |
| α3 Soller | at 0.7 m after sample, 0.2 m, 50×250 mm | " |
| α4 Soller | at 0.3 m after analyzer, 0.15 m, 50×100 mm | " |
| No α1 slot | assumed correct (primary collimation sits after the mono on IN8) | confirm. *needs IS* |
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

### GUI wart (code follow-up, not data)

The "Ideal:" bending labels in the controller still use PUMA's parallel-beam
mono formula and unsigned magnitudes; IN8's own
`calculate_crystal_bending` (point-source both sides, branch-signed) is
correct and used by scans, but the advisory labels don't call it yet.

---

## Priority guess for the next data pass

1. Virtual source aperture + spectrum (dominates absolute intensity).
2. Analyzer subdivision + mosaic and kf-tracked rva (resolution).
3. Collimator geometries (only matters once collimated modes are used —
   default is open/double-focused).
4. Second PG filter + filter switching.
5. Cu200 reflectivity/mosaic (only when the Cu branch is used).
