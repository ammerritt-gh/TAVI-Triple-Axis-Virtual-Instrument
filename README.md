# TAVI - Triple-Axis Virtual Instrument

TAVI is a Python-based graphical user interface for simulating triple-axis spectrometer experiments using McStas.

## Requirements

- Python 3.x
- McStas 3.x or later (with mcstasscript)
- Required Python packages:
  - mcstasscript
  - numpy
  - matplotlib
  - tkinter (usually included with Python)

## Installation

1. **Install McStas**
   
   Follow the instructions at [https://mcstas.org/](https://mcstas.org/) to install McStas for your operating system.

2. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   Alternatively, install packages individually:
   ```bash
   pip install mcstasscript numpy matplotlib
   ```

   Note: `tkinter` is typically included with Python installations. If not available, install it using your system's package manager:
   - Ubuntu/Debian: `sudo apt-get install python3-tk`
   - macOS: `brew install python-tk`
   - Windows: Usually included with Python

## Running the Application

There are two ways to run TAVI:

### New MVVM Architecture (Recommended)

```bash
python run_tavi.py
```

### Legacy Application

```bash
python McScript_Runner.py
```

## Architecture

TAVI uses an MVVM (Model-View-ViewModel) architecture for clean separation of concerns:

```
tavi/
├── models/           # State management
│   ├── instrument_model.py    # Instrument configuration state
│   ├── sample_model.py        # Sample/lattice parameters
│   ├── reciprocal_space_model.py  # Q-space and HKL state
│   ├── scan_model.py          # Scan configuration
│   ├── diagnostics_model.py   # Diagnostic monitor settings
│   ├── data_model.py          # I/O configuration
│   └── application_model.py   # Central state aggregator
├── views/            # GUI components
│   ├── main_view.py           # Main application window
│   └── docks/                 # Dock widgets
│       ├── instrument_config_dock.py
│       ├── reciprocal_space_dock.py
│       ├── sample_control_dock.py
│       ├── scan_controls_dock.py
│       ├── output_dock.py
│       ├── data_control_dock.py
│       └── diagnostics_dock.py
├── viewmodels/       # Data binding (future)
├── controllers/      # Business logic
│   └── scan_controller.py     # Asynchronous simulation execution
├── instruments/      # Instrument definitions
│   ├── base_instrument.py     # Abstract TAS instrument
│   └── puma.py                # PUMA-specific implementation
└── application.py    # Main application wiring
```

### Key Components

- **Models**: Hold the application state as observable values. Changes propagate to subscribers.
- **Views/Docks**: GUI widgets organized into logical sections (instrument, sample, scan, etc.)
- **Controllers**: Handle business logic like running simulations asynchronously.
- **Instruments**: Define instrument geometry and physics calculations. New instruments can be added by inheriting from `BaseInstrument`.

## Features

- Interactive GUI for configuring PUMA triple-axis spectrometer parameters
- Support for different crystal configurations (monochromator and analyzer)
- Scan command interface for 1D and 2D scans
- Diagnostic mode with configurable monitors
- Sample configuration including lattice parameters
- Automatic data processing and visualization
- Cross-platform support (Windows, macOS, Linux)
- Asynchronous simulation execution (GUI remains responsive)
- Modular design for adding new instruments

## Configuration

On first run, the application will:
- Create an `output` directory for simulation results
- Generate a `parameters.json` file to save your settings

These files are created in the current working directory and can be freely moved or shared between computers.

## File Structure

### New Architecture (tavi package)
- `run_tavi.py` - Entry point for new MVVM application
- `tavi/` - Main package with MVVM architecture

### Legacy Files
- `McScript_Runner.py` - Legacy GUI application
- `PUMA_instrument_definition.py` - PUMA instrument setup and McStas interface
- `PUMA_GUI_calculations.py` - GUI calculation utilities
- `McScript_Functions.py` - Helper functions for file operations
- `McScript_DataProcessing.py` - Data reading and plotting utilities
- `McScript_Sample_Definition.py` - Sample and reciprocal space calculations

## Output

Simulation results are saved in the `output` directory with the following structure:
- Each simulation run creates a timestamped folder
- Individual scan points are saved in subfolders with encoded parameters
- Data files include detector readings and scan parameters
- Plots are automatically generated for 1D and 2D scans

## Extending TAVI

### Adding a New Instrument

1. Create a new file in `tavi/instruments/` (e.g., `my_instrument.py`)
2. Create a class that inherits from `BaseInstrument`
3. Implement required methods: `name`, `get_available_monochromators()`, `get_available_analyzers()`, `calculate_crystal_bending()`
4. Define the instrument geometry (arm lengths, crystal options, etc.)

Example:
```python
from tavi.instruments.base_instrument import BaseInstrument, CrystalInfo

class MyInstrument(BaseInstrument):
    @property
    def name(self) -> str:
        return "MY_INSTRUMENT"
    
    # ... implement other required methods
```

## Troubleshooting

**"No module named 'mcstasscript'"**
- Install mcstasscript: `pip install mcstasscript`

**McStas not found**
- Ensure McStas is installed and in your PATH
- The application will use the default McStas configuration

**GUI doesn't appear**
- Check that tkinter is installed
- Try running with `-v` flag for verbose output

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please ensure your code:
- Uses platform-independent path handling (os.path.join, pathlib)
- Avoids hard-coded file paths
- Follows the MVVM architecture for new GUI features
- Includes appropriate comments and documentation
