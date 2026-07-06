"""Deterministic execution backend: analytic S(Q,omega) convolved with the
Cooper-Nathans / Popovici resolution ellipsoid, plus seeded Poisson counting.

This is the fast tier of the fidelity ladder (``docs/CLOSED_LOOP_DESIGN.md`` §6a,
``docs/CONTROL_FEATURES_DESIGN.md`` §6). It evaluates the *same* ground-truth sample
model that parameterizes the McStas sample component and reports counts through the
identical result pipeline as full Monte Carlo -- milliseconds per point instead of
seconds-to-minutes. It interprets no measured data (§6.6): it is a simulation
backend, not an analyst.

numpy + stdlib only -- no Qt, no mcstasscript, no scipy. It consumes a
:class:`tavi.resolution.ResolutionResult` (the 4x4 FWHM-normalized matrix in the
``(dQ_par, dQ_perp, dQ_z, dE)`` basis) as the convolution kernel.


S(Q,omega) ground-truth model
------------------------------
The analytic model mirrors the McStas ``Phonon_DFT`` component
(``components/Phonon_DFT.comp``) and its toy dispersion file
(``components/Al_test_phonons_centered.dat``) as closely as is practical for a
1-point-per-ms evaluator. Conventions chosen (and where they diverge from McStas):

* **q-parameterization.** Each (h,k,l) component is folded into the dispersion
  grid's span exactly as ``pdft_fold_into_grid`` does: ``q_i = ((x_i + half) mod
  period) - half``. The period is a property of the sample's dispersion FILE, not
  of ``Phonon_DFT`` itself (``grid_period`` in ``SampleSpec.properties``; default
  2, the span of ``Al_test_phonons_centered.dat``). With period 2, zone centers
  sit at **even** integers (the toy model is "centered on Gamma"), *not* at every
  integer. At the validated anchor Q=(2.15,0,0) this gives reduced q=0.15 (2 is
  even), matching the McStas ground truth and the CLOSED_LOOP §7 live measurement
  (E=6*sin(pi*0.15/2)=1.4004
  meV). A naive nearest-integer reduction would coincide near even integers and
  differ near odd ones; we mirror McStas.

* **Dispersion.** ``s = sqrt(sum_i sin^2(pi*q_i/2))`` (isotropic, per-axis sines),
  acoustic ``E = 6*s`` meV, optic ``E = 6 + 2*s`` meV -- the analytic form written
  in the ``Al_test_phonons_centered.dat`` header. The amplitudes (6; 6+2) are
  properties of that dispersion file, not of ``SampleSpec.properties``; everything
  else (temperature T for the Bose factor, ``phonon_gamma`` for the Lorentzian
  width, lattice ``a`` for the rlu->Angstrom^-1 metric) is read from
  ``spec.properties`` and never duplicated.

* **Bose factor.** Mirrors ``pdft_nbose``: each phonon mode appears at **+omega0**
  (Stokes, neutron loses energy) with weight ``n+1`` and at **-omega0**
  (anti-Stokes) with weight ``n``, where ``n = 1/(exp(omega0/kT) - 1)`` and
  ``kT = T / 11.605`` meV (the component's ``PDFT_T2E``). The anti-Stokes/Stokes
  ratio is therefore ``exp(-omega0/kT)`` exactly.

* **Gradient frame.** ``branches()`` returns ``grad_omega`` = d(omega)/dQ as a
  3-vector in the ``(Q_par, Q_perp, Q_z)`` instrument frame. It is computed by
  central-differencing the folded dispersion in rlu and scaling each component by
  ``a/(2*pi)`` (rlu -> Angstrom^-1 for a cubic lattice). The rlu axes (H,K,L) are
  identified with (Q_par, Q_perp, Q_z) respectively -- **exact when Q lies along a
  cubic principal axis** (the validated (H,0,0) anchor geometry), approximate for a
  general Q. This is the one deliberate divergence from a fully general
  crystal-frame gradient, which would require the sample orientation (UB matrix)
  that the engine is not given.

* **Idealization / fidelity gap (§6.5).** Fine intensity structure that the McStas
  kernel carries -- the ``1/omega`` one-phonon factor, the ``|Q.e|^2`` structure
  factor, Debye-Waller, the incoherent elastic line -- is **not** modeled; the
  per-mode weight is the flat grid intensity (1.0). The deterministic result is an
  honestly-idealized model, labelled ``engine="deterministic"`` in provenance.


Convolution
-----------
For one branch with surface ``eps(dq) = omega0 + grad . dq`` and Lorentzian HWHM
``gamma``, the measured intensity while scanning energy ``w`` at fixed Q0 is

    I(w) = weight * Voigt(w - omega0 ; sigma_t, gamma)

where ``sigma_t^2 = u^T Sigma u`` with ``u = (-grad, 1)`` and ``Sigma = inv(M)``
the resolution covariance in ``(dQ_par,dQ_perp,dQ_z,dE)``. Sigma_t is the energy
width of the dispersion ridge as seen through the ellipsoid: it reduces to the
vanadium energy width when ``grad = 0`` and grows as ``sqrt(sigma_E^2 +
grad^T Sigma_qq grad - 2 grad . Sigma_qE)`` when the branch disperses across the
Q-width of the resolution. The Voigt (Gaussian sigma_t convolved with Lorentzian
gamma) is evaluated by Gauss-Hermite quadrature (32 nodes, numpy only).

An elastic feature (Bragg) at reciprocal-lattice point ``tau`` contributes
``weight * exp(-1/2 x0^T M x0)`` with ``x0`` the 4-offset of ``(tau, 0)`` from the
ellipsoid center ``(Q0, w)`` -- the resolution volume sampled at the peak.


Brightness calibration
-----------------------
``mean = number_neutrons * brightness * (S (x) R)``. ``brightness`` is a single
**CALIBRATED (not derived)** constant per sample id, anchored so that the phonon
Stokes peak reproduces the McStas reference of ~61 counts at Q=(2.15,0,0),
omega=1.5 meV, 1e8 neutrons/point (CLOSED_LOOP §7), evaluated with a representative
PUMA resolution matrix. See ``BRIGHTNESS`` and ``anchor_convolved_intensity`` below;
the calibration is verified (roughly) in ``tests/test_deterministic_engine.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

# --- physical constants (mirrored from Phonon_DFT.comp) -----------------------
_KB_MEV_PER_K = 1.0 / 11.605       # kT (meV) = T(K) * this  (component PDFT_T2E)
_TWO_PI = 2.0 * math.pi
_EIGHT_LN2 = 8.0 * math.log(2.0)
_S2F = 2.0 * math.sqrt(2.0 * math.log(2.0))   # sigma -> FWHM

# --- dispersion amplitudes (from Al_test_phonons_centered.dat header) ---------
# NOT sample properties: these define the toy dispersion file itself.
_ACOUSTIC_AMP = 6.0     # meV;  E_acoustic = 6 * s
_OPTIC_GAP = 6.0        # meV;  E_optic = 6 + 2 * s
_OPTIC_AMP = 2.0        # meV

# Voigt lineshape: the Thompson-Cox-Hastings pseudo-Voigt (a Gaussian/Lorentzian
# blend matched in FWHM) is used rather than Gauss-Hermite quadrature. GH quadrature
# on the Gaussian aliases into a spurious *bimodal* profile whenever the Lorentzian
# HWHM is much narrower than the Gaussian sigma (the typical phonon regime here,
# gamma~0.1 meV vs sigma_t~0.45 meV) -- the narrow Lorentzian falls between nodes.
# The pseudo-Voigt is unimodal, area-normalized, and accurate to ~1%.

# --- MC validator ------------------------------------------------------------
_MC_SAMPLES = 256

# --- brightness calibration (CALIBRATED, not derived) -------------------------
# Anchor: ~61 Stokes counts at Q=(2.15,0,0), omega=1.5 meV, 1e8 neutrons/point,
# with the representative PUMA PG002 kf-fixed resolution used in the test suite.
# See anchor_convolved_intensity() and the calibration test.
BRIGHTNESS = {
    "Al_phonon_DFT": 6.41e-8,   # CALIBRATED: ~61 counts at the McStas anchor
    "Al_bragg": 1.0e-5,          # not anchored (no McStas Bragg reference yet)
    "none": 0.0,
}
_DEFAULT_BRIGHTNESS = 1.0e-4

MCSTAS_ANCHOR = {
    "sample_id": "Al_phonon_DFT",
    "hkl": (2.15, 0.0, 0.0),
    "w": 1.5,
    "number_neutrons": 1.0e8,
    "counts": 61.0,
}


# ==============================================================================
# Ground-truth S(Q,omega) models
# ==============================================================================
@dataclass(frozen=True)
class Branch:
    """One dispersing spectral feature, linearized at Q0.

    ``omega0``     energy of the ridge at Q0 (meV; signed -- negative = anti-Stokes)
    ``weight``     intensity weight (already includes the Bose factor)
    ``grad``       d(omega)/dQ, 3-vector in (Q_par, Q_perp, Q_z) (meV * Angstrom)
    ``gamma``      Lorentzian HWHM (meV); 0 -> pure Gaussian (delta * resolution)
    """
    omega0: float
    weight: float
    grad: tuple
    gamma: float


@dataclass(frozen=True)
class Elastic:
    """A resolution-limited elastic feature at a reciprocal-lattice point.

    ``weight``   intensity weight
    ``dq``       (tau - Q0) offset in (Q_par, Q_perp, Q_z) (Angstrom^-1); the
                 feature sits at energy 0.
    """
    weight: float
    dq: tuple


class AnalyticSQW:
    """Base ground-truth model. Subclasses implement ``branches``/``elastic``."""

    sample_id: str = ""

    def branches(self, hkl) -> list:
        """Dispersing (phonon) features at ``hkl`` -- a list of :class:`Branch`."""
        return []

    def elastic(self, hkl) -> list:
        """Elastic features at ``hkl`` -- a list of :class:`Elastic`."""
        return []


class ZeroSQW(AnalyticSQW):
    """'No sample' -- scatters nothing."""

    def __init__(self, sample_id: str = "none"):
        self.sample_id = sample_id


class PhononSQW(AnalyticSQW):
    """Acoustic + optic phonon branches mirroring McStas ``Phonon_DFT``.

    Parameterized from ``SampleSpec.properties``: ``a`` (lattice, rlu metric),
    ``T`` (Bose), ``phonon_gamma`` (Lorentzian FWHM, meV).
    """

    def __init__(self, a: float, temperature: float, phonon_gamma_fwhm: float,
                 sample_id: str = "Al_phonon_DFT", grid_period: float = 2.0):
        self.a = float(a)
        self.temperature = float(temperature)
        self.gamma_hwhm = 0.5 * float(phonon_gamma_fwhm)   # FWHM -> HWHM
        self.sample_id = sample_id
        # Folding period of the dispersion grid in rlu. A property of the sample's
        # dispersion file (Al_test_phonons_centered.dat spans [-1,1) -> period 2,
        # zone centers at even integers), NOT of Phonon_DFT itself -- another
        # material's grid may have a different periodicity.
        self.grid_period = float(grid_period)
        self._rlu_to_inv_ang = _TWO_PI / self.a            # |dQ|/d(rlu), cubic

    # -- dispersion -------------------------------------------------------
    def _fold(self, x: float) -> float:
        """Fold an rlu coordinate into the grid span, as pdft_fold_into_grid."""
        half = 0.5 * self.grid_period
        return ((x + half) % self.grid_period) - half

    def _s(self, hkl) -> float:
        half = 0.5 * self.grid_period
        return math.sqrt(sum(math.sin(math.pi * self._fold(c) / (2.0 * half)) ** 2
                             for c in hkl))

    def _omega_branch(self, hkl, branch: int) -> float:
        s = self._s(hkl)
        if branch == 0:
            return _ACOUSTIC_AMP * s
        return _OPTIC_GAP + _OPTIC_AMP * s

    def _grad_inv_ang(self, hkl, branch: int) -> np.ndarray:
        """d(omega)/dQ in (Q_par,Q_perp,Q_z) (meV*Angstrom), via central rlu diff.

        H,K,L rlu axes are identified with (Q_par,Q_perp,Q_z): exact for Q along a
        cubic principal axis (the anchor), approximate otherwise.
        """
        h = 1e-4
        g_rlu = np.empty(3)
        base = list(hkl)
        for i in range(3):
            up = list(base); up[i] += h
            dn = list(base); dn[i] -= h
            g_rlu[i] = (self._omega_branch(up, branch)
                        - self._omega_branch(dn, branch)) / (2 * h)
        # rlu gradient -> Angstrom^-1 gradient: d/dQ = (1 / (2pi/a)) d/d(rlu)
        return g_rlu / self._rlu_to_inv_ang

    def _bose_n(self, omega0: float) -> float:
        """n(omega0) = 1/(exp(omega0/kT) - 1) for omega0 > 0."""
        kt = self.temperature * _KB_MEV_PER_K
        if kt <= 0 or omega0 <= 0:
            return 0.0
        arg = omega0 / kt
        if arg > 700:
            return 0.0
        return 1.0 / (math.expm1(arg))

    def branches(self, hkl) -> list:
        out = []
        for b in (0, 1):
            omega0 = self._omega_branch(hkl, b)
            if omega0 <= 0:
                continue
            g = self._grad_inv_ang(hkl, b)
            n = self._bose_n(omega0)
            # Stokes: +omega0, weight n+1, surface slope +g
            out.append(Branch(omega0, n + 1.0, tuple(g), self.gamma_hwhm))
            # anti-Stokes: -omega0, weight n, surface slope -g
            out.append(Branch(-omega0, n, tuple(-g), self.gamma_hwhm))
        return out


class BraggSQW(AnalyticSQW):
    """Elastic Bragg deltas at integer HKL (mirrors ``Al_bragg`` / Single_crystal).

    A resolution-limited delta at every integer reciprocal-lattice point; the toy
    structure factor is flat (weight 1). Mosaic broadening is intentionally omitted
    (delta at Q with an elastic energy line -- see the design note).
    """

    def __init__(self, a: float, sample_id: str = "Al_bragg"):
        self.a = float(a)
        self.sample_id = sample_id
        self._rlu_to_inv_ang = _TWO_PI / self.a

    def elastic(self, hkl) -> list:
        # nearest integer reciprocal-lattice point
        tau = [round(c) for c in hkl]
        dq_rlu = np.array([tau[i] - hkl[i] for i in range(3)])
        dq = dq_rlu * self._rlu_to_inv_ang   # H->par, K->perp, L->z
        return [Elastic(1.0, tuple(dq))]


def ground_truth(sample_spec) -> Optional[AnalyticSQW]:
    """Factory: ``SampleSpec`` -> analytic ground truth, or ``None`` if unknown.

    Keyed by ``sample_spec.id``. ``None`` signals the caller to refuse ("no analytic
    ground truth for sample 'X'"). Parameters come from ``spec.properties``.
    """
    sid = getattr(sample_spec, "id", None)
    props = getattr(sample_spec, "properties", None) or {}
    if sid in ("none", "None", None):
        return ZeroSQW("none")
    if sid == "Al_phonon_DFT":
        return PhononSQW(
            a=props.get("a", 4.03893),
            temperature=props.get("T", 200.0),
            phonon_gamma_fwhm=props.get("phonon_gamma", 0.0),
            sample_id=sid,
            grid_period=props.get("grid_period", 2.0),
        )
    if sid == "Al_bragg":
        # lattice a from the spec's lattice tuple (Single_crystal has no 'a' prop)
        lattice = getattr(sample_spec, "lattice", None)
        a = lattice[0] if lattice else props.get("a", 4.05)
        return BraggSQW(a=a, sample_id=sid)
    return None


# ==============================================================================
# Convolution
# ==============================================================================
def _covariance(res_result) -> np.ndarray:
    """Resolution covariance Sigma = inv(M) in (dQ_par,dQ_perp,dQ_z,dE)."""
    M = np.asarray(res_result.matrix, dtype=float)
    return np.linalg.inv(M)


def _gaussian(delta: float, sigma: float) -> float:
    return math.exp(-0.5 * (delta / sigma) ** 2) / (sigma * math.sqrt(_TWO_PI))


def _lorentzian(delta: float, gamma: float) -> float:
    return (gamma / math.pi) / (gamma * gamma + delta * delta)


def _voigt(delta: float, sigma: float, gamma: float) -> float:
    """Pseudo-Voigt (Thompson-Cox-Hastings): Gaussian(sigma) (x) Lorentzian(HWHM
    gamma), evaluated at ``delta``. Area-normalized, unimodal.
    """
    if sigma <= 0 and gamma <= 0:
        return 0.0
    if gamma <= 0:
        return _gaussian(delta, sigma)
    if sigma <= 0:
        return _lorentzian(delta, gamma)
    fG = _S2F * sigma            # Gaussian FWHM
    fL = 2.0 * gamma             # Lorentzian FWHM
    f = (fG ** 5 + 2.69269 * fG ** 4 * fL + 2.42843 * fG ** 3 * fL ** 2
         + 4.47163 * fG ** 2 * fL ** 3 + 0.07842 * fG * fL ** 4 + fL ** 5) ** 0.2
    r = fL / f
    eta = 1.36603 * r - 0.47719 * r ** 2 + 0.11116 * r ** 3
    hwhm = f / 2.0
    sig = f / _S2F
    return eta * _lorentzian(delta, hwhm) + (1.0 - eta) * _gaussian(delta, sig)


def _convolved_intensity(res_result, sqw, hkl, w) -> float:
    """S (x) R at (hkl, w) -- dimensionless, before brightness/number_neutrons."""
    M = np.asarray(res_result.matrix, dtype=float)
    Sigma = np.linalg.inv(M)
    total = 0.0
    for br in sqw.branches(hkl):
        g = np.asarray(br.grad, dtype=float)
        u = np.array([-g[0], -g[1], -g[2], 1.0])
        var_t = float(u @ Sigma @ u)
        sigma_t = math.sqrt(var_t) if var_t > 0 else 0.0
        total += br.weight * _voigt(w - br.omega0, sigma_t, br.gamma)
    for el in sqw.elastic(hkl):
        x0 = np.array([el.dq[0], el.dq[1], el.dq[2], -w])
        total += el.weight * math.exp(-0.5 * float(x0 @ M @ x0))
    return total


def _convolved_intensity_mc(res_result, sqw, hkl, w, rng=None,
                            n_samples: int = _MC_SAMPLES) -> float:
    """Tiny-MC validator: average S(Q0+dq, w+dE) over samples of the 4D ellipsoid.

    Uses the same linearized dispersion as the analytic path, so agreement
    validates the Voigt quadrature + the u^T Sigma u projection.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    Sigma = _covariance(res_result)
    L = np.linalg.cholesky(0.5 * (Sigma + Sigma.T))
    x = (L @ rng.standard_normal((4, n_samples))).T   # (n, 4) samples ~ N(0, Sigma)
    brs = sqw.branches(hkl)
    els = sqw.elastic(hkl)
    acc = 0.0
    for row in x:
        dq = row[:3]
        de = row[3]
        s = 0.0
        for br in brs:
            g = np.asarray(br.grad, dtype=float)
            eps = br.omega0 + float(g @ dq)          # ridge energy at Q0+dq
            a = (w + de) - eps
            if br.gamma > 0:
                s += br.weight * (br.gamma / math.pi) / (br.gamma ** 2 + a * a)
            else:
                # delta ridge: contributes only in the analytic Gaussian limit;
                # approximate with a narrow Lorentzian for the MC cross-check
                gnar = 1e-3
                s += br.weight * (gnar / math.pi) / (gnar ** 2 + a * a)
        acc += s
    mc = acc / n_samples
    # elastic features are exact in closed form; add them identically
    M = np.asarray(res_result.matrix, dtype=float)
    for el in els:
        x0 = np.array([el.dq[0], el.dq[1], el.dq[2], -w])
        mc += el.weight * math.exp(-0.5 * float(x0 @ M @ x0))
    return mc


def evaluate_point(res_result, sqw, hkl, w, number_neutrons, brightness,
                   rng=None, noiseless=False, method="analytic") -> dict:
    """Mean (and optionally Poisson counts) at a single (hkl, w) point.

    ``method="analytic"`` (default) uses the Voigt/projection closed form;
    ``method="mc"`` uses the 4D-ellipsoid Monte-Carlo validator.

    Returns ``{"mean": float, "counts": int|float}``. ``counts`` == ``mean`` when
    ``noiseless`` or no ``rng`` is given; otherwise ``rng.poisson(mean)``.
    """
    if not getattr(res_result, "ok", False) or res_result.matrix is None:
        return {"mean": 0.0, "counts": 0.0}
    if method == "mc":
        conv = _convolved_intensity_mc(res_result, sqw, hkl, w, rng=rng)
    else:
        conv = _convolved_intensity(res_result, sqw, hkl, w)
    mean = number_neutrons * brightness * conv
    if not math.isfinite(mean) or mean < 0.0:
        mean = 0.0
    if noiseless or rng is None:
        counts = mean
    else:
        counts = int(rng.poisson(mean))
    return {"mean": mean, "counts": counts}


def anchor_convolved_intensity(res_result, sqw=None) -> float:
    """S (x) R at the McStas brightness anchor -- the calibration quantity.

    Used to derive/verify ``BRIGHTNESS[sample_id]``:
    ``brightness = anchor.counts / (anchor.number_neutrons * this)``.
    """
    if sqw is None:
        from instruments.descriptor import SampleSpec  # local: keep import-light
        spec = SampleSpec(
            "Al_phonon_DFT", "Al: Phonon DFT", "Phonon_DFT",
            properties={"a": 4.03893, "T": 200.0, "phonon_gamma": 0.2},
            lattice=(4.03893,) * 3 + (90.0, 90.0, 90.0),
        )
        sqw = ground_truth(spec)
    return _convolved_intensity(res_result, sqw,
                                MCSTAS_ANCHOR["hkl"], MCSTAS_ANCHOR["w"])


# ==============================================================================
# Scan convenience + provenance
# ==============================================================================
def _brightness_for(sqw) -> float:
    return BRIGHTNESS.get(getattr(sqw, "sample_id", ""), _DEFAULT_BRIGHTNESS)


def run_deterministic_scan(points: Sequence, res_results, sqw, number_neutrons,
                           seed, noiseless=False, method="analytic") -> list:
    """Run a deterministic scan over ``points`` (each an ``(hkl, w)`` pair).

    ``res_results`` is one :class:`~tavi.resolution.ResolutionResult` (broadcast) or
    a per-point sequence. Per-point RNG is ``default_rng((seed, point_index))`` so a
    skipped point never shifts a later point's stream. Returns the counts list
    (Poisson means, or exact means when ``noiseless``).
    """
    brightness = _brightness_for(sqw)
    counts = []
    for i, (hkl, w) in enumerate(points):
        rr = res_results[i] if isinstance(res_results, (list, tuple)) else res_results
        rng = None if noiseless else np.random.default_rng((int(seed), i))
        out = evaluate_point(rr, sqw, hkl, w, number_neutrons, brightness,
                             rng=rng, noiseless=noiseless, method=method)
        counts.append(out["counts"])
    return counts


def engine_metadata(seed, res_result, method="analytic") -> dict:
    """Result provenance for ``job.result.metadata`` (milestone 7 consumes this).

    ``res_result=None`` means the resolution was never evaluated (e.g. every scan
    point was infeasible); that is reported as ``cn_valid: None`` -- "not
    evaluated" -- rather than a false ``cn_valid: False`` claim about a config
    that may be perfectly CN-valid.
    """
    if res_result is None:
        return {
            "engine": "deterministic",
            "seed": int(seed),
            "method": method,
            "cn_valid": None,
            "invalidations": [],
            "resolution_method": None,
            "resolution_ok": False,
        }
    return {
        "engine": "deterministic",
        "seed": int(seed),
        "method": method,
        "cn_valid": bool(getattr(res_result, "cn_valid", False)),
        "invalidations": list(getattr(res_result, "invalidations", ()) or ()),
        "resolution_method": getattr(res_result, "method", None),
        "resolution_ok": bool(getattr(res_result, "ok", False)),
    }
