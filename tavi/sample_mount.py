"""Component-agnostic sample mounting and HKL conversion helpers."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from tavi.tas_geometry import mccode_euler_from_matrix


def reciprocal_basis_tas(a, b, c, alpha, beta, gamma) -> np.ndarray:
    """Return reciprocal basis columns in TAVI's TAS sample coordinates.

    Scalar lattice parameters use the Phonon_DFT-friendly convention:
    a is along x, b is in the xz horizontal plane, and c has its remaining
    component along y.  The returned columns are a*, b*, c* in inverse Angstrom.
    """
    a = float(a)
    b = float(b)
    c = float(c)
    aa = math.radians(float(alpha))
    bb = math.radians(float(beta))
    cc = math.radians(float(gamma))

    sin_cc = math.sin(cc)
    if abs(sin_cc) < 1e-12:
        raise ValueError("Degenerate lattice: gamma must not be 0 or 180 degrees.")

    direct_a = np.array([a, 0.0, 0.0], dtype=float)
    direct_b = np.array([b * math.cos(cc), 0.0, b * sin_cc], dtype=float)
    direct_cx = c * math.cos(bb)
    direct_cz = c * (math.cos(aa) - math.cos(cc) * math.cos(bb)) / sin_cc
    direct_cy_sq = c * c - direct_cx * direct_cx - direct_cz * direct_cz
    if direct_cy_sq < -1e-10:
        raise ValueError("Invalid lattice parameters produce negative c_y^2.")
    direct_c = np.array([
        direct_cx,
        math.sqrt(max(0.0, direct_cy_sq)),
        direct_cz,
    ], dtype=float)

    volume = float(np.dot(direct_a, np.cross(direct_b, direct_c)))
    if abs(volume) <= 1e-12:
        raise ValueError("Invalid lattice parameters: unit-cell volume is zero.")

    two_pi = 2.0 * math.pi
    a_star = two_pi * np.cross(direct_b, direct_c) / volume
    b_star = two_pi * np.cross(direct_c, direct_a) / volume
    c_star = two_pi * np.cross(direct_a, direct_b) / volume
    return np.column_stack([a_star, b_star, c_star])


@dataclass
class SampleMount:
    """Map file/component HKL coordinates into the mounted sample frame."""

    B_component: np.ndarray
    R_mount: np.ndarray

    @classmethod
    def from_lattice_tas(cls, a, b, c, alpha, beta, gamma, R_mount=None) -> "SampleMount":
        rotation = np.eye(3) if R_mount is None else np.asarray(R_mount, dtype=float)
        return cls(reciprocal_basis_tas(a, b, c, alpha, beta, gamma), rotation)

    def __post_init__(self):
        self.B_component = np.asarray(self.B_component, dtype=float)
        self.R_mount = np.asarray(self.R_mount, dtype=float)
        if self.B_component.shape != (3, 3):
            raise ValueError("B_component must be a 3x3 matrix.")
        if self.R_mount.shape != (3, 3):
            raise ValueError("R_mount must be a 3x3 matrix.")

    @property
    def mounted_basis(self) -> np.ndarray:
        """Return columns mapping HKL directly into mounted sample coordinates."""
        return self.R_mount @ self.B_component

    @property
    def mount_euler_deg(self) -> tuple[float, float, float]:
        """Return McStas ROTATED=[x,y,z] angles for the static mount arm."""
        return mccode_euler_from_matrix(self.R_mount)

    def hkl_to_q(self, H, K, L) -> tuple[float, float, float]:
        q = self.mounted_basis @ np.array([float(H), float(K), float(L)], dtype=float)
        return float(q[0]), float(q[1]), float(q[2])

    def q_to_hkl(self, qx, qy, qz) -> tuple[float, float, float]:
        q = np.array([float(qx), float(qy), float(qz)], dtype=float)
        hkl = np.linalg.solve(self.mounted_basis, q)
        return float(hkl[0]), float(hkl[1]), float(hkl[2])
