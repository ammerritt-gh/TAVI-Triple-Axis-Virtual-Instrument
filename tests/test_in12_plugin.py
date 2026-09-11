"""IN12 plugin contract tests (pattern: tests/test_in8_plugin.py).

Same split as the IN8 tests: light tests exercise only the import-light plugin
module; heavy tests import the IN12 definition module (which imports
mcstasscript) and skip without it.

IN12 is the first TAVI instrument with ``sense_mono = -1``, so several of these
guard that path specifically.
"""
import math

import pytest

from instruments.contract import InstrumentPlugin, PointSnapshot
from instruments.in12.plugin import (
    _IN12_PARAMS,
    ANA_FIXED_RV,
    IN12_MCSTAS_NAME,
    IN12Plugin,
    in12_descriptor,
)
from instruments.validation import validate_descriptor


# ---------------------------------------------------------------- light tests

def test_plugin_satisfies_protocol():
    assert isinstance(IN12Plugin(), InstrumentPlugin)


def test_plugin_descriptor_consistency():
    plugin = IN12Plugin()
    d = plugin.descriptor()
    assert plugin.id == d.id == "in12"
    assert plugin.display_name == d.display_name == "IN12 (ILL)"
    assert d.mcstas_name == IN12_MCSTAS_NAME == "IN12_McScript"


def test_descriptor_is_runnable():
    """Startup gates on assert_valid_descriptor(runnable=True)."""
    assert validate_descriptor(in12_descriptor(), runnable=True) == []


def test_descriptor_senses_are_the_w_configuration():
    """(-1, +1, -1): mono and analyser clockwise, sample counter-clockwise.

    Confirmed on three independent sources (MODEL_STATUS.md). The structural
    half -- mono and analyser on the SAME branch, sample on the other -- is
    what "W configuration" means, and is asserted separately so a partial
    regression cannot hide behind the triple.
    """
    g = in12_descriptor().geometry
    assert (g.sense_mono.value, g.sense_sample.value, g.sense_ana.value) == (-1, 1, -1)
    assert g.sense_mono.value == g.sense_ana.value != g.sense_sample.value


def test_monochromator_axis_limits_are_entirely_negative():
    """The signed evidence for sense_mono = -1 lives in the axis limits."""
    a1 = in12_descriptor().axis_limits["A1"]
    assert (a1.lower, a1.upper) == (-140.0, -10.0)
    assert a1.default < 0


def test_descriptor_mounts_shared_sample_library():
    from tavi.sample_library import default_sample_library

    assert in12_descriptor().samples == default_sample_library()


def test_crystal_faces_match_published_overall_dimensions():
    """Slab sizes are derived (face/count minus gap), so pin the face they
    reconstruct: 200x160 mm mono, 122 mm-wide analyser."""
    d = in12_descriptor()
    mono = d.mono_crystals[0]
    assert (mono.n_columns, mono.n_rows) == (11, 11)
    width = mono.slab_width * 11 + mono.gap * 10
    height = mono.slab_height * 11 + mono.gap * 10
    assert width == pytest.approx(0.200)
    assert height == pytest.approx(0.160)
    assert mono.mosaic == 24                      # 0.4 deg FWHM (2016 paper)

    # The analyser is driven the other way round: 1998 publishes the 11 mm
    # lamella width, so the GAP is the derived quantity, and eleven lamellae
    # must still span the published 122 mm face.
    ana = next(c for c in d.ana_crystals if c.id == "pg002")
    assert ana.slab_width == 0.011
    assert ana.slab_width * 11 + ana.gap * 10 == pytest.approx(0.122)
    # Three rows, not one: the fixed vertical focus comes from tilting the top
    # and bottom rows, which a single-row assembly cannot do.
    assert (ana.n_columns, ana.n_rows) == (11, 3)
    assert ana.slab_height * 3 + ana.gap * 2 == pytest.approx(0.118)


def test_heusler_analyser_uses_null_reflectivity_sentinel():
    heusler = next(c for c in in12_descriptor().ana_crystals if c.id == "heusler111")
    assert heusler.d_spacing == 3.44
    assert heusler.reflect_file == "NULL" and heusler.transmit_file == "NULL"
    assert heusler.r0 == 0.3


