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
