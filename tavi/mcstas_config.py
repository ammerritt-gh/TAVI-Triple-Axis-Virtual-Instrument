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
import shlex
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

_MPI_PLACEHOLDER_TOKENS = {
    "%*",
    "%n",
    "%N",
    "%exe",
    "%EXE",
    "%arg",
    "%ARG",
    "%args",
    "%ARGS",
    "{NP}",
    "${NP}",
    "${ARGS}",
    "${EXE}",
}


def _load_local_config():
    """Load the local mcstas_config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[TAVI] Warning: Could not parse {CONFIG_FILE}: {e}")
    return {}


def _get_mcstasscript_config_path():
    """Return McStasScript's configuration.yaml path if mcstasscript is importable."""
    try:
        import mcstasscript as ms
    except ImportError:
        return None

    return Path(ms.__file__).resolve().parent / "configuration.yaml"


def _parse_simple_yaml(path):
    """Parse simple top-level key/value YAML entries used by McStasScript config."""
    data = {}
    if path is None or not path.exists():
        return data

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip('"').strip("'")
                data[key.strip()] = value
    except OSError as e:
        print(f"[TAVI] Warning: Could not read McStasScript config {path}: {e}")

    return data


def _tokenize_command(command):
    """Split a command string into argv tokens without using a shell."""
    return shlex.split(command, posix=os.name != "nt")


def _normalize_mpi_launcher_argv(command):
    """Strip MPI size placeholders so callers can append their own -np and args."""
    if not command:
        return []

    try:
        tokens = _tokenize_command(command)
    except ValueError as e:
        print(f"[TAVI] Warning: Could not parse MPI launcher command '{command}': {e}")
        return []

    normalized = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue

        stripped = token.strip()
        lower = stripped.lower()
        if stripped in _MPI_PLACEHOLDER_TOKENS:
            continue
        if lower in {"-np", "--np", "/np", "-n", "--n", "/n"}:
            skip_next = True
            continue
        if lower in {"-machinefile", "--machinefile", "-hostfile", "--hostfile"}:
            normalized.append(stripped)
            skip_next = True
            continue
        normalized.append(stripped)

    return normalized


def _candidate_mccode_config_paths(mcrun_path, mcstas_path):
    """Yield likely mccode_config.json locations for a detected McStas install."""
    seen = set()
    search_roots = []

    if mcstas_path:
        search_roots.append(Path(mcstas_path))
        search_roots.append(Path(mcstas_path).parent)
    if mcrun_path:
        search_roots.append(Path(mcrun_path))
        search_roots.append(Path(mcrun_path).parent)

    for root in search_roots:
        for candidate in (
            root / "mccode_config.json",
            root / "misc" / "mccode_config.json",
            root / "resources" / "mccode_config.json",
        ):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            for candidate in root.rglob("mccode_config.json"):
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate
                    return
        except OSError:
            continue


def _read_mpirun_from_mccode_config(mcrun_path, mcstas_path):
    """Read the MPIRUN command from the nearest mccode_config.json if available."""
    for config_path in _candidate_mccode_config_paths(mcrun_path, mcstas_path):
        if not config_path.exists():
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[TAVI] Warning: Could not read {config_path}: {e}")
            continue

        if isinstance(payload, dict):
            # Conda-packaged McStas (3.4.65+) nests MPIRUN under a section
            # (e.g. {"run": {"MPIRUN": "mpiexec"}}); older configs are flat.
            sections = [payload] + [
                value for value in payload.values() if isinstance(value, dict)
            ]
            for section in sections:
                command = section.get("MPIRUN")
                if isinstance(command, str) and command.strip():
                    return command.strip()
    return None


def _find_mpiexec_near_mcrun(mcrun_path):
    """Look for a direct mpiexec binary in the detected McStas bin directory."""
    if not mcrun_path:
        return None

    bin_dir = Path(mcrun_path)
    for candidate in ("mpiexec.exe", "mpiexec"):
        exe_path = bin_dir / candidate
        if exe_path.exists():
            return str(exe_path)
    return None


