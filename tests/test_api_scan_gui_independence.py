"""GUI-independence of API scan submission (docs/API_SERVER_DESIGN.md sec 8).

POST /scan and POST /validate build their launch state from instrument defaults
overlaid with the request's ``parameters`` patch, reading NO live GUI widgets, so
text a human left in a scan-command widget can never poison an API scan and an
API scan never mutates the GUI. These tests instantiate the real controller with
an offscreen Qt platform (the API server disabled) and drive
``build_api_launch_state`` / ``_default_parameter_values`` directly -- the same
seam ``_submit_scan_on_gui`` / ``_validate_scan_on_gui`` use.
"""
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.scan_jobs import JobState  # noqa: E402


@pytest.fixture(scope="module")
def controller():
    """A real TAVIController on an offscreen Qt platform, API server disabled."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    iid = infos[0].id
    instrument = get_instrument(iid)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=iid, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        del window
        del app


def test_defaults_key_set_matches_gui_values(controller):
    # The widget-free defaults dict must cover exactly get_gui_values()'s keys,
    # so overlaying a patch onto it produces a complete launch vals dict.
    assert set(controller._default_parameter_values().keys()) == \
        set(controller.get_gui_values().keys())


def test_gui_and_api_launch_states_agree_at_the_snapshot_level(tmp_path):
    """A shared key set is not enough (packet slice3a): for the same
    instrument configuration, the GUI-launched and API-launched paths must
    emit the SAME McStas parameters at the same scan point. Before this
    slice they could not agree, because the GUI's Ideal button and the
    API's frozen defaults computed curvature from two independent
    hard-coded copies of PUMA's formula rather than the one producer.

    A fresh controller (not the module-scoped ``controller`` fixture) keeps
    this deterministic: the module toggles (e.g. PUMA's NMO combo) other
    tests in this file leave behind must not leak into a GUI-vs-API
    comparison neither side patches explicitly.
    """
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    iid = infos[0].id
    instrument = get_instrument(iid)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=iid, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        dock = ctrl.window.instrument_dock
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        dock.set_mono_id(mono)
        dock.set_ana_id(ana)
        dock.mtt_edit.setText("41.167")
        dock.att_edit.setText("41.167")
        # rhm/rvm/rha widgets only follow mtt/att when the operator applies
        # the Ideal values (or locks them) -- get_gui_values() reads the
        # widgets as they stand, not a live recompute. Apply here so the GUI
        # side reflects the angles just set, the same as an operator's flow.
        ctrl.apply_ideal_bending_values()

        gui_launch = ctrl._collect_simulation_launch_state()
        api_launch = ctrl.build_api_launch_state({
            "mtt": 41.167, "att": 41.167,
            "monocris": mono, "anacris": ana,
            "modules": gui_launch["vals"]["modules"],
            "scan_command1": "deltaE 0 1 0.5",
        })

        scans = [41.167, 0.0, 0.0, 41.167, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        gui_snapshot = ctrl.instrument.compute_snapshot(
            (scans, 0), 0, "angle", gui_launch["scan_config"], gui_launch["vals"],
            str(tmp_path),
        )
        api_snapshot = ctrl.instrument.compute_snapshot(
            (scans, 0), 0, "angle", api_launch["scan_config"], api_launch["vals"],
            str(tmp_path),
        )
        assert gui_snapshot.error_flags == api_snapshot.error_flags == []
        # abs=5e-4: the GUI's rhm/rvm/rha widgets round-trip through a
        # display-precision text field (a handful of decimals), while the
        # API keeps full float precision -- a real, pre-existing display
        # limit, not something this comparison should chase to bit parity.
        assert gui_snapshot.params == pytest.approx(api_snapshot.params, abs=5e-4)
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def test_scan_command2_widget_does_not_poison_api_scan(controller):
    # Headline regression: junk left in the scan_command_2 widget (never
    # submitted) must not bleed into an API scan that patches only command 1.
    controller.window.simulation_dock.scan_command_2_edit.setText("JUNK 9 9 9")
    launch = controller.build_api_launch_state(
        {"scan_command1": "H 1.9 2.1 0.01"}
    )
    assert launch["vals"]["scan_command1"] == "H 1.9 2.1 0.01"
    assert launch["vals"]["scan_command2"] == ""


def test_missing_scan_command_is_rejected(controller):
    # Defaults carry empty scan commands, so a patch with none is missing_required.
    with pytest.raises(cm.ApiError) as exc:
        controller.build_api_launch_state({})
    assert exc.value.code == "missing_required"
    with pytest.raises(cm.ApiError) as exc2:
        controller.build_api_launch_state({"scan_command1": "   "})
    assert exc2.value.code == "missing_required"


def test_hkl_patch_derives_matching_q(controller):
    # ISAR sends H/K/L and scans deltaE in momentum mode; the momentum-mode scan
    # template reads vals qx/qy/qz, so the HKL->Q derivation must match the
    # sample-mount solve under the (possibly adopted) lattice.
    launch = controller.build_api_launch_state(
        {"H": 1.0, "K": 1.0, "L": 0.0, "scan_command1": "deltaE 0 2 0.5"}
    )
    vals = launch["vals"]
    expected = controller._hkl_to_sample_q(1.0, 1.0, 0.0, vals)
    assert (vals["qx"], vals["qy"], vals["qz"]) == pytest.approx(expected)


def test_build_does_not_mutate_gui(controller):
    # Building an API launch state must leave every live widget untouched.
    before = controller.get_gui_values()
    controller.build_api_launch_state(
        {"H": 3.0, "scan_command1": "K -0.1 0.1 0.02"}
    )
    after = controller.get_gui_values()
    assert before == after


def test_invalid_patch_field_is_rejected(controller):
    with pytest.raises(cm.ApiError) as exc:
        controller.build_api_launch_state(
            {"scan_command1": "H 1.9 2.1 0.01", "Ei": "not-a-number"}
        )
    assert exc.value.code == "invalid_parameters"
    assert "Ei" in exc.value.details["errors"]


@pytest.mark.parametrize("instrument_id", ["puma", "in8", "in12"])
@pytest.mark.parametrize("source", ["api", "gui"])
def test_builtin_launch_state_stays_frozen_through_real_queue_boundary(
        instrument_id, source):
    """Every shipped scan_config satisfies the queue's deepcopy-safe execution contract."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(),
        instrument_infos=infos,
        current_instrument_id=instrument_id,
        save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    captured = {}
    executed = threading.Event()

    def capture_run(launch_state, job):
        captured["launch_state"] = launch_state
        with job.lock:
            job.state = JobState.DONE
            job.notify_state_change()
        executed.set()

    ctrl.run_simulation = capture_run
    try:
        ctrl.instrument_state.mis_omega = 1.25
        ctrl.diagnostic_settings = {
            "Detector PSD": True,
            "nested": {"gain": [1.0]},
        }
        ctrl.background_profile["enabled"] = True
        if source == "api":
            launch = ctrl.build_api_launch_state({
                "H": 1.0,
                "K": 1.0,
                "L": 0.0,
                "scan_command1": "deltaE 0 1 0.5",
            })
            cm.TaviApiBackend._apply_background_to_launch_state(ctrl, launch, None)
        else:
            ctrl.window.simulation_dock.scan_command_1_edit.setText(
                "deltaE 0 1 0.5")
            ctrl.window.simulation_dock.scan_command_2_edit.setText("")
            launch = ctrl._collect_simulation_launch_state()

        expected_h = launch["vals"]["H"]
        expected_mis_omega = launch["scan_config"].mis_omega
        expected_mount = launch["scan_config"].sample_mount.R_mount.copy()
        expected_gain = launch["diagnostic_settings"]["nested"]["gain"][:]
        expected_background_enabled = launch["background"]["enabled"]

        job = ctrl.submit_scan_job(launch, source)

        ctrl.instrument_state.mis_omega = 99.0
        ctrl.diagnostic_settings["nested"]["gain"].append(99.0)
        ctrl.background_profile["enabled"] = False
        launch["vals"]["H"] = 99.0
        launch["scan_config"].mis_omega = 99.0
        launch["scan_config"].sample_mount.R_mount[0, 0] = 99.0
        launch["diagnostic_settings"]["nested"]["gain"].append(99.0)
        launch["background"]["enabled"] = False

        assert executed.wait(timeout=2.0)
        frozen = captured["launch_state"]
        assert frozen is job.launch_state
        assert frozen["vals"]["H"] == expected_h
        assert frozen["scan_config"].mis_omega == expected_mis_omega
        assert frozen["scan_config"].sample_mount.R_mount.tolist() == (
            expected_mount.tolist())
        assert frozen["diagnostic_settings"]["nested"]["gain"] == expected_gain
        assert frozen["background"]["enabled"] is expected_background_enabled
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()
