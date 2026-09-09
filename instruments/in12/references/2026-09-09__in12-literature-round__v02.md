# IN12 literature round — 2026-09-09 (v02)

A second 2026-09-09 evidence pass, run after
[the web status check](2026-09-09__ill-in12-web-status__v01.md) and before the
IN12 package was merged. Where v01 re-read the live ILL pages, this round
searched the *published* record — the 2016 paper, ILL annual reports, JCNS
material, theses, experiment methods sections, and public instrument-software
parameter files — specifically to resolve the items the model was guessing at.

Two results changed the model. One changed nothing but promoted a guess to a
fact. One claimed correction was checked and rejected.

---

## 1. Scattering senses — RESOLVED, and the model was right

**`SM = −1, SS = +1, SA = −1`** in the convention where `+1` = left /
counter-clockwise, which is the convention the ILL SICS/TAS-MAD instrument
variables use.

Three independent lines agree:

1. **ILL's published monochromator travel** is entirely negative,
   −140° < 2θ_M < −10°. Strong but, strictly, not proof: a motor coordinate and
   the logical `SM` metadata need not share a sign, since software may apply
   offsets or inversions.
2. **The public Takin resolution preset**
   `data/instruments/in12_pg002_pg002.taz` (ILLGrenoble/takin) stores
   `mono_scatter_sense = 0`, `sample_scatter_sense = 1`,
   `ana_scatter_sense = 0` — monochromator and analyser on one branch, sample
   on the other. That is the **W configuration**, which ILL's own IN12
   documentation names for the instrument.
3. **H. Trepka, PhD dissertation, Stuttgart 2022** reports an actual
   post-upgrade IN12 configuration explicitly as `SM = −1, SS = 1, SA = −1`
   (kf = 1.3 Å⁻¹, double-focusing monochromator and analyser, Be filter).

A fourth source that *looks* contradictory is not. Brüning's IN12 RESCAL table
gives `SM = +1, SS = −1, SA = +1`, but legacy ResCal defines `+1 = right`, the
reverse of the SICS/raw-file convention. Normalised, it describes the identical
geometry: right–left–right.

No anonymously retrievable post-2012 raw IN12 file header exposing SM/SS/SA was
found. The evidence above is sufficient without one.

## 2. Distances

| Quantity | Value | Source |
|---|---|---|
| L1 guide exit → mono | **1.800 m** | Schmalzl 2016, "Monochromator": the monochromator centre is 1.8 m after the guide end |
| L2 mono → sample | **1.800 m** | the same passage: the sample sits at the same 1.8 m for ideal Rowland focusing |
| L3 sample → analyser | **variable, nominally ~1.3 m** | current ILL description explicitly calls it "a variable sample-to-analyser distance of about 1.3 m". The public Takin preset uses **1.46 m** |
| L4 analyser → detector | **0.720 m** | ILL; 72 cm in the Takin preset |
| Sample goniometer | **±20°** | ILL characteristics |

L2 was previously an inference from the Rowland argument; the paper states it
outright. **L3's travel limits remain unpublished** — 1.46 m is evidence that
1.30 m must not be presented as *the* arm length.

## 3. Monochromator

- **PG(002), 11 × 11, 20 cm wide × 16 cm high** — confirmed; the Takin preset
  independently encodes `mono_w = 20 cm`, `mono_h = 16 cm`, settling the
  orientation the ILL characteristics table muddles under a "height × width"
  heading.
- **Mosaic 0.4° = 24′ FWHM** — confirmed as the physical crystal mosaic (a
  thesis describing post-upgrade IN12 reproduces it, citing Schmalzl). The
  Takin preset's 33′ is an *effective* resolution parameter, not metrology.
- **Crystal thickness 2.0 ± 0.1 mm** — confirmed; Takin uses 0.2 cm.
- **Individual slab width/height, and every inter-crystal gap** — **not found**.
  No drawing, supplier datasheet or thesis gives the 121 crystal dimensions.
