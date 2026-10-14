"""The Crystal Focusing block's tracking state, on the real offscreen window and controller.

Each radius row has a Track ideal box. The operator's choice (track or hold) is
dock state; the box only renders the effective mode (fixed, scanned, no model,
track, held). Every state these tests reach is checked for the two agreements
that matter, separately:

- the launch: ``get_gui_values()['curvature_modes'][axis]`` is AUTOFOCUS iff
  ``is_bending_locked(axis)``, which is the choice unless the axis can never
  track (a crystal-fixed or no-model axis);
- the box: ticked iff the effective mode is track, enabled iff it is track or
  held (so a scanned axis whose choice is on launches AUTOFOCUS with an
  unticked, disabled box, exactly as the launch always did).

One controller per instrument for the module; each test starts from
``set_default_parameters()``. The config directory is an empty temp one, never
the session's shared copy, so a saved all-held file cannot change the start.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from gui.docks.instrument_dock import FOCUSING_AXES  # noqa: E402
from gui.field_marks import mark_for  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402

AUTOFOCUS, HELD = cm.CurvatureMode.AUTOFOCUS, cm.CurvatureMode.HELD
INSTRUMENTS = [info.id for info in available_instruments()]
# The axes whose crystal can never track: every runnable instrument but IN8 fixes rva.
NEVER = {"puma": ("rva",), "in8": (), "in12": ("rva",), "panda": ("rva",)}


def test_the_worktree_is_the_import_root():
    """Printed once, asserted: the controller under test is this checkout's."""
    print("TAVI_PySide6 import root:", os.path.dirname(os.path.abspath(cm.__file__)))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.dirname(os.path.abspath(cm.__file__)) == root


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """``world(instrument_id)``: that instrument's controller (one per module), freshly defaulted."""
    config = tmp_path_factory.mktemp("focusing_config")
    patch = pytest.MonkeyPatch()
    patch.setenv("TAVI_CONFIG_DIR", str(config))
    app = QApplication.instance() or QApplication([sys.argv[0]])
    made = {}

    def get(instrument_id):
        if instrument_id not in made:
            instrument = get_instrument(instrument_id)
            window = cm.TAVIMainWindow(
                instrument.descriptor(), instrument_infos=available_instruments(),
                current_instrument_id=instrument_id, save_selection=lambda _id: None)
            made[instrument_id] = cm.TAVIController(
                window, instrument, api_overrides={"disabled": True})
        ctrl = made[instrument_id]
        (config / "parameters.json").unlink(missing_ok=True)
        ctrl.set_default_parameters()
        _settle()
        return ctrl

    get.config = config
    yield get
    for ctrl in made.values():
        ctrl.shutdown()
        ctrl.window.deleteLater()
    app.processEvents()
    patch.undo()


def _settle():
    for _ in range(3):   # the coalescing timer, then anything it posts
        QApplication.processEvents()


def _box(ctrl, axis):
    return getattr(ctrl.window.instrument_dock, f"{axis}_track_check")


def _edit(ctrl, axis):
    return getattr(ctrl.window.instrument_dock, f"{axis}_edit")


def _agree(ctrl, never=()):
    """Both agreements for every axis in the state ctrl is in now; returns {axis: effective mode}."""
    idock = ctrl.window.instrument_dock
    vals = ctrl.get_gui_values()
    assert vals is not None
    modes = {}
    for axis in FOCUSING_AXES:
        mode = idock.mode(axis)
        # The launch: AUTOFOCUS iff is_bending_locked, which is the choice unless the axis never tracks.
        assert ctrl.is_bending_locked(axis) == (idock.choice(axis) and axis not in never), axis
        assert (vals["curvature_modes"][axis] == AUTOFOCUS) == ctrl.is_bending_locked(axis), axis
        # The box: ticked iff track, enabled iff track or held.
        assert _box(ctrl, axis).isChecked() == (mode == "track"), (axis, mode)
        assert _box(ctrl, axis).isEnabled() == (mode in ("track", "held")), (axis, mode)
        modes[axis] = mode
    return modes


def _ideal(ctrl):
    ideal = ctrl._compute_ideal_bending_values()
    assert ideal
    return ideal


def _text(ctrl, axis):
    return float(_edit(ctrl, axis).text())


