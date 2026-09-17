# Handoff — remote install failure, spaced Windows profile

> **Status:** live

**Start here: repair the launcher's environment selection next.** The defect is
confirmed locally and is the leading explanation of the remote failure; the
remote cause is not yet proven. No further Doctor run is needed before this fix.
**Date:** 2026-09-17
**Workstream:** installer v1.3.0 build 4 / remote user support

## Fresh-session brief

- **Symptom:** deterministic TAVI works, Monte Carlo fails; the repaired
  installation's Doctor successfully compiles and runs a stock instrument.
- **Leading cause:** the installer relocates the environment for the spaced
  Windows profile, but generated launchers still select it by name (`-n tavi`)
  without the relocated root. Normal launching can reopen the old broken
  environment; the Doctor explicitly selects the new one. Setting `MCSTAS`
  alone does not select Python or mcrun. Evidence and limitations are in §11.
- **Next action:** bind generated launchers to the installer's exact
  `ENV_PREFIX`, including normal Run, Open TAVI shell and repair/update calls.
  Deliver a small launcher repair for the existing installation as well as the
  installer correction; a reinstall is not required. Detailed scope and checks
  are in §12. No launcher fix has been implemented in this session.
- **Do not repeat diagnostics:** another Doctor run tests the already-working
  environment and cannot distinguish this fault. USB transfer is difficult:
  the operator permits ONE diagnostic transfer, not successive revised probes.
  The existing recorder uses `-p` and can mask the suspected fault; hold it.
- **Alternative causes:** missing compiler, broken MPI and a 30-rank launch
  refusal were excluded in the Doctor's environment (§8). Three TAVI sample
  builds passed locally with GCC (§11). Output-path spaces are a separate
  confirmed bug; the operator believes her save folder had none. Memory has no
  positive evidence and is low priority; it is not mathematically ruled out.
- **Repository state at handoff:** `main`, findings through `69b2621b`;
  recorder commits `449e0708` and `3c6506ba`. The build-4 installer/uninstaller
  edits and untracked Doctor in §6 predate this investigation and remain
  uncommitted. Preserve them and review their diff before implementing the fix.
  These local edits are NOT included in a fresh clone just by pulling `main`.

The user requested this write-up so the launcher can be fixed in a later
session. Do not interpret this document as a request to start that release work
or to send a probe now. Begin with this brief, §8, §11 and §12; §5 is historical.

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

## 5. Historical probe API notes — not the next action

The original proposal was an incremental headless probe followed by a GUI probe.
It was superseded by the one-transfer constraint and then by the launcher finding.
Do not execute that sequence. The API notes below are retained only as reference.

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

The generated Open TAVI shell has the same environment-selection defect as Run;
it is not an independent known-good baseline (§11).

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
   unset. The earlier conclusion that setting `MCSTAS` protects production was
   incorrect: it sets the resources path, not the Python/mcrun environment.
   See §11 for the generated launcher's missing environment root.

---

## 8. Ruled out — do not re-tread

**Boundary:** these remote results describe the environment explicitly selected
by the Doctor, not the environment an ordinary shortcut selected. An old
environment may still contain the original faults. The final row corrects an
earlier overbroad exclusion; it is not itself a ruled-out hypothesis.

| Hypothesis | Verdict |
|---|---|
| Installer build 1 (warn-only Visual Studio check, no gate) | No. Her install is build 4 with `COMPILER=gcc_win-64`. |
| `libmamba Invalid package cache file` warning | Benign. Caused by §7.3, self-heals on re-extract. |
| Missing C compiler / Visual Studio | No. GCC compiles and runs; the VS activation noise in every log is inert. |
| MPI refuses 30 ranks on her machine | No. The example ran at 30 ranks. TAVI sample-specific memory demand is a separate question (§11). |
| `mpiexec` not resolvable | No. Absolute path resolved, direct launch verified. |
| Stale per-user McStas config overriding the compiler | No. Absent. |
| Spaces anywhere in the McStas pipeline | Only the Doctor's selected paths were verified. The normal launcher can select the old environment (§11); output-path spaces are a separate defect (§10). |

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
- Establish the normal GUI's selected environment; §5's iterative probe proposal
  is superseded by the one-transfer constraint and §11's recorder caveat.
- Upstream McStas issue for §7.1.
- §7.2, §7.3, §7.4, §7.5.
- The workstream and the separate output-path defect are now pinned in `WIP.md`.

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

Validation: the initial 5 focused recorder tests passed in 1.73 s (caught worker exception,
raw failed command output including `check=True`, archive after startup failure,
abrupt exit and timeout). The earlier real offscreen GUI success/failure test
plus the initial 3 recorder checks passed together in 8.09 s.
The actual batch launcher was also run from a spaced package path against a
deliberately failing installed entrypoint, then against a missing environment:
both retained the required report. Local GUI compilation used the development
MSVC environment; it does not validate the remote GCC instrument build.

