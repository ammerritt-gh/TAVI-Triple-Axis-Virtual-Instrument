"""Base Dock Widget with custom border painting for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                               QFrame, QComboBox, QLabel, QSizePolicy, QStyle)
from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QPainter, QPen, QColor

from gui import metrics


COLLIMATION_OPEN_TOOLTIP = "Open: no collimator installed, coarsest resolution."


def pack_grid(grid):
    """Pack a label/field QGridLayout to its content, so labels sit beside their values.

    Call after the grid is filled. A label directly left of a field is
    right-aligned against it, the metrics gap separates the columns, fields
    keep their own width at the left of their cell, and a trailing stretch
    column takes the spare width.
    """
    grid.setHorizontalSpacing(metrics.LABEL_FIELD_GAP)
    for index in range(grid.count()):
        item = grid.itemAt(index)
        widget = item.widget()
        if widget is None:
            continue
        row, column, _rows, columns = grid.getItemPosition(index)
        if isinstance(widget, QLabel):
            right = grid.itemAtPosition(row, column + columns)
            field = right.widget() if right is not None else None
            if columns == 1 and field is not None and not isinstance(field, QLabel):
                widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        else:
            item.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    grid.setColumnStretch(grid.columnCount(), 1)


NARROW, WIDE = "narrow", "wide"


class _BlockFlow(QWidget):
    """Scroll-area content of a form dock: its group boxes as fixed-width blocks.

    One block column in Narrow, or in Wide when the scroll area cannot hold
    two blocks; two in Wide when it can, filling the left column first and
    splitting where the taller column is shortest. The blocks move only on a
    scroll-area resize that changes the column count, or on a mode change,
    never when a block's own height changes. The width decision reserves the
    vertical scrollbar, so the scrollbar coming and going cannot flip it.
    """

    def __init__(self, scroll_area):
        super().__init__()
        self._scroll = scroll_area
        self._blocks = []
        self._mode = NARROW
        self._count = 1
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(metrics.BLOCK_GAP)
        self._columns = []
        for _ in range(2):
            column = QVBoxLayout()
            column.setSpacing(metrics.BLOCK_GAP)
            column.addStretch(1)
            row.addLayout(column)
            self._columns.append(column)
        row.addStretch(1)
        scroll_area.installEventFilter(self)

    def minimumSizeHint(self):
        # One block wide whatever the column count, so the scroll area always
        # sizes this to its viewport and the count follows the viewport.
        return QSize(metrics.BLOCK_WIDTH, super().minimumSizeHint().height())

    def add_block(self, block):
        block.setFixedWidth(metrics.BLOCK_WIDTH)
        self._blocks.append(block)
        self._place()

    def set_mode(self, mode):
        self._mode = mode
        self._count = self._wanted_count()
        self._place()

    def eventFilter(self, watched, event):
        if watched is self._scroll and event.type() == QEvent.Resize:
            count = self._wanted_count()
            if count != self._count:
                self._count = count
                self._place()
        return False

    def _wanted_count(self):
        if self._mode != WIDE:
            return 1
        scrollbar = self._scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        room = self._scroll.width() - 2 * self._scroll.frameWidth() - scrollbar
        two = 2 * metrics.BLOCK_WIDTH + metrics.BLOCK_GAP
        if self._count == 1:
            two += metrics.BLOCK_REFLOW_HYSTERESIS
        return 2 if room >= two else 1

    def _place(self):
        heights = [0 if b.isHidden() else b.sizeHint().height() for b in self._blocks]
        split = len(self._blocks)
        if self._count == 2 and len(self._blocks) > 1:
            # On a tie the left column takes more (counting down from the end).
            split = min(range(len(heights) - 1, 0, -1),
                        key=lambda k: max(sum(heights[:k]), sum(heights[k:])))
        for column in self._columns:
            for block in self._blocks:
                column.removeWidget(block)
        for index, block in enumerate(self._blocks):
            column = self._columns[0 if index < split else 1]
            column.insertWidget(column.count() - 1, block)  # above the stretch


def collimation_label(value):
    """Display text for a collimation value; never stored or read back.

    Zero (or the metadata's "open") reads Open, other numbers carry the
    arcminute mark, a list/tuple/set (stacked collimators) joins its non-zero
    entries with "+", and any other string (already marked) passes through.
    """
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [collimation_label(v) for v in value]
        parts = [p for p in parts if p != "Open"]
        return "+".join(parts) if parts else "Open"
    if isinstance(value, str) and value.strip().lower() == "open":
        return "Open"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)  # already marked, or unreadable (None): as before
    return "Open" if number == 0 else f"{number:g}'"


class NoScrollComboBox(QComboBox):
    """A QComboBox that ignores mouse-wheel events unless it has focus.

    Prevents accidental selection changes when a user scrolls a dock/scroll
    area with the cursor over a drop-down. Deliberate use still works: click
    to focus, then the wheel adjusts the selection as usual. The popup list is
    unaffected. Focus policy is StrongFocus (click/tab only) so hovering or
    scrolling never grabs focus the way the default WheelFocus would.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class BorderedFrame(QFrame):
    """A QFrame that draws a rounded border around its contents."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self._border_color = QColor("#555555")
        self._border_width = 1
        self._border_radius = 6
    
    def set_border_color(self, color):
        """Set the border color."""
        self._border_color = QColor(color)
        self.update()
    
    def set_border_width(self, width):
        """Set the border width."""
        self._border_width = width
        self.update()
    
    def paintEvent(self, event):
        """Paint the rounded border."""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen = QPen(self._border_color)
        pen.setWidth(self._border_width)
        painter.setPen(pen)
        
        # Draw rounded rectangle with some margin
        margin = self._border_width // 2 + 1
        painter.drawRoundedRect(
            margin, margin,
            self.width() - 2 * margin,
            self.height() - 2 * margin,
            self._border_radius, self._border_radius
        )


class BaseDockWidget(QDockWidget):
    """Base dock widget with bordered frame and scroll area support.
    
    Provides:
    - A bordered frame around the entire dock content
    - Optional scroll area for long content
    - Consistent styling across all docks
    - For the form docks (blocks=True), group boxes added with add_block()
      and laid out as one or two block columns (set_column_width()); never
      a horizontal scroll, and never narrower than one block
    """

    def __init__(self, title, parent=None, use_scroll_area=True, blocks=False):
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)

        # Create the bordered frame as the dock's widget
        self._bordered_frame = BorderedFrame()
        frame_layout = QVBoxLayout()
        frame_layout.setContentsMargins(8, 8, 8, 8)  # Margin inside the border
        self._bordered_frame.setLayout(frame_layout)

        if use_scroll_area:
            # Create scroll area inside the bordered frame
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QScrollArea.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._scroll_area = scroll_area

            if blocks:
                scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                # Not horizontally expanding: the dock area hands spare width
                # (a bigger window, a narrower column) to the expanding docks,
                # the Display column, instead of sharing it out pro rata. The
                # dock still resizes; its maximum comes from its content.
                self.setSizePolicy(QSizePolicy.Fixed, self.sizePolicy().verticalPolicy())
                scroll_area.setMinimumWidth(metrics.BLOCK_WIDTH + scroll_area.style()
                                            .pixelMetric(QStyle.PM_ScrollBarExtent))
                self._content_widget = _BlockFlow(scroll_area)
                self._content_layout = None  # add_block() places the groups
            else:
                # Content widget goes inside scroll area
                self._content_widget = QWidget()
                self._content_layout = QVBoxLayout()
                self._content_layout.setSpacing(8)
                self._content_layout.setContentsMargins(0, 0, 0, 0)
                self._content_widget.setLayout(self._content_layout)

            scroll_area.setWidget(self._content_widget)
            frame_layout.addWidget(scroll_area)
        else:
            # Content widget directly in bordered frame (for docks like output with built-in scrolling)
            self._content_widget = QWidget()
            self._content_layout = QVBoxLayout()
            self._content_layout.setSpacing(8)
            self._content_layout.setContentsMargins(0, 0, 0, 0)
            self._content_widget.setLayout(self._content_layout)
            frame_layout.addWidget(self._content_widget)
        
        self.setWidget(self._bordered_frame)
    
    @property
    def content_layout(self):
        """Get the layout to add widgets to."""
        return self._content_layout

    def add_block(self, block):
        """Add a group box as the next block, in usage order (blocks=True docks)."""
        self._content_widget.add_block(block)

    def set_column_width(self, mode):
        """NARROW: one block column. WIDE: two where the dock is wide enough."""
        self._content_widget.set_mode(mode)

    def width_for_blocks(self, count):
        """The dock width that holds ``count`` block columns beside a scrollbar.

        Two columns include the hysteresis margin, so a dock sized to it goes
        two-up from one. Measures the frame around the scroll area, so it
        needs a dock that has been laid out (shown).
        """
        inner = count * metrics.BLOCK_WIDTH + (count - 1) * (
            metrics.BLOCK_GAP + metrics.BLOCK_REFLOW_HYSTERESIS)
        scrollbar = self._scroll_area.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        chrome = self.width() - self._scroll_area.width()  # frame margins and border
        return inner + scrollbar + chrome

    def set_border_color(self, color):
        """Set the border color for this dock."""
        self._bordered_frame.set_border_color(color)
    
    def set_border_width(self, width):
        """Set the border width for this dock."""
        self._bordered_frame.set_border_width(width)