def _tracked(ctrl):
    return [axis for axis in FOCUSING_AXES if ctrl.window.instrument_dock.mode(axis) == "track"]


def _scale_angle(ctrl, angle, factor):
    """Move A2 (``mtt``) or A6 (``att``) the way Enter in its field does."""
    idock = ctrl.window.instrument_dock
    edit = getattr(idock, f"{angle}_edit")
    edit.setText(f"{float(edit.text()) * factor:.4f}")
    getattr(ctrl, f"on_{angle}_changed")()
    _settle()


def _saved(world, ctrl):
    return json.loads((world.config / "parameters.json").read_text(encoding="utf-8"))[ctrl.instrument.id]


def _rewrite_saved(world, ctrl, change):
    path = world.config / "parameters.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document[ctrl.instrument.id])
    path.write_text(json.dumps(document), encoding="utf-8")


# --------------------------------------------------------------- fresh start

@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
@pytest.mark.parametrize("how", ["defaults", "load without a file"])
def test_a_fresh_start_ticks_every_askable_axis_and_follows_the_angles(world, instrument_id, how):
    ctrl = world(instrument_id)
    for axis in FOCUSING_AXES:   # leave the defaults first, so the start has something to undo
        ctrl.unlock_ideal_bending(axis)
    if how == "defaults":
        ctrl.set_default_parameters()
    else:
        assert not (world.config / "parameters.json").exists()
        ctrl.load_parameters()
    _settle()

    modes = _agree(ctrl, NEVER[instrument_id])
    assert {a for a, m in modes.items() if m == "track"} == set(FOCUSING_AXES) - set(NEVER[instrument_id])
    assert all(modes[a] == "fixed" for a in NEVER[instrument_id])
    ideal = _ideal(ctrl)
    for axis in _tracked(ctrl):
        assert _text(ctrl, axis) == pytest.approx(ideal[axis], abs=1e-3), axis

    before = dict(ideal)
    _scale_angle(ctrl, "mtt", 1.15)
    now = _ideal(ctrl)
    assert now["rhm"] != before["rhm"] or now["rvm"] != before["rvm"]
    for axis in _tracked(ctrl):
        assert _text(ctrl, axis) == pytest.approx(now[axis], abs=1e-3), axis
    _scale_angle(ctrl, "att", 1.15)
    later = _ideal(ctrl)
    assert later["rha"] != now["rha"]
    for axis in _tracked(ctrl):
        assert _text(ctrl, axis) == pytest.approx(later[axis], abs=1e-3), axis
    _agree(ctrl, NEVER[instrument_id])


# ------------------------------------------------------------ the operator's actions

@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_unticking_holds_the_value_and_ticking_applies_the_ideal_at_once(world, instrument_id):
    ctrl = world(instrument_id)
    held = _text(ctrl, "rhm")
    _box(ctrl, "rhm").click()   # untick
    assert _box(ctrl, "rhm").isChecked() is False and _box(ctrl, "rhm").isEnabled()
    assert ctrl.window.instrument_dock.mode("rhm") == "held"
    _agree(ctrl, NEVER[instrument_id])

    _scale_angle(ctrl, "mtt", 1.15)
    assert _text(ctrl, "rhm") == held                           # held through the A2 change
    assert _text(ctrl, "rhm") != pytest.approx(_ideal(ctrl)["rhm"], abs=1e-3)
    others = [a for a in _tracked(ctrl) if a != "rhm"]
    assert "rvm" in others and _text(ctrl, "rvm") == pytest.approx(_ideal(ctrl)["rvm"], abs=1e-3)

    _box(ctrl, "rhm").click()   # tick: the ideal at once
    assert _box(ctrl, "rhm").isChecked() is True
    assert _text(ctrl, "rhm") == pytest.approx(_ideal(ctrl)["rhm"], abs=1e-3)
    _agree(ctrl, NEVER[instrument_id])


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_typing_a_radius_unticks_it(world, instrument_id):
    ctrl = world(instrument_id)
    edit = _edit(ctrl, "rha")
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, "7.5")
    assert edit.text() == "7.5"
    assert _box(ctrl, "rha").isChecked() is False and _box(ctrl, "rha").isEnabled()
    assert not ctrl.is_bending_locked("rha")
    assert ctrl.get_gui_values()["rha"] == pytest.approx(7.5)
    _agree(ctrl, NEVER[instrument_id])


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_an_api_patch_of_a_radius_unticks_it(world, instrument_id):
    ctrl = world(instrument_id)
    applied, errors = ctrl.apply_parameters({"rhm": 9.0})
    assert not errors and applied
    assert _text(ctrl, "rhm") == pytest.approx(9.0)
    assert _box(ctrl, "rhm").isChecked() is False
    assert ctrl.window.instrument_dock.mode("rhm") == "held"
    # the sibling the patch did not name still tracks
    assert ctrl.window.instrument_dock.mode("rvm") == "track"
    _agree(ctrl, NEVER[instrument_id])


