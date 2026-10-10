# Triple-Axis Spectrometer (TAS) - PUMA Instrument Layout

> **Status:** live
> **Authority:** TAS angle names, sample-orientation offsets and sign conventions

## Overview

A triple-axis spectrometer (TAS) is a neutron scattering instrument used to measure the energy and momentum transfer of neutrons scattered from a sample. The instrument consists of three main rotation axes that control the path of neutrons from source to detector.

The PUMA instrument at FRM-II follows the standard TAS configuration:
- **Monochromator**: Selects incident neutron energy (Ei)
- **Sample**: Where scattering occurs
- **Analyzer**: Selects final neutron energy (Ef)
- **Detector**: Counts scattered neutrons

## Instrument Geometry

```
Source → Monochromator → Sample → Analyzer → Detector
         (A1 θ, A2 2θ)   (A3 rotation, A4 2θ)   (A5 θ, A6 2θ)
```

### Main Rotation Angles

TAVI numbers the angles the ILL way: A1–A6, in beam order, with each crystal's
θ and 2θ as a pair. The table is the contract; `tavi/quantities.py` is the
code that holds it, and every public surface (GUI labels, scan commands, the
API, saved settings, output files) takes its names from there. The Python
names inside the code (`mtt`, `stt`, `att`, the state's `A1`–`A4`) are
internal and keep TAVI's older numbering until the internals are renamed; the
McStas parameters carry physical names (`mono_two_theta_param` ...); see
`docs/MCSTAS_PARAMETERS.md`.

| ILL | Canonical ID | NICOS | Physical meaning | Sign and zero, as the code behaves |
|-----|--------------|-------|------------------|------------------------------------|
| **A1** | `mono_theta_deg` | `mth` | Monochromator Bragg angle θ | Derived, read-only: A2 / 2, signed as A2. Never an input |
| **A2** | `mono_two_theta_deg` | `mtt` | Monochromator scattering angle 2θ (take-off) | 0 = beam straight through; sign = the instrument's mono sense × the Bragg angle (table below) |
| **A3** | `sample_rotation_deg` | `sth` | Sample turntable rotation about the vertical axis; not a Bragg angle | 0 = mount frame parallel to the lab frame; positive turns the mount +x axis toward lab −z (`sample_omega_matrix`). Aliases `omega`, `psi` |
| **A4** | `sample_two_theta_deg` | `stt` | Scattering angle at the sample | 0 = forward scattering; positive turns the scattered beam toward lab +x, negative toward −x, so an instrument whose sample sense is −1 (PUMA) reads negative for the scattering it makes (table below). Alias `2theta` |
| **A5** | `analyzer_theta_deg` | `ath` | Analyzer Bragg angle θ | Derived, read-only: A6 / 2, signed as A6. Never an input |
| **A6** | `analyzer_two_theta_deg` | `att` | Analyzer scattering angle 2θ (take-off) | 0 = beam straight through; sign = the instrument's analyzer sense × the Bragg angle |
| – | `sample_lower_arc_deg` | `sgl` | Lower sample tilt arc, riding on the turntable | 0 = level; right-handed about the mount +x axis (perpendicular to the beam at A3 = 0) |
| – | `sample_upper_arc_deg` | `sgu` | Upper sample tilt arc, riding on the lower arc | 0 = level; right-handed about the mount +z axis (along the beam at A3 = 0) |

The sign of a 2θ readout is the instrument's *scattering sense* (vTAS `sm`,
`ss`, `sa`; the descriptor's `Geometry.sense_*`), which TAVI takes from each
instrument's plugin:

| Instrument | A2 mono | A4 sample | A6 analyzer |
|------------|---------|-----------|-------------|
| PUMA | + | − | + |
| IN8 | + | + | − |
| IN12 | − | + | − |
| PANDA | − | + | − |

A1 and A5 are not independent axes: the model has no separate crystal rocking
angle, so a scan or an API write naming A1 or A5 is refused with a message
pointing at A2 or A6. The Instrument dock shows them as read-only values beside
their 2θ fields. The arcs have no ILL number; they are not a four-circle χ.
Names that are not in this table (χ, φ, κ) are refused.

These angles are calculated automatically based on the desired momentum transfer **Q** and energy transfer **ΔE**.

### Conventions

What the code does today, and the function that does it. Nothing here is a
choice made for this document: where it states a convention, a test or a
function pins it.

- **Laboratory frame.** Origin at the sample, z along the incident beam
  (ki), y vertical (up), x horizontal. For a sample scattering angle the
  scattering vector is `Q_lab = ki − kf = (−kf·sin A4, 0, ki − kf·cos A4)`
  (`tavi.tas_geometry.lab_q_from_stt`), so a positive A4 turns the scattered
  beam toward +x. This is the frame McStas uses for the sample arm
  (`tavi.orientation` module docstring).
- **Two frames for Q.** The *public Q frame* is what the Q fields, scan
  commands and API use: `q_instrument_x/y/z_inv_angstrom`, with x and y in the
  horizontal scattering plane and z vertical. The *mounted-component frame* is
  the McStas sample frame that `U·B·hkl` lives in: x and z horizontal, y
  vertical. They differ by swapping the last two components, public (x, y, z) =
  mount (x, z, y): `tavi.tas_geometry.component_q_to_instrument_q`
  and `instrument_q_to_component_q`. At A3 = 0 the mount and lab axes coincide,
  so the public y axis runs along the beam and z is vertical.
- **Default crystal mount.** `tavi.sample_mount.reciprocal_basis_tas` builds B
  from the direct cell with direct **a** along mount x, direct **b** in the
  horizontal xz plane, and **c** carrying the remaining component along +y.
  Consequently c\* is exactly vertical (+y) for any cell, and in an orthogonal
  cell a\*, b\*, c\* lie along mount x, z, y (public x, y, z); in general
  a\* and b\* are neither along those axes nor horizontal. (Older comments that said "a\* along x"
  described the direct axis, not the reciprocal one; they were corrected with
  this document.) The standard setting has U = identity
  (`SampleMount.R_mount`), so in a cubic crystal (1 0 0) lies along public x,
  (0 1 0) along public y and (0 0 1) vertical. An optional mounting plane
  replaces U by `tavi.ub_matrix.u_from_plane`.
- **Rotation order and matrix action.** Matrices act on column vectors.
  `v_lab = R_stage · v_mount`, with `R_stage = R_A3 · R_sgl · R_sgu` (the
  turntable outermost; `tavi.orientation.stage_rotation`). Each factor is a
  right-handed rotation (`axis_rotation`) about its axis at stage zero: A3
  about +y, sgl about +x, sgu about +z (`instruments.descriptor.tas_goniometer`).
  The columns of B are a\*, b\*, c\*, so `Q_mount = U · B · (h, k, l)ᵀ`
  (`SampleMount.hkl_to_q`, `tavi.ub_matrix`). The sample sense picks the
  branch: sense +1 puts `−U·B·hkl` on `Q_lab`, sense −1 puts `+U·B·hkl`
  there (`q_mount_from_stage`; vTAS's Friedel convention).
- **The 2π convention.** B carries the 2π: a\* = 2π (b × c) / V, so reciprocal
  vectors and `Q` are in Å⁻¹ with |Q| = 2π/d, and wavevectors are
  |k| = 2π/λ with E = ħ²k²/2m (`tavi.neutron_conversions.energy2k`,
  `k2energy`). Bragg angles follow sin θ = π / (k·d) (`k2angle`).
  `tavi/reciprocal_space.py` holds a second, textbook layout (a\* along x, b\*
  in the xy plane) for the copies other programs vendor; TAVI's own HKL ↔ Q
  does not call it.
- **Radius semantics.** A *requested* radius (`mono_horizontal_radius_m`,
  `mono_vertical_radius_m`, `analyzer_horizontal_radius_m`,
  `analyzer_vertical_radius_m`: what a dock field, a scan command or an API
  write sets) is a magnitude in metres, and 0 means flat, always legal. The
  *applied* radius (`applied_mono_horizontal_radius_m` and its three siblings,
  `result.applied_curvature` in the API) is that magnitude signed by the
  crystal's actual local take-off branch: the sign of sin A1 for the
  monochromator radii and of sin A5 for the analyzer radii, never taken from
  the instrument's scattering sense, and unsigned at an exactly zero take-off
  (`set_crystal_bending`, `instruments/tas_runtime.py`). An applied radius is
  an output; sending one back as an input is refused.

## Sample Orientation

### The sample stage (goniometer)

Each instrument declares its sample stage as data (`goniometer` in its
descriptor, `instruments/descriptor.py`), outermost axis first. Every TAS has
the same three axes:

| Axis | Rotation axis (stage at zero) | Description |
|------|-------------------------------|-------------|
| **A3** | vertical (Y) | Turntable, `sample_rotation_deg` (NICOS `sth`; `omega` and `psi` are accepted aliases in scan commands and the API) |
| **sgl** | horizontal (X) | Lower tilt arc, riding on the turntable; perpendicular to the beam at A3 = 0 |
| **sgu** | horizontal (Z) | Upper tilt arc, riding on the lower arc; along the beam at A3 = 0 |

A mount-frame vector goes to the lab as `v_lab = R_A3 · R_sgl · R_sgu · v_mount`
(right-handed rotations). Arc travel comes from a cited source (IN12 ±20°,
PANDA ±15°, PUMA ±20°) or is "undocumented" and unlimited (IN8); each instrument's
`MODEL_STATUS.md` says which.

For a Q or HKL target, `tavi/orientation.py` `solve_stage` levels Q with the
smallest total arc tilt inside travel and turns it onto the scattering vector
with A3; a Q the arcs cannot level is refused, naming the arc, the angle it
would need and its travel. An in-plane Q needs no tilt and gets today's A3.
The sign convention is vTAS's: sense +1 puts `−U·B·hkl` on Q_lab, sense −1
`+U·B·hkl`. The instrument dock shows the readouts A3, `sgl`
and `sgu`; editing any of them reads Q back through the full stage.

### Readouts

The solved angles are **readouts**, and the crystal sits exactly at them:
nothing sits between the dial and the sample. (TAVI once offered two
corrections, ψ of the turntable and κ of the lower arc, and hid training
zero errors under them; both are retired, see *Alignment training*.) The
operator's UB lives in the readout frame, and only the McStas sample arm and
the analytic engine read where the crystal really is, which is the truth below.

A peak recorded with Take Position carries its stage record: every readout,
ki, kf and the sense (`tavi/orientation.py` `stage_record`). The UB fit reads
each peak at its recorded readouts (`record_angles`). A record holds the
readouts and nothing retired; a settings file from before the version-5 break
is refused whole (see *Saved parameters*). A peak without a record (a save from before the
goniometer, a TAS_MCP peak) is a **legacy** peak: its (ω, χ, 2θ) triple keeps
the old meaning, and the UB dock marks it. A stage peak saves that triple too,
computed from its record (`legacy_triple`: the legacy setting of the same Q),
so a reader that ignores the record fits the same U.

### Truth and belief

Two orientations exist side by side. The **belief** is the operator's: the
lattice fields and the UB. Every HKL ↔ Q conversion, the stage solver,
feasibility, the displays and the API read it (it reaches the runtime as the
instrument state's `sample_mount`). The **truth** is the crystal on the stage:
`U_true = R_hidden · U_described`, where `U_described` is the sample as
described (identity, TAVI's standard setting, or the optional mounting plane:
`tavi/ub_matrix.py` `u_from_plane` built on the selected sample's own lattice,
never the lattice fields) and `R_hidden` the rotation of a
loaded training exercise (identity otherwise). Only the McStas sample arm, the
analytic engine's per-point HKL (`docs/ANALYTIC_ENGINE.md` *Where the crystal
is*) and training grading (`tavi/ub_matrix.py` `grade_alignment`) read the
truth. The controller writes `U_true` through one setter
(`TAVIController._set_true_mount`); Calculate UB, a manual UB edit, Reset, a
lattice edit, Refine Lattice, every API write and a sample selection never
touch it, so a fitted UB moves the readouts commanded for an HKL, never the
simulated crystal. The operator's UB starts equal to `U_described` and is reset
to it by Reset, by loading or clearing an exercise, and by Defaults. Loading or
clearing the exercise, like applying or clearing a mounting plane, is refused
while a scattering plane is locked; Defaults releases the lock and clears the
exercise.

### Saved parameters

`parameters.json` holds one block per instrument, each carrying its
`_schema` version (5 now; the history is the comment on
`PARAMETERS_SCHEMA_VERSION`). Every physical quantity in a block is saved under
its canonical ID (`mono_two_theta_deg`, `sample_rotation_deg`, `h`,
`energy_transfer_mev` ...) and read back from that key only; each slit gap of
the active instrument is its own key, `slit.<stable_id>.horizontal_gap_mm` or
`.vertical_gap_mm`, in millimetres (the API's key for it). Version 5 is the
break that renumbered A2, A4 and A6, so a version-4 block would read its angles
under the wrong meaning and is refused rather than converted. A block keeps `U_described` and the plane under
`true_mount`, and `R_hidden` only inside the training hash; restore replaces
the hidden truth in full (no hash: `R_hidden` = I) without touching the saved
UB. The version is enforced, with no converter. Restore judges the whole file
first (`TAVIController._saved_parameters_refusal`): every top-level entry must
be a block of this version (a flat legacy file, or a block of another version
beside a current one, refuses the file), then this instrument's block: every
saved peak's stage record, and the saved exercise, which must be a mount-only
code this instrument can still observe, judged on the sample, crystals, fixed
energy and described mount **in the file**, never the live ones. On any
refusal nothing is applied and the file is renamed `parameters.json.bak`
(`.bak2`, `.bak3`, ... when one exists; a backup is never overwritten). At
start-up the defaults load; File > Load Parameters mid-session leaves the
session exactly as it was, and a valid file with no block for this instrument
is left in place, changing nothing. One message-centre line says why and names
the backup. The file is renamed whole, so the other instruments' blocks go with it
to the backup.

The UB dock's scattering-plane panel is belief too (`get_scattering_plane_info`
on the operator's U and lattice fields). Its plane normal is the zone axis
`zone_axis_uvw`: the vertical as an integer direct-lattice direction [u v w]
against the direct basis 2π (UB)⁻ᵀ, found by `small_integer_indices` (indices up
to 6, within 0.1° measured between Cartesian vectors), else the raw reciprocal
vector `plane_normal_hkl`. A vertical reciprocal vector has no integer (h k l)
on a non-orthogonal lattice, which is why the panel names the direct
direction. "c* elevation" (`chi_misalignment_deg`) is c*'s angle above the
horizontal; "a* azimuth" (`omega_offset_deg`) is a*'s angle from mount x in
the horizontal plane, a property of the UB, not of the turntable.

### The McStas sample chain

One Arm, `sample_mount`, at the sample position relative to `sample_arm` (z
along ki, y up). Its runtime rotation `sample_rx/ry/rz_param` is
`(R_stage(readouts) · U_true)^T` as McStas Euler angles
(`tavi/orientation.py` `sample_arm_euler`), because for an Arm
`R_abs(child) = R_rel · R_abs(parent)` and `v_local = R_abs · v_global`. The
sample component is emitted relative to it with no rotation of its own.

## Alignment Training (the Mount-only Exercise)

There is one training exercise: a crystal mounted crooked. A hidden rotation
`R_hidden` of the crystal in its mount, `U_true = R_hidden · U_described`,
is encoded in a hash that the UB Matrix dock generates, loads, clears and
checks; the student finds peaks, fits a UB and presses *Check My Alignment*.
(The Misalignment dock is retired, and so are the ψ and κ corrections and the
hidden motor-zero errors: a zero error of a turntable or an arc is not a
rotation of the crystal once the arcs tilt, so a UB fit could not undo it
exactly.)

**What is exact.** The hidden error is always exactly representable by U. From
correctly indexed reflections, the correct lattice and noiseless peaks, a UB
fit recovers it exactly, wherever the stage can bring the reflections into the
plane (the arcs tilted too), and the grade is aligned to rounding. **What is
graded.** Ordinary measurements (a peak found only to the scan's resolution, a
slightly wrong lattice field, a mis-indexed peak) are graded against the stated
tolerance on the checked reflections: `tavi/ub_matrix.py` `grade_alignment`
takes the worst miss, in degrees, between where each checked reflection of the
true crystal lies and where the operator's UB and lattice fields drive the
stage, and reports *aligned* (≤ 0.5°), *close* (≤ 2°) or *not aligned*. The
checked reflections are the student's peaks plus three reflections of the
mounting plane (u, v, u+v; without a described plane, the mount's horizontal x
and z as small (h k l) and their sum, else (1 0 0), (0 1 0), (1 1 0)).

**Codes.** The code keeps its 11-float layout, of which the last two (once the
motor-zero errors) are written 0. A code with a nonzero value there, or a retired
Misalignment-dock code (two floats), is refused, applying nothing: *this
exercise was made by an older TAVI and contains motor-zero errors, which are no
longer simulated; ask for a new code*. A code that does not decode at all is
refused with *this exercise code cannot be read*.

**Observable.** Generation and load both check that the instrument can reach
at least two non-parallel reference reflections of the sample for the hidden
rotation: indices up to 2 in size, non-zero structure factor (the sample's
reflection table, else its space group's centering rule), elastic at the fixed
energy, each brought into the scattering plane within the arcs' travel and the
instrument's axis limits by the run's own solve (`instruments/tas_runtime.py`
`training_reach_error`, over `check_point_feasibility`). Generation redraws up to 50 times and otherwise says
why; load refuses. A restore applies the same check to the instrument, sample,
crystals, fixed energy and described mount in the file being restored.

## Energy and Wave Vectors

The instrument can operate in two modes:

### Ki Fixed Mode (most common)
- Fixed incident energy: **Ei** = constant
- Variable final energy: **Ef** = Ei - ΔE
- Energy transfer: **ΔE** = Ei - Ef

### Kf Fixed Mode
- Fixed final energy: **Ef** = constant  
- Variable incident energy: **Ei** = Ef + ΔE
- Energy transfer: **ΔE** = Ei - Ef

### Wave Vector Relationships

- **Ki** = √(2mEi)/ℏ ≈ 0.6947√Ei (where Ei in meV, Ki in Å⁻¹)
- **Kf** = √(2mEf)/ℏ ≈ 0.6947√Ef
- **Q** = momentum transfer vector (calculated from H, K, L in reciprocal lattice units)

### Bragg's Law

For monochromator and analyzer crystals:
- **λ = 2d sin(θ)** where d is the crystal d-spacing
- **k = 2π/λ** relates wavelength to wave vector

## Crystal Focusing

The monochromator and analyzer can be bent to focus neutrons:

| Canonical ID | Alias | Description | Units |
|--------------|-------|-------------|-------|
| `mono_horizontal_radius_m` | **rhm** | Monochromator horizontal focusing radius | meters |
| `mono_vertical_radius_m` | **rvm** | Monochromator vertical focusing radius | meters |
| `analyzer_horizontal_radius_m` | **rha** | Analyzer horizontal focusing radius | meters |
| `analyzer_vertical_radius_m` | **rva** | Analyzer vertical focusing radius | meters |

Requested versus applied radii: see *Conventions* above.

**Ideal focusing**: The radius is calculated to focus neutrons onto the detector, maximizing intensity. Use the "Ideal" buttons in the GUI to calculate optimal values.

## Reciprocal Space Navigation

### Momentum Transfer
The momentum transfer **Q** is defined as:
- **Q = Ki - Kf** (vector difference)
- **|Q|²** = Ki² + Kf² - 2KiKf cos(A4), with A4 the sample 2θ

### HKL Coordinates
In reciprocal lattice units (r.l.u.):
- **(H, K, L)** defines the position in reciprocal space
- Requires sample lattice parameters: **a, b, c, α, β, γ**
- **Q** is calculated from HKL using the UB matrix

## Scanning Parameters

The instrument can scan any of the following parameters:

### Primary Scan Variables
- **H, K, L**: Reciprocal space coordinates (`h`, `k`, `l`)
- **qx, qy, qz**: Momentum transfer components in the public Q frame (Å⁻¹; `q_instrument_x/y/z_inv_angstrom`)
- **ΔE**: Energy transfer (meV; `energy_transfer_mev`, alias `deltaE`)

### Instrument Angles
- **A2, A3, A4, A6**: Direct angle control (angle mode): mono 2θ, sample rotation, sample 2θ, analyzer 2θ. Their NICOS names `mtt`, `sth`, `stt`, `att` and the aliases `omega`, `psi` (= A3) and `2theta` (= A4) name the same quantities
- **A1, A5**: Derived Bragg angles; refused as scan variables (scan A2 or A6)
- **sgl, sgu**: The goniometer arcs (angle mode only; refused beside Q/HKL/ΔE)
- **κ, χ, φ**: Retired or not modelled; a scan or an API write naming them is refused

### Crystal Focusing
- **rhm, rvm, rha, rva**: Crystal bending radii, requested magnitude: `mono_horizontal_radius_m`, `mono_vertical_radius_m`, `analyzer_horizontal_radius_m`, `analyzer_vertical_radius_m`

## GUI Organization

### Reciprocal Space Dock
- H, K, L inputs (r.l.u.)
- qx, qy, qz displays (Å⁻¹)
- Energy transfer ΔE (meV)

### Instrument Dock
- **Instrument Angles**: one angle per row, in beam order: Mono 2θ (A2), Sample rotation (A3), Sample 2θ (A4), Analyzer 2θ (A6), Lower arc sgl, Upper arc sgu (calculated from Q); A1 and A5 are read-only θ readouts beside their 2θ fields
- **Energies**: Ki, Kf, Ei, Ef
- **Crystal Focusing**: rhm, rvm, rha, rva

### Sample Dock
- Lattice parameters: a, b, c, α, β, γ
- Sample selection and properties
- Mounting plane

### UB Matrix Dock
- UB, peaks, scattering-plane lock
- Alignment training: generate, load, clear and check the mount-only exercise

## Scan Modes

### RLU Mode
Scan in reciprocal lattice units (H, K, L). The instrument automatically calculates all angles.

### Momentum Mode  
Scan in momentum space (qx, qy, qz). Direct control of momentum transfer.

### Angle Mode
Directly control instrument angles (A2, A3, A4, A6). Bypass automatic calculation.

## Key Relationships Summary

1. **A3 (sth, alias omega)**: the sample rotation, the turntable readout
2. **The crystal sits at the readouts**: A3, sgl and sgu, with no correction or zero error
3. **ΔE = Ei - Ef**: Energy transfer
4. **Q = Ki - Kf**: Momentum transfer (vector)