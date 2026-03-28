"""UB Matrix calculations for TAVI.

Implements the Busing-Levy (1967) UB matrix formalism for crystal orientation
on a triple-axis neutron spectrometer.

The UB matrix transforms Miller indices (HKL) to lab-frame Q vectors:
    Q_lab = UB @ [H, K, L]

where:
    B = reciprocal lattice metric matrix (from lattice parameters)
    U = crystal orientation matrix (orthogonal rotation, determined from Bragg peaks)
    UB = U @ B (combined transformation)

Convention: a* along x, b* in xy-plane, c* general (matching reciprocal_space.py).
"""
import math
import base64
import struct
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# Obfuscation key for training hash encoding (not cryptographic security)
_OBFUSCATION_KEY = b'TAVI_UB_TRAIN_26'


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with repeating key."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def compute_B_matrix(a, b, c, alpha, beta, gamma):
    """Compute the B matrix (Busing-Levy convention) from lattice parameters.

    The B matrix transforms Miller indices to Cartesian reciprocal-space coordinates:
        Q_crystal = B @ [H, K, L]

    Convention: a* along x, b* in xy-plane, c* general.

    Args:
        a, b, c: Lattice parameters in Angstroms.
        alpha, beta, gamma: Lattice angles in degrees.

    Returns:
        np.ndarray: 3x3 B matrix.
    """
    alpha_r = math.radians(alpha)
    beta_r = math.radians(beta)
    gamma_r = math.radians(gamma)

    ca, cb, cg = math.cos(alpha_r), math.cos(beta_r), math.cos(gamma_r)
    sa, sb, sg = math.sin(alpha_r), math.sin(beta_r), math.sin(gamma_r)

    # Unit cell volume
    V = a * b * c * math.sqrt(1 - ca**2 - cb**2 - cg**2 + 2*ca*cb*cg)
    if V <= 0:
        raise ValueError("Invalid lattice parameters: unit cell volume is zero or negative.")

    # Reciprocal lattice parameters
    two_pi = 2.0 * math.pi
    a_star = two_pi * b * c * sa / V
    b_star = two_pi * a * c * sb / V
    c_star = two_pi * a * b * sg / V

    # Reciprocal lattice angles
    ca_star = (cb*cg - ca) / (sb*sg)
    cb_star = (ca*cg - cb) / (sa*sg)
    cg_star = (ca*cb - cg) / (sa*sb)

    sa_star = math.sqrt(max(0.0, 1 - ca_star**2))
    sb_star = math.sqrt(max(0.0, 1 - cb_star**2))
    sg_star = math.sqrt(max(0.0, 1 - cg_star**2))

    _EPS = 1e-12
    if sg_star < _EPS:
        raise ValueError(
            f"Degenerate reciprocal lattice: sg_star={sg_star:.3e} (cg_star={cg_star:.6f}). "
            "The B matrix cannot be constructed because gamma* is 0° or 180°. "
            "Check that the lattice angles do not produce a degenerate reciprocal cell."
        )

    # B matrix: a* along x, b* in xy-plane
    B = np.array([
        [a_star, b_star * cg_star, c_star * cb_star],
        [0.0,    b_star * sg_star, c_star * (ca_star - cb_star*cg_star) / sg_star],
        [0.0,    0.0,              c_star * math.sqrt(
            max(0.0, 1 - ca_star**2 - cb_star**2 - cg_star**2 + 2*ca_star*cb_star*cg_star)
        ) / sg_star],
    ])

    return B


def angles_to_q_lab(sth, saz, stt, ki, kf):
    """Convert instrument angles to Q vector in lab frame.

    Uses the same formulas as PUMA_instrument_definition.calculate_q_and_deltaE.

    Args:
        sth: Sample theta (omega) in degrees.
        saz: Sample azimuthal angle in degrees.
        stt: Sample two-theta in degrees.
        ki: Incident wavevector (inverse Angstroms).
        kf: Scattered wavevector (inverse Angstroms).

    Returns:
        np.ndarray: [qx, qy, qz] in inverse Angstroms.
    """
    stt_r = math.radians(stt)
    sth_r = math.radians(sth)
    saz_r = math.radians(saz)

    Q_mag = math.sqrt(ki**2 + kf**2 - 2*ki*kf*math.cos(stt_r))
    qx = Q_mag * math.cos(sth_r - stt_r / 2)
    qy = Q_mag * math.sin(sth_r - stt_r / 2)
    qz = -kf * math.tan(saz_r)

    return np.array([qx, qy, qz])


