# Handoff — remote install failure, spaced Windows profile

> **Status:** live

Basic McStas runtime verified; remote TAVI failure still unconfirmed.
An actual-GUI recorder is now available; see §10 before sending anything.
**Date:** 2026-09-17
**Workstream:** installer v1.3.0 build 4 / remote user support

---

## 1. Situation

A user (Windows 11, `DESKTOP-ELV9C81`, profile `C:\Users\Mallika Boddapati`) installed
TAVI v1.3.0. The GUI launched and the deterministic engine worked, but every McStas
simulation failed. Reported symptom, verbatim as relayed: *"errno 2 no such file or
directory, simulation did not create a data folder."*

Diagnosis was remote, by log files, with no access to the machine.

---

## 2. Root cause found and fixed — spaces in the install path

conda-forge McStas 3.7.1 ships launchers that expand `%BINDIR%` **unquoted**:

```bat
@REM Isn't windows a lovely place???
@set BINDIR=%~dp0
@python -u %BINDIR%\..\share\mcstas\tools\Python\mcrun\mcrun.py %*
```

With a profile containing a space, `mcrun.bat` hands Python `C:\Users\Mallika` as the
script to run. First evidence, from the installer's own compile gate on her machine:

```
python: can't open file 'C:\\Users\\Mallika': [Errno 2] No such file or directory
```

McStas could not run at all on that machine, from the first install onward. **Every**
`.bat` in `<env>\bin` has the same defect (`mcplot`, `mcdisplay` ×7, `mcgui`, `mcdoc`,
`mctest`, `mcstasenv`). This is an upstream McStas bug. We routed around it; it is
not fixed at source.

**Fix shipped:** installer build 4 (`INSTALLER_VERSION=v1.3.0-4`) resolves a single
`TAVI_BASE` before anything else. When `%USERPROFILE%` contains a space, the source,
the environment, micromamba and the compile gate all move to `%SystemDrive%\TAVI-Data`.
`%TEMP%` is checked separately. The uninstaller mirrors the same resolution — it
previously hardcoded `%USERPROFILE%` in six places and would have removed nothing.

---

## 3. Verified state on the user's machine (2026-09-17, doctor report)

```
INSTALLER_VERSION = v1.3.0-4      COMPILER = gcc_win-64      PB_MAP = ok
RELOCATED         = yes           TAVI_BASE = C:\TAVI-Data
INSTALL_DIR       = C:\TAVI-Data\TAVI
ENV_PREFIX        = C:\TAVI-Data\mamba\envs\tavi
[OK] No overriding per-user McStas config.
   detect_mcstas()           = ('...\envs\tavi\bin', '...\envs\tavi\share\mcstas\resources')
   resolve_mpi_launcher_argv = ['...\envs\tavi\Library\bin\mpiexec.EXE']
   shutil.which('mpiexec')   = ...\Library\bin\mpiexec.EXE
   DEFAULT_MPI_COUNT         = 30
[OK] serial run passed
[OK] 2-rank MPI run passed
[OK] 30-rank MPI run passed
[OK] direct 30-rank launch passed
```

All four produced real detector output, and the MPI runs reported
`running on 30 nodes (master is 'DESKTOP-ELV9C81', MPI version 2.0)`.

These checks verify the compiler, resource tree, environment paths, MPI at both
2 and 30 ranks, and direct launch of the example binary. They do **not** test
TAVI's generated instrument or its first-point McStasScript `backengine()` call.
Do not infer that every McStas-related failure has been eliminated.

---

## 4. What is still broken

TAVI's GUI still fails to run a McStas point on that machine, with the same
`[Errno 2] No such file or directory` and no data folder. The failing layer is
not yet known: first-point generation/compilation/launch and result loading
remain candidates as well as the controller and plugin code.

