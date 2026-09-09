# IN12 Scientist Review

Please write comments anywhere. You do not need to fill out a schema or know
TAVI; a correction, drawing, screenshot, or link is enough for maintainers to
process.

TAVI now has a working IN12 model, built entirely from public documentation —
the 2016 upgrade paper and the current ILL pages. It runs, and its angle
magnitudes follow from the published geometry. What it cannot get from
publications is below, roughly in the order that would help most.

## The one question that matters most

**1. Can you send one current raw scan header (NOMAD or equivalent) showing all
six angles and the three scattering senses?**

This is worth more than everything else combined. TAVI's model of which way each
axis turns is a guess assembled from a 2001 scan file and the fact that the new
monochromator sits on the clockwise branch. If the guess is wrong, the angles
TAVI computes have the wrong sign. A single header — even a screenshot of one —
settles it permanently. An elastic point and an inelastic one would let us check
the whole triangle.

## Geometry and hardware

2. Are the four arm lengths right? We use guide exit → monochromator 1.800 m,
   monochromator → sample 1.800 m, sample → analyser 1.300 m, analyser →
   detector 0.720 m. **Is the sample–analyser distance actually variable, and if
   so between what limits?** No published source says.
3. What is the sample goniometer's angular range?
4. What are the physical width, height, and horizontal/vertical gaps of the
   individual crystals in the 11 × 11 monochromator? We currently divide the
   200 × 160 mm face by eleven and subtract a guessed 1.5 mm gap — visibly a
   placeholder.
5. Is the conventional PG analyser still eleven horizontal blades in one
   vertical row? What are the blade dimensions, gap, thickness, mosaic, and the
   allowed horizontal-radius range?
6. The Heusler(111) analyser: blade layout, dimensions, mosaic — and **does it
   focus horizontally or vertically?** The upgrade paper appears to say both in
   different places.
7. What sign convention do the horizontal and vertical monochromator focusing
   motors use, and are our mechanical minima (1.7 m horizontal, 0.5 m vertical)
   still current?

## Beam and background

8. Is the McStas or SIMRES H144 guide model from the upgrade study still
   available, or is there a modern source spectrum or MCPL file for the H144
   exit? TAVI currently uses an effective 20 × 140 mm source at the guide exit
   with a generic cold spectrum, which is the largest uncertainty in absolute
   intensity.
9. What slit and diaphragm openings are normally available, and at what
   distances from the monochromator and the sample?
10. What are the Soller collimator lengths and physical clear apertures?
11. Where exactly is the optional cooled Be filter installed in current
    configurations, and is it still in routine use?
12. Detector gas pressure, efficiency curve, and exact active dimensions.

## Status questions

13. **What is the present status of IN12-UFO** — installed, commissioned,
    mothballed, incomplete, or design-only? The ILL page still says IN12 "will
    be equipped with" it; we found no publication reporting it in operation. We
    have deliberately left it out.
14. Did the Endurance guide programme change anything for IN12 or H144? The
    published flux and resolution figures we use are from 2016 and we cannot
    tell whether they are pre- or post-Endurance.
15. What are the current conventional and polarised configuration presets — the
    settings a user would actually start from?

## Your comments

Please type below or annotate the questions above.
