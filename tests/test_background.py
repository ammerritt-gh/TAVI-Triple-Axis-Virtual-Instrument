"""Background contract: spec resolution, scaling bases, shape math, identity.

Covers ``tavi/background.py`` only -- no engine, no Qt. The rules under test are
the ones whose violation would be silent: a preset retuned without noticing, a
sample-origin term scaled off the phonon factor, a fingerprint that changes when
the same physics is delivered a different way.
"""
import json
import math

import numpy as np
import pytest

from instruments.descriptor import AnalyticCalibration
from tavi import background as bg
from tavi.background import (
    BACKGROUND_SCHEMA,
    PRESET_REGISTRY_VERSION,
    PRESETS,
    REFERENCE_ENERGY_MEV,
    BackgroundTerm,
    SampleScaleUnavailable,
    effective_fingerprint,
    mean_counts,
    metadata_block,
    profile_fingerprint,
    resolve,
)

N = 1.0e10  # a typical per-point neutron count

# ``np.trapz`` was removed in numpy 2.0 in favour of ``np.trapezoid``; keep the
# integral checks working on either.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def _frozen_form(resolved, enabled=True):
    """The frozen numeric spec that reproduces a resolved profile."""
    return {
        "enabled": enabled,
        "terms": [term.to_dict() for term in resolved.terms],
    }


# --- registry -------------------------------------------------------------

def test_every_preset_resolves_and_fingerprints_stably():
    for name in PRESETS:
        resolved = resolve({"enabled": True, "preset": name})
        assert resolved.preset == name
        assert resolved.enabled is True
        first = profile_fingerprint(resolved)
        assert len(first) == 16
        # Re-resolving the same spec must give the same identity.
        assert profile_fingerprint(resolve({"enabled": True, "preset": name})) == first


def test_preset_fingerprints_are_pinned():
    """Regression pin: a preset retune must be a deliberate, visible change.

    Bump ``PRESET_REGISTRY_VERSION`` alongside any update to these values.
    """
    assert PRESET_REGISTRY_VERSION == 1
    assert profile_fingerprint(resolve({"enabled": True, "preset": "flat_low"})) == (
        "8979ff9018e1757f"
    )
    assert profile_fingerprint(resolve({"enabled": True, "preset": "realistic"})) == (
        "90d99960a5c45aaf"
    )


def test_preset_roster_shapes_and_origins():
    by_name = {name: PRESETS[name]["terms"] for name in PRESETS}
    assert by_name["none"] == ()
    assert by_name["flat_low"][0].params["rate"] < by_name["flat_high"][0].params["rate"]
    assert any(t.shape == "linear_e" for t in by_name["sloped"])
    assert {t.shape for t in by_name["strong_elastic"]} == {
        "elastic_incoherent", "elastic_tail"
    }
    diffuse = by_name["sample_diffuse"][0]
    assert diffuse.origin == "sample"
    assert diffuse.optional is True
    assert {t.origin for t in by_name["realistic"]} == {
        "instrument", "sample_environment", "sample"
    }
    for terms in by_name.values():
        for term in terms:
            assert term.method == "analytic"
            assert set(term.params) >= set(bg._REQUIRED_PARAMS[term.shape])


def test_preset_catalog_is_json_serializable():
    catalog = bg.preset_catalog()
    assert set(catalog) == set(PRESETS)
    json.dumps(catalog, allow_nan=False)


# --- spec forms -----------------------------------------------------------

def test_frozen_form_resolves_with_no_preset_label():
    spec = {
        "enabled": True,
        "terms": [
            {"name": "floor", "shape": "flat", "origin": "instrument",
             "params": {"rate": 1e-9}},
        ],
    }
    resolved = resolve(spec)
    assert resolved.preset is None
    assert resolved.overrides_applied == {}
    assert resolved.terms[0].name == "floor"
    assert resolved.terms[0].method == "analytic"  # defaulted


def test_preset_form_and_equivalent_frozen_form_share_a_fingerprint():
    """Identity is the numerics, not the label or the delivery route."""
    from_preset = resolve({"enabled": True, "preset": "realistic"})
    from_frozen = resolve(_frozen_form(from_preset))
    assert from_frozen.preset is None
    assert profile_fingerprint(from_frozen) == profile_fingerprint(from_preset)


def test_none_spec_resolves_disabled():
    resolved = resolve(None)
    assert resolved.enabled is False
    assert resolved.preset == "none"
    assert resolved.terms == ()


