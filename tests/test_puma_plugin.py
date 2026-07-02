"""PUMA plugin contract tests (docs/CONFIGURABLE_INSTRUMENTS.md §17.7).

Light tests exercise only the import-light plugin module. Tests marked "heavy"
import the legacy PUMA module (which imports mcstasscript at module level) and
skip gracefully when mcstasscript is unavailable.
"""
import os

import pytest

from instruments.contract import InstrumentPlugin, RunExecutionState
from instruments.puma_plugin import PUMA_MCSTAS_NAME, PUMAPlugin, puma_descriptor


# ---------------------------------------------------------------- light tests

def test_plugin_satisfies_protocol():
    assert isinstance(PUMAPlugin(), InstrumentPlugin)


def test_plugin_descriptor_consistency():
    plugin = PUMAPlugin()
    d = plugin.descriptor()
    assert plugin.id == d.id == "puma"
    assert plugin.display_name == d.display_name == "PUMA (FRM-II)"
    assert d.mcstas_name == PUMA_MCSTAS_NAME == "PUMA_McScript"


def test_descriptor_sample_ids_match_gui_sample_map():
    """Descriptor sample ids/labels stay 1:1 with the GUI's sample_map (Phase 1)."""
    d = puma_descriptor()
    by_label = {s.display_name: s.id for s in d.samples}
    assert by_label["No sample"] == "none"
    assert by_label["AL: acoustic phonon"] == "Al_rod_phonon"
    assert by_label["Al: optic phonon"] == "Al_rod_phonon_optic"
    assert by_label["AL: Bragg"] == "Al_bragg"
    assert by_label["Al: Phonon DFT"] == "Al_phonon_DFT"


# ---------------------------------------------------------------- heavy tests

def _gui_vals(**overrides):
    """The instrument-config subset of get_gui_values() the scan config maps."""
    vals = {
        "K_fixed": "Ki Fixed",
        "NMO_installed": "None",
        "V_selector_installed": False,
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 2.5,
        "rvm": 1.2,
        "rha": 2.5,
        "fixed_E": 14.7,
        "monocris": "PG[002]",
        "anacris": "PG[002]",
        "alpha_1": "0",
        "alpha_2_30": True,
        "alpha_2_40": False,
        "alpha_2_60": True,
        "alpha_3": "30",
        "alpha_4": "0",
        "vbl_hgap": 0.088,
        "pbl_hgap": 0.1,
        "pbl_vgap": 0.1,
        "dbl_hgap": 0.05,
    }
    vals.update(overrides)
    return vals


def test_default_state_matches_legacy_defaults():
    pytest.importorskip("mcstasscript")
    from instruments.PUMA_instrument_definition import PUMA_Instrument

    plugin = PUMAPlugin()
    state = plugin.default_state()
    assert isinstance(state, PUMA_Instrument)
    assert state is not plugin.default_state()  # fresh object per call
    assert (state.L1, state.L2, state.L3, state.L4) == (2.150, 2.290, 0.880, 0.750)
    assert state.NMO_installed == "None"
    assert state.V_selector_installed is False
    assert state.source_type == "Maxwellian"


def test_scan_config_applies_gui_mapping():
    pytest.importorskip("mcstasscript")
    plugin = PUMAPlugin()
    base = plugin.default_state()
    base.mis_omega = 1.5          # hidden training state, absent from GUI values
    base_rhm = base.rhm
    mount = object()              # scan_config only assigns it
    diagnostics = {"Detector PSD": True}

    config = plugin.scan_config(base, _gui_vals(), "Al_bragg", diagnostics, mount)

    assert config is not base and base.rhm == base_rhm  # base not mutated
    assert config.mis_omega == 1.5                      # hidden state propagates
    assert config.K_fixed == "Ki Fixed"
    assert (config.rhm, config.rvm, config.rha, config.rva) == (2.5, 1.2, 2.5, 0.8)
    assert config.monocris == config.anacris == "PG[002]"
    assert config.sample_key == "Al_bragg"
    assert config.alpha_1 == 0.0
    assert config.alpha_2 == [30, 0, 60]
    assert config.alpha_3 == 30.0 and config.alpha_4 == 0.0
    assert (config.vbl_hgap, config.pbl_hgap, config.pbl_vgap, config.dbl_hgap) == (
        0.088, 0.1, 0.1, 0.05
    )
    assert config.sample_mount is mount
    assert config.diagnostic_settings.get("Detector PSD") is True


def test_scan_config_nmo_zeroes_mono_bending():
    pytest.importorskip("mcstasscript")
    plugin = PUMAPlugin()
    config = plugin.scan_config(
        plugin.default_state(), _gui_vals(NMO_installed="Vertical"), None, {}, object()
    )
    assert config.NMO_installed == "Vertical"
    assert config.rhm == 0 and config.rvm == 0
    assert config.rha == 2.5  # analyzer bending untouched by the NMO rule


