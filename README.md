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
   pip install mcstasscript numpy matplotlib
   ```

   Note: `tkinter` is typically included with Python installations. If not available, install it using your system's package manager:
   - Ubuntu/Debian: `sudo apt-get install python3-tk`
   - macOS: `brew install python-tk`
   - Windows: Usually included with Python

## Running the Application

1. Navigate to the TAVI directory
2. Run the main application:

   ```bash
   python McScript_Runner.py
   ```

## Features

- Interactive GUI for configuring PUMA triple-axis spectrometer parameters
- Support for different crystal configurations (monochromator and analyzer)
- Scan command interface for 1D and 2D scans
- Diagnostic mode with configurable monitors
- Sample configuration including lattice parameters
- Automatic data processing and visualization
- Cross-platform support (Windows, macOS, Linux)

## Configuration

On first run, the application will:
- Create an `output` directory for simulation results
- Generate a `parameters.json` file to save your settings

These files are created in the current working directory and can be freely moved or shared between computers.

## File Structure

- `McScript_Runner.py` - Main GUI application
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
- Includes appropriate comments and documentation
