# Phonon_DFT Component — Design Document v3

## Overview

`Phonon_DFT` is a McStas sample component for combined elastic (Bragg) and inelastic (phonon) neutron scattering from crystalline materials. It reads Bragg reflections from CIF files and phonon dispersions from DFT-calculated regular grids, scattering neutrons with physically correct kinematics and weighting.

The component is designed as an extensible "universal sample" that will grow to support multi-BZ intensity variation, magnetic excitations, and intrinsic phonon linewidths.

**Current version:** 2.0 — Bragg kernel validated, phonon kernel functional with root-finding and Lorentzian spectral function modes.

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

The `pdft_compute_lattice()` function uses a TAS-friendly convention when given scalar lattice parameters (a, b, c, α, β, γ):

```
a-vector along x,  b-vector in xz-plane,  c-vector has y-component
```

This puts **a\*** and **b\*** in the horizontal scattering plane (xz) and **c\*** along the vertical (y). For a cubic crystal with scalar `a`:
- **a\*** points along x
- **b\*** points along z
- **c\*** points along y

The (H,K,0) reciprocal plane is therefore the scattering plane, which is the standard TAS convention. A scan at Q = (2,0,0) in the file's coordinates maps directly to a Q vector in the scattering plane, and the phonon kernel sees the correct q-point.

**Note:** this convention differs from `Single_crystal`, which uses `b along z, a in yz-plane`. The `Single_crystal` convention is fine for Bragg scattering (which matches |τ| regardless of direction) but places a\* out of the scattering plane, causing phonon scans to probe the wrong q-point. The `Phonon_DFT` convention is chosen specifically to make phonon scattering work correctly for horizontal-plane TAS.

For explicit crystal orientation control (overrides the default convention), use the vector parameters:
```python
Al_sample.ax = 4.039;  Al_sample.ay = 0;     Al_sample.az = 0
Al_sample.bx = 0;      Al_sample.by = 0;     Al_sample.bz_l = 4.039
Al_sample.cx = 0;      Al_sample.cy = 4.039; Al_sample.cz = 0
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

4. **Intrinsic phonon linewidth approximation.** The Lorentzian mode uses a simple Lorentzian lineshape (not the full damped harmonic oscillator). This is valid when Γ ≪ ω_s. For strongly damped modes (Γ ∼ ω_s), the DHO form should be used instead (future enhancement).

5. **No UB matrix.** The crystal orientation is determined by the lattice vector convention (a\* and b\* in-plane, c\* vertical). For the common (H,K,0) scattering plane this works out of the box with scalar parameters. For arbitrary crystal orientations or non-standard scattering planes, users must specify lattice vectors explicitly via `ax/ay/az` etc. A full UB matrix parameter is planned for future versions.

---

## Lorentzian Spectral Function (Phase 2) — Implemented

### Motivation

The root-finding approach treats phonons as delta functions: `S(Q,ω) ∝ δ(ω − ω_s(q))`. This has two consequences:

1. **No intrinsic linewidth.** Real phonons have finite lifetime Γ (typically 0.1–2 meV), producing a Lorentzian lineshape. The delta-function mode cannot model this.

2. **Low efficiency.** The root-finder only produces signal when the Q-trajectory exactly crosses the dispersion surface. Many neutrons find roots but at energies the analyzer doesn't accept, wasting computational effort.

### Spectral function

The Lorentzian mode replaces the delta function with a Lorentzian spectral function:

$$S(\mathbf{Q}, \omega) \approx \sum_{s} I_s(\mathbf{q}) \cdot \frac{\Gamma_s / \pi}{(\omega - \omega_s(\mathbf{q}))^2 + \Gamma_s^2} \cdot [n(\omega,T) + 1]$$

where Γ_s is the HWHM (half-width at half-maximum) of the phonon line. Both Stokes (+ω_s) and anti-Stokes (−ω_s) terms are summed over all branches.

### Parameter

```c
phonon_gamma=0.5   // intrinsic phonon linewidth Γ (meV), Lorentzian FWHM
                    // 0 = delta function (root-finding, backward compatible)
                    // >0 = Lorentzian spectral function with importance-sampled v_f
