"""PANDA plugin contract tests (pattern: tests/test_in8_plugin.py).

Light tests exercise only the import-light plugin module; heavy tests import
the PANDA definition module (which imports mcstasscript) and skip without it.
"""
import pytest

from instruments.contract import InstrumentPlugin, PointSnapshot
from instruments.panda.plugin import (
    _PANDA_PARAMS,
    PANDA_MCSTAS_NAME,
    PANDAPlugin,
    panda_descriptor,
)
from instruments.validation import validate_descriptor


# ---------------------------------------------------------------- light tests

def test_plugin_satisfies_protocol():
    assert isinstance(PANDAPlugin(), InstrumentPlugin)


def test_plugin_descriptor_consistency():
    plugin = PANDAPlugin()
    d = plugin.descriptor()
    assert plugin.id == d.id == "panda"
    assert plugin.display_name == d.display_name == "PANDA (MLZ)"
    assert d.mcstas_name == PANDA_MCSTAS_NAME == "PANDA_McScript"


def test_descriptor_is_runnable():
    """Startup gates on assert_valid_descriptor(runnable=True)."""
    assert validate_descriptor(panda_descriptor(), runnable=True) == []


def test_descriptor_senses_have_negative_monochromator():
    """PANDA is the first TAVI instrument taking off negative at the mono.

    vPANDA declares scatsense_mono/sample/ana = -1/+1/-1; every bending radius
    downstream of this depends on the monochromator sign, so freeze it.
    """
    g = panda_descriptor().geometry
    assert (g.sense_mono.value, g.sense_sample.value, g.sense_ana.value) == (-1, 1, -1)


def test_descriptor_mounts_shared_sample_library():
    from tavi.sample_library import default_sample_library

    assert panda_descriptor().samples == default_sample_library()


def test_descriptor_has_primary_collimation_slot():
    """Unlike IN8, PANDA collimates ahead of the monochromator (alpha_1)."""
    slots = {slot.id: slot for slot in panda_descriptor().collimation}
    assert set(slots) == {"alpha_1", "alpha_2", "alpha_3", "alpha_4"}
    assert slots["alpha_1"].allowed == ("0", "20", "40", "60")
    for downstream in ("alpha_2", "alpha_3", "alpha_4"):
        assert slots[downstream].allowed == ("0", "15", "40", "60")


def test_analyzer_array_is_the_55_crystal_layout():
    """11 x 5 (2014 model + teaching notes), not vPANDA's stale 13 x 6."""
    ana = panda_descriptor().ana_crystals[0]
    assert (ana.n_columns, ana.n_rows) == (11, 5)
    assert ana.d_spacing == 3.355 and ana.mosaic == 20


def test_cu111_uses_null_reflectivity_sentinel():
    cu111 = next(c for c in panda_descriptor().mono_crystals if c.id == "cu111")
    assert cu111.d_spacing == 2.087
    assert cu111.reflect_file == "NULL" and cu111.transmit_file == "NULL"


def test_axis_limits_follow_the_published_ranges():
    """MLZ publishes A2 and A4 verbatim; A1 is the 2007 PG(002) travel on the
    negative branch sense_mono = -1 puts the monochromator on."""
    limits = panda_descriptor().axis_limits
    assert (limits["A2"].lower, limits["A2"].upper) == (5.0, 125.0)
    assert (limits["A4"].lower, limits["A4"].upper) == (-130.0, 100.0)
    assert (limits["A1"].lower, limits["A1"].upper) == (-132.0, -20.0)
    # Every default is the standard cold elastic setting and must be reachable.
    for axis, lim in limits.items():
        assert lim.lower <= lim.default <= lim.upper, axis


# ---------------------------------------------------------------- heavy tests

def _gui_vals(**overrides):
    """The instrument-config subset of get_gui_values() the scan config maps."""
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 4.0,
        "rvm": 1.8,
        "rha": 1.65,
        "rva": 0.60,
        "fixed_E": 4.978451631466585,     # kf = 1.55 A^-1
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "40", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"ms1": 40.0, "ss1": (40.0, 80.0), "ss2": (40.0, 80.0)},
    }
    vals.update(overrides)
    return vals


