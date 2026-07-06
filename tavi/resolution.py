"""Theoretical triple-axis resolution (Cooper-Nathans and Popovici).

General-purpose, dependency-light (numpy + stdlib only; no Qt, no mcstasscript,
no scipy) computation of the 4-D TAS resolution ellipsoid in the ``(dQ_par,
dQ_perp, dQ_z, dE)`` basis (Q_par along the scattering vector, Q_perp the
in-plane perpendicular, Q_z the vertical, E the energy transfer).

Matrix convention (ONE convention, used everywhere here)
--------------------------------------------------------
``ResolutionResult.matrix`` is the *FWHM-normalized* resolution matrix ``M``:
the resolution function is ``R(x) ~ exp(-1/2 * x^T M x)`` with ``M`` the
inverse-covariance (precision) matrix in the units meV / Angstrom^-1. From it,

* marginal ("vanadium") FWHM along axis i:  ``2*sqrt(2*ln2) * sqrt(inv(M)[i,i])``
* coherent ("Bragg") FWHM along axis i:     ``sqrt(8*ln2 / M[i,i])``

This is exactly the matrix returned by ISAR ``cn_resolution_matrix`` (which
builds ``8*ln2 * N`` from FWHM-valued divergences) and, equivalently, the ResLib
/ neutronpy Popovici matrix (whose divergences are pre-scaled by
``1/sqrt(8*ln2)`` to sigma, giving the same precision matrix). No convention
conversion is required between the two methods.

Attribution
-----------
* Cooper-Nathans kernel: ported verbatim from ISAR ``isar/synth/resolution.py``,
  itself a port of the ResCal ``rc_cnmat`` formulation
  (M. J. Cooper & R. Nathans, Acta Cryst. 23, 357 (1967)); only the resolution
  matrix is used, not the intensity prefactor (so CN ``r0`` is ``None``).
* Popovici kernel: ported from neutronpy
  (``neutronpy/instrument/tas_instrument.py``, D. Fobes et al., MIT license),
  a Python translation of ResLib 3.4c (A. Zheludev, ORNL, 1999-2007) implementing
  the Popovici method (M. Popovici, Acta Cryst. A31, 507 (1975)). neutronpy is
  NOT a runtime dependency; the math is reimplemented here.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Optional

import numpy as np

# --- physical / unit constants -------------------------------------------------
_ARCMIN = math.pi / (180.0 * 60.0)          # arcmin -> rad (FWHM-valued)
_EMEV_PER_K2 = 2.072142                       # E(meV) = 2.072142 * k^2  (Angstrom^-2)
_F = 1.0 / _EMEV_PER_K2                        # meV -> Angstrom^-2
_S2F = 2.0 * math.sqrt(2.0 * math.log(2.0))    # sigma -> FWHM
_EIGHT_LN2 = 8.0 * math.log(2.0)               # FWHM^2 <-> variance normalization
_FLAT_RADIUS_CM = 1.0e6                         # "flat" component radius (ResLib default)

FALLBACK_FWHM = 0.6  # meV, elastic_energy_fwhm() fallback when the triangle won't close

# --- documented Popovici spatial defaults (cm), applied + recorded when missing ---
_DEFAULT_DIMS = {
    "source_width": 6.0, "source_height": 12.0,
    "mono_width": 20.0, "mono_height": 20.0, "mono_depth": 0.2,
    "sample_width": 1.0, "sample_height": 1.0, "sample_depth": 1.0,
    "ana_width": 20.0, "ana_height": 20.0, "ana_depth": 0.2,
    "det_width": 2.5, "det_height": 10.0,
    "monitor_width": 5.0, "monitor_height": 12.0,
}
_DEFAULT_ARMS = (200.0, 200.0, 150.0, 100.0, 200.0)  # L0, L1, L2, L3, L1mon (cm)


# ==============================================================================
# Config / Result dataclasses
# ==============================================================================
@dataclass(frozen=True)
class ResolutionConfig:
    """Immutable resolution-calculation inputs (ISAR CN vocabulary + Popovici).

    Cooper-Nathans fields are required; the Popovici extension fields all default
    to ``None`` (flat / absent), in which case ``resolution(method="auto")``
    stays Cooper-Nathans.
    """
    # --- Cooper-Nathans core -----------------------------------------------
    dm: float                       # monochromator d-spacing (Angstrom)
    da: float                       # analyzer d-spacing (Angstrom)
    eta_m: float                    # mono horizontal mosaic (arcmin, FWHM)
    eta_a: float                    # analyzer horizontal mosaic (arcmin)
    sm: int                         # mono scattering sense (+1 / -1)
    ss: int                         # sample scattering sense
    sa: int                         # analyzer scattering sense
    kfix: float                     # fixed wavevector (Angstrom^-1)
    fx: int                         # 1 = ki fixed, 2 = kf fixed
    alf: tuple                      # (ALF1..ALF4) horizontal collimations (arcmin)
    bet: tuple                      # (BET1..BET4) vertical collimations (arcmin)
    q0: float                       # |Q| (Angstrom^-1)
    w: float                        # energy transfer (meV)
    eta_s: Optional[float] = None   # sample horizontal mosaic (arcmin); <=0/None -> eta_m

    # --- Popovici extensions (all optional; None -> CN-only) ---------------
    eta_m_v: Optional[float] = None   # mono vertical mosaic (arcmin); None -> eta_m
    eta_a_v: Optional[float] = None   # analyzer vertical mosaic; None -> eta_a
    eta_s_v: Optional[float] = None   # sample vertical mosaic; None -> effective eta_s
    rhm: Optional[float] = None       # mono horizontal curvature radius (m); 0/None -> flat
    rvm: Optional[float] = None       # mono vertical curvature radius (m)
    rha: Optional[float] = None       # analyzer horizontal curvature radius (m)
    rva: Optional[float] = None       # analyzer vertical curvature radius (m)
    arms: Optional[tuple] = None      # (L0, L1, L2, L3[, L1mon]) arm distances (cm)

    # spatial dimensions (cm); None -> documented default recorded in provenance
    source_width: Optional[float] = None
    source_height: Optional[float] = None
    mono_width: Optional[float] = None
    mono_height: Optional[float] = None
    mono_depth: Optional[float] = None
    sample_width: Optional[float] = None
    sample_height: Optional[float] = None
    sample_depth: Optional[float] = None
    sample_shape: str = "rectangular"   # "rectangular" or "cylindrical"
    ana_width: Optional[float] = None
    ana_height: Optional[float] = None
    ana_depth: Optional[float] = None
    det_width: Optional[float] = None
    det_height: Optional[float] = None
    monitor_width: Optional[float] = None
    monitor_height: Optional[float] = None

    # adapter-supplied metadata (echoed through the result verbatim)
    warnings: tuple = ()
    invalidations: tuple = ()
    provenance: dict = field(default_factory=dict)

    # --- helpers -----------------------------------------------------------
    def effective_eta_s(self) -> float:
        """Sample horizontal mosaic (arcmin); reuse eta_m when <=0 / None (ISAR fix)."""
        if self.eta_s is None or self.eta_s <= 0:
            return self.eta_m
        return self.eta_s

    def has_spatial(self) -> bool:
        """True when any Popovici spatial parameter is supplied."""
        if self.arms is not None:
            return True
        for k in _DEFAULT_DIMS:
            if getattr(self, k) is not None:
                return True
        return any(getattr(self, k) is not None for k in ("rhm", "rvm", "rha", "rva"))


@dataclass
class ResolutionResult:
    ok: bool
    reason: Optional[str]
    method: str                     # "cooper_nathans" | "popovici"
    cn_valid: bool
    warnings: tuple
    invalidations: tuple
    r0: Optional[float]             # None for CN (prefactor dropped); Popovici prefactor
    matrix: Optional[list]          # 4x4 FWHM-normalized precision matrix (list-of-lists)
    fwhm: Optional[dict]            # marginal / vanadium FWHMs {dE, dq_par, dq_perp, dq_z}
    bragg: Optional[dict]           # coherent widths {dE, dq_par, dq_perp, dq_z}
    principal_axes: Optional[dict]  # eigen-decomposition of the matrix -> FWHMs + vectors
    vanadium_fwhm_meV: Optional[float]
    projections: Optional[dict]     # 2-D ellipse params for the three coordinate planes
    basis: tuple = ("dQ_par", "dQ_perp", "dQ_z", "dE")
    config: Optional[dict] = None
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serializable dict (all numpy arrays already reduced to lists/floats)."""
        d = asdict(self)
        d["basis"] = list(self.basis)
        return d


