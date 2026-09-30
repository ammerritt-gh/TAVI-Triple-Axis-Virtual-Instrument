"""Offscreen controller checks for the orientation work (one shared controller)."""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from gui.docks.misalignment_dock import encode_misalignment  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.api_server import ApiError  # noqa: E402
from tavi.local_state import config_path  # noqa: E402
from tavi.tas_geometry import component_q_to_instrument_q  # noqa: E402


class _SyncBridge:
    """Stand-in for ApiBridge: run the marshalled call inline."""

    def call_on_gui(self, fn, timeout=5.0):
        return fn()


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
        # Let the accepted-edit flash timers of API writes finish before the
        # widgets go, or they fire into the next module's event loop.
        QTest.qWait(600)
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


def _reload_with(controller, edit):
    """Save the parameters, let ``edit`` change this instrument's saved block,
    load them back, and restore the file's original bytes."""
    path = config_path("parameters.json")
    original = open(path, "rb").read() if os.path.exists(path) else None
    try:
        controller.save_parameters()
        with open(path, "r", encoding="utf-8") as fh:
            document = json.load(fh)
        edit(document[controller.instrument.id])
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(document, fh)

        controller.load_parameters()
    finally:
        if original is None:
            os.remove(path)
        else:
            with open(path, "wb") as fh:
                fh.write(original)


def test_restoring_a_misalignment_hash_applies_both_angles(controller, messages):
    def edit(block):
        block["misalignment_hash_var"] = encode_misalignment(1.5, -0.75)

    _reload_with(controller, edit)

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


# --- 1.8: the arc readouts sgl / sgu ----------------------------------------------

def _set_q(controller, qx, qy, qz):
    """Type a Q into the scattering dock the way an operator does."""
    dock = controller.window.scattering_dock
    dock.deltaE_edit.setText("0")
    for edit, value in ((dock.qx_edit, qx), (dock.qy_edit, qy), (dock.qz_edit, qz)):
        edit.setText(repr(float(value)))
    controller.on_Q_changed()


def _field(edit):
    return float(edit.text())


def test_saved_chi_var_loads_into_sgl(controller, monkeypatch):
    def edit(block):
        block.pop("sgl_var", None)
        block.pop("sgu_var", None)
        block["chi_var"] = 3.5

    # Restoring the UB re-solves every angle from the saved Q afterwards (as
    # it always re-solved the old chi field); hold that off to see the loader.
    monkeypatch.setattr(controller, "update_angles_from_q", lambda: None)
    _reload_with(controller, edit)

    assert _field(controller.window.instrument_dock.sgl_edit) == pytest.approx(3.5)
    assert _field(controller.window.instrument_dock.sgu_edit) == pytest.approx(0.0)


def test_q_edit_solves_both_arcs_and_reads_back_through_them(controller):
    """A Q lifted out of the plane about the mount z axis needs the upper arc:
    the dock shows it, and the angles -> Q readback goes through both arcs."""
    idock = controller.window.instrument_dock
    q_mount = 2.9 * np.array([math.cos(math.radians(6.0)), math.sin(math.radians(6.0)), 0.0])
    q = component_q_to_instrument_q(q_mount)
    _set_q(controller, *q)
    assert abs(_field(idock.sgu_edit)) == pytest.approx(6.0, abs=1e-3)
    assert _field(idock.sgl_edit) == pytest.approx(0.0, abs=1e-3)

    # Angles are the source of truth now: Q comes back from them.
    sdock = controller.window.scattering_dock
    for edit in (sdock.qx_edit, sdock.qy_edit, sdock.qz_edit):
        edit.setText("0")
    controller.on_angles_changed()
    readback = [_field(e) for e in (sdock.qx_edit, sdock.qy_edit, sdock.qz_edit)]
    assert readback == pytest.approx(list(q), abs=1e-3)


