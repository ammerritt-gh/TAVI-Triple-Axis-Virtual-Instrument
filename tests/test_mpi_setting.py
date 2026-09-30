"""Issue #45: the MPI process count is a setting (default 4), not a fixed 30.

Qt-free: the settings file round trip and the same-count estimate filter.
Offscreen Qt: the Config menu, its dialog, and that every McStas run path
and estimate uses the count frozen when the scan was launched.

Every test points ``TAVI_CONFIG_DIR`` at its own ``tmp_path`` first: the
session copy of ``config/`` may already hold the operator's own count.
"""
import contextlib
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.runtime_tracker import RuntimeTracker  # noqa: E402
from tavi.scan_jobs import ScanJob  # noqa: E402


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVI_CONFIG_DIR", str(tmp_path))
    return tmp_path


@contextlib.contextmanager
def _controller(instrument_id="puma"):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    window.controller = ctrl  # main() does this by hand
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def _spy_estimates(monkeypatch, ctrl):
    """Record the kwargs (plus the calling method) of every estimate call."""
    calls = []
    real = ctrl.runtime_tracker.estimate_scan_seconds

    def spy(*args, **kwargs):
        calls.append(dict(kwargs, caller=sys._getframe(1).f_code.co_name))
        return real(*args, **kwargs)

    monkeypatch.setattr(ctrl.runtime_tracker, "estimate_scan_seconds", spy)
    return calls


def _mcstas_counts(calls):
    return [c.get("mpi_count") for c in calls if c.get("engine", "mcstas") == "mcstas"]


# ---- Qt-free --------------------------------------------------------------

def test_default_is_4_when_file_or_key_absent(config_dir):
    from tavi.settings import load_mpi_count

    assert load_mpi_count() == 4
    (config_dir / "settings.json").write_text('{"other": 1}', encoding="utf-8")
    assert load_mpi_count() == 4


def test_save_round_trips_and_keeps_other_keys(config_dir):
    from tavi.settings import load_mpi_count, save_mpi_count

    (config_dir / "settings.json").write_text('{"other": 1}', encoding="utf-8")
    save_mpi_count(30)
    assert load_mpi_count() == 30
    data = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
    assert data == {"other": 1, "mpi_count": 30}


@pytest.mark.parametrize("raw", ['{"mpi_count": 0', '{"mpi_count": 0}',
                                 '{"mpi_count": 257}', '{"mpi_count": "8"}',
                                 '{"mpi_count": true}', '[30]'])
def test_invalid_values_fall_back_to_4(config_dir, raw):
    from tavi.settings import load_mpi_count

    (config_dir / "settings.json").write_text(raw, encoding="utf-8")
    assert load_mpi_count() == 4


def test_hand_written_encodings(config_dir):
    from tavi.settings import load_mpi_count

    path = config_dir / "settings.json"
    path.write_bytes('{"mpi_count": 8}'.encode("utf-8-sig"))  # BOM: still read
    assert load_mpi_count() == 8
    path.write_bytes('{"mpi_count": 8}'.encode("utf-16"))  # not UTF-8: default
    assert load_mpi_count() == 4


def test_estimates_use_same_count_history_only(tmp_path):
    tracker = RuntimeTracker(config_path=str(tmp_path / "runtimes.json"))
    for n in (10000, 100000):
        tracker.add_record("puma", 5, n, 20.0, 2.0, 28.0, mpi_count=30)

    assert tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, mpi_count=4
    )["estimated_seconds"] is None
    assert tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, mpi_count=30
    )["estimated_seconds"] is not None

    # A record from before the count was recorded matches any count.
    tracker.add_record("puma", 5, 10000, 20.0, 2.0, 28.0, mpi_count=None)
    assert tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, mpi_count=4
    )["estimated_seconds"] is not None


# ---- Offscreen Qt, real main window + controller --------------------------

def test_config_menu_sits_between_utilities_and_help(config_dir):
    with _controller() as ctrl:
        actions = ctrl.window.menuBar().actions()  # held: the menus hang off them
        titles = [a.text().replace("&", "") for a in actions]
        i = titles.index("Utilities")
        assert titles[i + 1:i + 3] == ["Config", "Help"], titles
        first = actions[i + 1].menu().actions()[0].text().replace("&", "")
        assert first == "MPI processes…"


