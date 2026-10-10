"""Field marks bound to the live plan preview, on the real offscreen window (PUMA).

Each test drives the window the way an operator does -- typing in the command
boxes, toggling Relative, changing the docks' combos and fields -- then lets
the event loop run and reads every field's mark (``mark_for(field).state()``).
Nothing here calls ``update_field_marks`` itself: the marks must follow from
the controller's own triggers. The last test renders the mockup's case at the
two reference window sizes, saves the docks as PNGs and checks that the marks
move no widget and are not clipped. Its PNGs go to pytest's tmp_path; set
TAVI_SCREENSHOT_DIR to a folder to keep them (for example
C:\\Users\\AMM\\AppData\\Local\\Temp\\claude\\tavi-u4) for a visual check.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QStyle, QStyleOptionGroupBox, QWidget  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from gui.docks.base_dock import NARROW, WIDE  # noqa: E402
from gui.field_marks import mark_for  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.quantities import QUANTITIES  # noqa: E402
from test_compact_layout import LAPTOP, MONITOR, _resize, _use_windows_ui_font  # noqa: E402

NOTE = "not used by this scan"
A2, A1, A3, A4, A6, A5 = ("mono_two_theta_deg", "mono_theta_deg", "sample_rotation_deg",
                          "sample_two_theta_deg", "analyzer_two_theta_deg", "analyzer_theta_deg")
SGL, SGU = "sample_lower_arc_deg", "sample_upper_arc_deg"
QX, QY, QZ = ("q_instrument_x_inv_angstrom", "q_instrument_y_inv_angstrom",
              "q_instrument_z_inv_angstrom")
DE, EI, EF = "energy_transfer_mev", "incident_energy_mev", "final_energy_mev"
KI, KF = "incident_wavevector_inv_angstrom", "final_wavevector_inv_angstrom"
RHM, RVM, RVA = "mono_horizontal_radius_m", "mono_vertical_radius_m", "analyzer_vertical_radius_m"
STAGE = (A3, A4, SGL, SGU)
MONO, ANALYZER = (A2, A1, EI, KI), (A6, A5, EF, KF)
FIXED_RVA = {RVA: ("set", "fixed")}   # PUMA's analyzer bends vertically at a fixed 0.8 m


def _window(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cm.TAVIMainWindow, "_restore_layout_from_file", lambda self: False)
        win = cm.TAVIMainWindow(
            instrument.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id=instrument.id, save_selection=lambda _id: None,
        )
    ctrl = cm.TAVIController(win, instrument, api_overrides={"disabled": True})
    win.controller = ctrl  # as main() does
    win.show()
    app.processEvents()
    return win


def _close(win):
    win.controller.shutdown()
    win.deleteLater()
    QApplication.processEvents()


@pytest.fixture(scope="module")
def window():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    _use_windows_ui_font(app)
    win = _window("puma")
    try:
        yield win
    finally:
        _close(win)
        app.setFont(font)


@pytest.fixture(autouse=True)
def defaults(window):
    """Every test starts from the default parameters with both boxes empty, and leaves it so."""
    def reset():
        sim = window.simulation_dock
        for button in (sim.relative_1_button, sim.relative_2_button):
            button.setChecked(False)
        sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("mcstas"))
        window.controller.set_default_parameters()
        _type(window, "", "")
    reset()
    yield
    reset()


def _settle():
    for _ in range(3):   # the coalescing timer, then anything it posts
        QApplication.processEvents()


def _type(win, cmd1, cmd2="", rel1=None, rel2=None):
    sim = win.simulation_dock
    if rel1 is not None:
        sim.relative_1_button.setChecked(rel1)
    if rel2 is not None:
        sim.relative_2_button.setChecked(rel2)
    sim.scan_command_1_edit.setText(cmd1)
    sim.scan_command_2_edit.setText(cmd2)
    _settle()


def _fields(win):
    docks = (win.instrument_dock, win.scattering_dock)
    return {q.id: field for q in QUANTITIES for dock in docks
            if (field := dock.field_for(q.id)) is not None}


def _marks(win):
    """{canonical ID: (style, badge)} for every marked field."""
    out = {}
    for qid, field in _fields(win).items():
        style, badge, _command, _tooltip = mark_for(field).state()
        if style is not None:
            out[qid] = (style, badge)
    return out


def _state(win, qid):
    return mark_for(_fields(win)[qid]).state()


def _note(win):
    note = getattr(win.scattering_dock.point_group, "_group_note", None)
    return note.text() if note is not None and not note.isHidden() else None


def _set(ids, badge):
    return {qid: ("set", badge) for qid in ids}


# ------------------------------------------------------------ the plan's roles

def test_h_alone(window):
    _type(window, "H 1.9 2.1 0.05")
    assert _marks(window) == {
        "h": ("scanned", "1"), **_set((QX, QY, QZ, *STAGE), "1"),
        **_set((*MONO, *ANALYZER), "fixed Kf"), **FIXED_RVA}
    assert _state(window, "h")[2] == 1   # drawn in command 1's colour
    assert _note(window) is None


def test_h_and_k(window):
    _type(window, "H 1.9 2.1 0.05", "K 0 0.2 0.05")
    assert _marks(window) == {
        "h": ("scanned", "1"), "k": ("scanned", "2"), **_set((QX, QY, QZ, *STAGE), "1+2"),
        **_set((*MONO, *ANALYZER), "fixed Kf"), **FIXED_RVA}


@pytest.mark.parametrize("side", ["Kf", "Ki"])
def test_h_and_deltae_names_the_fixed_side(window, side):
    """The fixed side's crystal follows the setting, the other the transfer; the arcs follow H alone."""
    window.scattering_dock.K_fixed_combo.setCurrentText(f"{side} Fixed")
    _type(window, "H 1.9 2.1 0.05", "deltaE 0 2 0.5")
    held, moved = (ANALYZER, MONO) if side == "Kf" else (MONO, ANALYZER)
    assert _marks(window) == {
        "h": ("scanned", "1"), DE: ("scanned", "2"), **_set((QX, QY, QZ, SGL, SGU), "1"),
        **_set((A3, A4), "1+2"), **_set(held, f"fixed {side}"), **_set(moved, "2"), **FIXED_RVA}


