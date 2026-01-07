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
        q_layout = QFormLayout()
        q_group.setLayout(q_layout)
        
        # qx
        qx_widget = QWidget()
        qx_layout = QHBoxLayout()
        qx_layout.setContentsMargins(0, 0, 0, 0)
        self.qx_edit = QLineEdit()
        qx_layout.addWidget(self.qx_edit)
        qx_layout.addWidget(QLabel("1/Å"))
        qx_widget.setLayout(qx_layout)
        q_layout.addRow("qx:", qx_widget)
        
        # qy
        qy_widget = QWidget()
        qy_layout = QHBoxLayout()
        qy_layout.setContentsMargins(0, 0, 0, 0)
        self.qy_edit = QLineEdit()
        qy_layout.addWidget(self.qy_edit)
        qy_layout.addWidget(QLabel("1/Å"))
        qy_widget.setLayout(qy_layout)
        q_layout.addRow("qy:", qy_widget)
        
        # qz
        qz_widget = QWidget()
        qz_layout = QHBoxLayout()
        qz_layout.setContentsMargins(0, 0, 0, 0)
        self.qz_edit = QLineEdit()
        qz_layout.addWidget(self.qz_edit)
        qz_layout.addWidget(QLabel("1/Å"))
        qz_widget.setLayout(qz_layout)
        q_layout.addRow("qz:", qz_widget)
        
        main_layout.addWidget(q_group)
        
        # Relative HKL space section
        hkl_group = QGroupBox("Relative HKL Space (r.l.u.)")
        hkl_layout = QFormLayout()
        hkl_group.setLayout(hkl_layout)
        
        # H
        self.H_edit = QLineEdit()
        hkl_layout.addRow("H:", self.H_edit)
        
        # K
        self.K_edit = QLineEdit()
        hkl_layout.addRow("K:", self.K_edit)
        
        # L
        self.L_edit = QLineEdit()
        hkl_layout.addRow("L:", self.L_edit)
        
        main_layout.addWidget(hkl_group)
        
        # Energy transfer section
        energy_group = QGroupBox("Energy Transfer")
        energy_layout = QFormLayout()
        energy_group.setLayout(energy_layout)
        
        deltaE_widget = QWidget()
        deltaE_layout = QHBoxLayout()
        deltaE_layout.setContentsMargins(0, 0, 0, 0)
        self.deltaE_edit = QLineEdit()
        deltaE_layout.addWidget(self.deltaE_edit)
        deltaE_layout.addWidget(QLabel("meV"))
        deltaE_widget.setLayout(deltaE_layout)
        energy_layout.addRow("ΔE:", deltaE_widget)
        
        main_layout.addWidget(energy_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