Final review added capture of `scan_config`'s internal fields, including hidden
misalignment and the sample mount; its regression failed before the repair.
After the repair, `micromamba run -n tavi-dev python -m pytest tests -q -ra`
passed: **1267 passed, 746 warnings in 111.66 s**, no skips (115.3 s with
activation, within the 120 s process-tree timeout). The final support test count
is 6. The follow-up review found no further defect. Execution stayed direct
because this was a coupled diagnostic measurement loop; critic/reviewer used
fresh fallback agents after the Claude launcher failed, and the PA diff review
was clean. T1 required no panel/external-reader seat. Goals body and Inbox were
empty; this work adds support for the existing Windows operator workflow.

The original installer, uninstaller and old Doctor edits remain separate
outstanding work. The later investigation below changes the hypothesis ranking
and exposes a limitation of the recorder's explicit environment selection.

## 11. Alternative hypotheses and launcher mismatch (2026-09-17)

**Operator correction:** the affected user's save folder probably did not contain
spaces. Keep the reproduced output-path defect pinned independently; do not
attribute this remote failure to it without evidence.

### Leading candidate: normal launcher reopens the old environment

The build-4 installer sets `MAMBA_ROOT_PREFIX=C:\TAVI-Data\mamba` inside
`setlocal`. Its generated `run-tavi.bat` template (base64 at installer line 486)
sets `MCSTAS` to the new resources, but launches with:

```bat
"__MICROMAMBA_EXE__" run -n __ENV_NAME__ python TAVI_PySide6.py
```

It neither sets `MAMBA_ROOT_PREFIX` nor passes `-r` or an exact `-p` prefix.
The generated menu's Open TAVI shell has the same omission. The installer does
not persist its root via `setx` or shell initialization. The standalone Doctor,
in contrast, explicitly sets the relocated root before its tests.

**Locally reproduced mechanism:** remove inherited `MAMBA_*` and `CONDA_*`
variables, copy micromamba 2.5.0 to an unrelated space-free directory, and run
that executable with `--no-rc info --json`. Its base remains
`C:\Users\AMM\AppData\Roaming\mamba`. From that relocated executable,
`--no-rc run -n tavi where.exe python` selects the original profile's
`...\mamba\envs\tavi\python.exe`. Merely moving micromamba does not relocate
its default environment root. Both checks exited 0; each had a 20 s timeout.

If her earlier profile installation remains, a normal double-click can therefore
load source/resources from `C:\TAVI-Data` but Python and mcrun from
`C:\Users\Mallika Boddapati\...`. `detect_mcstas()` explicitly permits this
combination: `_probe_conda_env()` uses `sys.prefix` (lines 337-340), then
Strategy 0 returns that mcrun with the separately supplied resources (421-424).
This reintroduces the known unquoted-mcrun-script failure while deterministic
simulation still works and the correctly rooted Doctor passes.

**Scope of conclusion:** the launcher defect and local selection mechanism are
confirmed. Her actual normal-launch `sys.executable`, inherited root, installed
launcher contents and remaining old environment are not captured. A persistent
correct root would avoid this failure. A launch directly from the installer
could also inherit the correct temporary root. Do not call this a confirmed
remote diagnosis yet. A stale shortcut selecting an old source tree is another
possible variation, also unconfirmed.

### Other hypotheses checked

| Candidate | Evidence and current weight |
|---|---|
| GCC cannot compile TAVI's custom instrument | Reduced: locally compiled PUMA with Al Bragg, Al Phonon DFT and Pb Phonon DFT using cached GCC 16.2.0 and installer-style flags. All initialized, ran 1000 neutrons on 2 MPI ranks and wrote `detector.dat`. This covers these components, not every instrument/module combination or her exact environment. |
| Pb sample exhausts memory at 30 ranks | Conditional, not ruled out by the Doctor. The Pb grid has 3,090,903 rows; each rank parses its own full file into a doubling-capacity double table before building its grid. The text buffer and numeric table coexist during parsing. This can require hundreds of MB per rank, unlike PSI_DMC. No memory-exhaustion failure has been observed remotely or reproduced locally. |
| Missing/unreadable sample assets | Conditional. `Phonon_DFT` exits during initialization if a named reflection or dispersion file cannot be read. The install record says `PB_MAP=ok`, reducing the missing-map hypothesis for the repaired tree, but it does not establish which source tree the GUI opens. Shipped Al/Pb samples use LAZ files, so CIF conversion is not their normal path. |
| Generated binary blocked or component directory unwritable | No positive evidence. Doctor tests its own example and directory, so it does not prove these TAVI-specific operations succeed. Rank below the confirmed launcher discrepancy. |

