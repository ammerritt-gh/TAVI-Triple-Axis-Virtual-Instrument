"""A partial collimation patch must not delete the slots it omits.

``apply_parameters`` merges a request field-by-field, so a patched container
object replaces the previous one wholesale. A client sending only the slots it
wants to change therefore dropped the rest -- and every plugin's
``scan_config`` indexes each slot the descriptor declares, so the moment an
instrument gains a slot (IN8's ``alpha_1``), every previously valid partial
request became a ``KeyError``.
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
from instruments.descriptor import CurvatureAxis  # noqa: E402
from instruments.registry import get_instrument  # noqa: E402


def _settle():
    """The labels and marks follow the mark timer: let it run before a label is read."""
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture(scope="module")
def in8_controller():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("in8")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=[],
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        window.close()


def test_partial_collimation_patch_keeps_the_omitted_slots(in8_controller):
    state = in8_controller.build_api_launch_state(
        {"scan_command1": "sc h 2 0 0 0 0 1", "collimation": {"alpha_2": "30"}}
    )
    collimation = state["vals"]["collimation"]

    declared = {slot.id for slot in in8_controller.descriptor.collimation}
    assert set(collimation) == declared
    assert collimation["alpha_2"] == "30"
    # Everything the request did not name keeps its descriptor default.
    for slot in in8_controller.descriptor.collimation:
        if slot.id != "alpha_2":
            assert collimation[slot.id] == slot.default


def test_a_partial_patch_still_reaches_scan_config(in8_controller):
    """The end the KeyError was raised from."""
    state = in8_controller.build_api_launch_state(
        {"scan_command1": "sc h 2 0 0 0 0 1", "collimation": {"alpha_3": "40"}}
    )
    plugin = get_instrument("in8")
    base = plugin.default_state()
    config = plugin.scan_config(base, state["vals"], None, {}, base.sample_mount)
    assert (config.alpha_1, config.alpha_3) == (0.0, 40.0)


def _pin_rva(ctrl, monkeypatch):
    """Give the instrument's analyser a fixed vertical curvature."""
    import dataclasses

    pinned = dataclasses.replace(
        ctrl.descriptor,
        ana_crystals=tuple(
            dataclasses.replace(
                c, curvature={"rva": CurvatureAxis(driven=False, fixed_radius_m=0.05,
                                                    provenance="test fixture")})
            for c in ctrl.descriptor.ana_crystals))
    monkeypatch.setattr(ctrl, "descriptor", pinned, raising=False)
    monkeypatch.setattr(ctrl.instrument_state, "descriptor", lambda: pinned)
    return pinned


def launch_for(ctrl, cmd1, cmd2="", relative=(False, False), **patch):
    """A launch built as the API builds one, each box's relative flag set as given."""
    launch = ctrl.build_api_launch_state({"scan_command1": cmd1, "scan_command2": cmd2, **patch})
    launch["relative_mode_1"], launch["relative_mode_2"] = relative
    return launch


def issues_for(ctrl, cmd1, cmd2="", relative=(False, False), **patch):
    """Run's and the API's per-command gate, ``(hard, soft)``, on that launch."""
    return ctrl._scan_command_issues(launch_for(ctrl, cmd1, cmd2, relative, **patch))


def test_a_fixed_curvature_axis_is_refused_by_the_plan(in8_controller, monkeypatch):
    """The per-command gate leaves a fixed axis to the plan, which names the hardware."""
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    result = cm.TaviApiBackend(ctrl, _SyncBridge()).submit_validate({"parameters": {
        "scan_command1": "rva 0.3 0.6 0.05", "anacris": d.ana_crystals[0].id}})
    assert result["would_queue"] is False
    assert any(b.startswith("scan_validation: Command 1: The hardware holds rva "
                            "(analyzer vertical radius)")
               for b in result["blockers"]), result["blockers"]

    # The radii that side really does drive stay scannable.
    for cmd, expected in (("rha 1.0 2.0 0.1", "analyzer_horizontal_radius_m"),
                          ("rhm 3.0 5.0 0.5", "mono_horizontal_radius_m")):
        launch = launch_for(ctrl, cmd, anacris=d.ana_crystals[0].id)
        _plan, accepted, refused = ctrl._judge_boxes(launch, [(cmd, False), ("", False)])
        assert accepted[1].quantity == expected and refused == {}
        assert ctrl._scan_command_issues(launch) == ([], [])