def test_relative_a3_shows_its_base_and_range_and_the_unread_group(window):
    idock = window.instrument_dock
    base = float(idock.omega_edit.text())
    _type(window, "A3 -2 3 0.5", rel1=True)
    assert _marks(window) == {A3: ("scanned", "1 +Δ"), **FIXED_RVA}   # energies agree: unmarked
    tooltip = _state(window, A3)[3]
    for value in (base, base - 2, base + 3):
        assert f"{cm.format_editable_number(value)}°" in tooltip, tooltip
    assert _note(window) == NOTE

    idock.omega_edit.setText("")
    _settle()
    style, badge, _command, tooltip = _state(window, A3)
    assert (style, badge) == ("scanned", "1 +Δ")
    assert "empty" in tooltip and "Run will refuse" in tooltip
    assert _note(window) is None   # the scan does not compile: nothing else is claimed


def test_a2_scan_sets_ei_at_each_point(window):
    _type(window, "A2 40 42 1")
    marks = _marks(window)
    assert marks[A2] == ("scanned", "1")
    assert {qid: marks[qid] for qid in (A1, EI, KI, DE)} == _set((A1, EI, KI, DE), "1")
    assert not {A6, A5, EF, KF} & marks.keys()


def test_ruling_1_marks_a_stale_display_until_it_is_consistent(window):
    """Ei set from typed A2 alone is constant: marked only while the field shows another value."""
    ctrl, idock = window.controller, window.instrument_dock
    _type(window, "A3 0 2 1")
    assert EI not in _marks(window)
    idock.mtt_edit.setText("40")   # typed, not yet committed: Ei still shows the old value
    _settle()
    style, badge, command, tooltip = _state(window, EI)
    assert (style, badge, command) == ("set", "from A2", None)
    assert "Run will use" in tooltip and "meV" in tooltip
    assert _state(window, DE)[:2] == ("set", "from A2+A6")
    ctrl.on_mtt_changed()   # Enter: the handler re-derives the energies from A2
    _settle()
    assert not {EI, KI, DE} & _marks(window).keys()


def test_autofocused_radius_follows_its_crystal_and_a_scanned_one_is_scanned(window):
    ctrl = window.controller
    _type(window, "deltaE 0 2 0.5")
    assert RHM not in _marks(window)   # held: used as typed
    ctrl.apply_ideal_bending_value("rhm")   # Ideal lock: autofocus follows the mono 2θ
    _settle()
    try:
        assert _state(window, RHM)[:2] == ("set", "1")
        _type(window, "deltaE 0 2 0.5", "rhm 2.5 3 0.5")
        assert _state(window, RHM)[:3] == ("scanned", "2", 2)
    finally:
        ctrl.unlock_ideal_bending("rhm")


def test_slit_scan_marks_the_gap_field(window):
    _type(window, "pre_sample_hgap 10 20 5")
    field = window.instrument_dock.slit_widgets["pbl"]["width"]
    assert mark_for(field).state()[:3] == ("scanned", "1", 1)
    assert "mm" in mark_for(field).state()[3]


