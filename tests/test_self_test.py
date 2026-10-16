"""``TAVI_PySide6.py --self-test``: the verdict and the isolation step.

No McStas runs here; the live run is part of the unit review. The verdict is a
pure function of the job's end state and the files the point left behind, so each
way a point can fail to count is built here as a small folder.
"""
import os

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as cm  # noqa: E402

DETECTOR = (
    "# Format: McCode with text headers\n"
    "# variables: I I_err N\n"
    "12.5 0.5 625\n"
)


def _point(tmp_path, detector=DETECTOR, name="scan_0000"):
    folder = tmp_path / "scan"
    (folder / name).mkdir(parents=True)
    if detector is not None:
        (folder / name / "detector.dat").write_text(detector, encoding="utf-8")
    return str(folder)


def _verdict(folder, state="done", error=None, executed=(True,), skipped=()):
    return cm._self_test_verdict(state, error, list(executed), list(skipped), folder)


def test_completed_point_with_readable_detector_passes(tmp_path):
    ok, reason = _verdict(_point(tmp_path))
    assert ok, reason
    assert "625" in reason


@pytest.mark.parametrize("state", ["failed", "cancelled", "stopped"])
def test_job_not_done_fails_and_names_the_state(tmp_path, state):
    ok, reason = _verdict(_point(tmp_path), state=state, error="mcrun exploded")
    assert not ok
    assert state in reason and "mcrun exploded" in reason


def test_zero_executed_points_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path), executed=(False,))
    assert not ok and "0 point(s) executed" in reason


def test_no_executed_mask_at_all_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path), executed=())
    assert not ok and "executed" in reason


def test_more_than_one_point_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path), executed=(True, True))
    assert not ok and "expected exactly 1" in reason


def test_a_skipped_point_fails_even_if_the_job_is_done(tmp_path):
    ok, reason = _verdict(_point(tmp_path), skipped=[{"index": 0, "reason": "A4 out of range"}])
    assert not ok and "A4 out of range" in reason


def test_missing_detector_file_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path, detector=None))
    assert not ok and "detector.dat" in reason


def test_unreadable_detector_file_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path, detector="# variables: I I_err N\nnot numbers here\n"))
    assert not ok and "unreadable" in reason


def test_detector_without_the_data_header_fails(tmp_path):
    ok, reason = _verdict(_point(tmp_path, detector="# something else\n1 2 3\n"))
    assert not ok and "no readable detector data" in reason


def test_isolation_copies_config_and_redirects_the_variable(tmp_path, monkeypatch):
    root = tmp_path / "tavi"
    real = root / "config"
    real.mkdir(parents=True)
    (real / "parameters.json").write_text('{"keep": 1}', encoding="utf-8")
    monkeypatch.delenv("TAVI_CONFIG_DIR", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")  # restored by monkeypatch afterwards

    work = cm._self_test_isolate(str(root))

    assert os.path.dirname(work) == str(root)
    assert os.path.basename(work).startswith("selftest-")
    copy = os.environ["TAVI_CONFIG_DIR"]
    assert copy == os.path.join(work, "config")
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert (root / "config").exists() and copy != str(real)
    # the copy carries the state, and writing to it leaves the real folder alone
    assert open(os.path.join(copy, "parameters.json"), encoding="utf-8").read() == '{"keep": 1}'
    with open(os.path.join(copy, "parameters.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    assert (real / "parameters.json").read_text(encoding="utf-8") == '{"keep": 1}'


def test_isolation_copies_the_folder_the_variable_names(tmp_path, monkeypatch):
    """The source is "the config folder as resolved now": the override wins over <root>/config."""
    root = tmp_path / "tavi"
    root.mkdir()
    named = tmp_path / "elsewhere"
    named.mkdir()
    (named / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TAVI_CONFIG_DIR", str(named))  # both restored by monkeypatch afterwards
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")

    work = cm._self_test_isolate(str(root))

    assert os.path.isfile(os.path.join(work, "config", "settings.json"))
    assert not (root / "config").exists()  # nothing created at the real default location


def test_isolation_without_any_config_makes_an_empty_copy(tmp_path, monkeypatch):
    root = tmp_path / "tavi"
    root.mkdir()
    monkeypatch.setenv("TAVI_CONFIG_DIR", "")  # empty: no override, so the source is <root>/config (absent)
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")

    work = cm._self_test_isolate(str(root))

    assert os.path.isdir(os.path.join(work, "config"))
    assert not (root / "config").exists()


def test_config_dir_reads_the_variable_at_call_time(tmp_path, monkeypatch):
    """The isolation relies on this: no cached path inside tavi.local_state."""
    from tavi import local_state

    monkeypatch.setenv("TAVI_CONFIG_DIR", str(tmp_path / "a"))
    first = local_state.config_dir()
    monkeypatch.setenv("TAVI_CONFIG_DIR", str(tmp_path / "b"))
    assert local_state.config_dir() != first
    assert local_state.config_dir() == tmp_path / "b"


def test_import_failure_under_self_test_prints_the_verdict_and_exits_1(tmp_path, monkeypatch, capsys):
    exits = []
    monkeypatch.setattr(cm.os, "_exit", exits.append)  # restored after the test; the real exit would end pytest
    try:
        raise ImportError("no module named widgets")
    except ImportError as exc:
        cm._self_test_load_failed(type(exc), exc, exc.__traceback__, str(tmp_path))

    out, err = capsys.readouterr()
    assert exits == [1]
    assert "ImportError" in err  # the traceback still shows
    assert f"Throwaway folder kept for diagnosis: {tmp_path}" in out
    assert "TAVI SELF-TEST FAILED: TAVI could not load: ImportError: no module named widgets" in out
