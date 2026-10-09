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
    hkl_text,
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
    q_u = B @ np.asarray(hkl_u, dtype=float)
    q_v = B @ np.asarray(hkl_v, dtype=float)
    for name, hkl, q in (("along x", hkl_u, q_u), ("in plane", hkl_v, q_v)):
        if np.linalg.norm(q) < 1e-8:
            raise ValueError(f"the vector {name}, {hkl_text(hkl)}, is zero")
    if np.linalg.norm(np.cross(q_u, q_v)) < 1e-8 * np.linalg.norm(q_u) * np.linalg.norm(q_v):
        raise ValueError(f"{hkl_text(hkl_u)} and {hkl_text(hkl_v)} are parallel, so they span no plane")
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


# Residual flags (programme 3.1; D7 and M5 of the Unit 3 plan): a pair whose
# observed angle differs from its indexed angle by more than PAIR_FLAG_DEG, a
# peak whose |Q| differs from |B hkl| by more than Q_FLAG_FRACTION. When at
# least two peaks share one |Q| ratio to within Q_RATIO_SPREAD and that ratio
# is off by more than Q_FLAG_FRACTION, the lattice fields are named instead
# of the index.
PAIR_FLAG_DEG = 0.5
Q_FLAG_FRACTION = 0.02
Q_RATIO_SPREAD = 0.005


def _angle_deg(a, b):
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b)))


def alignment_residuals(ub, peaks, corrections=None) -> dict:
    """How the valid ``peaks`` agree with the operator's ``ub`` (U @ B, the
    lattice fields' B) and with each other, in the readout frame of
    ``corrections`` (the fit's frame, ``ObservedPeak.q_mount``).

    Per peak: ``q_obs`` = |q|, ``q_calc`` = |UB hkl| (= |B hkl|),
    ``q_mismatch`` = q_obs / q_calc - 1, ``angle_deg`` between q and UB hkl.
    Per pair: ``observed_deg`` between the two observed q, ``indexed_deg``
    between UB hkl_1 and UB hkl_2, ``difference_deg`` (observed - indexed).
    A flagged row carries its words in ``flag`` (None otherwise). Returns
    ``{"peaks", "pairs", "flags", "summary"}``; ``flags`` lists every
    flag's words with its reflection(s), ``summary`` is one line for the
    message center. Reads only the peaks and the UB, never the true mount.
    """
    ub = np.asarray(ub, dtype=float)
    rows, vectors = [], []
    for peak in peaks:
        if not peak.is_valid:
            continue
        q = peak.q_mount(corrections)
        q_ub = ub @ np.asarray(peak.hkl, dtype=float)
        q_obs, q_calc = float(np.linalg.norm(q)), float(np.linalg.norm(q_ub))
        rows.append({"hkl": tuple(peak.hkl), "q_obs": q_obs, "q_calc": q_calc,
                     "q_mismatch": q_obs / q_calc - 1.0, "angle_deg": _angle_deg(q, q_ub),
                     "flag": None})
        vectors.append((q, q_ub))

    ratios = [1.0 + row["q_mismatch"] for row in rows]
    lattice_off = (len(rows) >= 2 and max(ratios) / min(ratios) - 1.0 <= Q_RATIO_SPREAD
                   and abs(float(np.mean(ratios)) - 1.0) > Q_FLAG_FRACTION)
    flags = []
    for row in rows:
        if abs(row["q_mismatch"]) <= Q_FLAG_FRACTION:
            continue
        # |Q| goes as 1/length: the fields' lengths are the true ones times the ratio.
        cause = (f"lattice fields off by about {abs(float(np.mean(ratios)) - 1.0) * 100:.1f} %; "
                 "try Refine Lattice" if lattice_off else "likely mis-indexed")
        row["flag"] = f"|Q| is {row['q_mismatch'] * 100:+.1f} % from its indices: {cause}"
        flags.append(f"{hkl_text(row['hkl'])}: {row['flag']}")

    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            observed = _angle_deg(vectors[i][0], vectors[j][0])
            indexed = _angle_deg(vectors[i][1], vectors[j][1])
            pair = {"hkl1": rows[i]["hkl"], "hkl2": rows[j]["hkl"], "observed_deg": observed,
                    "indexed_deg": indexed, "difference_deg": observed - indexed, "flag": None}
            if abs(pair["difference_deg"]) > PAIR_FLAG_DEG:
                pair["flag"] = (f"the angle between {hkl_text(pair['hkl1'])} and "
                                f"{hkl_text(pair['hkl2'])} is {observed:.2f}° observed but "
                                f"{indexed:.2f}° from their indices: one of them is likely "
                                "mis-indexed")
                flags.append(pair["flag"])
            pairs.append(pair)

    summary = f"UB residuals: {len(rows)} peaks"
    if rows:
        summary += f", worst {max(r['angle_deg'] for r in rows):.3f}° off the UB"
    if pairs:
        summary += f", worst pair {max(abs(p['difference_deg']) for p in pairs):.3f}° off its indices"
    summary += "; flagged: " + "; ".join(flags) if flags else "; no flags"
    return {"peaks": rows, "pairs": pairs, "flags": flags, "summary": summary}


