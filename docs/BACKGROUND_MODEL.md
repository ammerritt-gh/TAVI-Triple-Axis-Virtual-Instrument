# TAVI Generated Background Model

> **Lifecycle:** Current
>
> **Authority:** canonical reference for the physical interpretation and numerical implementation of generated background in TAVI
>
> **Provenance:** hand-written
>
> **Implementation:** `tavi/background.py`, `tavi.background/2`, catalog version 2

## 1. Scope and scientific boundary

TAVI can add known background truth to a simulated scan. This is a forward
model: the configured sources generate detector counts in addition to the
sample signal. TAVI does **not** estimate a background from simulated data,
fit it, subtract it, or decide whether a measured feature is background.
Those are analysis tasks for a physicist or a client such as ISAR.

The model is intended for:

- testing whether an acquisition or analysis workflow remains reliable in
  the presence of plausible nuisance counts;
- constructing reproducible synthetic data with declared provenance;
- studying how a scan trajectory intersects fixed contaminant features such
  as aluminum powder rings; and
- injecting sparse detector failures that cannot be represented by a smooth
  Poisson mean.

It is not a facility-background prediction. With the exception of
crystallographic line positions and McStas-derived relative aluminum weights,
the catalog normalizations are phenomenological reference values. They do not
encode a measured mass of material, detector efficiency, shielding geometry,
or sample-specific cross section.

## 2. What “source” and “category” mean

A background configuration contains one global gate and one enable/scale pair
for every catalog source. The categories describe the **assumed physical
origin**:

| Category | Interpretation |
|---|---|
| **Environment** | Effects treated as independent of the selected instrument and sample, such as an ambient counting floor or cosmic-ray contamination. |
| **Instrument** | Scattering attributed to the instrument, mounting, cryostat, or other sample-environment material in the beam. |
| **Sample** | Nuisance scattering attributed to the sample itself, but not automatically normalized to the selected sample. |

Category is provenance, not a hidden scaling rule. Every source has its own
dimensionless scale $s$, and no source reads the sample’s analytic
calibration or acquires an automatic amplitude multiplier from the selected
sample. Resolution-broadened sources are the deliberate exception to complete
sample independence: changing the selected sample can change its mosaic and
therefore the calculated $\sigma_Q$ or $\sigma_E$. At a fixed point, exposure,
and fixed resolution widths, the planted source amplitudes are otherwise
unchanged by sample identity.

The catalog deliberately has no “sample diffuse” source. Diffuse scattering is
normally physical sample signal with scientific content; treating it as a
generic removable background would give the same name to two different
physical quantities.

## 3. Configuration semantics

New sessions start with the global background gate **off**. The flat floor,
energy-dependent slope, sample elastic line, and sample elastic tail are
prepared at scale 1; aluminum powder and cosmic-ray sources are prepared
unchecked at scale 1. Nothing is planted until the global gate and at least one
nonzero source are enabled.

For a smooth source $k$, the mean contribution at executed point $i$ is

$$
B_{ik}=N_i\,s_k\,R_k(|Q_i|,E_i),
$$

where:

- $N_i$ is the requested monitor count or neutron exposure;
- $s_k\ge 0$ is the source scale;
- $|Q_i|$ is the absolute momentum-transfer magnitude in Å$^{-1}$;
- $E_i$ is energy transfer in meV, positive for neutron energy loss; and
- $R_k$ is the fixed catalog shape.

The checkbox is the normal off-switch. Scale zero is also valid and contributes
nothing. Disabled sources retain their remembered scales.

For HKL scans, TAVI obtains $|Q|$ from the executed reciprocal-space point.
For angle scans it derives $|Q|$ from $k_i$, $k_f$, and the sample
two-theta angle using the same TAS geometry used elsewhere in the instrument
model.

### 3.1 Point sampling and “integrated” line rates

The Gaussian and Lorentzian elastic coefficients are called *integrated rates*
because they normalize continuous unit-area functions of energy. TAVI
evaluates that density at each requested scan point:

$$
B_i=N_i\,s\,A\,p(E_i).
$$

