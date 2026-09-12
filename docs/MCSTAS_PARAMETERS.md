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
instrument.add_parameter("A1_param", value=0, comment="Monochromator 2-theta angle")

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
# Using parameter in a calculation
component.rotation = "A1_param / 2"  # Half the A1 angle

# Combining multiple parameters
component.position = "L1_param + offset_param"
```

### 4. Setting Parameter Values at Runtime

```python
# Set parameters before running - NO RECOMPILATION NEEDED
instrument.set_parameters(
    A1_param=45.0,
    A2_param=-30.0,
    rhm_param=2.5
)

# Run the simulation (McStasScript's default is force_compile=True, so the
# first call compiles)
data = instrument.backengine()

# Change parameters and run again - pass force_compile=False or McStasScript
# recompiles anyway; TAVI does this once the first build has succeeded
# (instruments/tas_runtime.py, run_tas_point)
instrument.set_parameters(A1_param=46.0)
data2 = instrument.backengine(force_compile=False)
```

## PUMA Instrument Parameters

The following values are implemented as McStas parameters in `instruments/puma/model.py`:

### Angle Parameters (Primary Scan Variables)
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `A1_param` | Monochromator 2-theta angle | `mono_cradle` rotation |
| `A2_param` | Sample 2-theta angle | `analyzer_arm` rotation |
| `A3_param` | Sample theta (phi) angle | `sample_cradle` rotation |
| `A4_param` | Analyzer 2-theta angle | `analyzer_cradle`, `detector_arm` rotation |
| `saz_param` | Sample azimuthal angle (out-of-plane) | `sample_gonio` rotation |

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

### Sample Orientation Parameters
| Parameter | Description | Used By |
|-----------|-------------|---------|
| `chi_param` | User chi - out-of-plane tilt | Debugging/inspection |
| `kappa_param` | Chi alignment offset | Debugging/inspection |
| `psi_param` | Omega alignment offset | Debugging/inspection |
| `chi_total` | Combined chi (chi + kappa + mis_chi) | `sample_chi_arm` rotation |
| `omega_offset_total` | Combined omega offset (psi + misalignments) | `sample_cradle` rotation |
| `mount_rx_param` | Static sample mount rotation about x | `sample_mount` rotation |
| `mount_ry_param` | Static sample mount rotation about y | `sample_mount` rotation |
| `mount_rz_param` | Static sample mount rotation about z | `sample_mount` rotation |

### Hidden Misalignment Parameters (Training)
| Parameter | Description |
|-----------|-------------|
| `mis_chi_param` | Hidden chi misalignment |
| `mis_omega_param` | Hidden omega misalignment |

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
