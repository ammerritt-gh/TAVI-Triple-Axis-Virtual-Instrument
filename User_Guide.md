# User Guide

> **Status:** live
This user guide is to explain the TAVI GUI and the relevant functions of the program. It assumes that a user is familiar with the basics of neutron scattering and solid-state physics.

## Starting
Starting the program is done through the main file via Python:
```bash
python TAVI_PySide6.py
```

# Docks
The GUI is grouped into various docks that are separated by function. The docks are moveable. They can be moved within the GUI itself and docked to different parts, or they can be moved outside of the main GUI (e.g. to a second monitor). The view configuration is saved automatically, but if you lose a dock or wish to reset to defaults, this can be done in the top-left menus. All instrument parameters are saved upon starting a scan or when saved manually.

**View → Layout** arranges the docks in 2, 3 or 4 columns; it changes only the arrangement, never the column width or any field. With 3 columns: Instrument, Scattering and Simulation on the left, Sample over the UB Matrix in the middle, and the plot over the Message Log and the Data Control, Remote API and Fitting tabs on the right. With 4: Instrument, Sample, Scattering over Simulation, then the plot over the Message Log, Data Control, Fitting and Remote API tabs. With 2 (for a laptop or a short screen): Instrument, with the Message Log, Data Control, Fitting and Remote API tabs behind it, over the Scattering and Sample tabs; the plot over Simulation on the right. On first start TAVI fills the screen and picks 3 columns on a screen at least 1400 px wide and 980 px tall (the room Windows leaves above the taskbar, in its scaled pixels), otherwise 2: a 1920x1080 screen gets 3 at 100 % scaling (Simulation's scan commands may then need a scroll) and 2 at 125 %; **View → Reset to Default Layout** picks again for the window's screen and folds the rarely used Instrument blocks.

The Instrument, Sample, Scattering and Simulation docks lay their groups out as blocks of one fixed width. **View → Column Width → Narrow** makes each of these docks one block wide and gives the rest of the window to the plot; **Wide** makes them two blocks wide where the window leaves the plot enough room, with the groups filling the left column first. A dock too narrow for two blocks shows one column. First start picks Wide on a screen 2000 px or wider, otherwise Narrow. The layout, the column width and the folded blocks are saved when TAVI closes and restored on the next start; a saved layout from another TAVI version, older or newer, is set aside once as `view_layout.json.v<its version>.bak` beside it in `config/` (the Message Log says so; a file that cannot be moved, for example while another program holds it, is copied there instead) and the picked layout is used instead.

## Instrument Configuration Dock
The instrument configuration dock directly sets up the instrument, in the form of raw angles (A1-A4), mono/ana crystals and various parts of the instrument.

- Scan commands will override the instrument configuration. As an example, when one scans over ω, the value given in the instrument configuration dock is replaced by the scan value for each point.
- Angles and the K<sub>i</sub>/K<sub>f</sub>+E<sub>i</sub>/E<sub>f</sub> are all linked; changing one will update others, based on the given scattering geometry and mono/ana configuration. So for example, changing the E<sub>i</sub> will automatically change K<sub>i</sub> and the Mono 2θ angle.
- TAVI uses ω, sample θ and A3 as different names for the same equivalent angle.
- The blocks run in the order they are usually set: angles, energies, collimations, slits, crystals, then Crystal Focusing, Experimental Modules and Source Control. Those last three start folded: click the header, or press Space or Enter on it, to show the fields. While folded, the line under the header states what they hold: the four radii ("ideal" beside a radius held at its calculated ideal), the fitted modules ("none fitted" when there are none), or the source type. Whether each block is folded is saved with the layout.

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

The first block shows the point twice: Q (Å⁻¹, the neutron's view) on the left and HKL (r.l.u., the sample's view) on the right, with the energy transfer ΔE below both. The rows sit level, but qx is not H: Q = UB·HKL, and the two coincide only in the standard setting. The Fixed Mode block below it sets whether Ki or Kf is held, and that energy.

The usage of absolute Q or relative HKL space is determined by the "Sample frame mode" box in the sample dock. With this off, the isntrument uses absolute Q units. With it on, it uses HKL space, using the sample lattice parameters.

## Sample Dock
The sample dock is for configuring the sample within the beam of the instrument.
- The "Sample frame mode" checkbox determines whether the scattering is in absolute Q or HKL space.
- The sample selection determines whether the sample undergoes Bragg scattering or from an acoustic/optic phonon.
- The sample configuration box is under development.
- Lattice parameters determine the geometry of the lattice.
- Mounting plane (optional): an (h k l) "Along x" and an (h k l) "In plane" describe how the crystal sits on the stage, for example `1 0 0` and `0 0 1` for an H0L mount. Apply remounts the simulated crystal with the first vector along the stage x axis (horizontal and perpendicular to the beam at A3 = 0) and the second in the horizontal plane, built from the selected sample's own lattice (the lattice fields are your belief and do not move the crystal). The UB starts at the new mount; recorded peaks are kept. Clear, or Apply with both fields empty, returns to the standard setting. With "No sample" there is no crystal, so Apply is refused, as is a pair of parallel vectors. Selecting a different sample keeps the crystal where it is but clears the plane's description, because it named reflections of the previous sample; the message center says so. It also sets the lattice fields to the new sample's lattice and moves your UB onto it, as saving a lattice edit does. The API shows the plane as the read-only fields `mount_plane_u` and `mount_plane_v`.
- Sample alignment offsets are used with the misalignment training (below) to correct for any sample misalignment.

### Sample goniometer
The sample sits on a turntable (A3; `omega` in the API, saved files and scan commands) carrying two crossed tilt arcs: a lower arc `sgl`, which turns about the horizontal axis perpendicular to the beam at A3 = 0, and an upper arc `sgu`, which turns about the beam axis at A3 = 0. For every Q or HKL point TAVI finds the arc setting with the smallest tilt that brings Q into the scattering plane, within the arcs' travel: PUMA and IN12 ±20°, PANDA ±15°, and unlimited on IN8, whose travel no source documents. A point the arcs cannot reach is refused with the arc, the angle it needs and its travel. When a Q or HKL you type is refused, the angle fields keep the last point that could be reached: a red line under them says they are stale, and Take Position refuses them until a Q or HKL solves again or you edit an angle. The instrument dock shows both arc readouts side by side, labelled Tilt `sgl` and Tilt `sgu` (their tooltips give the axis and the travel). They are solved whenever Q or HKL changes; typing an arc value reads Q back through both arcs. A typed value past the arc's travel stays in the field, the message center says so, and an angle-mode scan counts that point as invalid before it runs. A value that is not a finite number (`inf`, `nan`) is refused: the field goes back to the arc's current value and the message center says why. ψ corrects the turntable and κ the lower arc. The old χ field is gone. Loading a session treats the arcs exactly as it treats ω: a saved arc value (an old session's χ reads as `sgl`) is kept only where a saved ω would be, because a session that carries a UB matrix (every save writes one) re-solves all the angles from its saved Q.

