"""Regression: GET /resolution's check_state must carry module state (D15).

``compute_resolution`` builds a throwaway ``check_state`` to solve the
requested point's own angles and curvature. Before this fix, that state never
received ``vals['modules']``, so PUMA's NMO -- which forces rhm/rvm flat via
``effective_curvature_axis`` -- was invisible to it: with "Vertical" NMO
fitted, the scan itself emits rhm = rvm = 0 (``effective_curvature_axis``
reads the module through the SAME state everywhere else), but GET
/resolution solved a bent-monochromator matrix instead, because its
check_state's module field defaulted to "None".
"""
import contextlib
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


@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def test_resolution_with_nmo_fitted_reads_flat_monochromator_radii():
    """PUMA, NMO="Vertical": GET /resolution's rhm/rvm must be exactly 0,
    matching what the scan itself would emit -- not a bent-mono solve from a
    module-blind check_state."""
    with _controller("puma") as ctrl:
        vals = ctrl._default_parameter_values()
        vals["modules"] = dict(vals["modules"])
        vals["modules"]["nmo"] = "Vertical"
        ctrl.get_gui_values = lambda: dict(vals)

        result = ctrl.compute_resolution()
        assert result["ok"] is True, result

        cfg = result["config"]
        assert cfg["rhm"] == pytest.approx(0.0, abs=1e-9)
        assert cfg["rvm"] == pytest.approx(0.0, abs=1e-9)


def test_resolution_without_nmo_is_unchanged():
    """Same call, no NMO fitted: baseline behaviour (a real, non-zero solved
    monochromator radius) must be untouched by the fix."""
    with _controller("puma") as ctrl:
        vals = ctrl._default_parameter_values()
        ctrl.get_gui_values = lambda: dict(vals)
        assert vals["modules"]["nmo"] == "None"

        result = ctrl.compute_resolution()
        assert result["ok"] is True, result

        cfg = result["config"]
        assert cfg["rhm"] != pytest.approx(0.0, abs=1e-9)
        assert cfg["rvm"] != pytest.approx(0.0, abs=1e-9)
