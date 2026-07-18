"""Repository paths shared by built-in instrument models."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = str(PROJECT_ROOT / "components")
