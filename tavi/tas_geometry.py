"""Triple-axis spectrometer geometry helpers.

The functions in this module work in the mounted sample/cradle frame used by
McStas: x and z are horizontal, y is vertical.  Positive sample omega/A3 rotates
sample +x toward lab -z, matching the PUMA sample cradle convention.
"""
import math
from dataclasses import dataclass

import numpy as np


EPS = 1e-12


@dataclass(frozen=True)
class TASAngles:
    """Sample angle solution for a target Q vector."""

    stt: float
    sth: float
    saz: float


def component_q_to_instrument_q(q_component: np.ndarray) -> np.ndarray:
    """Convert mounted component Q to the legacy PUMA/GUI Q convention.

    Component coordinates follow McStas/TAS sample axes: x and z are horizontal,
    y is vertical.  The public PUMA Q fields historically use x and y as the
    horizontal scattering plane and z as vertical.
    """
    q = np.asarray(q_component, dtype=float)
    if q.shape != (3,):
        raise ValueError("q_component must be a 3-vector.")
    return np.array([q[0], q[2], q[1]], dtype=float)


def instrument_q_to_component_q(q_instrument: np.ndarray) -> np.ndarray:
    """Convert legacy PUMA/GUI Q to mounted component coordinates."""
    q = np.asarray(q_instrument, dtype=float)
    if q.shape != (3,):
        raise ValueError("q_instrument must be a 3-vector.")
    return np.array([q[0], q[2], q[1]], dtype=float)