def test_alpha1_collimation_slot_exists_and_defaults_open():
    """Unlike IN8, IN12 can take a Soller in the guide-exit section."""
    slots = {slot.id: slot for slot in in12_descriptor().collimation}
    assert set(slots) == {"alpha_1", "alpha_2", "alpha_3", "alpha_4"}
    for slot in slots.values():
        assert slot.default == "0"
        assert slot.allowed == ("0", "10", "20", "30", "40", "60", "80")


def test_no_ufo_or_multi_analyser_capability():
    """IN12-UFO reached neutron commissioning but has no published routine
    science use, and multi-analyser secondaries are out of scope for v1
    regardless. This descriptor is the conventional single-detector IN12."""
    d = in12_descriptor()
    assert d.modules == ()
    assert d.primary_detector == "detector"
    assert d.detector_parser == "1d_monitor"


# ---------------------------------------------------------------- heavy tests

def _gui_vals(**overrides):
    """The instrument-config subset of get_gui_values() the scan config maps."""
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 3.84,
        "rvm": 0.84,
        "rha": 1.98,
        "rva": 1.40,
        "fixed_E": 8.288785,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "30",
                        "alpha_4": "0"},
        "slits_mm": {"sbl": (30.0, 60.0), "dbl_hgap": 50.0},
    }
    vals.update(overrides)
    return vals


def test_default_state_matches_descriptor_geometry():
    pytest.importorskip("mcstasscript")
    from instruments.in12.model import IN12_Instrument

    plugin = IN12Plugin()
    state = plugin.default_state()
    assert isinstance(state, IN12_Instrument)
    assert state is not plugin.default_state()  # fresh object per call
    assert (state.L1, state.L2, state.L3, state.L4) == (1.80, 1.80, 1.30, 0.72)
    assert (state.sense_mono, state.sense_sample, state.sense_ana) == (-1, 1, -1)
    assert (state.alpha_1, state.alpha_2, state.alpha_3, state.alpha_4) == (0, 0, 0, 0)
    assert state.source_type == "Maxwellian"


def test_mcstas_name_matches_definition_module():
    pytest.importorskip("mcstasscript")
    from instruments.in12.model import MCSTAS_NAME

    assert MCSTAS_NAME == IN12_MCSTAS_NAME


def test_scan_config_applies_gui_mapping():
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    base = plugin.default_state()
    base.mis_omega = 1.5          # hidden training state, absent from GUI values
    mount = object()
    diagnostics = {"Detector PSD": True}

    config = plugin.scan_config(base, _gui_vals(), "Al_bragg", diagnostics, mount)

    assert config is not base and base.alpha_3 == 0   # base not mutated
    assert config.mis_omega == 1.5                    # hidden state propagates
    assert config.K_fixed == "Kf Fixed"
    # scan_config is a pass-through of the GUI magnitudes now -- branch
    # signing and fixed-axis policy (PG's fixed vertical analyser focus
    # included) live in set_crystal_bending, the shared boundary
    # compute_scan_snapshot always crosses before a point runs.
    assert (config.rhm, config.rvm, config.rha, config.rva) == \
        (3.84, 0.84, 1.98, 1.40)
    assert config.monocris == config.anacris == "pg002"
    assert config.sample_key == "Al_bragg"
    assert (config.alpha_1, config.alpha_2, config.alpha_3, config.alpha_4) == \
        (0.0, 0.0, 30.0, 0.0)
    assert (config.sbl_wgap, config.sbl_hgap, config.dbl_hgap) == (0.03, 0.06, 0.05)
    assert config.sample_mount is mount
    assert config.diagnostic_settings.get("Detector PSD") is True


