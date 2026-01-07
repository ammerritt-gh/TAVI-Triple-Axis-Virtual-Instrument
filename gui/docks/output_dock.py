"""Output Window Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QTextEdit,
                                QGroupBox, QLabel, QProgressBar, QHBoxLayout)
from PySide6.QtCore import Qt


class OutputDock(QDockWidget):
    """Dock widget for output messages and progress."""
    
    def __init__(self, parent=None):
        super().__init__("Output", parent)
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Message center section
        message_group = QGroupBox("Message Center")
        message_layout = QVBoxLayout()
        message_group.setLayout(message_layout)
        
        self.message_text = QTextEdit()
        self.message_text.setReadOnly(True)
        message_layout.addWidget(self.message_text)
        
        main_layout.addWidget(message_group)
        
        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_group.setLayout(progress_layout)
        
        # Progress bar and label
        progress_widget = QWidget()
        progress_widget_layout = QHBoxLayout()
        progress_widget_layout.setContentsMargins(0, 0, 0, 0)
        progress_widget.setLayout(progress_widget_layout)
        
        self.progress_bar = QProgressBar()
        progress_widget_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("0% (0/0)")
        progress_widget_layout.addWidget(self.progress_label)
        
        progress_layout.addWidget(progress_widget)
        
        # Remaining time label
        self.remaining_time_label = QLabel("Remaining Time: ")
        progress_layout.addWidget(self.remaining_time_label)
        
        main_layout.addWidget(progress_group)