# -------------------------------------------------------------- fixed by a module

def test_puma_with_the_nmo_fitted_shows_the_mono_fixed_flat_and_the_choice_comes_back(world):
    ctrl = world("puma")
    idock = ctrl.window.instrument_dock
    ctrl.unlock_ideal_bending("rvm")
    idock.module_widgets["nmo"].setCurrentText("Both")
    _settle()

    modes = _agree(ctrl, NEVER["puma"])
    assert (modes["rhm"], modes["rvm"], modes["rha"], modes["rva"]) == ("fixed", "fixed", "track", "fixed")
    assert "flat while the nmo is fitted" in _box(ctrl, "rhm").toolTip().lower()
    assert _text(ctrl, "rhm") == 0 and _text(ctrl, "rvm") == 0
    assert idock.choice("rhm") is True and idock.choice("rvm") is False
    # a module-fixed axis keeps today's launch mode: its choice
    assert ctrl.get_gui_values()["curvature_modes"]["rhm"] == AUTOFOCUS
    assert ctrl.get_gui_values()["curvature_modes"]["rvm"] == HELD

    idock.module_widgets["nmo"].setCurrentText("None")
    _settle()
    modes = _agree(ctrl, NEVER["puma"])
    assert (modes["rhm"], modes["rvm"]) == ("track", "held")   # each axis's own choice returned
    assert _text(ctrl, "rhm") == pytest.approx(_ideal(ctrl)["rhm"], abs=1e-3)


# ------------------------------------------------------------ fixed and no model

def test_puma_rva_is_fixed_launches_held_and_saves_held(world):
    ctrl = world("puma")
    modes = _agree(ctrl, NEVER["puma"])
    assert modes["rva"] == "fixed"
    assert "0.8" in _box(ctrl, "rva").toolTip()
    assert ctrl.get_gui_values()["curvature_modes"]["rva"] == HELD
    ctrl.save_parameters()
    block = _saved(world, ctrl)
    assert block["rva_ideal_locked"] is False
    assert [block[f"{a}_ideal_locked"] for a in ("rhm", "rvm", "rha")] == [True, True, True]


def test_a_fixed_radius_shows_a_dash_in_the_ideal_column_not_its_fixed_value(world):
    ctrl = world("puma")
    idock = ctrl.window.instrument_dock
    assert idock.mode("rva") == "fixed"
    assert idock.rva_ideal_label.text() == "—"           # the 0.8 m field is not an ideal
    assert "no ideal" in idock.rva_ideal_label.toolTip().lower()
    idock.module_widgets["nmo"].setCurrentText("Both")        # rhm and rvm fixed flat
    _settle()
    assert idock.rhm_ideal_label.text() == idock.rvm_ideal_label.text() == "—"
    idock.module_widgets["nmo"].setCurrentText("None")
    _settle()
    assert idock.rhm_ideal_label.text() != "—" and idock.rvm_ideal_label.text() != "—"


