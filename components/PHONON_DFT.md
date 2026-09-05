# TAVI `Phonon_DFT` Component and File Contract

> **Owner:** TAVI project
>
> **Lifecycle:** Maintained
>
> **Authority:** Canonical reference for TAVI's `Phonon_DFT` component and shared data-file contract
>
> **Last verified:** 2026-07-27

TAVI owns `Phonon_DFT.comp`, the supported dispersion-file contract, the
bundled maps and reflection tables, and this documentation. The component runs
inside McStas and uses McStas libraries, but it is not an upstream McStas
component. Changes and support remain TAVI's responsibility.

The component models a single-crystal sample with two scattering channels:

1. coherent elastic Bragg scattering from a reflection table; and
2. coherent one-phonon Stokes and anti-Stokes scattering from a regular
   H-K-L dispersion grid.

TAVI's deterministic analytic engine consumes the same dispersion and
reflection assets. Its architecture, calibration, convolution, and limitations
are documented in
[`docs/ANALYTIC_ENGINE.md`](../docs/ANALYTIC_ENGINE.md).

## Supported dispersion format

A shared TAVI `Phonon_DFT` map is a UTF-8 text file with numeric data rows and
four supported dimension headers:

```text
# grid_nx <positive integer>
# grid_ny <positive integer>
# grid_nz <positive integer>
# num_branches <positive integer>

H K L E intensity branch
```

An optional linewidth column may appear on every data row:

```text
H K L E intensity branch Gamma
```

The headers are optional for compatibility with existing assets; both readers
can infer the dimensions from a complete regular grid. New TAVI-owned maps
should include all four so accidental truncation or a wrong branch count is
detected against declared dimensions.

The columns are:

| Column | Meaning | Unit or convention |
|---|---|---|
| `H K L` | Reciprocal-lattice coordinates | rlu |
| `E` | Branch energy | meV |
| `intensity` | Grid weight for the mode | arbitrary |
| `branch` | Branch identifier | zero-based integer |
| `Gamma` | Optional phonon FWHM | meV, non-negative |

The linewidth column is all-or-nothing: either every row has it or no row has
it. A positive interpolated `Gamma` overrides the component's global
`phonon_gamma`; zero selects the global value.

### Strict shared-contract validation

For a file to be valid in both McStas and analytic mode, TAVI requires:

- exactly six or seven numeric fields per data row;
- finite numeric values;
- positive grid dimensions and branch count;
- one regular coordinate axis for each of H, K, and L;
- exactly the declared Cartesian product of HKL cells and branches;
- no duplicate `(H,K,L,branch)` cells;
- branch identifiers contiguous from zero through
  `num_branches - 1`;
- non-negative linewidths; and
- consistent presence or absence of the linewidth column.

The analytic loader is intentionally stricter than the C component's historical
reader. A file that the component happens to tolerate is not a supported shared
asset unless it satisfies this contract. Malformed or incomplete files fail
visibly in analytic mode instead of falling back to hard-coded dispersion
equations.

Non-positive interpolated intensity is allowed in the file but contributes no
phonon scattering. Conventionally branch energies are non-negative; zero energy
is handled by the Gamma-point policy below.

The C component historically expects rows ordered with branch varying fastest,
then L, K, and H. The analytic loader is row-order independent after
validation.

## Interpolation and boundaries

Energy, intensity, and optional linewidth are interpolated trilinearly for
every branch.

With `tessellate=1`, each reciprocal coordinate is folded periodically into
the map range. A cell crossing the upper boundary wraps to the first grid
index, so interpolation remains continuous for maps whose boundary values are
periodic.

With `tessellate=0`, a point outside any map axis is unavailable. Analytic mode
returns no phonon modes rather than extrapolating. The McStas component skips a
phonon event that cannot be evaluated.

The number of branches is data-driven. Adding a third or later branch requires
no analytic-engine change and no component-source change within the compiled
limits.

The component declares these implementation limits:

- `PDFT_MAX_BRANCHES = 64`;
- `PDFT_MAX_PHONON_ROOTS = 128`; and
- `PDFT_MAX_TAU = 256`.

Keep shared maps at or below 64 branches unless those limits and their tests are
deliberately revised.

## Phonon scattering behavior

At the local phonon wavevector, the component evaluates all branches. For a
mode of positive energy `E` and grid intensity `I`, thermal population produces:

