# PANDA Scientist Review

PANDA now runs in TAVI. It was built from published sources and the team's
historical McStas files, with no input yet from anyone who operates the
instrument — so the questions below are the places where the model is guessing
and knows it.

Please comment anywhere in this file. A few corrections or a pointer to a
current drawing are worth more than a completed form; TAVI maintainers will do
the structured extraction and coding. `MODEL_STATUS.md` lists every value with
its source and confidence if you want to check something not asked about here.

A literature pass on 2026-09-09 answered several of the original questions from
the published record, so this list is shorter and sharper than it was. What
remains is what the public literature genuinely does not contain.

The five highest-priority questions are:

1. **The new monochromator.** Restart reports describe a new double-focusing
   PG(002) monochromator. Every monochromator number in our model — 11 × 11
   pieces of about 20 × 18 mm on 2 mm gaps, 20′ mosaic, 20°–132° travel, and the
   2.10 m distance to the sample — describes the *old* unit. What is the new
   one? Crystal count and arrangement, piece size, mosaic, focusing ranges,
   two-theta travel, and whether the monochromator–sample distance changed.

2. **Axis signs and zeros.** We assume monochromator, sample and analyser
   scattering senses of −1, +1, −1. The teaching notes confirm the convention is
   positive counter-clockwise with 2Θ_S positive, which supports the sample
   sign, but no document we could find states all three. What are the current
   NICOS motor signs, zero definitions and hard limits for the three two-theta
   axes? This is the single value most of our angle output depends on.

3. **Focusing limits, and the analyser's fixed vertical radius.** Two papers
   confirm the conventional analyser is vertically fixed and horizontally
   variable — but at what vertical radius? And what are the minimum and maximum
   horizontal and vertical bending radii for the monochromator and analyser? We
   apply no mechanical clamp at all, because no published limit exists, which
   means our model can request an impossible curvature.

4. **Cu(111) monochromator geometry.** The unit exists and has been commissioned,
   but every Cu(111) number in our model is a placeholder copied from the PG
   holder: 11 × 11 pieces of 20 × 18 mm, 30′ mosaic, peak reflectivity 0.7. How
   many pieces, what size, what mosaic, what reflectivity? (Minor: the MLZ page
   prints d = 2.08 Å where a = 3.6149 Å gives 2.087 Å, which rounds to 2.09. We
   use 2.087. Is 2.08 a legacy value?)

5. **Reference planes, and the analyser array's dimensions.** Two smaller
   things. First: the published 7.8 m source–monochromator distance is stable
   across 2007, 2015, 2016 and 2023, but the McStas models put the
   monochromator at about 8.81 m of model coordinate. Which physical planes does
   the 7.8 m connect? Second: the 55-crystal analyser count is confirmed, but is
   it arranged 11 × 5, and are the crystals about 13 × 25 mm on 3 mm gaps?

Two things that would be valuable but are not blocking:

- Measured mosaic distributions for the PG crystals, and the detector's active
  height and fill pressure. We use 20′ and 25 × 100 mm at 10 bar; all four are
  simulation assumptions with no PANDA-specific source behind them.
- The **thermal-source configuration**: which source spectrum should represent
  operation without the cold source?

Settled since the last revision, for information — no need to answer these
unless we have them wrong: the analyser is 55 crystals, not 78; the old
monochromator was 121; the conventional analyser's vertical focusing is fixed;
the 1″ tube is the focusing-mode detector and the 2″ the collimated one; and the
2016 proposed 1.48 m, m = 6 elliptic monochromator-to-sample guide was never
confirmed installed, so we do not model it.

## Your comments

Please type below or annotate any question above.
