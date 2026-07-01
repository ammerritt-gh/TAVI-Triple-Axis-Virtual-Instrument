"""Phase-0 DRAFT: the instrument registry.

Design sketch for the configurable-instruments effort
(see ``docs/CONFIGURABLE_INSTRUMENTS.md`` §5). **Nothing registers with it yet.**

Thin and explicit: instruments register a zero-arg *factory* (not an eager
instance) so importing the registry does not pull in PySide6 / McStasScript until
an instrument is actually selected. The active instrument is chosen at startup and
fixed for the session (decided -- §7.1 / §12.3), so the controller resolves it once.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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
