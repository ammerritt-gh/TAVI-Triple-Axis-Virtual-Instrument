# McStas Parameters in McStasScript

> **Status:** live
> **Authority:** which McStas values are run-time parameters and which force a recompile

This document explains how McStas parameters work in McStasScript and how they are implemented in the PUMA instrument definition.

## Overview: Parameters vs Variables

In McStas/McStasScript, there are two ways to pass values to components:

| Feature | **Parameters** | **Declared Variables** |
|---------|----------------|------------------------|
| **Definition** | `instrument.add_parameter("name")` | `instrument.add_declare_var("double", "name")` |
| **Exposed to user** | ✅ Yes - can be changed at runtime | ❌ No - internal only |
| **Change between runs** | ✅ **Without recompilation** | ❌ Requires recompilation |
| **Use in components** | `component.value = "param_name"` | `component.value = "var_name"` |

## Key Benefit: Avoiding Recompilation

When McStas compiles an instrument, it generates C code and compiles it into an executable. This compilation step can take significant time (10-30 seconds or more).

**Parameters allow changing values between simulation runs without recompiling the instrument.**

This is critical for:
- **Scans**: Running multiple simulations with different angle/position values
- **Optimization**: Iteratively adjusting values to find optimal settings
- **Interactive use**: Quick feedback when adjusting instrument settings

## How Parameters Work

### 1. Defining Parameters

```python
# Add a parameter with optional default value and comment
instrument.add_parameter("mono_two_theta_param", value=0, comment="Monochromator 2-theta angle")

# Parameters default to type 'double' but can be specified
instrument.add_parameter("int_param", value=5, type="int")
```

### 2. Using Parameters in Components

Parameters can be used in component attributes in two ways:

```python
# Method 1: String reference (recommended for clarity)
monochromator.RH = "rhm_param"

# Method 2: Direct assignment with instrument.parameters object
monochromator.RH = instrument.parameters["rhm_param"]
```

### 3. Mathematical Expressions with Parameters

Parameters can be combined in string expressions:

```python
# Placement takes AT=/ROTATED= lists (or set_AT()/set_ROTATED()); a string
# element is emitted verbatim into the .instr, so it may name parameters.
# This is how instruments/puma/model.py places the sample arm:
sample_arm = instrument.add_component(
    "sample_arm", "Arm", AT=[0, 0, PUMA.L1],  # PUMA.L1: the model state's arm length
    RELATIVE="origin",
    ROTATED=[0, "mono_two_theta_param", 0],
)

# Using a parameter in a calculation
sample_arm.set_ROTATED([0, "mono_two_theta_param / 2", 0])  # half the mono 2-theta

# Combining multiple parameters
sample_arm.set_AT([0, 0, "L1_param + offset_param"])
```

### 4. Setting Parameter Values at Runtime

```python
# Set parameters before running - NO RECOMPILATION NEEDED
instrument.set_parameters(
    mono_two_theta_param=45.0,
    sample_two_theta_param=-30.0,
    rhm_param=2.5
)

# Run the simulation (McStasScript's default is force_compile=True, so the
# first call compiles)
data = instrument.backengine()

# Change parameters and run again - pass force_compile=False or McStasScript
# recompiles anyway; TAVI does this once the first build has succeeded
# (instruments/tas_runtime.py, run_tas_point)
instrument.set_parameters(mono_two_theta_param=46.0)
data2 = instrument.backengine(force_compile=False)
```

## PUMA Instrument Parameters

The following values are implemented as McStas parameters in `instruments/puma/model.py`:

### Angle Parameters (Primary Scan Variables)
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `mono_two_theta_param` | Monochromator 2-theta angle | `sample_arm` rotation |
| `mono_theta_param` | Monochromator crystal θ | `mono_cradle` rotation |
| `sample_two_theta_param` | Sample 2-theta angle | `analyzer_arm` rotation |
| `sample_rotation_param` | Sample turntable readout | Inspection (the turntable reaches McStas through `sample_r*_param`) |
| `analyzer_two_theta_param` | Analyzer 2-theta angle | `detector_arm` rotation |
| `analyzer_theta_param` | Analyzer crystal θ | `analyzer_cradle` rotation |

