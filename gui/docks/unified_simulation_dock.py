"""Unified Simulation Dock for TAVI application.

Combines scan parameters, control buttons, diagnostic mode, counts display,
and progress tracking into a single dockable panel.
"""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QComboBox, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QFormLayout, QProgressBar,
                                QWidget)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


class UnifiedSimulationDock(BaseDockWidget):
    """Unified dock widget for simulation control and parameters."""
    
    def __init__(self, parent=None):
        super().__init__("Simulation", parent, use_scroll_area=True)
        self.setObjectName("SimulationDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Scan Parameters Section =====
        params_group = QGroupBox("Scan Parameters")
        params_layout = QGridLayout()
        params_layout.setSpacing(5)
        params_group.setLayout(params_layout)
        
        # Number of neutrons
        params_layout.addWidget(QLabel("# neutrons:"), 0, 0)
        self.number_neutrons_edit = QLineEdit()
        self.number_neutrons_edit.setMaximumWidth(100)
        params_layout.addWidget(self.number_neutrons_edit, 0, 1)
        params_layout.addWidget(QLabel("n"), 0, 2)
        
        main_layout.addWidget(params_group)
        
        # ===== Scan Commands Section =====
        scan_group = QGroupBox("Scan Commands")
        scan_layout = QVBoxLayout()
        scan_group.setLayout(scan_layout)
        
        scan_layout.addWidget(QLabel("Scan Command 1:"))
        self.scan_command_1_edit = QLineEdit()
        scan_layout.addWidget(self.scan_command_1_edit)
        
        scan_layout.addWidget(QLabel("Scan Command 2:"))
        self.scan_command_2_edit = QLineEdit()
        scan_layout.addWidget(self.scan_command_2_edit)
        
        main_layout.addWidget(scan_group)
        
        # ===== Control Buttons Section =====
        buttons_group = QGroupBox("Control Buttons")
        buttons_layout = QGridLayout()
        buttons_group.setLayout(buttons_layout)
        
        self.run_button = QPushButton("Run Simulation")
        buttons_layout.addWidget(self.run_button, 0, 0)
        
        self.stop_button = QPushButton("Stop Simulation")
        buttons_layout.addWidget(self.stop_button, 0, 1)
        
        self.quit_button = QPushButton("Quit")
        buttons_layout.addWidget(self.quit_button, 1, 0)
        
        self.validation_button = QPushButton("Open Validation GUI")
        buttons_layout.addWidget(self.validation_button, 1, 1)
        
        main_layout.addWidget(buttons_group)
        
        # ===== Parameter Management Section =====
        param_buttons_group = QGroupBox("Parameter Management")
        param_buttons_layout = QGridLayout()
        param_buttons_group.setLayout(param_buttons_layout)
        
        self.save_button = QPushButton("Save Parameters")
        param_buttons_layout.addWidget(self.save_button, 0, 0)
        
        self.load_button = QPushButton("Load Parameters")
        param_buttons_layout.addWidget(self.load_button, 0, 1)
        
        self.defaults_button = QPushButton("Load Defaults")
        param_buttons_layout.addWidget(self.defaults_button, 0, 2)
        
        main_layout.addWidget(param_buttons_group)
        
        # ===== Counts Display Section =====
        counts_group = QGroupBox("Counts")
        counts_layout = QFormLayout()
        counts_group.setLayout(counts_layout)
        
        self.max_counts_label = QLabel("0")
        counts_layout.addRow("Max counts:", self.max_counts_label)
        
        self.total_counts_label = QLabel("0")
        counts_layout.addRow("Total counts:", self.total_counts_label)
        
        main_layout.addWidget(counts_group)
        
        # ===== Diagnostic Mode Section =====
        mode_group = QGroupBox("Diagnostic Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.diagnostic_mode_check = QCheckBox("Enable Diagnostic Mode")
        mode_layout.addWidget(self.diagnostic_mode_check)
        
        self.config_diagnostics_button = QPushButton("Configuration")
        mode_layout.addWidget(self.config_diagnostics_button)
        
        main_layout.addWidget(mode_group)
        
        # ===== Progress Section =====
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
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
