# TAVI Installation Guide

> **Status:** live
## Triple Axis Virtual Instrument for Windows, macOS and Linux

TAVI is a simulation tool for triple-axis spectrometer (TAS) experiments, built on McStas. This guide covers installation, first-run validation, and troubleshooting. The Windows installer is the tested one; the macOS and Linux script is a provisional first attempt, described in its own section below.

---

## Quick Start

1. **Download** `WINDOWS-install-TAVI-v1.4.1.bat` from the v1.4.1 release at https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases (the installer is attached to each release; it may appear a little after the release itself)
2. **Double-click** the downloaded `.bat` to run the installer
3. **Choose where TAVI goes.** Press Enter to accept the suggested folder, or type a full path such as `D:\TAVI`. Everything — the program, its Python environment, McStas, the compiler and the downloaded packages, about 3 GB — lives inside that one folder. The path can only use letters, digits, dot, dash and underscore, with no spaces, because McStas cannot compile from a path with a space in it.
4. **Wait** about 15–25 minutes for installation to complete, longer on a slow connection. The window prints a `still running` line every 30 seconds; that means it has not stopped.
5. **Read the last screen.** It should say `INSTALLATION SUCCEEDED`. If it says anything else, see Troubleshooting below. Then you can run a 2-point scan to check further (see First-Run Validation below)

The installation cannot be moved afterwards once it exists — the Python environment stores its own location internally. The **TAVI Launcher** shortcut it creates, inside that folder, can be moved anywhere you like (your desktop, for instance).