The UB matrix is your belief about the crystal, not the crystal itself. The simulated crystal sits as the sample is described (TAVI's standard setting, or the mounting plane you applied) plus any hidden training rotation. Calculate UB, editing the UB, Reset, a lattice edit and Refine Lattice change the angles TAVI drives to for an HKL, never the crystal, so a wrong UB misses its peaks as it would on a real instrument. Reset, loading or clearing a training or misalignment exercise, and Defaults put the UB back to the sample as described. A session saved before this change loads with its UB taken as the crystal's mount, so it still diffracts where its UB says; an old training save comes back with its hidden rotation applied twice and does not grade correctly, so load its hash again from Defaults.

### UB matrix peaks
Each observed peak in the UB Matrix dock shows one angle per goniometer axis (A3, `sgl`, `sgu`), then 2θ, ki and kf. **Take Position** records the whole stage as it is at that moment: every arc readout, the ψ and κ corrections in force, ki, kf and the scattering sense. Calculate UB reads every recorded peak at the dial position it was really taken at, so changing ψ or κ afterwards does not move a peak that is already recorded. The fit is exact when the new corrections cancel the sample's misalignment, or when the peaks lie in the plane. Otherwise it is the best fit: a correction is not the same as turning the crystal once the arcs move. Peaks saved before the goniometer, and peaks from other tools, have no stage record. They are marked **legacy**, keep their old (ω, χ, 2θ) meaning and still fit as before; press Take Position again to record one on the stage.

### Residuals after Calculate UB
After a successful Calculate UB the **Residuals of the last Calculate UB** table shows how well your peaks agree with the new UB and with each other, and the message center gets a one-line summary. There is one row per peak: its measured |Q|, the |Q| its (h k l) has in your lattice fields, the mismatch in percent, and the angle between where the peak was measured and where your UB puts it. Then there is one row per pair of peaks: the angle between the two measured Q, the angle between their two (h k l), and the difference. Rows that need attention are marked ⚠ and shaded; hover over one to read why.
- **A pair off by more than 0.5°.** The two peaks are not at the angle their indices say, so one of them is likely mis-indexed. This is how a peak given the wrong (h k l) of the same |Q| shows itself, for example (1 1 0) entered for (1 -1 0).
- **A peak whose |Q| is more than 2 % off its indices.** When there are at least two peaks, all of them are off by the same ratio (within 0.5 %), and that ratio is more than 2 %, the row says your lattice fields are off by about that much: try Refine Lattice. Otherwise it reads "likely mis-indexed", for example (1 0 0) entered for a (2 0 0) peak. A multiple like that keeps every pair angle, so only |Q| can catch it.

The table describes the last Calculate UB and its peaks only. A failed fit leaves the previous UB and an empty table. Any other change to the UB (a manual edit, Reset, a lattice edit, Refine Lattice, loading a session, loading an exercise, Defaults) and any peak added, removed, re-indexed or re-taken empties it; press Calculate UB again to see the residuals of what you have now. Locking or releasing a plane does not change the UB and keeps the table. The residuals read only your peaks and your UB, never the hidden crystal.

### Refine Lattice
**Refine Lattice** fits the lattice to your peaks' measured |Q| and refines exactly the parameters your crystal system has. The system comes from the Sample dock's space group. The default group, 1 (P1), is taken as unset: the lattice fields' own symmetry is then used (the highest system they satisfy, for example a = b ≠ c with all angles 90° is tetragonal), and the message center and the dialog say so ("space group 1 (P1, the default) taken as unset"). A space group whose system the lattice fields do not have (a cubic group with a ≠ c, say) is refused: correct the fields or the group first. The dialog shows the system it refined, the current and refined parameters and each peak's |Q| before you apply them.

| System | Parameters refined | Peaks it needs |
|---|---|---|
| Cubic | a | 1 |
| Tetragonal | a, c | 2, at least one with l ≠ 0 and one with h or k ≠ 0 |
| Hexagonal, or trigonal on hexagonal axes | a, c | 2, likewise |
| Trigonal on rhombohedral axes | a, α | 2 |
| Orthorhombic | a, b, c | 3 |
| Monoclinic | a, b, c and the one angle not 90° (β when all are 90°) | 4 |
| Triclinic | a, b, c, α, β, γ | 6 |

The peaks must decide every parameter. A refinement whose peaks cannot is refused, and the message center names the system, how many parameters it fits and how many independent peaks you gave it; for example, only (h k 0) peaks for a tetragonal crystal cannot decide c. A refused refinement changes nothing. Only |Q| is used, never the angles between peaks, so a zero error in the arcs cannot leak into the lattice. That is why a monoclinic crystal needs four peaks and a triclinic one six, with different combinations of h, k and l. Every peak counts equally.

### Scattering plane (from your UB)
The UB Matrix dock's **Scattering Plane (from your UB)** box describes the plane your UB and lattice fields put horizontal. It is computed from your belief, not from the crystal itself and not from the locked arc tilts. **Plane normal [u v w]** is the zone axis: the direct-lattice direction that points straight up, so every reflection (h k l) with hu + kv + lw = 0 lies in the plane. In TAVI's standard setting it reads [0 0 1]; a (1 1 0)/(0 0 1) mount of a cubic crystal reads [1 -1 0]. When no direction with indices up to 6 lies within 0.1° of the vertical, the row says so and shows the raw reciprocal (h k l) of the vertical instead. **c\* elevation** is the angle of c\* above the horizontal plane (90° in the standard setting). **a\* azimuth** is the angle of a\* from the mount's x axis in the horizontal plane. It describes your UB's orientation about the vertical; the turntable correction is ψ.

### Lock plane
For an experiment you usually align once, lock a scattering plane and never move the tilt arcs again. The UB Matrix dock's Scattering Plane box has a **Lock plane** row: two (h k l) fields, **Lock** and **Release**. Lock puts the arcs where your UB levels the plane spanned by the two vectors (the smallest tilt inside the arcs' travel) and keeps them there; a plane the arcs cannot level within travel is refused, with the reason shown under the row and in the message center. With both fields empty, Lock takes the mounting plane, else the first two peaks with an (h k l), else (1 0 0)/(0 1 0).

