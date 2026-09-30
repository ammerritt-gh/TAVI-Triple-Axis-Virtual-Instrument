"""Crystal orientation core: the sample stage, its solver, and angles <-> Q.

Frames. The mount frame is the McStas sample frame (x, z horizontal, y up);
``U @ B @ hkl`` lives there. "Lab" is the sample-position frame McStas uses
(z along ki, y up); ``lab_q_from_stt`` gives the scattering vector there.

The stage. A goniometer is a sequence of axes, outermost (the turntable)
first. Each axis is duck-typed: ``name``, ``axis`` (unit rotation vector in
the stage frame with every axis at zero), ``lower`` and ``upper`` (degrees;
+/-inf is travel no source documents, enforced as unlimited). A positive
angle turns right-handedly about ``axis``, and
``v_lab = R_stage @ v_mount`` with ``R_stage = R_1 @ R_2 @ ... @ R_N``.
Descriptors supply ``instruments.descriptor.GonioAxis``; a peak's stage
record and the tests use ``StageAxis``.

Sense. Sample sense follows the vTAS Friedel convention verified live on IN8
(2026-07-02): a setting on the +1 branch puts ``-U B hkl`` on the lab
scattering vector, the -1 branch puts ``+U B hkl`` there. Callers hand
``solve_stage`` the already-signed mount vector.

Readout, correction, physical. The operator's UB lives in the readout frame
at the corrections in force: ``solve_stage`` returns READOUTS. The McStas
sample arm alone receives the physical angles, readout + correction +
hidden zero error (``sample_arm_euler``).

Imports nothing from ``instruments/`` and nothing Qt: ISAR vendors this file.
"""
import math
from typing import NamedTuple

import numpy as np

from tavi.tas_geometry import (
    instrument_q_to_component_q,
    lab_q_from_stt,
    mccode_euler_from_matrix,
    q_instrument_from_angles,
)

# Free-mode search grid over the held arc, degrees; see solve_stage.
GRID_STEP_DEG = 0.5
# A locked stage accepts a Q this far out of its plane (float noise and
# formatted GUI fields); anything more is refused with its angle.
LOCKED_PLANE_TOLERANCE_DEG = 1e-4


class StageAxis(NamedTuple):
    """A goniometer axis outside a descriptor (a peak's stage record, tests)."""

    name: str
    axis: tuple
    lower: float = -math.inf
    upper: float = math.inf


class StageUnreachable(ValueError):
    """No setting within travel does what was asked; the message says why,
    naming the axis, the angle it would need and its travel."""


def q_mount_from_legacy_angles(sth, saz, stt, ki, kf, sense_sample):
    """Return ``U @ B @ hkl`` (mount frame) measured at a legacy sample setting.

    ``(sth, saz, stt)`` is the legacy triple in degrees: turntable, the
    beam-fixed tilt under it, and the signed sample two-theta. The raw inverse
    of a +1-branch setting recovers the Friedel partner ``-Q``; the sign is
    undone here so every caller gets the crystal's own Q. Read only for peaks
    without a stage record (legacy saves, TAS_MCP).
    """
    q_mount = instrument_q_to_component_q(q_instrument_from_angles(sth, saz, stt, ki, kf))
    return -q_mount if sense_sample > 0 else q_mount


def axis_rotation(axis, angle_deg):
    """Right-handed rotation by ``angle_deg`` about the unit vector ``axis``."""
    x, y, z = (float(v) for v in axis)
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    k = 1.0 - c
    return np.array([
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ])


def stage_rotation(gonio, angles):
    """``R_stage`` for ``angles`` (a mapping name -> degrees; missing = 0)."""
    rotation = np.eye(3)
    for ax in gonio:
        rotation = rotation @ axis_rotation(ax.axis, angles.get(ax.name, 0.0))
    return rotation


