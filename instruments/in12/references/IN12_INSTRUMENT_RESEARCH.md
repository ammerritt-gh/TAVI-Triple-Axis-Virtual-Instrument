# IN12 Instrument Research Dossier

**Instrument:** IN12, cold-neutron triple-axis spectrometer  
**Facility:** Institut Laue-Langevin (ILL), Grenoble  
**Operation:** Forschungszentrum Jülich in collaboration with CEA Grenoble, CRG-B  
**Purpose:** Background research for a future TAVI instrument-catalogue descriptor  
**Research date:** 18 July 2026

## 1. Executive summary

The present IN12 is the post-2012 instrument on the H144 supermirror guide. Its primary spectrometer was comprehensively rebuilt: the old H142 guide and vertically focused monochromator were replaced by an H144 virtual-source system and a large, independently double-focused 11 × 11 PG(002) monochromator. The secondary spectrometer was substantially retained, which makes the surviving older McStas model useful for analyzer and detector geometry but unreliable for the current source, guide, monochromator, primary distance, and probably the monochromator sense.

The most useful discoveries for eventual TAVI authoring are:

1. A complete official historical McStas model exists in McCode under `ILL_H142_IN12`. It includes an IN12 wrapper, the old H142 guide, and the generic TAS template.
2. McCode includes `Be.trm`, a beryllium-filter transmission curve explicitly measured on IN12 at 80 K.
3. An older downloadable vTAS package contains `templateTAS.instr`, `templateUFO.instr`, and an embedded IN12/IN12-UFO geometry repository.
4. The 2016 upgrade paper provides unusually detailed current monochromator, guide, selector, and polarizer specifications.
5. The probable current TAVI senses are `[-1, +1, -1]` for monochromator, sample, and analyzer respectively, but only the monochromator sense is strongly established from post-upgrade documentation. A modern raw scan or confirmation from the instrument team is still required.
6. The principal remaining catalogue blockers are individual crystal dimensions and gaps, current analyzer blade specifications and mosaic, exact variable `L3` limits, and authoritative current control-system senses.

## 2. Instrument identity and scientific role

IN12 is a cold-neutron three-axis spectrometer used for low-energy magnetic excitations, low-frequency lattice dynamics, critical scattering, phase transitions, weak magnetic moments, thin films and multilayers, amorphous materials, and biological model membranes. It supports conventional unpolarized operation, longitudinal polarization analysis, and spherical polarization analysis with Cryopad.

