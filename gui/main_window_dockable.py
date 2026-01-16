"""Main Window for TAVI application with PySide6 and dockable panels."""
import sys
import os
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                QScrollArea, QMenuBar, QMenu, QMessageBox)
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QAction

from gui.docks.instrument_dock import InstrumentDock
from gui.docks.unified_scattering_dock import UnifiedScatteringDock
from gui.docks.unified_sample_dock import UnifiedSampleDock
from gui.docks.unified_simulation_dock import UnifiedSimulationDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock


class TAVIMainWindow(QMainWindow):
    """Main window for TAVI application with dockable panels."""
    
    # Layout config file path
    LAYOUT_CONFIG_FILE = "view_layout.json"
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TAVI - Triple-Axis Virtual Instrument")
        self.setGeometry(100, 100, 1600, 900)
        
        # Enable dock nesting for more flexible layouts
        self.setDockNestingEnabled(True)
        
        # Store default state for reset functionality
        self._default_state = None
        self._default_geometry = None
        
        # Create dock widgets with unique object names for state persistence
        self._create_docks()
        
        # Set up the central widget (minimal, as most content is in docks)
        self._setup_central_widget()
        
        # Add docks to the main window
        self._setup_dock_layout()
        
        # Create menu bar with View menu
        self._create_menus()
        
        # Store default layout state after initial setup
        self._store_default_state()
        
        # Try to restore saved layout
        self._restore_layout_from_file()
    
    def _create_docks(self):
        """Create all dock widgets."""
        # Instrument Panel (left)
        self.instrument_dock = InstrumentDock(self)
        self.instrument_dock.setObjectName("InstrumentDock")
        
        # Scattering Panel (middle) - Q-space, HKL, deltaE, Ki/Kf mode
        self.scattering_dock = UnifiedScatteringDock(self)
        
        # Sample Panel (middle) - lattice params, sample selection, misalignment
        self.sample_dock = UnifiedSampleDock(self)
        
        # Simulation Panel (right) - neutrons, scan commands, controls, diagnostics, progress
        self.simulation_dock = UnifiedSimulationDock(self)
        
        # Message Panel (right/bottom) - log output
        self.output_dock = OutputDock(self)
        self.output_dock.setObjectName("OutputDock")
        
        # Data Control Panel (right/bottom) - folders, load data
        self.data_control_dock = DataControlDock(self)
        self.data_control_dock.setObjectName("DataControlDock")
        
        # Store all docks in a list for easy iteration
        self._all_docks = [
            self.instrument_dock,
            self.scattering_dock,
            self.sample_dock,
            self.simulation_dock,
            self.output_dock,
            self.data_control_dock,
        ]
    
    def _setup_central_widget(self):
        """Set up a minimal central widget."""
        # Create a minimal central widget - most content is in docks
        central_widget = QWidget()
        central_widget.setMaximumWidth(0)  # Hide central widget
        central_widget.setMaximumHeight(0)
        self.setCentralWidget(central_widget)
    
    def _setup_dock_layout(self):
        """Set up the default dock layout (3-column arrangement)."""
        # Left column: Instrument
        self.addDockWidget(Qt.LeftDockWidgetArea, self.instrument_dock)
        
        # Middle column: Scattering, Sample (stacked/tabbed)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scattering_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.sample_dock)
        
        # Right column: Simulation, Output, Data Control
        self.addDockWidget(Qt.RightDockWidgetArea, self.simulation_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.output_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.data_control_dock)
        
        # Split left area to show Instrument on far left
        self.splitDockWidget(self.instrument_dock, self.scattering_dock, Qt.Horizontal)
        
        # Stack Sample below Scattering in the middle column
        self.splitDockWidget(self.scattering_dock, self.sample_dock, Qt.Vertical)
        
        # Stack Output below Simulation, then Data Control below Output
        self.splitDockWidget(self.simulation_dock, self.output_dock, Qt.Vertical)
        self.splitDockWidget(self.output_dock, self.data_control_dock, Qt.Vertical)
    
    def _create_menus(self):
        """Create the menu bar with View menu for dock management."""
        menubar = self.menuBar()
        
        # ===== File Menu =====
        file_menu = menubar.addMenu("&File")
        
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # ===== View Menu =====
        view_menu = menubar.addMenu("&View")
        
        # Add toggle actions for each dock (using built-in toggleViewAction)
        view_menu.addSection("Panels")
        for dock in self._all_docks:
            view_menu.addAction(dock.toggleViewAction())
        
        view_menu.addSeparator()
        
        # Restore All Docks action
        restore_all_action = QAction("&Restore All Panels", self)
        restore_all_action.setShortcut("Ctrl+Shift+R")
        restore_all_action.triggered.connect(self.restore_all_docks)
        view_menu.addAction(restore_all_action)
        
        # Reset to Default Layout action
        reset_layout_action = QAction("Reset to &Default Layout", self)
        reset_layout_action.triggered.connect(self.reset_to_default_layout)
        view_menu.addAction(reset_layout_action)
        
        view_menu.addSeparator()
        
        # Save Current Layout action
        save_layout_action = QAction("&Save Current Layout", self)
        save_layout_action.triggered.connect(self.save_layout_to_file)
        view_menu.addAction(save_layout_action)
        
        # ===== Help Menu =====
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About TAVI", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _store_default_state(self):
        """Store the default window state for reset functionality."""
        self._default_state = self.saveState()
        self._default_geometry = self.saveGeometry()
    
    def restore_all_docks(self):
        """Restore all docks to visible and docked state."""
        for dock in self._all_docks:
            dock.setVisible(True)
            dock.setFloating(False)
        self.statusBar().showMessage("All panels restored", 3000)
    
    def reset_to_default_layout(self):
        """Reset the dock layout to the default arrangement."""
        if self._default_state is not None:
            self.restoreState(self._default_state)
        if self._default_geometry is not None:
            self.restoreGeometry(self._default_geometry)
        
        # Ensure all docks are visible
        for dock in self._all_docks:
            dock.setVisible(True)
        
        self.statusBar().showMessage("Layout reset to default", 3000)
    
    def save_layout_to_file(self):
        """Save the current layout to a JSON config file."""
        config_path = self._get_layout_config_path()
        
        try:
            layout_data = {
                "window_geometry": self.saveGeometry().toBase64().data().decode('ascii'),
                "window_state": self.saveState().toBase64().data().decode('ascii'),
                "dock_visibility": {
                    dock.objectName(): dock.isVisible() for dock in self._all_docks
                },
                "dock_floating": {
                    dock.objectName(): dock.isFloating() for dock in self._all_docks
                }
            }
            
            with open(config_path, 'w') as f:
                json.dump(layout_data, f, indent=2)
            
            self.statusBar().showMessage(f"Layout saved to {config_path}", 3000)
            return True
        except Exception as e:
            QMessageBox.warning(self, "Save Layout Error", 
                              f"Failed to save layout: {e}")
            return False
    
    def _restore_layout_from_file(self):
        """Restore layout from the JSON config file if it exists."""
        config_path = self._get_layout_config_path()
        
        if not os.path.exists(config_path):
            return False
        
        try:
            with open(config_path, 'r') as f:
                layout_data = json.load(f)
            
            # Restore window geometry
            if "window_geometry" in layout_data:
                geometry_bytes = QByteArray.fromBase64(
                    layout_data["window_geometry"].encode('ascii')
                )
                self.restoreGeometry(geometry_bytes)
            
            # Restore window state (dock positions)
            if "window_state" in layout_data:
                state_bytes = QByteArray.fromBase64(
                    layout_data["window_state"].encode('ascii')
                )
                self.restoreState(state_bytes)
            
            # Restore dock visibility
            if "dock_visibility" in layout_data:
                for dock in self._all_docks:
                    name = dock.objectName()
                    if name in layout_data["dock_visibility"]:
                        dock.setVisible(layout_data["dock_visibility"][name])
            
            return True
        except Exception as e:
            print(f"Warning: Failed to restore layout: {e}")
            return False
    
    def _get_layout_config_path(self):
        """Get the path to the layout config file."""
        # Store in the same directory as the application
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                          self.LAYOUT_CONFIG_FILE)
    
    def _show_about(self):
        """Show the About dialog."""
        QMessageBox.about(self, "About TAVI",
                         "TAVI - Triple-Axis Virtual Instrument\n\n"
                         "A virtual instrument simulator for triple-axis neutron "
                         "spectrometry experiments.\n\n"
                         "Panels can be undocked, moved, and rearranged.\n"
                         "Use View menu to manage panel visibility.")
    
    def closeEvent(self, event):
        """Handle window close event - save layout automatically."""
        self.save_layout_to_file()
        event.accept()
    
    # ===== Compatibility Properties =====
    # These provide backward compatibility with the existing controller code
    # by mapping old dock names to the new unified docks
    
    @property
    def reciprocal_space_dock(self):
        """Backward compatibility: map to scattering_dock."""
        return self.scattering_dock
    
    @property
    def scan_controls_dock(self):
        """Backward compatibility: map to simulation_dock for scan params."""
        return self.simulation_dock
    
    @property
    def simulation_control_dock(self):
        """Backward compatibility: map to simulation_dock for control buttons."""
        return self.simulation_dock
    
    @property
    def diagnostics_dock(self):
        """Backward compatibility: map to simulation_dock for diagnostics."""
        return self.simulation_dock
    
    @property
    def misalignment_dock(self):
        """Backward compatibility: map to sample_dock for misalignment features."""
        return self.sample_dock


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