def test_scan_config_passes_through_a_negative_gui_radius_unchanged():
    """scan_config no longer signs anything -- a GUI value that already
    carries a sign passes straight through, same as a positive one."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    base = plugin.default_state()
    already_negative = plugin.scan_config(
        base, _gui_vals(rhm=-3.84, rvm=-0.84, rha=-1.98), None, {}, base.sample_mount
    )
    assert (already_negative.rhm, already_negative.rvm, already_negative.rha) == \
        (-3.84, -0.84, -1.98)


def test_crystal_info_resolves_against_in12_descriptor():
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    mono, ana = plugin.crystal_info("pg002", "heusler111")
    assert mono["dm"] == 3.355
    assert mono["ncolumns"] == 11 and mono["nrows"] == 11
    assert ana["da"] == 3.44
    assert ana["reflect"] == '"NULL"' and ana["transmit"] == '"NULL"'
    # State-level dispatch agrees with the plugin hook.
    state = plugin.default_state()
    assert state.crystal_info("pg002", "heusler111") == (mono, ana)
    # Unknown ids keep the legacy empty-dict behavior.
    assert plugin.crystal_info("nope", "nope") == ({}, {})


def test_snapshot_params_match_descriptor(tmp_path):
    """docs §16.11: snapshot params keys == descriptor scannable_parameters."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    state = plugin.default_state()
    state.monocris = "pg002"
    state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 8.288785

    # scans layout: mode-specific[0:4], rhm/rvm/rha/rva[4:8], chi/kappa/psi[8:11]
    scans = [-55.834469, 101.737423, 50.868712, -55.834469,
             -3.84, -0.84, -1.98, 0.0, 0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
    )

    assert isinstance(snapshot, PointSnapshot)
    assert snapshot.error_flags == []
    assert snapshot.params is not None
    assert set(snapshot.params) == {p.name for p in _IN12_PARAMS}
    assert "nu_param" not in snapshot.params      # no velocity selector in-model
    assert "vbl_hgap_param" not in snapshot.params


def test_angle_feasibility_rejects_a_positive_monochromator_angle():
    """IN12's mono cannot reach a positive two-theta -- its whole travel is
    -140..-10 deg. This is the axis limit that encodes sense_mono = -1."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    state = plugin.default_state()
    scans = [+55.834469, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]

    feasible, reason = plugin.check_point_feasibility(
        state, "angle", scans, {"deltaE": 0.0, "chi": 0.0}
    )

    assert feasible is False
    assert reason is not None and "A1" in reason and "outside" in reason


def test_momentum_feasibility_enforces_solved_axis_limits():
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 8.288785
    # |Q| = 3.95 A^-1 needs a sample two-theta past the +-120 deg travel at
    # ki = kf = 2.0 A^-1.
    scans = [3.95, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]

    feasible, reason = plugin.check_point_feasibility(
        state, "momentum", scans, {"deltaE": 0.0, "chi": 0.0}
    )

    assert feasible is False
    assert reason is not None and "A2" in reason and "outside" in reason


def test_crystal_bending_is_rowland_matched_and_branch_signed():
    """Literals are the pinned reference table (packet slice2 §pinned table),
    derived from IN12's declared arm lengths -- not recomputed from the
    implementation under test, which would pass against any policy it
    happened to adopt."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    state = plugin.default_state()
    mth, ath = -27.917234, -27.917234       # both branches negative on IN12
    radii = state.ideal_curvature("pg002", "pg002", mth, ath)

    assert radii["rhm"] == pytest.approx(-3.8445, abs=5e-5)
    assert radii["rvm"] == pytest.approx(-0.8428, abs=5e-5)
    assert radii["rha"] == pytest.approx(-1.9794, abs=5e-5)
    # The analyser's vertical radius is fixed hardware, branch-signed but not
    # computed -- and deliberately NOT the Rowland optimum, which is what
    # "fixed" means. Guard that it is not silently tracking the arms.
    assert radii["rva"] == pytest.approx(-ANA_FIXED_RV)
    ana_focus = 1 / (1 / 1.30 + 1 / 0.72)
    sin_th = math.sin(math.radians(abs(ath)))
    assert abs(radii["rva"]) > 2 * abs(2 * ana_focus * sin_th)


