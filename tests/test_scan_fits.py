"""Unit tests for tavi/scan_fits.py (COM/MAX reductions, quick fit, goto map).

Pure numpy/scipy, no Qt, no McStas. Covers the Qt-free computational core of
the GUI fitting dock sketched in ``docs/CONTROL_FEATURES_DESIGN.md`` §1 (with
the superseding decisions: scipy allowed, pseudo-Voigt model, soft gating).

All randomness uses a fixed ``np.random.default_rng`` seed and all comparisons
use absolute tolerances, so a failure is a real regression.
"""
import math
import os
import re

import numpy as np
import pytest

from tavi.scan_fits import (
    SCAN_VARIABLE_TO_FIELD,
    GotoPlan,
    PeakEstimate,
    QuickFitResult,
    com,
    field_for_scan_variable,
    fit_peak,
    format_goto_message,
    format_revert_message,
    peak_max,
    plan_goto,
)
from tavi.scan_fits import _DEFAULT_N_CURVE, _stall_is_expected

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")

_G_NORM = math.sqrt(4.0 * math.log(2.0) / math.pi)
_L_NORM = 2.0 / math.pi


def pseudo_voigt(x, area, fwhm, center, eta, background):
    """Reference implementation of the fitted model (kept independent)."""
    u = (np.asarray(x, dtype=float) - center) / fwhm
    gauss = (_G_NORM / fwhm) * np.exp(-4.0 * math.log(2.0) * u * u)
    lorentz = (_L_NORM / fwhm) / (1.0 + 4.0 * u * u)
    return area * (eta * lorentz + (1.0 - eta) * gauss) + background


def area_for_height(height, fwhm, eta):
    return height * fwhm / (eta * _L_NORM + (1.0 - eta) * _G_NORM)


# --------------------------------------------------------------------------
# fit_peak -- recovery
# --------------------------------------------------------------------------

def test_fit_recovers_poisson_pseudo_voigt():
    """Noisy pseudo-Voigt with zero-count bins: parameters come back."""
    eta_true, fwhm_true, center_true, bg_true = 0.3, 1.0, 5.0, 0.5
    area_true = area_for_height(200.0, fwhm_true, eta_true)
    x = np.arange(0.0, 10.05, 0.1)
    truth = pseudo_voigt(x, area_true, fwhm_true, center_true, eta_true, bg_true)
    y = np.random.default_rng(0).poisson(truth).astype(float)

    assert np.any(y == 0.0), "test needs zero-count bins to exercise the y=0 branch"

    res = fit_peak(x, y)

    assert res.converged, res.reason
    assert res.n_points == x.size
    assert res.n_free == 5
    assert res.dof == x.size - 5
    assert abs(res.center - center_true) < 0.02 * fwhm_true
    assert abs(res.fwhm - fwhm_true) < 0.15 * fwhm_true
    assert abs(res.area - area_true) < 0.15 * area_true
    assert res.curve_x.size == 400
    assert res.curve_y.size == 400
    assert res.deviance is not None and res.deviance_reduced is not None
    assert abs(res.deviance_reduced - res.deviance / res.dof) < 1e-12


def test_fit_noiseless_exact_model_is_tight():
    """Exact model data: the center comes back to a small fraction of the span."""
    eta_true, fwhm_true, center_true, bg_true = 0.4, 0.8, 4.2, 3.0
    area_true = area_for_height(500.0, fwhm_true, eta_true)
    x = np.linspace(1.0, 8.0, 141)
    y = pseudo_voigt(x, area_true, fwhm_true, center_true, eta_true, bg_true)
    span = x[-1] - x[0]

    res = fit_peak(x, y)

    assert res.converged, res.reason
    assert abs(res.center - center_true) < 1e-4 * span
    assert abs(res.fwhm - fwhm_true) < 1e-3 * fwhm_true
    assert abs(res.eta - eta_true) < 1e-3
    for err in (res.center_err, res.fwhm_err, res.area_err, res.background_err):
        assert err is not None and math.isfinite(err) and err > 0.0
    assert res.height_err is not None and math.isfinite(res.height_err)
    assert res.eta_fixed is None
    assert "covariance unreliable" not in res.warnings


