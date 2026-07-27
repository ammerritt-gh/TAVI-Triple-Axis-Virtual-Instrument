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
components are not.

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
sum channel means
    |
    v
optional seeded Poisson draw
```

`PhononDFTSQW` is a composite model containing private phonon and Bragg models.
Those channels remain separate through convolution and calibration; their
calibrated means are summed only immediately before optional Poisson noise.

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
mean_counts =
    N * (phonon_factor * convolved_phonon
       + elastic_factor * convolved_elastic)
```

The built-in `Al_phonon_DFT` calibration is:

- phonon: `6.41e-8`, preserving the established phonon anchor;
- elastic: `0.00023679974108073573`.

The elastic factor is derived from the mean of three identical saved McStas
scans: approximately 4,507 counts at `(2,0,0)`, zero energy transfer, and
`10^7` neutrons, normalized by the reflection's raw
`F^2 = 1.903296`.

With noise disabled, the engine returns the calibrated means. With noise
enabled, it applies a Poisson draw after summing the channel means. Each point
uses NumPy's reproducible generator initialized from `(job seed, point index)`,
preserving seeded scan reproducibility.

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
surfaces do not change.

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
  integration.

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
