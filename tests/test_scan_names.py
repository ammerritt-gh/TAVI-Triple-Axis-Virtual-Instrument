"""Scan-command names go through the quantity registry: A2 is the mono 2theta, A4 the sample 2theta.

TAVI's old A2 was the sample 2theta and its old A4 the analyzer 2theta, so a name that reads
the same now drives a different axis. These tests run the names through the real controller
paths that build scan points (the launch's compiled plan and its points) and check which
quantity moves.
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
from tavi import scan_fits  # noqa: E402

INSTRUMENT_IDS = [info.id for info in available_instruments()]

# canonical ID -> (internal field, spellings that must all mean it)
ANGLES = {
    "mono_two_theta_deg": ("mtt", ["A2", "a2", "mtt", "MTT", "mono_two_theta_deg"]),
    "sample_two_theta_deg": ("stt", ["A4", "stt", "2theta", "2THETA", "Sample_Two_Theta_Deg"]),
    "sample_rotation_deg": ("omega", ["A3", "omega", "Omega", "psi", "sth"]),
    "analyzer_two_theta_deg": ("att", ["A6", "att", "ATT"]),
    "sample_lower_arc_deg": ("sgl", ["sgl", "SGL"]),
    "sample_upper_arc_deg": ("sgu", ["sgu"]),
}
FIELDS = [field for field, _names in ANGLES.values()]


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

    def spy(scan_config, plan, scan_point):
        seen.append((plan, dict(scan_point)))
        return real(scan_config, plan, scan_point)

    monkeypatch.setattr(ctrl.instrument, "check_point_feasibility", spy)

    for canonical, (field, names) in ANGLES.items():
        start = float(defaults[field])
        for name in names:
            seen.clear()
            launch = ctrl.build_api_launch_state(
                {"scan_command1": f"{name} {start:.3f} {start + 0.5:.3f} 0.5"})
            result = ctrl.validate_scan_launch_state(launch)
            assert result["per_command"][0]["variable"] == canonical, (instrument_id, name)
            assert [plan.calculation for plan, _ in seen] == ["direct_motors"] * 2, (
                instrument_id, name)

            typed = launch["snapshot"]
            moved = {qid for qid, value in seen[1][1].items() if value != typed[qid]}
            assert moved == {canonical}, f"{instrument_id}: '{name}' moved {moved}"

        # The point is read as the quantity it names: only that one angle differs in the metadata.
        snapshots = [
            ctrl.instrument.compute_snapshot(plan, point, i, launch["scan_config"],
                                             launch["vals"], str(tmp_path)).metadata
            for i, (plan, point) in enumerate(seen)
        ]
        # `launch` is the last name's, which is a spelling of this same quantity.
        differing = {f for f in FIELDS if snapshots[0][f] != snapshots[1][f]}
        assert differing == {field}, f"{instrument_id}: {canonical} changed {differing}"


RELATIVE_BASES = {"mono_two_theta_deg": 11.0, "sample_two_theta_deg": 22.0,
                  "sample_rotation_deg": 33.0, "analyzer_two_theta_deg": 44.0}


@pytest.mark.parametrize("name, canonical", [
    ("A2", "mono_two_theta_deg"), ("mono_two_theta_deg", "mono_two_theta_deg"),
    ("A4", "sample_two_theta_deg"), ("sample_two_theta_deg", "sample_two_theta_deg"),
    ("A3", "sample_rotation_deg"), ("sample_rotation_deg", "sample_rotation_deg"),
    ("A6", "analyzer_two_theta_deg"), ("analyzer_two_theta_deg", "analyzer_two_theta_deg"),
])
def test_relative_angle_scan_starts_from_its_own_field(in8, name, canonical):
    launch = in8.build_api_launch_state({"scan_command1": f"{name} 1 2 1", **RELATIVE_BASES})
    launch["relative_mode_1"] = True
    first = in8.validate_scan_launch_state(launch)["per_command"][0]["values"][0]
    assert first == pytest.approx(RELATIVE_BASES[canonical] + 1.0), name


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
    with pytest.raises(cm.PlanRefused):
        in8._preview_launch(cmd1, cmd2)
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
    assert in8._scan_command_issues(cmd1, cmd2) == ([], [])
    plan = in8._preview_launch(cmd1, cmd2)[1]
    assert [c.text for c in plan.commands] == [cmd1, cmd2]


@pytest.mark.parametrize("name, field", [
    ("A2", "mono_two_theta_deg"), ("mtt", "mono_two_theta_deg"),
    ("A4", "sample_two_theta_deg"), ("stt", "sample_two_theta_deg"),
    ("2theta", "sample_two_theta_deg"),
    ("A6", "analyzer_two_theta_deg"), ("att", "analyzer_two_theta_deg"),
    ("A3", "sample_rotation_deg"), ("psi", "sample_rotation_deg"),
    ("sth", "sample_rotation_deg"),
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


def test_angle_scan_message_names_each_angle_as_the_dock_labels_it(tmp_path):
    """The per-point message reads each angle under its dock label's number, not the internal A1..A4."""
    from instruments.in8.plugin import IN8Plugin
    from instruments.tas_runtime import MOTORS, compute_scan_snapshot
    from plan_helpers import motors_point, plan_for

    plugin, vals = IN8Plugin(), {"deltaE": 0.0}
    state = plugin.default_state()
    snapshot = compute_scan_snapshot(
        plan_for(plugin, state, vals, MOTORS, scanned=("mono_two_theta_deg",)),
        motors_point(40.0, 44.0, 22.0, 80.0), 0, state, vals, str(tmp_path),
    )
    line = snapshot.log_message.splitlines()[0]
    for part in ("A2 (mono 2θ): 40", "A4 (sample 2θ): 44", "A3 (sample rotation): 22",
                 "A6 (analyzer 2θ): 80"):
        assert part in line, line