# ==============================================================================
# Small numpy helpers
# ==============================================================================
def _block_diag(*mats) -> np.ndarray:
    n = sum(m.shape[0] for m in mats)
    out = np.zeros((n, n), dtype=float)
    i = 0
    for m in mats:
        k = m.shape[0]
        out[i:i + k, i:i + k] = m
        i += k
    return out


def _marginalize(M: np.ndarray, i: int) -> np.ndarray:
    """Integrate out coordinate ``i`` of precision matrix ``M`` (Gaussian marginal)."""
    keep = [j for j in range(M.shape[0]) if j != i]
    return M[np.ix_(keep, keep)] - np.outer(M[keep, i], M[i, keep]) / M[i, i]


def _is_pos_def(M: np.ndarray) -> bool:
    if not np.all(np.isfinite(M)):
        return False
    try:
        np.linalg.cholesky(0.5 * (M + M.T))
        return True
    except np.linalg.LinAlgError:
        return False


# ==============================================================================
# Cooper-Nathans (ISAR port, verbatim math)
# ==============================================================================
def _cn_matrix(cfg: ResolutionConfig) -> Optional[np.ndarray]:
    """4x4 CN resolution matrix (dQ_par, dQ_perp, dQ_z, dE), FWHM-normalized.

    Verbatim port of ISAR ``cn_resolution_matrix``. Returns ``None`` when the
    scattering triangle cannot be closed.
    """
    dm, da = cfg.dm, cfg.da
    etam, etaa = cfg.eta_m * _ARCMIN, cfg.eta_a * _ARCMIN
    etas = cfg.effective_eta_s() * _ARCMIN
    sm, ss, sa = cfg.sm, cfg.ss, cfg.sa
    kfix, fx = cfg.kfix, int(cfg.fx)
    q0, w = cfg.q0, cfg.w
    alf0, alf1, alf2, alf3 = (a * _ARCMIN for a in cfg.alf)
    bet0, bet1, bet2, bet3 = (b * _ARCMIN for b in cfg.bet)

    ki = math.sqrt(kfix ** 2 + (fx - 1) * _F * w)
    kf = math.sqrt(kfix ** 2 - (2 - fx) * _F * w)
    c2t = (ki ** 2 + kf ** 2 - q0 ** 2) / (2 * ki * kf)
    if abs(c2t) > 1:
        return None
    thetam, thetaa = math.asin(math.pi / (dm * ki)), math.asin(math.pi / (da * kf))
    tan, sin = math.tan, math.sin

    N = np.zeros((6, 6))
    pm = 1 / (ki * etam) * np.array([sm * tan(thetam), 1.0])
    palf0 = 1 / (ki * alf0) * np.array([2 * sm * tan(thetam), 1.0])
    palf1 = 1 / (ki * alf1) * np.array([0.0, 1.0])
    pa = 1 / (kf * etaa) * np.array([-sa * tan(thetaa), 1.0])
    palf3 = 1 / (kf * alf3) * np.array([-2 * sa * tan(thetaa), 1.0])
    palf2 = 1 / (kf * alf2) * np.array([0.0, 1.0])
    N[0:2, 0:2] = np.outer(pm, pm) + np.outer(palf0, palf0) + np.outer(palf1, palf1)
    N[3:5, 3:5] = np.outer(pa, pa) + np.outer(palf3, palf3) + np.outer(palf2, palf2)
    N[2, 2] = (1 / bet1 ** 2 + 1 / ((2 * sin(thetam) * etam) ** 2 + bet0 ** 2)) / ki ** 2
    N[5, 5] = (1 / bet2 ** 2 + 1 / ((2 * sin(thetaa) * etaa) ** 2 + bet3 ** 2)) / kf ** 2

    ang1 = math.acos(-(kf ** 2 - q0 ** 2 - ki ** 2) / (2 * q0 * ki))
    ang2 = math.pi - math.acos(-(ki ** 2 - q0 ** 2 - kf ** 2) / (2 * q0 * kf))
    TI = np.array([[math.cos(ang1), -ss * math.sin(ang1)], [ss * math.sin(ang1), math.cos(ang1)]])
    TF = np.array([[math.cos(ang2), -ss * math.sin(ang2)], [ss * math.sin(ang2), math.cos(ang2)]])
    B = np.zeros((6, 6))
    B[0:2, 0:2] = TI
    B[0:2, 3:5] = -TF
    B[2, 2] = 1
    B[2, 5] = -1
    B[3, 0] = 2 * ki / _F
    B[3, 3] = -2 * kf / _F
    B[4, 0] = 1
    B[5, 2] = 1

    V = np.linalg.inv(B)
    Nold = V.T @ N @ V
    Nold = _marginalize(Nold, 5)            # integrate out kiz
    Nold = _marginalize(Nold, 4)            # integrate out kix -> 4x4
    NP = Nold - np.outer(Nold[:, 1], Nold[:, 1]) / (1 / (etas * q0) ** 2 + Nold[1, 1])
    NP[2, 2] = Nold[2, 2]
    return _EIGHT_LN2 * NP