def test_default_state_matches_descriptor_geometry():
    pytest.importorskip("mcstasscript")
    from instruments.panda.model import PANDA_Instrument

    plugin = PANDAPlugin()
    state = plugin.default_state()
    assert isinstance(state, PANDA_Instrument)
    assert state is not plugin.default_state()  # fresh object per call
    assert (state.L1, state.L2, state.L3, state.L4) == (5.00, 2.10, 1.05, 0.95)
    assert (state.sense_mono, state.sense_sample, state.sense_ana) == (-1, 1, -1)
    assert (state.alpha_1, state.alpha_2, state.alpha_3, state.alpha_4) == (0, 0, 0, 0)
    assert state.source_type == "Maxwellian"
    # The horizontal virtual source sits 2.180 m past the guide exit.
    assert state.l_virtual_source_mono == pytest.approx(2.82)


def test_mcstas_name_matches_definition_module():
    pytest.importorskip("mcstasscript")
    from instruments.panda.model import MCSTAS_NAME

    assert MCSTAS_NAME == PANDA_MCSTAS_NAME


def test_scan_config_applies_gui_mapping():
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    base = plugin.default_state()
    base.mis_omega = 1.5          # hidden training state, absent from GUI values
    mount = object()
    diagnostics = {"Detector PSD": True}

    config = plugin.scan_config(base, _gui_vals(), "Al_bragg", diagnostics, mount)

    assert config is not base and base.alpha_2 == 0    # base not mutated
    assert config.mis_omega == 1.5                     # hidden state propagates
    assert config.K_fixed == "Kf Fixed"
    assert config.monocris == config.anacris == "pg002"
    assert config.sample_key == "Al_bragg"
    assert (config.alpha_1, config.alpha_2, config.alpha_3, config.alpha_4) == \
        (0.0, 40.0, 0.0, 0.0)
    assert (config.ms1_wgap, config.ss1_wgap, config.ss1_hgap,
            config.ss2_wgap, config.ss2_hgap) == (0.04, 0.04, 0.08, 0.04, 0.08)
    assert config.sample_mount is mount
    assert config.diagnostic_settings.get("Detector PSD") is True


def test_scan_config_passes_through_curvature_magnitudes_unsigned():
    """scan_config no longer signs or fixes curvature -- that policy lives
    once in set_crystal_bending (the boundary every path to the instrument
    state crosses). Whatever the caller hands in comes straight through,
    positive or already negative."""
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    config = plugin.scan_config(plugin.default_state(), _gui_vals(),
                                "Al_bragg", {}, object())
    assert (config.rhm, config.rvm, config.rha, config.rva) == (4.0, 1.8, 1.65, 0.60)

    # A GUI that already carried a sign passes through unchanged too.
    flipped = plugin.scan_config(plugin.default_state(),
                                 _gui_vals(rhm=-4.0, rvm=-1.8, rha=-1.65),
                                 "Al_bragg", {}, object())
    assert (flipped.rhm, flipped.rvm, flipped.rha) == (-4.0, -1.8, -1.65)


def test_crystal_info_resolves_against_panda_descriptor():
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    mono, ana = plugin.crystal_info("cu111", "pg002")
    assert mono["dm"] == 2.087
    assert mono["reflect"] == '"NULL"' and mono["transmit"] == '"NULL"'
    assert ana["da"] == 3.355
    assert ana["ncolumns"] == 11 and ana["nrows"] == 5
    # State-level dispatch agrees with the plugin hook.
    state = plugin.default_state()
    assert state.crystal_info("cu111", "pg002") == (mono, ana)
    # Unknown ids keep the legacy empty-dict behavior.
    assert plugin.crystal_info("nope", "nope") == ({}, {})


