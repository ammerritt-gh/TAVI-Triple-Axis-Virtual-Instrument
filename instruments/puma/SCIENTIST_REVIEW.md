# PUMA Scientist Review

> **Status:** live

Thank you for looking at this. Please write comments anywhere in this file—in
sentences, fragments, or directly beside something that looks wrong. There is
no form to complete and no formatting to preserve. TAVI maintainers will do
the translation into code.

If you only have five minutes, these are the most useful questions:

1. Are the four arm lengths 2.150, 2.290, 0.880, and 0.750 m correct for the
   current instrument, and exactly which reference points define them?
2. What are the physical scattering senses/signs of the monochromator, sample,
   and analyser axes?
3. Are the PG monochromator/analyser slab sizes, counts, and mosaics in TAVI
   correct? (The bending limits and the analyser's fixed vertical radius are
   answered — see below.)
4. Which collimators, slits, filters, and detector geometry are actually
   installed, and where are they?
5. Which NMO and velocity-selector options describe real or planned hardware,
   rather than simulation experiments?

## What TAVI currently assumes

TAVI uses a simplified thermal source, a curved PG monochromator, four
collimation positions, slits around the sample, an optional nested mirror
optic, a curved PG analyser, and one ideal detector. It assumes the analyser's
vertical radius is fixed at 0.8 m and applies minimum bending radii (2.0 m
horizontal, 0.5 m vertical, on both crystals).

## Answered

**Bending limits and the fixed analyser vertical radius (question 3, in
part):** the operator reviewed these against PUMA's internal instrument
documentation and confirmed them with the instrument scientist on
2026-09-11 — the 2.0 m / 0.5 m minimum bending radii and the analyser's
fixed 0.8 m vertical radius are correct as modeled. This is a review-and-
confirmation, not an independently citable published source, and not a
guarantee against a future mechanical change. The slab sizes, counts, and
mosaics half of question 3 is still open.

## Other missing information

We would welcome a current instrument drawing, source spectrum, component
apertures/positions, crystal specifications, detector efficiency information,
and a small set of trusted angle readbacks for comparison.

## Your comments

Please type anywhere below—or annotate the text above. Even “this number looks
wrong” is useful.