def test_term_order_does_not_change_the_fingerprint():
    terms = [
        {"name": "b", "shape": "flat", "origin": "instrument", "params": {"rate": 1e-9}},
        {"name": "a", "shape": "flat", "origin": "instrument", "params": {"rate": 2e-9}},
    ]
    forward = resolve({"enabled": True, "terms": terms})
    reversed_ = resolve({"enabled": True, "terms": list(reversed(terms))})
    assert profile_fingerprint(forward) == profile_fingerprint(reversed_)


def test_enabled_flag_is_part_of_the_identity():
    on = resolve({"enabled": True, "preset": "flat_low"})
    off = resolve({"enabled": False, "preset": "flat_low"})
    assert profile_fingerprint(on) != profile_fingerprint(off)


# --- validation -----------------------------------------------------------

def test_unknown_preset_names_the_allowed_values():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "preset": "flat_medium"})
    message = str(excinfo.value)
    assert "flat_medium" in message
    for name in PRESETS:
        assert name in message


def test_unknown_override_term_names_the_allowed_terms():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "preset": "flat_low",
                 "overrides": {"instrument_flatt": {"rate": 1e-9}}})
    message = str(excinfo.value)
    assert "instrument_flatt" in message
    assert "instrument_flat" in message


def test_unknown_parameter_names_the_allowed_parameters():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "preset": "flat_low",
                 "overrides": {"instrument_flat": {"rate_per_meV": 1e-9}}})
    message = str(excinfo.value)
    assert "rate_per_meV" in message
    assert "rate" in message


def test_negative_rate_is_refused():
    with pytest.raises(ValueError, match=r">= 0"):
        resolve({"enabled": True, "preset": "flat_low",
                 "overrides": {"instrument_flat": {"rate": -1e-9}}})


def test_negative_slope_is_allowed_but_negative_intercept_is_not():
    resolve({"enabled": True, "preset": "sloped",
             "overrides": {"environment_slope": {"slope_per_meV": -1e-9}}})
    with pytest.raises(ValueError, match=r">= 0"):
        resolve({"enabled": True, "preset": "sloped",
                 "overrides": {"environment_slope": {"rate0": -1e-12}}})


def test_non_finite_parameter_is_refused():
    with pytest.raises(ValueError, match="finite"):
        resolve({"enabled": True, "preset": "flat_low",
                 "overrides": {"instrument_flat": {"rate": float("nan")}}})
    with pytest.raises(ValueError, match="finite"):
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "instrument",
             "params": {"rate": float("inf")}},
        ]})


def test_simulated_method_is_reserved_not_implemented():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "instrument",
             "method": "simulated", "params": {"rate": 1e-9}},
        ]})
    message = str(excinfo.value)
    assert "simulated" in message
    assert "analytic" in message


def test_unknown_shape_and_origin_name_allowed_values():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "quadratic_e", "origin": "instrument",
             "params": {"rate": 1e-9}},
        ]})
    for shape in bg.SHAPES:
        assert shape in str(excinfo.value)
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "cryostat",
             "params": {"rate": 1e-9}},
        ]})
    for origin in bg.ORIGINS:
        assert origin in str(excinfo.value)


def test_unknown_method_names_allowed_methods():
    with pytest.raises(ValueError) as excinfo:
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "instrument",
             "method": "handwave", "params": {"rate": 1e-9}},
        ]})
    for method in bg.METHODS:
        assert method in str(excinfo.value)


def test_missing_required_parameter_is_refused():
    with pytest.raises(ValueError, match="missing required"):
        resolve({"enabled": True, "terms": [
            {"name": "tail", "shape": "elastic_tail", "origin": "instrument",
             "params": {"rate_integrated": 1e-9}},
        ]})


def test_mixed_spec_forms_are_refused():
    with pytest.raises(ValueError, match="exactly one"):
        resolve({"enabled": True, "preset": "flat_low", "terms": []})


def test_unknown_spec_field_is_refused():
    with pytest.raises(ValueError, match="lockdown"):
        resolve({"enabled": True, "preset": "flat_low", "lockdown": True})


def test_duplicate_frozen_term_names_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "instrument",
             "params": {"rate": 1e-9}},
            {"name": "f", "shape": "flat", "origin": "instrument",
             "params": {"rate": 2e-9}},
        ]})


@pytest.mark.parametrize("optional", ["true", 1, 0, None])
def test_frozen_form_rejects_non_boolean_optional(optional):
    with pytest.raises(ValueError, match="'optional' must be a boolean"):
        resolve({"enabled": True, "terms": [
            {"name": "f", "shape": "flat", "origin": "instrument",
             "params": {"rate": 1e-9}, "optional": optional},
        ]})


