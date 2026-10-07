# Changelog

Fragments for the next release live in `changelog.d`; see `changelog.d\README.md` for the format.

## v1.3.2 — 2026-10-07

**Read this first.** Release 1.3.2 rebuilds how TAVI orients a crystal. The sample now sits on a turntable carrying two tilt arcs (sgl and sgu, which replace χ), and the simulated crystal follows its true mount rather than your UB matrix, so a wrong UB misses its peaks just as it would on a real instrument. Calculate UB is fixed on IN8, IN12 and PANDA, where the orientation used to come out turned 180°. Sessions saved before this release load as closely as they can, with two exceptions: a peak found in a session with a non-default crystal orientation may move, and an old training save no longer grades correctly. The Windows installer now keeps everything in one folder you choose, adds Uninstall to the launcher menu, and always starts the Python and McStas that belong to that installation: if your neutron simulations failed while the fast analytic engine worked, this is the fix, and a separate repair tool fixes existing installations. On Linux and macOS each simulation point now runs 4 MPI processes by default (set under Config → MPI processes), so small machines no longer fail at the first scan.

### Major features

- The simulated crystal now sits where the sample really is, not where your UB matrix says, so a wrong UB misses its peaks as on a real instrument; you can describe how the crystal is mounted with an optional mounting plane in the Sample dock, and training in both the UB Matrix and the Misalignment docks is graded by the worst miss over your reflections, with the Misalignment dock's tolerances now 0.5° and 2°. A new Lock plane in the UB Matrix dock holds the tilt arcs and kappa for an experiment: every point is solved at the locked tilts, a point out of the plane is refused naming the plane, and a STALE mark shows when your UB no longer levels it.

### Minor features

- The Windows installer asks where to put TAVI and keeps the program, its Python environment, McStas and the downloaded packages together in the folder you name, then opens that folder when it finishes. A shortcut is left inside it that you can move wherever you like, such as your desktop.
- After Calculate UB the UB Matrix dock shows how far each peak sits from your UB and whether each pair of peaks is at the angle its indices imply, so a mis-indexed peak is flagged, and Refine Lattice now respects the crystal system. The scattering-plane panel names the zone axis, the c* elevation and the a* azimuth, selecting a sample moves your UB onto its lattice, training grades reflections that lie in your mount's plane, and a locked plane runs at exactly its kappa from the GUI as from the API.
- The instrument dock shows both sample goniometer arcs, sgl and sgu: they are solved from Q and HKL, can be typed in and scanned in angle mode, and a saved session's or old scan folder's χ loads as sgl. Take Position now records the whole stage with the ψ and κ corrections in force, so changing a correction later does not move a recorded peak; older peaks are marked legacy and fit as before.
- The launcher menu now has an Uninstall option, so removing TAVI no longer means finding the uninstaller you downloaded months ago. It lists exactly what will be deleted, including your saved scan results, asks again if there are any, and leaves anything else you have put in the folder where it is.

### Quality of life

- The Windows installer no longer needs Visual Studio or the Microsoft MPI SDK. The C compiler is installed together with everything else, and the installer compiles and runs a test instrument before it finishes so a broken compiler is caught at install time, not at your first scan.
- A macOS and Linux installer script, with an uninstaller, is attached to the release beside the Windows installer, as it has been since v1.3.0. It is provisional: it has not yet been run on either platform, and its header says what to do when it fails.
- The macOS and Linux installer now compiles and runs a small test instrument with two MPI processes before it finishes, so a missing compiler or a broken MPI setup stops the install with the reason and a log, instead of failing at your first scan. Like the rest of that script, this check has not yet been run on either platform.
- A double-click support recorder collects a failed Monte Carlo run, its frozen instrument settings and diagnostic logs for offline troubleshooting, including failures before the application opens.

### Bug fixes

