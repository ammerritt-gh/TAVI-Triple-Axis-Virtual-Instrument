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
from instruments.registry import get_instrument  # noqa: E402


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
        ana_crystals=tuple(dataclasses.replace(c, fixed_curvature=("rva",))
                           for c in ctrl.descriptor.ana_crystals))
    monkeypatch.setattr(ctrl, "descriptor", pinned, raising=False)
    return pinned


def test_a_fixed_curvature_axis_is_refused_as_a_scan_variable(in8_controller,
                                                              monkeypatch):
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    axes = ctrl._fixed_curvature_axes("pg002", d.ana_crystals[0].id)

    var, warning = ctrl._validate_single_scan_command("rva 0.3 0.6 0.05", axes)
    assert var is None
    assert "fixed on" in warning and "cannot be scanned" in warning
    assert "analyser" in warning          # names the crystal, not the instrument

    # The radii that side really does drive stay scannable.
    for cmd, expected in (("rha 1.0 2.0 0.1", "rha"), ("rhm 3.0 5.0 0.5", "rhm")):
        var, warning = ctrl._validate_single_scan_command(cmd, axes)
        assert var == expected and warning is None


def test_the_refusal_actually_blocks_the_launch(in8_controller, monkeypatch):
    """The gate is worthless if it only annotates a widget.

    `_validate_scan_commands_text` is what the GUI Run button and the API
    launch path both consult. It used to escalate only messages containing a
    warning marker or the word "Unknown", so this refusal was shown and then
    launched anyway -- and so was every other hard rejection whose wording
    happened to lack the marker.
    """
    ctrl = in8_controller
    d = _pin_rva(ctrl, monkeypatch)
    ana = d.ana_crystals[0].id

    msg = ctrl._validate_scan_commands_text("rva 0.3 0.6 0.05", "", "pg002", ana)
    assert msg, "a refused scan variable must block the launch"
    assert "cannot be scanned" in msg

    # A scannable axis still launches.
    assert ctrl._validate_scan_commands_text("rha 1.0 2.0 0.1", "", "pg002", ana) == ""


def test_other_hard_rejections_also_block(in8_controller):
    """The same hole covered these; none of their wordings carry the marker."""
    ctrl = in8_controller
    for cmd in ("rhm 1.0 2.0", "rhm 1.0 2.0 0.1 0.2", "rhm a b c"):
        assert ctrl._validate_scan_commands_text(cmd, ""), cmd


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
    pinned = dataclasses.replace(ana, fixed_curvature=("rva",))
    monkeypatch.setattr(
        ctrl, "descriptor",
        dataclasses.replace(ctrl.descriptor, ana_crystals=(pinned, other)),
        raising=False)

    assert ctrl._fixed_curvature_axes("pg002", pinned.id)
    assert ctrl._fixed_curvature_axes("pg002", "other") == {}
    assert ctrl._fixed_curvature_axes("pg002", None) == {}

    # ...and that difference reaches the launch gate.
    cmd = "rva 0.3 0.6 0.05"
    assert ctrl._validate_scan_commands_text(cmd, "", "pg002", pinned.id)
    assert ctrl._validate_scan_commands_text(cmd, "", "pg002", "other") == ""


def test_nothing_is_refused_when_no_crystal_pins_anything(in8_controller):
    for spec in in8_controller.descriptor.ana_crystals:
        assert spec.fixed_curvature == ()
    assert in8_controller._validate_scan_commands_text(
        "rva 0.3 0.6 0.05", "", "pg002", "pg002") == ""


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

    hard, soft = ctrl._scan_command_issues("rva 0.3 0.6 0.05", "", "pg002", ana)
    assert hard and "cannot be scanned" in hard[0]
    assert soft == [], "a refused axis is not the operator's judgement call"

    # A very long scan is the operator's call, and stays overridable.
    hard, soft = ctrl._scan_command_issues("rha 1.0 2.0 0.0001", "", "pg002", ana)
    assert hard == []
    assert soft and "⚠" in soft[0]


def test_malformed_commands_are_hard(in8_controller):
    for cmd in ("rhm 1.0 2.0", "rhm 1.0 2.0 0.1 0.2", "rhm a b c", "nope 1 2 3"):
        hard, _ = in8_controller._scan_command_issues(cmd, "")
        assert hard, cmd
