"""Object-level PANDA build-tree tests (pattern: test_in8_build_tree.py).

Builds through the full plugin path and inspects ``component_list``.
Construction only -- no McStas compile or run. The plugin is used directly
(not through the registry) so these tests are registration-independent.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.panda.plugin import _PANDA_MONITORS, PANDAPlugin
from instruments.source import profile_values


def _build(sample_key=None, diagnostic_mode=False, diagnostic_settings=None,
           monocris="pg002", mode="full_spectrum",
           alpha_1="0", alpha_2="0", alpha_3="0", alpha_4="0", modules=None):
    plugin = PANDAPlugin()
    diagnostic_settings = diagnostic_settings or {}
    vals = {
        "K_fixed": "Kf Fixed",
        "moderator_mode": mode,
        "moderator_profile": "frm2_cold",
        **profile_values("frm2_cold"),
        "flat_band_half_width_mev": 2.0,
        "rhm": 4.0,
        "rvm": 1.8,
        "rha": 1.65,
        "rva": 0.60,
        "fixed_E": 4.978451631466585,       # kf = 1.55 A^-1
        "monocris": monocris,
        "anacris": "pg002",
        "modules": modules or {},
        "collimation": {"alpha_1": alpha_1, "alpha_2": alpha_2,
                        "alpha_3": alpha_3, "alpha_4": alpha_4},
        "slits_mm": {"ms1": 40.0, "ss1": (40.0, 80.0), "ss2": (40.0, 80.0)},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, sample_key, diagnostic_settings,
                                state.sample_mount)
    return plugin.build(config, diagnostic_mode, diagnostic_settings, 100000)


def _component_names(instrument):
    return [c.name for c in instrument.component_list]


@pytest.fixture(scope="module")
def diag_all_instrument():
    enabled = {m.id: True for m in _PANDA_MONITORS}
    return _build(sample_key="Al_bragg", diagnostic_mode=True,
                  diagnostic_settings=enabled, alpha_2="40")


@pytest.fixture(scope="module")
def plain_instrument():
    return _build()


# Every Soller open (the default): each is withdrawn from the beam, so no
# collimator component exists at all.
_BEAM_ORDER = [
    "origin", "source", "virtual_source",
    "mono_cradle", "monochromator", "sample_arm",
    "sample_slit", "sample_mount", "analyzer_arm", "sample_exit_slit",
    "analyzer_cradle", "analyzer", "detector_arm",
    "detector",
]

# The same backbone with all four Sollers inserted.
_BEAM_ORDER_COLLIMATED = [
    "origin", "source", "primary_collimator", "virtual_source",
    "mono_cradle", "monochromator", "sample_arm", "sample_collimator",
    "sample_slit", "sample_mount", "analyzer_arm", "sample_exit_slit", "analyzer_collimator",
    "analyzer_cradle", "analyzer", "detector_arm", "detector_collimator",
    "detector",
]

_SOLLERS = ("primary_collimator", "sample_collimator", "analyzer_collimator",
            "detector_collimator")


def test_backbone_beam_order(plain_instrument):
    """The structural components appear exactly once, in beam order."""
    names = _component_names(plain_instrument)
    assert [n for n in names if n in set(_BEAM_ORDER)] == _BEAM_ORDER


def test_declared_parameters_match_descriptor(plain_instrument):
    from instruments.panda.plugin import _PANDA_PARAMS

    declared = {p.name for p in plain_instrument.parameters}
    assert declared == {p.name for p in _PANDA_PARAMS}


def test_no_puma_or_in8_only_components(plain_instrument, diag_all_instrument):
    for instrument in (plain_instrument, diag_all_instrument):
        names = set(_component_names(instrument))
        assert not names & {"NMO_slit", "vertical_focusing_NMO",
                            "horizontal_focusing_NMO", "mono_collimator",
                            "postmono_slit", "exit_beam_tube",
                            "analyzer_filter", "detector_slit"}


def test_selector_absent_by_default(plain_instrument):
    assert "v_selector" not in _component_names(plain_instrument)


def test_selector_sits_after_the_primary_soller():
    """Experimental PANDA selector: PUMA's rotor, centred 0.80 m past the guide exit."""
    instrument = _build(alpha_1="40", modules={"v_selector": True})
    names = _component_names(instrument)
    assert names.count("v_selector") == 1
    assert names.index("primary_collimator") < names.index("v_selector") < names.index("virtual_source")
    selector = {c.name: c for c in instrument.component_list}["v_selector"]
    assert selector.component_name == "V_selector"
    assert selector.AT_data[2] == pytest.approx(0.80)
    assert selector.AT_reference == "origin"
    assert selector.nu == "nu_param"
    rotor = (selector.xwidth, selector.yheight, selector.zdepth, selector.radius,
             selector.length, selector.d, selector.nslit, selector.alpha)
    assert rotor == pytest.approx((0.100, 0.040, 0.310, 0.290, 0.25, 0.004, 72, 48.3))