def test_in12_heusler_rva_has_no_model_launches_held_and_keeps_its_choice(world):
    ctrl = world("in12")
    idock = ctrl.window.instrument_dock
    idock.set_ana_id("heusler111")
    _settle()
    ctrl.apply_ideal_bending_value("rva")   # the choice goes on; there is no ideal to take

    modes = _agree(ctrl, NEVER["in12"])
    assert modes["rva"] == "no_model" and idock.choice("rva") is True
    assert not _box(ctrl, "rva").isEnabled() and not _box(ctrl, "rva").isChecked()
    assert "no established focusing model" in _box(ctrl, "rva").toolTip().lower()
    assert ctrl.get_gui_values()["curvature_modes"]["rva"] == HELD
    assert _edit(ctrl, "rva").isEnabled()          # a typed value is honoured
    # the other three still track their real ideals
    assert modes["rhm"] == modes["rvm"] == modes["rha"] == "track"

    idock.set_ana_id("pg002")                      # the conventional analyser fixes rva instead
    _settle()
    assert _agree(ctrl, NEVER["in12"])["rva"] == "fixed" and idock.choice("rva") is True
    idock.set_ana_id("heusler111")
    _settle()
    assert _agree(ctrl, NEVER["in12"])["rva"] == "no_model" and idock.choice("rva") is True


def test_the_choice_kept_under_a_no_model_analyser_survives_save_and_reload(world):
    """IN12: no analyser lets rva track, so the choice is read back from the file and the dock."""
    ctrl = world("in12")
    idock = ctrl.window.instrument_dock
    idock.set_ana_id("heusler111")
    _settle()
    ctrl.apply_ideal_bending_value("rva")
    ctrl.save_parameters()
    assert _saved(world, ctrl)["rva_ideal_locked"] is True       # the choice, not what launches

    ctrl.set_default_parameters()                                 # PG(002): rva fixed, choice off
    assert idock.choice("rva") is False
    ctrl.load_parameters()
    _settle()
    assert idock.selected_ana_id() == "heusler111" and idock.choice("rva") is True
    assert _agree(ctrl, NEVER["in12"])["rva"] == "no_model"
    idock.set_ana_id("pg002")
    _settle()
    assert idock.choice("rva") is True and _agree(ctrl, NEVER["in12"])["rva"] == "fixed"


# ------------------------------------------------------------------ scan commands

@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
@pytest.mark.parametrize("choice", [True, False])
def test_a_scan_command_naming_rhm_shows_it_scanned_and_the_choice_returns(world, instrument_id, choice):
    ctrl = world(instrument_id)
    idock = ctrl.window.instrument_dock
    ctrl.window.simulation_dock.scan_command_2_edit.setText("")
    idock.set_choice("rhm", choice)

    ctrl.window.simulation_dock.scan_command_1_edit.setText("rhm 10 20 2")
    ctrl._refresh_scan_feedback()
    modes = _agree(ctrl, NEVER[instrument_id])
    assert modes["rhm"] == "scanned" and idock.scanned_command("rhm") == 1
    assert not _box(ctrl, "rhm").isEnabled() and not _box(ctrl, "rhm").isChecked()
    assert "command 1" in _box(ctrl, "rhm").toolTip()
    # the launch reports today's mode for a scanned axis: its choice
    assert ctrl.get_gui_values()["curvature_modes"]["rhm"] == (AUTOFOCUS if choice else HELD)
    assert all(modes[a] != "scanned" for a in ("rvm", "rha", "rva"))

    ctrl.window.simulation_dock.scan_command_1_edit.setText("")
    ctrl._refresh_scan_feedback()
    modes = _agree(ctrl, NEVER[instrument_id])
    assert modes["rhm"] == ("track" if choice else "held") and idock.scanned_command("rhm") is None


def test_the_field_marks_timer_pushes_the_scanned_map_too(world):
    ctrl = world("puma")
    ctrl.window.simulation_dock.scan_command_1_edit.setText("rvm 5 8 1")
    _settle()
    for _ in range(40):   # the coalescing timer runs on the event loop
        if ctrl.window.instrument_dock.mode("rvm") == "scanned":
            break
        QTest.qWait(25)
    assert ctrl.window.instrument_dock.mode("rvm") == "scanned"
    ctrl.window.simulation_dock.scan_command_1_edit.setText("")
    ctrl._refresh_scan_feedback()
    _agree(ctrl, NEVER["puma"])


def _assert_rhm_free(ctrl):
    """Once a command no longer names rhm: it tracks or holds by its choice, with no scan mark and no flag."""
    idock = ctrl.window.instrument_dock
    assert _agree(ctrl)["rhm"] == ("track" if idock.choice("rhm") else "held")
    assert idock.scanned_command("rhm") is None
    assert mark_for(_edit(ctrl, "rhm")).state()[0] != "scanned"   # a tracking axis carries a per-point "set" mark
    assert _flag(ctrl) == ""