def _prefer_direct_mpi_binary(argv, mcrun_path):
    """Replace wrapper batch launchers with a direct mpiexec binary when available."""
    if not argv:
        return []

    launcher_name = Path(argv[0]).name.lower()
    mpiexec_path = _find_mpiexec_near_mcrun(mcrun_path)
    if launcher_name.endswith((".bat", ".cmd")) or launcher_name.startswith("mpirun"):
        if mpiexec_path:
            return [mpiexec_path, *argv[1:]]

    if mpiexec_path and not Path(argv[0]).is_absolute() and launcher_name.startswith("mpiexec"):
        return [mpiexec_path, *argv[1:]]

    if not Path(argv[0]).is_absolute():
        # Direct execution bypasses the shell, so resolve a bare launcher name
        # (e.g. "mpiexec" from mccode_config.json) against PATH.
        resolved = shutil.which(argv[0])
        if resolved:
            return [resolved, *argv[1:]]

    return argv


def resolve_mpi_launcher_argv():
    """Return the MPI launcher argv prefix for direct McStas execution.

    The returned list excludes any size placeholders so the caller can append
    '-np', the compiled binary path, and runtime arguments directly.
    """
    yaml_config = _parse_simple_yaml(_get_mcstasscript_config_path())
    yaml_mcrun_path = yaml_config.get("mcrun_path")

    detected_mcrun_path, detected_mcstas_path = detect_mcstas()
    candidates = []
    if yaml_mcrun_path:
        candidates.append((yaml_mcrun_path, None))
    candidates.append((detected_mcrun_path, detected_mcstas_path))

    seen = set()
    for mcrun_path, mcstas_path in candidates:
        key = (mcrun_path, mcstas_path)
        if key in seen or not mcrun_path:
            continue
        seen.add(key)

        command = _read_mpirun_from_mccode_config(mcrun_path, mcstas_path)
        if command:
            argv = _prefer_direct_mpi_binary(_normalize_mpi_launcher_argv(command), mcrun_path)
            if argv:
                return argv

        mpiexec_path = _find_mpiexec_near_mcrun(mcrun_path)
        if mpiexec_path:
            return [mpiexec_path]

    return []


def _probe_standalone_install(base_dir):
    """Given a McStas base directory (e.g. C:/mcstas-3.5.16 or a conda env), find mcrun and resources.

    Returns (mcrun_path, mcstas_path) or (None, None).

    Handles several Windows McStas layouts:
        base/bin/mcrun.bat
        base/Library/bin/mcrun.bat  (Windows conda/micromamba)
        base/Scripts/mcrun.bat      (some Python/conda layouts)
        base/lib/                   (components directly here — misc/ present)
        base/lib/mcstas/<ver>/      (versioned subdirectory — misc/ present)
        base/share/mcstas/resources/
        base/Library/share/mcstas/resources/
    """
    base = Path(base_dir)
    if not base.is_dir():
        return None, None

    # --- Find mcrun ---
    mcrun = None
    for bin_dir in (base / "Library" / "bin", base / "Scripts", base / "bin"):
        if not bin_dir.is_dir():
            continue
        for candidate in ["mcrun.bat", "mcrun.exe", "mcrun", "mcrun.pl"]:
            if (bin_dir / candidate).exists():
                mcrun = str(bin_dir)
                break
        if mcrun:
            break

    # --- Find component resources ---
    mcstas_resources = None

    # Layout 1: components directly in base/lib/ (e.g. C:/mcstas-3.5.16/lib/)
    lib_direct = base / "lib"
    if lib_direct.is_dir() and (lib_direct / "misc").exists():
        mcstas_resources = str(lib_direct)

    # Layout 2: base/lib/mcstas/<version>/ (versioned subdirectory)
    if mcstas_resources is None:
        lib_mcstas = base / "lib" / "mcstas"
        if lib_mcstas.is_dir():
            versions = sorted(lib_mcstas.iterdir(), reverse=True)
            for v in versions:
                if v.is_dir() and (v / "misc").exists():
                    mcstas_resources = str(v)
                    break
            if mcstas_resources is None and (lib_mcstas / "misc").exists():
                mcstas_resources = str(lib_mcstas)

    # Layout 3: conda-style base/share/mcstas/resources/
    if mcstas_resources is None:
        share_resources = base / "share" / "mcstas" / "resources"
        if share_resources.is_dir():
            mcstas_resources = str(share_resources)

    # Layout 4: Windows conda variant base/Library/share/mcstas/resources/
    if mcstas_resources is None:
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