def q_mount_from_stage(gonio, angles, stt, ki, kf, sense_sample):
    """Return ``U @ B @ hkl`` (mount frame) measured at a full stage setting.

    ``angles`` are the stage angles in the frame the UB lives in (readouts at
    today's corrections); ``stt`` is the signed sample two-theta.
    """
    q = stage_rotation(gonio, angles).T @ lab_q_from_stt(ki, kf, stt)
    return -q if sense_sample > 0 else q


def stage_record(gonio, angles):
    """A JSON-friendly record of a stage setting that describes its own axes:
    ``{"axes": [[name, [x, y, z]], ...], "angles": {name: degrees}}``."""
    return {
        "axes": [[ax.name, [float(v) for v in ax.axis]] for ax in gonio],
        "angles": {ax.name: float(angles.get(ax.name, 0.0)) for ax in gonio},
    }


def gonio_from_record(record):
    """The ``StageAxis`` tuple a ``stage_record`` describes."""
    return tuple(StageAxis(name, tuple(axis)) for name, axis in record["axes"])


def sample_arm_euler(gonio, physical_angles, u_true):
    """McStas ``ROTATED`` (rx, ry, rz) degrees for the single sample arm.

    For an Arm, ``R_abs(child) = R_rel @ R_abs(parent)`` and
    ``v_local = R_abs @ v_global``, so a crystal whose mount-frame vectors are
    ``U_true @ v_crystal`` needs ``R_rel = (R_stage(physical) @ U_true)^T``.
    """
    rotation = stage_rotation(gonio, physical_angles) @ np.asarray(u_true, dtype=float)
    return mccode_euler_from_matrix(rotation.T)


def _wrap(angle_deg):
    """Wrap degrees to (-180, 180]."""
    wrapped = (np.asarray(angle_deg, dtype=float) + 180.0) % 360.0 - 180.0
    return np.where(wrapped == -180.0, 180.0, wrapped)


def _in_travel(ax, angle):
    return ax.lower <= angle <= ax.upper


def _travel_text(ax):
    if math.isinf(ax.lower) and math.isinf(ax.upper):
        return "unlimited"
    return f"[{ax.lower:.4g}, {ax.upper:.4g}]°"


def _rotate_many(axis, vectors, angles_rad):
    """Rodrigues rotation of ``vectors`` (n, 3) by ``angles_rad`` (n,) about ``axis``."""
    a = np.asarray(axis, dtype=float)
    c = np.cos(angles_rad)[:, None]
    s = np.sin(angles_rad)[:, None]
    return (vectors * c + np.cross(a, vectors) * s
            + a[None, :] * (vectors @ a)[:, None] * (1.0 - c))


def _level_roots(axis, w, v, target, scale):
    """Roots in theta of ``w . R_axis(theta) v = target``, vectorised over rows.

    The left side is ``A cos + B sin + C``, so the roots are exact:
    ``theta = atan2(B, A) +/- acos(-C / hypot(A, B))``. Returns the two root
    arrays in degrees (NaN where none). When ``v`` lies along ``axis`` the
    angle cannot move it: every angle works if the equation already holds
    (then 0 is returned), none otherwise.
    """
    a = np.asarray(axis, dtype=float)
    av = v @ a
    wa = w @ a
    big_a = np.einsum("ij,ij->i", w, v) - wa * av
    big_b = np.einsum("ij,ij->i", w, np.cross(a, v))
    big_c = wa * av - target
    radius = np.hypot(big_a, big_b)
    tol = 1e-12 * scale
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = -big_c / radius
    spread = np.arccos(np.clip(np.nan_to_num(ratio, nan=2.0), -1.0, 1.0))
    centre = np.arctan2(big_b, big_a)
    no_root = ~(np.abs(ratio) <= 1.0 + 1e-12)
    free = radius <= tol
    free_value = np.where(np.abs(big_c) <= tol, 0.0, np.nan)
    roots = []
    for sign in (1.0, -1.0):
        root = np.where(no_root, np.nan, np.degrees(centre + sign * spread))
        roots.append(_wrap(np.where(free, free_value, root)))
    return roots


