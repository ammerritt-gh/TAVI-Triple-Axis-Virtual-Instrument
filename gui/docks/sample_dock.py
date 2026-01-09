"""Sample Control Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox)
from PySide6.QtCore import Qt


class SampleDock(QDockWidget):
    """Dock widget for sample configuration."""
    
    def __init__(self, parent=None):
        super().__init__("Sample Control", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Sample frame mode checkbox
        self.sample_frame_mode_check = QCheckBox("Sample frame mode")
        main_layout.addWidget(self.sample_frame_mode_check)
        
        # Lattice parameters section
        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout()
        lattice_layout.setSpacing(5)
        lattice_group.setLayout(lattice_layout)
        
        # Row 1: a, b, c
        lattice_layout.addWidget(QLabel("a:"), 0, 0)
        self.lattice_a_edit = QLineEdit()
        self.lattice_a_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_a_edit, 0, 1)
        
        lattice_layout.addWidget(QLabel("b:"), 0, 2)
        self.lattice_b_edit = QLineEdit()
        self.lattice_b_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_b_edit, 0, 3)
        
        lattice_layout.addWidget(QLabel("c:"), 0, 4)
        self.lattice_c_edit = QLineEdit()
        self.lattice_c_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_c_edit, 0, 5)
        
        lattice_layout.addWidget(QLabel("(Å)"), 0, 6)
        
        # Row 2: alpha, beta, gamma
        lattice_layout.addWidget(QLabel("α:"), 1, 0)
        self.lattice_alpha_edit = QLineEdit()
        self.lattice_alpha_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_alpha_edit, 1, 1)
        
        lattice_layout.addWidget(QLabel("β:"), 1, 2)
        self.lattice_beta_edit = QLineEdit()
        self.lattice_beta_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_beta_edit, 1, 3)
        
        lattice_layout.addWidget(QLabel("γ:"), 1, 4)
        self.lattice_gamma_edit = QLineEdit()
        self.lattice_gamma_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_gamma_edit, 1, 5)
        
        lattice_layout.addWidget(QLabel("(deg)"), 1, 6)
        
        main_layout.addWidget(lattice_group)
        
        # Sample configuration button
        self.config_sample_button = QPushButton("Sample Configuration")
        main_layout.addWidget(self.config_sample_button)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