It does not multiply by the scan step or an energy-bin width. Consequently,
the sum of values from two scans with different point spacings is not itself an
invariant integrated intensity; a numerical integral requires the caller to
apply the appropriate quadrature weights.

The aluminum radial Gaussian follows a different convention: it has unit
height at the powder-ring center, not unit area in $Q$. Changing
$\sigma_Q$ broadens the region over which a scan sees the ring without
changing its configured center strength.

## 4. Common line-shape definitions

TAVI uses the unit-area Gaussian

$$
G(E;\sigma)=
\frac{1}{\sqrt{2\pi}\sigma}
\exp\left[-\frac{1}{2}\left(\frac{E}{\sigma}\right)^2\right]
$$

and unit-area Lorentzian

$$
L(E;\gamma)=
\frac{\gamma}{\pi(E^2+\gamma^2)},
$$

where $\sigma$ is a Gaussian standard deviation and $\gamma$ is a
Lorentzian half-width at half-maximum.

When a source requires an instrument width, TAVI uses the marginalized
covariance of the resolution result:

$$
\sigma_\alpha=\sqrt{\left[M^{-1}\right]_{\alpha\alpha}},
$$

with $M$ the resolution precision matrix in the
$(dQ_\parallel,dQ_\perp,dQ_z,dE)$ basis. This is not the narrower
conditional width $1/\sqrt{M_{\alpha\alpha}}$.

If the resolution result or one marginal width is invalid, that width alone
falls back to the source’s declared value. A failed resolution calculation
therefore removes invalid sample signal but does not make the physical
background disappear.

## 5. Environment sources

### 5.1 Flat floor — `environment_flat`

**Physical interpretation.** A featureless ambient counting floor: counts
that are present throughout a scan but are not attributed to the selected
sample or to a resolved instrument feature. It can stand in for weak room
radiation or a deliberately generic residual counting floor whose structure
is not resolved over the limited scan window. It is not a detector-specific
dark-current model; such an effect would belong to an instrument or detector
model rather than to this environment source.

**Implementation.**

$$
R_{\mathrm{flat}}=6.0\times10^{-10}
\quad\text{counts per monitor count}.
$$

At $N=10^8$, scale 1 contributes 0.06 mean counts per point.

**What the scale means.** The scale multiplies the pointwise floor directly.

**Limitations.** This is intentionally structureless. It has no detector,
time, wavelength, or shielding dependence and should not be interpreted as a
measured dark-current specification.

### 5.2 Energy-dependent slope — `environment_slope`

**Physical interpretation.** A phenomenological ambient background that
changes gradually over the energy-transfer window. It is useful when a
constant baseline would make an analysis unrealistically easy.

**Implementation.**

$$
R_{\mathrm{slope}}(E)=
\max\left[
0,\,
2.4\times10^{-9}
-6.0\times10^{-11}E
\right],
$$

with $E$ in meV. The rate is $2.4\times10^{-9}$ counts per monitor count
at $E=0$, falls linearly on the neutron-energy-loss side, and reaches zero
at $E=40$ meV. It rises linearly for negative energy transfer.

**What the scale means.** The scale multiplies the complete clamped curve.

**Limitations.** This is not a microscopic scattering law and does not impose
detailed balance. The zero at 40 meV is a catalog convention, not an
instrument cutoff.

### 5.3 Cosmic-ray spikes — `environment_cosmic_spikes`

**Physical interpretation.** Rare, high-count detector contamination from a
cosmic-ray interaction or particle shower that escaped pulse-height,
pulse-shape, coincidence, or downstream data-quality rejection. The relevant
failure mode is an isolated point that looks surprisingly intense, not a
small increase at every point.

**Implementation.** Cosmic rays are an event source and never enter the
smooth Poisson mean. At each executed point,

$$
\lambda_i=s\,(0.005)\frac{N_i}{10^{10}},
\qquad
n_i\sim\operatorname{Poisson}(\lambda_i).
$$

For each of the $n_i$ events, TAVI draws an amplitude

$$
A\sim\operatorname{LogNormal}(\ln 1000,\,0.8),
$$

