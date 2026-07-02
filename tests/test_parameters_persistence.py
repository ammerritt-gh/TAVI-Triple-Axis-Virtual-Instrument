"""parameters.json namespacing tests (design record §9, §17).

The load/save methods live on TAVIController (a QObject), so these tests build a
bare instance via __new__ and exercise only the pure-Python helpers -- no Qt
event loop, no widgets. Importing TAVI_PySide6 needs PySide6 + mcstasscript, so
the whole module skips when either is unavailable.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as controller_module


def _controller_stub():
    controller = controller_module.TAVIController.__new__(controller_module.TAVIController)
    controller.instrument = SimpleNamespace(id="puma")
    return controller


def test_namespaced_block_selected_by_instrument_id():
    controller = _controller_stub()
    document = {
        "puma": {"_schema": 1, "mtt_var": "41.167"},
        "in8": {"_schema": 1, "mtt_var": "77.0"},
    }
    assert controller._parameters_block(document)["mtt_var"] == "41.167"


def test_missing_or_malformed_block_gives_empty():
    controller = _controller_stub()
    assert controller._parameters_block({"in8": {"_schema": 1}}) == {}
    assert controller._parameters_block({"puma": "garbage"}) == {}
    assert controller._parameters_block("garbage") == {}


def test_saved_crystal_id_falls_back_to_first():
    resolve = controller_module.TAVIController._saved_crystal_id
    crystals = (
        SimpleNamespace(id="pg002", display_name="PG[002]"),
        SimpleNamespace(id="pg002_test", display_name="PG[002] test"),
    )
    assert resolve("pg002_test", crystals) == "pg002_test"
    assert resolve("unknown", crystals) == "pg002"


def test_saved_collimation_container_roundtrip():
    values = controller_module.TAVIController._saved_collimation_values(
        {"collimation": {"alpha_1": "60", "alpha_2": ["30", "60"]}}
    )
    assert values["alpha_1"] == "60"
    assert values["alpha_2"] == {"30", "60"}   # JSON list -> set
    assert controller_module.TAVIController._saved_collimation_values({}) == {}


def test_saved_slit_values_container_roundtrip():
    values = controller_module.TAVIController._saved_slit_values(
        {"slits_mm": {"vbl_hgap": 80.0, "pbl": [90.0, 95.0]}}
    )
    assert values == {"vbl_hgap": 80.0, "pbl": (90.0, 95.0)}   # JSON list -> tuple
    assert controller_module.TAVIController._saved_slit_values({}) == {}


def test_empty_block_falls_back_to_full_defaults():
    """A legacy flat file (or fresh instrument) must take the defaults path.

    Loading an empty block through the normal path would leave derived values
    like the ideal bending radii at 0 (flat crystals -> low intensity), so
    load_parameters must delegate to set_default_parameters before touching
    any widgets.
    """
    import inspect

    controller = _controller_stub()
    legacy_flat = {"mtt_var": "41.167", "rhm_var": "13.0272"}
    assert controller._parameters_block(legacy_flat) == {}

    source = inspect.getsource(controller_module.TAVIController.load_parameters)
    prelude = source.split("blockSignals", 1)[0]
    assert "if not parameters:" in prelude
    assert "self.set_default_parameters()" in prelude


def test_saved_lattice_wins_over_sample_lattice_adoption():
    """Sample selection adopts the sample's own lattice (SampleSpec.lattice),
    so load_parameters must apply the saved lattice values AFTER the sample
    restore or hand-edited lattices would be lost on reload."""
    import inspect

    source = inspect.getsource(controller_module.TAVIController.load_parameters)
    assert source.index("set_sample_by_key") < source.index("lattice_a_var")

    handler = inspect.getsource(controller_module.TAVIController.on_sample_changed)
    assert "_adopt_sample_lattice" in handler


def test_saved_module_values_container():
    values = controller_module.TAVIController._saved_module_values(
        {"modules": {"nmo": "Both", "v_selector": True}}
    )
    assert values == {"nmo": "Both", "v_selector": True}
    assert controller_module.TAVIController._saved_module_values({}) == {}
