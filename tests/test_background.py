"""Qt-free contract tests for the catalog-v2 background module."""

import math

import numpy as np
import pytest

from tavi import background as bg


ALL_IDS = (
    "environment_flat",
    "environment_slope",
    "environment_cosmic_spikes",
    "instrument_aluminum_powder",
    "sample_elastic",
    "sample_elastic_tail",
)


def _spec(*, enabled=True, sources=None, version=2):
    return {
        "catalog_version": version,
        "enabled": enabled,
        "sources": {} if sources is None else sources,
    }


def _one(source_id, *, scale=1.0, enabled=True, global_enabled=True):
    return bg.resolve(_spec(
        enabled=global_enabled,
        sources={source_id: {"enabled": enabled, "scale": scale}},
    ))


def _context(
    *,
    q=0.0,
    w=0.0,
    sigma_q=None,
    sigma_e=None,
    neutrons=1.0e8,
):
    return bg.BackgroundPointContext(q, w, sigma_q, sigma_e, neutrons)


def test_catalog_identity_categories_shapes_and_order_are_stable():
    assert bg.BACKGROUND_SCHEMA == "tavi.background/2"
    assert bg.CATALOG_VERSION == 2
    assert bg.CATEGORIES == ("environment", "instrument", "sample")
    assert bg.MEAN_SHAPES == (
        "flat", "linear_e", "powder_elastic",
        "elastic_incoherent", "elastic_tail",
    )
    assert bg.EVENT_SHAPES == ("cosmic_spike",)
    assert bg.BACKGROUND_STREAM == 0x6B67
    assert bg.BACKGROUND_EVENT_STREAM == 0xC05C
    assert tuple(bg.SOURCES) == ALL_IDS
    assert [
        bg.SOURCES[source_id].category for source_id in ALL_IDS
    ] == [
        "environment", "environment", "environment",
        "instrument", "sample", "sample",
    ]
    assert "sample_diffuse" not in bg.SOURCES


def test_catalog_descriptions_numerics_units_and_scale_meaning():
    catalog = bg.source_catalog()
    assert catalog["environment_flat"]["base_numerics"] == {"rate": 6.0e-10}
    assert catalog["environment_slope"]["base_numerics"] == {
        "rate0": 2.4e-9,
        "slope_per_meV": -6.0e-11,
    }

    cosmic = catalog["environment_cosmic_spikes"]
    assert cosmic["label"] == "Cosmic-ray spikes"
    assert cosmic["shape"] == "cosmic_spike"
    assert cosmic["base_numerics"] == {
        "events_per_1e10_monitor": 0.005,
        "amplitude_median_counts": 1000.0,
        "amplitude_log_sigma": 0.8,
        "amplitude_cap_counts": 100000,
    }
    assert "incidence only" in cosmic["scale_meaning"]
    assert "noiseless" in cosmic["description"]

    powder = catalog["instrument_aluminum_powder"]
    assert powder["label"] == "Aluminum powder lines"
    assert powder["shape"] == "powder_elastic"
    assert powder["base_numerics"]["lattice_a_ang"] == 4.0495
    assert powder["base_numerics"]["rate_integrated_111"] == 6.25e-6
    assert powder["base_numerics"]["sigma_q_fallback_inv_ang"] == 0.03
    assert powder["base_numerics"]["sigma_e_fallback_meV"] == 0.5
    assert [line["hkl"] for line in powder["base_numerics"]["lines"]] == [
        [1, 1, 1], [2, 0, 0], [2, 2, 0],
        [3, 1, 1], [2, 2, 2], [4, 0, 0],
    ]
    assert [line["q_inv_ang"] for line in powder["base_numerics"]["lines"]] == (
        pytest.approx([
            2.6874419522,
            3.1031906691,
            4.3885743308,
            5.1460595511,
            5.3748839044,
            6.2063813381,
        ])
    )
    assert [
        line["multiplicity"] for line in powder["base_numerics"]["lines"]
    ] == [8, 6, 12, 24, 8, 6]
    assert [
        line["structure_factor_sqrt_barn"]
        for line in powder["base_numerics"]["lines"]
    ] == [1.32, 1.30, 1.22, 1.17, 1.15, 1.08]
    assert [
        line["relative_weight"] for line in powder["base_numerics"]["lines"]
    ] == pytest.approx([
        1.0,
        0.629985766355,
        0.784654901248,
        1.230862103501,
        0.379505280073,
        0.217401005289,
    ])
    assert "all six" in powder["scale_meaning"]
    assert "about 500 counts" in powder["description"]
    assert "not transferable or cross-section calibrated" in powder["description"]
    assert "j|F|²/Q" in powder["description"]
    assert "covariance" in powder["description"]

    assert catalog["sample_elastic"]["base_numerics"] == {
        "rate_integrated": 4.5e-9,
        "sigma_fallback_meV": 0.5,
    }
    assert catalog["sample_elastic_tail"]["base_numerics"] == {
        "rate_integrated": 6.0e-9,
        "gamma_meV": 2.0,
    }
    for entry in catalog.values():
        assert set(entry) == {
            "category", "label", "description", "scale_meaning", "shape",
            "base_numerics", "units",
        }
        assert set(entry["base_numerics"]) == set(entry["units"])