- Stokes scattering at `+E`, weighted by `I(n + 1)`; and
- anti-Stokes scattering at `-E`, weighted by `In`;

where `n` is the Bose occupation at sample temperature `T`.

Modes with `abs(E) < 1e-10 meV` do not contribute one-phonon intensity. This
Gamma-point rule is shared with analytic mode. An acoustic zero therefore does
not create an artificial elastic phonon line; an allowed reflection in the
Bragg channel supplies the elastic peak.

`phonon_gamma` controls the global phonon FWHM:

- if it is positive, the component uses a Lorentzian spectral function and
  importance sampling;
- if it is zero, the component treats the dispersion as a delta mode and uses
  `phonon_e_steps` to bracket energy-conservation roots.

A positive per-point `Gamma` in the file replaces the global value for that
interpolated mode.

## Bragg scattering behavior

`reflections` names a CIF, LAU, or LAZ reflection file. CIF input is converted
through the McStas `cif2hkl` path; LAU/LAZ files are read directly.

Only finite reflections with positive raw F-squared contribute. Forbidden or
missing reflections are not synthesized. If an explicitly configured
reflection file cannot be loaded, the component aborts; analytic
`Phonon_DFT` mode follows the same fatal policy.

The component uses a simplified Ewald-sphere intersection and applies
`delta_d_d` to the elastic acceptance. It is not a replacement for every
feature in the upstream McStas `Single_crystal` component.

## Parameters

The principal setting parameters in `Phonon_DFT.comp` are:

| Group | Parameters |
|---|---|
| Assets | `reflections`, `dispersion` |
| Cylinder | `radius`, `yheight` |
| Box | `xwidth`, `yheight`, `zdepth` |
| Cross-sections | `sigma_abs`, `sigma_inc`, `barns` |
| Lattice lengths/angles | `a`, `b`, `c`, `alpha`, `beta`, `gamma_l` |
| Direct lattice vectors | `ax` through `cz` |
| Elastic physics | `delta_d_d`, `debye_waller` |
| Phonon physics | `T`, `phonon_gamma`, `tessellate`, `phonon_e_steps` |
| Event selection | `p_interact`, `p_phonon` |
| Focusing | `target_*`, `focus_*` |

Specify a cylinder through positive `radius` and `yheight`, a sphere through
positive `radius` with `yheight = 0`, or a box through positive `xwidth`,
`yheight`, and `zdepth`.

The lattice may be supplied by lengths and angles or by direct lattice
vectors. Internally generated reciprocal vectors include the conventional
`2*pi` factor.

`p_interact` controls scattering versus transmission. For interacting events,
`p_phonon` controls selection of the phonon channel relative to the elastic and
incoherent channels. These Monte Carlo importance controls have no direct
analytic-mode counterpart; analytic mode evaluates and calibrates its channels
separately.

## Built-in aluminium configuration

`tavi/sample_library.py` configures `Al_phonon_DFT` with:

- reflection file `Al_mp-134_symmetrized.laz`;
- dispersion file `Al_test_phonons_centered.dat`;
- cubic lattice parameter `a = 4.03893 A`;
- temperature `T = 200 K`;
- global `phonon_gamma = 0.2 meV`;
- `tessellate = 1`;
- `p_interact = 1`; and
- `p_phonon = 0.95`.

The sample also owns independent analytic phonon and elastic calibrations.
Those factors affect deterministic counts only; they are not component input
parameters.

The aluminium map is a toy: `sin^2(pi*H/2)` is periodic in each of H, K, and L
separately, so its zone centres sit only at all-even `(H,K,L)` and `(1,1,1)` is
a dispersion maximum. A real fcc crystal is also gapless at `(1,1,1)`. Any
consumer that infers zone centres from the map's period inherits this
difference between the two built-in samples.

## Built-in lead configuration

`tavi/sample_library.py` configures `Pb_phonon_DFT` with:

- reflection file `Pb_Fm-3m.laz` (committed; generated from tabulated
  constants, `b_coh = 9.405 fm`, `F2 = 14.1526 barn` on every allowed
  reflection);
- dispersion file `Pb_dft_phonons.dat` (**gitignored** with its source
  `pb_pdisp_3d_nq50` until the collaborator permits publication; a checkout
  without it lists the sample but fails at asset load);
