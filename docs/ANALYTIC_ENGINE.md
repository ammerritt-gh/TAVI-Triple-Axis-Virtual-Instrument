# TAVI Analytic Engine

> **Owner:** TAVI project
>
> **Lifecycle:** Maintained
>
> **Authority:** Canonical reference for TAVI's deterministic analytic scan engine
>
> **Last verified:** 2026-07-27

TAVI owns this engine, its scientific behavior, its calibration, and this
documentation. It is not an upstream McStas feature. McStas remains the
high-fidelity Monte Carlo backend; analytic mode is TAVI's fast deterministic
backend for supported sample models.

The engine exists to answer a narrow operational question quickly: what count
rate should a configured TAVI scan produce after applying the instrument
resolution? It uses the same sample assets as the corresponding McStas
component where possible, but it does not emulate every transport or geometry
effect in McStas.

## Public behavior

Clients select analytic mode by submitting an ordinary scan with
`engine="deterministic"`. Scan commands, API endpoints, GUI controls, result
arrays, seeded reproducibility, and noiseless operation are shared with the
existing deterministic interface.

The selected sample's `SampleSpec.component_type` determines the model:

| Component type | Analytic model |
|---|---|
| `Phonon_DFT` | File-backed phonon branches plus table-backed Bragg reflections |
| `Single_crystal` | Bragg reflections only |
| `SampleSpec` with no component | Zero-intensity model |
| any other component | Explicitly unsupported |

Dispatch is by component type, not by a hard-coded sample name. A new sample
using `Phonon_DFT` therefore uses the analytic `Phonon_DFT` implementation when
it supplies valid dispersion and reflection assets.

Analytic support is deliberately not a general scattering-model plugin
registry. Regular `Phonon_DFT` grids are supported; unrelated continua,
diffuse-scattering models, magnetic component types, and arbitrary McStas
components are not. This limit is about *sample* models. Instrument, sample
environment, and sample diffuse **background** is a separate additive mechanism
configured per session or per scan — see *Background generation* below — not a
sample scattering model.

## Architecture and ownership

The implementation is divided into deep modules with small interfaces:

- `tavi/dispersion_map.py` owns map parsing, strict validation, path-aware
  caching, tessellation, trilinear interpolation, per-point linewidths, and
  numerical energy gradients.
- `tavi/deterministic_engine.py` owns analytic scattering models, resolution
  convolution, channel calibration, count generation, and analytic provenance.
- `instruments/descriptor.py` owns the `SampleSpec` and
  `AnalyticCalibration` configuration contracts.
- `tavi/sample_library.py` owns the configured assets and calibrations for
  built-in samples.
- `TAVI_PySide6.py` owns scan orchestration and exposes deterministic failures
  through the normal job-result path.

The data flow is:

```text
SampleSpec
    |
    v
ground_truth(component_type)
    |
    +-- Phonon_DFT ----> DispersionMap + reflection table
    +-- Single_crystal ----------------> reflection table
    `-- no component ------------------> zero model
    |
    v
per-point resolution convolution
    |
    v
phonon calibration + elastic calibration
    |
    v
sum signal channel means
    |
    v
+ planted background mean (tavi/background.py)
    |
    v
