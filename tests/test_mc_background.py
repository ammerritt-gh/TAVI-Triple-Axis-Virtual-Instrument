"""Tests for the Monte-Carlo (McStas) additive background overlay (stage 6).

Two halves, for the same reason ``test_background_api.py`` splits: the overlay
math lives in ``tavi/background.py`` and is exercised directly here (Qt-free,
no McStas), while the ``run_simulation`` loop that consumes it is Qt-bound --
importing ``TAVI_PySide6`` needs PySide6 + mcstasscript and there is no headless
seam that runs a McStas point -- so its wiring is covered by source scans in the
style of ``test_background_api.py`` / ``test_fitting_dock.py``.
"""
import os

import numpy as np
import pytest

from tavi import background


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")

N = 1.0e8

# Flat rate used by the draw tests. Deliberately far above the preset roster
# (~2e-10) so N * rate is a mean of 500 counts: a realistic rate would draw zero
# almost every time and test nothing about the stream.
RATE = 5.0e-6
MEAN = N * RATE


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _flat(rate, enabled=True):
    return background.resolve({
        "enabled": enabled,
        "terms": [{
            "name": "instrument_flat",
            "shape": "flat",
            "origin": "instrument",
            "params": {"rate": rate},
        }],
    })


class _ExplodingFactory:
    """RNG factory that fails the test if the disabled path ever builds an RNG."""

    def __init__(self):
        self.calls = []

    def __call__(self, key):
        self.calls.append(key)
        raise AssertionError(
            "poisson_overlay constructed an RNG when it must not: key=%r" % (key,)
        )


# ==========================================================================
# poisson_overlay -- the testable overlay contract
# ==========================================================================

def test_overlay_is_reproducible_for_the_same_seed_and_index():
    resolved = _flat(RATE)
    first = background.poisson_overlay(resolved, 3.0, None, N, None, 1234, 7)
    second = background.poisson_overlay(resolved, 3.0, None, N, None, 1234, 7)
    assert first == second
    assert isinstance(first, int)


def test_overlay_differs_between_points():
    resolved = _flat(RATE)
    draws = [
        background.poisson_overlay(resolved, 3.0, None, N, None, 1234, i)
        for i in range(40)
    ]
    # A per-point stream, not one value repeated for the whole scan.
    assert len(set(draws)) > 1


def test_background_stream_is_separate_from_a_plain_seed_index_stream():
    """The overlay must never consume the numbers a (seed, i) stream would."""
    resolved = _flat(RATE)
    seed, index = 99, 3
    mean, _, _ = background.mean_counts(resolved, 0.0, None, N, None)
    plain = int(np.random.default_rng((seed, index)).poisson(mean))
    keyed = background.poisson_overlay(resolved, 0.0, None, N, None, seed, index)
    reference = int(
        np.random.default_rng(
            (seed, background.BACKGROUND_STREAM, index)
        ).poisson(mean)
    )
    assert keyed == reference
    assert keyed != plain


def test_stream_constant_is_stable():
    # Changing this value silently changes every previously drawn overlay.
    assert background.BACKGROUND_STREAM == 0x6B67


def test_disabled_profile_draws_nothing_and_builds_no_rng():
    factory = _ExplodingFactory()
    resolved = _flat(RATE, enabled=False)
    assert background.poisson_overlay(
        resolved, 1.0, None, N, None, 1, 0, rng_factory=factory
    ) == 0
    assert factory.calls == []


def test_zero_mean_draws_nothing_and_builds_no_rng():
    factory = _ExplodingFactory()
    # Enabled but with no terms at all, and enabled with an exactly-zero rate:
    # both have nothing to plant, so neither may touch the RNG.
    empty = background.resolve({"enabled": True, "preset": "none"})
    assert background.poisson_overlay(
        empty, 1.0, None, N, None, 1, 0, rng_factory=factory
    ) == 0
    zero_rate = _flat(0.0)
    assert background.poisson_overlay(
        zero_rate, 1.0, None, N, None, 1, 0, rng_factory=factory
    ) == 0
    assert factory.calls == []


def test_zero_neutrons_draws_nothing_and_builds_no_rng():
    factory = _ExplodingFactory()
    resolved = _flat(RATE)
    assert background.poisson_overlay(
        resolved, 1.0, None, 0.0, None, 1, 0, rng_factory=factory
    ) == 0
    assert factory.calls == []


def test_overlay_mean_agrees_with_the_resolved_rate():
    """Statistical agreement: many draws average to N * rate."""
    resolved = _flat(RATE)
    expected = MEAN  # 500 counts per point
    draws = np.array([
        background.poisson_overlay(resolved, 0.0, None, N, None, 4242, i)
        for i in range(2000)
    ], dtype=float)
    # Standard error of the mean of 2000 Poisson(500) draws is ~0.5 counts;
    # 5 counts is a 10-sigma band, so this is tight but not flaky.
    assert abs(draws.mean() - expected) < 5.0
    # Poisson, not a constant: the sample variance tracks the mean.
    assert 0.7 * expected < draws.var() < 1.4 * expected


