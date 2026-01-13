"""Main Window for TAVI application with PySide6."""
import sys
import os
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QScrollArea
from PySide6.QtCore import Qt

from gui.docks.instrument_dock import InstrumentDock
from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock
from gui.docks.sample_dock import SampleDock
from gui.docks.scan_controls_dock import ScanControlsDock
from gui.docks.diagnostics_dock import DiagnosticsDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock
from gui.docks.slit_controls_dock import SlitControlsDock


class TAVIMainWindow(QMainWindow):
    """Main window for TAVI application with 3-panel layout."""
    
    def __init__(self, instrument_config=None):
        super().__init__()
        self.setWindowTitle("TAVI - Triple-Axis Virtual Instrument")
        self.setGeometry(100, 100, 1500, 900)
        self.instrument_config = instrument_config
        
        # Create dock widgets
        self.instrument_dock = InstrumentDock(self, instrument_config)
        self.slit_controls_dock = SlitControlsDock(self)
        self.reciprocal_space_dock = ReciprocalSpaceDock(self)
        self.sample_dock = SampleDock(self)
        self.scan_controls_dock = ScanControlsDock(self)
        self.diagnostics_dock = DiagnosticsDock(self)
        self.output_dock = OutputDock(self)
        self.data_control_dock = DataControlDock(self)
        
        # Initialize slit controls from config if available
        if instrument_config:
            slit_values = {
                'hbl_hgap': instrument_config.hbl_hgap,
                'hbl_vgap': instrument_config.hbl_vgap,
                'vbl_hgap': instrument_config.vbl_hgap,
                'pbl_hgap': instrument_config.pbl_hgap,
                'pbl_vgap': instrument_config.pbl_vgap,
                'pbl_hoffset': instrument_config.pbl_hoffset,
                'pbl_voffset': instrument_config.pbl_voffset,
                'dbl_hgap': instrument_config.dbl_hgap,
            }
            self.slit_controls_dock.set_slit_values(slit_values)
            
            slit_ranges = {
                'hbl_hgap_range': instrument_config.hbl_hgap_range,
                'hbl_vgap_range': instrument_config.hbl_vgap_range,
                'vbl_hgap_range': instrument_config.vbl_hgap_range,
                'pbl_hgap_range': instrument_config.pbl_hgap_range,
                'pbl_vgap_range': instrument_config.pbl_vgap_range,
                'dbl_hgap_range': instrument_config.dbl_hgap_range,
            }
            self.slit_controls_dock.set_slit_ranges(slit_ranges)
        
        # Create central widget with 3-panel layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main horizontal layout for 3 columns
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Create a horizontal splitter for the 3-panel layout
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel: Instrument configuration and Slit controls (with scroll)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        left_layout.addWidget(self.instrument_dock.widget())
        left_layout.addWidget(self.slit_controls_dock.widget())
        
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        splitter.addWidget(left_scroll)
        
        # Middle panel: Reciprocal space, Sample, Scan controls, Diagnostics (with scroll)
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(5)
        middle_layout.addWidget(self.reciprocal_space_dock.widget())
        middle_layout.addWidget(self.sample_dock.widget())
        middle_layout.addWidget(self.scan_controls_dock.widget())
        middle_layout.addWidget(self.diagnostics_dock.widget())
        middle_layout.addStretch()
        
        middle_scroll = QScrollArea()
        middle_scroll.setWidgetResizable(True)
        middle_scroll.setWidget(middle_widget)
        middle_scroll.setFrameShape(QScrollArea.NoFrame)
        splitter.addWidget(middle_scroll)
        
        # Right panel: Output and Data control
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        right_layout.addWidget(self.output_dock.widget())
        right_layout.addWidget(self.data_control_dock.widget())
        splitter.addWidget(right_widget)
        
        # Set initial splitter sizes (roughly equal thirds, with right panel larger for output)
        splitter.setSizes([420, 420, 660])


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