While a plane is locked:
- Every Q or HKL point is solved at the locked tilts: only A3 (and 2θ) move. A point whose Q leaves the plane is refused, naming the plane and the angle Q leaves it by, in the angle fields' stale line, the scan point count, a scan's valid points, `/validate` and the run alike.
- The arc fields `sgl` and `sgu` and the lower-arc correction κ are read-only (their tooltips name the lock); ψ stays free. Scanning `sgl`, `sgu` or `kappa` is refused. An angle-mode scan runs at the lock's tilts, and a point whose arc values differ from them is refused before it runs. Every point, from the Run button or the API, runs at the lock's own κ, not the field's rounded display of it.
- Loading or clearing either exercise (the UB Matrix dock's training exercise or the Misalignment dock's exercise), and applying or clearing a mounting plane, are refused: they would move the crystal under the locked tilts. Release first. Defaults is the exception: it releases the lock itself.
- Calculate UB, editing the UB, Reset, a lattice edit and selecting a sample are allowed and never move the arcs. When your UB no longer levels the locked plane within 0.05°, the status line says **STALE**: release and lock again to follow the new UB.

Release returns to free mode, where the arcs follow each Q again. A save keeps the lock, and loading it restores the lock after the sample and any exercise; a saved lock whose tilts are past this instrument's travel is released with a message. Switching instrument releases the lock and removes it from the outgoing instrument's saved parameters (nothing else is saved). Training is graded at the locked tilts while a plane is locked.

