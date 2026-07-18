"""Object-level build-tree tests (design record §19).

Phase 3 made ``build()`` emit monitors/samples/collimators from descriptor
tables, so the old anti-drift source-scans (which regexed the literal blocks)
are replaced by building the instrument through the full plugin path and
inspecting the resulting component tree. Construction only -- **no McStas
compile or run** (``McStas_instr`` + ``add_component`` read component
definitions but never invoke a compiler).
"""
import pytest

pytest.importorskip("mcstasscript")

import instruments.builtin  # noqa: F401
from instruments.puma.plugin import _PUMA_MONITORS, puma_descriptor
from instruments.registry import get_instrument


def _build(sample_key=None, diagnostic_mode=False, diagnostic_settings=None,
           alpha_2=frozenset({"40"}), nmo="None", v_selector=False):
    plugin = get_instrument("puma")
    diagnostic_settings = diagnostic_settings or {}
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Mono",
        "source_dE": 2,
        "rhm": 13.0272,
        "rvm": 1.6102,
        "rha": 2.3034,
        "fixed_E": 14.7,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {"nmo": nmo, "v_selector": v_selector},
        "collimation": {"alpha_1": "40", "alpha_2": set(alpha_2),
                        "alpha_3": "30", "alpha_4": "30"},
        "slits_mm": {"vbl_hgap": 88.0, "pbl": (100.0, 100.0), "dbl_hgap": 50.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, sample_key, diagnostic_settings,
                                state.sample_mount)
    return plugin.build(config, diagnostic_mode, diagnostic_settings, 100000)


def _component_names(instrument):
    return [c.name for c in instrument.component_list]


@pytest.fixture(scope="module")
def diag_all_instrument():
    enabled = {m.id: True for m in _PUMA_MONITORS}
    return _build(sample_key="Al_bragg", diagnostic_mode=True,
                  diagnostic_settings=enabled,
                  alpha_2=frozenset({"30", "40", "60"}))


@pytest.fixture(scope="module")
def plain_instrument():
    return _build()


def test_all_monitors_present_once_and_in_descriptor_order(diag_all_instrument):
    names = _component_names(diag_all_instrument)
    monitor_names = [m.component_name for m in _PUMA_MONITORS]
    assert [n for n in names if n in set(monitor_names)] == monitor_names


def test_monitor_types_and_settings_match_descriptor(diag_all_instrument):
    """Every emitted monitor carries exactly its MonitorSpec settings.

    This includes postmono_Emonitor / postanalyzer_Emonitor sizes -- the two
    legacy copy-paste bugs assigned them to the wrong component (§18.4).
    """
    by_name = {c.name: c for c in diag_all_instrument.component_list}
    for spec in _PUMA_MONITORS:
        comp = by_name[spec.component_name]
        assert comp.component_name == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value, (
                f"{spec.component_name}.{key}: emitted {getattr(comp, key)!r}, "
                f"descriptor {value!r}"
            )


def test_fixed_monitor_sizes_are_crystal_extents(diag_all_instrument):
    by_name = {c.name: c for c in diag_all_instrument.component_list}
    assert by_name["postmono_Emonitor"].xwidth == 0.0202 * 13
    assert by_name["postmono_Emonitor"].yheight == 0.018 * 9
    assert by_name["postanalyzer_Emonitor"].xwidth == 0.01 * 21
    assert by_name["postanalyzer_Emonitor"].yheight == 0.0295 * 5


def test_plain_build_emits_no_monitors(plain_instrument):
    names = set(_component_names(plain_instrument))
    assert not names & {m.component_name for m in _PUMA_MONITORS}


def test_monitor_gating_is_per_monitor():
    instrument = _build(diagnostic_mode=True,
                        diagnostic_settings={"Detector PSD": True})
    names = set(_component_names(instrument))
    assert "detector_PSD" in names
    assert not names & {m.component_name for m in _PUMA_MONITORS
                        if m.component_name != "detector_PSD"}
    # a post-crystal monitor alone must not raise (legacy latent NameError when
    # the pre-crystal monitor's gate was off)
    lone_post = _build(diagnostic_mode=True,
                       diagnostic_settings={"Postmono Emonitor": True,
                                            "Post-analyzer EMonitor": True})
    lone_names = set(_component_names(lone_post))
    assert {"postmono_Emonitor", "postanalyzer_Emonitor"} <= lone_names


def test_descriptor_monitor_order_matches_module_table():
    assert tuple(puma_descriptor().monitors) == tuple(_PUMA_MONITORS)


def test_alpha2_collimators_follow_selection(diag_all_instrument, plain_instrument):
    all_names = _component_names(diag_all_instrument)   # alpha_2 = {30, 40, 60}
    emitted = [n for n in all_names if n.startswith("sample_collimator_")
               and n != "sample_collimator_dia"]
    assert emitted == ["sample_collimator_40", "sample_collimator_60",
                       "sample_collimator_30"]  # physical beam order

    default_names = _component_names(plain_instrument)  # alpha_2 = {40}
    assert "sample_collimator_40" in default_names
    assert "sample_collimator_60" not in default_names
    assert "sample_collimator_30" not in default_names


def test_alpha2_table_matches_descriptor_slot():
    from instruments.puma.model import _ALPHA2_COLLIMATORS

    slot = next(s for s in puma_descriptor().collimation if s.id == "alpha_2")
    assert {d for d, *_ in _ALPHA2_COLLIMATORS} == {int(v) for v in slot.allowed}


@pytest.mark.parametrize("sample_id", [
    "Al_rod_phonon", "Al_rod_phonon_optic", "Al_bragg", "Al_phonon_DFT",
])
def test_sample_emission_matches_library_spec(sample_id):
    from tavi.sample_library import default_sample_library

    spec = next(s for s in default_sample_library() if s.id == sample_id)
    instrument = _build(sample_key=sample_id)
    name = spec.component_name or spec.id
    comp = next(c for c in instrument.component_list if c.name == name)
    assert comp.component_name == spec.component_type
    for key, value in spec.properties.items():
        assert getattr(comp, key) == value, f"{name}.{key}"
    if spec.split is not None:
        assert str(spec.split) in str(comp.SPLIT)
    if spec.extend:
        assert spec.extend in comp.EXTEND


def test_no_sample_build_warns_and_adds_nothing(capsys, plain_instrument):
    from tavi.sample_library import default_sample_library

    sample_names = {s.component_name or s.id for s in default_sample_library()
                    if s.component_type is not None}
    instrument = _build(sample_key=None)
    assert not sample_names & set(_component_names(instrument))
    assert "Warning: No sample selected" in capsys.readouterr().out
    # sanity: mount hierarchy still present
    for arm in ("sample_gonio", "sample_chi_arm", "sample_cradle", "sample_mount"):
        assert arm in _component_names(plain_instrument)


def test_horizontal_nmo_offset_applies_only_when_both_units_are_installed():
    horizontal_only = _build(nmo="Horizontal")
    both = _build(nmo="Both")
    horizontal = next(
        component for component in horizontal_only.component_list
        if component.name == "horizontal_focusing_NMO"
    )
    horizontal_after_vertical = next(
        component for component in both.component_list
        if component.name == "horizontal_focusing_NMO"
    )

    assert horizontal.AT_data[2] == pytest.approx(1.29)
    assert horizontal.LEnd == pytest.approx(1.0)
    assert horizontal_after_vertical.AT_data[2] == pytest.approx(1.441)
    assert horizontal_after_vertical.LEnd == pytest.approx(0.849)
