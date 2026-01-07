"""Instrument Configuration Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, 
                                QLabel, QLineEdit, QComboBox, QCheckBox, QGroupBox,
                                QFormLayout, QGridLayout)
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
        angles_group.setLayout(angles_layout)
        
        # Mono 2theta
        angles_layout.addWidget(QLabel("Mono 2θ:"), 0, 0)
        self.mtt_edit = QLineEdit()
        angles_layout.addWidget(self.mtt_edit, 0, 1)
        
        # Sample 2theta
        angles_layout.addWidget(QLabel("Sample 2θ:"), 0, 2)
        self.stt_edit = QLineEdit()
        angles_layout.addWidget(self.stt_edit, 0, 3)
        
        # Sample Psi
        angles_layout.addWidget(QLabel("Sample Ψ:"), 0, 4)
        self.psi_edit = QLineEdit()
        angles_layout.addWidget(self.psi_edit, 0, 5)
        
        # Analyzer 2theta
        angles_layout.addWidget(QLabel("Ana 2θ:"), 0, 6)
        self.att_edit = QLineEdit()
        angles_layout.addWidget(self.att_edit, 0, 7)
        
        main_layout.addWidget(angles_group)
        
        # Energies section
        energies_group = QGroupBox("Energies and Wave Vectors")
        energies_layout = QGridLayout()
        energies_group.setLayout(energies_layout)
        
        # Ki
        energies_layout.addWidget(QLabel("Ki (1/Å):"), 0, 0)
        self.Ki_edit = QLineEdit()
        energies_layout.addWidget(self.Ki_edit, 0, 1)
        
        # Ei
        energies_layout.addWidget(QLabel("Ei (meV):"), 0, 2)
        self.Ei_edit = QLineEdit()
        energies_layout.addWidget(self.Ei_edit, 0, 3)
        
        # Kf
        energies_layout.addWidget(QLabel("Kf (1/Å):"), 0, 4)
        self.Kf_edit = QLineEdit()
        energies_layout.addWidget(self.Kf_edit, 0, 5)
        
        # Ef
        energies_layout.addWidget(QLabel("Ef (meV):"), 0, 6)
        self.Ef_edit = QLineEdit()
        energies_layout.addWidget(self.Ef_edit, 0, 7)
        
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
        focusing_group = QGroupBox("Crystal Focusing Factors")
        focusing_layout = QFormLayout()
        focusing_group.setLayout(focusing_layout)
        
        self.rhmfac_edit = QLineEdit()
        focusing_layout.addRow("rhm factor:", self.rhmfac_edit)
        
        self.rvmfac_edit = QLineEdit()
        focusing_layout.addRow("rvm factor:", self.rvmfac_edit)
        
        self.rhafac_edit = QLineEdit()
        focusing_layout.addRow("rha factor:", self.rhafac_edit)
        
        main_layout.addWidget(focusing_group)
        
        # Collimations section
        collimations_group = QGroupBox("Collimations")
        collimations_layout = QFormLayout()
        collimations_group.setLayout(collimations_layout)
        
        # Alpha 1
        self.alpha_1_combo = QComboBox()
        self.alpha_1_combo.addItems(["0", "20", "40", "60"])
        alpha_1_widget = QWidget()
        alpha_1_layout = QHBoxLayout()
        alpha_1_layout.setContentsMargins(0, 0, 0, 0)
        alpha_1_layout.addWidget(self.alpha_1_combo)
        alpha_1_layout.addWidget(QLabel("'"))
        alpha_1_widget.setLayout(alpha_1_layout)
        collimations_layout.addRow("Alpha 1 (source-mono):", alpha_1_widget)
        
        # Alpha 2
        alpha_2_widget = QWidget()
        alpha_2_layout = QHBoxLayout()
        alpha_2_layout.setContentsMargins(0, 0, 0, 0)
        self.alpha_2_30_check = QCheckBox("30'")
        self.alpha_2_40_check = QCheckBox("40'")
        self.alpha_2_60_check = QCheckBox("60'")
        alpha_2_layout.addWidget(self.alpha_2_30_check)
        alpha_2_layout.addWidget(self.alpha_2_40_check)
        alpha_2_layout.addWidget(self.alpha_2_60_check)
        alpha_2_widget.setLayout(alpha_2_layout)
        collimations_layout.addRow("Alpha 2 (mono-sample):", alpha_2_widget)
        
        # Alpha 3
        self.alpha_3_combo = QComboBox()
        self.alpha_3_combo.addItems(["0", "10", "20", "30", "45", "60"])
        alpha_3_widget = QWidget()
        alpha_3_layout = QHBoxLayout()
        alpha_3_layout.setContentsMargins(0, 0, 0, 0)
        alpha_3_layout.addWidget(self.alpha_3_combo)
        alpha_3_layout.addWidget(QLabel("'"))
        alpha_3_widget.setLayout(alpha_3_layout)
        collimations_layout.addRow("Alpha 3 (sample-analyzer):", alpha_3_widget)
        
        # Alpha 4
        self.alpha_4_combo = QComboBox()
        self.alpha_4_combo.addItems(["0", "10", "20", "30", "45", "60"])
        alpha_4_widget = QWidget()
        alpha_4_layout = QHBoxLayout()
        alpha_4_layout.setContentsMargins(0, 0, 0, 0)
        alpha_4_layout.addWidget(self.alpha_4_combo)
        alpha_4_layout.addWidget(QLabel("'"))
        alpha_4_widget.setLayout(alpha_4_layout)
        collimations_layout.addRow("Alpha 4 (analyzer-detector):", alpha_4_widget)
        
        main_layout.addWidget(collimations_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
