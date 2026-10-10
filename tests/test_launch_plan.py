"""One compile-and-expand at launch: the plan Run compiles is the plan that runs.

Real widgets (offscreen Qt) on IN8. Run collects the docks at the instant it
is pressed and compiles them once (``_compile_launch``); the queued job
carries that plan and its points, so editing a command box or a relative
base afterwards changes nothing that runs, and nothing downstream compiles
or parses a command again.
"""
import contextlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments import rules  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi import utilities  # noqa: E402
from tavi.scan_jobs import ScanJob  # noqa: E402

STH = "sample_rotation_deg"


@contextlib.contextmanager
def _controller(instrument_id="in8"):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def _relative_a3(ctrl, base, command="A3 -1 1 1"):
    """A relative A3 scan typed into box 1 around an A3 field of ``base``."""
    ctrl.set_default_parameters()
    sim, idock = ctrl.window.simulation_dock, ctrl.window.instrument_dock
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("deterministic"))
    idock.omega_edit.setText(repr(float(base)))
    sim.scan_command_1_edit.setText(command)
    sim.scan_command_2_edit.setText("")
    if not sim.relative_1_button.isChecked():
        sim.relative_1_button.click()


def _press_run(ctrl, monkeypatch):
    """Press Run; return the launch states it submitted and the dialogs it raised."""
    submitted, dialogs = [], []
    monkeypatch.setattr(ctrl, "submit_scan_job", lambda launch, source: submitted.append(launch))
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *args, **kwargs: dialogs.append(args[2]))
    ctrl.run_simulation_thread()
    return submitted, dialogs


def _reset(ctrl):
    sim = ctrl.window.simulation_dock
    if sim.relative_1_button.isChecked():
        sim.relative_1_button.click()
    sim.scan_command_1_edit.setText("")
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("mcstas"))
    ctrl.set_default_parameters()


def test_the_plan_compiled_at_launch_is_the_one_executed(monkeypatch, tmp_path):
    """Edit the command box, the relative base and even the frozen command text
    after Run: the job runs the launch's points, and its downstream path never
    builds a plan, expands one or parses a command."""
    with _controller() as ctrl:
        try:
            ctrl.output_directory = str(tmp_path)
            _relative_a3(ctrl, 30.0)
            submitted, dialogs = _press_run(ctrl, monkeypatch)
            assert dialogs == [] and len(submitted) == 1
            launch = submitted[0]
            job = ScanJob(job_id="t-launch-plan", source="gui", launch_state=launch)
            launch = job.launch_state           # what the worker runs: the job's frozen copy

            # After the launch: new text in the box, a new base, new frozen text.
            ctrl.window.simulation_dock.scan_command_1_edit.setText("A3 50 52 1")
            ctrl.window.instrument_dock.omega_edit.setText("99")
            launch["vals"]["scan_command1"] = "H 1 2 1"
            launch["relative_mode_1"] = False

            def refuse(*_args, **_kwargs):
                raise AssertionError("the run compiled or parsed a scan command again")

            for module, name in ((cm, "build_plan"), (cm, "expand"), (cm, "parse_scan_steps"),
                                 (rules, "build_plan"), (rules, "expand"),
                                 (rules, "parse_scan_steps"), (utilities, "parse_scan_steps")):
                monkeypatch.setattr(module, name, refuse)
            seen, real = [], ctrl.instrument.compute_snapshot
            monkeypatch.setattr(ctrl.instrument, "compute_snapshot",
                                lambda plan, point, *a, **k: seen.append(dict(point))
                                or real(plan, point, *a, **k))

            ctrl.run_simulation(launch, job=job)

            assert job.error is None, job.error
            assert [point[STH] for point in seen] == pytest.approx([29.0, 30.0, 31.0])
            assert job.result.variable_1 == STH
            assert job.result.scan_values_1 == pytest.approx([29.0, 30.0, 31.0])
        finally:
            _reset(ctrl)


