# TAVI PySide6 GUI - Quick Start Guide

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **System dependencies for PySide6 (Linux only):**
   
   On Ubuntu/Debian:
   ```bash
   sudo apt-get install libegl1 libxcb-cursor0 libxkbcommon-x11-0
   ```
   
   On other distributions, install equivalent packages for Qt/EGL support.
   
   **Windows and macOS**: No additional system packages needed.

## Running the Application

### New PySide6 GUI (Recommended)
```bash
python TAVI_PySide6.py
```

### Legacy Tkinter GUI
```bash
python McScript_Runner.py
```

## First Time Setup

1. Launch the application
2. The interface will open with default parameters
3. Click "Load Defaults" to ensure all parameters are initialized
4. Arrange the dock windows to your preference:
   - Drag dock title bars to reposition
   - Resize by dragging dock borders
   - Float docks by dragging them away from the main window
   - Tab docks together by dragging one onto another

## Basic Workflow

### 1. Configure Instrument
In the **Instrument Configuration** dock:
- Set instrument angles (Mono 2θ, Sample 2θ, Sample Ψ, Ana 2θ)
- Configure energies (Ki/Ei, Kf/Ef)
- Select monochromator and analyzer crystals
- Set collimations (Alpha 1-4)
- Enable experimental modules if needed (NMO, velocity selector)

### 2. Set Reciprocal Space Parameters
In the **Reciprocal Lattice Space** dock:
- Enter Q-space coordinates (qx, qy, qz) in Å⁻¹
- Or enter HKL coordinates in reciprocal lattice units
- Set energy transfer (ΔE) in meV

### 3. Configure Sample
In the **Sample Control** dock:
- Enter lattice parameters (a, b, c) in Ångströms
- Enter lattice angles (α, β, γ) in degrees
- Click "Sample Configuration" for detailed sample setup

### 4. Set Scan Parameters
In the **Scan Controls** dock:
- Enter number of neutrons for simulation
- Choose Ki or Kf fixed mode
- Enter fixed energy value
- Enter scan commands (e.g., "qx 2 2.2 0.1")
- Second scan command creates 2D scan

### 5. Run Simulation
1. Check **Output** dock for messages
2. Set output folder in **Data Control** dock
3. Click "Run Simulation" in **Scan Controls** dock
4. Monitor progress in **Output** dock
5. Results saved to output folder

### 6. Save Parameters
- Click "Save Parameters" to save current configuration
- Parameters are saved to `parameters.json`
- Next time you launch, parameters will be loaded automatically

## Dock Windows Overview

### Instrument Configuration
Complete instrument setup including angles, energies, crystals, and collimations.

### Reciprocal Lattice Space
Q-space (qx, qy, qz) and HKL coordinates with energy transfer.

### Sample Control
Lattice parameters and sample configuration.

### Scan Controls
Scan parameters, commands, control buttons, and parameter management.

### Diagnostics
Enable diagnostic mode and configure monitors.

### Output
Message center showing simulation progress and status.

### Data Control
Manage output folders and load existing data.

## Keyboard Shortcuts

- **Ctrl+S**: Save parameters
- **Ctrl+Q**: Quit application

## Tips and Tricks

1. **Dock Arrangement**: Your dock layout is personal! Arrange it to match your workflow.

2. **Tabbed Docks**: Related docks can be tabbed together (e.g., Reciprocal Space and Sample Control).

3. **Parameter Sets**: Save different parameter sets with different names by copying `parameters.json`.

4. **Quick Access**: Float frequently-used docks for quick access while keeping others docked.

5. **Monitor Messages**: Keep the Output dock visible to monitor simulation progress.

6. **Validation**: Use "Open Validation GUI" to check scan validity before running.

## Customization

### Window Layout
The application remembers your dock arrangement between sessions. To reset:
1. Close the application
2. Delete any Qt settings files (location varies by OS)
3. Relaunch with default layout

### Parameters
Edit `parameters.json` directly for batch parameter changes.

## Troubleshooting

### GUI doesn't start (Linux)
**Problem**: Missing system libraries for Qt/EGL
**Solution**: Install required system packages (see Installation section)

### Parameters not loading
**Problem**: Corrupted `parameters.json`
**Solution**: Delete `parameters.json` and click "Load Defaults"

### Docks disappeared
**Problem**: Dock was closed
**Solution**: View menu → Show [Dock Name] (feature to be implemented)

### Simulation not running
**Problem**: Check Output dock for error messages
**Solution**: Verify all parameters are valid, check McStas installation

## Getting Help

1. Check `GUI_ARCHITECTURE.md` for detailed architecture information
2. Check `REFACTORING_SUMMARY.md` for feature list
3. Check original `McScript_Runner.py` for reference implementation
4. Check output messages in the Output dock

## Differences from Legacy GUI

### Advantages of New GUI
- ✅ Modular dock-based layout
- ✅ User-customizable arrangement
- ✅ More organized grouping of controls
- ✅ Modern Qt framework
- ✅ Better cross-platform support

### What's the Same
- ✅ All parameters and functionality preserved
- ✅ Same backend calculations and simulations
- ✅ Same McStas integration
- ✅ Compatible parameter files

## Example: Running a Simple Scan

1. **Set instrument**:
   - Kf Fixed mode
   - Fixed E = 14.7 meV
   - PG[002] crystals

2. **Set sample**:
   - Lattice: a=3.78, b=3.78, c=5.49 Å
   - Angles: α=β=γ=90°

3. **Set scan**:
   - Command 1: `qx 2 2.2 0.1`
   - Command 2: `deltaE 3 7 0.25`

4. **Run**:
   - Number of neutrons: 1e6
   - Click "Run Simulation"

5. **Monitor**:
   - Watch Output dock for progress
   - Results saved to output folder

## Next Steps

- Explore the interface by adjusting docks
- Try different parameter combinations
- Run validation before long scans
- Save your preferred dock layout
- Create multiple parameter sets for different experiments

Enjoy using TAVI!
