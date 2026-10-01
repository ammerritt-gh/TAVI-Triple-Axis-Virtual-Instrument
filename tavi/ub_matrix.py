"""UB Matrix calculations for TAVI.

Implements the Busing-Levy (1967) UB matrix formalism for crystal orientation
on a triple-axis neutron spectrometer.

The UB matrix transforms Miller indices (HKL) to mounted-sample Q vectors:
    Q_sample = UB @ [H, K, L]

where:
    B = reciprocal lattice metric matrix in the component's local sample frame
    U = static mount orientation matrix, determined from Bragg peaks
    UB = U @ B (combined transformation into the mounted sample frame)

Convention: scalar lattice parameters use the TAS component frame:
a* along x, b* in the horizontal xz-plane, c* vertical-ish along y.
"""
import math
import base64
import struct
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from tavi.orientation import (
    gonio_from_record,
    q_mount_from_legacy_angles,
    q_mount_from_stage,
    record_angles,
    solve_stage,
    stage_rotation,
)
from tavi.sample_mount import reciprocal_basis_tas
from tavi.tas_geometry import lab_q_from_stt, stt_from_q_norm


# Obfuscation key for training hash encoding (not cryptographic security)
_OBFUSCATION_KEY = b'TAVI_UB_TRAIN_26'


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with repeating key."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def compute_B_matrix(a, b, c, alpha, beta, gamma):
    """Compute the B matrix (Busing-Levy convention) from lattice parameters.

    The B matrix transforms Miller indices to Cartesian reciprocal-space coordinates:
        Q_crystal = B @ [H, K, L]

    Convention: a* along x, b* in the horizontal xz-plane, c* general.

    Args:
        a, b, c: Lattice parameters in Angstroms.
        alpha, beta, gamma: Lattice angles in degrees.

    Returns:
        np.ndarray: 3x3 B matrix.
    """
    return reciprocal_basis_tas(a, b, c, alpha, beta, gamma)


def validate_rotation_matrix(matrix: np.ndarray, atol: float = 1e-3) -> np.ndarray:
    """Return matrix as float array if it is a proper 3D rotation."""
    rotation = np.asarray(matrix, dtype=float)
    if rotation.shape != (3, 3):
        raise ValueError("Rotation matrix must be 3x3.")
    if not np.all(np.isfinite(rotation)):
        raise ValueError("Rotation matrix contains non-finite values.")
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=atol):
        raise ValueError("Derived U is not orthogonal; UB does not describe a physical mount rotation.")
    det = float(np.linalg.det(rotation))
    if not math.isclose(det, 1.0, abs_tol=atol):
        raise ValueError(f"Derived U must be a proper rotation with det=+1; got det={det:.6g}.")
    return rotation