@pytest.mark.parametrize("enabled", ["true", 1, 0, None])
def test_non_boolean_enabled_is_refused_in_both_forms(enabled):
    with pytest.raises(ValueError, match="'enabled' must be a boolean"):
        resolve({"enabled": enabled, "preset": "flat_low"})
    with pytest.raises(ValueError, match="'enabled' must be a boolean"):
        resolve({"enabled": enabled, "terms": []})


# --- overrides ------------------------------------------------------------

def test_override_merge_is_exact_and_echoed():
    resolved = resolve({
        "enabled": True,
        "preset": "realistic",
        "overrides": {"environment_elastic": {"rate_integrated": 5.0e-9}},
    })
    by_name = {term.name: term for term in resolved.terms}
    elastic = by_name["environment_elastic"]
    assert elastic.params["rate_integrated"] == 5.0e-9
    # Unspecified parameters keep their preset value (deep merge, not replace).
    assert elastic.params["sigma_fallback_meV"] == (
        PRESETS["realistic"]["terms"][2].params["sigma_fallback_meV"]
    )
    # Untouched terms are untouched.
    assert by_name["instrument_flat"].params == (
        PRESETS["realistic"]["terms"][0].params
    )
    assert resolved.overrides_applied == {
        "environment_elastic": {"rate_integrated": 5.0e-9}
    }


def test_overrides_do_not_mutate_the_registry():
    before = dict(PRESETS["flat_low"]["terms"][0].params)
    resolve({"enabled": True, "preset": "flat_low",
             "overrides": {"instrument_flat": {"rate": 9.9e-9}}})
    assert PRESETS["flat_low"]["terms"][0].params == before


def test_override_changes_the_fingerprint():
    base = resolve({"enabled": True, "preset": "flat_low"})
    tweaked = resolve({"enabled": True, "preset": "flat_low",
                       "overrides": {"instrument_flat": {"rate": 3.0e-10}}})
    assert profile_fingerprint(base) != profile_fingerprint(tweaked)


# --- scaling bases --------------------------------------------------------

def test_instrument_and_environment_terms_scale_with_neutrons_only():
    resolved = resolve({"enabled": True, "terms": [
        {"name": "inst", "shape": "flat", "origin": "instrument",
         "params": {"rate": 2.0e-10}},
        {"name": "env", "shape": "flat", "origin": "sample_environment",
         "params": {"rate": 3.0e-10}},
    ]})
    total, per_term, skipped = mean_counts(resolved, 5.0, 0.5, N, sample_scale=1e-8)
    assert skipped == ()
    assert per_term["inst"] == pytest.approx(N * 2.0e-10)
    assert per_term["env"] == pytest.approx(N * 3.0e-10)
    assert total == pytest.approx(N * 5.0e-10)


def test_sample_terms_scale_with_the_diffuse_background_channel():
    resolved = resolve({"enabled": True, "preset": "sample_diffuse"})
    scale = 1.0e-8
    total, per_term, skipped = mean_counts(resolved, 3.0, 0.4, N, sample_scale=scale)
    assert skipped == ()
    expected = N * scale * PRESETS["sample_diffuse"]["terms"][0].params["rate"]
    assert per_term["sample_diffuse"] == pytest.approx(expected)
    assert total == pytest.approx(expected)


def test_optional_sample_term_is_skipped_and_recorded_without_a_scale():
    resolved = resolve({"enabled": True, "preset": "realistic"})
    total, per_term, skipped = mean_counts(resolved, 2.0, 0.5, N, sample_scale=None)
    assert skipped == ("sample_diffuse",)
    assert "sample_diffuse" not in per_term
    assert total == pytest.approx(sum(per_term.values()))
    assert total > 0.0


def test_required_sample_term_without_a_scale_raises_structured_refusal():
    resolved = resolve({"enabled": True, "terms": [
        {"name": "needed", "shape": "flat", "origin": "sample",
         "params": {"rate": 0.05}},
        {"name": "floor", "shape": "flat", "origin": "instrument",
         "params": {"rate": 1e-10}},
    ]})
    with pytest.raises(SampleScaleUnavailable) as excinfo:
        mean_counts(resolved, 0.0, 0.5, N, sample_scale=None)
    assert excinfo.value.terms == ("needed",)
    assert isinstance(excinfo.value, ValueError)


def test_disabled_profile_contributes_nothing():
    resolved = resolve({"enabled": False, "preset": "realistic"})
    assert mean_counts(resolved, 1.0, 0.5, N, sample_scale=1e-8) == (0.0, {}, ())