def test_catalog_views_are_detached_and_nested_definitions_are_immutable():
    catalog = bg.source_catalog()
    catalog["instrument_aluminum_powder"]["base_numerics"]["lines"][0][
        "q_inv_ang"
    ] = 99.0
    first = bg.SOURCES[
        "instrument_aluminum_powder"
    ].base_numerics["lines"][0]
    assert first["q_inv_ang"] == pytest.approx(2.6874419522)
    with pytest.raises(TypeError):
        first["q_inv_ang"] = 99.0


def test_new_session_defaults_only_new_sources_unchecked_at_x1():
    resolved = bg.resolve(None)
    assert resolved.catalog_version == 2
    assert resolved.enabled is False
    assert tuple(state.source_id for state in resolved.sources) == ALL_IDS
    assert all(state.scale == 1.0 for state in resolved.sources)
    assert {
        state.source_id for state in resolved.sources if state.enabled
    } == {
        "environment_flat",
        "environment_slope",
        "sample_elastic",
        "sample_elastic_tail",
    }
    assert bg.normalized_spec(resolved) == bg.default_spec()


def test_sparse_request_normalizes_omitted_sources_disabled():
    resolved = _one("instrument_aluminum_powder", scale=0.25)
    assert resolved.source("instrument_aluminum_powder").scale == 0.25
    for source_id in set(ALL_IDS) - {"instrument_aluminum_powder"}:
        assert resolved.source(source_id).enabled is False
        assert resolved.source(source_id).scale == 1.0
    assert set(bg.normalized_spec(resolved)["sources"]) == set(ALL_IDS)


@pytest.mark.parametrize("missing", ["catalog_version", "enabled", "sources"])
def test_all_canonical_top_level_fields_are_required(missing):
    spec = _spec()
    spec.pop(missing)
    with pytest.raises(ValueError, match="missing required"):
        bg.resolve(spec)


@pytest.mark.parametrize("version", [0, 1, 3, -1])
def test_catalog_version_mismatch_including_remote_v1_is_rejected(version):
    with pytest.raises(ValueError, match="version mismatch"):
        bg.resolve(_spec(version=version))


@pytest.mark.parametrize("version", [True, 2.0, "2", None])
def test_catalog_version_type_is_strict(version):
    with pytest.raises(ValueError, match="must be integer"):
        bg.resolve(_spec(version=version))


@pytest.mark.parametrize("old_field", ["preset", "overrides", "terms", "scale"])
def test_old_request_fields_are_rejected(old_field):
    spec = _spec()
    spec[old_field] = "realistic"
    with pytest.raises(ValueError, match="unknown background spec field"):
        bg.resolve(spec)


def test_unknown_fields_and_removed_diffuse_source_are_rejected():
    spec = _spec()
    spec["surprise"] = True
    with pytest.raises(ValueError, match="unknown background spec field"):
        bg.resolve(spec)
    with pytest.raises(ValueError, match="unknown background source"):
        bg.resolve(_spec(sources={
            "sample_diffuse": {"enabled": True, "scale": 1.0},
        }))
    with pytest.raises(ValueError, match="unknown field"):
        bg.resolve(_spec(sources={
            "environment_flat": {
                "enabled": True, "scale": 1.0, "rate": 2.0,
            },
        }))