# ==============================================================================
# Popovici (neutronpy / ResLib 3.4c port, Q-coordinate form)
# ==============================================================================
def _popovici_matrix(cfg: ResolutionConfig):
    """Popovici 4x4 matrix (dQ_par, dQ_perp, dQ_z, dE) FWHM-normalized, plus R0
    and a provenance dict. Returns ``(M, r0, prov)`` or ``(None, None, prov)``
    when the triangle cannot close.
    """
    prov: dict = {}
    defaulted = []

    def dim(name):
        v = getattr(cfg, name)
        if v is None:
            defaulted.append(name)
            return _DEFAULT_DIMS[name]
        return v

    # collimations -> sigma (rad); mosaics -> sigma (rad)
    c1 = _ARCMIN / math.sqrt(_EIGHT_LN2)
    alpha = np.array(cfg.alf, dtype=float) * c1
    beta = np.array(cfg.bet, dtype=float) * c1
    etam = cfg.eta_m * c1
    etamv = (cfg.eta_m_v if cfg.eta_m_v is not None else cfg.eta_m) * c1
    etaa = cfg.eta_a * c1
    etaav = (cfg.eta_a_v if cfg.eta_a_v is not None else cfg.eta_a) * c1
    etas = cfg.effective_eta_s() * c1
    etasv = (cfg.eta_s_v if cfg.eta_s_v is not None else cfg.effective_eta_s()) * c1

    sm, ss, sa = cfg.sm, cfg.ss, cfg.sa
    kfix, fx = cfg.kfix, int(cfg.fx)
    q, w = cfg.q0, cfg.w

    ki = math.sqrt(kfix ** 2 + (fx - 1) * _F * w)
    kf = math.sqrt(kfix ** 2 - (2 - fx) * _F * w)
    c2t = (ki ** 2 + kf ** 2 - q ** 2) / (2 * ki * kf)
    if abs(c2t) > 1:
        return None, None, prov

    taum = 2.0 * math.pi / cfg.dm
    taua = 2.0 * math.pi / cfg.da
    thetam = math.asin(taum / (2.0 * ki)) * sm
    thetaa = math.asin(taua / (2.0 * kf)) * sa
    s2theta = math.acos(c2t) * ss
    thetas = s2theta / 2.0
    phi = math.atan2(-kf * math.sin(s2theta), ki - kf * math.cos(s2theta))

    # arms (cm); L1mon defaults to L1
    if cfg.arms is not None:
        arms = list(cfg.arms)
        L0, L1, L2, L3 = arms[:4]
        L1mon = arms[4] if len(arms) > 4 else L1
    else:
        defaulted.append("arms")
        L0, L1, L2, L3, L1mon = _DEFAULT_ARMS

    # curvature radii (m -> cm), flat when 0/None; sign-corrected by sense
    def radius_cm(v):
        if v is None or v == 0:
            return _FLAT_RADIUS_CM
        return v * 100.0
    monorh = radius_cm(cfg.rhm) * sm
    monorv = radius_cm(cfg.rvm) * sm
    anarh = radius_cm(cfg.rha) * sa
    anarv = radius_cm(cfg.rva) * sa

    # spatial covariance blocks (variance = size^2 / 12 [/16 cyl])
    bshape = np.diag([dim("source_width") ** 2 / 12.0, dim("source_height") ** 2 / 12.0])
    mshape = np.diag([dim("mono_depth") ** 2 / 12.0, dim("mono_width") ** 2 / 12.0,
                      dim("mono_height") ** 2 / 12.0])
    sfac = 16.0 if cfg.sample_shape == "cylindrical" else 12.0
    sshape = np.diag([dim("sample_depth") ** 2 / sfac, dim("sample_width") ** 2 / sfac,
                      dim("sample_height") ** 2 / sfac])
    ashape = np.diag([dim("ana_depth") ** 2 / 12.0, dim("ana_width") ** 2 / 12.0,
                      dim("ana_height") ** 2 / 12.0])
    dshape = np.diag([dim("det_width") ** 2 / 12.0, dim("det_height") ** 2 / 12.0])
    monitorshape = np.diag([dim("monitor_width") ** 2 / 12.0, dim("monitor_height") ** 2 / 12.0])

    # rotate sample shape into the Q frame
    psi = thetas - phi
    rot = np.array([[math.cos(psi), math.sin(psi), 0.0],
                    [-math.sin(psi), math.cos(psi), 0.0],
                    [0.0, 0.0, 1.0]])
    sshape = rot @ sshape @ rot.T

    tanm, tana = math.tan(thetam), math.tan(thetaa)
    sinm, sina, sins = math.sin(thetam), math.sin(thetaa), math.sin(thetas)
    coss = math.cos(thetas)
    cosm, cosa = math.cos(thetam), math.cos(thetaa)

    G = np.diag(1.0 / np.array([alpha[0], alpha[1], beta[0], beta[1],
                                alpha[2], alpha[3], beta[2], beta[3]]) ** 2)
    F = np.diag(1.0 / np.array([etam, etamv, etaa, etaav]) ** 2)

    A = np.array([
        [ki / 2.0 / tanm, -ki / 2.0 / tanm, 0, 0, 0, 0, 0, 0],
        [0, ki, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, ki, 0, 0, 0, 0],
        [0, 0, 0, 0, kf / 2.0 / tana, -kf / 2.0 / tana, 0, 0],
        [0, 0, 0, 0, kf, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, kf, 0],
    ], dtype=float)

    C = np.array([
        [0.5, 0.5, 0, 0, 0, 0, 0, 0],
        [0, 0, 1.0 / (2 * sinm), -1.0 / (2 * sinm), 0, 0, 0, 0],
        [0, 0, 0, 0, 0.5, 0.5, 0, 0],
        [0, 0, 0, 0, 0, 0, 1.0 / (2 * sina), -1.0 / (2 * sina)],
    ], dtype=float)

    Bm = np.array([
        [math.cos(phi), math.sin(phi), 0, -math.cos(phi - s2theta), -math.sin(phi - s2theta), 0],
        [-math.sin(phi), math.cos(phi), 0, math.sin(phi - s2theta), -math.cos(phi - s2theta), 0],
        [0, 0, 1, 0, 0, -1],
        [2 * _EMEV_PER_K2 * ki, 0, 0, -2 * _EMEV_PER_K2 * kf, 0, 0],
    ], dtype=float)

    Sinv = _block_diag(bshape, mshape, sshape, ashape, dshape)  # 13x13 variances
    S = np.linalg.inv(Sinv)

    T = np.array([
        [-1.0 / (2 * L0), 0, cosm * (1.0 / L1 - 1.0 / L0) / 2.0,
         sinm * (1.0 / L0 + 1.0 / L1 - 2.0 / (monorh * sinm)) / 2.0, 0,
         sins / (2 * L1), coss / (2 * L1), 0, 0, 0, 0, 0, 0],
        [0, -1.0 / (2 * L0 * sinm), 0, 0,
         (1.0 / L0 + 1.0 / L1 - 2.0 * sinm / monorv) / (2 * sinm), 0, 0,
         -1.0 / (2 * L1 * sinm), 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, sins / (2 * L2), -coss / (2 * L2), 0,
         cosa * (1.0 / L3 - 1.0 / L2) / 2.0,
         sina * (1.0 / L2 + 1.0 / L3 - 2.0 / (anarh * sina)) / 2.0, 0, 1.0 / (2 * L3), 0],
        [0, 0, 0, 0, 0, 0, 0, -1.0 / (2 * L2 * sina), 0, 0,
         (1.0 / L2 + 1.0 / L3 - 2.0 * sina / anarv) / (2 * sina), 0, -1.0 / (2 * L3 * sina)],
    ], dtype=float)

    D = np.array([
        [-1.0 / L0, 0, -cosm / L0, sinm / L0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, cosm / L1, sinm / L1, 0, sins / L1, coss / L1, 0, 0, 0, 0, 0, 0],
        [0, -1.0 / L0, 0, 0, 1.0 / L0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, -1.0 / L1, 0, 0, 1.0 / L1, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, sins / L2, -coss / L2, 0, -cosa / L2, sina / L2, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, cosa / L3, sina / L3, 0, 1.0 / L3, 0],
        [0, 0, 0, 0, 0, 0, 0, -1.0 / L2, 0, 0, 1.0 / L2, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -1.0 / L3, 0, 1.0 / L3],
    ], dtype=float)

    K = S + T.T @ F @ T
    H = np.linalg.inv(D @ np.linalg.inv(K) @ D.T)
    Ninv = A @ np.linalg.inv(H + G) @ A.T
    Minv = Bm @ Ninv @ Bm.T
    M = np.linalg.inv(Minv)

    # R0 prefactor (ResLib normalization; monitor-normalized, moncor=1)
    Rm = ki ** 3 / tanm
    Ra = kf ** 3 / tana
    r0 = Rm * Ra * (2 * math.pi) ** 4 / (64.0 * math.pi ** 2 * sinm * sina)
    r0 = r0 * math.sqrt(abs(np.linalg.det(F) / np.linalg.det(H + G)))

    # monitor normalization
    g = G[:4, :4]
    f = F[:2, :2]
    c = C[:2, :4]
    t = np.array([
        [-1.0 / (2 * L0), 0, cosm * (1.0 / L1mon - 1.0 / L0) / 2.0,
         sinm * (1.0 / L0 + 1.0 / L1mon - 2.0 / (monorh * sinm)) / 2.0, 0, 0, 1.0 / (2 * L1mon)],
        [0, -1.0 / (2 * L0 * sinm), 0, 0,
         (1.0 / L0 + 1.0 / L1mon - 2.0 * sinm / monorv) / (2 * sinm), 0, 0],
    ], dtype=float)
    sinv = _block_diag(bshape, mshape, monitorshape)
    s = np.linalg.inv(sinv)
    d = np.array([
        [-1.0 / L0, 0, -cosm / L0, sinm / L0, 0, 0, 0],
        [0, 0, cosm / L1mon, sinm / L1mon, 0, 0, 1.0 / L1mon],
        [0, -1.0 / L0, 0, 0, 1.0 / L0, 0, 0],
        [0, 0, 0, 0, -1.0 / L1mon, 0, 0],
    ], dtype=float)
    Rmon = Rm * (2 * math.pi) ** 2 / (8 * math.pi * sinm) * math.sqrt(abs(
        np.linalg.det(f) / np.linalg.det(np.linalg.inv(d @ np.linalg.inv(s + t.T @ f @ t) @ d.T) + g)))
    r0 = r0 / Rmon
    r0 = r0 * ki                                # 1/ki monitor efficiency
    r0 = r0 / (2 * math.pi) ** 2 * math.sqrt(abs(np.linalg.det(M)))   # Chesser-Axe
    r0 = r0 * kf / ki                            # kf/ki cross-section factor

    # sample mosaic (Werner-Pynn): broaden Q_perp (horiz) and Q_z (vert)
    if etas > 0:
        Minv = np.linalg.inv(M)
        r0 = r0 / math.sqrt((1 + (q * etas) ** 2 * M[2, 2]) * (1 + (q * etasv) ** 2 * M[1, 1]))
        Minv[1, 1] = Minv[1, 1] + q ** 2 * etas ** 2
        Minv[2, 2] = Minv[2, 2] + q ** 2 * etasv ** 2
        M = np.linalg.inv(Minv)

    if defaulted:
        prov["popovici_defaults_applied"] = defaulted
    prov["arms_cm"] = [L0, L1, L2, L3, L1mon]
    prov["curvature_cm"] = {"monorh": monorh, "monorv": monorv, "anarh": anarh, "anarv": anarv}
    return M, float(abs(r0)), prov