### Aligning from cold: a walkthrough
The whole path from a fresh start to a scan in an aligned plane, mouse and keyboard only:
1. Start clean. Open the UB Matrix dock with **Open UB Matrix...** in the Sample dock (or **View → UB Matrix**); with 3 columns it is already docked under the Sample dock, with 2 or 4 it opens as a floating panel. Uncheck **Lock** on any peak entry, remove extra entries with ✗ (two always remain) and clear the two that are left, and clear the two **Lock plane** fields (Defaults leaves their text). Then choose **File → Load Defaults**. The UB is now the sample as described, with no mounting plane.
2. For a training exercise, paste its hash into the UB Matrix dock's **Student: Load Exercise** field and press **Load**.
3. In the Simulation dock choose **Engine: Deterministic (analytic)** for quick scans (McStas works too, more slowly).
4. Type the (h k l) of a strong reflection, for example 2 0 0, into the Scattering dock. The instrument goes where your UB says the reflection is, which for a misaligned crystal is not quite where it is.
5. Rock the sample: press **Relative** beside the first scan command, enter `A3 -3 3 0.1` and press **Run Simulation**.
6. In the Fitting dock press **Fit**, then **Go to CEN**: A3 moves to the fitted centre of the peak.
7. In the UB Matrix dock press **Take Position** on Peak 1 and type its (h k l).
8. Repeat steps 4 to 7 for a second reflection that is not parallel to the first, for example 0 2 0, into Peak 2.
9. Press **Calculate UB** and read the residuals table. A row marked ⚠ means a peak is likely mis-indexed, or that your lattice fields are off: correct the (h k l), or try Refine Lattice, and press Calculate UB again until no row is marked.
10. Read the **Scattering Plane (from your UB)** box: the plane normal [u v w] is the direction your UB now puts vertical.
11. Type the two reflections that span the plane you want into the **Lock plane** fields, for example 2 0 0 and 0 2 0, and press **Lock**. With both fields empty, Lock takes the mounting plane if you applied one, else the first two peaks with an (h k l); typing the two is the sure way.
12. Press **Relative** again to turn it off, enter your scan, for example `H 1.9 2.1 0.1`, check that the point count under the scan commands says every point is valid, and press **Run Simulation**. Every point runs at the locked tilts and κ.

