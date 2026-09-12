# TAVI McStas Path Resolution — Proposed Solution

## The Problem

When running TAVI from your development checkout (`C:\Users\AMM\Documents\Github\Science\TAVI`) rather than through the micromamba installer environment, McStasScript can't find your standalone McStas 3.5.16 installation at `C:\mcstas-3.5.16`. This happens because:

1. **McStasScript's `Configurator`** stores paths in a user-level YAML file (`~/.mcstasscript/configuration.yaml`). If that file doesn't exist or points to a different installation, it silently fails to find `mcrun`, the compiler toolchain, and the standard component library.

2. **Windows PATH isn't enough** — McStasScript doesn't search PATH for `mcrun`. It only checks its own config file and a few hardcoded default locations (typically `/usr/local/mcstas/...` on Linux or the conda env prefix).

3. **The installer script** configures McStasScript correctly *within the micromamba `tavi` env*, but that configuration doesn't carry over to your separate Python installation.

## Proposed Solution: A Local `mcstas_config.json` + Startup Configurator

Rather than relying on the global McStasScript config or environment variables, TAVI can ship its own local config file and apply it at startup. This is clean, portable, and works regardless of how TAVI is launched.

### 1. Add `config/mcstas_config.json`

```json
{
    "mcstas_path": null,
    "mcrun_path": null,
    "auto_detect": true,
    "search_paths": [
        "C:/mcstas-3.5.16",
        "C:/mcstas-3.5",
        "C:/mcstas-3.4",
        "C:/mcstas"
    ],
    "_comment": "Set mcstas_path and mcrun_path explicitly to skip auto-detection. mcstas_path should point to the 'resources' folder containing standard components (e.g. C:/mcstas-3.5.16/lib/mcstas/3.5.16). mcrun_path should point to the folder containing mcrun.bat (e.g. C:/mcstas-3.5.16/bin)."
}
```

### 2. Add `tavi/mcstas_config.py` — the detection/configuration module