def test_all_monitors_present_once_and_in_descriptor_order(diag_all_instrument):
    names = _component_names(diag_all_instrument)
    monitor_names = [m.component_name for m in _PANDA_MONITORS]
    assert len(_PANDA_MONITORS) == 21
    assert [n for n in names if n in set(monitor_names)] == monitor_names


def test_monitor_types_and_settings_match_descriptor(diag_all_instrument):
    by_name = {c.name: c for c in diag_all_instrument.component_list}
    for spec in _PANDA_MONITORS:
        comp = by_name[spec.component_name]
        assert comp.component_name == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value


def test_plain_build_emits_no_monitors(plain_instrument):
    names = set(_component_names(plain_instrument))
    assert not names & {m.component_name for m in _PANDA_MONITORS}


def test_monitor_gating_is_per_monitor():
    instrument = _build(diagnostic_mode=True,
                        diagnostic_settings={"Detector PSD": True})
    names = set(_component_names(instrument))
    assert "detector_PSD" in names
    assert not names & {m.component_name for m in _PANDA_MONITORS
                        if m.component_name != "detector_PSD"}


def test_backbone_beam_order_with_every_soller_inserted():
    names = _component_names(_build(alpha_1="20", alpha_2="40", alpha_3="15",
                                    alpha_4="60"))
    assert ([n for n in names if n in set(_BEAM_ORDER_COLLIMATED)]
            == _BEAM_ORDER_COLLIMATED)


def test_open_sollers_leave_the_beam_entirely():
    """Open is withdrawn, not divergence == 0.

    A zero-divergence ``Collimator_linear`` still carries its two rectangular
    apertures and absorbs rays, so the real vPANDA instrument gated its
    collimators with ``WHEN`` clauses rather than opening them in place.
    """
    assert not set(_component_names(_build())) & set(_SOLLERS)


def test_collimators_track_selection_including_the_primary():
    collimated = _build(alpha_1="20", alpha_2="40", alpha_3="15", alpha_4="60")
    by_name = {c.name: c for c in collimated.component_list}
    assert by_name["primary_collimator"].divergence == 20.0
    assert by_name["sample_collimator"].divergence == 40.0
    assert by_name["analyzer_collimator"].divergence == 15.0
    assert by_name["detector_collimator"].divergence == 60.0


def test_each_soller_is_independent():
    """Inserting one blade must not drag its neighbours into the beam."""
    slots = {"primary_collimator": "alpha_1", "sample_collimator": "alpha_2",
             "analyzer_collimator": "alpha_3", "detector_collimator": "alpha_4"}
    for inserted, slot in slots.items():
        names = set(_component_names(_build(**{slot: "40"})))
        assert names & set(_SOLLERS) == {inserted}


def test_both_crystals_transport_all_orders():
    """The real PANDA suppresses higher orders with hardware this model lacks
    (analyser-side PG, cold-Be and BeO filters; the unmodelled supermirror guide),
    so the tree transports every order and its simulated higher-order contamination
    overestimates the real instrument's.
    """
    by_name = {c.name: c for c in _build().component_list}
    assert by_name["monochromator"].order == 0
    assert by_name["analyzer"].order == 0


def test_virtual_source_is_a_scannable_slit_at_the_right_place():
    """ms1 sits 2.180 m past the guide exit -- 2.82 m ahead of the mono, which
    is the object distance the horizontal focusing formula uses."""
    instrument = _build()
    by_name = {c.name: c for c in instrument.component_list}
    ms1 = by_name["virtual_source"]
    assert ms1.component_name == "Slit"
    assert ms1.xwidth == "ms1_wgap_param"
    assert ms1.yheight == 0.180
    assert ms1.AT_data[2] == pytest.approx(2.180)
    assert ms1.AT_reference == "origin"


def test_sample_and_exit_slits_are_scannable():
    instrument = _build()
    by_name = {c.name: c for c in instrument.component_list}
    assert by_name["sample_slit"].xwidth == "ss1_wgap_param"
    assert by_name["sample_slit"].yheight == "ss1_hgap_param"
    assert by_name["sample_exit_slit"].xwidth == "ss2_wgap_param"
    assert by_name["sample_exit_slit"].yheight == "ss2_hgap_param"


