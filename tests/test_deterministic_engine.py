"""Tests for tavi.deterministic_engine (analytic S(Q,omega) (x) resolution).

mcstasscript/Qt-free: imports only tavi.deterministic_engine, tavi.resolution,
instruments.descriptor, numpy, json, pathlib, time -> joins the safe pytest set.
A real ResolutionResult is built from the validated CN goldens
(tests/data/cn_goldens.json), so the convolution kernel is a genuine PUMA matrix.
"""
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from instruments.descriptor import AnalyticCalibration, SampleSpec
from tavi.sample_library import default_sample_library
from tavi.resolution import ResolutionConfig, cooper_nathans
import tavi.deterministic_engine as de


_GOLDENS = json.loads(
    (Path(__file__).parent / "data" / "cn_goldens.json").read_text(
        encoding="utf-8"
    )
)


def _res(name="puma_pg002_kf2.662_inelastic", **over):
    v = _GOLDENS[name]
    p = v["params"]
    kw = dict(
        dm=p["DM"], da=p["DA"], eta_m=p["ETAM"], eta_a=p["ETAA"], eta_s=p.get("ETAS"),
        sm=p["SM"], ss=p["SS"], sa=p["SA"], kfix=p["KFIX"], fx=p["FX"],
        alf=(p["ALF1"], p["ALF2"], p["ALF3"], p["ALF4"]),
        bet=(p["BET1"], p["BET2"], p["BET3"], p["BET4"]),
        q0=v["q0"], w=v["w"],
    )
    kw.update(over)
    return cooper_nathans(ResolutionConfig(**kw))


def _phonon_spec():
    return next(
        sample
        for sample in default_sample_library()
        if sample.id == "Al_phonon_DFT"
    )


def _bragg_spec():
    return next(
        sample for sample in default_sample_library() if sample.id == "Al_bragg"
    )


def _phonon_sqw():
    return de.ground_truth(_phonon_spec())


ANCHOR_HKL = (2.15, 0.0, 0.0)


# --------------------------------------------------------------------------- factory
def test_ground_truth_known_ids():
    assert isinstance(de.ground_truth(_phonon_spec()), de.PhononDFTSQW)
    assert isinstance(de.ground_truth(_bragg_spec()), de.BraggSQW)
    none = SampleSpec("none", "No sample", None)
    assert isinstance(de.ground_truth(none), de.ZeroSQW)


def test_ground_truth_unknown_returns_none():
    unknown = SampleSpec("Fe_pnictide_xyz", "mystery", "Some_comp", properties={})
    assert de.ground_truth(unknown) is None


def test_ground_truth_dispatches_phonon_dft_by_component_type():
    renamed = replace(_phonon_spec(), id="renamed_al_map")
    assert isinstance(de.ground_truth(renamed), de.PhononDFTSQW)


# --------------------------------------------------------------------------- dispersion
def test_real_dispersion_map_matches_saved_anchor_values():
    sqw = _phonon_sqw()
    modes = sqw._phonon.dispersion_map.evaluate(ANCHOR_HKL, tessellate=True)
    assert modes[0].energy_mev == pytest.approx(1.3963545)
    assert modes[1].energy_mev == pytest.approx(6.4654515)
    assert modes[0].intensity == pytest.approx(1.0)
    assert modes[1].intensity == pytest.approx(1.0)


def test_phonon_dft_bragg_table_and_gamma_policy():
    sqw = _phonon_sqw()
    allowed = [
        feature
        for feature in sqw.elastic((2, 0, 0))
        if np.linalg.norm(feature.dq) < 1.0e-12
    ]
    forbidden = [
        feature
        for feature in sqw.elastic((1, 0, 0))
        if np.linalg.norm(feature.dq) < 1.0e-12
    ]
    assert len(allowed) == 1
    assert allowed[0].weight == pytest.approx(1.903296)
    assert forbidden == []

    gamma_branches = sqw.branches((2, 0, 0))
    assert len(gamma_branches) == 2
    assert sorted(branch.omega0 for branch in gamma_branches) == pytest.approx(
        [-6.0, 6.0]
    )


