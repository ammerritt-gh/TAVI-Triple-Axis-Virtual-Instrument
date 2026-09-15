# TAVI Windows Installer / Uninstaller Design Document

> **Status:** live

_Last updated: 2026-09-15_

This document records the intended design, constraints, failure modes, and regression checks for the TAVI Windows user installer and uninstaller. Its purpose is to prevent future installer updates from reintroducing the failures encountered during the May 2026 rewrite/debug cycle.

The installer target is a normal Windows user machine, not a developer checkout. The installer must be robust for users who do not already have a configured conda/micromamba environment, do not know McStas internals, and should not need to edit paths manually.

---

## 1. Scope

### Installer responsibilities

The Windows installer is responsible for:

1. Explaining what it will do before making changes.
2. Asking for confirmation before installation proceeds.
3. Verifying or warning about external build/runtime prerequisites:
   - Visual Studio C++ compiler bootstrap.
   - Microsoft MPI SDK.

   > **Superseded 2026-09-15 (build 3):** there is no external prerequisite
   > any more. The compiler (conda-forge GCC) ships inside the `tavi`
   > environment and is configured and compile-checked by the installer
   > itself. See "McStas compiler (build 3)" below.
4. Installing or reusing micromamba without modifying global shell startup behavior.
5. Creating or updating the `tavi` micromamba environment.
6. Installing the required McStas package set.
7. Installing/updating the TAVI source tree under the user profile.
8. Configuring McStas/McStasScript paths.
9. Creating launcher scripts:
   - `run-tavi.bat`
   - `update-tavi.bat`
   - `TAVI-Launcher.bat`
10. Creating a desktop launcher shortcut when possible.
11. Failing early when a required runtime resource is missing.

### Uninstaller responsibilities

The Windows uninstaller is responsible for removing only the user-installed TAVI application:

1. Ask for confirmation.
2. Remove the `tavi` micromamba environment.
3. Remove `%USERPROFILE%\TAVI`.
4. Remove the desktop shortcut.
5. Never remove micromamba itself.
6. Never remove unrelated environments such as `tavi-dev`.

---

## 2. Non-goals

The installer should not:

- Install Visual Studio / Build Tools automatically.
- Install Microsoft MPI SDK automatically.
- Remove or modify unrelated micromamba environments.
- Delete the whole micromamba root.
- Require the user to run `micromamba shell init`.
- Depend on a developer checkout.
- Depend on `tavi-dev`.
- Depend on system-wide conda activation state.
- Assume that Python, Git, or McStas are already installed globally.
- Assume that McStasScript can infer the McStas resource path correctly without validation.

---

## 3. Key paths and names

Current intended defaults:

```bat
set "TAVI_VERSION=main"
set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"

set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"

set "ENV_NAME=tavi"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"
```

Important distinction:

- The **developer** launcher may run from a checkout such as:
  - `C:\Users\AMM\Documents\Github\Science\TAVI`
  - environment: `tavi-dev`
- The **user installer** must run from:
  - `%USERPROFILE%\TAVI`
  - environment: `tavi`

The uninstaller must affect only the user-installed copy, not the developer checkout.

---

## 4. Required user-facing behavior

The installer must begin with a clear explanation and a confirmation prompt.

Minimum required explanation:

- It will check Visual Studio compiler support.
- It will check Microsoft MPI SDK.
- It will install or reuse micromamba.
- It will create/update the `tavi` environment.
- It will install/update TAVI under `%USERPROFILE%\TAVI`.
- It will configure McStas/McStasScript paths.
- It will create launcher scripts.

It must explicitly state:

- It will **not** run `micromamba shell init`.
- It will **not** remove the whole micromamba installation.
- It may remove a broken `cmd.exe` AutoRun hook only if it contains `micromamba` or `mamba`.
- It will ask before recreating the `tavi` environment.
- It will ask before moving aside a broken non-conda environment folder.

Required prompt:

```bat
choice /C YN /M "Continue with TAVI installation"
```

The safe uninstaller must likewise explain what it removes and what it does not remove, then prompt before proceeding.

---

## 5. Batch scripting constraints

The installer must be written in conservative Windows batch style.

### Required

Use:

```bat
@echo off
setlocal DisableDelayedExpansion
```

Reasons:

- Paths may contain parentheses, especially:
  - `C:\Program Files (x86)\...`
- Delayed expansion can corrupt values containing `!`.
- Large parenthesized blocks with generated `echo` commands are fragile.

### Avoid

Do not use large generated launcher blocks like:

```bat
(
  echo ...
  echo ...
  echo ...
) > "%RUN_SCRIPT%"
```

This style is fragile when lines contain:

- parentheses,
- `&&`,
- `%`,
- quoted paths,
- `Program Files (x86)`,
- nested batch syntax.

Observed failures included commands being mangled into fragments such as:

```text
'ho' is not recognized as an internal or external command
'et' is not recognized as an internal or external command
'Step' is not recognized as an internal or external command
'MICROMAMBA_DIRENV_NAME' is not recognized as an internal or external command
'9009' is not recognized as an internal or external command
```

