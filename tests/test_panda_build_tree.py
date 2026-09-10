"""Object-level PANDA build-tree tests (pattern: test_in8_build_tree.py).

Builds through the full plugin path and inspects ``component_list``.
Construction only -- no McStas compile or run. The plugin is used directly
(not through the registry) so these tests are registration-independent.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.panda.plugin import _PANDA_MONITORS, PANDAPlugin


def _build(sample_key=None, diagnostic_mode=False, diagnostic_settings=None,
           monocris="pg002", source_type="Maxwellian",
           alpha_1="0", alpha_2="0", alpha_3="0", alpha_4="0"):
    plugin = PANDAPlugin()
    diagnostic_settings = diagnostic_settings or {}
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": source_type,
        "source_dE": 2,
        "rhm": 4.0,
        "rvm": 1.8,
        "rha": 1.65,
        "fixed_E": 4.978451631466585,       # kf = 1.55 A^-1
        "monocris": monocris,
        "anacris": "pg002",
        "modules": {},
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
    "sample_slit", "sample_gonio", "sample_chi_arm", "sample_cradle",
    "sample_mount", "analyzer_arm", "sample_exit_slit",
    "analyzer_cradle", "analyzer", "detector_arm",
    "detector",
]

# The same backbone with all four Sollers inserted.
_BEAM_ORDER_COLLIMATED = [
    "origin", "source", "primary_collimator", "virtual_source",
    "mono_cradle", "monochromator", "sample_arm", "sample_collimator",
    "sample_slit", "sample_gonio", "sample_chi_arm", "sample_cradle",
    "sample_mount", "analyzer_arm", "sample_exit_slit", "analyzer_collimator",
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
        assert not names & {"v_selector", "NMO_slit", "vertical_focusing_NMO",
                            "horizontal_focusing_NMO", "mono_collimator",
                            "postmono_slit", "exit_beam_tube",
                            "analyzer_filter", "detector_slit"}


def test_all_monitors_present_once_and_in_descriptor_order(diag_all_instrument):
    names = _component_names(diag_all_instrument)
    monitor_names = [m.component_name for m in _PANDA_MONITORS]
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


def test_both_crystals_are_first_order_only():
    """PANDA's status record claims an order-clean beam; the tree must deliver it.

    ``Monochromator_curved`` at its default ``order=0`` reflects at every
    multiple of the supplied reciprocal-lattice vector, and the default source
    is the broadband Maxwellian branch, so nothing else here would exclude a
    lambda/2 component. This is the assertion that makes the documented
    "no higher-order contamination" true rather than aspirational.
    """
    by_name = {c.name: c for c in _build().component_list}
    assert by_name["monochromator"].order == 1
    assert by_name["analyzer"].order == 1


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


def test_source_wiring_mono_vs_maxwellian():
    maxwellian = _build(source_type="Maxwellian")
    by_name = {c.name: c for c in maxwellian.component_list}
    source = by_name["source"]
    assert source.component_name == "Source_div_Maxwellian_v2"
    assert source.energy_distribution == 2
    assert source.E0 == "E0_param"
    # The source aperture is the SR-2 guide exit, not a virtual source.
    assert source.xwidth == 0.107 and source.yheight == 0.138

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


def test_maxwellian_de_clears_the_source_init_guard_at_pandas_cold_floor():
    """Source_div_Maxwellian_v2 exits in INITIALIZE when E0 - dE <= 0.

    PANDA's published floor is kf = 1.05 A^-1, i.e. E0 = 2.28 meV, so IN8's
    thermal dE = 3 would abort a routine cold run before any detector data.
    """
    source_dE = _build(source_type="Maxwellian").get_component("source").dE
    e0_floor_meV = 2.072142 * 1.05 ** 2          # kf = 1.05 A^-1
    assert e0_floor_meV - source_dE > 0, (e0_floor_meV, source_dE)


def test_mono_source_de_default_also_clears_the_guard():
    source_dE = _build(source_type="Mono").get_component("source").dE
    assert 2.072142 * 1.05 ** 2 - source_dE > 0