def test_sample_calibration_channel_is_available_on_the_library_sample():
    from tavi.sample_library import default_sample_library
    by_id = {spec.id: spec for spec in default_sample_library()}
    assert by_id["Al_phonon_DFT"].analytic_calibration.diffuse_background == 1.0e-8
    assert by_id["Al_bragg"].analytic_calibration.diffuse_background is None
    # The field defaults, so pre-existing construction sites stay valid.
    assert AnalyticCalibration(phonon=1.0, elastic=1.0).diffuse_background is None


# --- shape math -----------------------------------------------------------

def test_linear_term_uses_e_ref_zero_and_clamps_at_zero():
    assert REFERENCE_ENERGY_MEV == 0.0
    term = BackgroundTerm(
        name="slope", shape="linear_e", origin="sample_environment",
        params={"rate0": 1.0e-9, "slope_per_meV": -4.0e-11},
    )
    assert bg.term_rate(term, 0.0) == pytest.approx(1.0e-9)   # value at E_ref
    assert bg.term_rate(term, 10.0) == pytest.approx(1.0e-9 - 4.0e-10)
    assert bg.term_rate(term, -10.0) == pytest.approx(1.0e-9 + 4.0e-10)
    assert bg.term_rate(term, 25.0) == pytest.approx(0.0)
    assert bg.term_rate(term, 100.0) == 0.0  # clamped, never negative


def test_elastic_incoherent_uses_the_point_sigma():
    term = BackgroundTerm(
        name="el", shape="elastic_incoherent", origin="sample_environment",
        params={"rate_integrated": 3.0e-9, "sigma_fallback_meV": 0.5},
    )
    sigma = 0.8
    for w in (0.0, 0.3, 1.5):
        expected = 3.0e-9 * math.exp(-0.5 * (w / sigma) ** 2) / (
            sigma * math.sqrt(2.0 * math.pi)
        )
        assert bg.term_rate(term, w, sigma) == pytest.approx(expected, rel=1e-12)


def test_elastic_incoherent_falls_back_when_sigma_is_unavailable():
    term = BackgroundTerm(
        name="el", shape="elastic_incoherent", origin="sample_environment",
        params={"rate_integrated": 3.0e-9, "sigma_fallback_meV": 0.5},
    )
    fallback = bg.term_rate(term, 0.0, None)
    assert fallback == pytest.approx(bg.term_rate(term, 0.0, 0.5))
    # A degenerate resolution width is treated the same as no width at all.
    assert bg.term_rate(term, 0.0, 0.0) == pytest.approx(fallback)
    assert bg.term_rate(term, 0.0, float("nan")) == pytest.approx(fallback)


def test_elastic_incoherent_rate_integrated_is_a_true_area():
    resolved = resolve({"enabled": True, "terms": [
        {"name": "el", "shape": "elastic_incoherent", "origin": "sample_environment",
         "params": {"rate_integrated": 3.0e-9, "sigma_fallback_meV": 0.5}},
    ]})
    grid = np.linspace(-20.0, 20.0, 40001)
    values = np.array([
        mean_counts(resolved, float(w), 0.6, N)[0] for w in grid
    ])
    assert _trapezoid(values, grid) == pytest.approx(N * 3.0e-9, rel=1e-6)


def test_elastic_tail_is_a_lorentzian_pinned_at_zero():
    term = BackgroundTerm(
        name="tail", shape="elastic_tail", origin="instrument",
        params={"rate_integrated": 6.0e-9, "gamma_meV": 2.0},
    )
    peak = bg.term_rate(term, 0.0)
    assert peak == pytest.approx(6.0e-9 / (math.pi * 2.0), rel=1e-12)
    # Half-maximum at E = gamma, and a slow 1/E^2 wing (not Gaussian-fast).
    assert bg.term_rate(term, 2.0) == pytest.approx(peak / 2.0, rel=1e-12)
    assert bg.term_rate(term, 20.0) == pytest.approx(
        6.0e-9 * 2.0 / (math.pi * (400.0 + 4.0)), rel=1e-12
    )
    # The tail ignores the resolution width entirely: planted truth is not convolved.
    assert bg.term_rate(term, 1.0, 0.1) == bg.term_rate(term, 1.0, 5.0)


