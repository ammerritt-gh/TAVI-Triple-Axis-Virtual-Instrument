# PANDA Triple-Axis Spectrometer: Instrument Research Dossier

**Instrument:** PANDA  
**Facility:** Heinz Maier-Leibnitz Zentrum (MLZ), Forschungs-Neutronenquelle Heinz Maier-Leibnitz (FRM II), Garching, Germany  
**Beam tube:** SR-2  
**Research date:** 2026-07-18  
**Purpose:** Source material for a future PANDA definition in the TAVI instrument catalogue

## Executive summary

PANDA is a cold/thermal triple-axis neutron spectrometer whose name expands historically as *Polarisation Analysierendes Drei-Achsenspektrometer*. Its design emphasizes a short source-to-monochromator distance, double focusing at the monochromator, a focusing analyzer, selectable Soller collimation, and low background. PANDA can also operate with Heusler monochromator and analyzer crystals for polarized-neutron measurements. The multiplexed BAMBUS secondary spectrometer is under commissioning.

The most valuable external discovery is a public PANDA McStas repository maintained on the FRM II infrastructure. It contains a 2014 full instrument, detailed older models by Peter Link, source spectra and material files, a custom monitor component, and multiple BAMBUS simulations. This collection is more extensive than the attached `vPANDA` file and should be preserved as the principal historical simulation source.

The attached `vPANDA` file is useful as a parameterized, McStasScript-oriented model, but it should not be regarded as an as-built 2026 digital twin. It appears to inherit substantial geometry from the 2007 model, contains at least one clear physical error—the sapphire-filter thickness—and has incomplete or questionable kinematic, focusing, detector, polarization, and source representations.

## Principal sources

### Supplied material