optional seeded Poisson draw
```

- `tavi/background.py` owns the background contract: term shapes, the origin
  taxonomy and its scaling rules, the preset registry, the fingerprints, the
  count math, and the shared metadata block. It is engine-independent and is
  consumed by the Monte Carlo path as well.

`PhononDFTSQW` is a composite model containing private phonon and Bragg models.
Those channels remain separate through convolution and calibration; their
calibrated means are summed only immediately before optional Poisson noise.

Background is never derived from the sample model. It arrives at
`evaluate_point` as an already-computed per-point mean and is added *after* the
signal's validity clamp, so a background-free profile leaves every count
bit-identical to a pre-background TAVI.

## Asset resolution and failure policy

Relative dispersion and reflection filenames are resolved beneath TAVI's
`components` directory. Absolute paths are accepted. The configured filename
and resolved path are retained in result provenance.

Dispersion maps are cached by:

1. resolved path;
2. file size; and
3. nanosecond modification time.

Replacing or modifying a map therefore reloads it without restarting TAVI.

A missing or malformed file explicitly configured for a `Phonon_DFT` sample is
a fatal deterministic-job error. TAVI must not silently substitute equations,
unit structure factors, or another map because that would make analytic and
McStas scans describe different samples.

`Single_crystal` has one compatibility exception. Some built-in reflection
files are owned by a McStas installation and may not be available to a
standalone analytic process. If such a file is unavailable, TAVI may use the
legacy centering rule with unit F-squared. Results identify this as
`reflection_mode="centering_unit_f2_fallback"`. This fallback is never used for
an explicitly configured `Phonon_DFT` reflection file.

## Phonon channel

The file contract is defined in
[`components/PHONON_DFT.md`](../components/PHONON_DFT.md). At an HKL point, the
map evaluates every branch dynamically; no branch count is compiled into the
Python engine.

For a mode with positive interpolated intensity and energy `E`, the engine
creates:

- a Stokes contribution at `+E` with weight `I(n + 1)`; and
- an anti-Stokes contribution at `-E` with weight `In`;

where `n = 1 / expm1(E / kT)` and `kT = T / 11.605` in meV.

Modes satisfying `abs(E) < 1e-10 meV` contribute no one-phonon intensity. This
matches the `Phonon_DFT` component's Gamma-point behavior and prevents the
acoustic branch from masquerading as an elastic line. Result provenance calls
this `zero_energy_policy="match_phonon_dft_skip"`. The elastic peak comes from
the reflection table instead.

An optional seventh map column supplies a per-grid-point phonon linewidth. A
positive interpolated value overrides the sample's global `phonon_gamma`;
otherwise the global value is used. File and sample linewidths are FWHM in
meV; the convolution converts them to HWHM.

The map supplies a numerical energy gradient in reciprocal-lattice units.
For the present cubic principal-axis samples, H, K, and L map to the resolution
frame's parallel, perpendicular, and vertical directions after conversion by
`2*pi/a`. This is exact for that configured geometry but is an approximation
for a general UB orientation; the analytic engine does not currently consume a
UB matrix.

Each phonon line is convolved with the four-dimensional Gaussian resolution
using a pseudo-Voigt profile. With local mode gradient `grad`, covariance
`Sigma`, and `u=(-grad, 1)`, the projected Gaussian variance is:

```text
sigma_squared = transpose(u) * Sigma * u
```

## Elastic channel

The existing LAU/LAZ reflection parser provides HKL and raw F-squared values.
Only finite, positive-F-squared reflections contribute. Forbidden or missing
reflections are absent rather than being synthesized by the analytic model.

Each allowed reflection is treated as a resolution-limited delta function and
convolved with the point's four-dimensional Gaussian resolution. For offset
vector `x` and resolution precision matrix `M`, its uncalibrated contribution
is:

```text
F_squared * exp(-0.5 * transpose(x) * M * x)
```

This repairs the former false dip at exact Gamma: the phonon acoustic mode is
correctly skipped at zero energy while the independent `(2,0,0)` reflection
supplies the elastic peak.

This is not yet a full replica of the McStas Bragg shape. Analytic Bragg peaks
do not include the component's complete Ewald-sphere weighting,
`delta_d_d`, mosaic, sample-shape, absorption, or multiple-scattering effects.
Those are future fidelity improvements, not part of the deterministic delta
model.

## Calibration and count generation

Sample normalization is data, not an engine-global sample-name lookup.
`SampleSpec.analytic_calibration` contains:

```text
AnalyticCalibration(phonon=<factor>, elastic=<factor>,
                    diffuse_background=<factor or None>)
