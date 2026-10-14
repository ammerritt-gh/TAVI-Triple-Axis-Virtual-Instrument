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
    assert "flat" in _box(ctrl, "rhm").toolTip()
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