These are not normal package failures. They indicate `cmd.exe` parsing corruption or polluted startup commands.

### Launcher generation

Launcher files may be generated using a safer method such as PowerShell `Set-Content` from a controlled template. If base64 templates are used, the design goal is to avoid fragile batch parser expansion while writing nested batch files.

Any future replacement approach must satisfy:

- no large parenthesized echo blocks,
- no dependence on delayed expansion,
- no unescaped generated `&&`,
- safe with paths containing parentheses,
- safe with empty optional variables.

---

## 6. `cmd.exe` AutoRun constraint

The installer must never run:

```bat
micromamba shell init --shell cmd.exe ...
```

Reason: this can modify the Windows `cmd.exe` AutoRun registry hook. A malformed or stale AutoRun hook can corrupt later batch execution and emit broken command fragments.

The installer may check and remove stale AutoRun hooks only if they clearly contain `mamba` or `micromamba`.

Current intended cleanup:

```bat
reg query "HKCU\Software\Microsoft\Command Processor" /v AutoRun > "%TEMP%\tavi_autorun_hkcu.txt" 2>nul
findstr /i "micromamba mamba" "%TEMP%\tavi_autorun_hkcu.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    reg delete "HKCU\Software\Microsoft\Command Processor" /v AutoRun /f >nul 2>nul
)
```

Do not delete unrelated AutoRun hooks.

---

## 7. Micromamba design

Micromamba should be treated as a standalone executable:

```bat
"%MICROMAMBA_EXE%" run -n %ENV_NAME% ...
```

The installer must not require activation of the environment in the current shell.

The installer must not require:

```bat
conda activate
micromamba activate
micromamba shell init
```

The installer should set:

```bat
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
```

and use the known prefix rather than attempting to infer it from noisy activation output.

The micromamba binary itself must be pinned and verified, not downloaded loose:

```bat
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"
curl -L -o "%MICROMAMBA_EXE%.tmp" "https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
```

Verify the downloaded binary's SHA256 against `EXPECTED_SHA256` before using it; do not run an unverified download. **Not yet implemented (noted 2026-09-12):** the shipping installer defines `EXPECTED_SHA256` but never computes or compares a hash; it runs `micromamba.exe --version` straight after the download. This is a requirement, not a description of current behaviour.

---

## 8. Environment creation/update behavior

The installer must support three cases:

### Case A: no environment exists

Create the environment using pinned core packages.

### Case B: valid `tavi` environment exists

Removed and recreated from the package list, no prompt (decision 2026-09-15: an
environment is a function of its spec and is never repaired in place; the
installer's opening prompt already names the rebuild; micromamba's package
cache makes it a link step).

Detection is `if exist "%ENV_PREFIX%\conda-meta\history"`. The earlier
`micromamba env list | findstr /r /c:"^tavi[ ]"` never matched, because the
listing indents every line; every "existing environment" run before
2026-09-15 reached this case only through the broken-prefix fallback prompt.
Found by the second cold run of build 2, when that fallback had been removed.

### Case C: broken folder exists at target prefix

Micromamba may fail with:

```text
Non-conda folder exists at prefix - aborting.
```

This means the folder exists but is not a valid conda environment.

The installer must detect this before `micromamba create` and ask whether to move it aside.

Detection rule:

- folder exists at `%ENV_PREFIX%`
- but `%ENV_PREFIX%\conda-meta\history` does not exist

Expected behavior:

```text
[WARN] A non-conda or incomplete folder already exists at:
       %ENV_PREFIX%
[INFO] This is the exact condition that causes libmamba's error:
       Non-conda folder exists at prefix - aborting.
Move this broken folder aside and create a fresh environment?
```

If accepted, move to a backup name such as:

```bat
%MAMBA_ROOT_PREFIX%\envs\tavi_broken_%RANDOM%_%RANDOM%
```

Do not delete directly.

---

## 9. Package constraints

The installer should not assume that McStas is present just because `mcstasscript` is present.

The environment must include the McStas package family, pinned consistently to the same version:

```bat
set "MCSTAS_VERSION=3.7.1"

set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git pyside6 mcstasscript"
```

Known issue encountered:

- `McStasScript` was installed.
- `mcstas` packages were installed.
- But TAVI still failed because `Progress_bar.comp` was not visible to McStasScript.
- Therefore installing packages is insufficient; the resource path and specific component must be verified.

Python packages: all from conda-forge, including `pyside6` and `mcstasscript`;
there is no pip step.

Why (2026-09-15): conda-forge matplotlib depends on `pyside6`, which pins
`qt6-main`; the conda `pyside6`/`shiboken6` dist-info has no RECORD so pip can
never uninstall it; `pip install --upgrade PySide6` was a no-op only while
PyPI and conda-forge matched, and failed with `uninstall-no-record-file` on
2026-09-15 when PyPI (6.11.2) was ahead of the solved conda package
(6.11.1); forcing it with `--ignore-installed` loaded PySide6 6.11.2 against
Qt 6.11.1 in `Library\bin` (`DLL load failed while importing QtWidgets`).