```

Per-branch Γ values are supported via column 7 of the dispersion file (FWHM in meV). When present, the per-point value overrides the global `phonon_gamma` for that branch/q-point.

### Algorithm: importance-sampled v_f

The key challenge is efficient sampling of the final neutron speed v_f. Uniform v_f sampling wastes most neutrons far from the dispersion surface where S(Q,ω) ≈ 0. The implemented solution uses importance sampling from a Lorentzian mixture:

```
1. Choose random scattered direction (focused toward target)
2. Compute B^-1 (reciprocal-to-r.l.u. matrix)

--- Importance sampling of v_f ---
3. Estimate Q at elastic limit (v_f = v_i) for the chosen direction
4. For each branch s, interpolate E_s(q) at the estimated Q
5. For each (branch, sign=±1), compute target:
     v_f_target = sqrt(v_i^2 ∓ E_s / VS2E)
   and transform Γ to v_f space:
     σ_vf = Γ_HWHM / (2 · VS2E · v_f_target)
   with a floor of 10 m/s to prevent infinitely narrow sampling peaks.
6. Sample v_f from mixture PDF:
     pdf(v_f) = 0.1/vf_range + 0.9 · (1/N) · Σ_j Lor(v_f; target_j, σ_j)
   10% uniform background ensures coverage far from branches.
   Cauchy sampling: pick component j, then v_f = target_j + σ_j · tan(π(u-0.5))
   Reject if outside [vf_min, vf_max], resample uniformly.
7. Evaluate mixture PDF at sampled v_f (for importance weight)

--- Spectral function evaluation ---
8. Compute Q = k_i − k_f at the sampled v_f, convert to r.l.u., fold
9. For each branch: interpolate E_s, I_s, Γ_s; sum Lorentzian × Bose
10. Weight = p_incoming × p1 × p2 × p3 / p_phonon
    where:
      p1 = exp(−μ_a,i·l_i − μ_a,f·l_o)          (absorption)
      p2 = solid_angle · l_full · V_rho / (4π)    (geometry)
      p3 = (v_f/v_i) · DW · κ² · K2V² · S_total / pdf(v_f)
```

### Why this works

The weight per neutron is proportional to `S_total / pdf(v_f)`. When v_f lands near a phonon branch:
- `S_total` is large (Lorentzian peak)
- `pdf(v_f)` is also large (importance distribution peaks there too)
- Their ratio is well-behaved → low weight variance

With uniform sampling, `pdf = 1/vf_range` is constant, so the weight variance is dominated by the enormous dynamic range of `S_total` (orders of magnitude between on-peak and off-peak). The importance sampling concentrates samples where the signal is, dramatically reducing the number of neutrons needed for convergence.

### Fallbacks and edge cases

- **No valid targets** (all branches give E_s > E_i for Stokes, or lattice issues): falls back to pure uniform sampling (imp_uniform_weight = 1.0).
- **Cauchy tail extends outside [vf_min, vf_max]**: rejected sample is replaced by a uniform draw.
- **σ_vf floor of 10 m/s**: prevents the sampling Lorentzian from becoming a near-delta function when Γ is tiny, which would cause numerical issues in the Cauchy CDF inversion.
- **phonon_gamma = 0**: entire Lorentzian block is skipped; root-finding mode runs as before.

### Normalization consistency

In the limit Γ → 0, the Lorentzian `(Γ/π) / ((ω−ω_s)² + Γ²)` → δ(ω−ω_s). The weight formula reduces to the root-finding formula because:
- `S_total` → `I_s × δ(ω−ω_s) × Bose`
- `1/pdf(v_f)` → the v_f-space Jacobian `dv_f/dω = 1/(2·VS2E·v_f)`
- The product reproduces `VS2E/|ω| × Bose × I × 2·VS2E·v_f / J` from the root-finding p3×p4.

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
| Lorentzian linewidth | ✅ Implemented | Importance-sampled v_f, per-point or global Γ |
| Multi-BZ intensity | ⬜ Planned | Phase 3 |
| Magnon kernel | ⬜ Planned | Phase 4 |
| Multiple scattering | ⬜ Not started | |
| OpenACC / GPU | ⬜ Not started | |
| UB matrix | ⬜ Not started | |

---

## File Structure

```
Phonon_DFT.comp                    ← main component file (~2060 lines)
Al_mp-134_symmetrized.cif          ← test CIF (Al, Fm-3m)
Al_test_phonons.dat                ← test dispersion (isotropic toy model, 2 branches)
Phonon_DFT_design_v4.md            ← this document
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
