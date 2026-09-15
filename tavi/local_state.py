"""Where TAVI keeps its local, generated state.

``config/`` under the repository root, or ``TAVI_CONFIG_DIR`` when that
environment variable is set. The override exists so the test suite can
point every reader and writer at a throwaway copy (root ``conftest.py``);
it is not an operator setting.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """The directory holding local state; created on demand."""
    override = os.environ.get("TAVI_CONFIG_DIR")
    path = Path(override) if override else REPO_ROOT / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path(name: str) -> Path:
    """Absolute path of one local-state file, e.g. ``parameters.json``."""
    return config_dir() / name