def _normalize_mcstas_resources_path(path):
    """Return the actual component resources directory for a McStas path-like value."""
    if not path:
        return None
    p = Path(path)
    candidates = [
        p,
        p / "resources",
        p / "share" / "mcstas" / "resources",
        p / "Library" / "share" / "mcstas" / "resources",
    ]
    for candidate in candidates:
        if candidate.is_dir() and ((candidate / "misc").exists() or (candidate / "monitors").exists() or (candidate / "sources").exists()):
            return str(candidate)
    return str(p) if p.is_dir() else None


def _has_mcstas_component(mcstas_path, component_name):
    """Check whether a McStas component .comp file is visible under a resources path."""
    root = _normalize_mcstas_resources_path(mcstas_path)
    if not root:
        return False
    try:
        return any(Path(root).rglob(component_name + ".comp"))
    except OSError:
        return False


def detect_mcstas():
    """Detect McStas installation and return (mcrun_path, mcstas_path).

    Tries multiple strategies in order of priority.
    """
    config = _load_local_config()

    # Strategy 0: Explicit environment variable from launcher/user.
    env_mcstas = os.environ.get("MCSTAS") or os.environ.get("MCSTAS_COMPONENT_PATH")
    env_mcstas = _normalize_mcstas_resources_path(env_mcstas)
    if env_mcstas:
        mcrun, _ = _probe_conda_env()
        if mcrun:
            print(f"[TAVI] Using McStas from environment: {env_mcstas}")
            return mcrun, env_mcstas

    # Strategy 1: Explicit paths from config file
    explicit_mcrun = config.get("mcrun_path")
    explicit_mcstas = _normalize_mcstas_resources_path(config.get("mcstas_path"))
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
        parent = Path(mcrun).parent
        _, mcstas = _probe_standalone_install(parent)
        return mcrun, mcstas

    print("[TAVI] Warning: Could not find McStas installation")
    return None, None


def configure_mcstasscript(mcrun_path=None, mcstas_path=None):
    """Apply detected paths to McStasScript's Configurator.

    Call this once at application startup, before any ms.McStas_instr() calls.
    """
    if mcrun_path is None or mcstas_path is None:
        mcrun_path, mcstas_path = detect_mcstas()

    mcstas_path = _normalize_mcstas_resources_path(mcstas_path)

    if mcrun_path is None or mcstas_path is None:
        print("[TAVI] Error: Cannot configure McStasScript — McStas not found")
        print("[TAVI]   Edit config/mcstas_config.json with your McStas paths")
        return False

    # Set environment variables before importing/using McStasScript. Some McStasScript
    # internals read these directly when constructing component readers.
    os.environ["MCSTAS"] = str(mcstas_path)
    os.environ["MCSTAS_COMPONENT_PATH"] = str(mcstas_path)

    try:
        import mcstasscript as ms
    except ImportError:
        print("[TAVI] Error: mcstasscript is not installed")
        return False

    try:
        configurator = ms.Configurator()
        configurator.set_mcrun_path(mcrun_path)
        configurator.set_mcstas_path(mcstas_path)
        print(f"[TAVI] McStasScript configured:")
        print(f"[TAVI]   mcrun:  {mcrun_path}")
        print(f"[TAVI]   mcstas: {mcstas_path}")
        if not _has_mcstas_component(mcstas_path, "Progress_bar"):
            print(f"[TAVI] Warning: Progress_bar.comp was not found under {mcstas_path}")
        return True
    except Exception as e:
        print(f"[TAVI] Error configuring McStasScript: {e}")
        return False


# Auto-configure on import
_configured = configure_mcstasscript()