def test_defaults_and_load_clear_a_scan_command_and_its_scanned_axis(world):
    """The command boxes are set with signals blocked, so the marks must be redrawn after them."""
    ctrl = world("in8")
    idock, sim = ctrl.window.instrument_dock, ctrl.window.simulation_dock
    ctrl.save_parameters()
    assert _saved(world, ctrl)["scan_command_var1"] == "H 1.9 2.1 0.01"   # the saved file names no rhm

    sim.scan_command_1_edit.setText("rhm 10 20 2")
    _settle()
    assert _agree(ctrl)["rhm"] == "scanned"
    assert mark_for(_edit(ctrl, "rhm")).state()[0] == "scanned"
    assert _flag(ctrl) == "● 1 not tracking"

    ctrl.set_default_parameters()                          # File > Defaults
    _settle()
    _assert_rhm_free(ctrl)

    sim.scan_command_1_edit.setText("rhm 10 20 2")
    _settle()
    assert _agree(ctrl)["rhm"] == "scanned"
    ctrl.load_parameters()                                 # File > Load Parameters
    _settle()
    _assert_rhm_free(ctrl)


# ------------------------------------------------------------------ saved files

@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_a_saved_file_with_all_four_held_loads_held(world, instrument_id):
    ctrl = world(instrument_id)
    ctrl.save_parameters()
    _rewrite_saved(world, ctrl, lambda block: block.update(
        {f"{a}_ideal_locked": False for a in FOCUSING_AXES}))
    ctrl.set_default_parameters()
    ctrl.load_parameters()
    _settle()

    modes = _agree(ctrl, NEVER[instrument_id])
    assert not any(ctrl.window.instrument_dock.choice(a) for a in FOCUSING_AXES)
    assert set(modes.values()) <= {"held", "fixed"}
    assert all(ctrl.get_gui_values()["curvature_modes"][a] == HELD for a in FOCUSING_AXES)


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_a_saved_file_without_the_keys_loads_tracking_and_saves_the_same_choices(world, instrument_id):
    ctrl = world(instrument_id)
    ctrl.save_parameters()
    _rewrite_saved(world, ctrl, lambda block: [block.pop(f"{a}_ideal_locked") for a in FOCUSING_AXES])
    for axis in FOCUSING_AXES:   # start from the opposite of the expectation
        ctrl.window.instrument_dock.set_choice(axis, axis in NEVER[instrument_id])
    ctrl.load_parameters()
    _settle()

    modes = _agree(ctrl, NEVER[instrument_id])
    assert {a for a, m in modes.items() if m == "track"} == set(FOCUSING_AXES) - set(NEVER[instrument_id])
    ideal = _ideal(ctrl)
    for axis in _tracked(ctrl):
        assert _text(ctrl, axis) == pytest.approx(ideal[axis], abs=1e-3)
    # a crystal-fixed axis (PUMA's rva) loads held, as the fresh default does, and saves that way
    ctrl.save_parameters()
    assert {a: _saved(world, ctrl)[f"{a}_ideal_locked"] for a in FOCUSING_AXES} == {
        a: a not in NEVER[instrument_id] for a in FOCUSING_AXES}


def test_an_old_puma_file_without_the_keys_records_rva_held_after_load_and_save(world):
    ctrl = world("puma")
    ctrl.save_parameters()
    _rewrite_saved(world, ctrl, lambda block: [block.pop(f"{a}_ideal_locked") for a in FOCUSING_AXES])
    ctrl.load_parameters()
    _settle()
    assert ctrl.get_gui_values()["curvature_modes"]["rva"] == HELD
    ctrl.save_parameters()
    assert _saved(world, ctrl)["rva_ideal_locked"] is False
    _agree(ctrl, NEVER["puma"])


# ------------------------------------------- what the block says: summary, flag, rows

def _group(ctrl):
    return ctrl.window.instrument_dock.collapsible_groups["instrument.focusing"]


def _rows(ctrl):
    """The folded summary: two rows of cells, the full text of each."""
    return _group(ctrl)._summary


