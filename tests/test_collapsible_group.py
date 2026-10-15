"""CollapsibleGroup's folded rows, header flag and title elision, offscreen.

A standalone group at the block width in the window's font. Folded, a rows
summary lays out as an aligned grid; a long cell elides with its full text as
tooltip; the header flag stays whole on the header line, folded or open; a
long title elides with its full text kept in the tooltip and accessible name.
A string summary behaves as before.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from gui import metrics, theme  # noqa: E402
from gui.docks.base_dock import CollapsibleGroup  # noqa: E402
from test_compact_layout import _use_windows_ui_font  # noqa: E402

TITLE = "Crystal Focusing (Absolute Radii, m)"
FLAG = "● 4 not tracking"
ROWS = [["rhm 15.08 m track", "rvm 1.39 m held"],
        ["rha 2.30 m scanned", "rva 0.80 m fixed"]]


@pytest.fixture
def make_group():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    _use_windows_ui_font(app)
    groups = []

    def make(title=TITLE):
        group = CollapsibleGroup(title)
        group.setFixedWidth(metrics.BLOCK_WIDTH)
        group.show()
        groups.append(group)
        _settle()
        return group

    try:
        yield make
    finally:
        for group in groups:
            group.deleteLater()
        QApplication.processEvents()
        app.setFont(font)


def _settle():
    for _ in range(3):
        QApplication.processEvents()


def _in(group, widget):
    """The widget's rectangle in the group's own coordinates."""
    return QRect(widget.mapTo(group, QPoint(0, 0)), widget.size())


def _cell(group, text):
    return next(label for label in group.summary_rows.findChildren(QLabel)
                if label.text() == text or label.toolTip() == text)


def test_flag_sits_on_the_header_line_folded_and_open(make_group):
    group = make_group()
    group.set_flag(FLAG, "Two axes ride on their held values.")
    for collapsed in (True, False):
        group.set_collapsed(collapsed)
        _settle()
        flag, header = group.flag_label, _in(group, group.header)
        rect = _in(group, flag)
        assert flag.isVisible(), collapsed
        assert header.top() <= rect.top() and rect.bottom() <= header.bottom(), (rect, header)
        assert flag.width() >= flag.sizeHint().width(), collapsed
        assert flag.text() == FLAG and flag.accessibleName() == FLAG
        assert flag.toolTip() == "Two axes ride on their held values."


def test_empty_flag_is_hidden(make_group):
    group = make_group()
    group.set_flag(FLAG)
    group.set_flag("")
    _settle()
    assert group.flag_label.isHidden()


def test_the_whole_header_row_folds_the_block_when_nothing_is_flagged(make_group):
    group = make_group("Source Control")
    group.set_collapsed(True)
    _settle()
    inner = group.width() - group.layout().contentsMargins().right()
    edge = QPoint(inner - 5, group.header.geometry().center().y())   # the row's right end, past the title
    target = QApplication.widgetAt(group.mapToGlobal(edge))
    assert target is group.header, target
    QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, target.mapFromGlobal(group.mapToGlobal(edge)))
    _settle()
    assert not group.is_collapsed()


def test_flag_text_reads_on_the_panel(make_group):
    group = make_group()
    group.set_flag(FLAG)
    background = QApplication.palette().color(QPalette.Window)
    assert _contrast(QColor(theme.FLAG_TEXT), background) >= 4.5


@pytest.mark.parametrize("title", [TITLE, TITLE + " for every axis the instrument has"])
def test_title_elides_for_the_flag_and_keeps_its_full_text(make_group, title):
    group = make_group(title)
    group.set_flag(FLAG)
    _settle()
    header, flag = group.header, group.flag_label
    assert header.sizeHint().width() <= header.width(), header.text()
    assert _in(group, header).right() <= _in(group, flag).left(), "title runs under the flag"
    assert flag.width() >= flag.sizeHint().width()
    assert header.accessibleName() == title
    if header.text() != title:
        assert header.text().endswith("…")
        assert header.toolTip().startswith(title)
    else:
        assert header.toolTip().startswith(f"Show the {title} fields")


def test_rows_form_a_grid_while_folded(make_group):
    group = make_group()
    group.set_summary(ROWS)
    group.set_collapsed(True)
    _settle()
    assert group.summary_rows.isVisible() and group.summary_label.isHidden()
    rhm, rvm = (_in(group, _cell(group, text)) for text in ROWS[0])
    rha, rva = (_in(group, _cell(group, text)) for text in ROWS[1])
    assert rhm.left() == rha.left() and rvm.left() == rva.left(), "columns not shared"
    assert rhm.left() < rvm.left(), "second column not to the right of the first"
    assert rhm.top() < rha.top(), "second row not below the first"


def test_rows_hide_while_open_and_return_when_folded_again(make_group):
    group = make_group()
    group.set_summary(ROWS)
    group.set_collapsed(True)
    _settle()
    assert group.summary_rows.isVisible()
    group.set_collapsed(False)
    _settle()
    assert not group.summary_rows.isVisible()
    group.set_collapsed(True)
    _settle()
    assert group.summary_rows.isVisible()


def test_long_cell_elides_with_full_text_and_never_widens_the_block(make_group):
    group = make_group()
    long = "rha 2.30 m scanned by the command rha 10 20 2 at every point of the scan"
    group.set_summary([[long, "rva 0.80 m fixed"]])
    group.set_collapsed(True)
    _settle()
    cell = _cell(group, long)
    assert cell.text().endswith("…") and cell.toolTip() == long
    assert _cell(group, "rva 0.80 m fixed").text() == "rva 0.80 m fixed", "short cell elided"
    assert _in(group, cell).right() < group.width()
    assert group.width() == metrics.BLOCK_WIDTH
    assert group.minimumSizeHint().width() <= metrics.BLOCK_WIDTH


def test_string_summary_behaves_as_before(make_group):
    group = make_group()
    line = "rhm 15.0809 ideal, rvm 1.3909 ideal, rha 2.3034 ideal, rva 0.8 ideal, source Mono"
    group.set_summary(ROWS)
    group.set_summary(line)
    group.set_collapsed(True)
    _settle()
    assert group.summary_label.isVisible() and not group.summary_rows.isVisible()
    assert group.summary_label.toolTip() == line
    shown = group.summary_label.text()
    assert shown == line or shown.endswith("…"), shown


def _contrast(foreground, background):
    """WCAG contrast ratio of two colours."""
    def luminance(colour):
        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        return (0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green())
                + 0.0722 * channel(colour.blue()))
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)