@dataclass
class ObservedPeak:
    """A Bragg peak observation with HKL and instrument angles.

    Attributes:
        hkl: Miller indices (H, K, L).
        angles: Legacy sample triple (omega/sth, chi/saz, stt) in degrees;
            stt is the signed readout.
        ki: Incident wavevector at observation (inverse Angstroms).
        kf: Scattered wavevector at observation (inverse Angstroms).
        locked: Whether this peak entry is locked from editing.
        sense_sample: Sample scattering sense (+1/-1) the peak was taken on.
            None resolves to the stage record's sense, else (a legacy save,
            a TAS_MCP peak) to the sign of stt.
        stage: Optional stage record (``tavi.orientation.stage_record``: the
            axes, their readouts, and from Take Position the corrections in
            force, ki, kf and the sense). When present, Q is read through the
            full stage and only ``stt`` of ``angles`` is used (the UB dock
            still writes the legacy triple of the same Q,
            ``tavi.orientation.legacy_triple``, for readers that ignore the
            record); None (a "legacy" peak) reads the legacy triple's meaning.
    """
    hkl: tuple = (0.0, 0.0, 0.0)
    angles: tuple = (0.0, 0.0, 0.0)  # (sth, saz, stt)
    ki: float = 0.0
    kf: float = 0.0
    locked: bool = False
    sense_sample: Optional[int] = None
    stage: Optional[dict] = None

    def __post_init__(self):
        if self.sense_sample is None and self.stage is not None:
            self.sense_sample = self.stage.get("sense")
        if self.sense_sample is None:
            self.sense_sample = 1 if self.angles[2] > 0 else -1

    @property
    def is_legacy(self) -> bool:
        """No stage record: the angles are the legacy (sth, saz, stt) triple."""
        return self.stage is None

    def q_mount(self, corrections=None) -> np.ndarray:
        """U @ B @ hkl measured at this peak, in the readout frame of
        ``corrections`` (the corrections in force now, {axis: degrees}).

        A stage peak enters at readout + (correction at record time -
        correction now), so a correction changed after Take Position does not
        move it; ``corrections`` None reads it as recorded. Hidden zero errors
        are never part of a record. A legacy peak ignores ``corrections``.
        """
        sth, saz, stt = self.angles
        if self.ki <= 0 or self.kf <= 0:
            return np.array([0.0, 0.0, 0.0])
        if self.stage is not None:
            return q_mount_from_stage(gonio_from_record(self.stage),
                                      record_angles(self.stage, corrections),
                                      stt, self.ki, self.kf, self.sense_sample)
        return q_mount_from_legacy_angles(sth, saz, stt, self.ki, self.kf, self.sense_sample)

    @property
    def q_lab(self) -> np.ndarray:
        """U @ B @ hkl in the mounted sample frame, from the stored setting
        (``q_mount`` as recorded)."""
        return self.q_mount()

    @property
    def is_valid(self) -> bool:
        """Check if this peak has enough data for UB calculation."""
        h, k, l = self.hkl
        if h == 0 and k == 0 and l == 0:
            return False
        if self.ki <= 0 or self.kf <= 0:
            return False
        q = self.q_lab
        return np.linalg.norm(q) > 1e-6

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            'hkl': list(self.hkl),
            'angles': list(self.angles),
            'ki': self.ki,
            'kf': self.kf,
            'locked': self.locked,
            'sense_sample': self.sense_sample,
            'stage': self.stage,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'ObservedPeak':
        """Deserialize from dictionary."""
        return cls(
            hkl=tuple(d.get('hkl', [0, 0, 0])),
            angles=tuple(d.get('angles', [0, 0, 0])),
            ki=d.get('ki', 0.0),
            kf=d.get('kf', 0.0),
            locked=d.get('locked', False),
            sense_sample=d.get('sense_sample'),
            stage=d.get('stage'),
        )


def calculate_U_two_peaks(peak1: ObservedPeak, peak2: ObservedPeak,
                          B: np.ndarray, corrections=None) -> np.ndarray:
    """Calculate the U orientation matrix from two observed Bragg peaks.

    Uses the Busing-Levy (1967) method:
    1. Compute Q vectors in crystal frame (B @ hkl) and lab frame (from angles).
    2. Build orthonormal triads in both frames.
    3. U = T_lab @ T_crystal^(-1)

    Args:
        peak1: First observed Bragg peak.
        peak2: Second observed Bragg peak.
        B: 3x3 B matrix.
        corrections: The corrections in force now ({axis: degrees}); the fit
            is in their readout frame (``ObservedPeak.q_mount``).

    Returns:
        np.ndarray: 3x3 U matrix (orthogonal, det ~ +1).

    Raises:
        ValueError: If peaks are collinear or invalid.
    """
    # Crystal-frame Q vectors
    q1_c = B @ np.array(peak1.hkl)
    q2_c = B @ np.array(peak2.hkl)

    # Lab-frame Q vectors
    q1_l = peak1.q_mount(corrections)
    q2_l = peak2.q_mount(corrections)

    # Validate
    for label, v in [("peak1 crystal", q1_c), ("peak2 crystal", q2_c),
                     ("peak1 lab", q1_l), ("peak2 lab", q2_l)]:
        if np.linalg.norm(v) < 1e-8:
            raise ValueError(f"Zero-length Q vector for {label}.")

    T_crystal = _busing_levy_triad(q1_c, q2_c, "crystal")
    T_lab = _busing_levy_triad(q1_l, q2_l, "lab")

    # U = T_lab @ T_crystal^(-1)
    # Since T_crystal is orthonormal, T_crystal^(-1) = T_crystal^T
    U = T_lab @ T_crystal.T

    return U