def test_the_refusal_actually_blocks_the_launch(in8_controller, monkeypatch):
    """The gate is worthless if it only annotates a widget.

    `_scan_command_issues` is what the GUI Run button and the API
    launch path both consult. It used to escalate only messages containing a
    warning marker or the word "Unknown", so this refusal was shown and then
    launched anyway -- and so was every other hard rejection whose wording
    happened to lack the marker.
    """
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    ana = d.ana_crystals[0].id

    result = cm.TaviApiBackend(ctrl, _SyncBridge()).submit_validate(
        {"parameters": {"scan_command1": "rva 0.3 0.6 0.05", "anacris": ana}})
    assert any("cannot be scanned" in b for b in result["blockers"]), (
        "a refused radius must block the launch")

    # A scannable axis still launches.
    assert issues_for(ctrl, "rha 1.0 2.0 0.1", monocris="pg002", anacris=ana) == ([], [])


def test_other_hard_rejections_also_block(in8_controller):
    """The same hole covered these; none of their wordings carry the marker."""
    ctrl = in8_controller
    for cmd in ("rhm 1.0 2.0", "rhm 1.0 2.0 0.1 0.2", "rhm a b c"):
        assert issues_for(ctrl, cmd)[0], cmd


def test_the_pin_follows_the_crystal_the_caller_names(in8_controller, monkeypatch):
    """Fixed focusing belongs to the crystal assembly, not the instrument.

    And the caller decides which crystal: an API request carries its own
    frozen selection, which need not be what the GUI currently shows. Reading
    the dock here would validate an API scan against the wrong crystal.
    """
    import dataclasses

    ctrl = in8_controller
    ana = ctrl.descriptor.ana_crystals[0]
    other = dataclasses.replace(ana, id="other", display_name="Other")
    pinned = dataclasses.replace(
        ana, curvature={"rva": CurvatureAxis(driven=False, fixed_radius_m=0.05,
                                              provenance="test fixture")})
    both = dataclasses.replace(ctrl.descriptor, ana_crystals=(pinned, other))
    monkeypatch.setattr(ctrl, "descriptor", both, raising=False)
    monkeypatch.setattr(ctrl.instrument_state, "descriptor", lambda: both)

    # ...and that difference reaches the launch: the plan refuses the pinned
    # crystal's radius, because the request names that crystal.
    blockers = cm.TaviApiBackend(ctrl, _SyncBridge()).submit_validate({"parameters": {
        "scan_command1": "rva 0.3 0.6 0.05", "anacris": pinned.id}})["blockers"]
    assert any(b.startswith("scan_validation: Command 1: The hardware holds rva")
               for b in blockers)


def test_nothing_is_refused_when_no_crystal_pins_anything(in8_controller):
    for spec in in8_controller.descriptor.ana_crystals:
        assert spec.fixed_curvature == ()
    assert issues_for(in8_controller, "rva 0.3 0.6 0.05",
                      monocris="pg002", anacris="pg002") == ([], [])


def test_a_hard_rejection_is_not_offered_as_a_choice(in8_controller, monkeypatch):
    """The GUI Run path used to show every issue with "continue anyway".

    Answering Yes then launched a scan over a refused axis and overwrote the
    fixed radius it pins, which is the hole the refusal exists to close. Hard
    and soft issues are separated so the Run path can refuse one and ask about
    the other.
    """
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    ana = d.ana_crystals[0].id

    # The pinned radius is the plan's refusal of that command: hard, never offered as a choice.
    hard, soft = issues_for(ctrl, "rva 0.3 0.6 0.05", monocris="pg002", anacris=ana)
    assert len(hard) == 1 and hard[0].startswith("Command 1: The hardware holds rva"), hard
    assert soft == []

    # A very long scan is the operator's call, and stays overridable.
    hard, soft = issues_for(ctrl, "rha 1.0 2.0 0.0001", monocris="pg002", anacris=ana)
    assert hard == []
    assert soft and "⚠" in soft[0]