def test_elastic_tail_rate_integrated_is_a_true_area():
    resolved = resolve({"enabled": True, "terms": [
        {"name": "tail", "shape": "elastic_tail", "origin": "instrument",
         "params": {"rate_integrated": 4.0e-9, "gamma_meV": 2.0}},
    ]})
    # Lorentzian wings are heavy; integrate wide and allow the analytic residual.
    grid = np.linspace(-4000.0, 4000.0, 400001)
    values = np.array([mean_counts(resolved, float(w), None, N)[0] for w in grid])
    assert _trapezoid(values, grid) == pytest.approx(N * 4.0e-9, rel=1e-3)


def test_flat_term_is_energy_independent():
    term = BackgroundTerm(
        name="f", shape="flat", origin="instrument", params={"rate": 2.0e-10}
    )
    assert bg.term_rate(term, -30.0) == bg.term_rate(term, 0.0) == bg.term_rate(term, 30.0)


# --- fingerprints ---------------------------------------------------------

def test_fingerprints_are_independent_of_the_delivery_source():
    resolved = resolve({"enabled": True, "preset": "strong_elastic"})
    default_block = metadata_block(resolved, source="config_default")
    override_block = metadata_block(resolve(_frozen_form(resolved)),
                                    source="per_scan_override")
    assert default_block["source"] != override_block["source"]
    assert (default_block["profile_fingerprint"]
            == override_block["profile_fingerprint"])
    assert (default_block["effective_fingerprint"]
            == override_block["effective_fingerprint"])


def test_effective_fingerprint_tracks_sample_scale_and_skips():
    resolved = resolve({"enabled": True, "preset": "realistic"})
    profile = profile_fingerprint(resolved)
    a = effective_fingerprint(resolved, 1.0e-8, ())
    b = effective_fingerprint(resolved, 2.0e-8, ())
    c = effective_fingerprint(resolved, None, ("sample_diffuse",))
    assert len({profile, a, b, c}) == 4
    # Skipped-term order must not matter.
    assert effective_fingerprint(resolved, None, ("b", "a")) == (
        effective_fingerprint(resolved, None, ("a", "b"))
    )


# --- metadata block -------------------------------------------------------

def test_metadata_block_full_contents():
    resolved = resolve({
        "enabled": True,
        "preset": "realistic",
        "overrides": {"instrument_flat": {"rate": 4.0e-10}},
    })
    block = metadata_block(
        resolved,
        source="config_default",
        sample_scale=1.0e-8,
        skipped_terms=(),
    )
    assert block["background_schema"] == BACKGROUND_SCHEMA
    assert block["preset_registry_version"] == PRESET_REGISTRY_VERSION
    assert block["enabled"] is True
    assert block["preset"] == "realistic"
    assert block["source"] == "config_default"
    assert block["overrides_applied"] == {"instrument_flat": {"rate": 4.0e-10}}
    assert block["sample_scale"] == 1.0e-8
    assert block["skipped_terms"] == []
    assert block["profile_fingerprint"] == profile_fingerprint(resolved)
    assert block["effective_fingerprint"] == effective_fingerprint(resolved, 1.0e-8, ())
    assert "background_seed" not in block
    names = [term["name"] for term in block["terms"]]
    assert names == [term.name for term in resolved.terms]
    for term in block["terms"]:
        assert set(term["units"]) == set(term["params"]) | set(
            bg.PARAMETER_UNITS[term["shape"]]
        )
    assert set(block["parameter_units"]) == set(bg.SHAPES)
    json.dumps(block, allow_nan=False)


def test_metadata_block_disabled_form_is_short_but_still_provenance():
    resolved = resolve({"enabled": False, "preset": "flat_low"})
    block = metadata_block(resolved, source="per_scan_override")
    assert set(block) == {
        "background_schema", "enabled", "preset", "source",
        "profile_fingerprint", "effective_fingerprint",
    }
    assert block["enabled"] is False
    assert block["preset"] == "flat_low"
    assert block["source"] == "per_scan_override"


def test_metadata_block_records_skips_and_seed_when_given():
    resolved = resolve({"enabled": True, "preset": "realistic"})
    _, _, skipped = mean_counts(resolved, 1.0, 0.5, N, sample_scale=None)
    block = metadata_block(
        resolved,
        source="per_scan_override",
        sample_scale=None,
        skipped_terms=skipped,
        background_seed=4242,
    )
    assert block["sample_scale"] is None
    assert block["skipped_terms"] == ["sample_diffuse"]
    assert block["background_seed"] == 4242


def test_metadata_block_does_not_alias_the_resolved_profile():
    resolved = resolve({"enabled": True, "preset": "flat_low"})
    block = metadata_block(resolved, source="config_default")
    block["terms"][0]["params"]["rate"] = 1.0
    assert resolved.terms[0].params["rate"] == 2.0e-10
