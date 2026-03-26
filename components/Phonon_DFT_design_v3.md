# Phonon_DFT Component — Design Document v3

## Overview

`Phonon_DFT` is a McStas sample component for combined elastic (Bragg) and inelastic (phonon) neutron scattering from crystalline materials. It reads Bragg reflections from CIF files and phonon dispersions from DFT-calculated regular grids, scattering neutrons with physically correct kinematics and weighting.

The component is designed as an extensible "universal sample" that will grow to support multi-BZ intensity variation, magnetic excitations, and intrinsic phonon linewidths.

**Current version:** 1.0 — Bragg kernel validated, phonon kernel functional with root-finding approach.

**Repository:** `ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument`

---

## Current Architecture

The phonon and Bragg scattering paths are **completely independent**, separated by a simple coin flip at the start of each neutron event. This avoids the weight-dilution problems that arise from unified cross-section frameworks, and allows each channel to compute its own neutron weight from scratch following the conventions of its respective reference component (`Phonon_simple` for phonons, `Single_crystal` for Bragg).

```
Neutron enters sample
         │
         ▼
   rand01() < p_phonon?
     ┌────┴────┐
     │ YES     │ NO
     ▼         ▼
  PHONON     BRAGG + INCOHERENT
  (self-     (Single_crystal-style
  contained,  channel framework with
  Phonon_     transmission decision,
  simple-     Ewald sphere search,
  style       weight factors)
  weight)
```

Each path:
- Saves the incoming neutron weight `p_incoming` before any modifications
- Applies its own physics-based weight factors independently
- Compensates for the `p_phonon` / `(1-p_phonon)` branching probability

---

## Component Parameters (as implemented)

```c
SETTING PARAMETERS (
  /* --- Data files --- */
  string reflections="NULL",    // CIF, LAU, or LAZ file for Bragg peaks
  string dispersion="NULL",     // Phonon dispersion grid file (H K L E I Branch)

  /* --- Sample geometry --- */
  radius=0, yheight=0,          // cylinder (or sphere if yheight=0)
  xwidth=0, zdepth=0,           // box

  /* --- Material --- */
  sigma_abs=0, sigma_inc=0,     // cross sections per unit cell (barns)
  a=0, b=0, c=0,                // lattice parameters (Å)
  alpha=90, beta=90, gamma_l=90,// lattice angles (deg)
  ax=0, ay=0, az=0,             // direct lattice vectors (override a,b,c)
  bx=0, by=0, bz_l=0,
  cx=0, cy=0, cz=0,

  /* --- Bragg --- */
  delta_d_d=1e-4,               // Gaussian d-spacing mosaic width (RMS)
  barns=1,                      // F² units: 1=barns, 0=fm²

  /* --- Phonon --- */
  p_phonon=0.5,                 // MC probability for phonon channel
  int tessellate=1,             // 1=tile BZ over all Q-space, 0=single grid only
  int phonon_e_steps=50,        // root-finding bracket subdivisions per branch

  /* --- Common --- */
  debye_waller=1,               // global Debye-Waller factor
  T=300,                        // temperature (K) for Bose factor
  p_interact=0.8,               // Bragg/incoherent interaction probability

  /* --- Focusing --- */
  target_x=0, target_y=0, target_z=0,
  target_index=0,               // relative component index for focusing target
  focus_r=0, focus_xw=0, focus_yh=0,
  focus_aw=0, focus_ah=0        // angular focusing (deg)
)
```

---

## Bragg Kernel (implemented, validated)

### Pipeline

```
CIF file → cif2hkl → F²(hkl) list → pdft_read_bragg()
  → sort by |τ| → store in pdft_bragg_refl array
```

The `cif2hkl` tool is reused from the McStas `Single_crystal`/`PowderN` infrastructure via a `#ifndef CIF2HKL` guard. Filenames are validated against shell metacharacters before being passed to `system()`.

### Ewald sphere model

