"""A slit gap is finite and zero or more millimetres, at every entry point (F7).

A negative or non-finite gap reached McStas as a closed beam with a plausible-looking
result. The API refuses it with HTTP 400, the GUI field returns to its last accepted
text, the scan plan refuses a command that reaches it, and a launch refuses a typed gap
outside the domain, such as one restored from a saved file. Zero is a closed slit and
stays legal.
"""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from instruments.rules import PlanRefused, build_plan, context_from_state, expand  # noqa: E402
from tavi.api_server import ApiError  # noqa: E402
from tavi.local_state import config_path  # noqa: E402
from tavi.quantities import by_id  # noqa: E402
from test_slit_scans import _launch  # noqa: E402

INSTRUMENT = "in8"     # the registry id
LABEL = "IN8"          # the label test_slit_scans' _launch takes


@pytest.fixture
def controller():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(INSTRUMENT)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def _gap(ctrl):
    """(gap ID, its field) for the first horizontal slit of this instrument."""
    edits = ctrl._slit_gap_edits()
    qid = next(q for q in edits if q.endswith("horizontal_gap_mm"))
    return qid, edits[qid]


def test_the_api_refuses_a_negative_or_non_finite_gap_and_takes_zero(controller):
    qid, edit = _gap(controller)
    before = edit.text()
    for bad in (-5.0, math.nan, math.inf):
        applied, errors = controller.apply_parameters({qid: bad})
        assert qid in errors and qid not in applied, bad
        assert edit.text() == before

    applied, errors = controller.apply_parameters({qid: 0.0})
    assert not errors and qid in applied
    assert float(edit.text()) == 0.0


def test_a_launch_refuses_a_negative_gap_with_400_and_takes_zero(controller):
    qid, _ = _gap(controller)
    with pytest.raises(ApiError) as caught:
        controller.build_api_launch_state({"scan_command1": "deltaE 0 1 1", qid: -5.0})
    assert caught.value.status == 400
    controller.build_api_launch_state({"scan_command1": "deltaE 0 1 1", qid: 0.0})


def test_the_scan_plan_refuses_a_command_that_reaches_a_negative_gap():
    plugin, config, vals, snapshot = _launch(LABEL)
    qid = sorted(plugin.capabilities().slit_bindings)[0]
    alias = by_id(qid).aliases[0]
    ctx = context_from_state(config, vals, plugin.capabilities())
    name = by_id(qid).name

    with pytest.raises(PlanRefused) as caught:
        build_plan([(f"{alias} -1 -1 1", False), ("", False)], ctx)
    assert caught.value.command == 1 and name in str(caught.value) and "-1" in str(caught.value)

    plan = build_plan([(f"{alias} -1 -1 1", True), ("", False)], ctx)   # relative to 0.5 mm
    snapshot[qid] = 0.5
    with pytest.raises(PlanRefused) as caught:
        expand(plan, snapshot)
    assert caught.value.command == 1 and "-0.5" in str(caught.value)

    points = expand(build_plan([(f"{alias} 0 2 1", False), ("", False)], ctx), snapshot).points
    assert [point[qid] for point in points] == [0.0, 1.0, 2.0]


def test_a_relative_run_refuses_a_negative_base_gap_even_when_its_points_are_legal():
    plugin, config, vals, snapshot = _launch(LABEL)
    qid = sorted(plugin.capabilities().slit_bindings)[0]
    alias = by_id(qid).aliases[0]
    ctx = context_from_state(config, vals, plugin.capabilities())
    plan = build_plan([(f"{alias} 6 6 1", True), ("", False)], ctx)   # points land at 1 mm
    snapshot[qid] = -5.0                                              # the typed base
    with pytest.raises(PlanRefused) as caught:
        expand(plan, snapshot)
    assert by_id(qid).name in str(caught.value) and "-5" in str(caught.value)


def test_the_gui_field_returns_to_its_last_accepted_text_on_a_negative_gap(controller):
    qid, edit = _gap(controller)
    seen = []
    controller.message_printed.connect(seen.append)
    try:
        accepted = edit.text()
        edit.setText("-5")
        edit.editingFinished.emit()
        assert edit.text() == accepted
        assert any(m.startswith("Slit gap refused") and by_id(qid).name in m for m in seen)

        seen.clear()
        edit.setText("0")
        edit.editingFinished.emit()
        assert edit.text() == "0"
        assert not any("Slit gap refused" in m for m in seen)
    finally:
        controller.message_printed.disconnect(seen.append)


def test_a_launch_refuses_a_saved_negative_gap_naming_it(controller):
    qid, _ = _gap(controller)
    path = config_path("parameters.json")
    original = open(path, "rb").read() if os.path.exists(path) else None
    try:
        controller.save_parameters()
        with open(path, "r", encoding="utf-8") as fh:
            document = json.load(fh)
        document[INSTRUMENT][qid] = -5.0
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(document, fh)
        controller.load_parameters()

        state = controller._collect_simulation_launch_state()
        with pytest.raises(PlanRefused) as caught:
            controller._compile_launch(state)
        assert by_id(qid).name in str(caught.value) and "-5" in str(caught.value)
    finally:
        if original is None:
            os.remove(path)
        else:
            with open(path, "wb") as fh:
                fh.write(original)
