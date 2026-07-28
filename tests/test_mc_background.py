"""Tests for the McStas additive ``tavi.background/2`` overlay."""
import os

import numpy as np

from tavi import background


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")
N = 1.0e8
TARGET_RATE = 5.0e-6
TARGET_MEAN = N * TARGET_RATE
FLAT_BASE_RATE = background.SOURCES["environment_flat"].base_numerics["rate"]


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _flat(enabled=True, scale=None, source_enabled=True):
    if scale is None:
        scale = TARGET_RATE / FLAT_BASE_RATE
    return background.resolve({
        "catalog_version": background.CATALOG_VERSION,
        "enabled": enabled,
        "sources": {
            "environment_flat": {
                "enabled": source_enabled,
                "scale": scale,
            },
        },
    })


class _ExplodingFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, key):
        self.calls.append(key)
        raise AssertionError(f"unexpected RNG construction for key {key!r}")


def _context(*, q=0.0, w=0.0, sigma_q=None, sigma_e=None, neutrons=N):
    return background.BackgroundPointContext(
        q, w, sigma_q, sigma_e, neutrons
    )


def test_overlay_is_reproducible_and_point_keyed():
    resolved = _flat()
    context = _context(w=3.0)
    first = background.poisson_overlay(resolved, context, 1234, 7)
    second = background.poisson_overlay(resolved, context, 1234, 7)
    assert first == second
    assert isinstance(first, int)
    draws = [
        background.poisson_overlay(resolved, context, 1234, index)
        for index in range(40)
    ]
    assert len(set(draws)) > 1


def test_overlay_stream_is_stable_and_separate():
    resolved = _flat()
    seed, index = 99, 3
    context = _context()
    mean, _ = background.mean_counts(resolved, context)
    plain = int(np.random.default_rng((seed, index)).poisson(mean))
    keyed = background.poisson_overlay(
        resolved, context, seed, index
    )
    reference = int(np.random.default_rng(
        (seed, background.BACKGROUND_STREAM, index)
    ).poisson(mean))
    assert background.BACKGROUND_STREAM == 0x6B67
    assert keyed == reference
    assert keyed != plain


def test_disabled_global_source_zero_scale_and_zero_neutrons_build_no_rng():
    cases = [
        (_flat(enabled=False), N),
        (_flat(source_enabled=False), N),
        (_flat(scale=0.0), N),
        (_flat(), 0.0),
    ]
    for resolved, neutrons in cases:
        factory = _ExplodingFactory()
        assert background.poisson_overlay(
            resolved, _context(w=1.0, neutrons=neutrons),
            1, 0, rng_factory=factory
        ) == 0
        assert factory.calls == []


def test_overlay_mean_agrees_with_independent_source_scale():
    resolved = _flat()
    context = _context()
    draws = np.array([
        background.poisson_overlay(resolved, context, 4242, index)
        for index in range(2000)
    ], dtype=float)
    assert abs(draws.mean() - TARGET_MEAN) < 5.0
    assert 0.7 * TARGET_MEAN < draws.var() < 1.4 * TARGET_MEAN

    doubled = _flat(scale=2.0 * TARGET_RATE / FLAT_BASE_RATE)
    double_draws = np.array([
        background.poisson_overlay(doubled, context, 4242, index)
        for index in range(2000)
    ], dtype=float)
    assert abs(double_draws.mean() - 2.0 * TARGET_MEAN) < 8.0


def test_overlay_uses_sigma_e_for_sample_elastic_source():
    resolved = background.resolve({
        "catalog_version": 2,
        "enabled": True,
        "sources": {
            "sample_elastic": {"enabled": True, "scale": 1.0},
        },
    })
    narrow, _ = background.mean_counts(
        resolved, _context(sigma_e=0.2)
    )
    wide, _ = background.mean_counts(
        resolved, _context(sigma_e=2.0)
    )
    assert narrow > wide
    assert background.poisson_overlay(
        resolved, _context(w=8.0), 7, 1
    ) >= 0


def test_powder_source_has_no_hidden_sample_scale_or_refusal():
    resolved = background.resolve({
        "catalog_version": 2,
        "enabled": True,
        "sources": {
            "instrument_aluminum_powder": {"enabled": True, "scale": 2.0},
        },
    })
    center = background.source_catalog()[
        "instrument_aluminum_powder"
    ]["base_numerics"]["lines"][0]["q_inv_ang"]
    context = _context(q=center)
    mean, per_source = background.mean_counts(resolved, context)
    assert mean > 0
    assert per_source == {"instrument_aluminum_powder": mean}
    assert background.poisson_overlay(resolved, context, 1, 0) >= 0


def _mc_branch(source):
    body = source.split("def run_simulation", 1)[1]
    return body.split("return self._run_scan_deterministic", 1)[1]


def test_mc_path_resolves_v2_once_before_build_without_sample_scaling():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "background = _background.resolve(background_spec)" in branch
    assert "self._background_sample_scale(" not in branch
    assert "SampleScaleUnavailable" not in branch
    assert branch.index("_background.resolve(background_spec)") < branch.index(
        "self.instrument.build("
    )


def test_mc_path_freezes_seed_and_uses_both_overlay_streams_inside_global_gate():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "background_seed = launch_state.get('seed')" in branch
    assert "zlib.crc32" in branch
    assert "launch_state['background_seed'] = background_seed" in branch
    assert branch.count("_background.poisson_overlay(") == 1
    assert branch.count("counts = counts + bg_counts") == 1
    assert branch.count("_background.draw_event_overlay(") == 1
    assert branch.count("counts = counts + event_counts") == 1
    assert "if background.enabled and counts is not None:" in branch
    call_tail = branch.split("_background.poisson_overlay(", 1)[1].split(
        "if bg_counts:", 1
    )[0]
    assert "background_seed" in call_tail
    assert "i" in call_tail
    assert "background_scale" not in call_tail


def test_mc_resolution_solve_is_gated_for_elastic_and_powder_sources():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "'elastic_incoherent', 'powder_elastic'" in branch
    assert "background_needs_sigma_q = 'powder_elastic'" in branch
    lines = branch.splitlines()
    gate_index = next(
        index for index, line in enumerate(lines)
        if line.strip() == (
            "if background_needs_sigma_q or background_needs_sigma_e:"
        )
    )
    gate_indent = len(lines[gate_index]) - len(lines[gate_index].lstrip())
    for needle in ("marginal_sigma", "_resolution(", "resolution_config("):
        hits = [index for index, line in enumerate(lines) if needle in line]
        assert hits
        assert all(index > gate_index for index in hits)
        assert all(
            len(lines[index]) - len(lines[index].lstrip()) > gate_indent
            for index in hits
        )


def test_mc_path_stamps_shared_v2_metadata_without_legacy_fields():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "job.result.metadata['background'] = _background.metadata_block(" in branch
    assert "realized_events=realized_background_events" in branch
    assert "sample_scale=" not in branch
    assert "skipped_terms=" not in branch


def test_mc_path_derives_angle_scan_q_and_keeps_detector_only_overlay():
    source = _read(CONTROLLER_PATH)
    helper = source.split(
        "def _background_q_magnitude", 1
    )[1].split("def format_editable_number", 1)[0]
    assert "lab_q_from_stt(" in helper
    assert 'metadata["Ki"]' in helper
    assert 'metadata["Kf"]' in helper
    assert 'metadata["stt"]' in helper
    branch = _mc_branch(source)
    assert "intensity, intensity_error, counts = read_1Ddetector_file" in branch
    assert "intensity = intensity +" not in branch
