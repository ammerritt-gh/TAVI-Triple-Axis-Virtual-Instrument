"""Machine-level preferences set from the Config menu (``config/settings.json``).

Local state, not a project fixture: no setup script writes this file, so a
choice made here survives reinstalling the environment.
"""
import json

from instruments.contract import DEFAULT_MPI_COUNT
from tavi.local_state import config_path

SETTINGS_FILENAME = "settings.json"
MPI_COUNT_MAX = 256


def _path():
    return config_path(SETTINGS_FILENAME)


def _read() -> dict:
    """The settings object; ``{}`` when absent, unreadable or not an object."""
    path = _path()
    if not path.exists():
        return {}
    try:
        # utf-8-sig: a hand-written file from Windows PowerShell may carry a BOM.
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:  # ValueError: bad JSON or not UTF-8
        print(f"[TAVI] Warning: Could not parse {path}: {e}; using default settings")
        return {}
    if not isinstance(data, dict):
        print(f"[TAVI] Warning: {path} is not a JSON object; using default settings")
        return {}
    return data


def load_mpi_count() -> int:
    """The configured MPI process count, or ``DEFAULT_MPI_COUNT``."""
    data = _read()
    if "mpi_count" not in data:
        return DEFAULT_MPI_COUNT
    n = data["mpi_count"]
    if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= MPI_COUNT_MAX:
        return n
    print(f"[TAVI] Warning: mpi_count {n!r} in {_path()} is not an integer "
          f"1-{MPI_COUNT_MAX}; using {DEFAULT_MPI_COUNT}")
    return DEFAULT_MPI_COUNT


def save_mpi_count(n: int) -> None:
    """Persist ``n``, keeping any other keys. ``OSError`` propagates."""
    data = _read()
    data["mpi_count"] = int(n)
    with open(_path(), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
