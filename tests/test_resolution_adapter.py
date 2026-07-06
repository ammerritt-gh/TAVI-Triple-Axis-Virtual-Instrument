"""Plugin resolution-adapter tests (milestone 3, plan A2).

Exercise ``PUMAPlugin.resolution_config`` / ``IN8Plugin.resolution_config`` and
the shared ``instruments.resolution_adapter``. All numpy-only; no mcstasscript,
no Qt -- the adapter is a pure function of descriptor + ``vals``, so these run in
the safe pytest allowlist.
"""
import math

import pytest

from instruments.in8_plugin import IN8Plugin
from instruments.puma_plugin import PUMAPlugin
from tavi.resolution import cooper_nathans

_EK = 2.072142


def _puma_vals(**overrides):
    """A default-ish PUMA GUI ``vals`` subset the adapter consumes."""
    vals = {
        "K_fixed": "Ki Fixed",
        "fixed_E": 14.7,
        "source_type": "Maxwellian",
        "monocris": "pg002",
        "anacris": "pg002",
        "rhm": 2.5, "rvm": 1.2, "rha": 2.5,
        "modules": {"nmo": "None", "v_selector": False},
        "collimation": {
            "alpha_1": "40",
            "alpha_2": {"40"},
            "alpha_3": "30",
            "alpha_4": "30",
        },
    }
    vals.update(overrides)
    return vals


def _in8_vals(**overrides):
    vals = {
        "K_fixed": "Kf Fixed",
        "fixed_E": 14.7,
        "source_type": "Maxwellian",
        "monocris": "pg002",
        "anacris": "pg002",
        "rhm": 5.0, "rvm": 3.0, "rha": 5.0,
        "collimation": {
            "alpha_2": "40",
            "alpha_3": "40",
            "alpha_4": "40",
        },
    }
    vals.update(overrides)
    return vals


# ------------------------------------------------------------------ PUMA basics

def test_puma_crystals_mosaics_and_senses():
    cfg = PUMAPlugin().resolution_config(_puma_vals(), q0=2.0, w=0.0)
    assert cfg.dm == cfg.da == 3.355          # PG[002]
    assert cfg.eta_m == cfg.eta_a == 35       # descriptor mosaic
    # PUMA senses (+1, -1, +1) per its Geometry.
    assert (cfg.sm, cfg.ss, cfg.sa) == (1, -1, 1)
    assert cfg.q0 == 2.0 and cfg.w == 0.0


def test_puma_kfix_fx_both_modes():
    expected_k = math.sqrt(14.7 / _EK)
    ki_cfg = PUMAPlugin().resolution_config(_puma_vals(K_fixed="Ki Fixed"), 2.0, 0.0)
    assert ki_cfg.fx == 1
    assert ki_cfg.kfix == pytest.approx(expected_k, rel=1e-9)
    kf_cfg = PUMAPlugin().resolution_config(_puma_vals(K_fixed="Kf Fixed"), 2.0, 0.0)
    assert kf_cfg.fx == 2
    assert kf_cfg.kfix == pytest.approx(expected_k, rel=1e-9)


def test_puma_alpha2_multiselect_takes_min_nonzero():
    cfg = PUMAPlugin().resolution_config(
        _puma_vals(collimation={
            "alpha_1": "40", "alpha_2": {"30", "60"},
            "alpha_3": "30", "alpha_4": "30",
        }), 2.0, 0.0,
    )
    assert cfg.alf == (40.0, 30.0, 30.0, 30.0)  # alpha_2 -> tightest (30)
    assert "collimation_substitutions" not in cfg.provenance


def test_puma_open_collimation_substitutes_60_with_warning():
    cfg = PUMAPlugin().resolution_config(
        _puma_vals(collimation={
            "alpha_1": "0", "alpha_2": {"40"},
            "alpha_3": "30", "alpha_4": "30",
        }), 2.0, 0.0,
    )
    assert cfg.alf[0] == 60.0
    assert any("alpha_1 open" in w for w in cfg.warnings)
    subs = cfg.provenance["collimation_substitutions"]
    assert subs["alpha_1"]["effective"] == 60.0


def test_puma_empty_multiselect_is_open():
    cfg = PUMAPlugin().resolution_config(
        _puma_vals(collimation={
            "alpha_1": "40", "alpha_2": set(),
            "alpha_3": "30", "alpha_4": "30",
        }), 2.0, 0.0,
    )
    assert cfg.alf[1] == 60.0
    assert any("alpha_2 open" in w for w in cfg.warnings)