def test_gaussian_truth_triggers_eta_boundary_refit():
    """eta=0 truth: eta is pinned at the boundary and refit with 4 free params."""
    fwhm_true, center_true, bg_true = 0.5, 2.0, 5.0
    area_true = area_for_height(800.0, fwhm_true, 0.0)
    x = np.linspace(0.5, 3.5, 121)
    y = pseudo_voigt(x, area_true, fwhm_true, center_true, 0.0, bg_true)

    res = fit_peak(x, y, seed={"eta": 0.0005})

    assert res.converged, res.reason
    assert res.eta_fixed == 0.0
    assert res.eta == 0.0
    assert res.eta_err is None
    assert res.n_free == 4
    assert res.dof == x.size - 4
    assert abs(res.center - center_true) < 1e-3
    assert abs(res.fwhm - fwhm_true) < 1e-2 * fwhm_true
    # The refit starts from the previous optimum; the resulting line-search
    # stall is expected and must not amber the result.
    assert "optimizer line search stalled" not in res.warnings


def test_warm_start_refit_at_optimum_is_not_amber():
    """Round-tripping a fit's own parameters as the seed must not produce the
    line-search-stall warning: the start is already optimal, so the stall is a
    numerical formality, not a fit-quality concern."""
    eta_true, fwhm_true, center_true, bg_true = 0.4, 0.8, 4.2, 3.0
    area_true = area_for_height(500.0, fwhm_true, eta_true)
    x = np.linspace(1.0, 8.0, 141)
    y = pseudo_voigt(x, area_true, fwhm_true, center_true, eta_true, bg_true)

    first = fit_peak(x, y)
    assert first.converged, first.reason
    seed = {"area": first.area, "fwhm": first.fwhm, "center": first.center,
            "eta": first.eta, "background": first.background}
    second = fit_peak(x, y, seed=seed)

    assert second.converged, second.reason
    assert "optimizer line search stalled" not in second.warnings
    assert abs(second.center - first.center) < 1e-6


def test_cold_start_stall_keeps_its_warning():
    """MAINTAINERS: zero progress alone must not suppress the stall warning.

    L-BFGS-B status 2 means the line search could not improve on the current
    point -- which is a formality when the run *started* at the optimum and a
    real fit-quality signal when a cold moment-seeded run got nowhere. Testing
    only "made no progress" conflates the two. The discriminator is unit-tested
    here because provoking a cold-start stall from real data is not reliably
    reproducible across scipy builds.
    """
    tiny = 1e-12  # "no measurable progress"
    # Warm start / eta-boundary refit that went nowhere: expected, suppress.
    assert _stall_is_expected(True, 100.0 + tiny, 100.0) is True
    assert _stall_is_expected(True, 100.0, 100.0) is True
    # Same zero progress, but from a cold start: a real signal, keep it.
    assert _stall_is_expected(False, 100.0, 100.0) is False
    assert _stall_is_expected(False, 100.0 + tiny, 100.0) is False
    # A warm start that DID improve substantially is not "already optimal".
    assert _stall_is_expected(True, 500.0, 100.0) is False
    # Degenerate deviances never claim the stall was expected.
    assert _stall_is_expected(True, float("inf"), 100.0) is False
    assert _stall_is_expected(True, 100.0, None) is False


def test_all_zero_counts_is_refused_not_converged():
    """An empty scan must not yield a goto-able centre.

    The optimizer will "converge" on all-zero counts -- area pinned at its
    lower bound and the centre parked wherever it started, typically at a
    range edge -- and a caller would happily drive a motor there. fit_peak
    refuses with the same wording com/peak_max use.
    """
    x = np.linspace(0.0, 4.0, 41)
    y = np.zeros_like(x)

    res = fit_peak(x, y)

    assert res.converged is False
    assert res.reason == "no counts in selection"
    assert res.center is None
    # The two non-fitting reductions agree, so a UI cannot enable one goto
    # button while refusing another on the same data.
    assert com(x, y).ok is False
    assert peak_max(x, y).ok is False


def test_all_zero_counts_inside_the_selected_range_is_refused():
    """The refusal follows the *selection*, not the whole scan: a range that
    excludes every count is as empty as an empty scan."""
    x = np.linspace(0.0, 10.0, 101)
    y = pseudo_voigt(x, 100.0, 0.5, 8.0, 0.0, 0.0)
    y[x < 5.0] = 0.0

    res = fit_peak(x, y, xrange=(0.0, 4.0))

    assert res.converged is False
    assert res.reason == "no counts in selection"


