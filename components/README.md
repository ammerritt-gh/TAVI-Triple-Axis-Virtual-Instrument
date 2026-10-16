# Custom McStas Components

> **Status:** live

This folder contains modified and custom McStas components used in the TAVI simulation framework. These components extend or fix functionality from the standard McStas library to better suit the needs of triple-axis instrument simulations.

## Component Overview

| Component | Based On | Key Modifications |
|-----------|----------|-------------------|
| `FlatEllipse_finite_mirror_optimized.comp` | Custom NMO component | Mirror table files, MPI fixes, binary search optimization |
| `Optic_Phonon_simple.comp` | `Phonon_simple.comp` | Optic phonon dispersion, SCATTER keyword |
| `Phonon_DFT.comp` | TAVI custom component | Regular-grid multi-branch phonons plus table-backed Bragg scattering |
| `Phonon_simple_SCATTER.comp` | `Phonon_simple.comp` | Added SCATTER keyword |
| `Source_Maxwell_direct.comp` | `Source_gen.comp` (spectrum and facility table) | Facility spectrum of up to three Maxwellians sampled directly in energy, one weight for every ray; an unphysical flat-band mode for fast statistics |

---

## Phonon_DFT.comp

### Purpose

Models coherent one-phonon Stokes/anti-Stokes scattering from a regular H-K-L
dispersion map together with coherent elastic Bragg scattering from a
reflection table. TAVI's deterministic analytic engine reads the same two
assets.

This component, its shared map format, and its documentation are owned and
maintained by the TAVI project, not upstream McStas. The canonical component
and file-contract reference is [`PHONON_DFT.md`](PHONON_DFT.md); the analytic
backend is documented in
[`docs/ANALYTIC_ENGINE.md`](../docs/ANALYTIC_ENGINE.md).

---

## FlatEllipse_finite_mirror_optimized.comp

### Purpose
Simulates Nested Mirror Optics (NMO) for neutron focusing using flat elliptical mirrors.

### Differences from Standard Components

1. **Mirror Table File Support**: Users can provide mirror positions (B-values) and per-mirror m-values from external files rather than calculating them at runtime:
   - `rfront_inner_file`: File containing mirror radial positions
   - `mirror_mvalue_file`: File containing per-mirror front/back coating m-values

2. **Binary Search Optimization**: Implements `find_mirror_channel_binary()` for O(log n) mirror channel lookup instead of linear search, significantly improving performance for large mirror arrays.

3. **MPI Integration Fixes**: 
   - Proper MPI rank detection to prevent duplicate console output
   - `MPI_Barrier()` synchronization after initialization
   - Safe error handling with `MPI_Abort()` instead of bare `exit()`
   - Only rank 0 prints status messages

4. **Silicon Refraction Modeling**: Optional silicon substrate refraction for more accurate neutron transport through mirror substrates.

### Associated Header Files

- `calciterativemirrors_fixed.h`: Fixed version of mirror calculation routines
- `conic_finite_mirror_fixed.h`: Fixed version of conic mirror geometry routines

The `_fixed` versions of these headers contain bug fixes and MPI-safe modifications compared to the original versions (`calciterativemirrors.h`, `conic_finite_mirror.h`).

### Example Input Files

- `example_bvalues.txt`: Sample mirror position file format
- `example_mvalues.txt`: Sample per-mirror m-value file format
- `PUMA_NMO_HorizontalFocusing.txt`: PUMA-specific horizontal focusing configuration
- `PUMA_NMO_VerticalFocusing.txt`: PUMA-specific vertical focusing configuration

---

## Optic_Phonon_simple.comp

### Purpose
Simulates inelastic neutron scattering from optical phonons in a sample.

### Differences from Standard `Phonon_simple.comp`

1. **Optic Phonon Dispersion**: Implements an optical phonon branch with parameters:
   - `zero_energy`: Energy at the zone center (Γ point)
   - `maximum_energy`: Maximum phonon energy
   
   The dispersion relation is:
   ```
   ω(q) = sqrt(zero_energy² + maximum_energy² × Jq/6)
   ```
   where Jq is the structure factor for an fcc lattice.

2. **SCATTER Keyword**: Includes the `SCATTER` keyword at the scattering point, enabling proper neutron history tracking and compatibility with `SPLIT` and other McStas features that rely on scattering event markers.

3. **Extended Parameter Array**: Uses 12 parameters (`parms[0-11]`) instead of 11 to accommodate the optical phonon parameters.