# Refine Lattice by crystal system (Unit 3, D8/D12/D13). Each system maps its
# free parameters onto the six components (g11, g22, g33, g12, g13, g23) of
# the reciprocal metric G* = B^T B, in which |Q|^2 = hkl . G* . hkl is linear.
_G_STAR = ("g11", "g22", "g33", "g12", "g13", "g23")
_METRIC_CONSTRAINTS = {
    "cubic": [{"g11": 1, "g22": 1, "g33": 1}],
    "tetragonal": [{"g11": 1, "g22": 1}, {"g33": 1}],
    "orthorhombic": [{"g11": 1}, {"g22": 1}, {"g33": 1}],
    # gamma = 120 deg makes gamma* = 60 deg: a*.b* = |a*|^2 / 2.
    "hexagonal": [{"g11": 1, "g22": 1, "g12": 0.5}, {"g33": 1}],
    "rhombohedral": [{"g11": 1, "g22": 1, "g33": 1}, {"g12": 1, "g13": 1, "g23": 1}],
    # Monoclinic: the unique axis's two cross terms stay zero.
    "monoclinic_a": [{"g11": 1}, {"g22": 1}, {"g33": 1}, {"g23": 1}],
    "monoclinic_b": [{"g11": 1}, {"g22": 1}, {"g33": 1}, {"g13": 1}],
    "monoclinic_c": [{"g11": 1}, {"g22": 1}, {"g33": 1}, {"g12": 1}],
    "triclinic": [{name: 1} for name in _G_STAR],
}
# D13's order: the highest symmetry first.
CRYSTAL_SYSTEMS_BY_SYMMETRY = ("cubic", "hexagonal", "trigonal", "tetragonal",
                               "orthorhombic", "monoclinic", "triclinic")


def _metric_setting(system, lattice):
    """The constraint set ``system`` takes for ``lattice`` (a, b, c, alpha,
    beta, gamma), or None when the lattice does not have that system's
    metric (lengths equal to 1e-6 relative, angles to 1e-4 deg)."""
    a, b, c, alpha, beta, gamma = (float(x) for x in lattice)

    def same(x, y):
        return abs(x - y) <= 1e-6 * max(abs(x), abs(y))

    def deg(x, y):
        return abs(x - y) <= 1e-4

    right = [deg(angle, 90.0) for angle in (alpha, beta, gamma)]
    hexagonal = same(a, b) and right[0] and right[1] and deg(gamma, 120.0)
    rhombohedral = same(a, b) and same(b, c) and deg(alpha, beta) and deg(beta, gamma)
    if system == "cubic":
        return "cubic" if all(right) and same(a, b) and same(b, c) else None
    if system == "tetragonal":
        return "tetragonal" if all(right) and same(a, b) else None
    if system == "orthorhombic":
        return "orthorhombic" if all(right) else None
    if system == "hexagonal":
        return "hexagonal" if hexagonal else None
    if system == "trigonal":
        return "hexagonal" if hexagonal else "rhombohedral" if rhombohedral else None
    if system == "monoclinic":
        if sum(right) < 2:
            return None
        # The unique axis: the one angle not 90 deg, b when none.
        return "monoclinic_" + ("a" if not right[0] else "c" if not right[2] else "b")
    if system == "triclinic":
        return "triclinic"
    raise ValueError(f"'{system}' is not a crystal system")


