# User Guide
This user guide is to explain the TAVI GUI and the relevant functions of the program. It assumes that a user is familiar with the basics of neutron scattering and solid-state physics.

## Starting
Starting the program is done through the main file via Python:
```bash
python TAVI_PySide6.py
```

# Docks
The GUI is grouped into various docks that are separated by function. The docks are moveable. They can be moved within the GUI itself and docked to different parts, or they can be moved outside of the main GUI (e.g. to a second monitor). The view configuration is saved automatically, but if you lose a dock or wish to reset to defaults, this can be done in the top-left menus. All instrument parameters are saved upon starting a scan or when saved manually.

## Instrument Configuration Dock
The instrument configuration dock directly sets up the instrument, in the form of raw angles (A1-A4), mono/ana crystals and various parts of the instrument.

- Scan commands will override the instrument configuration. As an example, when one scans over ω, the value given in the instrument configuration dock is replaced by the scan value for each point.
- Angles and the K<sub>i</sub>/K<sub>f</sub>+E<sub>i</sub>/E<sub>f</sub> are all linked; changing one will update others, based on the given scattering geometry and mono/ana configuration. So for example, changing the E<sub>i</sub> will automatically change K<sub>i</sub> and the Mono 2θ angle.
- TAVI uses ω, sample θ and A3 as different names for the same equivalent angle.

### Collimations
Collimations are given here based on what is available for the instrument. For example, on PUMA the α1 collimations are mutually exclusive but the α2 collimations are not. 0 is the "open" configuration, with no collimator at all, which may be unrealistic, but is available for testing.

- α1 is the source-to-monochromator collimation
- α2 is the monochromator-to-sample collimation
- α3 is the sample-to-analyzer collimation 
- α4 is the analyzer-to-detector collimation. 

### Crystal Focusing
The monochromator and analyzer crystal focusing can be controlled in this section. The ideal radius of curvature is calculated and shown, based on the instrument geometry, in the fixed boxes. If a box is grayed out and unselectable, then the entry is "locked" to the calculated ideal radius. It will automatically update as the geomtry changes e.g. when scanning. If the box is *not* grayed out and it *is* selectable, then the radius of curvature has been set by the user: it will stay with what is in the entry box. To set back to the ideal value, just click the button. In all cases, scans over the focusing will override any values here.

### Experimental Modules
This contains experimental modules that are not normally included or set up. On PUMA, the nested mirror optic (NMO) is not yet installed, and the velocity selector is an option for testing but does not exist.

## Scattering Dock
The scattering dock controls the parameters of the scattering experiment i.e. the QE-setup and scattering mode. Like the instrument control, the scattering controls are linked together, and e.g. changes to energy transfers will change angles and final/initial energies depending on the mode.

The usage of absolute Q or relative HKL space is determined by the "Sample frame mode" box in the sample dock. With this off, the isntrument uses absolute Q units. With it on, it uses HKL space, using the sample lattice parameters.

## Sample Dock
The sample dock is for configuring the sample within the beam of the instrument.
- The "Sample frame mode" checkbox determines whether the scattering is in absolute Q or HKL space.
- The sample selection determines whether the sample undergoes Bragg scattering or from an acoustic/optic phonon.
- The sample configuration box is under development.
- Lattice parameters determine the geometry of the lattice.
- Sample alignment offsets are used with the misalignment training (below) to correct for any sample misalignment.

### Misalignment Training Dock
By default, the sample is perfectly aligned in the beam. It is possible to create an obfuscated misalignment in the sample that can then be corrected, for example when training a student in aligning a sample. To generate and correct a misalignment, follow these steps:
1. Enter the desired misalignment in ω (in-place) and χ (out-of-plane) angles. Click "generate hash" and delete these entries if the student will be using the computer later.
2. Enter the misalignment hash in the box and load it, either within the same run or shared with a student, to add a hidden misalignment to the sample.
3. In the sample dock, the student may enter offsets to correct the misalignment. Note that misalignment + correction = 0 ideally.
4. A student may check the alignment (roughly) in the dock with the provided button.

## Simulation Dock
The simulation dock is the main center for ruinning an experiment.

- Select the number of neutrons. A rough estimate for the time the simulation will take, per point, is given here.
- To start an simulation, click the "Run Simulation" button.
- "Stop Simulation" will stop any ongoing simulation once a point finishes. "Quit" will also stop simulations and quit.

Finished simulations are saved into a named folder. When all scans are completed, the program saves a formatted data file and display figure automatically.
### Running Scans
Scans are simulations over multiple points. Scans can be 1D or 2D, with 1 or 2 scan commands given. Scans are given as "variable X Y Z" with variable as the variable to scan over, X the starting point, Y the ending point, and Z the step size. The "Relative" button will scan relative to its current position, so e.g. a scan "omega 0 10 0.1" will scan omega from 0° to 10° in steps of 0.1°, but with **relative** enabled it will scan from the current ω position to +10°. The "Valid Commands" button will give some help on scan commands and what scan parameters are allowed. It will try to estimate the number of points, how many are valid or invalid (due to scattering geometry) and estimate how long the command will take in total.

**IMPORTANT**
Scan commands use the current setup of the instrument and *then* override it with the scan command. For example, if you would like to scan over H, but keep K=L=ΔE=0, enter K=L=ΔE=0 in the scattering dock, but enter anything for H; it will be replaced point-by-point with the scan command. Any follow-on calculations will happen automatically, so e.g. a scan over H will automatically change instrument angles. Note that some scan elements are incompatible with each other due to conflicting calculations, these are forbidden and you sholuld see a warning.