def _flag(ctrl):
    group = _group(ctrl)
    return "" if group.flag_label.isHidden() else group.flag_label.text()


def _status(ctrl, axis):
    label = getattr(ctrl.window.instrument_dock, f"{axis}_status_label")
    return "" if label.isHidden() else label.text()


def _cells(ctrl, words):
    """The 2x2 the summary should be: each axis's field text and its mode word."""
    return [[f"{a} {_edit(ctrl, a).text()} m {words[a]}" for a in pair]
            for pair in (("rhm", "rvm"), ("rha", "rva"))]


def _words(**changes):
    return {"rhm": "track", "rvm": "track", "rha": "track", "rva": "track", **changes}


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_all_tracking_is_a_2x2_with_no_flag_and_a_fixed_axis_never_counts(world, instrument_id):
    ctrl = world(instrument_id)
    words = _words(**{a: "fixed" for a in NEVER[instrument_id]})
    assert _rows(ctrl) == _cells(ctrl, words)
    assert _flag(ctrl) == ""                                  # PUMA's fixed rva alone: no flag
    assert not _group(ctrl).flag_label.toolTip()
    for axis in FOCUSING_AXES:                                # no status line on a tracking row
        label = getattr(ctrl.window.instrument_dock, f"{axis}_status_label")
        assert label.isHidden() == (axis not in NEVER[instrument_id]), axis
        assert (label.text() == "") == (axis not in NEVER[instrument_id]), axis


def test_one_held_axis_is_flagged_and_the_flag_names_it(world):
    ctrl = world("puma")
    _box(ctrl, "rhm").click()
    assert _rows(ctrl) == _cells(ctrl, _words(rhm="held", rva="fixed"))
    assert _flag(ctrl) == "● 1 not tracking"
    assert "rhm held" in _group(ctrl).flag_label.toolTip()
    assert "tick track ideal" in _group(ctrl).flag_label.toolTip().lower()
    assert "rvm" not in _group(ctrl).flag_label.toolTip()
    assert _group(ctrl).flag_label.accessibleName() == "● 1 not tracking"
    _box(ctrl, "rhm").click()                                 # tick again: the flag goes out
    assert _flag(ctrl) == "" and _rows(ctrl) == _cells(ctrl, _words(rva="fixed"))


def test_a_held_axis_equal_to_its_ideal_still_counts(world):
    ctrl = world("in8")
    _box(ctrl, "rha").click()                                 # untick: the field keeps the ideal
    assert _text(ctrl, "rha") == pytest.approx(_ideal(ctrl)["rha"], abs=1e-3)
    assert _flag(ctrl) == "● 1 not tracking"
    assert _status(ctrl, "rha") == "held at the ideal"


def test_a_scanned_axis_counts_and_says_which_command(world):
    ctrl = world("puma")
    ctrl.window.simulation_dock.scan_command_2_edit.setText("")
    ctrl.window.simulation_dock.scan_command_1_edit.setText("rhm 10 20 2")
    ctrl._refresh_scan_feedback()
    assert _rows(ctrl) == _cells(ctrl, _words(rhm="scanned", rva="fixed"))
    assert _flag(ctrl) == "● 1 not tracking"
    tip = _group(ctrl).flag_label.toolTip()
    assert "command 1" in tip and "open the block" not in tip.lower()   # a scanned axis is not changed in the block
    assert _status(ctrl, "rhm") == "scanned by command 1; remove rhm from the command to restore your setting"
    ctrl.window.simulation_dock.scan_command_1_edit.setText("")
    ctrl._refresh_scan_feedback()
    assert _flag(ctrl) == "" and _status(ctrl, "rhm") == ""


def test_in12_heusler_rva_counts_and_reads_held_in_the_summary(world):
    ctrl = world("in12")
    ctrl.window.instrument_dock.set_ana_id("heusler111")
    _settle()
    assert _rows(ctrl) == _cells(ctrl, _words(rva="held"))    # no model: the typed value is held
    assert _flag(ctrl) == "● 1 not tracking"
    assert "rva held" in _group(ctrl).flag_label.toolTip()
    assert _status(ctrl, "rva").startswith("held: tracking unavailable, no established focusing model")