@dataclass
class ObservedPeak:
    """A Bragg peak observation with HKL and instrument angles.

    Attributes:
        hkl: Miller indices (H, K, L).
        angles: Instrument angles (omega/sth, chi/saz, stt) in degrees.
        ki: Incident wavevector at observation (inverse Angstroms).
        kf: Scattered wavevector at observation (inverse Angstroms).
        locked: Whether this peak entry is locked from editing.
    """
    hkl: tuple = (0.0, 0.0, 0.0)
    angles: tuple = (0.0, 0.0, 0.0)  # (sth, saz, stt)
    ki: float = 0.0
    kf: float = 0.0
    locked: bool = False

    @property
    def q_lab(self) -> np.ndarray:
        """Compute Q in lab frame from stored angles and wavevectors."""
        sth, saz, stt = self.angles
        if self.ki <= 0 or self.kf <= 0:
            return np.array([0.0, 0.0, 0.0])
        return angles_to_q_lab(sth, saz, stt, self.ki, self.kf)

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
        )


def calculate_U_two_peaks(peak1: ObservedPeak, peak2: ObservedPeak,
                          B: np.ndarray) -> np.ndarray:
    """Calculate the U orientation matrix from two observed Bragg peaks.

    Uses the Busing-Levy (1967) method:
    1. Compute Q vectors in crystal frame (B @ hkl) and lab frame (from angles).
    2. Build orthonormal triads in both frames.
    3. U = T_lab @ T_crystal^(-1)

    Args:
        peak1: First observed Bragg peak.
        peak2: Second observed Bragg peak.
        B: 3x3 B matrix.

    Returns:
        np.ndarray: 3x3 U matrix (orthogonal, det ~ +1).

    Raises:
        ValueError: If peaks are collinear or invalid.
    """
    # Crystal-frame Q vectors
    q1_c = B @ np.array(peak1.hkl)
    q2_c = B @ np.array(peak2.hkl)

    # Lab-frame Q vectors
    q1_l = peak1.q_lab
    q2_l = peak2.q_lab

    # Validate
    for label, v in [("peak1 crystal", q1_c), ("peak2 crystal", q2_c),
                     ("peak1 lab", q1_l), ("peak2 lab", q2_l)]:
        if np.linalg.norm(v) < 1e-8:
            raise ValueError(f"Zero-length Q vector for {label}.")

    # Build orthonormal triad in crystal frame
    t1_c = q1_c / np.linalg.norm(q1_c)
    cross_c = np.cross(q1_c, q2_c)
    if np.linalg.norm(cross_c) < 1e-8:
        raise ValueError("Peaks are collinear in crystal frame — cannot determine U.")
    t2_c = cross_c / np.linalg.norm(cross_c)
    t3_c = np.cross(t1_c, t2_c)
    T_crystal = np.column_stack([t1_c, t2_c, t3_c])

    # Build orthonormal triad in lab frame
    t1_l = q1_l / np.linalg.norm(q1_l)
    cross_l = np.cross(q1_l, q2_l)
    if np.linalg.norm(cross_l) < 1e-8:
        raise ValueError("Peaks are collinear in lab frame — cannot determine U.")
    t2_l = cross_l / np.linalg.norm(cross_l)
    t3_l = np.cross(t1_l, t2_l)
    T_lab = np.column_stack([t1_l, t2_l, t3_l])

    # U = T_lab @ T_crystal^(-1)
    # Since T_crystal is orthonormal, T_crystal^(-1) = T_crystal^T
    U = T_lab @ T_crystal.T

    return U