TAVI tries to inform you if you use the wrong commands, the wrong format, or if something looks off, but it will not catch everything.

### Runtimes Cache
TAVI keeps a local log of the last 100 scans and their runtimes, and uses these to estimate how long scans will take. If there is an issue with the time estimations, you can clear this log with the "Clear Runtimes" button. Note that scans under different conditions do have different times, and the times are only an estimate.

Estimates are now kept **per machine**: the log records which computer each scan ran on, so if you use TAVI on several machines of different speeds their timings no longer blend together. Estimates also account for the execution engine (McStas vs. deterministic) and whether a scan reuses the previous compiled binary (a reused binary skips compile time, so the estimate drops it). On a fresh machine there is no local history yet — run the Scan-time benchmark once (see Utilities, below) to give it a clean baseline; ordinary scan history then refines the estimate the more you use it.

### Diagnostic Mode
Diagnostic mode enables different monitors in the beam to check beam characteristics, e.g. the neutron energy profile, position and divergence. This is helpful for understanding what is going on in the instrument and troubleshooting. Use "Enable Diagnostic Mode" to have these monitors enabled and for them to appear after a scan. Use the "Configuration" button to change which monitors are enabled.

## Display Dock
The display dock shows ongoing data collection as scans finished. If you run a single simulation (no scan commands), it will just display the final counts. For 1D scans, it shows a line graph, and for 2D a heatmap. The figure is saved automatically when all scans are done, but you can save it with more control using the "Save Plot" button.

## Message Log
The message log gives information about the ongoing program, for example, during a scan it will read back all the instrument angles.

## Data Control
Use the data control dock to determine where data is saved. Each scan is saved to its own folder, with every simulation saved to subfolders. Note that if a folder name would overlap, it appends a number at the end; it is ok to leave the name the same, it will do "scan_name" then "scan_name_1" then "scan_name_2" and so on. It (should) never overwrite your folders.

You can load data folders here as well, and they will be displayed in the display dock.

## Remote API

TAVI can be driven remotely by an external program (a script, a notebook, `curl`, or an LLM agent) through a local HTTP API, in addition to the interactive GUI. Remote clients can read the instrument state, change parameters, submit scans, stream live results, and download scan data; everything they do is mirrored back into the GUI so you can watch. The **Remote API** dock shows the listening address, lets you set the access mode (Allow control / Read-only / Off), and displays the job queue, budget, and an activity log. The server listens on `127.0.0.1:8642` by default and is off-limits to other machines unless you change that. For the full reference — endpoints, parameters, scan-command syntax, and worked examples — see `docs/API_USER_GUIDE.md`.

## Utilities

The **Utilities** menu holds standalone helper windows that read the current setup but do not change your scan.

### Scan-time benchmark

Scan-time estimates are kept per machine (see Runtimes Cache). A fresh install has no history for the current computer, so its first estimates are guesses. **Utilities → Scan-time benchmark…** gives that machine a clean baseline: it runs a short, fixed sweep of tiny scans around your current position, times them, and stores this machine's speed. You only need to run it once when you start using TAVI on a new machine — after that, ordinary scan history keeps the estimates accurate.

The dialog shows:

- **This machine** — hostname, CPU, a machine id, when it was last benchmarked, and the stored speed index.
- **Benchmark plan** — the stages that will run (a cold McStas stage that measures compile time, warm McStas stages at two neutron counts, and a deterministic stage if the instrument supports it). You can edit the neutron count of each stage before running.
- **Run / Cancel** — Run queues the stages through the normal scan queue (they show up in the job list tagged as benchmark jobs); Cancel stops them. You cannot start a benchmark while a scan is already running or queued.
- **Cross-check** — after the benchmark finishes, this compares each stage's measured time against what your existing (non-benchmark) history would have predicted, and flags any row that drifts more than 30%. A large drift usually means your history is stale or the machine has changed.

The benchmark writes its output to folders prefixed `benchmark_` so they are easy to identify and clean up.

### Resolution calculator

Computes the theoretical instrument resolution (FWHMs and projection ellipses) for the current setup at a chosen (H, K, L, ΔE). It reads the live main-window configuration but changes nothing.

### Updates

This user guide was last updated Jul. 6, 2026.
# Reciprocal Space Dock

The **View → Reciprocal Space** panel provides an interactive horizontal
reciprocal-space view of the current TAVI point.  It can be tabbed with the
Display panel or floated to another monitor; its position and visibility follow
the normal saved dock layout.

Drag **P1 / Q** to choose a Q target or **P2 / ki** to change the incident arm.
The lock buttons beside `ki`, `kf`, `|Q|`, and `ΔE` constrain that gesture; a
rejected move leaves the committed instrument state unchanged.  The Ki-fixed,
Kf-fixed, and Elastic buttons are convenient presets, not restrictions on using
other lock combinations.  During a valid drag, the controller's canonical Q,
energy, and HKL fields update live; mouse release finalizes the gesture and its
last live state.

Use the mouse wheel to zoom at the pointer and middle-drag (or Space+left-drag)
to pan.  Snap-to-reflections has priority over the optional HKL grid.  The view
preserves the current `qz` and labels it when the point is outside the displayed
plane.  Bragg circles filled by a reflection table use its `F²`; hollow circles
are explicitly a centering-rule fallback and are not structure-factor filtered.
