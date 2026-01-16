"""Data Control Dock for TAVI application."""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QWidget)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


class DataControlDock(BaseDockWidget):
    """Dock widget for data control (save/load)."""
    
    def __init__(self, parent=None):
        super().__init__("Data Control", parent, use_scroll_area=True)
        self.setObjectName("DataControlDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # Save folder section
        save_group = QGroupBox("Output Folder")
        save_layout = QVBoxLayout()
        save_group.setLayout(save_layout)
        
        # Target folder
        target_widget = QWidget()
        target_layout = QHBoxLayout()
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_widget.setLayout(target_layout)
        
        target_layout.addWidget(QLabel("Target output folder:"))
        self.save_browse_button = QPushButton("Browse")
        target_layout.addWidget(self.save_browse_button)
        
        save_layout.addWidget(target_widget)
        
        self.save_folder_edit = QLineEdit()
        save_layout.addWidget(self.save_folder_edit)
        
        # Actual folder
        save_layout.addWidget(QLabel("Actual output folder:"))
        self.actual_folder_label = QLabel("")
        self.actual_folder_label.setFrameStyle(QLabel.Panel | QLabel.Sunken)
        save_layout.addWidget(self.actual_folder_label)
        
        main_layout.addWidget(save_group)
        
        # Load folder section
        load_group = QGroupBox("Load Data")
        load_layout = QVBoxLayout()
        load_group.setLayout(load_layout)
        
        # Load folder
        load_widget = QWidget()
        load_widget_layout = QHBoxLayout()
        load_widget_layout.setContentsMargins(0, 0, 0, 0)
        load_widget.setLayout(load_widget_layout)
        
        load_widget_layout.addWidget(QLabel("Folder to load data:"))
        self.load_browse_button = QPushButton("Browse")
        load_widget_layout.addWidget(self.load_browse_button)
        self.load_data_button = QPushButton("Load")
        load_widget_layout.addWidget(self.load_data_button)
        
        load_layout.addWidget(load_widget)
        
        self.load_folder_edit = QLineEdit()
        load_layout.addWidget(self.load_folder_edit)
        
        main_layout.addWidget(load_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
