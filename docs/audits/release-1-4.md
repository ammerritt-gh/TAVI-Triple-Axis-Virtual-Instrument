# Audit — release 1.4

> **Status:** live
> **Authority:** findings for the release 1.4 review; no application changes are made by this audit

**Audited:** `4efb3eb8` on 2026-10-17, against `v1.3.2`; lanes covered: duplicate authority, recovery, GUI/API agreement, test blind spots and bypassed invariants. Coverage includes full reads of the scan-plan/quantity contracts, GUI layout/base dock/instrument/simulation/fitting controls, process cancellation, Maxwellian component, source integration and its compiled verifier; release-diff and caller tracing of controller/API/persistence, instrument builders, installation/repair, output loading and tests. This is focused release-path coverage, not a claim that every unchanged dependency or every line of the repository was audited. Meter unreadable (usage-history file unavailable); allowance floor waived. Stopped: direct review complete within the operator's file-only scope. Independent external verification was not completed. No board entry, separate repository reproducer, commit or push is part of this run.

The full suite and compiled Maxwellian checks passed, and all four instrument windows were inspected offscreen. The four reproduced findings concern repair, recovery and a scan warning; none alleges a defect in the Maxwellian sampler. Start with repair, whose success message is misleading in the situation it is intended to fix. Existing handoff deferrals are not duplicated below.

**Validation:** in an isolated archive of the audited revision, `micromamba run -n tavi-dev python -m pytest tests -p no:cacheprovider -q -ra --tb=short --basetemp <temporary-root>/pytest-temp` returned **3421 passed, 4 skipped, 1845 warnings**, exit 0: 669.64 seconds pytest time, 675.81 seconds wall, under a 1200-second process-tree timeout. Three skips are stage-specific inability to level the h = l plane; the fourth is the already-recorded unavailable shared documentation checker. Warning categories were inspected: pytest/Matplotlib deprecations, Qt signal disconnects, conversion-domain warnings, and layout/axis warnings. This is not a warning-free run. The isolated tree contained the local Pb dispersion fixture, so that fixture did not silently skip. Earlier targeted runs covered launchers, saved/output versions and source GUI/API integration. Experiments used temporary trees and configuration, with a copied McStasScript package to isolate its package-local writes.

**Compiled source evidence:** `micromamba run -n tavi-dev python tools/verify_source_maxwell_direct.py`, unchanged from the audited revision, returned **PASS**, exit 0, with McStas 3.7.1 and MSVC: 17.9 seconds reported by the verifier, 21.23 seconds wrapper wall. All seven checks passed: 13 profile rows in wavelength and energy against `Source_gen`, absolute totals against analytic integrals, constant ray weights, full-spectrum independence from E0/dE, flat-band support/level/uniformity, invalid-input refusals, and wide-angle sampling per steradian. The deliberately wrong controls failed as intended. The largest absolute-total discrepancy was 1.26 standard deviations; spectral chi-square per compared bin ranged 0.87–1.11. These are checks of the implemented distribution and normalization, not a new calibration of facility fluxes.

**GUI evidence and limits:** real offscreen Qt controllers were rendered for PUMA, IN8, IN12 and PANDA at 1108 × 851, including each source panel; PUMA was also inspected at 2560 × 1392 with flat-band controls and a fitted synthetic scan. All 11 images were inspected. Rendering used Fusion with the platform palette because the native Windows 11 style does not draw readable text in this offscreen setup. This verifies those widget paths and layouts, not hands-on acceptance on the physical displays. A fresh downloaded installation, ordinary full-instrument Monte Carlo run through the installed launcher, minimum-supported McStas version and external-consumer migration were not newly established here. The evidence therefore does not certify the release as ready to publish.

## 1. P1 · Repair reports success without restoring deleted program files

- **Observed at:** `4efb3eb8`.
- **Effort:** 1–3 hours; pinned-revision restoration in `installer/launchers/update-tavi.bat` and a repair test using real Git; preserve local configuration and output.
- **Evidence:** `installer/launchers/update-tavi.bat:80–107` performs `git checkout` and dependency imports before reporting success.
  `installer/launchers/run-tavi.bat:40` refuses a missing application entrypoint.
  `tests/test_installer_launchers.py:1550–1601` exercises repair through a successful micromamba stub rather than verifying restoration by Git.
- **Failure:** deleting the tracked `app/TAVI_PySide6.py` from a pinned installation does not make checkout of that same tag fail. Git retains the deletion and exits 0. The repair's import check does not import the application, so healthy dependencies lead to `REPAIR SUCCEEDED` while Run still refuses the installation.
- **Reproduce with:** in a temporary local Git repository, commit a fixture `TAVI_PySide6.py`, tag it `v1.4.0`, clone and check out that tag; delete the cloned entrypoint, then run the repair's `git fetch --tags origin` and `git checkout v1.4.0`. Observed exit 0, checkout output `D TAVI_PySide6.py`, and the file still absent. The probe used the checkout arguments extracted from the current repair script. The full repair batch was not executed: its subsequent success path was checked in source.
- **Remedy boundary:** make the repair's pinned-source restoration actually restore required tracked files, or refuse with an accurate recovery message. Do not remove the installation's local settings or outputs.
- **Verified:** direct Git reproduction and source trace, 2026-10-17; no independent verifier verdict.

