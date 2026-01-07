"""Diagnostics Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QCheckBox, QGroupBox, QPushButton)
from PySide6.QtCore import Qt


class DiagnosticsDock(QDockWidget):
    """Dock widget for diagnostics configuration."""
    
    def __init__(self, parent=None):
        super().__init__("Diagnostics", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Diagnostic mode section
        mode_group = QGroupBox("Diagnostic Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.diagnostic_mode_check = QCheckBox("Enable Diagnostic Mode")
        mode_layout.addWidget(self.diagnostic_mode_check)
        
        self.config_diagnostics_button = QPushButton("Configuration")
        mode_layout.addWidget(self.config_diagnostics_button)
        
        main_layout.addWidget(mode_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
