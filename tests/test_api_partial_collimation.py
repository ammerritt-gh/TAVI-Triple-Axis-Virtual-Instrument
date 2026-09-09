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
