"""Strict, cached access to regular-grid McStas ``Phonon_DFT`` maps.

The public surface is deliberately small: :func:`load_dispersion_map` loads and
validates one file, and :meth:`DispersionMap.evaluate` returns every interpolated
mode at one HKL point. Parsing, cache invalidation, tessellation, interpolation,
linewidth handling, and numerical gradients stay private to this module.

Parsing is vectorised (``numpy.loadtxt`` plus array checks) because a fine
real-crystal map runs to millions of rows; the row-by-row walk survives only
as the diagnostic that names the offending line once ``loadtxt`` has refused a
file.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Iterable

import numpy as np


_HEADER_PATTERN = re.compile(
    r"^\s*#\s*(grid_nx|grid_ny|grid_nz|num_branches)\s+(\S+)\s*$",
    re.IGNORECASE,
)
_HEADER_PREFIX_PATTERN = re.compile(
    r"^\s*#\s*(grid_nx|grid_ny|grid_nz|num_branches)\b",
    re.IGNORECASE,
)
_REGULAR_RTOL = 1.0e-7
_REGULAR_ATOL = 1.0e-10
_BOUNDARY_TOL = 1.0e-10


class DispersionMapError(ValueError):
    """A configured dispersion map is malformed or cannot be evaluated."""


@dataclass(frozen=True, slots=True)
class DispersionMode:
    """One interpolated branch at an HKL point."""

    branch: int
    energy_mev: float
    intensity: float
    linewidth_fwhm_mev: float
    gradient_rlu: tuple[float, float, float]


class DispersionMap:
    """Validated regular H-K-L grid with a dynamic branch dimension."""

    def __init__(
        self,
        *,
        path: Path,
        sha256: str,
        axes: tuple[np.ndarray, np.ndarray, np.ndarray],
        energies: np.ndarray,
        intensities: np.ndarray,
        linewidths: np.ndarray | None,
    ):
        self.path = path
        self.sha256 = sha256
        self._axes = axes
        self._energies = energies
        self._intensities = intensities
        self._linewidths = linewidths
        self.branch_count = int(energies.shape[3])
        self.grid_shape = tuple(int(size) for size in energies.shape[:3])
        self.has_point_linewidths = linewidths is not None

        for array in (*axes, energies, intensities):
            array.setflags(write=False)
        if linewidths is not None:
            linewidths.setflags(write=False)

    def evaluate(
        self,
        hkl: Iterable[float],
        *,
        tessellate: bool,
    ) -> tuple[DispersionMode, ...]:
        """Evaluate all branches at ``hkl``.

        Tessellated queries fold into each grid span using the same minimum/span
        modulo convention as ``pdft_fold_into_grid``. A non-tessellated query
        outside the configured grid returns no modes, matching the McStas
        interpolation refusal used by the component's branch loop.
        """
        point = np.asarray(tuple(hkl), dtype=float)
        if point.shape != (3,) or not np.all(np.isfinite(point)):
            raise DispersionMapError("HKL must contain three finite values")
        prepared = self._prepare_point(point, tessellate=tessellate)
        if prepared is None:
            return ()

        energy, intensity, linewidth = self._interpolate(prepared)
        gradients = self._numerical_gradients(prepared, tessellate=tessellate)
        return tuple(
            DispersionMode(
                branch=branch,
                energy_mev=float(energy[branch]),
                intensity=float(intensity[branch]),
                linewidth_fwhm_mev=float(linewidth[branch]),
                gradient_rlu=tuple(float(value) for value in gradients[:, branch]),
            )
            for branch in range(self.branch_count)
        )

    def _prepare_point(
        self,
        point: np.ndarray,
        *,
        tessellate: bool,
    ) -> np.ndarray | None:
        prepared = point.copy()
        for dimension, axis in enumerate(self._axes):
            minimum = float(axis[0])
            maximum = float(axis[-1])
            span = maximum - minimum
            if tessellate:
                if span > _BOUNDARY_TOL:
                    prepared[dimension] = (
                        (prepared[dimension] - minimum) % span
                    ) + minimum
                else:
                    prepared[dimension] = minimum
            elif (
                prepared[dimension] < minimum - _BOUNDARY_TOL
                or prepared[dimension] > maximum + _BOUNDARY_TOL
            ):
                return None
            else:
                prepared[dimension] = min(
                    maximum, max(minimum, prepared[dimension])
                )
        return prepared

    @staticmethod
    def _cell(axis: np.ndarray, value: float) -> tuple[int, int, float]:
        if len(axis) == 1:
            return 0, 0, 0.0
        if value >= float(axis[-1]) - _BOUNDARY_TOL:
            return len(axis) - 1, 0, 0.0
        lower = int(np.searchsorted(axis, value, side="right") - 1)
        lower = max(0, min(lower, len(axis) - 2))
        upper = lower + 1
        fraction = (value - float(axis[lower])) / float(axis[upper] - axis[lower])
        return lower, upper, min(1.0, max(0.0, float(fraction)))

    def _interpolate(
        self,
        point: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cells = [
            self._cell(axis, float(point[dimension]))
            for dimension, axis in enumerate(self._axes)
        ]

        def interpolate(values: np.ndarray) -> np.ndarray:
            result = np.zeros(self.branch_count, dtype=float)
            for h_corner in (0, 1):
                for k_corner in (0, 1):
                    for l_corner in (0, 1):
                        corners = (h_corner, k_corner, l_corner)
                        indices = tuple(
                            cells[dimension][corner]
                            for dimension, corner in enumerate(corners)
                        )
                        weight = math.prod(
                            (
                                cells[dimension][2]
                                if corner
                                else 1.0 - cells[dimension][2]
                            )
                            for dimension, corner in enumerate(corners)
                        )
                        result += weight * values[indices]
            return result

        linewidths = (
            interpolate(self._linewidths)
            if self._linewidths is not None
            else np.zeros(self.branch_count, dtype=float)
        )
        return (
            interpolate(self._energies),
            interpolate(self._intensities),
            linewidths,
        )

    def _numerical_gradients(
        self,
        point: np.ndarray,
        *,
        tessellate: bool,
    ) -> np.ndarray:
        gradients = np.zeros((3, self.branch_count), dtype=float)
        base_energy = self._interpolate(point)[0]
        for dimension, axis in enumerate(self._axes):
            if len(axis) == 1:
                continue
            step = max(float(axis[1] - axis[0]) * 1.0e-3, 1.0e-6)
            plus = point.copy()
            minus = point.copy()
            plus[dimension] += step
            minus[dimension] -= step
            plus = self._prepare_point(plus, tessellate=tessellate)
            minus = self._prepare_point(minus, tessellate=tessellate)
            if plus is not None and minus is not None:
                gradients[dimension] = (
                    self._interpolate(plus)[0] - self._interpolate(minus)[0]
                ) / (2.0 * step)
            elif plus is not None:
                gradients[dimension] = (
                    self._interpolate(plus)[0] - base_energy
                ) / step
            elif minus is not None:
                gradients[dimension] = (
                    base_energy - self._interpolate(minus)[0]
                ) / step
        return gradients


_CACHE: dict[Path, tuple[int, int, DispersionMap]] = {}


def _parse_positive_header_int(name: str, raw_value: str, line_number: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise DispersionMapError(
            f"line {line_number}: {name} must be an integer"
        ) from exc
    if value <= 0:
        raise DispersionMapError(f"line {line_number}: {name} must be positive")
    return value


def _parse_headers(path: Path) -> dict[str, int]:
    """Collect the ``# grid_n* / num_branches`` declarations from comment lines."""
    headers: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if "#" not in line:
                continue
            header_match = _HEADER_PATTERN.match(line)
            if header_match:
                name = header_match.group(1).lower()
                value = _parse_positive_header_int(
                    name, header_match.group(2), line_number
                )
                previous = headers.get(name)
                if previous is not None and previous != value:
                    raise DispersionMapError(
                        f"line {line_number}: conflicting {name} declarations"
                    )
                headers[name] = value
            elif _HEADER_PREFIX_PATTERN.match(line):
                raise DispersionMapError(
                    f"line {line_number}: malformed grid header declaration"
                )
    return headers