In a training exercise, **Check My Alignment** then grades how well your setup finds the true reflections.

### Misalignment Training Dock
By default, the sample is perfectly aligned in the beam. It is possible to create an obfuscated misalignment in the sample that can then be corrected, for example when training a student in aligning a sample. To generate and correct a misalignment, follow these steps:
1. Enter the desired misalignment of the turntable (ω mis, in-plane) and of the lower arc (sgl mis, out-of-plane). Click "generate hash" and delete these entries if the student will be using the computer later.
2. Enter the misalignment hash in the box and load it, either within the same run or shared with a student, to add a hidden misalignment to the sample. One exercise is loaded at a time: while a UB training exercise is loaded, loading or clearing a misalignment is refused (and the other way round); clear the other exercise first, or press Defaults. Loading or clearing an exercise puts the UB back to the sample as described.
3. In the sample dock, the student may enter offsets to correct the misalignment, or find the peaks and fit a UB that absorbs it.
4. A student may check the alignment in the dock with the provided button; it is graded as described below.

### Training: how alignment is graded
The UB Matrix dock's training exercise (a hidden mount rotation plus hidden zero errors) and the Misalignment dock's exercise (hidden zero errors only) are graded by one check, with the same tolerances. It does not compare your UB with the hidden rotation, or ψ and κ with the hidden offsets. It asks whether your setup puts the instrument on the reflections: for each reflection it takes the angles your UB, lattice fields and ψ/κ corrections command, and measures how far the true reflection is from where they drive. The miss is the larger of the angle between the true and the commanded scattering vector, and the 2θ difference between the commanded and the true |Q| at the current ki and kf. The reflections are your peaks' HKLs plus three of the mounting plane (u, v and u+v); with no plane described, they are the smallest (h k l) along the mount's horizontal x and z axes and their sum, which in the standard setting are (1 0 0), (0 1 0) and (1 1 0). When either axis has no (h k l) with indices up to 6 within 0.1°, the check grades (1 0 0), (0 1 0) and (1 1 0) and the message center says so. The worst miss decides: within 0.5° is aligned, within 2° close, more is not yet aligned. Only the worst miss and its HKL are shown. A true |Q| that closes no scattering triangle at the current ki and kf counts as way off, naming the reflection.

