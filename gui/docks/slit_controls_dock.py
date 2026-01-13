"""Slit Controls Dock for TAVI application."""
from PySide6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, 
                                QLabel, QGroupBox, QGridLayout, QDoubleSpinBox)
from PySide6.QtCore import Qt


class SlitControlsDock(QDockWidget):
    """Dock widget for slit size controls."""
    
    def __init__(self, parent=None):
        super().__init__("Slit Controls", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # Create main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)
        
        # H-Blende (Source collimation slit)
        hblende_group = QGroupBox("H-Blende (Source Collimation)")
        hblende_layout = QGridLayout()
        hblende_layout.setSpacing(5)
        hblende_group.setLayout(hblende_layout)
        
        hblende_layout.addWidget(QLabel("Horizontal gap (m):"), 0, 0)
        self.hbl_hgap_spin = QDoubleSpinBox()
        self.hbl_hgap_spin.setRange(0.01, 0.20)
        self.hbl_hgap_spin.setSingleStep(0.001)
        self.hbl_hgap_spin.setDecimals(4)
        self.hbl_hgap_spin.setValue(0.078)
        hblende_layout.addWidget(self.hbl_hgap_spin, 0, 1)
        
        hblende_layout.addWidget(QLabel("Vertical gap (m):"), 1, 0)
        self.hbl_vgap_spin = QDoubleSpinBox()
        self.hbl_vgap_spin.setRange(0.01, 0.30)
        self.hbl_vgap_spin.setSingleStep(0.001)
        self.hbl_vgap_spin.setDecimals(4)
        self.hbl_vgap_spin.setValue(0.150)
        hblende_layout.addWidget(self.hbl_vgap_spin, 1, 1)
        
        main_layout.addWidget(hblende_group)
        
        # V-Blende (Post-mono slit)
        vblende_group = QGroupBox("V-Blende (Post-Monochromator)")
        vblende_layout = QGridLayout()
        vblende_layout.setSpacing(5)
        vblende_group.setLayout(vblende_layout)
        
        vblende_layout.addWidget(QLabel("Horizontal gap (m):"), 0, 0)
        self.vbl_hgap_spin = QDoubleSpinBox()
        self.vbl_hgap_spin.setRange(0.01, 0.20)
        self.vbl_hgap_spin.setSingleStep(0.001)
        self.vbl_hgap_spin.setDecimals(4)
        self.vbl_hgap_spin.setValue(0.088)
        vblende_layout.addWidget(self.vbl_hgap_spin, 0, 1)
        
        main_layout.addWidget(vblende_group)
        
        # P-Blende (Pre-sample slit)
        pblende_group = QGroupBox("P-Blende (Pre-Sample)")
        pblende_layout = QGridLayout()
        pblende_layout.setSpacing(5)
        pblende_group.setLayout(pblende_layout)
        
        pblende_layout.addWidget(QLabel("Horizontal gap (m):"), 0, 0)
        self.pbl_hgap_spin = QDoubleSpinBox()
        self.pbl_hgap_spin.setRange(0.01, 0.20)
        self.pbl_hgap_spin.setSingleStep(0.001)
        self.pbl_hgap_spin.setDecimals(4)
        self.pbl_hgap_spin.setValue(0.100)
        pblende_layout.addWidget(self.pbl_hgap_spin, 0, 1)
        
        pblende_layout.addWidget(QLabel("Vertical gap (m):"), 1, 0)
        self.pbl_vgap_spin = QDoubleSpinBox()
        self.pbl_vgap_spin.setRange(0.01, 0.20)
        self.pbl_vgap_spin.setSingleStep(0.001)
        self.pbl_vgap_spin.setDecimals(4)
        self.pbl_vgap_spin.setValue(0.100)
        pblende_layout.addWidget(self.pbl_vgap_spin, 1, 1)
        
        pblende_layout.addWidget(QLabel("Horizontal offset (m):"), 2, 0)
        self.pbl_hoffset_spin = QDoubleSpinBox()
        self.pbl_hoffset_spin.setRange(-0.10, 0.10)
        self.pbl_hoffset_spin.setSingleStep(0.001)
        self.pbl_hoffset_spin.setDecimals(4)
        self.pbl_hoffset_spin.setValue(0.0)
        pblende_layout.addWidget(self.pbl_hoffset_spin, 2, 1)
        
        pblende_layout.addWidget(QLabel("Vertical offset (m):"), 3, 0)
        self.pbl_voffset_spin = QDoubleSpinBox()
        self.pbl_voffset_spin.setRange(-0.10, 0.10)
        self.pbl_voffset_spin.setSingleStep(0.001)
        self.pbl_voffset_spin.setDecimals(4)
        self.pbl_voffset_spin.setValue(0.0)
        pblende_layout.addWidget(self.pbl_voffset_spin, 3, 1)
        
        main_layout.addWidget(pblende_group)
        
        # D-Blende (Detector slit)
        dblende_group = QGroupBox("D-Blende (Detector)")
        dblende_layout = QGridLayout()
        dblende_layout.setSpacing(5)
        dblende_group.setLayout(dblende_layout)
        
        dblende_layout.addWidget(QLabel("Horizontal gap (m):"), 0, 0)
        self.dbl_hgap_spin = QDoubleSpinBox()
        self.dbl_hgap_spin.setRange(0.01, 0.10)
        self.dbl_hgap_spin.setSingleStep(0.001)
        self.dbl_hgap_spin.setDecimals(4)
        self.dbl_hgap_spin.setValue(0.050)
        dblende_layout.addWidget(self.dbl_hgap_spin, 0, 1)
        
        main_layout.addWidget(dblende_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
    
    def get_slit_values(self):
        """Get current slit values as a dictionary."""
        return {
            'hbl_hgap': self.hbl_hgap_spin.value(),
            'hbl_vgap': self.hbl_vgap_spin.value(),
            'vbl_hgap': self.vbl_hgap_spin.value(),
            'pbl_hgap': self.pbl_hgap_spin.value(),
            'pbl_vgap': self.pbl_vgap_spin.value(),
            'pbl_hoffset': self.pbl_hoffset_spin.value(),
            'pbl_voffset': self.pbl_voffset_spin.value(),
            'dbl_hgap': self.dbl_hgap_spin.value(),
        }
    
    def set_slit_values(self, values):
        """Set slit values from a dictionary."""
        if 'hbl_hgap' in values:
            self.hbl_hgap_spin.setValue(values['hbl_hgap'])
        if 'hbl_vgap' in values:
            self.hbl_vgap_spin.setValue(values['hbl_vgap'])
        if 'vbl_hgap' in values:
            self.vbl_hgap_spin.setValue(values['vbl_hgap'])
        if 'pbl_hgap' in values:
            self.pbl_hgap_spin.setValue(values['pbl_hgap'])
        if 'pbl_vgap' in values:
            self.pbl_vgap_spin.setValue(values['pbl_vgap'])
        if 'pbl_hoffset' in values:
            self.pbl_hoffset_spin.setValue(values['pbl_hoffset'])
        if 'pbl_voffset' in values:
            self.pbl_voffset_spin.setValue(values['pbl_voffset'])
        if 'dbl_hgap' in values:
            self.dbl_hgap_spin.setValue(values['dbl_hgap'])
    
    def set_slit_ranges(self, ranges):
        """Set slit value ranges from configuration."""
        if 'hbl_hgap_range' in ranges:
            r = ranges['hbl_hgap_range']
            self.hbl_hgap_spin.setRange(r[0], r[1])
        if 'hbl_vgap_range' in ranges:
            r = ranges['hbl_vgap_range']
            self.hbl_vgap_spin.setRange(r[0], r[1])
        if 'vbl_hgap_range' in ranges:
            r = ranges['vbl_hgap_range']
            self.vbl_hgap_spin.setRange(r[0], r[1])
        if 'pbl_hgap_range' in ranges:
            r = ranges['pbl_hgap_range']
            self.pbl_hgap_spin.setRange(r[0], r[1])
        if 'pbl_vgap_range' in ranges:
            r = ranges['pbl_vgap_range']
            self.pbl_vgap_spin.setRange(r[0], r[1])
        if 'dbl_hgap_range' in ranges:
            r = ranges['dbl_hgap_range']
            self.dbl_hgap_spin.setRange(r[0], r[1])
