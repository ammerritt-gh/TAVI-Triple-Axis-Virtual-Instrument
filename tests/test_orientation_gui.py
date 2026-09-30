"""Offscreen controller checks for the orientation work (one shared controller)."""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from gui.docks.misalignment_dock import encode_misalignment  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.local_state import config_path  # noqa: E402


@pytest.fixture(scope="module")
def controller():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(infos[0].id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture
def messages(controller):
    seen = []
    controller.message_printed.connect(seen.append)
    try:
        yield seen
    finally:
        controller.message_printed.disconnect(seen.append)


def test_restoring_a_misalignment_hash_applies_both_angles(controller, messages):
    path = config_path("parameters.json")
    original = open(path, "rb").read() if os.path.exists(path) else None
    try:
        controller.save_parameters()
        with open(path, "r", encoding="utf-8") as fh:
            document = json.load(fh)
        document[controller.instrument.id]["misalignment_hash_var"] = encode_misalignment(1.5, -0.75)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(document, fh)

        controller.load_parameters()
    finally:
        if original is None:
            os.remove(path)
        else:
            with open(path, "wb") as fh:
                fh.write(original)

    assert not [m for m in messages if "Failed to restore misalignment" in m]
    assert controller.instrument_state.mis_omega == pytest.approx(1.5)
    assert controller.instrument_state.mis_chi == pytest.approx(-0.75)
    assert controller.window.misalignment_dock.get_loaded_misalignment() == pytest.approx((1.5, -0.75))


def test_plane_refresh_failure_reaches_the_message_center(controller, messages, monkeypatch):
    def broken():
        raise RuntimeError("plane probe")

    monkeypatch.setattr(controller.ub_matrix, "get_plane_info", broken)
    controller._update_ub_display()

    assert any("plane probe" in m for m in messages)
