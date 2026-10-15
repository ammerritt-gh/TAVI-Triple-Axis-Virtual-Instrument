"""A save folder McStas cannot use is refused at Run, before any point starts.

Offscreen Qt with the real window and controller (``api_overrides={"disabled":
True}``). McStas is not run: the plugin's ``build`` and ``run_point`` and the
detector reader are stand-ins, and ``tavi.mcstas_paths.mcstas_path`` is
monkeypatched so each test chooses the form McStas would receive. The refusal's
dialog is replaced too, so no modal box can block a test.

Wall-time budget for this file: a few seconds.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi import mcstas_paths  # noqa: E402
from tavi.scan_jobs import JobState, ScanJob  # noqa: E402

FOLDER = "Müller Probe"  # a space: no McStas form on a drive without short names


@pytest.fixture
def asked(monkeypatch):
    """What McStas would have been asked to do: stand-ins record here and run nothing."""
    calls = []

    def build(*args, **kwargs):
        calls.append("build")
        return "stub-instrument"

    def run_point(instrument, snapshot, output_folder, number_neutrons,
                  execution_state, mpi_count=None):
        calls.append(output_folder)
        os.makedirs(output_folder, exist_ok=True)
        return "stub-detector-data", [], {
            'mode': 'stub', 'returncode': 0, 'stdout': '',
            'binary_path': None, 'output_folder': output_folder,
            'error_message': None, 'launcher_argv': [],
            'armed_direct_run': False,
        }

    monkeypatch.setattr(cm, "read_1Ddetector_file", lambda folder: (1.0, 0.1, 10.0))
    return calls, build, run_point


@pytest.fixture
def controller(monkeypatch, asked):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("puma")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id="puma", save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    _calls, build, run_point = asked
    monkeypatch.setattr(ctrl.instrument, "build", build)
    monkeypatch.setattr(ctrl.instrument, "run_point", run_point)
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture
def dialogs(monkeypatch):
    """Every warning box TAVI would show, recorded instead of shown."""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda parent, title, text, *rest, **kw: shown.append((title, text))))
    return shown


def _launch(ctrl, base, folder, engine=None):
    ctrl.output_directory = str(base)
    launch = ctrl.build_api_launch_state({
        "H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": "deltaE 15 20 5",
    })
    launch["save_folder_input"] = os.path.join(str(base), folder)
    if engine:
        launch["engine"] = engine
    ctrl._compile_launch(launch)
    return launch


def _watch(ctrl):
    """The refusal signal, the scan end and the message-centre lines, in arrival order."""
    events, messages = [], []
    ctrl.mcstas_path_refused.connect(lambda text: events.append(("refused", text)))
    ctrl.scan_completed.connect(lambda: events.append(("completed", None)))
    ctrl.message_printed.connect(messages.append)
    return events, messages


def test_gui_run_is_refused_before_any_point(tmp_path, monkeypatch, asked, dialogs, controller):
    monkeypatch.setattr(mcstas_paths, "mcstas_path", lambda path: None)
    calls = asked[0]
    launch = _launch(controller, tmp_path, FOLDER)
    folder = launch["save_folder_input"]
    events, messages = _watch(controller)
    job = ScanJob(job_id="t-refuse-gui", source="gui", launch_state=launch)

    controller.run_simulation(launch, job=job)

    text = mcstas_paths.refusal_message(folder)
    assert calls == [], calls
    assert not os.path.exists(folder), "the empty run folder was left behind"
    assert os.path.isdir(tmp_path)
    assert job.state == JobState.FAILED and job.error == text
    assert any(text in line for line in messages), messages
    assert events == [("refused", text), ("completed", None)], events
    QApplication.processEvents()
    assert dialogs == [("Cannot save in this folder", text)], dialogs


def test_refusal_dialog_opens_outside_the_drain(dialogs, controller):
    # A modal opened inside _drain_updates would hold the drain and park the scan thread.
    controller._on_mcstas_path_refused("refused text")
    assert dialogs == []
    QApplication.processEvents()
    assert dialogs == [("Cannot save in this folder", "refused text")]


def test_api_run_is_refused_without_a_dialog(tmp_path, monkeypatch, asked, dialogs, controller):
    monkeypatch.setattr(mcstas_paths, "mcstas_path", lambda path: None)
    calls = asked[0]
    launch = _launch(controller, tmp_path, FOLDER)
    folder = launch["save_folder_input"]
    events, messages = _watch(controller)
    job = ScanJob(job_id="t-refuse-api", source="api", launch_state=launch)

    controller.run_simulation(launch, job=job)

    text = mcstas_paths.refusal_message(folder)
    assert calls == [], calls
    assert not os.path.exists(folder)
    assert job.state == JobState.FAILED and job.error == text
    assert any(text in line for line in messages), messages
    assert events == [("completed", None)], events
    assert dialogs == [], dialogs


def test_deterministic_engine_is_never_refused(tmp_path, monkeypatch, asked, dialogs, controller):
    probed = []
    monkeypatch.setattr(mcstas_paths, "mcstas_path", lambda path: probed.append(path))
    launch = _launch(controller, tmp_path, FOLDER, engine="deterministic")
    folder = launch["save_folder_input"]
    events, _messages = _watch(controller)
    job = ScanJob(job_id="t-refuse-det", source="gui", launch_state=launch)

    controller.run_simulation(launch, job=job)

    assert probed == [], "the deterministic engine asked McStas's path check"
    assert not any(kind == "refused" for kind, _ in events), events
    assert dialogs == [], dialogs
    assert os.path.isfile(os.path.join(folder, "scan_parameters.txt"))


def test_safe_folder_runs_and_is_written_under_its_long_name(tmp_path, monkeypatch, asked,
                                                             dialogs, controller):
    monkeypatch.setattr(mcstas_paths, "mcstas_path", lambda path: path)
    calls = asked[0]
    folder = os.path.join(str(tmp_path), "Müller_Straße")
    launch = _launch(controller, tmp_path, "Müller_Straße")
    events, _messages = _watch(controller)
    job = ScanJob(job_id="t-safe", source="gui", launch_state=launch)

    controller.run_simulation(launch, job=job)

    assert calls, "a safe folder never reached McStas"
    assert not any(kind == "refused" for kind, _ in events), events
    assert dialogs == [], dialogs
    assert os.path.isfile(os.path.join(folder, "scan_parameters.txt"))
