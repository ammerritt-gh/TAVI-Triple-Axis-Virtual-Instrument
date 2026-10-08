"""Main Window for TAVI application with PySide6 and dockable panels."""
import sys
import os
import json
import shutil
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                QScrollArea, QMenuBar, QMenu, QMessageBox,
                                QInputDialog, QSizePolicy, QStyle, QTabBar)
from PySide6.QtCore import Qt, QByteArray, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication

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


LAYOUT_COLUMNS = (2, 3, 4)  # the View > Layout presets


def initial_layout_for_size(available_width, available_height):
    """(columns, column width) for a screen whose available area is this many logical px.

    What first start and Reset to Default Layout pick: 3 columns on a screen
    wide and tall enough for them, else 2 (a laptop, or a short screen such as
    1920x1080 at 125 %); Wide on a wide one, else Narrow. The thresholds are
    in ``metrics``. 4 columns is only ever the user's choice.
    """
    tall = available_height >= metrics.LAYOUT_THREE_COLUMNS_MIN_HEIGHT
    columns = 3 if available_width >= metrics.LAYOUT_TWO_COLUMNS_BELOW and tall else 2
    return columns, WIDE if available_width >= metrics.LAYOUT_WIDE_FROM else NARROW


class TAVIMainWindow(QMainWindow):
    """Main window for TAVI application with dockable panels."""

    # 3: the 2/3/4-column presets. A file of another version is set aside (.bak), not read.
    LAYOUT_VERSION = 3

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

        # Create dock widgets with unique object names for state persistence
        self._create_docks()

        # Connect signals between docks
        self._connect_dock_signals()

        # Set up the central widget (minimal, as most content is in docks)
        self._setup_central_widget()

        # The screen-picked preset: what first start shows, and what a saved
        # layout restores over.
        room = self.screen().availableGeometry()
        self._columns, self._column_width = initial_layout_for_size(room.width(), room.height())
        self._setup_dock_layout(self._columns)

        # Create menu bar with View menu
        self._create_menus()

        # A saved layout of this version wins; otherwise the preset stands,
        # on a window fitted to the screen once it is shown.
        self._layout_restored = self._restore_layout_from_file()
        if not self._layout_restored:
            self.setGeometry(self.screen().availableGeometry())  # refined once shown
        self.set_column_width(self._column_width, fit=False)
        QTimer.singleShot(0, self._apply_startup_geometry)

    def _apply_startup_geometry(self):
        """Once shown: fit the window to its screen and size the preset, unless a layout was restored.

        A restored window keeps its frame unless the frame is larger than its
        screen (a layout saved on a big monitor, opened on a laptop).
        """
        if not self._layout_restored:
            self._fit_to_screen()
        else:
            frame, room = self.frameGeometry(), self.screen().availableGeometry()
            if frame.width() > room.width() or frame.height() > room.height():
                self._fit_to_screen()
        if self._preset_unsized:
            self._size_preset()

    def _fit_to_screen(self):
        """Maximize to the screen's available area.

        The size lands at once (setGeometry is synchronous) so the docks can
        be sized straight after; the maximize itself arrives later from the
        window system and changes little.
        """
        if not self.isMaximized():
            room, frame, inner = (self.screen().availableGeometry(), self.frameGeometry(),
                                  self.geometry())
            self.setGeometry(room.adjusted(inner.left() - frame.left(),
                                           inner.top() - frame.top(),
                                           inner.right() - frame.right(),
                                           inner.bottom() - frame.bottom()))
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def _size_preset(self):
        """Size the current preset to the window: the form columns to the column
        width, the Display column to its proportions, each form column's short
        docks to their content.

        Needs the window at its size: before it is shown the dock area ignores
        resizeDocks.
        """
        self._fit_form_docks()
        self.layout().activate()  # the widths land and the panels reflow first
        self._split_columns()
        self._preset_unsized = False

    def _split_columns(self):
        """Vertical splits: content-sized short docks, the elastic dock takes the rest.

        In each column below, the first dock is elastic (it scrolls, or is the
        plot) and each of the others gets its content's height, capped at
        ``metrics.SPLIT_CONTENT_MAX_SHARE`` of the column. Together they leave
        the elastic dock ``metrics.SPLIT_ELASTIC_MIN_SHARE``; past that the
        lower ones are cut short and scroll (Simulation keeps Run, Stop and the
        progress at its top).
        """
        columns = {
            2: [(self.instrument_dock, self.scattering_dock),
                (self.display_dock, self.simulation_dock)],
            3: [(self.instrument_dock, self.scattering_dock, self.simulation_dock),
                (self.sample_dock, self.ub_matrix_dock)],
            4: [(self.simulation_dock, self.scattering_dock)],
        }[self._columns]
        separator = self.style().pixelMetric(QStyle.PM_DockWidgetSeparatorExtent, None, self)
        for elastic, *short in columns:
            column = self._dock_area_height() - len(short) * separator
            cap = int(column * metrics.SPLIT_CONTENT_MAX_SHARE)
            room = int(column * (1 - metrics.SPLIT_ELASTIC_MIN_SHARE))
            sizes = []
            for dock in short:  # top to bottom: the lower one is cut short first
                sizes.append(min(self._content_height(dock), cap, room))
                room -= sizes[-1]
            self.resizeDocks([elastic, *short], [column - sum(sizes), *sizes], Qt.Vertical)
        if self._columns != 2:
            self._split_display_column()

    def _dock_area_height(self):
        """The height the dock columns share: the window less its menu and status bars."""
        status = self.statusBar()
        return (self.height() - self.menuBar().height()
                - (status.height() if status.isVisible() else 0))

    def _content_height(self, dock):
        """A dock's content height with its title bar, frame and any tab strip."""
        scroll = dock._scroll_area
        height = dock._content_widget.sizeHint().height() + dock.height() - scroll.height()
        if self.tabifiedDockWidgets(dock):
            height += max((bar.height() for bar in self.findChildren(
                               QTabBar, options=Qt.FindDirectChildrenOnly)
                           if bar.isVisible() and dock.windowTitle()
                           in [bar.tabText(i) for i in range(bar.count())]), default=0)
        return height

    def _split_display_column(self):
        """Give the plot most of its column; the Message Log and the tabs below stay usable.

        3 columns: Display 55 %, Log 20 %, tabs 25 %; 4 columns: Display 55 %,
        the tabs (Log among them) 45 %. The docks keep these proportions as
        the window resizes.
        """
        column = self._dock_area_height()
        if self._columns == 3:
            docks, shares = [self.display_dock, self.output_dock, self.data_control_dock], [55, 20, 25]
        else:
            docks, shares = [self.display_dock, self.output_dock], [55, 45]
        self.resizeDocks(docks, [column * share // 100 for share in shares], Qt.Vertical)
    
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
        self.reciprocal_space_dock.setVisible(False)  # opened from View

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

        # Only the plot grows with the window. The form docks are already not
        # horizontally expanding (BaseDockWidget); these share a form column in
        # some presets (UB Matrix under Sample, the tabs behind Instrument),
        # where an expanding dock would take a share of the spare width. They
        # still resize; their maximum comes from their content.
        for dock in (self.ub_matrix_dock, self.output_dock, self.data_control_dock,
                     self.fitting_dock, self.api_dock):
            dock.setSizePolicy(QSizePolicy.Fixed, dock.sizePolicy().verticalPolicy())

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
    
    def _setup_dock_layout(self, columns):
        """Place the docks in the View > Layout preset of ``columns`` (2, 3 or 4).

        3 columns (the operator's own arrangement; the pick on a screen wide and tall enough):
            Instrument  | Sample     | Display
            Scattering  | UB Matrix  | Message Log
            Simulation  |            | [Data Control | Remote API | Fitting]
        4 columns:
            Instrument | Sample | Scattering | Display
                       |        | Simulation | [Log | Data Control | Fitting | Remote API]
        2 columns (the pick otherwise):
            [Instrument | Log | Data Control | Fitting | Remote API] | Display
            [Scattering | Sample]                                   | Simulation

        Every placed dock ends docked and shown, each tab group's first dock
        raised. Reciprocal Space goes back behind Display at its current
        visibility, Misalignment floats at its visibility (centred on the
        screen if it was docked), and UB Matrix is docked only in 3 columns
        (floating and hidden otherwise). Fitting is never tabbed
        with Display: its overlay is drawn on the plot, so both must show at
        once. A dock moves by removal
        and re-adding, which keeps its widgets and connections. The sizes are
        _size_preset()'s, once the window has its size.
        """
        instrument, sample, scattering, simulation = (
            self.instrument_dock, self.sample_dock, self.scattering_dock, self.simulation_dock)
        display, log, data, fitting, api = (
            self.display_dock, self.output_dock, self.data_control_dock, self.fitting_dock,
            self.api_dock)
        reciprocal, ub, misalignment = (
            self.reciprocal_space_dock, self.ub_matrix_dock, self.misalignment_dock)
        placed = [instrument, sample, scattering, simulation, display, log, data, fitting, api]
        reciprocal_shown, misalignment_shown = (not reciprocal.isHidden(),
                                                not misalignment.isHidden())
        moved = (placed + [reciprocal]
                 + ([ub] if columns == 3 or not ub.isFloating() else [])
                 + ([] if misalignment.isFloating() else [misalignment]))
        for dock in moved:
            self.removeDockWidget(dock)  # detaches and hides; nothing is destroyed
        # Lay the emptied area out now: Qt (6.11) then strips the dissolved
        # tab groups' bars and parks them off the window. Without this pass
        # they stay painted where they were, tabs and all, over the new docks.
        self.layout().activate()

        def add(dock):
            self.addDockWidget(Qt.LeftDockWidgetArea, dock)
            if dock.isFloating():  # only takes once the dock is in the layout
                dock.setFloating(False)

        def below(upper, dock):
            add(dock)
            self.splitDockWidget(upper, dock, Qt.Vertical)

        def right_of(left, dock):
            add(dock)
            self.splitDockWidget(left, dock, Qt.Horizontal)

        add(instrument)
        if columns == 2:
            right_of(instrument, display)
            below(instrument, scattering)
            below(display, simulation)
            tabs = [(scattering, sample), (instrument, log, data, fitting, api),
                    (display, reciprocal)]
        elif columns == 3:
            right_of(instrument, sample)
            right_of(sample, display)
            below(instrument, scattering)
            below(scattering, simulation)
            below(sample, ub)
            below(display, log)
            below(log, data)
            tabs = [(display, reciprocal), (data, api, fitting)]
        else:
            right_of(instrument, sample)
            right_of(sample, scattering)
            right_of(scattering, display)
            below(scattering, simulation)
            below(display, log)
            tabs = [(display, reciprocal), (log, data, fitting, api)]

        # Lay the dock area out before tabifying: tabifying into columns
        # rebuilt before any layout pass leaves Qt a second, orphaned tab bar
        # that is shown with the window at its stale position.
        self.layout().activate()
        for group in tabs:
            for previous, dock in zip(group, group[1:]):
                add(dock)
                self.tabifyDockWidget(previous, dock)

        for dock in placed + ([ub] if columns == 3 else []):
            dock.setVisible(True)
        reciprocal.setVisible(reciprocal_shown)
        if columns != 3:
            self._float_centred(ub, False)
        # Docked by the user, or by Restore All Panels.
        self._float_centred(misalignment, misalignment_shown)
        for group in tabs:
            group[0].raise_()
        self._tidy_tab_bars()
        self._columns = columns
        self._preset_unsized = True

    def _tidy_tab_bars(self):
        """Show the live tab strips and hide the dead ones (Qt 6.11 does neither here).

        On a shown window Qt leaves a new tab group's bar hidden until it next
        applies a whole state, and leaves a dissolved group's bar where it was;
        once the layout has been laid out with the group gone (see
        _setup_dock_layout) that bar holds no tabs. So a bar with tabs is a
        live group's and one with none is dead. A one-tab bar (a group whose
        other docks are closed) is Qt's to show or park. Qt does not reuse the
        dead bars: a few small hidden widgets per layout change.
        The rule needs restoreState to run before show(): restoring over a
        shown window leaves the replaced groups' bars still holding their
        tabs, and this would show them.
        """
        for bar in self.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly):
            if bar.count() >= 2:
                bar.show()
            elif bar.count() == 0:
                bar.hide()

    
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

        # Layout: plain actions, not radio items, so no check mark lies about
        # the arrangement once the user drags a dock.
        layout_menu = view_menu.addMenu("&Layout")
        self.layout_actions = {}
        for columns in LAYOUT_COLUMNS:
            action = QAction(f"&{columns} columns", self)
            action.setStatusTip(f"Arrange the panels in {columns} columns; changes the "
                                f"dock arrangement only, not the column width or any field")
            action.triggered.connect(lambda _checked=False, n=columns: self.apply_layout(n))
            layout_menu.addAction(action)
            self.layout_actions[columns] = action

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
        reset_layout_action.setStatusTip(
            "The layout and column width picked for this screen, the window fitted "
            "to it, and the rare Instrument blocks folded")
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

    def restore_all_docks(self):
        """Show every panel, docking standard panels and floating Reciprocal Space.

        A panel Qt cannot dock (one never docked) stays floating; one that
        lies off every screen is centred on the main window's screen.
        """
        for dock in self._all_docks:
            dock.setVisible(True)
            if dock is not self.reciprocal_space_dock:
                dock.setFloating(False)
        self._show_reciprocal_window()
        for dock in self._all_docks:
            if self._off_every_screen(dock):
                self._centre_on_screen(dock)
        self.statusBar().showMessage("All panels restored", 3000)
    
    def apply_layout(self, columns):
        """View > Layout: arrange the docks in the ``columns`` preset; the column width stays."""
        self._setup_dock_layout(columns)
        self._size_preset()
        self.statusBar().showMessage(f"Panels arranged in {columns} columns", 3000)

    def reset_to_default_layout(self):
        """View > Reset to Default Layout: what first start would pick for this screen.

        The preset and column width picked for the window's screen, the window
        fitted to that screen, and the rare Instrument blocks folded again.
        """
        room = self.screen().availableGeometry()
        columns, width = initial_layout_for_size(room.width(), room.height())
        for group in self.instrument_dock.collapsible_groups.values():
            group.set_collapsed(True)
        self.set_column_width(width, fit=False)
        self._setup_dock_layout(columns)
        self._fit_to_screen()
        self._size_preset()
        self.statusBar().showMessage(
            f"Layout reset to the default for this screen: {columns} columns, {width}", 3000)

    def _float_centred(self, dock, shown):
        """Float a dock the preset has no place for, shown or not; a docked one
        leaves the dock area and moves to the centre of the main window's screen."""
        if not dock.isFloating():
            self.removeDockWidget(dock)
            dock.setFloating(True)
            self._centre_on_screen(dock)
        dock.setVisible(shown)

    def _centre_on_screen(self, dock):
        """Move a floating dock to the centre of the main window's screen."""
        dock.move(self.screen().availableGeometry().center() - dock.rect().center())

    def _layout_note(self, message):
        """Tell the user about the window layout, in the Message Log and on the console.

        Written straight into the log: the restore runs before the controller
        (and its message signal) exists.
        """
        print(message)
        self.output_dock.message_text.append(message)

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
        the same fallback each panel makes when it is too narrow for two. A
        form panel in the Display column (Simulation, in 2 columns) takes that
        column's width and reflows to it instead.
        """
        display_x = self.display_dock.x() if self.display_dock.isVisible() else None
        # A tab behind another is "visible" but parked off the window: skip it.
        docks = [d for d in self._form_docks()
                 if d.isVisible() and not d.visibleRegion().isEmpty() and not d.isFloating()
                 and d.x() != display_x]
        if not docks:
            return
        count = 1
        if self._column_width == WIDE:
            columns = len({d.x() for d in docks})  # docks stacked in a column share x
            if columns * docks[0].width_for_blocks(2) + metrics.WIDE_PLOT_MIN_WIDTH <= self.width():
                count = 2
        # Never narrower than another dock sharing the column can go (UB
        # Matrix under Sample): Qt would paint that dock over the next column.
        others = [d for d in self._all_docks if d.isVisible() and not d.isFloating()
                  and not d.visibleRegion().isEmpty() and d not in docks]

        def width(dock):
            floor = max((o.minimumSizeHint().width() for o in others if o.x() == dock.x()),
                        default=0)
            return max(dock.width_for_blocks(count), floor)

        self.resizeDocks(docks, [width(d) for d in docks], Qt.Horizontal)

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
                "columns": self._columns,  # the last View > Layout preset applied
                "collapsed_groups": {
                    key: group.is_collapsed()
                    for key, group in self.instrument_dock.collapsible_groups.items()
                },
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
        """Restore the saved layout if it is of this version; True when it now stands.

        No file is a first start: False, silently. A file of another version
        (or none) is set aside once as ``view_layout.json.v<old>.bak``, or
        copied there when it cannot be moved (it is then overwritten on exit). An
        unreadable file, a geometry or state Qt refuses, or any other error
        falls back to the preset. Each of these says so in the Message Log.
        After a restore, Misalignment, and UB Matrix outside 3 columns, float
        at their saved visibility (centred if they came back docked), and a
        floating dock no screen shows is brought back. Call it only before show(): restoreState over a shown window leaves
        stale tab bars that still hold tabs, which _tidy_tab_bars would show.
        """
        config_path = self._get_layout_config_path()

        if not os.path.exists(config_path):
            return False

        touched = False  # once Qt has been handed the saved state
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                layout_data = json.load(f)
            if not isinstance(layout_data, dict):
                raise ValueError(f"a JSON {type(layout_data).__name__}, not an object")

            version = layout_data.get("layout_version")
            if version != self.LAYOUT_VERSION:
                backup = f"{config_path}.v{version if isinstance(version, int) else 'none'}.bak"
                try:
                    os.replace(config_path, backup)  # overwrites an older .bak
                    kept = f"was set aside as {backup}"
                except OSError as moving:
                    # A locked file may still be readable: copy it aside instead.
                    # Either way this file is overwritten when TAVI closes.
                    try:
                        shutil.copyfile(config_path, backup)
                        kept = (f"could not be moved ({moving}), so it was copied to {backup}; "
                                f"{config_path} itself is overwritten when TAVI closes")
                    except OSError as copying:
                        kept = (f"could not be moved ({moving}; copying failed too: "
                                f"{copying}); {config_path} is overwritten when TAVI closes")
                self._layout_note(
                    f"Window layout: the saved layout is from another TAVI version (layout version "
                    f"{version}; this one reads {self.LAYOUT_VERSION}) and {kept}. Using the "
                    f"{self._columns}-column layout picked for this screen; View > Layout "
                    f"changes it.")
                return False

            geometry = QByteArray.fromBase64(layout_data["window_geometry"].encode('ascii'))
            state = QByteArray.fromBase64(layout_data["window_state"].encode('ascii'))
            touched = True
            if not self.restoreGeometry(geometry):
                raise ValueError("Qt refused its window_geometry")
            if not self.restoreState(state):
                raise ValueError("Qt refused its window_state")
            self._preset_unsized = False  # the saved sizes stand

            # Restore dock visibility
            if "dock_visibility" in layout_data:
                for dock in self._all_docks:
                    name = dock.objectName()
                    if name in layout_data["dock_visibility"]:
                        dock.setVisible(layout_data["dock_visibility"][name])

            # The last preset applied: where a lost dock goes back to.
            columns = layout_data.get("columns")
            if columns in LAYOUT_COLUMNS:
                self._columns = columns
            else:
                print(f"Warning: columns is {columns!r} in {config_path}; "
                      f"taking {self._columns} for a lost dock's place")

            # Qt 6.11 restores a hidden dock that a preset took out and floated
            # as docked, with no place: it would open as a full-width row.
            # These two float wherever the preset gives them no place.
            for dock in ([self.misalignment_dock]
                         + ([] if self._columns == 3 else [self.ub_matrix_dock])):
                self._float_centred(dock, not dock.isHidden())

            width = layout_data.get("column_width", NARROW)
            if width not in (NARROW, WIDE):
                print(f"Warning: unknown column_width {width!r} in {config_path}; "
                      f"using {NARROW}")
                width = NARROW
            self._column_width = width

            # Folded blocks: a missing or non-boolean entry folds (the default).
            folded = layout_data.get("collapsed_groups", {})
            if not isinstance(folded, dict):
                print(f"Warning: collapsed_groups is {folded!r} in {config_path}, "
                      f"not a mapping")
                folded = {}
            for key, group in self.instrument_dock.collapsible_groups.items():
                collapsed = folded.get(key)  # None when missing
                if not isinstance(collapsed, bool):
                    print(f"Warning: collapsed_groups[{key!r}] is {collapsed!r} in "
                          f"{config_path}; folding it (the default)")
                    collapsed = True
                group.set_collapsed(collapsed)
        except Exception as e:
            self._layout_note(
                f"Window layout: could not restore {config_path} ({e!r}). Using the "
                f"{self._columns}-column layout picked for this screen.")
            if touched:  # Qt may have moved docks, onto no screen too, before it failed
                self._setup_dock_layout(self._columns)
                self._rescue_lost_docks()  # the preset leaves Misalignment where it is
            return False
        self._rescue_lost_docks()
        self._tidy_tab_bars()  # the bars of the preset the state replaced
        return True

    def _rescue_lost_docks(self):
        """Bring back each floating dock, shown or hidden, that lies on no screen.

        Qt usually puts such a window back on a screen itself; this is the
        net under it. Only the lost docks move: one with a place in the
        current preset (every dock but Misalignment, and UB Matrix outside
        3 columns) docks again where it last was, or at the edge of the dock
        area when Qt kept no place; the others move to the centre of the
        main window's screen.
        """
        lost = [dock for dock in self._all_docks if self._off_every_screen(dock)]
        if not lost:
            return
        homeless = [self.misalignment_dock] + ([] if self._columns == 3 else [self.ub_matrix_dock])
        for dock in lost:
            if dock in homeless:
                self._centre_on_screen(dock)
                continue
            dock.setFloating(False)  # back where it was docked, if Qt kept the place
            if dock.isFloating():  # no place kept: Qt refuses to redock it
                self.addDockWidget(Qt.LeftDockWidgetArea, dock)
                dock.setFloating(False)
        names = ", ".join(dock.windowTitle() for dock in lost)
        self._layout_note(f"Window layout: {names} had been saved off every screen; "
                          f"brought back.")

    @staticmethod
    def _off_every_screen(dock):
        """A floating dock that no screen shows any part of."""
        return dock.isFloating() and not any(
            screen.availableGeometry().intersects(dock.frameGeometry())
            for screen in QGuiApplication.screens())

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
