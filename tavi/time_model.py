"""Affine scan-time cost model: ``per_point = overhead + rate * ncount``.

Per-point simulation time is affine in the neutron count, not purely linear: a
fixed overhead (prep/queue/MPI fan-out/postprocess) dominates below ~1e7
neutrons, and a per-neutron rate dominates above it. Treating the whole cost as
per-neutron (the old model) turns that fixed overhead into phantom neutron cost
and inflates high-ncount estimates by orders of magnitude.

This module fits the affine model in closed form via weighted least squares over
``(ncount, per_point_seconds, weight)`` samples grouped by exact ncount. It is
Qt-free and has no third-party dependencies (the fit is closed-form; scipy is
not needed).
"""
from typing import Dict, List, Optional, Tuple

# Fit gate: an affine fit needs at least this many distinct ncount groups and a
# spread of at least this ratio between the largest and smallest ncount. Below
# the spread there is no lever arm to separate overhead from rate, so the model
# degrades to the single-cluster fallback instead of fabricating a slope.
MIN_GROUPS = 2
SPREAD_MIN = 10.0

# Extrapolation guard: predictions beyond this factor of the observed ncount
# range are flagged so callers can force low confidence.
EXTRAPOLATION_FACTOR = 10.0

Sample = Tuple[float, float, float]  # (ncount, per_point_seconds, weight)


def weighted_median(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """Weighted median of ``(value, weight)`` pairs (weights > 0).

    Moved here from ``RuntimeTracker`` so the fitter and the tracker share one
    implementation. Falls back to the unweighted median when all weights are
    non-positive. Returns ``None`` for an empty input.
    """
    if not pairs:
        return None
    ordered = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in ordered)
    if total <= 0:
        vals = [v for v, _ in ordered]
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    half = total / 2.0
    cum = 0.0
    for value, weight in ordered:
        cum += weight
        if cum >= half:
            return value
    return ordered[-1][0]


def _group_samples(samples: List[Sample]) -> List[Tuple[float, float, float]]:
    """Collapse samples to one point per exact ncount.

    Returns ``[(ncount, weighted_median_value, summed_weight), ...]``. Samples
    with a non-positive ncount, a missing/negative value, or a non-positive
    weight are dropped.
    """
    groups: Dict[float, List[Tuple[float, float]]] = {}
    for ncount, value, weight in samples:
        if ncount is None or ncount <= 0:
            continue
        if value is None or value < 0:
            continue
        if weight is None or weight <= 0:
            continue
        groups.setdefault(float(ncount), []).append((value, weight))
    points: List[Tuple[float, float, float]] = []
    for ncount, members in groups.items():
        y = weighted_median(members)
        if y is None:
            continue
        w = sum(w for _, w in members)
        points.append((ncount, y, w))
    return points


def fit_affine_time_model(samples: List[Sample]) -> Dict[str, object]:
    """Fit ``per_point = overhead + rate * ncount`` by weighted least squares.

    ``samples`` is a list of ``(ncount, per_point_seconds, weight)``. Samples are
    grouped by exact ncount (weighted median per group, summed weight). An
    affine fit requires at least ``MIN_GROUPS`` groups and an ncount spread of at
    least ``SPREAD_MIN``; otherwise the result is tagged ``"degenerate"`` (or
    ``None`` when there are no usable samples) and the caller falls back to
    single-cluster scaling.

    Non-negativity is enforced: a negative rate clips to zero (flat overhead
    fit), and a negative overhead clips to zero (pure per-neutron fit).

    Returns ``{"overhead", "rate", "kind", "n_groups", "ncount_min",
    "ncount_max"}`` where ``kind`` is ``"affine" | "degenerate" | None``.
    """
    points = _group_samples(samples)
    if not points:
        return {"overhead": None, "rate": None, "kind": None,
                "n_groups": 0, "ncount_min": None, "ncount_max": None}

    n_groups = len(points)
    ncount_min = min(p[0] for p in points)
    ncount_max = max(p[0] for p in points)

    degenerate = {"overhead": None, "rate": None, "kind": "degenerate",
                  "n_groups": n_groups, "ncount_min": ncount_min,
                  "ncount_max": ncount_max}

    if n_groups < MIN_GROUPS:
        return degenerate
    if ncount_min <= 0 or (ncount_max / ncount_min) < SPREAD_MIN:
        return degenerate

    Sw = sum(w for _, _, w in points)
    Sx = sum(w * x for x, _, w in points)
    Sxx = sum(w * x * x for x, _, w in points)
    Sy = sum(w * y for _, y, w in points)
    Sxy = sum(w * x * y for x, y, w in points)

    D = Sw * Sxx - Sx * Sx
    if D == 0:
        return degenerate

    b = (Sw * Sxy - Sx * Sy) / D
    a = (Sy - b * Sx) / Sw

    # Non-negativity clips.
    if b < 0:
        b = 0.0
        a = Sy / Sw if Sw > 0 else 0.0
    elif a < 0:
        a = 0.0
        b = Sxy / Sxx if Sxx > 0 else 0.0

    return {"overhead": a, "rate": b, "kind": "affine",
            "n_groups": n_groups, "ncount_min": ncount_min,
            "ncount_max": ncount_max}


