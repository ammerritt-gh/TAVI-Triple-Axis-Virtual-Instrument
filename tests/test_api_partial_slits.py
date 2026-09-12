"""A partial ``slits_mm`` patch must not KeyError at launch.

Ledger entry 10 (P2) in docs/audits/new-instruments-crystal-bending.md:
``collimation`` and ``modules`` are both refilled from the descriptor when a
patch names only some of their ids (the same defect shape, fixed for
``modules`` by PR #33). ``slits_mm`` was the one container left without a
refill, while every plugin indexes its slit ids directly (e.g.
``instruments/puma/plugin.py``'s ``slits_mm['pbl']``, ``['vbl_hgap']``,
``['dbl_hgap']``) -- so a request naming one declared slit and omitting the
rest was accepted by the parser and then KeyError'd inside
``build_api_launch_state`` on all four instruments.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402

_INSTRUMENT_IDS = [info.id for info in available_instruments()]


@pytest.fixture(params=_INSTRUMENT_IDS)
def controller(request):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(request.param)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=request.param, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def test_a_partial_slits_patch_succeeds_with_omitted_slits_at_defaults(controller):
    """Name one declared slit and omit the rest; the launch state must still
    carry every declared slit id, the omitted ones at their descriptor
    default -- including the tuple-vs-scalar shape the plugins' indexing
    depends on (a two-gap slit is ``(width, height)``, a one-gap slit is a
    bare scalar)."""
    slits = controller.descriptor.slits
    named = slits[0]
    value = (50.0, 20.0) if named.has_width and named.has_height else 50.0

    state = controller.build_api_launch_state({
        "scan_command1": "deltaE 0 1 1",
        "slits_mm": {named.id: value},
    })

    result = state["vals"]["slits_mm"]
    declared_ids = {s.id for s in slits}
    assert set(result) == declared_ids
    assert result[named.id] == value
    for slit in slits:
        if slit.id != named.id:
            width = float(slit.default_width_mm or 0)
            if slit.has_width and slit.has_height:
                assert result[slit.id] == (width, float(slit.default_height_mm or 0))
            else:
                assert result[slit.id] == width


def test_a_partial_patch_reaches_the_plugin_without_a_keyerror(controller):
    """The end the KeyError was raised from: ``build_api_launch_state`` calls
    ``self.instrument.scan_config(...)``, which indexes every slit id the
    descriptor declares directly. Reaching the assertion below already proves
    it did not KeyError."""
    slits = controller.descriptor.slits
    named = slits[0]
    value = (50.0, 20.0) if named.has_width and named.has_height else 50.0

    state = controller.build_api_launch_state({
        "scan_command1": "deltaE 0 1 1",
        "slits_mm": {named.id: value},
    })
    assert state["scan_config"] is not None
