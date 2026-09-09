"""A partial collimation patch must not delete the slots it omits.

``apply_parameters`` merges a request field-by-field, so a patched container
object replaces the previous one wholesale. A client sending only the slots it
wants to change therefore dropped the rest -- and every plugin's
``scan_config`` indexes each slot the descriptor declares, so the moment an
instrument gains a slot (IN8's ``alpha_1``), every previously valid partial
request became a ``KeyError``.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import get_instrument  # noqa: E402


@pytest.fixture(scope="module")
def in8_controller():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("in8")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=[],
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        window.close()


def test_partial_collimation_patch_keeps_the_omitted_slots(in8_controller):
    state = in8_controller.build_api_launch_state(
        {"scan_command1": "sc h 2 0 0 0 0 1", "collimation": {"alpha_2": "30"}}
    )
    collimation = state["vals"]["collimation"]

    declared = {slot.id for slot in in8_controller.descriptor.collimation}
    assert set(collimation) == declared
    assert collimation["alpha_2"] == "30"
    # Everything the request did not name keeps its descriptor default.
    for slot in in8_controller.descriptor.collimation:
        if slot.id != "alpha_2":
            assert collimation[slot.id] == slot.default


def test_a_partial_patch_still_reaches_scan_config(in8_controller):
    """The end the KeyError was raised from."""
    state = in8_controller.build_api_launch_state(
        {"scan_command1": "sc h 2 0 0 0 0 1", "collimation": {"alpha_3": "40"}}
    )
    plugin = get_instrument("in8")
    base = plugin.default_state()
    config = plugin.scan_config(base, state["vals"], None, {}, base.sample_mount)
    assert (config.alpha_1, config.alpha_3) == (0.0, 40.0)


def test_a_fixed_curvature_axis_is_refused_as_a_scan_variable(in8_controller,
                                                              monkeypatch):
    """Refusing beats silently ignoring or silently honouring.

    scan_config pins a fixed radius, but compute_scan_snapshot reads
    scans[4:8] and lets a scan override it, so an accepted scan over a pinned
    axis either does nothing or quietly defeats the pin.
    """
    import dataclasses

    ctrl = in8_controller
    pinned = dataclasses.replace(
        ctrl.descriptor,
        ana_crystals=tuple(dataclasses.replace(c, fixed_curvature=("rva",))
                           for c in ctrl.descriptor.ana_crystals))
    monkeypatch.setattr(ctrl, "descriptor", pinned, raising=False)

    var, warning = ctrl._validate_single_scan_command("rva 0.3 0.6 0.05")
    assert var is None
    assert "fixed on" in warning and "cannot be scanned" in warning
    assert "analyser" in warning          # names the crystal, not the instrument

    # The radii that side really does drive stay scannable.
    var, warning = ctrl._validate_single_scan_command("rha 1.0 2.0 0.1")
    assert var == "rha" and warning is None
    var, warning = ctrl._validate_single_scan_command("rhm 3.0 5.0 0.5")
    assert var == "rhm" and warning is None


def test_the_pin_follows_the_selected_crystal(in8_controller, monkeypatch):
    """Fixed focusing belongs to the crystal assembly, not the instrument.

    IN12 carries a PG(002) analyser with a documented fixed vertical focus and
    a Heusler whose focusing behaviour is unknown; a flag on the instrument
    would assert the first crystal's evidence about the second.
    """
    import dataclasses

    ctrl = in8_controller
    ana = ctrl.descriptor.ana_crystals[0]
    other = dataclasses.replace(ana, id="other", display_name="Other")
    pinned = dataclasses.replace(ana, fixed_curvature=("rva",))
    monkeypatch.setattr(
        ctrl, "descriptor",
        dataclasses.replace(ctrl.descriptor, ana_crystals=(pinned, other)),
        raising=False)

    ctrl.window.instrument_dock.anacris_combo.addItem("Other", "other")

    ctrl.window.instrument_dock.set_ana_id(pinned.id)
    assert ctrl._validate_single_scan_command("rva 0.3 0.6 0.05")[0] is None

    ctrl.window.instrument_dock.set_ana_id("other")
    assert ctrl._validate_single_scan_command("rva 0.3 0.6 0.05")[0] == "rva"

    ctrl.window.instrument_dock.set_ana_id(pinned.id)


def test_nothing_is_refused_when_no_crystal_pins_anything(in8_controller):
    for spec in in8_controller.descriptor.ana_crystals:
        assert spec.fixed_curvature == ()
    var, warning = in8_controller._validate_single_scan_command("rva 0.3 0.6 0.05")
    assert var == "rva" and warning is None