def test_malformed_commands_are_hard(in8_controller):
    for cmd in ("rhm 1.0 2.0", "rhm 1.0 2.0 0.1 0.2", "rhm a b c", "nope 1 2 3"):
        hard, _ = issues_for(in8_controller, cmd)
        assert hard, cmd


def test_a_step_that_cannot_reach_the_end_is_hard(in8_controller):
    # A zero or wrong-sign step used to come back with its variable and an
    # unmarked message, so it was neither hard nor soft and launched anyway.
    # A step past the whole range would run a point beyond the stated end
    # ("A3 0 10 15" expands to 0 and 15); the API guide calls it an error.
    for cmd in ("A3 0 10 0", "A3 0 10 -1", "A3 10 0 1", "H 1 2 0",
                "A3 0 10 15", "H 1.99 2.01 0.1", "A3 10 0 -15"):
        hard, _ = issues_for(in8_controller, cmd)
        assert hard, cmd


def test_a_step_that_does_not_divide_the_range_is_a_note_not_a_refusal(in8_controller):
    # "A3 0 10 4" stops at 8 and says so; the note blocks nothing and needs no force.
    assert issues_for(in8_controller, "A3 0 10 4") == ([], [])
    assert in8_controller._scan_command_warnings(launch_for(in8_controller, "A3 0 10 4")) == [
        "Command 1: Step 4 does not divide 0 to 10; the scan stops at 8."]
    assert in8_controller._scan_command_warnings(launch_for(in8_controller, "A3 0 10 2")) == []


def test_the_count_warning_counts_the_points_the_truncated_scan_runs(in8_controller):
    # The old count rounded 502.5 steps up to 504 points; the scan runs 503.
    warning, = in8_controller._scan_command_warnings(launch_for(in8_controller, "A3 0 1000 1.99"))
    assert warning.startswith("Command 1: Warning: 503 scan points.")
    assert in8_controller._count_scan_points("A3 0 1000 1.99", "") == 503

    # Over 1000 points the warning is soft, and the stop note rides in the same text.
    hard, soft = issues_for(in8_controller, "A3 0 1000 0.9")
    assert hard == [] and len(soft) == 1
    assert "1112 points" in soft[0] and "stops at 999.9" in soft[0]


def test_the_scan_command_label_shows_the_stop_note_without_blocking(in8_controller):
    dock = in8_controller.window.simulation_dock
    try:
        dock.scan_command_1_edit.setText("A3 0 10 4")
        _settle()
        assert not dock.scan_warning_1_label.isHidden()
        assert "stops at 8" in dock.scan_warning_1_label.text()
        assert in8_controller._preflight_scan_validation() == ([], [])

        dock.scan_command_1_edit.setText("A3 0 10 2")
        _settle()
        assert dock.scan_warning_1_label.isHidden()
    finally:
        dock.scan_command_1_edit.setText("")


def test_the_api_warns_on_an_undivided_step_without_blocking(in8_controller):
    backend = cm.TaviApiBackend(in8_controller, _SyncBridge())
    result = backend.submit_validate({"parameters": {"scan_command1": "A3 0 10 4"}})
    assert result["would_queue"] is True, result["blockers"]
    assert result["blockers"] == []
    assert result["warnings"] == [
        "Command 1: Step 4 does not divide 0 to 10; the scan stops at 8."]

    result = backend.submit_validate({"parameters": {"scan_command1": "A3 0 10 2"}})
    assert result["warnings"] == []


def test_a_queued_undivided_step_carries_the_same_warning(in8_controller, monkeypatch):
    from tavi.scan_jobs import ScanJob

    def submit(launch_state, source):
        job = ScanJob(job_id="j-stop-note", source=source, launch_state=launch_state)
        in8_controller._job_registry.add(job)
        return job

    monkeypatch.setattr(in8_controller, "submit_scan_job", submit)
    body = cm.TaviApiBackend(in8_controller, _SyncBridge()).submit_scan(
        {"parameters": {"scan_command1": "A3 0 10 4"}})
    assert body["warnings"] == [
        "Command 1: Step 4 does not divide 0 to 10; the scan stops at 8."]