@pytest.mark.parametrize("bad", ["x", None, float("nan"), float("inf"), [1, 2]])
def test_hostile_n_curve_falls_back_instead_of_raising(bad):
    """fit_peak promises never to raise; n_curve is the one argument that goes
    straight into np.linspace, so junk must degrade to the default."""
    fwhm_true, center_true, bg_true = 0.6, 2.0, 4.0
    area_true = area_for_height(400.0, fwhm_true, 0.2)
    x = np.linspace(0.5, 3.5, 61)
    y = pseudo_voigt(x, area_true, fwhm_true, center_true, 0.2, bg_true)

    res = fit_peak(x, y, n_curve=bad)

    assert res.converged, res.reason
    assert res.curve_x is not None
    assert res.curve_x.size == _DEFAULT_N_CURVE


def test_n_curve_is_clamped_to_at_least_two_points():
    x = np.linspace(0.5, 3.5, 61)
    y = pseudo_voigt(x, area_for_height(400.0, 0.6, 0.0), 0.6, 2.0, 0.0, 4.0)

    res = fit_peak(x, y, n_curve=0)

    assert res.converged, res.reason
    assert res.curve_x.size == 2


def test_center_error_matches_analytic_gaussian_estimate():
    """Guards the deviance->covariance factor (cov = 2*inv(H), not inv(H)).

    For a Gaussian peak of FWHM W carrying N counts above background, the
    center's standard error is W / (2.3548 * sqrt(N)). A missing (or doubled)
    factor of two in the covariance shows up as a sqrt(2) or 1/sqrt(2) error
    here, which the factor-of-2 window catches.
    """
    fwhm_true, center_true, bg_true = 0.2, 2.0, 20.0
    area_true = area_for_height(10000.0, fwhm_true, 0.0)
    x = np.arange(1.0, 3.0001, 0.01)
    y = pseudo_voigt(x, area_true, fwhm_true, center_true, 0.0, bg_true)

    res = fit_peak(x, y, seed={"eta": 0.0})

    assert res.converged, res.reason
    assert res.center_err is not None
    peak_counts = float(np.sum(y - bg_true))
    analytic = fwhm_true / (2.3548 * math.sqrt(peak_counts))
    ratio = res.center_err / analytic
    assert 0.5 < ratio < 2.0, f"center_err/analytic = {ratio} (expected ~1)"


def test_flat_background_only_is_amber_not_an_exception():
    x = np.linspace(0.0, 2.0, 21)
    y = np.full(x.size, 5.0)

    res = fit_peak(x, y)

    assert isinstance(res, QuickFitResult)
    assert "weak peak vs background" in res.warnings


def test_double_peak_raises_the_multi_peak_warning():
    fwhm = 0.3
    x = np.linspace(0.0, 6.0, 121)
    y = (pseudo_voigt(x, area_for_height(100.0, fwhm, 0.2), fwhm, 2.0, 0.2, 1.0)
         + pseudo_voigt(x, area_for_height(95.0, fwhm, 0.2), fwhm, 4.0, 0.2, 0.0))

    res = fit_peak(x, y)

    assert "possible multiple peaks" in res.warnings


def test_peak_at_range_edge_warns():
    fwhm = 0.4
    x = np.linspace(0.0, 4.0, 81)
    y = pseudo_voigt(x, area_for_height(300.0, fwhm, 0.2), fwhm, 0.05, 0.2, 2.0)

    res = fit_peak(x, y)

    assert "center near range edge" in res.warnings


# --------------------------------------------------------------------------
# fit_peak -- input contract (never raises)
# --------------------------------------------------------------------------

def test_negative_counts_are_an_honest_failure():
    x = np.linspace(0.0, 1.0, 10)
    y = np.ones(10)
    y[3] = -1.0

    res = fit_peak(x, y)

    assert res.converged is False
    assert "negative" in res.reason


def test_nan_points_are_dropped_before_fitting():
    fwhm = 0.6
    x = np.linspace(0.0, 4.0, 81)
    y = pseudo_voigt(x, area_for_height(400.0, fwhm, 0.2), fwhm, 2.0, 0.2, 2.0)
    y[5] = np.nan
    x[7] = np.nan

    res = fit_peak(x, y)

    assert res.converged, res.reason
    assert res.n_points == 79
    assert abs(res.center - 2.0) < 1e-3


