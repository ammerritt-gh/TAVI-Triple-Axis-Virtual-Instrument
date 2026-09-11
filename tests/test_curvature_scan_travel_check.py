"""D14/D22, Codex-critique acceptance: the curvature-travel check on a scan
command examines EVERY value the command expands to, not just its two
endpoints, and the same check now runs for a relative command too (a
GUI-Run entry-point regression pins that an out-of-travel relative scan
never reaches the job queue).

``curvature_scan_error`` (``instruments.tas_runtime``) is the module-level
helper both ``_validate_single_scan_command`` (the literal-text preflight)
and ``validate_scan_launch_state``'s per-point check now share, reusing
``parse_scan_steps`` for the expansion so this test's numbers are exactly
what execution would run with.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

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


# PUMA declares rhm min_radius_m = 2.0, no declared maximum.


def test_absolute_interior_point_is_refused_though_endpoints_are_legal():
    """PUMA absolute 'rhm 0 2 1' has legal endpoints (0 = flat, 2.0 = the
    declared minimum) but an illegal interior point at 1.0 m -- every
    expanded value must be checked, not just the two endpoints."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id
        hard, _ = ctrl._scan_command_issues("rhm 0 2 1", "", mono, ana)
        assert hard, "the interior point at 1.0 m must hard-block"
        assert "rhm" in hard[0]


def test_relative_interior_point_is_refused_the_same_way():
    """The relative equivalent at current rhm=2.5: offsets -2.5, -1.5, -0.5
    expand to the identical 0.0, 1.0, 2.0 m -- same interior refusal."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id
        hard, _ = ctrl._scan_command_issues(
            "rhm -2.5 -0.5 1", "", mono, ana, relative_1=True,
            current_values={"rhm": 2.5},
        )
        assert hard, "the interior point at 1.0 m must hard-block"
        assert "rhm" in hard[0]


def test_relative_command_on_a_non_numeric_current_value_is_a_hard_issue():
    """No base to expand the offsets against -- a hard issue naming the
    field, not a silent pass-through."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id
        hard, _ = ctrl._scan_command_issues(
            "rhm 0.5 1.0 0.5", "", mono, ana, relative_1=True,
            current_values={"rhm": None},
        )
        assert hard, "a relative command with no numeric base must hard-block"
        assert "rhm" in hard[0]


def test_api_blocking_scan_issues_agrees_on_the_absolute_interior_point_case():
    """The API's ``_blocking_scan_issues`` calls the identical
    ``_scan_command_issues`` gate, so the reachable (always-absolute) API
    scan-submission path refuses the same interior point the GUI does."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id
        vals = {"monocris": mono, "anacris": ana, "modules": {},
                "rhm": 0.0, "rvm": 0.0, "rha": 0.0, "rva": 0.0}
        issues = cm.TaviApiBackend._blocking_scan_issues(
            ctrl, vals, "rhm 0 2 1", "", force=False
        )
        assert issues, "the API path must refuse the same interior point"
        assert "rhm" in issues[0]


def test_out_of_travel_relative_scan_never_enqueues_but_in_travel_does(monkeypatch):
    """Entry-point regression: ``run_simulation_thread`` (the GUI Run
    button's handler) refuses the packet's worked example
    ('rhm -1.9 -1.5 0.1' relative off rhm=2.5, expanding to 0.6-1.0 m,
    below PUMA's 2.0 m minimum) before ``submit_scan_job`` is ever called,
    and lets the in-travel equivalent through."""
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(ana)
        idock.mtt_edit.setText("41.167")
        idock.att_edit.setText("41.167")
        idock.rhm_edit.setText("2.5")

        sdock = ctrl.window.simulation_dock
        sdock.relative_1_button.setChecked(True)
        sdock.scan_command_2_edit.setText("")

        submitted = []
        monkeypatch.setattr(
            ctrl, "submit_scan_job", lambda *a, **k: submitted.append(a)
        )

        sdock.scan_command_1_edit.setText("rhm -1.9 -1.5 0.1")
        ctrl.run_simulation_thread()
        assert submitted == [], "an out-of-travel relative scan must never enqueue"

        sdock.scan_command_1_edit.setText("rhm 0.5 1.0 0.5")
        ctrl.run_simulation_thread()
        assert len(submitted) == 1, "an in-travel relative scan must enqueue"