def test_the_gui_preflight_returns_the_pair_run_unpacks(in8_controller):
    """The Run path does `hard, soft = self._preflight_scan_validation()`.

    The wrapper was left returning a joined string while its caller was changed
    to unpack two lists, so every click of Run raised ValueError -- including
    with empty or perfectly valid commands. No test drove the Run path, so the
    suite stayed green through it. This pins the contract between them.
    """
    dock = in8_controller.window.simulation_dock
    for cmd in ("", "rhm 3.0 5.0 0.5", "nonsense"):
        dock.scan_command_1_edit.setText(cmd)
        dock.scan_command_2_edit.setText("")
        result = in8_controller._preflight_scan_validation()
        assert isinstance(result, tuple) and len(result) == 2, cmd
        hard, soft = result
        assert isinstance(hard, list) and isinstance(soft, list), cmd

    dock.scan_command_1_edit.setText("")


def _run_refusal(controller, cmd1, cmd2, monkeypatch):
    """Press Run with these commands; return the refusal shown (None if it launched)."""
    from PySide6.QtWidgets import QMessageBox

    dock = controller.window.simulation_dock
    dialogs, submitted = [], []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kw: dialogs.append(args[2]))
    monkeypatch.setattr(controller, "submit_scan_job", lambda launch, source: submitted.append(1))
    dock.scan_command_1_edit.setText(cmd1)
    dock.scan_command_2_edit.setText(cmd2)
    try:
        controller.run_simulation_thread()
    finally:
        dock.scan_command_1_edit.setText("")
        dock.scan_command_2_edit.setText("")
    assert bool(dialogs) != bool(submitted), (dialogs, submitted)
    return dialogs[0] if dialogs else None


def _api_blockers(controller, cmd1, cmd2):
    backend = cm.TaviApiBackend(controller, _SyncBridge())
    result = backend.submit_validate({
        "parameters": {"scan_command1": cmd1, "scan_command2": cmd2}, "force": True})
    assert result["would_queue"] is False
    return result["blockers"]


def test_a_q_versus_hkl_conflict_cannot_be_overridden(in8_controller, monkeypatch):
    """H selects the HKL calculation, which computes Q from it: a Q command
    beside H would be overwritten at every point, so the plan refuses the pair,
    on the GUI Run and over the API with force alike. The gate judges the pair
    as the labels do, so the conflict is a hard issue there too."""
    cmd1, cmd2 = "H 1.99 2.01 0.01", "qx 1.9 2.1 0.1"
    why = ("Q x is calculated from H in the HKL calculation, so it cannot also be scanned. "
           "force does not override a command conflict.")
    assert issues_for(in8_controller, cmd1, cmd2) == ([why], [])
    assert _run_refusal(in8_controller, cmd1, cmd2, monkeypatch).startswith(why)
    assert "scan_validation: " + why in _api_blockers(in8_controller, cmd1, cmd2)
    backend = cm.TaviApiBackend(in8_controller, _SyncBridge())
    with pytest.raises(cm.ApiError) as refused:
        backend.submit_scan({"parameters": {"scan_command1": cmd1, "scan_command2": cmd2},
                             "force": True, "allow_partial": True})
    assert (refused.value.status, refused.value.code) == (400, "scan_validation")
    assert str(refused.value.message) == why


@pytest.mark.parametrize("cmd1, cmd2", [
    ("H 1.99 2.01 0.01", "omega -1 1 0.5"),
    ("deltaE 0 5 1", "omega -1 1 0.5"),
    ("H 1.99 2.01 0.01", "A3 -1 1 0.5"),
    ("qx 1.9 2.1 0.1", "A4 40 41 1"),
])
def test_an_angle_beside_a_q_hkl_or_energy_scan_is_refused_even_forced(
        in8_controller, cmd1, cmd2, monkeypatch):
    """The Q-side command selects a calculation that computes the angle, so the
    pair cannot be scanned as written; the GUI Run and the API (with force)
    refuse it alike, naming what computes the angle."""
    refusal = _run_refusal(in8_controller, cmd1, cmd2, monkeypatch)
    assert refusal and "cannot also be scanned" in refusal, refusal
    assert any(b.startswith("scan_validation: ") and "cannot also be scanned" in b
               for b in _api_blockers(in8_controller, cmd1, cmd2))