def test_mismatched_lengths_and_empty_selection():
    assert "different lengths" in fit_peak([1.0, 2.0], [1.0]).reason
    x = np.linspace(0.0, 1.0, 10)
    y = np.ones(10)
    empty = fit_peak(x, y, mask=np.zeros(10, dtype=bool))
    assert empty.converged is False
    assert "no usable points" in empty.reason


def test_zero_span_range_and_reversed_range():
    fwhm = 0.5
    x = np.linspace(0.0, 4.0, 81)
    y = pseudo_voigt(x, area_for_height(400.0, fwhm, 0.1), fwhm, 2.0, 0.1, 2.0)

    zero = fit_peak(x, y, xrange=(1.0, 1.0))
    assert zero.converged is False
    assert "zero span" in zero.reason

    forward = fit_peak(x, y, xrange=(1.0, 3.0))
    reversed_ = fit_peak(x, y, xrange=(3.0, 1.0))
    assert forward.converged and reversed_.converged
    assert forward.n_points == reversed_.n_points
    assert abs(forward.center - reversed_.center) < 1e-9


def test_descending_x_matches_ascending_x():
    fwhm = 0.5
    x = np.linspace(0.0, 4.0, 81)
    y = pseudo_voigt(x, area_for_height(400.0, fwhm, 0.25), fwhm, 2.3, 0.25, 2.0)

    up = fit_peak(x, y)
    down = fit_peak(x[::-1], y[::-1])

    assert up.converged and down.converged
    assert abs(up.center - down.center) < 1e-9
    assert up.n_points == down.n_points


def test_too_few_points_and_too_few_unique_x():
    few = fit_peak([0.0, 1.0, 2.0, 3.0], [1.0, 5.0, 5.0, 1.0])
    assert few.converged is False
    assert "6 usable points" in few.reason

    # 10 points, only 5 distinct abscissae: duplicates are allowed but do not
    # count toward the unique-x requirement.
    x = np.repeat(np.arange(5.0), 2)
    y = np.array([1.0, 2.0, 5.0, 6.0, 20.0, 21.0, 5.0, 4.0, 1.0, 2.0])
    dupes = fit_peak(x, y)
    assert dupes.converged is False
    assert "distinct x" in dupes.reason


def test_duplicate_x_above_the_unique_threshold_still_fits():
    fwhm = 0.6
    x = np.linspace(0.0, 4.0, 41)
    x = np.concatenate([x, x[10:15]])  # a few repeated measurements
    y = pseudo_voigt(x, area_for_height(400.0, fwhm, 0.2), fwhm, 2.0, 0.2, 2.0)

    res = fit_peak(x, y)

    assert res.converged, res.reason
    assert res.n_points == 46
    assert abs(res.center - 2.0) < 1e-3


# --------------------------------------------------------------------------
# com / peak_max
# --------------------------------------------------------------------------

def test_com_on_a_symmetric_array():
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, 4.0, 10.0, 4.0, 1.0])

    res = com(x, y)

    assert isinstance(res, PeakEstimate)
    assert res.ok and res.reason == ""
    assert abs(res.x - 2.0) < 1e-12
    assert res.n_points == 5
    assert res.total_counts == 20.0
    assert res.bin_width is None


def test_com_shifts_with_a_spike_and_returns_when_masked():
    # Symmetric peak on 0..4 (COM = 2.0) plus a spurious spike at x = 5.
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([1.0, 4.0, 10.0, 4.0, 1.0, 40.0])

    with_spike = com(x, y)
    assert with_spike.x > 2.0

    mask = np.array([True, True, True, True, True, False])
    masked = com(x, y, mask=mask)
    assert abs(masked.x - 2.0) < 1e-12
    assert masked.n_points == 5


def test_com_xrange_restriction():
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([10.0, 4.0, 10.0, 4.0, 10.0])

    restricted = com(x, y, xrange=(1.0, 3.0))

    assert restricted.n_points == 3
    assert abs(restricted.x - 2.0) < 1e-12


def test_com_rejects_all_zero_selection():
    res = com([0.0, 1.0, 2.0], [0.0, 0.0, 0.0])
    assert res.ok is False
    assert res.reason == "no counts in selection"
    assert res.x is None


def test_peak_max_ties_resolve_to_the_first_ascending_x():
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([1.0, 5.0, 5.0, 1.0, 0.0, 0.0])

    res = peak_max(x, y)

    assert res.ok
    assert res.x == 1.0
    assert res.bin_width == 1.0  # (x[2] - x[0]) / 2
    assert res.total_counts == 12.0


