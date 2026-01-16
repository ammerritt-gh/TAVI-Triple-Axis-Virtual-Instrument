"""Scattering Dock for TAVI application.

Contains absolute Q-space, relative HKL space, and energy transfer parameters.
"""
from PySide6.QtWidgets import (QLabel, QLineEdit, QGroupBox, QGridLayout, QComboBox)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


class UnifiedScatteringDock(BaseDockWidget):
    """Dock widget for scattering parameters (Q-space, HKL, energy transfer)."""
    
    def __init__(self, parent=None):
        super().__init__("Scattering", parent, use_scroll_area=True)
        self.setObjectName("ScatteringDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Absolute Q Space Section =====
        q_group = QGroupBox("Absolute Q Space (Å⁻¹)")
        q_layout = QGridLayout()
        q_layout.setSpacing(5)
        q_group.setLayout(q_layout)
        
        # qx
        q_layout.addWidget(QLabel("qx:"), 0, 0)
        self.qx_edit = QLineEdit()
        self.qx_edit.setMaximumWidth(80)
        q_layout.addWidget(self.qx_edit, 0, 1)
        q_layout.addWidget(QLabel("1/Å"), 0, 2)
        
        # qy
        q_layout.addWidget(QLabel("qy:"), 1, 0)
        self.qy_edit = QLineEdit()
        self.qy_edit.setMaximumWidth(80)
        q_layout.addWidget(self.qy_edit, 1, 1)
        q_layout.addWidget(QLabel("1/Å"), 1, 2)
        
        # qz
        q_layout.addWidget(QLabel("qz:"), 2, 0)
        self.qz_edit = QLineEdit()
        self.qz_edit.setMaximumWidth(80)
        q_layout.addWidget(self.qz_edit, 2, 1)
        q_layout.addWidget(QLabel("1/Å"), 2, 2)
        
        main_layout.addWidget(q_group)
        
        # ===== Relative HKL Space Section =====
        hkl_group = QGroupBox("Relative HKL Space (r.l.u.)")
        hkl_layout = QGridLayout()
        hkl_layout.setSpacing(5)
        hkl_group.setLayout(hkl_layout)
        
        # H
        hkl_layout.addWidget(QLabel("H:"), 0, 0)
        self.H_edit = QLineEdit()
        self.H_edit.setMaximumWidth(80)
        hkl_layout.addWidget(self.H_edit, 0, 1)
        
        # K
        hkl_layout.addWidget(QLabel("K:"), 1, 0)
        self.K_edit = QLineEdit()
        self.K_edit.setMaximumWidth(80)
        hkl_layout.addWidget(self.K_edit, 1, 1)
        
        # L
        hkl_layout.addWidget(QLabel("L:"), 2, 0)
        self.L_edit = QLineEdit()
        self.L_edit.setMaximumWidth(80)
        hkl_layout.addWidget(self.L_edit, 2, 1)
        
        main_layout.addWidget(hkl_group)
        
        # ===== Energy Transfer Section =====
        energy_group = QGroupBox("Energy Transfer")
        energy_layout = QGridLayout()
        energy_layout.setSpacing(5)
        energy_group.setLayout(energy_layout)
        
        energy_layout.addWidget(QLabel("ΔE:"), 0, 0)
        self.deltaE_edit = QLineEdit()
        self.deltaE_edit.setMaximumWidth(80)
        energy_layout.addWidget(self.deltaE_edit, 0, 1)
        energy_layout.addWidget(QLabel("meV"), 0, 2)
        
        main_layout.addWidget(energy_group)
        
        # ===== Ki/Kf Fixed Mode Section =====
        mode_group = QGroupBox("Fixed Mode")
        mode_layout = QGridLayout()
        mode_layout.setSpacing(5)
        mode_group.setLayout(mode_layout)
        
        # Ki or Kf fixed
        mode_layout.addWidget(QLabel("Ki/Kf fixed:"), 0, 0)
        self.K_fixed_combo = QComboBox()
        self.K_fixed_combo.addItems(["Ki Fixed", "Kf Fixed"])
        self.K_fixed_combo.setMaximumWidth(100)
        mode_layout.addWidget(self.K_fixed_combo, 0, 1)
        
        # Fixed E
        mode_layout.addWidget(QLabel("Fixed E:"), 1, 0)
        self.fixed_E_edit = QLineEdit()
        self.fixed_E_edit.setMaximumWidth(80)
        mode_layout.addWidget(self.fixed_E_edit, 1, 1)
        mode_layout.addWidget(QLabel("meV"), 1, 2)
        
        main_layout.addWidget(mode_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