def test_puma_bet_from_descriptor_default():
    cfg = PUMAPlugin().resolution_config(_puma_vals(), 2.0, 0.0)
    assert cfg.bet == (120.0, 120.0, 120.0, 120.0)
    assert cfg.provenance["bet"]["source"] == "descriptor default"


# ------------------------------------------------------------------ sample mosaic

def test_eta_s_from_sample_mosaic_vs_reuse():
    # Al_bragg carries properties['mosaic'] = 5 in the sample library.
    bragg = PUMAPlugin().resolution_config(_puma_vals(sample_key="Al_bragg"), 2.0, 0.0)
    assert bragg.eta_s == 5
    assert "Al_bragg" in bragg.provenance["eta_s_source"]
    # A phonon sample has no mosaic property -> eta_s None -> module reuses eta_m.
    phonon = PUMAPlugin().resolution_config(_puma_vals(sample_key="Al_rod_phonon"), 2.0, 0.0)
    assert phonon.eta_s is None
    assert phonon.effective_eta_s() == phonon.eta_m
    # No sample selected -> None likewise.
    none = PUMAPlugin().resolution_config(_puma_vals(), 2.0, 0.0)
    assert none.eta_s is None


# ------------------------------------------------------------------ NMO / flags

def test_puma_nmo_invalidates_and_cn_reports_invalid():
    cfg = PUMAPlugin().resolution_config(
        _puma_vals(modules={"nmo": "Vertical", "v_selector": False}), 2.0, 0.0,
    )
    assert cfg.invalidations and "NMO installed" in cfg.invalidations[0]
    res = cooper_nathans(cfg)
    assert res.cn_valid is False
    assert res.invalidations == cfg.invalidations


def test_puma_v_selector_and_mono_source_warn():
    cfg = PUMAPlugin().resolution_config(
        _puma_vals(modules={"nmo": "None", "v_selector": True}, source_type="Mono"),
        2.0, 0.0,
    )
    assert any("velocity selector" in w for w in cfg.warnings)
    assert any("monochromatic source" in w for w in cfg.warnings)
    assert cfg.invalidations == ()          # warnings, not invalidations


# ------------------------------------------------------------------ end-to-end CN

def test_puma_end_to_end_cooper_nathans_plausible_fwhm():
    cfg = PUMAPlugin().resolution_config(_puma_vals(), q0=2.0, w=0.0)
    res = cooper_nathans(cfg)
    assert res.ok is True
    assert res.cn_valid is True
    # A standard thermal-TAS vanadium energy FWHM sits in ~0.3-3 meV.
    assert 0.3 < res.vanadium_fwhm_meV < 3.0


# ------------------------------------------------------------------ IN8

def test_in8_senses_crystals_and_kfix():
    cfg = IN8Plugin().resolution_config(_in8_vals(), q0=2.0, w=0.0)
    assert cfg.dm == cfg.da == 3.355          # PG[002]
    assert cfg.eta_m == cfg.eta_a == 30       # IN8 descriptor mosaic
    # IN8 verified senses (+1, +1, -1).
    assert (cfg.sm, cfg.ss, cfg.sa) == (1, 1, -1)
    assert cfg.fx == 2
    assert cfg.kfix == pytest.approx(math.sqrt(14.7 / _EK), rel=1e-9)


def test_in8_cu200_dspacing():
    cfg = IN8Plugin().resolution_config(_in8_vals(monocris="cu200"), 2.0, 0.0)
    assert cfg.dm == 1.807


def test_in8_missing_alpha1_is_open():
    # IN8's collimation dict has no alpha_1 slot -> treated as open (60 arcmin).
    cfg = IN8Plugin().resolution_config(_in8_vals(), 2.0, 0.0)
    assert cfg.alf[0] == 60.0
    assert any("alpha_1 open" in w for w in cfg.warnings)
    assert cfg.alf[1:] == (40.0, 40.0, 40.0)


def test_in8_no_module_invalidations():
    cfg = IN8Plugin().resolution_config(_in8_vals(), 2.0, 0.0)
    assert cfg.invalidations == ()
    res = cooper_nathans(cfg)
    assert res.ok is True and res.cn_valid is True
