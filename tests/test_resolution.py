"""Tests for tavi.resolution (Cooper-Nathans + Popovici).

mcstasscript/Qt-free: imports only tavi.resolution, numpy, json, pathlib -> joins
the safe pytest set. CN goldens were generated from ISAR's validated
cn_resolution_matrix (tests/data/cn_goldens.json).
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from tavi.resolution import (
    ResolutionConfig,
    cooper_nathans,
    popovici,
    resolution,
    projected_fwhm,
    elastic_energy_fwhm,
)

_GOLDENS = json.loads((Path(__file__).parent / "data" / "cn_goldens.json").read_text())
_CASES = {k: v for k, v in _GOLDENS.items() if isinstance(v, dict)}


def _cfg_from_golden(v, **over):
    p = v["params"]
    kw = dict(
        dm=p["DM"], da=p["DA"], eta_m=p["ETAM"], eta_a=p["ETAA"], eta_s=p.get("ETAS"),
        sm=p["SM"], ss=p["SS"], sa=p["SA"], kfix=p["KFIX"], fx=p["FX"],
        alf=(p["ALF1"], p["ALF2"], p["ALF3"], p["ALF4"]),
        bet=(p["BET1"], p["BET2"], p["BET3"], p["BET4"]),
        q0=v["q0"], w=v["w"],
    )
    kw.update(over)
    return ResolutionConfig(**kw)


def _flat_popovici_cfg(base_cfg, scale):
    """Large-dimension, flat-curvature Popovici config built from a CN config."""
    d = scale
    return ResolutionConfig(
        dm=base_cfg.dm, da=base_cfg.da, eta_m=base_cfg.eta_m, eta_a=base_cfg.eta_a,
        eta_s=base_cfg.eta_s, sm=base_cfg.sm, ss=base_cfg.ss, sa=base_cfg.sa,
        kfix=base_cfg.kfix, fx=base_cfg.fx, alf=base_cfg.alf, bet=base_cfg.bet,
        q0=base_cfg.q0, w=base_cfg.w,
        arms=(200.0, 200.0, 150.0, 100.0, 200.0),
        source_width=6 * d, source_height=12 * d,
        mono_width=20 * d, mono_height=20 * d, mono_depth=0.2 * d,
        sample_width=1 * d, sample_height=1 * d, sample_depth=1 * d,
        ana_width=20 * d, ana_height=20 * d, ana_depth=0.2 * d,
        det_width=2.5 * d, det_height=10 * d,
    )


# --------------------------------------------------------------------------- CN goldens
@pytest.mark.parametrize("name", list(_CASES))
def test_cn_matrix_matches_isar_golden(name):
    v = _CASES[name]
    res = cooper_nathans(_cfg_from_golden(v))
    assert res.ok and res.method == "cooper_nathans"
    assert res.r0 is None  # CN drops the prefactor (ISAR port)
    M = np.array(res.matrix)
    Mg = np.array(v["matrix"])
    denom = np.abs(Mg)
    mask = denom > 1e-6
    assert np.all(np.abs(M[mask] - Mg[mask]) / denom[mask] <= 1e-9)
    # near-zero golden entries must also be near-zero
    assert np.all(np.abs(M[~mask]) <= 1e-6)


@pytest.mark.parametrize("name", list(_CASES))
def test_cn_vanadium_matches_isar_golden(name):
    v = _CASES[name]
    res = cooper_nathans(_cfg_from_golden(v))
    assert abs(res.vanadium_fwhm_meV - v["vanadium_fwhm_meV"]) \
        <= 1e-9 * v["vanadium_fwhm_meV"]


# --------------------------------------------------------------------------- refusals
def test_infeasible_triangle_returns_refusal_not_exception():
    assert _GOLDENS["_infeasible_q8_returns_none"] is True
    v = _CASES["puma_pg002_kf2.662_elastic"]
    res = cooper_nathans(_cfg_from_golden(v, q0=8.0))
    assert res.ok is False
    assert res.matrix is None and res.vanadium_fwhm_meV is None
    assert res.reason and "triangle" in res.reason.lower()


def test_infeasible_via_dispatcher_and_popovici():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    cfg = _cfg_from_golden(v, q0=8.0)
    assert resolution(cfg, method="cooper_nathans").ok is False
    # give it spatial params so popovici path is exercised, still refuses
    cfg_p = _flat_popovici_cfg(cfg, 10)
    assert popovici(cfg_p).ok is False


# --------------------------------------------------------------------------- eta_s reuse
@pytest.mark.parametrize("bad_eta_s", [None, 0.0, -5.0])
def test_eta_s_nonpositive_reuses_eta_m(bad_eta_s):
    v = _CASES["puma_pg002_kf2.662_elastic"]
    r_reuse = cooper_nathans(_cfg_from_golden(v, eta_s=bad_eta_s))
    r_explicit = cooper_nathans(_cfg_from_golden(v, eta_s=v["params"]["ETAM"]))
    assert r_reuse.matrix == r_explicit.matrix
    assert r_reuse.vanadium_fwhm_meV == r_explicit.vanadium_fwhm_meV


# --------------------------------------------------------------------------- helpers
def test_projected_fwhm_along_energy_axis_equals_vanadium():
    v = _CASES["puma_pg002_kf2.662_inelastic"]
    res = cooper_nathans(_cfg_from_golden(v))
    p = projected_fwhm(res.matrix, [0.0, 0.0, 0.0, 1.0])
    assert p == pytest.approx(res.fwhm["dE"], rel=1e-12)
    assert p == pytest.approx(res.vanadium_fwhm_meV, rel=1e-12)


def test_elastic_energy_fwhm_matches_cn_at_w0():
    v = _CASES["puma_pg002_kf2.662_inelastic"]
    cfg = _cfg_from_golden(v)  # w = 1.5
    ev = elastic_energy_fwhm(cfg)
    res0 = cooper_nathans(ResolutionConfig(**{**cfg.__dict__, "w": 0.0}))
    assert ev == pytest.approx(res0.vanadium_fwhm_meV, rel=1e-12)


def test_elastic_energy_fwhm_fallback_on_infeasible():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    cfg = _cfg_from_golden(v, q0=8.0)
    assert elastic_energy_fwhm(cfg, fallback=0.6) == 0.6


# --------------------------------------------------------------------------- matrix properties
@pytest.mark.parametrize("name", list(_CASES))
def test_matrix_symmetric_positive_definite(name):
    res = cooper_nathans(_cfg_from_golden(_CASES[name]))
    M = np.array(res.matrix)
    assert np.allclose(M, M.T, atol=1e-6 * np.max(np.abs(M)))
    assert np.all(np.linalg.eigvalsh(M) > 0)
    assert all(f > 0 for f in res.principal_axes["fwhm"])
    for ax in ("dE", "dq_par", "dq_perp", "dq_z"):
        assert res.fwhm[ax] > 0 and res.bragg[ax] > 0


# --------------------------------------------------------------------------- Popovici flat limit
def test_popovici_flat_limit_approaches_cn():
    """With flat curvatures and growing component dimensions, Popovici FWHMs
    converge to Cooper-Nathans. In-plane axes converge to <1%; the vertical
    Q_z retains a ~2-3% offset because the vertical sample-mosaic term is
    modeled by Popovici but not by the ISAR CN kernel."""
    v = _CASES["puma_pg002_kf2.662_elastic"]
    cn = cooper_nathans(_cfg_from_golden(v))
    inplane = ("dE", "dq_par", "dq_perp")

    # (a) monotone approach: max in-plane rel error shrinks as dimensions grow
    prev = None
    for scale in (1, 3, 10, 30):
        r = popovici(_flat_popovici_cfg(cn_cfg := _cfg_from_golden(v), scale))
        assert r.ok
        err = max(abs(r.fwhm[k] - cn.fwhm[k]) / cn.fwhm[k] for k in inplane)
        if prev is not None:
            assert err < prev
        prev = err

    # (b) large-dimension agreement
    r = popovici(_flat_popovici_cfg(_cfg_from_golden(v), 100))
    assert r.ok
    for k in inplane:
        assert abs(r.fwhm[k] - cn.fwhm[k]) / cn.fwhm[k] < 0.01
    assert abs(r.fwhm["dq_z"] - cn.fwhm["dq_z"]) / cn.fwhm["dq_z"] < 0.05


# --------------------------------------------------------------------------- Popovici sanity
def test_popovici_curvature_changes_matrix_and_is_pos_def():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    flat_cfg = _flat_popovici_cfg(_cfg_from_golden(v), 1)
    curv_cfg = ResolutionConfig(**{**flat_cfg.__dict__, "rhm": 2.0})  # 2 m focusing
    flat = popovici(flat_cfg)
    curv = popovici(curv_cfg)
    assert flat.ok and curv.ok
    assert not np.allclose(np.array(flat.matrix), np.array(curv.matrix))
    assert np.all(np.linalg.eigvalsh(np.array(curv.matrix)) > 0)
    assert curv.r0 is not None and curv.r0 > 0
    assert flat.r0 is not None and flat.r0 > 0


def test_popovici_records_default_provenance_and_warning():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    # spatial present (arms) but dimensions omitted -> defaults recorded
    cfg = ResolutionConfig(**{**_cfg_from_golden(v).__dict__,
                              "arms": (200.0, 200.0, 150.0, 100.0, 200.0)})
    r = popovici(cfg)
    assert r.ok
    assert "popovici_defaults_applied" in r.provenance
    assert any("defaulted" in w for w in r.warnings)


# --------------------------------------------------------------------------- dispatcher
def test_dispatcher_auto_selects_method():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    cn_cfg = _cfg_from_golden(v)
    assert resolution(cn_cfg, method="auto").method == "cooper_nathans"
    pop_cfg = _flat_popovici_cfg(cn_cfg, 10)
    assert resolution(pop_cfg, method="auto").method == "popovici"
    assert resolution(pop_cfg, method="cooper_nathans").method == "cooper_nathans"
    assert resolution(cn_cfg, method="popovici").method == "popovici"


def test_dispatcher_rejects_unknown_method():
    with pytest.raises(ValueError):
        resolution(_cfg_from_golden(_CASES["puma_pg002_kf2.662_elastic"]), method="nope")


# --------------------------------------------------------------------------- determinism / serialization
def test_determinism():
    v = _CASES["in8_ki_fixed_sample_mosaic"]
    a = cooper_nathans(_cfg_from_golden(v))
    b = cooper_nathans(_cfg_from_golden(v))
    assert a.to_dict() == b.to_dict()
    cfg = _flat_popovici_cfg(_cfg_from_golden(v), 5)
    pa, pb = popovici(cfg), popovici(cfg)
    assert pa.to_dict() == pb.to_dict()


@pytest.mark.parametrize("name", list(_CASES))
def test_to_dict_json_roundtrips(name):
    res = cooper_nathans(_cfg_from_golden(_CASES[name]))
    s = json.dumps(res.to_dict())
    back = json.loads(s)
    assert back["method"] == "cooper_nathans"
    assert back["matrix"] == res.matrix
    assert list(back["basis"]) == ["dQ_par", "dQ_perp", "dQ_z", "dE"]


def test_popovici_to_dict_json_roundtrips():
    v = _CASES["puma_pg002_kf2.662_elastic"]
    res = popovici(_flat_popovici_cfg(_cfg_from_golden(v), 10))
    s = json.dumps(res.to_dict())
    assert json.loads(s)["r0"] > 0


def test_projections_present_for_three_planes():
    res = cooper_nathans(_cfg_from_golden(_CASES["tight_collimation_cu220"]))
    assert set(res.projections) == {"q_par_q_perp", "q_par_E", "q_perp_E"}
    for pl in res.projections.values():
        assert "tilt_rad" in pl and len(pl["fwhm_principal"]) == 2
