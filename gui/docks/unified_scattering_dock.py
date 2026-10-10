"""Scattering Dock for TAVI application.

The scattering point as Q (the neutron's view, left) and as HKL (the sample's
view, right), with the energy transfer below both; then the fixed Ki/Kf mode.
"""
from PySide6.QtWidgets import (QLabel, QLineEdit, QGroupBox, QGridLayout, QWidget)

from gui.docks.base_dock import BaseDockWidget, NoScrollComboBox, pack_grid


class UnifiedScatteringDock(BaseDockWidget):
    """Dock widget for scattering parameters (Q-space, HKL, energy transfer)."""

    def __init__(self, parent=None):
        super().__init__("Scattering", parent, use_scroll_area=True, blocks=True)
        self.setObjectName("ScatteringDock")


        # ===== The point: Q | HKL side by side, ΔE below =====
        # Two frames of one vector (Q = UB·HKL): the rows sit level but qx is
        # not H outside the standard setting, so each sub-column carries its
        # own header and labels, and nothing pairs a Q row with an HKL row.
        # Grid columns: 0-1 Q, 2 the gap (ΔE's unit sits in it), 3-4 HKL.
        point_group = QGroupBox("Q, HKL and ΔE")
        point_layout = QGridLayout()
        point_layout.setSpacing(5)
        point_group.setLayout(point_layout)

        point_layout.addWidget(QLabel("Q (Å⁻¹)"), 0, 0, 1, 2)
        point_layout.addWidget(QLabel("HKL (r.l.u.)"), 0, 3, 1, 2)
        self.qx_edit = QLineEdit()
        self.qy_edit = QLineEdit()
        self.qz_edit = QLineEdit()
        self.H_edit = QLineEdit()
        self.K_edit = QLineEdit()
        self.L_edit = QLineEdit()
        rows = ((("qx", self.qx_edit), ("H", self.H_edit)),
                (("qy", self.qy_edit), ("K", self.K_edit)),
                (("qz", self.qz_edit), ("L", self.L_edit)))
        for row, pair in enumerate(rows, start=1):
            for column, (name, edit) in zip((0, 3), pair):
                edit.setMaximumWidth(80)
                point_layout.addWidget(QLabel(f"{name}:"), row, column)
                point_layout.addWidget(edit, row, column + 1)

        point_layout.addWidget(QLabel("ΔE:"), 4, 0)
        self.deltaE_edit = QLineEdit()
        self.deltaE_edit.setMaximumWidth(80)
        point_layout.addWidget(self.deltaE_edit, 4, 1)
        point_layout.addWidget(QLabel("meV"), 4, 2)

        pack_grid(point_layout)
        point_layout.setColumnMinimumWidth(2, 16)  # the gap between the two frames
        self.add_block(point_group)

        # ===== Fixed Mode: Ki or Kf fixed, and its energy =====
        fixed_group = QGroupBox("Fixed Mode")
        fixed_layout = QGridLayout()
        fixed_layout.setSpacing(5)
        fixed_group.setLayout(fixed_layout)

        fixed_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.K_fixed_combo = NoScrollComboBox()
        self.K_fixed_combo.addItems(["Ki Fixed", "Kf Fixed"])
        self.K_fixed_combo.setMaximumWidth(100)
        fixed_layout.addWidget(self.K_fixed_combo, 0, 1)
        fixed_layout.addWidget(QLabel("Fixed E:"), 1, 0)
        self.fixed_E_edit = QLineEdit()
        self.fixed_E_edit.setMaximumWidth(80)
        fixed_layout.addWidget(self.fixed_E_edit, 1, 1)
        fixed_layout.addWidget(QLabel("meV"), 1, 2)

        pack_grid(fixed_layout)
        self.add_block(fixed_group)

        # Down the Q column, then the HKL column, then ΔE (so L -> ΔE), then the mode.
        chain = (self.qx_edit, self.qy_edit, self.qz_edit, self.H_edit, self.K_edit,
                 self.L_edit, self.deltaE_edit, self.K_fixed_combo, self.fixed_E_edit)
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