Simplified relative to `Single_crystal`: a 1D Gaussian proximity check rather than the full 2D tangent-plane + Cholesky decomposition. For each reflection:

1. Compute `ρ = |k_i − τ|`, deviation from Ewald sphere: `Δ = |ρ − k_i|`
2. Gaussian weight: `w = exp(−Δ²/(2σ²))` where `σ = delta_d_d × |τ|`
3. Cross section: `w / (V₀ × k_i² × σ)`

Reflection selection is weighted by F² × w, with the `Single_crystal`-style `pmul` weight correction ensuring equal statistics across reflections.

### Scattering direction

Deterministic: `k_f = k_i − τ`, renormalized to `|k_f| = |k_i|` (elastic). This means every Bragg-scattered neutron goes in exactly the right direction — no focusing needed for Bragg, and every Bragg event that satisfies the Ewald condition reaches the analyzer.

### Validated behavior

- Correct peak positions for Al fcc (symmetry-allowed reflections only)
- Reasonable peak widths controlled by `delta_d_d`
- Compatible with CIF (via cif2hkl), LAU, and LAZ file formats
- Lattice parameters from file header or user-specified

---

## Phonon Kernel (implemented, functional)

### Input file format

Regular-grid columnar text, one row per (q-point, branch):

```
# Phonon dispersion data
# grid_nx 21
# grid_ny 21
# grid_nz 21
# num_branches 6
# Columns: H(rlu) K(rlu) L(rlu) E(meV) Intensity Branch
0.000000 0.000000 0.000000 0.000000 1.000000 0
0.000000 0.000000 0.000000 6.000000 1.000000 1
0.050000 0.000000 0.000000 1.234000 0.852000 0
...
```

The grid can span any range in r.l.u. (e.g. [0,2], [-0.5,0.5], [-1,1]). Grid dimensions are read from the header or auto-detected from the data by counting unique H, K, L values. Branch index is 0-based.

### Tessellation

When `tessellate=1`, the phonon grid is tiled periodically over all of reciprocal space. Any Q (in r.l.u.) is folded into the grid's range via:

```c
q_folded = fmod(q - grid_min, grid_span);
if (q_folded < 0) q_folded += grid_span;
q_folded += grid_min;
```

When `tessellate=0`, Q outside the grid range returns zero intensity (no phonon scattering at that Q).

### Trilinear interpolation

The phonon energy and intensity at an arbitrary q-point are interpolated from the 8 surrounding grid nodes. Periodic boundary wrapping (`ix1 = 0` when `ix1 >= nx`) handles the BZ-edge seamlessly for tessellated grids.

### Scattering algorithm (Ridders root-finding)

Follows the `Phonon_simple` algorithm:

```
1. Choose random scattered direction (focused toward target)
2. NORM to unit vector v̂_f
3. For each branch b, for both Stokes (+ω) and anti-Stokes (−ω):
   a. Bracket v_f into phonon_e_steps intervals
   b. Ridders root-finding on f(v_f) = sign × E_phonon(Q(v_f)) − E_neutron(v_f)
      Each evaluation: compute Q → convert to r.l.u. via B⁻¹ → fold → interpolate
   c. Store valid roots {v_f, ω, branch}
4. Select one root uniformly at random
5. Compute Jacobian, set final velocity
6. Weight = p_incoming × p1 × p2 × p3 × p4 / p_phonon
```

Weight factors (exactly matching `Phonon_simple`):
- `p1 = exp(−μ_a,i × l_i − μ_a,f × l_o)` — absorption along path
- `p2 = n_roots × solid_angle × l_full × V_rho / (4π)` — focusing / geometry
- `p3 = (v_f/v_i) × DW × κ² × K2V² × VS2E / |ω| × n_Bose` — cross section
- `p4 = 2 × VS2E × v_f / J_factor` — Jacobian of the delta function

The `V_rho = N_atoms / V₀` factor was a critical fix — using `1/V₀` instead of `V_rho` gave weights that were `N_atoms` times too small.

### Pointer passing

