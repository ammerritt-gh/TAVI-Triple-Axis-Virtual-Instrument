# Changelog

Fragments for the next release live in `changelog.d`; see `changelog.d\README.md` for the format.

## v1.3.0 — 2026-09-14

**Read this first.** Release 1.3 adds a fast analytic scan engine that returns an approximate result in milliseconds per point, for a quick check before committing to the full neutron simulation. IN12 (ILL) and PANDA (MLZ) join PUMA and IN8 as selectable instruments, each with a model-status document recording what is verified and what remains approximated. A reciprocal-space panel draws the scattering triangle, the lattice points and the instrument's reachable region for the current sample and settings, updating as you change them. TAVI can now be driven from outside the window through a local API server, with an API panel in the GUI and a user guide describing every request.

### Major features

- Scans can now run on a fast analytic engine instead of the full neutron simulation, giving a fast approximate result for the supported sample models in milliseconds per point instead of seconds to minutes. Use it for a quick check before committing to the real simulation, not as a substitute for it.
- IN12 (ILL) and PANDA (MLZ) join PUMA and IN8 as selectable instruments, PANDA in its documented pre-shutdown configuration; each instrument's model-status document records what is verified and what remains approximated.
- A reciprocal-space panel draws the scattering triangle, the lattice points and the instrument's reachable region for the current sample and settings, and updates as you change them, in the style of vTAS.
- TAVI can now be driven from outside the window: a local API server accepts scan, validation and instrument requests from scripts or other programs, with an API panel in the GUI to start it and watch it, and a user guide describing every request.

### Minor features

- The sample loaded for a scan can now be chosen as part of a remote API request, the same way it is chosen in the GUI.
- A standalone dispersion viewer window plots the phonon dispersion of any sample that ships with a dispersion map, such as the new lead sample, along a chosen crystal direction, with an optional comparison overlay, without running a scan.
- A Fitting dock fits a peak in your scan data and moves a motor to its centre, maximum or centre-of-mass position, with one click to undo the move.
- A lead sample with a three-branch phonon dispersion from a DFT calculation by Rolf Heid (KIT) is available in the sample library alongside the simplified samples.
- Each bending direction of a crystal can now be set independently to auto-focus, held at a fixed radius, or driven by a scan, and the analyser's second focusing axis is a real setting rather than a hidden fixed value.
- A Resolution calculator under the Utilities menu shows the instrument's theoretical momentum and energy resolution at any reciprocal-lattice point and energy transfer you type in, without running a scan.
- A scan-time benchmark under the Utilities menu measures your computer's simulation speed and uses it for more accurate time estimates before you launch a scan, shown as overhead and neutron rate.
- A configurable synthetic nuisance background, with environment, instrument and sample contributions, can be added on top of the simulated counts from a new dialog; it is a plausible background, not a prediction of a real facility's. It is off by default, so existing scans look exactly as before until you turn it on.

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
- IN8's monochromator angle range now matches the range ILL currently publishes, which is narrower at the low-angle end than before.
- Entering or sending an invalid number, such as infinite or not-a-number, for a crystal's bending radius is refused with a clear error instead of being accepted and producing a broken simulation.
- Choosing an option for an instrument's optional module (such as a beam-focusing mirror) that is not one of the supported choices is now rejected instead of silently building an instrument that does not match what you asked for. Changing only some module options over the API no longer crashes the run.
- Opening a collimator to its widest, unrestricted setting now genuinely removes it from the beam path, instead of leaving its housing in place to absorb some neutrons.
- Updating one of an instrument's collimation settings over the API no longer clears every other collimation slot you did not mention.
- Starting a run after changing only some of an instrument's beam-defining slits no longer fails; the slits you did not touch keep their default values.
- A scan's recorded incident and final energies now always match the crystal angles the instrument used for that point, whichever energy you chose to fix.
- Typing a scan only into the second scan-command box now shows the correct number of points in the preview, matching what actually runs, instead of zero.
- Setting two bending radii of the monochromator in the same request no longer silently loses one of the values, whichever order you send them in.