def _busing_levy_triad(v1, v2, frame):
    """Orthonormal columns (v1, v1 x v2, v1 x (v1 x v2)), all normalised: the
    Busing-Levy triad of two non-parallel vectors in ``frame``."""
    t1 = v1 / np.linalg.norm(v1)
    cross = np.cross(v1, v2)
    if np.linalg.norm(cross) < 1e-8:
        raise ValueError(f"Peaks are collinear in {frame} frame — cannot determine U.")
    t2 = cross / np.linalg.norm(cross)
    t3 = np.cross(t1, t2)
    return np.column_stack([t1, t2, t3])


def u_from_plane(B: np.ndarray, hkl_u, hkl_v) -> np.ndarray:
    """The mount U of a crystal mounted with ``hkl_u`` along the mount x axis
    and ``hkl_v`` in the horizontal plane (mount xz, y up), on the +z side.

    ``B`` is the crystal's own B (the remount passes the sample's true B, never
    the lattice fields). Raises ValueError naming the problem for a zero or a
    parallel pair."""
    def shown(hkl):
        return "(" + " ".join(f"{float(x):g}" for x in hkl) + ")"

    q_u = B @ np.asarray(hkl_u, dtype=float)
    q_v = B @ np.asarray(hkl_v, dtype=float)
    for name, hkl, q in (("along x", hkl_u, q_u), ("in plane", hkl_v, q_v)):
        if np.linalg.norm(q) < 1e-8:
            raise ValueError(f"the vector {name}, {shown(hkl)}, is zero")
    if np.linalg.norm(np.cross(q_u, q_v)) < 1e-8 * np.linalg.norm(q_u) * np.linalg.norm(q_v):
        raise ValueError(f"{shown(hkl_u)} and {shown(hkl_v)} are parallel, so they span no plane")
    T_crystal = _busing_levy_triad(q_u, q_v, "crystal")
    T_mount = _busing_levy_triad(np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), "mount")
    return T_mount @ T_crystal.T


def refine_U_matrix(peaks: list, B: np.ndarray, corrections=None) -> np.ndarray:
    """Calculate U from multiple peaks using SVD-based Procrustes solution.

    Minimizes sum_i ||q_lab_i - U @ B @ hkl_i||^2 subject to U being orthogonal.

    Falls back to two-peak method if only 2 valid peaks.

    Args:
        peaks: List of ObservedPeak instances.
        B: 3x3 B matrix.
        corrections: The corrections in force now (see calculate_U_two_peaks).

    Returns:
        np.ndarray: 3x3 U matrix (orthogonal, det ~ +1).
    """
    valid_peaks = [p for p in peaks if p.is_valid]
    if len(valid_peaks) < 2:
        raise ValueError(f"Need at least 2 valid peaks, got {len(valid_peaks)}.")
    if len(valid_peaks) == 2:
        return calculate_U_two_peaks(valid_peaks[0], valid_peaks[1], B, corrections)

    # Build paired point sets: q_crystal (P) and q_lab (Q)
    # We want U such that Q ~ U @ P
    P = np.zeros((3, len(valid_peaks)))
    Q = np.zeros((3, len(valid_peaks)))

    for i, peak in enumerate(valid_peaks):
        P[:, i] = B @ np.array(peak.hkl)
        Q[:, i] = peak.q_mount(corrections)

    # Cross-covariance matrix
    H_mat = P @ Q.T  # Note: we want U s.t. Q = U @ P, so H = P @ Q^T

    # SVD
    Usvd, S, Vt = np.linalg.svd(H_mat)
    if S[1] < 1e-8 * S[0]:
        raise ValueError("Peaks are collinear — cannot determine U.")

    # Ensure proper rotation (det = +1, not reflection)
    d = np.linalg.det(Vt.T @ Usvd.T)
    D = np.diag([1, 1, np.sign(d)])

    U = Vt.T @ D @ Usvd.T

    return U