def test_angle_pairs_that_write_distinct_slots_are_accepted(in8_controller):
    for cmd1, cmd2 in (("A3 30 31 1", "A4 40 41 1"), ("omega 30 31 1", "sgl 0 1 1")):
        assert issues_for(in8_controller, cmd1, cmd2) == ([], []), (cmd1, cmd2)
        assert in8_controller._preview_launch(cmd1, cmd2)[1].calculation == "direct_motors"


@pytest.mark.parametrize("cmd1, cmd2", [
    ("A3 30 31 1", "omega 40 41 1"),
    ("A4 30 31 1", "2theta 40 41 1"),
    ("H 1.99 2.01 0.01", "H 1.99 2.01 0.01"),
])
def test_two_commands_scanning_one_quantity_are_refused_even_forced(
        in8_controller, cmd1, cmd2, monkeypatch):
    """Two spellings of one quantity: only one value per point could survive."""
    refusal = _run_refusal(in8_controller, cmd1, cmd2, monkeypatch)
    assert refusal and "Both commands scan" in refusal and "scan it once" in refusal
    assert any(b.startswith("scan_validation: Both commands scan")
               for b in _api_blockers(in8_controller, cmd1, cmd2))


class _SyncBridge:
    """Stand-in for ApiBridge: run the marshalled call inline."""

    def call_on_gui(self, fn, timeout=5.0):
        return fn()


def test_api_force_clears_soft_issues_only(in8_controller, monkeypatch):
    """``force`` is the operator's override, so it clears what the GUI offers
    as a choice and nothing more.

    A hard rejection -- here a refused fixed-curvature axis -- used to vanish
    under ``force``, and the scan ran with the pin silently overwritten. Both
    API gates, /validate and /scan, must hold it whatever the caller says.
    """
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    ana = d.ana_crystals[0].id
    backend = cm.TaviApiBackend(ctrl, _SyncBridge())

    hard = {"scan_command1": "rva 0.3 0.6 0.05", "scan_command2": "",
            "anacris": ana}
    for force in (False, True):
        result = backend.submit_validate({"parameters": hard, "force": force})
        assert result["would_queue"] is False, force
        assert any("cannot be scanned" in b for b in result["blockers"]), (
            force, result["blockers"])
        with pytest.raises(cm.ApiError) as excinfo:
            backend.submit_scan({"parameters": hard, "force": force})
        assert excinfo.value.code == "scan_validation", force

    # A soft issue -- a very long scan -- stays the operator's call: blocked
    # by default, cleared by force.
    soft = {"scan_command1": "rha 1.0 2.0 0.0001", "scan_command2": "",
            "anacris": ana}
    blocked = backend.submit_validate({"parameters": soft})["blockers"]
    assert any(b.startswith("scan_validation") for b in blocked), blocked
    forced = backend.submit_validate({"parameters": soft, "force": True})["blockers"]
    assert not any(b.startswith("scan_validation") for b in forced), forced


def test_h_with_a4_is_refused_in_the_gui_and_over_the_api_even_forced(in8_controller,
                                                                    monkeypatch):
    """Ownership wording and the force sentence on the conflict label, the Run
    dialog, /validate and /scan; the box that drives the conflict is styled."""
    ctrl = in8_controller
    sim = ctrl.window.simulation_dock
    cmd1, cmd2 = "H 0.9 1.1 0.1", "A4 40 42 1"
    why = ("A4 (sample 2θ) is calculated from H in the HKL calculation, so it cannot also be "
           "scanned. force does not override a command conflict.")
    sim.scan_command_1_edit.setText(cmd1)
    sim.scan_command_2_edit.setText(cmd2)
    _settle()
    try:
        assert sim.scan_conflict_label.text() == why
        assert not sim.scan_conflict_label.isHidden()
        assert sim.scan_command_2_edit.styleSheet() == sim.STYLE_WARNING
        assert sim.scan_command_1_edit.styleSheet() == sim.STYLE_NORMAL
    finally:
        sim.scan_command_1_edit.setText("")
        sim.scan_command_2_edit.setText("")
    assert _run_refusal(ctrl, cmd1, cmd2, monkeypatch).startswith(why)

    backend = cm.TaviApiBackend(ctrl, _SyncBridge())
    parameters = {"scan_command1": cmd1, "scan_command2": cmd2}
    assert "scan_validation: " + why in backend.submit_validate(
        {"parameters": parameters, "force": True})["blockers"]
    with pytest.raises(cm.ApiError) as refused:
        backend.submit_scan({"parameters": parameters, "force": True, "allow_partial": True})
    assert (refused.value.status, refused.value.code,
            str(refused.value.message)) == (400, "scan_validation", why)