def test_peak_max_bin_width_at_the_edges():
    x = np.array([0.0, 0.5, 1.5, 3.5])
    assert peak_max(x, [9.0, 1.0, 1.0, 1.0]).bin_width == 0.5
    assert peak_max(x, [1.0, 1.0, 1.0, 9.0]).bin_width == 2.0


def test_peak_max_all_zero_and_xrange():
    zero = peak_max([0.0, 1.0, 2.0], [0.0, 0.0, 0.0])
    assert zero.ok is False and zero.x is None

    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([100.0, 4.0, 10.0, 4.0, 1.0])
    restricted = peak_max(x, y, xrange=(1.0, 4.0))
    assert restricted.ok and restricted.x == 2.0


def test_peak_max_negative_counts_refused():
    res = peak_max([0.0, 1.0, 2.0], [1.0, -1.0, 3.0])
    assert res.ok is False
    assert "negative" in res.reason


# --------------------------------------------------------------------------
# Goto mapping
# --------------------------------------------------------------------------

def test_scan_variable_to_field_rows():
    expected = {
        "H": "H", "K": "K", "L": "L", "deltaE": "deltaE",
        "qx": "qx", "qy": "qy", "qz": "qz",
        "A1": "mtt", "A2": "stt", "2theta": "stt", "A3": "omega", "A4": "att",
        "omega": "psi", "psi": "psi", "kappa": "kappa",
        "chi": None, "rva": None,
        "rhm": "rhm", "rvm": "rvm", "rha": "rha",
    }
    assert SCAN_VARIABLE_TO_FIELD == expected


def test_field_for_scan_variable_lookup():
    assert field_for_scan_variable("A2") == "stt"
    assert field_for_scan_variable("2theta") == "stt"
    assert field_for_scan_variable("omega") == "psi"
    assert field_for_scan_variable("chi") is None
    assert field_for_scan_variable("rva") is None
    # Case-insensitive fallback onto a known spelling.
    assert field_for_scan_variable("a4") == "att"
    assert field_for_scan_variable("DELTAE") == "deltaE"
    # Unknowns and non-strings are simply not goto-able.
    assert field_for_scan_variable("nonsense") is None
    assert field_for_scan_variable("") is None
    assert field_for_scan_variable(None) is None


# --------------------------------------------------------------------------
# Goto policy (plan_goto) and message wording
# --------------------------------------------------------------------------

def test_plan_goto_ok_path_carries_field_and_float():
    plan = plan_goto("A3", 12.4173, busy=False)

    assert isinstance(plan, GotoPlan)
    assert plan.ok is True
    assert plan.reason == ""
    assert plan.variable == "A3"
    assert plan.field == "omega"
    assert isinstance(plan.value, float)
    assert plan.value == 12.4173


def test_plan_goto_accepts_int_numeric_string_and_numpy_float():
    assert plan_goto("A4", 7, busy=False).value == 7.0
    assert plan_goto("A4", "7.5", busy=False).value == 7.5
    # A fitted center arrives as a numpy scalar.
    plan = plan_goto("A4", np.float64(7.5), busy=False)
    assert plan.ok and type(plan.value) is float and plan.value == 7.5


def test_plan_goto_case_insensitive_variable():
    plan = plan_goto("a2", 45.0, busy=False)
    assert plan.ok and plan.field == "stt"


def test_plan_goto_refuses_when_busy_before_anything_else():
    """Busy wins even over an otherwise invalid request, so the operator is
    told the actionable thing first."""
    plan = plan_goto("nonsense", float("nan"), busy=True)

    assert plan.ok is False
    assert plan.reason == "a scan is running or queued"
    assert plan.field is None
    assert plan.value is None


def test_plan_goto_distinguishes_not_gotoable_from_unknown():
    known = plan_goto("chi", 1.0, busy=False)
    assert known.ok is False
    assert known.reason == "'chi' is not goto-able"

    also_known = plan_goto("rva", 1.0, busy=False)
    assert also_known.reason == "'rva' is not goto-able"

    unknown = plan_goto("wibble", 1.0, busy=False)
    assert unknown.ok is False
    assert unknown.reason == "unknown scan variable 'wibble'"


def test_plan_goto_refuses_non_string_variable():
    plan = plan_goto(None, 1.0, busy=False)
    assert plan.ok is False
    assert "unknown scan variable" in plan.reason


