"""Slit scans end to end, in millimetres, on all four instruments.

A slit gap is a scan command wherever the instrument binds it to a McStas
parameter. The plan carries the gap per point in mm; the snapshot emits it
through the binding, in metres, as a runtime parameter, so a slit scan never
rebuilds. The analytic engine has no aperture model and refuses one, at the
GUI and over the API alike.
"""
import importlib
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")

from instruments.rules import PlanRefused, build_plan, context_from_state, expand  # noqa: E402
from tavi.quantities import by_id, public_values  # noqa: E402
from tavi.sample_mount import SampleMount  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "solver_baseline_cases", Path(__file__).resolve().parent / "data" / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)

LABELS = tuple(cases.PLUGINS)
MOTORS = {"mono_two_theta_deg": "mtt", "sample_two_theta_deg": "stt",
          "sample_rotation_deg": "sth", "analyzer_two_theta_deg": "att",
          "sample_lower_arc_deg": "sgl", "sample_upper_arc_deg": "sgu"}


def _plugin(label):
    module, cls = cases.PLUGINS[label]
    return getattr(importlib.import_module(module), cls)()


def _bound_gaps():
    return [(label, qid) for label in LABELS
            for qid in sorted(_plugin(label).capabilities().slit_bindings)]


def _launch(label):
    """(plugin, scan config, vals, snapshot) at H K L = 1 1 0, ΔE = 0, the motors solved there."""
    plugin = _plugin(label)
    base = plugin.default_state()
    base.sample_mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90)
    vals = cases._launch_vals(plugin.descriptor())
    config = plugin.scan_config(base, vals, None, {}, base.sample_mount)
    snapshot = {**public_values(vals, plugin.descriptor().slits),
                "h": 1.0, "k": 1.0, "l": 0.0, "energy_transfer_mev": 0.0}
    plan = build_plan([("H 1 1 1", False), ("", False)],
                      context_from_state(config, vals, plugin.capabilities()))
    meta = plugin.compute_snapshot(plan, expand(plan, snapshot).points[0], 0, config, vals,
                                   ".").metadata
    snapshot.update({qid: meta[key] for qid, key in MOTORS.items()})
    return plugin, config, vals, snapshot


def _run(label, commands):
    """The plan of ``commands`` and each point's snapshot, as the run computes them."""
    plugin, config, vals, snapshot = _launch(label)
    plan = build_plan(commands, context_from_state(config, vals, plugin.capabilities()))
    points = expand(plan, snapshot).points
    return plugin, snapshot, plan, points, [
        plugin.compute_snapshot(plan, point, i, config, vals, ".") for i, point in enumerate(points)]


@pytest.mark.parametrize("label, qid", _bound_gaps())
def test_an_h_and_slit_scan_emits_the_changing_aperture_per_point(label, qid):
    alias = by_id(qid).aliases[0]
    plugin, snapshot, plan, points, snaps = _run(
        label, [("H 0.99 1.01 0.02", False), (f"{alias} 10 20 10", False)])
    assert plan.calculation == "hkl"
    bindings = plugin.capabilities().bindings
    name = bindings[qid].name
    seen = set()
    for point, snap in zip(points, snaps):
        assert snap.error_flags == [], snap.error_flags
        assert snap.params[name] == pytest.approx(point[qid] * 1e-3, abs=1e-15)   # mm -> m
        assert snap.metadata[qid] == point[qid]                                    # recorded in mm
        assert snap.metadata["H"] == point["h"]
        for other, spec in bindings.items():   # every other aperture stays as typed
            if other.startswith("slit.") and other != qid:
                assert snap.params[spec.name] == pytest.approx(snapshot[other] * 1e-3), other
        seen.add((point["h"], snap.params[name]))
    assert seen == {(0.99, 0.010), (1.01, 0.010), (0.99, 0.020), (1.01, 0.020)}


@pytest.mark.parametrize("label", LABELS)
def test_a_lone_slit_scan_changes_the_aperture_and_holds_the_motors(label):
    """Ruling 5's slit variant: no command selects a geometry, so the motors run as typed
    (A3 rocked off the HKL solve here) and only the aperture moves."""
    plugin, config, vals, snapshot = _launch(label)
    qid = sorted(plugin.capabilities().slit_bindings)[0]
    snapshot["sample_rotation_deg"] += 1.5
    plan = build_plan([("", False), (f"{qid} 5 15 5", False)],
                      context_from_state(config, vals, plugin.capabilities()))
    assert plan.calculation == "direct_motors"
    name = plugin.capabilities().bindings[qid].name
    emitted = []
    for i, point in enumerate(expand(plan, snapshot).points):
        snap = plugin.compute_snapshot(plan, point, i, config, vals, ".")
        for motor, key in MOTORS.items():
            assert snap.metadata[key] == snapshot[motor], key
        emitted.append(snap.params[name])
    assert emitted == pytest.approx([0.005, 0.010, 0.015], abs=1e-15)