## 2. P3 · Fine-step scan warnings report the wrong endpoint

- **Observed at:** `4efb3eb8`.
- **Effort:** 0.5–1 hour; endpoint formatting in the shared scan warning and one fine-step regression.
- **Evidence:** `tavi/utilities.py:110–119` expands scan values without rounding.
  `tavi/utilities.py:156–162` rounds the warning's endpoint to three decimal places.
  `TAVI_PySide6.py:4791–4797` displays the shared note on the GUI command box; `4985–5002` constructs it.
  `TAVI_PySide6.py:8078–8088` includes that note in API scan warnings through the same command-note path used by the GUI.
- **Failure:** the valid command `h 2 2.0005 0.0002` produces points `(2.0, 2.0002, 2.0004)`, but its warning says `Step 0.0002 does not divide 2 to 2.0005; the scan stops at 2.` The warning therefore describes a different endpoint from the accepted plan. Execution keeps the correct precision; this finding concerns the misleading preview/API warning, not incorrect scan points.
- **Reproduce with:** construct a real PUMA controller with Qt offscreen and isolated configuration; call `build_api_launch_state({"scan_command1": "h 2 2.0005 0.0002"})`, `_compile_launch(launch)` and `_scan_command_warnings(launch)`. Inspect the expanded axis and warning. The controller probe produced the three points above and the rounded warning; its assertion that the warning names `2.0004` failed. The pure helper also reproduces this with `scan_stop_note(2, 2.0005, 0.0002)`.
- **Remedy boundary:** format the actual endpoint with sufficient precision in the shared warning. Keep the accepted point expansion and the non-divisible-range warning policy.
- **Verified:** direct offscreen Qt controller reproduction and shared-helper source trace, 2026-10-17; no independent verifier verdict.

## 3. P3 · Invalid diagnostic settings crash startup and leave load-time signals blocked

- **Observed at:** `4efb3eb8`.
- **Effort:** 1–2 hours; saved-record validation and load cleanup in the controller, with an offscreen widget regression.
- **Evidence:** `TAVI_PySide6.py:6503–6537` does not validate the diagnostic-settings container before load.
  `TAVI_PySide6.py:6795–6796` blocks scan-command signals.
  `TAVI_PySide6.py:6935–6941` unpacks the supplied diagnostic settings as a mapping; `6949–6950` only unblocks signals after that succeeds.
  `TAVI_PySide6.py:1453` loads saved parameters during controller construction.
- **Failure:** a parseable schema-5 record with `diagnostic_settings: null` passes the preliminary refusal check and raises `TypeError: 'NoneType' object is not a mapping`. During construction this prevents normal startup. Loading the same record in an existing controller leaves the scan-command signals blocked after the exception.
- **Reproduce with:** in an isolated configuration directory, write `{"in8":{"_schema":5,"diagnostic_settings":null}}` to `parameters.json`, then construct the real IN8 controller with Qt offscreen. For the second path, construct from valid settings first, inject the same null member into a saved record and call `load_parameters(keep_current_on_refusal=True)`; inspect `controller.window.simulation_dock.scan_command_1_edit.signalsBlocked()` after the exception. Both probes failed at line 6941; the latter returned true for blocked signals. Two targeted probes, 6.52 seconds wall, exit 1 as expected. McStasScript was copied into the temporary test tree to isolate its package configuration writes.
- **Remedy boundary:** validate the container before applying the saved record and reliably restore blocked signals on failure. Do not broaden this into a saved-state framework. This requires malformed input; it is not evidence that normal schema-3 migration fails.
- **Verified:** two real offscreen Qt controller reproductions, 2026-10-17; no independent verifier verdict.

## 4. P3 · An installation failure can make the same folder unusable for retry

- **Observed at:** `4efb3eb8`.
- **Effort:** 1–3 hours; partial-install ownership/retry handling in the Windows installer and its failure-injection test.
- **Evidence:** `installer/WINDOWS-install-TAVI-v1.4.0.bat:264–282` refuses a nonempty destination without recognized ownership or the external installing record.
  `installer/WINDOWS-install-TAVI-v1.4.0.bat:456–465` continues when it cannot create the external record directory.
  `installer/WINDOWS-install-TAVI-v1.4.0.bat:707–712` writes the installation marker only late in the successful path.
- **Failure:** when the external installation record cannot be created and installation subsequently fails, the destination contains installer-created files but neither accepted ownership signal. A retry refuses those files as unrelated content rather than resuming or recovering the installation.
- **Reproduce with:** run an unchanged temporary copy of the installer twice with `/dir <temporary-install-folder> /test-fail micromamba`. Set `LOCALAPPDATA` to a temporary regular file, so its `TAVI` subdirectory cannot be created; isolate `USERPROFILE`, `TEMP`, `TMP` and `TAVI_TEST_DESKTOP` in temporary storage too. The first run exited 1 at the injected failure; the second exited 1 at the unrelated-files refusal before reaching that failure. Combined wall time: 3.83 seconds. No download or real installation was performed.
- **Remedy boundary:** retain trustworthy evidence of an installer-owned partial attempt or provide an explicit recovery path. Keep the guard against deleting unrelated directories. A different destination/manual cleanup is currently a workaround; this is an edge case, not an ordinary-install blocker.
- **Verified:** two executions of the unchanged installer in temporary storage, 2026-10-17; no independent verifier verdict.
