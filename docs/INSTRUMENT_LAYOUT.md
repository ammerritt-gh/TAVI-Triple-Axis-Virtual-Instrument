# Triple-Axis Spectrometer (TAS) - PUMA Instrument Layout

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

### Actual Sample Angles

The sample has two controllable orientation angles that are calculated from the Q-vector:

| Angle | Symbol | Type | Description |
|-------|--------|------|-------------|
| **ω** | omega | In-plane rotation | Sample rotation about vertical (Y) axis - **equals A3 (sth)** |
| **χ** | chi | Out-of-plane tilt | Sample tilt about horizontal (X) axis |

**Key Relationship**: ω = A3 (sth). The omega field displays the calculated sample theta angle.

### Sample Alignment Offsets

These offsets are used to correct for sample misalignment and are set during initial alignment:

| Offset | Symbol | Applied to | Description |
|--------|--------|-----------|-------------|
| **ψ** | psi | ω offset | In-plane alignment correction (added to omega) |
| **κ** | kappa | χ offset | Out-of-plane alignment correction (added to chi) |

**Purpose**: The offsets allow you to align the sample's crystal axes with the instrument coordinates without changing the calculated angles.

### Effective Sample Rotation

The actual sample rotation in the McStas simulation includes:

- **In-plane**: `A3 + ψ + misalignments`
- **Out-of-plane**: `χ + κ + misalignments`

Note that ω is not added separately since ω = A3 already.

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
- **ω, χ**: Sample orientation (orientation mode)
- **ψ, κ**: Alignment offsets

### Crystal Focusing
- **rhm, rvm, rha, rva**: Crystal bending radii

## GUI Organization

### Reciprocal Space Dock
- H, K, L inputs (r.l.u.)
- qx, qy, qz displays (Å⁻¹)
- Energy transfer ΔE (meV)

### Instrument Dock
- **Instrument Angles**: A1, A2, A4, ω, χ (calculated from Q)
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
Scan sample orientation angles (ω, χ, ψ, κ) while keeping Q fixed.

## Key Relationships Summary

1. **ω = A3 (sth)**: Omega displays the calculated sample theta
2. **Total in-plane rotation**: A3 + ψ + misalignments
3. **Total out-of-plane tilt**: χ + κ + misalignments
4. **ΔE = Ei - Ef**: Energy transfer
5. **Q = Ki - Kf**: Momentum transfer (vector)
6. **ψ, κ are offsets only**: They don't change with Q, only during alignment