@pytest.mark.parametrize("scale", [-1.0, math.inf, -math.inf, math.nan])
def test_scale_must_be_finite_and_non_negative(scale):
    with pytest.raises(ValueError, match="'scale'"):
        _one("environment_flat", scale=scale)


@pytest.mark.parametrize("scale", [True, False, "1", None])
def test_scale_rejects_non_numeric_values_and_booleans(scale):
    with pytest.raises(ValueError, match="must be a number"):
        _one("environment_flat", scale=scale)


def test_point_context_validates_physics_and_exposure():
    with pytest.raises(ValueError, match=r"\|Q\|"):
        _context(q=-1.0)
    with pytest.raises(ValueError, match="energy transfer"):
        _context(w=math.nan)
    with pytest.raises(ValueError, match="monitor counts"):
        _context(neutrons=math.inf)
    context = _context(sigma_q=math.nan, sigma_e=-1.0)
    assert math.isnan(context.sigma_q_inv_ang)
    assert context.sigma_e_meV == -1.0


def test_flat_slope_elastic_and_tail_shapes_use_context():
    assert bg.source_rate(
        bg.SOURCES["environment_flat"], _context(w=-100)
    ) == 6.0e-10
    slope = bg.SOURCES["environment_slope"]
    assert bg.source_rate(slope, _context(w=20)) == pytest.approx(1.2e-9)
    assert bg.source_rate(slope, _context(w=41)) == 0.0
    assert bg.term_rate(slope, _context(w=20)) == bg.source_rate(
        slope, _context(w=20)
    )

    elastic = bg.SOURCES["sample_elastic"]
    narrow = bg.source_rate(elastic, _context(sigma_e=0.25))
    fallback = bg.source_rate(elastic, _context(sigma_e=None))
    invalid = bg.source_rate(elastic, _context(sigma_e=math.nan))
    assert narrow == pytest.approx(
        4.5e-9 / (0.25 * math.sqrt(2.0 * math.pi))
    )
    assert fallback == pytest.approx(
        4.5e-9 / (0.5 * math.sqrt(2.0 * math.pi))
    )
    assert invalid == fallback

    tail = bg.SOURCES["sample_elastic_tail"]
    assert bg.source_rate(tail, _context(w=2.0)) == pytest.approx(
        6.0e-9 * 2.0 / (math.pi * 8.0)
    )


def test_powder_lines_peak_at_catalog_centers_and_are_symmetric_in_q():
    powder = bg.SOURCES["instrument_aluminum_powder"]
    center = powder.base_numerics["lines"][1]["q_inv_ang"]
    at_center = bg.source_rate(
        powder, _context(q=center, w=0, sigma_q=0.01, sigma_e=0.25)
    )
    left = bg.source_rate(
        powder, _context(q=center - 0.02, w=0, sigma_q=0.01, sigma_e=0.25)
    )
    right = bg.source_rate(
        powder, _context(q=center + 0.02, w=0, sigma_q=0.01, sigma_e=0.25)
    )
    assert at_center > left
    assert left == pytest.approx(right)
    expected = (
        6.25e-6
        * powder.base_numerics["lines"][1]["relative_weight"]
        / (0.25 * math.sqrt(2.0 * math.pi))
    )
    assert at_center == pytest.approx(expected)


def test_powder_al111_reference_visibility_is_pinned():
    powder = bg.SOURCES["instrument_aluminum_powder"]
    center = float(powder.base_numerics["lines"][0]["q_inv_ang"])
    resolved = _one("instrument_aluminum_powder")
    mean, per_source = bg.mean_counts(
        resolved,
        _context(
            q=center,
            w=0.0,
            sigma_q=0.03,
            sigma_e=0.5,
            neutrons=1.0e8,
        ),
    )
    assert mean == pytest.approx(498.6778505018)
    assert per_source == {"instrument_aluminum_powder": mean}


