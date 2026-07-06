"""Tests for tavi.deterministic_engine (analytic S(Q,omega) (x) resolution).

mcstasscript/Qt-free: imports only tavi.deterministic_engine, tavi.resolution,
instruments.descriptor, numpy, json, pathlib, time -> joins the safe pytest set.
A real ResolutionResult is built from the validated CN goldens
(tests/data/cn_goldens.json), so the convolution kernel is a genuine PUMA matrix.
"""
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

from instruments.descriptor import SampleSpec
from tavi.resolution import ResolutionConfig, cooper_nathans
import tavi.deterministic_engine as de


_GOLDENS = json.loads((Path(__file__).parent / "data" / "cn_goldens.json").read_text())


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
    return SampleSpec(
        "Al_phonon_DFT", "Al: Phonon DFT", "Phonon_DFT",
        properties={"a": 4.03893, "T": 200.0, "phonon_gamma": 0.2},
        lattice=(4.03893, 4.03893, 4.03893, 90.0, 90.0, 90.0),
    )


def _phonon_sqw():
    return de.ground_truth(_phonon_spec())


ANCHOR_HKL = (2.15, 0.0, 0.0)


# --------------------------------------------------------------------------- factory
def test_ground_truth_known_ids():
    assert isinstance(de.ground_truth(_phonon_spec()), de.PhononSQW)
    bragg = SampleSpec("Al_bragg", "AL: Bragg", "Single_crystal",
                       properties={"mosaic": 5}, lattice=(4.05,) * 3 + (90.0,) * 3)
    assert isinstance(de.ground_truth(bragg), de.BraggSQW)
    none = SampleSpec("none", "No sample", None)
    assert isinstance(de.ground_truth(none), de.ZeroSQW)


def test_ground_truth_unknown_returns_none():
    unknown = SampleSpec("Fe_pnictide_xyz", "mystery", "Some_comp", properties={})
    assert de.ground_truth(unknown) is None


# --------------------------------------------------------------------------- dispersion
def test_dispersion_matches_analytic_form_at_anchor():
    # q=0.15 acoustic: E = 6*sin(pi*0.15/2) = 1.4004 meV (CLOSED_LOOP §7).
    sqw = _phonon_sqw()
    e_ac = sqw._omega_branch(ANCHOR_HKL, 0)
    assert abs(e_ac - 6.0 * math.sin(math.pi * 0.15 / 2)) < 1e-9
    assert abs(e_ac - 1.4004) < 1e-3
    e_op = sqw._omega_branch(ANCHOR_HKL, 1)
    assert abs(e_op - (6.0 + 2.0 * math.sin(math.pi * 0.15 / 2))) < 1e-9


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
    out = de.evaluate_point(res, sqw, pts[10][0], pts[10][1], 1e8,
                            de.BRIGHTNESS["Al_phonon_DFT"], rng=rng)
    assert out["counts"] == full[10]


# --------------------------------------------------------------------------- noiseless
def test_noiseless_returns_means_no_rng():
    res, sqw = _res(), _phonon_sqw()
    out = de.evaluate_point(res, sqw, ANCHOR_HKL, 1.5, 1e8,
                            de.BRIGHTNESS["Al_phonon_DFT"], noiseless=True)
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
    expected = 6.0 * math.sin(math.pi * 0.15 / 2)   # 1.4004 meV
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
    bright = de.BRIGHTNESS["Al_phonon_DFT"]
    rng = np.random.default_rng(5)
    out = de.evaluate_point(res, sqw, ANCHOR_HKL, 1.4, 1e8, bright,
                            rng=rng, noiseless=True, method="mc")
    a = de.evaluate_point(res, sqw, ANCHOR_HKL, 1.4, 1e8, bright,
                          noiseless=True, method="analytic")["mean"]
    assert out["mean"] > 0 and abs(out["mean"] - a) / a < 0.2


# --------------------------------------------------------------------------- Bose
def test_bose_anti_stokes_weaker_than_stokes():
    # The integrated area ratio (widths cancel) equals n/(n+1) = exp(-omega0/kT).
    res, sqw = _res(), _phonon_sqw()
    omega0 = 6.0 * math.sin(math.pi * 0.15 / 2)
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
    bragg_spec = SampleSpec("Al_bragg", "AL: Bragg", "Single_crystal",
                            properties={"mosaic": 5},
                            lattice=(4.05,) * 3 + (90.0,) * 3)
    sqw = de.ground_truth(bragg_spec)
    res = _res("puma_pg002_kf2.662_elastic")
    bright = de.BRIGHTNESS["Al_bragg"]
    on = de.evaluate_point(res, sqw, (2, 0, 0), 0.0, 1e8, bright, noiseless=True)["mean"]
    off_q = de.evaluate_point(res, sqw, (2.3, 0, 0), 0.0, 1e8, bright, noiseless=True)["mean"]
    off_e = de.evaluate_point(res, sqw, (2, 0, 0), 3.0, 1e8, bright, noiseless=True)["mean"]
    assert on > 0
    assert off_q < 1e-6 * on
    assert off_e < 1e-3 * on


# --------------------------------------------------------------------------- calibration
def test_brightness_anchor_gives_about_61_counts():
    res, sqw = _res(), _phonon_sqw()
    conv = de.anchor_convolved_intensity(res, sqw)
    mean = (de.MCSTAS_ANCHOR["number_neutrons"]
            * de.BRIGHTNESS["Al_phonon_DFT"] * conv)
    assert 40 < mean < 90   # rough calibration to the ~61-count McStas reference


# --------------------------------------------------------------------------- guards
def test_zero_negative_mean_guard():
    res = _res()
    zero = de.ground_truth(SampleSpec("none", "No sample", None))
    out = de.evaluate_point(res, zero, (2.15, 0, 0), 1.5, 1e8, 0.0,
                            rng=np.random.default_rng(0))
    assert out["mean"] == 0.0 and out["counts"] == 0
    # infeasible resolution -> zero, no crash
    bad = _res(q0=99.0)   # triangle cannot close
    assert not bad.ok
    out2 = de.evaluate_point(bad, _phonon_sqw(), (2.15, 0, 0), 1.5, 1e8, 1e-7,
                             rng=np.random.default_rng(0))
    assert out2["mean"] == 0.0


# --------------------------------------------------------------------------- metadata
def test_engine_metadata():
    res = _res()
    md = de.engine_metadata(seed=99, res_result=res, method="analytic")
    assert md["engine"] == "deterministic"
    assert md["seed"] == 99
    assert md["cn_valid"] is True
    assert md["resolution_method"] == "cooper_nathans"
    assert isinstance(md["invalidations"], list)


# --------------------------------------------------------------------------- timing
def test_timing_smoke_21_points_under_100ms():
    res, sqw = _res(), _phonon_sqw()
    pts = [(ANCHOR_HKL, float(w)) for w in np.linspace(-3, 4, 21)]
    t0 = time.perf_counter()
    de.run_deterministic_scan(pts, res, sqw, 1e8, seed=0, noiseless=True)
    dt = time.perf_counter() - t0
    assert dt < 0.1, dt