@pytest.mark.parametrize("label", LABELS)
def test_a_slit_value_does_not_touch_the_build_fingerprint(label):
    """Scans change runtime parameters, never rebuild per point: the build fingerprint
    is blind to every gap."""
    plugin = _plugin(label)
    base = plugin.default_state()
    vals = cases._launch_vals(plugin.descriptor())
    wide = cases._launch_vals(plugin.descriptor(), slits_mm={
        s.id: ((37.0, 41.0) if s.has_height else 37.0) for s in plugin.descriptor().slits})
    fingerprints = {plugin.build_fingerprint(plugin.scan_config(base, v, None, {},
                                                                base.sample_mount))
                    for v in (vals, wide)}
    assert len(fingerprints) == 1


def test_an_unbound_or_missing_slit_and_the_analytic_engine_are_refused():
    plugin, config, vals, _snapshot = _launch("IN8")
    ctx = context_from_state(config, vals, plugin.capabilities())
    with pytest.raises(PlanRefused, match="This instrument has no detector slit vertical gap"):
        build_plan([("detector_vgap 5 15 5", False), ("", False)], ctx)
    ctx = context_from_state(config, vals, plugin.capabilities(), engine="deterministic")
    with pytest.raises(PlanRefused, match="the analytic engine has no aperture model"):
        build_plan([("H 1 1.1 0.1", False), ("pre_sample_hgap 5 15 5", False)], ctx)


# --- the GUI and the API (real widgets, offscreen) --------------------------------

class _SyncBridge:
    def call_on_gui(self, fn, timeout=5.0):
        return fn()


@pytest.fixture(scope="module")
def in8():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    import instruments.builtin  # noqa: F401  (registers built-in instruments)
    import TAVI_PySide6 as cm
    from instruments.registry import available_instruments, get_instrument

    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("in8")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id="in8", save_selection=lambda _id: None)
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    ctrl.set_default_parameters()
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def _h_scan(ctrl):
    """An H scan around the H the docks hold."""
    h = ctrl.get_gui_values()["H"]
    return f"H {h - 0.01:.4f} {h + 0.01:.4f} 0.01"


def _label(ctrl, cmd1, cmd2, engine="mcstas"):
    sim = ctrl.window.simulation_dock
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData(engine))
    sim.scan_command_1_edit.setText(cmd1)
    sim.scan_command_2_edit.setText(cmd2)
    ctrl.validate_scan_commands()
    shown = sim.scan_conflict_label.text() if not sim.scan_conflict_label.isHidden() else ""
    sim.scan_command_1_edit.setText("")
    sim.scan_command_2_edit.setText("")
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("mcstas"))
    return shown


def _press_run(ctrl, monkeypatch, cmd1, cmd2="", engine="mcstas", relative=False):
    """Press Run; (submitted launch states, dialogs raised)."""
    from PySide6.QtWidgets import QMessageBox

    sim = ctrl.window.simulation_dock
    submitted, dialogs = [], []
    monkeypatch.setattr(ctrl, "submit_scan_job", lambda launch, source: submitted.append(launch))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: dialogs.append(a[2]))
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData(engine))
    if sim.relative_1_button.isChecked() != relative:
        sim.relative_1_button.click()
    sim.scan_command_1_edit.setText(cmd1)
    sim.scan_command_2_edit.setText(cmd2)
    try:
        ctrl.run_simulation_thread()
    finally:
        if sim.relative_1_button.isChecked():
            sim.relative_1_button.click()
        sim.scan_command_1_edit.setText("")
        sim.scan_command_2_edit.setText("")
        sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("mcstas"))
    return submitted, dialogs