def refine_U_matrix(peaks: list, B: np.ndarray) -> np.ndarray:
    """Calculate U from multiple peaks using SVD-based Procrustes solution.

    Minimizes sum_i ||q_lab_i - U @ B @ hkl_i||^2 subject to U being orthogonal.

    Falls back to two-peak method if only 2 valid peaks.

    Args:
        peaks: List of ObservedPeak instances.
        B: 3x3 B matrix.

    Returns:
        np.ndarray: 3x3 U matrix (orthogonal, det ~ +1).
    """
    valid_peaks = [p for p in peaks if p.is_valid]
    if len(valid_peaks) < 2:
        raise ValueError(f"Need at least 2 valid peaks, got {len(valid_peaks)}.")
    if len(valid_peaks) == 2:
        return calculate_U_two_peaks(valid_peaks[0], valid_peaks[1], B)

    # Build paired point sets: q_crystal (P) and q_lab (Q)
    # We want U such that Q ~ U @ P
    P = np.zeros((3, len(valid_peaks)))
    Q = np.zeros((3, len(valid_peaks)))

    for i, peak in enumerate(valid_peaks):
        P[:, i] = B @ np.array(peak.hkl)
        Q[:, i] = peak.q_lab

    # Cross-covariance matrix
    H_mat = P @ Q.T  # Note: we want U s.t. Q = U @ P, so H = P @ Q^T

    # SVD
    Usvd, S, Vt = np.linalg.svd(H_mat)

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

    # Apply constraints based on crystal system
    if crystal_system in ("cubic",):
        # Scale all equally, keep angles fixed
        a_new = a0 * avg_scale
        refined = (a_new, a_new, a_new, 90.0, 90.0, 90.0)
    elif crystal_system in ("tetragonal",):
        a_new = a0 * avg_scale
        c_new = c0 * avg_scale
        refined = (a_new, a_new, c_new, 90.0, 90.0, 90.0)
    elif crystal_system in ("hexagonal",):
        a_new = a0 * avg_scale
        c_new = c0 * avg_scale
        refined = (a_new, a_new, c_new, 90.0, 90.0, 120.0)
    elif crystal_system in ("orthorhombic",):
        a_new = a0 * avg_scale
        b_new = b0 * avg_scale
        c_new = c0 * avg_scale
        refined = (a_new, b_new, c_new, 90.0, 90.0, 90.0)
    else:
        # General: uniform scaling of lengths
        a_new = a0 * avg_scale
        b_new = b0 * avg_scale
        c_new = c0 * avg_scale
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

    The instrument scattering plane is the xy-plane (qz=0).
    With U applied, crystal directions map to lab frame via U @ B.

    Args:
        U: 3x3 orientation matrix.
        B: 3x3 B matrix.

    Returns:
        dict with scattering plane analysis.
    """
    UB = U @ B

    # The lab z-axis (out of scattering plane) in crystal HKL coordinates
    # Q_lab = UB @ hkl => hkl = UB^{-1} @ Q_lab
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

    # The lab z direction in HKL space (plane normal)
    z_lab = np.array([0.0, 0.0, 1.0])
    plane_normal_hkl = UB_inv @ z_lab

    # In-plane vectors: lab x and y in HKL space
    x_lab = np.array([1.0, 0.0, 0.0])
    y_lab = np.array([0.0, 1.0, 0.0])
    in_plane_v1 = UB_inv @ x_lab
    in_plane_v2 = UB_inv @ y_lab

    # Chi misalignment: angle between crystal c* axis and lab z
    # c* direction in crystal frame = B @ [0,0,1]
    c_star_crystal = B @ np.array([0.0, 0.0, 1.0])
    c_star_lab = U @ c_star_crystal
    c_star_lab_norm = c_star_lab / np.linalg.norm(c_star_lab)

    # Angle from horizontal plane (complement of angle with z)
    chi_mis = math.degrees(math.asin(np.clip(c_star_lab_norm[2], -1, 1)))

    # Omega offset: rotation of a* from lab x in the xy-plane
    a_star_crystal = B @ np.array([1.0, 0.0, 0.0])
    a_star_lab = U @ a_star_crystal
    omega_offset = math.degrees(math.atan2(a_star_lab[1], a_star_lab[0]))

    return {
        'plane_normal_hkl': tuple(plane_normal_hkl),
        'in_plane_vector1_hkl': tuple(in_plane_v1),
        'in_plane_vector2_hkl': tuple(in_plane_v2),
        'chi_misalignment_deg': chi_mis,
        'omega_offset_deg': omega_offset,
    }


class UBMatrix:
    """Manages the UB matrix for crystal orientation on a TAS.

    The UB matrix transforms Miller indices to lab-frame Q:
        Q_lab = UB @ [H, K, L]

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
        U = np.asarray(U, dtype=float)
        if U.shape != (3, 3):
            raise ValueError("U must be a 3x3 matrix.")
        self._U = U.copy()
        self._UB = self._U @ self._B

    def set_UB(self, UB: np.ndarray):
        """Set the UB matrix directly, extract U = UB @ B^(-1)."""
        UB = np.asarray(UB, dtype=float)
        if UB.shape != (3, 3):
            raise ValueError("UB must be a 3x3 matrix.")
        self._UB = UB.copy()
        try:
            B_inv = np.linalg.inv(self._B)
            self._U = self._UB @ B_inv
        except np.linalg.LinAlgError:
            self._U = np.eye(3)

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
    def calculate_U_from_peaks(self) -> np.ndarray:
        """Calculate U from stored peaks and apply it.

        Returns:
            np.ndarray: The calculated U matrix.
        """
        valid = [p for p in self.peaks if p.is_valid]
        if len(valid) < 2:
            raise ValueError(f"Need at least 2 valid peaks, have {len(valid)}.")

        if len(valid) == 2:
            U = calculate_U_two_peaks(valid[0], valid[1], self._B)
        else:
            U = refine_U_matrix(valid, self._B)

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
    axis = axis / np.linalg.norm(axis)

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
        return U, float(mis_omega), float(mis_chi)
    except Exception as e:
        raise ValueError(f"Invalid training hash: {e}")