def test_vertical_bending_clamps_at_the_provisional_minimum():
    """The clamp is a PROVISIONAL model assumption, not a published limit.

    MODEL_STATUS.md records the 2016 reading (~0.5 m to flat) as unconfirmed,
    so this pins the behaviour of the assumption the model states -- that at
    small Bragg angles the ideal radius drops below the minimum and is
    clamped -- not the existence of a 0.5 m mechanical stop."""
    pytest.importorskip("mcstasscript")
    from instruments.in12.model import MONO_MIN_RV

    state = IN12Plugin().default_state()
    radii = state.ideal_curvature("pg002", "pg002", -10.0, -30.0)
    ideal = -2 * 0.9 * math.sin(math.radians(10.0))
    assert abs(ideal) < MONO_MIN_RV                  # the clamp really engages
    assert radii["rvm"] == pytest.approx(-MONO_MIN_RV)  # clamped, sign preserved


def test_build_fingerprint_stable_and_sensitive():
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    base = plugin.default_state()
    base.monocris = base.anacris = "pg002"

    fp1 = plugin.build_fingerprint(base)
    assert plugin.build_fingerprint(base) == fp1  # deterministic

    changed = plugin.default_state()
    changed.monocris = "pg002"
    changed.anacris = "heusler111"
    assert plugin.build_fingerprint(changed) != fp1   # crystal change detected

    # alpha_1 is IN12's extra slot -- it must be part of the build state.
    collimated = plugin.default_state()
    collimated.monocris = collimated.anacris = "pg002"
    collimated.alpha_1 = 30.0
    assert plugin.build_fingerprint(collimated) != fp1

    # Slit gaps are runtime McStas parameters -- not build inputs.
    slit_changed = plugin.default_state()
    slit_changed.monocris = slit_changed.anacris = "pg002"
    slit_changed.sbl_wgap = 0.02
    assert plugin.build_fingerprint(slit_changed) == fp1

    assert plugin.build_fingerprint(base, True, {}) != fp1
    assert plugin.build_fingerprint(base, True, {"Source PSD": True}) != \
        plugin.build_fingerprint(base, True, {})
    assert plugin.build_fingerprint(base, False, None) == fp1


def test_resolution_config_uses_in12_senses_and_crystals():
    cfg = IN12Plugin().resolution_config(_gui_vals(), q0=2.0, w=0.0)
    assert cfg.dm == cfg.da == 3.355          # PG[002] both sides
    assert cfg.eta_m == 24 and cfg.eta_a == 30
    assert (cfg.sm, cfg.ss, cfg.sa) == (-1, 1, -1)
    assert cfg.invalidations == ()


def test_resolution_config_can_collimate_the_primary_arm():
    """IN8 has no alpha_1 at all, so its ALF1 is always the open substitute.
    IN12 declares the slot, so a real primary collimation reaches the adapter."""
    cfg = IN12Plugin().resolution_config(
        _gui_vals(collimation={"alpha_1": "30", "alpha_2": "0",
                               "alpha_3": "30", "alpha_4": "0"}),
        q0=2.0, w=0.0,
    )
    assert cfg.alf[0] == 30.0
    assert not any("alpha_1 open" in w for w in cfg.warnings)


def test_scanned_radius_still_lands_on_the_take_off_branch(tmp_path):
    """Regression: scan_config signs the radii it copies out of the GUI, but a
    SCANNED radius bypasses it -- compute_scan_snapshot reads scans[4:8] and
    calls set_crystal_bending directly. IN12's override forces the branch.

    IN12 takes off negative at both crystals, so a positive scanned radius puts
    the curvature centre on the wrong side and defocuses by orders of
    magnitude while every angle stays valid."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
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

    Real angles are required now: the base setter derives the branch sign
    from ``self.A1``/``self.A4``, not from an unconditional instrument-wide
    override (see ``instruments/tas_runtime.py::set_crystal_bending``). No
    crystal is selected, so every axis reads as driven/unfixed -- the
    supplied -0.6 m for rva is not IN12's fixed 1.40 m analyser radius.
    """
    pytest.importorskip("mcstasscript")
    state = IN12Plugin().default_state()
    state.set_angles(A1=-55.834468, A4=-55.834468)  # IN12's negative take-off branch
    state.set_crystal_bending(rhm=-4.0, rvm=-1.8, rha=-1.65, rva=-0.6)
    assert (state.rhm, state.rvm, state.rha, state.rva) == (-4.0, -1.8, -1.65, -0.6)
    state.set_crystal_bending(rhm=4.0)
    assert state.rhm == -4.0
    assert state.rvm == -1.8            # untouched arguments stay put