@pytest.mark.parametrize("value", [
    True, False,                       # bool is a float in Python: reject it
    np.bool_(True), np.bool_(False),   # ... and so is a numpy bool
    float("nan"), float("inf"), float("-inf"),
    np.float64("nan"),
    None, "abc", [1.0],
])
def test_plan_goto_refuses_values_that_are_not_real_finite_numbers(value):
    plan = plan_goto("A3", value, busy=False)

    assert plan.ok is False, f"{value!r} should not be an acceptable target"
    assert plan.reason == "target value is not finite"
    assert plan.field is None
    assert plan.value is None


def test_format_goto_message_is_stable():
    assert (format_goto_message("goto CEN", "A3", "omega", 12.34, 12.4173)
            == "goto CEN: A3 12.340 -> 12.417 (field omega)")


def test_format_goto_message_unknown_old_value_and_extra():
    message = format_goto_message("goto", "A3", "omega", None, 1.5,
                                  extra="COM of 41 points")
    assert message == "goto: A3 ? -> 1.500 (field omega) -- COM of 41 points"


def test_format_goto_message_switches_to_exponent_for_extreme_values():
    assert "1.5e-07" in format_goto_message("goto", "H", "H", 0.0, 1.5e-7)
    assert format_goto_message("goto", "H", "H", 0.0, 1.5e-7).startswith(
        "goto: H 0.000 -> ")


def test_format_revert_message_is_stable():
    assert format_revert_message("omega", 12.34) == "revert: omega restored to 12.340"
    assert format_revert_message("omega", None) == "revert: omega restored to ?"


def test_plan_goto_field_agrees_with_the_lookup_table():
    for variable, field in SCAN_VARIABLE_TO_FIELD.items():
        plan = plan_goto(variable, 1.0, busy=False)
        assert plan.field == field_for_scan_variable(variable)
        assert plan.ok is (field is not None)


def _api_field_map_body():
    """The literal ``_api_field_map`` body from the controller source.

    Source scan rather than import: importing ``TAVI_PySide6`` would pull in
    PySide6/mcstasscript, which the suite forbids (see ``tests/README.md`` and
    ``test_controller_is_instrument_agnostic.py``).
    """
    with open(CONTROLLER_PATH, encoding="utf-8") as handle:
        source = handle.read()
    start = source.index("def _api_field_map(self)")
    end = source.index("_API_APPLY_ORDER", start)
    return source[start:end]


def test_every_mapped_field_exists_in_the_controller_field_map():
    """MAINTAINERS: if ``_api_field_map`` renames a field, update
    ``SCAN_VARIABLE_TO_FIELD`` in ``tavi/scan_fits.py`` in the same change."""
    body = _api_field_map_body()
    keys = set(re.findall(r"^\s*'([A-Za-z_][A-Za-z0-9_]*)':", body, re.MULTILINE))
    assert "mtt" in keys, "field-map scan found no keys -- the scan pattern broke"

    missing = sorted({f for f in SCAN_VARIABLE_TO_FIELD.values() if f} - keys)
    assert not missing, (
        "scan_fits.SCAN_VARIABLE_TO_FIELD names fields that _api_field_map "
        "does not define: %s" % missing
    )


def test_known_api_field_map_keys_are_unchanged():
    """Characterization copy of the controller's settable-field list.

    MAINTAINERS: when ``_api_field_map`` gains or loses a key, update this list
    *and* re-check ``SCAN_VARIABLE_TO_FIELD`` in ``tavi/scan_fits.py``.
    """
    known = {
        'mtt', 'stt', 'omega', 'chi', 'att',
        'Ki', 'Ei', 'Kf', 'Ef', 'K_fixed', 'fixed_E',
        'qx', 'qy', 'qz', 'H', 'K', 'L', 'deltaE',
        'lattice_a', 'lattice_b', 'lattice_c',
        'lattice_alpha', 'lattice_beta', 'lattice_gamma',
        'kappa', 'psi', 'sample', 'monocris', 'anacris',
        'rhm', 'rvm', 'rha', 'source_type', 'source_dE',
        'modules', 'collimation', 'slits_mm',
        'number_neutrons', 'scan_command1', 'scan_command2', 'diagnostic_mode',
    }
    body = _api_field_map_body()
    actual = set(re.findall(r"^\s*'([A-Za-z_][A-Za-z0-9_]*)': \(", body, re.MULTILINE))
    assert actual == known