def lattice_crystal_system(lattice):
    """D13: the highest-symmetry crystal system whose metric ``lattice`` has."""
    return next(s for s in CRYSTAL_SYSTEMS_BY_SYMMETRY if _metric_setting(s, lattice))


def refine_lattice_from_peaks(peaks: list, initial_lattice: tuple,
                              crystal_system: str = None) -> dict:
    """Refine the lattice from the valid peaks' |Q|, by crystal system.

    Constrained linear least squares of |Q|^2 (A^-2) in the reciprocal metric
    G* = B^T B: each system refines exactly its own parameters -- triclinic 6,
    monoclinic 4 (unique axis from ``initial_lattice``: the one angle not 90,
    b when none), orthorhombic 3, tetragonal 2, hexagonal and trigonal on
    hexagonal axes 2, trigonal on rhombohedral axes 2, cubic 1. The lattice
    comes back from the direct metric G = (2 pi)^2 (G*)^-1. ``crystal_system``
    None takes the highest-symmetry system ``initial_lattice`` satisfies
    (``lattice_crystal_system``); ``initial_lattice`` otherwise only decides
    the setting.

    Ceiling (D8): |Q|^2 rows only, so no arc zero error leaks into the lattice
    (they are rotation-invariant); monoclinic needs four reflections and
    triclinic six with independent quadratic forms. Upgrade path: pair
    dot-product rows (q_i . q_j = hkl_i . G* . hkl_j), which decide a
    triclinic cell from three peaks but read the peaks' relative orientation,
    so arc zero errors leak in. Ceiling (D12): unweighted, since TAVI records
    no per-peak uncertainty; upgrade path: weights from the peak fits' widths.

    Raises ValueError naming the system, its parameter count and the
    independent rows the peaks give when they cannot decide it; also for a
    lattice that does not have the system's metric (a trigonal lattice in
    neither setting included) and a fitted G* that is not positive definite.

    Returns:
        dict with 'lattice' (refined params), 'residuals' (per-peak),
        'rms_error' and 'crystal_system' (the system refined).
    """
    system = crystal_system or lattice_crystal_system(initial_lattice)
    setting = _metric_setting(system, initial_lattice)
    if setting is None:
        a, b, c, alpha, beta, gamma = initial_lattice
        raise ValueError(
            f"the lattice fields (a={a:g}, b={b:g}, c={c:g}, α={alpha:g}, β={beta:g}, "
            f"γ={gamma:g}) do not have the {system} metric; correct them or the space group")
    constraint = np.array([[column.get(name, 0.0) for column in _METRIC_CONSTRAINTS[setting]]
                           for name in _G_STAR], dtype=float)
    n_params = constraint.shape[1]

    observed = [(tuple(p.hkl), float(np.linalg.norm(p.q_lab))) for p in peaks if p.is_valid]
    rows = np.array([[h * h, k * k, l * l, 2 * h * k, 2 * h * l, 2 * k * l]
                     for (h, k, l), _ in observed], dtype=float).reshape(-1, 6) @ constraint
    rank = int(np.linalg.matrix_rank(rows)) if len(observed) else 0
    if rank < n_params:
        raise ValueError(
            f"{system} refinement fits {n_params} parameter{'s' if n_params > 1 else ''} but "
            f"the {len(observed)} valid peak{'s' if len(observed) != 1 else ''} give "
            f"{rank} independent |Q|² row{'s' if rank != 1 else ''}; add reflections "
            "that decide the rest")
    params, *_ = np.linalg.lstsq(rows, np.array([q * q for _, q in observed]), rcond=None)
    g = constraint @ params
    g_star = np.array([[g[0], g[3], g[4]], [g[3], g[1], g[5]], [g[4], g[5], g[2]]])
    if not np.all(np.linalg.eigvalsh(g_star) > 0):
        raise ValueError(f"the {system} fit gives a reciprocal metric that is not positive "
                         "definite: these peaks describe no lattice")
    metric = (2 * math.pi) ** 2 * np.linalg.inv(g_star)
    lengths = np.sqrt(np.diag(metric))

    def angle(i, j):
        cosine = metric[i, j] / (lengths[i] * lengths[j])
        return math.degrees(math.acos(max(-1.0, min(1.0, float(cosine)))))

    refined = (float(lengths[0]), float(lengths[1]), float(lengths[2]),
               angle(1, 2), angle(0, 2), angle(0, 1))

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
        'crystal_system': system,
    }