- The installer no longer stops with "Cannot uninstall shiboken6" or starts TAVI with a Qt DLL error afterwards. Every Python package now comes from the same conda-forge channel, an existing environment is rebuilt instead of patched, and the installer checks that the GUI toolkit loads before it finishes.
- Starting TAVI now always uses the Python and McStas that belong to that installation. Where a machine carried a second installation under the same name, a normal start could take the program from one and the simulation engine from the other, and every neutron simulation then failed while the analytic engine carried on working. A separate repair tool fixes machines already installed with an earlier version, without reinstalling.
- Simulations on Linux and macOS computers with fewer than 30 cores no longer fail out of the box: the number of MPI processes per point now starts at 4. It is set from the new Config menu and remembered on this computer; on a machine with fewer than 4 physical cores, lower it there.
- Out-of-plane Q and HKL points are now reached the way a real sample stage reaches them: a turntable carrying two crossed arcs, with the arcs' travel enforced where a source documents it (PUMA and IN12 ±20°, PANDA ±15°; IN8 unlimited) and a refusal naming the arc, the angle it needs and its travel when a point is out of reach. The simulation no longer mounts the crystal with the inverse rotation: until now a crystal oriented 23° one way was simulated 23° the other way.
- Calculate UB now gives the right crystal orientation on IN8, IN12 and PANDA, where it came out turned 180° and sent HKL moves after a fit to the wrong setting (PUMA was not affected). Saved peaks load unchanged and fit correctly, and a UB matrix saved before this fix loads as it was saved: on IN8, IN12 and PANDA the message center says it may still be turned and Calculate UB refits it.

## v1.3.0 — 2026-09-14

**Read this first.** Release 1.3 adds a fast analytic scan engine that returns an approximate result in milliseconds per point, for a quick check before committing to the full neutron simulation. IN12 (ILL) and PANDA (MLZ) join PUMA and IN8 as selectable instruments, each with a model-status document recording what is verified and what remains approximated. A reciprocal-space panel draws the scattering triangle, the lattice points and the instrument's reachable region for the current sample and settings, updating as you change them. TAVI can now be driven from outside the window through a local API server, with an API panel in the GUI and a user guide describing every request.

### Major features

- Scans can now run on a fast analytic engine instead of the full neutron simulation, giving a fast approximate result for the supported sample models in milliseconds per point instead of seconds to minutes. Use it for a quick check before committing to the real simulation, not as a substitute for it.
- IN12 (ILL) and PANDA (MLZ) join PUMA and IN8 as selectable instruments, PANDA in its documented pre-shutdown configuration; each instrument's model-status document records what is verified and what remains approximated.
- A reciprocal-space panel draws the scattering triangle, the lattice points and the instrument's reachable region for the current sample and settings, and updates as you change them, in the style of vTAS.
- TAVI can now be driven from outside the window: a local API server accepts scan, validation and instrument requests from scripts or other programs, with an API panel in the GUI to start it and watch it, and a user guide describing every request.

### Minor features

- The sample loaded for a scan can now be chosen as part of a remote API request, the same way it is chosen in the GUI.
- A standalone dispersion viewer window plots the phonon dispersion of any sample that has a dispersion map, such as the new lead sample, along a chosen crystal direction, with an optional comparison overlay, without running a scan.
- A Fitting dock fits a peak in your scan data and moves a motor to its centre, maximum or centre-of-mass position, with one click to undo the move.
- A lead sample with a three-branch phonon dispersion from a DFT calculation by Rolf Heid (KIT) is available in the sample library alongside the simplified samples. Its dispersion map is generated on your machine by the installer (or by hand with `tools\make_pb_assets.py`); until then the sample is listed but a run with it fails to load.
- Each bending direction of a crystal can now be set independently to auto-focus, held at a fixed radius, or driven by a scan, and the analyser's second focusing axis is a real setting rather than a hidden fixed value.
- A Resolution calculator under the Utilities menu shows the instrument's theoretical momentum and energy resolution at any reciprocal-lattice point and energy transfer you type in, without running a scan.
- A scan-time benchmark under the Utilities menu measures your computer's simulation speed and uses it for more accurate time estimates before you launch a scan, shown as overhead and neutron rate.
- A configurable synthetic nuisance background, with environment, instrument and sample contributions, can be added on top of the simulated counts from a new dialog; it is a plausible background, not a prediction of a real facility's. It is off by default, so existing scans look exactly as before until you turn it on.
- IN8 gains the collimator slot between source and monochromator that ILL documents, alongside the three slots it already had; it is open by default, so existing IN8 settings run as before.