rounds it to a positive integer, and caps it at 100000 detector counts.
Multiple events at one point are summed.

At scale 1 and $N=10^{10}$, the expected incidence is 0.005 events per
point, or one event in a 200-point scan on average. At $N=10^8$, it is one
event per 20000 points on average.

**What the scale means.** Scale changes event incidence only. It does not
multiply the amplitude distribution.

**Noise and reproducibility.** Events are added after ordinary counting noise
and are still realized in deterministic `noiseless` scans: the spike is the
planted contamination, not statistical fluctuation around a tiny smooth mean.
The event generator uses its own stream and is keyed by job seed, flattened
point index, and a stable source-ID key. Reordering sources, changing the
aluminum line list, or skipping another point cannot redraw later cosmic
events.

**Limitations.** The incidence and amplitude distribution are testing
defaults, not a measured cosmic flux or detector-rejection efficiency.
Spatial coincidence and multi-detector shower topology are not modeled.

## 6. Instrument source

### 6.1 Aluminum powder lines — `instrument_aluminum_powder`

**Physical interpretation.** Aluminum in a cryostat, sample holder, mounting
plate, or other machinery can intercept the beam as many randomly oriented
crystallites. Coherent elastic scattering then forms Debye–Scherrer cones.
In reciprocal-space magnitude these appear as powder rings at fixed $|Q|$,
independent of the sample orientation.

A TAS scan does not normally display an entire ring. Its trajectory through
$(Q,E)$ space intersects a ring only when both:

1. the executed $|Q|$ approaches an aluminum reflection; and
2. the energy transfer approaches zero.

The resulting contamination can therefore resemble a narrow, reproducible
peak at a position unrelated to a sample excitation. An HKL coordinate by
itself is insufficient to identify the crossing: it must be converted through
the selected sample lattice to absolute $|Q|$.

**Ring positions.** TAVI assumes fcc aluminum with $a=4.0495$ Å:

$$
Q_{hkl}=\frac{2\pi}{a}\sqrt{h^2+k^2+l^2}.
$$

The catalog includes:

| Reflection | $Q_i$ (Å$^{-1}$) | Multiplicity $j_i$ | McStas $\lvert F_i\rvert$ (barn$^{1/2}$) | Relative weight $w_i$ |
|---|---:|---:|---:|---:|
| Al (111) | 2.687442 | 8 | 1.32 | 1.000000 |
| Al (200) | 3.103191 | 6 | 1.30 | 0.629986 |
| Al (220) | 4.388574 | 12 | 1.22 | 0.784655 |
| Al (311) | 5.146060 | 24 | 1.17 | 1.230862 |
| Al (222) | 5.374884 | 8 | 1.15 | 0.379505 |
| Al (400) | 6.206381 | 6 | 1.08 | 0.217401 |

The multiplicities and structure-factor magnitudes are pinned catalog data
transcribed from McStas 3.6.14 `Al.laz`; TAVI does not read that external file
at runtime. Relative weights follow the McStas `PowderN` kernel,

$$
w_i=
\frac{j_i|F_i|^2/Q_i}
     {j_{111}|F_{111}|^2/Q_{111}}.
$$

This is why Al (311) is slightly stronger than Al (111): its larger powder
multiplicity outweighs its smaller structure factor.

**Implementation.**

$$
R_{\mathrm{Al}}(|Q|,E)=
A_{111}\,
\sum_i w_i
\exp\left[
-\frac{1}{2}
\left(\frac{|Q|-Q_i}{\sigma_Q}\right)^2
\right]
\,G(E;\sigma_E),
$$

with

$$
A_{111}=6.25\times10^{-6}
$$

counts per monitor count integrated over energy at the Al (111) ring center.
All six reflections share one source scale.

TAVI uses the marginalized longitudinal width
$\sigma_Q=\sigma(dQ_\parallel)$ for the radial powder coordinate and the
marginalized $\sigma_E$ from the instrument resolution. Invalid widths fall
back independently to
$\sigma_Q=0.03$ Å$^{-1}$ and $\sigma_E=0.5$ meV.