def test_the_fixed_analyser_curvature_is_not_scannable():
    """The fixed vertical focus is declared on the crystal, not the instrument.

    scan_config pins rva, but compute_scan_snapshot reads the radii out of
    scans[4:8], so an accepted scan would either do nothing or quietly defeat
    the pin. Fixed focusing is a property of the analyser assembly, so the
    Heusler option on this same instrument claims nothing: its focusing
    behaviour is not established, and a flag on the instrument would have
    asserted the PG analyser's evidence about it.
    """
    d = in12_descriptor()
    ana = {c.id: c for c in d.ana_crystals}
    assert ana["pg002"].fixed_curvature == ("rva",)

    # The radii this instrument really does drive stay scannable.
    for spec in d.mono_crystals:
        assert spec.fixed_curvature == ()
    for spec in d.ana_crystals:
        assert "rha" not in spec.fixed_curvature


def _heusler_id():
    for spec in in12_descriptor().ana_crystals:
        if spec.id != "pg002":
            return spec.id
    raise AssertionError("IN12 should carry a second analyser")


def test_the_heusler_does_not_inherit_pg_s_fixed_vertical_focus():
    """The 1998 fixed-focus evidence is about the PG(002) assembly only.

    scan_config pinned rva = -ANA_FIXED_RV unconditionally, so selecting the
    Heusler still started every scan with PG's 1.40 m vertical curvature --
    which is precisely the cross-crystal inference that declaring
    fixed_curvature per crystal exists to prevent.
    """
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    heusler = _heusler_id()

    ana = {c.id: c for c in in12_descriptor().ana_crystals}
    assert ana["pg002"].fixed_curvature == ("rva",)
    assert ana[heusler].fixed_curvature == ()

    state = plugin.default_state()
    state.anacris = "pg002"
    assert state.ana_vertical_is_fixed()
    state.anacris = heusler
    assert not state.ana_vertical_is_fixed()

    # ...and the ideal radius follows, rather than PG's fixed value: PG gets
    # its fixed hardware radius, while the Heusler's focusing is unpublished
    # (focusing_known=False) and is REFUSED rather than given an invented one.
    mth = ath = -27.917234
    state.monocris = "pg002"
    radii_pg = state.ideal_curvature("pg002", "pg002", mth, ath)
    assert radii_pg["rva"] == pytest.approx(-ANA_FIXED_RV)
    with pytest.raises(ValueError, match="focusing_known"):
        state.ideal_curvature("pg002", heusler, mth, ath)


def test_scan_config_passes_through_rva_regardless_of_analyser():
    """scan_config carries rva straight through for every analyser now --
    PG's fixed vertical focus and the Heusler's unknown one are
    set_crystal_bending's job (see
    test_the_heusler_does_not_inherit_pg_s_fixed_vertical_focus), not
    scan_config's."""
    pytest.importorskip("mcstasscript")
    plugin = IN12Plugin()
    heusler = _heusler_id()
    base = plugin.default_state()

    def _config(anacris, rva):
        vals = {
            "K_fixed": "Kf Fixed", "source_type": "Maxwellian", "source_dE": 2,
            "rhm": 3.0, "rvm": 1.2, "rha": 1.5, "rva": rva,
            "fixed_E": 8.288785, "monocris": "pg002", "anacris": anacris,
            "modules": {},
            "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "0",
                            "alpha_4": "0"},
            "slits_mm": {"sbl": (30.0, 60.0), "dbl_hgap": 50.0},
        }
        return plugin.scan_config(base, vals, None, {}, base.sample_mount)

    assert _config("pg002", rva=ANA_FIXED_RV).rva == ANA_FIXED_RV
    assert _config(heusler, rva=0.9).rva == pytest.approx(0.9)
    assert _config(heusler, rva=0.0).rva == 0.0
