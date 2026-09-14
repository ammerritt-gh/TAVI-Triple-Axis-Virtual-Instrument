# TAVI Installation Guide

> **Status:** live
## Triple Axis Virtual Instrument for Windows, macOS and Linux

TAVI is a simulation tool for triple-axis spectrometer (TAS) experiments, built on McStas. This guide covers installation, first-run validation, and troubleshooting. The Windows installer is the tested one; the macOS and Linux script is a provisional first attempt, described in its own section below.

---

## Quick Start

1. **Install Visual Studio Build Tools** (see Prerequisites below — do this first)
2. **Download** `WINDOWS-install-TAVI-vX.Y.Z.bat` from the latest release at https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases (the installer is attached to each release; it may appear a little after the release itself)
3. **Double-click** the downloaded `.bat` to run the installer
4. **Wait** 10–20 minutes for installation to complete
5. **Run a 2-point scan** to validate the installation (see First-Run Validation below)

macOS or Linux: see [macOS and Linux (provisional, never executed)](#macos-and-linux-provisional-never-executed).

---

## Prerequisites

### Required: Visual Studio Build Tools (C++ compiler)

McStas compiles neutron instrument simulations at runtime and requires a C++ compiler. The easiest way to get this:

1. Go to: https://visualstudio.microsoft.com/downloads/
2. Scroll down to **"Tools for Visual Studio"**
3. Download **"Build Tools for Visual Studio 2022"** (or 2026 if available)
4. Run the installer and select **"Desktop development with C++"**
5. Under Individual Components, include:
   - C++/CLI support (latest MSVC)
   - MSVC v143 build tools
   - MSVC v142 build tools
6. Click Install (~6 GB disk space)

The installer detects Visual Studio automatically using `vswhere.exe`, so it handles non-standard install paths correctly (e.g. VS 2026 installs to a `\18\` directory rather than `\2026\`). If you have Visual Studio already installed with C++ tools, you're all set.

### Optional: Microsoft MPI SDK

Required only for NMO-enabled simulation workflows. Basic simulations work without it.

Download from: https://learn.microsoft.com/en-us/message-passing-interface/microsoft-mpi

The installer detects MPI automatically and includes the SDK paths in generated launchers if found.

---

## What the Installer Does

The installer performs these steps automatically:

1. **Detects Visual Studio** — via `vswhere.exe`; warns if not found
2. **Detects MPI SDK** — optional; warns if not found
3. **Installs micromamba** — a lightweight conda package manager (pinned version with checksum verification)
4. **Creates the `tavi` environment** — with Python 3.11, McStas, and all dependencies; or reconciles an existing environment to the current package manifest
5. **Clones TAVI** — from GitHub at the release pinned in the installer
6. **Configures McStasScript** — so it can find the McStas installation in the conda environment
7. **Builds the lead-sample dispersion map** — `components\Pb_dft_phonons.dat`, about 150 MB, a few minutes with no output. It is optional: if the step fails the installer warns, records `PB_MAP=missing` in `INSTALL_INFO.txt` and continues; the "Pb: Phonon DFT" sample then stays listed but a run with it fails at asset load until you open the TAVI shell and run `python tools\make_pb_assets.py`
8. **Creates launcher scripts** — that bootstrap the Visual Studio compiler environment before starting TAVI, so the first-point compile succeeds

### Installed Components

| Component | Purpose |
|-----------|---------|
| micromamba | Package manager (like conda, but faster) |
| McStas | Neutron ray-tracing simulation engine |
| McStasScript | Python API for McStas |
| Python 3.11 | Runtime |
| PySide6 | GUI framework |
| NumPy, SciPy, Matplotlib | Scientific computing |
| h5py, PyYAML | Data I/O |

---

## Versioning

The installer pins a specific TAVI release via the `TAVI_VERSION` variable near the top of the script. Installers published as release artifacts will always pin a specific tag (e.g. `v1.3.0`). Development builds may set `TAVI_VERSION=main`.

To check which version is installed:

```batch
cd %USERPROFILE%\TAVI
git describe --tags
```

To move to a newer release, download that release's installer from the [releases page](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases) and run it. The launcher's **Update TAVI** option repairs the current pinned installation (fetches tags, re-checks out the same tag, refreshes pip packages) and never changes which release is installed.

---

## Using TAVI

### TAVI Launcher

After installation, use the **"TAVI Launcher"** shortcut on your desktop:

| Option | Description |
|--------|-------------|
| **[1] Run TAVI** | Start the TAVI application |
| **[2] Update TAVI** | Repair the current pinned installation (re-fetch and re-check-out the same tag, refresh pip packages) |
| **[3] Open TAVI folder** | Browse installation files |
| **[4] Open TAVI shell** | Command prompt inside the `tavi` environment (no compiler bootstrap; run `run-tavi.bat` to start TAVI with one) |
| **[5] Exit** | Close the launcher |

### Direct Scripts

These scripts are installed in `%USERPROFILE%\TAVI`:

| Script | Purpose |
|--------|---------|
| `TAVI-Launcher.bat` | Menu launcher (recommended entry point) |
| `run-tavi.bat` | Launch TAVI directly |
| `update-tavi.bat` | Update to the pinned release |

`run-tavi.bat` calls the detected `vcvars64.bat x64` inline and appends the MS-MPI include and lib paths before starting TAVI; the launcher menu's Run option delegates to it. The shell and update options do not bootstrap the compiler. There is no separate helper script. This is what allows McStas to compile on first run.

---

## First-Run Validation

A successful installation requires more than the GUI launching. The critical path involves a McStas compile on the first simulation point. After installing:

1. Launch TAVI from the desktop shortcut
2. Configure a simple scan (any 2-point scan with the default PUMA settings)
3. Run it and confirm:
   - The first scan point compiles successfully (~10–30 seconds)
   - The second point runs faster (reusing the compiled binary)
   - Results appear in the display panel

If the first point fails to compile, the most likely cause is the compiler bootstrap not being applied — see Troubleshooting below.

---

## Troubleshooting

### "C++ compiler not found" during install

1. Install Visual Studio Build Tools (see Prerequisites)
2. Re-run the installer — it will detect the newly installed compiler

### Simulation fails to compile on first run

Make sure you are launching from `TAVI-Launcher.bat` or `run-tavi.bat` (not by running `python TAVI_PySide6.py` directly in a plain command prompt). These scripts set up the compiler environment before TAVI starts.

If you bypassed the compiler check during installation, re-run the installer with Visual Studio installed to regenerate the launcher scripts with a working bootstrap.

### "MPI launcher could not be resolved" in message center

This indicates an NMO/MPI workflow is active but the Microsoft MPI SDK is not installed or was not found at install time. Install the MPI SDK (see Prerequisites) and re-run the installer to regenerate the launcher scripts with MPI paths included.

### "Failed to download micromamba"

Check your internet connection and try again. If behind a proxy, configure Windows proxy settings before running the installer.

### "Failed to create environment"

Check available disk space (~3 GB needed) and internet connection. Run again with `--verbose` for detailed output.

### Import errors on launch (`No module named 'PySide6'`, etc.)

Use option **[2] Update TAVI** from the launcher, which also reinstalls pip packages. Alternatively, run `update-tavi.bat` directly.

### McStas not found / wrong McStas version used

The installer configures McStasScript to use the McStas installation inside the `tavi` conda environment. If a system-wide McStas installation (from the standalone installer) is interfering, the launcher scripts override the `MCSTAS` environment variable. If you see unexpected McStas paths in the TAVI message center, re-run the installer to regenerate the launcher scripts.

---

## Advanced Usage

### Manual environment activation

```batch
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe run -n tavi python TAVI_PySide6.py
```

Note: this bypasses the compiler bootstrap the generated launchers perform. Simulations may fail to compile unless the Visual Studio environment is already active in the calling shell.

### Updating McStas (conda)

```batch
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe install -n tavi mcstas mcstas-core -c conda-forge -y
```

### Uninstalling TAVI

Run `WINDOWS-uninstall-TAVI.bat` from the installer folder. It will:

1. Remove the `tavi` conda environment
2. Remove the TAVI code directory (asking first if it does not look like a TAVI install)
3. Remove the desktop shortcut

It never removes micromamba itself, Visual Studio, the MPI SDK, or any other micromamba environment you may have (`tavi-dev` included). On macOS and Linux, `POSIX-uninstall-TAVI.sh` follows the same rules.

---

## Technical Notes

### Why micromamba instead of conda?

Faster installation and environment solving, smaller footprint, and better handling of complex dependency chains like McStas.

### Why PySide6 via pip?

PySide6 is not officially distributed via conda-forge by the Qt Project. The pip version is better maintained and avoids Qt library conflicts.

### Compiler bootstrap rationale

McStas generates and compiles C instrument files at runtime. The compiler must be available in the process environment when `mcrun` is called. The generated launcher scripts call `vcvars64.bat x64` before starting TAVI, which sets `PATH`, `INCLUDE`, `LIB`, and related variables so `cl.exe` is available to McStas. Launching TAVI directly with `python TAVI_PySide6.py` in a plain shell bypasses this and will cause first-point compile failures.

### mcstas_config.json and runtimes.json

TAVI stores local McStas path configuration in `config/mcstas_config.json` and per-scan runtime estimates in `config/runtimes.json`. These are generated at runtime and should not be edited manually unless you need to override a specific McStas path.

### Installation paths

| Item | Location |
|------|----------|
| micromamba binary | `%USERPROFILE%\AppData\Local\micromamba\micromamba.exe` |
| tavi conda environment | `%USERPROFILE%\AppData\Roaming\mamba\envs\tavi\` |
| TAVI code | `%USERPROFILE%\TAVI\` |
| Launcher scripts | `%USERPROFILE%\TAVI\*.bat` |
| Simulation output | `%USERPROFILE%\TAVI\output\` |

---

## macOS and Linux (provisional, never executed)

`POSIX-install-TAVI-v1.3.0.sh` and `POSIX-uninstall-TAVI.sh` are attached to the
v1.3.0 release. They were written on 2026-09-14 by mirroring the Windows installer
step by step and have **never been run on macOS or Linux** by the maintainer, who
has neither machine. Treat them as a first attempt:

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
bash POSIX-install-TAVI-v1.3.0.sh
```

A downloaded script is not executable, so run it through `bash` rather than
double-clicking it. It explains what it will do and asks before changing anything.
Afterwards:

```bash
bash ~/TAVI/run-tavi.sh          # start TAVI
bash ~/TAVI/update-tavi.sh       # repair the pinned install (same tag, refreshed pip packages)
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
  -c conda-forge -c nodefaults -y
$MM run -n tavi python -m pip install --upgrade pip PySide6 mcstasscript

# 3. source, pinned to the release tag
$MM run -n tavi git clone --branch v1.3.0 --depth 1 --single-branch \
  https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git ~/TAVI

# 4. McStasScript paths (PREFIX is ~/micromamba/envs/tavi)
$MM run -n tavi python -c "import mcstasscript as ms; c = ms.Configurator(); \
  c.set_mcrun_path('$MAMBA_ROOT_PREFIX/envs/tavi/bin'); \
  c.set_mcstas_path('$MAMBA_ROOT_PREFIX/envs/tavi/share/mcstas/resources')"

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

*Last updated: 2026-09-14 (v1.3.0 installers; provisional macOS/Linux script)*