At scale 1, $N=10^8$, $\sigma_E=0.5$ meV, and the exact Q/E center, the
isolated Al (111) line contributes 498.68 mean counts. This is an empirical
visibility normalization: approximately 1% of the current 50000-count TAVI
reference Bragg peak under those conditions. The corresponding isolated
reference-condition maxima are approximately 499, 314, 391, 614, 189, and
108 counts for (111), (200), (220), (311), (222), and (400).

**What the scale means.** It represents the unknown overall amount and
acceptance of aluminum contamination. Scale 100 makes Al (111) comparable to
the 50000-count reference Bragg peak under the same reference conditions while
preserving the relative line pattern.

**Limitations.**

- The absolute normalization is not an aluminum cross-section calibration and
  is not transferable without qualification across instruments or resolution
  settings.
- Material thickness, absorption, texture, illuminated volume, detector
  acceptance, and exact mounting geometry are omitted.
- The Q and E factors are separable; Q–E covariance is ignored.
- The radial Gaussian is peak-normalized rather than Q-area-normalized.
- The source is analytically overlaid; aluminum is not ray-traced as a
  physical McStas component in this model.

## 7. Sample sources

These sources are attributed to the sample in provenance, but they remain
independent controls. TAVI does not infer their magnitude from composition,
mass, sample selection, phonon intensity, or elastic calibration.

### 7.1 Elastic incoherent line — `sample_elastic`

**Physical interpretation.** Resolution-limited elastic scattering with no
modeled Q structure, attributed to the sample. It is a simplified stand-in for
an incoherent elastic contribution that produces a line at zero energy
throughout the scanned Q range.

**Implementation.**

$$
R_{\mathrm{inc}}(E)=
(4.5\times10^{-9})\,G(E;\sigma_E).
$$

The coefficient is counts per monitor count integrated over energy.
$\sigma_E$ is the marginalized instrument energy width, with a 0.5 meV
fallback.

At $N=10^8$, scale 1, and $\sigma_E=0.5$ meV, the center contributes
approximately 0.359 mean counts.

**What the scale means.** It multiplies the integrated elastic-line
normalization.

**Limitations.** The model is Q-independent and has no composition, isotope,
Debye–Waller, multiple-scattering, or sample-geometry dependence. It is not a
calculation of the selected sample’s incoherent cross section.

### 7.2 Broad elastic tail — `sample_elastic_tail`

**Physical interpretation.** Broad intensity around the elastic position
attributed to the sample. It provides a long-tailed nuisance beneath low-energy
features when a resolution-limited Gaussian alone would be too benign.

**Implementation.**

$$
R_{\mathrm{tail}}(E)=
(6.0\times10^{-9})\,L(E;2.0\ \mathrm{meV}).
$$

The coefficient is counts per monitor count integrated over energy, and the
Lorentzian half-width at half-maximum is fixed at 2 meV. At $N=10^8$, scale
1, and $E=0$, it contributes approximately 0.0955 mean counts.

**What the scale means.** It multiplies the integrated tail normalization.

**Limitations.** The width is a declared source property and is not convolved
with the instrument resolution. This is a phenomenological elastic tail, not
an inferred quasielastic mode or a microscopic relaxation model.

## 8. How the two execution engines plant background

Both engines use the same Qt-free catalog and point evaluator, so a source has
the same configured mean in deterministic and McStas execution.

### Deterministic engine

For each point:

1. calculate the signal-channel means;
2. calculate and add all active smooth background means;
3. return the exact sum when `noiseless=true`, otherwise draw the ordinary
   signal-plus-background Poisson count; and
4. draw and add cosmic events afterward.

Thus cosmic events remain present in noiseless scans but are absent from
`mean` and `channel_means.background`.

### McStas engine

McStas produces the ray-traced detector result. TAVI then:

1. draws the analytic smooth background overlay from its dedicated stream;
2. adds it to detector **counts**, without altering McStas weighted-intensity
   columns; and
3. draws and adds cosmic events from their separate event stream.

The McStas path does not treat `noiseless` as suppression of its ordinary
simulation statistics. Background sources in catalog version 2 are analytic
overlays; no catalog source is currently implemented as ray-traced
sample-environment geometry.

