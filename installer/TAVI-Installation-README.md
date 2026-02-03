# TAVI Installation Guide
## Triple Axis Virtual Instrument for Windows

TAVI is a simulation tool for triple-axis neutron spectrometers, built on top of McStas. This guide will help you get TAVI running on your Windows computer.

---

## Quick Start

1. **Download** `install-TAVI.bat`
2. **Install Visual Studio Build Tools** (if you don't have a C++ compiler)
3. **Double-click** `install-TAVI.bat` to run the installer
4. **Wait** 10-20 minutes for installation to complete
5. **Use** the "TAVI Launcher" shortcut on your desktop

---

## Prerequisites

### Required: C++ Compiler (Visual Studio Build Tools)

McStas needs a C++ compiler to compile neutron instrument simulations. The easiest way to get this is:

1. Go to: https://visualstudio.microsoft.com/downloads/
2. Scroll down to **"Tools for Visual Studio"**
3. Download **"Build Tools for Visual Studio 2022"**
4. Run the installer
5. Select **"Desktop development with C++"** workload
6. Click Install (requires ~6 GB disk space)

**Alternative**: If you already have Visual Studio 2019 or 2022 installed with C++ tools, you're all set.

### Recommended: Internet Connection

- Required for initial installation (~1-2 GB download)
- Required for updates
- Not required to run simulations after installation

---

## What the Installer Does

The `install-TAVI.bat` script performs these steps automatically:

1. **Checks for C++ compiler** - Warns if not found
2. **Installs micromamba** - A lightweight conda package manager
3. **Creates 'tavi' environment** - With Python 3.11, McStas, and dependencies
4. **Downloads TAVI** - From the GitHub repository
5. **Configures McStasScript** - So it can find McStas
6. **Creates shortcuts** - On your desktop for easy access

### Installed Components

| Component | Purpose |
|-----------|---------|
| micromamba | Package manager (like conda, but faster) |
| McStas | Neutron ray-tracing simulation engine |
| McStasScript | Python API for McStas |
| Python 3.11 | Programming language |
| PySide6 | GUI framework |
| NumPy, SciPy, Matplotlib | Scientific computing libraries |

---

## Using TAVI

### TAVI Launcher

After installation, use the **"TAVI Launcher"** shortcut on your desktop. It provides:

| Option | Description |
|--------|-------------|
| **[1] Run TAVI** | Start the TAVI application |
| **[2] Update TAVI** | Download latest version from GitHub |
| **[3] Open TAVI folder** | Browse installation files |
| **[4] Open TAVI shell** | Command prompt for debugging |
| **[5] Exit** | Close the launcher |

### Direct Scripts

You can also run these scripts directly from the TAVI folder (`%USERPROFILE%\TAVI`):

- `run-tavi.bat` - Runs TAVI directly
- `update-tavi.bat` - Updates TAVI from GitHub
- `TAVI-Launcher.bat` - The menu-based launcher

---

## Troubleshooting

### "C++ compiler not found"

1. Install Visual Studio Build Tools (see Prerequisites above)
2. Restart the installer after installation completes

### "Failed to download micromamba"

- Check your internet connection
- Try running the installer again
- If behind a proxy, configure Windows proxy settings

### "Failed to create environment"

- Check you have ~3 GB free disk space
- Try running the installer as Administrator
- Check your internet connection

### "McStas simulation fails to compile"

1. Make sure Visual Studio Build Tools are installed
2. Run TAVI from the launcher (not directly with Python)
3. The launcher sets up the C++ compiler environment

### "Import error: No module named 'PySide6'"

Run the update option from the TAVI Launcher to reinstall packages.

### TAVI runs but simulations are slow

McStas compiles instrument files on first run. Subsequent runs should be faster.

---

## Advanced Usage

### Manual Environment Activation

To work with the TAVI environment manually:

```batch
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe shell init --shell cmd.exe
:: Close and reopen command prompt, then:
micromamba activate tavi
cd %USERPROFILE%\TAVI
python TAVI_PySide6.py
```

### Updating McStas

To update McStas to the latest version:

```batch
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe update -n tavi mcstas mcstas-core -y
```

### Uninstallation

To remove TAVI completely:

1. Delete `%USERPROFILE%\TAVI` folder
2. Delete `%USERPROFILE%\AppData\Local\micromamba` folder
3. Delete the desktop shortcut

---

## Technical Notes

### Why micromamba instead of conda?

- Faster installation and environment solving
- Smaller footprint
- Better handling of complex dependency chains
- Works well with McStas conda packages

### Why PySide6 via pip instead of conda?

- PySide6 is not officially provided via conda by the Qt Project
- The pip version is better maintained
- Avoids Qt library conflicts with other conda packages

### Installation Paths

| Item | Location |
|------|----------|
| micromamba | `%USERPROFILE%\AppData\Local\micromamba\` |
| TAVI environment | `%USERPROFILE%\AppData\Local\micromamba\envs\tavi\` |
| TAVI code | `%USERPROFILE%\TAVI\` |
| McStas libraries | Inside the tavi environment |

---

## Getting Help

- **TAVI Issues**: https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/issues
- **McStas Documentation**: https://www.mcstas.org/
- **McStasScript Docs**: https://github.com/PaNOSC-ViNYL/McStasScript

---

*Last updated: February 2026*