def test_snapshot_params_match_descriptor(tmp_path):
    """docs §16.11: snapshot params keys == descriptor scannable_parameters."""
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = "pg002"
    state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 4.978451631466585

    # scans layout: mode-specific[0:4], rhm/rvm/rha/rva[4:8], chi/kappa/psi[8:11]
    scans = [-74.332, 120.180, 60.090, -74.332, -4.0, -1.8, -1.65, -0.6,
             0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
    )

    assert isinstance(snapshot, PointSnapshot)
    assert snapshot.error_flags == []
    assert snapshot.params is not None
    assert set(snapshot.params) == {p.name for p in _PANDA_PARAMS}
    assert "nu_param" not in snapshot.params      # no velocity selector
    assert "sbl_wgap_param" not in snapshot.params  # IN8's slit names, not PANDA's


def test_angle_feasibility_enforces_raw_axis_limits():
    """A positive A1 is unreachable: PANDA's monochromator is on the -1 branch."""
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    state = plugin.default_state()
    scans = [74.332, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]

    feasible, reason = plugin.check_point_feasibility(
        state, "angle", scans, {"deltaE": 0.0, "chi": 0.0}
    )

    assert feasible is False
    assert reason is not None and "A1" in reason and "outside" in reason


def test_momentum_feasibility_enforces_the_five_degree_beam_stop():
    """PANDA cannot reach small sample two-theta (5 deg < 2ThetaS)."""
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 4.978451631466585
    scans = [0.05, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]

    feasible, reason = plugin.check_point_feasibility(
        state, "momentum", scans, {"deltaE": 0.0, "chi": 0.0}
    )

    assert feasible is False
    assert reason is not None and "A2" in reason and "outside" in reason


def test_crystal_bending_splits_the_monochromator_object_distance():
    """Horizontal focusing images the virtual source (2.82 m); vertical
    focusing images the guide exit (L1 = 5.00 m). Both radii come out negative
    on PANDA's take-off branch.

    Literals are the pinned reference table (packet slice2 §pinned table),
    derived from PANDA's declared arm lengths -- not recomputed from the
    implementation under test, which would pass against any policy it
    happened to adopt. PANDA's row is independently corroborated by
    ``instruments/panda/MODEL_STATUS.md:114``.
    """
    pytest.importorskip("mcstasscript")

    plugin = PANDAPlugin()
    state = plugin.default_state()
    mth, ath = -37.166, -37.166      # signed: PANDA's A1/2 and A4/2 are negative
    radii = state.ideal_curvature("pg002", "pg002", mth, ath)

    assert radii["rhm"] == pytest.approx(-3.9848, abs=5e-5)
    assert radii["rvm"] == pytest.approx(-1.7869, abs=5e-5)
    assert radii["rha"] == pytest.approx(-1.6511, abs=5e-5)
    assert radii["rva"] == pytest.approx(-0.6000, abs=5e-5)
    # The two monochromator planes must not share an object distance.
    mono_focus_h = 1 / (1 / 2.82 + 1 / 2.10)
    mono_focus_v = 1 / (1 / 5.00 + 1 / 2.10)
    assert mono_focus_h != mono_focus_v
    assert all(r < 0 for r in radii.values())


def test_build_fingerprint_stable_and_sensitive():
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    base = plugin.default_state()
    base.monocris = base.anacris = "pg002"

    fp1 = plugin.build_fingerprint(base)
    assert plugin.build_fingerprint(base) == fp1  # deterministic

    changed = plugin.default_state()
    changed.monocris = "cu111"
    changed.anacris = "pg002"
    assert plugin.build_fingerprint(changed) != fp1   # crystal change detected

    # The primary collimator compiles in/out just like the downstream three.
    primary = plugin.default_state()
    primary.monocris = primary.anacris = "pg002"
    primary.alpha_1 = 40.0
    assert plugin.build_fingerprint(primary) != fp1

    # Aperture gaps are runtime McStas parameters -- not build inputs.
    slit_changed = plugin.default_state()
    slit_changed.monocris = slit_changed.anacris = "pg002"
    slit_changed.ms1_wgap = 0.02
    slit_changed.ss1_wgap = 0.02
    assert plugin.build_fingerprint(slit_changed) == fp1

    assert plugin.build_fingerprint(base, True, {}) != fp1
    assert plugin.build_fingerprint(base, True, {"Source PSD": True}) != \
        plugin.build_fingerprint(base, True, {})
    assert plugin.build_fingerprint(base, False, None) == fp1


