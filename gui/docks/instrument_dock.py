"""Instrument Configuration Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, 
                                QLabel, QLineEdit, QComboBox, QCheckBox, QGroupBox,
                                QFormLayout, QGridLayout)
from PySide6.QtCore import Qt


class InstrumentDock(QDockWidget):
    """Dock widget for instrument configuration."""
    
    def __init__(self, parent=None, instrument_config=None):
        super().__init__("Instrument Configuration", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.instrument_config = instrument_config
        
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
        # Populate from config if available
        if self.instrument_config:
            mono_crystals = self.instrument_config.get_monochromator_names()
            self.monocris_combo.addItems(mono_crystals)
        else:
            self.monocris_combo.addItems(["PG[002]", "PG[002] test"])
        crystals_layout.addRow("Monochromator crystal:", self.monocris_combo)
        
        self.anacris_combo = QComboBox()
        # Populate from config if available
        if self.instrument_config:
            ana_crystals = self.instrument_config.get_analyzer_names()
            self.anacris_combo.addItems(ana_crystals)
        else:
            self.anacris_combo.addItems(["PG[002]"])
        crystals_layout.addRow("Analyzer crystal:", self.anacris_combo)
        
        main_layout.addWidget(crystals_group)
        
        # Optics section
        optics_group = QGroupBox("Experimental Modules")
        optics_layout = QFormLayout()
        optics_group.setLayout(optics_layout)
        
        self.nmo_combo = QComboBox()
        # Populate from config if available
        if self.instrument_config:
            self.nmo_combo.addItems(self.instrument_config.nmo_options)
        else:
            self.nmo_combo.addItems(["None", "Vertical", "Horizontal", "Both"])
        optics_layout.addRow("NMO installed:", self.nmo_combo)
        
        # Show velocity selector option only if available in config
        self.v_selector_check = None
        if not self.instrument_config or self.instrument_config.v_selector_available:
            self.v_selector_check = QCheckBox("Enable velocity selector (Use in Ki fixed mode)")
            optics_layout.addRow(self.v_selector_check)
        
        main_layout.addWidget(optics_group)
        
        # Focusing section
        focusing_group = QGroupBox("Crystal Focusing Factors")
        focusing_layout = QGridLayout()
        focusing_layout.setSpacing(5)
        focusing_group.setLayout(focusing_layout)
        
        focusing_layout.addWidget(QLabel("rhm:"), 0, 0)
        self.rhmfac_edit = QLineEdit()
        self.rhmfac_edit.setMaximumWidth(60)
        focusing_layout.addWidget(self.rhmfac_edit, 0, 1)
        
        focusing_layout.addWidget(QLabel("rvm:"), 0, 2)
        self.rvmfac_edit = QLineEdit()
        self.rvmfac_edit.setMaximumWidth(60)
        focusing_layout.addWidget(self.rvmfac_edit, 0, 3)
        
        focusing_layout.addWidget(QLabel("rha:"), 1, 0)
        self.rhafac_edit = QLineEdit()
        self.rhafac_edit.setMaximumWidth(60)
        focusing_layout.addWidget(self.rhafac_edit, 1, 1)
        
        main_layout.addWidget(focusing_group)
        
        # Collimations section
        collimations_group = QGroupBox("Collimations")
        collimations_layout = QGridLayout()
        collimations_layout.setSpacing(5)
        collimations_group.setLayout(collimations_layout)
        
        # Alpha 1
        collimations_layout.addWidget(QLabel("α1 (src-mono):"), 0, 0)
        self.alpha_1_combo = QComboBox()
        # Populate from config if available
        if self.instrument_config:
            alpha_1_items = [str(x) for x in self.instrument_config.alpha_1_options]
            self.alpha_1_combo.addItems(alpha_1_items)
        else:
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
        
        # Store alpha_2 checkboxes dynamically
        self.alpha_2_checks = {}
        alpha_2_options = getattr(self.instrument_config, 'alpha_2_options', [30, 40, 60]) if self.instrument_config else [30, 40, 60]
        for option in alpha_2_options:
            checkbox = QCheckBox(f"{option}'")
            self.alpha_2_checks[option] = checkbox
            alpha_2_layout.addWidget(checkbox)
        
        # For backward compatibility, keep old attribute names if they exist
        if 30 in self.alpha_2_checks:
            self.alpha_2_30_check = self.alpha_2_checks[30]
        if 40 in self.alpha_2_checks:
            self.alpha_2_40_check = self.alpha_2_checks[40]
        if 60 in self.alpha_2_checks:
            self.alpha_2_60_check = self.alpha_2_checks[60]
        
        alpha_2_widget.setLayout(alpha_2_layout)
        collimations_layout.addWidget(alpha_2_widget, 1, 1, 1, 2)
        
        # Alpha 3
        collimations_layout.addWidget(QLabel("α3 (smp-ana):"), 2, 0)
        self.alpha_3_combo = QComboBox()
        # Populate from config if available
        if self.instrument_config:
            alpha_3_items = [str(x) for x in self.instrument_config.alpha_3_options]
            self.alpha_3_combo.addItems(alpha_3_items)
        else:
            self.alpha_3_combo.addItems(["0", "10", "20", "30", "45", "60"])
        self.alpha_3_combo.setMaximumWidth(80)
        collimations_layout.addWidget(self.alpha_3_combo, 2, 1)
        collimations_layout.addWidget(QLabel("'"), 2, 2)
        
        # Alpha 4
        collimations_layout.addWidget(QLabel("α4 (ana-det):"), 3, 0)
        self.alpha_4_combo = QComboBox()
        # Populate from config if available
        if self.instrument_config:
            alpha_4_items = [str(x) for x in self.instrument_config.alpha_4_options]
            self.alpha_4_combo.addItems(alpha_4_items)
        else:
            self.alpha_4_combo.addItems(["0", "10", "20", "30", "45", "60"])
        self.alpha_4_combo.setMaximumWidth(80)
        collimations_layout.addWidget(self.alpha_4_combo, 3, 1)
        collimations_layout.addWidget(QLabel("'"), 3, 2)
        
        main_layout.addWidget(collimations_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
