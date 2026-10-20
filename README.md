# TAVI - Triple-Axis Virtual Instrument

[![DOI](https://zenodo.org/badge/1129648649.svg)](https://zenodo.org/badge/latestdoi/1129648649)

TAVI is a graphical user interface for simulating triple-axis spectrometer (TAS) experiments using McStas, a neutron experiment simulation package. It is a Python-based GUI that runs the Python-based McStasScript, to call McStas, then save and display the results. TAVI ships four runnable instrument models (PUMA at MLZ, IN8 and IN12 at ILL, PANDA at MLZ) selected in the GUI.

## Why use TAVI?

TAVI is built with a user-friendly GUI that makes it (subjectively speaking) easier to use compared to using McStas directly. In particular, it requires no special knowledge of McStas components or Python programming, which makes it ideal for e.g. students and users who are not as familiar with McStas and/or neutron scattering; students who have used it for Praktika have responded positively to TAVI. An example of the GUI interface is shown below after a 2D phonon scan of lead based on DFT calculations.

<img width="2560" height="1392" alt="image" src="https://github.com/user-attachments/assets/efc9d071-74cf-4cee-a533-956edfc43315" />

TAVI writes an instrument file at runtime through McStasScript, then calls McStas. This is a fairly fast process, and normal compile times are &lt;10s. We have found that runtimes on a modern computer are roughly similar to nominal TAS counting times, i.e. 1 second per point for Bragg peak scan and ~1 minute per point for phonons. An example scan is shown below (a Bragg peak scan):

<img width="787" height="581" alt="TAVI_scan_animation" src="https://github.com/user-attachments/assets/1fc212dd-165b-4f52-aa20-ab452c246610" />

## Requirements

TAVI installs itself with a one-click installer, including Python+packages, McStas and the C-compilers McStas requires.

## Installation

### Batch file Installation

The installer brings its own C compiler; Visual Studio is not needed.

Download `WINDOWS-install-TAVI-vX.Y.Z.bat` from the latest release at [https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases) (the installer is attached to each release; it may appear a little after the release itself) and run it.

macOS and Linux: `POSIX-install-TAVI-vX.Y.Z.sh` on the same release page is a provisional script that has not yet been run on either platform; `installer/TAVI-Installation-README.md` says how to run it and what to do when it fails.

## Running the Application

To run TAVI, either use the TAVI launcher that the installation placed, or navigate to the folder containing the files and run:

```bash
python TAVI_PySide6.py
```

The GUI will launch. Adjust the instrument settings to your liking, decide on the number of neutrons for the simulation, and press the 'Run Simulation' button. Output will be saved in the `output` folder, and also displayed in the display dock. For a more detailed guide, see [User_Guide.md](User_Guide.md). The physical interpretation and numerical implementation of TAVI's generated background sources are documented in [docs/BACKGROUND_MODEL.md](docs/BACKGROUND_MODEL.md).

## Output

Simulation results are saved in the `output` directory with the following structure:

- Each simulation run creates a timestamped folder
- Individual scan points are saved in subfolders
- Data files include detector readings and scan parameters
- Plots are automatically generated for 1D and 2D scans

## Remote API

TAVI includes an optional remote API that lets external programs — scripts, notebooks, `curl`, or LLM agents — drive a running TAVI GUI over a local HTTP port. You can read the full instrument state, set any parameter, submit scans, stream live per-point results, and fetch complete scan data. The server binds `127.0.0.1:8642` by default and is controlled from the **Remote API** dock (Allow control / Read-only / Off). See `docs/API_USER_GUIDE.md` for the complete guide, including copy-paste examples for both humans and LLM agents.

## Instrument packages

Each instrument lives under `instruments/<id>/` with its runtime model (when
runnable), a plain-language overview, evidence status, immutable reference
snapshots where available (or documented snapshot gaps where none exists), and
one low-effort scientist review document. PUMA, IN8, IN12 and PANDA are all
runnable and appear in the
instrument picker. See `docs/INSTRUMENT_AUTHORING.md` and validate packages
with `python -m instruments.package_validation`.

## Troubleshooting

For help, please raise a Github issue or contact me directly.

## External Credits

TAVI is based on McStas and McStasScript, which can be found at the following location (respectively):

[https://mcstas.org/](https://mcstas.org/)

[https://mads-bertelsen.github.io/index.html](https://mads-bertelsen.github.io/index.html)

The lead sample (`Pb_phonon_DFT`) uses phonon frequencies calculated with
density-functional perturbation theory by **Rolf Heid** (Karlsruhe Institute of
Technology, KIT): the grid `pb_pdisp_3d_nq50`, from which
`components/Pb_dft_phonons.dat` is built, is included with his permission.

## License

Licensed under the GNU General Public License v3.0. See `LICENSE`.

## Funding

This work was funded by the **Bundesministerium für Forschung, Technologie und Raumfahrt** (BMBFTR) under the **NMO4PUMA** project, supported by the Karlsruhe Institute for Technology (KIT).
