# PANDA Scientist Review

PANDA now runs in TAVI. It was built from published sources and the team's
historical McStas files, with no input yet from anyone who operates the
instrument — so the questions below are the places where the model is guessing
and knows it.

Please comment anywhere in this file. A few corrections or a pointer to a
current drawing are worth more than a completed form; TAVI maintainers will do
the structured extraction and coding. `MODEL_STATUS.md` lists every value with
its source and confidence if you want to check something not asked about here.

The seven highest-priority questions are:

1. **Reference planes.** The published source–monochromator distance is ~7.8 m,
   but the McStas models put the monochromator at ~8.81 m of model coordinate.
   Which physical planes does the 7.8 m figure connect? TAVI currently starts
   at the guide exit and calls it 5.00 m to the monochromator, which avoids
   the question rather than answering it.

2. **Monochromator–sample distance.** 2.10 m or 2.15 m — and does it depend on
   configuration? The two numbers split evenly across the sources.

3. **Analyzer array.** Is the PG analyzer definitively 11 × 5 = 55 crystals of
   about 13 × 25 mm? TAVI assumes so, following the 2014 model and the teaching
   notes, over the older 13 × 6 = 78.

4. **Axis signs and zeros.** TAVI assumes monochromator, sample and analyzer
   scattering senses of −1, +1, −1 — i.e. the monochromator and analyzer take
   off to one side and the sample to the other. What are the current NICOS
   motor signs, zero definitions and hard limits for the three two-theta axes?
   The published mechanical range for the monochromator is still the 2007
   figure (20°–132° for PG(002)); is that current?

5. **Focusing limits.** What are the minimum and maximum horizontal and
   vertical bending radii for the monochromator and the analyzer? TAVI applies
   no mechanical clamp today because none is documented. Related: is the
   conventional analyzer's vertical curvature genuinely fixed, and at what
   radius?

6. **Cu(111) monochromator geometry.** How many crystal pieces, what size, what
   mosaic, and what peak reflectivity? Every Cu(111) number in TAVI is a
   placeholder copied from the PG holder.

7. **Aperture limits.** What are the travel limits and normal working settings
   for `ms1` (the horizontal virtual source), `ss1` and `ss2`? TAVI uses the
   historical model's 40 mm / 40 × 80 mm / 40 × 80 mm defaults with no limits.

Two further things that would be valuable but are not blocking:

- The **thermal-source configuration**: which source spectrum should represent
  operation without the cold source?
- The **1.48 m, m = 6 elliptic monochromator-to-sample guide** proposed in the
  2016 optimization study — was it ever installed? TAVI does not model it, on
  the basis that no source after 2016 confirms it.

## Your comments

Please type below or annotate any question above.