# ==============================================================================
# Result assembly + geometry helpers
# ==============================================================================
_AXES = ("dq_par", "dq_perp", "dq_z", "dE")
_PLANES = {
    "q_par_q_perp": (0, 1),
    "q_par_E": (0, 3),
    "q_perp_E": (1, 3),
}


def _ellipse2d(cov2: np.ndarray) -> dict:
    """2-D projection ellipse from a 2x2 covariance sub-block."""
    evals, evecs = np.linalg.eigh(0.5 * (cov2 + cov2.T))
    evals = np.clip(evals, 0.0, None)
    tilt = math.atan2(evecs[1, 0], evecs[0, 0])
    return {
        "tilt_rad": float(tilt),
        "fwhm_principal": [float(_S2F * math.sqrt(v)) for v in evals],
        "fwhm_axis0": float(_S2F * math.sqrt(max(cov2[0, 0], 0.0))),
        "fwhm_axis1": float(_S2F * math.sqrt(max(cov2[1, 1], 0.0))),
        "covariance": cov2.tolist(),
    }


def _result_from_matrix(cfg, M, method, r0, extra_warnings=(), extra_prov=None):
    cov = np.linalg.inv(M)
    fwhm = {}
    bragg = {}
    for idx, ax in enumerate(_AXES):
        fwhm[ax] = float(_S2F * math.sqrt(cov[idx, idx]))
        bragg[ax] = float(math.sqrt(_EIGHT_LN2 / M[idx, idx]))

    evals, evecs = np.linalg.eigh(0.5 * (M + M.T))
    principal = {
        "eigenvalues": [float(v) for v in evals],
        "fwhm": [float(math.sqrt(_EIGHT_LN2 / v)) for v in evals],
        "eigenvectors": evecs.T.tolist(),   # row i is the i-th eigenvector
    }

    projections = {}
    for name, (i, j) in _PLANES.items():
        sub = cov[np.ix_([i, j], [i, j])]
        projections[name] = _ellipse2d(sub)

    prov = dict(cfg.provenance)
    prov["energy_const_meV_per_k2"] = _EMEV_PER_K2
    prov["matrix_convention"] = "FWHM-normalized precision; R~exp(-1/2 x^T M x)"
    if extra_prov:
        prov.update(extra_prov)

    return ResolutionResult(
        ok=True,
        reason=None,
        method=method,
        cn_valid=(len(cfg.invalidations) == 0),
        warnings=tuple(cfg.warnings) + tuple(extra_warnings),
        invalidations=tuple(cfg.invalidations),
        r0=r0,
        matrix=M.tolist(),
        fwhm=fwhm,
        bragg=bragg,
        principal_axes=principal,
        vanadium_fwhm_meV=fwhm["dE"],
        projections=projections,
        config=_config_echo(cfg),
        provenance=prov,
    )