def test_h_scan_bragg_center_repairs_false_dip():
    sqw = _phonon_sqw()
    resolution = _res("puma_pg002_kf2.662_elastic")
    hs = (1.95, 1.99, 2.0, 2.01, 2.05)
    means = de.run_deterministic_scan(
        [((h, 0.0, 0.0), 0.0) for h in hs],
        resolution,
        sqw,
        1.0e7,
        seed=0,
        noiseless=True,
    )
    center = means[2]
    assert means.index(max(means)) == 2
    assert 4400.0 < center < 4650.0
    assert center > means[1]
    assert center > means[3]


def _three_branch_grid() -> str:
    lines = [
        "# grid_nx 2",
        "# grid_ny 2",
        "# grid_nz 2",
        "# num_branches 3",
    ]
    for h in (0.0, 1.0):
        for k in (0.0, 1.0):
            for l in (0.0, 1.0):
                for branch in range(3):
                    energy = 1.0 + branch + h + k + l
                    lines.append(
                        f"{h:g} {k:g} {l:g} {energy:g} 1 {branch} 0.2"
                    )
    return "\n".join(lines) + "\n"


def _custom_phonon_spec(dispersion: Path, reflections: Path) -> SampleSpec:
    return SampleSpec(
        "custom_map",
        "Custom map",
        "Phonon_DFT",
        properties={
            "a": 4.0,
            "T": 200.0,
            "phonon_gamma": 0.2,
            "tessellate": 1,
            "dispersion": str(dispersion),
            "reflections": str(reflections),
        },
        lattice=(4.0, 4.0, 4.0, 90.0, 90.0, 90.0),
        analytic_calibration=AnalyticCalibration(phonon=1.0, elastic=1.0),
    )


def test_third_grid_branch_produces_pair_without_engine_change(tmp_path):
    dispersion = tmp_path / "three.dat"
    dispersion.write_text(_three_branch_grid(), encoding="utf-8")
    reflections = tmp_path / "one.laz"
    reflections.write_text(
        "# column_F2 4\n2 0 0 1.0\n", encoding="utf-8"
    )
    sqw = de.ground_truth(_custom_phonon_spec(dispersion, reflections))
    branches = sqw.branches((0.5, 0.5, 0.5))
    assert len(branches) == 6
    assert sorted(branch.omega0 for branch in branches) == pytest.approx(
        [-4.5, -3.5, -2.5, 2.5, 3.5, 4.5]
    )


def test_configured_phonon_dft_assets_fail_visibly(tmp_path):
    missing_dispersion = tmp_path / "missing.dat"
    reflections = tmp_path / "one.laz"
    reflections.write_text(
        "# column_F2 4\n2 0 0 1.0\n", encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError, match="dispersion map not found"):
        de.ground_truth(_custom_phonon_spec(missing_dispersion, reflections))

    dispersion = tmp_path / "three.dat"
    dispersion.write_text(_three_branch_grid(), encoding="utf-8")
    missing_reflections = tmp_path / "missing.laz"
    with pytest.raises(FileNotFoundError, match="reflection table not found"):
        de.ground_truth(
            _custom_phonon_spec(dispersion, missing_reflections)
        )

    malformed_reflections = tmp_path / "malformed.laz"
    malformed_reflections.write_text("2 0 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable positive F2"):
        de.ground_truth(
            _custom_phonon_spec(dispersion, malformed_reflections)
        )


# --------------------------------------------------------------------------- seeding
def test_same_seed_bit_identical():
    res, sqw = _res(), _phonon_sqw()
    pts = [(( 2.15, 0, 0), w) for w in np.linspace(-3, 4, 21)]
    c1 = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=42)
    c2 = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=42)
    assert c1 == c2


def test_different_seed_differs():
    res, sqw = _res(), _phonon_sqw()
    pts = [((2.15, 0, 0), w) for w in np.linspace(-3, 4, 21)]
    c1 = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=42)
    c2 = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=43)
    assert c1 != c2


def test_per_point_stream_isolated():
    # a skipped point must not shift a later point's stream
    res, sqw = _res(), _phonon_sqw()
    pts = [((2.15, 0, 0), w) for w in np.linspace(-3, 4, 21)]
    full = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=7)
    # recompute point 10 alone with its own index-keyed stream
    rng = np.random.default_rng((7, 10))
    out = de.evaluate_point(
        res, sqw, pts[10][0], pts[10][1], 1e8, rng=rng
    )
    assert out["counts"] == full[10]