def test_the_live_label_run_and_validate_accept_a_bound_slit_scan(in8, monkeypatch):
    import TAVI_PySide6 as cm

    cmd1, cmd2 = _h_scan(in8), "pre_sample_hgap 10 20 10"
    assert in8._scan_command_issues(cmd1, cmd2) == ([], [])
    assert _label(in8, cmd1, cmd2) == ""
    assert _label(in8, "pre_sample_hgap 10 20 10", "") == ""
    submitted, dialogs = _press_run(in8, monkeypatch, cmd1, cmd2)
    assert dialogs == [] and len(submitted) == 1, dialogs
    expansion = submitted[0]["expansion"]
    assert expansion.values[2] == (10.0, 20.0)
    assert {p["slit.pre_sample.horizontal_gap_mm"] for p in expansion.points} == {10.0, 20.0}
    launch = submitted[0]
    for i, point in enumerate(expansion.points):   # each point folder records its own gap
        snap = in8.instrument.compute_snapshot(launch["plan"], point, i, launch["scan_config"],
                                               launch["vals"], ".")
        written = in8.point_output_parameters(launch["vals"], snap.metadata, i, 1000)
        assert written["slit.pre_sample.horizontal_gap_mm"] == point["slit.pre_sample.horizontal_gap_mm"]

    backend = cm.TaviApiBackend(in8, _SyncBridge())
    for c1, c2 in ((cmd1, cmd2), ("pre_sample_hgap 10 20 10", "")):
        result = backend.submit_validate({"parameters": {"scan_command1": c1,
                                                         "scan_command2": c2}})
        assert result["would_queue"] is True, result["blockers"]


def test_a_slit_scan_is_refused_on_the_analytic_engine_everywhere(in8, monkeypatch):
    """GUI live label and Run dialog, API /validate and /scan (force and allow_partial
    do not clear it)."""
    import TAVI_PySide6 as cm

    why = "pre-sample slit horizontal gap cannot be scanned here: the analytic engine has no aperture model."
    for cmd1, cmd2 in ((_h_scan(in8), "pre_sample_hgap 10 20 10"),
                       ("pre_sample_hgap 10 20 10", "")):
        assert _label(in8, cmd1, cmd2, engine="deterministic") == why
        submitted, dialogs = _press_run(in8, monkeypatch, cmd1, cmd2, engine="deterministic")
        assert submitted == [] and len(dialogs) == 1 and why in dialogs[0], dialogs

        backend = cm.TaviApiBackend(in8, _SyncBridge())
        params = {"scan_command1": cmd1, "scan_command2": cmd2}
        result = backend.submit_validate({"parameters": params, "engine": "deterministic",
                                          "force": True})
        assert result["would_queue"] is False
        assert "scan_validation: " + why in result["blockers"], result["blockers"]
        with pytest.raises(cm.ApiError) as refused:
            backend.submit_scan({"parameters": params, "engine": "deterministic",
                                 "force": True, "allow_partial": True})
        assert (refused.value.status, refused.value.code) == (400, "scan_validation")
        assert str(refused.value.message) == why


def test_a_relative_slit_scan_with_an_empty_gap_field_refuses_naming_it(in8, monkeypatch):
    """Real widgets: the pre-sample width field emptied under a relative scan of it."""
    edit = in8.window.instrument_dock.slit_widgets["sbl"]["width"]
    typed = edit.text()
    try:
        submitted, dialogs = _press_run(in8, monkeypatch, "pre_sample_hgap -5 5 5", relative=True)
        assert dialogs == [] and len(submitted) == 1, dialogs
        assert submitted[0]["expansion"].values[1] == tuple(float(typed) + d for d in (-5, 0, 5))

        edit.setText("")
        submitted, dialogs = _press_run(in8, monkeypatch, "pre_sample_hgap -5 5 5", relative=True)
        assert submitted == [] and len(dialogs) == 1, dialogs
        assert dialogs[0].startswith(
            "Command 1 steps relative to pre-sample slit horizontal gap, but its field holds "
            "no number to step from."), dialogs
        assert edit.text() == ""
    finally:
        edit.setText(typed)


def test_goto_drives_a_slit_gap_field_and_reverts_it(in8):
    """A slit scan's CEN is a gap: goto sets that field (mm) and revert restores it."""
    edit = in8.window.instrument_dock.slit_widgets["sbl"]["width"]
    typed = float(edit.text())
    ok, message = in8.goto_scan_variable("pre_sample_hgap", typed + 7.0, label="goto CEN")
    assert ok, message
    assert float(edit.text()) == typed + 7.0
    assert in8.can_revert_goto()
    ok, message = in8.revert_last_goto()
    assert ok, message
    assert float(edit.text()) == typed