def refine_lattice_from_peaks(peaks: list, initial_lattice: tuple,
                              crystal_system: str = None) -> dict:
    """Refine lattice parameters from observed peak positions.

    Compares observed d-spacings with calculated ones and adjusts lattice parameters.
    Uses simple least-squares fitting.

    Args:
        peaks: List of ObservedPeak instances.
        initial_lattice: (a, b, c, alpha, beta, gamma) initial guess.
        crystal_system: Optional crystal system name to constrain refinement.

    Returns:
        dict with 'lattice' (refined params), 'residuals' (per-peak), 'rms_error'.
    """
    valid_peaks = [p for p in peaks if p.is_valid]
    if len(valid_peaks) < 1:
        raise ValueError("Need at least 1 valid peak for lattice refinement.")

    a0, b0, c0, al0, be0, ga0 = initial_lattice

    # Collect observed |Q| for each peak
    observed = []
    for peak in valid_peaks:
        q_obs = np.linalg.norm(peak.q_lab)
        observed.append((peak.hkl, q_obs))

    # Simple refinement: scale lattice parameters to match observed d-spacings
    # For each peak: |Q_calc| = |B @ hkl|, |Q_obs| from angles
    # Minimize sum of (|Q_calc| - |Q_obs|)^2 by scaling

    B0 = compute_B_matrix(a0, b0, c0, al0, be0, ga0)

    residuals = []
    scale_ratios = []
    for hkl, q_obs in observed:
        q_calc = np.linalg.norm(B0 @ np.array(hkl))
        if q_calc > 1e-8:
            residuals.append(q_obs - q_calc)
            scale_ratios.append(q_obs / q_calc)

    if not scale_ratios:
        return {
            'lattice': initial_lattice,
            'residuals': [],
            'rms_error': float('inf'),
        }

    # Average scale factor
    avg_scale = np.mean(scale_ratios)

    # Apply constraints based on crystal system.
    # |Q| ∝ 1/a, so avg_scale = mean(q_obs/q_calc) > 1 means observed |Q| is
    # larger → real-space lattice constants are smaller → divide by avg_scale.
    if crystal_system in ("cubic",):
        a_new = a0 / avg_scale
        refined = (a_new, a_new, a_new, 90.0, 90.0, 90.0)
    elif crystal_system in ("tetragonal",):
        a_new = a0 / avg_scale
        c_new = c0 / avg_scale
        refined = (a_new, a_new, c_new, 90.0, 90.0, 90.0)
    elif crystal_system in ("hexagonal",):
        a_new = a0 / avg_scale
        c_new = c0 / avg_scale
        refined = (a_new, a_new, c_new, 90.0, 90.0, 120.0)
    elif crystal_system in ("orthorhombic",):
        a_new = a0 / avg_scale
        b_new = b0 / avg_scale
        c_new = c0 / avg_scale
        refined = (a_new, b_new, c_new, 90.0, 90.0, 90.0)
    else:
        # General: uniform scaling of lengths
        a_new = a0 / avg_scale
        b_new = b0 / avg_scale
        c_new = c0 / avg_scale
        refined = (a_new, b_new, c_new, al0, be0, ga0)

    # Compute residuals with refined lattice
    B_new = compute_B_matrix(*refined)
    final_residuals = []
    for hkl, q_obs in observed:
        q_calc = np.linalg.norm(B_new @ np.array(hkl))
        final_residuals.append({
            'hkl': hkl,
            'q_obs': q_obs,
            'q_calc': q_calc,
            'delta_q': q_obs - q_calc,
            'd_obs': 2*math.pi/q_obs if q_obs > 0 else 0,
            'd_calc': 2*math.pi/q_calc if q_calc > 0 else 0,
        })

    rms = math.sqrt(np.mean([(r['delta_q'])**2 for r in final_residuals]))

    return {
        'lattice': refined,
        'residuals': final_residuals,
        'rms_error': rms,
    }