def test_the_flag_counts_held_and_scanned_but_not_the_fixed_nmo_axes(world):
    ctrl = world("puma")
    idock = ctrl.window.instrument_dock
    idock.module_widgets["nmo"].setCurrentText("Both")        # rhm, rvm, rva all fixed
    _settle()
    assert _flag(ctrl) == ""
    assert _rows(ctrl)[0] == ["rhm flat fixed", "rvm flat fixed"]   # a flat fixed radius reads flat
    assert _rows(ctrl)[1] == _cells(ctrl, _words(rva="fixed"))[1]
    _box(ctrl, "rha").click()
    assert _flag(ctrl) == "● 1 not tracking"
    ctrl.window.simulation_dock.scan_command_1_edit.setText("rha 2 3 0.5")
    ctrl._refresh_scan_feedback()                             # held choice, now scanned: still one
    assert _flag(ctrl) == "● 1 not tracking"
    ctrl.window.simulation_dock.scan_command_1_edit.setText("")
    ctrl._refresh_scan_feedback()
    idock.module_widgets["nmo"].setCurrentText("None")
    _settle()


def test_a_flat_fixed_radius_reads_flat_in_the_folded_cell(world):
    ctrl = world("puma")
    ctrl.window.instrument_dock.module_widgets["nmo"].setCurrentText("Both")
    _settle()
    assert _rows(ctrl)[0] == ["rhm flat fixed", "rvm flat fixed"]   # the open block says "flat"
    ctrl.window.instrument_dock.module_widgets["nmo"].setCurrentText("None")
    _settle()


def test_the_flag_shows_folded_and_open_and_the_summary_follows_every_edit(world):
    ctrl = world("puma")
    group, idock = _group(ctrl), ctrl.window.instrument_dock
    ctrl.unlock_ideal_bending("rvm")
    try:
        for collapsed in (True, False):
            group.set_collapsed(collapsed)
            assert not group.flag_label.isHidden() and group.flag_label.text() == "● 1 not tracking"
        idock.rvm_edit.setText("1.234")                       # every field edit reaches the cell
        assert _rows(ctrl)[0][1] == "rvm 1.234 m held"
        idock.rvm_edit.setText("")
        assert _rows(ctrl)[0][1] == "rvm empty held"
    finally:
        group.set_collapsed(True)


# ------------------------------------------------------------- the status line

def test_the_held_difference_is_signed_in_metres_and_follows_every_edit(world):
    ctrl = world("in8")
    ctrl.unlock_ideal_bending("rhm")
    ideal = _ideal(ctrl)["rhm"]
    edit = _edit(ctrl, "rhm")
    edit.setText(f"{ideal + 0.12:.3f}")
    assert _status(ctrl, "rhm") == "held, 0.120 m above ideal"
    edit.setText(f"{ideal - 0.2:.3f}")
    assert _status(ctrl, "rhm") == "held, 0.200 m below ideal"
    edit.setText(f"{ideal:.3f}")
    assert _status(ctrl, "rhm") == "held at the ideal"
    edit.setText("")
    assert _status(ctrl, "rhm") == "held, the field is not a number"
    edit.setText(f"{ideal + 1:.3f}")
    assert _status(ctrl, "rhm") == "held, 1.000 m above ideal"
    _scale_angle(ctrl, "mtt", 1.15)                           # the ideal moves under a held value
    moved = _ideal(ctrl)["rhm"]
    shown = _status(ctrl, "rhm")
    assert shown == f"held, {abs(ideal + 1 - moved):.3f} m {'above' if ideal + 1 > moved else 'below'} ideal"
    assert shown != "held, 1.000 m above ideal"


def test_the_status_line_says_each_non_tracking_reason_and_a_tracking_row_has_none(world):
    ctrl = world("puma")
    assert [_status(ctrl, a) for a in FOCUSING_AXES] == ["", "", "", "fixed at 0.8 m for the PG[002] analyser"]
    ctrl.window.instrument_dock.module_widgets["nmo"].setCurrentText("Both")
    _settle()
    assert _status(ctrl, "rhm").startswith("fixed") and "flat while the NMO is fitted" in _status(ctrl, "rhm")
    ctrl.window.instrument_dock.module_widgets["nmo"].setCurrentText("None")
    _settle()
    assert _status(ctrl, "rhm") == ""


