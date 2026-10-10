"""Field marks on offscreen Qt: the overlay, badge and group note leave layouts alone.

Also pins the simulation dock's command chips and legend, placed so the
warning labels above them keep their place.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (QApplication, QGridLayout, QGroupBox, QHBoxLayout,  # noqa: E402
                               QLabel, QLineEdit, QWidget)

from gui import theme  # noqa: E402
from gui.docks.unified_simulation_dock import UnifiedSimulationDock  # noqa: E402
from gui.field_marks import mark_for, set_group_note  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([sys.argv[0]])


def _form(app, edge=False):
    """A label and a field in a shown box, the field at the box's right edge when ``edge``."""
    box = QWidget()
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    field = QLineEdit("0.9")
    field.setStyleSheet("QLineEdit{border:1px solid #b8b8b8;}")
    grid.addWidget(QLabel("H"), 0, 0)
    grid.addWidget(field, 0, 1)
    if not edge:
        grid.setColumnStretch(2, 1)
    box.show()
    app.processEvents()
    return box, field


def test_mark_leaves_stylesheet_geometry_and_size_hint_alone(app):
    box, field = _form(app)
    style, geometry, hint = field.styleSheet(), field.geometry(), box.sizeHint()
    mark = mark_for(field)
    mark.set_mark("scanned", "1 +Δ", 1, "base 0.9; range 0.9 to 1.1")
    app.processEvents()
    assert field.styleSheet() == style
    assert field.geometry() == geometry
    assert box.sizeHint() == hint
    assert mark.state() == ("scanned", "1 +Δ", 1, "base 0.9; range 0.9 to 1.1")
    assert mark_for(field) is mark


def test_overlay_is_mouse_transparent_and_badge_carries_tooltip(app):
    box, field = _form(app)
    mark = mark_for(field)
    mark.set_mark("set", "1+2")
    app.processEvents()
    assert mark._outline.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert mark._outline.isVisible() and mark._badge.isVisible()
    mark.set_mark("scanned", "2 +Δ", 2, "base 4.000 meV; range 3.000 to 5.000 meV")
    assert mark._badge.toolTip() == "base 4.000 meV; range 3.000 to 5.000 meV"


def test_no_mark_hides_overlay_and_badge(app):
    box, field = _form(app)
    mark = mark_for(field)
    mark.set_mark("scanned", "1", 1)
    mark.set_mark(None)
    app.processEvents()
    assert not mark._outline.isVisible() and not mark._badge.isVisible()
    assert mark.state() == (None, "", None, "")


def test_badge_stays_inside_parent_at_right_edge(app):
    box, field = _form(app, edge=True)
    assert field.geometry().right() == box.rect().right()
    mark = mark_for(field)
    mark.set_mark("scanned", "2 +Δ", 2)
    app.processEvents()
    assert mark._badge.isVisible()
    assert box.rect().contains(mark._badge.geometry())


def test_group_note_shows_hides_without_size_change(app):
    box = QGroupBox("Fixed Mode")
    grid = QGridLayout(box)
    grid.addWidget(QLabel("Fixed E:"), 0, 0)
    grid.addWidget(QLineEdit(), 0, 1)
    box.show()
    app.processEvents()
    hint = box.sizeHint()
    set_group_note(box, "not used by this scan")
    app.processEvents()
    note = next(label for label in box.findChildren(QLabel)
                if label.text() == "not used by this scan")
    assert note.isVisible() and box.sizeHint() == hint
    set_group_note(box, None)
    app.processEvents()
    assert not note.isVisible() and box.sizeHint() == hint


def test_field_in_tight_cell_keeps_its_outline(app):
    """The overlay lives in the group box, not the zero-margin cell that would clip it."""
    group = QGroupBox("Instrument Angles")
    grid = QGridLayout(group)
    grid.setSpacing(3)
    cell = QWidget()
    cell_layout = QHBoxLayout(cell)
    cell_layout.setContentsMargins(0, 0, 0, 0)
    field = QLineEdit("2")
    cell_layout.addWidget(field)
    grid.addWidget(QLabel("Mono 2θ"), 0, 0)
    grid.addWidget(cell, 0, 1)
    group.show()
    app.processEvents()
    mark = mark_for(field)
    mark.set_mark("set", "2")
    app.processEvents()
    assert mark._outline.parentWidget() is group
    field_rect = QRect(field.mapTo(group, QPoint(0, 0)), field.size())
    outline_rect = QRect(mark._outline.mapTo(group, QPoint(0, 0)), mark._outline.size())
    assert outline_rect.contains(field_rect.adjusted(-1, -1, 1, 1))
    # The row just above the field carries the outline colour, not the group's background.
    above = group.grab().toImage().pixelColor(field_rect.center().x(), field_rect.top() - 1)
    assert above == QColor(theme.DERIVED_OUTLINE)


def test_command_chip_text_colour_comes_from_the_theme(app):
    dock = UnifiedSimulationDock()
    assert theme.CHIP_TEXT in dock.scan_chip_1.styleSheet()
    assert theme.CHIP_TEXT in dock.scan_chip_2.styleSheet()
    dock.deleteLater()


def test_simulation_dock_keeps_warnings_and_gains_chips_and_legend(app):
    dock = UnifiedSimulationDock()
    assert dock.scan_warning_1_label is not None
    assert dock.scan_warning_2_label is not None
    assert dock.scan_conflict_label is not None
    assert dock.scan_chip_1.text() == "1" and dock.scan_chip_2.text() == "2"
    assert "dashed = scanned" in dock.scan_legend_label.text()
    dock.show()
    app.processEvents()

    def at(widget):
        return widget.mapTo(dock, QPoint(0, 0))

    for chip, edit in ((dock.scan_chip_1, dock.scan_command_1_edit),
                       (dock.scan_chip_2, dock.scan_command_2_edit)):
        assert at(chip).x() < at(edit).x()
        assert abs(at(chip).y() - at(edit).y()) < edit.height()
    # The legend sits below the command-2 field and above the Valid Commands button.
    assert at(dock.scan_command_2_edit).y() < at(dock.scan_legend_label).y()
    assert at(dock.scan_legend_label).y() < at(dock.show_commands_button).y()
    dock.deleteLater()
    app.processEvents()


def test_the_legend_keys_the_ruling_1_badge_and_the_unmarked_fields(app):
    dock = UnifiedSimulationDock()
    text = dock.scan_legend_label.text()
    dock.deleteLater()
    assert "from A2 = the run recomputes it from that field" in text
    assert "unmarked = used as typed" in text