**The error text has never been captured.** [TAVI_PySide6.py:9526](../TAVI_PySide6.py#L9526)
formats it as `Simulation failed: {e}`; for a `FileNotFoundError` that string contains
the path that could not be opened, which names the fault outright. Three requests for
it produced paraphrases only. Do not ask a fourth time — capture it mechanically.

---

## 5. Earlier proposal — headless probe (superseded by §10)

Write a script that drives TAVI's own scan path with no Qt, run it on her machine via
the doctor or the TAVI shell, and print the full traceback plus `execution_info`.
This closes the loop without depending on anyone copying console text.

API surface, verified against source:

- `instruments/builtin.py` performs registration; `main()` calls it. **The probe must
  call it first** or the registry is empty.
- `instruments.registry.get_instrument("puma")` → plugin.
- Plugin methods ([instruments/puma/plugin.py:320](../instruments/puma/plugin.py#L320)):
  - `default_state()` → `PUMA_Instrument`
  - `scan_config(base_state, gui_values, sample_key, diagnostic_settings, sample_mount)`
    — `gui_values` needs `modules`, `collimation`, `slits_mm`, `K_fixed`, `source_type`,
    `source_dE`, `rhm`/`rvm`/`rha`/`rva`, `fixed_E`, `monocris`, `anacris`
  - `build(config, diagnostic_mode, diagnostic_settings, number_neutrons)`
  - `compute_snapshot(scan_item, scan_index, scan_mode, config, vals, data_folder, ...)`
  - `run_point(instrument, snapshot, output_folder, number_neutrons, execution_state, mpi_count)`
- `RunExecutionState` is in [instruments/contract.py](../instruments/contract.py);
  `DEFAULT_MPI_COUNT = 30` at line 44.
- The run itself is [instruments/tas_runtime.py](../instruments/tas_runtime.py):
  `run_tas_point` (line 1323), `_run_point_direct` (line 1282).

If the probe fails, the traceback is the answer. If it passes, the fault is above the
plugin layer — in `TAVIController`, the prep-thread pipeline, or result loading — and
the next probe drives the GUI offscreen (`QT_QPA_PLATFORM=offscreen`).

Cheaper alternative if someone is at the machine: Launcher → **[4] Open TAVI shell** →
`python TAVI_PySide6.py` → run one point → copy the console.

---

## 6. Files changed (uncommitted, working tree, `main` otherwise clean)

```
 M installer/WINDOWS-install-TAVI-v1.3.0.bat   build 4: TAVI_BASE space-safe resolution
 M installer/WINDOWS-uninstall-TAVI.bat        mirrors the same resolution
?? installer/TAVI-Doctor.bat                   new diagnostic, standalone
```

`TAVI-Doctor.bat` is a double-click diagnostic that changes nothing. It reports paths,
the install record, stray installs, mcrun/mpiexec locations, the compiler config, what
`detect_mcstas()`/`resolve_mpi_launcher_argv()` return with `MCSTAS` set exactly as
`run-tavi.bat` sets it, then compiles and runs PSI_DMC four ways (serial, `--mpi=2`,
`--mpi=30`, direct `mpiexec -np 30`). It writes a full log plus a ~20-line summary and
opens the summary in Notepad. `/quiet` suppresses Notepad and the prompt.

**Every MPI test must keep its `-c`.** Without it mcrun reuses the serial binary, every
rank believes it is the master, and the run dies in a storm of
`unable to create directory (mcuse_dir)` — a fault in the test, not the machine. That
mistake was shipped once and cost a round trip.

Verification run this session: `installer/` scripts pass a goto/label integrity check
and a path-resolution check across clean, spaced-profile and spaced-`%TEMP%` cases
(scratchpad scripts `check_labels.py`, `test_installer_paths.py`); the doctor runs
green end to end locally.

---

## 7. Defects found, not fixed

1. **Upstream McStas:** unquoted `%BINDIR%` in every `.bat` in `<env>\bin`. Breaks any
   Windows user with a space in their profile. Deserves an upstream issue; one
   character per file.
2. **[tavi/mcstas_config.py](../tavi/mcstas_config.py)** — `_find_mpiexec_near_mcrun()`
   searches the mcrun directory (`<env>\bin`), but conda ships `mpiexec.exe` in
   `<env>\Library\bin`. That lookup never fires; resolution falls through to
   `shutil.which`, i.e. to PATH. Where PATH lacks it, `_prefer_direct_mpi_binary`
   returns the bare string `mpiexec`.
3. **[tavi/mcstas_config.py:515](../tavi/mcstas_config.py#L515)** — `configure_mcstasscript()`
   runs at import and rewrites `configuration.yaml` inside the mcstasscript package on
   **every launch**. conda hardlinks that file into the package cache, so every TAVI
   start invalidates the cache entry. That is the source of the alarming
   `libmamba Invalid package cache file ... mcstasscript-0.0.9x` warning on any
   reinstall. Harmless — mamba re-extracts — but it frightens users. Fix as build 3
   fixed `mccode_config.json`: unlink before write.
4. **Installer gate covers 2 MPI ranks; production uses 30.** Already on the board for
   1.3.1 as a Linux issue; it is a coverage gap on every platform.
5. **`detect_mcstas()` Strategy 0** pairs an `MCSTAS` env-var resources path with a
   conda-env `mcrun` without checking they are the same installation. Observed on the
   dev box producing McStas 3.6.14 resources with a 3.7.1 mcrun when `MCSTAS` was
   unset. `run-tavi.bat` always sets it, so production is unaffected.

---

## 8. Ruled out — do not re-tread

| Hypothesis | Verdict |
|---|---|
| Installer build 1 (warn-only Visual Studio check, no gate) | No. Her install is build 4 with `COMPILER=gcc_win-64`. |
| `libmamba Invalid package cache file` warning | Benign. Caused by §7.3, self-heals on re-extract. |
| Missing C compiler / Visual Studio | No. GCC compiles and runs; the VS activation noise in every log is inert. |
| `DEFAULT_MPI_COUNT = 30` too high for her machine | No. 30 ranks verified working there. |
| `mpiexec` not resolvable | No. Absolute path resolved, direct launch verified. |
| Stale per-user McStas config overriding the compiler | No. Absent. |
| Spaces anywhere in the McStas pipeline | Eliminated by relocation and verified space-free. |

The Visual Studio `cannot find the path specified` lines fill most of every log. They
are the `vs2022_win-64` activation hook on a machine without Visual Studio, documented
inert in `installer/TAVI_Windows_Installer_Uninstaller_Design_Document.md` §16. Ignore
them; read only the `[OK]`/`[PROBLEM]` lines and the last line of each failed command.

---

## 9. Open items

- Commit and PR the three installer files (sized T2: release artifact, destructive
  actions; the T2 seats were skipped on the operator's explicit instruction).
- Changelog fragment for the space-safe install — `changelog.d/` exists, this is
  user-facing.
- The headless probe in §5, and the answer it produces.
- Upstream McStas issue for §7.1.
- §7.2, §7.3, §7.4, §7.5.
- `WIP.md` board entry for this workstream.

---

## 10. One-transfer support recorder and local findings (2026-09-17)

**Operator constraint:** the diagnostic must travel remotely to a laptop and
then to the affected computer by USB. There is ONE diagnostic transfer; do not
ask for another probe with changed parameters if the first hypothesis fails.

The replacement for §5 is `tools/support/Record-TAVI.bat` plus
`tools/support/tavi_record.py` and their README, distributed together in a ZIP.
The batch file activates the existing installation's exact environment prefix.
The recorder launches the installed GUI and records the user's actual failing
run: command lines, child output/return codes, caught Python exceptions in
worker threads, frozen launch settings, execution metadata, environment/package
inventory, selected saved configs, launchers/shortcuts and generated instrument
files. A supervisor saves a ZIP even if the GUI cannot import or crashes; the
batch bootstrap log survives failed environment activation. Return the whole
Reports folder. It does not patch TAVI; normal GUI config/output writes still
occur. Close other TAVI instances first, reproduce once, then close this GUI.

**Confirmed locally, not yet confirmed as the remote cause:** McStasScript
concatenates the output directory after `-d` without quoting it in
`helper/managed_mcrun.py:269-272`. The actual offscreen GUI Run button with PUMA,
1000 neutrons and a space-free save folder compiled and ran on 30 MPI ranks.
Changing only the save-folder name to `folder with spaces`, with first-point
compilation forced by clearing the local test's reuse cache, failed with
`OSError: No such instrument file: "with"`, then `Simulation did not create data
folder`. The recorder captured the exact command, raw subprocess error and
the controller's caught exception. Relocating the installation does not protect
against a spaced save-folder name. No production fix has been applied.

Validation: 5 focused recorder tests passed in 1.73 s (caught worker exception,
raw failed command output including `check=True`, archive after startup failure,
abrupt exit and timeout). The earlier real offscreen GUI success/failure test
plus the initial 3 recorder checks passed together in 8.09 s.
The actual batch launcher was also run from a spaced package path against a
deliberately failing installed entrypoint, then against a missing environment:
both retained the required report. Local GUI compilation used the development
MSVC environment; it does not validate the remote GCC instrument build.

Next: inspect the returned recorder report before attributing the remote failure
to the output-path bug or changing production code. The original installer,
uninstaller and old Doctor edits remain separate outstanding work.