def test_powder_sums_overlapping_lines_and_uses_both_fallback_widths():
    powder = bg.SOURCES["instrument_aluminum_powder"]
    lines = powder.base_numerics["lines"]
    midpoint = (
        float(lines[3]["q_inv_ang"]) + float(lines[4]["q_inv_ang"])
    ) / 2.0
    broad = bg.source_rate(
        powder, _context(q=midpoint, sigma_q=0.5, sigma_e=0.5)
    )
    expected = (
        6.25e-6
        * sum(
            float(line["relative_weight"])
            * math.exp(
                -0.5
                * ((midpoint - float(line["q_inv_ang"])) / 0.5) ** 2
            )
            for line in lines
        )
        / (0.5 * math.sqrt(2.0 * math.pi))
    )
    assert broad == pytest.approx(expected)

    center = float(lines[0]["q_inv_ang"])
    fallback = bg.source_rate(
        powder, _context(
            q=center, sigma_q=math.nan, sigma_e=-1.0
        )
    )
    explicit = bg.source_rate(
        powder, _context(q=center, sigma_q=0.03, sigma_e=0.5)
    )
    assert fallback == explicit


def test_event_source_has_no_smooth_mean():
    resolved = _one("environment_cosmic_spikes")
    assert bg.mean_counts(resolved, _context(neutrons=1.0e12)) == (0.0, {})
    with pytest.raises(ValueError, match="no smooth mean rate"):
        bg.source_rate(
            bg.SOURCES["environment_cosmic_spikes"], _context()
        )


def test_mean_sources_scale_independently_and_global_off_is_empty():
    resolved = bg.resolve(_spec(sources={
        "environment_flat": {"enabled": True, "scale": 2.0},
        "sample_elastic_tail": {"enabled": True, "scale": 0.5},
        "environment_cosmic_spikes": {"enabled": True, "scale": 10.0},
    }))
    context = _context(w=2.0, neutrons=1.0e8)
    total, per_source = bg.mean_counts(resolved, context)
    assert set(per_source) == {"environment_flat", "sample_elastic_tail"}
    assert per_source["environment_flat"] == pytest.approx(0.12)
    assert total == pytest.approx(sum(per_source.values()))
    assert bg.mean_counts(
        _one("environment_flat", global_enabled=False), context
    ) == (0.0, {})


def test_cosmic_event_rng_key_incidence_amplitudes_rounding_and_cap():
    resolved = _one("environment_cosmic_spikes", scale=2.0)
    seen = {}

    class FakeRng:
        def poisson(self, expected):
            seen["expected"] = expected
            return 3

        def lognormal(self, *, mean, sigma, size):
            seen["lognormal"] = (mean, sigma, size)
            return np.array([0.2, 1000.4, 200000.0])

    def factory(key):
        seen["key"] = key
        return FakeRng()

    added, records = bg.draw_event_overlay(
        resolved,
        _context(neutrons=1.0e10),
        seed=17,
        index=47,
        rng_factory=factory,
    )
    assert seen["expected"] == pytest.approx(0.01)
    assert seen["key"] == (
        17,
        bg.BACKGROUND_EVENT_STREAM,
        47,
        bg.stable_source_key("environment_cosmic_spikes"),
    )
    assert seen["lognormal"] == (math.log(1000.0), 0.8, 3)
    assert added == 1 + 1000 + 100000
    assert records == [{
        "point_index": 47,
        "source_id": "environment_cosmic_spikes",
        "event_count": 3,
        "added_counts": added,
    }]


def test_cosmic_is_seeded_per_point_and_scale_changes_incidence_only():
    source = _one("environment_cosmic_spikes", scale=1.0)
    doubled = _one("environment_cosmic_spikes", scale=2.0)
    context = _context(neutrons=1.0e14)
    first = bg.draw_event_overlay(source, context, 1234, 7)
    second = bg.draw_event_overlay(source, context, 1234, 7)
    other_point = bg.draw_event_overlay(source, context, 1234, 8)
    assert first == second
    assert first != other_point

    class CaptureRng:
        def __init__(self, expected_values):
            self.expected_values = expected_values

        def poisson(self, expected):
            self.expected_values.append(expected)
            return 0

    expected_values = []
    factory = lambda key: CaptureRng(expected_values)
    bg.draw_event_overlay(source, context, 1, 0, rng_factory=factory)
    bg.draw_event_overlay(doubled, context, 1, 0, rng_factory=factory)
    assert expected_values[1] == pytest.approx(2.0 * expected_values[0])