def test_config_dialog_shows_current_value_and_saves(config_dir, monkeypatch):
    from tavi.settings import load_mpi_count

    captured = {}

    def fake_get_int(parent, title, label, value, lo, hi, *rest, **kw):
        captured.update(label=label, value=value, lo=lo, hi=hi)
        return 8, True

    monkeypatch.setattr(QInputDialog, "getInt", fake_get_int)
    with _controller() as ctrl:
        bar = ctrl.window.menuBar()
        config_action = next(a for a in bar.actions()
                             if a.text().replace("&", "") == "Config")
        config_action.menu().actions()[0].trigger()

        assert captured["value"] == 4
        assert (captured["lo"], captured["hi"]) == (1, 256)
        assert str(os.cpu_count()) in captured["label"]
        assert load_mpi_count() == 8
        assert ctrl.mpi_count == 8
        assert ctrl._collect_simulation_launch_state()["mpi_count"] == 8


def test_scan_runs_at_the_count_frozen_at_launch(config_dir, monkeypatch):
    with _controller() as ctrl:
        ctrl.output_directory = str(config_dir)
        seen = []

        def stub_run_point(instrument, snapshot, output_folder, number_neutrons,
                           execution_state, mpi_count=None):
            seen.append(mpi_count)
            os.makedirs(output_folder, exist_ok=True)
            return "stub-detector-data", [], {
                'mode': 'stub', 'returncode': 0, 'stdout': '',
                'binary_path': None, 'output_folder': output_folder,
                'error_message': None, 'launcher_argv': [],
                'armed_direct_run': False,
            }

        monkeypatch.setattr(ctrl.instrument, "build", lambda *a, **k: "stub-instrument")
        monkeypatch.setattr(ctrl.instrument, "run_point", stub_run_point)
        monkeypatch.setattr(cm, "read_1Ddetector_file", lambda folder: (1.0, 0.1, 10.0))

        ctrl.mpi_count = 7
        launch = ctrl.build_api_launch_state({
            "H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": "deltaE 15 20 5",
        })
        ctrl.mpi_count = 9  # changed after submission: must not leak in
        calls = _spy_estimates(monkeypatch, ctrl)
        job = ScanJob(job_id="t-mpi-frozen", source="api", launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        assert len(seen) >= 2 and all(n == 7 for n in seen), seen
        assert ctrl.runtime_tracker.records["puma"][-1].mpi_count == 7
        # The GUI labels refreshed after the scan rightly read the new setting;
        # only the scan's own estimates must carry the frozen count.
        counts = _mcstas_counts(c for c in calls if c["caller"] == "run_simulation")
        assert counts and all(n == 7 for n in counts), counts


def test_gui_estimates_and_benchmark_use_the_setting(config_dir, monkeypatch):
    with _controller() as ctrl:
        ctrl.mpi_count = 8
        calls = _spy_estimates(monkeypatch, ctrl)
        ctrl._update_scan_estimates()
        plan = ctrl.build_benchmark_plan()
        ctrl.benchmark_crosscheck()
        counts = _mcstas_counts(calls)
        assert counts and all(n == 8 for n in counts), counts

        # A running benchmark keeps the count it started with.
        submitted = []

        class _Job:
            def __init__(self, n):
                self.job_id = f"stub-{n}"

        def stub_submit(launch_state, source):
            submitted.append(launch_state["mpi_count"])
            return _Job(len(submitted))

        monkeypatch.setattr(ctrl, "submit_scan_job", stub_submit)
        ctrl.run_benchmark(plan)
        ctrl.mpi_count = 3
        ctrl._submit_benchmark_stage(plan[0], len(plan))
        assert submitted and all(n == 8 for n in submitted), submitted

        # Its cross-check reads that benchmark's count, not the new setting.
        del calls[:]
        ctrl.benchmark_crosscheck(plan)
        counts = _mcstas_counts(calls)
        assert counts and all(n == 8 for n in counts), counts