def test_overlay_uses_sigma_e_for_the_elastic_line():
    """A narrower sigma_E concentrates the same integrated rate at E = 0."""
    resolved = background.resolve({"enabled": True, "preset": "strong_elastic"})
    narrow, _, _ = background.mean_counts(resolved, 0.0, 0.2, N, None)
    wide, _, _ = background.mean_counts(resolved, 0.0, 2.0, N, None)
    assert narrow > wide
    # Away from the elastic line the fallback/None path must still be finite.
    assert background.poisson_overlay(
        resolved, 8.0, None, N, None, 7, 1
    ) >= 0


def test_sample_origin_refusal_propagates_from_the_overlay():
    resolved = background.resolve({
        "enabled": True,
        "terms": [{
            "name": "sample_diffuse",
            "shape": "flat",
            "origin": "sample",
            "params": {"rate": 0.05},
        }],
    })
    with pytest.raises(background.SampleScaleUnavailable):
        background.poisson_overlay(resolved, 0.0, None, N, None, 1, 0)
    # With a scale it plants N * scale * rate.
    assert background.poisson_overlay(resolved, 0.0, None, N, 1.0e-8, 1, 0) >= 0


# ==========================================================================
# Qt-bound MC loop: source scans (see module docstring)
# ==========================================================================

def _mc_branch(source):
    """The McStas half of ``run_simulation`` (after the deterministic return)."""
    body = source.split("def run_simulation", 1)[1]
    return body.split("return self._run_scan_deterministic", 1)[1]


def test_mc_path_resolves_the_background_once_before_the_loop():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "background = _background.resolve(background_spec)" in branch
    assert "self._background_sample_scale(" in branch
    assert "'background_source') or 'config_default'" in branch
    # Resolution happens before the McStas build, not inside the point loop.
    assert branch.index("_background.resolve(background_spec)") < branch.index(
        "self.instrument.build("
    )


def test_mc_path_fails_the_job_on_an_inapplicable_background():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "sample_background_scale_unavailable" in branch
    assert "invalid background profile" in branch
    assert "_background.SampleScaleUnavailable" in branch
    assert "job.state = JobState.FAILED" in branch


def test_mc_path_freezes_a_background_seed():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "background_seed = launch_state.get('seed')" in branch
    assert "zlib.crc32" in branch
    assert "launch_state['background_seed'] = background_seed" in branch


def test_mc_path_overlays_poisson_counts_per_point():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "_background.poisson_overlay(" in branch
    assert "counts = counts + bg_counts" in branch
    # Gated on enabled, so a disabled profile is bit-identical to no background.
    assert "if background.enabled and counts is not None:" in branch
    # sigma_E only under the elastic_incoherent flag.
    assert "background_needs_sigma = background.enabled and any(" in branch
    assert "if background_needs_sigma:" in branch


def test_mc_overlay_is_applied_exactly_once_per_point():
    """No second addition site: a double overlay would silently double the truth."""
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert branch.count("_background.poisson_overlay(") == 1
    assert branch.count("counts = counts + bg_counts") == 1
    # The only mutation of `counts` in the McStas branch is the detector read
    # and this one overlay.
    assignments = [
        line.strip() for line in branch.splitlines()
        if line.strip().startswith("counts =") or line.strip().startswith("counts +=")
    ]
    assert assignments == [
        "counts = counts + bg_counts",
    ], assignments


def test_mc_overlay_work_is_entirely_inside_the_enabled_gate():
    """Disabled profile == today's numerics: no RNG, no resolution, no draw."""
    branch = _mc_branch(_read(CONTROLLER_PATH))
    lines = branch.splitlines()
    gate_index = next(
        n for n, line in enumerate(lines)
        if line.strip() == "if background.enabled and counts is not None:"
    )
    gate_indent = len(lines[gate_index]) - len(lines[gate_index].lstrip())
    # Everything the overlay does lives strictly deeper than the gate line, so a
    # disabled profile executes none of it.
    for needle in ("_background.poisson_overlay(", "sigma_e_mev", "_resolution(",
                   "counts = counts + bg_counts", "resolution_config("):
        hits = [n for n, line in enumerate(lines) if needle in line]
        assert hits, needle
        for n in hits:
            assert n > gate_index, needle
            assert len(lines[n]) - len(lines[n].lstrip()) > gate_indent, needle


def test_mc_resolution_solve_only_happens_under_the_sigma_flag():
    """sigma_E laziness: the 4x4 inversion never runs for a non-elastic profile."""
    branch = _mc_branch(_read(CONTROLLER_PATH))
    lines = branch.splitlines()
    flag_index = next(
        n for n, line in enumerate(lines) if line.strip() == "if background_needs_sigma:"
    )
    flag_indent = len(lines[flag_index]) - len(lines[flag_index].lstrip())
    for needle in ("sigma_e_mev", "_resolution(", "resolution_config("):
        hits = [n for n, line in enumerate(lines) if needle in line]
        assert hits, needle
        for n in hits:
            assert n > flag_index, needle
            assert len(lines[n]) - len(lines[n].lstrip()) > flag_indent, needle
    # ... and the term flag itself is the elastic_incoherent test.
    assert "term.shape == 'elastic_incoherent' for term in background.terms" in branch


def test_mc_path_stamps_the_shared_metadata_block():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "job.result.metadata['background'] = _background.metadata_block(" in branch
    assert "skipped_terms=background_skipped," in branch
    assert "background_seed if background.enabled else None" in branch