# --------------------------------------------------------------- tooltips and help

def _tips(ctrl, axis):
    idock = ctrl.window.instrument_dock
    return (_box(ctrl, axis).toolTip(), _edit(ctrl, axis).toolTip(),
            getattr(idock, f"{axis}_ideal_label").toolTip())


def test_every_mode_explains_itself_in_sentences_on_the_box_the_field_and_the_ideal(world):
    ctrl = world("puma")
    idock = ctrl.window.instrument_dock
    box, field, readout = _tips(ctrl, "rhm")                  # tracking
    assert "follows the calculated ideal" in box and "every scan point" in box and "type a value" in box
    assert "every scan point" in field and "every scan point" in readout
    assert all(tip.endswith(".") for tip in (box, field, readout))

    _box(ctrl, "rhm").click()                                 # held
    ideal = f"{_ideal(ctrl)['rhm']:.3f} m"
    box, field, readout = _tips(ctrl, "rhm")
    for tip in (box, field):
        assert "whole scan" in tip and ideal in tip and "Tick Track ideal to follow it again" in tip
    assert "held" in readout and "metres" in readout
    _box(ctrl, "rhm").click()

    ctrl.window.simulation_dock.scan_command_1_edit.setText("rhm 10 20 2")   # scanned
    ctrl._refresh_scan_feedback()
    box, field, _readout = _tips(ctrl, "rhm")
    assert "command 1" in box and "disabled" in box and "applies again" in box
    assert "command 1" in field
    ctrl.window.simulation_dock.scan_command_1_edit.setText("")
    ctrl._refresh_scan_feedback()

    box, field, readout = _tips(ctrl, "rva")                  # fixed: a disabled box gives its reason
    assert not _box(ctrl, "rva").isEnabled()
    assert "0.8 m" in box and "hardware" in box and "0.8 m" in field and "hardware" in readout
    assert idock.mode("rva") == "fixed"


def test_a_no_model_axis_tooltips_give_the_reason(world):
    ctrl = world("in12")
    ctrl.window.instrument_dock.set_ana_id("heusler111")
    _settle()
    box, field, readout = _tips(ctrl, "rva")
    assert not _box(ctrl, "rva").isEnabled()
    for tip in (box, field):
        assert "no established focusing model for the Heusler[111]" in tip
    assert "held for the whole scan" in box
    assert "no ideal" in readout.lower()


def test_one_help_line_says_what_a_scan_does_with_each_mode(world):
    ctrl = world("puma")
    help_line = ctrl.window.instrument_dock.focusing_help_label
    assert help_line.wordWrap() and not help_line.isHidden()
    text = help_line.text()
    for words in ("Tracked radii follow the ideal at every scan point", "Held radii",
                  "whole scan", "named in a scan command is scanned instead"):
        assert words in text, words


def test_accessible_names_on_the_boxes_the_readouts_and_the_flag(world):
    ctrl = world("in8")
    idock = ctrl.window.instrument_dock
    for axis in FOCUSING_AXES:
        assert axis in _box(ctrl, axis).accessibleName() and "Track ideal" in _box(ctrl, axis).accessibleName()
        assert axis in getattr(idock, f"{axis}_ideal_label").accessibleName()
    _box(ctrl, "rhm").click()
    assert _box(ctrl, "rhm").accessibleDescription().startswith("held")
    assert _group(ctrl).flag_label.accessibleName() == "● 1 not tracking"


# ------------------------------------------------------------------- continuity

def test_a_background_ideal_update_never_touches_a_held_field_or_its_selection(world):
    ctrl = world("in8")
    ctrl.unlock_ideal_bending("rha")
    edit = _edit(ctrl, "rha")
    edit.setText("7.123456")
    edit.setFocus()
    edit.setSelection(2, 3)
    focus_before = QApplication.focusWidget()
    _scale_angle(ctrl, "att", 1.15)                           # the ideals move
    ctrl.update_ideal_bending_buttons()
    _settle()
    assert edit.text() == "7.123456"
    assert (edit.selectionStart(), edit.selectedText()) == (2, "123")
    assert QApplication.focusWidget() is focus_before