The install step ends with a smoke check that instantiates a QApplication
and imports mcstasscript; the generated repair script runs the same check
and never mutates packages.

Future maintainers should consider pinning PySide6 and McStasScript if newer versions introduce regressions. At minimum, the installer must print package versions or make them easy to inspect.

---

## 10. McStas path detection

The installer must not rely on noisy `micromamba run` output to determine the environment prefix.

Bad pattern:

```bat
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python -c "import sys; print(sys.prefix)" > "%TEMP%\tavi_prefix.txt"
set /p ENV_PREFIX=<"%TEMP%\tavi_prefix.txt"
```

This failed because activation scripts emitted unrelated lines before Python output, including:

```text
You seem to have a system wide installation of MSMPI.
```

The installer then treated that text as the environment path and attempted to use:

```text
"You seem to have a system wide installation of MSMPI. "\share\mcstas\resources
```

Correct pattern:

```bat
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
```

Then check known McStas resource layouts:

```bat
set "MCSTAS_RESOURCES=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS_RESOURCES%" set "MCSTAS_RESOURCES=%ENV_PREFIX%\Library\share\mcstas\resources"
```

Then find `mcrun` in known locations:

```bat
set "MCRUN_DIR=%ENV_PREFIX%\Library\bin"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\Scripts"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\bin"
```

The installer should fail early if either is missing.

---

## 11. Required McStas resource validation

The installer must verify the actual component requested by TAVI.

Current TAVI uses:

```python
instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])
```

Therefore the installer must verify:

```bat
dir /s /b "%MCSTAS_RESOURCES%\Progress_bar.comp" > "%TEMP%\tavi_progress.txt" 2>nul
findstr /r "." "%TEMP%\tavi_progress.txt" >nul 2>nul
```

If not found, fail before completing installation:

```text
[ERROR] Progress_bar.comp was not found under:
        %MCSTAS_RESOURCES%
[INFO] McStas is installed, but this package layout/version lacks the component TAVI requests.
```

This check prevents the runtime failure:

```text
NameError: No component named Progress_bar in McStas installation or current work directory.
```

Future TAVI change option:

- Replace `Progress_bar` with `Arm`, or
- Add fallback logic in `instruments/puma/model.py`.

If TAVI stops depending on `Progress_bar`, update this validation check accordingly.

---

## 12. McStasScript configuration

After detecting paths, the installer should persist McStasScript configuration:

```python
import mcstasscript as ms
c = ms.Configurator()
c.set_mcrun_path(r"%MCRUN_DIR%")
c.set_mcstas_path(r"%MCSTAS_RESOURCES%")
```

The launcher should also set runtime environment variables before launching TAVI:

```bat
set "MCSTAS=%MCSTAS_RESOURCES%"
set "MCSTAS_COMPONENT_PATH=%MCSTAS%"
```

This duplication is intentional. It reduces dependence on McStasScript’s persisted config and helps subprocesses inherit a valid McStas resource path.

### Why TAVI configures McStasScript itself

Absorbed 2026-09-12 from the retired `config/TAVI-McStas-Path-Resolution.md`. A developer
checkout run outside the installer's `tavi` environment could not find a standalone McStas:
McStasScript reads its own configuration file rather than searching `PATH`, and the
installer's configuration lives inside the `tavi` environment only. `tavi/mcstas_config.py`
therefore resolves McStas at import time (the `MCSTAS` environment variable first, then
`config/mcstas_config.json`, then search paths, Windows defaults, the conda environment
and `PATH`; the module docstring is the authority) and configures McStasScript before any
instrument is built. `config/mcstas_config.json` is gitignored local state.

---

## 13. TAVI source install/update behavior

The installer must install source into:

```bat
%USERPROFILE%\TAVI
```

Expected cases:

### Case A: no folder

Clone into the folder.

### Case B: folder is a Git repo

Fetch, checkout target branch/version, and pull fast-forward only.

### Case C: folder exists but is not a Git repo

Move it aside rather than copying over it or deleting it.

Expected behavior:

```text
[WARN] %INSTALL_DIR% exists but is not a Git repository.
[INFO] Moving existing folder to: ...
```

Then clone fresh.

The installer must verify after clone/update:

```bat
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" (
    echo [ERROR] TAVI_PySide6.py not found after clone/update.
    exit /b 1
)
```

Future recommended validation:

```bat
if not exist "%INSTALL_DIR%\tavi\mcstas_config.py" (
    echo [ERROR] tavi\mcstas_config.py not found after clone/update.
    exit /b 1
)
```

This would have caught the earlier missing-module failure:

```text
ModuleNotFoundError: No module named 'tavi.mcstas_config'
```

---

## 14. Source control constraints for TAVI

The file:

```text
tavi/mcstas_config.py
```

is application source and must be committed.

It should not be in `.gitignore`.

Reason: `instruments/puma/model.py` imports:

```python
from tavi.mcstas_config import resolve_mpi_launcher_argv
```