def get_scattering_plane_info(U: np.ndarray, B: np.ndarray) -> dict:
    """Analyze the scattering plane defined by the current UB matrix.

    The instrument scattering plane is the mounted sample xz-plane (qy=0).
    With U applied, crystal directions map to mounted sample frame via U @ B.

    Args:
        U: 3x3 orientation matrix.
        B: 3x3 B matrix.

    Returns:
        dict with scattering plane analysis.
    """
    UB = U @ B

    # The mounted sample y-axis (out of scattering plane) in crystal HKL coordinates.
    try:
        UB_inv = np.linalg.inv(UB)
    except np.linalg.LinAlgError:
        return {
            'plane_normal_hkl': (0, 0, 0),
            'in_plane_vector1_hkl': (0, 0, 0),
            'in_plane_vector2_hkl': (0, 0, 0),
            'chi_misalignment_deg': 0.0,
            'omega_offset_deg': 0.0,
        }

    y_sample = np.array([0.0, 1.0, 0.0])
    plane_normal_hkl = UB_inv @ y_sample

    # In-plane vectors: mounted sample x and z in HKL space.
    x_sample = np.array([1.0, 0.0, 0.0])
    z_sample = np.array([0.0, 0.0, 1.0])
    in_plane_v1 = UB_inv @ x_sample
    in_plane_v2 = UB_inv @ z_sample

    # Chi misalignment: angle between crystal c* axis and vertical sample y.
    # c* direction in crystal frame = B @ [0,0,1]
    c_star_crystal = B @ np.array([0.0, 0.0, 1.0])
    c_star_lab = U @ c_star_crystal
    c_star_lab_norm = c_star_lab / np.linalg.norm(c_star_lab)

    # Angle from horizontal plane (complement of angle with z)
    chi_mis = math.degrees(math.asin(np.clip(c_star_lab_norm[1], -1, 1)))

    # Omega offset: rotation of a* from sample x in the horizontal xz-plane.
    a_star_crystal = B @ np.array([1.0, 0.0, 0.0])
    a_star_lab = U @ a_star_crystal
    omega_offset = math.degrees(math.atan2(a_star_lab[2], a_star_lab[0]))

    return {
        'plane_normal_hkl': tuple(plane_normal_hkl),
        'in_plane_vector1_hkl': tuple(in_plane_v1),
        'in_plane_vector2_hkl': tuple(in_plane_v2),
        'chi_misalignment_deg': chi_mis,
        'omega_offset_deg': omega_offset,
    }