def mccode_rotation_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    """Return the McCode rotation matrix for ROTATED=[rx, ry, rz]."""
    rx = math.radians(rx_deg)
    ry = math.radians(ry_deg)
    rz = math.radians(rz_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return np.array([
        [cy * cz, sx * sy * cz + cx * sz, sx * sz - cx * sy * cz],
        [-cy * sz, cx * cz - sx * sy * sz, sx * cz + cx * sy * sz],
        [sy, -sx * cy, cx * cy],
    ], dtype=float)


def mccode_euler_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """Convert a McCode rotation matrix back to ROTATED=[rx, ry, rz] degrees."""
    r = np.asarray(matrix, dtype=float)
    if r.shape != (3, 3):
        raise ValueError("Rotation matrix must be 3x3.")

    sy = float(np.clip(r[2, 0], -1.0, 1.0))
    ry = math.asin(sy)
    cy = math.cos(ry)

    if abs(cy) > EPS:
        rx = math.atan2(-r[2, 1], r[2, 2])
        rz = math.atan2(-r[1, 0], r[0, 0])
    else:
        # Gimbal lock: choose rz=0 and keep a stable combined x rotation.
        rz = 0.0
        rx = math.atan2(r[0, 1], r[1, 1])

    return math.degrees(rx), math.degrees(ry), math.degrees(rz)


def sample_omega_matrix(sth_deg: float) -> np.ndarray:
    """Rotation for PUMA A3/sth from mounted sample frame to lab frame."""
    a = math.radians(sth_deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([
        [c, 0.0, s],
        [0.0, 1.0, 0.0],
        [-s, 0.0, c],
    ], dtype=float)


def sample_tilt_matrix(saz_deg: float) -> np.ndarray:
    """Rotation for PUMA saz from mounted sample frame to lab frame."""
    return mccode_rotation_matrix(saz_deg, 0.0, 0.0)


def stt_from_q_norm(q_norm: float, ki: float, kf: float, sense_sample: int = -1) -> float:
    """Compute sample two-theta from |Q|, ki, and kf.

    ``sense_sample`` selects the scattering branch: the returned angle carries
    its sign (vTAS ss convention; the historical baked value is -1).
    """
    if ki <= 0 or kf <= 0:
        raise ValueError("ki and kf must be positive.")
    cos_stt = (q_norm * q_norm - ki * ki - kf * kf) / (-2.0 * ki * kf)
    if cos_stt < -1.0 - 1e-10 or cos_stt > 1.0 + 1e-10:
        raise ValueError("Sample two-theta angle invalid for Q, ki, and kf.")
    cos_stt = float(np.clip(cos_stt, -1.0, 1.0))
    return sense_sample * math.degrees(math.acos(cos_stt))


def lab_q_from_stt(ki: float, kf: float, stt_deg: float) -> np.ndarray:
    """Return lab-frame Q for the selected PUMA sample scattering angle."""
    stt = math.radians(stt_deg)
    return np.array([
        -kf * math.sin(stt),
        0.0,
        ki - kf * math.cos(stt),
    ], dtype=float)


def solve_sample_angles(
    q_sample: np.ndarray, ki: float, kf: float, *, sense_sample: int = -1
) -> TASAngles:
    """Solve TAS sample angles for a target Q in mounted sample coordinates."""
    q = np.asarray(q_sample, dtype=float)
    if q.shape != (3,):
        raise ValueError("q_sample must be a 3-vector.")
    q_norm = float(np.linalg.norm(q))
    if q_norm <= EPS:
        raise ValueError("Zero momentum transfer is invalid.")

    stt = stt_from_q_norm(q_norm, ki, kf, sense_sample)
    q_lab = lab_q_from_stt(ki, kf, stt)
    phi_lab = math.atan2(q_lab[2], q_lab[0])

    # Apply the x-axis sample tilt first.  Choose the tilt that removes the
    # vertical component before the omega rotation.
    if abs(q[1]) <= EPS and abs(q[2]) <= EPS:
        saz = 0.0
    else:
        saz = math.degrees(math.atan2(-q[1], q[2]))

    q_tilted = sample_tilt_matrix(saz) @ q
    if abs(q_tilted[1]) > 1e-8 * max(1.0, q_norm):
        raise ValueError("Could not bring target Q into the horizontal scattering plane.")

    phi_sample = math.atan2(q_tilted[2], q_tilted[0])
    sth = math.degrees(phi_sample - phi_lab)
    return TASAngles(stt=stt, sth=sth, saz=saz)


def solve_instrument_angles(
    q_instrument: np.ndarray, ki: float, kf: float, *, sense_sample: int = -1
) -> TASAngles:
    """Solve TAS sample angles for Q in the public instrument/GUI convention."""
    q = np.asarray(q_instrument, dtype=float)
    if q.shape != (3,):
        raise ValueError("q_instrument must be a 3-vector.")
    q_norm = float(np.linalg.norm(q))
    if q_norm <= EPS:
        raise ValueError("Zero momentum transfer is invalid.")

    stt = stt_from_q_norm(q_norm, ki, kf, sense_sample)
    q_lab = lab_q_from_stt(ki, kf, stt)
    phi_lab = math.atan2(q_lab[2], q_lab[0])
    phi_target = math.atan2(q[1], q[0])
    sth = math.degrees(phi_target - phi_lab)

    q_horizontal = math.hypot(q[0], q[1])
    saz = -math.degrees(math.atan2(q[2], q_horizontal))
    return TASAngles(stt=stt, sth=sth, saz=saz)


def q_sample_from_angles(sth: float, saz: float, stt: float, ki: float, kf: float) -> np.ndarray:
    """Compute mounted-sample Q from TAS sample angles."""
    q_lab = lab_q_from_stt(ki, kf, stt)
    rotation = sample_omega_matrix(sth) @ sample_tilt_matrix(saz)
    return np.linalg.solve(rotation, q_lab)


def q_instrument_from_angles(sth: float, saz: float, stt: float, ki: float, kf: float) -> np.ndarray:
    """Compute public instrument/GUI Q from TAS sample angles."""
    q_lab = lab_q_from_stt(ki, kf, stt)
    q_norm = float(np.linalg.norm(q_lab))
    phi_lab = math.atan2(q_lab[2], q_lab[0])
    phi_target = math.radians(sth) + phi_lab
    saz_rad = math.radians(saz)
    q_horizontal = q_norm * math.cos(saz_rad)
    return np.array([
        q_horizontal * math.cos(phi_target),
        q_horizontal * math.sin(phi_target),
        -q_norm * math.sin(saz_rad),
    ], dtype=float)


def q_lab_from_angles(sth: float, saz: float, stt: float, ki: float, kf: float) -> np.ndarray:
    """Compute lab Q from TAS sample angles."""
    q_sample = q_sample_from_angles(sth, saz, stt, ki, kf)
    return sample_omega_matrix(sth) @ sample_tilt_matrix(saz) @ q_sample