def _refusal(cfg, method, reason):
    return ResolutionResult(
        ok=False, reason=reason, method=method,
        cn_valid=(len(cfg.invalidations) == 0),
        warnings=tuple(cfg.warnings), invalidations=tuple(cfg.invalidations),
        r0=None, matrix=None, fwhm=None, bragg=None, principal_axes=None,
        vanadium_fwhm_meV=None, projections=None,
        config=_config_echo(cfg), provenance=dict(cfg.provenance),
    )


def _config_echo(cfg) -> dict:
    d = asdict(cfg)
    # tuples -> lists for JSON friendliness
    for k, v in list(d.items()):
        if isinstance(v, tuple):
            d[k] = list(v)
    return d


# ==============================================================================
# Public API
# ==============================================================================
def cooper_nathans(cfg: ResolutionConfig) -> ResolutionResult:
    """Cooper-Nathans resolution (ISAR port). Refusals are results, not exceptions."""
    try:
        M = _cn_matrix(cfg)
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return _refusal(cfg, "cooper_nathans", "resolution undefined at this geometry")
    if M is None:
        return _refusal(cfg, "cooper_nathans",
                        "scattering triangle cannot close for this (Q, E) and fixed-k setup")
    if not _is_pos_def(M):
        return _refusal(cfg, "cooper_nathans", "resolution undefined at this geometry")
    return _result_from_matrix(cfg, M, "cooper_nathans", None)