When the global gate is off, every active scale is zero, exposure is zero, or
all sources are individually disabled, TAVI constructs no background random
generator and preserves background-free scan identity.

## 9. GUI and remote control

The Simulation row contains:

`Background: [global checkbox] [Background configuration…]`

The global checkbox applies immediately. The configuration dialog remains
available while the gate is off, stages edits until **Apply**, and groups the
sources by physical origin. **Cancel** leaves the controller unchanged.

The remote request envelope is:

```json
{
  "catalog_version": 2,
  "enabled": true,
  "sources": {
    "instrument_aluminum_powder": {"enabled": true, "scale": 1.0},
    "environment_cosmic_spikes": {"enabled": true, "scale": 0.5}
  }
}
```

`PUT /background` replaces the session configuration wholesale. A
`background` object on `POST /validate` or `POST /scan` replaces the session
configuration for that request; it is never merged with it. Omitted catalog
sources normalize to disabled at scale 1. Unknown IDs, fields, invalid scales,
and catalog-version mismatches are rejected.

This replacement rule lets a campaign-owning client such as ISAR declare its
background truth independently of whatever a TAVI operator last configured.
An ISAR campaign normally freezes that declaration and sends it with every
validation and scan request.

For endpoint details, use [API_USER_GUIDE.md](API_USER_GUIDE.md). `GET /schema`
is the machine-readable authority for the current catalog definitions and
units.

## 10. Provenance, fingerprints, and event records

Every finished scan carries a `result.metadata.background` block, including
background-free scans. It records:

- `background_schema` and `catalog_version`;
- whether the global gate was enabled;
- `delivery_source` (`config_default` or `per_scan_override`);
- every normalized source state and its catalog definition;
- `profile_fingerprint`;
- `effective_fingerprint`;
- background seed when applicable; and
- sparse nonzero cosmic-event realization records.

The profile fingerprint includes every remembered source setting. The
effective fingerprint includes only globally enabled, individually enabled,
positive-scale sources. Delivery route, RNG seed, and realized cosmic events
do not change configured physics and are excluded from identity.

A cosmic realization record has the form:

```json
{
  "point_index": 47,
  "source_id": "environment_cosmic_spikes",
  "event_count": 1,
  "added_counts": 1437
}
```

Zero-event records are omitted. Event counts are not included in the smooth
background mean.

## 11. Choosing a source for a simulation

| Experimental concern | Appropriate source | Important caution |
|---|---|---|
| A weak, nearly constant ambient baseline | Flat floor | Not a measured detector dark rate |
| A baseline that changes across the energy window | Energy-dependent slope | Phenomenological; no detailed balance |
| Rare unfiltered detector excursions | Cosmic-ray spikes | Scale controls incidence, not amplitude |
| Mounting, cryostat, or machinery aluminum in the beam | Aluminum powder lines | Requires simultaneous Q-ring and elastic-energy intersection |
| Q-independent resolution-limited sample elastic scattering | Elastic incoherent line | Not normalized from sample composition |
| Long tails beneath low-energy structure | Broad elastic tail | Not a microscopic quasielastic model |

For a controlled robustness study, enable only the source under study first.
Add sources one at a time before constructing a mixed profile. Because source
scales are independent and the planted truth is recorded, this produces scans
whose failure modes remain interpretable.

## 12. Implementation ownership

The numerical contract lives in `tavi/background.py` and has no Qt dependency.
The GUI renders that catalog rather than owning a second list of sources. Both
simulation engines, API schema, persistence, fingerprints, and metadata call
the same module.

Related references:

- [ANALYTIC_ENGINE.md](ANALYTIC_ENGINE.md) — deterministic signal model,
  resolution use, and engine integration;
- [API_USER_GUIDE.md](API_USER_GUIDE.md) — request and response contracts;
- [CONTROL_FEATURES_DESIGN.md](CONTROL_FEATURES_DESIGN.md) — control/analysis
  boundary and architectural rationale; and
- [../User_Guide.md](../User_Guide.md) — operator workflow.
