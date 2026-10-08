"""Scattering Dock for TAVI application.

Relative HKL, energy transfer and the fixed Ki/Kf mode, then absolute Q.
"""
from PySide6.QtWidgets import (QLabel, QLineEdit, QGroupBox, QGridLayout)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget, NoScrollComboBox, pack_grid


class UnifiedScatteringDock(BaseDockWidget):
    """Dock widget for scattering parameters (Q-space, HKL, energy transfer)."""
    
    def __init__(self, parent=None):
        super().__init__("Scattering", parent, use_scroll_area=True, blocks=True)
        self.setObjectName("ScatteringDock")
        
        
        # Workflow order: the point in relative HKL, its energy transfer and
        # the fixed Ki/Kf energy, then the same point as absolute Q.

        # ===== Relative HKL Space Section: H [ ] K [ ] L [ ] =====
        hkl_group = QGroupBox("Relative HKL Space (r.l.u.)")
        hkl_layout = QGridLayout()
        hkl_layout.setSpacing(5)
        hkl_group.setLayout(hkl_layout)

        self.H_edit = QLineEdit()
        self.K_edit = QLineEdit()
        self.L_edit = QLineEdit()
        for column, (name, edit) in enumerate(
                (("H", self.H_edit), ("K", self.K_edit), ("L", self.L_edit))):
            edit.setMaximumWidth(60)
            hkl_layout.addWidget(QLabel(f"{name}:"), 0, 2 * column)
            hkl_layout.addWidget(edit, 0, 2 * column + 1)

        pack_grid(hkl_layout)
        self.add_block(hkl_group)

        # ===== Energy Section: ΔE, then the fixed mode and its energy =====
        energy_group = QGroupBox("Energy Transfer and Fixed Mode")
        energy_layout = QGridLayout()
        energy_layout.setSpacing(5)
        energy_group.setLayout(energy_layout)

        energy_layout.addWidget(QLabel("ΔE:"), 0, 0)
        self.deltaE_edit = QLineEdit()
        self.deltaE_edit.setMaximumWidth(60)
        energy_layout.addWidget(self.deltaE_edit, 0, 1)
        energy_layout.addWidget(QLabel("meV"), 0, 2)

        energy_layout.addWidget(QLabel("Mode:"), 1, 0)
        self.K_fixed_combo = NoScrollComboBox()
        self.K_fixed_combo.addItems(["Ki Fixed", "Kf Fixed"])
        self.K_fixed_combo.setMaximumWidth(100)
        energy_layout.addWidget(self.K_fixed_combo, 1, 1)
        energy_layout.addWidget(QLabel("Fixed E:"), 1, 2)
        self.fixed_E_edit = QLineEdit()
        self.fixed_E_edit.setMaximumWidth(60)
        energy_layout.addWidget(self.fixed_E_edit, 1, 3)
        energy_layout.addWidget(QLabel("meV"), 1, 4)

        pack_grid(energy_layout)
        self.add_block(energy_group)

        # ===== Absolute Q Space Section: qx [ ] qy [ ] qz [ ] =====
        q_group = QGroupBox("Absolute Q Space (Å⁻¹)")
        q_layout = QGridLayout()
        q_layout.setSpacing(5)
        q_group.setLayout(q_layout)

        self.qx_edit = QLineEdit()
        self.qy_edit = QLineEdit()
        self.qz_edit = QLineEdit()
        for column, (name, edit) in enumerate(
                (("qx", self.qx_edit), ("qy", self.qy_edit), ("qz", self.qz_edit))):
            edit.setMaximumWidth(60)
            q_layout.addWidget(QLabel(f"{name}:"), 0, 2 * column)
            q_layout.addWidget(edit, 0, 2 * column + 1)

        pack_grid(q_layout)
        self.add_block(q_group)
        