def _arc_roots(inner, solved, held, grid, q_mount, up, target, scale):
    """Roots of the levelling equation in inner axis ``solved`` with inner axis
    ``held`` at each value of ``grid`` (degrees): two root arrays."""
    n = len(grid)
    rad = np.radians(grid)
    other = inner[held]
    if held < solved:               # held arc carries the solved one
        w = _rotate_many(other.axis, np.tile(up, (n, 1)), -rad)   # R_held^T up
        v = np.tile(q_mount, (n, 1))
    else:                           # held arc rides on the solved one
        w = np.tile(up, (n, 1))
        v = _rotate_many(other.axis, np.tile(q_mount, (n, 1)), rad)
    return _level_roots(inner[solved].axis, w, v, target, scale)


def _refine(inner, solved, held, start, branch, q_mount, up, target, scale):
    """Zoom in on the smallest total tilt along one branch of the levelling
    curve, from one grid step either side of ``start``: 33 samples per round,
    each round sixteen times narrower, down to ~1e-9 degrees."""
    held_axis, solved_axis = inner[held], inner[solved]
    best_value, half = start, GRID_STEP_DEG
    best = (math.inf, start, math.nan)
    for _ in range(9):
        lo = max(best_value - half, held_axis.lower)
        hi = min(best_value + half, held_axis.upper)
        values = np.append(np.linspace(lo, hi, 33), best_value)
        roots = _arc_roots(inner, solved, held, values, q_mount, up, target, scale)[branch]
        with np.errstate(invalid="ignore"):
            ok = (roots >= solved_axis.lower) & (roots <= solved_axis.upper)
        cost = np.where(ok, values ** 2 + roots ** 2, np.inf)
        index = int(np.argmin(cost))
        if not cost[index] < best[0]:
            break
        best = (float(cost[index]), float(values[index]), float(roots[index]))
        best_value, half = best[1], (hi - lo) / 32.0
    return best


def _level_candidates(inner, q_mount, up, target, scale):
    """Every levelling solution the search finds, as blocks of inner-axis
    angle rows, each with (solved index, held index, branch) for refinement."""
    if len(inner) == 1:
        roots = _level_roots(inner[0].axis, up[None, :], q_mount[None, :], target, scale)
        return [r.reshape(1, 1) for r in roots], [(0, None, 0), (0, None, 1)]
    grid = np.arange(-180.0, 180.0, GRID_STEP_DEG)
    blocks, meta = [], []
    # Each arc takes its turn as the solved axis (A2): an arc parallel to Q
    # cannot move it, so holding only the other arc on the grid would miss
    # the narrow band where its roots exist.
    for solved, held in ((1, 0), (0, 1)):
        roots = _arc_roots(inner, solved, held, grid, q_mount, up, target, scale)
        for branch, root in enumerate(roots):
            angles = np.empty((len(grid), 2))
            angles[:, solved] = root
            angles[:, held] = grid
            blocks.append(angles)
            meta.append((solved, held, branch))
    return blocks, meta


def _turntable(turntable, q_level, q_lab):
    """Turntable angle carrying the levelled ``q_level`` onto ``q_lab``: the
    azimuth difference, computed as the legacy solver does (not wrapped)."""
    sign = 1.0 if turntable.axis[1] > 0 else -1.0
    angle = sign * math.degrees(
        math.atan2(q_level[2], q_level[0]) - math.atan2(q_lab[2], q_lab[0])
    )
    for candidate in (angle, angle - 360.0, angle + 360.0):
        if _in_travel(turntable, candidate):
            return candidate
    raise StageUnreachable(
        f"{turntable.name} needs {angle:.4g}° but its travel is {_travel_text(turntable)}"
    )


