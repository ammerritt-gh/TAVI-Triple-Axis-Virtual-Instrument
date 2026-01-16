"""Main Window for TAVI application with PySide6 and dockable panels."""
import sys
import os
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                QScrollArea, QMenuBar, QMenu, QMessageBox)
from PySide6.QtCore import Qt, QByteArray, QTimer
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
        
        # Set geometry after a small delay to avoid Qt geometry warnings
        QTimer.singleShot(0, lambda: self.setGeometry(100, 100, 1600, 900))
    
    def _create_docks(self):
        """Create all dock widgets."""
        # Instrument Panel (column 1, top)
        self.instrument_dock = InstrumentDock(self)
        
        # Scattering Panel (column 1, bottom)
        self.scattering_dock = UnifiedScatteringDock(self)
        
        # Sample Panel (column 2, top)
        self.sample_dock = UnifiedSampleDock(self)
        
        # Simulation Panel (column 2, bottom)
        self.simulation_dock = UnifiedSimulationDock(self)
        
        # Message Panel (column 3, top)
        self.output_dock = OutputDock(self)
        
        # Data Control Panel (column 3, bottom)
        self.data_control_dock = DataControlDock(self)
        
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
        # Create a small central widget - needed for proper dock behavior
        # A completely hidden central widget can cause docking issues
        central_widget = QWidget()
        central_widget.setMinimumSize(1, 1)
        central_widget.setMaximumSize(1, 1)
        self.setCentralWidget(central_widget)
    
    def _setup_dock_layout(self):
        """Set up the default dock layout (3-column arrangement).
        
        Layout:
        ┌─────────────┬─────────────┬─────────────┐
        │ Instrument  │   Sample    │   Output    │
        │             │             │  (Message)  │
        ├─────────────┼─────────────┤             │
        │ Scattering  │ Simulation  │             │
        │             │             ├─────────────┤
        │             │             │    Data     │
        │             │             │   Control   │
        └─────────────┴─────────────┴─────────────┘
        """
        # Step 1: Add all docks to the left area first
        self.addDockWidget(Qt.LeftDockWidgetArea, self.instrument_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.sample_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.output_dock)
        
        # Step 2: Create 3 columns by splitting horizontally
        # Split instrument from sample (instrument stays left, sample goes right)
        self.splitDockWidget(self.instrument_dock, self.sample_dock, Qt.Horizontal)
        # Split sample from output (sample stays left, output goes right)
        self.splitDockWidget(self.sample_dock, self.output_dock, Qt.Horizontal)
        
        # Step 3: Add bottom docks to each column
        # Scattering below Instrument (column 1)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scattering_dock)
        self.splitDockWidget(self.instrument_dock, self.scattering_dock, Qt.Vertical)
        
        # Simulation below Sample (column 2)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.simulation_dock)
        self.splitDockWidget(self.sample_dock, self.simulation_dock, Qt.Vertical)
        
        # Data Control below Output (column 3)
        self.addDockWidget(Qt.RightDockWidgetArea, self.data_control_dock)
        self.splitDockWidget(self.output_dock, self.data_control_dock, Qt.Vertical)
        
        # Step 4: Set column widths
        self.resizeDocks(
            [self.instrument_dock, self.sample_dock, self.output_dock],
            [400, 500, 450],
            Qt.Horizontal
        )
        
        # Step 5: Set row heights within each column
        self.resizeDocks(
            [self.instrument_dock, self.scattering_dock],
            [400, 400],
            Qt.Vertical
        )
        
        self.resizeDocks(
            [self.sample_dock, self.simulation_dock],
            [400, 400],
            Qt.Vertical
        )
        
        self.resizeDocks(
            [self.output_dock, self.data_control_dock],
            [600, 200],
            Qt.Vertical
        )
    
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


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
