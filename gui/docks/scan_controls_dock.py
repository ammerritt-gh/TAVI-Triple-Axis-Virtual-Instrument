"""Scan Controls Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout,
                                QLabel, QLineEdit, QComboBox, QGroupBox, QPushButton,
                                QFormLayout, QGridLayout, QCheckBox)
from PySide6.QtCore import Qt


class ScanControlsDock(QDockWidget):
    """Dock widget for scan controls."""
    
    def __init__(self, parent=None):
        super().__init__("Scan Controls", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Scan parameters section
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
        
        # Ki or Kf fixed
        params_layout.addWidget(QLabel("Ki/Kf fixed:"), 1, 0)
        self.K_fixed_combo = QComboBox()
        self.K_fixed_combo.addItems(["Ki Fixed", "Kf Fixed"])
        self.K_fixed_combo.setMaximumWidth(100)
        params_layout.addWidget(self.K_fixed_combo, 1, 1, 1, 2)
        
        # Fixed E
        params_layout.addWidget(QLabel("Fixed E:"), 2, 0)
        self.fixed_E_edit = QLineEdit()
        self.fixed_E_edit.setMaximumWidth(100)
        params_layout.addWidget(self.fixed_E_edit, 2, 1)
        params_layout.addWidget(QLabel("meV"), 2, 2)
        
        main_layout.addWidget(params_group)
        
        # Scan commands section
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
        
        # Control buttons section
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
        
        # Parameter buttons section
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
        
        # Display options section
        display_group = QGroupBox("Display Options")
        display_layout = QVBoxLayout()
        display_group.setLayout(display_layout)
        
        self.auto_display_check = QCheckBox("Auto-display plots after simulation")
        self.auto_display_check.setChecked(False)  # Default to off; can be enabled safely (threading handled by signal-based architecture)
        display_layout.addWidget(self.auto_display_check)
        
        main_layout.addWidget(display_group)
        
        # Counts display section
        counts_group = QGroupBox("Counts")
        counts_layout = QFormLayout()
        counts_group.setLayout(counts_layout)
        
        self.max_counts_label = QLabel("0")
        counts_layout.addRow("Max counts:", self.max_counts_label)
        
        self.total_counts_label = QLabel("0")
        counts_layout.addRow("Total counts:", self.total_counts_label)
        
        main_layout.addWidget(counts_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