def test_a_lone_command_2_keeps_its_number(window):
    _type(window, "", "H 1.9 2.1 0.05")
    marks = _marks(window)
    assert marks["h"] == ("scanned", "2") and _state(window, "h")[2] == 2
    assert {qid: marks[qid] for qid in STAGE} == _set(STAGE, "2")


def test_a_half_typed_command_withdraws_every_mark(window):
    sim = window.simulation_dock
    _type(window, "H 1.9 2.1 0.05")
    assert _marks(window)[A3] == ("set", "1")
    sim.scan_command_1_edit.setText("H 1.9")
    _settle()
    assert _marks(window) == {}   # "H 1.9" is no command, and the pair does not compile
    assert not sim.scan_warning_1_label.isHidden() and sim.scan_warning_1_label.text()


def test_a_refused_pair_keeps_only_each_commands_own_scanned_mark(window):
    sim = window.simulation_dock
    _type(window, "H 1.9 2.1 0.05", "A4 40 42 1")
    assert _marks(window) == {"h": ("scanned", "1"), A4: ("scanned", "2")}
    assert sim.scan_conflict_label.text().startswith(
        "A4 (sample 2θ) is calculated from H in the HKL calculation")


# ------------------------------------------------------------ context triggers

def test_fixed_side_change(window):
    _type(window, "H 1.9 2.1 0.05")
    assert _state(window, A6)[:2] == ("set", "fixed Kf")
    window.scattering_dock.K_fixed_combo.setCurrentText("Ki Fixed")
    _settle()
    assert _state(window, A6)[:2] == ("set", "fixed Ki")


def test_curvature_policy_change(window):
    ctrl = window.controller
    _type(window, "deltaE 0 2 0.5")
    assert RVM not in _marks(window)
    ctrl.apply_ideal_bending_value("rvm")
    _settle()
    try:
        assert _state(window, RVM)[:2] == ("set", "1")
    finally:
        ctrl.unlock_ideal_bending("rvm")
    _settle()
    assert RVM not in _marks(window)


def test_plane_lock(window):
    ctrl = window.controller
    _type(window, "H 1.9 2.1 0.05")
    assert _state(window, SGL)[:2] == ("set", "1")
    ctrl.on_lock_plane()
    _settle()
    try:
        assert ctrl.instrument_state.plane_lock is not None
        assert _marks(window)[SGL] == _marks(window)[SGU] == ("set", "plane lock")
    finally:
        ctrl.on_release_plane()
    _settle()
    assert _state(window, SGL)[:2] == ("set", "1")


def test_module_change(window):
    idock = window.instrument_dock
    _type(window, "H 1.9 2.1 0.05")
    assert RVM not in _marks(window)
    idock.module_widgets["nmo"].setCurrentText("Both")   # the NMO holds the mono flat
    _settle()
    try:
        assert _marks(window)[RVM] == ("set", "fixed")
    finally:
        idock.module_widgets["nmo"].setCurrentText("None")
    _settle()
    assert RVM not in _marks(window)


def test_engine_change(window):
    """A slit scan is refused on the analytic engine (no aperture model), so its mark goes."""
    sim = window.simulation_dock
    field = window.instrument_dock.slit_widgets["pbl"]["width"]
    _type(window, "pre_sample_hgap 10 20 5")
    assert mark_for(field).state()[0] == "scanned"
    sim.engine_combo.setCurrentIndex(sim.engine_combo.findData("deterministic"))
    _settle()
    assert mark_for(field).state()[0] is None


def test_lattice_edit(window):
    """An emptied lattice parameter refuses the plan, so the marks go; typed back, they return."""
    sample = window.sample_dock
    _type(window, "H 1.9 2.1 0.05")
    text = sample.lattice_a_edit.text()
    sample.lattice_a_edit.setText("")
    _settle()
    assert _marks(window) == {}
    sample.lattice_a_edit.setText(text)
    _settle()
    assert _marks(window)[A3] == ("set", "1")


def test_instrument_switch_and_crystal_change():
    """A restart on IN12 binds the new docks; its PG analyzer holds rva, the Heusler one does not."""
    win = _window("in12")
    try:
        win.controller.set_default_parameters()
        _type(win, "H 1.9 2.1 0.05")
        assert _marks(win)["h"] == ("scanned", "1")
        assert _marks(win)[RVA] == ("set", "fixed")
        win.instrument_dock.set_ana_id("heusler111")
        _settle()
        assert RVA not in _marks(win)
    finally:
        _close(win)


# ------------------------------------------------------------------ continuity