The McStas parameters carry physical names. The `A1`–`A4` state attributes,
the `mtt`/`stt`/`att` edits and the scan-slot layout in
`instruments/tas_runtime.py` keep TAVI's older numbering internally (A1 the
monochromator 2θ, A2 the sample 2θ, A3 the sample rotation, A4 the analyzer
2θ) until U3 removes them. Everything a user sees (GUI labels, scan commands,
the API, saved settings, output files) uses the ILL numbering. Each plugin
binds its parameters to canonical IDs in its descriptor
(`ParameterSpec.quantity`, with `scale` converting the unit: McStas value =
scale × quantity value), and `plugin.capabilities().bindings` collects them:

| McStas parameter | Internal name | Physical quantity | Public ILL number | Canonical ID |
|---|---|---|---|---|
| `mono_two_theta_param` | A1, `mtt` | monochromator 2θ | A2 | `mono_two_theta_deg` |
| `sample_two_theta_param` | A2, `stt` | sample 2θ | A4 | `sample_two_theta_deg` |
| `sample_rotation_param` | A3, `sth`, `omega` | sample rotation (turntable) | A3 | `sample_rotation_deg` |
| `analyzer_two_theta_param` | A4, `att` | analyzer 2θ | A6 | `analyzer_two_theta_deg` |
| `mono_theta_param` | (none) | monochromator θ | A1 | `mono_theta_deg` |
| `analyzer_theta_param` | (none) | analyzer θ | A5 | `analyzer_theta_deg` |
| `sgl_param` | `sgl` | lower sample arc | (none) | `sample_lower_arc_deg` |
| `sgu_param` | `sgu` | upper sample arc | (none) | `sample_upper_arc_deg` |
| `rhm_param`, `rvm_param` | `rhm`, `rvm` | applied monochromator radii, signed by the branch | (none) | `applied_mono_horizontal_radius_m`, `applied_mono_vertical_radius_m` |
| `rha_param`, `rva_param` | `rha`, `rva` | applied analyzer radii, signed by the branch | (none) | `applied_analyzer_horizontal_radius_m`, `applied_analyzer_vertical_radius_m` |