def test_a_relative_base_edited_between_preview_and_run_runs_from_the_run_time_base(
        monkeypatch):
    """The preview compiles from its own collection; Run collects anew, so an A3
    edited after the preview is the base the scan steps from."""
    with _controller() as ctrl:
        try:
            _relative_a3(ctrl, 30.0)
            _launch, plan, preview = ctrl._preview_launch(
                *(ctrl.window.simulation_dock.scan_command_1_edit.text(), ""))
            assert preview.bases == {1: 30.0} and plan.commands[0].relative
            assert sum(ctrl._count_valid_scan_points("A3 -1 1 1", "")) == 3

            ctrl.window.instrument_dock.omega_edit.setText("40")
            submitted, dialogs = _press_run(ctrl, monkeypatch)

            assert dialogs == [] and len(submitted) == 1
            expansion = submitted[0]["expansion"]
            assert expansion.bases == {1: 40.0}
            assert [point[STH] for point in expansion.points] == pytest.approx([39.0, 40.0, 41.0])
        finally:
            _reset(ctrl)


def test_an_empty_relative_base_field_refuses_the_run_naming_it(monkeypatch):
    """Empty the A3 field under a relative A3 scan and press Run: refused, naming
    the field, nothing queued and no field or instrument readout moved. An empty
    field the plan reads as typed (K beside an H scan) refuses the same way;
    one it does not read (H in an A3 scan) is no issue."""
    with _controller() as ctrl:
        try:
            idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
            _relative_a3(ctrl, 30.0)
            idock.omega_edit.setText("")
            edits = list(ctrl._plan_input_edits().values())
            texts = [edit.text() for edit in edits]
            readouts = dict(ctrl.instrument_state.stage_readouts())
            jobs = len(ctrl._job_registry.all_jobs())

            submitted, dialogs = _press_run(ctrl, monkeypatch)

            assert submitted == [] and len(dialogs) == 1, (submitted, dialogs)
            assert dialogs[0].startswith("Command 1 steps relative to A3 (sample rotation), "
                                         "but its field holds no number to step from."), dialogs
            assert [edit.text() for edit in edits] == texts
            assert ctrl.instrument_state.stage_readouts() == readouts
            assert len(ctrl._job_registry.all_jobs()) == jobs

            ctrl.window.simulation_dock.relative_1_button.click()        # absolute from here
            idock.omega_edit.setText("30")
            ctrl.window.simulation_dock.scan_command_1_edit.setText("H 1 1.1 0.1")
            sdock.K_edit.setText("")
            submitted, dialogs = _press_run(ctrl, monkeypatch)
            assert submitted == [] and dialogs[0].startswith(
                "K is used as typed, but the launch state holds no number for it."), dialogs

            sdock.K_edit.setText("0")
            sdock.H_edit.setText("")
            ctrl.window.simulation_dock.scan_command_1_edit.setText("A3 29 31 1")
            submitted, dialogs = _press_run(ctrl, monkeypatch)
            assert dialogs == [] and len(submitted) == 1
        finally:
            _reset(ctrl)


# --- Ruling 5: a scan that selects no geometry holds the motors -------------------

MOTOR_FIELDS = {"mono_two_theta_deg": "mtt_edit", "sample_two_theta_deg": "stt_edit",
                "sample_rotation_deg": "omega_edit", "analyzer_two_theta_deg": "att_edit",
                "sample_lower_arc_deg": "sgl_edit", "sample_upper_arc_deg": "sgu_edit"}
MOTOR_META = {"mono_two_theta_deg": "mtt", "sample_two_theta_deg": "stt",
              "sample_rotation_deg": "sth", "analyzer_two_theta_deg": "att",
              "sample_lower_arc_deg": "sgl", "sample_upper_arc_deg": "sgu"}


def _run_snapshots(ctrl, monkeypatch, tmp_path, command=""):
    """Press Run with ``command`` in box 1; the launch's plan and its points' snapshots."""
    sim = ctrl.window.simulation_dock
    if sim.relative_1_button.isChecked():
        sim.relative_1_button.click()
    sim.scan_command_1_edit.setText(command)
    submitted, dialogs = _press_run(ctrl, monkeypatch)
    assert dialogs == [] and len(submitted) == 1, dialogs
    launch = submitted[0]
    plan = launch["plan"]
    return plan, [ctrl.instrument.compute_snapshot(plan, point, i, launch["scan_config"],
                                                   launch["vals"], str(tmp_path))
                  for i, point in enumerate(launch["expansion"].points)], launch


