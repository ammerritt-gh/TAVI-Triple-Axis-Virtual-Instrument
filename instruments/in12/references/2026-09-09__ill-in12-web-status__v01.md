# IN12 current-status web check — 2026-09-09

Captured 2026-09-09 by re-fetching the live ILL IN12 pages and searching for
post-2016 changes, before promoting the IN12 package from `research` to
`runnable`. The purpose was to find anything that had moved since the
2026-07-18 research dossier (`2026-07-18__in12-research-dossier__v01.md`),
which was built mainly from the 2016 Schmalzl upgrade paper.

**Headline: nothing contradicts the dossier.** Every figure re-checked against
the live ILL pages is unchanged. IN12-UFO is still described in the future
tense a decade on.

Pages fetched: the ILL IN12 characteristics, instrument-layout, description and
contacts pages, plus the FZ-Jülich JCNS IN12 page (no usable content), plus
targeted searches on ScienceDirect, arXiv, GitHub code search and the ILL
Endurance programme materials. The ILL nav advertises a dedicated
"Multi-analyzer IN12-UFO" page, but the URL 404s on direct fetch — its content
could not be read.

---

## 1. Operating envelope — confirmed, unchanged

| Quantity | Value |
|---|---|
| Wavelength | 1.26 < λ/Å < 6.3 |
| Incident wavevector | 1.0 < ki/Å⁻¹ < 5.0 |
| Incident energy | 2.1 < Ei/meV < 42 |
| Flux at sample, ki = 2 Å⁻¹ | 1.04×10⁸ n cm⁻² s⁻¹ double-focusing; 8.4×10⁷ with the velocity selector; 5.02×10⁷ with selector + 60′ |
| Energy resolution | 22 / 75 / 110 μeV FWHM at Ei = 2.3 / 4 / 5 meV with 30′; 150 μeV at ki = 1.5 Å⁻¹ double-focusing |

Source: ILL IN12 characteristics page. These match the 2016 paper exactly — no
change registered on the live site.

## 2. Distances

| Distance | Value | Confidence |
|---|---|---|
| Guide exit → monochromator (L1) | 1.8 m | confirmed (instrument-layout page) |
| Monochromator → sample (L2) | **no number on either live page** | not found on the live site; the 2016 paper's 1.8 m Rowland-matched value stands |
| Sample → analyser (L3) | "about 1.3 m" | confirmed; **whether it is variable, and over what range, is not stated anywhere** |
| Analyser → detector (L4) | 0.72 m | confirmed |
| Cold source → instrument | ~115 m via guide H144 | confirmed |

## 3. Angular limits

| Axis | Range | Confidence |
|---|---|---|
| Monochromator 2θ | **−10° to −140°** | confirmed — the live page still publishes the range as entirely negative, which is the evidence for the clockwise/negative monochromator branch |
| Sample 2θ | −120° to +120° | confirmed |
| Analyser 2θ | −140° to +140° | confirmed |
| Sample goniometer | not given on either live page | not found |

## 4. Monochromator

PG(002), double focusing (horizontal + vertical), **11 × 11** crystals,
**20 cm × 16 cm** overall — all confirmed on the live layout/characteristics
pages and matching the dossier.

Not found on the current site: the numeric mosaic (the dossier's 0.4° = 24′
comes from the 2016 paper), the horizontal/vertical curvature ranges, and any
per-slab dimension or gap. Per-slab geometry appears to be published nowhere.

## 5. Analysers

Standard PG(002) and polarisation Heusler(111) are both confirmed as the
current pair; no replacement or additional analyser is mentioned anywhere.

The specific numbers — 12.2 × 11.8 cm PG, 7.5 × 14.5 cm Heusler, blade counts,
mosaics — are **not restated anywhere on the current site**, and a targeted
search found no other page or paper carrying them. They remain 2016-paper /
ILL-table values with no independent confirmation.

## 6. IN12-UFO — the key status question