```python
"""McStas path detection and McStasScript configuration for TAVI.

This module finds a McStas installation and configures McStasScript at import
time, so that ms.McStas_instr() calls work regardless of how TAVI is launched.

Resolution order:
  1. Explicit paths in config/mcstas_config.json
  2. Auto-detection from known Windows install locations
  3. Conda/micromamba environment (the installer's approach)
  4. System PATH fallback
"""

import json
import os
import sys
import glob
import shutil
from pathlib import Path


def _find_project_root():
    """Walk up from this file to find the TAVI project root (contains TAVI_PySide6.py)."""
    d = Path(__file__).resolve().parent
    for _ in range(5):
        if (d / "TAVI_PySide6.py").exists():
            return d
        d = d.parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _find_project_root()
CONFIG_FILE = PROJECT_ROOT / "config" / "mcstas_config.json"


def _load_local_config():
    """Load the local mcstas_config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[TAVI] Warning: Could not parse {CONFIG_FILE}: {e}")
    return {}


def _probe_standalone_install(base_dir):
    """Given a McStas base directory (e.g. C:/mcstas-3.5.16), find mcrun and resources.
    
    Returns (mcrun_path, mcstas_path) or (None, None).
    
    Standalone Windows McStas typically has:
        base/bin/mcrun.bat          (or mcrun.exe, mcrun.pl)
        base/lib/mcstas/<version>/  (the 'resources' folder with standard .comp files)
    """
    base = Path(base_dir)
    if not base.is_dir():
        return None, None

    # Find mcrun
    bin_dir = base / "bin"
    mcrun = None
    if bin_dir.is_dir():
        for candidate in ["mcrun.bat", "mcrun.exe", "mcrun", "mcrun.pl"]:
            if (bin_dir / candidate).exists():
                mcrun = str(bin_dir)
                break

    # Find component resources
    lib_base = base / "lib" / "mcstas"
    mcstas_resources = None
    if lib_base.is_dir():
        # Look for versioned subdirectory (e.g. lib/mcstas/3.5.16/)
        versions = sorted(lib_base.iterdir(), reverse=True)
        for v in versions:
            if v.is_dir() and (v / "misc").exists():
                # This looks like a valid resources dir (has misc/, share/, etc.)
                mcstas_resources = str(v)
                break
        if mcstas_resources is None:
            # Maybe resources are directly in lib/mcstas/
            if (lib_base / "misc").exists():
                mcstas_resources = str(lib_base)

    # Also check share/mcstas/resources (conda-style layout)
    if mcstas_resources is None:
        share_resources = base / "share" / "mcstas" / "resources"
        if share_resources.is_dir():
            mcstas_resources = str(share_resources)
        # Windows conda variant
        share_resources_alt = base / "Library" / "share" / "mcstas" / "resources"
        if share_resources_alt.is_dir():
            mcstas_resources = str(share_resources_alt)

    return mcrun, mcstas_resources


def _probe_conda_env():
    """Check if we're running inside a conda/micromamba env with McStas installed."""
    env_prefix = Path(sys.prefix)
    return _probe_standalone_install(env_prefix)


def _search_path_for_mcrun():
    """Try to find mcrun on the system PATH."""
    mcrun = shutil.which("mcrun") or shutil.which("mcrun.bat")
    if mcrun:
        return str(Path(mcrun).parent)
    return None


def _search_windows_default_locations():
    """Scan common Windows McStas install locations."""
    patterns = [
        "C:/mcstas-*",
        "C:/Program Files/mcstas-*",
        "C:/Program Files (x86)/mcstas-*",
        os.path.expanduser("~/mcstas-*"),
    ]
    candidates = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    # Sort descending so newest version is tried first
    candidates.sort(reverse=True)
    return candidates


def detect_mcstas():
    """Detect McStas installation and return (mcrun_path, mcstas_path).
    
    Tries multiple strategies in order of priority.
    """
    config = _load_local_config()

    # Strategy 1: Explicit paths from config file
    explicit_mcrun = config.get("mcrun_path")
    explicit_mcstas = config.get("mcstas_path")
    if explicit_mcrun and explicit_mcstas:
        if Path(explicit_mcrun).is_dir() and Path(explicit_mcstas).is_dir():
            print(f"[TAVI] Using explicit McStas config: mcrun={explicit_mcrun}, lib={explicit_mcstas}")
            return explicit_mcrun, explicit_mcstas
        else:
            print(f"[TAVI] Warning: Explicit paths in mcstas_config.json don't exist, falling through to auto-detect")

    if not config.get("auto_detect", True):
        print("[TAVI] Warning: auto_detect is disabled and explicit paths are invalid/missing")
        return None, None

    # Strategy 2: Search configured paths
    search_paths = config.get("search_paths", [])
    for sp in search_paths:
        mcrun, mcstas = _probe_standalone_install(sp)
        if mcrun and mcstas:
            print(f"[TAVI] Found McStas at configured search path: {sp}")
            return mcrun, mcstas

    # Strategy 3: Scan Windows default locations
    for candidate in _search_windows_default_locations():
        mcrun, mcstas = _probe_standalone_install(candidate)
        if mcrun and mcstas:
            print(f"[TAVI] Found McStas at: {candidate}")
            return mcrun, mcstas

    # Strategy 4: Conda/micromamba environment
    mcrun, mcstas = _probe_conda_env()
    if mcrun and mcstas:
        print(f"[TAVI] Found McStas in conda environment: {sys.prefix}")
        return mcrun, mcstas

    # Strategy 5: System PATH
    mcrun = _search_path_for_mcrun()
    if mcrun:
        print(f"[TAVI] Found mcrun on PATH: {mcrun}")
        # We have mcrun but not necessarily the lib path — try parent
        parent = Path(mcrun).parent
        _, mcstas = _probe_standalone_install(parent)
        return mcrun, mcstas

    print("[TAVI] Warning: Could not find McStas installation")
    return None, None


def configure_mcstasscript(mcrun_path=None, mcstas_path=None):
    """Apply detected paths to McStasScript's Configurator.
    
    Call this once at application startup, before any ms.McStas_instr() calls.
    """
    try:
        import mcstasscript as ms
    except ImportError:
        print("[TAVI] Error: mcstasscript is not installed")
        return False

    if mcrun_path is None or mcstas_path is None:
        mcrun_path, mcstas_path = detect_mcstas()

    if mcrun_path is None or mcstas_path is None:
        print("[TAVI] Error: Cannot configure McStasScript — McStas not found")
        print("[TAVI]   Edit config/mcstas_config.json with your McStas paths")
        return False

    try:
        configurator = ms.Configurator()
        configurator.set_mcrun_path(mcrun_path)
        configurator.set_mcstas_path(mcstas_path)
        print(f"[TAVI] McStasScript configured:")
        print(f"[TAVI]   mcrun:  {mcrun_path}")
        print(f"[TAVI]   mcstas: {mcstas_path}")
        return True
    except Exception as e:
        print(f"[TAVI] Error configuring McStasScript: {e}")
        return False


# Auto-configure on import
_configured = configure_mcstasscript()
```

