"""Scan-command names go through the quantity registry: A2 is the mono 2theta, A4 the sample 2theta.

TAVI's old A2 was the sample 2theta and its old A4 the analyzer 2theta, so a name that reads
the same now drives a different axis. These tests run the names through the real controller
paths that build scan points (template, slot table, expansion) and check which quantity moves.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from instruments.tas_runtime import SLOT_SGL, SLOT_SGU  # noqa: E402
from tavi import scan_fits  # noqa: E402

INSTRUMENT_IDS = [info.id for info in available_instruments()]

# canonical ID -> (internal field, scan-point slot, spellings that must all mean it)
ANGLES = {
    "mono_two_theta_deg": ("mtt", 0, ["A2", "a2", "mtt", "MTT", "mono_two_theta_deg"]),
    "sample_two_theta_deg": ("stt", 1, ["A4", "stt", "2theta", "2THETA", "Sample_Two_Theta_Deg"]),
    "sample_rotation_deg": ("omega", 2, ["A3", "omega", "Omega", "psi", "sth"]),
    "analyzer_two_theta_deg": ("att", 3, ["A6", "att", "ATT"]),
    "sample_lower_arc_deg": ("sgl", SLOT_SGL, ["sgl", "SGL"]),
    "sample_upper_arc_deg": ("sgu", SLOT_SGU, ["sgu"]),
}
FIELDS = [field for field, _slot, _names in ANGLES.values()]


class _SyncBridge:
    def call_on_gui(self, fn, timeout=5.0):
        return fn()


def _controller_for(instrument_id):
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


@pytest.fixture(scope="module")
def in8():
    yield from _controller_for("in8")


@pytest.fixture()
def controller(instrument_id):
    yield from _controller_for(instrument_id)


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_every_angle_and_arc_name_scans_the_quantity_it_names(controller, instrument_id, tmp_path,
                                                              monkeypatch):
    ctrl = controller
    defaults = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})["vals"]
    seen = []
    real = ctrl.instrument.check_point_feasibility

    def spy(scan_config, scan_mode, scan_point, vals):
        seen.append((scan_mode, list(scan_point)))
        return real(scan_config, scan_mode, scan_point, vals)

    monkeypatch.setattr(ctrl.instrument, "check_point_feasibility", spy)

    for canonical, (field, slot, names) in ANGLES.items():
        start = float(defaults[field])
        for name in names:
            seen.clear()
            launch = ctrl.build_api_launch_state(
                {"scan_command1": f"{name} {start:.3f} {start + 0.5:.3f} 0.5"})
            result = ctrl.validate_scan_launch_state(launch)
            assert result["per_command"][0]["variable"] == canonical, (instrument_id, name)
            assert [mode for mode, _ in seen] == ["angle", "angle"], (instrument_id, name)

            template = ctrl._build_scan_point_template("angle", launch["vals"])
            moved = {i for i, (a, b) in enumerate(zip(template, seen[1][1])) if a != b}
            assert moved == {slot}, f"{instrument_id}: '{name}' moved slots {moved}, wanted {slot}"

        # The slot is read as the quantity it names: only that one angle differs in the metadata.
        snapshots = [
            ctrl.instrument.compute_snapshot((point, i), i, "angle", launch["scan_config"],
                                             launch["vals"], str(tmp_path)).metadata
            for i, (_mode, point) in enumerate(seen)
        ]
        # `launch` is the last name's, which is a spelling of this same quantity.
        differing = {f for f in FIELDS if snapshots[0][f] != snapshots[1][f]}
        assert differing == {field}, f"{instrument_id}: {canonical} changed {differing}"


@pytest.mark.parametrize("command, fragment", [
    ("phi 0 1 1", "does not have"),
    ("kappa 0 1 1", "does not have"),
    ("chi 0 1 1", "sgl and sgu"),
    ("A1 0 1 1", "not modelled yet; scan A2"),
    ("mth 0 1 1", "not modelled yet; scan A2"),
    ("A5 0 1 1", "not modelled yet; scan A6"),
    ("ath 0 1 1", "not modelled yet; scan A6"),
    ("pre_sample_hgap 1 2 0.5", "slit scans arrive with the point plan"),
    ("detector_vgap 1 2 0.5", "slit scans arrive with the point plan"),
    ("sbl_hgap 1 2 0.5", "pre_sample_vgap"),
    ("vbl_hgap 1 2 0.5", "post_mono_hgap"),
    ("Ei 1 2 1", "cannot be scanned"),
    ("Ki 1 2 1", "cannot be scanned"),
])
def test_refused_names_are_refused_with_the_registry_message(in8, command, fragment):
    hard, _soft = in8._scan_command_issues(command, "")
    assert len(hard) == 1 and fragment in hard[0], hard

    backend = cm.TaviApiBackend(in8, _SyncBridge())
    result = backend.submit_validate({"parameters": {"scan_command1": command}})
    assert result["would_queue"] is False
    assert any(fragment in blocker for blocker in result["blockers"]), result["blockers"]


def test_an_unknown_name_gets_suggestions_from_the_registry(in8):
    hard, _soft = in8._scan_command_issues("sample_rot 0 1 1", "")
    assert len(hard) == 1 and "sample_rotation_deg" in hard[0], hard
    hard, _soft = in8._scan_command_issues("xyz 0 1 1", "")
    assert "Unknown variable 'xyz'" in hard[0] and "A4" in hard[0], hard


@pytest.mark.parametrize("cmd1, cmd2", [
    ("A4 30 31 1", "stt 40 41 1"),
    ("A3 30 31 1", "psi 40 41 1"),
    ("omega 30 31 1", "sth 40 41 1"),
    ("A2 30 31 1", "mtt 40 41 1"),
    ("H 1 1.1 0.1", "A4 30 31 1"),
    ("qx 2 2.1 0.1", "H 1 1.1 0.1"),
    ("sgl 0 1 1", "deltaE 0 1 1"),
    ("sgu 0 1 1", "H 1 1.1 0.1"),
])
def test_conflicting_pairs_are_refused_under_the_new_names(in8, cmd1, cmd2):
    hard, _soft = in8._scan_command_issues(cmd1, cmd2)
    assert len(hard) == 1, (cmd1, cmd2, hard)
    backend = cm.TaviApiBackend(in8, _SyncBridge())
    result = backend.submit_validate(
        {"parameters": {"scan_command1": cmd1, "scan_command2": cmd2}, "force": True})
    assert result["would_queue"] is False and result["blockers"], (cmd1, cmd2)


@pytest.mark.parametrize("cmd1, cmd2", [
    ("A3 30 31 1", "A4 40 41 1"),
    ("A2 30 31 1", "A6 40 41 1"),
    ("A4 30 31 1", "A6 40 41 1"),
    ("H 1 1.1 0.1", "K 0 0.1 0.1"),
])
def test_independent_pairs_stay_compatible(in8, cmd1, cmd2):
    hard, _soft = in8._scan_command_issues(cmd1, cmd2)
    assert [h for h in hard if "Conflict" in h or "Both commands" in h] == [], hard


@pytest.mark.parametrize("name, field", [
    ("A2", "mtt"), ("mtt", "mtt"), ("A4", "stt"), ("stt", "stt"), ("2theta", "stt"),
    ("A6", "att"), ("att", "att"), ("A3", "omega"), ("psi", "omega"), ("sth", "omega"),
])
def test_goto_maps_the_named_quantity_to_its_field(name, field):
    plan = scan_fits.plan_goto(name, 12.5, busy=False)
    assert plan.ok and plan.field == field, plan


@pytest.mark.parametrize("name", ["A1", "A5", "chi", "phi", "pre_sample_hgap"])
def test_goto_refuses_what_a_scan_refuses(name):
    plan = scan_fits.plan_goto(name, 1.0, busy=False)
    assert not plan.ok and plan.field is None


@pytest.mark.parametrize("name, edit", [
    ("A2", "mtt_edit"), ("A4", "stt_edit"), ("A6", "att_edit"), ("psi", "omega_edit"),
])
def test_goto_from_a_scan_drives_the_field_of_the_quantity_it_scanned(in8, name, edit):
    in8.set_default_parameters()
    try:
        widget = getattr(in8.window.instrument_dock, edit)
        target = float(widget.text()) + 0.25
        ok, message = in8.goto_scan_variable(name, target)
        assert ok, message
        assert float(widget.text()) == pytest.approx(target)
    finally:
        in8.set_default_parameters()