macOS or Linux: see [macOS and Linux (provisional, never executed)](#macos-and-linux-provisional-never-executed).

---

## Prerequisites

Windows 10/11, about 3 GB of disk, internet. No compiler install: the environment carries GCC from conda-forge.

---

## What the Installer Does

After you choose (or confirm) the install folder, the installer performs these steps automatically, all inside it:

1. **Installs micromamba** — a lightweight conda package manager (pinned version with checksum verification)
2. **Creates the environment** — in a `tavi-env` folder inside your chosen install folder, with Python 3.11, McStas, GCC (conda-forge) and MS-MPI, and all dependencies, including PySide6 and McStasScript from conda-forge; an existing environment is removed and rebuilt
3. **Clones TAVI** — from GitHub at the release pinned in the installer, into an `app` folder inside your chosen install folder
4. **Configures McStasScript** — so it can find the McStas installation in the conda environment
5. **Configures and compile-checks the McStas compiler** — points McStas's own config at the environment's GCC (five overrides, written into the environment's copy of `mccode_config.json`), moves aside any stale per-user McStas config that would override it, then compiles and runs the `PSI_DMC` example serially and under MPI. Either failure stops the install: TAVI runs every simulation under MPI
6. **Builds the lead-sample dispersion map** — `components\Pb_dft_phonons.dat`, about 150 MB, a few minutes with no output. It is optional: if the step fails the installer warns, records `PB_MAP=missing` in `INSTALL_INFO.txt` and continues; the "Pb: Phonon DFT" sample then stays listed but a run with it fails at asset load until you open the TAVI shell and run `python tools\make_pb_assets.py`
7. **Installs the launcher scripts** — copies the launchers, including `collect-diagnostics.bat`, into your chosen install folder and creates the "TAVI Launcher" shortcut there
8. **Runs a test simulation** — starts TAVI without a window and runs one small McStas simulation through TAVI itself, so a broken TAVI is caught here and not at your first scan. It takes a minute or two and writes nothing into your `output` folder.

### When the installer finishes

Your last screen says one of these. Only the `C` key closes that window; other keys do nothing.

| Headline | What it means |
|----------|---------------|
| `INSTALLATION SUCCEEDED` | TAVI is installed and its test simulation worked. Start it from the TAVI Launcher. |
| `INSTALLATION FAILED` | A step did not finish. The screen names the step and the error, and says what was removed (see below). Nothing of the new install is removed: what was installed so far stays in the TAVI folder. |
| `TAVI INSTALLED, BUT THE TEST SIMULATION FAILED` | TAVI is installed and will open, but its test simulation did not work, so simulations will probably fail too. The screen says `Nothing was removed: TAVI is fully installed in that folder.` (or, when an older installation was replaced, that it was removed and the new TAVI is fully installed) and how to start it from the TAVI Launcher. |
| `INSTALLATION CANCELLED` | You answered No to "Continue with TAVI installation?". Nothing new was installed, and it is not a failure. |

On a failure, the last lines of the install log appear on screen and Notepad opens the full log. The screen offers **D**: press D to collect diagnostics for support, which makes the zip described under Troubleshooting. The screen then comes back; press **C** to close it.

Removal of anything that was already there is limited to one case. If you agreed to replace an older TAVI installation (or one that did not finish), the installer removes it before the new install begins, and the last screen says so, with one of these sentences:

- `The old TAVI installation was removed before this install began. Nothing of the new install was removed: what was installed so far is still in that folder.` (failure)
- `Part of the old TAVI installation could not be removed, and part of it may already have gone. Nothing of the new install was removed: what was installed so far is still in that folder.` (failure)
- `The old TAVI installation was removed. Nothing new was installed.` (cancelled)

When no old installation was removed, a failure says `Nothing was removed: what was installed so far is still in that folder.`, and a cancelled install says `Nothing was installed and nothing was removed.`

After a successful install, or one whose test simulation failed, the installer asks: *Also put a copy of the TAVI Launcher shortcut on your desktop?* Press Enter for yes (the recommended answer), or type N and Enter for no. The shortcut also stays in your install folder, which opens in Explorer when the installer finishes.

### Installed Components

| Component | Purpose |
|-----------|---------|
| micromamba | Package manager (like conda, but faster) |
| McStas | Neutron ray-tracing simulation engine |
| McStasScript | Python API for McStas |
| Python 3.11 | Runtime |
| PySide6 | GUI framework |
| GCC (MinGW-w64) | C compiler McStas uses to build instruments |
| MS-MPI | MPI runtime for parallel simulation runs |
| NumPy, SciPy, Matplotlib | Scientific computing |
| h5py, PyYAML | Data I/O |

---

## Versioning

The installer pins a specific TAVI release via the `TAVI_VERSION` variable near the top of the script. Installers published as release artifacts will always pin a specific tag (e.g. `v1.4.1`). Development builds may set `TAVI_VERSION=main`.

To check which version is installed:

```batch
cd <your install folder>\app
git describe --tags
```

To move to a newer release, download that release's installer from the [releases page](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases) and run it. The launcher's **Repair TAVI** option repairs the current pinned installation (fetches tags, re-checks out the same tag, checks that the GUI toolkit and McStasScript load) and never changes which release is installed.

---

## Using TAVI

### TAVI Launcher

After installation, use the **"TAVI Launcher"** shortcut, which lives inside your install folder (move it to your desktop if you like):

| Option | Description |
|--------|-------------|
| **[1] Run TAVI** | Start the TAVI application |
| **[2] Repair TAVI** | Repair the current pinned installation (re-fetch and re-check-out the same tag, check that the GUI toolkit and McStasScript load) |
| **[3] Open TAVI folder** | Browse installation files |
| **[4] Open TAVI shell** | Command prompt inside the TAVI environment |
| **[5] Collect diagnostics for support** | Gather the logs and the TAVI Doctor's report into one zip file for the person helping you (see Troubleshooting). Takes a few minutes. |
| **[6] Uninstall TAVI** | Remove the installation (see Uninstalling TAVI below) |
| **[7] Exit** | Close the launcher |

### Direct Scripts

These scripts are installed directly in your chosen install folder (not inside the `app` subfolder):

| Script | Purpose |
|--------|---------|
| `TAVI-Launcher.bat` | Menu launcher (recommended entry point) |
| `run-tavi.bat` | Launch TAVI directly |
| `update-tavi.bat` | Repair the pinned release |
| `uninstall-tavi.bat` | Remove the installation |
| `collect-diagnostics.bat` | Gather the logs and the TAVI Doctor's report into one zip (menu item 5) |

`run-tavi.bat` sets `MCSTAS` to the environment's resources and starts TAVI; the launcher menu's Run option delegates to it. No compiler bootstrap is needed — the environment's McStas config already points at its own GCC.

---

## First-Run Validation

A successful installation requires more than the GUI launching. The critical path involves a McStas compile on the first simulation point. After installing:

1. Launch TAVI from the desktop shortcut
2. Configure a simple scan (any 2-point scan with the default PUMA settings)
3. Run it and confirm:
   - The first scan point compiles successfully (~10–30 seconds)
   - The second point runs faster (reusing the compiled binary)
   - Results appear in the display panel

The installer already compile-checks the compiler before it finishes, so a first-point compile failure is unexpected — see Troubleshooting below.

---

## Troubleshooting

### Where the logs are, and what to send

Every install, launch, repair and uninstall writes a log file to this folder:

    %LOCALAPPDATA%\TAVI\logs\

Paste that into the address bar of Explorer. The file names start with `install-`, `launch-`, `repair-` or `uninstall-`, followed by the date and time. The file `install-status.txt` in your install folder says how the last install ended. These logs stay on your computer when TAVI is removed.

If that folder cannot be written (some managed laptops block it), the logs go into the Windows temporary folder instead. Type `%TEMP%` in the Explorer address bar to open it. The diagnostics zip goes to the same place. Whichever folder is used, the last screen of each run prints the full path of the file to send, so copy the path from there. If nothing could be saved in either place, that screen says so.

If something goes wrong, open the **TAVI Launcher** and choose **[5] Collect diagnostics for support**. It takes a few minutes, because it runs TAVI's Doctor, which runs four short test simulations. When it finishes, Explorer opens the logs folder with one file selected, named `TAVI-diagnostics-<date and time>.zip`. Send that one file to the person who helps you with TAVI. It holds the logs, the crash log, the install status, the version record, the compiler-check logs and the Doctor's report. It contains your user name and folder paths. TAVI does not send it anywhere; you send it.

### TAVI crashes or closes unexpectedly

Send `output/tavi-crash.log` from the TAVI folder with your report; the console prints its full path at startup. It records your operating system, library versions and display session (on Linux, Wayland or X11), uncaught errors and Qt warnings, and on Linux and macOS the Python stack of every thread when TAVI crashes. The diagnostics zip (launcher menu item 5) includes this file, so you can send that instead.

### Compiler check failed during install

Look at `<base>\compile_check\serial.log` (or `mpi.log` if the MPI run was the one that failed), where `<base>` is the install folder you chose, for the compiler error, then re-run the installer; it rebuilds the environment from scratch. The MPI run uses `mpiexec` from the environment, not a system-wide MS-MPI. The diagnostics zip (launcher menu item 5) includes both logs.

### Monte Carlo simulations fail but the deterministic engine still works (installation from before 1.3.2)

An installation made before version 1.3.2 starts TAVI by selecting its environment by *name*, which can load the wrong environment's Python and `mcrun` if a second one with the same name exists on the machine — for example because an earlier install had to relocate off a profile path with a space in it. The symptom is that ordinary scan setup and the deterministic engine work fine, but any run that needs a real McStas simulation fails. Download `TAVI-Repair-Launchers.bat` from the releases page and run it: it rewrites your three launcher scripts to always use your exact installed environment, without reinstalling anything or changing any package. Your previous launchers are kept beside the new ones, named `.bak-<number>`. Installing version 1.3.2 or later fixes this permanently.

### "Failed to download micromamba"

Check your internet connection and try again. If behind a proxy, configure Windows proxy settings before running the installer.

### "Failed to create environment"

Check available disk space (~3 GB needed) and internet connection. The full output is in the install log; see "Where the logs are, and what to send" above.

### Import errors on launch (`No module named 'PySide6'`, etc.)

Run the installer again, pointed at the same install folder. It removes the environment and rebuilds it from the package list; downloads are cached so this is quick. The launcher's **[2] Repair TAVI** only reports whether the environment loads; it does not rebuild it.

### McStas not found / wrong McStas version used

The installer configures McStasScript to use the McStas installation inside the TAVI folder's own environment (`<base>\tavi-env`). If a system-wide McStas installation (from the standalone installer) is interfering, the launcher scripts override the `MCSTAS` environment variable. If you see unexpected McStas paths in the TAVI message center, re-run the installer, which reinstalls the launcher scripts.

---

## Advanced Usage

### Manual environment activation

The environment is always selected by its exact folder, not by name — replace `<base>` with your install folder:

```batch
"<base>\micromamba\micromamba.exe" -r "<base>\mamba" run -p "<base>\tavi-env" python TAVI_PySide6.py
```

### Updating McStas

Do not update McStas in place with `micromamba install`: a new McStas package brings its own `mccode_config.json`, which points at Visual Studio's `cl.exe` again, and the next simulation fails to compile. A newer McStas arrives with a newer installer, which rebuilds the environment and re-applies the GCC configuration.

### Uninstalling TAVI

The normal way is the **TAVI Launcher**'s **[6] Uninstall TAVI** option. It asks for confirmation (twice, if you have saved scan results), then removes:

- the program (`app`)
- your scan results (`app\output`) and saved settings (`app\config`)
- the Python/McStas environment (`tavi-env`)
- the downloaded package cache (`mamba`)
- the five launcher scripts and the shortcut in the install folder, and the copy on your desktop if it opens this installation
- the installer's status file and any diagnostics folders TAVI made

Anything else you have put in the install folder is left alone and reported at the end. Reinstalling later downloads about 1.5 GB of packages again. Your logs in `%LOCALAPPDATA%\TAVI\logs` are kept, so a problem with the uninstall can still be looked at; delete that folder by hand if you do not want them.

If the launcher itself is missing or damaged, run `<your install folder>\uninstall-tavi.bat` directly, or download `WINDOWS-uninstall-TAVI.bat` from the releases page — a standalone fallback that finds your installation (by argument, by its own saved location record, in the usual default folders, or by asking) and hands off to the uninstaller that came with it. It also knows how to remove an installation from before version 1.3.2.

It removes the micromamba and the package cache that live inside the TAVI folder, because they belong to that installation. It never touches a micromamba installed anywhere else, and never any other environment you may have (`tavi-dev` included). On macOS and Linux, `POSIX-uninstall-TAVI.sh` follows the same rules.

---

## Technical Notes

### Why micromamba instead of conda?

Faster installation and environment solving, smaller footprint, and better handling of complex dependency chains like McStas.

### Why PySide6 from conda-forge, not pip?

Because conda-forge matplotlib already depends on the conda-forge PySide6, which pins the environment's Qt. A pip PySide6 installed on top cannot replace it (the conda package has no pip RECORD file) and, when forced, loads against the wrong Qt DLLs. One package manager per environment: every Python package in `tavi` comes from conda-forge, and the installer verifies that PySide6 and McStasScript load before it continues (2026-09-15).

### Why GCC from conda-forge

conda-forge's Windows McStas package is configured for `cl.exe` and only locates an installed Visual Studio, so without a change every user would need to install Visual Studio Build Tools first. conda-forge ships a working MinGW-w64 GCC (`gcc_win-64`) instead: the installer adds it to the `tavi` environment and, at install time, overrides five entries in the environment's own copy of McStas's `mccode_config.json` — `CC`, `MPICC` (the GCC executable), `CFLAGS` (include/lib paths plus a `-B` flag pointing at the sysroot's `usr/lib`, since conda-forge's GCC looks for `crt2.o` there instead of the sysroot's plain `lib`), `MPIFLAGS` (`-DUSE_MPI -lmsmpi`), and `NCRYSTALFLAGS` (rewritten from the package's MSVC-syntax default). The config lives inside the environment (not `%APPDATA%\mcstas`) so it is created and destroyed with the environment and there is exactly one source of truth; the installer unlinks the file before writing it, because conda hardlinks package files into its cache and into every other environment that has the same McStas package, and an in-place write would change them all. The installer then compiles and runs a test instrument before it finishes, so a broken compiler is caught at install time rather than on your first scan.

### mcstas_config.json and runtimes.json

TAVI stores local McStas path configuration in `config/mcstas_config.json` and per-scan runtime estimates in `config/runtimes.json`. These are generated at runtime and should not be edited manually unless you need to override a specific McStas path.

### Installation paths

Everything lives under the one folder you chose during install (`<base>` below — by default `%USERPROFILE%\TAVI`, or `%SystemDrive%\TAVI-Data` if your profile path cannot hold McStas, for instance because it contains a space):

| Item | Location |
|------|----------|
| Install folder (chosen at install time) | `<base>` |
| micromamba binary | `<base>\micromamba\micromamba.exe` |
| TAVI environment (Python, McStas, GCC, MS-MPI) | `<base>\tavi-env\` |
| Package cache / root prefix | `<base>\mamba\` |
| TAVI code | `<base>\app\` |
| Compile-gate logs | `<base>\compile_check\` |
| Launcher scripts | `<base>\*.bat` |
| Simulation output | `<base>\app\output\` |
| Saved settings | `<base>\app\config\` |
| Install record (used to locate the installation) | `%LOCALAPPDATA%\TAVI\install-record.txt` |
| Install, launch, repair and uninstall logs; the diagnostics zip | `%LOCALAPPDATA%\TAVI\logs\` |
| Outcome of the last install | `<base>\install-status.txt` |

**The installation cannot be moved.** The environment and its generated McStas configuration store the absolute install path internally; moving or renaming `<base>` breaks it. Only the "TAVI Launcher" shortcut can be moved.

---

## macOS and Linux (provisional, never executed)

`POSIX-install-TAVI-v1.4.1.sh` and `POSIX-uninstall-TAVI.sh` are attached to the
v1.4.1 release. The v1.4.1 script is the v1.3.2 one pinned to the new tag; the
Windows installer's 1.4 additions (install log, test simulation) are not in it. They were written on 2026-09-14 (for v1.3.0) by mirroring the
Windows installer step by step and have **never been run on macOS or Linux** by
the maintainer, who has neither machine. v1.3.2 adds one check after the McStas
step: it compiles and runs a McStas example under MPI with two processes, as
TAVI runs every simulation, and stops the install if that fails. That check has
never been run either. Treat them as a first attempt:

- If the script fails, stop at the first failure. Do not debug it. Paste the whole
  terminal output into an issue at
  https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues with
  the label `platform-installer`. A fixed script or a "cannot work here" answer
  follows from that.
- A partial run may leave `~/.local/bin/micromamba` (only if the script installed
  it), `~/micromamba` (the root prefix holding the `tavi` environment) and `~/TAVI`.
  Run `bash POSIX-uninstall-TAVI.sh` to remove the environment and the folder, or
  delete them by hand, before retrying a fixed version.

### Supported platforms

macOS 12 or later (Intel and Apple Silicon) and glibc-based Linux (x86_64 and
aarch64). Anything else, including musl-based distributions such as Alpine, is
refused before anything is downloaded.

### Prerequisites

- macOS: the Xcode Command Line Tools, for the SDK the conda-forge compiler needs:
  `xcode-select --install`. The script checks with `xcode-select -p` and
  `xcrun --sdk macosx --show-sdk-path` and stops if either fails.
- Linux: `curl` or `wget`. The C compiler comes with the McStas conda package.
- Both: internet access and about 3 GB under your home directory.

### Running it

```bash
bash POSIX-install-TAVI-v1.4.1.sh
```

If it stops at the compile check, the message names the log it kept. The likely
causes are no working C compiler, no MPI in the environment, fewer than two CPU
cores (Open MPI refuses to start more processes than there are cores), or
running the installer as root.

A downloaded script is not executable, so run it through `bash` rather than
double-clicking it. It explains what it will do and asks before changing anything.
Afterwards:

```bash
bash ~/TAVI/run-tavi.sh          # start TAVI
bash ~/TAVI/update-tavi.sh       # repair the pinned install (same tag, environment check)
bash POSIX-uninstall-TAVI.sh     # remove the tavi environment and ~/TAVI
```

On macOS the installer also writes `~/TAVI/run-tavi.command`, which Finder opens in
Terminal on a double-click.

### What it does, as commands

The script is these steps with checks and prompts around them. If it fails partway
you can continue by hand from the step it named; `MM` is the micromamba binary it
chose and `~/micromamba` its root prefix.

```bash
# 1. micromamba (reused if already on PATH or at ~/.local/bin/micromamba; the
#    script verifies the download's SHA-256 against a value pinned per platform)
mkdir -p ~/.local/bin
curl -fL -o ~/.local/bin/micromamba \
  https://github.com/mamba-org/micromamba-releases/releases/download/2.5.0-1/micromamba-osx-arm64   # or -osx-64, -linux-64, -linux-aarch64
chmod 0755 ~/.local/bin/micromamba
export MAMBA_ROOT_PREFIX=~/micromamba
MM=~/.local/bin/micromamba

# 2. environment
$MM create -n tavi python=3.11 mcstas=3.7.1 mcstas-core=3.7.1 mcstas-data=3.7.1 \
  mcstas-mcgui=3.7.1 mcstas-vis=3.7.1 numpy scipy matplotlib h5py pyyaml git \
  pyside6 mcstasscript -c conda-forge -c nodefaults -y

# 3. source, pinned to the release tag
$MM run -n tavi git clone --branch v1.4.1 --depth 1 --single-branch \
  https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git ~/TAVI

# 4. McStasScript paths (PREFIX is ~/micromamba/envs/tavi)
$MM run -n tavi python -c "import mcstasscript as ms; c = ms.Configurator(); \
  c.set_mcrun_path('$MAMBA_ROOT_PREFIX/envs/tavi/bin'); \
  c.set_mcstas_path('$MAMBA_ROOT_PREFIX/envs/tavi/share/mcstas/resources')"

# 4b. compile check: a McStas example under MPI, two processes
D=$(mktemp -d) && cp $MAMBA_ROOT_PREFIX/envs/tavi/share/mcstas/resources/examples/PSI/PSI_DMC/PSI_DMC.instr $D/ \
  && (cd $D && $MM run -n tavi mcrun -c --mpi=2 PSI_DMC.instr -n 1000 -d mpi lambda=2.5666)

# 5. lead-sample dispersion map (150 MB, a few minutes, optional)
cd ~/TAVI && $MM run -n tavi python tools/make_pb_assets.py

# 6. run
cd ~/TAVI && MCSTAS=$MAMBA_ROOT_PREFIX/envs/tavi/share/mcstas/resources \
  $MM run -n tavi python TAVI_PySide6.py
```

### Uninstalling

`POSIX-uninstall-TAVI.sh` reads `~/TAVI/INSTALL_INFO.txt` for the micromamba binary
and root prefix the installer used (the environment name is always `tavi`), removes the `tavi` environment
and `~/TAVI` (only if `TAVI_PySide6.py` is found there), and never removes micromamba
itself, the root prefix or any other environment.

---

## Getting Help

- **TAVI issues**: https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
- **McStas documentation**: https://www.mcstas.org/
- **McStasScript documentation**: https://mads-bertelsen.github.io/

---

*Last updated: 2026-10-16 (v1.4.0: install log and logs folder, three endings with a test simulation, desktop copy, diagnostics menu item; the macOS/Linux script is unchanged at v1.3.2; 2026-10-19: re-stamped as v1.4.0; 2026-10-20: re-stamped as v1.4.1)*