def per_point_estimate(model: Optional[Dict[str, object]],
                       samples: List[Sample],
                       num_neutrons: float) -> Tuple[Optional[float], Optional[str]]:
    """Predict per-point seconds at ``num_neutrons`` from ``model``/``samples``.

    Returns ``(seconds, fit_tag)`` with ``fit_tag`` one of ``"affine"``,
    ``"nearest"``, ``"extrapolated"`` (or ``(None, None)`` when there is nothing
    to predict from).

    - An ``"affine"`` model predicts ``overhead + rate * N`` (clipped at 0).
    - Otherwise (degenerate / no model) the highest-ncount group ``(N0, y0)`` is
      the anchor: ``N <= N0`` returns ``y0`` (``"nearest"`` -- overhead is
      observation-bounded, never scaled down); ``N > N0`` returns the
      conservative all-is-rate ``y0 * (N / N0)`` (``"extrapolated"``).
    """
    if num_neutrons is None or num_neutrons <= 0:
        return (None, None)

    if model and model.get("kind") == "affine":
        a = model.get("overhead") or 0.0
        b = model.get("rate") or 0.0
        return (max(0.0, a + b * num_neutrons), "affine")

    groups = _group_samples(samples)
    if not groups:
        return (None, None)

    x0, y0, _ = max(groups, key=lambda g: g[0])
    if x0 <= 0 or num_neutrons <= x0:
        return (y0, "nearest")
    return (y0 * (num_neutrons / x0), "extrapolated")


def reference_ncount(model: Optional[Dict[str, object]],
                     samples: List[Sample]) -> Optional[float]:
    """The ncount a prediction is anchored on (for extrapolation checks).

    For an affine model this is ``ncount_max``; otherwise it is the highest
    observed ncount among the samples. ``None`` when nothing is available.
    """
    if model and model.get("kind") == "affine":
        return model.get("ncount_max")
    groups = _group_samples(samples)
    if not groups:
        return None
    return max(g[0] for g in groups)


def scale_per_point(y: float, ncount: float,
                    local_model: Dict[str, float],
                    foreign_model: Dict[str, float]) -> float:
    """Convert a foreign-machine per-point time to the local machine.

    Splits the foreign per-point value ``y`` (measured at ``ncount``) into its
    rate and overhead fractions using the foreign affine model, then rescales
    each fraction by the local/foreign ratio of that component::

        frac_rate = b_f * N / (a_f + b_f * N)              (clamped to [0, 1])
        y' = y * (frac_rate * (b_l / b_f) + (1 - frac_rate) * (a_l / a_f))

    A zero denominator in either component ratio leaves that component's ratio
    at 1.0 (no scaling). ``a_*`` = overhead, ``b_*`` = rate.
    """
    a_f = foreign_model.get("overhead") or 0.0
    b_f = foreign_model.get("rate") or 0.0
    a_l = local_model.get("overhead") or 0.0
    b_l = local_model.get("rate") or 0.0

    denom = a_f + b_f * ncount
    frac_rate = (b_f * ncount / denom) if denom > 0 else 0.0
    frac_rate = min(1.0, max(0.0, frac_rate))

    rate_ratio = (b_l / b_f) if b_f > 0 else 1.0
    over_ratio = (a_l / a_f) if a_f > 0 else 1.0

    return y * (frac_rate * rate_ratio + (1.0 - frac_rate) * over_ratio)
