"""Sample Control Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QFormLayout, QCheckBox, QComboBox)
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

        # Sample selection combo box
        sample_select_layout = QHBoxLayout()
        sample_select_layout.setContentsMargins(0, 0, 0, 0)
        sample_select_layout.setSpacing(6)
        sample_select_layout.addWidget(QLabel("Sample:"))
        self.sample_combo = QComboBox()
        # Mapping of displayed label -> internal sample key used in instrument definitions
        self.sample_map = {
            "None": None,
            "AL: acoustic phonon": "Al_rod_phonon",
            "Al: optic phonon": "Al_rod_phonon_optic",
            "AL: Bragg": "Al_bragg",
        }
        self.sample_combo.addItems(list(self.sample_map.keys()))
        sample_select_layout.addWidget(self.sample_combo)
        main_layout.addLayout(sample_select_layout)
        
        # Sample Orientation section (alignment offsets only)
        orientation_group = QGroupBox("Sample Alignment Offsets")
        orientation_layout = QGridLayout()
        orientation_layout.setSpacing(5)
        orientation_group.setLayout(orientation_layout)
        
        # Row 0: kappa (κ) and psi (ψ) - alignment offsets
        orientation_layout.addWidget(QLabel("κ:"), 0, 0)
        self.kappa_edit = QLineEdit()
        self.kappa_edit.setMaximumWidth(70)
        self.kappa_edit.setToolTip("Alignment offset for ω (omega)")
        orientation_layout.addWidget(self.kappa_edit, 0, 1)
        orientation_layout.addWidget(QLabel("°"), 0, 2)
        
        orientation_layout.addWidget(QLabel("ψ:"), 0, 3)
        self.psi_edit = QLineEdit()
        self.psi_edit.setMaximumWidth(70)
        self.psi_edit.setToolTip("Alignment offset for χ (chi)")
        orientation_layout.addWidget(self.psi_edit, 0, 4)
        orientation_layout.addWidget(QLabel("°"), 0, 5)
        
        # Info label
        orientation_info = QLabel("κ, ψ: alignment offsets")
        orientation_info.setStyleSheet("color: gray; font-size: 10px;")
        orientation_layout.addWidget(orientation_info, 1, 0, 1, 6)
        
        main_layout.addWidget(orientation_group)
        
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

    def get_selected_sample_key(self):
        """Return the internal sample key for the currently selected sample."""
        label = self.sample_combo.currentText()
        return self.sample_map.get(label, None)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