def test_an_arc_under_a_plane_lock_shows_the_plans_wording(in8_controller):
    ctrl = in8_controller
    sim = ctrl.window.simulation_dock
    ctrl.instrument_state.plane_lock = {"hkl_u": [1.0, 0.0, 0.0], "hkl_v": [0.0, 1.0, 0.2],
                                        "tilts": {"sgl": 11.31, "sgu": 0.0}}
    try:
        sim.scan_command_1_edit.setText("sgl 0 2 1")
        _settle()
        assert sim.scan_warning_1_label.text().startswith(
            "The plane lock holds sgl (lower arc): the locked scattering plane (1 0 0)/(0 1 0.2)")
        assert sim.scan_conflict_label.isHidden()
        assert sim.scan_command_1_edit.styleSheet() == sim.STYLE_WARNING
        blockers = cm.TaviApiBackend(ctrl, _SyncBridge()).submit_validate(
            {"parameters": {"scan_command1": "sgl 0 2 1"}})["blockers"]
        assert any(b.startswith("scan_validation: Command 1: The plane lock holds sgl (lower arc)")
                   for b in blockers), blockers
    finally:
        ctrl.instrument_state.plane_lock = None
        sim.scan_command_1_edit.setText("")


def test_a_radius_scan_on_a_fixed_assembly_shows_the_plans_wording(in8_controller,
                                                                  monkeypatch):
    ctrl = in8_controller
    sim = ctrl.window.simulation_dock
    d = _pin_rva(ctrl, monkeypatch)
    dock = ctrl.window.instrument_dock
    previous = dock.selected_ana_id()
    dock.set_ana_id(d.ana_crystals[0].id)
    try:
        sim.scan_command_1_edit.setText("rva 0.3 0.6 0.05")
        _settle()
        assert sim.scan_warning_1_label.text().startswith(
            "The hardware holds rva (analyzer vertical radius) at 0.05 m")
        assert sim.scan_command_1_edit.styleSheet() == sim.STYLE_WARNING
    finally:
        sim.scan_command_1_edit.setText("")
        dock.set_ana_id(previous)


def test_an_arc_or_radius_beside_h_is_refused_by_the_plan(in8_controller, monkeypatch):
    """Paired with H, the same two refusals come from the plan, in box 2's label."""
    ctrl = in8_controller
    sim = ctrl.window.simulation_dock
    d = _pin_rva(ctrl, monkeypatch)
    dock = ctrl.window.instrument_dock
    previous = dock.selected_ana_id()
    dock.set_ana_id(d.ana_crystals[0].id)
    ctrl.instrument_state.plane_lock = {"hkl_u": [1.0, 0.0, 0.0], "hkl_v": [0.0, 1.0, 0.2],
                                        "tilts": {"sgl": 11.31, "sgu": 0.0}}
    try:
        sim.scan_command_1_edit.setText("H 0.9 1.1 0.1")
        sim.scan_command_2_edit.setText("sgl 0 2 1")
        _settle()
        assert sim.scan_warning_2_label.text().startswith("The plane lock holds sgl (lower arc)")
        assert sim.scan_command_2_edit.styleSheet() == sim.STYLE_WARNING
        assert sim.scan_command_1_edit.styleSheet() == sim.STYLE_NORMAL
        sim.scan_command_2_edit.setText("rva 0.3 0.6 0.05")
        _settle()
        assert sim.scan_warning_2_label.text().startswith(
            "The hardware holds rva (analyzer vertical radius) at 0.05 m")
        assert sim.scan_command_2_edit.styleSheet() == sim.STYLE_WARNING
    finally:
        ctrl.instrument_state.plane_lock = None
        sim.scan_command_1_edit.setText("")
        sim.scan_command_2_edit.setText("")
        dock.set_ana_id(previous)
