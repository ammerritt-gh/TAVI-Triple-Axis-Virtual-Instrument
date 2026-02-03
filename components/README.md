# Custom McStas Components

This folder contains modified and custom McStas components used in the TAVI simulation framework. These components extend or fix functionality from the standard McStas library to better suit the needs of triple-axis instrument simulations.

## Component Overview

| Component | Based On | Key Modifications |
|-----------|----------|-------------------|
| `FlatEllipse_finite_mirror_optimized.comp` | Custom NMO component | Mirror table files, MPI fixes, binary search optimization |
| `Optic_Phonon_simple.comp` | `Phonon_simple.comp` | Optic phonon dispersion, SCATTER keyword |
| `Phonon_simple_SCATTER.comp` | `Phonon_simple.comp` | Added SCATTER keyword |
| `Source_div_Maxwellian_v2.comp` | `Source_div.comp` | Proper Maxwellian sampling, multiple distribution options |

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

## Source_div_Maxwellian_v2.comp

### Purpose
A rectangular neutron source with Gaussian or uniform divergence and multiple energy distribution options.

### Differences from Standard `Source_div.comp`

1. **Proper Maxwellian Energy Sampling**: When `energy_distribution=2`, uses mathematically correct Gamma(3/2, kT) sampling:
   ```c
   /* Maxwellian: P(E) ~ sqrt(E) * exp(-E / kT) */
   /* Peak at E0 requires kT = 2*E0 */
   E = kT * (-log(u1) + 0.25 * n1 * n1);
   ```
   This correctly samples from the Maxwell-Boltzmann distribution where the peak occurs at the specified E0.

2. **Three Energy Distribution Options**:
   - `energy_distribution=0`: Uniform between E0-dE and E0+dE
   - `energy_distribution=1`: Gaussian centered at E0 with width dE
   - `energy_distribution=2`: Maxwellian peaking at E0

3. **Two Divergence Distribution Options**:
   - `divergence_distribution=0`: Uniform angular distribution
   - `divergence_distribution=1`: Gaussian angular distribution

4. **Fixed Divergence Banding**: Corrected the uniform divergence sampling to use completely independent random calls for each axis, avoiding correlation artifacts that could cause visible banding patterns in the beam.

5. **Wide Energy Range Support**: Better numerical handling for simulations spanning large energy ranges, particularly important for thermal/cold neutron source modeling.

### Parameters
| Parameter | Units | Description |
|-----------|-------|-------------|
| `xwidth` | m | Width of source |
| `yheight` | m | Height of source |
| `focus_aw` | deg | Horizontal divergence (FWHM for Gaussian) |
| `focus_ah` | deg | Vertical divergence (FWHM for Gaussian) |
| `E0` | meV | Mean/peak energy |
| `dE` | meV | Energy half-spread |
| `energy_distribution` | 0/1/2 | Uniform/Gaussian/Maxwellian |
| `divergence_distribution` | 0/1 | Uniform/Gaussian |
| `flux` | n/(s·cm²·sr·meV) | Source flux |

---

## Other Files

### Instrument Files
- `PUMA_McScript.instr`: McStas instrument definition for the PUMA spectrometer
- `PUMA_McScript.c`: Compiled C code for the PUMA instrument

### Configuration Files
- `PUMA_mirror_array.txt`: Mirror array configuration for PUMA

### Documentation
- `Header_Files_Analysis.md`: Detailed analysis of header file modifications
- `NMO_Component_Documentation.md`: Extended documentation for NMO components

---

## Usage Notes

1. **Component Path**: Ensure this `components/` folder is in your McStas component search path, or use absolute paths in your instrument file.

2. **Header Dependencies**: The NMO component requires both `_fixed.h` header files. The original (unfixed) versions are retained for reference.

3. **MPI Simulations**: When running with MPI, use `FlatEllipse_finite_mirror_optimized.comp` to avoid duplicate output and potential race conditions.

4. **Compatibility**: These components are tested with McStas 3.x. Some modifications may be required for McStas 2.x.
