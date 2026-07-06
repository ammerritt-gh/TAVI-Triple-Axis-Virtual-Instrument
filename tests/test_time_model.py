"""Tests for tavi.time_model: closed-form affine fit, non-negativity clips,
the degenerate single-cluster fallback rows, weighting, and cross-machine
component scaling.
"""
import pytest

from tavi.time_model import (
    fit_affine_time_model,
    per_point_estimate,
    reference_ncount,
    scale_per_point,
    weighted_median,
)


# --------------------------------------------------------------------------
# Weighted median (moved from RuntimeTracker)
# --------------------------------------------------------------------------

def test_weighted_median_empty_is_none():
    assert weighted_median([]) is None


def test_weighted_median_picks_heavy_side():
    # Heavy weight on 5.0 pulls the median off the numeric middle.
    assert weighted_median([(1.0, 1.0), (5.0, 100.0)]) == 5.0


def test_weighted_median_zero_weight_falls_back_to_plain():
    assert weighted_median([(2.0, 0.0), (4.0, 0.0)]) == 3.0


# --------------------------------------------------------------------------
# Affine recovery
# --------------------------------------------------------------------------

def test_affine_recovery_exact():
    # per_point = 1.5 + 3e-8 * N sampled at three ncounts -> exact recovery.
    a, b = 1.5, 3e-8
    samples = [(n, a + b * n, 1.0) for n in (1e4, 1e5, 1e8)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "affine"
    assert model["overhead"] == pytest.approx(a, rel=1e-6)
    assert model["rate"] == pytest.approx(b, rel=1e-6)
    assert model["n_groups"] == 3
    assert model["ncount_min"] == 1e4
    assert model["ncount_max"] == 1e8


def test_minimal_two_group_fit_is_line_through_points():
    # Two groups, spread == 10 -> passes gate; exact line through both.
    samples = [(1e5, 1.0, 1.0), (1e6, 10.0, 1.0)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "affine"
    # slope (10-1)/(1e6-1e5) = 1e-5; intercept 0.
    assert model["rate"] == pytest.approx(1e-5, rel=1e-9)
    assert model["overhead"] == pytest.approx(0.0, abs=1e-9)
    seconds, tag = per_point_estimate(model, samples, 9e5)
    assert tag == "affine"
    assert seconds == pytest.approx(9.0, rel=1e-9)


def test_affine_prediction_matches_puma_shape():
    # The real PUMA benchmark shape: ~1.33 s overhead, ~3.2e-8 s/neutron.
    samples = [
        (1e4, 1.330, 1.0),
        (1e4, 1.330, 1.0),
        (1e5, 1.354, 1.0),
        (1e8, 4.498, 1.0),
    ]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "affine"
    s8, _ = per_point_estimate(model, samples, 1e8)
    s5, _ = per_point_estimate(model, samples, 1e5)
    s4, _ = per_point_estimate(model, samples, 1e4)
    assert s8 == pytest.approx(4.5, rel=0.15)
    assert s5 == pytest.approx(1.35, rel=0.10)
    assert s4 == pytest.approx(1.33, rel=0.10)


# --------------------------------------------------------------------------
# Non-negativity clips
# --------------------------------------------------------------------------

def test_negative_rate_clips_to_flat_overhead():
    # A decreasing trend would give b < 0; clip to b=0, a=weighted mean.
    samples = [(1e4, 5.0, 1.0), (1e6, 2.0, 1.0)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "affine"
    assert model["rate"] == 0.0
    assert model["overhead"] == pytest.approx(3.5, rel=1e-9)  # (5+2)/2


def test_negative_overhead_clips_to_pure_rate():
    # A steep line whose intercept goes negative clips to a=0, pure per-neutron.
    samples = [(1e5, 1.0, 1.0), (1e6, 100.0, 1.0)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "affine"
    assert model["overhead"] == 0.0
    assert model["rate"] > 0.0
    # a=0 fit: b = Sxy/Sxx.
    Sxy = 1e5 * 1.0 + 1e6 * 100.0
    Sxx = 1e5 ** 2 + 1e6 ** 2
    assert model["rate"] == pytest.approx(Sxy / Sxx, rel=1e-9)


# --------------------------------------------------------------------------
# Degenerate rows (single ncount cluster)
# --------------------------------------------------------------------------

def test_degenerate_no_samples():
    model = fit_affine_time_model([])
    assert model["kind"] is None
    seconds, tag = per_point_estimate(model, [], 1e6)
    assert seconds is None and tag is None


def test_degenerate_single_group_below_anchor_is_nearest():
    samples = [(1e5, 2.0, 1.0)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "degenerate"
    seconds, tag = per_point_estimate(model, samples, 5e4)  # N <= N0
    assert tag == "nearest"
    assert seconds == 2.0  # never scaled down below the observed overhead


def test_degenerate_single_group_at_anchor_is_nearest():
    samples = [(1e5, 2.0, 1.0)]
    seconds, tag = per_point_estimate(fit_affine_time_model(samples), samples, 1e5)
    assert tag == "nearest"
    assert seconds == 2.0


def test_degenerate_single_group_above_anchor_is_extrapolated():
    samples = [(1e5, 2.0, 1.0)]
    seconds, tag = per_point_estimate(fit_affine_time_model(samples), samples, 2e5)
    assert tag == "extrapolated"
    assert seconds == pytest.approx(4.0)  # 2.0 * (2e5 / 1e5)


def test_spread_below_gate_is_degenerate():
    # Two groups but spread only 5x (< SPREAD_MIN) -> no fit.
    samples = [(1e5, 1.0, 1.0), (5e5, 1.2, 1.0)]
    model = fit_affine_time_model(samples)
    assert model["kind"] == "degenerate"
    # Anchor is the higher-ncount group.
    seconds, tag = per_point_estimate(model, samples, 5e5)
    assert tag == "nearest"
    assert seconds == pytest.approx(1.2)


# --------------------------------------------------------------------------
# Weighting
# --------------------------------------------------------------------------

def test_group_weighted_median_uses_weights():
    # Same ncount, two disagreeing values; the heavier one wins the group.
    samples = [(1e5, 1.0, 1.0), (1e5, 9.0, 50.0), (1e6, 90.0, 1.0)]
    model = fit_affine_time_model(samples)
    # Group at 1e5 collapses to 9.0 (heavy), line through (1e5,9) and (1e6,90).
    s, _ = per_point_estimate(model, samples, 1e5)
    assert s == pytest.approx(9.0, rel=1e-6)


def test_reference_ncount_affine_and_degenerate():
    affine = [(1e4, 1.0, 1.0), (1e8, 4.0, 1.0)]
    assert reference_ncount(fit_affine_time_model(affine), affine) == 1e8
    single = [(1e5, 2.0, 1.0)]
    assert reference_ncount(fit_affine_time_model(single), single) == 1e5


# --------------------------------------------------------------------------
# Cross-machine component scaling
# --------------------------------------------------------------------------

def test_scale_per_point_component_wise():
    # Foreign a=2, b=1e-5 at N=1e5 -> frac_rate = 1/3. Local twice as fast on
    # both components -> both ratios 0.5 -> scaled value halved regardless.
    foreign = {"overhead": 2.0, "rate": 1e-5}
    local = {"overhead": 1.0, "rate": 0.5e-5}
    y = 4.0
    assert scale_per_point(y, 1e5, local, foreign) == pytest.approx(2.0)


def test_scale_per_point_zero_denominator_is_identity_component():
    # Foreign overhead 0 and rate 0 -> denom 0, both ratios default to 1.0.
    foreign = {"overhead": 0.0, "rate": 0.0}
    local = {"overhead": 5.0, "rate": 5.0}
    assert scale_per_point(3.0, 1e5, local, foreign) == pytest.approx(3.0)
