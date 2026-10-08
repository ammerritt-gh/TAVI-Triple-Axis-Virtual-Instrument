"""Main Window for TAVI application with PySide6 and dockable panels."""
import sys
import os
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                QScrollArea, QMenuBar, QMenu, QMessageBox,
                                QInputDialog)
from PySide6.QtCore import Qt, QByteArray, QTimer
from PySide6.QtGui import QAction, QActionGroup

import tavi
from tavi.local_state import config_path as local_config_path
from tavi.settings import MPI_COUNT_MAX
from gui import metrics
from gui.docks.base_dock import NARROW, WIDE
from gui.docks.instrument_dock import InstrumentDock
from gui.docks.unified_scattering_dock import UnifiedScatteringDock
from gui.docks.unified_sample_dock import UnifiedSampleDock
from gui.docks.unified_simulation_dock import UnifiedSimulationDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock
from gui.docks.display_dock import DisplayDock
from gui.docks.fitting_dock import FittingDock
from gui.docks.misalignment_dock import MisalignmentDock
from gui.docks.ub_matrix_dock import UBMatrixDock
from gui.docks.api_dock import ApiDock
from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock


class TAVIMainWindow(QMainWindow):
    """Main window for TAVI application with dockable panels."""
    
    LAYOUT_VERSION = 2
    
    def __init__(self, descriptor=None, instrument_infos=None,
                 current_instrument_id=None, save_selection=None):
        super().__init__()
        if descriptor is None:
            raise ValueError("TAVIMainWindow requires the active InstrumentDescriptor")
        self.descriptor = descriptor
        self.setWindowTitle(
            f"TAVI - Triple-Axis Virtual Instrument - {descriptor.display_name}"
        )

        # Instrument-switcher wiring (populated by main(); gui/ stays free of any
        # registry import). ``instrument_infos`` are lightweight (id, display_name)
        # entries, ``save_selection`` is a callable(id) that persists the choice.
        self._instrument_infos = list(instrument_infos or [])
        self._current_instrument_id = current_instrument_id
        self._save_selection = save_selection
        self._instrument_actions = {}
        # Set to the chosen id when the user confirms an instrument switch; main()
        # reads this after app.exec() returns to relaunch with the new instrument.
        self._restart_instrument_id = None

        # Enable dock nesting for more flexible layouts
        self.setDockNestingEnabled(True)
        
        # Store default state for reset functionality
        self._default_state = None
        self._default_geometry = None
        
        # Create dock widgets with unique object names for state persistence
        self._create_docks()
        
        # Connect signals between docks
        self._connect_dock_signals()
        
        # Set up the central widget (minimal, as most content is in docks)
        self._setup_central_widget()
        
        # Add docks to the main window
        self._setup_dock_layout()
        
        # Create menu bar with View menu
        self._create_menus()
        
        # Store default layout state after initial setup
        self._store_default_state()

        # Restore a saved layout when present. The default layout keeps the
        # reciprocal-space panel closed until the user opens it from View.
        self._column_width = NARROW
        self._restore_layout_from_file()
        self.set_column_width(self._column_width, fit=False)

        # Set geometry after a small delay to avoid Qt geometry warnings, then
        # fit the form panels to their column width so the plot gets the rest.
        QTimer.singleShot(0, self._apply_startup_geometry)

    def _apply_startup_geometry(self):
        self.setGeometry(100, 100, 1600, 900)
        self._fit_form_docks()
    
    def _create_docks(self):
        """Create all dock widgets."""
        # Instrument Panel (column 1, top)
        self.instrument_dock = InstrumentDock(self, descriptor=self.descriptor)

        # Scattering Panel (column 1, bottom)
        self.scattering_dock = UnifiedScatteringDock(self)

        # Sample Panel (column 2, top)
        self.sample_dock = UnifiedSampleDock(self, descriptor=self.descriptor)
        
        # Misalignment Training Panel (initially hidden, opened from Sample panel)
        self.misalignment_dock = MisalignmentDock(self)
        # Prefer it to open as a floating panel and start hidden
        try:
            self.misalignment_dock.setFloating(True)
            self.misalignment_dock.setVisible(False)
        except Exception:
            pass
        
        # UB Matrix Panel (initially hidden, opened from Sample panel)
        self.ub_matrix_dock = UBMatrixDock(self, descriptor=self.descriptor)
        try:
            self.ub_matrix_dock.setFloating(True)
            self.ub_matrix_dock.setVisible(False)
        except Exception:
            pass
        
        # Simulation Panel (column 2, bottom)
        self.simulation_dock = UnifiedSimulationDock(self)
        
        # Display Panel (column 3, top) - Real-time plot display
        self.display_dock = DisplayDock(self)

        # Fitting Panel (column 3, bottom) - quick peak fit of the displayed
        # 1D scan plus the scan-derived goto buttons. It reads the scan through
        # display_dock.scan_snapshot() and draws its overlay on that dock's
        # axes, so it must be created after the display dock.
        self.fitting_dock = FittingDock(self, display_dock=self.display_dock)

        # Interactive reciprocal-space canvas.  It is a normal dock so users
        # can tab, float, maximise, and persist it with the existing layout.
        self.reciprocal_space_dock = ReciprocalSpaceDock(self)
        
        # Message Panel (column 3, middle)
        self.output_dock = OutputDock(self)
        
        # Data Control Panel (column 3, bottom)
        self.data_control_dock = DataControlDock(self)

        # Remote API Panel (column 3, near output/data)
        self.api_dock = ApiDock(self)

        # Store all docks in a list for easy iteration
        self._all_docks = [
            self.instrument_dock,
            self.scattering_dock,
            self.sample_dock,
            self.misalignment_dock,
            self.ub_matrix_dock,
            self.simulation_dock,
            self.display_dock,
            self.fitting_dock,
            self.reciprocal_space_dock,
            self.output_dock,
            self.data_control_dock,
            self.api_dock,
        ]
    
    def _connect_dock_signals(self):
        """Connect signals between docks."""
        # Connect sample dock button to open misalignment dock
        self.sample_dock.open_misalignment_dock_requested.connect(
            self._on_open_misalignment_dock
        )
        
        # Connect misalignment dock signal to update sample dock indicator
        self.misalignment_dock.misalignment_changed.connect(
            self.sample_dock.update_misalignment_indicator
        )
        
        # Connect sample dock button to open UB matrix dock
        self.sample_dock.open_ub_matrix_dock_requested.connect(
            self._on_open_ub_matrix_dock
        )
        
        # Connect UB matrix dock signal to update sample dock indicator
        self.ub_matrix_dock.ub_matrix_changed.connect(
            self.sample_dock.update_ub_indicator
        )

        # Fitting dock follows the displayed dataset: a reset drops its overlay
        # and cached fit (the display dock has already cleared the axes), a
        # finish refreshes the COM/MAX readouts. The fit itself is never
        # re-run automatically.
        self.display_dock.scan_data_reset.connect(
            self.fitting_dock.on_scan_reset
        )
        self.display_dock.scan_data_finished.connect(
            self.fitting_dock.on_scan_finished
        )

    def _on_open_misalignment_dock(self):
        """Handle request to open the misalignment dock."""
        # Show and raise the misalignment dock
        self.misalignment_dock.setVisible(True)
        self.misalignment_dock.raise_()
        self.misalignment_dock.activateWindow()
    
    def _on_open_ub_matrix_dock(self):
        """Handle request to open the UB matrix dock."""
        self.ub_matrix_dock.setVisible(True)
        self.ub_matrix_dock.raise_()
        self.ub_matrix_dock.activateWindow()
    
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
        │ Instrument  │   Sample    │  Display    │
        │             │             │  (Plot)     │
        ├─────────────┼─────────────┼─────────────┤
        │ Scattering  │ Simulation  │   Output    │
        │             │             │  (Message)  │
        │             │             ├─────────────┤
        │             │             │    Data     │
        │             │             │   Control   │
        └─────────────┴─────────────┴─────────────┘
        """
        # Step 1: Add all docks to the left area first
        self.addDockWidget(Qt.LeftDockWidgetArea, self.instrument_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.sample_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.display_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.reciprocal_space_dock)
        self.tabifyDockWidget(self.display_dock, self.reciprocal_space_dock)
        self.display_dock.raise_()
        self.reciprocal_space_dock.setVisible(False)
        
        # Step 2: Create 3 columns by splitting horizontally
        # Split instrument from sample (instrument stays left, sample goes right)
        self.splitDockWidget(self.instrument_dock, self.sample_dock, Qt.Horizontal)
        # Split sample from display (sample stays left, display goes right)
        self.splitDockWidget(self.sample_dock, self.display_dock, Qt.Horizontal)
        
        # Step 3: Add bottom docks to each column
        # Scattering below Instrument (column 1)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scattering_dock)
        self.splitDockWidget(self.instrument_dock, self.scattering_dock, Qt.Vertical)
        
        # Simulation below Sample (column 2)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.simulation_dock)
        self.splitDockWidget(self.sample_dock, self.simulation_dock, Qt.Vertical)
        
        # Output below Display (column 3)
        self.addDockWidget(Qt.RightDockWidgetArea, self.output_dock)
        self.splitDockWidget(self.display_dock, self.output_dock, Qt.Vertical)
        
        # Data Control below Output (column 3)
        self.addDockWidget(Qt.RightDockWidgetArea, self.data_control_dock)
        self.splitDockWidget(self.output_dock, self.data_control_dock, Qt.Vertical)

        # Remote API tabbed with Data Control (column 3, bottom)
        self.addDockWidget(Qt.RightDockWidgetArea, self.api_dock)
        self.tabifyDockWidget(self.data_control_dock, self.api_dock)

        # Fitting tabbed alongside them, deliberately NOT with the Display
        # dock: its overlay is drawn on the Display plot, so both have to be
        # visible at once.
        self.addDockWidget(Qt.RightDockWidgetArea, self.fitting_dock)
        self.tabifyDockWidget(self.api_dock, self.fitting_dock)
        self.data_control_dock.raise_()

        # Misalignment dock is added and configured elsewhere to avoid duplicate layout entries.
        
        # Step 4: Set column widths
        self.resizeDocks(
            [self.instrument_dock, self.sample_dock, self.display_dock],
            [400, 500, 450],
            Qt.Horizontal
        )
        
        # Step 5: Set row heights within each column
        self.resizeDocks(
            [self.instrument_dock, self.scattering_dock],
            [400, 400],
            Qt.Vertical
        )
        
        # Make Sample shorter and Simulation taller to better use vertical space
        self.resizeDocks(
            [self.sample_dock, self.simulation_dock],
            [300, 500],
            Qt.Vertical
        )
        
        self.resizeDocks(
            [self.display_dock, self.output_dock, self.data_control_dock],
            [350, 350, 150],
            Qt.Vertical
        )

    
    def _create_menus(self):
        """Create the menu bar with View menu for dock management."""
        menubar = self.menuBar()
        
        # ===== File Menu =====
        file_menu = menubar.addMenu("&File")

        # The controller connects these three to its handlers. No ellipsis on
        # Save/Load: they write and read the fixed file with no chooser.
        self.save_parameters_action = QAction("&Save Parameters", self)
        self.save_parameters_action.setStatusTip(
            "Overwrite config/parameters.json with the current fields")
        file_menu.addAction(self.save_parameters_action)

        self.load_parameters_action = QAction("&Load Parameters", self)
        self.load_parameters_action.setStatusTip(
            "Read every instrument, sample and scan field from config/parameters.json")
        file_menu.addAction(self.load_parameters_action)

        self.load_defaults_action = QAction("Load &Defaults", self)
        self.load_defaults_action.setStatusTip(
            "Set every field back to the instrument defaults")
        file_menu.addAction(self.load_defaults_action)

        file_menu.addSeparator()

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

        # Column Width: a setting (it stays checked), not an arrangement.
        width_menu = view_menu.addMenu("Column &Width")
        width_group = QActionGroup(self)
        width_group.setExclusive(True)
        self.column_width_actions = {}
        for mode, text, tip in (
                (NARROW, "&Narrow", "Form panels one block wide; the plot gets the rest"),
                (WIDE, "&Wide", "Form panels two blocks wide where there is room")):
            action = QAction(text, self, checkable=True)
            action.setStatusTip(tip)
            action.triggered.connect(lambda _checked=False, m=mode: self.set_column_width(m))
            width_group.addAction(action)
            width_menu.addAction(action)
            self.column_width_actions[mode] = action

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
        
        # ===== Instrument Menu =====
        # Only shown when the launcher supplied the registered-instrument list.
        if self._instrument_infos:
            instrument_menu = menubar.addMenu("&Instrument")
            group = QActionGroup(self)
            group.setExclusive(True)
            for info in self._instrument_infos:
                action = QAction(info.display_name, self, checkable=True)
                action.setData(info.id)
                if info.id == self._current_instrument_id:
                    # The active instrument reads as the current choice and does
                    # nothing when clicked (disabled but still visibly checked).
                    action.setChecked(True)
                    action.setEnabled(False)
                action.triggered.connect(
                    lambda _checked=False, iid=info.id: self._on_instrument_selected(iid)
                )
                group.addAction(action)
                instrument_menu.addAction(action)
                self._instrument_actions[info.id] = action

        # ===== Utilities Menu =====
        utilities_menu = menubar.addMenu("&Utilities")

        resolution_action = QAction("&Resolution calculator…", self)
        resolution_action.triggered.connect(self._open_resolution_dialog)
        utilities_menu.addAction(resolution_action)

        benchmark_action = QAction("&Scan-time benchmark…", self)
        benchmark_action.triggered.connect(self._open_benchmark_dialog)
        utilities_menu.addAction(benchmark_action)

        # ===== Config Menu =====
        # Machine-level preferences, stored in config/settings.json.
        config_menu = menubar.addMenu("&Config")

        mpi_action = QAction("&MPI processes…", self)
        mpi_action.triggered.connect(self._open_mpi_dialog)
        config_menu.addAction(mpi_action)

        config_menu.addSeparator()

        # Connected by the controller; it confirms first and names the instrument.
        self.clear_runtimes_action = QAction("&Clear Runtime Data…", self)
        self.clear_runtimes_action.setStatusTip(
            "Delete the scan-time estimate history for the current instrument (asks first)")
        config_menu.addAction(self.clear_runtimes_action)

        # ===== Help Menu =====
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About TAVI", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _on_instrument_selected(self, instrument_id):
        """Handle an Instrument-menu selection: confirm and restart, or revert."""
        if instrument_id == self._current_instrument_id:
            return

        info = next(
            (i for i in self._instrument_infos if i.id == instrument_id), None
        )
        name = info.display_name if info is not None else instrument_id

        reply = QMessageBox.question(
            self,
            "Switch Instrument",
            f"Switching to {name} requires restarting TAVI.\n\n"
            f"TAVI will close and reopen with {name}. Any running or queued "
            f"scans will be stopped and unsaved changes to the current session "
            f"will be lost.\n\n"
            f"Restart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            # Declined: put the check back on the current instrument, quietly.
            current_action = self._instrument_actions.get(self._current_instrument_id)
            if current_action is not None:
                current_action.blockSignals(True)
                current_action.setChecked(True)
                current_action.blockSignals(False)
            return

        # Confirmed: persist the new choice FIRST, then trigger the restart via
        # the normal close path (closeEvent -> controller.shutdown() + layout save).
        # A locked plane does not survive a switch: the controller releases it
        # and drops it from this instrument's saved block (nothing else saved).
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.release_lock_for_switch()
        if self._save_selection is not None:
            self._save_selection(instrument_id)
        self._restart_instrument_id = instrument_id
        self.close()
    
    def _open_resolution_dialog(self):
        """Open (or re-raise) the non-modal Resolution calculator utility.

        Created lazily and kept as a single instance; each open prefills the
        inputs from current GUI state and recomputes. Requires the controller,
        which main() attaches after construction.
        """
        controller = getattr(self, "controller", None)
        if controller is None:
            QMessageBox.warning(self, "Resolution calculator",
                                "Controller not ready yet.")
            return
        if getattr(self, "_resolution_dialog", None) is None:
            from gui.dialogs.resolution_dialog import ResolutionDialog
            self._resolution_dialog = ResolutionDialog(controller, parent=self)
        dialog = self._resolution_dialog
        dialog.refresh_from_state()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_benchmark_dialog(self):
        """Open (or re-raise) the non-modal Scan-time benchmark utility.

        Created lazily and kept as a single instance; each open refreshes the
        machine panel and plan table from current state. Requires the
        controller, which main() attaches after construction.
        """
        controller = getattr(self, "controller", None)
        if controller is None:
            QMessageBox.warning(self, "Scan-time benchmark",
                                "Controller not ready yet.")
            return
        if getattr(self, "_benchmark_dialog", None) is None:
            from gui.dialogs.benchmark_dialog import BenchmarkDialog
            self._benchmark_dialog = BenchmarkDialog(controller, parent=self)
        dialog = self._benchmark_dialog
        dialog.refresh_from_state()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_mpi_dialog(self):
        """Ask for the MPI process count; the controller persists it."""
        controller = getattr(self, "controller", None)
        if controller is None:
            QMessageBox.warning(self, "MPI processes", "Controller not ready yet.")
            return
        cores = os.cpu_count() or "an unknown number of"
        label = (
            "MPI processes per simulated point.\n"
            f"This computer has {cores} logical processors. On Linux and macOS, "
            "Open MPI allows at most one process per physical core, often half "
            "that number; Windows allows more.\n"
            "Applies from the next scan."
        )
        value, ok = QInputDialog.getInt(
            self, "MPI processes", label, controller.mpi_count, 1, MPI_COUNT_MAX
        )
        if not ok or value == controller.mpi_count:
            return
        try:
            controller.set_mpi_count(value)
        except OSError as exc:
            QMessageBox.warning(self, "MPI processes",
                                f"Could not save the setting: {exc}")

    def _store_default_state(self):
        """Store the default window state for reset functionality."""
        self._default_state = self.saveState()
        self._default_geometry = self.saveGeometry()
    
    def restore_all_docks(self):
        """Show every panel, docking standard panels and floating Reciprocal Space."""
        for dock in self._all_docks:
            dock.setVisible(True)
            if dock is not self.reciprocal_space_dock:
                dock.setFloating(False)
        self._show_reciprocal_window()
        self.statusBar().showMessage("All panels restored", 3000)
    
    def reset_to_default_layout(self):
        """Reset the dock layout to the default arrangement."""
        if self._default_state is not None:
            self.restoreState(self._default_state)
        if self._default_geometry is not None:
            self.restoreGeometry(self._default_geometry)
        self.statusBar().showMessage("Layout reset to default", 3000)

    def _form_docks(self):
        return [self.instrument_dock, self.sample_dock,
                self.scattering_dock, self.simulation_dock]

    def set_column_width(self, mode, fit=True):
        """View > Column Width: lay each form panel out one (NARROW) or two (WIDE)
        blocks wide, and with ``fit`` size the docked ones to it."""
        self._column_width = mode
        self.column_width_actions[mode].setChecked(True)
        for dock in self._form_docks():
            dock.set_column_width(mode)
        if fit:
            self._fit_form_docks()

    def _fit_form_docks(self):
        """Size the docked, visible form panels to the column width; Display takes the rest.

        Wide sizes them two blocks wide only where the window then still
        leaves the plot ``metrics.WIDE_PLOT_MIN_WIDTH``; otherwise one block,
        the same fallback each panel makes when it is too narrow for two.
        """
        docks = [d for d in self._form_docks() if d.isVisible() and not d.isFloating()]
        if not docks:
            return
        count = 1
        if self._column_width == WIDE:
            columns = len({d.x() for d in docks})  # docks stacked in a column share x
            if columns * docks[0].width_for_blocks(2) + metrics.WIDE_PLOT_MIN_WIDTH <= self.width():
                count = 2
        self.resizeDocks(docks, [d.width_for_blocks(count) for d in docks], Qt.Horizontal)

    def save_layout_to_file(self):
        """Save the current layout to a JSON config file."""
        config_path = self._get_layout_config_path()
        
        try:
            layout_data = {
                "layout_version": self.LAYOUT_VERSION,
                "window_geometry": self.saveGeometry().toBase64().data().decode('ascii'),
                "window_state": self.saveState().toBase64().data().decode('ascii'),
                "dock_visibility": {
                    dock.objectName(): dock.isVisible() for dock in self._all_docks
                },
                "dock_floating": {
                    dock.objectName(): dock.isFloating() for dock in self._all_docks
                },
                "column_width": self._column_width,
            }
            
            with open(config_path, 'w', encoding='utf-8') as f:
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
            with open(config_path, 'r', encoding='utf-8') as f:
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

            # Missing (a file from before the setting) means Narrow.
            width = layout_data.get("column_width", NARROW)
            if width not in (NARROW, WIDE):
                print(f"Warning: unknown column_width {width!r} in {config_path}; "
                      f"using {NARROW}")
                width = NARROW
            self._column_width = width
            return True
        except Exception as e:
            print(f"Warning: Failed to restore layout: {e}")
            return False

    def _show_reciprocal_window(self):
        """Show the reciprocal-space canvas as a usable floating workspace."""
        dock = getattr(self, "reciprocal_space_dock", None)
        if dock is None:
            return
        dock.setFloating(True)
        dock.resize(1100, 750)
        dock.setVisible(True)
    
    def _get_layout_config_path(self):
        """Get the path to the layout config file."""
        return str(local_config_path("view_layout.json"))
    
    def _show_about(self):
        """Show the About dialog."""
        QMessageBox.about(self, "About TAVI",
                         "TAVI - Triple-Axis Virtual Instrument\n"
                         f"Version v{tavi.__version__}\n\n"
                         "A virtual instrument simulator for triple-axis neutron "
                         "spectrometry experiments.\n\n"
                         "Panels can be undocked, moved, and rearranged.\n"
                         "Use View menu to manage panel visibility.")
    
    def closeEvent(self, event):
        """Handle window close event - stop simulation and save layout."""
        # Stop any running simulation and tear down the job worker before closing.
        if hasattr(self, 'controller') and self.controller is not None:
            self.controller.print_to_message_center("Window closing - stopping simulation...")
            if hasattr(self.controller, 'shutdown'):
                self.controller.shutdown()
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