def solve_stage(gonio, q_mount, q_lab, locked=None):
    """Readouts that carry ``q_mount`` onto ``q_lab``: ``R_stage @ q_mount = q_lab``.

    ``q_mount`` is the already-signed mount-frame vector (module docstring),
    ``|q_mount| = |q_lab|``. Returns ``{name: degrees}`` for every axis, or
    raises ``StageUnreachable``.

    Free mode (``locked`` None): the inner axes level Q with the smallest total
    tilt (sum of squared inner-axis angles) inside travel, then the turntable
    turns it onto ``q_lab``. The choice is a function of the point alone.
    Locked mode (``locked`` = {inner name: degrees}): the tilts never move;
    a Q they leave out of the horizontal plane is refused with its angle.

    Search, for two inner axes: each arc in turn is held on a grid over a full
    turn (GRID_STEP_DEG) while the levelling equation is solved exactly in the
    other; the union of the roots is filtered by travel, and the smallest-tilt
    root is refined along its own branch to the minimum. Levelling is exact
    whatever the grid; only the minimality is grid-limited.
    Ceiling: a tilt minimum narrower than one grid step can be missed, and at
    most two inner axes are supported. Measured per point through
    ``calculate_stage_angles`` (2026-10-01, this machine): median 1.0 ms,
    worst 1.6 ms tilted; 0.06 ms level. Upgrade path: the closed-form
    stationary points of the tilt along the levelling curve.
    """
    turntable, inner = gonio[0], tuple(gonio[1:])
    q_mount = np.asarray(q_mount, dtype=float)
    q_lab = np.asarray(q_lab, dtype=float)
    up = np.asarray(turntable.axis, dtype=float)
    scale = float(np.linalg.norm(q_lab)) or 1.0
    target = float(up @ q_lab)

    if locked is not None:
        tilts = {ax.name: float(locked.get(ax.name, 0.0)) for ax in inner}
        q_level = stage_rotation(inner, tilts) @ q_mount
        out = math.degrees(math.asin(max(-1.0, min(1.0, (up @ q_level - target) / scale))))
        if abs(out) > LOCKED_PLANE_TOLERANCE_DEG:
            fixed = ", ".join(f"{name} = {value:.4g}°" for name, value in tilts.items())
            raise StageUnreachable(
                f"Q is {out:+.4g}° out of the locked scattering plane ({fixed})"
            )
        return {turntable.name: _turntable(turntable, q_level, q_lab), **tilts}

    if abs(up @ q_mount - target) <= 1e-12 * scale and all(
            _in_travel(ax, 0.0) for ax in inner):
        # Already level: no tilt, and the turntable angle bit-identical to the
        # legacy in-plane solve.
        return {turntable.name: _turntable(turntable, q_mount, q_lab),
                **{ax.name: 0.0 for ax in inner}}
    if not inner:
        raise StageUnreachable("the stage has no arcs to bring Q into the scattering plane")
    if len(inner) > 2:
        raise NotImplementedError("solve_stage handles at most two inner axes")

    blocks, meta = _level_candidates(inner, q_mount, up, target, scale)
    rows = np.vstack(blocks)
    tilt = np.where(np.isnan(rows).any(axis=1), np.inf, np.sum(rows ** 2, axis=1))
    if not np.isfinite(tilt).any():
        raise StageUnreachable("no arc setting brings Q into the scattering plane")
    fits = np.isfinite(tilt)
    for i, ax in enumerate(inner):
        fits &= (rows[:, i] >= ax.lower) & (rows[:, i] <= ax.upper)
    if not fits.any():
        for ax, angle in zip(inner, rows[int(np.argmin(tilt))]):
            if not _in_travel(ax, angle):
                raise StageUnreachable(
                    f"{ax.name} needs {angle:.4g}° to bring Q into the scattering "
                    f"plane but its travel is {_travel_text(ax)}"
                )

    # The chosen root: smallest tilt in travel over the union, refined along
    # its own branch (first minimum wins a tie, so the choice is repeatable).
    chosen = int(np.argmin(np.where(fits, tilt, np.inf)))
    block_index = int(np.searchsorted(np.cumsum([len(b) for b in blocks]), chosen, side="right"))
    solved, held, branch = meta[block_index]
    angles = [float(a) for a in rows[chosen]]
    if held is not None:
        _, held_angle, root = _refine(inner, solved, held, angles[held], branch,
                                      q_mount, up, target, scale)
        angles[held], angles[solved] = held_angle, root
    tilts = {ax.name: angle for ax, angle in zip(inner, angles)}
    q_level = stage_rotation(inner, tilts) @ q_mount
    return {turntable.name: _turntable(turntable, q_level, q_lab), **tilts}


