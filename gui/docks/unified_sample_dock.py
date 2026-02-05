"""Unified Sample Dock for TAVI application.

Combines sample parameters and lattice configuration into a single dockable panel.
"""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QComboBox, QFrame)
from PySide6.QtCore import Qt, Signal

from gui.docks.base_dock import BaseDockWidget


class UnifiedSampleDock(BaseDockWidget):
    """Unified dock widget for sample configuration."""
    
    # Signal to request opening the misalignment dock
    open_misalignment_dock_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__("Sample", parent, use_scroll_area=True)
        self.setObjectName("SampleDock")
        
        # Reference to misalignment dock (will be set by main window)
        self.misalignment_dock = None
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Sample Selection Section =====
        sample_select_group = QGroupBox("Sample Selection")
        sample_select_layout = QVBoxLayout()
        sample_select_layout.setSpacing(5)
        sample_select_group.setLayout(sample_select_layout)
        
        # Sample selection combo box
        sample_combo_layout = QHBoxLayout()
        sample_combo_layout.setContentsMargins(0, 0, 0, 0)
        sample_combo_layout.setSpacing(6)
        sample_combo_layout.addWidget(QLabel("Sample:"))
        self.sample_combo = QComboBox()
        self.sample_map = {
            "None": None,
            "AL: acoustic phonon": "Al_rod_phonon",
            "Al: optic phonon": "Al_rod_phonon_optic",
            "AL: Bragg": "Al_bragg",
        }
        self.sample_combo.addItems(list(self.sample_map.keys()))
        sample_combo_layout.addWidget(self.sample_combo)
        sample_select_layout.addLayout(sample_combo_layout)
        
        # Sample configuration button
        self.config_sample_button = QPushButton("Sample Configuration")
        sample_select_layout.addWidget(self.config_sample_button)
        
        main_layout.addWidget(sample_select_group)
        
        # ===== Lattice Parameters Section =====
        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout()
        lattice_layout.setSpacing(5)
        lattice_group.setLayout(lattice_layout)
        
        # Row 0: a, b, c
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
        
        # Row 1: alpha, beta, gamma
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
        
        # ===== Sample Alignment Offsets Section =====
        orientation_group = QGroupBox("Sample Alignment Offsets")
        orientation_layout = QGridLayout()
        orientation_layout.setSpacing(5)
        orientation_group.setLayout(orientation_layout)
        
        # Row 0: psi (ψ) - offset for omega, kappa (κ) - offset for chi
        orientation_layout.addWidget(QLabel("ψ:"), 0, 0)
        self.psi_edit = QLineEdit()
        self.psi_edit.setMaximumWidth(70)
        self.psi_edit.setToolTip("Alignment offset for ω (omega) - in-plane")
        orientation_layout.addWidget(self.psi_edit, 0, 1)
        orientation_layout.addWidget(QLabel("°"), 0, 2)
        
        orientation_layout.addWidget(QLabel("κ:"), 0, 3)
        self.kappa_edit = QLineEdit()
        self.kappa_edit.setMaximumWidth(70)
        self.kappa_edit.setToolTip("Alignment offset for χ (chi) - out-of-plane")
        orientation_layout.addWidget(self.kappa_edit, 0, 4)
        orientation_layout.addWidget(QLabel("°"), 0, 5)
        
        # Info label
        orientation_info = QLabel("ψ: offset for ω, κ: offset for χ")
        orientation_info.setStyleSheet("color: gray; font-size: 10px;")
        orientation_layout.addWidget(orientation_info, 1, 0, 1, 6)
        
        main_layout.addWidget(orientation_group)
        
        # ===== Separator =====
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)
        
        # ===== Misalignment Training Section =====
        misalignment_group = QGroupBox("Misalignment Training")
        misalignment_layout = QVBoxLayout()
        misalignment_layout.setSpacing(8)
        misalignment_group.setLayout(misalignment_layout)
        
        # Button to open misalignment dock
        self.open_misalignment_button = QPushButton("Open Misalignment Training...")
        self.open_misalignment_button.setMinimumHeight(30)
        misalignment_layout.addWidget(self.open_misalignment_button)
        
        # Status indicator
        self.misalignment_indicator_label = QLabel("⚪ No misalignment loaded")
        self.misalignment_indicator_label.setStyleSheet("color: gray; font-size: 11px;")
        self.misalignment_indicator_label.setAlignment(Qt.AlignCenter)
        misalignment_layout.addWidget(self.misalignment_indicator_label)
        
        main_layout.addWidget(misalignment_group)
        
        # Add stretch at the end
        main_layout.addStretch()
        
        # Connect internal signals
        self.open_misalignment_button.clicked.connect(self._on_open_misalignment_dock)
    
    def get_selected_sample_key(self):
        """Return the internal sample key for the currently selected sample."""
        label = self.sample_combo.currentText()
        return self.sample_map.get(label, None)
    
    def _on_open_misalignment_dock(self):
        """Handle button click to open misalignment dock."""
        self.open_misalignment_dock_requested.emit()
    
    def update_misalignment_indicator(self, has_misalignment: bool):
        """Update the indicator to show if misalignment is loaded.
        
        Args:
            has_misalignment: True if misalignment is loaded, False otherwise
        """
        if has_misalignment:
            self.misalignment_indicator_label.setText("🟢 Misalignment loaded")
            self.misalignment_indicator_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        else:
            self.misalignment_indicator_label.setText("⚪ No misalignment loaded")
            self.misalignment_indicator_label.setStyleSheet("color: gray; font-size: 11px;")
