"""Reflection-table parsing and centering-rule fallback for reciprocal views."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Reflection:
    h: float
    k: float
    l: float
    f_squared: float | None = None

@dataclass(frozen=True)
class ProjectedReflection:
    qx: float; qy: float; f_squared: float | None; hkl_label: str; qz: float


def load_reflections(path: str | Path) -> list[Reflection]:
    """Read a permissive McStas LAU/LAZ numeric table (H K L ... F2)."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"reflection table not found: {source}")
    reflections = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            values = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", line.split("#", 1)[0])
            if len(values) < 3:
                continue
            try:
                h, k, l = (float(value) for value in values[:3])
                f2 = float(values[-1]) if len(values) >= 4 else None
            except ValueError:
                continue
            reflections.append(Reflection(h, k, l, f2))
    return reflections


def centering_allowed(h: int, k: int, l: int, space_group: int | None) -> bool:
    """Conservative centering-only fallback for common cubic/hexagonal groups.

    It intentionally does not claim structure-factor or screw/glide absences.
    """
    if space_group is None:
        return True
    # F-centred cubic: Fm-3m 225 and related common F groups.
    if 196 <= space_group <= 230:
        return (h % 2 == k % 2 == l % 2)
    # I-centred tetragonal/cubic families.
    if space_group in {79, 80, 82, 87, 88, 97, 98, 107, 108, 109, 110, 119, 120, 121, 122, 139, 140, 141, 142, 197, 199, 204, 206, 211, 214, 217, 220, 229, 230}:
        return (h + k + l) % 2 == 0
    return True


def plane_filtered_unique(projected, qz: float, tolerance: float = 1.0e-5):
    """Keep displayed-plane reflection rows once, preserving first occurrence.

    Returns :class:`ProjectedReflection` rows, preserving the original qz.
    Keeping this policy Qt-free lets the canvas remain a pure renderer.
    """
    seen = set()
    result = []
    for row in projected:
        qx, qy, f_squared, label, reflection_qz = row.qx, row.qy, row.f_squared, row.hkl_label, row.qz
        if abs(reflection_qz - qz) > tolerance:
            continue
        key = (round(qx, 8), round(qy, 8))
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result
