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
         (A1)            (A3)     (A4)
                         (A2)
```

### Main Rotation Angles

The four primary angles define the instrument configuration:

| Angle | Symbol | Name | Description |
|-------|--------|------|-------------|
| **A1** | mtt | Monochromator 2θ | Take-off angle from monochromator |
| **A2** | stt | Sample 2θ | Scattering angle at sample |
| **A3** | sth | Sample θ | Sample rotation (in-plane) |
| **A4** | att | Analyzer 2θ | Take-off angle from analyzer |

These angles are calculated automatically based on the desired momentum transfer **Q** and energy transfer **ΔE**.

### Coordinate System

- **Horizontal plane**: Defined by neutron beam path
- **Vertical axis (Y)**: Perpendicular to horizontal plane (up)
- **In-plane**: Rotation about vertical axis (azimuthal)
- **Out-of-plane**: Tilt away from horizontal plane (elevation)

## Sample Orientation

### The sample stage (goniometer)

Each instrument declares its sample stage as data (`goniometer` in its
descriptor, `instruments/descriptor.py`), outermost axis first. Every TAS has
the same three axes:

| Axis | Rotation axis (stage at zero) | Description |
|------|-------------------------------|-------------|
| **A3** | vertical (Y) | Turntable; the A3 field shows it (`omega` in the API and saved files; ω = A3 = sth) |
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
each peak at its recorded readouts (`record_angles`). A record saved while the
corrections existed may carry a `"corrections"` entry: all zero it reads as it
is, but a nonzero one put the peak in another readout frame that cannot be
reconstructed, so it is refused (a saved file holding one is refused whole, see
*Saved parameters*). A peak without a record (a save from before the
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
`_schema` version (4 now; the history is the comment on
`PARAMETERS_SCHEMA_VERSION`). A block keeps `U_described` and the plane under
`true_mount`, and `R_hidden` only inside the training hash; restore replaces
the hidden truth in full (no hash: `R_hidden` = I) without touching the saved
UB. The version is enforced, with no converter. Restore judges the whole block
first (`TAVIController._saved_parameters_refusal`): its version, every saved
peak's stage record, and the saved exercise, which must be a mount-only code
this instrument can still observe, judged on the sample, crystals, fixed
energy and described mount **in the file**, never the live ones. On any
refusal nothing is applied and the file is renamed `parameters.json.bak`
(`.bak2`, `.bak3`, ... when one exists; a backup is never overwritten). At
start-up the defaults load; File > Load Parameters mid-session leaves the
session exactly as it was. One message-centre line says why and names the
backup. The file is renamed whole, so the other instruments' blocks go with it
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
(The Misalignment dock and the hidden motor-zero errors, ψ and κ, are retired:
a zero error of a turntable or an arc is not a rotation of the crystal once the
arcs tilt, so a UB fit could not undo it exactly.)

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
motor-zero errors) are written 0. A code with a nonzero value there, a retired
Misalignment-dock code (two floats) or one that does not decode is refused,
applying nothing: *this exercise was made by an older TAVI and contains
motor-zero errors, which are no longer simulated; ask for a new code*.

**Observable.** Generation and load both check that the instrument can reach
at least two non-parallel reference reflections of the sample for the hidden
rotation: indices up to 2 in size, non-zero structure factor (the sample's
reflection table, else its space group's centering rule), elastic at the fixed
energy, each brought into the scattering plane within the arcs' travel by the
run's own solve (`instruments/tas_runtime.py` `training_reach_error`, over
`check_point_feasibility`). Generation redraws up to 50 times and otherwise says
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

| Parameter | Description | Units |
|-----------|-------------|-------|
| **rhm** | Monochromator horizontal focusing radius | meters |
| **rvm** | Monochromator vertical focusing radius | meters |
| **rha** | Analyzer horizontal focusing radius | meters |
| **rva** | Analyzer vertical focusing radius | meters |

**Ideal focusing**: The radius is calculated to focus neutrons onto the detector, maximizing intensity. Use the "Ideal" buttons in the GUI to calculate optimal values.

## Reciprocal Space Navigation

### Momentum Transfer
The momentum transfer **Q** is defined as:
- **Q = Ki - Kf** (vector difference)
- **|Q|²** = Ki² + Kf² - 2KiKf cos(A2)

### HKL Coordinates
In reciprocal lattice units (r.l.u.):
- **(H, K, L)** defines the position in reciprocal space
- Requires sample lattice parameters: **a, b, c, α, β, γ**
- **Q** is calculated from HKL using the UB matrix

## Scanning Parameters

The instrument can scan any of the following parameters:

### Primary Scan Variables
- **H, K, L**: Reciprocal space coordinates
- **qx, qy, qz**: Momentum transfer components (Å⁻¹)
- **ΔE**: Energy transfer (meV)

### Instrument Angles
- **A1, A2, A3, A4**: Direct angle control (angle mode)
- **sgl, sgu**: The goniometer arcs (angle mode only; refused beside Q/HKL/ΔE)
- **ω**: The sample rotation A3 itself (an alias of A3; angle mode)
- **ψ, κ**: Retired; a scan or an API write naming them is refused

### Crystal Focusing
- **rhm, rvm, rha, rva**: Crystal bending radii

## GUI Organization

### Reciprocal Space Dock
- H, K, L inputs (r.l.u.)
- qx, qy, qz displays (Å⁻¹)
- Energy transfer ΔE (meV)

### Instrument Dock
- **Instrument Angles**: A1, A2, A4, ω (A3), sgl, sgu (calculated from Q)
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
Directly control instrument angles (A1, A2, A3, A4). Bypass automatic calculation.

## Key Relationships Summary

1. **ω = A3 (sth)**: Omega is the sample rotation, the turntable readout
2. **The crystal sits at the readouts**: A3, sgl and sgu, with no correction or zero error
3. **ΔE = Ei - Ef**: Energy transfer
4. **Q = Ki - Kf**: Momentum transfer (vector)