# --------------------------------------------------------------------------- noiseless
def test_noiseless_returns_means_no_rng():
    res, sqw = _res(), _phonon_sqw()
    out = de.evaluate_point(
        res, sqw, ANCHOR_HKL, 1.5, 1e8, noiseless=True
    )
    assert out["counts"] == out["mean"]
    assert out["mean"] > 0
    # noiseless scan is deterministic and float-valued (means, not ints)
    pts = [(ANCHOR_HKL, w) for w in np.linspace(-3, 4, 21)]
    means = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=0, noiseless=True)
    assert all(isinstance(m, float) for m in means)


# --------------------------------------------------------------------------- peak position
def test_deltaE_scan_peak_at_dispersion_energy():
    res, sqw = _res(), _phonon_sqw()
    ws = np.linspace(0.5, 2.5, 401)               # fine grid around the Stokes peak
    pts = [(ANCHOR_HKL, float(w)) for w in ws]
    means = de.run_deterministic_scan(pts, res, sqw, 1e8, seed=0, noiseless=True)
    peak_w = ws[int(np.argmax(means))]
    expected = 1.3963545
    assert abs(peak_w - expected) < 0.1             # resolution-limited tolerance


# --------------------------------------------------------------------------- widths
def test_observed_width_at_least_vanadium():
    res, sqw = _res(), _phonon_sqw()
    van = res.vanadium_fwhm_meV
    # observed Stokes width: fit sigma via FWHM of the noiseless lineshape
    ws = np.linspace(-1.5, 4.5, 2001)
    means = np.array(de.run_deterministic_scan(
        [(ANCHOR_HKL, float(w)) for w in ws], res, sqw, 1e8, seed=0, noiseless=True))
    # isolate the Stokes peak (w > 0.7)
    mask = ws > 0.7
    wsub, msub = ws[mask], means[mask]
    half = msub.max() / 2.0
    above = wsub[msub >= half]
    obs_fwhm = above.max() - above.min()
    assert obs_fwhm >= van * 0.98                    # observed >= vanadium (slope adds)
    # sanity: not absurdly broader than sqrt(van^2 + (slope*dq)^2) allows
    assert obs_fwhm < van + 1.0


# --------------------------------------------------------------------------- analytic vs MC
def test_analytic_vs_mc_agree():
    # Validate the analytic Voigt/projection against the 4D-ellipsoid Monte Carlo.
    res, sqw = _res(), _phonon_sqw()
    rng = np.random.default_rng(123)
    for w in (1.2, 1.4, 1.6):
        a = de._convolved_intensity(res, sqw, ANCHOR_HKL, w)
        m = de._convolved_intensity_mc(res, sqw, ANCHOR_HKL, w,
                                       rng=rng, n_samples=40000)
        assert abs(a - m) / a < 0.05, (w, a, m)


def test_mc_method_smoke():
    # the evaluate_point mc path runs and returns a positive mean near analytic
    res, sqw = _res(), _phonon_sqw()
    rng = np.random.default_rng(5)
    out = de.evaluate_point(
        res, sqw, ANCHOR_HKL, 1.4, 1e8,
        rng=rng, noiseless=True, method="mc",
    )
    a = de.evaluate_point(
        res, sqw, ANCHOR_HKL, 1.4, 1e8,
        noiseless=True, method="analytic",
    )["mean"]
    assert out["mean"] > 0 and abs(out["mean"] - a) / a < 0.2


# --------------------------------------------------------------------------- Bose
def test_bose_anti_stokes_weaker_than_stokes():
    # The integrated area ratio (widths cancel) equals n/(n+1) = exp(-omega0/kT).
    res, sqw = _res(), _phonon_sqw()
    omega0 = 1.3963545
    ws = np.linspace(-4.0, 4.0, 4001)          # symmetric window: full both peaks
    means = np.array(de.run_deterministic_scan(
        [(ANCHOR_HKL, float(w)) for w in ws], res, sqw, 1e8, seed=0, noiseless=True))
    dw = ws[1] - ws[0]
    stokes = means[(ws > 0.4) & (ws < 3.0)].sum() * dw
    anti = means[(ws > -3.0) & (ws < -0.4)].sum() * dw
    assert anti < stokes
    kt = 200.0 * de._KB_MEV_PER_K
    expected_ratio = math.exp(-omega0 / kt)
    assert abs(anti / stokes - expected_ratio) < 0.03, (anti / stokes, expected_ratio)