GCC validation command: `python %TEMP%\tavi-support-checks.py
output\install-diagnosis\test_gcc.py -s` (scratch scripts, not routine suite).
Final result: **3 passed in 17.72 s**, 19.5 s including activation under a
120 s process-tree timeout. Used the existing development Python/McStas/MPI
with a separate cached GCC environment and per-run `--override-config`; installed
compiler configs were not changed. Initial construction-only defaults lacked
runtime parameter values, then supplied zero source energy; these test setup
errors were corrected before the successful run. Detector counts were zero at
this tiny arbitrary-angle check: this establishes compilation, initialization,
execution and output, not scientific intensity correctness.

### Consequence for the one-transfer recorder

`Record-TAVI.bat` explicitly selects the repaired environment with `-p`.
**It can therefore mask the normal launcher's missing-root defect.** A successful
recorded run would not clear normal launching. Its launcher/old-install inventory
is still useful, but its active environment describes the recorder's choice.
Do not spend the single transfer on the assumption that it reproduces the normal
shortcut's environment. No revised remote probe has been requested or sent in
this investigation. Decide the smallest launcher correction or capture of normal
launch selection before using that transfer; installer changes remain a separate
release slice.

## 12. Later launcher repair: scope and acceptance

**Recommendation communicated to the operator:** confidence is sufficient to
repair the confirmed launcher defect first, without another Doctor or recorder
run. The operator also considers memory unlikely. Verification of her usual
Monte Carlo run after the launcher repair is the remaining remote acceptance,
not a request for another diagnostic package.

### Where the fix belongs

The authoritative generator is
`installer/WINDOWS-install-TAVI-v1.3.0.bat`, not a generated local `run-tavi.bat`.
At the investigated working-tree revision, `ENV_PREFIX` is resolved at line 57;
three base64 templates and their placeholder replacements are at lines 486-488:

| Generated surface | Required coverage |
|---|---|
| `RUN_SCRIPT` / `run-tavi.bat` | The Python GUI launch must select the exact installed environment. |
| `UPDATE_SCRIPT` / repair script | Every micromamba call must select that same environment, including git and import checks. Preserve the existing pinned-release behavior. |
| `LAUNCHER_SCRIPT` / menu | Open TAVI shell must select it too; Run and Update must call the corrected scripts. |

Prefer the existing resolved `ENV_PREFIX` as a quoted `-p` argument. For example,
the template's GUI command would become:

```bat
"__MICROMAMBA_EXE__" run -p "__ENV_PREFIX__" python TAVI_PySide6.py
```

Add the corresponding placeholder substitution when generating each affected
script. Use resolved installer values, not a hardcoded `C:` drive or user name.
Setting a root locally in each generated script is an alternative, but selecting
the exact prefix directly avoids dependence on inherited root configuration.
Do not use a global `setx` change as the repair. Keep quoted paths, correct working
directories, McStas resource variables and visible errors.

Also provide a narrow way to repair the scripts already installed on the affected
computer: changing the installer alone does not update her existing launchers.
Use the installed paths/record; preserve the old launchers for rollback. Rebuilding
the environment, changing scientific code, changing MPI defaults and repairing
the separate output-path bug are outside this fix. This is future T2 release work;
the current session only records findings.

### Local checks before delivery

1. Reproduce wrong selection with both an old/default `tavi` environment and a
   relocated `tavi` environment present. Start outside the installer/activated
   environment, with no inherited root; also check an explicitly stale root.
2. Execute the actual generated batch scripts after correction. Verify
   `sys.executable`/`sys.prefix` and the detected mcrun/resources all belong to the
   intended installation. Cover the default layout and relocated spaced-profile
   layout; ensure a missing intended prefix fails visibly rather than selecting
   another environment. Decode/check every template and substitution, not just
   the first Run command.
3. Check menu shell and repair/update environment selection without fetching or
   checking out releases merely to test it. A local recorder/stub can verify those
   commands; retain the real GUI launch as a separate integration check.
4. Through the corrected launcher environment, use real offscreen Qt widgets to
   run one small Monte Carlo point in a space-free output folder. Require fresh
   compilation and detector output; deterministic success alone is insufficient.
   Keep existing config isolation, no-window guards and bounded test timeouts.
5. After delivering the small launcher repair, her ordinary shortcut and usual
   Monte Carlo run are the remote check. If it still fails, first verify the
   corrected launcher was actually used; then reassess the lower-ranked causes
   from available evidence. Do not restart the repeated-probe loop.