The `pdft_phonon_omega()` function (called by the Ridders root-finder) needs access to the phonon grid and lattice data. Since `static` globals proved unreliable across McStas's code generation, the grid and lattice pointers are encoded into the `parms` double array via `memcpy`:

```c
memcpy(&ph_parms[11], &grid_ptr, sizeof(pdft_phonon_grid *));
memcpy(&ph_parms[12], &lat_ptr, sizeof(pdft_lattice *));
```

This is portable (sizeof(double) ≥ sizeof(void*) on all platforms) and avoids any shared mutable state.

### Lattice convention

The `pdft_compute_lattice()` function follows `Single_crystal`'s convention when given scalar lattice parameters (a, b, c, α, β, γ):

```
b-vector along z,  a-vector in yz-plane,  c-vector has x-component
```

This means for a cubic crystal with scalar `a`:
- **a\*** points along y
- **b\*** points along z
- **c\*** points along x

For a TAS with its scattering plane in xz, the instrument's "H" direction maps to **b\*** and **c\*** (K and L in the file), not a\* (H in the file). The H axis in the file maps to the vertical (y) direction, which is out of the scattering plane.

This is correct and consistent with `Single_crystal`, but **the user must be aware** that TAVI's H, K, L labels may not correspond directly to the file's H, K, L indices unless the lattice vectors are specified explicitly via `ax/ay/az` etc. to match the desired orientation.

For explicit crystal orientation control, use the vector parameters:
```python
Al_sample.ax = 4.039;  Al_sample.ay = 0;  Al_sample.az = 0   # a along x
Al_sample.bx = 0;      Al_sample.by = 4.039; Al_sample.bz_l = 0  # b along y
Al_sample.cx = 0;      Al_sample.cy = 0;  Al_sample.cz = 4.039   # c along z
```

### Validated behavior

- Acoustic and optic phonon branches visible in pre-analyzer energy monitors
- Correct energy positions given the lattice convention and Q-trajectory
- 100% root-finding success rate
- Weight per phonon event: ~10⁻⁹ (with TAS source weight ~10⁻⁷ at sample)
- Requires ~10⁹ total neutrons for measurable phonon signal through the analyzer
- Bragg peaks and phonons visible simultaneously in the same simulation

---

## MSVC / Windows Compatibility

The component compiles on Windows with MSVC (`cl.exe`) in C89 mode. Key constraints:

- **All variable declarations at block top.** No mid-block declarations after statements.
- **No `struct` keyword in TRACE declarations.** All structs use `typedef` so TRACE variables are declared as `pdft_tau_data tlist[N]` not `struct pdft_tau_data tlist[N]`.
- **No variable names that collide with McStas internals.** The name `T` is reserved (temperature parameter). Local arrays use prefixed names like `pdft_tlist`.
- **POSIX compatibility shims:** `strcasecmp → _stricmp`, `unlink → _unlink`, `close → _close` via `#ifdef _MSC_VER`.
- **`tmpnam()` instead of `mkstemp()`** for temporary file creation (mkstemp is POSIX-only).
- **`#pragma acc routine`** wrapped in `#ifndef _MSC_VER` guards.

---

## Known Limitations

1. **Single component instance only.** The pointer-passing mechanism (`memcpy` into parms) is safe, but the component has not been tested with multiple `Phonon_DFT` instances in one instrument.

2. **No multiple scattering.** Each neutron scatters at most once. The Bragg path has the framework for a multiple-scattering loop (from `Single_crystal`) but it is not implemented.

3. **Phonon cross-section prefactor.** The `b²/M` factor from `Phonon_simple` is not included. The dispersion file's Intensity column should encode the full scattering cross section. With uniform `I=1.0` test files, phonon intensities are missing this scale factor (~0.44 fm²/amu for Al).

4. **No intrinsic phonon linewidth.** Phonons are delta functions in energy. The observed peak width comes from instrumental Q-resolution only. See "Future: Lorentzian Spectral Function" below.

