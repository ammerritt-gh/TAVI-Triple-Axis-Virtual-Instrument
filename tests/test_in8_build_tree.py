"""Object-level IN8 build-tree tests (Phase 4; pattern: test_puma_build_tree.py).

Builds through the full plugin path and inspects ``component_list``.
Construction only -- no McStas compile or run. The plugin is used directly
(not through the registry) so these tests are registration-independent.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.in8_plugin import _IN8_MONITORS, IN8Plugin


def _build(sample_key=None, diagnostic_mode=False, diagnostic_settings=None,
           monocris="pg002", source_type="Maxwellian",
           alpha_2="0", alpha_3="0", alpha_4="0"):
    plugin = IN8Plugin()
    diagnostic_settings = diagnostic_settings or {}
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": source_type,
        "source_dE": 2,
        "rhm": 3.0,
        "rvm": 1.2,
        "rha": 1.5,
        "fixed_E": 14.68,
        "monocris": monocris,
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_2": alpha_2, "alpha_3": alpha_3, "alpha_4": alpha_4},
        "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, sample_key, diagnostic_settings,
                                state.sample_mount)
    return plugin.build(config, diagnostic_mode, diagnostic_settings, 100000)


def _component_names(instrument):
    return [c.name for c in instrument.component_list]


@pytest.fixture(scope="module")
def diag_all_instrument():
    enabled = {m.id: True for m in _IN8_MONITORS}
    return _build(sample_key="Al_bragg", diagnostic_mode=True,
                  diagnostic_settings=enabled, alpha_3="30")


@pytest.fixture(scope="module")
def plain_instrument():
    return _build()


_BEAM_ORDER = [
    "origin", "source", "mono_cradle", "monochromator", "sample_arm",
    "sample_collimator", "sample_slit", "sample_gonio", "sample_chi_arm",
    "sample_cradle", "sample_mount", "analyzer_arm", "analyzer_filter",
    "analyzer_collimator", "analyzer_cradle", "analyzer", "detector_arm",
    "detector_collimator", "detector_slit", "detector",
]


def test_backbone_beam_order(plain_instrument):
    """The structural components appear exactly once, in beam order."""
    names = _component_names(plain_instrument)
    assert [n for n in names if n in set(_BEAM_ORDER)] == _BEAM_ORDER


def test_declared_parameters_match_descriptor(plain_instrument):
    from instruments.in8_plugin import _IN8_PARAMS

    declared = {p.name for p in plain_instrument.parameters}
    assert declared == {p.name for p in _IN8_PARAMS}


def test_no_puma_only_components(plain_instrument, diag_all_instrument):
    for instrument in (plain_instrument, diag_all_instrument):
        names = set(_component_names(instrument))
        assert not names & {"v_selector", "NMO_slit", "vertical_focusing_NMO",
                            "horizontal_focusing_NMO", "mono_collimator",
                            "postmono_slit", "exit_beam_tube"}


def test_all_monitors_present_once_and_in_descriptor_order(diag_all_instrument):
    names = _component_names(diag_all_instrument)
    monitor_names = [m.component_name for m in _IN8_MONITORS]
    assert [n for n in names if n in set(monitor_names)] == monitor_names


def test_monitor_types_and_settings_match_descriptor(diag_all_instrument):
    by_name = {c.name: c for c in diag_all_instrument.component_list}
    for spec in _IN8_MONITORS:
        comp = by_name[spec.component_name]
        assert comp.component_name == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value


def test_plain_build_emits_no_monitors(plain_instrument):
    names = set(_component_names(plain_instrument))
    assert not names & {m.component_name for m in _IN8_MONITORS}


def test_monitor_gating_is_per_monitor():
    instrument = _build(diagnostic_mode=True,
                        diagnostic_settings={"Detector PSD": True})
    names = set(_component_names(instrument))
    assert "detector_PSD" in names
    assert not names & {m.component_name for m in _IN8_MONITORS
                        if m.component_name != "detector_PSD"}


def test_collimators_track_selection():
    open_build = _build()
    by_name = {c.name: c for c in open_build.component_list}
    assert by_name["sample_collimator"].divergence == 0.0
    assert by_name["analyzer_collimator"].divergence == 0.0
    assert by_name["detector_collimator"].divergence == 0.0

    collimated = _build(alpha_2="30", alpha_3="40", alpha_4="60")
    by_name = {c.name: c for c in collimated.component_list}
    assert by_name["sample_collimator"].divergence == 30.0
    assert by_name["analyzer_collimator"].divergence == 40.0
    assert by_name["detector_collimator"].divergence == 60.0


def test_mono_crystal_matches_descriptor_pg002(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    mono = by_name["monochromator"]
    assert mono.DM == 3.355
    assert mono.zwidth == 0.025 and mono.yheight == 0.017
    assert mono.NH == 11 and mono.NV == 11
    assert mono.reflect == '"HOPG.rfl"' and mono.transmit == '"HOPG.trm"'
    ana = by_name["analyzer"]
    assert ana.DM == 3.355
    assert ana.NH == 9 and ana.NV == 7


def test_cu200_mono_emits_null_reflectivity():
    instrument = _build(monocris="cu200")
    by_name = {c.name: c for c in instrument.component_list}
    mono = by_name["monochromator"]
    assert mono.DM == 1.807
    assert mono.r0 == 0.7
    assert mono.reflect == '"NULL"' and mono.transmit == '"NULL"'


def test_detector_contract(plain_instrument):
    by_name = {c.name: c for c in plain_instrument.component_list}
    detector = by_name["detector"]
    assert detector.component_name == "Monitor"      # writes detector.dat
    assert detector.xwidth == 0.042                  # 3He tube opening 42x89 mm
    assert detector.yheight == 0.089


def test_source_wiring_mono_vs_maxwellian():
    maxwellian = _build(source_type="Maxwellian")
    by_name = {c.name: c for c in maxwellian.component_list}
    source = by_name["source"]
    assert source.component_name == "Source_div_Maxwellian_v2"
    assert source.energy_distribution == 2
    assert source.E0 == "E0_param"
    assert source.xwidth == 0.030 and source.yheight == 0.120

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