def popovici(cfg: ResolutionConfig) -> ResolutionResult:
    """Popovici resolution (ResLib/neutronpy port). Same result shape and matrix
    convention as :func:`cooper_nathans`."""
    try:
        M, r0, prov = _popovici_matrix(cfg)
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return _refusal(cfg, "popovici", "resolution undefined at this geometry")
    if M is None:
        return _refusal(cfg, "popovici",
                        "scattering triangle cannot close for this (Q, E) and fixed-k setup")
    if not _is_pos_def(M):
        return _refusal(cfg, "popovici", "resolution undefined at this geometry")
    warnings = ()
    if prov.get("popovici_defaults_applied"):
        warnings = ("Popovici dims defaulted: " + ", ".join(prov["popovici_defaults_applied"]),)
    return _result_from_matrix(cfg, M, "popovici", r0, extra_warnings=warnings, extra_prov=prov)


def resolution(cfg: ResolutionConfig, method: str = "auto") -> ResolutionResult:
    """Dispatch to Popovici or Cooper-Nathans.

    ``method="auto"`` -> Popovici when spatial params are present, else CN.
    ``"cooper_nathans"`` / ``"popovici"`` force the respective method.
    """
    if method == "auto":
        method = "popovici" if cfg.has_spatial() else "cooper_nathans"
    if method == "popovici":
        return popovici(cfg)
    if method == "cooper_nathans":
        return cooper_nathans(cfg)
    raise ValueError(f"unknown resolution method: {method!r}")