If the module is present only in the developer checkout but not pushed, the user install will fail at startup.

Reasonable ignore pattern:

```gitignore
config/mcstas_config.json
```

Recommended repo pattern:

```text
tavi/mcstas_config.py                  commit
config/mcstas_config.example.json      commit
config/mcstas_config.json              ignore
```

---

## 15. `tavi/mcstas_config.py` constraints

The TAVI runtime McStas config helper should support the same Windows env layouts as the installer.

It should check for `mcrun` under:

```text
%ENV_PREFIX%\Library\bin
%ENV_PREFIX%\Scripts
%ENV_PREFIX%\bin
```

It should check resources under:

```text
%ENV_PREFIX%\share\mcstas\resources
%ENV_PREFIX%\Library\share\mcstas\resources
```

It should respect:

```text
MCSTAS
MCSTAS_COMPONENT_PATH
```

when those point to valid resource directories.

It should set those variables before importing/configuring McStasScript where practical.

It should warn clearly if `Progress_bar.comp` or any future required component is missing.

---

## 16. Launcher expectations

The installer must create:

```text
%USERPROFILE%\TAVI\run-tavi.bat
%USERPROFILE%\TAVI\update-tavi.bat
%USERPROFILE%\TAVI\TAVI-Launcher.bat
%USERPROFILE%\Desktop\TAVI Launcher.lnk
```

### `run-tavi.bat`

Required behavior:

1. `cd /d "%INSTALL_DIR%"`
2. Set:
   - `MCSTAS`
   - `MCSTAS_COMPONENT_PATH`
3. Check that `%MCSTAS%` exists.
4. ~~Optionally call Visual Studio `vcvars64.bat` if found. Locate it via `vswhere.exe` (`%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe`), not a hardcoded version path: VS 2026 installs to `...\Microsoft Visual Studio\18\...`, not `...\2026\...`, so a hardcoded year/version segment breaks detection.~~
5. ~~Optionally append Microsoft MPI SDK include/lib paths if found.~~

   > **Superseded 2026-09-15 (build 3):** `run-tavi.bat` no longer bootstraps
   > a compiler at launch time. The environment's own McStas config already
   > points at conda-forge GCC, configured once during install. See "McStas
   > compiler (build 3)" below.
6. Run:

```bat
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python TAVI_PySide6.py
```

7. Pause if TAVI exits with an error.

### `update-tavi.bat`

Required behavior:

1. `git fetch origin`
2. `git checkout %TAVI_VERSION%`
3. `git pull --ff-only origin %TAVI_VERSION%`
4. Check that PySide6 (a `QApplication`) and mcstasscript load; on failure
   say to run the installer again. The script never installs or upgrades
   packages (2026-09-15).
5. Pause and report failures clearly.

### `TAVI-Launcher.bat`

Required menu:

```text
[1] Run TAVI
[2] Update TAVI
[3] Open TAVI folder
[4] Open TAVI shell
[5] Exit
```

The shell option should run a shell inside the `tavi` environment but must not alter global shell startup.

---

### McStas compiler (build 3)

conda-forge's Windows McStas package is configured for `cl.exe` and only
locates an installed Visual Studio; every user previously had to install
Visual Studio Build Tools (and, for MPI, the Microsoft MPI SDK) before
McStas would compile. Spike evidence (2026-09-15, scratch env `tavi-gcc`):
conda-forge `gcc_win-64` (MinGW-w64 GCC 16.2) compiles and runs McStas 3.7.1
instruments, serial and under `mpiexec` (MPI recompile pulls in `msmpi.dll`
from the conda `msmpi` package, which also ships `mpiexec.exe`), including
TAVI's PUMA instrument with its custom components and lattice/phonon files.

The installer adds `gcc_win-64` and `msmpi` to the `tavi` environment's
package list, then overrides five entries in the environment's own copy of
`mccode_config.json` (`<ENV_PREFIX>\share\mcstas\tools\Python\mccodelib\mccode_config.json`),
backing up the package's MSVC original alongside it first:

- `CC`, `MPICC` — the environment's `x86_64-w64-mingw32-gcc.exe`.
- `CFLAGS` — include/lib paths under `${CONDA_PREFIX}` plus
  `-B${CONDA_PREFIX}/Library/x86_64-w64-mingw32/sysroot/usr/lib/`: conda-forge's
  GCC looks for `crt2.o` in `sysroot/usr/lib`, and the package puts it there
  rather than in `sysroot/lib`, so without the `-B` flag linking fails.
- `MPIFLAGS` — `-DUSE_MPI -lmsmpi`.
- `NCRYSTALFLAGS` — rewritten from the package's MSVC syntax
  (`ncrystal-config` output assumes `cl.exe`).

The config is written **inside the environment**, not
`%USERPROFILE%\AppData\mcstas\...` (the per-environment user config McStas
also reads): it dies with the environment, there is exactly one source of
truth to keep in sync with a McStas upgrade, and nothing under `%APPDATA%`
needs cleaning up at uninstall. `vs2022_win-64` (pulled in by `mcstas-core`
via `c-compiler`) still gets installed and only locates MSVC; with GCC
configured it is inert.