```

`diffuse_background` is optional and belongs to the background model below; it
never enters the signal channels.

For a point simulated with `N` neutrons:

```text
signal_mean =
    N * (phonon_factor * convolved_phonon
       + elastic_factor * convolved_elastic)

mean_counts = signal_mean + background_mean
```

The built-in `Al_phonon_DFT` calibration is:

- phonon: `6.41e-8`, preserving the established phonon anchor;
- elastic: `0.00023679974108073573`.

The elastic factor is derived from the mean of three identical saved McStas
scans: approximately 4,507 counts at `(2,0,0)`, zero energy transfer, and
`10^7` neutrons, normalized by the reflection's raw
`F^2 = 1.903296`.

With noise disabled, the engine returns the calibrated means — including the
background mean, so a noiseless scan is the exact analytic expectation of what
the instrument would count, background and all. With noise enabled, it applies a
Poisson draw after summing the channel means. Each point uses NumPy's
reproducible generator initialized from `(job seed, point index)`, preserving
seeded scan reproducibility.

## Background generation

TAVI *generates* background truth and never infers it. The contract is
`tavi/background.py`, wire identity `tavi.background/1` — one module shared by
both engines, the API server, and the GUI, so a scan record's background
provenance never depends on which engine produced it. Scientific interpretation
of a background (fitting it, subtracting it) remains outside TAVI
(`docs/CONTROL_FEATURES_DESIGN.md` §0, §6.7).

A profile is a list of additive terms plus one strength knob. It is
**default-off**: an unconfigured session plants nothing, and a disabled or empty
profile reproduces the background-free counts bit-identically.

### Strength: the `scale` knob and the 10:1 anchor

Every preset in registry version 2 is anchored on a **signal-to-background ratio
of 10:1**. The `Al_phonon_DFT` sample peaks at ~`4e-8` counts per monitor count,
so a preset's characteristic background rate is ~`4e-9` — the `flat` preset is
exactly that, and the others sum to about it away from their elastic features.

`scale` (optional, float, finite, `>= 0`, default `1.0`) is the user-facing knob
on top of that anchor. It multiplies **every** term's rate uniformly, whatever
its origin or shape, so a whole profile moves with one number: `scale = 0.1` is a
100:1 experiment, `scale = 10` a 1:1 one, `scale = 0` plants nothing while still
fingerprinting as the profile it is. `scale = 0` plants nothing **and refuses
nothing**: the sample-scale requirement below is checked after the strength
knob, so a profile turned all the way down never rejects a scan over a term
whose rate would have been multiplied by zero.

Two properties make it safe to reason about:

- It is applied at **evaluation** time (in `mean_counts`, and so in the Monte
  Carlo overlay too), never folded into the term parameters. A stamped scan
  record therefore reads *"the preset's published numbers, times this knob"*
  rather than an opaque retuned term list nobody can trace to a preset.
- It is part of the **profile fingerprint** (below): a different multiplier is
  different planted physics, hence a different background identity — never a
  cosmetic field two otherwise-identical profiles can disagree on.

Because the knob exists, the roster carries no low/high variants: a preset
chooses the *character* of a background, `scale` chooses its *strength*. That is
why registry version 2 merged the former `flat_low` / `flat_high` pair into one
`flat` preset.

### Term shapes

Each term evaluates to a *rate* in counts per monitor count at the point's
energy transfer `E`. Units are declared per parameter, not per shape, so a
reader of a stamped scan record can tell counts/monitor from
counts/monitor/meV.

| Shape | Rate at energy transfer `E` | Parameters (units) |
|---|---|---|
| `flat` | `rate` | `rate` — counts per monitor count |
| `linear_e` | `max(0, rate0 + slope_per_meV * (E - 0))` | `rate0` — counts/monitor at `E_ref = 0 meV`; `slope_per_meV` — counts/monitor/meV |
| `elastic_incoherent` | `rate_integrated * N(E; 0, sigma_E)` | `rate_integrated` — counts/monitor integrated over `E`; `sigma_fallback_meV` — meV (default `0.5`) |
| `elastic_tail` | `rate_integrated * L(E; 0, gamma_meV)` | `rate_integrated` — counts/monitor integrated over `E`; `gamma_meV` — Lorentzian HWHM |

`N` and `L` are unit-area Gaussian and Lorentzian profiles centred at `E = 0`,
so integrating a planted elastic rate over all `E` returns `rate_integrated`
exactly. `linear_e` is anchored at an explicit reference energy of `0 meV` (not
the scan's first point) and clamps at zero rather than going negative. Rate-like
parameters may not be negative and widths must be strictly positive: a negative
rate would subtract counts.

### Origin and the two scaling bases

`origin` is not decoration — it fixes the scaling base of the term:

| Origin | Mean counts at a point |
|---|---|
| `instrument` | `N * rate(E)` |
| `sample_environment` | `N * rate(E)` |
| `sample` | `N * diffuse_background * rate(E)` |

The profile's `scale` multiplies each of those, so the full expression for a
term is `scale × (base) × rate(E)`.

`diffuse_background` is the sample's own explicit `AnalyticCalibration`
channel. Sample-origin terms **never** borrow the phonon or elastic factor —
diffuse scattering does not scale with a one-phonon cross-section.

When the selected sample has no usable `diffuse_background` (no sample, no
calibration, or a non-finite/negative stored value), there is no implicit
fallback scale, because guessing one would invent truth. Instead:

- a **required** sample-origin term refuses the scan with
  `sample_background_scale_unavailable` (raised as `SampleScaleUnavailable`,
  surfaced by `POST /scan` and `POST /validate` as a 400 / blocker), and
- an **optional** term (`"optional": true`) is silently skipped in the counts
  but loudly recorded — the skipped-term list appears in the metadata block and
  enters the effective fingerprint.

### Planting is not resolution-convolved

Signal channels are convolved with the four-dimensional resolution function.
Background terms are **not**: they are written directly in the observed energy
coordinate.

- `elastic_incoherent` is written at the point's *marginalized* energy
  resolution width, `sigma_E = sqrt(inv(M)[3,3])` where `M` is the
  FWHM-normalized precision matrix (`deterministic_engine.sigma_e_mev`). That is
  the vanadium-like width an instrument actually sees, **not** `1/sqrt(M[3,3])`,
  which is the conditional width at zero momentum offset and is narrower.
  `sigma_E` is computed lazily — only when an `elastic_incoherent` term is
  present, since it costs a 4×4 inversion per point — and falls back to the
  term's own `sigma_fallback_meV` when the resolution solve fails.
- `elastic_tail` is a bare Lorentzian pinned at `E = 0`; its width is a declared
  instrument property, not a resolution consequence.

A point whose resolution solve failed still counts background: a real instrument
counts background wherever it counts at all, so only the signal channels drop to
zero there, and `channel_means['background']` is always present.

### Monte Carlo overlay

The McStas engine plants the same truth as an **additive analytic Poisson
overlay** on the ray-traced counts: the mean comes from the same
`background.mean_counts`, and the integer draw comes from a dedicated per-point
stream `default_rng((background_seed, BACKGROUND_STREAM, point_index))`. The
stream constant (`0x6B67`) keys background draws away from every plain
`(seed, index)` signal stream and is fixed forever — changing it would change
every previously drawn overlay. `background_seed` is the request's `seed` when
given, otherwise a CRC-32 of the job id, and is frozen into the launch state so
a replay redraws the same overlay. A disabled profile constructs no RNG at all.

The overlay is always Poisson-drawn: `noiseless` is a deterministic-engine
concept the Monte Carlo path ignores. McStas intensity columns are independent
of counts and are left untouched. Ray-traced background — simulating the
environment rather than adding it — is the schema-reserved term method
`"simulated"` and is **not implemented**; `"analytic"` is the only method this
version accepts.

### Fingerprints and provenance

Two 16-hex-character digests identify a background:

- **`profile_fingerprint`** — the pre-sample-scaling numerics (schema id,
  enabled flag, `scale`, sorted terms).
- **`effective_fingerprint`** — the same, plus the sample scale actually applied
  and the terms skipped for want of one. This is the pooling identity: two scans
  sharing a profile but differing in effective sample scaling must never pool.
  The sample scale enters this digest **only when a `sample`-origin term
  actually contributed** — the profile is enabled, `scale > 0`, and at least one
  such term was not skipped — so a pure instrument/environment profile pools
  across samples whose `diffuse_background` calibrations differ but never
  touched a count. A profile that plants nothing likewise has no skips to
  record. The metadata block still *reports* the raw `sample_scale` and
  `skipped_terms` it was given: what a run saw is provenance, not identity.

Both deliberately exclude the preset name and the delivery source, so a session
default and a per-scan override that describe the same physics fingerprint
identically.

Every scan's `result.metadata` carries a `background` block built by the one
shared helper `background.metadata_block()` — including when the profile is
disabled, because absence of background is provenance too. It records the schema
id, preset registry version, enabled flag, preset name (`null` for a frozen
numeric profile), the `scale` knob, the delivery `source` (`config_default` /
`per_scan_override`), the applied overrides, the fully numeric (**unscaled**)
terms with their units, the sample
scale, the skipped terms, both fingerprints, and — on a Monte Carlo scan with
background enabled — `background_seed`. The client-facing field list is in
[`API_USER_GUIDE.md`](API_USER_GUIDE.md).

## Result provenance

Deterministic results add an `analytic_model` metadata object. It records:

- channel names;
- dispersion branch count;
- allowed reflection count;
- configured asset filenames;
- resolved asset paths and SHA-256 hashes;
- phonon and elastic calibration values;
- reflection mode; and
- the zero-energy policy.

These fields are additive. Existing API endpoints, scan commands, and GUI
surfaces do not change. Background provenance is a sibling `background` block
(see *Background generation*), stamped by both engines through the same helper
and present even when no background was planted.

Provenance is part of the scientific result. If a new analytic channel, asset,
fallback, or calibration can change a count, its identity must be represented
there.

## Extending supported maps

Adding another branch to a valid `Phonon_DFT` map does not require analytic
engine changes. Add the new contiguous branch index at every HKL grid point,
update the map header, and configure the sample to use the file. The loader
returns all branches and the model creates the corresponding Stokes and
anti-Stokes pair.

Engine work is required only when introducing a different model family or data
contract—for example, a continuum, diffuse map, magnetic cross-section, or a
non-regular grid.

## Verification and maintenance

Primary tests are:

- `tests/test_dispersion_map.py` for parsing, validation, interpolation,
  tessellation, arbitrary branch counts, and cache invalidation;
- `tests/test_deterministic_engine.py` for channels, resolution convolution,
  calibration, Gamma-point behavior, seeded noise, and timing; and
- `tests/test_engine_dispatch.py` for scan-engine selection and result
  integration;
- `tests/test_background.py` for the background contract (shapes, scaling,
  resolution, fingerprints, count math, metadata block);
- `tests/test_background_api.py` for `GET`/`PUT /background`, the per-scan
  override, and `POST /validate` parity; and
- `tests/test_mc_background.py` for the Monte Carlo Poisson overlay and its
  seeded stream.

When changing analytic behavior:

1. update this document;
2. update [`components/PHONON_DFT.md`](../components/PHONON_DFT.md) if the
   shared component/file contract or parity changes;
3. update the API and control-design documents if client-visible behavior
   changes;
4. add or update deterministic tests; and
5. verify both the targeted tests and the full TAVI suite.

TAVI maintainers are responsible for keeping the engine, component contract,
sample calibration, provenance, and documentation in agreement. Similarity to
McStas behavior is a tested compatibility goal, not transferred ownership.