A reflection your UB cannot reach (too large a |Q|, or past the arcs' travel) is skipped, and the message center names it. If fewer than two non-parallel reflections remain, or no sample is selected, the check answers "cannot assess" and says why. After you select a different sample in a plane-mounted session, the plane's description is gone but the mount is kept, so grading uses your peaks plus the reflections along the kept mount's horizontal axes.

A UB fitted from peaks found on the misaligned crystal passes even with ψ = 0. In the plane, a turntable offset is a turn of the whole crystal about the vertical, and the fit absorbs it exactly, so the fitted UB drives to the true reflections. With tilted arcs, a correction offset is absorbed only approximately (see *UB matrix peaks*): the fit is exact only when the corrections cancel the zero errors, and otherwise the grade is the residual miss the fit leaves.

The exercise is hidden from the GUI and the remote API: no field, label, scan result or API response shows the hidden rotation or offsets, and a save keeps them only inside the obfuscated hash. It is not hidden from McStas's own output files, which record the sample arm's parameters, zero errors included.

## Simulation Dock
The simulation dock is the main center for ruinning an experiment.

- Select the number of neutrons. A rough estimate for the time the simulation will take, per point, is given here.
- To start an simulation, click the "Run Simulation" button.
- "Stop Simulation" will stop any ongoing simulation once a point finishes. **File → Quit** also stops simulations, then closes TAVI.

Finished simulations are saved into a named folder. When all scans are completed, the program saves a formatted data file and display figure automatically.
### Running Scans
Scans are simulations over multiple points. Scans can be 1D or 2D, with 1 or 2 scan commands given. Scans are given as "variable X Y Z" with variable as the variable to scan over, X the starting point, Y the ending point, and Z the step size. The "Relative" button will scan relative to its current position, so e.g. a scan "omega 0 10 0.1" will scan omega from 0° to 10° in steps of 0.1°, but with **relative** enabled it will scan from the current ω position to +10°. The "Valid Commands" button will give some help on scan commands and what scan parameters are allowed. It will try to estimate the number of points, how many are valid or invalid (due to scattering geometry) and estimate how long the command will take in total.

**IMPORTANT**
Scan commands use the current setup of the instrument and *then* override it with the scan command. For example, if you would like to scan over H, but keep K=L=ΔE=0, enter K=L=ΔE=0 in the scattering dock, but enter anything for H; it will be replaced point-by-point with the scan command. Any follow-on calculations will happen automatically, so e.g. a scan over H will automatically change instrument angles. Note that some scan elements are incompatible with each other due to conflicting calculations, these are forbidden and you sholuld see a warning.

The goniometer arcs `sgl` and `sgu` can be scanned in angle mode: on their own, or with A1–A4. Beside a Q, HKL or ΔE command they are refused, because such a scan solves the arcs at every point; scan κ, the lower-arc correction, instead. The old `chi` scan variable is refused with a message naming the arcs. A scan folder saved before this change still loads, with its χ read as `sgl`.

TAVI tries to inform you if you use the wrong commands, the wrong format, or if something looks off, but it will not catch everything.

### Background

The Simulation dock places **Background** on the row under the execution-engine selector.
Its checkbox is the global on/off switch and applies immediately. New sessions
start with it off, so scans initially contain no planted background.

Use **Background configuration…** to prepare the mix even while the global
switch is off. The modal dialog groups the fixed sources by their assumed
origin:

- **Environment** — ambient effects assumed independent of the instrument and
  sample, including sparse cosmic-ray spikes.
- **Instrument** — sample-environment, mounting, or instrument-related effects,
  including one control for six synthetic aluminum powder reflections from
  aluminum caught in the beam.
- **Sample** — elastic incoherent and broad-tail effects attributed to the
  sample. Diffuse scattering is not offered because it is measured sample
  physics, not background.

Each available source has its own enable checkbox and scale multiplier. Hover
over its label or scale control for a description of what the source represents.
**Apply** commits every staged source setting; **Cancel** discards the dialog
edits. Disabled sources retain their scales, and the button tooltip summarizes
the configured sources. TAVI plants these configured sources into both McStas
and deterministic scans; it does not fit or subtract background from data.
The aluminum multiplier scales all six lines together. Their relative
strengths follow McStas's aluminum powder convention; the Al (111) absolute
reference is tuned for visible contamination (about 1% of the current
reference Bragg peak), not claimed as a calibrated cross section. The cosmic
multiplier changes event incidence only, not spike amplitude, and cosmic
events remain present in noiseless deterministic scans.

For the physical interpretation, equations, numerical calibration, and
limitations of every source, see
[`docs/BACKGROUND_MODEL.md`](docs/BACKGROUND_MODEL.md).

### Runtimes Cache
TAVI keeps a local log of the last 100 scans and their runtimes, and uses these to estimate how long scans will take. If there is an issue with the time estimations, you can clear the current instrument's part of this log with **Config → Clear Runtime Data…**, which asks first. Note that scans under different conditions do have different times, and the times are only an estimate.

Estimates are now kept **per machine**: the log records which computer each scan ran on, so if you use TAVI on several machines of different speeds their timings no longer blend together. Estimates also account for the execution engine (McStas vs. deterministic) and whether a scan reuses the previous compiled binary (a reused binary skips compile time, so the estimate drops it). On a fresh machine there is no local history yet — run the Scan-time benchmark once (see Utilities, below) to give it a clean baseline; ordinary scan history then refines the estimate the more you use it.

### Diagnostic Mode
Diagnostic mode enables different monitors in the beam to check beam characteristics, e.g. the neutron energy profile, position and divergence. This is helpful for understanding what is going on in the instrument and troubleshooting. Use "Enable Diagnostic Mode" to have these monitors enabled and for them to appear after a scan. Use the "Configuration" button to change which monitors are enabled.

## Display Dock
The display dock shows ongoing data collection as scans finished. If you run a single simulation (no scan commands), it will just display the final counts. For 1D scans, it shows a line graph, and for 2D a heatmap. The figure is saved automatically when all scans are done, but you can save it with more control using the "Save Plot" button.

## Fitting Dock

The **Fitting** dock (a tab beside Data Control and Remote API: below the plot
with 3 or 4 columns, behind the Instrument dock with 2)
fits a peak in the 1D scan currently shown in the Display dock and lets you
drive the scanned variable straight to it — the same "run a scan, go to the
peak" move you would make on a real instrument, without reading a number off
the screen and retyping it.

**Workflow**

1. Run a 1D scan. The dock follows whatever the Display dock is showing, so a
   scan you load from disk works too. It is inactive for 2D scans and says so.
2. *(Optional)* Restrict the range. Press **Select range** and drag across the
   plot, or type a min and max. The chosen window is shaded on the plot and
   everything below uses only the points inside it. **Clear** goes back to the
   whole scan. Note that pan and zoom are switched off while range selection is
   active, and are not switched back on for you.
3. Press **Fit**. Nothing is fitted until you do — a running scan never refits
   itself under you, so the numbers on screen always belong to a fit you asked
   for. You *can* fit part-way through a scan; only the points measured so far
   are used, so press Fit again later to use the rest.
4. Read the result. The fit curve is drawn over your data in red with a dashed
   line at the centre, and the grid lists centre, FWHM, height, area, the
   pseudo-Voigt mixing parameter `eta`, background, reduced deviance, and the
   point/degree-of-freedom count, each with its uncertainty.
5. Press **Go to CEN**, **Go to COM**, or **Go to MAX**. The scanned variable's
   parameter field is set to that value, exactly as if you had typed it — you
   will see it change, and it is recorded in the message log and the session
   journal.

**COM and MAX** do not need a fit — they appear as soon as the scan has counts.
COM is the counts-weighted centre of mass over raw counts (no background
subtraction — the same convention `spec` uses). The small **Copy** button next
to each puts the value on the clipboard at full precision.

They are not live per point. They are recomputed when the scan finishes, when a
scan starts or stops, when you change the range, and when you press Fit — so
during a running scan the numbers on screen can lag the plot. The **Go to COM**
and **Go to MAX** buttons do not use the displayed number: they recompute from
the current data at the moment you click, so the instrument always moves to a
value derived from everything measured so far, even if the readout above was a
few points behind.

**MAX is a bin, not a peak position.** It is the abscissa of the highest
measured point, with no interpolation, so it can only ever be as accurate as
your step size — the tooltip tells you what that step is. Use CEN when you want
a position better than one step.

**Amber "Go to CEN" means "look at the plot before you press it."** The fit
converged and the value is usable, but something about it deserves a glance:
the peak sits near the edge of the range, the centre uncertainty is large
compared to the width, the peak is weak against the background, there may be
more than one peak, or there were few degrees of freedom. Hover the button to
see which. TAVI does not refuse the move — you can see the fit curve on your
data and are better placed to judge it than the software is. The button is only
*disabled* when there is no converged fit at all (you have not pressed Fit yet,
the range changed since you did, or the fit failed); the tooltip says which.

The goto buttons are also disabled while any scan is queued or running — the
instrument is not moved out from under a measurement — and for scan variables
that have no settable field to move (`rva`, the retired `chi` of an old scan, and anything unrecognised),
which the tooltip names.

**Revert** undoes the last goto, restoring the field to the value it had
beforehand. It is one level deep: one goto, one revert.

**Noiseless runs.** If the last scan was run on the deterministic engine with
noise switched off, the status line says `noiseless run - σ nominal`. The fit
treats the values as counts and the quoted uncertainties assume Poisson
statistics, so on noiseless data they describe a hypothetical measurement, not
this one. The fitted centre is still meaningful; its error bar is not.

## Reciprocal Space Dock

The **View → Reciprocal Space** panel provides an interactive horizontal
reciprocal-space view of the current TAVI point. It can be tabbed with the
Display panel or floated to another monitor; its position and visibility follow
the normal saved dock layout.

Drag **P1 / Q** to choose a Q target or **P2 / ki** to change the incident arm.
The lock buttons beside `ki`, `kf`, `|Q|`, and `ΔE` constrain that gesture; a
rejected move leaves the committed instrument state unchanged. The Ki-fixed,
Kf-fixed, and Elastic buttons are convenient presets, not restrictions on using
other lock combinations. During a valid drag, the controller's canonical Q,
energy, and HKL fields update live; mouse release finalizes the gesture and its
last live state.

Use the mouse wheel to zoom at the pointer and middle-drag (or Space+left-drag)
to pan. Snap-to-reflections has priority over the optional HKL grid. The view
preserves the current `qz` and labels it when the point is outside the displayed
plane. Bragg circles filled by a reflection table use its `F²`; hollow circles
are explicitly a centering-rule fallback and are not structure-factor filtered.

## Message Log
The message log gives information about the ongoing program, for example, during a scan it will read back all the instrument angles.

## Data Control
Use the data control dock to determine where data is saved. Each scan is saved to its own folder, with every simulation saved to subfolders. Note that if a folder name would overlap, it appends a number at the end; it is ok to leave the name the same, it will do "scan_name" then "scan_name_1" then "scan_name_2" and so on. It (should) never overwrite your folders.

You can load data folders here as well, and they will be displayed in the display dock.

## Remote API

TAVI can be driven remotely by an external program (a script, a notebook, `curl`, or an LLM agent) through a local HTTP API, in addition to the interactive GUI. Remote clients can read the instrument state, change parameters, submit scans, stream live results, and download scan data; everything they do is mirrored back into the GUI so you can watch. The **Remote API** dock shows the listening address, lets you set the access mode (Allow control / Read-only / Off), and displays the job queue, budget, and an activity log. The server listens on `127.0.0.1:8642` by default and is off-limits to other machines unless you change that. For the full reference — endpoints, parameters, scan-command syntax, and worked examples — see `docs/API_USER_GUIDE.md`.

The API follows the goniometer: the arc readouts `sgl` and `sgu` are writable parameters and angle-mode scan variables. The old `chi` is refused, both as a parameter write (HTTP 400) and as a scan variable, with a message naming `sgl` and `sgu`. A client that still sends `chi` must switch to the arcs.

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

## Config

The **Config** menu holds machine-level preferences. They are stored in `config/settings.json` on this computer, so setup scripts do not overwrite them.

**Config → MPI processes…** sets how many MPI processes each simulated point uses. New installs start at 4. The dialog shows this computer's number of logical processors; on Linux and macOS, Open MPI allows at most one process per physical core (often half the logical count), while Windows allows more. The change applies from the next scan. Time estimates use history recorded at the same count (plus older runs from before the count was recorded), so after switching to a count with no history the first scan may show no estimate.

### Updates

This user guide was last updated Jul. 28, 2026.