def test_snapshot_params_match_descriptor(tmp_path):
    """docs §16.11: snapshot params keys == descriptor scannable_parameters."""
    pytest.importorskip("mcstasscript")
    plugin = PUMAPlugin()
    state = plugin.default_state()
    state.monocris = "PG[002]"
    state.anacris = "PG[002]"
    state.K_fixed = "Ki Fixed"
    state.fixed_E = 14.7

    # scans layout: mode-specific[0:4], rhm/rvm/rha/rva[4:8], chi/kappa/psi[8:11]
    scans = [41.0, -84.0, -42.0, 83.0, 2.5, 1.2, 2.5, 0.8, 0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
    )

    assert snapshot["error_flags"] == []
    assert snapshot["params"] is not None
    descriptor_names = {p.name for p in plugin.descriptor().scannable_parameters}
    assert set(snapshot["params"]) == descriptor_names
    assert set(snapshot) == {
        "params", "output_folder", "scan_index", "deltaE",
        "error_flags", "metadata", "indices", "log_message",
    }


def test_run_execution_state_is_shared():
    pytest.importorskip("mcstasscript")
    from instruments.PUMA_instrument_definition import PUMARunExecutionState

    assert PUMARunExecutionState is RunExecutionState


def test_binary_fallback_uses_mcstas_name(tmp_path):
    pytest.importorskip("mcstasscript")
    from types import SimpleNamespace

    from instruments.PUMA_instrument_definition import (
        MCSTAS_NAME,
        _resolve_materialized_binary_path,
        data_dir,
    )

    assert MCSTAS_NAME == PUMA_MCSTAS_NAME
    fallback = _resolve_materialized_binary_path(SimpleNamespace(input_path=None, name=None))
    assert fallback == os.path.abspath(os.path.join(data_dir, f"{MCSTAS_NAME}.exe"))
    derived = _resolve_materialized_binary_path(
        SimpleNamespace(input_path=str(tmp_path), name="Foo")
    )
    assert derived == os.path.abspath(os.path.join(str(tmp_path), "Foo.exe"))


# Golden copies of the pre-Phase-2 hard-coded crystal dicts; the descriptor
# adapter must reproduce them exactly (incl. the embedded-quote reflect/transmit
# strings emitted verbatim into the .instr).
_GOLDEN_PG002_MONO = {
    'dm': 3.355, 'slabwidth': 0.0202, 'slabheight': 0.018, 'ncolumns': 13,
    'nrows': 9, 'gap': 0.0005, 'mosaic': 35, 'r0': 1.0,
    'reflect': '"HOPG.rfl"', 'transmit': '"HOPG.trm"',
}
_GOLDEN_PG002_ANA = {
    'da': 3.355, 'slabwidth': 0.01, 'slabheight': 0.0295, 'ncolumns': 21,
    'nrows': 5, 'gap': 0.0005, 'mosaic': 35, 'r0': 1.0,
    'reflect': '"HOPG.rfl"', 'transmit': '"HOPG.trm"',
}


def test_crystal_adapter_matches_golden_dicts():
    pytest.importorskip("mcstasscript")
    from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

    mono, ana = mono_ana_crystals_setup("PG[002]", "PG[002]")
    assert mono == _GOLDEN_PG002_MONO
    assert ana == _GOLDEN_PG002_ANA

    # Test variant: PG[002] geometry, d-spacing 2.355, mono-only.
    mono_test, ana_test = mono_ana_crystals_setup("PG[002] test", "PG[002]")
    assert mono_test == {**_GOLDEN_PG002_MONO, 'dm': 2.355}
    assert ana_test == _GOLDEN_PG002_ANA


def test_crystal_adapter_accepts_ids_and_labels():
    pytest.importorskip("mcstasscript")
    from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

    assert mono_ana_crystals_setup("pg002", "pg002") == mono_ana_crystals_setup(
        "PG[002]", "PG[002]"
    )
    assert mono_ana_crystals_setup("pg002_test", "pg002")[0]['dm'] == 2.355
    # Unknown keys keep the legacy empty-dict behavior.
    assert mono_ana_crystals_setup("nope", "nope") == ({}, {})


def test_crystal_info_matches_legacy():
    pytest.importorskip("mcstasscript")
    from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

    plugin = PUMAPlugin()
    assert plugin.crystal_info("PG[002]", "PG[002]") == mono_ana_crystals_setup(
        "PG[002]", "PG[002]"
    )


def test_build_fingerprint_stable_and_sensitive():
    pytest.importorskip("mcstasscript")
    plugin = PUMAPlugin()
    base = plugin.default_state()
    base.monocris = base.anacris = "pg002"

    fp1 = plugin.build_fingerprint(base)
    fp2 = plugin.build_fingerprint(base)
    assert fp1 == fp2  # deterministic

    changed = plugin.default_state()
    changed.monocris = changed.anacris = "pg002"
    changed.NMO_installed = "Vertical"
    assert plugin.build_fingerprint(changed) != fp1  # build-time change detected