### Use Case
Ideal for simulating materials with optical phonon modes, where the standard acoustic phonon model (`Phonon_simple`) is insufficient.

---

## Phonon_simple_SCATTER.comp

### Purpose
Standard acoustic phonon scattering with proper McStas SCATTER event marking.

### Differences from Standard `Phonon_simple.comp`

1. **SCATTER Keyword Added**: The single modification is adding `SCATTER;` after `PROP_DT(dt+t0);` in the TRACE section:
   ```c
   PROP_DT(dt+t0);             /* Point of scattering */
   SCATTER;                     /* SCATTER keyword added by AMM */
   ```

### Why This Matters
The `SCATTER` keyword is essential for:
- Proper neutron weight tracking
- Compatibility with `SPLIT` for variance reduction
- Correct behavior with `EXTEND` blocks that check for scattering events
- Monitor components that filter by scattering history

The standard `Phonon_simple.comp` in McStas omits this keyword, which can cause issues in complex instrument simulations.

---

## Source_Maxwell_direct.comp

### Purpose
The neutron source for every TAVI instrument: a rectangular emitter with the flux
spectrum of a facility moderator, sampled directly in energy. It is written to
upstream McStas standard (`%I/%D/%P/%L/%E/%VALIDATION` header, validated input,
`rand01()` guarded, no heap use in TRACE) so it can be contributed to
`mcstas-comps/contrib/`; submission is outside this project's current work. It
replaces `Source_div_Maxwellian_v2.comp` and `Source_gen_Maxwellian.comp`.

### Two modes (`flat_band`, a runtime setting; switching never recompiles)
- **Full spectrum** (`flat_band=0`, the default). The spectrum is exactly the one
  `Source_gen` builds from the same `T1..T3`, `I1..I3`: the sum of up to three
  Maxwellians. The component picks an active pair with probability Ii/sum(I) and
  draws the energy from the Gamma(2, theta) density E exp(-E/theta)/theta^2 with
  theta = C*T/949 meV, C = VS2E*K2V^2*4*pi^2 (about 81.80 meV A^2), the same
  constant `Source_gen` implies. There are no energy cut-offs.
- **Flat band** (`flat_band=1`). E is uniform in E0 +- dE and the facility spectrum
  plays no part. This mode is deliberately unphysical: it exists to get good
  statistics around one energy quickly, its total intensity scales with dE, and
  its absolute intensity must not be compared with the full spectrum.

Directions are drawn with McStas's own `randvec_target_rect_angular`, as
`Source_gen` does: uniform per steradian in a `focus_aw` x `focus_ah` window
(full widths). **Every ray leaves with the same weight**, in both modes. The source
never reweights a ray by its energy, direction or position (decision 1 below).

### Parameters
| Parameter | Units | Description |
|-----------|-------|-------------|
| `xwidth`, `yheight` | m | Source rectangle |
| `focus_aw`, `focus_ah` | deg | Full horizontal width and vertical height of the emission window (at most 360 and 180) |
| `T1`, `I1` | K, n/(s cm^2 sr) | First Maxwellian and its integrated flux |
| `T2`, `I2`, `T3`, `I3` | K, n/(s cm^2 sr) | Second and third pair, `0` = unused (a pair is active when T>0 and I>0) |
| `flat_band` | 0 or 1 | `0` full spectrum, `1` flat band |
| `E0`, `dE` | meV | Flat band centre and half-width; read only when `flat_band=1` |
| `flux` | n/(s cm^2 sr meV) | Flat-band flux per energy unit (default 1); read only when `flat_band=1` |

Invalid input stops the run: INITIALIZE prints the component, the instance and
the parameter with its value on stderr and exits. It refuses a non-positive or
non-finite `xwidth`, `yheight`, `focus_aw`, `focus_ah`, or a window beyond 360 x 180
deg; a negative or non-finite T or I; no active pair; an I sum that overflows; an
active pair whose energy scale is not finite; a ray weight that is not finite
or not positive; `flat_band` other than 0 or 1; and, with
`flat_band=1`, a `dE` or `flux` that is not positive, or `E0 - dE <= 0`.