5. **No UB matrix.** The crystal orientation is fixed by the lattice vector convention. There is no rotation matrix to align crystallographic axes with the instrument frame. Users must specify lattice vectors explicitly to control orientation.

---

## Future: Lorentzian Spectral Function (Phase 2)

### Motivation

The current root-finding approach treats phonons as delta functions: `S(Q,ω) ∝ δ(ω − ω_s(q))`. This has two consequences:

1. **No intrinsic linewidth.** Real phonons have finite lifetime Γ (typically 0.1–2 meV), producing a Lorentzian lineshape. The current component cannot model this.

2. **Low efficiency.** The root-finder only produces signal when the Q-trajectory exactly crosses the dispersion surface. Many neutrons find roots but at energies the analyzer doesn't accept, wasting computational effort.

### Proposed approach

Replace the delta function with a damped harmonic oscillator (DHO) or Lorentzian spectral function:

$$S(\mathbf{Q}, \omega) = \sum_{s} \frac{I_s(\mathbf{q})}{\omega_s(\mathbf{q})} \cdot \frac{4\omega_s \Gamma_s}{(\omega^2 - \omega_s^2)^2 + 4\omega^2\Gamma_s^2} \cdot [n(\omega,T) + 1]$$

For small Γ (Γ ≪ ω_s), this simplifies to a Lorentzian:

$$S(\mathbf{Q}, \omega) \approx \sum_{s} I_s(\mathbf{q}) \cdot \frac{\Gamma_s / \pi}{(\omega - \omega_s(\mathbf{q}))^2 + \Gamma_s^2} \cdot [n(\omega,T) + 1]$$

### Algorithm change

Instead of root-finding:

```
1. Choose random scattered direction (focused toward target)
2. Choose random v_f from a physically motivated distribution
   (e.g. uniform in E_transfer, or importance-sampled near E_phonon)
3. Compute Q = k_i − k_f, convert to r.l.u., fold into BZ
4. For each branch: interpolate E_phonon(q) and I(q)
5. Evaluate S(Q, ω) = Σ_s I_s × Lorentzian(ω, ω_s, Γ_s) × Bose
6. Weight neutron by S(Q, ω) × kinematic factors
```

This approach:
- **Every neutron contributes.** No root-finding failure. Every scattered neutron has nonzero weight (though it may be small far from the dispersion surface).
- **Natural linewidth.** The Lorentzian gives physical broadening controlled by Γ.
- **Simpler code.** No Ridders root-finder needed. The omega function becomes a simple evaluation rather than an iterative solver.
- **Better TAS efficiency.** Importance sampling of v_f near the expected phonon energies concentrates computational effort where the signal is.

### New parameter

```c
phonon_gamma=0.5   // intrinsic phonon linewidth Γ (meV), Lorentzian HWHM
                    // 0 = delta function (current behavior, via root-finding)
                    // >0 = Lorentzian spectral function
```

Per-branch Γ values could be supported via an additional column in the dispersion file (column 7: Gamma).

### Implementation considerations

- **v_f sampling distribution:** Uniform sampling in v_f wastes many neutrons far from the dispersion. Importance sampling from a Gaussian centered on the expected v_f (computed from E_i and E_max) would improve efficiency dramatically.
- **Normalization:** The Lorentzian must be normalized so that in the limit Γ→0, the result matches the current root-finding approach. The integral of the Lorentzian over all ω is 1, so the weight at the peak is `1/(πΓ)`.
- **Multiple branches:** When Γ is comparable to branch separations, the Lorentzians of different branches overlap. The sum over branches handles this naturally.
- **Compatibility:** When `phonon_gamma=0`, fall back to the current root-finding algorithm. This preserves backward compatibility and allows comparison.

---

## Future: Multi-BZ Intensity (Phase 3)

The current implementation folds all Q into a single BZ and uses a single intensity value per (q, branch). In reality, the phonon scattering intensity depends on which BZ the neutron probes because of the Q·e(q,s) polarization factor and the phase factors from atomic positions.