The public A1 (monochromator θ) and A5 (analyzer θ) are derived, never inputs:
half of A2 and A6, signed as them, produced by one function
(`instruments.rules.crystal_theta`, the `crystal_theta` rule's evaluator). The
models emit them as `mono_theta_param` and `analyzer_theta_param`, and the
crystal cradles rotate by those, so a later rocking rule can drive θ without
changing the tree. `docs/INSTRUMENT_LAYOUT.md` holds the public angle table.

### Crystal Bending Parameters
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `rhm_param` | Monochromator horizontal bending radius | `monochromator` component |
| `rvm_param` | Monochromator vertical bending radius | `monochromator` component |
| `rha_param` | Analyzer horizontal bending radius | `analyzer` component |
| `rva_param` | Analyzer vertical bending radius | `analyzer` component |

### Slit Aperture Parameters
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `vbl_hgap_param` | Post-mono slit width (between mono and sample) | `postmono_slit` |
| `pbl_hgap_param` | Pre-sample slit width (horizontal, before sample) | `sample_slit` |
| `pbl_vgap_param` | Pre-sample slit height (vertical, before sample) | `sample_slit` |
| `dbl_hgap_param` | Detector slit width (before detector) | `detector_slit` |

These are metres, under the plugin's own slit names. The public name of each
gap is a key in millimetres: `vbl_hgap_param` is `slit.post_mono.horizontal_gap_mm`,
`pbl_hgap_param` and `pbl_vgap_param` are `slit.pre_sample.horizontal_gap_mm` and
`.vertical_gap_mm`, and `dbl_hgap_param` is `slit.detector.horizontal_gap_mm`.
Each is bound in the descriptor with `scale=1e-3`. Every aperture on all four
instruments is a runtime parameter, so a slit scan changes it per point without
recompiling (`tests/test_plugin_bindings.py`).

### Sample Orientation Parameters
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `sample_rx_param` | Sample arm rotation about x | `sample_mount` rotation |
| `sample_ry_param` | Sample arm rotation about y | `sample_mount` rotation |
| `sample_rz_param` | Sample arm rotation about z | `sample_mount` rotation |
| `sgl_param` | Lower arc `sgl` readout | Debugging/inspection |
| `sgu_param` | Upper arc `sgu` readout | Debugging/inspection |

The whole sample orientation is one Arm. `sample_rx/ry/rz_param` are the McStas
Euler angles of `(R_stage · U)^T`, where `R_stage` is the goniometer (A3, `sgl`,
`sgu`) at its **readouts** (there is no correction and no zero error)
and `U` is the true crystal mount `U_true` (`tavi/orientation.py`
`sample_arm_euler`, filled per point by
`TAS_Instrument.sample_orientation_params`). The arm never reads the
operator's UB: fitting or editing the UB changes the readouts commanded for an
HKL, not the simulated crystal (`docs/INSTRUMENT_LAYOUT.md`, "Truth and
belief"). They are runtime parameters: a new A3, arc setting, UB or
true mount never recompiles, and `build_fingerprint` does not see them. Every
instrument shares this set.

A `Single_crystal` sample takes its lattice from its reflection file and lays
it out in the component's own frame. Cubic Al cannot tell the frames apart; a
non-cubic `Single_crystal` sample must give explicit lattice vectors
(`ax, ay, az`, `bx, ...`) in TAVI's frame (a along x, b in the horizontal xz
plane, c completing it: `tavi/sample_mount.py` `reciprocal_basis_tas`), or its
crystal axes will not be where the UB says.

### Source Parameters
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `E0_param` | Source energy (meV) for the monochromatic source | `source.E0` |
| `nu_param` | Velocity selector frequency | `v_selector` component (only when `V_selector_installed`) |

## What Requires Recompilation

The following changes **always require recompilation** because they are baked into the generated instrument, either as which components are present or as component configuration that is not a McStas parameter. The authoritative list is the build-time state hashed by `PUMAPlugin.build_fingerprint()` (`instruments/puma/plugin.py`); the controller reuses the previous compiled binary only when that hash matches:

- **Diagnostic mode and settings**: adding/removing monitors (PSD, DSD, E_monitor)
- **NMO configuration**: changing between None/Vertical/Horizontal/Both
- **Velocity selector**: enabling/disabling
- **Collimators**: `alpha_1`, the installed `alpha_2` set (30', 40', 60'), `alpha_3`, `alpha_4`
- **Crystals**: `monocris`, `anacris` (baked into the component tree at build time)
- **Source**: `source_type`, `source_dE`
- **Sample type**: changing the sample component (`sample_key`)

These are typically configuration changes made between scans, not during scans, so recompilation is acceptable.

## Best Practices

1. **Make scannable values parameters**: Any value that changes during a scan should be a McStas parameter
2. **Keep configuration values hardcoded**: Values that only change between scans (collimation, NMO, sample type) can remain as Python values
3. **Use descriptive names**: End parameter names with `_param` for clarity
4. **Add comments**: Use the `comment` argument to document each parameter
5. **Group related parameters**: Set related parameters together in `set_parameters()` calls

## References

- [McStasScript Parameters and Variables Guide](https://mads-bertelsen.github.io/user_guide/parameters_and_variables.html)
- [McStas Component Manual](https://www.mcstas.org/documentation/)