def test_api_chi_write_is_refused_naming_the_arcs(controller):
    backend = cm.TaviApiBackend(controller, _SyncBridge())
    with pytest.raises(ApiError) as patched:
        backend.patch_parameters({"chi": 5.0}, force=True)
    assert patched.value.status == 400
    reason = patched.value.details["errors"]["chi"]
    assert "sgl" in reason and "sgu" in reason

    with pytest.raises(ApiError) as launched:
        controller.build_api_launch_state({"chi": 5.0})
    assert launched.value.status == 400
    assert launched.value.details["errors"]["chi"] == reason


def test_api_arcs_are_writable_fields_in_the_schema(controller):
    backend = cm.TaviApiBackend(controller, _SyncBridge())
    result = backend.patch_parameters({"sgl": 2.5, "sgu": -1.5}, force=True)
    assert set(result["applied"]) == {"sgl", "sgu"}
    idock = controller.window.instrument_dock
    assert (_field(idock.sgl_edit), _field(idock.sgu_edit)) == (2.5, -1.5)

    names = [f["name"] for f in controller.build_api_schema()["fields"]]
    assert {"sgl", "sgu"} <= set(names) and "chi" not in names
    params = controller.get_gui_values()
    assert "chi" not in params and (params["sgl"], params["sgu"]) == (2.5, -1.5)


# --- 1.8 (A6): the arcs as scan variables -------------------------------------------

def test_chi_scan_is_refused_naming_the_arcs(controller):
    hard, _soft = controller._scan_command_issues("chi 0 2 1", "")
    assert len(hard) == 1 and "'sgl'" in hard[0] and "'sgu'" in hard[0]
    backend = cm.TaviApiBackend(controller, _SyncBridge())
    result = backend.submit_validate({"parameters": {"scan_command1": "chi 0 2 1"}})
    assert result["would_queue"] is False
    assert any("'sgl'" in b and "'sgu'" in b for b in result["blockers"])


def test_arc_scan_in_a_q_mode_is_refused_naming_kappa(controller):
    for other in ("H 1.9 2.1 0.1", "qx 2 2.2 0.1", "deltaE 0 2 1"):
        hard, _soft = controller._scan_command_issues("sgl 0 2 1", other)
        assert len(hard) == 1 and "kappa" in hard[0], (other, hard)
    # Alone (or with an angle), an arc scan is an angle-mode scan.
    for pair in (("sgu 0 2 1", ""), ("sgl 0 2 1", "A3 30 31 1")):
        assert controller._scan_command_issues(*pair) == ([], [])
        assert controller._determine_scan_mode(*pair) == "angle"


def test_angle_mode_api_scan_with_arcs_emits_their_rotation(controller, tmp_path):
    """The arcs patched over the API reach the sample arm of an angle-mode scan
    point, composed here from the stage description (A3 about y, sgl about x,
    sgu about z; physical = readout + correction + zero error)."""
    from tavi.tas_geometry import mccode_rotation_matrix

    launch = controller.build_api_launch_state(
        {"sgl": 3.0, "sgu": -2.0, "scan_command1": "A3 35 36 1"})
    assert controller.validate_scan_launch_state(launch)["infeasible"] == []
    vals, config = launch["vals"], launch["scan_config"]
    point = controller._build_scan_point_template("angle", vals)
    point[controller._SCAN_VARIABLE_TO_INDEX["A3"]] = 35.0
    snapshot = controller.instrument.compute_snapshot(
        (point, 0), 0, "angle", config, vals, str(tmp_path))
    params = snapshot.params

    def rot(axis, deg):
        a, t = np.asarray(axis, dtype=float), math.radians(deg)
        k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k)

    stage = (rot((0, 1, 0), 35.0 + config.psi + config.mis_omega)
             @ rot((1, 0, 0), 3.0 + config.kappa + config.mis_chi)
             @ rot((0, 0, 1), -2.0))
    arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                 params["sample_rz_param"])
    assert np.allclose(arm, (stage @ config.sample_mount.R_mount).T, rtol=0.0, atol=1e-12)
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (3.0, -2.0)