# --------------------------------------------------------------------------- Bragg
def test_bragg_peak_at_integer_hkl_zero_away():
    sqw = de.ground_truth(_bragg_spec())
    res = _res("puma_pg002_kf2.662_elastic")
    on = de.evaluate_point(
        res, sqw, (2, 0, 0), 0.0, 1e8, noiseless=True
    )["mean"]
    off_q = de.evaluate_point(
        res, sqw, (2.3, 0, 0), 0.0, 1e8, noiseless=True
    )["mean"]
    off_e = de.evaluate_point(
        res, sqw, (2, 0, 0), 3.0, 1e8, noiseless=True
    )["mean"]
    assert on > 0
    assert off_q < 1e-6 * on
    assert off_e < 1e-3 * on


def test_single_crystal_missing_table_stamps_legacy_fallback():
    sqw = de.ground_truth(_bragg_spec())
    metadata = sqw.analytic_metadata()
    assert metadata["reflection_mode"] == "centering_unit_f2_fallback"
    assert metadata["reflections"]["configured_filename"] == "Al.lau"
    assert metadata["reflections"]["resolved_path"] is None
    assert any(
        np.linalg.norm(feature.dq) < 1.0e-12
        for feature in sqw.elastic((2, 0, 0))
    )
    assert not any(
        np.linalg.norm(feature.dq) < 1.0e-12
        for feature in sqw.elastic((1, 0, 0))
    )


# --------------------------------------------------------------------------- calibration
def test_phonon_calibration_anchor_gives_about_61_counts():
    res, sqw = _res(), _phonon_sqw()
    conv = de.anchor_convolved_intensity(res, sqw)
    mean = (de.MCSTAS_ANCHOR["number_neutrons"]
            * sqw.calibration.phonon * conv)
    assert 40 < mean < 90   # rough calibration to the ~61-count McStas reference


# --------------------------------------------------------------------------- guards
def test_zero_negative_mean_guard():
    res = _res()
    zero = de.ground_truth(SampleSpec("none", "No sample", None))
    out = de.evaluate_point(
        res, zero, (2.15, 0, 0), 1.5, 1e8,
        rng=np.random.default_rng(0),
    )
    assert out["mean"] == 0.0 and out["counts"] == 0
    # infeasible resolution -> zero, no crash
    bad = _res(q0=99.0)   # triangle cannot close
    assert not bad.ok
    out2 = de.evaluate_point(
        bad, _phonon_sqw(), (2.15, 0, 0), 1.5, 1e8,
        rng=np.random.default_rng(0),
    )
    assert out2["mean"] == 0.0


# --------------------------------------------------------------------------- metadata
def test_engine_metadata():
    res = _res()
    md = de.engine_metadata(
        seed=99, res_result=res, method="analytic", sqw=_phonon_sqw()
    )
    assert md["engine"] == "deterministic"
    assert md["seed"] == 99
    assert md["cn_valid"] is True
    assert md["resolution_method"] == "cooper_nathans"
    assert isinstance(md["invalidations"], list)
    assert md["analytic_model"]["channels"] == ["phonon", "elastic"]
    assert md["analytic_model"]["branch_count"] == 2
    assert md["analytic_model"]["reflection_count"] > 0
    assert (
        md["analytic_model"]["zero_energy_policy"]
        == "match_phonon_dft_skip"
    )
    assert len(md["analytic_model"]["dispersion"]["sha256"]) == 64
    assert len(md["analytic_model"]["reflections"]["sha256"]) == 64


def test_engine_metadata_never_evaluated_is_not_invalid():
    # No resolution ever computed (e.g. all points infeasible): cn_valid must be
    # None ("not evaluated"), not a false claim that the config is CN-invalid.
    md = de.engine_metadata(seed=7, res_result=None, method="analytic")
    assert md["cn_valid"] is None
    assert md["invalidations"] == []
    assert md["resolution_method"] is None
    assert md["resolution_ok"] is False


# --------------------------------------------------------------------------- timing
def test_timing_smoke_21_points_under_100ms():
    res, sqw = _res(), _phonon_sqw()
    pts = [(ANCHOR_HKL, float(w)) for w in np.linspace(-3, 4, 21)]
    t0 = time.perf_counter()
    de.run_deterministic_scan(pts, res, sqw, 1e8, seed=0, noiseless=True)
    dt = time.perf_counter() - t0
    assert dt < 0.1, dt
