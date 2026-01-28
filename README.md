# TAVI - Triple-Axis Virtual Instrument

TAVI is a Python-based graphical user interface for simulating triple-axis spectrometer experiments using McStas.


[TAVI in use](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/tree/main/repo_info/TAVI_usage_screenshot.png?raw=true)

## Requirements

- Python 3.x
- McStas 3.x or later (with mcstasscript)
- Required Python packages:
  - mcstasscript
  - numpy
  - matplotlib
  - PySide6 (for the new modular GUI)
  - tkinter (for the legacy GUI, usually included with Python)

## Installation

1. **Install McStas**
   
   Follow the instructions at [https://mcstas.org/](https://mcstas.org/) to install McStas for your operating system. Do NOT use the McStas package, but install the McStas metapackage (under legacy options). Be sure to add McStas to your system path.

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

To run TAVI, navigate to the folder containing the files and run:

```bash
python TAVI_PySide6.py
```

## Output

Simulation results are saved in the `output` directory with the following structure:
- Each simulation run creates a timestamped folder
- Individual scan points are saved in subfolders
- Data files include detector readings and scan parameters
- Plots are automatically generated for 1D and 2D scans

## Troubleshooting

**"No module named 'mcstasscript'"**
- Install mcstasscript: `pip install mcstasscript`

**McStas not found**
- Ensure McStas is installed and in your PATH

## External Credits

TAVI is based on McStas and McStasScript, which can be found at the following location (respectively):
[https://mcstas.org/](https://mcstas.org/)

[https://mads-bertelsen.github.io/index.html](https://mads-bertelsen.github.io/index.html)

## License

Licensed under the GNU General Public License v3.0. See `LICENSE`.
