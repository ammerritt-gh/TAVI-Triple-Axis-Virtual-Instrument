"""Base Dock Widget with custom border painting for TAVI application."""
from PySide6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QScrollArea, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor


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
    """
    
    def __init__(self, title, parent=None, use_scroll_area=True):
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
    
    def set_border_color(self, color):
        """Set the border color for this dock."""
        self._bordered_frame.set_border_color(color)
    
    def set_border_width(self, width):
        """Set the border width for this dock."""
        self._bordered_frame.set_border_width(width)
