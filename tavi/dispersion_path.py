"""Reciprocal-space paths through a ``Phonon_DFT`` map (Qt-free).

A path is a sequence of labelled conventional-rlu points; :func:`parse_path`
reads it from text such as ``"Γ X W K Γ L"`` or ``"Γ K (1,1,0)"`` and
:func:`trace_path` evaluates every branch of a loaded map along it, exactly as
the analytic engine does (trilinear, tessellated).  The GUI in
``gui/dispersion_viewer.py`` is a thin layer over these two functions.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from tavi.dispersion_map import DispersionMap

# ponytail: fcc only, both built-in Phonon_DFT samples are fcc; add a per-lattice
# table (bcc, sc, hexagonal) when a non-fcc sample arrives.
SPECIAL_POINTS: dict[str, tuple[float, float, float]] = {
    "Γ": (0.0, 0.0, 0.0),
    "X": (1.0, 0.0, 0.0),
    "W": (1.0, 0.5, 0.0),
    "K": (0.75, 0.75, 0.0),
    "L": (0.5, 0.5, 0.5),
    "U": (1.0, 0.25, 0.25),
}
_ALIASES = {"G": "Γ", "GAMMA": "Γ"}

PRESET_PATHS: dict[str, str] = {
    "fcc standard  Γ–X–W–K–Γ–L–U–W–L–K": "Γ X W K Γ L U W L K",
    "fcc short  Γ–X–W–K–Γ–L": "Γ X W K Γ L",
    "[ζ00]  Γ–X": "Γ X",
    "[ζζ0]  Γ–K–X": "Γ K (1,1,0)",
    "[ζζζ]  Γ–L": "Γ L",
}

_TUPLE_PATTERN = re.compile(r"^\(?\s*([^,\s]+)\s*,\s*([^,\s]+)\s*,\s*([^,\s)]+)\s*\)?$")


class PathError(ValueError):
    """The path text names a point that cannot be resolved."""


def parse_path(text: str) -> list[tuple[str, tuple[float, float, float]]]:
    """Return ``[(label, (h, k, l)), ...]`` from space, dash or arrow separated tokens."""
    cleaned = re.sub(r"\)\s*,\s*\(", ") (", text)          # "(a,b,c),(d,e,f)" -> two tokens
    tokens = [t for t in re.split(r"[\s\-–→>]+", cleaned) if t]
    points = []
    for token in tokens:
        name = _ALIASES.get(token.upper(), token.upper())
        if name in SPECIAL_POINTS:
            points.append((name, SPECIAL_POINTS[name]))
            continue
        match = _TUPLE_PATTERN.match(token)
        if match is None:
            raise PathError(
                f"unknown point {token!r}; use one of {' '.join(SPECIAL_POINTS)} or (h,k,l)"
            )
        try:
            hkl = tuple(float(value) for value in match.groups())
        except ValueError as exc:
            raise PathError(f"non-numeric coordinate in {token!r}") from exc
        points.append(("(" + ",".join(f"{v:g}" for v in hkl) + ")", hkl))
    if len(points) < 2:
        raise PathError("a path needs at least two points")
    return points


@dataclass(frozen=True)
class PathTrace:
    """Branch energies along a path, with tick positions for the named points."""

    distance: np.ndarray      # cumulative path length, rlu
    energies: np.ndarray      # [point, branch], meV
    ticks: list[float]        # distance of each named point
    labels: list[str]


def trace_path(
    dispersion: DispersionMap,
    path: list[tuple[str, tuple[float, float, float]]],
    points_per_segment: int = 200,
) -> PathTrace:
    distance: list[float] = []
    energies: list[list[float]] = []
    ticks = [0.0]
    travelled = 0.0

    def modes(hkl):
        return [m.energy_mev for m in dispersion.evaluate(hkl, tessellate=True)]

    for (_, start), (_, end) in zip(path, path[1:]):
        start_v, end_v = np.asarray(start, float), np.asarray(end, float)
        length = float(np.linalg.norm(end_v - start_v))
        for t in np.linspace(0.0, 1.0, points_per_segment, endpoint=False):
            distance.append(travelled + t * length)
            energies.append(modes(start_v + t * (end_v - start_v)))
        travelled += length
        ticks.append(travelled)
    distance.append(travelled)
    energies.append(modes(path[-1][1]))
    return PathTrace(
        distance=np.asarray(distance),
        energies=np.asarray(energies),
        ticks=ticks,
        labels=[label for label, _ in path],
    )
