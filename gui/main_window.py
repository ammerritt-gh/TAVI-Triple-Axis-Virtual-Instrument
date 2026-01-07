"""Main Window for TAVI application with PySide6."""
import sys
import os
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import Qt

from gui.docks.instrument_dock import InstrumentDock
from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock
from gui.docks.sample_dock import SampleDock
from gui.docks.scan_controls_dock import ScanControlsDock
from gui.docks.diagnostics_dock import DiagnosticsDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock


class TAVIMainWindow(QMainWindow):
    """Main window for TAVI application."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TAVI - Triple-Axis Virtual Instrument")
        self.setGeometry(100, 100, 1600, 900)
        
        # Create dock widgets
        self.instrument_dock = InstrumentDock(self)
        self.reciprocal_space_dock = ReciprocalSpaceDock(self)
        self.sample_dock = SampleDock(self)
        self.scan_controls_dock = ScanControlsDock(self)
        self.diagnostics_dock = DiagnosticsDock(self)
        self.output_dock = OutputDock(self)
        self.data_control_dock = DataControlDock(self)
        
        # Add docks to main window
        # Left side: Instrument configuration
        self.addDockWidget(Qt.LeftDockWidgetArea, self.instrument_dock)
        
        # Right side top: Reciprocal space and Sample control
        self.addDockWidget(Qt.RightDockWidgetArea, self.reciprocal_space_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.sample_dock)
        
        # Right side middle: Scan controls
        self.addDockWidget(Qt.RightDockWidgetArea, self.scan_controls_dock)
        
        # Right side bottom: Diagnostics
        self.addDockWidget(Qt.RightDockWidgetArea, self.diagnostics_dock)
        
        # Bottom: Data control
        self.addDockWidget(Qt.BottomDockWidgetArea, self.data_control_dock)
        
        # Center: Output window
        self.addDockWidget(Qt.BottomDockWidgetArea, self.output_dock)
        
        # Tabify some docks for better space usage
        self.tabifyDockWidget(self.reciprocal_space_dock, self.sample_dock)
        
        # Set initial sizes (optional)
        self.resizeDocks(
            [self.instrument_dock, self.output_dock],
            [400, 300],
            Qt.Horizontal
        )


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