def check_training_quality(student_U: np.ndarray, teacher_U: np.ndarray,
                           student_psi: float, student_kappa: float,
                           mis_omega: float, mis_chi: float,
                           tol_good: float = 0.5, tol_close: float = 2.0) -> dict:
    """Check student's alignment against teacher's hidden exercise.

    Args:
        student_U: Student's calculated U matrix.
        teacher_U: Teacher's hidden U matrix.
        student_psi: Student's psi offset (corrects omega misalignment).
        student_kappa: Student's kappa offset (corrects chi misalignment).
        mis_omega: Hidden omega misalignment.
        mis_chi: Hidden chi misalignment.
        tol_good: Tolerance for "aligned" (degrees).
        tol_close: Tolerance for "close" (degrees).

    Returns:
        dict with per-component feedback and overall status.
    """
    # Misalignment check (same as existing misalignment dock)
    in_plane_error = abs(student_psi - (-mis_omega))
    out_of_plane_error = abs(student_kappa - (-mis_chi))

    def status_for_error(err):
        if err <= tol_good:
            return "aligned"
        elif err <= tol_close:
            return "close"
        else:
            return "way_off"

    in_plane_status = status_for_error(in_plane_error)
    out_of_plane_status = status_for_error(out_of_plane_error)

    # Orientation check: angle between student and teacher U matrices
    # Rotation difference: R_diff = student_U @ teacher_U^T
    # Angle = arccos((trace(R_diff) - 1) / 2)
    R_diff = student_U @ teacher_U.T
    trace = np.clip(np.trace(R_diff), -1, 3)
    ori_angle = math.degrees(math.acos(np.clip((trace - 1) / 2, -1, 1)))

    ori_status = status_for_error(ori_angle)

    def hint_for_error(err, status):
        if status == "aligned":
            return "Well aligned!"
        elif status == "close":
            return f"Close (~{err:.1f}\u00b0 off)"
        elif err <= 5.0:
            return f"Getting there (~{err:.1f}\u00b0 off)"
        else:
            return f"Way off (>{err:.0f}\u00b0)"

    # Overall: worst of all three
    status_priority = {"aligned": 0, "close": 1, "way_off": 2}
    all_statuses = [in_plane_status, out_of_plane_status, ori_status]
    overall = max(all_statuses, key=lambda s: status_priority[s])

    return {
        'in_plane': in_plane_status,
        'in_plane_error': in_plane_error,
        'in_plane_hint': hint_for_error(in_plane_error, in_plane_status),
        'out_of_plane': out_of_plane_status,
        'out_of_plane_error': out_of_plane_error,
        'out_of_plane_hint': hint_for_error(out_of_plane_error, out_of_plane_status),
        'orientation': ori_status,
        'orientation_error': ori_angle,
        'orientation_hint': hint_for_error(ori_angle, ori_status),
        'overall': overall,
    }