### Quality of life

- A scan request too large for the configured neutron budget is turned down immediately, rather than after the program has worked out which of its points are reachable.
- Simulations that use a phonon dispersion sample start noticeably faster: the dispersion data loads in a few seconds instead of up to half a minute.
- You can request more neutrons per point and per queued job than before, for scans that need extra statistics.

### Bug fixes

- An API scan or validation request with a mistyped or misplaced setting is refused immediately with a message naming the field, instead of being accepted and silently doing something unintended.
- Submitting a scan or validation request through the remote API no longer depends on whatever is sitting in the GUI's scan boxes, and a scan already queued or running is no longer affected by later changes in the GUI.
- Values TAVI writes into the number boxes itself, after a goto-CEN, a remote API write or a derived recalculation, no longer show up highlighted as unconfirmed edits. Only values you typed and have not yet applied are highlighted.
- Editing an energy or wavevector now moves the monochromator and analyser onto the branch the selected instrument actually uses, and a scan submitted through the API or started from fresh defaults on IN8, IN12 or PANDA is no longer refused or driven on the wrong side.
- Scanning a crystal's angle through its zero-degree position no longer crashes the run. At that position an auto-focused crystal is treated as unbent, as if pointed straight at the beam with no focusing; a radius you hold yourself stays as you set it.
- A scan that passes through an instrument's direct-beam position (a crystal at exactly zero degrees) no longer crashes or shows a made-up energy transfer for that point. The point is marked as direct transmission and the values that cannot be known are left blank.
- An analyser focusing axis that the crystal's design permanently fixes (such as the vertical focus on PANDA or IN12) is now refused if you try to scan it, instead of silently letting the scan override it.
- Asking for an energy transfer larger than the neutron beam can supply is refused with a clear message instead of silently running a scan with invalid motor angles.
- IN8's monochromator angle range now matches the range ILL currently publishes, which is narrower at both ends than before (11 to 90 degrees instead of -40 to 110).
- Entering or sending an invalid number, such as infinite or not-a-number, for a crystal's bending radius is refused with a clear error instead of being accepted and producing a broken simulation.
- Choosing an option for an instrument's optional module (such as a beam-focusing mirror) that is not one of the supported choices is now rejected instead of silently building an instrument that does not match what you asked for. Changing only some module options over the API no longer crashes the run.
- The default neutron source now samples the Maxwellian spectrum it documents: its energy distribution was too cold, peaking as intended but with too few neutrons above the peak. Every instrument is affected, and counts at a given setting are lower than in 1.2 (about a quarter lower in the IN8 reference scan), so intensities from the two versions are not directly comparable.
- IN8's Cu(200) monochromator now carries its documented anisotropic mosaic (25 arcminutes horizontal, 10 vertical) instead of a single 25 arcminute value, which changes its vertical resolution and throughput.
- Opening a collimator to its widest, unrestricted setting now genuinely removes it from the beam path, instead of leaving its housing in place to absorb some neutrons.
- Updating one of an instrument's collimation settings over the API no longer clears every other collimation slot you did not mention.
- Starting a run after changing only some of an instrument's beam-defining slits no longer fails; the slits you did not touch keep their default values.
- A scan's recorded incident and final energies now always match the crystal angles the instrument used for that point, whichever energy you chose to fix.
- Typing a scan only into the second scan-command box now shows the correct number of points in the preview, matching what actually runs, instead of zero.
- Setting two bending radii of the monochromator in the same request no longer silently loses one of the values, whichever order you send them in.

