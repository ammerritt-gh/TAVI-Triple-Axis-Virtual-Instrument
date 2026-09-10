# IN12 Scientist Review

Please write comments anywhere. You do not need to fill out a schema or know
TAVI; a correction, drawing, screenshot, or link is enough for maintainers to
process.

TAVI has a working IN12 model, built entirely from public documentation — the
2016 upgrade paper, the current ILL pages, the 1998 analyser construction note,
and ILL's own Takin resolution preset. It runs, and **its angles are sound**:
the scattering senses were settled from the published record as
`SM = −1, SS = +1, SA = −1`, the W configuration.

What the model cannot get from publications is everything that sets **how much
signal** it predicts, and how sharp. Those questions are below, in the order
that would help most. Anything you can answer — even partially, even as "that
number was never written down" — moves us forward.

## Beam and intensity (by far the largest uncertainty)

1. **Is the McStas or SIMRES model of H144 from the upgrade study still
   available?** The 2016 paper says the new guide was calculated in McStas and
   the primary spectrometer in SIMRES plus in-house routines, but neither is
   public. Failing that: is there a **modern source spectrum or MCPL file for
   the H144 exit**? TAVI currently replaces all 115 m of guide with an
   effective 20 × 140 mm source at the exit carrying a generic cold spectrum,
   which dominates our absolute-intensity error.
2. **Velocity selector.** We can confirm only Astrium, more than 36 m upstream,
   fully movable in/out, and a 2.23–6.3 Å design range. Rotor diameter and
   length, blade count, helix angle, speed range, the wavelength-to-speed
   calibration, and the intrinsic transmission are all unconfirmed for the IN12
   unit — published figures we found belong to different Astrium selectors.
3. **Where is the cooled Be filter normally installed?** Published IN12
   experiments put it both in the incident beam (with the selector out) and
   between sample and analyser. Is there a standard configuration?

## Crystal assemblies

4. **What are the physical width, height, and horizontal/vertical gaps of the
   individual crystals in the 11 × 11 monochromator?** We divide the 200 × 160
   mm face by eleven and subtract a guessed 1.5 mm gap — visibly a placeholder.
   A drawing or a supplier sheet would replace it outright.
5. **The conventional PG analyser.** We model eleven 11 mm vertical lamellae in
   **three rows**, on the reading that the fixed vertical focus comes from
   tilting the top and bottom rows (ILL Annual Report 1998). Is three the right
   row count? What are the crystal thickness and the inter-crystal gaps?
6. **What is the analyser's fixed vertical focusing radius?** We use 1.40 m,
   taken from ILL's public Takin preset, which is a resolution parameter rather
   than a mechanical value.
7. **The Heusler(111) analyser.** Blade layout, dimensions, mosaic — and does
   it focus horizontally or vertically? Published IN12 experiments report both,
   so we assume that is configuration-dependent. Is it one reconfigurable
   assembly or two interchangeable ones?
8. **Are our mechanical curvature limits current** — 1.7 m horizontal and 0.5 m
   vertical minima on the monochromator — and **what sign convention do the
   focusing motors use?** We would like to check the signs at more than one
   real setting.

## Geometry

9. **The sample–analyser distance is variable.** ILL says "about 1.3 m" and the
   Takin preset uses 1.46 m. **What is the permitted travel range?** With it we
   can expose L3 as a real instrument setting instead of freezing it at 1.30 m.
10. What slit and diaphragm openings are normally available, and at what
    distances from the monochromator and the sample?
11. What are the Soller collimator lengths and physical clear apertures?
12. Detector gas pressure, efficiency curve, and exact active dimensions.

## Status questions

13. **IN12-UFO.** We can trace it through neutron commissioning (2016 CRG
    report), a 2018 "commissioning phase" contribution, and a 2023 status talk
    describing it as interchangeable with the standard secondary — but we found
    no published experiment stating its data were taken with UFO. **Is it in
    routine user operation today?** We have deliberately left it out of the
    conventional model; if it is in real use, it deserves its own.
14. **Was the second bent-perfect Si(111) monochromator commissioned** after
    the 2024 shutdown? It was planned in a September 2024 presentation but the
    characteristics page still lists only PG(002).
15. **Did the Endurance programme change anything for IN12 or H144?** We could
    find no IN12-specific figures, so we are still using the 2016 flux and
    resolution values.
16. What are the current conventional and polarised configuration presets — the
    settings a user would actually start from?
17. If any of this is easier to answer with a **current raw scan header**
    (NOMAD or equivalent), one file would confirm several of the above at once.

## Your comments

Please type below or annotate the questions above.
