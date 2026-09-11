"""Regression: GET /resolution (``TAVIController.compute_resolution``) must
solve curvature at the REQUESTED point, not read whatever radii happen to be
sitting in the GUI fields.

This is the most consequential of three sites this defect hit -- a sibling
campaign repo asks this route for resolution at planner-chosen points and
consumes ``bragg.dE`` for acquisition decisions, so a wrong-point resolution
here is silently wrong, not visibly broken.

Uses IN12 (a negative-branch instrument, per the packet): PUMA takes off
positive at both crystals and would hide a sign error entirely. The adapter's
"arrived signed" warning is the tell for a broken magnitude conversion -- if
it ever fires here, the overlay handed the resolution model a signed radius.
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
from instruments.contract import CurvatureMode  # noqa: E402
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


def _solved_ideal(ctrl, vals, H, K, L, deltaE):
    """Ground truth: solve THIS point's own angles, then its own ideal
    curvature -- independent of ``compute_resolution``, the code under test."""
    qx, qy, qz = ctrl._hkl_to_sample_q(H, K, L, vals)
    check_state = ctrl.instrument.default_state()
    check_state.monocris = vals["monocris"]
    check_state.anacris = vals["anacris"]
    check_state.K_fixed = vals["K_fixed"]
    check_state.fixed_E = vals["fixed_E"]
    angles, error_flags = check_state.calculate_angles(
        qx, qy, qz, deltaE, check_state.fixed_E, check_state.K_fixed,
        check_state.monocris, check_state.anacris,
    )
    assert error_flags == []
    mtt, _stt, _sth, _saz, att = angles
    return check_state.ideal_curvature(
        check_state.monocris, check_state.anacris, mtt / 2, att / 2,
    )


def test_resolution_solves_curvature_at_the_requested_point_not_the_gui_fields():
    """All four axes AUTOFOCUS: the GUI fields hold a wildly different
    (wrong) radius set, as if the operator's widgets were sitting at a
    completely different point. GET /resolution must recompute for the
    REQUESTED (H,K,L,deltaE), not echo those stale field values."""
    with _controller("in12") as ctrl:
        vals = ctrl._default_parameter_values()
        vals["curvature_modes"] = {
            axis: CurvatureMode.AUTOFOCUS
            for axis in ("rhm", "rvm", "rha", "rva")
        }
        # Obviously-wrong "current GUI state" radii -- nowhere near what
        # (H,K,L)=(1,0,0) actually focuses to.
        vals["rhm"] = vals["rvm"] = vals["rha"] = vals["rva"] = 99.0
        ctrl.get_gui_values = lambda: dict(vals)

        H, K, L, deltaE = 1.0, 0.0, 0.0, 0.3
        result = ctrl.compute_resolution(H=H, K=K, L=L, deltaE=deltaE)
        assert result["ok"] is True, result

        expected = _solved_ideal(ctrl, vals, H, K, L, deltaE)
        cfg = result["config"]
        for axis in ("rhm", "rvm", "rha", "rva"):
            assert cfg[axis] == pytest.approx(abs(expected[axis]), abs=1e-6), axis
            assert cfg[axis] != pytest.approx(99.0), (
                f"{axis} echoed the stale GUI field instead of solving "
                "this point's own curvature"
            )

        # The magnitude-conversion guard must never fire: the overlay is
        # responsible for stripping the sign before it reaches the adapter.
        assert not any("arrived signed" in w for w in result["warnings"]), \
            result["warnings"]


def test_resolution_mixed_mode_held_axis_stays_held_autofocus_axis_moves():
    """A HELD axis keeps the operator's own number; an AUTOFOCUS sibling on
    the SAME crystal still recomputes for the requested point. Exercises the
    per-axis branch the packet calls out explicitly."""
    with _controller("in12") as ctrl:
        vals = ctrl._default_parameter_values()
        vals["curvature_modes"] = {
            "rhm": CurvatureMode.HELD,
            "rvm": CurvatureMode.AUTOFOCUS,
            "rha": CurvatureMode.AUTOFOCUS,
            "rva": CurvatureMode.AUTOFOCUS,
        }
        held_rhm = 2.5
        vals["rhm"] = held_rhm
        vals["rvm"] = 99.0
        ctrl.get_gui_values = lambda: dict(vals)

        H, K, L, deltaE = 1.0, 0.0, 0.0, 0.3
        result = ctrl.compute_resolution(H=H, K=K, L=L, deltaE=deltaE)
        assert result["ok"] is True, result

        expected = _solved_ideal(ctrl, vals, H, K, L, deltaE)
        cfg = result["config"]
        # HELD: the operator's own magnitude, untouched by the point solve.
        assert cfg["rhm"] == pytest.approx(held_rhm, abs=1e-9)
        # AUTOFOCUS (same mono crystal, sibling axis): recomputed for this point.
        assert cfg["rvm"] == pytest.approx(abs(expected["rvm"]), abs=1e-6)
        assert cfg["rvm"] != pytest.approx(99.0)

        assert not any("arrived signed" in w for w in result["warnings"]), \
            result["warnings"]