def small_integer_indices(vec, basis, max_index=6, tol_deg=0.1):
    """The smallest integer triple n (each |n_i| <= ``max_index``) whose
    Cartesian ``basis @ n`` lies along the Cartesian ``vec`` (either sign)
    within ``tol_deg``, or None. The angle is measured between Cartesian
    vectors, so the lattice metric is honoured. Smallest: the least max |n_i|,
    then the least sum |n_i|, then lexicographic; the first non-zero
    component is positive. Deterministic: one exhaustive pass, no tie."""
    vec = np.asarray(vec, dtype=float)
    if not np.linalg.norm(vec) > 0:
        return None
    span = np.arange(-max_index, max_index + 1)
    n = np.array(np.meshgrid(span, span, span, indexing="ij")).reshape(3, -1).T
    lead = np.where(n[:, 0] != 0, n[:, 0], np.where(n[:, 1] != 0, n[:, 1], n[:, 2]))
    n = n[lead > 0]
    cart = n @ np.asarray(basis, dtype=float).T
    angle = np.degrees(np.arctan2(np.linalg.norm(np.cross(cart, vec), axis=1),
                                  np.abs(cart @ vec)))
    matches = [tuple(int(x) for x in t) for t in n[angle <= tol_deg]]
    if not matches:
        return None
    return min(matches, key=lambda t: (max(map(abs, t)), sum(map(abs, t)), t))


