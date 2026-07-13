"""Reflection-table parsing and centering-rule fallback for reciprocal views."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import math
from fractions import Fraction


@dataclass(frozen=True)
class Reflection:
    h: float
    k: float
    l: float
    f_squared: float | None = None

@dataclass(frozen=True)
class ProjectedReflection:
    qx: float; qy: float; f_squared: float | None; hkl_label: str; qz: float

def primitive_miller(h: float, k: float, l: float, tolerance: float = 1e-8):
    """Canonicalise proportional rational HKL, else decimal-normalise by max.

    A half-integer vector such as ``(.5, 2, -2)`` becomes ``(1, 4, -4)``;
    irrational directions intentionally retain a bounded decimal representation.
    """
    values = (float(h), float(k), float(l))
    fractions = [Fraction(value).limit_denominator(96) for value in values]
    if all(abs(float(frac) - value) <= tolerance for frac, value in zip(fractions, values)):
        denominator = math.lcm(*(frac.denominator for frac in fractions))
        integers = tuple(int(frac * denominator) for frac in fractions)
        divisor = math.gcd(math.gcd(abs(integers[0]), abs(integers[1])), abs(integers[2])) or 1
        return tuple(value // divisor for value in integers)
    maximum = max(abs(value) for value in values) or 1.0
    return tuple(round(value / maximum, 6) for value in values)


def load_reflections(path: str | Path) -> list[Reflection]:
    """Read usable McStas LAU/LAZ reflections with a positive finite F2.

    ``column_F2`` metadata is one-based.  Without metadata, the conventional
    fourth column is used.  HKL-only or otherwise unusable tables are rejected
    so callers can fall back to the selected space group's centering rule
    without claiming structure-factor filtering.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"reflection table not found: {source}")
    reflections = []
    f2_column = None
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            metadata = re.search(r"#\s*column_F2\s+(\d+)", line, re.IGNORECASE)
            if metadata:
                column_number = int(metadata.group(1))
                if column_number < 4:
                    raise ValueError("column_F2 must identify column 4 or later")
                f2_column = column_number - 1  # table metadata is 1-based
                continue
            values = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", line.split("#", 1)[0])
            if len(values) < 3:
                continue
            try:
                h, k, l = (float(value) for value in values[:3])
                index = f2_column if f2_column is not None else 3
                if len(values) <= index:
                    continue
                f2 = float(values[index])
            except (ValueError, IndexError):
                continue
            if not all(math.isfinite(value) for value in (h, k, l, f2)) or f2 <= 0.0:
                continue
            reflections.append(Reflection(h, k, l, f2))
    if not reflections:
        raise ValueError(f"reflection table contains no usable positive F2 rows: {source}")
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


def reflection_label_is_clear(position, used_positions, width: float, height: float,
                              minimum_distance: float = 22.0) -> bool:
    """Screen-space label decluttering shared by all visible reflection strengths."""
    x, y = position
    return (
        12 < x < width - 35
        and 12 < y < height - 12
        and all(math.dist((x, y), other) > minimum_distance for other in used_positions)
    )