def _signed_angle(axis, start, end):
    """Angle about ``axis`` turning ``start`` onto ``end`` (their components
    perpendicular to it), degrees; 0 when either lies along the axis."""
    a = np.asarray(axis, dtype=float)
    s = start - a * (a @ start)
    e = end - a * (a @ end)
    if np.linalg.norm(s) < 1e-12 or np.linalg.norm(e) < 1e-12:
        return 0.0
    return math.degrees(math.atan2(a @ np.cross(s, e), s @ e))


def lock_plane(gonio, ub, hkl_u, hkl_v):
    """Inner-axis angles {name: degrees} that make the plane spanned by
    ``UB @ hkl_u`` and ``UB @ hkl_v`` horizontal, with the smallest total
    tilt inside travel; ``StageUnreachable`` otherwise.

    The plane normal must go onto the turntable axis (either sign). With two
    arcs that is the intersection of two cones -- the normal's orbit about the
    inner arc and the vertical's orbit about the outer arc -- solved in closed
    form: up to four settings.
    """
    turntable, inner = gonio[0], tuple(gonio[1:])
    ub = np.asarray(ub, dtype=float)
    normal = np.cross(ub @ np.asarray(hkl_u, dtype=float), ub @ np.asarray(hkl_v, dtype=float))
    if np.linalg.norm(normal) < 1e-12:
        raise ValueError("The two plane vectors are parallel.")
    normal = normal / np.linalg.norm(normal)
    up = np.asarray(turntable.axis, dtype=float)
    if len(inner) > 2:
        raise NotImplementedError("lock_plane handles at most two inner axes")
    solutions = []
    for goal in (up, -up):
        if not inner:
            if np.allclose(normal, goal, rtol=0.0, atol=1e-12):
                solutions.append(())
        elif len(inner) == 1:
            a = np.asarray(inner[0].axis, dtype=float)
            if abs(a @ normal - a @ goal) < 1e-12:
                solutions.append((_signed_angle(a, normal, goal),))
        else:
            a_out, a_in = (np.asarray(ax.axis, dtype=float) for ax in inner)
            d = float(a_out @ a_in)
            m = np.cross(a_out, a_in)
            if np.linalg.norm(m) < 1e-12:
                raise StageUnreachable("the two arcs are parallel; no plane can be levelled")
            # p = R_in(t_in) normal = R_out(-t_out) goal lies on both cones.
            c_out, c_in = float(a_out @ goal), float(a_in @ normal)
            alpha = (c_out - c_in * d) / (1.0 - d * d)
            beta = (c_in - c_out * d) / (1.0 - d * d)
            gamma_sq = (1.0 - alpha * alpha - beta * beta - 2 * alpha * beta * d) / (m @ m)
            if gamma_sq < -1e-12:
                continue
            for sign in (1.0, -1.0):
                p = alpha * a_out + beta * a_in + sign * math.sqrt(max(gamma_sq, 0.0)) * m
                solutions.append((_signed_angle(a_out, p, goal),
                                  _signed_angle(a_in, normal, p)))
    if not solutions:
        raise StageUnreachable("no arc setting brings this plane horizontal")
    solutions = sorted((tuple(float(_wrap(angle)) for angle in s) for s in solutions),
                       key=lambda s: sum(angle * angle for angle in s))
    for s in solutions:
        if all(_in_travel(ax, angle) for ax, angle in zip(inner, s)):
            return {ax.name: angle for ax, angle in zip(inner, s)}
    for ax, angle in zip(inner, solutions[0]):
        if not _in_travel(ax, angle):
            raise StageUnreachable(
                f"{ax.name} needs {angle:.4g}° to bring the plane horizontal "
                f"but its travel is {_travel_text(ax)}"
            )
    raise StageUnreachable("no arc setting within travel brings this plane horizontal")
