# TAVI Installation Guide
## Triple Axis Virtual Instrument for Windows

TAVI is a simulation tool for triple-axis spectrometer (TAS) experiments, built on McStas. This guide covers installation, first-run validation, and troubleshooting.

---

## Quick Start

1. **Install Visual Studio Build Tools** (see Prerequisites below — do this first)
2. **Download** `WINDOWS-install-TAVI.bat` from the [installer folder](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/main/installer/WINDOWS-install-TAVI.bat)
3. **Double-click** `WINDOWS-install-TAVI.bat` to run the installer
4. **Wait** 10–20 minutes for installation to complete
5. **Run a 2-point scan** to validate the installation (see First-Run Validation below)

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

`WINDOWS-install-TAVI.bat` performs these steps automatically:

1. **Detects Visual Studio** — via `vswhere.exe`; warns if not found
2. **Detects MPI SDK** — optional; warns if not found
3. **Installs micromamba** — a lightweight conda package manager (pinned version with checksum verification)
4. **Creates the `tavi` environment** — with Python 3.11, McStas, and all dependencies; or reconciles an existing environment to the current package manifest
5. **Clones TAVI** — from GitHub at the release pinned in the installer
6. **Configures McStasScript** — so it can find the McStas installation in the conda environment
7. **Creates launcher scripts** — that bootstrap the Visual Studio compiler environment before starting TAVI, so the first-point compile succeeds

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

The installer pins a specific TAVI release via the `TAVI_VERSION` variable near the top of the script. Installers published as release artifacts will always pin a specific tag (e.g. `v1.0.0`). Development builds may set `TAVI_VERSION=main`.

To check which version is installed:

```batch
cd %USERPROFILE%\TAVI
git describe --tags
```

To update to a new release, re-run the installer (it will reconcile the environment and check out the new tag), or use the **Update TAVI** option in the launcher.

---

## Using TAVI

### TAVI Launcher

After installation, use the **"TAVI Launcher"** shortcut on your desktop:

| Option | Description |
|--------|-------------|
| **[1] Run TAVI** | Start the TAVI application |
| **[2] Update TAVI** | Fetch and check out the pinned release from GitHub |
| **[3] Open TAVI folder** | Browse installation files |
| **[4] Open TAVI shell** | Command prompt with compiler environment bootstrapped |
| **[5] Exit** | Close the launcher |

### Direct Scripts

These scripts are installed in `%USERPROFILE%\TAVI`:

| Script | Purpose |
|--------|---------|
| `TAVI-Launcher.bat` | Menu launcher (recommended entry point) |
| `run-tavi.bat` | Launch TAVI directly |
| `update-tavi.bat` | Update to the pinned release |
| `tavi-bootstrap.bat` | Shared bootstrap helper — do not run directly |

All launcher scripts call `tavi-bootstrap.bat`, which initialises the Visual Studio compiler environment (`vcvarsall.bat x64`) and injects MPI paths before starting TAVI. This is what allows McStas to compile on first run.

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
2. Re-run `WINDOWS-install-TAVI.bat` — it will detect the newly installed compiler

### Simulation fails to compile on first run

Make sure you are launching from `TAVI-Launcher.bat` or `run-tavi.bat` (not by running `python TAVI_PySide6.py` directly in a plain command prompt). These scripts call `tavi-bootstrap.bat`, which sets up the compiler environment before TAVI starts.

If you bypassed the compiler check during installation, re-run the installer with Visual Studio installed to regenerate the launcher scripts with a working bootstrap.

### "MPI launcher could not be resolved" in message center

This indicates an NMO/MPI workflow is active but the Microsoft MPI SDK is not installed or was not found at install time. Install the MPI SDK (see Prerequisites) and re-run `WINDOWS-install-TAVI.bat` to regenerate the launcher scripts with MPI paths included.

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

Note: this bypasses the compiler bootstrap in `tavi-bootstrap.bat`. Simulations may fail to compile unless the Visual Studio environment is already active in the calling shell.

### Updating McStas (conda)

```batch
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe install -n tavi mcstas mcstas-core -c conda-forge -y
```

### Uninstalling TAVI

Run `WINDOWS-uninstall-TAVI.bat` from the installer folder. It will:

1. Remove the `tavi` conda environment
2. Ask whether to also remove micromamba (useful if you have no other environments)
3. Remove the TAVI code directory
4. Remove the desktop shortcut

It will not touch Visual Studio, the MPI SDK, or any other micromamba environments you may have.

---

## Technical Notes

### Why micromamba instead of conda?

Faster installation and environment solving, smaller footprint, and better handling of complex dependency chains like McStas.

### Why PySide6 via pip?

PySide6 is not officially distributed via conda-forge by the Qt Project. The pip version is better maintained and avoids Qt library conflicts.

### Compiler bootstrap rationale

McStas generates and compiles C instrument files at runtime. The compiler must be available in the process environment when `mcrun` is called. The generated launcher scripts call `vcvarsall.bat x64` before starting TAVI, which sets `PATH`, `INCLUDE`, `LIB`, and related variables so `cl.exe` is available to McStas. Launching TAVI directly with `python TAVI_PySide6.py` in a plain shell bypasses this and will cause first-point compile failures.

### mcstas_config.json and runtimes.json

TAVI stores local McStas path configuration in `config/mcstas_config.json` and per-scan runtime estimates in `config/runtimes.json`. These are generated at runtime and should not be edited manually unless you need to override a specific McStas path.

### Installation paths

| Item | Location |
|------|----------|
| micromamba binary | `%USERPROFILE%\AppData\Local\micromamba\micromamba.exe` |
| tavi conda environment | `%USERPROFILE%\AppData\Local\micromamba\envs\tavi\` |
| TAVI code | `%USERPROFILE%\TAVI\` |
| Launcher scripts | `%USERPROFILE%\TAVI\*.bat` |
| Simulation output | `%USERPROFILE%\TAVI\output\` |

---

## Getting Help

- **TAVI issues**: https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
- **McStas documentation**: https://www.mcstas.org/
- **McStasScript documentation**: https://mads-bertelsen.github.io/

---

*Last updated: May 2026*
