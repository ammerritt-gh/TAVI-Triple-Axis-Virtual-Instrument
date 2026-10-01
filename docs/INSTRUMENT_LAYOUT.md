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
PANDA ±15°) or is "undocumented" and unlimited (PUMA, IN8); each instrument's
`MODEL_STATUS.md` says which.

For a Q or HKL target, `tavi/orientation.py` `solve_stage` levels Q with the
smallest total arc tilt inside travel and turns it onto the scattering vector
with A3; a Q the arcs cannot level is refused, naming the arc, the angle it
would need and its travel. An in-plane Q needs no tilt and gets today's A3.
The sign convention is vTAS's: sense +1 puts `−U·B·hkl` on Q_lab, sense −1
`+U·B·hkl`. The instrument dock shows the readouts A3, `sgl`
and `sgu`; editing any of them reads Q back through the full stage.

### Corrections and physical angles

| Offset | Symbol | Corrects | Description |
|--------|--------|----------|-------------|
| **ψ** | psi | A3 | Turntable correction |
| **κ** | kappa | sgl | Lower-arc correction |

The solved angles are **readouts**: the operator's UB lives in the readout
frame at the corrections in force. The crystal sits at the **physical** angles,
readout + correction + hidden zero error (`mis_omega` on A3, `mis_chi` on sgl),
and only the McStas sample arm reads those. Which field corrects an axis and
which holds its zero error is declared on the axis (`GonioAxis.correction`,
`GonioAxis.zero_error` in `tas_goniometer`), not in the runtime.

A peak recorded with Take Position carries its stage record: every readout,
the corrections in force, ki, kf and the sense (`tavi/orientation.py`
`stage_record`; never a zero error). The UB fit reads each peak at readout +
(correction at record time − correction now) (`record_angles`), its physical
dial position in today's readout frame, so changing ψ or κ after a peak was
taken does not move that peak. A correction is not a mount rotation once the arcs
move, so a fit across a correction change is exact only where the new
corrections cancel the zero errors (or the peaks are in the plane); elsewhere
it is the least-squares U. A peak without a record (a save from before the
goniometer, a TAS_MCP peak) is a **legacy** peak: its (ω, χ, 2θ) triple keeps
the old meaning, and the UB dock marks it. A stage peak saves that triple too,
computed from its record (`legacy_triple`: the legacy setting of the same Q),
so a reader that ignores the record fits the same U.

### The McStas sample chain

One Arm, `sample_mount`, at the sample position relative to `sample_arm` (z
along ki, y up). Its runtime rotation `sample_rx/ry/rz_param` is
`(R_stage(physical) · U)^T` as McStas Euler angles
(`tavi/orientation.py` `sample_arm_euler`), because for an Arm
`R_abs(child) = R_rel · R_abs(parent)` and `v_local = R_abs · v_global`. The
sample component is emitted relative to it with no rotation of its own.

## Hidden Misalignment Angles (Training Mode)

For training exercises, hidden misalignment angles can be applied:

| Angle | Description |
|-------|-------------|
| mis_omega | Hidden in-plane misalignment |
| mis_chi | Hidden out-of-plane misalignment |
| mis_psi | Additional hidden in-plane misalignment |

These are encoded in a hash and can only be revealed by correctly adjusting the ψ and κ offsets to compensate.

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
- **ω**: Steps the ψ slot (orientation mode)
- **ψ, κ**: Corrections of the turntable and the lower arc

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
- **Alignment Offsets**: κ, ψ (set during alignment)
- Sample selection and properties

### Misalignment Dock
- Load/check/clear misalignment exercises
- Alignment feedback during training

## Scan Modes

### RLU Mode
Scan in reciprocal lattice units (H, K, L). The instrument automatically calculates all angles.

### Momentum Mode  
Scan in momentum space (qx, qy, qz). Direct control of momentum transfer.

### Angle Mode
Directly control instrument angles (A1, A2, A3, A4). Bypass automatic calculation.

### Orientation Mode
Scan the corrections (ω, ψ, κ) while keeping Q fixed.

## Key Relationships Summary

1. **ω = A3 (sth)**: Omega displays the calculated sample theta
2. **Total in-plane rotation**: A3 + ψ + misalignments
3. **Lower arc, physical**: sgl + κ + misalignments (the upper arc sgu has no correction)
4. **ΔE = Ei - Ef**: Energy transfer
5. **Q = Ki - Kf**: Momentum transfer (vector)
6. **ψ, κ are offsets only**: They don't change with Q, only during alignment