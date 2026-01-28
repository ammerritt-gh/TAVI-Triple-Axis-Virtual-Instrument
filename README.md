# TAVI - Triple-Axis Virtual Instrument

TAVI is a graphical user interface for simulating triple-axis spectrometer (TAS) experiments using McStas. It is basically a Python-based GUI that runs the Pyton-based McStasScript, to call McStas, then save and display the results. Currently, it simulates the PUMA TAS at the MLZ.

## Why use TAVI?
TAVI is built with a user-friendly GUI that makes it (subjectively speaking) easier to use compared to using McStas directly. In particular, it requires no special knowledge of McStas components or Python programming, which makes it ideal for e.g. students and users; students who have used it for Praktika have responded positively to TAVI. An example of the GUI interface is shown below after a 2D phonon scan.

<img width="1920" height="1080" alt="TAVI_usage_screenshot" src="https://github.com/user-attachments/assets/61ba084d-733e-4f3a-99ec-104e71be1691" />


TAVI writes an instrument file at runtime through McStasScript, then calls McStas. This is a fairly fast process, and normal compile times are <10s. We have found that runtimes on a modern computer are roughly similar to nominal TAS counting times, i.e. 1 second per point for Bragg peak scan and ~1 minute per point for phonons. An example scan is shown below (a Bragg peak scan):


![TAVI_scan_animation](https://github.com/user-attachments/assets/edf7c97b-b965-4184-90ee-d4ce6db9b333)

## Requirements

- Python 3.x
- McStas 3.4 or later (with mcstasscript)
- Required Python packages:
  - mcstasscript
  - numpy
  - matplotlib
  - PySide6 (for the new modular GUI)
 
  - TAVI includes custom McStas components that are present in /components. These do not need to be placed in the McStas installation folders unless you try to use them in other programs.

## Installation

1. **Install McStas**
   
   Follow the instructions at [https://mcstas.org/](https://mcstas.org/) to install McStas for your operating system. Do NOT use the McStas package, but install the McStas metapackage (under legacy options). Be sure to add McStas to your system path.

2. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   Alternatively, install packages individually:
   ```bash
   pip install mcstasscript numpy matplotlib pyside6
   ```

## Running the Application

To run TAVI, navigate to the folder containing the files and run:

```bash
python TAVI_PySide6.py
```

The GUI will launch. Adjust the instrument settings to your liking, decide on the number of neutrons for the simulation, and press the 'Run Simulation' button. Output will be saved in the `output` folder, and also displayed in the display dock. A more detailed tutorial is to follow...

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

## Funding

This work was funded by the **Bundesministerium für Forschung, Technologie und Raumfahrt** (BMBFTR) under the **NMO4PUMA** project, supported by the Karlsruhe Institute for Technology (KIT).
