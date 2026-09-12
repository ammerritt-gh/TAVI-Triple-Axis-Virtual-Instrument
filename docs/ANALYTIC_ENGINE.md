# TAVI Analytic Engine

> **Status:** live
> **Owner:** TAVI project
>
> **Authority:** Canonical reference for TAVI's deterministic analytic scan engine
>
> **Last verified:** 2026-07-28

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
components are not. This limit is about *sample* models. Environment,
instrument, and sample **background** are a separate additive mechanism
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

- `tavi/background.py` owns the background contract: the fixed source catalog,
  per-source scaling, shapes, fingerprints, count math, and shared metadata
  block. It is engine-independent and is consumed by the Monte Carlo path as
  well.

`PhononDFTSQW` is a composite model containing private phonon and Bragg models.
Those channels remain separate through convolution and calibration; their
calibrated means are summed only immediately before optional Poisson noise.

Background is never derived from the sample model. It arrives at
`evaluate_point` as an already-computed per-point mean and is added *after* the
signal's validity clamp, so a configuration that plants no background leaves every count
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
AnalyticCalibration(phonon=<factor>, elastic=<factor>)
```

For a point simulated with `N` neutrons:

```text
signal_mean =
    N * (phonon_factor * convolved_phonon
       + elastic_factor * convolved_elastic)

