"""Reciprocal Lattice Space Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QFormLayout)
from PySide6.QtCore import Qt


class ReciprocalSpaceDock(QDockWidget):
    """Dock widget for reciprocal lattice space configuration."""
    
    def __init__(self, parent=None):
        super().__init__("Reciprocal Lattice Space", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # Absolute Q space section
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
        
        # Relative HKL space section
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
        
        # Energy transfer section
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
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
