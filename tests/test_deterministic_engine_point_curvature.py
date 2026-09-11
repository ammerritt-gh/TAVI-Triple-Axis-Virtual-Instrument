"""Regression: the deterministic engine's per-point resolution kernel
(``TAVIController._run_scan_deterministic``) must use THIS point's own
applied curvature radii, not the frozen launch-time ``vals``.

Curvature became per-point (AUTOFOCUS recomputes at each point's own solved
angles); the deterministic engine kept reading the launch dict, so every
point in a scan was convolved with one launch-time radius set regardless of
where it actually solved to -- changing SIMULATED COUNTS, not just metadata,
because ``evaluate_point`` consumes the resolution.

Runs the real analytic engine end to end through ``TAVIController.run_simulation``
(engine="deterministic"); no McStas involved. A wrapped ``resolution_config``
records the radii each point actually asked the resolution model for.
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


def _spy_resolution_config(ctrl):
    """Wrap ``ctrl.instrument.resolution_config`` to record each call's
    rhm/rvm/rha/rva, still delegating to the real implementation."""
    calls = []
    real = ctrl.instrument.resolution_config

    def _wrapped(vals, q0, w, point_angles=None):
        calls.append(tuple(vals[axis] for axis in ("rhm", "rvm", "rha", "rva")))
        return real(vals, q0, w, point_angles=point_angles)

    ctrl.instrument.resolution_config = _wrapped
    return calls


def test_deterministic_engine_resolution_follows_each_points_own_curvature(tmp_path):
    """A deltaE scan under Kf-Fixed moves Ei (hence mtt) point to point while
    att stays put -- so with every axis AUTOFOCUS, the mono-side radii
    (rhm/rvm) the resolution model is asked for must differ between points,
    while the ana-side radii (rha/rva) stay put."""
    with _controller("panda") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "deltaE 0 3 1.5",
        })
        launch["engine"] = "deterministic"

        calls = _spy_resolution_config(ctrl)
        ctrl.run_simulation(launch, job=None)

        assert len(calls) == 3, calls
        rhm_values = {round(c[0], 6) for c in calls}
        rha_values = {round(c[2], 6) for c in calls}
        assert len(rhm_values) == 3, (
            "the mono-side AUTOFOCUS radius was identical across every "
            "point -- the resolution kernel is still reading the frozen "
            f"launch vals instead of each point's own curvature: {calls}"
        )
        assert len(rha_values) == 1, (
            "the analyzer take-off never moves in this scan, so its "
            f"AUTOFOCUS radius should be constant across points: {calls}"
        )

        # Every radius handed to the resolution model must be a magnitude
        # (PANDA is a negative-branch instrument) -- the overlay's whole job.
        for rhm, rvm, rha, rva in calls:
            assert rhm >= 0 and rvm >= 0 and rha >= 0 and rva >= 0, calls


def test_deterministic_engine_direct_curvature_scan_changes_the_kernel(tmp_path):
    """A scan that directly sweeps rha (a curvature axis) must change the
    resolution kernel at all -- the pre-fix code convolved every point with
    the one frozen rha the launch state carried, so a scanned rha never
    touched the resolution model at all."""
    with _controller("panda") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "rha 1.0 3.0 1.0",
        })
        launch["engine"] = "deterministic"

        calls = _spy_resolution_config(ctrl)
        ctrl.run_simulation(launch, job=None)

        assert len(calls) == 3, calls
        rha_values = [round(c[2], 6) for c in calls]
        assert len(set(rha_values)) == 3, (
            "the scanned rha axis never reached the resolution model -- "
            f"every point still used the frozen launch value: {calls}"
        )
        assert sorted(v for v in rha_values) == pytest.approx([1.0, 2.0, 3.0])