- cubic lattice parameter `a = 4.9508 A` (room-temperature Pb; the DFT
  lattice constant has not been supplied);
- temperature `T = 300 K`; otherwise the aluminium parameters.

`tools/make_pb_assets.py` builds both files. The DFT source is a `50^3` grid in
primitive-reciprocal internal coordinates (`q = x*b1 + y*b2 + z*b3` with
`b1 = (-1,1,1)`, `b2 = (1,-1,1)`, `b3 = (1,1,-1)`) with three sorted branch
energies per point and no eigenvectors. The tool places conventional `(H,K,L)`
nodes on `[-1,1]` at step 0.02 (`101^3` points, 3.1 million rows, ~150 MB).
Nodes whose H, K and L share parity in units of the step are exact DFT nodes
(`x = (K+L)/2`, `y = (H+L)/2`, `z = (H+K)/2`), so every DFT node is used; the
other three in four sit at primitive cell centres and are trilinearly
interpolated on the periodic primitive grid. Every intensity is `1.0` because the
source carries no structure factors, the twelve numerically negative frequencies
near Gamma (worst `-0.065 meV`) are clamped to zero, and the analytic
calibration is copied from aluminium uncalibrated. The tool's self-check asserts
`E = 0` at `(0,0,0)` and `(1,1,1)`, the X- and L-point values, the period-2
wrap, and cubic symmetry.

The analytic loader (`tavi/dispersion_map.py`) parses with `numpy.loadtxt` and
vectorised validation so a map of this size loads in seconds; the row walk
survives only to name the offending line of a refused file.

## Dispersion viewer

`run-dispersion-viewer.bat` opens `gui/dispersion_viewer.py`, a windowless
PySide6 tool that plots any `components/*.dat` map (with an optional second map
overlaid dashed) along a reciprocal-space path — presets for the fcc special
points `Γ X W K L U` or free text such as `Γ K (1,1,0)` — exactly as the
analytic engine evaluates it. Figures are saved to `figures/` by default
(gitignored, deliberately not `output/`); the last folder and controls are
remembered. The Qt-free path logic lives in `tavi/dispersion_path.py` so the
main TAVI window can host the same widget later.

## Adding or replacing a branch

To add a branch:

1. assign the next contiguous zero-based branch identifier;
2. add one row for that branch at every HKL grid cell;
3. update `# num_branches`;
4. keep the Gamma column present on all rows or none; and
5. run the map and deterministic-engine tests.

No analytic-engine rebuild or code change is required. McStas may recompile the
instrument through its normal build workflow, but `Phonon_DFT.comp` itself does
not need to change unless a compiled limit or the file contract changes.

A different scattering representation—a non-regular grid, continuum, diffuse
map, or magnetic cross-section—is a new model contract, not merely another
branch.

## McStas and analytic parity

The two backends deliberately share:

- the dispersion and reflection files;
- branch enumeration;
- trilinear interpolation;
- periodic tessellation;
- optional per-point linewidths;
- the zero-energy one-phonon skip; and
- positive raw F-squared reflection selection.

They deliberately differ after the shared sample model:

| McStas `Phonon_DFT.comp` | TAVI analytic engine |
|---|---|
| Samples neutron histories | Computes deterministic mean intensity |
| Applies sample geometry and event importance | Applies TAS resolution convolution |
| Includes transmission, absorption, and incoherent paths | Models calibrated phonon and elastic channels |
| Uses root finding or Lorentzian event sampling | Evaluates Stokes/anti-Stokes lines directly |
| Uses simplified Ewald and `delta_d_d` acceptance | Uses resolution-limited elastic deltas |

Agreement is expected at documented calibration anchors and qualitative map
features, not event-for-event identity.

## Maintenance responsibility

Changes to `Phonon_DFT.comp`, its data-file contract, or bundled maps must:

1. update this document;
2. update [`docs/ANALYTIC_ENGINE.md`](../docs/ANALYTIC_ENGINE.md) when analytic
   parity or limitations change;
3. update configured sample provenance and calibration when applicable; and
4. add tests covering parsing, branch behavior, Gamma handling, Bragg
   selection, and the zero-energy policy.

TAVI maintainers own this compatibility surface. Upstream McStas documentation
can explain the host runtime and library APIs, but it is not the authority for
this custom component or TAVI's supported map format.