### Upgrade paths

1. **Extended grid (no folding):** User provides a dispersion file covering multiple BZs (e.g. [-3,3]³). Set `tessellate=0`. The grid is larger but the lookup is unchanged.

2. **Eigenvector storage:** Store phonon eigenvectors per (q, branch, atom) and compute the one-phonon structure factor at runtime. This is the physics-correct approach and what tools like Euphonic compute.

3. **Q-dependent intensity column:** The dispersion file encodes I(Q) for specific Q values across multiple BZs. The grid covers the full Q range with BZ-dependent intensities pre-computed.

The current architecture supports all three via the `tessellate` flag and the separation of energy interpolation from intensity interpolation.

---

## Future: Magnetic Excitations (Phase 4)

Magnon scattering uses the same grid infrastructure but with different cross-section prefactors: `(γr₀)²F²(Q)` instead of `b²/M`, and a magnetic polarization factor `(1 + Q̂_z²)` for unpolarized neutrons. A separate `magnon_dispersion` file and `magnon_grid` struct would parallel the phonon system.

---

## Implementation Status

| Feature | Status | Notes |
|---|---|---|
| Bragg from CIF | ✅ Validated | Peaks at correct positions and relative intensities |
| Bragg from LAU/LAZ | ✅ Implemented | Same pipeline via `pdft_read_bragg` |
| Lattice from parameters | ✅ Implemented | Scalar (a,b,c,α,β,γ) or vector (ax,ay,az...) |
| Lattice from file header | ✅ Implemented | Parsed from CIF header |
| Phonon grid loading | ✅ Implemented | Auto-detection of grid dimensions |
| Trilinear interpolation | ✅ Implemented | Periodic BCs for tessellation |
| BZ tessellation | ✅ Implemented | Arbitrary grid ranges, fmod folding |
| Root-finding (Ridders) | ✅ Implemented | 100% success rate in testing |
| Phonon weight factors | ✅ Implemented | Matches Phonon_simple formula |
| Bose factor | ✅ Implemented | Overflow-guarded for large E/T |
| Channel separation | ✅ Implemented | Independent paths, no weight dilution |
| MSVC compatibility | ✅ Validated | C89 compliant, typedef-based structs |
| Cylinder/box/sphere geometry | ✅ Implemented | |
| Incoherent channel | ✅ Implemented | Isotropic elastic, proper 4π sampling |
| Diagnostic output | ✅ Implemented | Weight breakdown, root-finding statistics |
| Lorentzian linewidth | ⬜ Planned | Phase 2 |
| Multi-BZ intensity | ⬜ Planned | Phase 3 |
| Magnon kernel | ⬜ Planned | Phase 4 |
| Multiple scattering | ⬜ Not started | |
| OpenACC / GPU | ⬜ Not started | |
| UB matrix | ⬜ Not started | |

---

## File Structure

```
Phonon_DFT.comp                    ← main component file (~1700 lines)
Al_mp-134_symmetrized.cif          ← test CIF (Al, Fm-3m)
Al_test_phonons.dat                ← test dispersion (isotropic toy model, 2 branches)
Phonon_DFT_design_v3.md            ← this document
```

---

## Typical Usage

```python
sample = instrument.add_component("sample", "Phonon_DFT",
    AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle")

# Bragg scattering
sample.reflections = '"Al_mp-134_symmetrized.cif"'
sample.delta_d_d = 1.45e-3

# Phonon scattering  
sample.dispersion = '"Al_phonons_dft.dat"'
sample.tessellate = 1
sample.p_phonon = 0.5

# Sample geometry
sample.radius = 5e-3
sample.yheight = 30e-3

# Material
sample.a = 4.03893
sample.sigma_abs = 0.231
sample.sigma_inc = 0
sample.T = 300

# Focusing (required for phonon statistics on TAS)
sample.target_index = 2       # point at analyzer
sample.focus_aw = 5.0         # horizontal (deg)
sample.focus_ah = 15.0        # vertical (deg)
```