def _diagnose_rows(path: Path, cause: Exception) -> DispersionMapError:
    """Walk the rows once ``loadtxt`` has refused them and name the first offender."""
    gamma_columns: bool | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            content = line.split("#", 1)[0].strip()
            if not content:
                continue
            fields = content.split()
            if len(fields) < 6:
                return DispersionMapError(
                    f"line {line_number}: expected H K L E intensity branch "
                    "and optional linewidth"
                )
            if len(fields) > 7:
                return DispersionMapError(
                    f"line {line_number}: expected at most seven dispersion fields"
                )
            row_has_gamma = len(fields) == 7
            if gamma_columns is None:
                gamma_columns = row_has_gamma
            elif gamma_columns != row_has_gamma:
                return DispersionMapError(
                    f"line {line_number}: linewidth column is present on only "
                    "part of the grid"
                )
            try:
                [float(value) for value in fields]
            except ValueError:
                return DispersionMapError(
                    f"line {line_number}: non-numeric dispersion value"
                )
    return DispersionMapError(f"cannot parse dispersion rows in {path}: {cause}")


def _regular_axis(
    values: np.ndarray,
    *,
    name: str,
    expected_size: int | None,
) -> np.ndarray:
    axis = np.unique(values)
    if expected_size is not None and len(axis) != expected_size:
        raise DispersionMapError(
            f"{name} dimension is {len(axis)}, header declares {expected_size}"
        )
    if len(axis) > 1:
        differences = np.diff(axis)
        if np.any(differences <= 0.0) or not np.allclose(
            differences,
            differences[0],
            rtol=_REGULAR_RTOL,
            atol=_REGULAR_ATOL,
        ):
            raise DispersionMapError(f"{name} coordinates do not form a regular grid")
    return axis