- **B₄C 2.3 mm + aluminium 3 mm backing** — not found outside the original
  claim.
- **Curvature limits (~1.7 m horizontal, ~0.5 m vertical, to flat) and the
  focusing-motor sign convention** — **not found**. ILL says only that both
  axes are variable. The Takin preset uses a vertical radius of 1.20 m in its
  saved setup, which demonstrates a setting, not a limit.

## 4. Analyser — the substantive correction

**The conventional PG(002) analyser is not eleven blades in one row, and it is
not vertically flat.**

W. Schmidt and B. Fåk, **"New focusing analyser on IN12", ILL Annual Report
1998**, describes it as built:

- **eleven vertical lamellae**, lamella width **11 mm**;
- motorised **variable horizontal focusing**;
- **fixed vertical focusing, produced by tilting the top and bottom crystal
  rows** (the report's Fig. 1 says the tilt is visible);
- PG(002) mosaic **about 0.5°**;
- complete assembly approximately **125 × 125 mm²**;
- mechanics by Ingenieurbüro Stronciwilk, Berlin.

The 2010–2012 project rebuilt the **primary** spectrometer, so this secondary
hardware description is the one that still governs. Current ILL active
dimensions are 12.2 × 11.8 cm².

Tilting a *top and bottom row* requires at least three rows. Eleven 11 mm
lamellae span 121 of the 122 mm active face, so the crystals are effectively
butted.

**Fixed vertical radius:** the Takin preset encodes `pop_ana_curvv = 140 cm`
with `pop_ana_use_curvv = 1` (and horizontal curvature disabled in that saved
setup). 1.40 m is therefore *probable*, from a resolution preset rather than a
mechanical drawing. Note it is deliberately far from the point-source Rowland
radius for L3/L4 (~0.43 m at a typical take-off) — which is what a *fixed*
focus looks like: correct at one setting only.

**Mosaic:** 1998's ~0.5° = 30′ is better supported as the nominal physical
value than the 2001 scan header's 35′; Takin's 33′ is again effective.

Post-upgrade experiments confirm both focusing modes are used in anger: some
run with vertical focusing on and horizontal off, and a 2015 CeCo(In,Cd)₅
experiment deliberately ran the PG analyser flat to cut background.

**Not found:** crystal thickness, inter-crystal gaps, and the complete
row/piece inventory.

## 5. Heusler(111) — the "conflict" is not a conflict

7.5 × 14.5 cm², d = 3.44 Å — confirmed on the ILL characteristics page.

The focusing axis is **configuration-dependent**, not a source error:

- horizontally focusing: a 2014 *Nature Communications* IN12 experiment
  (flipping ratio ≈ 17.4) and a 2025 *PRB* IN12 experiment (kf = 1.8 Å⁻¹,
  flipping ratio ≈ 22);
- vertically focusing: a 2024 *PRX Life* supplemental methods section
  (flipping ratio 24).

No public construction note says whether this is one reconfigurable assembly or
two interchangeable ones; ILL says only "curved Heusler". Blade count, blade
dimensions, gaps, mosaic and reflectivity are all **not found**.

## 6. Velocity selector — most of the detail is unconfirmed

Confirmed from Schmalzl 2016 and the current ILL description: **Astrium GmbH**,
**>36 m upstream** of the guide end, **fully movable in/out**, **design range
2.23–6.3 Å** with no forbidden speeds in that window, and directly followed by
the guide changer / polarising cavity.

**Not confirmed for the IN12 unit:** 60 blades, 23.9° helix, Δλ/λ ≈ 25 %, 83 %
transmission at 4 Å, rotor diameter, rotor length, speed range, and the
wavelength↔rpm calibration. Detailed Astrium selector data does exist in the
literature, but for clearly different 72-blade / 48.3° devices that must not be
transplanted onto IN12. The v01 dossier's selector detail should be treated as
unsourced until the instrument team confirms it.

(The ILL flux figures give 8.4×10⁷ with the selector against 1.04×10⁸ without,
about 81 %, but that is not a clean intrinsic transmission measurement.)

## 7. Beryllium filter — optional and position-dependent

A cooled Be filter is definitely still usable post-upgrade, but there is no
single "the filter position": Trepka's post-upgrade experiment used one; a
recent UTe₂ experiment ran **without** the velocity selector and put a Be
filter in the **incident** beam; another experiment reports a cooled Be filter
**between sample and analyser**.

Omitting it from a baseline model of the normal selector configuration is
reasonable.

**One claimed correction here was checked and rejected.** The suggestion that
the McStas transmission table measured on IN12 is `BeO.trm` rather than
`Be.trm` is wrong for the installed McStas 3.x resources. The shipped file is
`data/Be.trm`, whose header reads: *"Be transmission, as measured on IN12.
T=80 K. Thickness: 0.05 [m]. From: B. Fåk (CEA/ILL)."* There is no `BeO.trm`
in the data directory at all (`Be.trm`, `HOPG.trm` and
`Al2O3_sapphire.trm` are the only `.trm` files). Presumably an older McStas
document listed it differently.

## 8. Detector

Single vertical ³He tube, **12 cm high × 5 cm diameter** — confirmed on the ILL
characteristics page and independently in the Takin preset.

**Not found:** ³He pressure, fill-gas mixture, wall material and thickness,
efficiency versus wavelength, and the precise active length.

One adjacent post-upgrade change: in 2016 IN12 installed a new **²³⁵U incident
beam monitor**, replacing an older ³He monitor. That is the monitor, not the
secondary detector.

## 9. IN12-UFO — built and commissioned, but no published routine use

This is a correction to the v01 reading. UFO was **not** merely an unbuilt
proposal:

- the **IN12 2016 CRG annual report** says development focused on commissioning
  the multi-analyser / multi-detector UFO, that several neutron tests had been
  performed, and that mechanical-stability and background problems had been
  identified and corrected; first science experiments were planned for 2018;
- a **2018 JCNS conference contribution** says UFO was "currently in a
  commissioning phase";
- **K. Schmalzl's 2023 ECNS instrument-status contribution** describes UFO in
  the present tense as *interchangeable with the standard secondary
  spectrometer*, capable of programmed simultaneous Q–ω scans.

What is **not found**: any peer-reviewed paper stating its data were measured
with IN12-UFO, and any evidence of routine user operation comparable to the
conventional secondary.

The ILL web page's surviving "will be equipped" wording is therefore stale, not
an accurate current status. Excluding UFO from a conventional single-detector
model remains correct — but it should not be described as never built.

## 10. Post-2016 changes

- **Endurance did not evidently touch H144.** The official completion material
  discusses the H15 guide project (February 2024, feeding D007, D11+, SAM,
  SHARPER) and does not name H144 or IN12. The Endurance brochure's mention of
  IN12 and a renovated H144 places that in the *preceding* **Millennium**
  programme (IN12, 2008–2012). No IN12-specific post-Endurance flux or
  resolution measurement was found, and the current ILL page still publishes
  exactly the 2016 figures.
- **A second bent-perfect Si(111) monochromator** was proposed in the 2023
  instrument-status presentation, and a September 2024 presentation planned
  installation "in this reactor shutdown". The current ILL characteristics page
  still lists only PG(002), and no 2025–2026 commissioning report was found.
  **Installation status unknown.**
- **Polarisation** remains actively supported: longitudinal and spherical
  analysis, Cryopad, fields to 15 T, and Mezei-flipper polarisation analysis
  with horizontal or vertical high fields (2024 presentation).
- **MIEZE / NRSE / spin-echo on IN12** — not found; apparently absent.
- **New main ³He detector** — not found.

## 11. Public simulation models

**A post-upgrade public parameter model does exist**, which v01 missed: the
Takin repository ships `data/instruments/in12_pg002_pg002.taz`
(github.com/ILLGrenoble/takin), citing Schmalzl 2016 and current ILL
documentation. Verified directly. Its contents:

```text
pop_dist_src_mono    180 cm      pop_mono_w        20 cm
pop_dist_mono_sample 180 cm      pop_mono_h        16 cm
pop_dist_sample_ana  146 cm      pop_mono_curvv    120 cm  (use_curvv 1)
pop_dist_ana_det      72 cm      pop_mono_curvh      0     (use_curvh 0)
                                 pop_mono_thick    0.2 cm
pop_ana_w          12.2 cm       mono_d            3.355 A
pop_ana_h          11.8 cm       mono_mosaic       33'
pop_ana_curvv       140 cm  (use_curvv 1)
pop_ana_curvh         0    (use_curvh 0)          pop_det_w   5 cm
ana_d              3.355 A       ana_mosaic 33'   pop_det_h  12 cm

mono_scatter_sense 0   sample_scatter_sense 1   ana_scatter_sense 0
```

It is a resolution parameter set, not a ray-tracing model.

Schmalzl 2016 states that the new guide was calculated with **McStas** and the
whole primary spectrometer with **SIMRES plus in-house routines**, so full
internal models certainly existed. None is publicly obtainable:

- post-upgrade IN12 or H144 McStas `.instr` — **not found**;
- public SIMRES or RESTRAX input — **not found**;
- MCPL dump or tabulated phase space at the H144 exit — **not found**.

The publicly documented McStas IN12 example is the old one; the McStas manual
describes it as the **2005** configuration built from drawings, confirming that
`ILL_H142_IN12` must not be read as the post-2012 machine.

On the guide itself, the public record does support the modelled geometry: IN12
sits ~115 m from the vertical cold source; the last ~80 m runs at R = −2000 m
with a 45 × 105 mm cross-section and an m = 2.4 outer concave wall; the final
8 m widens 105 → 140 mm vertically and focuses 45 → 20 mm horizontally with
side coating rising to m = 3.2. The upstream 6 m at R = 2700 m and ~21 m at
R = 4000 m are better described as the **common H14 guide system** shared before
the four H14 branches split, not as H144 specifically.

The 20 × 140 mm effective exit source is therefore geometrically well founded,
and the absence of any public exit spectrum or divergence correlation confirms
that the source model is the dominant remaining uncertainty in absolute
intensity.

---

## What this round changed in the model

1. Senses promoted from provisional to **confirmed**; no numeric change.
2. Conventional PG analyser changed from **11 × 1, vertically flat** to
   **11 × 3 with a fixed vertical radius of 1.40 m**, with the 11 mm lamella
   width now driving the geometry and the gap derived from it.
3. L3 re-described as one setting of a variable arm rather than the arm length.
4. IN12-UFO re-described as commissioned-but-not-in-published-routine-use
   rather than never built.
5. Heusler focusing re-described as configuration-dependent rather than a
   source conflict.
6. `Be.trm` retained after checking the installed McStas resources.

## Now worth asking the instrument team rather than the literature

Monochromator individual crystal dimensions and gaps; the B₄C/aluminium backing
dimensions; mechanical curvature limits and focusing-motor sign conventions;
the actual sample→analyser travel; analyser crystal gap, thickness and full row
inventory; an authoritative fixed vertical radius for the analyser; Heusler
blade geometry and how both focusing modes are obtained; the selector's rotor
geometry, blade count and rpm↔λ calibration; ³He detector pressure, gas mixture
and efficiency; the standard Be-filter position; a post-2012 raw file header;
a post-upgrade H144/IN12 McStas or SIMRES model and an exit MCPL file; whether
the Si(111) monochromator was commissioned after the 2024 shutdown; and any
IN12-specific Endurance before/after numbers.