### 3. Wire it into `TAVI_PySide6.py`

Add one line near the top of `TAVI_PySide6.py`, **before** the `import mcstasscript as ms` line:

```python
# Configure McStas paths before importing mcstasscript
import tavi.mcstas_config  # noqa: F401 — side-effect import, configures McStasScript

import mcstasscript as ms
```

That's it. The import triggers auto-detection and applies the paths to McStasScript's configurator before any instrument code runs.

### 4. For your specific setup

For your `C:\mcstas-3.5.16` installation, the auto-detection should pick it up automatically since `C:/mcstas-3.5.16` is in the default `search_paths`. But if the directory layout differs from what `_probe_standalone_install` expects, you can set explicit paths in `config/mcstas_config.json`:

```json
{
    "mcstas_path": "C:/mcstas-3.5.16/lib/mcstas/3.5.16",
    "mcrun_path": "C:/mcstas-3.5.16/bin",
    "auto_detect": true
}
```

You'd want to verify the actual directory structure. The key things to check:

- **`mcrun_path`**: the folder containing `mcrun.bat` (or `mcrun.exe`)
- **`mcstas_path`**: the folder containing the standard `.comp` files and `misc/` subdirectory — this is typically something like `C:/mcstas-3.5.16/lib/mcstas/3.5.16/` for a standalone install

## Why Not a Virtual Environment?

A venv/virtualenv alone doesn't solve the McStas problem because:

1. **McStas isn't a pip package** — the core `mcrun` binary, the C compiler pipeline, and the standard `.comp` component library are native-code artifacts. They can't be `pip install`ed into a venv.

2. **The micromamba approach already works** — your installer creates a proper conda environment with McStas from conda-forge. That's essentially the "virtual environment" solution, and it handles the native dependencies correctly.

3. **What you actually need for development** is a way for TAVI to *find* the McStas installation that already exists on your system. The local config approach above does exactly this without requiring any environment setup.

If you did want a venv for Python dependency isolation during development, you could create one and install the Python dependencies into it, but you'd still need the config approach above to find McStas itself:

```batch
cd C:\Users\AMM\Documents\Github\Science\TAVI
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The `mcstas_config.py` module would work the same way inside the venv.

## Integration with the Existing Installer

The installer (`WINDOWS-install-TAVI.bat`) already configures McStasScript via the micromamba env. The local config approach doesn't conflict — it just adds a fallback chain that also works outside the managed env. If someone runs TAVI through the installer's launcher, the conda env detection (Strategy 4) kicks in and everything works as before.

## `.gitignore` Consideration

If you want each developer to have their own McStas paths without checking them in, you could `.gitignore` the config file and ship a template:

```
# In .gitignore
config/mcstas_config.json

# Ship a template instead
config/mcstas_config.json.example
```

Alternatively, since the auto-detection covers the most common cases, you could check in the config with `null` paths (as shown above) and let auto-detect handle it — only requiring manual config for unusual setups.
