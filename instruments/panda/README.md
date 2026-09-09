# PANDA (MLZ) — Runnable Package

PANDA is the cold three-axes spectrometer at beam tube SR-2 of the FRM II
(MLZ, Garching), operated by JCNS. It is built for high flux at low incident
energy: a short source-to-monochromator distance, a supermirror guide feeding a
horizontal virtual source, a double-focusing monochromator, a focusing
analyzer, four selectable Soller positions, and low background.

TAVI models it as a plain single-analyzer, single-detector triple-axis
spectrometer, and specifically models **pre-shutdown PANDA**: FRM II has
produced no neutrons since March 2020, and the 2024–25 restart work includes a
new PG(002) monochromator, so the monochromator values here describe the unit
the literature documents rather than the one that will come back online. See
[MODEL_STATUS.md](MODEL_STATUS.md).

What is in the beam, in order:

1. **Source** at the SR-2 guide exit — a Maxwellian (or monochromatic) source
   with the guide's exit aperture, 107 × 138 mm. Guide transport upstream of
   this plane is not simulated; it is folded into the spectrum.
2. **Primary Soller `ca1`** — 20′/40′/60′ or open, 0.50 m long. On the real
   instrument this is the automatic changer; the three downstream collimators
   are changed by hand.
3. **Horizontal virtual source `ms1`** — a variable-width slit 2.18 m past the
   guide exit and 2.82 m ahead of the monochromator. This is PANDA's defining
   primary optic and the object the monochromator images horizontally onto the
   sample.
4. **Monochromator** — PG(002) or Cu(111), 11 × 11 pieces, double focusing.
   The horizontal radius focuses from `ms1`; the vertical radius focuses from
   the guide exit. Both radii are negative because PANDA's monochromator takes
   off on the negative branch.
5. **Soller `ca2`, sample slit `ss1`** — 15′/40′/60′ or open, and PANDA's
   motorized pre-sample aperture.
6. **Sample** — mounted through the shared orientation hierarchy
   (goniometer → chi → cradle → mount) from `tavi/sample_library.py`.
7. **Sample exit slit `ss2`, Soller `ca3`, analyzer** — PG(002), 11 × 5 = 55
   pieces, horizontally focusing.
8. **Soller `ca4`, detector** — the 1″ high-pressure ³He tube used in the
   focusing configuration, 25 × 100 mm.

Component dependencies: `Source_div_Maxwellian_v2` from the central
`components/` tree; `Monochromator_curved`, `Collimator_linear`, `Slit`,
`Monitor`, `PSD_monitor`, `E_monitor`, `Divergence_monitor` and the sample
components from stock McStas. `HOPG.rfl` / `HOPG.trm` resolve from the McStas
data directory. This package adds no assets of its own.

**Scattering senses are (−1, +1, −1)** — monochromator negative, sample
positive, analyzer negative. PANDA is the first TAVI instrument whose
*monochromator* take-off is negative, so every bending radius it uses is
negative.

**What is deliberately not modeled:** BAMBUS (the multiplexed secondary
spectrometer, under commissioning), the Heusler polarized configuration and
all spin-dependent transport, the Si(111) bent-perfect monochromator, the
upstream sapphire filter, the analyzer-side PG/Be/BeO filters, and the
proposed elliptic monochromator-to-sample guide. Each is recorded with its
reason in [MODEL_STATUS.md](MODEL_STATUS.md).

Corrections and current-hardware answers are most useful in
[SCIENTIST_REVIEW.md](SCIENTIST_REVIEW.md); evidence lives in
[references/](references/SOURCES.md).
