"""Scan-derived motion and quick-fit core for the GUI fitting dock.

Qt-free, controller-free helper module (same ownership rule as
``tavi/scan_jobs.py``): it reduces a 1D scan's ``(x, counts)`` arrays to a
number plus a verdict.  It never moves anything and never raises on bad data --
every failure path returns a result object carrying a human-readable reason.

Design origin: ``docs/CONTROL_FEATURES_DESIGN.md`` §1 ("goto CEN"), which
sketched this module.  Three decisions supersede that sketch:

* **scipy is allowed.**  The design doc avoided a scipy dependency and proposed
  a hand-rolled Gauss--Newton; the fit here uses
  ``scipy.optimize.minimize(method="L-BFGS-B")`` on a Baker--Cousins deviance.
* **pseudo-Voigt, not Gaussian-only.**  TAS lineshapes are rarely pure
  Gaussians; the model is an area-parameterized pseudo-Voigt (shared FWHM,
  mixing parameter ``eta``) on a flat background.
* **soft gating.**  The doc refused to return a value for edge peaks, multiple
  peaks, poor fits, etc.  Here those conditions become ``warnings`` on an
  otherwise valid result -- the fit only reports ``converged=False`` on a
  genuine failure (bad input, too few points, optimizer failure).  Whether an
  amber result is acted on is the caller's decision.

Public surface:

* :func:`com` -- counts-weighted centroid (SPEC convention: raw counts, no
  background subtraction).
* :func:`peak_max` -- abscissa of the highest count bin.
* :func:`fit_peak` -- pseudo-Voigt + flat background quick fit.
* :data:`SCAN_VARIABLE_TO_FIELD` / :func:`field_for_scan_variable` -- which
  settable GUI parameter field a scan variable maps to, for a later "goto".
* :func:`plan_goto` / :func:`format_goto_message` /
  :func:`format_revert_message` -- the refusal policy and wording for the
  controller's "goto"; the controller keeps only the widget work.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Model constants
# --------------------------------------------------------------------------

_FOUR_LN2 = 4.0 * math.log(2.0)
#: Peak height of a unit-area Gaussian of unit FWHM.
_G_NORM = math.sqrt(_FOUR_LN2 / math.pi)
#: Peak height of a unit-area Lorentzian of unit FWHM.
_L_NORM = 2.0 / math.pi
#: Model floor used *inside the cost only*, so ln(y/f) stays finite.
_MODEL_FLOOR = 1e-12
#: Smallest admissible fitted area (the lower bound on ``I``).
_MIN_AREA = 1e-12
#: Distance from 0/1 at which ``eta`` counts as sitting on its boundary.
_ETA_EDGE = 1e-3
#: Samples on the returned model curve when the caller does not say.
_DEFAULT_N_CURVE = 400
#: Hard cap on the model curve, so an absurd request cannot MemoryError out of
#: a function that promises never to raise.
_MAX_N_CURVE = 100000

_PARAM_NAMES = ("area", "fwhm", "center", "eta", "background")


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PeakEstimate:
    """Result of a non-fitting reduction (:func:`com` / :func:`peak_max`)."""

    ok: bool
    reason: str
    x: Optional[float]
    n_points: int
    total_counts: float
    #: Local abscissa spacing at the reported point.  Populated by
    #: :func:`peak_max` so a UI can caveat "highest bin, not interpolated";
    #: always ``None`` for :func:`com`.
    bin_width: Optional[float] = None


@dataclass(frozen=True)
class QuickFitResult:
    """Result of :func:`fit_peak`.

    ``converged=False`` means no usable fit exists (bad input, too few points,
    optimizer failure) and ``reason`` says why.  ``converged=True`` with a
    non-empty ``warnings`` tuple is an amber result: usable, but the caller
    should show the reasons.
    """

    converged: bool
    reason: str
    center: Optional[float] = None
    center_err: Optional[float] = None
    fwhm: Optional[float] = None
    fwhm_err: Optional[float] = None
    area: Optional[float] = None
    area_err: Optional[float] = None
    height: Optional[float] = None
    height_err: Optional[float] = None
    eta: Optional[float] = None
    eta_err: Optional[float] = None
    background: Optional[float] = None
    background_err: Optional[float] = None
    #: 0.0 / 1.0 when the eta-boundary refit ran, else ``None``.
    eta_fixed: Optional[float] = None
    deviance: Optional[float] = None
    deviance_reduced: Optional[float] = None
    n_points: int = 0
    n_free: int = 0
    dof: int = 0
    warnings: tuple = ()
    curve_x: Optional[np.ndarray] = None
    curve_y: Optional[np.ndarray] = None


# --------------------------------------------------------------------------
# Shared preprocessing
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Selection:
    """Cleaned, x-sorted selection plus the metadata every consumer needs."""

    x: np.ndarray
    y: np.ndarray
    lo: float
    hi: float
    span: float
    n_unique: int
    min_dx: Optional[float]


def _preprocess(x, counts, mask=None, xrange=None):
    """Clean/sort a scan selection.

    Returns ``(selection, reason)``; exactly one of the two is ``None``.
    Never raises: malformed input comes back as a reason string.
    """
    try:
        xa = np.asarray(x, dtype=float).ravel() if np.ndim(x) <= 1 else None
        ya = np.asarray(counts, dtype=float).ravel() if np.ndim(counts) <= 1 else None
    except (TypeError, ValueError) as exc:
        log.warning("scan_fits: could not coerce scan arrays to float: %s", exc)
        return None, "x/counts are not numeric arrays"

    if xa is None or ya is None:
        return None, "x and counts must be 1-D"
    if xa.size != ya.size:
        return None, "x and counts have different lengths (%d vs %d)" % (xa.size, ya.size)
    if xa.size == 0:
        return None, "no data points"

    if mask is None:
        usable = np.ones(xa.size, dtype=bool)
    else:
        try:
            ma = np.asarray(mask).ravel()
        except (TypeError, ValueError) as exc:
            log.warning("scan_fits: could not coerce mask: %s", exc)
            return None, "mask is not a boolean array"
        if ma.size != xa.size:
            return None, "mask has a different length from x (%d vs %d)" % (ma.size, xa.size)
        usable = ma.astype(bool)

    usable = usable & np.isfinite(xa) & np.isfinite(ya)

    # Poisson counts model: a negative count is an input error, not noise.
    if np.any(ya[usable] < 0.0):
        return None, "negative counts in selection (counts must be Poisson)"

    if xrange is not None:
        try:
            r0, r1 = (float(v) for v in xrange)
        except (TypeError, ValueError) as exc:
            log.warning("scan_fits: bad xrange %r: %s", xrange, exc)
            return None, "xrange must be a pair of numbers"
        if not (math.isfinite(r0) and math.isfinite(r1)):
            return None, "xrange must be finite"
        lo_r, hi_r = (r0, r1) if r0 <= r1 else (r1, r0)
        if hi_r == lo_r:
            return None, "xrange has zero span"
        usable = usable & (xa >= lo_r) & (xa <= hi_r)

    if not np.any(usable):
        return None, "no usable points in selection"

    xs = xa[usable]
    ys = ya[usable]
    order = np.argsort(xs, kind="stable")
    xs = xs[order]
    ys = ys[order]

    uniq = np.unique(xs)
    diffs = np.diff(uniq)
    diffs = diffs[diffs > 0.0]
    min_dx = float(diffs.min()) if diffs.size else None

    lo = float(xs[0])
    hi = float(xs[-1])
    return _Selection(
        x=xs, y=ys, lo=lo, hi=hi, span=hi - lo,
        n_unique=int(uniq.size), min_dx=min_dx,
    ), None


# --------------------------------------------------------------------------
# Non-fitting reductions
# --------------------------------------------------------------------------

def com(x, counts, *, mask=None, xrange=None) -> PeakEstimate:
    """Counts-weighted centroid ``sum(x*c) / sum(c)``.

    Computed on **raw counts with no background subtraction**, which is the
    SPEC convention this mirrors (``docs/CONTROL_FEATURES_DESIGN.md`` §1.3).
    """
    sel, reason = _preprocess(x, counts, mask=mask, xrange=xrange)
    if sel is None:
        return PeakEstimate(ok=False, reason=reason, x=None, n_points=0,
                            total_counts=0.0, bin_width=None)

    total = float(np.sum(sel.y))
    n = int(sel.x.size)
    if total <= 0.0:
        return PeakEstimate(ok=False, reason="no counts in selection", x=None,
                            n_points=n, total_counts=total, bin_width=None)

    value = float(np.sum(sel.x * sel.y) / total)
    return PeakEstimate(ok=True, reason="", x=value, n_points=n,
                        total_counts=total, bin_width=None)


def peak_max(x, counts, *, mask=None, xrange=None) -> PeakEstimate:
    """Abscissa of the highest count in the selection.

    Ties resolve to the **first point in ascending-x order**.  ``bin_width``
    carries the local abscissa spacing at that point so a UI can caveat that
    this is the highest measured bin, not an interpolated position.
    """
    sel, reason = _preprocess(x, counts, mask=mask, xrange=xrange)
    if sel is None:
        return PeakEstimate(ok=False, reason=reason, x=None, n_points=0,
                            total_counts=0.0, bin_width=None)

    total = float(np.sum(sel.y))
    n = int(sel.x.size)
    if total <= 0.0:
        return PeakEstimate(ok=False, reason="no counts in selection", x=None,
                            n_points=n, total_counts=total, bin_width=None)

    idx = int(np.argmax(sel.y))  # argmax returns the first maximum
    if n == 1:
        width = sel.min_dx
    elif idx == 0:
        width = float(sel.x[1] - sel.x[0])
    elif idx == n - 1:
        width = float(sel.x[-1] - sel.x[-2])
    else:
        width = float(sel.x[idx + 1] - sel.x[idx - 1]) / 2.0
    if width is not None and width <= 0.0:
        width = sel.min_dx  # duplicated abscissae: fall back to the grid step

    return PeakEstimate(ok=True, reason="", x=float(sel.x[idx]), n_points=n,
                        total_counts=total, bin_width=width)


# --------------------------------------------------------------------------
# Pseudo-Voigt model
# --------------------------------------------------------------------------

def _model(x, area, fwhm, center, eta, background):
    """Area-parameterized pseudo-Voigt on a flat background.

    Both components integrate to ``area`` and share ``fwhm``; ``eta=0`` is a
    pure Gaussian and ``eta=1`` a pure Lorentzian.
    """
    u = (x - center) / fwhm
    u2 = u * u
    gauss = (_G_NORM / fwhm) * np.exp(-_FOUR_LN2 * u2)
    lorentz = (_L_NORM / fwhm) / (1.0 + 4.0 * u2)
    return area * (eta * lorentz + (1.0 - eta) * gauss) + background


def _peak_height(area, fwhm, eta):
    """Model value at ``center`` minus the background."""
    return area * (eta * _L_NORM + (1.0 - eta) * _G_NORM) / fwhm


def _deviance(params, x, y):
    """Baker--Cousins Poisson deviance ``2*sum(f - y + y*ln(y/f))``.

    The ``y=0`` term reduces to ``2*f``.  The model is clamped to a tiny
    positive floor here (and only here) so the logarithm stays finite.
    """
    f = _model(x, *params)
    if not np.all(np.isfinite(f)):
        return np.inf
    f = np.maximum(f, _MODEL_FLOOR)
    terms = f - y
    pos = y > 0.0
    if np.any(pos):
        terms[pos] += y[pos] * np.log(y[pos] / f[pos])
    total = 2.0 * float(np.sum(terms))
    return total if math.isfinite(total) else np.inf


# --------------------------------------------------------------------------
# Numerical Hessian / covariance
# --------------------------------------------------------------------------

def _numeric_hessian(cost, p, lower, upper):
    """Central-difference Hessian of ``cost`` at ``p``.

    A parameter sitting on (or within a step of) a bound has its evaluation
    centre nudged inward by one step, which makes the stencil one-sided with
    respect to the optimum -- the alternative, differencing outside the bound,
    evaluates the model in a region the fit already declared invalid.
    Returns ``None`` when the box is too narrow to difference in.
    """
    n = len(p)
    h = np.array([max(1e-6, 1e-4 * abs(v)) for v in p], dtype=float)
    base = np.array(p, dtype=float)
    for i in range(n):
        lo_i = lower[i] if lower[i] is not None else -np.inf
        hi_i = upper[i] if upper[i] is not None else np.inf
        if hi_i - lo_i < 2.0 * h[i]:
            log.warning("scan_fits: parameter %d box narrower than its Hessian "
                        "step; covariance unavailable", i)
            return None
        base[i] = min(max(base[i], lo_i + h[i]), hi_i - h[i])

    hess = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i, n):
            pp = base.copy(); pp[i] += h[i]; pp[j] += h[j]
            pm = base.copy(); pm[i] += h[i]; pm[j] -= h[j]
            mp = base.copy(); mp[i] -= h[i]; mp[j] += h[j]
            mm = base.copy(); mm[i] -= h[i]; mm[j] -= h[j]
            value = (cost(pp) - cost(pm) - cost(mp) + cost(mm)) / (4.0 * h[i] * h[j])
            hess[i, j] = value
            hess[j, i] = value
    if not np.all(np.isfinite(hess)):
        log.warning("scan_fits: non-finite numerical Hessian; covariance unavailable")
        return None
    return hess


def _covariance(hess):
    """Covariance from the Hessian of a deviance.

    The cost is ``C = -2 ln L`` (up to a constant), so the Fisher information
    is ``H/2`` and ``cov = inv(H/2) = 2 * inv(H)``.  Returns ``None`` when the
    inverse is unusable.
    """
    if hess is None:
        return None
    try:
        cov = 2.0 * np.linalg.inv(hess)
    except np.linalg.LinAlgError as exc:
        log.warning("scan_fits: Hessian inversion failed: %s", exc)
        return None
    if not np.all(np.isfinite(cov)):
        log.warning("scan_fits: non-finite covariance matrix")
        return None
    if np.any(np.diag(cov) <= 0.0):
        log.warning("scan_fits: non-positive variance on the covariance diagonal")
        return None
    return cov


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

def _moment_seed(sel):
    """Moment-based starting parameters ``(area, fwhm, center, eta, bg)``."""
    x, y = sel.x, sel.y
    span = sel.span
    min_dx = sel.min_dx if sel.min_dx is not None else (span / max(x.size - 1, 1))

    bg0 = float(np.clip(np.median(y), 0.0, None))
    yc = np.clip(y - bg0, 0.0, None)
    ysum = float(np.sum(yc))
    if ysum > 0.0:
        center0 = float(np.sum(x * yc) / ysum)
        m2 = float(np.sum((x - center0) ** 2 * yc) / ysum)
        fwhm0 = float(np.clip(2.3548 * math.sqrt(max(m2, 0.0)), 2.0 * min_dx, span))
    else:
        center0 = float(x[int(np.argmax(y))])
        fwhm0 = span / 4.0
    if not (fwhm0 > 0.0):
        fwhm0 = max(2.0 * min_dx, span / 4.0)

    peak0 = max(float(np.max(y)) - bg0, _MIN_AREA)
    area0 = peak0 * fwhm0 / _G_NORM
    return [area0, fwhm0, center0, 0.5, bg0]


def _apply_seed_override(start, seed):
    """Overlay a caller-supplied ``seed`` dict onto moment starting values."""
    if not isinstance(seed, dict):
        log.warning("scan_fits: ignoring non-dict seed %r", type(seed).__name__)
        return start
    for i, name in enumerate(_PARAM_NAMES):
        if name not in seed:
            continue
        try:
            value = float(seed[name])
        except (TypeError, ValueError) as exc:
            log.warning("scan_fits: ignoring unusable seed for %s: %s", name, exc)
            continue
        if math.isfinite(value):
            start[i] = value
        else:
            log.warning("scan_fits: ignoring non-finite seed for %s", name)
    return start


# --------------------------------------------------------------------------
# Fit
# --------------------------------------------------------------------------

def _minimize(sel, start, bounds, fixed_eta=None):
    """Run L-BFGS-B on the deviance; returns ``(params, result)``.

    ``fixed_eta`` freezes ``eta``, leaving four free parameters.
    """
    x, y = sel.x, sel.y
    free_idx = [0, 1, 2, 3, 4] if fixed_eta is None else [0, 1, 2, 4]

    def expand(pfree):
        full = np.empty(5, dtype=float)
        if fixed_eta is None:
            full[:] = pfree
        else:
            full[0], full[1], full[2], full[4] = pfree
            full[3] = fixed_eta
        return full

    def cost(pfree):
        return _deviance(expand(pfree), x, y)

    p0 = [float(np.clip(start[i], bounds[i][0],
                        bounds[i][1] if bounds[i][1] is not None else np.inf))
          for i in free_idx]
    res = minimize(cost, p0, method="L-BFGS-B",
                   bounds=[bounds[i] for i in free_idx],
                   options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-10})
    return res, cost, free_idx, expand


def _collect_warnings(sel, center, center_err, fwhm, height, background, dof):
    """Amber conditions -- advisory only, never blockers."""
    warns = []
    span = sel.span
    if span > 0.0 and center is not None:
        edge = 0.05 * span
        if (center - sel.lo) < edge or (sel.hi - center) < edge:
            warns.append("center near range edge")
    if center_err is None or (fwhm is not None and center_err > 0.25 * fwhm):
        warns.append("center uncertainty large")
    if height is not None and background is not None:
        if height < 3.0 * math.sqrt(max(background, 1.0)):
            warns.append("weak peak vs background")
    if _count_local_maxima(sel.y) >= 2:
        warns.append("possible multiple peaks")
    if dof < 3:
        warns.append("few degrees of freedom")
    return tuple(warns)


def _count_local_maxima(y, fraction=0.7):
    """Interior local maxima of a 3-point boxcar smoothing, above ``fraction``
    of the smoothed global maximum."""
    n = y.size
    if n < 3:
        return 0
    smooth = np.empty(n, dtype=float)
    smooth[0] = (y[0] + y[1]) / 2.0
    smooth[-1] = (y[-1] + y[-2]) / 2.0
    if n > 2:
        smooth[1:-1] = (y[:-2] + y[1:-1] + y[2:]) / 3.0
    peak = float(np.max(smooth))
    if peak <= 0.0:
        return 0
    threshold = fraction * peak
    count = 0
    for i in range(1, n - 1):
        if smooth[i] >= threshold and smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            count += 1
    return count


def _curve_points(n_curve):
    """Samples on the model curve, defensively coerced.

    ``fit_peak`` promises never to raise, and the curve length is the one
    argument a caller can hand straight to ``np.linspace``.  Junk (a string,
    ``None``, NaN, infinity) becomes the default plus a log line rather than a
    ``ValueError`` escaping from the middle of a fit.
    """
    try:
        value = float(n_curve)
    except (TypeError, ValueError) as exc:
        log.warning("scan_fits: unusable n_curve %r (%s); using %d",
                    n_curve, exc, _DEFAULT_N_CURVE)
        return _DEFAULT_N_CURVE
    if not math.isfinite(value):
        log.warning("scan_fits: non-finite n_curve %r; using %d",
                    n_curve, _DEFAULT_N_CURVE)
        return _DEFAULT_N_CURVE
    if value > _MAX_N_CURVE:
        log.warning("scan_fits: n_curve %r exceeds the cap; using %d",
                    n_curve, _MAX_N_CURVE)
        return _MAX_N_CURVE
    return max(int(value), 2)


def _stall_is_expected(start_was_optimum, start_deviance, deviance):
    """Whether a line-search stall is a formality rather than a bad fit.

    L-BFGS-B reports status 2 (ABNORMAL_TERMINATION_IN_LNSRCH) both when a run
    *began* at the optimum and when a run got nowhere from a bad start.  Those
    mean opposite things, and zero progress alone does not separate them: a
    cold moment-seeded fit that fails to improve on its seed also shows zero
    progress, and that is exactly the case an operator needs flagged.

    So both conditions must hold: the start was *deliberately* an optimum (a
    caller-supplied warm start, or the eta-boundary refit that restarts from
    the previous fit), **and** the run made no measurable progress from it.
    A cold start that stalls keeps its warning.
    """
    if not start_was_optimum:
        return False
    if deviance is None or not math.isfinite(start_deviance):
        return False
    return start_deviance - deviance <= max(1e-6, 1e-9 * abs(deviance))


def fit_peak(x, counts, *, mask=None, xrange=None, seed=None,
             n_curve=_DEFAULT_N_CURVE) -> QuickFitResult:
    """Fit a pseudo-Voigt + flat background to a scan selection.

    Parameters
    ----------
    x, counts : sequence
        Abscissa and raw counts of the scan.
    mask : sequence of bool, optional
        Per-point keep flags (``True`` = use the point).
    xrange : (float, float), optional
        Restrict the fit to this abscissa window; a reversed pair is
        normalized.
    seed : dict, optional
        Warm start from a previous fit on the same scan, keyed by the public
        parameter names ``area``, ``fwhm``, ``center``, ``eta``,
        ``background``.  Non-finite or unusable entries are logged and ignored.
    n_curve : int
        Number of points on the returned fine model curve.  Unusable values
        (non-numeric, non-finite) are logged and replaced by the default.

    Never raises: a failure comes back as ``converged=False`` plus ``reason``.
    """
    sel, reason = _preprocess(x, counts, mask=mask, xrange=xrange)
    if sel is None:
        return QuickFitResult(converged=False, reason=reason)

    n = int(sel.x.size)
    # 5 free parameters + 1: fewer points (or fewer distinct abscissae) than
    # that cannot constrain the model at all.
    if n < 6:
        return QuickFitResult(converged=False, n_points=n,
                              reason="need at least 6 usable points, got %d" % n)
    if sel.n_unique < 6:
        return QuickFitResult(
            converged=False, n_points=n,
            reason="need at least 6 distinct x values, got %d" % sel.n_unique)
    if sel.span <= 0.0 or sel.min_dx is None:
        return QuickFitResult(converged=False, n_points=n,
                              reason="selection has zero abscissa span")
    # No counts means no peak. The optimizer will happily "converge" on such a
    # selection -- area pinned at its lower bound, center parked wherever it
    # started -- and report a centre a caller could drive a motor to. Refuse
    # for the same reason, and with the same wording, as com/peak_max.
    if float(np.sum(sel.y)) <= 0.0:
        return QuickFitResult(converged=False, n_points=n,
                              reason="no counts in selection")

    ymax = float(np.max(sel.y))
    bounds = [
        (_MIN_AREA, None),               # area
        (sel.min_dx, 2.0 * sel.span),    # fwhm
        (sel.lo, sel.hi),                # center
        (0.0, 1.0),                      # eta
        (0.0, ymax + 1.0),               # background
    ]

    start = _moment_seed(sel)
    if seed is not None:
        start = _apply_seed_override(start, seed)

    res, cost, free_idx, expand = _minimize(sel, start, bounds)
    params = expand(np.asarray(res.x, dtype=float))
    fixed_eta = None
    last_start = list(start)  # start vector of the most recent minimize run
    # Whether that start was *deliberately* an optimum. A caller-supplied seed
    # is a warm start from a previous fit of the same data; the eta-boundary
    # refit below restarts from the run that just finished. See
    # _stall_is_expected for why zero progress alone is not the test.
    start_was_optimum = seed is not None

    # Eta on a boundary: refit with it frozen so the covariance is not taken
    # across the constraint.
    if np.all(np.isfinite(params)):
        if params[3] <= _ETA_EDGE:
            fixed_eta = 0.0
        elif params[3] >= 1.0 - _ETA_EDGE:
            fixed_eta = 1.0
        if fixed_eta is not None:
            start2 = list(params)
            start2[3] = fixed_eta
            res, cost, free_idx, expand = _minimize(sel, start2, bounds,
                                                    fixed_eta=fixed_eta)
            params = expand(np.asarray(res.x, dtype=float))
            last_start = list(start2)
            start_was_optimum = True

    n_free = len(free_idx)
    dof = n - n_free
    finite = bool(np.all(np.isfinite(params)))
    # L-BFGS-B status 2 (ABNORMAL_TERMINATION_IN_LNSRCH) is what a *converged*
    # start looks like: the line search cannot improve on the current point.
    # The eta-boundary refit starts from the previous optimum and hits this
    # routinely. Accept it, but surface it as a warning rather than silently.
    stalled = (not bool(res.success)) and int(getattr(res, "status", -1)) == 2
    converged = (bool(res.success) or stalled) and finite

    if not finite:
        return QuickFitResult(
            converged=False, n_points=n, n_free=n_free, dof=dof,
            reason="fit produced non-finite parameters")

    area, fwhm, center, eta, background = (float(v) for v in params)
    deviance = _deviance(params, sel.x, sel.y)
    deviance = float(deviance) if math.isfinite(deviance) else None
    dev_red = (deviance / dof) if (deviance is not None and dof > 0) else None
    height = _peak_height(area, fwhm, eta)

    warns = []
    message = getattr(res, "message", "")
    if isinstance(message, bytes):
        message = message.decode("utf-8", "replace")
    if stalled:
        start_dev = _deviance(np.asarray(last_start, dtype=float), sel.x, sel.y)
        if _stall_is_expected(start_was_optimum, start_dev, deviance):
            # The run began at (numerically) the optimum -- a warm start or the
            # eta-boundary refit -- so a line-search stall is the expected exit,
            # not a fit-quality concern.
            log.info("scan_fits: line search stalled at an already-optimal "
                     "start: %s", message)
        else:
            warns.append("optimizer line search stalled")
            log.info("scan_fits: line search stalled: %s", message)
    elif not converged:
        log.warning("scan_fits: optimizer did not converge: %s", message)

    cov = _covariance(_numeric_hessian(cost, np.asarray(res.x, dtype=float),
                                       [bounds[i][0] for i in free_idx],
                                       [bounds[i][1] for i in free_idx]))
    errs = {name: None for name in _PARAM_NAMES}
    height_err = None
    if cov is None:
        warns.append("covariance unreliable")
    else:
        sd = np.sqrt(np.diag(cov))
        for slot, full_i in enumerate(free_idx):
            errs[_PARAM_NAMES[full_i]] = float(sd[slot])
        # height = area * (eta*L + (1-eta)*G) / fwhm; propagate with full
        # cross terms over whichever of (area, fwhm, eta) are free.
        shape = (eta * _L_NORM + (1.0 - eta) * _G_NORM) / fwhm
        grad_full = {
            0: shape,                                     # d/d area
            1: -area * shape / fwhm,                      # d/d fwhm
            3: area * (_L_NORM - _G_NORM) / fwhm,         # d/d eta
        }
        idx = [slot for slot, full_i in enumerate(free_idx) if full_i in grad_full]
        jac = np.array([grad_full[free_idx[slot]] for slot in idx], dtype=float)
        sub = cov[np.ix_(idx, idx)]
        var = float(jac @ sub @ jac)
        height_err = math.sqrt(var) if var > 0.0 and math.isfinite(var) else None

    grid = np.linspace(sel.lo, sel.hi, _curve_points(n_curve))
    curve = _model(grid, area, fwhm, center, eta, background)

    warns.extend(_collect_warnings(sel, center, errs["center"], fwhm, height,
                                   background, dof))
    if not converged:
        warns.append("fit did not converge")

    return QuickFitResult(
        converged=converged,
        reason="" if converged else "optimizer did not converge",
        center=center, center_err=errs["center"],
        fwhm=fwhm, fwhm_err=errs["fwhm"],
        area=area, area_err=errs["area"],
        height=height, height_err=height_err,
        eta=eta, eta_err=None if fixed_eta is not None else errs["eta"],
        background=background, background_err=errs["background"],
        eta_fixed=fixed_eta,
        deviance=deviance, deviance_reduced=dev_red,
        n_points=n, n_free=n_free, dof=dof,
        warnings=tuple(dict.fromkeys(warns)),
        curve_x=grid, curve_y=curve,
    )


# --------------------------------------------------------------------------
# Goto mapping
# --------------------------------------------------------------------------

# Scan variable -> settable GUI parameter field (TAVI_PySide6.TAVIController._api_field_map).
# Derived from the scan-point template (_build_scan_point_template) and
# _SCAN_VARIABLE_TO_INDEX: angle-mode slots are [mtt, stt, omega, att] so A1->mtt,
# A2/2theta->stt, A3->omega, A4->att. Scan variables 'omega' and 'psi' both step
# template slot 10, which is seeded from the psi field -> both map to 'psi'.
# 'chi' is None: its template slot 8 is hardcoded 0 rather than seeded from the chi
# field, so the field<->slot relationship is unverified (a goto could double-apply
# an offset). 'rva' is None: no settable field exists in _api_field_map.
SCAN_VARIABLE_TO_FIELD = {
    "H": "H", "K": "K", "L": "L", "deltaE": "deltaE",
    "qx": "qx", "qy": "qy", "qz": "qz",
    "A1": "mtt", "A2": "stt", "2theta": "stt", "A3": "omega", "A4": "att",
    "omega": "psi", "psi": "psi", "kappa": "kappa",
    "chi": None, "rva": None,
    "rhm": "rhm", "rvm": "rvm", "rha": "rha",
}

#: Case-insensitive index onto the canonical spellings above.  Built once;
#: lower-case collisions cannot occur in the table as written.
_SCAN_VARIABLE_FOLDED = {name.lower(): name for name in SCAN_VARIABLE_TO_FIELD}


def _canonical_scan_variable(name) -> Optional[str]:
    """Canonical spelling of a scan variable, or ``None`` if it is unknown.

    Knowing *that* a variable exists is separate from knowing whether it is
    goto-able: ``chi``/``rva`` are known rows whose field is ``None``, and the
    two cases must produce different refusals.
    """
    if not isinstance(name, str):
        return None
    if name in SCAN_VARIABLE_TO_FIELD:
        return name
    return _SCAN_VARIABLE_FOLDED.get(name.lower())


def field_for_scan_variable(name: str) -> Optional[str]:
    """Settable parameter field for a scan variable; ``None`` = not goto-able.

    Exact (case-sensitive) match first, then a case-insensitive lookup against
    the known spellings.  An unknown variable returns ``None``.
    """
    canonical = _canonical_scan_variable(name)
    if canonical is None:
        return None
    return SCAN_VARIABLE_TO_FIELD[canonical]


# --------------------------------------------------------------------------
# Goto policy and wording
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GotoPlan:
    """Verdict on a requested "move the instrument to this value".

    ``ok=True`` carries the settable parameter field and a plain ``float``;
    ``ok=False`` carries a human-readable ``reason`` and nothing else.  All of
    the refusal policy lives here so the controller side stays thin.
    """

    ok: bool
    reason: str
    variable: str
    field: Optional[str]
    value: Optional[float]


def plan_goto(variable, value, *, busy: bool) -> GotoPlan:
    """Decide whether a goto may run, and onto which parameter field.

    Refusals are checked in this order, because each later check is only
    meaningful once the earlier one passed:

    1. ``busy`` -- a scan is running or queued, so nothing may be moved;
    2. the variable is unknown, or known but not goto-able;
    3. the target value is not a real finite number.

    Booleans are rejected explicitly (``np.bool_`` included, since a reduction
    can produce one): ``True`` is a perfectly good float in Python and would
    silently move an axis to 1.0.
    """
    name = variable if isinstance(variable, str) else repr(variable)

    if busy:
        return GotoPlan(ok=False, reason="a scan is running or queued",
                        variable=name, field=None, value=None)

    canonical = _canonical_scan_variable(variable)
    if canonical is None:
        return GotoPlan(ok=False, reason="unknown scan variable '%s'" % name,
                        variable=name, field=None, value=None)
    field = SCAN_VARIABLE_TO_FIELD[canonical]
    if field is None:
        return GotoPlan(ok=False, reason="'%s' is not goto-able" % name,
                        variable=name, field=None, value=None)

    if isinstance(value, (bool, np.bool_)):
        return GotoPlan(ok=False, reason="target value is not finite",
                        variable=name, field=None, value=None)
    try:
        target = float(value)
    except (TypeError, ValueError) as exc:
        log.warning("scan_fits: goto target %r is not numeric: %s", value, exc)
        return GotoPlan(ok=False, reason="target value is not finite",
                        variable=name, field=None, value=None)
    if not math.isfinite(target):
        return GotoPlan(ok=False, reason="target value is not finite",
                        variable=name, field=None, value=None)

    return GotoPlan(ok=True, reason="", variable=name, field=field, value=target)


def _fmt_value(value) -> str:
    """Render a parameter value for a message; ``None`` becomes ``'?'``."""
    if value is None:
        return "?"
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        log.warning("scan_fits: unformattable value %r: %s", value, exc)
        return str(value)
    if not math.isfinite(number):
        return str(number)
    if number == 0.0 or 1e-3 <= abs(number) < 1e6:
        return "%.3f" % number
    return "%.3g" % number


def format_goto_message(label: str, variable: str, field: str,
                        old_value, new_value, *, extra: str = "") -> str:
    """One-line report of a completed goto.

    e.g. ``goto CEN: A3 12.340 -> 12.417 (field omega)``.  ``old_value`` may be
    ``None`` (the previous reading was unavailable) and renders as ``?``.
    ``extra`` appends fit context supplied by the caller.
    """
    message = "%s: %s %s -> %s (field %s)" % (
        label, variable, _fmt_value(old_value), _fmt_value(new_value), field,
    )
    if extra:
        message += " -- %s" % extra
    return message


def format_revert_message(field: str, restored_value) -> str:
    """One-line report of a completed single-level revert."""
    return "revert: %s restored to %s" % (field, _fmt_value(restored_value))
