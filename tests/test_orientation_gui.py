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
    """IN8: the arcs' travel is undocumented (unlimited)."""
    yield from _controller_for("in8")


@pytest.fixture(scope="module")
def in12():
    """IN12: the arcs have documented travel (+/-20 deg)."""
    yield from _controller_for("in12")


def _controller_for(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        # No wait for pending flash timers: they are bound to their fields
        # and die with the window (test_flash_timers_die_with_their_field).
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


@pytest.fixture
def in12_messages(in12):
    seen = []
    in12.message_printed.connect(seen.append)
    try:
        yield seen
    finally:
        in12.message_printed.disconnect(seen.append)


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


def test_flash_timers_die_with_their_field(controller):
    """A field deleted while its accepted-edit flash is pending takes the
    flash timers with it (they are bound to the field, not free closures)."""
    import shiboken6
    from PySide6.QtWidgets import QLineEdit

    flashed, typed = QLineEdit(), QLineEdit()
    flashed.setProperty("original_value", "")
    controller._flash_field_saved(flashed)
    controller._setup_field_feedback(typed)
    typed.setText("1")
    typed.editingFinished.emit()
    QTest.qWait(30)                  # the 300 ms restore of the typed edit is pending
    shiboken6.delete(flashed)
    shiboken6.delete(typed)
    QTest.qWait(600)                 # past every pending flash timer


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


def test_saved_arcs_reload_by_the_omega_rule(controller):
    """The real load path: a saved arc value (a pre-arc save's chi_var reads
    as sgl) survives exactly where the saved omega does. A save carrying a UB
    state (every save writes one) re-solves all the angles from the saved Q."""
    idock = controller.window.instrument_dock
    _set_q(controller, 2.0, 0.4, 0.3)          # out of the plane: needs the arcs

    def pre_arc(block):
        block.pop("sgl_var", None)
        block.pop("sgu_var", None)
        block["chi_var"] = 3.5
        block["omega_var"] = 12.5

    _reload_with(controller, pre_arc)
    vals = controller.get_gui_values()
    angles, flags = controller.instrument_state.calculate_stage_angles(
        vals["qx"], vals["qy"], vals["qz"], vals["deltaE"], vals["fixed_E"],
        vals["K_fixed"], vals["monocris"], vals["anacris"])
    assert flags == [] and max(abs(angles[3]), abs(angles[5])) > 0.5
    shown = [_field(e) for e in (idock.omega_edit, idock.sgl_edit, idock.sgu_edit)]
    assert shown == pytest.approx([angles[2], angles[3], angles[5]], abs=1e-3)

    def pre_arc_without_ub(block):
        pre_arc(block)
        block.pop("ub_matrix_state")
        block["ub_training_hash"] = ""

    _reload_with(controller, pre_arc_without_ub)
    shown = [_field(e) for e in (idock.omega_edit, idock.sgl_edit, idock.sgu_edit)]
    assert shown == pytest.approx([12.5, 3.5, 0.0])


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


# --- 1.7: peaks and Take Position on the stage ------------------------------------

def _take_peaks(controller, hkls):
    """Drive to each HKL through the scattering dock, press Take Position on
    peak i, type its HKL; return each peak's data right after it was taken
    beside the dock's readouts at that moment."""
    dock = controller.window.ub_matrix_dock
    while len(dock._peak_widgets) > len(hkls):
        dock.remove_peak_entry(len(dock._peak_widgets) - 1)
    while len(dock._peak_widgets) < len(hkls):
        dock.add_peak_entry()
    controller._reconnect_peak_signals()
    sdock, idock = controller.window.scattering_dock, controller.window.instrument_dock
    sdock.deltaE_edit.setText("0")
    taken = []
    for index, hkl in enumerate(hkls):
        for edit, value in zip((sdock.H_edit, sdock.K_edit, sdock.L_edit), hkl):
            edit.setText(repr(float(value)))
        controller.on_HKL_changed()
        controller.on_take_peak_position(index)
        pw = dock.get_peak_widget(index)
        for edit, value in zip((pw.h_edit, pw.k_edit, pw.l_edit), hkl):
            edit.setText(repr(float(value)))
        shown = {name: _field(edit) for name, edit in
                 (("A3", idock.omega_edit), ("sgl", idock.sgl_edit), ("sgu", idock.sgu_edit))}
        taken.append((pw, pw.get_peak_data(), shown))
    return taken


def _set_corrections(controller, psi, kappa):
    sam = controller.window.sample_dock
    sam.psi_edit.setText(repr(psi))
    sam.kappa_edit.setText(repr(kappa))


def test_take_position_records_the_stage_and_zero_errors_never_enter(controller):
    """Take Position records every stage readout, the corrections, ki, kf and
    the sense; changing only the hidden zero errors leaves the fitted UB
    unchanged; a saved peak reloads with its record."""
    from tavi.tas_geometry import mccode_rotation_matrix

    gonio = controller.instrument_state.goniometer
    _set_corrections(controller, 1.0, 0.5)
    fits = []
    for mis in ((0.7, -0.4), (-2.0, 1.5)):
        controller.instrument_state.set_misalignment(*mis)
        # The same tilted belief both times, so the peaks need both arcs.
        controller.ub_matrix.set_U(mccode_rotation_matrix(2.0, 10.0, -1.5))
        taken = _take_peaks(controller, [(2, 0, 0), (0, 2, 0)])
        assert all(abs(shown["sgl"]) + abs(shown["sgu"]) > 0.5 for _, _, shown in taken)
        for pw, data, shown in taken:
            assert [label.text() for label in pw.axis_labels] == [f"{ax.name}:" for ax in gonio]
            assert not pw.is_legacy and pw.legacy_label.isHidden()
            record = data["stage"]
            assert record["angles"] == pytest.approx(shown)
            assert record["corrections"] == {"A3": 1.0, "sgl": 0.5, "sgu": 0.0}
            assert record["sense"] == controller.instrument_state.sense_sample
            assert (record["ki"], record["kf"]) == pytest.approx((data["ki"], data["kf"]), abs=1e-4)
            assert set(record) == {"axes", "angles", "corrections", "ki", "kf", "sense"}
        controller.on_calculate_ub()
        fits.append(controller.ub_matrix.U)
    assert np.array_equal(fits[0], fits[1])

    saved = [p.to_dict() for p in controller.ub_matrix.peaks]
    dock = controller.window.ub_matrix_dock
    dock.set_peak_entries(saved)
    for pw, peak in zip(dock._peak_widgets, saved):
        assert not pw.is_legacy
        assert pw.get_peak_data()["stage"] == peak["stage"]


def test_refit_after_a_psi_change_turns_the_ub_by_that_change(controller):
    """In the plane (no arcs) a correction change is exactly a turn of the UB
    about the vertical: peaks taken under psi = 1 and refit under psi = 2 give
    a UB turned by 1 degree, so the same peaks stay at the same dial."""
    controller.instrument_state.set_misalignment(0.0, 0.0)
    controller.ub_matrix.reset_U()
    _set_corrections(controller, 1.0, 0.0)
    _take_peaks(controller, [(2, 0, 0), (0, 2, 0)])
    controller.on_calculate_ub()
    u_at_1 = controller.ub_matrix.U
    _set_corrections(controller, 2.0, 0.0)
    controller.on_calculate_ub()
    turn = controller.ub_matrix.U @ u_at_1.T
    assert math.degrees(math.acos((np.trace(turn) - 1) / 2)) == pytest.approx(1.0, abs=1e-9)
    assert abs(turn[1, 1]) == pytest.approx(1.0, abs=1e-12)     # about the mount vertical


def test_legacy_peaks_load_marked_and_fit_as_before(controller):
    """Peaks without a stage record keep the (omega, chi, 2theta) triple's
    meaning, are marked legacy (derived, not stored) and fit as before."""
    from tavi.tas_geometry import solve_instrument_angles
    from tavi.ub_matrix import ObservedPeak, UBMatrix

    vals = controller.get_gui_values()
    lattice = [vals[f"lattice_{p}"] for p in ("a", "b", "c", "alpha", "beta", "gamma")]
    ub = UBMatrix(*lattice)
    u = np.array([[0.9254165783983234, 0.2146101771427565, -0.3123245560187264],
                  [-0.33682408883346515, 0.843493268656316, -0.41841204441673263],
                  [0.17364817766693036, 0.49240387650610407, 0.8528685319524433]])
    k = vals["Kf"]
    saved = []
    for hkl in [(2, 0, 0), (0, 2, 0), (1, 1, 1)]:
        q = component_q_to_instrument_q(u @ ub.B @ np.array(hkl, dtype=float))
        a = solve_instrument_angles(q, k, k)
        saved.append({"hkl": list(hkl), "angles": [a.sth, a.saz, a.stt], "ki": k, "kf": k,
                      "locked": False})
    dock = controller.window.ub_matrix_dock
    dock.set_peak_entries(saved)
    for pw, peak in zip(dock._peak_widgets, saved):
        data = pw.get_peak_data()
        assert pw.is_legacy and not pw.legacy_label.isHidden()
        assert data["stage"] is None and "legacy" not in data
        assert data["angles"] == pytest.approx(tuple(peak["angles"]), abs=1e-4)

    _set_corrections(controller, 1.5, -0.5)          # a legacy peak ignores them
    controller.on_calculate_ub()
    expected = UBMatrix.from_dict({"lattice": lattice,
                                   "peaks": [ObservedPeak.from_dict(d).to_dict() for d in saved]})
    expected.calculate_U_from_peaks()
    assert np.allclose(controller.ub_matrix.U, expected.U, rtol=0.0, atol=1e-4)
    assert np.allclose(controller.ub_matrix.U, u, rtol=0.0, atol=1e-4)


# --- arc travel reaches the operator (IN12, +/-20 deg) ------------------------------

def test_q_edit_past_arc_travel_reports_the_solver_reason(in12, in12_messages):
    """45 deg of elevation cannot be levelled on +/-20 deg arcs: the Q edit
    leaves the angles alone and says why, in the solver's words."""
    from instruments.tas_runtime import describe_scan_error_flags

    idock = in12.window.instrument_dock
    before = [idock.omega_edit.text(), idock.sgl_edit.text(), idock.sgu_edit.text()]
    # Instrument convention: qz is vertical.
    _set_q(in12, 2.5 * math.cos(math.radians(45)), 0.0, 2.5 * math.sin(math.radians(45)))

    vals = in12.get_gui_values()
    _angles, flags = in12.instrument_state.calculate_stage_angles(
        vals["qx"], vals["qy"], vals["qz"], vals["deltaE"], vals["fixed_E"],
        vals["K_fixed"], vals["monocris"], vals["anacris"])
    reason = describe_scan_error_flags(flags)
    assert "travel is [-20, 20]°" in reason
    assert any(reason in m for m in in12_messages), in12_messages
    assert [idock.omega_edit.text(), idock.sgl_edit.text(), idock.sgu_edit.text()] == before


# The one arc-travel refusal, worded as the solver's own (instruments.tas_runtime).
SGL_PAST_TRAVEL = "sgl needs {:g}° but its travel is [-20, 20]°"


def test_angle_mode_point_past_travel_is_invalid_before_the_run(in12, tmp_path):
    """An IN12 'sgl 18 22 2' scan: 22 deg is past travel in the GUI point
    count, the API validation, and the run's valid mask (ScanResult and the
    scan_initialized signal the display and SSE read), not only mid-run."""
    from tavi.scan_jobs import ScanJob

    in12.output_directory = str(tmp_path)
    in12.window.instrument_dock.sgl_edit.setText("0")
    in12.window.instrument_dock.sgu_edit.setText("0")
    assert in12._count_valid_scan_points("sgl 18 22 2", "") == (2, 1)

    launch = in12.build_api_launch_state({"scan_command1": "sgl 18 22 2"})
    infeasible = in12.validate_scan_launch_state(launch)["infeasible"]
    assert [(p["index"], p["reason"]) for p in infeasible] == [(2, SGL_PAST_TRAVEL.format(22))]

    shown = []
    in12.scan_initialized.connect(lambda *args: shown.append(args[2]))
    launch["engine"] = "deterministic"
    job = ScanJob(job_id="t-arc-travel", source="api", launch_state=launch)
    in12.run_simulation(launch, job=job)
    assert job.result.valid_mask_1 == [True, True, False]
    assert shown == [[True, True, False]]

    # The 2D mask, beside a turntable scan.
    assert in12._count_valid_scan_points("sgl 18 22 2", "A3 30 31 1") == (4, 2)
    launch = in12.build_api_launch_state(
        {"scan_command1": "sgl 18 22 2", "scan_command2": "A3 30 31 1"})
    launch["engine"] = "deterministic"
    job = ScanJob(job_id="t-arc-travel-2d", source="api", launch_state=launch)
    in12.run_simulation(launch, job=job)
    assert job.result.valid_mask_2d == [[True, True, False]] * 2


def test_orientation_scan_is_judged_by_the_solved_arcs(in12, tmp_path):
    """A psi scan solves the arcs from Q per point, so an sgl field past
    travel does not make its points invalid: the GUI count and the run's
    mask agree."""
    from tavi.scan_jobs import ScanJob

    in12.output_directory = str(tmp_path)
    _set_q(in12, 2.0, 0.5, 0.0)
    in12.window.instrument_dock.sgl_edit.setText("25")
    try:
        assert in12._count_valid_scan_points("psi -2 2 1", "") == (5, 0)
        launch = in12.build_api_launch_state({"scan_command1": "psi -2 2 1"})
        launch["engine"] = "deterministic"
        job = ScanJob(job_id="t-psi-arcs", source="api", launch_state=launch)
        in12.run_simulation(launch, job=job)
        assert job.result.valid_mask_1 == [True] * 5
    finally:
        in12.window.instrument_dock.sgl_edit.setText("0")


def test_api_arc_write_past_travel_is_refused_with_the_reason(in12):
    backend = cm.TaviApiBackend(in12, _SyncBridge())
    with pytest.raises(ApiError) as patched:
        backend.patch_parameters({"sgl": 25.0}, force=True)
    assert patched.value.status == 400
    reason = patched.value.details["errors"]["sgl"]
    assert reason.endswith(SGL_PAST_TRAVEL.format(25)), reason
    with pytest.raises(ApiError) as launched:
        in12.build_api_launch_state({"sgl": 25.0})
    assert launched.value.status == 400
    assert launched.value.details["errors"]["sgl"] == reason
    assert backend.patch_parameters({"sgl": 20.0}, force=True)["applied"] == ["sgl"]
    backend.patch_parameters({"sgl": 0.0}, force=True)


@pytest.mark.parametrize("bad", ["inf", "nan"])
def test_non_finite_arc_is_refused_with_a_plain_reason(controller, messages, bad):
    """IN8's arcs have unlimited travel, so finiteness is checked on its own:
    the API refuses the write, the GUI refuses the edit and restores the field."""
    reason = f"sgl must be a finite angle, not {bad}"
    backend = cm.TaviApiBackend(controller, _SyncBridge())
    with pytest.raises(ApiError) as patched:
        backend.patch_parameters({"sgl": bad}, force=True)
    assert patched.value.status == 400
    assert patched.value.details["errors"]["sgl"].endswith(reason)

    idock = controller.window.instrument_dock
    before = controller.instrument_state.sgl
    idock.sgl_edit.setText(bad)
    controller.on_arc_changed()
    assert any(reason in m for m in messages), messages
    assert controller.instrument_state.sgl == before
    assert float(idock.sgl_edit.text()) == before


def test_gui_arc_edit_past_travel_reports_the_reason(in12, in12_messages):
    """The field keeps what was typed (an angle-mode run refuses it later)."""
    idock = in12.window.instrument_dock
    idock.sgl_edit.setText("25")
    in12.on_arc_changed()
    assert any(SGL_PAST_TRAVEL.format(25) in m for m in in12_messages), in12_messages
    assert idock.sgl_edit.text() == "25" and in12.instrument_state.sgl == 25.0
    idock.sgl_edit.setText("0")
    in12.on_arc_changed()