def test_mark_updates_leave_focus_selection_style_and_names_alone(window):
    sim, idock = window.simulation_dock, window.instrument_dock
    window.activateWindow()
    box = sim.scan_command_1_edit
    box.setFocus()
    QTest.keyClicks(box, "H 1.9 2.1 0.05")
    _settle()
    box.setSelection(2, 3)
    fields = _fields(window)
    before = {qid: (f.styleSheet(), f.accessibleName(), f.text()) for qid, f in fields.items()}
    stt = idock.stt_edit
    stt.setCursorPosition(1)
    sim.relative_2_button.setChecked(True)   # a context change and an edit: marks update
    sim.scan_command_2_edit.setText("K 0 0.2 0.05")
    _settle()
    assert _marks(window)["k"] == ("scanned", "2 +Δ")
    assert QApplication.focusWidget() is box
    assert (box.selectionStart(), box.selectedText()) == (2, "1.9")
    assert stt.cursorPosition() == 1
    after = {qid: (f.styleSheet(), f.accessibleName(), f.text()) for qid, f in fields.items()}
    assert after == before


# ------------------------------------------------------- geometry and pictures

def _overlay_widgets(win):
    marks = [mark_for(field) for field in _fields(win).values()]
    note = getattr(win.scattering_dock.point_group, "_group_note", None)
    return {w for m in marks for w in (m._outline, m._badge)} | ({note} if note else set())


def _geometries(win, docks, skip):
    return {w: (w.geometry(), w.isVisible()) for dock in docks
            for w in dock.findChildren(QWidget) if w not in skip}


def _assert_inside(win):
    """Every shown outline, badge and note lies inside the box that hosts it, badges unclipped."""
    for qid, field in _fields(win).items():
        mark = mark_for(field)
        for widget in (mark._outline, mark._badge):
            if widget.isVisible():
                assert widget.parentWidget().rect().contains(widget.geometry()), qid
        if mark._badge.isVisible():
            assert mark._badge.width() >= mark._badge.sizeHint().width(), qid
    group = win.scattering_dock.point_group
    note = getattr(group, "_group_note", None)
    if note is not None and note.isVisible():
        assert group.rect().contains(note.geometry())
        option = QStyleOptionGroupBox()
        group.initStyleOption(option)
        title = group.style().subControlRect(QStyle.CC_GroupBox, option,
                                             QStyle.SC_GroupBoxLabel, group)
        assert note.geometry().left() > title.right(), "the note covers the group title"


@pytest.mark.parametrize("size, mode, columns", [(LAPTOP, NARROW, 2), (MONITOR, WIDE, 3)],
                         ids=["laptop-2col-narrow", "monitor-3col-wide"])
def test_mockup_case_moves_nothing_and_clips_nothing(window, size, mode, columns, tmp_path):
    """H 0.9 1.1 0.02 in box 1, deltaE -1 1 0.25 relative in box 2, fixed Kf; then an A3 scan for the note."""
    _resize(window, size, mode, columns)
    ctrl, idock = window.controller, window.instrument_dock
    docks = {"simulation": window.simulation_dock, "scattering": window.scattering_dock,
             "instrument": idock}
    labels = [idock.mtt_label, idock.omega_label, idock.stt_label, idock.att_label,
              idock.sgl_label, idock.sgu_label]
    shots = os.environ.get("TAVI_SCREENSHOT_DIR") or str(tmp_path)
    os.makedirs(shots, exist_ok=True)
    tag = f"{size[0]}x{size[1]}"
    for case, (cmd1, cmd2, rel2) in {"mockup": ("H 0.9 1.1 0.02", "deltaE -1 1 0.25", True),
                                     "a3": ("A3 -2 2 0.5", "", False)}.items():
        _type(window, cmd1, cmd2, rel1=False, rel2=rel2)
        ctrl._update_scan_estimates()   # the debounced count first: below, only the marks change
        _settle()
        for field in _fields(window).values():
            mark_for(field).set_mark(None)
        cm.set_group_note(window.scattering_dock.point_group, None)
        _settle()
        skip = _overlay_widgets(window)
        before = _geometries(window, docks.values(), skip)
        ctrl.update_field_marks()
        _settle()
        assert _overlay_widgets(window) == skip   # no new widget appeared
        assert _geometries(window, docks.values(), skip) == before, "a mark moved a widget"
        _assert_inside(window)
        for label in labels:
            assert label.isVisible() and label.width() >= label.sizeHint().width(), label.text()
        for name, dock in docks.items():
            suffix = "" if case == "mockup" else "-a3"
            assert dock.grab().save(os.path.join(shots, f"s42-{tag}-{name}{suffix}.png"))
        if case == "mockup":
            assert _marks(window)["h"] == ("scanned", "1")
            assert _marks(window)[DE] == ("scanned", "2 +Δ")
            assert _marks(window)[A6] == ("set", "fixed Kf")
        else:
            assert _note(window) == NOTE