def test_mono_crystal_matches_descriptor_pg002(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    mono = by_name["monochromator"]
    assert mono.DM == 3.355
    assert mono.zwidth == 0.020 and mono.yheight == 0.018
    assert mono.NH == 11 and mono.NV == 11
    assert mono.mosaic == 20
    assert mono.reflect == '"HOPG.rfl"' and mono.transmit == '"HOPG.trm"'
    ana = by_name["analyzer"]
    assert ana.DM == 3.355
    assert ana.NH == 11 and ana.NV == 5           # 55 crystals, not vPANDA's 78
    assert ana.zwidth == 0.013 and ana.yheight == 0.025


def test_cu111_mono_emits_null_reflectivity():
    instrument = _build(monocris="cu111")
    by_name = {c.name: c for c in instrument.component_list}
    mono = by_name["monochromator"]
    assert mono.DM == 2.087
    assert mono.r0 == 0.7
    assert mono.reflect == '"NULL"' and mono.transmit == '"NULL"'


def test_detector_contract(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    detector = by_name["detector"]
    assert detector.component_name == "Monitor"      # writes detector.dat
    assert detector.xwidth == 0.025                  # 1" 3He tube
    assert detector.yheight == 0.100


def test_source_wiring_is_the_same_in_both_modes():
    """The mode is a run-time parameter: it never changes the tree."""
    for mode in ("full_spectrum", "flat_band"):
        by_name = {c.name: c for c in _build(mode=mode).component_list}
        source = by_name["source"]
        assert source.component_name == "Source_Maxwell_direct"
        assert source.E0 == "E0_param" and source.dE == "flat_band_de_param"
        assert source.flat_band == "moderator_flat_band_param"
        assert [source.T1, source.I1, source.T2, source.I2, source.T3, source.I3] == [
            f"moderator_{kind}{n}_param" for n in (1, 2, 3) for kind in ("t", "i")]
        # The source aperture is the SR-2 guide exit, not a virtual source.
        assert source.xwidth == 0.107 and source.yheight == 0.138


def test_sample_emission_from_shared_library():
    instrument = _build(sample_key="Al_bragg")
    by_name = {c.name: c for c in instrument.component_list}
    assert "Al_Bragg" in by_name                     # legacy capital-B name
    names = _component_names(instrument)
    assert names.index("sample_mount") < names.index("Al_Bragg") < names.index("analyzer_arm")


def test_no_sample_warns_and_omits_component(capsys):
    instrument = _build(sample_key=None)
    names = set(_component_names(instrument))
    assert "Al_Bragg" not in names
    assert "No sample selected" in capsys.readouterr().out


def test_default_flat_band_half_width_clears_the_source_guard_at_pandas_cold_floor():
    """Source_Maxwell_direct stops a flat-band run when E0 - dE <= 0.

    PANDA's published floor is kf = 1.05 A^-1, i.e. E0 = 2.28 meV, so the
    default half-width must stay below that or a routine cold flat-band run
    is refused at that floor.
    """
    dE = PANDAPlugin().default_state().flat_band_half_width_mev
    assert 2.072142 * 1.05 ** 2 - dE > 0, dE


def test_monitor_order_holds_with_the_selector_and_primary_soller_in_beam():
    enabled = {m.id: True for m in _PANDA_MONITORS}
    instrument = _build(sample_key="Al_bragg", diagnostic_mode=True,
                        diagnostic_settings=enabled, alpha_1="40",
                        modules={"v_selector": True})
    names = _component_names(instrument)
    monitor_names = [m.component_name for m in _PANDA_MONITORS]
    assert [n for n in names if n in set(monitor_names)] == monitor_names
    assert (names.index("primary_collimator") < names.index("v_selector")
            < names.index("source_DSD") < names.index("virtual_source"))


def test_crystal_face_monitors_follow_the_selected_crystal(monkeypatch):
    """Crystal-face monitors take the selected crystal's slab extents.

    PG(002) and Cu(111) share slab extents, so a real crystal swap cannot show
    a missing override; doubling the slabs in crystal_info does.
    """
    from instruments.panda.model import PANDA_Instrument

    mono_info, ana_info = PANDA_Instrument().crystal_info("pg002", "pg002")

    def doubled(info):
        return {**info, "slabwidth": 2 * info["slabwidth"],
                "slabheight": 2 * info["slabheight"]}

    monkeypatch.setattr(PANDA_Instrument, "crystal_info",
                        lambda self, monocris, anacris: (doubled(mono_info),
                                                         doubled(ana_info)))
    enabled = {m.id: True for m in _PANDA_MONITORS}
    by_name = {c.name: c for c in
               _build(diagnostic_mode=True, diagnostic_settings=enabled).component_list}
    mono_w = 2 * mono_info["slabwidth"] * mono_info["ncolumns"]
    mono_h = 2 * mono_info["slabheight"] * mono_info["nrows"]
    ana_w = 2 * ana_info["slabwidth"] * ana_info["ncolumns"]
    ana_h = 2 * ana_info["slabheight"] * ana_info["nrows"]
    expected = {"premono_Emonitor": (mono_w, mono_h),
                "postmono_Emonitor": (mono_w, mono_h),
                "preanalyzer_Emonitor": (ana_w, ana_h),
                "preanalyzer_PSD": (ana_w, ana_h),
                "postanalyzer_Emonitor": (ana_w, ana_h),
                "postanalyzer_PSD": (ana_w, ana_h)}
    for name, (w, h) in expected.items():
        assert by_name[name].xwidth == pytest.approx(w), name
        assert by_name[name].yheight == pytest.approx(h), name