@pytest.mark.parametrize(
    "resolved, context",
    [
        (_one("environment_cosmic_spikes", global_enabled=False), _context()),
        (_one("environment_cosmic_spikes", enabled=False), _context()),
        (_one("environment_cosmic_spikes", scale=0.0), _context()),
        (_one("environment_cosmic_spikes"), _context(neutrons=0.0)),
    ],
)
def test_disabled_zero_scale_and_zero_exposure_events_construct_no_rng(
    resolved, context
):
    def forbidden_rng(key):
        raise AssertionError("inactive event source must not construct an RNG")

    assert bg.draw_event_overlay(
        resolved, context, 1, 0, rng_factory=forbidden_rng
    ) == (0, [])


def test_smooth_poisson_overlay_is_seeded_and_skips_rng_when_empty():
    resolved = _one("environment_flat")
    context = _context(neutrons=1.0e10)
    assert bg.poisson_overlay(resolved, context, 1234, 7) == (
        bg.poisson_overlay(resolved, context, 1234, 7)
    )

    def forbidden_rng(key):
        raise AssertionError("empty smooth mean must not construct an RNG")

    assert bg.poisson_overlay(
        _one("environment_cosmic_spikes"),
        context,
        1,
        0,
        rng_factory=forbidden_rng,
    ) == 0


def test_fingerprints_include_definitions_and_scales_but_not_events_or_seed():
    resolved = _one("environment_cosmic_spikes", scale=0.5)
    changed = _one("environment_cosmic_spikes", scale=1.5)
    assert bg.profile_fingerprint(resolved) != bg.profile_fingerprint(changed)
    assert bg.effective_fingerprint(resolved) != bg.effective_fingerprint(changed)

    events = [{
        "point_index": 47,
        "source_id": "environment_cosmic_spikes",
        "event_count": 1,
        "added_counts": 1437,
    }]
    plain = bg.metadata_block(resolved, "config_default")
    planted = bg.metadata_block(
        resolved,
        "config_default",
        background_seed=9,
        realized_events=events,
    )
    assert plain["profile_fingerprint"] == planted["profile_fingerprint"]
    assert plain["effective_fingerprint"] == planted["effective_fingerprint"]
    assert planted["realized_events"] == events


def test_effective_fingerprint_only_includes_active_sources():
    globally_off_a = _one(
        "environment_flat", scale=1.0, global_enabled=False
    )
    globally_off_b = _one(
        "instrument_aluminum_powder", scale=99.0, global_enabled=False
    )
    all_disabled = _one(
        "environment_flat", enabled=False, global_enabled=True
    )
    zero_scale = _one(
        "environment_flat", scale=0.0, global_enabled=True
    )
    assert bg.effective_fingerprint(globally_off_a) == (
        bg.effective_fingerprint(globally_off_b)
    )
    assert bg.effective_fingerprint(globally_off_a) == (
        bg.effective_fingerprint(all_disabled)
    )
    assert bg.effective_fingerprint(globally_off_a) == (
        bg.effective_fingerprint(zero_scale)
    )


def test_metadata_is_complete_and_sparse_event_records_drop_zeroes():
    resolved = _one("instrument_aluminum_powder", scale=0.5)
    block = bg.metadata_block(
        resolved,
        "per_scan_override",
        background_seed=4242,
        realized_events=[
            {
                "point_index": 1,
                "source_id": "environment_cosmic_spikes",
                "event_count": 0,
                "added_counts": 0,
            },
        ],
    )
    assert block["background_schema"] == "tavi.background/2"
    assert block["catalog_version"] == 2
    assert block["background_seed"] == 4242
    assert "realized_events" not in block
    assert set(block["sources"]) == set(ALL_IDS)
    assert block["sources"]["instrument_aluminum_powder"]["scale"] == 0.5
    assert block["sources"]["instrument_aluminum_powder"]["shape"] == (
        "powder_elastic"
    )
    assert set(block).isdisjoint({
        "preset", "overrides_applied", "sample_scale", "skipped_terms",
        "scale", "source", "terms", "preset_registry_version",
    })