class UBMatrix:
    """Manages the UB matrix for crystal orientation on a TAS.

    The UB matrix transforms Miller indices to mounted-sample Q:
        Q_sample = UB @ [H, K, L]

    where B encodes the lattice and U encodes the crystal orientation.
    """

    def __init__(self, a=4.05, b=4.05, c=4.05, alpha=90, beta=90, gamma=90):
        """Initialize with lattice parameters. U defaults to identity."""
        self._lattice = (float(a), float(b), float(c),
                         float(alpha), float(beta), float(gamma))
        self._B = compute_B_matrix(*self._lattice)
        self._U = np.eye(3)
        self._UB = self._U @ self._B
        self.peaks: list = []

    @property
    def lattice(self) -> tuple:
        """Current lattice parameters (a, b, c, alpha, beta, gamma)."""
        return self._lattice

    @property
    def B(self) -> np.ndarray:
        """Current B matrix."""
        return self._B.copy()

    @property
    def U(self) -> np.ndarray:
        """Current U orientation matrix."""
        return self._U.copy()

    @property
    def UB(self) -> np.ndarray:
        """Current UB matrix."""
        return self._UB.copy()

    @property
    def is_identity(self) -> bool:
        """True if U is the identity matrix (no orientation set)."""
        return np.allclose(self._U, np.eye(3), atol=1e-6)

    def set_lattice(self, a, b, c, alpha, beta, gamma):
        """Update lattice parameters, recompute B and UB."""
        self._lattice = (float(a), float(b), float(c),
                         float(alpha), float(beta), float(gamma))
        self._B = compute_B_matrix(*self._lattice)
        self._UB = self._U @ self._B

    def set_U(self, U: np.ndarray):
        """Set the U orientation matrix directly."""
        U = validate_rotation_matrix(U)
        self._U = U.copy()
        self._UB = self._U @ self._B

    def set_UB(self, UB: np.ndarray):
        """Set the UB matrix directly, extract U = UB @ B^(-1)."""
        UB = np.asarray(UB, dtype=float)
        if UB.shape != (3, 3):
            raise ValueError("UB must be a 3x3 matrix.")
        try:
            B_inv = np.linalg.inv(self._B)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Cannot extract U because the B matrix is singular.") from exc
        U = validate_rotation_matrix(UB @ B_inv)
        self._U = U.copy()
        self._UB = UB.copy()

    def reset_U(self):
        """Reset U to identity (no orientation)."""
        self._U = np.eye(3)
        self._UB = self._U @ self._B

    def hkl_to_q(self, H, K, L) -> tuple:
        """Convert Miller indices to lab-frame Q using the UB matrix.

        Args:
            H, K, L: Miller indices.

        Returns:
            tuple: (qx, qy, qz) in inverse Angstroms.
        """
        q = self._UB @ np.array([float(H), float(K), float(L)])
        return float(q[0]), float(q[1]), float(q[2])

    def q_to_hkl(self, qx, qy, qz) -> tuple:
        """Convert lab-frame Q to Miller indices using the UB matrix.

        Args:
            qx, qy, qz: Q components in inverse Angstroms.

        Returns:
            tuple: (H, K, L) Miller indices.

        Raises:
            np.linalg.LinAlgError: If UB matrix is singular.
        """
        q = np.array([float(qx), float(qy), float(qz)])
        hkl = np.linalg.solve(self._UB, q)
        return float(hkl[0]), float(hkl[1]), float(hkl[2])
    def calculate_U_from_peaks(self, corrections=None) -> np.ndarray:
        """Calculate U from stored peaks and apply it.

        ``corrections`` are the corrections in force now ({axis: degrees});
        the fitted UB lives in their readout frame. None reads every peak as
        recorded.

        Returns:
            np.ndarray: The calculated U matrix.
        """
        valid = [p for p in self.peaks if p.is_valid]
        if len(valid) < 2:
            raise ValueError(f"Need at least 2 valid peaks, have {len(valid)}.")

        if len(valid) == 2:
            U = calculate_U_two_peaks(valid[0], valid[1], self._B, corrections)
        else:
            U = refine_U_matrix(valid, self._B, corrections)

        self.set_U(U)
        return U

    def refine_lattice(self, crystal_system: str = None) -> dict:
        """Refine lattice parameters from stored peaks.

        Returns:
            dict with 'lattice', 'residuals', 'rms_error'.
        """
        return refine_lattice_from_peaks(self.peaks, self._lattice, crystal_system)

    def get_plane_info(self) -> dict:
        """Get scattering plane analysis."""
        return get_scattering_plane_info(self._U, self._B)

    def to_dict(self) -> dict:
        """Serialize UB matrix state for JSON storage."""
        return {
            'lattice': list(self._lattice),
            'U': self._U.tolist(),
            'peaks': [p.to_dict() for p in self.peaks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'UBMatrix':
        """Restore UB matrix state from dictionary."""
        lattice = tuple(d.get('lattice', [4.05, 4.05, 4.05, 90, 90, 90]))
        ub = cls(*lattice)
        U = d.get('U')
        if U is not None:
            ub.set_U(np.array(U))
        peaks_data = d.get('peaks', [])
        ub.peaks = [ObservedPeak.from_dict(p) for p in peaks_data]
        return ub


# ===== Training Mode: Hidden Orientation + Misalignment =====

def _random_rotation_matrix(max_angle_deg: float) -> np.ndarray:
    """Generate a random rotation matrix with angle up to max_angle_deg.

    Uses axis-angle representation with random axis and random angle.
    """
    # Random rotation axis (unit vector on sphere)
    axis = np.random.randn(3)
    norm = np.linalg.norm(axis)
    while norm < 1e-10:
        axis = np.random.randn(3)
        norm = np.linalg.norm(axis)
    axis = axis / norm

    # Random angle uniformly in [0, max_angle_deg]
    angle = math.radians(np.random.uniform(0, max_angle_deg))

    # Rodrigues' rotation formula
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    R = np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)
    return R


def generate_training_exercise(max_ori_angle: float = 10.0,
                                max_mis_angle: float = 5.0,
                                include_orientation: bool = True,
                                include_misalignment: bool = True) -> str:
    """Generate a training exercise hash with hidden orientation and/or misalignment.

    Args:
        max_ori_angle: Maximum orientation rotation angle (degrees).
        max_mis_angle: Maximum misalignment angle for omega/chi (degrees).
        include_orientation: Whether to include a random U rotation.
        include_misalignment: Whether to include angular misalignment.

    Returns:
        str: Encoded hash string.
    """
    if include_orientation:
        U = _random_rotation_matrix(max_ori_angle)
    else:
        U = np.eye(3)

    if include_misalignment:
        mis_omega = np.random.uniform(-max_mis_angle, max_mis_angle)
        mis_chi = np.random.uniform(-max_mis_angle, max_mis_angle)
    else:
        mis_omega = 0.0
        mis_chi = 0.0

    return encode_training(U, mis_omega, mis_chi)


def encode_training(U: np.ndarray, mis_omega: float, mis_chi: float) -> str:
    """Encode a training exercise (U matrix + misalignment) into a hash string.

    Packs 11 floats (9 for U + 2 for misalignment), XOR-obfuscates, base64 encodes.

    Args:
        U: 3x3 orientation matrix.
        mis_omega: In-plane misalignment (degrees).
        mis_chi: Out-of-plane misalignment (degrees).

    Returns:
        str: Encoded hash string.
    """
    values = list(U.flatten()) + [float(mis_omega), float(mis_chi)]
    packed = struct.pack('<11f', *values)
    obfuscated = _xor_bytes(packed, _OBFUSCATION_KEY)
    return base64.urlsafe_b64encode(obfuscated).decode('ascii')


def decode_training(hash_str: str) -> tuple:
    """Decode a training exercise hash string.

    Returns:
        tuple: (U_matrix as np.ndarray(3,3), mis_omega, mis_chi)
    """
    try:
        obfuscated = base64.urlsafe_b64decode(hash_str.encode('ascii'))
        packed = _xor_bytes(obfuscated, _OBFUSCATION_KEY)
        values = struct.unpack('<11f', packed)
        U = np.array(values[:9]).reshape(3, 3)
        mis_omega = values[9]
        mis_chi = values[10]
    except Exception as e:
        raise ValueError(f"Invalid training hash: {e}")
    # The hash stores float32: orthonormalise (the nearest rotation, polar
    # decomposition) so the hidden mount is an exact rotation.
    left, _, right = np.linalg.svd(validate_rotation_matrix(U))
    return left @ right, float(mis_omega), float(mis_chi)


def grade_alignment(gonio, sense, ki, kf, ub, corrections, u_true, b_true, zero_errors,
                    hkls, locked=None, tol_good=0.5, tol_close=2.0) -> dict:
    """Grade the operator's alignment against the truth by its worst miss.

    For each reflection in ``hkls``: the readouts the operator's belief
    commands -- ``ub`` (U @ B from the UB and the lattice fields) through
    ``solve_stage`` on ``gonio``, free, or on the plane lock's tilts
    ``locked`` ({inner axis: degrees}) when one is set -- plus ``corrections``
    and the hidden ``zero_errors`` ({axis: degrees}) are the physical angles.
    The miss is the larger of the angle between the true reflection in the
    lab, ``R_stage(physical) @ u_true @ b_true @ hkl`` (signed per ``sense``),
    and the commanded lab Q, and the 2theta difference between the commanded
    and the true |Q| at the same ``ki``, ``kf``. A true |Q| that closes no
    scattering triangle there is a miss of inf, named. A reflection the
    belief cannot reach is skipped and named in ``skipped``.

    Returns ``{"status", "summary", "worst_miss", "worst_hkl", "skipped"}``.
    The worst miss decides: "aligned" (<= ``tol_good`` degrees), "close"
    (<= ``tol_close``), else "way_off"; "cannot_assess" when ``b_true`` is
    None (no sample) or fewer than two non-parallel reflections are
    reachable. The summary names the worst miss and its HKL only, so it shows
    nothing of the hidden truth but how far the belief is from it.
    """
    def shown(hkl):
        return "(" + " ".join(f"{float(x):g}" for x in hkl) + ")"

    def cannot(reason, skipped=()):
        return {"status": "cannot_assess", "summary": f"Cannot assess: {reason}",
                "worst_miss": None, "worst_hkl": None, "skipped": list(skipped)}

    if b_true is None:
        return cannot("no sample is selected, so there is no crystal to grade against")
    ub = np.asarray(ub, dtype=float)
    flip = -1.0 if sense > 0 else 1.0           # +1 branch: -U B hkl on the lab Q
    misses, skipped = [], []
    for hkl in hkls:
        h = np.asarray(hkl, dtype=float)
        q_belief = ub @ h
        try:
            stt = stt_from_q_norm(float(np.linalg.norm(q_belief)), ki, kf, sense)
            q_lab = lab_q_from_stt(ki, kf, stt)
            readouts = solve_stage(gonio, flip * q_belief, q_lab, locked=locked)
        except ValueError as exc:               # StageUnreachable included
            skipped.append(f"{shown(hkl)}: {exc}")
            continue
        physical = {ax.name: readouts[ax.name] + corrections.get(ax.name, 0.0)
                    + zero_errors.get(ax.name, 0.0) for ax in gonio}
        q_true = u_true @ b_true @ h
        true_lab = stage_rotation(gonio, physical) @ (flip * q_true)
        miss = math.degrees(math.atan2(float(np.linalg.norm(np.cross(true_lab, q_lab))),
                                       float(true_lab @ q_lab)))
        try:
            stt_true = stt_from_q_norm(float(np.linalg.norm(q_true)), ki, kf, sense)
            miss = max(miss, abs(stt_true - stt))
        except ValueError:
            miss = math.inf                     # the true |Q| closes no triangle here
        misses.append((tuple(hkl), miss))

    reached = [np.asarray(hkl, dtype=float) for hkl, _ in misses]
    if not any(np.linalg.norm(np.cross(a, b)) > 1e-9
               for i, a in enumerate(reached) for b in reached[i + 1:]):
        return cannot("fewer than two non-parallel reflections are reachable", skipped)
    worst_hkl, worst = max(misses, key=lambda item: item[1])
    status = "aligned" if worst <= tol_good else "close" if worst <= tol_close else "way_off"
    summary = (f"{shown(worst_hkl)} closes no scattering triangle at this ki, kf"
               if math.isinf(worst) else f"Worst miss {worst:.2f}° at {shown(worst_hkl)}")
    return {"status": status, "summary": summary, "worst_miss": worst,
            "worst_hkl": worst_hkl, "skipped": skipped}