def projected_fwhm(matrix, direction4) -> float:
    """Marginal FWHM along an arbitrary 4-direction of a FWHM-normalized matrix.

    ``matrix`` is a 4x4 FWHM-normalized precision matrix (list-of-lists or array);
    ``direction4`` a 4-vector (need not be normalized). Returns the projected
    marginal FWHM: ``2*sqrt(2 ln2) * sqrt(u^T inv(M) u)`` with ``u`` the unit
    direction.
    """
    M = np.asarray(matrix, dtype=float)
    u = np.asarray(direction4, dtype=float)
    n = np.linalg.norm(u)
    if n == 0:
        raise ValueError("direction4 must be non-zero")
    u = u / n
    var = float(u @ np.linalg.inv(M) @ u)
    return _S2F * math.sqrt(var)


def elastic_energy_fwhm(cfg: ResolutionConfig, fallback: float = FALLBACK_FWHM) -> float:
    """Marginal ("vanadium") energy FWHM at the elastic line (Cooper-Nathans).

    Mirrors ISAR ``cn_energy_fwhm``: evaluates CN at ``w = 0`` and returns the
    vanadium energy FWHM (meV); ``fallback`` when the triangle cannot close.
    """
    res = cooper_nathans(replace(cfg, w=0.0))
    if not res.ok:
        return fallback
    return res.vanadium_fwhm_meV