The file is **unlinked before it is written**. conda links package files
into an environment as NTFS hardlinks to the package cache, so the
environment's `mccode_config.json`, the cache copy and every other
environment with the same McStas package are one inode. The first build 3
cold run wrote the file in place and thereby rewrote the config of the
operator's `tavi-dev` and `tavi` environments and the cache (found
2026-09-15; restored from the `.conda` archive with
`micromamba package extract`). `Path.unlink()` followed by a fresh write
gives the environment its own file; the backup copy is a real copy too.

Before writing the config, a per-user McStas config for this environment
name (`%USERPROFILE%\AppData\mcstas\<version>_tavi\mccode_config.json`,
which `mcrun` reads ahead of the environment's file) is moved aside with an
`[INFO]` line: a stale one from an earlier McStas setup would silently
override the compiler just configured (external reader, 2026-09-15). If
the move fails and the file is still there, the install stops with
`[ERROR]`: a machine that still has Visual Studio would otherwise pass the
gate through the stale `cl.exe` config and stay silently dependent on it.

The installer then gates the install on a real compile: it copies the
`PSI_DMC` example into a scratch directory under `%TEMP%` and runs
`mcrun -c ... -n 1000 lambda=2.5666`, once `-d serial` and once
`-d mpi --mpi=2`. `PSI_DMC` rather than `PSI_DMC_simple` because its
PowderN sample requests the NCrystal flags, so all five overrides are
exercised. Either failure is `[ERROR]` and stops the install (exit 1): TAVI
runs every simulation point under MPI (`DEFAULT_MPI_COUNT` in
`instruments/contract.py`, no serial fallback), so an install whose MPI
build fails would fail at the first scan instead — the external reader's
P1 on the warn-only first draft. The gate directory
(`%TEMP%\tavi_compile_check`) is left in place after the install; its
`serial.log`/`mpi.log` are the first thing to check if compilation fails
later.

A machine with no Visual Studio was simulated by hiding the environment's
`vswhere.exe`: the `vs2022_win-64` activation prints a few "not recognized"
lines on every `micromamba run` and McStas still compiles and runs (exit 0).
Not yet run on a machine that truly lacks it. A McStas version upgrade should re-check all five
overrides, the `-B` quirk in particular.

---

## 17. Safe uninstaller design

The safe uninstaller must remove only:

```text
%USERPROFILE%\TAVI
tavi environment
%USERPROFILE%\Desktop\TAVI Launcher.lnk
```

It must explicitly not remove:

```text
micromamba itself
tavi-dev
any other environment
```

(the compiler lives inside the `tavi` environment as of build 3, so
removing it is covered by removing the environment; see "McStas compiler
(build 3)" above.)

It must not delete `%USERPROFILE%\AppData\Roaming\mamba` or `%USERPROFILE%\AppData\Local\micromamba`.

If `%USERPROFILE%\TAVI` does not contain `TAVI_PySide6.py`, it should warn and ask before deleting anyway.

This protects against accidental deletion of a wrong folder.

The POSIX uninstaller applies the same must-not-remove list to its own paths; see §25.

---

## 18. Known failure modes and regression tests

### Failure: generated batch corruption

Symptoms:

```text
'ho' is not recognized as an internal or external command
'et' is not recognized as an internal or external command
'Step' is not recognized as an internal or external command
'MICROMAMBA_DIRENV_NAME' is not recognized
```

Regression prevention:

- Do not use large parenthesized echo blocks.
- Do not enable delayed expansion.
- Do not run `micromamba shell init`.
- Remove stale mamba/micromamba AutoRun hooks only when detected.

Test:

1. Run installer from PowerShell.
2. Run installer from `cmd.exe`.
3. Ensure no command fragments appear.

---

### Failure: missing TAVI directory after clone/update

Symptoms:

```text
TAVI_PySide6.py not found
C:\Users\AMM\TAVI does not contain expected files
```

Regression prevention:

- If install dir exists but is not a Git repo, move it aside.
- Clone directly into `%USERPROFILE%\TAVI`.
- Verify `TAVI_PySide6.py`.

Test:

1. Delete `%USERPROFILE%\TAVI`.
2. Run installer.
3. Confirm `TAVI_PySide6.py` exists.
4. Create a dummy non-Git `%USERPROFILE%\TAVI` folder.
5. Rerun installer.
6. Confirm the dummy folder is moved aside and clone succeeds.

---

### Failure: missing `tavi.mcstas_config`

Symptom:

```text
ModuleNotFoundError: No module named 'tavi.mcstas_config'
```

Cause:

- File existed in developer checkout but was not committed/pushed.

Regression prevention:

- Commit `tavi/mcstas_config.py`.
- Verify it exists after clone.

Test:

```powershell
Test-Path C:\Users\AMM\TAVI\tavi\mcstas_config.py
```

---

### Failure: `Progress_bar` not found

Symptom:

```text
NameError: No component named Progress_bar in McStas installation or current work directory.
```

Causes encountered or suspected:

- McStas resource path not configured.
- Wrong McStas resource root.
- McStas installed but required component absent.
- McStasScript pointed at dummy/test resource path only.

Regression prevention:

- Detect resources directly under `%ENV_PREFIX%`.
- Configure McStasScript.
- Set `MCSTAS` and `MCSTAS_COMPONENT_PATH` in launcher.
- Verify `Progress_bar.comp` during installation.

Test:

```powershell
Get-ChildItem C:\Users\AMM\AppData\Roaming\mamba\envs\tavi\share\mcstas\resources -Recurse -Filter Progress_bar.comp
```

---

### Failure: noisy activation output corrupts detected prefix

Symptom:

```text
[ERROR] McStas resources not found.
Tried: "You seem to have a system wide installation of MSMPI. "\share\mcstas\resources
```

Cause:

- Installer captured the first line of `micromamba run python -c "print(sys.prefix)"`.
- Activation scripts printed other text first.

Regression prevention:

- Do not infer prefix from `micromamba run` output.
- Use known `%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%`.

Test:

1. Ensure MSMPI activation messages are present.
2. Run installer Step 6.
3. Confirm it still uses `%USERPROFILE%\AppData\Roaming\mamba\envs\tavi`.

---

### Failure: broken environment prefix

Symptom:

```text
error libmamba Non-conda folder exists at prefix - aborting.
critical libmamba Non-conda folder exists at prefix - aborting.
```

Cause:

- Folder exists at target environment prefix but is not a valid conda environment.

Regression prevention:

- Detect before create.
- Ask to move aside.
- Move to backup, do not delete.

Test:

1. Create an empty folder:
   ```powershell
   New-Item -ItemType Directory "$env:USERPROFILE\AppData\Roaming\mamba\envs\tavi"
   ```
2. Run installer.
3. Confirm it detects broken prefix and offers to move it aside.

---

### Failure: uninstaller removes developer environment

Symptom:

- Running dev launcher fails because the uninstaller removed a shared micromamba environment or the entire micromamba tree.

Regression prevention:

- Safe uninstaller removes only `ENV_NAME=tavi`.
- Never remove micromamba itself.
- Never remove `tavi-dev`.

Test:

```powershell
micromamba env list
```

Before and after uninstall:

- `tavi` may be removed.
- `tavi-dev` must remain.

---

## 19. Minimal user requirements

A normal user should need only:

1. Windows 10/11.
2. Internet access.
3. Permission to write under their own user profile.
4. ~~Visual Studio C++ Build Tools installed for full McStas compilation capability.~~
5. ~~Microsoft MPI SDK recommended/required for MPI workflows.~~

   > **Superseded 2026-09-15 (build 3):** nothing beyond Windows 10/11 and
   > disk/network. See "McStas compiler (build 3)" below.

The installer should install within user-writable locations:

```text
%USERPROFILE%\TAVI
%USERPROFILE%\AppData\Local\micromamba
%USERPROFILE%\AppData\Roaming\mamba\envs\tavi
```

It should not require Administrator privileges for the core install.

~~If Visual Studio or MSMPI are missing, warn clearly rather than corrupting the install. Only fail hard when TAVI cannot run in the intended mode.~~ Superseded 2026-09-15 (build 3): the compile gate fails hard on a serial or an MPI compile failure, since TAVI runs every point under MPI. See "McStas compiler (build 3)" below.

---

## 20. Expected successful install output

A successful install should end with something equivalent to:

```text
Installation complete.
Installed to: C:\Users\<USER>\TAVI
Environment : tavi
McStas      : 3.7.1

Run:
  C:\Users\<USER>\TAVI\TAVI-Launcher.bat
```

Expected files:

```text
%USERPROFILE%\TAVI\TAVI_PySide6.py
%USERPROFILE%\TAVI\tavi\mcstas_config.py
%USERPROFILE%\TAVI\run-tavi.bat
%USERPROFILE%\TAVI\update-tavi.bat
%USERPROFILE%\TAVI\TAVI-Launcher.bat
%USERPROFILE%\Desktop\TAVI Launcher.lnk
```

Expected environment:

```text
%USERPROFILE%\AppData\Roaming\mamba\envs\tavi
```

Expected McStas resources:

```text
%USERPROFILE%\AppData\Roaming\mamba\envs\tavi\share\mcstas\resources
```

Expected required component:

```text
Progress_bar.comp
```

somewhere under the McStas resources tree, unless TAVI is changed to stop requiring it.

---

## 21. Manual diagnostic commands

### List relevant packages

```powershell
C:\Users\AMM\AppData\Local\micromamba\micromamba.exe list -n tavi | findstr /i "mcstas mccode mcstasscript pyside"
```

### Check McStas resource tree

```powershell
dir C:\Users\AMM\AppData\Roaming\mamba\envs\tavi\share\mcstas
dir C:\Users\AMM\AppData\Roaming\mamba\envs\tavi\share\mcstas\resources
```

### Check required component

```powershell
Get-ChildItem C:\Users\AMM\AppData\Roaming\mamba\envs\tavi\share\mcstas\resources -Recurse -Filter Progress_bar.comp
```

### Check TAVI import

```powershell
C:\Users\AMM\AppData\Local\micromamba\micromamba.exe run -n tavi python -c "import tavi.mcstas_config as c; print(c.detect_mcstas())"
```

### Check installed source

```powershell
Test-Path C:\Users\AMM\TAVI\TAVI_PySide6.py
Test-Path C:\Users\AMM\TAVI\tavi\mcstas_config.py
```

### Check broken AutoRun

```powershell
reg query "HKCU\Software\Microsoft\Command Processor" /v AutoRun
```

If it contains stale `mamba`/`micromamba` text:

```powershell
reg delete "HKCU\Software\Microsoft\Command Processor" /v AutoRun /f
```

---

## 22. Pre-release checklist for installer updates

Before publishing a new installer:

- [ ] Installer starts with explanation and confirmation.
- [ ] Installer does not call `micromamba shell init`.
- [ ] Installer uses `setlocal DisableDelayedExpansion`.
- [ ] Installer avoids large parenthesized generated `echo` blocks.
- [ ] Installer detects/removes only stale mamba/micromamba AutoRun hooks.
- [ ] Installer asks before recreating the `tavi` environment.
- [ ] Installer handles broken non-conda prefix folders.
- [ ] Installer pins all McStas packages consistently.
- [ ] Installer verifies `TAVI_PySide6.py`.
- [ ] Installer verifies `tavi\mcstas_config.py`.
- [ ] Installer detects McStas resources using known prefix, not captured noisy output.
- [ ] Installer verifies `Progress_bar.comp` or the current required component.
- [ ] Launcher sets `MCSTAS` and `MCSTAS_COMPONENT_PATH`.
- [ ] Launcher runs via explicit `micromamba.exe run -n tavi`.
- [ ] Installer's compile gate passes serial and MPI on `PSI_DMC`.
- [ ] Safe uninstaller does not remove micromamba itself.
- [ ] Safe uninstaller does not remove `tavi-dev`.
- [ ] Install, update, run, and uninstall have been tested from both PowerShell and `cmd.exe`.

---

### Release recipe

Operator ruling, 2026-09-13: the release tool (`bin/release.py` in
Agentic-Control-Scheme) does not create, check, or upload an installer. A
release is the version bump, the changelog, the PR, the tag and the GitHub
release with its notes; an installer is a downstream artifact of a tag,
written after the tag exists.

(a) `/release X.Y.Z` bumps the version, harvests the changelog, and opens
    the release PR. The operator reviews and merges it. `/release X.Y.Z
    publish` tags the merged commit and creates the GitHub release with the
    notes. Nothing in either phase touches `installer/`.

(b) After the tag exists: copy the previous pinned installer to
    `WINDOWS-install-TAVI-vX.Y.Z.bat`, stamp the header comment and the
    `TAVI_VERSION` and `INSTALLER_VERSION` lines by hand, make whatever
    changes the release needs, run it cold on a clean directory against the
    real tag, commit it on main, and upload it with `gh release upload
    vX.Y.Z installer\WINDOWS-install-TAVI-vX.Y.Z.bat --clobber`. The release
    page may exist before its installer does.

(c) For 1.3 specifically: the installer needs a post-clone step that builds
    `components\Pb_dft_phonons.dat` (gitignored, 150 MB,
    `tools\make_pb_assets.py`; the target environment already carries numpy
    and scipy) — `setup-tavi-dev.bat` lines 182-193 are the model. Done in
    `WINDOWS-install-TAVI-v1.3.0.bat` (2026-09-14): the step warns and
    continues on failure and records `PB_MAP=ok|missing` in
    `INSTALL_INFO.txt`. The same file also made the micromamba SHA-256 check
    real (v1.2.0 declared `EXPECTED_SHA256` and never compared it) and moved
    the Visual Studio path read out of the block that fills it (§18, the
    DisableDelayedExpansion parse-time trap: `%VSINSTALLDIR%` inside the
    block was always empty, so no v1.2.0 launcher carried `vcvars64.bat`).

(d) macOS and Linux: `POSIX-install-TAVI-v1.3.0.sh` and
    `POSIX-uninstall-TAVI.sh`, a bash pair pinned to the same tag and
    uploaded the same way, provisional and never executed on either
    platform (§25). A later release copies and re-stamps them like the
    Windows file.

(e) `WINDOWS-install-TAVI.bat`, the unversioned copy that tracks `main`, is
    unmaintained: it lacks the 1.3 changes and each release derives from the
    previous *pinned* file, per (b). Delete it or bring it up to date before
    pointing anyone at it.

(f) 2026-09-15: build 2 of the v1.3.0 installers
    (`INSTALLER_VERSION=v1.3.0-2`, file names unchanged) — conda-only
    environment, rebuild-always, Qt smoke check. Re-uploaded over the
    v1.3.0 release assets with `--clobber`; `INSTALL_INFO.txt` tells the
    builds apart.

(g) 2026-09-15: build 3 of the v1.3.0 installers
    (`INSTALLER_VERSION=v1.3.0-3`) — conda-forge GCC (`gcc_win-64`) and
    `msmpi` added to the environment, Visual Studio detection and the MPI
    SDK check dropped, McStas's own config pointed at GCC inside the
    environment, and the install gated on a real serial and MPI compile of
    `PSI_DMC`. See "McStas compiler (build 3)" above.

## 23. Recommended future improvements

1. Replace batch with a small PowerShell installer or Python bootstrapper for safer string handling.
2. Add a machine-readable installer manifest:
   ```json
   {
     "python": "3.11",
     "mcstas": "3.7.1",
     "env": "tavi",
     "install_dir": "%USERPROFILE%\\TAVI"
   }
   ```
3. Add `--diagnose` mode that prints paths, package versions, and component availability without modifying anything.
4. Add a TAVI startup self-check panel/dialog for:
   - McStas resource path,
   - `mcrun`,
   - required components,
   - compiler availability,
   - MPI availability.
5. Add fallback in TAVI from `Progress_bar` to `Arm` if `Progress_bar.comp` is not available.
6. Consider pinning `pyside6` and `mcstasscript` conda versions after testing known-good ones.
7. Store installer version in the installed TAVI directory for support/debugging.

---

## 24. Summary of core lessons

The installer must be boring, explicit, and conservative.

The main regressions came from:

- fragile batch generation,
- using noisy command output as data,
- assuming `mcstasscript` implied valid McStas resources,
- assuming local dev files were committed,
- unsafe uninstaller scope,
- and insufficient early validation.

Future changes should preserve the successful pattern:

```text
explain -> confirm -> create/update env safely -> install source safely ->
detect known paths explicitly -> validate required resources -> generate launchers safely
```

Do not optimize away the checks. They are now part of the installer contract.

---

## 25. POSIX variant (macOS and Linux), provisional

Written 2026-09-14 as `installer/POSIX-install-TAVI-v1.3.0.sh` and
`installer/POSIX-uninstall-TAVI.sh`; never executed on macOS or Linux by the
maintainer, who has neither machine. The scripts say so in their headers and
at run time, and tell the user to stop at the first failure and open an issue
labelled `platform-installer` with the full output.

Layout, which the uninstaller and every later POSIX installer must honour:

```text
~/.local/bin/micromamba   micromamba binary, only if the script installed it
~/micromamba              MAMBA_ROOT_PREFIX, exported on every call
~/micromamba/envs/tavi    the tavi environment (ENV_PREFIX is read back from
                          python's sys.prefix after creation, not computed)
~/TAVI                    the pinned checkout, run-tavi.sh, update-tavi.sh,
                          run-tavi.command (macOS), INSTALL_INFO.txt
```

Rules that differ from or extend the Windows script:

- Bash 3.2 syntax only (macOS ships 3.2.57): no associative arrays,
  `mapfile`, case-conversion expansions or `[[ -v ]]`; `case` tables; `local`
  declared then assigned; `$HOME` never `~`. `set -euo pipefail`, with every
  continue-on-failure step written as `if ! cmd; then warn; fi`.
- Supported tuples: Darwin x86_64/arm64, Linux x86_64/aarch64 with glibc.
  Anything else exits before downloading.
- macOS preflight: `xcode-select -p` and `xcrun --sdk macosx --show-sdk-path`
  must both succeed; the conda-forge compiler that `mcstas-core` pulls in
  needs that SDK.
- An existing micromamba (on PATH or at `~/.local/bin/micromamba`) is reused
  and never overwritten. A fresh download is verified against a SHA-256
  pinned per platform (the values published with micromamba 2.5.0-1); a
  mismatch aborts, there is no warn-and-continue.
- Generated scripts carry the absolute micromamba path and export
  `MAMBA_ROOT_PREFIX`, so they work when `~/.local/bin` is not on PATH.
- `INSTALL_INFO.txt` adds `MICROMAMBA_EXE`, `MAMBA_ROOT_PREFIX`, `ENV_PREFIX`,
  `PB_MAP` and `PLATFORM`; the uninstaller reads the binary and root prefix
  from it rather than recomputing, and never lets it rename the env it removes.

Must-not-remove list for the POSIX uninstaller (§17's counterpart): micromamba
itself, `MAMBA_ROOT_PREFIX`, any environment other than `tavi`, the Xcode
tools. `~/TAVI` is removed only when it contains `TAVI_PySide6.py`; otherwise
the script refuses and exits 1.

Checks that can run on the Windows machine: `bash -n` on both scripts, a grep
for the forbidden constructs above, the uninstaller's guard test under Git
Bash with `HOME` pointed at a fixture and a stub `micromamba` on PATH, and the
`verify_sha256` function sourced and called with a right and a wrong hash.
Nothing else is verified until a user on either platform reports back.