def get_scattering_plane_info(U: np.ndarray, B: np.ndarray) -> dict:
    """Analyze the scattering plane defined by the current UB matrix.

    The instrument scattering plane is the mounted sample xz-plane (qy=0).
    With U applied, crystal directions map to mounted sample frame via U @ B.

    Args:
        U: 3x3 orientation matrix.
        B: 3x3 B matrix.

    Returns:
        dict with scattering plane analysis: ``plane_normal_hkl`` (the
        vertical as a raw reciprocal vector), ``in_plane_vector1_hkl`` and
        ``in_plane_vector2_hkl`` (mount x and z, Miller coefficients),
        ``chi_misalignment_deg`` (the c* elevation above the horizontal),
        ``omega_offset_deg`` (the a* azimuth from mount x) and
        ``zone_axis_uvw`` (the vertical as integer [u v w], or None).
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
            'zone_axis_uvw': None,
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
        # The zone axis [u v w]: the direct-lattice direction along the
        # vertical, against the direct basis 2 pi (UB)^-T (None: no small one).
        'zone_axis_uvw': small_integer_indices(y_sample, 2 * math.pi * UB_inv.T),
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
        """True if U is the identity matrix (TAVI's standard setting)."""
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
        """Set U to identity, TAVI's standard setting."""
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


# ===== Training Mode: Hidden Mount Rotation =====

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
                               include_orientation: bool = True,
                               accept=None, max_draws: int = 50) -> str:
    """Generate a mount-only training exercise hash: a hidden rotation of the
    crystal in its mount (``U_true = R_hidden @ U_described``). Both motor-zero
    values of the code are written as 0; the code keeps its 11-float layout.

    Args:
        max_ori_angle: Maximum rotation angle (degrees).
        include_orientation: Whether to include a random rotation (False
            gives the identity, i.e. no hidden error).
        accept: Optional ``accept(R) -> None | str`` called with each drawn
            rotation: None takes it, a string is the reason it is refused and
            the rotation is drawn again, up to ``max_draws`` times.

    Returns:
        str: Encoded hash string.

    Raises:
        ValueError: when no draw was accepted; the message carries the last
            reason.
    """
    reason = None
    for _ in range(max_draws if include_orientation else 1):
        U = _random_rotation_matrix(max_ori_angle) if include_orientation else np.eye(3)
        reason = accept(U) if accept is not None else None
        if reason is None:
            return encode_training(U, 0.0, 0.0)
    raise ValueError(f"no hidden rotation within {max_ori_angle:g}° could be drawn "
                     f"that this instrument can observe ({max_draws} tried): {reason}")


def encode_training(U: np.ndarray, mis_omega: float, mis_chi: float) -> str:
    """Encode a training exercise (U matrix + two motor-zero floats) into a hash string.

    Packs 11 floats (9 for U + 2 motor-zero values, which a mount-only
    exercise leaves 0), XOR-obfuscates, base64 encodes.

    Args:
        U: 3x3 orientation matrix.
        mis_omega: Turntable motor-zero (degrees); retired, 0 in every new code.
        mis_chi: Lower-arc motor-zero (degrees); retired, 0 in every new code.

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


MOTOR_ZERO_REFUSAL = ("this exercise was made by an older TAVI and contains motor-zero "
                      "errors, which are no longer simulated; ask for a new code")


def decode_mount_exercise(hash_str: str) -> np.ndarray:
    """The hidden mount rotation of a mount-only exercise code.

    Raises ``ValueError`` with the reason, applying nothing, for a code that
    does not decode (a retired Misalignment-dock code included) or whose
    motor-zero values are not 0.
    """
    try:
        rotation, mis_omega, mis_chi = decode_training(hash_str)
    except ValueError as exc:
        raise ValueError(f"this exercise code cannot be read ({exc}); it may be damaged or "
                         "made by an older TAVI. Ask for a new code") from exc
    if mis_omega != 0.0 or mis_chi != 0.0:
        raise ValueError(MOTOR_ZERO_REFUSAL)
    return rotation


def has_two_nonparallel(hkls) -> bool:
    """True when two of ``hkls`` point in different directions (so they fix an orientation)."""
    vectors = [np.asarray(hkl, dtype=float) for hkl in hkls]
    return any(np.linalg.norm(np.cross(a, b)) > 1e-9
               for i, a in enumerate(vectors) for b in vectors[i + 1:])


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
            skipped.append(f"{hkl_text(hkl)}: {exc}")
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

    if not has_two_nonparallel(hkl for hkl, _ in misses):
        return cannot("fewer than two non-parallel reflections are reachable", skipped)
    worst_hkl, worst = max(misses, key=lambda item: item[1])
    status = "aligned" if worst <= tol_good else "close" if worst <= tol_close else "way_off"
    summary = (f"{hkl_text(worst_hkl)} closes no scattering triangle at this ki, kf"
               if math.isinf(worst) else f"Worst miss {worst:.2f}° at {hkl_text(worst_hkl)}")
    return {"status": status, "summary": summary, "worst_miss": worst,
            "worst_hkl": worst_hkl, "skipped": skipped}
