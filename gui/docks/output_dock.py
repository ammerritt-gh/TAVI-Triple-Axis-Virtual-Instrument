"""Output Window Dock for TAVI application."""
from PySide6.QtWidgets import (QVBoxLayout, QTextEdit, QGroupBox)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


class OutputDock(BaseDockWidget):
    """Dock widget for output messages (log)."""
    
    def __init__(self, parent=None):
        # Use use_scroll_area=False since QTextEdit has built-in scrolling
        super().__init__("Message Log", parent, use_scroll_area=False)
        self.setObjectName("OutputDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # Message center section - expands to fill the dock
        message_group = QGroupBox("Message Center")
        message_layout = QVBoxLayout()
        message_group.setLayout(message_layout)
        
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)
        # Let the dock system manage sizing
        message_layout.addWidget(self.message_text)
        
        main_layout.addWidget(message_group)