def _parse_dispersion_map(path: Path) -> DispersionMap:
    headers = _parse_headers(path)
    try:
        table = np.loadtxt(path, comments="#", dtype=float, ndmin=2, encoding="utf-8")
    except ValueError as exc:
        raise _diagnose_rows(path, exc) from exc

    if table.size == 0:
        raise DispersionMapError(f"dispersion map contains no data rows: {path}")
    columns = table.shape[1]
    if columns < 6:
        raise DispersionMapError(
            "expected H K L E intensity branch and optional linewidth"
        )
    if columns > 7:
        raise DispersionMapError("expected at most seven dispersion fields")
    gamma_columns = columns == 7

    finite = np.isfinite(table).all(axis=1)
    if not finite.all():
        raise DispersionMapError(
            f"data row {int(np.argmax(~finite)) + 1}: dispersion values must be finite"
        )
    branch_values = table[:, 5]
    if np.any(branch_values < 0.0) or np.any(branch_values != np.floor(branch_values)):
        bad = int(np.argmax((branch_values < 0.0) | (branch_values != np.floor(branch_values))))
        raise DispersionMapError(
            f"data row {bad + 1}: branch must be a non-negative integer"
        )
    branches = branch_values.astype(int)
    if gamma_columns and np.any(table[:, 6] < 0.0):
        raise DispersionMapError(
            f"data row {int(np.argmax(table[:, 6] < 0.0)) + 1}: "
            "linewidth must be non-negative"
        )

    branch_ids = np.unique(branches)
    if not np.array_equal(branch_ids, np.arange(branch_ids[-1] + 1)):
        raise DispersionMapError(
            f"branch indices must be contiguous from 0; found {branch_ids.tolist()}"
        )
    header_branches = headers.get("num_branches")
    if header_branches is not None and header_branches != len(branch_ids):
        raise DispersionMapError(
            f"branch count is {len(branch_ids)}, header declares {header_branches}"
        )

    axes = (
        _regular_axis(table[:, 0], name="H", expected_size=headers.get("grid_nx")),
        _regular_axis(table[:, 1], name="K", expected_size=headers.get("grid_ny")),
        _regular_axis(table[:, 2], name="L", expected_size=headers.get("grid_nz")),
    )
    shape = tuple(len(axis) for axis in axes) + (len(branch_ids),)
    expected_rows = math.prod(shape)

    grid_index = tuple(
        np.searchsorted(axis, table[:, dimension]) for dimension, axis in enumerate(axes)
    ) + (branches,)
    flat = np.ravel_multi_index(grid_index, shape)
    unique_flat, first_index, counts = np.unique(flat, return_index=True, return_counts=True)
    if len(unique_flat) != len(flat):
        duplicate_row = table[int(first_index[np.argmax(counts > 1)])]
        raise DispersionMapError(
            f"duplicate grid cell at ({duplicate_row[0]:g}, {duplicate_row[1]:g}, "
            f"{duplicate_row[2]:g}), branch {int(duplicate_row[5])}"
        )
    if len(unique_flat) != expected_rows:
        raise DispersionMapError(
            f"grid requires {expected_rows} unique rows, found {len(unique_flat)}"
        )

    energies = np.empty(shape, dtype=float)
    intensities = np.empty(shape, dtype=float)
    energies.flat[flat] = table[:, 3]
    intensities.flat[flat] = table[:, 4]
    linewidths = None
    if gamma_columns:
        linewidths = np.empty(shape, dtype=float)
        linewidths.flat[flat] = table[:, 6]

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return DispersionMap(
        path=path,
        sha256=digest,
        axes=axes,
        energies=energies,
        intensities=intensities,
        linewidths=linewidths,
    )


def load_dispersion_map(path: str | Path) -> DispersionMap:
    """Load one map, invalidating the cache when size or mtime changes."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"dispersion map not found: {resolved}")
    stat = resolved.stat()
    cached = _CACHE.get(resolved)
    if cached is not None and cached[:2] == (stat.st_size, stat.st_mtime_ns):
        return cached[2]
    loaded = _parse_dispersion_map(resolved)
    _CACHE[resolved] = (stat.st_size, stat.st_mtime_ns, loaded)
    return loaded