mean_counts = signal_mean + background_mean
```

The built-in `Al_phonon_DFT` calibration (which `Pb_phonon_DFT` copies
uncalibrated, see `components/PHONON_DFT.md`) is:

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
`tavi/background.py`, wire identity `tavi.background/2` — one module shared by
both engines, the API server, and the GUI, so a scan record's background
provenance never depends on which engine produced it. Scientific interpretation
of a background (fitting it, subtracting it) remains outside TAVI
(`docs/CONTROL_FEATURES_DESIGN.md` §0, §6.7).
The canonical physicist-facing account of what each source represents, its
equations, calibration, and limitations is
[`BACKGROUND_MODEL.md`](BACKGROUND_MODEL.md); this section concentrates on
engine integration.

A configuration selects independently scaled sources from catalog version 2.
It is **default-off**. A new session prepares the flat, slope, elastic-line,
and broad-tail sources at scale `1.0`; the new aluminum and cosmic sources are
remembered unchecked at scale `1.0`. Each source scale is finite and
non-negative; an omitted source in a request is normalized to disabled at scale
`1.0`.

The request interface is deliberately small:

```json
{
  "catalog_version": 2,
  "enabled": true,
  "sources": {
    "environment_flat": {"enabled": true, "scale": 1.0},
    "sample_elastic": {"enabled": true, "scale": 0.5}
  }
}
```

The catalog fixes source identity, category, shape, base numerics, units, label,
and description. A request can select and scale those definitions but cannot
replace their physics. Session configuration and per-scan overrides use the
same object; an override replaces the session configuration wholesale.

### Mean and event shapes

Callers provide one immutable `BackgroundPointContext` containing `|Q|`, `E`,
the marginalized radial-Q and energy widths when available, and monitor counts.
Mean shapes return a rate in counts per monitor count. Event shapes are kept
out of the smooth Poisson mean and return sparse additive detector events.

| Shape | Rate at energy transfer `E` | Parameters (units) |
|---|---|---|
| `flat` | `rate` | `rate` — counts per monitor count |
| `linear_e` | `max(0, rate0 + slope_per_meV * (E - 0))` | `rate0` — counts/monitor at `E_ref = 0 meV`; `slope_per_meV` — counts/monitor/meV |
| `powder_elastic` | `rate_integrated_111 * sum_i weight_i * exp(-0.5*((|Q|-Q_i)/sigma_Q)^2) * N(E; 0, sigma_E)` | Six structured Al line centers and McStas-derived relative weights, an Al (111) reference rate, and Q/E fallback sigmas |
| `elastic_incoherent` | `rate_integrated * N(E; 0, sigma_E)` | `rate_integrated` — counts/monitor integrated over `E`; `sigma_fallback_meV` — meV (default `0.5`) |
| `elastic_tail` | `rate_integrated * L(E; 0, gamma_meV)` | `rate_integrated` — counts/monitor integrated over `E`; `gamma_meV` — Lorentzian HWHM |

`cosmic_spike` is the event shape. Its expected events per point are
`scale * 0.005 * monitor_counts / 1e10`. Each event amplitude is log-normal
(median 1000 counts, natural-log sigma 0.8), rounded to at least one count and
capped at 100000 counts. Scale changes incidence only, never amplitude.

`N` and `L` are unit-area Gaussian and Lorentzian profiles centred at `E = 0`,
so integrating a planted elastic rate over all `E` returns `rate_integrated`
exactly. `linear_e` is anchored at an explicit reference energy of `0 meV` (not
the scan's first point) and clamps at zero rather than going negative. Rate-like
parameters may not be negative and widths must be strictly positive: a negative
rate would subtract counts.

### Catalog sources and scaling

Category is descriptive provenance, not a hidden scaling rule. Every active
mean source uses the same expression:

`mean counts = monitor counts × source rate(|Q|, E) × source scale`

The catalog contains:

| Category | Source id | Shape and base numerics at scale 1 |
|---|---|---|
| Environment | `environment_flat` | `flat(rate=6e-10)` |
| Environment | `environment_slope` | `linear_e(rate0=2.4e-9, slope_per_meV=-6e-11)` |
| Environment | `environment_cosmic_spikes` | `cosmic_spike(events_per_1e10_monitor=0.005, amplitude median=1000, log_sigma=0.8, cap=100000)` |
| Instrument | `instrument_aluminum_powder` | Six `powder_elastic` lines from fcc Al `a=4.0495 Å`, `rate_integrated_111=6.25e-6`, McStas-derived relative weights, fallback `sigma_Q=0.03 Å^-1`, `sigma_E=0.5 meV` |
| Sample | `sample_elastic` | `elastic_incoherent(rate_integrated=4.5e-9, sigma_fallback_meV=0.5)` |
| Sample | `sample_elastic_tail` | `elastic_tail(rate_integrated=6e-9, gamma_meV=2.0)` |

The aluminum centers are calculated from (111), (200), (220), (311), (222),
and (400): approximately 2.687, 3.103, 4.389, 5.146, 5.375, and
6.206 Å^-1. Their relative strengths use the installed McStas `Al.laz`
values and the `PowderN` line kernel `j|F|²/Q`, normalized to Al (111):

| Reflection | Multiplicity `j` | `|F|` (barn^0.5) | Relative weight |
|---|---:|---:|---:|
| Al (111) | 8 | 1.32 | 1.000000 |
| Al (200) | 6 | 1.30 | 0.629986 |
| Al (220) | 12 | 1.22 | 0.784655 |
| Al (311) | 24 | 1.17 | 1.230862 |
| Al (222) | 8 | 1.15 | 0.379505 |
| Al (400) | 6 | 1.08 | 0.217401 |

One source scale still moves all six together. The Al (111) reference rate was
set empirically to make the line about 500 counts at scale 1 in the current
TAVI visibility reference (roughly 1% of its 50000-count Bragg peak). That
absolute visibility is not a calibrated aluminum cross section and is not
claimed to transfer unchanged across instruments, monitor exposures, or
resolution settings. The relative weights omit texture, geometry, material
thickness, acceptance, and other installation-specific effects. Diffuse sample
scattering is deliberately absent because it is measured sample physics, not
generated background.

### Planting is not resolution-convolved

Signal channels are convolved with the four-dimensional resolution function.
Background sources are **not**: they are written directly in the observed energy
coordinate.

- `sample_elastic` (shape `elastic_incoherent`) is written at the point's
  *marginalized* energy
  resolution width, `sigma_E = sqrt(inv(M)[3,3])` where `M` is the
  FWHM-normalized precision matrix (`deterministic_engine.marginal_sigma`). That is
  the vanadium-like width an instrument actually sees, **not** `1/sqrt(M[3,3])`,
  which is the conditional width at zero momentum offset and is narrower.
  `sigma_E` is computed lazily — only when an `elastic_incoherent` term is
  present, since it costs a 4×4 inversion per point — and falls back to the
  term's own `sigma_fallback_meV` when the resolution solve fails.
- `instrument_aluminum_powder` uses the marginalized radial width
  `sigma_Q = sqrt(inv(M)[0,0])` and the same marginalized energy width. The
  catalog fallbacks apply independently when either width is unavailable.
  Q-E covariance is intentionally ignored.
- `sample_elastic_tail` (shape `elastic_tail`) is a bare Lorentzian pinned at
  `E = 0`; its width is a declared source property, not a resolution
  consequence.

A point whose resolution solve failed still counts background: a real instrument
counts background wherever it counts at all, so only the signal channels drop to
zero there, and `channel_means['background']` is always present.

### Monte Carlo overlay

The McStas engine plants smooth truth as an **additive analytic Poisson
overlay** on the ray-traced counts: the mean comes from the same
`background.mean_counts`, and the integer draw comes from a dedicated per-point
stream `default_rng((background_seed, BACKGROUND_STREAM, point_index))`. The
stream constant (`0x6B67`) keys background draws away from every plain
`(seed, index)` signal stream and is fixed forever — changing it would change
every previously drawn overlay. `background_seed` is the request's `seed` when
given, otherwise a CRC-32 of the job id, and is frozen into the launch state so
a replay redraws the same overlay. A globally disabled configuration constructs
no RNG at all.

The overlay is always Poisson-drawn: `noiseless` is a deterministic-engine
concept the Monte Carlo path ignores. McStas intensity columns are independent
of counts and are left untouched. Ray-traced background remains future work;
catalog version 2 contains only analytically planted sources.

Cosmic events use a distinct fixed stream `BACKGROUND_EVENT_STREAM=0xC05C`.
Each source/point RNG is keyed by seed, event stream, flattened zero-based point
index, and the first 32 SHA-256 bits of the stable source id. Thus source
ordering, added aluminum lines, and skipped points cannot redraw later events.
Both engines add cosmic counts after their ordinary mean/noise draw, including
when the deterministic engine is `noiseless=true`.

### Fingerprints and provenance

Two 16-hex-character digests identify a background:

- **`profile_fingerprint`** hashes the schema, catalog version, catalog
  definitions, global enable, and every normalized source's remembered enable
  and scale state.
- **`effective_fingerprint`** hashes only the physics that can plant counts:
  catalog numerics plus globally and individually active, non-zero-scaled
  sources. This is the pooling identity, so changing an inactive source's
  remembered scale does not split equivalent evidence.

Both deliberately exclude the delivery source, so a session default and a
per-scan override that describe the same physics fingerprint identically.

Every scan's `result.metadata` carries a `background` block built by the one
shared helper `background.metadata_block()` — including when the profile is
disabled, because absence of background is provenance too. It records the schema
id, catalog version, global enable, `delivery_source` (`config_default` /
`per_scan_override`), every normalized source with category, label, enable,
scale, scale meaning, shape, base numerics and units, both fingerprints, and an
applicable `background_seed`. Non-zero event realizations add sparse
`realized_events` records with point index, source id, event count, and added
counts. Event counts are never included in `mean` or
`channel_means.background`. The client-facing field list is in
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
