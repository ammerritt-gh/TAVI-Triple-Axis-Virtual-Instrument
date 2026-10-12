"""Save writes the UB dock's observed peaks; load and a fresh start restore them (audit F2)."""
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402

from test_orientation_gui import _controller_for  # noqa: E402
from tavi.local_state import config_path  # noqa: E402
from tavi.ub_matrix import ObservedPeak  # noqa: E402

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)

# The child builds a controller as the fixture does; startup runs load_parameters.
_CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])
from test_orientation_gui import _controller_for
ctrl = next(_controller_for("in8"))
print("PEAKS=" + json.dumps(ctrl.window.ub_matrix_dock.get_observation_peak_data()))
"""


@pytest.fixture
def controller():
    yield from _controller_for("in8")


@pytest.fixture(autouse=True)
def _restore_parameters_file():
    path = config_path("parameters.json")
    original = None
    if os.path.exists(path):
        with open(path, "rb") as fh:
            original = fh.read()
    yield
    if original is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "wb") as fh:
            fh.write(original)


def _saved_peaks(controller):
    with open(config_path("parameters.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)[controller.instrument.id]["ub_matrix_state"]["peaks"]


def _blank_dock(controller):
    controller.window.ub_matrix_dock.set_peak_entries([])
    controller._reconnect_peak_signals()


def _take_one(controller, hkl):
    """Drive to hkl through the scattering dock, press Take Position on row 0,
    and type the row's HKL, as an operator does; return the row."""
    sdock = controller.window.scattering_dock
    sdock.deltaE_edit.setText("0")
    for edit, value in zip((sdock.H_edit, sdock.K_edit, sdock.L_edit), hkl):
        edit.setText(repr(float(value)))
    controller.on_HKL_changed()
    controller.on_take_peak_position(0)
    pw = controller.window.ub_matrix_dock.get_peak_widget(0)
    for edit, value in zip((pw.h_edit, pw.k_edit, pw.l_edit), hkl):
        edit.setText(repr(float(value)))
    return pw


def test_save_writes_the_taken_peak_and_leaves_the_ub_alone(controller):
    """A Take Position peak with no Calculate UB is saved with every field;
    the save fits nothing and changes neither the UB nor the model's peaks."""
    _blank_dock(controller)
    pw = _take_one(controller, (2, 0, 0))
    pw.lock_check.setChecked(True)
    expected = json.loads(json.dumps(pw.get_peak_data()))
    U_before = controller.ub_matrix.U.copy()
    model_peaks_before = list(controller.ub_matrix.peaks)

    controller.save_parameters()

    saved = _saved_peaks(controller)
    assert len(saved) == 1
    for key in ("hkl", "angles", "ki", "kf", "locked", "sense_sample", "stage"):
        assert saved[0][key] == expected[key], key
    assert np.array_equal(controller.ub_matrix.U, U_before)
    assert controller.ub_matrix.peaks == model_peaks_before


def test_blank_rows_save_no_peaks_and_load_clears_the_dock(controller):
    """Two blank rows are not observations: they save as no peaks even when the
    UB model still holds a peak the dock does not show, and loading that file
    clears a peak the dock holds."""
    _blank_dock(controller)
    controller.ub_matrix.peaks = [ObservedPeak(hkl=(1, 0, 0), angles=(0.0, 0.0, 30.0),
                                               ki=1.5, kf=1.5)]

    controller.save_parameters()

    assert _saved_peaks(controller) == []
    assert len(controller.ub_matrix.peaks) == 1

    _take_one(controller, (0, 2, 0))
    controller.load_parameters()
    assert [p for p in controller.window.ub_matrix_dock.get_all_peak_data() if p["ki"] > 0] == []


def test_a_typed_row_is_an_observation(controller):
    """A row the operator types into is saved, not only one filled by Take Position."""
    _blank_dock(controller)
    QTest.keyClicks(controller.window.ub_matrix_dock.get_peak_widget(0).h_edit, "1")

    controller.save_parameters()

    saved = _saved_peaks(controller)
    assert len(saved) == 1
    assert saved[0]["hkl"][0] == pytest.approx(1.0)


def test_a_fresh_start_restores_the_saved_peak_exactly(controller):
    """A saved peak reloads in a fresh process with every field; the blank row
    that pads the dock is not reported as an observation."""
    _blank_dock(controller)
    pw = _take_one(controller, (2, 0, 0))
    pw.lock_check.setChecked(True)
    controller.save_parameters()
    saved = _saved_peaks(controller)
    assert len(saved) == 1

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    assert env.get("TAVI_CONFIG_DIR"), "the child must read the session's isolated config"
    child = subprocess.run([sys.executable, "-c", _CHILD, TESTS_DIR], env=env, cwd=REPO_ROOT,
                           timeout=120, capture_output=True)
    assert child.returncode == 0, child.stderr.decode("utf-8", "replace")
    line = [ln for ln in child.stdout.decode("utf-8").splitlines() if ln.startswith("PEAKS=")]
    assert line, child.stdout.decode("utf-8", "replace")
    assert json.loads(line[-1][len("PEAKS="):]) == saved