def _hkl_snapshot(ctrl, launch, tmp_path):
    """The point the pre-plan no-scan Run ran: the HKL fields, re-solved."""
    from instruments.rules import HKL_CALC, context_from_state, point_plan

    config, vals = launch["scan_config"], launch["vals"]
    plan = point_plan(context_from_state(config, vals, ctrl.instrument.capabilities()), HKL_CALC)
    point = {"h": vals["H"], "k": vals["K"], "l": vals["L"],
             "energy_transfer_mev": vals["deltaE"]}
    return ctrl.instrument.compute_snapshot(plan, point, 0, config, vals, str(tmp_path))


@pytest.mark.parametrize("command", ["", "rhm 2 3 0.5", "pre_sample_hgap 10 30 10"],
                         ids=["no-scan", "curvature-scan", "slit-scan"])
def test_a_scan_selecting_no_geometry_holds_the_motors_as_typed(command, monkeypatch,
                                                                tmp_path):
    """Ruling 5. With HKL and motors agreeing, a plain Run, a curvature or a slit scan
    give the point the old HKL re-solve gave (to the fields' display rounding).
    With A3 rocked by hand, so that they disagree, they keep A3 and the arcs
    exactly as typed; the HKL re-solve would have moved A3 back."""
    with _controller() as ctrl:
        try:
            ctrl.set_default_parameters()
            idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
            # The motors follow the HKL fields, as the HKL handler sets them.
            hkl = (2.0, 0.0, 0.2)
            for edit, value in zip((sdock.H_edit, sdock.K_edit, sdock.L_edit), hkl):
                edit.setText(repr(value))
            q = ctrl._hkl_to_sample_q(*hkl, ctrl.get_gui_values())
            for edit, value in zip((sdock.qx_edit, sdock.qy_edit, sdock.qz_edit), q):
                edit.setText(repr(float(value)))
            ctrl.update_angles_from_q()
            assert abs(float(idock.sgl_edit.text())) + abs(float(idock.sgu_edit.text())) > 1.0

            plan, snaps, launch = _run_snapshots(ctrl, monkeypatch, tmp_path, command)
            assert plan.calculation == "direct_motors"
            today = _hkl_snapshot(ctrl, launch, tmp_path)
            for snap in snaps:
                assert snap.error_flags == []
                for qid, key in MOTOR_META.items():
                    assert snap.metadata[key] == pytest.approx(today.metadata[key], abs=1e-3), key
                for name in ("mono_two_theta_param", "sample_two_theta_param",
                             "analyzer_two_theta_param", "sample_rx_param", "sample_ry_param",
                             "sample_rz_param", "E0_param"):
                    assert snap.params[name] == pytest.approx(today.params[name], abs=1e-3), name

            # Rock A3 by hand (no handler: HKL stays where it was).
            typed = {qid: float(getattr(idock, edit).text()) for qid, edit in MOTOR_FIELDS.items()}
            typed["sample_rotation_deg"] += 1.5
            idock.omega_edit.setText(repr(typed["sample_rotation_deg"]))
            plan, snaps, launch = _run_snapshots(ctrl, monkeypatch, tmp_path, command)
            assert len(snaps) == (1 if not command else 3)
            for snap in snaps:
                for qid, key in MOTOR_META.items():
                    assert snap.metadata[key] == typed[qid], key
            resolved = _hkl_snapshot(ctrl, launch, tmp_path).metadata["sth"]
            assert resolved == pytest.approx(typed["sample_rotation_deg"] - 1.5, abs=1e-3)
        finally:
            _reset(ctrl)


def test_the_manifest_names_a_locked_points_requested_and_realized_q():
    """Off the lock's plane by less than its tolerance: the point runs at its projection, and the
    manifest keeps the Q asked for beside the in-plane Q the stage reaches."""
    with _controller("puma") as ctrl:
        ctrl.set_default_parameters()
        ctrl.window.ub_matrix_dock.lock_u_edit.setText("1 0 0")
        ctrl.window.ub_matrix_dock.lock_v_edit.setText("0 1 0.2")
        ctrl.on_lock_plane()
        assert ctrl.instrument_state.plane_lock is not None
        launch = ctrl.build_api_launch_state(
            {"scan_command1": "H 1 1 1", "K": 0.5, "L": 0.1001, "deltaE": 0.0})
        entry = ctrl.validate_scan_launch_state(launch)["point_manifest"][0]
    assert entry["feasible"], entry["reason"]
    requested, realized = entry["requested_q_inv_angstrom"], entry["realized_q_inv_angstrom"]
    assert 1e-6 < max(abs(a - b) for a, b in zip(requested, realized)) < 5e-4