Available sample environments include high and low temperatures, including \(^3\)He and dilution inserts, high pressure, electric fields, magnetic fields up to 15 T, vacuum tanks, and polarization-analysis equipment. The [current ILL instrument description](https://www.ill.eu/en/for-ill-users/instruments/instruments-list/in12/) emphasizes the combination of high flux, low background, low higher-order contamination, and tunable resolution.

The old instrument was shut down in October 2010. The rebuilt IN12 returned to user operation at the end of 2012. The detailed upgrade was published as K. Schmalzl *et al.*, “The upgraded cold neutron three-axis spectrometer IN12 at the ILL,” *Nuclear Instruments and Methods in Physics Research A* **819** (2016), 89–98, [doi:10.1016/j.nima.2016.02.067](https://doi.org/10.1016/j.nima.2016.02.067).

## 3. Recommended conventional-IN12 geometry

### 3.1 Distances

| Quantity | Recommended value | Status and interpretation |
|---|---:|---|
| Vertical cold source to IN12 | approximately 115 m | Physical reactor-source distance through H144. |
| H144 guide exit to monochromator | 1.800 m | Strongly documented. The guide exit is the virtual source. |
| Monochromator to sample, `L2` | 1.800 m | Designed to match the guide-exit–monochromator distance for Rowland focusing. |
| Sample to analyzer, `L3` | approximately 1.300 m | Variable; exact allowed limits are not published. |
| Analyzer to detector, `L4` | 0.720 m | Strongly documented current value. |

For a compact TAVI description, the cleanest interpretation is to treat the 20 × 140 mm H144 exit as an effective source and use `L1 = 1.8 m`. For a full McStas guide model, the physical vertical cold source is roughly 115 m upstream and the complete H144 transport must be represented. A bare source placed 115 m away without the guide would not reproduce the incident phase space.

### 3.2 Angular ranges

| Axis | Published range | TAVI implication |
|---|---:|---|
| Monochromator scattering angle | \(-140^\circ < 2\theta_M < -10^\circ\) | Current monochromator is on the clockwise/right/negative branch. |
| Sample scattering angle | \(-120^\circ < 2\theta_S < +120^\circ\) | Both scattering sides are accessible. |
| Analyzer scattering angle | \(-140^\circ < 2\theta_A < +140^\circ\) | Both analyzer branches are mechanically accessible. |
| Sample goniometer | approximately ±20° | Motorised, nonmagnetic goniometer. |

The upgrade paper describes a monochromator take-off angle from approximately −10° to −70°, clockwise relative to the incident beam. This appears to use the monochromator Bragg angle rather than the full `2θ` scattering angle; the current ILL characteristics page gives the corresponding full range of approximately −10° to −140°.

### 3.3 Probable senses

Using the TAVI convention in which a left/counter-clockwise turn is `+1` and a right/clockwise turn is `-1`, the best current working assignment is:

```text
monochromator sense = -1
sample sense        = +1
analyzer sense      = -1
```

Confidence is not uniform:

- `SM = -1` is strongly supported by the post-upgrade clockwise monochromator branch and negative current monochromator-angle range.
- `SS = +1` and `SA = -1` occur in a real historical IN12 scan header and are consistent with continuity of the reused secondary spectrometer.
- A 2010 vTAS repository entry instead gives `SS = -1`, while generic McStas templates contain still other defaults. Those files therefore cannot settle the present control convention.

The recommended `[-1, +1, -1]` assignment should remain explicitly provisional until checked against one current NOMAD/raw IN12 file or confirmed by the instrument team.

## 4. Current component sequence

A useful conventional configuration can be represented as:

1. Vertical cold source and H144 guide transport, or an effective source at the H144 exit.
2. Exit diaphragms and optional pre-monochromator Soller collimator.
3. Optional upstream Mezei flipper.
4. Double-focused PG(002) monochromator.
5. Optional pre-sample collimator.
6. Sample and sample environment.
7. Optional post-sample collimator and, in suitable low-energy configurations, a cooled beryllium filter.
8. Horizontally focused PG(002) analyzer, or Heusler(111) analyzer for polarization analysis.
9. Optional analyzer-to-detector collimator.
10. Single vertical \(^3\)He detector tube.

The velocity selector and transmission polarizing cavity are much farther upstream inside the guide and should not be placed in the short 1.8 m guide-exit–monochromator section.

## 5. H144 guide and virtual source

### 5.1 Overall guide layout

IN12 is at an end position on H144, approximately 115 m from the vertical cold source. The guide has an overall S-shaped trajectory:

- approximately 6 m straight after the vertical cold source;
- approximately 6 m with curvature radius `R = 2700 m`;
- 21.3 m with `R = 4000 m`;
- a final section of about 80 m with `R ≈ -2000 m`.

The final 80 m has a nominal cross-section of 45 mm wide × 105 mm high. The overall guide coating is approximately `m = 2`. Because of the final curvature, the outer concave wall is coated to `m = 2.4`, while the inner convex wall is adequately served by approximately `m = 2`.

### 5.2 Final focusing section

The final 8 m forms an asymmetric focusing nose:

- vertical opening expands from 105 to 140 mm;
- horizontal opening contracts from 45 to 20 mm;
- sidewall coatings rise as high as `m = 3.2` toward the exit;
- the curved trajectory continues at about `R = -2000 m`;
- the intended focused spot at the sample is roughly 2 × 3 cm.

The widening reduces further vertical guide reflections and better illuminates the 16 cm-high monochromator. The horizontal taper forms the virtual source needed for focusing onto small samples.

Simulations found only roughly a 15–20% gain from more elaborate whole-guide elliptical forms under the existing geometrical constraints. The adopted design is therefore largely conventional until the specialised final 8 m.

### 5.3 Guide flux information

The upgrade study reports approximate gold-foil capture fluxes of:

| Position | Capture flux |
|---|---:|
| Beginning of final focusing section | \(1.66\times10^{10}\) n cm\(^{-2}\) s\(^{-1}\) |
| H144 guide exit | \(2.59\times10^{10}\) n cm\(^{-2}\) s\(^{-1}\) |
| New monochromator position | \(0.53\times10^{10}\) n cm\(^{-2}\) s\(^{-1}\) |

The measured flux exceeded the contemporary McStas/SIMRES predictions because the available vertical cold-source description underestimated the real H1 capture flux, reportedly by as much as approximately 30%.

## 6. PG(002) monochromator

The upgraded monochromator is the best documented crystal assembly on the instrument.

| Property | Current value |
|---|---|
| Material/reflection | Pyrolytic graphite PG(002) |
| Lattice spacing | `d = 3.355 Å` |
| Array | 11 columns × 11 rows |
| Overall assembly | 20 cm wide × 16 cm high |
| Crystal mosaicity | 0.4° FWHM = 24 arcmin |
| PG crystal thickness | 2.0 ± 0.1 mm |
| Backing per crystal | 2.3 mm absorbing B\(_4\)C plate, then 3 mm aluminium support |
| Horizontal curvature | Continuously adjustable from approximately 1.7 m radius to flat |
| Vertical curvature | Continuously adjustable from approximately 0.5 m radius to flat |
| Focusing axes | Horizontal and vertical, independently motorised |
| Central crystal | Fixed |
| Source and sample focal arms | approximately 1.8 m each |

The paper explicitly gives the orientation as 16 cm height × 20 cm width. One current ILL table displays 20 × 16 cm under a height × width label, apparently swapping the orientation. The engineering discussion and guide-exit optimisation make the paper’s 16 cm vertical dimension substantially more credible.

### 6.1 Missing slab geometry

No located source gives the physical width, height, or gaps of the individual graphite slabs. Dividing the total assembly by eleven gives nominal pitches:

```text
horizontal pitch ≈ 200 mm / 11 = 18.18 mm
vertical pitch   ≈ 160 mm / 11 = 14.55 mm
```

These are not slab dimensions. They include all gaps and mechanical allowance and should only be used as visibly provisional placeholders.

For a future TAVI descriptor, `HOPG.rfl` is a reasonable reflectivity file and no transmission file is the likely starting point, but the model reflectivity scale `r0` and any transmission treatment are modelling choices rather than published hardware facts.

## 7. Conventional PG(002) analyzer

The present [ILL characteristics page](https://www.ill.eu/en/for-ill-users/instruments/instruments-list/in12/characteristics/) gives:

| Property | Value |
|---|---|
| Material/reflection | PG(002) |
| Lattice spacing | `d = 3.355 Å` |
| Overall dimensions | approximately 12.2 × 11.8 cm |
| Horizontal curvature | Variable |
| Vertical curvature | Fixed |
| Sample–analyzer arm | approximately 1.3 m, variable |
| Analyzer–detector arm | 0.72 m |

The upgrade paper rounds the assembly to approximately 12.5 × 12.5 cm. The current exact values closely reproduce the old official McStas wrapper’s `WA = 0.121 m` and `HA = 0.118 m`.

The historical McStas model uses 11 horizontal analyzer blades and one vertical row. Because the upgrade principally replaced the primary spectrometer and retained the secondary arrangement, a strong provisional current model is:

```text
analyzer columns = 11
analyzer rows    = 1
overall width    = 0.122 m
overall height   = 0.118 m
```

This implies a horizontal pitch near 11.1 mm, not a confirmed physical blade width. The current blade mosaic, thickness, gap, fixed vertical curvature, and horizontal curvature limits have not been found. Historical sources suggest mosaics around 30–35 arcmin, but neither number should be presented as a confirmed post-upgrade specification.

## 8. Heusler analyzer and polarization analysis

The alternative polarized configuration uses a vertically focusing Heusler(111) analyzer.

| Property | Value |
|---|---|
| Reflection | Heusler(111) |
| Lattice spacing | `d = 3.44 Å` |
| Overall dimensions | 7.5 × 14.5 cm |
| Function | Energy and polarization analysis |

The upgrade paper reports that the newer tall, horizontally focusing Heusler analyzer increased polarized flux by approximately a factor of two. Specific blade count, blade size, gaps, mosaic, and curvature data were not located.

IN12 supports longitudinal polarization analysis and spherical polarization analysis with Cryopad.

## 9. Velocity selector

The selector is located more than 36 m upstream of the guide exit and is mounted on a movable in/out table.

| Property | Value |
|---|---|
| Manufacturer | Astrium GmbH |
| Designed wavelength range | 2.23–6.3 Å |
| Number of blades | 60 |
| Screw angle | 23.9° |
| Relative wavelength resolution | approximately 25% |
| Transmission at 4 Å | approximately 83% |
| Measured average transmission | approximately 82–84% |
| Blade coating | \(^{10}\)B neutron absorber |
| Function | Higher-order suppression and background reduction |

The broad wavelength band allows reduced transmission below the nominal limit: at 1.9 Å, the transmitted intensity is approximately half the peak value. The selector is removed for short-wavelength/high-`ki` work where higher-order reflections are less important.

The design specification called for false-neutron suppression below approximately \(10^{-7}\) for wavelengths above 2.5 Å; experimental suppression was demonstrated to be better than approximately \(10^{-4}\).

## 10. Transmission polarizer and guide fields

Immediately behind the selector, about 35 m upstream of the guide exit, a vertical guide changer selects either a normal guide element or a transmission-polarizing cavity.

### 10.1 Cavity construction

- Double-V transmission cavity, approximately 2.5 m long.
- Standard guide envelope approximately 45 mm wide × 105 mm high.
- Silicon wafers 0.3 mm thick, coated on both sides with Fe/Si.
- Wafers tilted 0.3° relative to the incident beam.
- Two channels separated by an absorbing `m = 1.8` supermirror dividing wall, 0.3 mm thick.
- Guide-element sidewalls approximately `m = 1.8`.
- Polarizing element has no curvature.
- Magnetic housing provides approximately 450 G vertically.
- Permanent-magnet guide fields elsewhere provide at least approximately 30 G.
- Helmholtz coils preserve polarization around the monochromator shielding.

### 10.2 Polarizing performance

- Spin-up coating equivalent approximately `m = 3.8`, reflectivity above 79%; this spin state is reflected and absorbed.
- Transmitted spin-down coating approximately `m = 0.7`.
- Designed wavelength range 2–6 Å.
- Measured incident polarization at the sample approximately 90–95%.
- Transmission approximately 30–37% of the incident unpolarized intensity.
- Typical measured flipping ratio approximately 20–24; values above 27 were reported depending on beam size.
- Outgoing polarization with the Heusler analyzer above 97%.
- Mezei flipper efficiencies around 99.1–99.6% or higher.

## 11. Collimation, diaphragms, filters, and detector

### 11.1 Collimation

Available Gd-coated Soller collimators are:

```text
10, 20, 30, 40, 60, and 80 arcmin
```

They may be placed before the sample, between sample and analyzer, and between analyzer and detector. In the short section between guide exit and monochromator, IN12 can also accept diaphragms, an optional Soller collimator, and an optional Mezei flipper.

There is no simple permanently installed conventional `α1` in normal modern operation: the H144 exit and focusing monochromator define the primary phase space. A catalogue should distinguish available removable collimation from a fixed default chain.

### 11.2 Beryllium filter

The old instrument used a cooled beryllium filter at about 80 K. Modern experimental papers also report a cooled Be filter after the sample for appropriate low-energy configurations. McCode’s [`Be.trm`](https://github.com/McStasMcXtrace/McCode/blob/master/mcstas-comps/data/Be.trm) file is explicitly labelled as transmission measured on IN12 at 80 K and is therefore a particularly valuable reusable instrument-specific data asset.

The velocity selector has replaced the filter as the primary general higher-order-suppression device, but the filter remains relevant as an optional secondary component.

### 11.3 Detector

The conventional detector is:

- one vertical \(^3\)He tube;
- approximately 12 cm active height;
- approximately 5 cm diameter.

Gas pressure, efficiency curve, wall composition, dead regions, and exact active length were not located.

## 12. Operating envelope and performance

| Quantity | Current published value |
|---|---:|
| Wavelength range | approximately 1.26–6.3 Å |
| Incident wavevector | `ki = 1.0–5.0 Å⁻¹` |
| Incident energy | approximately 2.1–42 meV |
| Horizontal divergence at sample, double focus | approximately 2–3° |
| Reciprocal-space resolution near `ki = 1.5 Å⁻¹` | approximately 0.05 Å⁻¹ |
| High-energy-transfer W configuration | approximately 10–25 meV |

### 12.1 Flux at `ki = 2 Å⁻¹`

| Configuration | Flux at sample |
|---|---:|
| Double focused | \(1.04\times10^8\) n cm\(^{-2}\) s\(^{-1}\) |
| Double focused, selector inserted | \(8.4\times10^7\) n cm\(^{-2}\) s\(^{-1}\) |
| Selector plus 60′ collimation | \(5.02\times10^7\) n cm\(^{-2}\) s\(^{-1}\) |

The upgrade yielded approximately an order-of-magnitude increase at the sample around `ki = 2 Å⁻¹` compared with the former IN12.

### 12.2 Energy resolution

With 30′ collimation, reported elastic FWHM values are approximately:

| Incident energy | Energy-resolution FWHM |
|---:|---:|
| 2.3 meV | 22 μeV |
| 4 meV | 75 μeV |
| 5 meV | 110 μeV |

In double-focus operation at `ki = 1.5 Å⁻¹`, the reported FWHM is approximately 150 μeV. The upgrade paper also reports vanadium elastic widths on the order of 0.04–0.05 meV or lower at low wavevectors with tight collimation, rising to roughly 1–1.5 meV at the high end of the accessible range.

## 13. Historical full McStas model

McCode contains the official historical model:

- [`ILL_H142_IN12` directory](https://github.com/McStasMcXtrace/McCode/tree/master/mcstas-comps/examples/ILL/ILL_H142_IN12)
- [`ILL_H142_IN12.instr`](https://github.com/McStasMcXtrace/McCode/blob/master/mcstas-comps/examples/ILL/ILL_H142_IN12/ILL_H142_IN12.instr)

It was written by Emmanuel Farhi in April 2004 and models the old H142 instrument, not current H144 IN12.

Its wrapper defaults include:

```text
ILL_H142_IN12(
    m=1,
    KI=2.662,
    QM=1.0,
    EN=0.0,
    verbose=1,
    WM=0.08,
    HM=0.12,
    NHM=1,
    NVM=6,
    RMV=-1,
    WA=0.121,
    HA=0.118,
    NHA=11,
    NVA=1,
    RAH=-1,
    L2=1.726,
    L3=1.300,
    L4=0.710
)
```

Interpretation:

- old monochromator: 80 mm wide × 120 mm high, one horizontal column × six vertical slabs, vertically focused;
- analyzer: 121 mm wide × 118 mm high, eleven horizontal blades × one vertical row, horizontally focused;
- old distances: `L2 = 1.726 m`, `L3 = 1.300 m`, `L4 = 0.710 m`.

For a post-upgrade model:

- replace the H142 guide/source block with H144 or an H144-exit effective source;
- replace the 1 × 6 monochromator with the present 11 × 11 double-focused assembly;
- update `L2` to 1.8 m and `L4` to 0.72 m;
- preserve `L3 ≈ 1.3 m` but make it scannable if supported;
- explicitly set the senses rather than inheriting generic template defaults;
- reconsider all inherited generic collimation and mosaic defaults.

The generic `templateTAS.instr` defaults include senses and mosaics that are not authoritative IN12 measurements. They must not be mistaken for hardware specifications simply because the IN12 wrapper includes the template.

## 14. Historical raw IN12 control data

A historical IN12 scan distributed through the McCode/iFit data collection provides a useful concrete control-system snapshot. It is dated 11 August 2001 and contains:

```text
DM = 3.355 Å
DA = 3.354 Å
SM = +1
SS = +1
SA = -1

ETAM = 35 arcmin
ETAA = 35 arcmin

ALF1 = 40 arcmin
ALF2 = 60 arcmin
ALF3 = 120 arcmin
ALF4 = 120 arcmin

BET1 = BET2 = BET3 = BET4 = 120 arcmin
```

This is useful evidence for the secondary senses and old practical mosaic/collimation values, but it predates the primary upgrade by roughly a decade. The current monochromator is installed on the opposite, clockwise branch, so the historical `SM = +1` must not be carried forward.

## 15. Older Yellow Book specifications

The old ILL Yellow Book sheet is useful for identifying retained secondary components but describes the pre-upgrade instrument:

- H142 guide, approximately 108 m long;
- guide beam about 12 × 3 cm;
- vertically focused PG(002) monochromator, about 12 × 8 cm;
- wavelength range approximately 2.3–6 Å;
- `ki ≈ 1.05–2.6 Å⁻¹`;
- incident energy approximately 2.3–14 meV;
- old supermirror bender aperture around 4.5 × 3.7 cm, polarization above 95%, transmission around 50–60%;
- cooled 10 cm beryllium filter at approximately 80 K;
- collimators 10, 20, 30, 40, and 60 arcmin;
- the same broad secondary angular ranges, detector dimensions, and goniometer range later reported for upgraded IN12.

These values should be used only as historical evidence. In particular, the old bender was replaced by the far-upstream transmission cavity.

## 16. vTAS and IN12-UFO resources

The [ILL vTAS page](https://www.ill.eu/en/for-ill-users/software-and-scientific-tools/software-scientific-tools/vtas/) describes support for both conventional TAS and multiplexer/UFO configurations, using Cooper–Nathans calculations and a McStas-like Monte Carlo mode.

An older McCode Debian package, `vtas-0.6-amd64.deb`, contains:

```text
/usr/local/vtas/templateTAS.instr
/usr/local/vtas/templateUFO.instr
vIMPS.jar
media/instruments_repository.xml
```

The generic templates are not a current IN12 McStas model, but the embedded repository contains IN12-labelled geometry from approximately November 2010.

### 16.1 Conventional IN12 repository entry

The historical repository gives approximately:

```text
sample rotation radius / L2 = 1.7 m
analyzer rotation radius/L3 = 1.3 m
detector radius / L4         = 0.7 m
SM = +1
SS = -1
SA = -1
sample table radius          = 0.35 m
PG monochromator d           = 3.355 Å
PG analyzer d                = 3.355 Å
```

This is pre-upgrade and conflicts with a real old scan on the sample sense. It should be treated as approximate software metadata, not as an authority over measured control data or current geometry.

### 16.2 IN12-UFO geometry

The IN12-UFO concept uses fifteen independently rotated and positioned analyzer channels to map scattered intensity onto a two-dimensional detector. The [2010 JCNS report](https://www.fz-juelich.de/en/jcns/downloads/jcnsreports/2010_in-12/%40%40download/file/2010_IN-12.pdf) describes analyzer units on rails, individual analyzer rotation, fifteen \(^3\)He detector tubes, a movable focus diaphragm, interchangeable analyzer–detector lengths, and free, focused, constant-energy, and linear-`Q` scan modes.

Values recoverable from the old vTAS template/repository include:

| Quantity | Historical design/template value |
|---|---:|
| Analyzer channels | 15, indexed −7 to +7 |
| Lateral channel pitch | approximately 22 mm |
| Crystal envelope per channel | approximately 25.5 mm wide × 90 mm high |
| Subdivision in generic template | 3 horizontal × 1 vertical |
| Focusing radius | approximately 0.530 m |
| Analyzer–detector distance in generic template | approximately 0.500 m |
| Documented adjustable analyzer–detector range | approximately 0.45–0.65 m |
| Repository detector distance | approximately 0.660 m |
| Generic modeled detector surface | approximately 0.6 × 0.4 m |
| Analyzer assembly inclination | approximately 30° |

The old repository supplies individual nominal analyzer angles of approximately 7°, 9°, 11°, 12°, 14°, 16°, 17°, 19°, 20°, 22°, 23°, 25°, 26°, 27°, and 29°, with longitudinal offsets from approximately +70 to −70 mm.

The generic UFO template uses values such as `dA = 3.266 Å` and non-IN12 arm lengths; these must not be assumed to describe final hardware. The present ILL page still speaks of UFO as something IN12 “will be equipped” with. The entire UFO block should therefore remain labelled historical/design information until its current installation and commissioning status are confirmed.

## 17. Source conflicts and cautions

### 17.1 Monochromator dimensions

- Upgrade paper: 16 cm height × 20 cm width.
- One current ILL table: 20 × 16 cm under a height × width heading.

The paper’s orientation is preferred because it is consistent with the explicit 16 cm effective vertical height used in guide optimisation.

### 17.2 Analyzer dimensions

- Upgrade paper: approximately 12.5 × 12.5 cm.
- Current ILL page: 12.2 × 11.8 cm.
- Historical official McStas: 12.1 × 11.8 cm.

Use the current 12.2 × 11.8 cm value; the paper is evidently rounded.

### 17.3 Polarizer description

Some migrated ILL text retains a stale reference to a supermirror bender after the first collimator. The post-upgrade paper and current layout description clearly establish the upstream transmission cavity and guide changer as the modern primary polarizer.

### 17.4 Senses

- Real 2001 raw scan: `[+1, +1, -1]`.
- 2010 vTAS IN12 metadata: `[+1, -1, -1]`.
- Generic historical McStas template defaults: another non-authoritative combination.
- Post-upgrade monochromator: demonstrably on the clockwise/negative branch.

Use `[-1, +1, -1]` only as the best evidence-based provisional modern assignment.

### 17.5 Conventional versus UFO configuration

The current conventional single-detector instrument is well documented. The UFO material is detailed enough to preserve for research, but its present operational status is unclear and should not be silently merged into the conventional descriptor.

## 18. Provisional TAVI-oriented parameter set

This is a research summary, not a ready-to-commit descriptor:

```text
name = "IN12"
facility = "ILL"
type = "cold-neutron triple-axis spectrometer"

# Compact model with H144 exit as virtual source
L1 = 1.800 m
L2 = 1.800 m
L3 = 1.300 m  # variable; limits unknown
L4 = 0.720 m

sense_mono   = -1
sense_sample = +1  # provisional
sense_ana    = -1  # strongly historical, current confirmation desirable

monochromator:
  type = PG(002)
  d = 3.355 Å
  width = 0.200 m
  height = 0.160 m
  columns = 11
  rows = 11
  mosaic_h = 24 arcmin
  mosaic_v = 24 arcmin
  thickness = 0.0020 m
  horizontal_radius_range = 1.7 m to flat
  vertical_radius_range = 0.5 m to flat
  slab_width = unknown
  slab_height = unknown
  gaps = unknown

analyzer:
  type = PG(002)
  d = 3.355 Å
  width = 0.122 m
  height = 0.118 m
  columns = 11       # probable from retained historical assembly
  rows = 1           # probable from retained historical assembly
  horizontal_focus = variable
  vertical_focus = fixed
  mosaic = unknown   # historical 30–35 arcmin
  slab_dimensions = unknown
  gaps = unknown

detector:
  type = He3 tube
  diameter = 0.050 m
  active_height = 0.120 m

collimation_options_arcmin = [10, 20, 30, 40, 60, 80]

axis_limits:
  mono_2theta = [-140, -10] degrees
  sample_2theta = [-120, +120] degrees
  analyzer_2theta = [-140, +140] degrees
  sample_goniometer = [-20, +20] degrees
```

The signed curvature convention must be tied to the instrument’s actual motor directions rather than inferred from generic Rowland formulas. Both monochromator axes are continuously adjustable; the horizontal and vertical bend signs should therefore be checked at more than one real instrument setting.

## 19. Highest-priority missing information

The most useful questions for the IN12 team are:

1. Can they provide one current NOMAD/raw scan header showing all six instrument angles and the three senses?
2. What are the physical width, height, and horizontal/vertical gaps of the 11 × 11 monochromator crystals?
3. Is the current conventional PG analyzer still 11 horizontal blades × one vertical row?
4. What are the PG analyzer blade dimensions, gap, thickness, mosaic, fixed vertical radius, and allowed horizontal-radius range?
5. What is the precise permitted range of sample–analyzer distance `L3`?
6. What slit and diaphragm openings are normally available, and at what distances from the monochromator and sample?
7. What are the Soller collimator lengths and physical clear apertures?
8. Is the McStas or SIMRES H144 guide model used for the upgrade study still available?
9. Is there a modern source spectrum, McStas source definition, or MCPL file for the H144 exit?
10. What are the selector rotor length, diameter, speed range, and wavelength-to-speed calibration?
11. What are the detector gas pressure, efficiency curve, wall material, dead regions, and exact active dimensions?
12. Where exactly is the optional cooled Be filter installed in current configurations?
13. What is the present status of IN12-UFO: installed, commissioned, mothballed, incomplete, or design-only?
14. What are the current conventional and polarized configuration presets?
15. What sign convention do the horizontal and vertical focusing motors use?

The current ILL contact page lists Karin Schmalzl as first responsible, with Stéphane Raymond and Wolfgang F. Schmidt as co-responsibles. They are the most likely route to current engineering drawings, control-system conventions, and any surviving guide simulation.

## 20. Recommended catalogue strategy

The initial TAVI entry should describe the conventional post-upgrade H144/PG(002)/PG(002)/single-detector configuration. It should use an effective H144-exit source for tractability, expose the variable `L3`, the two monochromator curvatures, analyzer horizontal curvature, collimator selections, and optional selector/filter/polarization modes where the catalogue schema permits.

The Heusler analyzer should be represented as an alternative polarized configuration. IN12-UFO should be a separate configuration or separate descriptor rather than folded into the conventional instrument, and only after its operational status and final geometry are confirmed.

## 21. Principal sources and assets

### Current and upgrade documentation

- [ILL IN12 description](https://www.ill.eu/en/for-ill-users/instruments/instruments-list/in12/)
- [ILL IN12 characteristics](https://www.ill.eu/en/for-ill-users/instruments/instruments-list/in12/characteristics/)
- K. Schmalzl *et al.*, [“The upgraded cold neutron three-axis spectrometer IN12 at the ILL”](https://doi.org/10.1016/j.nima.2016.02.067), NIM A 819 (2016), 89–98.
- [ILL vTAS software page](https://www.ill.eu/en/for-ill-users/software-and-scientific-tools/software-scientific-tools/vtas/)

### McStas/McCode assets

- [Historical `ILL_H142_IN12` McStas directory](https://github.com/McStasMcXtrace/McCode/tree/master/mcstas-comps/examples/ILL/ILL_H142_IN12)
- [Historical `ILL_H142_IN12.instr`](https://github.com/McStasMcXtrace/McCode/blob/master/mcstas-comps/examples/ILL/ILL_H142_IN12/ILL_H142_IN12.instr)
- [IN12-measured `Be.trm` at 80 K](https://github.com/McStasMcXtrace/McCode/blob/master/mcstas-comps/data/Be.trm)
- [McCode package repository](https://packages.mccode.org/)

### UFO material

- [2010 JCNS IN12/IN12-UFO report](https://www.fz-juelich.de/en/jcns/downloads/jcnsreports/2010_in-12/%40%40download/file/2010_IN-12.pdf)

### Historical instrument sheet

- [Former IN12 ILL Yellow Book sheet](https://rencurel.essworkshop.org/documents/YellowBookCDrom/data/10_4_4.pdf)

