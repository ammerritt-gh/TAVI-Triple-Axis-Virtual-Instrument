"""Object-level IN12 build-tree tests (pattern: test_in8_build_tree.py).

Builds through the full plugin path and inspects ``component_list``.
Construction only -- no McStas compile or run. The plugin is used directly
(not through the registry) so these tests are registration-independent.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.in12.plugin import _IN12_MONITORS, IN12Plugin


def _build(sample_key=None, diagnostic_mode=False, diagnostic_settings=None,
           anacris="pg002", source_type="Maxwellian",
           alpha_1="0", alpha_2="0", alpha_3="0", alpha_4="0"):
    plugin = IN12Plugin()
    diagnostic_settings = diagnostic_settings or {}
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": source_type,
        "source_dE": 2,
        "rhm": 3.84,
        "rvm": 0.84,
        "rha": 1.98,
        "fixed_E": 8.288785,
        "monocris": "pg002",
        "anacris": anacris,
        "modules": {},
        "collimation": {"alpha_1": alpha_1, "alpha_2": alpha_2,
                        "alpha_3": alpha_3, "alpha_4": alpha_4},
        "slits_mm": {"sbl": (30.0, 60.0), "dbl_hgap": 50.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, sample_key, diagnostic_settings,
                                state.sample_mount)
    return plugin.build(config, diagnostic_mode, diagnostic_settings, 100000)


def _component_names(instrument):
    return [c.name for c in instrument.component_list]


@pytest.fixture(scope="module")
def diag_all_instrument():
    enabled = {m.id: True for m in _IN12_MONITORS}
    return _build(sample_key="Al_bragg", diagnostic_mode=True,
                  diagnostic_settings=enabled, alpha_3="30")


@pytest.fixture(scope="module")
def plain_instrument():
    return _build()


# Every Soller open (the default): each is withdrawn from the beam, so no
# collimator component exists at all.
_BEAM_ORDER = [
    "origin", "source", "mono_cradle", "monochromator",
    "sample_arm", "sample_slit", "sample_gonio",
    "sample_chi_arm", "sample_cradle", "sample_mount", "analyzer_arm",
    "analyzer_cradle", "analyzer", "detector_arm",
    "detector_slit", "detector",
]

# The same backbone with all four Sollers inserted.
_BEAM_ORDER_COLLIMATED = [
    "origin", "source", "mono_collimator", "mono_cradle", "monochromator",
    "sample_arm", "sample_collimator", "sample_slit", "sample_gonio",
    "sample_chi_arm", "sample_cradle", "sample_mount", "analyzer_arm",
    "analyzer_collimator", "analyzer_cradle", "analyzer", "detector_arm",
    "detector_collimator", "detector_slit", "detector",
]

_SOLLERS = ("mono_collimator", "sample_collimator", "analyzer_collimator",
            "detector_collimator")


def test_backbone_beam_order(plain_instrument):
    """The structural components appear exactly once, in beam order."""
    names = _component_names(plain_instrument)
    assert [n for n in names if n in set(_BEAM_ORDER)] == _BEAM_ORDER


def test_declared_parameters_match_descriptor(plain_instrument):
    from instruments.in12.plugin import _IN12_PARAMS

    declared = {p.name for p in plain_instrument.parameters}
    assert declared == {p.name for p in _IN12_PARAMS}


def test_no_other_instrument_components(plain_instrument, diag_all_instrument):
    """No PUMA optics, and no IN8 filter -- IN12 carries no permanent filter."""
    for instrument in (plain_instrument, diag_all_instrument):
        names = set(_component_names(instrument))
        assert not names & {"v_selector", "NMO_slit", "vertical_focusing_NMO",
                            "horizontal_focusing_NMO", "postmono_slit",
                            "exit_beam_tube", "analyzer_filter"}


def test_all_monitors_present_once_and_in_descriptor_order(diag_all_instrument):
    names = _component_names(diag_all_instrument)
    monitor_names = [m.component_name for m in _IN12_MONITORS]
    assert [n for n in names if n in set(monitor_names)] == monitor_names


def test_monitor_types_and_settings_match_descriptor(diag_all_instrument):
    by_name = {c.name: c for c in diag_all_instrument.component_list}
    for spec in _IN12_MONITORS:
        comp = by_name[spec.component_name]
        assert comp.component_name == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value


def test_plain_build_emits_no_monitors(plain_instrument):
    names = set(_component_names(plain_instrument))
    assert not names & {m.component_name for m in _IN12_MONITORS}


def test_monitor_gating_is_per_monitor():
    instrument = _build(diagnostic_mode=True,
                        diagnostic_settings={"Detector PSD": True})
    names = set(_component_names(instrument))
    assert "detector_PSD" in names
    assert not names & {m.component_name for m in _IN12_MONITORS
                        if m.component_name != "detector_PSD"}


def test_backbone_beam_order_with_every_soller_inserted():
    names = _component_names(_build(alpha_1="10", alpha_2="30", alpha_3="40",
                                    alpha_4="60"))
    assert ([n for n in names if n in set(_BEAM_ORDER_COLLIMATED)]
            == _BEAM_ORDER_COLLIMATED)


def test_open_sollers_leave_the_beam_entirely():
    """Open is withdrawn, not divergence == 0.

    IN12's primary Soller is an optional 30 mm-wide aperture assembly halfway
    between the guide exit and the monochromator, at a PLACEHOLDER position: it
    must not be sitting in the default open beam. A zero-divergence
    ``Collimator_linear`` only loses its angular transmission function -- the
    two rectangular apertures stay and absorb.
    """
    assert not set(_component_names(_build())) & set(_SOLLERS)


def test_each_soller_is_independent():
    """Inserting one blade must not drag its neighbours into the beam."""
    slots = {"mono_collimator": "alpha_1", "sample_collimator": "alpha_2",
             "analyzer_collimator": "alpha_3", "detector_collimator": "alpha_4"}
    for inserted, slot in slots.items():
        names = set(_component_names(_build(**{slot: "30"})))
        assert names & set(_SOLLERS) == {inserted}


def test_both_crystals_are_first_order_only():
    """The status record claims an order-clean beam; the tree must deliver it.

    The default source is the broadband Maxwellian branch (``dE`` normalizes,
    it does not cut), and ``Monochromator_curved`` at its default ``order=0``
    reflects at every multiple of the supplied reciprocal-lattice vector -- so
    the velocity selector and Be filter this model omits are not what excludes
    a lambda/2 component. ``order=1`` is.
    """
    by_name = {c.name: c for c in _build().component_list}
    assert by_name["monochromator"].order == 1
    assert by_name["analyzer"].order == 1


def test_collimators_track_selection_including_the_primary_arm():
    collimated = _build(alpha_1="10", alpha_2="30", alpha_3="40", alpha_4="60")
    by_name = {c.name: c for c in collimated.component_list}
    assert by_name["mono_collimator"].divergence == 10.0
    assert by_name["sample_collimator"].divergence == 30.0
    assert by_name["analyzer_collimator"].divergence == 40.0
    assert by_name["detector_collimator"].divergence == 60.0


def test_mono_crystal_matches_descriptor_pg002(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    mono = by_name["monochromator"]
    assert mono.DM == 3.355
    assert mono.NH == 11 and mono.NV == 11
    # 11 slabs + 10 gaps must reconstruct the published 200 x 160 mm face.
    assert mono.zwidth * 11 + 0.0015 * 10 == pytest.approx(0.200)
    assert mono.yheight * 11 + 0.0015 * 10 == pytest.approx(0.160)
    assert mono.reflect == '"HOPG.rfl"' and mono.transmit == '"HOPG.trm"'


def test_conventional_analyzer_is_eleven_lamellae_in_three_rows(plain_instrument):
    """1998: eleven 11 mm vertical lamellae for horizontal focusing, with the
    top and bottom rows tilted for a fixed vertical focus."""
    by_name = {c.name: c for c in plain_instrument.component_list}
    ana = by_name["analyzer"]
    assert ana.DM == 3.355
    assert ana.NH == 11 and ana.NV == 3
    assert ana.zwidth == 0.011                          # published lamella width
    assert ana.zwidth * 11 + ana.gap * 10 == pytest.approx(0.122)
    assert ana.yheight * 3 + ana.gap * 2 == pytest.approx(0.118)


def test_heusler_analyzer_emits_null_reflectivity():
    instrument = _build(anacris="heusler111")
    by_name = {c.name: c for c in instrument.component_list}
    ana = by_name["analyzer"]
    assert ana.DM == 3.44
    assert ana.r0 == 0.3
    assert ana.reflect == '"NULL"' and ana.transmit == '"NULL"'


def test_detector_contract(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    detector = by_name["detector"]
    assert detector.component_name == "Monitor"      # writes detector.dat
    assert detector.xwidth == 0.050                  # 3He tube, 5 cm diameter
    assert detector.yheight == 0.120                 # 12 cm active height


def test_source_is_the_guide_exit_aperture():
    maxwellian = _build(source_type="Maxwellian")
    by_name = {c.name: c for c in maxwellian.component_list}
    source = by_name["source"]
    assert source.component_name == "Source_div_Maxwellian_v2"
    assert source.energy_distribution == 2
    assert source.E0 == "E0_param"
    # H144 exit after the focusing nose: 20 mm wide x 140 mm high.
    assert source.xwidth == 0.020 and source.yheight == 0.140

    mono_source = _build(source_type="Mono")
    by_name = {c.name: c for c in mono_source.component_list}
    assert by_name["source"].energy_distribution == 0
    assert by_name["source"].dE == 2


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
