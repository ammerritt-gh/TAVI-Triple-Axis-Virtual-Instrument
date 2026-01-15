"""Instrument Configuration Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, 
                                QLabel, QLineEdit, QComboBox, QCheckBox, QGroupBox,
                                QFormLayout, QGridLayout, QPushButton)
from PySide6.QtCore import Qt


class InstrumentDock(QDockWidget):
    """Dock widget for instrument configuration."""
    
    def __init__(self, parent=None):
        super().__init__("Instrument Configuration", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Angles section
        angles_group = QGroupBox("Instrument Angles")
        angles_layout = QGridLayout()
        angles_layout.setSpacing(5)
        angles_group.setLayout(angles_layout)
        
        # Mono 2theta
        angles_layout.addWidget(QLabel("Mono 2θ:"), 0, 0)
        self.mtt_edit = QLineEdit()
        self.mtt_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.mtt_edit, 0, 1)
        
        # Sample 2theta
        angles_layout.addWidget(QLabel("Sample 2θ:"), 0, 2)
        self.stt_edit = QLineEdit()
        self.stt_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.stt_edit, 0, 3)
        
        # Sample Psi
        angles_layout.addWidget(QLabel("Sample Ψ:"), 1, 0)
        self.psi_edit = QLineEdit()
        self.psi_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.psi_edit, 1, 1)
        
        # Analyzer 2theta
        angles_layout.addWidget(QLabel("Ana 2θ:"), 1, 2)
        self.att_edit = QLineEdit()
        self.att_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.att_edit, 1, 3)
        
        main_layout.addWidget(angles_group)
        
        # Energies section
        energies_group = QGroupBox("Energies and Wave Vectors")
        energies_layout = QGridLayout()
        energies_layout.setSpacing(5)
        energies_group.setLayout(energies_layout)
        
        # Ki
        energies_layout.addWidget(QLabel("Ki (1/Å):"), 0, 0)
        self.Ki_edit = QLineEdit()
        self.Ki_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ki_edit, 0, 1)
        
        # Ei
        energies_layout.addWidget(QLabel("Ei (meV):"), 0, 2)
        self.Ei_edit = QLineEdit()
        self.Ei_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ei_edit, 0, 3)
        
        # Kf
        energies_layout.addWidget(QLabel("Kf (1/Å):"), 1, 0)
        self.Kf_edit = QLineEdit()
        self.Kf_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Kf_edit, 1, 1)
        
        # Ef
        energies_layout.addWidget(QLabel("Ef (meV):"), 1, 2)
        self.Ef_edit = QLineEdit()
        self.Ef_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ef_edit, 1, 3)
        
        main_layout.addWidget(energies_group)
        
        # Crystals section
        crystals_group = QGroupBox("Monochromator and Analyzer Crystals")
        crystals_layout = QFormLayout()
        crystals_group.setLayout(crystals_layout)
        
        self.monocris_combo = QComboBox()
        self.monocris_combo.addItems(["PG[002]", "PG[002] test"])
        crystals_layout.addRow("Monochromator crystal:", self.monocris_combo)
        
        self.anacris_combo = QComboBox()
        self.anacris_combo.addItems(["PG[002]"])
        crystals_layout.addRow("Analyzer crystal:", self.anacris_combo)
        
        main_layout.addWidget(crystals_group)
        
        # Optics section
        optics_group = QGroupBox("Experimental Modules")
        optics_layout = QFormLayout()
        optics_group.setLayout(optics_layout)
        
        self.nmo_combo = QComboBox()
        self.nmo_combo.addItems(["None", "Vertical", "Horizontal", "Both"])
        optics_layout.addRow("NMO installed:", self.nmo_combo)
        
        self.v_selector_check = QCheckBox("Enable velocity selector (Use in Ki fixed mode)")
        optics_layout.addRow(self.v_selector_check)
        
        main_layout.addWidget(optics_group)
        
        # Focusing section
        focusing_group = QGroupBox("Crystal Focusing (Absolute Radii, m)")
        focusing_layout = QGridLayout()
        focusing_layout.setSpacing(5)
        focusing_group.setLayout(focusing_layout)
        
        focusing_layout.addWidget(QLabel("rhm:"), 0, 0)
        self.rhm_edit = QLineEdit()
        self.rhm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rhm_edit, 0, 1)
        self.rhm_ideal_button = QPushButton("Ideal: --")
        self.rhm_ideal_button.setCheckable(True)
        self.rhm_ideal_button.setMaximumWidth(140)
        self.rhm_ideal_button.setToolTip("Set rhm to the calculated ideal value")
        focusing_layout.addWidget(self.rhm_ideal_button, 0, 2)
        
        focusing_layout.addWidget(QLabel("rvm:"), 0, 3)
        self.rvm_edit = QLineEdit()
        self.rvm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rvm_edit, 0, 4)
        self.rvm_ideal_button = QPushButton("Ideal: --")
        self.rvm_ideal_button.setCheckable(True)
        self.rvm_ideal_button.setMaximumWidth(140)
        self.rvm_ideal_button.setToolTip("Set rvm to the calculated ideal value")
        focusing_layout.addWidget(self.rvm_ideal_button, 0, 5)
        
        focusing_layout.addWidget(QLabel("rha:"), 1, 0)
        self.rha_edit = QLineEdit()
        self.rha_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rha_edit, 1, 1)
        self.rha_ideal_button = QPushButton("Ideal: --")
        self.rha_ideal_button.setCheckable(True)
        self.rha_ideal_button.setMaximumWidth(140)
        self.rha_ideal_button.setToolTip("Set rha to the calculated ideal value")
        focusing_layout.addWidget(self.rha_ideal_button, 1, 2)
        
        main_layout.addWidget(focusing_group)
        
        # Collimations section
        collimations_group = QGroupBox("Collimations")
        collimations_layout = QGridLayout()
        collimations_layout.setSpacing(5)
        collimations_group.setLayout(collimations_layout)
        
        # Alpha 1
        collimations_layout.addWidget(QLabel("α1 (src-mono):"), 0, 0)
        self.alpha_1_combo = QComboBox()
        self.alpha_1_combo.addItems(["0", "20", "40", "60"])
        self.alpha_1_combo.setMaximumWidth(80)
        collimations_layout.addWidget(self.alpha_1_combo, 0, 1)
        collimations_layout.addWidget(QLabel("'"), 0, 2)
        
        # Alpha 2
        collimations_layout.addWidget(QLabel("α2 (mono-smp):"), 1, 0)
        alpha_2_widget = QWidget()
        alpha_2_layout = QHBoxLayout()
        alpha_2_layout.setContentsMargins(0, 0, 0, 0)
        alpha_2_layout.setSpacing(3)
        self.alpha_2_30_check = QCheckBox("30'")
        self.alpha_2_40_check = QCheckBox("40'")
        self.alpha_2_60_check = QCheckBox("60'")
        alpha_2_layout.addWidget(self.alpha_2_30_check)
        alpha_2_layout.addWidget(self.alpha_2_40_check)
        alpha_2_layout.addWidget(self.alpha_2_60_check)
        alpha_2_widget.setLayout(alpha_2_layout)
        collimations_layout.addWidget(alpha_2_widget, 1, 1, 1, 2)
        
        # Alpha 3
        collimations_layout.addWidget(QLabel("α3 (smp-ana):"), 2, 0)
        self.alpha_3_combo = QComboBox()
        self.alpha_3_combo.addItems(["0", "10", "20", "30", "45", "60"])
        self.alpha_3_combo.setMaximumWidth(80)
        collimations_layout.addWidget(self.alpha_3_combo, 2, 1)
        collimations_layout.addWidget(QLabel("'"), 2, 2)
        
        # Alpha 4
        collimations_layout.addWidget(QLabel("α4 (ana-det):"), 3, 0)
        self.alpha_4_combo = QComboBox()
        self.alpha_4_combo.addItems(["0", "10", "20", "30", "45", "60"])
        self.alpha_4_combo.setMaximumWidth(80)
        collimations_layout.addWidget(self.alpha_4_combo, 3, 1)
        collimations_layout.addWidget(QLabel("'"), 3, 2)
        
        main_layout.addWidget(collimations_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
