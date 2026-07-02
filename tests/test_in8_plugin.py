"""IN8 plugin contract tests (Phase 4, design record §20).

Same split as tests/test_puma_plugin.py: light tests exercise only the
import-light plugin module; heavy tests import the IN8 definition module
(which imports mcstasscript via the PUMA module) and skip without it.
"""
import pytest

from instruments.contract import InstrumentPlugin, PointSnapshot
from instruments.in8_plugin import (
    _IN8_PARAMS,
    IN8_MCSTAS_NAME,
    IN8Plugin,
    in8_descriptor,
)
from instruments.validation import validate_descriptor


# ---------------------------------------------------------------- light tests

def test_plugin_satisfies_protocol():
    assert isinstance(IN8Plugin(), InstrumentPlugin)


def test_plugin_descriptor_consistency():
    plugin = IN8Plugin()
    d = plugin.descriptor()
    assert plugin.id == d.id == "in8"
    assert plugin.display_name == d.display_name == "IN8 (ILL)"
    assert d.mcstas_name == IN8_MCSTAS_NAME == "IN8_McScript"


def test_descriptor_is_runnable():
    """Startup gates on assert_valid_descriptor(runnable=True)."""
    assert validate_descriptor(in8_descriptor(), runnable=True) == []


def test_descriptor_senses_are_vtas_verified():
    g = in8_descriptor().geometry
    assert (g.sense_mono.value, g.sense_sample.value, g.sense_ana.value) == (1, 1, -1)


def test_descriptor_mounts_shared_sample_library():
    from tavi.sample_library import default_sample_library

    assert in8_descriptor().samples == default_sample_library()


def test_cu200_uses_null_reflectivity_sentinel():
    cu200 = next(c for c in in8_descriptor().mono_crystals if c.id == "cu200")
    assert cu200.d_spacing == 1.807
    assert cu200.reflect_file == "NULL" and cu200.transmit_file == "NULL"
    assert cu200.r0 == 0.7


# ---------------------------------------------------------------- heavy tests

def _gui_vals(**overrides):
    """The instrument-config subset of get_gui_values() the scan config maps."""
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 3.0,
        "rvm": 1.2,
        "rha": 1.5,
        "fixed_E": 14.68,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_2": "0", "alpha_3": "30", "alpha_4": "0"},
        "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
    }
    vals.update(overrides)
    return vals


def test_default_state_matches_descriptor_geometry():
    pytest.importorskip("mcstasscript")
    from instruments.IN8_instrument_definition import IN8_Instrument

    plugin = IN8Plugin()
    state = plugin.default_state()
    assert isinstance(state, IN8_Instrument)
    assert state is not plugin.default_state()  # fresh object per call
    assert (state.L1, state.L2, state.L3, state.L4) == (2.28, 2.48, 1.05, 0.70)
    assert (state.sense_mono, state.sense_sample, state.sense_ana) == (1, 1, -1)
    assert (state.alpha_2, state.alpha_3, state.alpha_4) == (0, 0, 0)
    assert state.source_type == "Maxwellian"


def test_mcstas_name_matches_definition_module():
    pytest.importorskip("mcstasscript")
    from instruments.IN8_instrument_definition import MCSTAS_NAME

    assert MCSTAS_NAME == IN8_MCSTAS_NAME


def test_scan_config_applies_gui_mapping():
    pytest.importorskip("mcstasscript")
    plugin = IN8Plugin()
    base = plugin.default_state()
    base.mis_omega = 1.5          # hidden training state, absent from GUI values
    mount = object()
    diagnostics = {"Detector PSD": True}

    config = plugin.scan_config(base, _gui_vals(), "Al_bragg", diagnostics, mount)

    assert config is not base and base.alpha_3 == 0   # base not mutated
    assert config.mis_omega == 1.5                    # hidden state propagates
    assert config.K_fixed == "Kf Fixed"
    # Branch-signed curvature: GUI magnitudes; analyzer take-off is the -1
    # branch so rha/rva come out negative.
    assert (config.rhm, config.rvm, config.rha, config.rva) == (3.0, 1.2, -1.5, -0.31)
    assert config.monocris == config.anacris == "pg002"
    assert config.sample_key == "Al_bragg"
    # Single-select collimation slots -- floats, not PUMA's stacked list.
    assert config.alpha_2 == 0.0
    assert config.alpha_3 == 30.0
    assert config.alpha_4 == 0.0
    assert (config.sbl_wgap, config.sbl_hgap, config.dbl_hgap) == (0.04, 0.1, 0.04)
    assert config.sample_mount is mount
    assert config.diagnostic_settings.get("Detector PSD") is True


