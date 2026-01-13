# Instrument Configuration Guide

This document explains how to define and use instrument configurations in TAVI.

## Overview

TAVI now supports dynamic instrument definitions through JSON configuration files. This allows new instruments to be defined without modifying the GUI code. The configuration system extracts:

- Instrument arm lengths (for angle/energy conversions)
- Monochromator/analyzer crystal options and parameters
- Focusing options and ranges
- Experimental modules (NMO, velocity selector)
- Collimator options
- Slit configurations and ranges

## Configuration File Format

Instrument configurations are stored in JSON files in the `instruments/` directory with the naming convention `{INSTRUMENT_NAME}_config.json`.

### Structure

```json
{
  "name": "INSTRUMENT_NAME",
  "description": "Description of the instrument",
  
  "arm_lengths": {
    "L1": 2.150,  // source-mono distance (m)
    "L2": 2.290,  // mono-sample distance (m)
    "L3": 0.880,  // sample-ana distance (m)
    "L4": 0.750   // ana-det distance (m)
  },
  
  "monochromator_crystals": {
    "CRYSTAL_NAME": {
      "dm": 3.355,           // d-spacing (Å)
      "slabwidth": 0.0202,   // blade width (m)
      "slabheight": 0.018,   // blade height (m)
      "ncolumns": 13,        // number of columns
      "nrows": 9,            // number of rows
      "gap": 0.0005,         // gap between blades (m)
      "mosaic": 35,          // mosaic spread (arc minutes)
      "r0": 1.0              // reflectivity
    }
  },
  
  "analyzer_crystals": {
    "CRYSTAL_NAME": {
      "da": 3.355,           // d-spacing (Å)
      "slabwidth": 0.01,     // blade width (m)
      "slabheight": 0.0295,  // blade height (m)
      "ncolumns": 21,        // number of columns
      "nrows": 5,            // number of rows
      "gap": 0.0005,         // gap between blades (m)
      "mosaic": 35,          // mosaic spread (arc minutes)
      "r0": 1.0              // reflectivity
    }
  },
  
  "focusing": {
    "rhm_range": [0, 10],    // horizontal mono focusing range
    "rvm_range": [0, 10],    // vertical mono focusing range
    "rha_range": [0, 10],    // horizontal ana focusing range
    "rva_value": 0.8,        // fixed vertical ana focusing
    "rhm_min": 2.0,          // min horizontal mono focusing (m)
    "rvm_min": 0.5,          // min vertical mono focusing (m)
    "rha_min": 2.0           // min horizontal ana focusing (m)
  },
  
  "experimental_modules": {
    "nmo_options": ["None", "Vertical", "Horizontal", "Both"],
    "v_selector_available": true
  },
  
  "collimators": {
    "alpha_1_options": [0, 20, 40, 60],       // src-mono (arc minutes)
    "alpha_2_options": [30, 40, 60],          // mono-sample (arc minutes)
    "alpha_3_options": [0, 10, 20, 30, 45, 60], // sample-ana (arc minutes)
    "alpha_4_options": [0, 10, 20, 30, 45, 60]  // ana-det (arc minutes)
  },
  
  "slits": {
    "hbl_hgap": 0.078,           // H-blende horizontal gap (m)
    "hbl_vgap": 0.150,           // H-blende vertical gap (m)
    "vbl_hgap": 0.088,           // V-blende horizontal gap (m)
    "pbl_hgap": 0.100,           // P-blende horizontal gap (m)
    "pbl_vgap": 0.100,           // P-blende vertical gap (m)
    "pbl_hoffset": 0.0,          // P-blende horizontal offset (m)
    "pbl_voffset": 0.0,          // P-blende vertical offset (m)
    "dbl_hgap": 0.050,           // D-blende horizontal gap (m)
    "hbl_hgap_range": [0.01, 0.20],  // allowed range for GUI control
    "hbl_vgap_range": [0.01, 0.30],
    "vbl_hgap_range": [0.01, 0.20],
    "pbl_hgap_range": [0.01, 0.20],
    "pbl_vgap_range": [0.01, 0.20],
    "dbl_hgap_range": [0.01, 0.10]
  }
}
```

## Using a Configuration

### Default Configuration

By default, TAVI loads the PUMA configuration (`instruments/PUMA_config.json`). This happens automatically when you run:

```bash
python TAVI_PySide6.py
```

### Custom Configuration

To use a different instrument configuration, you have two options:

1. **Create a new configuration file**: Create a new JSON file following the format above (e.g., `instruments/MY_INSTRUMENT_config.json`)

2. **Modify the main application**: Edit `TAVI_PySide6.py` to load your configuration:

```python
config_file = os.path.join(instruments_dir, 'MY_INSTRUMENT_config.json')
instrument_config = load_instrument_config(config_file)
```

## GUI Updates

When a configuration is loaded:

1. **Instrument Dock**: Crystal options, collimators, and experimental modules are populated from the config
2. **Slit Controls Dock**: Slit default values and ranges are set from the config
3. **Instrument Parameters**: Arm lengths and other parameters are applied to the instrument

## Slit Controls

The new Slit Controls dock allows you to adjust slit sizes for:

- **H-Blende**: Source collimation slit (horizontal and vertical gaps)
- **V-Blende**: Post-monochromator slit (horizontal gap)
- **P-Blende**: Pre-sample slit (horizontal/vertical gaps and offsets)
- **D-Blende**: Detector slit (horizontal gap)

Slit values are saved with other parameters and applied during simulations.

## Creating a New Instrument

To create a configuration for a new instrument:

1. Copy `instruments/PUMA_config.json` to `instruments/YOUR_INSTRUMENT_config.json`
2. Update all fields with your instrument's specifications
3. Pay special attention to:
   - Arm lengths (critical for angle calculations)
   - Crystal d-spacings and dimensions
   - Available collimators and modules
   - Slit ranges (should match physical constraints)
4. Test the configuration by loading it in TAVI

## Advanced Usage

### Python API

You can also use the configuration loader in your own scripts:

```python
from instruments.instrument_config import load_instrument_config

config = load_instrument_config('instruments/PUMA_config.json')
print(f"Instrument: {config.name}")
print(f"Monochromator crystals: {config.get_monochromator_names()}")

# Get crystal info
pg002_info = config.get_monochromator_info("PG[002]")
print(f"d-spacing: {pg002_info['dm']} Å")
```

### Finding Available Instruments

```python
from instruments.instrument_config import get_available_instruments

instruments = get_available_instruments()
print(f"Available instruments: {instruments}")
```

## Validation

The configuration loader performs basic validation:
- Checks that the file exists and is valid JSON
- Required fields are documented but not enforced (defaults are used)
- GUI elements will use defaults if configuration is missing or incomplete

## Troubleshooting

**Configuration not loading?**
- Check that the file exists in the `instruments/` directory
- Verify JSON syntax (use a JSON validator)
- Check console output for error messages

**GUI elements not populating?**
- Verify crystal names match exactly in the configuration
- Check that arrays (like `alpha_1_options`) are properly formatted
- Ensure numeric values are numbers, not strings

**Slit controls not working?**
- Check that slit value ranges are valid (min < max)
- Verify default slit values are within the specified ranges