### Facility table
The `%D` block of the component lists `Source_gen`'s facility rows (PSI, ILL VCS,
HCS, thermal tube and hot source, HZB, FRM2 cold and thermal, LLB, TRIGA) unchanged,
in its `T1=..,I1=..` notation. Every row pastes into the component and works (the
HZB cold row's `radius` does not exist here: give `xwidth` and `yheight`). The
verification tool checks the table against the installed `Source_gen.comp`:
labels, order and numbers.

### Versioning
The `* Version:` line in the `%I` header is the component's version. There is one
file name and the version lives inside it (decision 2 below). Every change to the
physics, the weight or the parameters bumps the version and gets a changelog line.
A new file name is for a breaking change only, meaning the interface: a rename, a
removed parameter, or a parameter whose meaning changes. A correction that makes
the component do what it always documented goes in place with a version bump.
TAVI stamps the component name, version and the first 12 hex digits of the file's
SHA-256 (line endings normalised to LF) into its outputs; the hash catches an
edit made without a version bump. TAVI does not refuse a version mismatch.

### Test instrument
`examples/Tests_sources/Test_Source_Maxwell_direct/Test_Source_Maxwell_direct.instr`
(upstream layout, `%INSTRUMENT_SITE: Tests_sources`, three `%Example:` lines) puts
a wavelength, energy, position and divergence monitor right after the source.
`SRC=0` uses this component, `SRC=1` uses `Source_gen` with the same T/I and
window. Bin counts and ranges (`nL`, `nE`, `Emin`, `Emax`, `Ndiv`) are parameters
so the verification can set them.

### Verification
`tools/verify_source_maxwell_direct.py` compiles the test instrument once with
`mcrun`, runs it in parallel (no MPI, fixed seeds, timeouts that kill and report)
and checks the monitors' `I`, `I_err` and `N`:

    micromamba run -n tavi-dev python tools/verify_source_maxwell_direct.py

It takes about 15 s on a 16-core machine, prints the path of its report
(`output/source_verification/<timestamp>/report.md`) and exits non-zero on any
failure. It is never run by pytest. **Run it before any change to the component
ships.** The seven checks:

1. The spectrum equals `Source_gen`'s for all 12 facility rows and the single
   temperature, in the wavelength and the energy monitor (pull per bin, chi2
   within n +- 4 sqrt(2n) over at least 50 bins; a run with fewer bins is repeated
   at 4x the rays once, then fails). Control: I2 doubled must fail.
2. The absolute total equals the analytic sum within 4 sigma.
3. One weight: I/N equals the predicted weight to 1e-4 in every non-empty bin of
   every monitor, and I_err^2 N = I^2. Control: `Source_gen`'s output must fail.
4. Full spectrum ignores `E0` and `dE` (bit-identical arrays).
5. Flat band: counts only inside E0 +- dE, level flux x area x Omega per meV, uniform.
6. Bad input is refused with the parameter named; the same values are accepted
   where the mode does not read them.
7. Uniform per steradian, in a 60 x 120 deg window. McStas's `Divergence_monitor`
   measures the vertical angle as atan2(vy, vz), not the latitude the source draws
   uniformly, so the tool derives the exact expectation for that variable. The data
   must fail the uniform-in-angle and uniform-in-latitude expectations.

**Verification record** (the same summary as the component's `%VALIDATION`):
verified 2026-10-16 with McStas 3.7.1 (git) and MSVC, component version 1.0, file
hash 547bf45f49e3; ray counts 2e7 per facility row and source, 5e6 for the flat
band and the wide window, 1e6 for the E0/dE comparison; all seven checks passed, with
11 refusals (including focus_aw=0 and focus_ah=181). The I-sum and ray-weight overflow
refusals were checked by hand, not by the tool. Run: about 17 s wall on the 16-core
machine (tool total 17.3 s, compile 1.4 s); report
`output/source_verification/20261016-174434/report.md` (gitignored).
Spectrum: chi2/n from 0.87 to 1.11 over 26 comparisons (at least 276 bins each);
the I2-doubled control gave chi2 6786 and 6693 and failed. Totals: 26 within 1.26
sigma. One weight: deviation at most 5e-10. Flat band: level ratio 1.000000.
Vertical angle: chi2 95.2 for 128 bins (band 64 to 192), against 117325 for
uniform-in-angle and 167130 for uniform-in-latitude. Resolution: an energy-scale
error as small as 0.04 percent (kT instead of C*T/949) is not detected.

---

## Other Files

### Instrument Files
- `PUMA_McScript.instr`: McStas instrument definition for the PUMA spectrometer
- `PUMA_McScript.c`: Compiled C code for the PUMA instrument

### Configuration Files
- `PUMA_mirror_array.txt`: Mirror array configuration for PUMA

### Documentation
- [`NMO_Component_Documentation.md`](NMO_Component_Documentation.md): Extended documentation for NMO components
- [`PHONON_DFT.md`](PHONON_DFT.md): Canonical `Phonon_DFT` component and dispersion-file contract

---

## Usage Notes

1. **Component Path**: Ensure this `components/` folder is in your McStas component search path, or use absolute paths in your instrument file.

2. **Header Dependencies**: The NMO component requires both `_fixed.h` header files. The original (unfixed) versions are retained for reference.

3. **MPI Simulations**: When running with MPI, use `FlatEllipse_finite_mirror_optimized.comp` to avoid duplicate output and potential race conditions.

4. **Compatibility**: These components are tested with McStas 3.x. Some modifications may be required for McStas 2.x.

---

## Decisions

### 2026-10-16 — no post-hoc weighting: rays are shaped only at the source
**Ruled by:** operator. **Question:** does the efficient band mode carry the facility profile's spectrum (a flat band reweighted by the profile at each ray's energy, as `Source_gen` does for a narrow window), or stay flat? **Options:** A, both modes describe the same source and per-ray weights vary; B, a deliberately unphysical flat band in which every ray has the same weight. **Decision:** B, and as a principle for the whole source: "B. It's a deliberately unphysical instrument here." (line 246) "My guiding principle here is that we do direct sampling. The neutrons that we only change the neutrons at the source. We never back calculate at the end here." (line 246) "We are trying to give either a truthful, directly sampled spectrum that's Maxwellian distributed, or an unphysical but more computationally efficient square intensity right at EI that's used just for getting good statistics with known limitations." (line 248) **Why:** "And so weighting like that is very dangerous and something we don't want to do." (line 246) The operator had seen large error bars and spiky jumps with the stock McStas source, where a flat band is reweighted after the fact. **Constrains:** (as the approved design works the ruling out; these details are the design's, not the operator's words) both modes emit rays of one constant weight, a testable property (the spread of starting weights is exactly zero, check 3 of `tools/verify_source_maxwell_direct.py`); no per-ray weight by energy, direction or position anywhere in the component, and no energy cut-offs; the flat band is documented as unphysical with its limits stated; optimising where rays go is out of scope. **Transcript:** docs/transcripts/2026-10-16-tavi-source-maxwellian-review-b5b7377a.md. **Checked:** clerk 2026-10-16, backed, session b5b7377a (the one-weight constraint is the design's working-out of the ruling, not the operator's words).

### 2026-10-16 — versioning, and what counts as breaking
**Ruled by:** operator. **Question:** how is the component versioned from the first release onward, and does a documented correction that changes results go in seamlessly with a version bump or get a new file name? **Options:** A, the version in the file name (`<Name>_v1.comp`), a new file per change, the old file stays shipped; B, one file name with a version number inside and refusal on mismatch. For what is breaking: the interface (corrections go in place), or results (corrections get a new name). **Decision:** B-ish, without refusal, and breaking means the interface. Versioning: "B-ish." (line 447) "It's only on breaking things that we should have a new version that forces that to change. So we stamp a version number inside and make it clear to users. I don't think we need to be refusing a mismatch, right?" (line 447) "And so it should be seamless for them when we change the component that it just changes for them there." (line 447) Breaking: "I think the first and usually it's a change that's large enough to usually have different parameters or something." (line 485) "Even the source_maxima_3 has, for example, still keeps a size parameter just for backwards compatibility." (line 485) "And so really a break is really you're asking people to put a lot of work in to redo instruments and things like this, so it should have a really good reason to be doing that." (line 485) **Why:** a new file per minor change forces an edit of every instrument file for nothing, and users do not go back to old components; a break costs users real work, and McStas itself keeps obsolete parameters instead of forcing one. **Constrains:** one component file with a version number inside it (the `Version:` line); outputs record that version (the approved design's addition, not the operator's words; the short file hash is an agent default, reversible); no refusal on a mismatch; a new file name only for a breaking change, that is a rename, a removed parameter or a parameter whose meaning changes, and it should have "a really good reason"; corrections go in place with a version bump and a changelog line; retired parameters stay accepted where practical. **Transcript:** docs/transcripts/2026-10-16-tavi-source-maxwellian-review-b5b7377a.md. **Checked:** clerk 2026-10-16, backed, session b5b7377a.