def test_crystal_info_resolves_against_in8_descriptor():
    pytest.importorskip("mcstasscript")
    plugin = IN8Plugin()
    mono, ana = plugin.crystal_info("cu200", "pg002")
    assert mono["dm"] == 1.807
    assert mono["reflect"] == '"NULL"' and mono["transmit"] == '"NULL"'
    assert ana["da"] == 3.355
    assert ana["ncolumns"] == 9 and ana["nrows"] == 7
    # State-level dispatch agrees with the plugin hook.
    state = plugin.default_state()
    assert state.crystal_info("cu200", "pg002") == (mono, ana)
    # Unknown ids keep the legacy empty-dict behavior.
    assert plugin.crystal_info("nope", "nope") == ({}, {})


def test_snapshot_params_match_descriptor(tmp_path):
    """docs §16.11: snapshot params keys == descriptor scannable_parameters."""
    pytest.importorskip("mcstasscript")
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = "pg002"
    state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 14.68

    # scans layout: mode-specific[0:4], rhm/rvm/rha/rva[4:8], chi/kappa/psi[8:11]
    scans = [41.19, 71.30, 35.65, -41.19, 3.0, 1.2, 1.5, 0.31, 0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
    )

    assert isinstance(snapshot, PointSnapshot)
    assert snapshot.error_flags == []
    assert snapshot.params is not None
    descriptor_names = {p.name for p in _IN8_PARAMS}
    assert set(snapshot.params) == descriptor_names
    assert "nu_param" not in snapshot.params      # no velocity selector on IN8
    assert "vbl_hgap_param" not in snapshot.params


def test_crystal_bending_is_point_source_and_branch_signed():
    pytest.importorskip("mcstasscript")
    import math

    plugin = IN8Plugin()
    state = plugin.default_state()
    mth, ath = 20.59, -20.59       # signed angles: A4/2 is negative on IN8
    rhm, rvm, rha, rva = state.calculate_crystal_bending(1, 1, 1, mth, ath)
    sin_th = math.sin(math.radians(abs(mth)))
    mono_focus = 1 / (1 / 2.28 + 1 / 2.48)
    ana_focus = 1 / (1 / 1.05 + 1 / 0.70)
    assert rhm == pytest.approx(2 * mono_focus / sin_th)
    assert rvm == pytest.approx(2 * mono_focus * sin_th)
    # Analyzer radii carry the branch sign: curvature center on the take-off
    # side (wrong sign defocuses by ~1e7 in peak intensity).
    assert rha == pytest.approx(-2 * ana_focus / sin_th)
    assert rva == pytest.approx(-2 * ana_focus * sin_th)  # computed, not fixed


def test_build_fingerprint_stable_and_sensitive():
    pytest.importorskip("mcstasscript")
    plugin = IN8Plugin()
    base = plugin.default_state()
    base.monocris = base.anacris = "pg002"

    fp1 = plugin.build_fingerprint(base)
    assert plugin.build_fingerprint(base) == fp1  # deterministic

    changed = plugin.default_state()
    changed.monocris = "cu200"
    changed.anacris = "pg002"
    assert plugin.build_fingerprint(changed) != fp1   # crystal change detected

    collimated = plugin.default_state()
    collimated.monocris = collimated.anacris = "pg002"
    collimated.alpha_3 = 30.0
    assert plugin.build_fingerprint(collimated) != fp1  # collimator compiles in/out

    # Slit gaps are runtime McStas parameters -- not build inputs.
    slit_changed = plugin.default_state()
    slit_changed.monocris = slit_changed.anacris = "pg002"
    slit_changed.sbl_wgap = 0.02
    assert plugin.build_fingerprint(slit_changed) == fp1

    assert plugin.build_fingerprint(base, True, {}) != fp1
    assert plugin.build_fingerprint(base, True, {"Source PSD": True}) != \
        plugin.build_fingerprint(base, True, {})
    assert plugin.build_fingerprint(base, False, None) == fp1