def test_resolution_config_needs_no_primary_collimation_substitution():
    """IN8 has no alpha_1 and the adapter substitutes 60 arcmin with a warning.
    PANDA has one, so a selected primary collimation reaches the config as-is."""
    pytest.importorskip("mcstasscript")
    vals = dict(_gui_vals(collimation={"alpha_1": "20", "alpha_2": "40",
                                       "alpha_3": "40", "alpha_4": "40"}))
    cfg = PANDAPlugin().resolution_config(vals, q0=2.0, w=0.0)
    assert cfg.alf == (20.0, 40.0, 40.0, 40.0)
    assert not any("alpha_1" in w for w in cfg.warnings)
    # PANDA's senses reach the resolution config unchanged.
    assert (cfg.sm, cfg.ss, cfg.sa) == (-1, 1, -1)
    assert cfg.dm == cfg.da == 3.355


def test_scanned_radius_still_lands_on_the_take_off_branch(tmp_path):
    """Regression: scan_config signs the radii it copies out of the GUI, but a
    SCANNED radius bypasses it -- compute_scan_snapshot reads scans[4:8] and
    calls set_crystal_bending directly. PANDA's override forces the branch."""
    pytest.importorskip("mcstasscript")
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 4.978451631466585

    # Positive magnitudes in the scans array, exactly as the GUI carries them.
    scans = [-74.332, 120.180, 60.090, -74.332, 4.0, 1.8, 1.65, 0.6,
             0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
        variable_name1="rhm", variable_name2="rha",
    )

    assert snapshot.error_flags == []
    assert snapshot.params["rhm_param"] == -4.0
    assert snapshot.params["rha_param"] == -1.65


def test_set_crystal_bending_is_idempotent_on_already_signed_values():
    """A value already signed onto the take-off branch is not flipped back.

    Real angles and a real crystal are required now: the base setter derives
    the branch sign from ``self.A1``/``self.A4``, not from an unconditional
    instrument-wide override (see ``instruments/tas_runtime.py::set_crystal_bending``).
    """
    pytest.importorskip("mcstasscript")
    state = PANDAPlugin().default_state()
    state.monocris = state.anacris = "pg002"
    state.set_angles(A1=-74.332, A4=-74.332)  # PANDA's negative take-off branch
    state.set_crystal_bending(rhm=-4.0, rvm=-1.8, rha=-1.65, rva=-0.6)
    assert (state.rhm, state.rvm, state.rha, state.rva) == (-4.0, -1.8, -1.65, -0.6)
    state.set_crystal_bending(rhm=4.0)
    assert state.rhm == -4.0
    assert state.rvm == -1.8            # untouched arguments stay put


def test_the_fixed_analyser_curvature_is_not_scannable():
    """The fixed vertical focus is declared on the crystal, not the instrument.

    scan_config pins rva, but compute_scan_snapshot reads the radii out of
    scans[4:8], so an accepted scan would either do nothing or quietly defeat
    the pin. Fixed focusing is a property of the analyser assembly, confirmed
    here by two peer-reviewed papers about this analyser; it would not
    transfer to a different one.
    """
    d = panda_descriptor()
    ana = {c.id: c for c in d.ana_crystals}
    assert ana["pg002"].fixed_curvature == ("rva",)

    # The radii this instrument really does drive stay scannable.
    for spec in d.mono_crystals:
        assert spec.fixed_curvature == ()
    for spec in d.ana_crystals:
        assert "rha" not in spec.fixed_curvature
