"""Scan-field marks: the outline and badge that say how a scan treats a field.

Drawing only. The plan decides which mark a field gets; this module draws it.
The outline is an overlay beside the field, never a stylesheet change, so the
controller's edit and error highlighting still show, and no layout moves.
"""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGroupBox, QLabel, QWidget

from gui import theme

# Outline sits this far outside the field, in px; 1 keeps rows 3 px apart visibly separate.
_OUTLINE_GAP = 1
# Badge takes the window colour so it reads as a legend set in the outline's gap.
_BADGE_STYLE = "font-size: 9px; padding: 1px 2px; background: palette(window);"
_FIELD_EVENTS = (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide)
_NOTE_MARGIN = 8
_STYLES = (None, "scanned", "set")


class _Follow(QObject):
    """Calls ``update`` when ``watched`` gets one of ``events``; lives as long as ``watched``."""

    def __init__(self, watched, update, events):
        super().__init__(watched)
        self._update = update
        self._events = events
        watched.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in self._events:
            self._update()
        return False


class _Outline(QWidget):
    """The outline overlay: no input, painted from its mark's state."""

    def __init__(self, mark, parent):
        super().__init__(parent)
        self._mark = mark
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, event):
        style, _badge, command, _tooltip = self._mark.state()
        rect = QRectF(self.rect())
        with QPainter(self) as painter:
            if style == "scanned":
                # The dash is centred on the field's edge: 1 px outside, 1 px over its border.
                pen = QPen(QColor(theme.COMMAND_COLORS[command]), theme.SCANNED_PEN_WIDTH,
                           Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect.adjusted(_OUTLINE_GAP, _OUTLINE_GAP,
                                               -_OUTLINE_GAP, -_OUTLINE_GAP))
            else:
                half = theme.SET_PEN_WIDTH / 2
                painter.setPen(QPen(QColor(theme.DERIVED_OUTLINE), theme.SET_PEN_WIDTH))
                painter.drawRect(rect.adjusted(half, half, -half, -half))
                edge = theme.SET_BOTTOM_EDGE_WIDTH
                painter.fillRect(QRectF(0, self.height() - edge, self.width(), edge),
                                 QColor(theme.DERIVED_OUTLINE))


class FieldMark:
    """The one mark of a field: an outline overlay and a badge straddling its top-right corner."""

    def __init__(self, field):
        self._field = field
        self._state = (None, "", None, "")
        host = _overlay_host(field)
        self._outline = _Outline(self, host)
        self._badge = QLabel(host)
        for widget in _path(field, host):
            _Follow(widget, self._place, _FIELD_EVENTS)
        self._place()

    def set_mark(self, style, badge="", command=None, tooltip=""):
        """Draw ``style`` ("scanned", "set" or None for no mark); repeating the same arguments does nothing."""
        if style not in _STYLES:
            raise ValueError(f"unknown field mark style {style!r}")
        state = (style, badge, command, tooltip)
        if state == self._state:
            return
        self._state = state
        if style == "scanned":
            colour, weight = theme.COMMAND_COLORS[command], "bold"
        else:
            colour, weight = theme.BADGE_TEXT, "normal"
        self._badge.setText(badge)
        self._badge.setStyleSheet(f"color: {colour}; font-weight: {weight}; {_BADGE_STYLE}")
        self._badge.setToolTip(tooltip)
        self._badge.ensurePolished()  # the 9 px stylesheet font must apply before the size is taken
        self._badge.adjustSize()
        self._place()

    def state(self):
        """(style, badge, command, tooltip) as last set."""
        return self._state

    def _place(self):
        style, badge, _command, _tooltip = self._state
        field = self._field
        host = _overlay_host(field)
        shown = style is not None and field.isVisibleTo(host)
        self._outline.setVisible(shown)
        self._badge.setVisible(shown and bool(badge))
        if not shown:
            return
        frame = QRect(field.mapTo(host, QPoint(0, 0)), field.size())
        self._outline.setGeometry(frame.adjusted(-_OUTLINE_GAP, -_OUTLINE_GAP,
                                                 _OUTLINE_GAP, _OUTLINE_GAP))
        self._outline.raise_()
        width, height = self._badge.width(), self._badge.height()
        x = min(max(0, frame.right() + _OUTLINE_GAP - width), host.width() - width)
        y = min(max(0, frame.top() - height // 2), host.height() - height)
        self._badge.move(x, y)
        self._badge.raise_()


def _overlay_host(field):
    """The nearest group box, else the top-level window: a tight parent would clip the outset."""
    host = field.parentWidget()
    while not isinstance(host, QGroupBox) and host.parentWidget() is not None:
        host = host.parentWidget()
    return host


def _path(field, host):
    """Widgets from ``field`` up to ``host``, both included."""
    widget = field
    yield widget
    while widget is not host:
        widget = widget.parentWidget()
        yield widget


def mark_for(field):
    """The field's one mark, created on first use. The field must already be laid out (have a parent)."""
    mark = getattr(field, "_field_mark", None)
    if mark is None:
        if field.parentWidget() is None:
            raise ValueError("a field mark needs its field in a layout first")
        mark = field._field_mark = FieldMark(field)
    return mark


def set_group_note(group_box, text=None):
    """A quiet italic note in the group box's title row, right-aligned; None hides it."""
    note = getattr(group_box, "_group_note", None)
    if note is None:
        if text is None:
            return
        note = group_box._group_note = QLabel(group_box)
        note.setAttribute(Qt.WA_TransparentForMouseEvents)
        note.setStyleSheet(f"color: {theme.NOTE_TEXT}; font-style: italic;")
        _Follow(group_box, lambda: _place_note(note), (QEvent.Resize,))
    note.setVisible(text is not None)
    if text is not None:
        note.setText(text)
        note.adjustSize()
        _place_note(note)


def _place_note(note):
    group = note.parentWidget()
    title_bottom = group.contentsRect().top()
    note.move(group.width() - note.width() - _NOTE_MARGIN,
              max(0, (title_bottom - note.height()) // 2))