**Still future tense. Not commissioned, as far as any public source shows.**

The live ILL instrument-layout page says, in 2026: *"As a further option, IN12
will be equipped with a 2-dimensional position-sensitive detector and an array
of fifteen analysers which can be rotated and positioned individually…"* —
wording unchanged from the upgrade era.

No paper, conference proceeding, ILL or JCNS annual-report entry, or arXiv
methods section from **2020–2026** describes IN12-UFO as commissioned, in user
operation, or abandoned. The only substantive UFO references found are the
original proposal-era papers (Kempa et al., *Physica B*, 2004/2006), both
pre-dating the 2012 upgrade. A December-2024 arXiv paper (YbBr₃ magnon decay)
uses IN12 but gives no detail on which secondary spectrometer.

Confidence: **probable, not confirmed** — the one page most likely to carry an
authoritative statement (`…/description/multi-analyzer-in12-ufo`) could not be
fetched.

## 7. Post-2016 changes

- **Endurance guide programme** (completed 27 November 2024) covered the guide
  hall that carries H144. The programme's general claims are ×4–25 count-rate
  gains across instruments, but **no IN12- or H144-specific before/after
  figures were found**. Whether IN12's flux figures above are pre- or
  post-Endurance is unresolved.
- **Cryopad / longitudinal and spherical polarisation analysis**: still listed,
  no change.
- **Sample environment**: 15 T magnet, high pressure, electric field, vacuum
  tank, ³He and dilution inserts — all still listed, nothing new found.
- **Detector, selector, incident polariser**: no change documented. The
  supermirror incident polarisation is still listed at >95 % with a flipping
  ratio of 20–27 depending on energy.
- **MIEZE / NRSE / spin-echo**: no mention anywhere; apparently absent.

## 8. Collimation and filters

Gd-coated Soller collimators **10′, 20′, 30′, 40′, 60′, 80′** — confirmed,
exactly as the dossier records.

The cooled beryllium filter is **not mentioned on any current ILL page found**.
It is physically plausible at the long-wavelength end and appears in
experimental papers, but current routine use could not be confirmed.

## 9. Detector

Single vertical ³He tube, **12 cm high × 5 cm diameter** — confirmed on the
current characteristics page, matching the dossier. Gas pressure and efficiency
are not published.

## 10. Contacts

First responsible **Karin Schmalzl**; co-responsible **Stéphane Raymond**
(confirmed by direct page fetch). Search summaries additionally name Wolfgang
F. Schmidt as a co-responsible and Bruno Vettard as technician — probable, not
confirmed from the fetched page body.

## 11. Public simulation models

**None found for the post-upgrade instrument.** A GitHub code search of the
McCode repository for "IN12" returned zero files: there is no `ILL_H144`
model, no updated IN12 instrument file, and no evidence the historical
`ILL_H142_IN12` example was ever renamed or updated to the H144 geometry. No
standalone MCPL source or SIMRES model for IN12 or H144 was located.

---

## Corrections to the 2026-07-18 dossier

None of substance. One correction of emphasis: **IN12-UFO should be treated as
not commissioned and probably still notional**, not as an imminent capability.

## Still unknown after this check

1. L2 (monochromator–sample) — no number on any live page.
2. Whether L3 is variable, and over what range.
3. Sample goniometer angular range.
4. Monochromator mosaic on the current site, curvature ranges, per-slab
   dimensions and gaps.
5. Analyser blade counts, mosaics, and the published face dimensions —
   unconfirmed outside the 2016 paper.
6. Whether a cooled Be filter is in current routine use.
7. ³He detector pressure and efficiency.
8. ILL's own current status statement for IN12-UFO (page 404s).
9. Any IN12/H144-specific quantitative gain from the 2024 Endurance completion.
10. Any post-upgrade McStas / SIMRES / MCPL model for IN12 or H144.
11. The two additional contact names, from the Contacts page body itself.
