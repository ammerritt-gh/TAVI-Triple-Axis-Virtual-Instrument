"""The instrument registry (``docs/CONFIGURABLE_INSTRUMENTS.md`` §5, §17).

Built-in instruments register in ``instruments/builtin.py``, which ``main()``
imports once at startup.

Thin and explicit: instruments register a zero-arg *factory* (not an eager
instance) so importing the registry does not pull in PySide6 / McStasScript until
an instrument is actually selected. The active instrument is chosen at startup and
fixed for the session (decided -- §7.1 / §12.3), so the controller resolves it once.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from instruments.contract import InstrumentPlugin


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    """Lightweight entry for the startup instrument picker."""

    id: str
    display_name: str


_FACTORIES: dict[str, Callable[[], InstrumentPlugin]] = {}
_DISPLAY_NAMES: dict[str, str] = {}


def register(
    instrument_id: str,
    display_name: str,
    factory: Callable[[], InstrumentPlugin],
) -> None:
    """Register an instrument by id. ``factory`` returns a fresh ``InstrumentPlugin``."""
    if instrument_id in _FACTORIES:
        raise ValueError(f"Instrument id already registered: {instrument_id!r}")
    _FACTORIES[instrument_id] = factory
    _DISPLAY_NAMES[instrument_id] = display_name


def available_instruments() -> list[InstrumentInfo]:
    """Return registered instruments (for the startup picker), sorted by id."""
    return [InstrumentInfo(i, _DISPLAY_NAMES[i]) for i in sorted(_FACTORIES)]


def get_instrument(instrument_id: str) -> InstrumentPlugin:
    """Resolve and instantiate the instrument with the given id."""
    try:
        factory = _FACTORIES[instrument_id]
    except KeyError:
        known = ", ".join(sorted(_FACTORIES)) or "(none registered)"
        raise KeyError(
            f"Unknown instrument {instrument_id!r}. Available: {known}"
        ) from None
    return factory()


# --- Remembered instrument selection ----------------------------------------
#
# The id of the last-resolved instrument is persisted so the next launch reopens
# the same instrument (docs/CONFIGURABLE_INSTRUMENTS.md §7.1). This lives here,
# beside the registry it references, and stays Qt-free. The file is local
# generated state (like config/api_config.json), not a project fixture.

_SELECTION_FILENAME = "instrument_selection.json"


def _selection_config_path(config_path=None) -> Path:
    """Resolve the selection config path (default: ``config/`` under repo root)."""
    if config_path is not None:
        return Path(config_path)
    return Path(__file__).resolve().parent.parent / "config" / _SELECTION_FILENAME


def load_last_instrument(
    valid_ids: Iterable[str] | None = None,
    config_path=None,
) -> str | None:
    """Return the saved last-instrument id, or ``None`` if unavailable.

    An absent file yields ``None`` silently. Corrupt/unreadable JSON yields
    ``None`` with a one-line console warning (no silent swallowing). If
    ``valid_ids`` is given, a saved id that is not among them is treated as
    stale and ignored (returns ``None``, no warning).
    """
    path = _selection_config_path(config_path)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[TAVI] Warning: Could not parse {path}: {e}; ignoring saved instrument")
        return None

    if not isinstance(data, dict):
        print(f"[TAVI] Warning: {path} is not a JSON object; ignoring saved instrument")
        return None

    saved = data.get("last_instrument")
    if not isinstance(saved, str) or not saved:
        return None
    if valid_ids is not None and saved not in set(valid_ids):
        return None
    return saved


def save_last_instrument(instrument_id: str, config_path=None) -> None:
    """Persist ``instrument_id`` as the last-selected instrument."""
    path = _selection_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_instrument": instrument_id}, f, indent=2)
