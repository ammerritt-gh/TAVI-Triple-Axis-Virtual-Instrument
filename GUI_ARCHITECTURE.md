# TAVI PySide6 GUI Architecture

## Overview

The TAVI application has been refactored to use PySide6 with a modular dock-based architecture following MVVM principles. The GUI is split into separate, configurable dock widgets that can be arranged by the user.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          TAVI Main Window                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌────────────────────┐  ┌────────────────────────────────────────────┐ │
│  │   Instrument       │  │  Reciprocal Space & Sample Control         │ │
│  │   Configuration    │  │  (Tabbed)                                  │ │
│  │                    │  │  ┌──────────────────────────────────────┐  │ │
│  │  • Angles          │  │  │ Reciprocal Lattice Space             │  │ │
│  │  • Energies (Ki/Ei)│  │  │  • qx, qy, qz (Å⁻¹)                 │  │ │
│  │  • Crystals        │  │  │  • H, K, L (r.l.u.)                 │  │ │
│  │  • Collimations    │  │  │  • ΔE (meV)                         │  │ │
│  │  • NMO/Velocity    │  │  └──────────────────────────────────────┘  │ │
│  │    Selector        │  │  ┌──────────────────────────────────────┐  │ │
│  │  • Crystal Focusing│  │  │ Sample Control                       │  │ │
│  └────────────────────┘  │  │  • Lattice parameters (a,b,c,α,β,γ) │  │ │
│                          │  │  • Sample configuration              │  │ │
│  ┌────────────────────┐  │  └──────────────────────────────────────┘  │ │
│  │   Scan Controls    │  └────────────────────────────────────────────┘ │
│  │                    │                                                  │
│  │  • # neutrons      │  ┌────────────────────────────────────────────┐ │
│  │  • Ki/Kf fixed     │  │          Diagnostics                       │ │
│  │  • Fixed E         │  │  • Enable diagnostic mode                  │ │
│  │  • Scan commands   │  │  • Configuration button                    │ │
│  │  • Control buttons │  └────────────────────────────────────────────┘ │
│  │  • Counts display  │                                                  │
│  └────────────────────┘                                                  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                      Output Window                                   │ │
│  │  • Message center (scrollable text)                                 │ │
│  │  • Progress bar and percentage                                      │ │
│  │  • Remaining time estimate                                          │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                      Data Control                                    │ │
│  │  • Output folder selection                                          │ │
│  │  • Load data functionality                                          │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Module Structure

### Main Application
- **TAVI_PySide6.py**: Main entry point with TAVIController class
  - Connects GUI signals to backend logic
  - Manages simulation threads
  - Handles parameter save/load
  - Coordinates between different docks

### GUI Modules

#### gui/main_window.py
- `TAVIMainWindow`: Main window class that arranges all docks
- Default layout with docks positioned logically
- Supports user customization of dock positions

#### gui/docks/instrument_dock.py
- `InstrumentDock`: Complete instrument configuration
  - Instrument angles (Mono 2θ, Sample 2θ, Sample Ψ, Ana 2θ)
  - Energies and wave vectors (Ki, Ei, Kf, Ef)
  - Crystal selections (Monochromator, Analyzer)
  - Experimental modules (NMO, Velocity selector)
  - Crystal focusing factors (rhm, rvm, rha)
  - Collimations (Alpha 1, 2, 3, 4)

#### gui/docks/reciprocal_space_dock.py
- `ReciprocalSpaceDock`: Reciprocal lattice space parameters
  - Absolute Q-space (qx, qy, qz in Å⁻¹)
  - Relative HKL space (H, K, L in r.l.u.)
  - Energy transfer (ΔE in meV)

#### gui/docks/sample_dock.py
- `SampleDock`: Sample configuration
  - Lattice parameters (a, b, c, α, β, γ)
  - Sample frame mode toggle
  - Sample configuration button

#### gui/docks/scan_controls_dock.py
- `ScanControlsDock`: Scan execution and control
  - Number of neutrons
  - Ki or Kf fixed mode
  - Fixed energy value
  - Scan command inputs (2 lines)
  - Control buttons (Run, Stop, Quit, Validation)
  - Parameter management (Save, Load, Defaults)
  - Counts display (max, total)

#### gui/docks/diagnostics_dock.py
- `DiagnosticsDock`: Diagnostics configuration
  - Enable/disable diagnostic mode
  - Configuration button for monitor settings

#### gui/docks/output_dock.py
- `OutputDock`: Output display and progress tracking
  - Message center (scrollable text area)
  - Progress bar with percentage
  - Remaining time estimate

#### gui/docks/data_control_dock.py
- `DataControlDock`: Data management
  - Output folder selection with browse button
  - Actual output folder display
  - Load data functionality with browse button

## Key Features

### Modular Design
- Each dock is a self-contained module
- Docks can be rearranged, resized, floated, or tabbed by the user
- Clean separation between GUI (View) and logic (Controller)

### Backward Compatibility
- Original tkinter GUI (`McScript_Runner.py`) remains functional
- New PySide6 GUI (`TAVI_PySide6.py`) uses same backend modules
- Both GUIs can coexist in the repository

### Extensibility
- Easy to add new docks or modify existing ones
- Controller pattern allows clean integration with backend
- Signal/slot mechanism for thread-safe GUI updates

## Usage

### Running the Application

```bash
python TAVI_PySide6.py
```

### Customizing Dock Layout
1. Run the application
2. Drag docks to new positions
3. Resize docks as needed
4. Docks can be:
   - Docked to edges (left, right, top, bottom)
   - Tabbed together
   - Floated as separate windows
   - Hidden/shown from the View menu

### Development

To add a new dock:
1. Create a new dock class in `gui/docks/`
2. Import it in `gui/main_window.py`
3. Add it to the main window layout
4. Connect its signals in the controller

## Benefits of the New Architecture

1. **Better Organization**: Related controls are grouped in logical docks
2. **Flexibility**: Users can arrange the interface to their preferences
3. **Maintainability**: Each dock is isolated and easier to modify
4. **Scalability**: Easy to add new features without cluttering the interface
5. **Modern Framework**: PySide6 provides better cross-platform support and features
6. **MVVM Pattern**: Clear separation between View (docks) and ViewModel (controller)

## Migration Notes

All functionality from the original tkinter GUI has been preserved in the dock structure:
- Instrument configuration → Instrument Dock
- Q-space and HKL parameters → Reciprocal Space Dock
- Sample parameters → Sample Dock
- Scan parameters and buttons → Scan Controls Dock
- Diagnostic options → Diagnostics Dock
- Message center and progress → Output Dock
- Folder selection and data loading → Data Control Dock

The controller (`TAVIController` in `TAVI_PySide6.py`) maintains all the backend integration and business logic from the original application.