- `INSTRUMENT_AUTHORING(1).md`: TAVI catalogue authoring requirements.
- `2007-01-01__panda-overview__v01.md`: PANDA overview corresponding to the 2007 *Neutron News* article, DOI [10.1080/10448630701623087](https://doi.org/10.1080/10448630701623087).
- `2007-01-01__panda-table__v01.csv`: tabulated historical instrument characteristics.
- `2013-01-01__panda-supermirror-guide__v01.md`: despite its filename, this is text from the 2016 NIM A paper, [“Optimizing the neutron delivery system of the cold three axes spectrometer PANDA”](https://www.sciencedirect.com/science/article/abs/pii/S016890021630897X), DOI `10.1016/j.nima.2016.08.060`.
- `2026-07-03__vpanda-mcstas__v01.instr`: McStasScript-generated virtual PANDA model. The 2026 date appears to be a generation or packaging date, not evidence that all dimensions represent the current physical instrument.

### Public instrument information

- [Current PANDA instrument page at MLZ](https://mlz-garching.de/panda)
- [PANDA team wiki](https://wiki.mlz-garching.de/panda%3Aindex)
- [PANDA simulation wiki](https://wiki.mlz-garching.de/panda%3Asimulation)
- [2015 PANDA instrument paper](https://jlsrf.org/index.php/lsf/article/download/35/pdf/261), DOI `10.17815/jlsrf-1-35`
- [PANDA teaching notes](https://wiki.mlz-garching.de/_media/fopra%3Apanda-eng.pdf)
- [PANDA sample-environment wiki](https://wiki.mlz-garching.de/panda%3Ase)
- [2015 BAMBUS design paper](https://www.helmholtz-berlin.de/pubbin/oai_publication?ID=88338&VT=1), DOI `10.1088/1742-6596/592/1/012145`

## Public McStas repository

The PANDA simulation wiki links to the instrument-team repository:

- [Repository tree](https://forge.frm2.tum.de/cgit/frm2/panda/mcstas.git/tree/)
- [Repository history](https://forge.frm2.tum.de/cgit/cgit.cgi/frm2/panda/mcstas.git/)
- [Direct 2014 `panda.instr` file](https://forge.frm2.tum.de/cgit/frm2/panda/mcstas.git/plain/panda_instrument_files/panda.instr)

Clone command:

```bash
git clone https://forge.frm2.tum.de/review/frm2/panda/mcstas.git
```

Important contents include:

| Path | Contents and value |
|---|---|
| `panda_instrument_files/panda.instr` | Josh A. Lim's March 2014 PANDA model for McStas 2.1rc1; probably the strongest single historical starting model |
| `panda_instrument_files/HOPG.rfl` | PG reflectivity data |
| `panda_instrument_files/C_graphite.lau` | Graphite crystallographic data |
| `panda_instrument_files/coldSourceFRM2norm.dat` | Measured or processed FRM II cold-source spectrum |
| `archive/instruments/panda.inst` | Peter Link's detailed July 2007 primary-spectrometer model |
| `archive/instruments/panda1.inst` | Earlier May 2004 PANDA model |
| `archive/instruments/panda_primbeam.inst` | Primary-beam model |
| `archive/instruments/panda_source.inst` | Source-only model |
| `archive/instruments/Al2O3_sapphire.trm` | Sapphire transmission data |
| archived `Kfac_monitor.comp` | Custom monitor component |
| `13_bambus_inelastic/` | BAMBUS inelastic models at final energies of 3.0, 3.5, 4.0, 4.5, and 5.0 meV |
| `14_BAMBUS_elastic/` | Corresponding elastic BAMBUS models |
| `bambus_python/` | BAMBUS geometry, Rowland-circle, reciprocal-space, and coverage calculations |

The visible repository history is principally from 2015 and includes commits described as adding “Peter Links old PANDA simulation files.” The repository is therefore an authoritative historical collection, but not necessarily a current as-built model. No explicit licence file was found at repository root, so reuse or redistribution of its code and data should be checked separately.

## Recommended baseline values

These values are the most defensible starting point for a future catalogue definition. Items marked provisional should remain visibly qualified until confirmed against current instrument-control or engineering information.

| Property | Recommended value | Confidence and qualification |
|---|---:|---|
| Instrument type | Cold/thermal triple-axis spectrometer | High |
| Beam tube | SR-2 | High; current MLZ page |
| Source–monochromator distance | Approximately 7.8 m | High as a published physical figure; model-coordinate discrepancy discussed below |
| Monochromator–sample distance | 2.10–2.15 m | Medium; configuration/version dependent |
| Sample–analyzer distance | 1.05 m | High |
| Analyzer–detector distance | 0.95 m | High |
| Default monochromator | PG(002), \(d=3.355\) Å | High |
| Default analyzer | PG(002), \(d=3.355\) Å | High |
| PG mosaic | 20 arcmin in the simulation models | High for the model; actual distribution may differ |
| PG monochromator array | 11 × 11 crystals | High |
| PG analyzer array | Probably 11 × 5 = 55 crystals | Medium-high; older models use 13 × 6 |
| Primary collimation | 20′, 40′, 60′, and open | High |
| Other collimators | 15′, 40′, 60′, and open | High |
| Sample scattering range | \(5^\circ < 2\theta_S < 125^\circ\) | High; current specification |
| Analyzer range | \(-130^\circ < 2\theta_A < 100^\circ\) | High; current specification |
| Analyzer lower limit | \(k_f>1.05\) Å⁻¹ | High; current specification |
| Conventional detectors | 1-inch and 2-inch high-pressure \(^3\)He tubes | High |
| Provisional TAVI senses | monochromator −1, sample +1, analyzer −1 | Medium-high; attached and 2014 models agree, but control-system confirmation is desirable |

## Source and primary guide

### Source model in `vPANDA`

The attached model uses an approximately 135 × 80 mm source focused onto a 110 × 100 mm aperture at 1.18108 m. Its three-Maxwellian representation is:

| Temperature | Intensity parameter |
|---:|---:|
| 361.9 K | \(7.22\times10^{12}\) |
| 159.0 K | \(6.74\times10^{12}\) |
| 35.66 K | \(6.435\times10^{12}\) |

Peter Link's older model uses essentially the same source representation. The 2014 model instead supports `coldSourceFRM2norm.dat` and provides a different Maxwellian fallback. The supplied spectrum file is preferable to either hard-coded approximation when reproducing the historical cold-source configuration.

The current official page distinguishes operation **with** and **without** the cold source. A present-day thermal-source configuration therefore requires a different source description; neither the attached Maxwellian model nor the historical cold-source spectrum should automatically be used for it.

### Guide geometry

The attached model describes three guide sections:

| Start \(z\) | Length | Entrance | Exit | Coating |
|---:|---:|---:|---:|---|
| 1.196 m | 1.307 m | 105 × 98 mm | 105 × 118 mm | \(m=3\), all sides |
| 2.540 m | 0.997 m | 106 × 119 mm | 106 × 134 mm | chiefly \(m=3\) side walls |
| 3.546 m | 0.180 m | 107 × 135 mm | 107 × 138 mm | \(m=2\) side walls |

The second section has alternative narrow-guide configurations represented as approximately:

- 50 mm wide, uncoated or naturally reflecting guide;
- 40 mm wide guide with \(m=2\) side walls.

The older model uses a 197 mm final guide rather than 180 mm. An approximately 3 mm aluminium window is placed near model coordinate \(z=3.810\) m, with the end-of-beam/reference plane around 3.813 m.

The guide reflectivity constants differ between model generations. The attached model uses `R0=.99`, `Qc=.02174`, `alpha=3`, and `W=.001`, while the 2007 model uses markedly different empirical constants. These parameters should not be treated as measured current coating performance without further documentation.

## Primary apertures, filter, and collimation

Positions below are relative to the guide exit/reference plane in the attached model.

| Element | Relative position | Nominal dimensions |
|---|---:|---:|
| Primary collimator, `ca1` | +0.10 m | 108 × 160 mm; 0.50 m long |
| Sapphire filter | +0.90 m | approximately 70 mm physical thickness |
| `sk1` entrance | +1.010 m | 110 × 150 mm |
| `sk1` exit | +2.030 m | 90 × 180 mm |
| Horizontal virtual source, `ms1` | +2.180 m | variable width × 180 mm |
| `sk2` entrance | +2.476 m | 50 × 180 mm |
| `sk2` exit | +2.936 m | 70 × 200 mm |
| Monochromator center | +5.000 m | — |

The primary collimator positions are 20′, 40′, 60′, and open. In several simulation branches, open is represented numerically as 120′, but it is not necessarily a physical 120′ Soller collimator. The PANDA teaching material says that the primary collimator changer is automatic, whereas downstream collimators are normally changed manually. The physical Soller collimators are around 20 cm long and collimate horizontally.

### Sapphire-filter correction

The attached file specifies a sapphire-filter thickness of 0.86 m:

```c
thickness = .86
```

This is almost certainly an inherited or transcription error. Peter Link's original file explicitly describes a 70 mm sapphire filter and uses 0.07 m. A solid 0.86 m sapphire element is not physically credible in this location. A future catalogue model should use 0.07 m unless newer engineering documentation establishes a different value.

## Monochromator configurations

The current official PANDA page provides separate incident-wavevector ranges for operation with and without the cold source:

| Monochromator | \(d\) | With cold source | Without cold source | Focusing |
|---|---:|---:|---:|---|
| PG(002) | 3.355 Å | \(k_i=1.05–4.0\) Å⁻¹ | \(1.5–4.0\) Å⁻¹ | variable horizontal and vertical |
| Cu(111) | 2.08 Å | \(1.8–7.0\) Å⁻¹ | \(1.8–7.0\) Å⁻¹ | variable horizontal and vertical |
| Si(111) | 3.13 Å | \(1.2–5.0\) Å⁻¹ | \(1.5–5.0\) Å⁻¹ | variable horizontal, fixed vertical |
| Heusler | 3.35 Å | \(1.1–4.0\) Å⁻¹ | \(1.5–4.0\) Å⁻¹ | variable vertical; polarized beam |

Current headline limits are:

- energy transfer up to approximately 18 meV with the cold source;
- energy transfer up to approximately 35 meV without the cold source;
- momentum transfer up to approximately 7 Å⁻¹.

These figures supersede the lower or differing values quoted in the 2007 and 2015 publications. The PANDA wiki also says that long-shutdown work includes renewed electronics, a renewed sample table, BAMBUS preparation, and preparation for a thermal-source cycle using Cu(111) and Si(111) monochromators.

### PG monochromator construction

The consistent McStas representation is:

- 11 × 11 PG(002) crystal pieces;
- pieces approximately 20 mm wide and 18–20 mm high;
- approximately 2 mm gaps;
- 20 arcmin mosaic;
- variable horizontal and vertical focusing;
- `HOPG.rfl` reflectivity data.

The 2016 guide paper describes nominal 20 × 20 mm pieces and an approximately 34 mm focused beam diameter at the sample for the existing monochromator system. The model's 18 mm active height may reflect a clear dimension or simplified component geometry rather than a different physical crystal.

The older model uses empirical curvature parameters approximately proportional to

\[
R_V \approx \frac{3.1}{k_i},
\qquad
R_H \approx 3.02 k_i.
\]

These quantities follow the internal McStas crystal-component convention and should not be interpreted directly as physical radii in metres.

## Monochromator-to-sample section

The attached `vPANDA` uses a monochromator–sample distance of 2.10 m. The 2007 Peter Link model and 2014 Josh Lim model use 2.15 m. The 2016 guide study describes an available distance of 2.10 m. This may reflect a later mechanical change, a distinction between reference planes, or rounding; both values should remain documented until confirmed.

The attached model includes:

- `sk3` entrance: 136 × 174 mm at 0.266 m from the monochromator;
- secondary collimator `ca2`: 40 × 120 mm, 0.20 m long, at approximately 0.90 m;
- `ca2` choices: 15′, 40′, 60′, or open;
- `sk3` exit: 60 × 100 mm at approximately 1.15 m;
- sample entrance slit `ss1`: approximately 1.70 m from the monochromator;
- `vPANDA` default sample aperture: 40 × 80 mm;
- older nominal sample slit: closer to 20 × 40 mm.

### Proposed elliptic focusing guide

The 2016 optimization study proposed an \(m=6\) elliptic guide between the monochromator and sample:

| Parameter | Proposed value |
|---|---:|
| Length | 1.480 m |
| Entrance | 40 × 60 mm |
| Exit | 13.7 × 17.9 mm |
| Monochromator to entrance | 0.500 m |
| Exit to sample | 0.120 m |
| Total monochromator–sample distance | 2.100 m |

At \(k_i=1.5\) Å⁻¹, the simulated performance was approximately:

| Configuration | Vertical FWHM | Horizontal FWHM | Relative intensity on 3 × 3 mm sample |
|---|---:|---:|---:|
| Monochromator alone | 34.5 mm | 34.0 mm | 1.00 |
| 1.48 m elliptic guide | 8.4 mm | 6.0 mm | 1.95 |
| Parabolic alternative | 8.0 mm | 9.2 mm | 1.23 |

The paper uses prospective wording such as “shall,” “expected,” and “chosen.” No later official source was found confirming that the guide was installed. It should therefore be represented as an optional or proposed configuration rather than baseline hardware.

## Sample table and angular convention

The current specified sample-scattering range is

\[
5^\circ < 2\theta_S < 125^\circ.
\]

Teaching documentation describes sample-goniometer rotations of about ±15° and translations of a few millimetres. It defines positive sample scattering in the counterclockwise direction. The attached model declares monochromator, sample, and analyzer senses of −1, +1, and −1, respectively. The 2014 model uses the same effective pattern through its component rotations. This is the best provisional TAVI convention, but it should ultimately be checked against current NICOS motor signs and zero definitions.

The Pb single crystal and Pb phonon components in `vPANDA` are test samples used to exercise elastic and inelastic simulation. They are not PANDA instrument hardware and should not appear in a catalogue definition except as optional examples.

## Secondary spectrometer

Nominal flight-path distances are:

- sample–analyzer: 1.05 m;
- analyzer–detector: 0.95 m.

Representative apertures in the attached model are:

| Element | Position | Aperture |
|---|---:|---:|
| Sample exit slit, `ss2` | +0.40 m from sample | configurable |
| Analyzer-arm entrance aperture | \(L_{SA}-0.60\) m | 40 × 120 mm |
| Third collimator, `ca3` | \(L_{SA}-0.55\) m | 40 × 140 mm; 0.20 m long |
| Analyzer-arm exit aperture | \(L_{SA}-0.20\) m | 60 × 100 mm |
| Detector-arm entrance aperture | +0.40 m from analyzer | 40 × 120 mm |
| Fourth collimator, `ca4` | +0.410 m | 40 × 140 mm; 0.20 m long |
| Detector-arm exit aperture | \(L_{AD}-0.10\) m | 30 × 120 mm |

The downstream collimators support 15′, 40′, and 60′ settings plus open.

## Analyzer

Supported analyzer materials are PG(002) for unpolarized work and Heusler for polarized operation. The current limits are:

- \(-130^\circ < 2\theta_A < 100^\circ\);
- \(k_f>1.05\) Å⁻¹;
- variable horizontal focusing;
- conventional analyzer vertical curvature apparently fixed.

The PG model uses crystals approximately 13 mm wide, 25 mm high, separated by 3 mm gaps, with 20 arcmin mosaic.

### Analyzer-array discrepancy

| Source | Analyzer layout |
|---|---:|
| Peter Link 2007 model | 13 × 6 = 78 crystals |
| Attached `vPANDA` | 13 × 6 = 78 crystals |
| Josh Lim 2014 model | 11 × 5 = 55 crystals |
| PANDA teaching documentation | 55 crystals |

The agreement between the later model and the physical teaching document makes 11 × 5 the stronger baseline. The 13 × 6 array in `vPANDA` is probably inherited from the 2007 model.

## Filters

The complete instrument should distinguish the upstream sapphire background filter from analyzer-side higher-order filters:

| Filter | Typical use |
|---|---|
| Sapphire, approximately 70 mm | Upstream fast-neutron and epithermal-background suppression |
| PG, approximately 60 mm | \(k_f=2.57\) or 2.662 Å⁻¹ |
| Cryogenic Be, \(T\le45\) K | \(k_f\le1.55\) Å⁻¹ |
| Liquid-nitrogen-cooled BeO | \(k_f\le1.33\) Å⁻¹ |

The attached model includes only the sapphire transmission component. PG, Be, and BeO filters would need separate configurable components.

## Conventional detectors

PANDA uses:

- a 1-inch high-pressure \(^3\)He tube for focused configurations;
- a 2-inch high-pressure \(^3\)He tube for collimated configurations;
- approximately 100 mm active height.

The teaching notes give approximately 10 bar fill pressure and roughly 90% counting efficiency. `vPANDA` represents these detectors only through PSD monitors:

| Monitor | Modeled dimensions |
|---|---:|
| Full diagnostic detector | 60 × 200 mm |
| 1-inch window | 25 × 100 mm |
| 2-inch window | 50 × 100 mm |

There is no detailed physical \(^3\)He detector component in the attached model.

## Polarized-neutron configuration

The polarized setup uses:

- Heusler monochromator;
- Heusler analyzer;
- sample-space Helmholtz coils for longitudinal polarization analysis.

The 2015 instrument paper gives a cold-source Heusler incident range of approximately \(k_i=1.1–4.0\) Å⁻¹. The attached `vPANDA` does not implement polarized-neutron transport, spin flippers, guide fields, or polarization matrices. Its scalar PG geometry therefore cannot stand in for the polarized configuration.

## Performance and validation targets

Published sample fluxes for a vertically focused, horizontally flat PG monochromator without collimation are approximately:

| \(k_i\) | Filter | Flux at sample |
|---:|---|---:|
| 1.55 Å⁻¹ | Be | \(1.9\times10^7\) n cm⁻² s⁻¹ |
| 2.662 Å⁻¹ | PG | \(5.5\times10^7\) n cm⁻² s⁻¹ |

Other historical performance figures include:

- energy resolution below approximately 0.03 meV near \(k=1.1\) Å⁻¹ in a flat-monochromator/flat-analyzer, open–60′–open–open configuration;
- inelastic background below approximately one count per minute in favorable configurations;
- an optional evacuated flight-path enclosure, historically around 60 cm long.

These are useful simulation-validation targets but are insufficient on their own to normalize a present-day source model.

## BAMBUS multiplexed secondary spectrometer

The original BAMBUS design uses five concentric, vertically scattering PG(002) analyzer arcs at fixed final energies:

\[
E_f = 3.0,\ 3.5,\ 4.0,\ 4.5,\ 5.0\ \text{meV}.
\]

Original design features include:

- approximately 75° total sample-scattering-angle coverage;
- 2°-wide angular channels;
- approximately 1° dead space between channels;
- neighboring channels alternating between upward and downward scattering;
- approximately 2° × 2° accepted outgoing divergence;
- wide-angle Be filtration and radial collimation;
- a 3 meV lower final-energy choice, with 2.5 meV rejected because of less favorable flux and resolution matching.

The current MLZ page describes BAMBUS as supplying 100 \(q\)–\(\Delta E\) channels and being under commissioning. That present status supersedes the original paper's precise channel-count expectations, while the five-energy geometry and repository simulations remain important design evidence.

## Sample environment

Current headline capabilities include:

- temperatures from approximately 50 mK to above 1300 K;
- vertical magnetic fields up to 12 T;
- closed-cycle refrigerator: approximately 3.5–300 K;
- \(^3\)He system: approximately 0.45–300 K;
- dilution refrigerator: approximately 0.05–6 K;
- adiabatic demagnetization refrigerator: approximately 0.3–300 K.

Older sample-environment wiki values include a closed-cycle cryostat around 2.5–320 K, a \(^3\)He insert reaching approximately 0.35 K, dilution operation around 80 mK, and several 5–12 T magnets. The current MLZ page should be preferred for catalogue headline ranges.

## Audit of the attached `vPANDA` model

The file is valuable for component placement and for exposing intended configurable fields, but the following points should be corrected or explicitly qualified before using it as a TAVI source.

1. **Sapphire thickness is erroneous.** It uses 0.86 m rather than the approximately 0.07 m value explicitly documented in the source model.
2. **Default focusing is disabled.** Monochromator and analyzer bend parameters default to zero even though focusing is fundamental to routine PANDA operation.
3. **Analyzer array is probably stale.** It uses 13 × 6 rather than the later-supported 11 × 5, 55-crystal arrangement.
4. **The included Pb sample is only a test object.** It is not part of the instrument definition.
5. **The detector is represented by monitors rather than a physical detector model.**
6. **Some kinematic code is questionable.** One branch derives an energy-transfer quantity from \(k_f-k_i\), becoming singular for elastic scattering and not representing the general TAS energy relation.
7. **Angle senses are not consistently propagated.** The declared senses are useful, but not every derived angle expression visibly applies them.
8. **Source normalization is uncertain.** The model's Maxwellian source differs from the 2014 model and does not describe the current thermal-source configuration.
9. **Current monochromators are absent.** Cu(111), Si(111), and Heusler configurations are not implemented.
10. **Analyzer-side filters are absent.** PG, cryogenic Be, and cooled BeO configurations are not implemented.
11. **Polarization is absent.** Heusler crystals, fields, flippers, and spin-dependent transport are not modeled.
12. **Zero bend defaults make the virtual instrument physically unrepresentative.** A valid configuration must explicitly calculate or supply focusing values.
13. **The 2026 filename is misleading if read as a hardware date.** The geometry is substantially derived from historical McStas files.

## Known discrepancies and interpretation

### Source–monochromator distance

The 2007 overview, 2015 BAMBUS paper, and 2016 guide paper repeatedly state approximately 7.8 m. The McStas models place the monochromator at approximately model coordinate 8.81 m: roughly 3.81 m to the guide-exit reference plus 5.00 m downstream. The likely explanation is a different source or reference plane, but this is not resolved. A TAVI `source_mono` distance should not silently adopt 8.81 m merely because it is the component coordinate.

### Monochromator–sample distance

- Peter Link 2007: 2.15 m.
- Josh Lim 2014: 2.15 m.
- Attached `vPANDA`: 2.10 m.
- 2016 guide study: 2.10 m available distance.

The difference may record a real later configuration, different component centers, or rounding.

### Analyzer crystal count

The older model and `vPANDA` use 78 crystals, while the later model and teaching documentation give 55. The latter should be preferred provisionally.

### Source spectrum

The old and attached models share one Maxwellian triplet. The 2014 model supplies a different approximation and a spectrum file. Current operation without the cold source requires yet another source description. The catalogue may ultimately need separately named source-era or source-mode configurations.

### Instrument senses

The attached and 2014 simulations support the effective sense tuple (−1, +1, −1). The older Peter Link file uses a different rotation convention. Current control-system motor definitions remain the best final authority.

### Physical versus proposed focusing guide

The 2016 \(m=6\) elliptic guide is well documented as a proposed optimization but is not confirmed as installed by later official material. It should not be enabled by default.

## Questions for PANDA instrument staff

The following short list would eliminate most remaining ambiguity:

1. Which physical reference planes define the published 7.8 m source–monochromator distance?
2. Is the present monochromator–sample distance 2.10 m or 2.15 m, and does it differ by configuration?
3. Is the current PG analyzer definitively an 11 × 5, 55-crystal assembly?
4. Was the proposed 1.48 m, \(m=6\) elliptic focusing guide ever installed?
5. Which source spectrum should represent the upcoming operation without the cold source?
6. What are the current NICOS signs, zero definitions, and hard limits for the monochromator, sample, and analyzer axes?
7. Are measured crystal-specific mosaic distributions and reflectivity curves available for PG, Cu, Si, and Heusler?
8. What are the present motorized slit limits and conventional default apertures?
9. Is the approximately 70 mm sapphire filter installed and usable in the thermal-source configuration?
10. What is the finalized BAMBUS detector/channel geometry, and how does it differ from the 2015 model?
11. Are instrument definition or geometry files available from NICOS, digital engineering records, or a newer McStas branch?

## Suggested source hierarchy for future TAVI authoring

When values conflict, a sensible hierarchy is:

1. current control-system limits and current PANDA staff confirmation;
2. current official MLZ technical data;
3. later physical documentation and teaching material;
4. 2014 McStas model and measured source/material files;
5. 2016 optimization study for optional guide geometry;
6. Peter Link's detailed 2007 model for otherwise undocumented primary geometry;
7. attached `vPANDA` for parameter names and relative placement, after correcting inherited errors.

The strongest practical starting combination is therefore:

- the 2014 `panda.instr` for the conventional spectrometer;
- Peter Link's 2007 model for detailed primary-beam geometry;
- `coldSourceFRM2norm.dat`, `HOPG.rfl`, `C_graphite.lau`, and `Al2O3_sapphire.trm` for simulation inputs;
- the attached `vPANDA` for McStasScript-oriented parameterization;
- the BAMBUS directories for the multiplexed secondary spectrometer;
- the current MLZ page for supported configurations and limits.

## References

1. PANDA instrument page, MLZ: <https://mlz-garching.de/panda>
2. PANDA team wiki: <https://wiki.mlz-garching.de/panda%3Aindex>
3. PANDA simulation wiki: <https://wiki.mlz-garching.de/panda%3Asimulation>
4. PANDA McStas repository: <https://forge.frm2.tum.de/cgit/frm2/panda/mcstas.git/tree/>
5. A. Schneidewind and P. Link, “PANDA: Cold three axes spectrometer,” *Journal of Large-Scale Research Facilities* (2015), DOI `10.17815/jlsrf-1-35`: <https://jlsrf.org/index.php/lsf/article/download/35/pdf/261>
6. PANDA overview, *Neutron News* (2007), DOI `10.1080/10448630701623087`: <https://doi.org/10.1080/10448630701623087>
7. “Optimizing the neutron delivery system of the cold three axes spectrometer PANDA,” *Nuclear Instruments and Methods in Physics Research A* (2016), DOI `10.1016/j.nima.2016.08.060`: <https://www.sciencedirect.com/science/article/abs/pii/S016890021630897X>
8. PANDA teaching notes: <https://wiki.mlz-garching.de/_media/fopra%3Apanda-eng.pdf>
9. BAMBUS design paper, *Journal of Physics: Conference Series* (2015), DOI `10.1088/1742-6596/592/1/012145`: <https://www.helmholtz-berlin.de/pubbin/oai_publication?ID=88338&VT=1>
10. PANDA sample-environment wiki: <https://wiki.mlz-garching.de/panda%3Ase>

