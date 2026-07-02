"""Main application controller for TAVI with PySide6 GUI."""
import sys
import os
import shutil
import json
import time
import datetime
import copy
import threading
import queue
import math
import mcstasscript as ms

from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit
from PySide6.QtCore import QObject, Signal, Slot, QTimer

# Import the instrument contract (the concrete instrument arrives via main())
from instruments.contract import PrepFailure, RunExecutionState

# Import TAVI core modules
from tavi.data_processing import (read_1Ddetector_file, write_parameters_to_file,
                                   simple_plot_scan_commands, display_existing_data,
                                   read_parameters_from_file, write_1D_scan, write_2D_scan)
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy
from tavi.utilities import parse_scan_steps, incremented_path_writing
from tavi.sample_mount import SampleMount
from tavi.tas_geometry import component_q_to_instrument_q, instrument_q_to_component_q
from tavi.ub_matrix import (UBMatrix, ObservedPeak, check_training_quality,
                            decode_training, generate_training_exercise, encode_training)
from tavi.runtime_tracker import RuntimeTracker

# Import GUI
from gui.main_window import TAVIMainWindow
from gui.dialogs.diagnostic_config_dialog import DiagnosticConfigDialog

# Physical constants
N_MASS = 1.67492749804e-27  # neutron mass
E_CHARGE = 1.602176634e-19  # electron charge
K_B = 0.08617333262  # Boltzmann's constant in meV/K
HBAR_meV = 6.582119569e-13  # H-bar in meV*s
HBAR = 1.05459e-34  # H-bar in J*s


class TAVIController(QObject):
    """Controller class to connect GUI with backend logic."""
    
    # Signals for thread-safe GUI updates
    progress_updated = Signal(int, int)  # current, total
    remaining_time_updated = Signal(str)
    elapsed_time_updated = Signal(str)
    counts_updated = Signal(float, float)  # max_counts, total_counts
    message_printed = Signal(str)
    
    # Signals for real-time display dock updates
    scan_initialized = Signal(str, list, list, str, str, list, list)  # mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d
    scan_point_updated_1d = Signal(int, float)  # index, counts
    scan_point_updated_2d = Signal(int, int, float)  # idx_x, idx_y, counts
    scan_point_invalid_1d = Signal(int)  # index
    scan_point_invalid_2d = Signal(int, int)  # idx_x, idx_y
    scan_current_index_1d = Signal(int)  # current index
    scan_current_index_2d = Signal(int, int)  # idx_x, idx_y
    scan_completed = Signal()  # scan finished
    scan_auto_save = Signal()  # trigger auto-save of plot
    single_point_result = Signal(float, float)  # max_counts, total_counts for single-point scan
    
    # Signals for diagnostic plots (must run on main thread)
    diagnostic_plot_requested = Signal(object)  # McStasData object
    instrument_diagram_requested = Signal(object)  # McStas instrument object
    
    # Signal for runtime data updates (triggers re-estimation of scan times)
    runtime_data_updated = Signal()
    actual_output_folder_updated = Signal(str)
    pre_scan_estimate_updated = Signal(str)
    
    def __init__(self, window, instrument):
        super().__init__()
        self.window = window
        # The active instrument plugin (fixed for the session) and its live state.
        self.instrument = instrument
        self.instrument_state = instrument.default_state()
        self.descriptor = instrument.descriptor()
        self._mcstas_name = self.descriptor.mcstas_name

        # UB matrix for crystal orientation
        self.ub_matrix = UBMatrix()
        
        # Global variables
        self.stop_event = threading.Event()
        self.diagnostic_settings = {}
        self.current_sample_settings = {}
        # Cross-scan binary reuse (design record §18.5): the last compiled
        # instrument, its execution state, and the build fingerprint it was
        # compiled from. Populated after a scan that actually compiled.
        self._binary_reuse_cache = None
        
        # Flag to prevent recursive updates
        self.updating = False
        
        # Track previous field values to detect actual changes (vs spurious editingFinished signals)
        self._previous_values = {}
        
        # Initialize runtime tracker for scan time estimation
        self.runtime_tracker = RuntimeTracker()
        
        # Debounce timer for scan command validation and time estimates
        self._scan_update_timer = QTimer()
        self._scan_update_timer.setSingleShot(True)
        self._scan_update_timer.setInterval(300)  # 300ms debounce
        self._scan_update_timer.timeout.connect(self._update_scan_estimates)
        
        # Initialize crystal info with the descriptor's first mono/ana crystals
        self.monocris_info, self.anacris_info = self.instrument.crystal_info(
            self.descriptor.mono_crystals[0].id, self.descriptor.ana_crystals[0].id
        )
        
        # Initialize output directory
        self.output_directory = os.path.join(os.getcwd(), "output")
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        
        # Connect signals
        self.connect_signals()
        
        # Load parameters
        self.load_parameters()
        
        # Update crystal info based on loaded parameters
        self.update_monocris_info()
        self.update_anacris_info()

        # Update ideal focusing buttons after initial load
        self.update_ideal_bending_buttons()
        
        # Set up visual feedback for all input fields
        self.setup_visual_feedback()
        
        # Trigger initial scan estimate update
        self._update_scan_estimates()
        
        # Print initialization message
        self.print_to_message_center("GUI initialized.")
    
    def connect_signals(self):
        """Connect all GUI signals to controller methods."""
        # Simulation control buttons (moved to right panel)
        self.window.simulation_dock.run_button.clicked.connect(self.run_simulation_thread)
        self.window.simulation_dock.stop_button.clicked.connect(self.stop_simulation)
        self.window.simulation_dock.quit_button.clicked.connect(self.quit_application)
        self.window.simulation_dock.clear_runtimes_button.clicked.connect(self.clear_runtime_data)
        
        # Parameter buttons (moved to right panel)
        self.window.simulation_dock.save_button.clicked.connect(self.save_parameters)
        self.window.simulation_dock.load_button.clicked.connect(self.load_parameters)
        self.window.simulation_dock.defaults_button.clicked.connect(self.set_default_parameters)
        
        # Diagnostics button
        self.window.simulation_dock.config_diagnostics_button.clicked.connect(self.configure_diagnostics)
        
        # Sample configuration button
        self.window.sample_dock.config_sample_button.clicked.connect(self.configure_sample)
        
        # Sample orientation controls - connected later in signal setup
        # (omega/chi are actual angles, psi/kappa are alignment offsets)
        
        # Misalignment training dock
        self.window.misalignment_dock.check_alignment_button.clicked.connect(self.on_check_alignment)
        self.window.misalignment_dock.load_hash_button.clicked.connect(self.on_load_misalignment_hash)
        self.window.misalignment_dock.clear_misalignment_button.clicked.connect(self.on_clear_misalignment)
        
        # UB Matrix dock
        self.window.ub_matrix_dock.calculate_ub_button.clicked.connect(self.on_calculate_ub)
        self.window.ub_matrix_dock.refine_lattice_button.clicked.connect(self.on_refine_lattice)
        self.window.ub_matrix_dock.reset_ub_button.clicked.connect(self.on_reset_ub)
        self.window.ub_matrix_dock.ub_matrix_changed.connect(self.on_ub_matrix_edited)
        self.window.ub_matrix_dock.generate_training_button.clicked.connect(self.on_generate_training)
        self.window.ub_matrix_dock.load_training_button.clicked.connect(self.on_load_training)
        self.window.ub_matrix_dock.clear_training_button.clicked.connect(self.on_clear_training)
        self.window.ub_matrix_dock.check_training_button.clicked.connect(self.on_check_training)
        # Connect peak Take Position and Remove buttons
        self._reconnect_peak_signals()
        self.window.ub_matrix_dock.add_peak_button.clicked.connect(self._on_peak_added)
        
        # Data control buttons
        self.window.data_control_dock.save_browse_button.clicked.connect(
            lambda: self.open_folder_dialog(self.window.data_control_dock.save_folder_edit)
        )
        self.window.data_control_dock.load_browse_button.clicked.connect(
            lambda: self.open_folder_dialog(self.window.data_control_dock.load_folder_edit)
        )
        self.window.data_control_dock.load_data_button.clicked.connect(self.load_and_display_data)
        
        # Connect internal signals to GUI updates
        self.progress_updated.connect(self.update_progress)
        self.remaining_time_updated.connect(self.update_remaining_time)
        self.elapsed_time_updated.connect(self.update_elapsed_time)
        self.counts_updated.connect(self.update_counts_entry)
        self.message_printed.connect(self.window.output_dock.message_text.append)
        
        # Connect display dock signals
        self.scan_initialized.connect(self._on_scan_initialized)
        self.scan_point_updated_1d.connect(self.window.display_dock.update_1d_point)
        self.scan_point_updated_2d.connect(self.window.display_dock.update_2d_point)
        self.scan_point_invalid_1d.connect(self.window.display_dock.mark_1d_point_invalid)
        self.scan_point_invalid_2d.connect(self.window.display_dock.mark_2d_point_invalid)
        self.scan_current_index_1d.connect(self.window.display_dock.set_current_scan_index)
        self.scan_current_index_2d.connect(self.window.display_dock.set_current_scan_index_2d)
        self.scan_completed.connect(self.window.display_dock.scan_complete)
        self.scan_auto_save.connect(self.window.display_dock.auto_save_plot)
        self.single_point_result.connect(self.window.display_dock.show_single_point_result)
        
        # Connect diagnostic plot signals (runs on main thread for matplotlib)
        self.diagnostic_plot_requested.connect(self._show_diagnostic_plots)
        self.instrument_diagram_requested.connect(self._show_instrument_diagram)
        
        # Connect runtime data update signal to refresh scan time estimates
        self.runtime_data_updated.connect(self._update_scan_estimates)
        self.actual_output_folder_updated.connect(self._on_actual_output_folder_updated)
        self.pre_scan_estimate_updated.connect(self.window.simulation_dock.update_pre_scan_estimate)
        
        # Connect crystal selection changes
        self.window.instrument_dock.monocris_combo.currentTextChanged.connect(self.update_monocris_info)
        self.window.instrument_dock.anacris_combo.currentTextChanged.connect(self.update_anacris_info)

        # Connect NMO selection change to update ideal bending values (instrument-
        # specific coupling; the module widget only exists when declared)
        if getattr(self.window.instrument_dock, "nmo_combo", None) is not None:
            self.window.instrument_dock.nmo_combo.currentTextChanged.connect(self.update_ideal_bending_buttons)

        # Ideal focusing buttons
        self.window.instrument_dock.rhm_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rhm")
        )
        self.window.instrument_dock.rvm_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rvm")
        )
        self.window.instrument_dock.rha_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rha")
        )

        # User edits unlock ideal lock
        self.window.instrument_dock.rhm_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rhm")
        )
        self.window.instrument_dock.rvm_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rvm")
        )
        self.window.instrument_dock.rha_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rha")
        )
        
        # Connect field editing events for linked updates
        # Instrument angles - update energies and Q-space
        self.window.instrument_dock.mtt_edit.editingFinished.connect(self.on_mtt_changed)
        self.window.instrument_dock.att_edit.editingFinished.connect(self.on_att_changed)
        self.window.instrument_dock.stt_edit.editingFinished.connect(self.on_stt_changed)
        self.window.instrument_dock.omega_edit.editingFinished.connect(self.on_omega_changed)
        self.window.instrument_dock.chi_edit.editingFinished.connect(self.on_chi_changed)
        
        # Energies - update related energies and angles
        self.window.instrument_dock.Ki_edit.editingFinished.connect(self.on_Ki_changed)
        self.window.instrument_dock.Ei_edit.editingFinished.connect(self.on_Ei_changed)
        self.window.instrument_dock.Kf_edit.editingFinished.connect(self.on_Kf_changed)
        self.window.instrument_dock.Ef_edit.editingFinished.connect(self.on_Ef_changed)
        
        # K fixed mode and fixed E - update all related values
        self.window.scattering_dock.K_fixed_combo.currentTextChanged.connect(self.on_K_fixed_changed)
        self.window.scattering_dock.fixed_E_edit.editingFinished.connect(self.on_fixed_E_changed)
        
        # Q-space - update HKL and angles
        self.window.scattering_dock.qx_edit.editingFinished.connect(self.on_Q_changed)
        self.window.scattering_dock.qy_edit.editingFinished.connect(self.on_Q_changed)
        self.window.scattering_dock.qz_edit.editingFinished.connect(self.on_Q_changed)
        
        # HKL - update Q-space and angles
        self.window.scattering_dock.H_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.scattering_dock.K_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.scattering_dock.L_edit.editingFinished.connect(self.on_HKL_changed)
        
        # DeltaE - update energies
        self.window.scattering_dock.deltaE_edit.editingFinished.connect(self.on_deltaE_changed)
        
        # Lattice parameters - only update via Save button (lock/unlock mechanism)
        # Connect the lattice save signal from the sample dock
        self.window.sample_dock.lattice_parameters_changed.connect(self.on_lattice_changed)
        # Sample alignment offsets (kappa and psi)
        self.window.sample_dock.kappa_edit.editingFinished.connect(self.on_alignment_offset_changed)
        self.window.sample_dock.psi_edit.editingFinished.connect(self.on_alignment_offset_changed)
        # Sample selection change -> update the instrument state and show status
        try:
            self.window.sample_dock.sample_combo.currentTextChanged.connect(self.on_sample_changed)
        except Exception:
            pass
        
        # Scan command validation - check for conflicts and errors on text change and on focus out
        self.window.simulation_dock.scan_command_1_edit.textChanged.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_2_edit.textChanged.connect(self.validate_scan_commands)
        # Also validate when editing is finished (focus lost) to catch final state
        self.window.simulation_dock.scan_command_1_edit.editingFinished.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_2_edit.editingFinished.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_1_edit.editingFinished.connect(self._trigger_scan_update)
        self.window.simulation_dock.scan_command_2_edit.editingFinished.connect(self._trigger_scan_update)
        
        # Connect scan command and neutron changes to debounced time estimate update
        self.window.simulation_dock.scan_command_1_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.scan_command_2_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.number_neutrons_edit.textChanged.connect(self._trigger_scan_update)
        # Also connect the new mantissa/exponent fields directly for immediate feedback
        self.window.simulation_dock.neutron_mantissa_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.neutron_exponent_edit.textChanged.connect(self._trigger_scan_update)
        # Also update on editingFinished to catch committed changes
        try:
            self.window.simulation_dock.number_neutrons_edit.editingFinished.connect(self._trigger_scan_update)
        except Exception:
            pass
    
    def setup_visual_feedback(self):
        """Set up visual feedback for all input fields to show pending/saved states."""
        # Collect all QLineEdit widgets from all docks
        line_edits = []
        
        # Instrument dock (incl. the descriptor-generated slit edits)
        line_edits.extend(self.window.instrument_dock.line_edits_for_feedback())
        
        # Reciprocal space dock
        line_edits.extend([
            self.window.scattering_dock.qx_edit,
            self.window.scattering_dock.qy_edit,
            self.window.scattering_dock.qz_edit,
            self.window.scattering_dock.H_edit,
            self.window.scattering_dock.K_edit,
            self.window.scattering_dock.L_edit,
            self.window.scattering_dock.deltaE_edit,
        ])
        
        # Sample dock - only alignment offsets, NOT lattice fields (those use lock/unlock)
        line_edits.extend([
            self.window.sample_dock.kappa_edit,
            self.window.sample_dock.psi_edit,
        ])
        
        # Scan controls dock
        line_edits.extend([
            self.window.simulation_dock.neutron_mantissa_edit,
            self.window.simulation_dock.neutron_exponent_edit,
            self.window.scattering_dock.fixed_E_edit,
            self.window.simulation_dock.scan_command_1_edit,
            self.window.simulation_dock.scan_command_2_edit,
        ])
        
        # Apply visual feedback to all line edits
        for line_edit in line_edits:
            self._setup_field_feedback(line_edit)
    
    def _setup_field_feedback(self, line_edit):
        """Set up visual feedback for a single QLineEdit widget."""
        # Store original value and style
        line_edit.setProperty("original_value", line_edit.text())
        line_edit.setProperty("original_style", line_edit.styleSheet())
        
        # Connect to textChanged to show pending state
        def on_text_changed():
            if not self.updating:  # Only show pending if not programmatically updating
                original = line_edit.property("original_value")
                current = line_edit.text()
                if current != original:
                    # Show pending state with orange border
                    line_edit.setStyleSheet("QLineEdit { border: 2px solid #FF8C00; }")
        
        line_edit.textChanged.connect(on_text_changed)
        
        # Connect to editingFinished to show saved state and flash
        original_finished_handler = None
        
        def on_editing_finished():
            original = line_edit.property("original_value")
            current = line_edit.text()
            
            if current != original:
                # Flash with bold dark border to show changes were saved
                line_edit.setStyleSheet("QLineEdit { border: 3px solid #000000; }")
                
                # Update stored original value
                line_edit.setProperty("original_value", current)
                
                # After 300ms, return to normal state
                QTimer.singleShot(300, lambda: line_edit.setStyleSheet(line_edit.property("original_style") or ""))
            else:
                # No changes, just return to normal
                line_edit.setStyleSheet(line_edit.property("original_style") or "")
        
        # We need to ensure editingFinished fires AFTER the field update handlers
        # So we'll connect with a slight delay
        def delayed_on_editing_finished():
            QTimer.singleShot(10, on_editing_finished)
        
        line_edit.editingFinished.connect(delayed_on_editing_finished)
    
    def quit_application(self):
        """Quit the application."""
        # Stop any running simulation before quitting
        self.stop_event.set()
        self.print_to_message_center("Shutting down...")
        QApplication.quit()
    
    def open_folder_dialog(self, line_edit):
        """Open file dialog to select a folder."""
        default_folder = os.getcwd()
        folder_selected = QFileDialog.getExistingDirectory(
            self.window, "Select Folder", default_folder
        )
        if folder_selected:
            line_edit.setText(folder_selected)
    
    def print_to_message_center(self, message):
        """Print message to the GUI message center."""
        self.message_printed.emit(message)
        print(message)  # Also print to console
    
    @Slot(int, int)
    def update_progress(self, current, total):
        """Update progress bar."""
        percentage = int(current * 100 / total) if total > 0 else 0
        self.window.simulation_dock.progress_bar.setValue(percentage)
        self.window.simulation_dock.progress_label.setText(f"{percentage}% ({current}/{total})")
    
    @Slot(str)
    def update_remaining_time(self, remaining_time):
        """Update remaining time label."""
        self.window.simulation_dock.remaining_time_label.setText(f"Estimated Remaining Time: {remaining_time}")

    @Slot(str)
    def update_elapsed_time(self, elapsed_time_str):
        """Update elapsed time label in the UI."""
        # Use the dock helper if available
        try:
            self.window.simulation_dock.update_elapsed_time(elapsed_time_str)
        except Exception:
            # Fallback: set label directly
            try:
                self.window.simulation_dock.elapsed_time_label.setText(f"Elapsed Time: {elapsed_time_str}")
            except Exception:
                pass
    
    @Slot(float, float)
    def update_counts_entry(self, max_counts, total_counts):
        """Update counts display."""
        self.window.simulation_dock.max_counts_label.setText(str(int(max_counts)))
        self.window.simulation_dock.total_counts_label.setText(str(int(total_counts)))
    
    @Slot(str, list, list, str, str, list, list)
    def _on_scan_initialized(self, mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d):
        """Handle scan initialization signal and forward to display dock."""
        if mode == '1D':
            self.window.display_dock.initialize_scan(mode, values1, valid_mask1, var1)
        else:
            self.window.display_dock.initialize_scan(mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d)

    @Slot(str)
    def _on_actual_output_folder_updated(self, folder):
        """Update the resolved output folder on the main thread."""
        self.window.data_control_dock.actual_folder_label.setText(folder)
        self.window.display_dock.set_data_folder(folder)
    
    @Slot(object)
    def _show_diagnostic_plots(self, data):
        """Display diagnostic monitor plots on the main thread.
        
        This slot is called from the simulation thread via signal to ensure
        matplotlib GUI runs on the main thread.
        """
        if data is None or data is math.nan:
            self.print_to_message_center("No diagnostic data to display")
            return
        try:
            self.print_to_message_center("Displaying diagnostic monitor plots...")
            ms.make_sub_plot(data, log=False)
        except Exception as e:
            self.print_to_message_center(f"Could not display diagnostic plots: {e}")
    
    @Slot(object)
    def _show_instrument_diagram(self, instrument):
        """Display instrument diagram on the main thread.
        
        This slot is called from the simulation thread via signal to ensure
        matplotlib GUI runs on the main thread.
        """
        if instrument is None:
            return
        
        try:
            self.print_to_message_center("Displaying instrument diagram...")
            instrument.show_diagram()
        except Exception as e:
            self.print_to_message_center(f"Could not display instrument diagram: {e}")
    
    def _build_scan_metadata(self, vals):
        """Build display metadata from a frozen values snapshot."""
        metadata = {}
        
        # Number of neutrons
        metadata['number_neutrons'] = vals.get('number_neutrons', 1000000)
        
        # Ki/Kf fixed mode
        metadata['K_fixed'] = vals.get('K_fixed', 'Ki Fixed')
        
        # Fixed E
        metadata['fixed_E'] = vals.get('fixed_E', 0)
        
        # Collimations (descriptor-driven container: str or set[str] per slot)
        collimation = vals.get('collimation', {})
        for slot in self.descriptor.collimation:
            value = collimation.get(slot.id)
            if slot.multi_select:
                selected = [v for v in slot.allowed if v in (value or ())]
                metadata[slot.id] = (
                    "+".join(f"{v}'" for v in selected) if selected else "open"
                )
            else:
                metadata[slot.id] = value if value is not None else 'open'
        
        # Crystals
        metadata['monocris'] = vals.get('monocris', self.descriptor.mono_crystals[0].id)
        metadata['anacris'] = vals.get('anacris', self.descriptor.ana_crystals[0].id)
        
        # Alignment offsets
        metadata['kappa'] = vals.get('kappa', 0)
        metadata['psi'] = vals.get('psi', 0)
        
        # Q-space coordinates
        metadata['qx'] = vals.get('qx', 0)
        metadata['qy'] = vals.get('qy', 0)
        metadata['qz'] = vals.get('qz', 0)
        
        # HKL coordinates
        metadata['H'] = vals.get('H', 0)
        metadata['K'] = vals.get('K', 0)
        metadata['L'] = vals.get('L', 0)
        
        # Energy transfer
        metadata['deltaE'] = vals.get('deltaE', 0)
        
        # Optional modules (legacy display keys kept for the display dock)
        modules = vals.get('modules', {})
        metadata['NMO_installed'] = modules.get('nmo', 'None')
        metadata['V_selector_installed'] = modules.get('v_selector', False)

        return metadata

    def _build_current_scan_metadata(self):
        """Build scan metadata from current GUI values."""
        vals = self.get_gui_values()
        if not vals:
            return {}

        return self._build_scan_metadata(vals)

    def _write_stage_timing_summary(self, data_folder, stage_summary):
        """Persist per-run stage timing data under the scan output folder."""
        summary_path = os.path.join(data_folder, "stage_timing_summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(stage_summary, handle, indent=2)
        return summary_path
    
    def get_gui_values(self):
        """Helper to get all GUI values as a dict."""
        try:
            return {
                'mtt': float(self.window.instrument_dock.mtt_edit.text() or 0),
                'stt': float(self.window.instrument_dock.stt_edit.text() or 0),
                'omega': float(self.window.instrument_dock.omega_edit.text() or 0),
                'chi': float(self.window.instrument_dock.chi_edit.text() or 0),
                'att': float(self.window.instrument_dock.att_edit.text() or 0),
                'Ki': float(self.window.instrument_dock.Ki_edit.text() or 0),
                'Ei': float(self.window.instrument_dock.Ei_edit.text() or 0),
                'Kf': float(self.window.instrument_dock.Kf_edit.text() or 0),
                'Ef': float(self.window.instrument_dock.Ef_edit.text() or 0),
                'K_fixed': self.window.scattering_dock.K_fixed_combo.currentText(),
                'fixed_E': float(self.window.scattering_dock.fixed_E_edit.text() or 0),
                'qx': float(self.window.scattering_dock.qx_edit.text() or 0),
                'qy': float(self.window.scattering_dock.qy_edit.text() or 0),
                'qz': float(self.window.scattering_dock.qz_edit.text() or 0),
                'H': float(self.window.scattering_dock.H_edit.text() or 0),
                'K': float(self.window.scattering_dock.K_edit.text() or 0),
                'L': float(self.window.scattering_dock.L_edit.text() or 0),
                'deltaE': float(self.window.scattering_dock.deltaE_edit.text() or 0),
                'lattice_a': float(self.window.sample_dock.lattice_a_edit.text() or 1),
                'lattice_b': float(self.window.sample_dock.lattice_b_edit.text() or 1),
                'lattice_c': float(self.window.sample_dock.lattice_c_edit.text() or 1),
                'lattice_alpha': float(self.window.sample_dock.lattice_alpha_edit.text() or 90),
                'lattice_beta': float(self.window.sample_dock.lattice_beta_edit.text() or 90),
                'lattice_gamma': float(self.window.sample_dock.lattice_gamma_edit.text() or 90),
                'kappa': float(self.window.sample_dock.kappa_edit.text() or 0),
                'psi': float(self.window.sample_dock.psi_edit.text() or 0),
                'monocris': self.window.instrument_dock.selected_mono_id(),
                'anacris': self.window.instrument_dock.selected_ana_id(),
                'rhm': float(self.window.instrument_dock.rhm_edit.text() or 0),
                'rvm': float(self.window.instrument_dock.rvm_edit.text() or 0),
                'rha': float(self.window.instrument_dock.rha_edit.text() or 0),
                'source_type': self.window.instrument_dock.selected_source_id(),
                'source_dE': float(self.window.instrument_dock.source_dE_edit.text() or 2),
                # Descriptor-driven categories (the plugin's scan_config owns the
                # mapping from these containers to its instrument state fields).
                'modules': self.window.instrument_dock.module_values(),
                'collimation': self.window.instrument_dock.collimation_values(),
                'slits_mm': self.window.instrument_dock.slit_values_mm(),
                'number_neutrons': self.window.simulation_dock.get_number_neutrons(),
                'scan_command1': self.window.simulation_dock.scan_command_1_edit.text(),
                'scan_command2': self.window.simulation_dock.scan_command_2_edit.text(),
                'diagnostic_mode': self.window.simulation_dock.diagnostic_mode_check.isChecked(),
            }
        except ValueError:
            return None

    def _build_sample_mount(self, vals):
        """Build the current component-agnostic sample mount from GUI lattice + UB."""
        local_ub_matrix = copy.deepcopy(self.ub_matrix)
        local_ub_matrix.set_lattice(
            vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
            vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
        )
        return SampleMount.from_lattice_tas(
            vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
            vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
            R_mount=local_ub_matrix.U,
        )

    def _hkl_to_sample_q(self, H, K, L, vals):
        """Convert HKL to public instrument/GUI Q using the current sample mount."""
        q_component = self._build_sample_mount(vals).hkl_to_q(H, K, L)
        q = component_q_to_instrument_q(q_component)
        return float(q[0]), float(q[1]), float(q[2])

    def _sample_q_to_hkl(self, qx, qy, qz, vals):
        """Convert public instrument/GUI Q to HKL using the current sample mount."""
        q_component = instrument_q_to_component_q([qx, qy, qz])
        return self._build_sample_mount(vals).q_to_hkl(*q_component)

    def _collect_simulation_launch_state(self):
        """Freeze GUI state before starting the simulation worker thread."""
        vals = self.get_gui_values()
        if not vals:
            return None

        try:
            sample_key = self.window.sample_dock.get_selected_sample_key()
        except Exception:
            sample_key = None

        diagnostic_settings = copy.deepcopy(self.diagnostic_settings)

        return {
            'vals': vals,
            'save_folder_input': self.window.data_control_dock.save_folder_edit.text(),
            'sample_key': sample_key,
            'scan_config': self.instrument.scan_config(
                self.instrument_state, vals, sample_key, diagnostic_settings,
                self._build_sample_mount(vals),
            ),
            'diagnostic_settings': diagnostic_settings,
            'relative_mode_1': self.window.simulation_dock.relative_1_button.isChecked(),
            'relative_mode_2': self.window.simulation_dock.relative_2_button.isChecked(),
            'compact_save_enabled': self.window.data_control_dock.compact_save_check.isChecked(),
        }
    
    def set_gui_value(self, widget, value, precision=4):
        """Helper to set GUI value with proper formatting."""
        if self.updating:
            return
        try:
            formatted = f"{float(value):.{precision}f}".rstrip('0').rstrip('.')
            widget.setText(formatted)
        except (ValueError, TypeError):
            pass

    def normalize_scan_variable(self, name):
        """Normalize scan variable names to canonical form.
        
        Note: omega and 2theta are kept as-is for display purposes,
        but they map to the same indices as A3 and A2 respectively.
        """
        if not name:
            return name
        name = str(name).strip()
        lower = name.lower()
        if lower in ["h", "k", "l"]:
            return lower.upper()
        if lower in ["a1", "a2", "a3", "a4"]:
            return lower.upper()
        if lower == "2theta":
            return "2theta"  # Keep as 2theta for display, maps to same index as A2
        if lower == "omega":
            return "omega"  # Keep as omega for display, maps to same index as A3
        if lower == "deltae":
            return "deltaE"
        if lower in ["qx", "qy", "qz", "rhm", "rvm", "rha", "rva"]:
            return lower
        if lower in ["chi", "kappa", "psi"]:
            return lower
        return name
    
    def _field_value_changed(self, field_name: str, current_value: float, tolerance: float = 1e-9) -> bool:
        """
        Check if a field value has actually changed from its previous value.
        This prevents spurious updates from editingFinished signals when focus changes
        without the value being modified.
        
        Args:
            field_name: Unique identifier for the field
            current_value: The current numeric value of the field
            tolerance: Tolerance for floating point comparison
            
        Returns:
            True if the value has changed, False otherwise
        """
        previous = self._previous_values.get(field_name)
        if previous is None or abs(previous - current_value) > tolerance:
            self._previous_values[field_name] = current_value
            return True
        return False
    
    def _update_tracked_value(self, field_name: str, value: float):
        """Update the tracked value for a field (use when setting field programmatically)."""
        self._previous_values[field_name] = value
    
    def update_all_variables(self, skip_crystal_angles=False):
        """
        Comprehensive update of all instrument variables based on K_fixed mode.
        This is the central method that ensures all fields stay in sync.
        
        Args:
            skip_crystal_angles: If True, don't update mtt/att (use when angles are source of truth)
        """
        if self.updating:
            return
        
        vals = self.get_gui_values()
        if not vals or not self.monocris_info or not self.anacris_info:
            return
        
        try:
            self.updating = True
            
            
            # Update Ei and Ef based on K_fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                # Ki/Ei are fixed, calculate Ef
                Ei = vals['fixed_E']
                Ef = Ei - vals['deltaE']
            else:  # Kf Fixed
                # Kf/Ef are fixed, calculate Ei
                Ef = vals['fixed_E']
                Ei = Ef + vals['deltaE']
            
            # Calculate wave vectors from energies
            Ki = energy2k(Ei)
            Kf = energy2k(Ef)
            
            # Recalculate deltaE to ensure consistency
            deltaE = Ei - Ef
            
            # Update energy-related GUI fields
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
            
            # Only update crystal angles if not skipping (angles are not the source of truth)
            if not skip_crystal_angles:
                mtt = 2 * k2angle(Ki, self.monocris_info['dm'])
                att = 2 * k2angle(Kf, self.anacris_info['da'])
                self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            
        except (ValueError, KeyError) as e:
            pass
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()

    def _compute_ideal_bending_values(self, mtt=None, att=None):
        """Compute ideal absolute bending radii from current angles.
        
        When NMO (Nested Mirror Optic) is installed, the ideal monochromator
        bending is flat (0), since the NMO provides the focusing.
        
        For the monochromator: Uses parallel beam formula since the source is
        effectively at infinity (neutron guide produces quasi-parallel beam).
        Per McStas Monochromator_curved documentation:
            RV = 2*L*sin(theta)
            RH = 2*L/sin(theta)
        where L = L2 (monochromator to sample distance) and theta is Bragg angle.
        
        For the analyzer: Uses point-source formula since the sample is a real
        point source at L3, focusing to the detector at L4.
        """
        try:
            if mtt is None:
                mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            if att is None:
                att = float(self.window.instrument_dock.att_edit.text() or 0)

            # Check if NMO is installed - if so, ideal monochromator bending is flat (0)
            nmo_combo = getattr(self.window.instrument_dock, "nmo_combo", None)
            nmo_installed = nmo_combo.currentText() if nmo_combo is not None else "None"
            if nmo_installed != "None":
                # NMO provides focusing, so ideal monochromator bending is flat
                rhm = 0
                rvm = 0
            else:
                # Use theta (mtt/2) not 2-theta (mtt) per McStas documentation:
                # RV = 2*L*sin(theta) where theta is the Bragg angle
                sin_m = math.sin(math.radians(mtt / 2))

                if sin_m == 0:
                    return None

                # Parallel beam formula: source effectively at infinity (guide output)
                # Focus from monochromator to sample at distance L2
                rhm = 2 * self.instrument_state.L2 / sin_m
                rvm = 2 * self.instrument_state.L2 * sin_m

                if rhm < 2.0:
                    rhm = 2.0
                if rvm < 0.5:
                    rvm = 0.5

            # Analyzer: point-source formula (sample is real point source)
            denom_a = (1 / self.instrument_state.L3 + 1 / self.instrument_state.L4)
            # Use theta (att/2) not 2-theta (att) per McStas documentation
            sin_a = math.sin(math.radians(att / 2))

            if denom_a == 0 or sin_a == 0:
                return None

            rha = 2 / sin_a / denom_a
            rva = 0.8

            if rha < 2.0:
                rha = 2.0

            return {"rhm": rhm, "rvm": rvm, "rha": rha, "rva": rva}
        except Exception:
            return None

    def update_ideal_bending_buttons(self):
        """Update ideal bending button labels based on current angles."""
        ideal = self._compute_ideal_bending_values()
        if not ideal:
            self.window.instrument_dock.rhm_ideal_button.setText("Ideal: --")
            self.window.instrument_dock.rvm_ideal_button.setText("Ideal: --")
            self.window.instrument_dock.rha_ideal_button.setText("Ideal: --")
            return

        rhm_locked = self.is_bending_locked("rhm")
        rvm_locked = self.is_bending_locked("rvm")
        rha_locked = self.is_bending_locked("rha")

        # Show "Flat" when NMO is installed and ideal value is 0
        if ideal['rhm'] == 0:
            self.window.instrument_dock.rhm_ideal_button.setText(
                f"Ideal ({'L' if rhm_locked else 'U'}): Flat (NMO)"
            )
        else:
            self.window.instrument_dock.rhm_ideal_button.setText(
                f"Ideal ({'L' if rhm_locked else 'U'}): {ideal['rhm']:.3f} m"
            )
        
        if ideal['rvm'] == 0:
            self.window.instrument_dock.rvm_ideal_button.setText(
                f"Ideal ({'L' if rvm_locked else 'U'}): Flat (NMO)"
            )
        else:
            self.window.instrument_dock.rvm_ideal_button.setText(
                f"Ideal ({'L' if rvm_locked else 'U'}): {ideal['rvm']:.3f} m"
            )
        
        self.window.instrument_dock.rha_ideal_button.setText(
            f"Ideal ({'L' if rha_locked else 'U'}): {ideal['rha']:.3f} m"
        )

        # If locked to ideal, keep fields synced
        if not self.updating:
            self.updating = True
            try:
                if rhm_locked:
                    self._update_locked_field_if_needed(self.window.instrument_dock.rhm_edit, ideal['rhm'])
                if rvm_locked:
                    self._update_locked_field_if_needed(self.window.instrument_dock.rvm_edit, ideal['rvm'])
                if rha_locked:
                    self._update_locked_field_if_needed(self.window.instrument_dock.rha_edit, ideal['rha'])
            finally:
                self.updating = False

    def apply_ideal_bending_value(self, key):
        """Apply the ideal bending value to the selected input field."""
        ideal = self._compute_ideal_bending_values()
        if not ideal:
            return
        if key == "rhm":
            self.window.instrument_dock.rhm_ideal_button.setChecked(True)
            self.window.instrument_dock.rhm_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rhm_edit, ideal['rhm'])
        elif key == "rvm":
            self.window.instrument_dock.rvm_ideal_button.setChecked(True)
            self.window.instrument_dock.rvm_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rvm_edit, ideal['rvm'])
        elif key == "rha":
            self.window.instrument_dock.rha_ideal_button.setChecked(True)
            self.window.instrument_dock.rha_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rha_edit, ideal['rha'])
        self.update_ideal_bending_buttons()

    def apply_ideal_bending_values(self):
        """Apply ideal bending values to all fields."""
        ideal = self._compute_ideal_bending_values()
        if not ideal:
            return
        self._set_and_confirm_field(self.window.instrument_dock.rhm_edit, ideal['rhm'])
        self._set_and_confirm_field(self.window.instrument_dock.rvm_edit, ideal['rvm'])
        self._set_and_confirm_field(self.window.instrument_dock.rha_edit, ideal['rha'])

    def unlock_ideal_bending(self, key):
        """Unlock ideal bending button when user edits the field."""
        if key == "rhm":
            self.window.instrument_dock.rhm_ideal_button.setChecked(False)
            self.window.instrument_dock.rhm_ideal_button.setEnabled(True)
        elif key == "rvm":
            self.window.instrument_dock.rvm_ideal_button.setChecked(False)
            self.window.instrument_dock.rvm_ideal_button.setEnabled(True)
        elif key == "rha":
            self.window.instrument_dock.rha_ideal_button.setChecked(False)
            self.window.instrument_dock.rha_ideal_button.setEnabled(True)

    def is_bending_locked(self, key):
        """Return True if a bending field is locked to ideal."""
        if key == "rhm":
            return self.window.instrument_dock.rhm_ideal_button.isChecked() and not self.window.instrument_dock.rhm_ideal_button.isEnabled()
        if key == "rvm":
            return self.window.instrument_dock.rvm_ideal_button.isChecked() and not self.window.instrument_dock.rvm_ideal_button.isEnabled()
        if key == "rha":
            return self.window.instrument_dock.rha_ideal_button.isChecked() and not self.window.instrument_dock.rha_ideal_button.isEnabled()
        return False

    def _set_and_confirm_field(self, line_edit, value, force=False):
        """Set a field programmatically and flash accepted state."""
        if self.updating and not force:
            return
        try:
            self.updating = True
            formatted = self._format_field_value(value)
            line_edit.setText(formatted)
            line_edit.setProperty("original_value", line_edit.text())
            self._flash_field_saved(line_edit)
        except (ValueError, TypeError):
            pass
        finally:
            self.updating = False

    def _format_field_value(self, value, precision=4):
        """Format numeric field value consistently."""
        return f"{float(value):.{precision}f}".rstrip('0').rstrip('.')

    def _update_locked_field_if_needed(self, line_edit, value):
        """Update locked field only if the value changed."""
        try:
            formatted = self._format_field_value(value)
        except (ValueError, TypeError):
            return
        if line_edit.text() == formatted:
            return
        self._set_and_confirm_field(line_edit, value, force=True)

    def _flash_field_saved(self, line_edit):
        """Flash field to indicate programmatic update accepted."""
        original_style = line_edit.property("original_style") or ""
        line_edit.setStyleSheet("QLineEdit { border: 2px solid #FF8C00; }")

        def _bold_then_reset():
            line_edit.setStyleSheet("QLineEdit { border: 3px solid #000000; }")
            QTimer.singleShot(300, lambda: line_edit.setStyleSheet(original_style))

        QTimer.singleShot(150, _bold_then_reset)

    def _load_bending_parameters(self, parameters):
        """Load absolute bending radii from the saved parameter block."""
        self.window.instrument_dock.rhm_edit.setText(str(parameters.get("rhm_var", "0")))
        self.window.instrument_dock.rvm_edit.setText(str(parameters.get("rvm_var", "0")))
        self.window.instrument_dock.rha_edit.setText(str(parameters.get("rha_var", "0")))

    def _apply_bending_lock_state(self, rhm_locked, rvm_locked, rha_locked):
        """Apply lock state for ideal bending buttons."""
        self.window.instrument_dock.rhm_ideal_button.setChecked(bool(rhm_locked))
        self.window.instrument_dock.rhm_ideal_button.setEnabled(not bool(rhm_locked))
        self.window.instrument_dock.rvm_ideal_button.setChecked(bool(rvm_locked))
        self.window.instrument_dock.rvm_ideal_button.setEnabled(not bool(rvm_locked))
        self.window.instrument_dock.rha_ideal_button.setChecked(bool(rha_locked))
        self.window.instrument_dock.rha_ideal_button.setEnabled(not bool(rha_locked))

        if any([rhm_locked, rvm_locked, rha_locked]):
            self.update_ideal_bending_buttons()
    
    def on_mtt_changed(self):
        """Update energies when mono 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        # Check if value actually changed
        if not self._field_value_changed('mtt', vals['mtt']):
            return
        
        try:
            self.updating = True
            # Update Ki and Ei from mtt
            Ki = angle2k(vals['mtt'] / 2, self.monocris_info['dm'])
            Ei = k2energy(Ki)
            
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_att_changed(self):
        """Update energies when analyzer 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        # Check if value actually changed
        if not self._field_value_changed('att', vals['att']):
            return
        
        try:
            self.updating = True
            # Update Kf and Ef from att
            Kf = angle2k(vals['att'] / 2, self.anacris_info['da'])
            Ef = k2energy(Kf)
            
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ki_changed(self):
        """Update Ei and mtt when Ki changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        try:
            self.updating = True
            Ei = k2energy(vals['Ki'])
            mtt = 2 * k2angle(vals['Ki'], self.monocris_info['dm'])
            
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ei_changed(self):
        """Update Ki and mtt when Ei changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        try:
            self.updating = True
            Ki = energy2k(vals['Ei'])
            mtt = 2 * k2angle(Ki, self.monocris_info['dm'])
            
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{vals['Ei']:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = vals['Ei'] - Ef
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Kf_changed(self):
        """Update Ef and att when Kf changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        try:
            self.updating = True
            Ef = k2energy(vals['Kf'])
            att = 2 * k2angle(vals['Kf'], self.anacris_info['da'])
            
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ef_changed(self):
        """Update Kf and att when Ef changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        try:
            self.updating = True
            Kf = energy2k(vals['Ef'])
            att = 2 * k2angle(Kf, self.anacris_info['da'])
            
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(f"{vals['Ef']:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - vals['Ef']
            self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_K_fixed_changed(self):
        """Update all when K fixed mode changes."""
        self.update_all_variables()
        self.update_angles_from_q()
    
    def on_fixed_E_changed(self):
        """Update all when fixed E changes."""
        self.update_all_variables()
        self.update_angles_from_q()
    
    def on_deltaE_changed(self):
        """Update energies when deltaE changes."""
        self.update_all_variables()
        # Keep sample angles in sync with updated deltaE
        self.update_angles_from_q()
    
    def on_stt_changed(self):
        """Handle sample 2theta (stt) change."""
        if self.updating:
            return
        try:
            stt = float(self.window.instrument_dock.stt_edit.text() or 0)
            # Only update if value actually changed (avoid spurious editingFinished signals)
            if not self._field_value_changed('stt', stt):
                return
            # Trigger angle-based updates
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid sample 2θ value")
    
    def on_angles_changed(self):
        """Update Q-space when angles change."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return

        try:
            self.updating = True
            mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            stt = float(self.window.instrument_dock.stt_edit.text() or 0)
            sth = float(self.window.instrument_dock.omega_edit.text() or 0)
            att = float(self.window.instrument_dock.att_edit.text() or 0)
            saz = float(self.window.instrument_dock.chi_edit.text() or 0)

            q_vals, error_flags = self.instrument_state.calculate_q_and_deltaE(
                mtt, stt, sth, saz, att,
                vals['fixed_E'], vals['K_fixed'],
                vals['monocris'], vals['anacris']
            )
            if not error_flags:
                qx, qy, qz, deltaE = q_vals
                self.window.scattering_dock.qx_edit.setText(f"{qx:.4f}".rstrip('0').rstrip('.'))
                self.window.scattering_dock.qy_edit.setText(f"{qy:.4f}".rstrip('0').rstrip('.'))
                self.window.scattering_dock.qz_edit.setText(f"{qz:.4f}".rstrip('0').rstrip('.'))
                self.window.scattering_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
                # Update tracked Q values since we just set them
                self._update_tracked_value('qx', qx)
                self._update_tracked_value('qy', qy)
                self._update_tracked_value('qz', qz)
        except Exception:
            pass
        finally:
            self.updating = False
            # Update HKL based on new Q values, but skip recalculating angles
            # since the angles are the source of truth here
            self.on_Q_changed(skip_angle_update=True)
            # Update energies based on updated deltaE, but don't recalculate mtt/att
            # since crystal angles are part of the input and shouldn't change
            self.update_all_variables(skip_crystal_angles=True)
    
    def on_Q_changed(self, skip_angle_update=False):
        """Update HKL when Q changes.
        
        This is called either:
        1. Directly by user editing Q fields (skip_angle_update=False)
        2. From on_angles_changed when angles are source of truth (skip_angle_update=True)
        """
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        # Check if any Q value actually changed (avoid spurious editingFinished triggers)
        qx_changed = self._field_value_changed('qx', vals['qx'])
        qy_changed = self._field_value_changed('qy', vals['qy'])
        qz_changed = self._field_value_changed('qz', vals['qz'])
        
        if not skip_angle_update and not (qx_changed or qy_changed or qz_changed):
            # No actual change and not called from angles - skip update
            return
        
        try:
            self.updating = True
            H, K, L = self._sample_q_to_hkl(vals['qx'], vals['qy'], vals['qz'], vals)
            self.window.scattering_dock.H_edit.setText(f"{H:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.K_edit.setText(f"{K:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.L_edit.setText(f"{L:.4f}".rstrip('0').rstrip('.'))
            # Update tracked values for HKL since we just set them
            self._update_tracked_value('H', H)
            self._update_tracked_value('K', K)
            self._update_tracked_value('L', L)
        except:
            pass
        finally:
            self.updating = False
            # Update sample/instrument angles based on Q (skip if change originated from angles)
            if not skip_angle_update:
                self.update_angles_from_q()
    
    def on_HKL_changed(self):
        """Update Q when HKL changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        try:
            H = float(self.window.scattering_dock.H_edit.text() or 0)
            K = float(self.window.scattering_dock.K_edit.text() or 0)
            L = float(self.window.scattering_dock.L_edit.text() or 0)
            
            # Check if any HKL value actually changed (avoid spurious editingFinished triggers)
            h_changed = self._field_value_changed('H', H)
            k_changed = self._field_value_changed('K', K)
            l_changed = self._field_value_changed('L', L)
            
            if not (h_changed or k_changed or l_changed):
                # No actual change - skip update
                return
            
            self.updating = True
            qx, qy, qz = self._hkl_to_sample_q(H, K, L, vals)
            self.window.scattering_dock.qx_edit.setText(f"{qx:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.qy_edit.setText(f"{qy:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.qz_edit.setText(f"{qz:.4f}".rstrip('0').rstrip('.'))
            # Update tracked values for Q since we just set them
            self._update_tracked_value('qx', qx)
            self._update_tracked_value('qy', qy)
            self._update_tracked_value('qz', qz)
        except:
            pass
        finally:
            self.updating = False
            # Update sample/instrument angles based on Q
            self.update_angles_from_q()
    
    def on_lattice_changed(self):
        """Update HKL when lattice parameters change. Q stays constant (machine config)."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        try:
            # Q is fixed (machine configuration), recalculate HKL for new lattice
            qx = float(self.window.scattering_dock.qx_edit.text() or 0)
            qy = float(self.window.scattering_dock.qy_edit.text() or 0)
            qz = float(self.window.scattering_dock.qz_edit.text() or 0)
            
            self.updating = True
            # Update UB matrix B when lattice changes
            self.ub_matrix.set_lattice(
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
            H, K, L = self._sample_q_to_hkl(qx, qy, qz, vals)
            self.window.scattering_dock.H_edit.setText(f"{H:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.K_edit.setText(f"{K:.4f}".rstrip('0').rstrip('.'))
            self.window.scattering_dock.L_edit.setText(f"{L:.4f}".rstrip('0').rstrip('.'))
            # Update tracked values for HKL since we just set them
            self._update_tracked_value('H', H)
            self._update_tracked_value('K', K)
            self._update_tracked_value('L', L)
            
            self.print_to_message_center(
                f"Lattice updated: HKL = ({H:.4f}, {K:.4f}, {L:.4f}) for Q = ({qx:.4f}, {qy:.4f}, {qz:.4f}) Å⁻¹"
            )
        except Exception as e:
            self.print_to_message_center(f"Error updating HKL from lattice: {e}")
        finally:
            self.updating = False

    def update_angles_from_q(self):
        """Update instrument/sample angles based on current Q and deltaE."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        try:
            self.updating = True
            angles_array, error_flags = self.instrument_state.calculate_angles(
                vals['qx'], vals['qy'], vals['qz'], vals['deltaE'],
                vals['fixed_E'], vals['K_fixed'],
                vals['monocris'], vals['anacris']
            )
            if not error_flags:
                mtt, stt, sth, saz, att = angles_array
                self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.stt_edit.setText(f"{stt:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.omega_edit.setText(f"{sth:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.chi_edit.setText(f"{saz:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
                # Update tracked values for angles since we just set them
                self._update_tracked_value('omega', sth)
                self._update_tracked_value('chi', saz)
                self._update_tracked_value('stt', stt)
                self._update_tracked_value('mtt', mtt)
                self._update_tracked_value('att', att)
        except Exception:
            pass
        finally:
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def update_monocris_info(self):
        """Update monochromator crystal information."""
        monocris = self.window.instrument_dock.selected_mono_id()
        anacris = self.window.instrument_dock.selected_ana_id()
        self.monocris_info, _ = self.instrument.crystal_info(monocris, anacris)
        self.update_all_variables()

    def update_anacris_info(self):
        """Update analyzer crystal information."""
        monocris = self.window.instrument_dock.selected_mono_id()
        anacris = self.window.instrument_dock.selected_ana_id()
        _, self.anacris_info = self.instrument.crystal_info(monocris, anacris)
        self.update_all_variables()
    
    def on_alignment_offset_changed(self):
        """Handle changes to alignment offsets (kappa=chi offset, psi=omega offset)."""
        if self.updating:
            return
        try:
            kappa = float(self.window.sample_dock.kappa_edit.text() or 0)
            psi = float(self.window.sample_dock.psi_edit.text() or 0)
            self.instrument_state.kappa = kappa
            self.instrument_state.psi = psi
            self.print_to_message_center(f"Alignment offsets updated: κ={kappa}° (chi offset), ψ={psi}° (omega offset)")
        except ValueError:
            self.print_to_message_center("Invalid alignment offset value")
    
    def validate_scan_commands(self):
        """Validate scan commands for errors, typos, and parameter conflicts.
        
        This checks:
        1. Unknown/invalid variable names (typos)
        2. Malformed commands (wrong number of parts, invalid numbers)
        3. Suspicious parameters (e.g., > 1000 scan points)
        4. Conflicts between linked parameters (e.g., qx + H)
        5. Mode conflicts (orientation angles vs momentum/HKL)
        """
        from gui.docks.unified_simulation_dock import (
            LINKED_PARAMETER_GROUPS, MODE_CONFLICTS, VALID_SCAN_VARIABLES
        )
        
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        
        # Clear all previous warnings
        self.window.simulation_dock.clear_all_scan_warnings()
        
        # Validate each command individually
        var1, warning1 = self._validate_single_scan_command(cmd1)
        var2, warning2 = self._validate_single_scan_command(cmd2)
        
        if warning1:
            self.window.simulation_dock.set_scan_command_warning(1, warning1)
        if warning2:
            self.window.simulation_dock.set_scan_command_warning(2, warning2)
        
        # If both commands have variables, check for conflicts
        if var1 and var2:
            conflict = self._check_scan_parameter_conflict(var1, var2)
            if conflict:
                self.window.simulation_dock.set_scan_conflict_warning(conflict)
    
    def _validate_single_scan_command(self, command: str) -> tuple:
        """Validate a single scan command and return (variable_name, warning_message).
        
        Returns:
            tuple: (normalized_variable_name or None, warning_message or None)
        """
        from gui.docks.unified_simulation_dock import VALID_SCAN_VARIABLES
        
        if not command:
            return (None, None)
        
        parts = command.split()
        
        # Check for minimum parts (variable, start, end, step)
        if len(parts) < 4:
            return (None, "Incomplete: needs 'variable start end step'")
        
        if len(parts) > 4:
            return (None, "Too many parts: use 'variable start end step'")
        
        var_name = parts[0]
        var_lower = var_name.lower()
        
        # Handle 2theta as alias for A2
        if var_lower == "2theta":
            var_lower = "a2"
        
        # Check for known variable name
        if var_lower not in VALID_SCAN_VARIABLES:
            # Try to suggest similar names
            suggestions = [v for v in VALID_SCAN_VARIABLES if var_lower in v or v in var_lower]
            if suggestions:
                return (None, f"Unknown variable '{var_name}'. Did you mean: {', '.join(suggestions)}?")
            else:
                return (None, f"Unknown variable '{var_name}'. Valid: qx, qy, qz, H, K, L, deltaE, A1-A4, 2theta, omega, chi, etc.")
        
        # Validate numeric parts
        try:
            start = float(parts[1])
            end = float(parts[2])
            step = float(parts[3])
        except ValueError:
            return (None, "Invalid numbers. Check start, end, and step values.")
        
        # Check for zero step
        if step == 0:
            return (var_lower, "Step size cannot be zero.")
        
        # Check step sign consistency with direction
        if (end > start and step < 0) or (end < start and step > 0):
            return (var_lower, "Step sign doesn't match direction (start → end).")
        
        # Calculate number of points and warn if too many or too few
        import numpy as np
        num_points = int(np.floor(abs(end - start) / abs(step) + 0.5)) + 1
        
        if num_points > 1000:
            return (var_lower, f"⚠ {num_points} points - this may take a very long time!")
        elif num_points > 500:
            return (var_lower, f"Warning: {num_points} scan points. Consider fewer steps.")
        elif num_points == 1:
            return (var_lower, f"⚠ Only 1 scan point! Step ({step}) larger than range ({start} to {end}).")
        elif num_points <= 0:
            return (var_lower, "Invalid range: no points would be generated.")
        
        # Normalize variable name
        normalized = self.normalize_scan_variable(var_name)
        return (normalized.lower() if normalized else var_lower, None)
    
    def _check_scan_parameter_conflict(self, var1: str, var2: str) -> str:
        """Check if two scan variables conflict with each other.
        
        Args:
            var1: First variable name (lowercase)
            var2: Second variable name (lowercase)
            
        Returns:
            str: Conflict warning message, or empty string if no conflict
        """
        from gui.docks.unified_simulation_dock import LINKED_PARAMETER_GROUPS, MODE_CONFLICTS
        
        # Normalize to lowercase for comparison
        v1 = var1.lower()
        v2 = var2.lower()
        
        # Same variable - definitely a conflict
        if v1 == v2:
            return f"⚠ Both commands scan '{v1}' - use different parameters"
        
        q_vars = {"qx", "qy", "qz"}
        hkl_vars = {"h", "k", "l"}
        if (v1 in q_vars and v2 in hkl_vars) or (v1 in hkl_vars and v2 in q_vars):
            return "Conflict: Q and HKL scans describe the same target momentum under the current sample mount"

        # Check linked parameter groups (parameters that control the same thing)
        for group_name, group_vars in LINKED_PARAMETER_GROUPS.items():
            if v1 in group_vars and v2 in group_vars:
                return f"⚠ Conflict: '{var1}' and '{var2}' are linked ({group_name.replace('_', ' ')})"
        
        # Check mode conflicts (orientation vs momentum/HKL)
        for conflict_name, (set1, set2) in MODE_CONFLICTS.items():
            if (v1 in set1 and v2 in set2) or (v1 in set2 and v2 in set1):
                return f"⚠ Conflict: orientation angle vs Q/HKL - angles will override calculated positions"
        
        return ""
    
    def _get_current_value_for_variable(self, var_name: str, vals: dict, scan_point_template: list) -> float:
        """Get the current value for a scan variable to use as relative base.
        
        Args:
            var_name: Normalized variable name (e.g., 'qx', 'H', 'omega')
            vals: Dictionary of GUI values
            scan_point_template: Template array with current values
            
        Returns:
            float: Current value for the variable
        """
        var = var_name.lower() if var_name else ""
        
        # Q-space variables
        if var == 'qx':
            return vals.get('qx', 0)
        elif var == 'qy':
            return vals.get('qy', 0)
        elif var == 'qz':
            return vals.get('qz', 0)
        elif var == 'deltae':
            return vals.get('deltaE', 0)
        # HKL variables
        elif var == 'h':
            return vals.get('H', 0)
        elif var == 'k':
            return vals.get('K', 0)
        elif var == 'l':
            return vals.get('L', 0)
        # Instrument angles (A3 is calculated sample angle; omega is an offset scan)
        elif var == 'a1':
            return vals.get('mtt', 0)
        elif var == 'a2' or var == '2theta':
            return vals.get('stt', 0)
        elif var == 'a3':
            return vals.get('omega', 0)
        elif var == 'a4':
            return vals.get('att', 0)
        # Sample orientation (chi, kappa, psi)
        elif var == 'chi':
            return scan_point_template[8] if len(scan_point_template) > 8 else 0
        elif var == 'kappa':
            return scan_point_template[9] if len(scan_point_template) > 9 else 0
        elif var == 'psi' or var == 'omega':
            return scan_point_template[10] if len(scan_point_template) > 10 else 0
        # Crystal bending
        elif var == 'rhm':
            return vals.get('rhm', 0)
        elif var == 'rvm':
            return vals.get('rvm', 0)
        elif var == 'rha':
            return vals.get('rha', 0)
        elif var == 'rva':
            return vals.get('rva', 0.8)
        
        return 0
    
    def _trigger_scan_update(self):
        """Trigger a debounced update of scan estimates."""
        self._scan_update_timer.start()
    
    def _update_scan_estimates(self):
        """Update all scan time estimates based on current settings.
        
        This is called after a debounce delay when scan commands or neutron count change.
        It updates:
        1. Time per point estimate (next to neutron count)
        2. Point count breakdown (below scan commands)
        3. Total time estimate (below point count)
        """
        import numpy as np
        
        # Get current values
        try:
            num_neutrons = self.window.simulation_dock.get_number_neutrons()
        except ValueError:
            num_neutrons = 1000000
        
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        
        # Get instrument name
        instrument_name = self.instrument.id
        
        # Update time per point estimate
        _, run_time_per_point = self.runtime_tracker.get_estimates(instrument_name, num_neutrons)
        if run_time_per_point is not None:
            time_str = f"~{RuntimeTracker.format_time(run_time_per_point)}/point"
            self.window.simulation_dock.update_time_per_point(time_str)
        else:
            self.window.simulation_dock.update_time_per_point("No timing data")
        
        # Calculate point counts
        count1, count2 = 0, 0
        valid_count = 0
        invalid_count = 0
        single_point_invalid = False
        
        if cmd1:
            try:
                _, array1 = parse_scan_steps(cmd1)
                count1 = len(array1)
            except Exception:
                count1 = 0
        
        if cmd2:
            try:
                _, array2 = parse_scan_steps(cmd2)
                count2 = len(array2)
            except Exception:
                count2 = 0
        
        # Calculate total points for determining if precalculation should be skipped
        total_potential_points = count1 * count2 if (count1 > 0 and count2 > 0) else max(count1, count2)
        
        # If >1000 points, defer validation to avoid GUI hang
        if total_potential_points > 1000:
            self.print_to_message_center(f"⚠ {total_potential_points} scan points - validation deferred until simulation starts")
            self.window.simulation_dock.update_point_count_display_deferred(count1, count2)
            # Still show time estimate based on total points (assume all valid for estimate)
            total_time, compile_time, _ = self.runtime_tracker.estimate_total_time(
                instrument_name, total_potential_points, num_neutrons
            )
            if total_time is not None:
                total_str = RuntimeTracker.format_time(total_time)
                compile_str = RuntimeTracker.format_time(compile_time)
                self.window.simulation_dock.update_total_time_estimate(total_str, compile_str)
            else:
                self.window.simulation_dock.update_total_time_estimate("")
            return
        
        # Calculate valid/invalid counts
        if count1 > 0 or count2 > 0:
            valid_count, invalid_count = self._count_valid_scan_points(cmd1, cmd2)
        else:
            # Single point mode - check if current position is valid
            valid, _ = self._check_current_point_validity()
            if valid:
                valid_count = 1
                invalid_count = 0
            else:
                valid_count = 0
                invalid_count = 1
                single_point_invalid = True
        
        total_points = valid_count + invalid_count
        all_invalid = (valid_count == 0 and total_points > 0)
        
        # Update point count display
        self.window.simulation_dock.update_point_count_display(
            count1, count2, valid_count, invalid_count, all_invalid or single_point_invalid
        )
        
        # Update total time estimate
        total_time, compile_time, _ = self.runtime_tracker.estimate_total_time(
            instrument_name, valid_count, num_neutrons
        )
        if total_time is not None:
            total_str = RuntimeTracker.format_time(total_time)
            compile_str = RuntimeTracker.format_time(compile_time)
            self.window.simulation_dock.update_total_time_estimate(total_str, compile_str)
        else:
            self.window.simulation_dock.update_total_time_estimate("")
    
    def _count_valid_scan_points(self, cmd1: str, cmd2: str) -> tuple:
        """Count valid and invalid scan points for given scan commands.
        
        Args:
            cmd1: First scan command
            cmd2: Second scan command (may be empty)
            
        Returns:
            tuple: (valid_count, invalid_count)
        """
        import numpy as np
        
        # Get current GUI values for validation
        vals = self.get_gui_values()
        
        # Build scan point template
        scan_point_template = [
            vals['qx'], vals['qy'], vals['qz'], vals['deltaE'],
            vals['rhm'], vals['rvm'], vals['rha'], vals.get('rva', 0.8),
            0, vals.get('kappa', 0), vals.get('psi', 0),
            vals.get('H', 0), vals.get('K', 0), vals.get('L', 0)
        ]
        
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltae': 3,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7,
            'chi': 8, 'kappa': 9, 'psi': 10, 'omega': 10,
            'h': 11, 'k': 12, 'l': 13,
            'a1': 0, 'a2': 1, 'a3': 2, 'a4': 3,  # Angle mode
            '2theta': 1,
        }
        
        # Determine scan mode
        scan_mode = self._determine_scan_mode(cmd1, cmd2)
        
        # Create a throwaway instrument state for validation - use GUI values, not
        # the live state (it may not be updated until run_simulation is called)
        check_state = self.instrument.default_state()
        check_state.monocris = vals.get('monocris', self.descriptor.mono_crystals[0].id)
        check_state.anacris = vals.get('anacris', self.descriptor.ana_crystals[0].id)
        check_state.K_fixed = vals.get('K_fixed', 'Kf Fixed')
        check_state.fixed_E = vals.get('fixed_E', 14.7)
        check_state.sample_mount = self._build_sample_mount(vals)
        
        valid_count = 0
        invalid_count = 0
        
        try:
            variable_name1, array_values1 = parse_scan_steps(cmd1) if cmd1 else (None, [])
            variable_name2, array_values2 = parse_scan_steps(cmd2) if cmd2 else (None, [])
            
            if variable_name1:
                variable_name1 = self.normalize_scan_variable(variable_name1).lower()
            if variable_name2:
                variable_name2 = self.normalize_scan_variable(variable_name2).lower()
            
            # 1D scan
            if cmd1 and not cmd2:
                for value1 in array_values1:
                    scan_point = scan_point_template[:]
                    if variable_name1 in variable_to_index:
                        scan_point[variable_to_index[variable_name1]] = value1
                    
                    valid = self._validate_scan_point(scan_point, scan_mode, vals, check_state)
                    if valid:
                        valid_count += 1
                    else:
                        invalid_count += 1
            
            # 2D scan
            elif cmd1 and cmd2:
                for value2 in array_values2:
                    for value1 in array_values1:
                        scan_point = scan_point_template[:]
                        if variable_name1 in variable_to_index:
                            scan_point[variable_to_index[variable_name1]] = value1
                        if variable_name2 in variable_to_index:
                            scan_point[variable_to_index[variable_name2]] = value2
                        
                        valid = self._validate_scan_point(scan_point, scan_mode, vals, check_state)
                        if valid:
                            valid_count += 1
                        else:
                            invalid_count += 1
        except Exception as e:
            # If parsing fails, return 0 valid points
            return (0, 0)
        
        return (valid_count, invalid_count)
    
    def _validate_scan_point(self, scan_point: list, scan_mode: str, vals: dict, check_state) -> bool:
        """Validate a single scan point.
        
        Args:
            scan_point: List of scan parameters
            scan_mode: One of 'momentum', 'rlu', 'angle', 'orientation'
            vals: GUI values dictionary
            check_state: throwaway instrument state (configured with GUI values)
            
        Returns:
            True if point is valid, False otherwise
        """
        try:
            if scan_mode == "momentum":
                qx, qy, qz, deltaE = scan_point[:4]
                _, error_flags = check_state.calculate_angles(
                    qx, qy, qz, deltaE, check_state.fixed_E, check_state.K_fixed,
                    check_state.monocris, check_state.anacris
                )
                return not error_flags
            elif scan_mode == "rlu":
                H, K, L = scan_point[11], scan_point[12], scan_point[13]
                deltaE = scan_point[3]
                qx, qy, qz = component_q_to_instrument_q(
                    check_state.sample_mount.hkl_to_q(H, K, L)
                )
                _, error_flags = check_state.calculate_angles(
                    qx, qy, qz, deltaE, check_state.fixed_E, check_state.K_fixed,
                    check_state.monocris, check_state.anacris
                )
                return not error_flags
            else:
                # Angle mode - always valid
                return True
        except Exception:
            return False
    
    def _determine_scan_mode(self, cmd1: str, cmd2: str) -> str:
        """Determine the scan mode based on scan command variables.
        
        Args:
            cmd1: First scan command
            cmd2: Second scan command
            
        Returns:
            str: One of 'momentum', 'rlu', 'angle', 'orientation'
        """
        momentum_vars = {'qx', 'qy', 'qz', 'deltae'}
        rlu_vars = {'h', 'k', 'l'}
        angle_vars = {'a1', 'a2', 'a3', 'a4', '2theta'}
        orientation_vars = {'omega', 'chi', 'psi', 'kappa'}
        
        vars_used = set()
        for cmd in [cmd1, cmd2]:
            if cmd:
                parts = cmd.split()
                if parts:
                    vars_used.add(parts[0].lower())
        
        if vars_used & rlu_vars:
            return "rlu"
        elif vars_used & momentum_vars:
            return "momentum"
        elif vars_used & angle_vars:
            return "angle"
        elif vars_used & orientation_vars:
            return "orientation"
        else:
            # Default to rlu mode if no specific scan variables
            return "rlu"
    
    def _check_current_point_validity(self) -> tuple:
        """Check if the current single point (no scan) is valid.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            vals = self.get_gui_values()
            if not vals:
                return (False, "Could not get GUI values")
            
            # Use GUI values directly, not the live state (may not be updated)
            check_state = self.instrument.default_state()
            check_state.monocris = vals.get('monocris', self.descriptor.mono_crystals[0].id)
            check_state.anacris = vals.get('anacris', self.descriptor.ana_crystals[0].id)
            check_state.K_fixed = vals.get('K_fixed', 'Kf Fixed')
            check_state.fixed_E = vals.get('fixed_E', 14.7)
            
            _, error_flags = check_state.calculate_angles(
                vals['qx'], vals['qy'], vals['qz'], vals['deltaE'],
                check_state.fixed_E, check_state.K_fixed,
                check_state.monocris, check_state.anacris
            )
            return (not error_flags, error_flags if error_flags else "")
        except Exception as e:
            return (False, str(e))

    def on_omega_changed(self):
        """Handle omega (ω) change - sample in-plane rotation."""
        if self.updating:
            return
        try:
            omega = float(self.window.instrument_dock.omega_edit.text() or 0)
            # Only update if value actually changed (avoid spurious editingFinished signals)
            if not self._field_value_changed('omega', omega):
                return
            self.instrument_state.omega = omega
            self.print_to_message_center(f"Sample ω updated: {omega}°")
            # Trigger angle-based updates
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid omega value")
    
    def on_chi_changed(self):
        """Handle chi (χ) change - sample out-of-plane tilt."""
        if self.updating:
            return
        try:
            chi = float(self.window.instrument_dock.chi_edit.text() or 0)
            # Only update if value actually changed (avoid spurious editingFinished signals)
            if not self._field_value_changed('chi', chi):
                return
            self.instrument_state.saz = chi
            self.print_to_message_center(f"Sample χ updated: {chi}° (out-of-plane)")
            # Calculated chi/saz affects qz - trigger recalculation
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid chi value")
    
    def on_load_misalignment_hash(self):
        """Handle loading misalignment from hash - apply hidden values to instrument."""
        if self.window.misalignment_dock.has_misalignment():
            mis_omega, mis_chi = self.window.misalignment_dock.get_loaded_misalignment()
            self.instrument_state.set_misalignment(mis_omega=mis_omega, mis_chi=mis_chi)
            self.print_to_message_center("Hidden misalignment loaded and applied to instrument")
    
    def on_clear_misalignment(self):
        """Handle clearing misalignment - reset hidden values on instrument."""
        self.instrument_state.set_misalignment(mis_omega=0, mis_chi=0)
        self.print_to_message_center("Misalignment cleared")
        # Also clear any stored hash in the sample dock so it won't be reloaded
        try:
            if hasattr(self.window, 'sample_dock') and hasattr(self.window.sample_dock, 'load_hash_edit'):
                self.window.sample_dock.load_hash_edit.clear()
            if hasattr(self.window.sample_dock, '_loaded_misalignment'):
                self.window.misalignment_dock._loaded_misalignment = None
            if hasattr(self.window.misalignment_dock, 'misalignment_status_label'):
                self.window.misalignment_dock.misalignment_status_label.setText("No misalignment loaded")
                self.window.misalignment_dock.misalignment_status_label.setStyleSheet("color: gray;")
            if hasattr(self.window.misalignment_dock, 'check_alignment_button'):
                self.window.misalignment_dock.check_alignment_button.setEnabled(False)
        except Exception:
            pass
    
    def on_check_alignment(self):
        """Check user's alignment against hidden misalignment and update feedback."""
        try:
            # psi_edit is the in-plane offset (corrects omega misalignment)
            # kappa_edit is the out-of-plane offset (corrects chi misalignment)
            psi = float(self.window.sample_dock.psi_edit.text() or 0)
            kappa = float(self.window.sample_dock.kappa_edit.text() or 0)
            # update_alignment_feedback(user_psi, user_kappa)
            self.window.misalignment_dock.update_alignment_feedback(psi, kappa)
        except ValueError:
            self.print_to_message_center("Invalid sample orientation values for alignment check")

    # ===== UB Matrix Controller Methods =====

    def on_calculate_ub(self):
        """Calculate UB matrix from observed peaks in the UB dock."""
        try:
            peaks_data = self.window.ub_matrix_dock.get_all_peak_data()
            # Build ObservedPeak list
            self.ub_matrix.peaks = []
            for pd in peaks_data:
                if pd is None:
                    continue
                peak = ObservedPeak(
                    hkl=pd['hkl'],
                    angles=pd['angles'],
                    ki=pd['ki'],
                    kf=pd['kf'],
                    locked=pd.get('locked', False),
                )
                self.ub_matrix.peaks.append(peak)

            # Sync lattice from GUI
            vals = self.get_gui_values()
            if vals:
                self.ub_matrix.set_lattice(
                    vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                    vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
                )

            U = self.ub_matrix.calculate_U_from_peaks()
            self._update_ub_display()
            self.print_to_message_center(
                f"UB matrix calculated from {len([p for p in self.ub_matrix.peaks if p.is_valid])} peaks"
            )
            # Refresh HKL/angles for current Q
            self.on_Q_changed()
        except Exception as e:
            self.print_to_message_center(f"UB calculation failed: {e}")

    def on_refine_lattice(self):
        """Refine lattice parameters from observed peaks."""
        try:
            peaks_data = self.window.ub_matrix_dock.get_all_peak_data()
            self.ub_matrix.peaks = []
            for pd in peaks_data:
                if pd is None:
                    continue
                peak = ObservedPeak(
                    hkl=pd['hkl'],
                    angles=pd['angles'],
                    ki=pd['ki'],
                    kf=pd['kf'],
                    locked=pd.get('locked', False),
                )
                self.ub_matrix.peaks.append(peak)

            result = self.ub_matrix.refine_lattice()
            refined = result['lattice']

            # Show refinement dialog
            from gui.docks.ub_matrix_dock import LatticeRefinementDialog
            vals = self.get_gui_values()
            current = (
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
            )
            dlg = LatticeRefinementDialog(current, refined, result['residuals'], result['rms_error'], self.window)
            if dlg.exec():
                # Apply refined lattice to sample dock
                a, b, c, alpha, beta, gamma = refined
                self.window.sample_dock.lattice_a_edit.setText(f"{a:.4f}".rstrip('0').rstrip('.'))
                self.window.sample_dock.lattice_b_edit.setText(f"{b:.4f}".rstrip('0').rstrip('.'))
                self.window.sample_dock.lattice_c_edit.setText(f"{c:.4f}".rstrip('0').rstrip('.'))
                self.window.sample_dock.lattice_alpha_edit.setText(f"{alpha:.4f}".rstrip('0').rstrip('.'))
                self.window.sample_dock.lattice_beta_edit.setText(f"{beta:.4f}".rstrip('0').rstrip('.'))
                self.window.sample_dock.lattice_gamma_edit.setText(f"{gamma:.4f}".rstrip('0').rstrip('.'))
                self.on_lattice_changed()
                self.print_to_message_center(
                    f"Refined lattice applied: a={a:.4f}, b={b:.4f}, c={c:.4f}, "
                    f"α={alpha:.2f}, β={beta:.2f}, γ={gamma:.2f}"
                )
            else:
                self.print_to_message_center("Lattice refinement not applied")
        except Exception as e:
            self.print_to_message_center(f"Lattice refinement failed: {e}")

    def on_reset_ub(self):
        """Reset UB matrix to identity (clear orientation)."""
        self.ub_matrix.reset_U()
        self._update_ub_display()
        self.print_to_message_center("UB matrix reset to identity")
        # Refresh HKL from current Q using direct method
        self.on_Q_changed()

    def on_ub_matrix_edited(self, is_non_identity: bool):
        """Handle manual editing of UB matrix in the dock."""
        try:
            UB = self.window.ub_matrix_dock.get_ub_matrix_from_fields()
            self.ub_matrix.set_UB(UB)
            self._update_ub_display()
            self.print_to_message_center("UB matrix updated from manual edit")
            self.on_Q_changed()
        except Exception as e:
            self.print_to_message_center(f"Invalid UB matrix: {e}")

    def on_take_peak_position(self, peak_index: int):
        """Fill peak angle fields from current instrument position."""
        vals = self.get_gui_values()
        if not vals:
            return
        pw = self.window.ub_matrix_dock.get_peak_widget(peak_index)
        if pw:
            pw.set_angles_from_position(
                vals['omega'], vals['chi'], vals['stt'],
                vals['Ki'], vals['Kf'],
            )
            self.print_to_message_center(
                f"Peak {peak_index + 1}: position taken "
                f"(ω={vals['omega']:.2f}°, χ={vals['chi']:.2f}°, 2θ={vals['stt']:.2f}°, "
                f"ki={vals['Ki']:.4f}, kf={vals['Kf']:.4f})"
            )

    def _on_peak_added(self):
        """Connect signals for newly added peak widget."""
        self._reconnect_peak_signals()

    def _on_peak_removed(self, index: int):
        """Handle peak removal."""
        self.window.ub_matrix_dock.remove_peak_entry(index)
        self._reconnect_peak_signals()

    def _reconnect_peak_signals(self):
        """Reconnect take_position and remove signals for all peak widgets."""
        for pw in self.window.ub_matrix_dock._peak_widgets:
            try:
                pw.take_position_requested.disconnect()
            except RuntimeError:
                pass
            try:
                pw.remove_requested.disconnect()
            except RuntimeError:
                pass
            pw.take_position_requested.connect(self.on_take_peak_position)
            pw.remove_requested.connect(self._on_peak_removed)

    def _update_ub_display(self):
        """Update UB matrix display and scattering plane info in the dock."""
        self.window.ub_matrix_dock.update_ub_display(
            self.ub_matrix.UB, self.ub_matrix.is_identity
        )
        try:
            plane_info = self.ub_matrix.get_plane_info()
            self.window.ub_matrix_dock.update_plane_info(plane_info)
        except Exception:
            pass
        # Update sample dock indicator
        if hasattr(self.window, 'sample_dock'):
            self.window.sample_dock.update_ub_indicator(not self.ub_matrix.is_identity)
        # Refresh angles from Q since UB affects the mapping
        self.update_angles_from_q()

    # ===== UB Training Methods =====

    def on_generate_training(self):
        """Generate a training exercise hash with hidden orientation + misalignment."""
        try:
            max_ori = self.window.ub_matrix_dock.max_ori_spin.value()
            max_mis = self.window.ub_matrix_dock.max_mis_spin.value()
            include_ori = self.window.ub_matrix_dock.include_orientation_check.isChecked()
            include_mis = self.window.ub_matrix_dock.include_misalignment_check.isChecked()

            hash_str = generate_training_exercise(
                max_ori_angle=max_ori,
                max_mis_angle=max_mis,
                include_orientation=include_ori,
                include_misalignment=include_mis,
            )
            self.window.ub_matrix_dock.training_hash_display.setText(hash_str)
            self.print_to_message_center("Training exercise generated - share the hash with students")
        except Exception as e:
            self.print_to_message_center(f"Failed to generate training: {e}")

    def on_load_training(self):
        """Load a training exercise from hash, apply hidden orientation + misalignment."""
        try:
            hash_str = self.window.ub_matrix_dock.load_hash_edit.text().strip()
            if not hash_str:
                self.print_to_message_center("No training hash entered")
                return

            U, mis_omega, mis_chi = decode_training(hash_str)

            # Store the training exercise
            self.window.ub_matrix_dock._loaded_training = (U, mis_omega, mis_chi)

            # Apply hidden orientation to UB matrix
            self.ub_matrix.set_U(U)
            # Apply hidden misalignment to instrument
            self.instrument_state.set_misalignment(mis_omega=mis_omega, mis_chi=mis_chi)

            # Update displays
            self._update_ub_display()
            self.window.ub_matrix_dock.update_training_status(True)

            self.print_to_message_center("Training exercise loaded - hidden orientation and misalignment applied")
        except ValueError as e:
            self.print_to_message_center(f"Invalid training hash: {e}")
        except Exception as e:
            self.print_to_message_center(f"Failed to load training: {e}")

    def on_clear_training(self):
        """Clear training exercise, reset orientation and misalignment."""
        self.window.ub_matrix_dock._loaded_training = None
        self.ub_matrix.reset_U()
        self.instrument_state.set_misalignment(mis_omega=0, mis_chi=0)
        self._update_ub_display()
        self.window.ub_matrix_dock.update_training_status(False)
        self.print_to_message_center("Training exercise cleared")

    def on_check_training(self):
        """Check student alignment against loaded training exercise."""
        try:
            training = self.window.ub_matrix_dock._loaded_training
            if training is None:
                self.print_to_message_center("No training exercise loaded")
                return

            teacher_U, mis_omega, mis_chi = training

            # Get student's current state
            student_U = self.ub_matrix.U
            vals = self.get_gui_values()
            student_psi = vals.get('psi', 0) if vals else 0
            student_kappa = vals.get('kappa', 0) if vals else 0

            results = check_training_quality(
                student_U, teacher_U,
                student_psi, student_kappa,
                mis_omega, mis_chi,
            )
            self.window.ub_matrix_dock.update_check_results(results)
            self.print_to_message_center(
                f"Alignment check: orientation {results['orientation']}, "
                f"in-plane {results['in_plane']}, out-of-plane {results['out_of_plane']}"
            )
        except Exception as e:
            self.print_to_message_center(f"Training check failed: {e}")

    def configure_diagnostics(self):
        """Open diagnostics configuration window."""
        dialog = DiagnosticConfigDialog(
            self.window, self.diagnostic_settings, monitors=self.descriptor.monitors
        )
        if dialog.exec():
            # User clicked Save and Close
            self.diagnostic_settings = dialog.get_settings()
            # Update the live instrument state with new settings
            self.instrument_state.update_diagnostic_settings(self.diagnostic_settings)
            # Save parameters to persist the settings
            self.save_parameters()
            self.print_to_message_center("Diagnostic settings saved")
        else:
            self.print_to_message_center("Diagnostic configuration cancelled")
    
    def configure_sample(self):
        """Open sample configuration window."""
        # TODO: Implement sample configuration dialog
        self.print_to_message_center("Sample configuration window not yet implemented")
    
    def clear_runtime_data(self):
        """Clear cached runtime data with confirmation dialog."""
        from PySide6.QtWidgets import QMessageBox
        
        # Get current record count for the message
        record_count = self.runtime_tracker.get_record_count(self.instrument.id)
        
        reply = QMessageBox.question(
            self.window,
            "Clear Runtime Data",
            f"Are you sure you want to clear all cached runtime data?\n\n"
            f"This will delete {record_count} scan timing records used to estimate\n"
            f"scan durations. New estimates will be generated as you run more scans.\n\n"
            f"Use this if time estimates seem incorrect.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            cleared = self.runtime_tracker.clear_records()
            self.print_to_message_center(f"Cleared {cleared} runtime records. Time estimates will be recalculated from new scans.")
            # Clear displayed estimates
            self.window.simulation_dock.update_total_time_estimate("")
        else:
            self.print_to_message_center("Runtime data clearing cancelled.")
    
    def load_and_display_data(self):
        """Load and display existing data in the display dock."""
        folder = self.window.data_control_dock.load_folder_edit.text()
        if folder and os.path.exists(folder):
            self.print_to_message_center(f"Loading data from: {folder}")
            try:
                # Read parameters to get scan commands
                scan_parameters = read_parameters_from_file(folder)
                scan_cmd1 = scan_parameters.get('scan_command1', '')
                scan_cmd2 = scan_parameters.get('scan_command2', '')
                
                # Build metadata for info panel
                metadata = self._build_scan_metadata_from_parameters(scan_parameters)
                
                # Load data into display dock
                self.window.display_dock.load_existing_data(folder, scan_cmd1, scan_cmd2, metadata)
                self.print_to_message_center("Data loaded into display dock")
            except Exception as e:
                self.print_to_message_center(f"Error loading data: {str(e)}")
        else:
            self.print_to_message_center("Invalid folder path for loading data")
    
    def _build_scan_metadata_from_parameters(self, params):
        """Build scan metadata dict from loaded parameters."""
        metadata = {}
        
        # Number of neutrons
        if 'number_neutrons' in params:
            try:
                metadata['number_neutrons'] = int(float(params['number_neutrons']))
            except (ValueError, TypeError):
                pass
        
        # Ki/Kf fixed mode
        if 'K_fixed' in params:
            metadata['K_fixed'] = params['K_fixed']
        
        # Fixed E
        if 'fixed_E' in params:
            try:
                metadata['fixed_E'] = float(params['fixed_E'])
            except (ValueError, TypeError):
                pass
        
        # Collimations
        for key in ['alpha_1', 'alpha_2', 'alpha_3', 'alpha_4']:
            if key in params:
                metadata[key] = params[key]
        
        # Crystals
        if 'monocris' in params:
            metadata['monocris'] = params['monocris']
        if 'anacris' in params:
            metadata['anacris'] = params['anacris']
        
        # Alignment offsets
        for key in ['kappa', 'psi']:
            if key in params:
                try:
                    metadata[key] = float(params[key])
                except (ValueError, TypeError):
                    pass
        
        # Q-space coordinates
        for key in ['qx', 'qy', 'qz']:
            if key in params:
                try:
                    metadata[key] = float(params[key])
                except (ValueError, TypeError):
                    pass
        
        # HKL coordinates
        for key in ['H', 'K', 'L']:
            if key in params:
                try:
                    metadata[key] = float(params[key])
                except (ValueError, TypeError):
                    pass
        
        # Energy transfer
        if 'deltaE' in params:
            try:
                metadata['deltaE'] = float(params['deltaE'])
            except (ValueError, TypeError):
                pass
        
        # NMO and velocity selector
        if 'NMO_installed' in params:
            metadata['NMO_installed'] = params['NMO_installed']
        if 'V_selector_installed' in params:
            metadata['V_selector_installed'] = params.get('V_selector_installed', False)
        
        return metadata

    # -------- persistence helpers (descriptor-driven categories)

    @staticmethod
    def _saved_crystal_id(saved, crystals):
        """Resolve a saved crystal id, falling back to the instrument default."""
        for spec in crystals:
            if saved == spec.id:
                return spec.id
        return crystals[0].id

    @staticmethod
    def _saved_module_values(parameters):
        return parameters.get("modules", {})

    @staticmethod
    def _saved_collimation_values(parameters):
        # JSON round-trips multi-select sets as lists
        return {
            slot_id: set(value) if isinstance(value, list) else value
            for slot_id, value in parameters.get("collimation", {}).items()
        }

    @staticmethod
    def _saved_slit_values(parameters):
        # JSON round-trips (width, height) tuples as lists
        return {
            slit_id: tuple(value) if isinstance(value, list) else value
            for slit_id, value in parameters.get("slits_mm", {}).items()
        }

    def _slit_values_for_save(self):
        try:
            slit_values = self.window.instrument_dock.slit_values_mm()
        except ValueError:
            # Malformed text in a slit field; persist nothing so load falls
            # back to the descriptor defaults.
            return {}
        return {
            slit_id: list(value) if isinstance(value, tuple) else value
            for slit_id, value in slit_values.items()
        }

    def save_parameters(self):
        """Save all parameters to JSON file."""
        parameters = {
            "mtt_var": self.window.instrument_dock.mtt_edit.text(),
            "stt_var": self.window.instrument_dock.stt_edit.text(),
            "omega_var": self.window.instrument_dock.omega_edit.text(),
            "chi_var": self.window.instrument_dock.chi_edit.text(),
            "att_var": self.window.instrument_dock.att_edit.text(),
            "Ki_var": self.window.instrument_dock.Ki_edit.text(),
            "Kf_var": self.window.instrument_dock.Kf_edit.text(),
            "Ei_var": self.window.instrument_dock.Ei_edit.text(),
            "Ef_var": self.window.instrument_dock.Ef_edit.text(),
            "number_neutrons_var": self.window.simulation_dock.get_number_neutrons(),
            "K_fixed_var": self.window.scattering_dock.K_fixed_combo.currentText(),
            "source_type_var": self.window.instrument_dock.selected_source_id(),
            "source_dE_var": self.window.instrument_dock.source_dE_edit.text(),
            "modules": self.window.instrument_dock.module_values(),
            "rhm_var": self.window.instrument_dock.rhm_edit.text(),
            "rvm_var": self.window.instrument_dock.rvm_edit.text(),
            "rha_var": self.window.instrument_dock.rha_edit.text(),
            "rhm_ideal_locked": self.is_bending_locked("rhm"),
            "rvm_ideal_locked": self.is_bending_locked("rvm"),
            "rha_ideal_locked": self.is_bending_locked("rha"),
            "fixed_E_var": self.window.scattering_dock.fixed_E_edit.text(),
            "qx_var": self.window.scattering_dock.qx_edit.text(),
            "qy_var": self.window.scattering_dock.qy_edit.text(),
            "qz_var": self.window.scattering_dock.qz_edit.text(),
            # HKL values
            "H_var": self.window.scattering_dock.H_edit.text(),
            "K_var": self.window.scattering_dock.K_edit.text(),
            "L_var": self.window.scattering_dock.L_edit.text(),
            "deltaE_var": self.window.scattering_dock.deltaE_edit.text(),
            "monocris_var": self.window.instrument_dock.selected_mono_id(),
            "anacris_var": self.window.instrument_dock.selected_ana_id(),
            "collimation": {
                slot_id: sorted(value) if isinstance(value, set) else value
                for slot_id, value in
                self.window.instrument_dock.collimation_values().items()
            },
            # Slit apertures (stored in mm)
            "slits_mm": self._slit_values_for_save(),
            "diagnostic_mode_var": self.window.simulation_dock.diagnostic_mode_check.isChecked(),
            "lattice_a_var": self.window.sample_dock.lattice_a_edit.text(),
            "lattice_b_var": self.window.sample_dock.lattice_b_edit.text(),
            "lattice_c_var": self.window.sample_dock.lattice_c_edit.text(),
            "lattice_alpha_var": self.window.sample_dock.lattice_alpha_edit.text(),
            "lattice_beta_var": self.window.sample_dock.lattice_beta_edit.text(),
            "lattice_gamma_var": self.window.sample_dock.lattice_gamma_edit.text(),
            # Sample alignment offsets (kappa and psi)
            "kappa_var": self.window.sample_dock.kappa_edit.text(),
            "psi_offset_var": self.window.sample_dock.psi_edit.text(),
            # Misalignment hash only (keeps values hidden from students)
            "misalignment_hash_var": self.window.misalignment_dock.load_hash_edit.text(),
            "scan_command_var1": self.window.simulation_dock.scan_command_1_edit.text(),
            "scan_command_var2": self.window.simulation_dock.scan_command_2_edit.text(),
            "save_folder_var": self.window.data_control_dock.save_folder_edit.text(),
            "load_folder_var": self.window.data_control_dock.load_folder_edit.text(),
            "diagnostic_settings": self.diagnostic_settings,
            "current_sample_settings": self.current_sample_settings,
            "space_group_number_var": self.window.sample_dock.spacegroup_combo.currentData() if hasattr(self.window.sample_dock, 'spacegroup_combo') else None,
            # UB matrix state
            "ub_matrix_state": self.ub_matrix.to_dict(),
            "ub_training_hash": self.window.ub_matrix_dock.load_hash_edit.text() if hasattr(self.window, 'ub_matrix_dock') else "",
        }
        # Namespace by instrument id with a schema version (design record §9,
        # §16.8): {"<instrument_id>": {"_schema": 1, ...}}. Other instruments'
        # blocks in the file are preserved; anything else is discarded.
        parameters["_schema"] = self.PARAMETERS_SCHEMA_VERSION
        document = {}
        if os.path.exists("config/parameters.json"):
            try:
                with open("config/parameters.json", "r") as file:
                    existing = json.load(file)
                if isinstance(existing, dict):
                    document = {
                        block_id: block for block_id, block in existing.items()
                        if isinstance(block, dict) and "_schema" in block
                    }
            except (json.JSONDecodeError, OSError):
                document = {}
        document[self.instrument.id] = parameters
        # Ensure config directory exists
        os.makedirs("config", exist_ok=True)
        with open("config/parameters.json", "w") as file:
            json.dump(document, file)
        self.print_to_message_center("Parameters saved successfully")

    PARAMETERS_SCHEMA_VERSION = 1

    def _parameters_block(self, document):
        """This instrument's block from ``{"<id>": {"_schema": N, ...}}``.

        Missing/malformed block -> empty dict (every field read falls back to
        its default).
        """
        if not isinstance(document, dict):
            return {}
        block = document.get(self.instrument.id, {})
        return block if isinstance(block, dict) else {}

    @staticmethod
    def _can_reuse_binary(cache, fingerprint, diagnostic_mode):
        """Whether the previous scan's compiled binary satisfies this scan.

        Diagnostic-mode scans always rebuild: their first point must run
        ``backengine()`` so McStasData is available for the diagnostic plots
        (design record §18.5).
        """
        if diagnostic_mode or not cache:
            return False
        execution_state = cache.get("execution_state")
        return bool(
            cache.get("fingerprint") == fingerprint
            and execution_state is not None
            and execution_state.first_backengine_succeeded
            and execution_state.binary_path
            and os.path.isfile(execution_state.binary_path)
        )

    @staticmethod
    def _updated_binary_cache(cache, reused, fingerprint, instrument,
                              execution_state, instr_archive_path):
        """Next value of the cross-scan binary cache after a scan finishes.

        A scan that compiled (first backengine succeeded) owns the on-disk
        binary and replaces the cache. A reused or aborted-before-compile scan
        leaves the previous entry in place -- the binary on disk is unchanged.
        """
        if reused:
            return cache
        if (
            execution_state.first_backengine_succeeded
            and execution_state.binary_path
            and os.path.isfile(execution_state.binary_path)
        ):
            return {
                "fingerprint": fingerprint,
                "instrument": instrument,
                "execution_state": execution_state,
                "instr_path": (
                    instr_archive_path
                    if instr_archive_path and os.path.isfile(instr_archive_path)
                    else None
                ),
            }
        return cache

    def load_parameters(self):
        """Load parameters from JSON file."""
        if os.path.exists("config/parameters.json"):
            with open("config/parameters.json", "r") as file:
                parameters = self._parameters_block(json.load(file))

                # No saved block for this instrument (fresh install or a
                # pre-namespacing file): use the full default path so derived
                # values like ideal bending radii are applied, not left at 0.
                if not parameters:
                    self.set_default_parameters()
                    self.print_to_message_center(
                        f"No saved parameters for '{self.instrument.id}'; defaults loaded"
                    )
                    return

                # Block signals during loading to prevent premature validation
                self.window.simulation_dock.scan_command_1_edit.blockSignals(True)
                self.window.simulation_dock.scan_command_2_edit.blockSignals(True)
                
                # Set GUI values from parameters (saved crystal values may be
                # legacy display labels or CrystalSpec ids; both resolve)
                self.window.instrument_dock.set_mono_id(self._saved_crystal_id(
                    parameters.get("monocris_var"), self.descriptor.mono_crystals
                ))
                self.window.instrument_dock.set_ana_id(self._saved_crystal_id(
                    parameters.get("anacris_var"), self.descriptor.ana_crystals
                ))
                self.window.instrument_dock.mtt_edit.setText(str(parameters.get("mtt_var", "41.167")))
                self.window.instrument_dock.stt_edit.setText(str(parameters.get("stt_var", "-71.2502")))
                self.window.instrument_dock.omega_edit.setText(str(parameters.get("omega_var", "-35.6251")))
                self.window.instrument_dock.chi_edit.setText(str(parameters.get("chi_var", 0)))
                self.window.instrument_dock.att_edit.setText(str(parameters.get("att_var", "41.167")))
                self.window.instrument_dock.Ki_edit.setText(str(parameters.get("Ki_var", "2.6634")))
                self.window.instrument_dock.Kf_edit.setText(str(parameters.get("Kf_var", "2.6634")))
                self.window.instrument_dock.Ei_edit.setText(str(parameters.get("Ei_var", "14.7")))
                self.window.instrument_dock.Ef_edit.setText(str(parameters.get("Ef_var", "14.7")))
                self.window.instrument_dock.set_source_id(
                    parameters.get("source_type_var", self.descriptor.source_types[0].id)
                )
                self.window.instrument_dock.source_dE_edit.setText(str(parameters.get("source_dE_var", "2")))
                # Descriptor-driven categories (nested containers; legacy flat
                # keys from pre-Phase-2 files migrate through the fallbacks)
                self.window.instrument_dock.set_module_values(
                    self._saved_module_values(parameters)
                )
                self.window.instrument_dock.set_collimation_values(
                    self._saved_collimation_values(parameters)
                )
                self.window.instrument_dock.set_slit_values_mm(
                    self._saved_slit_values(parameters)
                )

                # Load absolute bending values (backward-compatible with factor-based params)
                self._load_bending_parameters(parameters)

                # Restore ideal lock state
                self._apply_bending_lock_state(
                    parameters.get("rhm_ideal_locked", False),
                    parameters.get("rvm_ideal_locked", False),
                    parameters.get("rha_ideal_locked", False),
                )
                
                self.window.simulation_dock.set_number_neutrons(parameters.get("number_neutrons_var", 1000000))
                self.window.scattering_dock.K_fixed_combo.setCurrentText(parameters.get("K_fixed_var", "Kf Fixed"))
                self.window.scattering_dock.fixed_E_edit.setText(str(parameters.get("fixed_E_var", 14.7)))
                self.window.scattering_dock.qx_edit.setText(str(parameters.get("qx_var", "3.1028")))
                self.window.scattering_dock.qy_edit.setText(str(parameters.get("qy_var", 0)))
                self.window.scattering_dock.qz_edit.setText(str(parameters.get("qz_var", 0)))
                # HKL values
                self.window.scattering_dock.H_edit.setText(str(parameters.get("H_var", 2)))
                self.window.scattering_dock.K_edit.setText(str(parameters.get("K_var", 0)))
                self.window.scattering_dock.L_edit.setText(str(parameters.get("L_var", 0)))
                self.window.scattering_dock.deltaE_edit.setText(str(parameters.get("deltaE_var", 0)))
                self.window.simulation_dock.diagnostic_mode_check.setChecked(parameters.get("diagnostic_mode_var", True))
                # Default scan: H-scan around Al (200) Bragg peak
                self.window.simulation_dock.scan_command_1_edit.setText(parameters.get("scan_command_var1", "H 1.9 2.1 0.01"))
                self.window.simulation_dock.scan_command_2_edit.setText(parameters.get("scan_command_var2", ""))
                
                # Sample alignment offsets (kappa and psi)
                self.window.sample_dock.kappa_edit.setText(str(parameters.get("kappa_var", 0)))
                self.window.sample_dock.psi_edit.setText(str(parameters.get("psi_offset_var", 0)))
                # Misalignment hash - decode and apply without revealing values
                mis_hash = str(parameters.get("misalignment_hash_var", ""))
                if mis_hash and mis_hash != "None" and mis_hash != "":
                    self.window.misalignment_dock.load_hash_edit.setText(mis_hash)
                    # Decode and apply the misalignment to the instrument
                    try:
                        from gui.docks.misalignment_dock import decode_misalignment
                        omega_m, chi_m, psi_m = decode_misalignment(mis_hash)
                        self.instrument_state.set_misalignment(omega_m, chi_m, psi_m)
                        # Store in dock and update UI to show it's loaded
                        self.window.misalignment_dock._loaded_misalignment = (omega_m, chi_m, psi_m)
                        self.window.misalignment_dock.misalignment_status_label.setText("✓ Misalignment loaded (hidden)")
                        self.window.misalignment_dock.misalignment_status_label.setStyleSheet("color: green; font-weight: bold;")
                        self.window.misalignment_dock.check_alignment_button.setEnabled(True)
                        # Update the indicator in the sample dock
                        self.window.sample_dock.update_misalignment_indicator(True)
                        self.print_to_message_center("Misalignment hash restored from saved parameters")
                    except Exception as e:
                        self.print_to_message_center(f"Failed to restore misalignment: {e}")
                # Restore sample selection by persisted sample id (default Al Bragg)
                try:
                    saved_sample = parameters.get("current_sample_settings", {})
                    if not self.window.sample_dock.set_sample_by_key(
                        saved_sample.get("sample_key", "Al_bragg")
                    ):
                        self.window.sample_dock.set_sample_by_key("Al_bragg")
                except Exception:
                    pass
                # Saved lattice values are applied AFTER the sample restore: the
                # sample-change handler adopts the sample's own lattice, and the
                # user's saved (possibly hand-edited) values must win on reload.
                self.window.sample_dock.lattice_a_edit.setText(str(parameters.get("lattice_a_var", "4.05")))
                self.window.sample_dock.lattice_b_edit.setText(str(parameters.get("lattice_b_var", "4.05")))
                self.window.sample_dock.lattice_c_edit.setText(str(parameters.get("lattice_c_var", "4.05")))
                self.window.sample_dock.lattice_alpha_edit.setText(str(parameters.get("lattice_alpha_var", "90")))
                self.window.sample_dock.lattice_beta_edit.setText(str(parameters.get("lattice_beta_var", "90")))
                self.window.sample_dock.lattice_gamma_edit.setText(str(parameters.get("lattice_gamma_var", "90")))
                # Restore space group selection
                try:
                    sg_number = parameters.get("space_group_number_var")
                    if sg_number is not None and hasattr(self.window.sample_dock, 'spacegroup_combo'):
                        idx = self.window.sample_dock.spacegroup_combo.findData(int(sg_number))
                        if idx >= 0:
                            self.window.sample_dock.spacegroup_combo.setCurrentIndex(idx)
                except Exception:
                    pass
                # Restore UB matrix state
                ub_state = parameters.get("ub_matrix_state")
                if ub_state:
                    try:
                        self.ub_matrix = UBMatrix.from_dict(ub_state)
                        self._update_ub_display()
                        # Restore peak entries in dock
                        peaks_data = []
                        for p in self.ub_matrix.peaks:
                            peaks_data.append(p.to_dict())
                        if peaks_data:
                            self.window.ub_matrix_dock.set_peak_entries(peaks_data)
                        self._reconnect_peak_signals()
                        self.print_to_message_center("UB matrix state restored")
                    except Exception as e:
                        self.print_to_message_center(f"Failed to restore UB matrix: {e}")
                # Restore UB training hash
                ub_hash = str(parameters.get("ub_training_hash", ""))
                if ub_hash and ub_hash != "None" and ub_hash != "":
                    try:
                        self.window.ub_matrix_dock.load_hash_edit.setText(ub_hash)
                        U, mis_omega, mis_chi = decode_training(ub_hash)
                        self.window.ub_matrix_dock._loaded_training = (U, mis_omega, mis_chi)
                        self.ub_matrix.set_U(U)
                        self.instrument_state.set_misalignment(mis_omega=mis_omega, mis_chi=mis_chi)
                        self._update_ub_display()
                        self.window.ub_matrix_dock.update_training_status(True)
                    except Exception as e:
                        self.print_to_message_center(
                            f"Failed to restore UB training hash '{ub_hash[:20]}...': {e}"
                        )
                # Set display and folder fields (use sensible defaults if missing)
                folder_suggestion = os.path.join(self.output_directory, "initial_testing")
                self.window.data_control_dock.save_folder_edit.setText(parameters.get("save_folder_var", folder_suggestion))
                self.window.data_control_dock.load_folder_edit.setText(parameters.get("load_folder_var", folder_suggestion))
                
                # Load diagnostic settings with defaults for any missing keys
                default_diag = DiagnosticConfigDialog.get_default_settings(
                    self.descriptor.monitors
                )
                loaded_diag = parameters.get("diagnostic_settings", {})
                # Merge: use loaded value if present, else default
                self.diagnostic_settings = {**default_diag, **loaded_diag}
                self.current_sample_settings = parameters.get("current_sample_settings", {})

                self.update_ideal_bending_buttons()
                
                # Unblock signals after all parameters are loaded
                self.window.simulation_dock.scan_command_1_edit.blockSignals(False)
                self.window.simulation_dock.scan_command_2_edit.blockSignals(False)
                
            self.print_to_message_center("Parameters loaded successfully")
        else:
            self.set_default_parameters()
    
    def set_default_parameters(self):
        """Set default parameters."""
        # Block signals during loading to prevent premature validation
        self.window.simulation_dock.scan_command_1_edit.blockSignals(True)
        self.window.simulation_dock.scan_command_2_edit.blockSignals(True)
        
        self.window.instrument_dock.set_mono_id(self.descriptor.mono_crystals[0].id)
        self.window.instrument_dock.set_ana_id(self.descriptor.ana_crystals[0].id)
        self.window.instrument_dock.mtt_edit.setText("41.167")
        self.window.instrument_dock.stt_edit.setText("-71.2502")
        self.window.instrument_dock.omega_edit.setText("-35.6251")
        self.window.instrument_dock.chi_edit.setText("0")
        self.window.instrument_dock.att_edit.setText("41.167")
        self.window.instrument_dock.Ki_edit.setText("2.6634")
        self.window.instrument_dock.Kf_edit.setText("2.6634")
        self.window.instrument_dock.Ei_edit.setText("14.7")
        self.window.instrument_dock.Ef_edit.setText("14.7")
        # Descriptor defaults for modules/collimation/slits (empty dict = defaults)
        self.window.instrument_dock.set_module_values({})
        self.window.instrument_dock.set_source_id(self.descriptor.source_types[0].id)
        self.window.instrument_dock.source_dE_edit.setText("2")
        self.window.instrument_dock.set_collimation_values({})
        # Slit apertures - descriptor defaults (SlitSpec.default_*_mm)
        self.window.instrument_dock.set_slit_values_mm({})

        # Set default absolute bending to ideal values
        self.update_ideal_bending_buttons()
        self.apply_ideal_bending_values()
        
        self.window.simulation_dock.set_number_neutrons(1000000)
        self.window.scattering_dock.K_fixed_combo.setCurrentText("Kf Fixed")
        self.window.scattering_dock.fixed_E_edit.setText("14.7")
        self.window.scattering_dock.qx_edit.setText("3.1028")
        self.window.scattering_dock.qy_edit.setText("0")
        self.window.scattering_dock.qz_edit.setText("0")
        # Set HKL defaults - Al (200) Bragg peak
        self.window.scattering_dock.H_edit.setText("2")
        self.window.scattering_dock.K_edit.setText("0")
        self.window.scattering_dock.L_edit.setText("0")
        self.window.scattering_dock.deltaE_edit.setText("0")
        self.window.simulation_dock.diagnostic_mode_check.setChecked(True)
        
        self.window.sample_dock.lattice_a_edit.setText("4.05")
        self.window.sample_dock.lattice_b_edit.setText("4.05")
        self.window.sample_dock.lattice_c_edit.setText("4.05")
        self.window.sample_dock.lattice_alpha_edit.setText("90")
        self.window.sample_dock.lattice_beta_edit.setText("90")
        self.window.sample_dock.lattice_gamma_edit.setText("90")
        # Sample alignment offset defaults
        self.window.sample_dock.kappa_edit.setText("0")
        self.window.sample_dock.psi_edit.setText("0")
        # Default scan: H-scan around Al (200) Bragg peak - quick 21 point scan
        self.window.simulation_dock.scan_command_1_edit.setText("H 1.9 2.1 0.01")
        self.window.simulation_dock.scan_command_2_edit.setText("")
        
        # Set default folder paths
        folder_suggestion = os.path.join(self.output_directory, "initial_testing")
        self.window.data_control_dock.save_folder_edit.setText(folder_suggestion)
        self.window.data_control_dock.load_folder_edit.setText(folder_suggestion)
        
        self.diagnostic_settings = DiagnosticConfigDialog.get_default_settings(
            self.descriptor.monitors
        )
        self.current_sample_settings = {}
        # Reset UB matrix to identity
        self.ub_matrix = UBMatrix()
        if hasattr(self.window, 'ub_matrix_dock'):
            self._update_ub_display()
            self.window.ub_matrix_dock._loaded_training = None
            self.window.ub_matrix_dock.update_training_status(False)
            self._reconnect_peak_signals()
        # Default sample to Al: Bragg for easy testing
        try:
            self.window.sample_dock.set_sample_by_key("Al_bragg")
        except Exception:
            pass
        
        # Unblock signals after all parameters are set
        self.window.simulation_dock.scan_command_1_edit.blockSignals(False)
        self.window.simulation_dock.scan_command_2_edit.blockSignals(False)
        
        self.print_to_message_center("Default parameters loaded")
    
    def run_simulation_thread(self):
        """Start simulation in a separate thread."""
        # Pre-flight validation - check for scan command issues
        validation_result = self._preflight_scan_validation()
        if validation_result:
            # There are issues - show warning but allow proceeding
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self.window,
                "Scan Command Issues",
                f"{validation_result}\n\nDo you want to continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self.print_to_message_center("Simulation cancelled due to scan command issues")
                return
        
        self.stop_event.clear()
        
        # Reset progress bar and show initializing state
        self.window.simulation_dock.progress_bar.setValue(0)
        self.window.simulation_dock.progress_label.setText("Initializing...")
        self.window.simulation_dock.remaining_time_label.setText("Estimated Remaining Time: calculating...")
        self.pre_scan_estimate_updated.emit("")

        self.save_parameters()
        launch_state = self._collect_simulation_launch_state()
        if not launch_state:
            self.print_to_message_center("Error: Could not get GUI values")
            return
        self.window.display_dock.set_scan_metadata(self._build_scan_metadata(launch_state['vals']))
        
        simulation_thread = threading.Thread(target=self.run_simulation, args=(launch_state,))
        simulation_thread.start()
    
    def _preflight_scan_validation(self) -> str:
        """Check scan commands before running simulation.
        
        Returns:
            str: Error/warning message if issues found, empty string if OK
        """
        from gui.docks.unified_simulation_dock import (
            LINKED_PARAMETER_GROUPS, MODE_CONFLICTS, VALID_SCAN_VARIABLES
        )
        
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        
        issues = []
        
        # Validate command 1
        var1, warning1 = self._validate_single_scan_command(cmd1)
        if warning1 and "⚠" in warning1:  # Only block on serious warnings
            issues.append(f"Command 1: {warning1}")
        elif warning1 and "Unknown" in warning1:
            issues.append(f"Command 1: {warning1}")
        
        # Validate command 2
        var2, warning2 = self._validate_single_scan_command(cmd2)
        if warning2 and "⚠" in warning2:
            issues.append(f"Command 2: {warning2}")
        elif warning2 and "Unknown" in warning2:
            issues.append(f"Command 2: {warning2}")
        
        # Check for conflicts between commands
        if var1 and var2:
            conflict = self._check_scan_parameter_conflict(var1, var2)
            if conflict:
                issues.append(conflict)
        
        return "\n".join(issues)

    def on_sample_changed(self, label):
        """Handle sample selection changes from the GUI."""
        try:
            key = self.window.sample_dock.get_selected_sample_key()
            self.instrument_state.sample_key = key
            self.current_sample_settings = {"sample_label": label, "sample_key": key}
            self.print_to_message_center(f"Sample selection changed: {label} ({key})")
            self._adopt_sample_lattice(key)
        except Exception as e:
            self.print_to_message_center(f"Sample selection change failed: {e}")

    def _adopt_sample_lattice(self, sample_key):
        """Set the lattice fields from the selected sample's own lattice.

        Samples carry their lattice constants (SampleSpec.lattice) because the
        McStas components bake them in -- driving e.g. Phonon_DFT (a=4.03893)
        with a mismatched GUI lattice misses its Bragg condition entirely.
        The parameter-restore path re-applies saved lattice values afterwards,
        so hand-edited lattices survive a reload.
        """
        spec = next((s for s in self.descriptor.samples if s.id == sample_key), None)
        if spec is None or spec.lattice is None:
            return
        a, b, c, alpha, beta, gamma = spec.lattice
        dock = self.window.sample_dock
        for edit, value in ((dock.lattice_a_edit, a), (dock.lattice_b_edit, b),
                            (dock.lattice_c_edit, c), (dock.lattice_alpha_edit, alpha),
                            (dock.lattice_beta_edit, beta), (dock.lattice_gamma_edit, gamma)):
            edit.setText(f"{value:g}")
        self.print_to_message_center(
            f"Lattice set from sample '{spec.display_name}': "
            f"a={a:g}, b={b:g}, c={c:g}"
        )
    
    def stop_simulation(self):
        """Stop the running simulation."""
        self.stop_event.set()
        self.print_to_message_center("Stop requested...")

    def _prep_worker(self, scan_parameter_input, scan_mode, scan_config, is_2d_scan,
                     variable_name1, variable_name2, vals, data_folder,
                     scan_command1, scan_command2, snapshot_queue, stop_event):
        """Compute per-point snapshots ahead of the simulation thread."""
        try:
            for scan_index, scan_item in enumerate(scan_parameter_input):
                if stop_event.is_set():
                    break

                prep_stage_start = time.perf_counter()
                snapshot = self.instrument.compute_snapshot(
                    scan_item,
                    scan_index,
                    scan_mode,
                    scan_config,
                    vals,
                    data_folder,
                    is_2d_scan=is_2d_scan,
                    variable_name1=variable_name1,
                    variable_name2=variable_name2,
                    scan_command1=scan_command1,
                    scan_command2=scan_command2,
                )
                prep_compute_duration = time.perf_counter() - prep_stage_start
                queue_wait_start = time.perf_counter()

                while not stop_event.is_set():
                    try:
                        snapshot_queue.put(snapshot, timeout=0.1)
                        # The queued PointSnapshot is shared by reference; stamping
                        # timing after put() is visible to the consumer loop.
                        queue_wait_duration = time.perf_counter() - queue_wait_start
                        snapshot.timing['prep_compute_duration_s'] = prep_compute_duration
                        snapshot.timing['prep_queue_wait_duration_s'] = queue_wait_duration
                        snapshot.timing['prep_duration_s'] = prep_compute_duration + queue_wait_duration
                        break
                    except queue.Full:
                        continue
        except Exception as exc:
            failure = PrepFailure(str(exc))
            while not stop_event.is_set():
                try:
                    snapshot_queue.put(failure, timeout=0.1)
                    break
                except queue.Full:
                    continue
        finally:
            while True:
                try:
                    snapshot_queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    if stop_event.is_set():
                        break
                    continue
    
    def run_simulation(self, launch_state):
        """Run the full simulation."""
        self.message_printed.emit("Starting simulation...")

        vals = launch_state['vals']
        scan_config = launch_state['scan_config']
        diagnostic_settings = launch_state['diagnostic_settings']
        number_neutrons = vals['number_neutrons']
        scan_command1 = vals['scan_command1']
        scan_command2 = vals['scan_command2']
        diagnostic_mode = vals['diagnostic_mode']
        relative_mode_1 = launch_state['relative_mode_1']
        relative_mode_2 = launch_state['relative_mode_2']
        compact_save_enabled = launch_state['compact_save_enabled']

        data_folder = launch_state['save_folder_input']
        # If the folder already exists, increment instead
        new_data_folder = incremented_path_writing(self.output_directory, data_folder)
        data_folder = new_data_folder

        self.actual_output_folder_updated.emit(data_folder)
        
        # Write parameters to file
        write_parameters_to_file(data_folder, vals)
        
        # Initialize scan arrays
        scan_parameter_input = []
        
        scan_mode = self._determine_scan_mode(scan_command1, scan_command2)
        
        # Mapping for scannable parameters
        # Indices: 0-3: Q/HKL/angles, 4-7: bending, 8-10: sample orientation (chi, kappa, psi)
        # A3 is the calculated sample angle.  omega/psi are in-plane orientation offsets.
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
            'H': 0, 'K': 1, 'L': 2, 'deltaE': 3,
            'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,
            'omega': 10, '2theta': 1,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7,
            'chi': 8, 'kappa': 9, 'psi': 10
        }
        
        # Initialize scan point template
        # Extended to 11 elements: 0-3: Q/HKL/angles, 4-7: bending, 8-10: chi/kappa/psi
        # Note: omega is normalized to A3, so no separate index needed
        scan_point_template = [0] * 11
        if scan_mode == "momentum":
            scan_point_template[:4] = [vals['qx'], vals['qy'], vals['qz'], vals['deltaE']]
        elif scan_mode == "rlu":
            scan_point_template[:4] = [vals['H'], vals['K'], vals['L'], vals['deltaE']]
        elif scan_mode == "angle":
            scan_point_template[:4] = [vals['mtt'], vals['stt'], vals['omega'], vals['att']]
        elif scan_mode == "orientation":
            # For orientation scans, use current Q values but scan static offsets.
            scan_point_template[:4] = [vals['qx'], vals['qy'], vals['qz'], vals['deltaE']]
        # Static chi offset is not the visible calculated chi/saz instrument angle.
        scan_point_template[8] = 0
        scan_point_template[9] = vals['kappa']
        scan_point_template[10] = vals['psi']
        
        # Track if this is a single-point scan (no scan commands)
        is_single_point_scan = not scan_command1 and not scan_command2
        
        # Handle no scan commands (single point simulation)
        if not scan_command1 and not scan_command2:
            # Store as tuple (scan_point, idx_1d) for consistency
            scan_parameter_input.append((scan_point_template[:], 0))
        
        # Swap if only second command provided
        if scan_command2 and not scan_command1:
            scan_command1 = scan_command2
            scan_command2 = None
        
        variable_name1 = ""
        variable_name2 = ""
        
        # Arrays to track requested scan geometry for display
        valid_mask_1d = []
        valid_mask_2d = None
        array_values1 = []
        array_values2 = []
        check_state = self.instrument.default_state()
        check_state.monocris = scan_config.monocris
        check_state.anacris = scan_config.anacris
        check_state.K_fixed = scan_config.K_fixed
        check_state.fixed_E = scan_config.fixed_E
        
        # Single scan command
        if scan_command1 and not scan_command2:
            variable_name1, array_values1 = parse_scan_steps(scan_command1)
            variable_name1 = self.normalize_scan_variable(variable_name1)
            
            # Apply relative offset if enabled for command 1
            if relative_mode_1:
                base_value = self._get_current_value_for_variable(variable_name1, vals, scan_point_template)
                array_values1 = array_values1 + base_value
                self.message_printed.emit(f"Relative scan: {variable_name1} base value = {base_value}")
            
            valid_mask_1d = [False] * len(array_values1)
            
            for idx, value1 in enumerate(array_values1):
                scan_point = scan_point_template[:]
                scan_point[variable_to_index[variable_name1]] = value1
                scan_parameter_input.append((scan_point, idx))

                if scan_mode in ("momentum", "orientation"):
                    _, error_flags = check_state.calculate_angles(
                        *scan_point[:4], scan_config.fixed_E, scan_config.K_fixed,
                        scan_config.monocris, scan_config.anacris
                    )
                elif scan_mode == "rlu":
                    qx, qy, qz = component_q_to_instrument_q(
                        scan_config.sample_mount.hkl_to_q(
                            scan_point[0], scan_point[1], scan_point[2]
                        )
                    )
                    _, error_flags = check_state.calculate_angles(
                        qx, qy, qz, scan_point[3], scan_config.fixed_E,
                        scan_config.K_fixed, scan_config.monocris, scan_config.anacris
                    )
                else:
                    error_flags = []

                valid_mask_1d[idx] = not error_flags
            
            # Initialize display dock for 1D scan
            self.scan_initialized.emit('1D', list(array_values1), valid_mask_1d, 
                                       variable_name1, "", [], [])
        
        # Double scan command
        if scan_command2 and scan_command1:
            variable_name1, array_values1 = parse_scan_steps(scan_command1)
            variable_name2, array_values2 = parse_scan_steps(scan_command2)
            variable_name1 = self.normalize_scan_variable(variable_name1)
            variable_name2 = self.normalize_scan_variable(variable_name2)
            
            # Apply relative offset if enabled for each command independently
            if relative_mode_1:
                base_value1 = self._get_current_value_for_variable(variable_name1, vals, scan_point_template)
                array_values1 = array_values1 + base_value1
                self.message_printed.emit(f"Relative scan 1: {variable_name1} base = {base_value1}")
            if relative_mode_2:
                base_value2 = self._get_current_value_for_variable(variable_name2, vals, scan_point_template)
                array_values2 = array_values2 + base_value2
                self.message_printed.emit(f"Relative scan 2: {variable_name2} base = {base_value2}")
            
            # Build a full validity mask for display, but still enqueue every requested point.
            valid_mask_2d = [[False] * len(array_values1) for _ in range(len(array_values2))]
            
            for idx_y, value2 in enumerate(array_values2):
                for idx_x, value1 in enumerate(array_values1):
                    scan_point = scan_point_template[:]
                    scan_point[variable_to_index[variable_name1]] = value1
                    scan_point[variable_to_index[variable_name2]] = value2
                    scan_parameter_input.append((scan_point, idx_x, idx_y))

                    if scan_mode in ("momentum", "orientation"):
                        _, error_flags = check_state.calculate_angles(
                            *scan_point[:4], scan_config.fixed_E, scan_config.K_fixed,
                            scan_config.monocris, scan_config.anacris
                        )
                    elif scan_mode == "rlu":
                        qx, qy, qz = component_q_to_instrument_q(
                            scan_config.sample_mount.hkl_to_q(
                                scan_point[0], scan_point[1], scan_point[2]
                            )
                        )
                        _, error_flags = check_state.calculate_angles(
                            qx, qy, qz, scan_point[3], scan_config.fixed_E,
                            scan_config.K_fixed, scan_config.monocris, scan_config.anacris
                        )
                    else:
                        error_flags = []

                    valid_mask_2d[idx_y][idx_x] = not error_flags
            
            # Initialize display dock for 2D scan
            self.scan_initialized.emit('2D', list(array_values1), [], variable_name1,
                                       variable_name2, list(array_values2), valid_mask_2d)
        
        # Track if this is a 2D scan
        is_2d_scan = scan_command2 and scan_command1

        if is_2d_scan:
            estimated_runtime_points = int(sum(sum(1 for value in row if value) for row in valid_mask_2d))
        elif is_single_point_scan:
            estimated_runtime_points = 1
        else:
            estimated_runtime_points = int(sum(1 for value in valid_mask_1d if value))
        estimated_runtime_points = max(estimated_runtime_points, 1)
        
        # Run the scans
        start_time = time.time()
        total_scans = len(scan_parameter_input)
        self.message_printed.emit(f"Running {total_scans} scan points...")
        
        # Show pre-scan estimate based on historical data
        instrument_name = self.instrument.id
        total_est, compile_est, _ = self.runtime_tracker.estimate_total_time(
            instrument_name, estimated_runtime_points, number_neutrons
        )
        if total_est is not None:
            est_str = RuntimeTracker.format_time(total_est)
            self.pre_scan_estimate_updated.emit(est_str)
            self.message_printed.emit(f"Estimated total time: {est_str}")
        else:
            self.pre_scan_estimate_updated.emit("")
        
        total_counts = 0
        max_counts = 0
        
        # Track individual scan times for runtime recording
        executed_scan_times = []
        simulation_stage_durations = []
        point_stage_timings = []
        first_successful_stage_record_index = None
        
        # Data collection for output files
        import numpy as np
        if is_2d_scan:
            # For 2D scans: store counts in a 2D grid
            counts_grid = np.full((len(array_values2), len(array_values1)), np.nan)
        else:
            # For 1D scans: store x values and counts as parallel arrays
            scan_x_values = []
            scan_counts = []
        
        effective_diagnostic_settings = diagnostic_settings if diagnostic_mode else {}
        build_fingerprint = self.instrument.build_fingerprint(
            scan_config, diagnostic_mode, effective_diagnostic_settings
        )
        reuse_binary = self._can_reuse_binary(
            self._binary_reuse_cache, build_fingerprint, diagnostic_mode
        )
        if reuse_binary:
            instrument = self._binary_reuse_cache["instrument"]
            execution_state = self._binary_reuse_cache["execution_state"]
            self.message_printed.emit(
                "Build settings unchanged; reusing compiled instrument from previous scan"
            )
        else:
            instrument = self.instrument.build(
                scan_config,
                diagnostic_mode,
                effective_diagnostic_settings,
                number_neutrons,
            )
            execution_state = RunExecutionState()
        retained_diagnostic_data = None

        if diagnostic_mode and diagnostic_settings.get('Show Instrument Diagram', False):
            self.instrument_diagram_requested.emit(instrument)

        snapshot_queue = queue.Queue()
        prep_thread = threading.Thread(
            target=self._prep_worker,
            args=(
                scan_parameter_input,
                scan_mode,
                scan_config,
                is_2d_scan,
                variable_name1,
                variable_name2,
                vals,
                data_folder,
                scan_command1,
                scan_command2,
                snapshot_queue,
                self.stop_event,
            ),
            daemon=True,
        )
        prep_thread.start()

        processed_points = 0
        remaining_runtime_points = estimated_runtime_points
        data = None
        simulation_stopped = False
        simulation_error_message = None

        try:
            while True:
                if self.stop_event.is_set():
                    simulation_stopped = True
                    break

                try:
                    snapshot = snapshot_queue.get(timeout=0.1)
                except queue.Empty:
                    if prep_thread.is_alive():
                        continue
                    break

                if snapshot is None:
                    break

                if isinstance(snapshot, PrepFailure):
                    simulation_error_message = f"Preparation thread failed: {snapshot.message}"
                    self.message_printed.emit(simulation_error_message)
                    break

                scan_start_time = time.time()
                i = snapshot.scan_index
                self.message_printed.emit(snapshot.log_message)
                indices = snapshot.indices
                idx_1d = indices['idx_1d']
                idx_x = indices['idx_x']
                idx_y = indices['idx_y']
                scan_folder = snapshot.output_folder
                error_flags = list(snapshot.error_flags)
                metadata = snapshot.metadata
                deltaE = snapshot.deltaE
                qx = metadata['qx']
                qy = metadata['qy']
                qz = metadata['qz']
                H = metadata['H']
                K = metadata['K']
                L = metadata['L']
                mtt = metadata['mtt']
                stt = metadata['stt']
                sth = metadata['sth']
                att = metadata['att']
                rhm = metadata['rhm']
                rvm = metadata['rvm']
                rha = metadata['rha']
                rva = metadata['rva']
                omega_scan = metadata['omega']
                chi_scan = metadata['chi']
                psi_scan = metadata['psi']
                kappa_scan = metadata['kappa']
                timing = snapshot.timing
                prep_duration = float(timing.get('prep_duration_s', 0.0))
                prep_compute_duration = float(timing.get('prep_compute_duration_s', 0.0))
                prep_queue_wait_duration = float(timing.get('prep_queue_wait_duration_s', 0.0))
                simulation_duration = 0.0

                if is_2d_scan:
                    self.scan_current_index_2d.emit(idx_x, idx_y)
                else:
                    self.scan_current_index_1d.emit(idx_1d)

                execution_info = {
                    'mode': 'skipped',
                    'returncode': None,
                    'stdout': None,
                    'binary_path': execution_state.binary_path,
                    'output_folder': scan_folder,
                    'error_message': None,
                    'launcher_argv': list(execution_state.mpi_launcher_argv or []),
                    'armed_direct_run': False,
                }

                if not error_flags and snapshot.params is not None:
                    simulation_stage_start = time.perf_counter()
                    data, error_flags, execution_info = self.instrument.run_point(
                        instrument,
                        snapshot,
                        scan_folder,
                        number_neutrons,
                        execution_state,
                    )
                    simulation_duration = time.perf_counter() - simulation_stage_start
                    simulated_point = True
                else:
                    data = math.nan
                    self.message_printed.emit(f"Point {i}: skipped, error flags: {error_flags}")
                    simulated_point = False

                if execution_info.get('armed_direct_run'):
                    launcher_text = " ".join(execution_info.get('launcher_argv', [])) or "unresolved"
                    self.message_printed.emit(
                        f"Direct run armed: binary={execution_info.get('binary_path')}, "
                        f"launcher={launcher_text}, point={i}"
                    )

                if execution_info.get('mode') == 'direct' and not error_flags:
                    self.message_printed.emit(f"Point {i} executed via direct binary")

                if retained_diagnostic_data is None and data is not None and data is not math.nan:
                    retained_diagnostic_data = data

                postprocessing_stage_start = time.perf_counter()

                # On the first scan point, copy the .instr file to the parent folder
                # (it's the same for every point since only parameters change, not the compiled
                # instrument structure; rewriting it per-point would be redundant).
                if i == 0:
                    instr_src = os.path.join(scan_folder, f"{self._mcstas_name}.instr")
                    instr_dst = os.path.join(data_folder, f"{self._mcstas_name}.instr")
                    # Direct binary runs write no .instr into the scan folder;
                    # a reused-binary scan archives the compiling scan's copy.
                    if not os.path.exists(instr_src) and reuse_binary:
                        cached_instr = self._binary_reuse_cache.get("instr_path")
                        if cached_instr and os.path.isfile(cached_instr):
                            instr_src = cached_instr
                    if os.path.exists(instr_src):
                        try:
                            shutil.copy2(instr_src, instr_dst)
                        except Exception as e:
                            self.print_to_message_center(
                                f"Warning: Failed to copy .instr file: {e}\n"
                                f"  Source: {instr_src}\n  Dest: {instr_dst}"
                            )

                # Compact save mode: remove large intermediate files from the scan sub-folder.
                # detector.dat and scan_parameters.txt are kept; everything else is transient.
                if compact_save_enabled:
                    for _fname in (f"{self._mcstas_name}.c", f"{self._mcstas_name}.instr", "mccode.sim"):
                        _fpath = os.path.join(scan_folder, _fname)
                        if os.path.exists(_fpath):
                            try:
                                os.remove(_fpath)
                            except Exception as e:
                                self.print_to_message_center(
                                    f"Warning: Failed to delete {_fname}: {e}\n  Path: {_fpath}"
                                )

                # Check for errors
                if error_flags:
                    if execution_info.get('error_message'):
                        self.message_printed.emit(
                            f"Point {i} {execution_info.get('mode')} error: {execution_info['error_message']}"
                        )
                    if execution_info.get('stdout'):
                        stdout_text = execution_info['stdout'].strip()
                        if stdout_text:
                            self.message_printed.emit(
                                f"Point {i} direct output:\n{stdout_text}"
                            )
                    message = f"Scan failed, error flags: {error_flags}"
                    self.message_printed.emit(message)
                    if is_2d_scan:
                        self.scan_point_invalid_2d.emit(idx_x, idx_y)
                    elif not is_single_point_scan and idx_1d >= 0:
                        self.scan_point_invalid_1d.emit(idx_1d)

                    if not is_2d_scan and not is_single_point_scan and idx_1d >= 0 and idx_1d < len(array_values1):
                        scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(np.nan)
                else:
                    # Build scan-specific parameters for this point
                    scan_point_params = {
                        **metadata,
                        'scan_index': i,
                        'deltaE': deltaE,
                        'number_neutrons': number_neutrons,
                    }
                    # Merge with full GUI vals for completeness; scan_point_params overrides stale vals
                    full_params = {**vals, **scan_point_params}
                    write_parameters_to_file(scan_folder, full_params)
                    
                    # Read detector file to get counts
                    intensity, intensity_error, counts = read_1Ddetector_file(scan_folder)
                    message = f"Final counts at detector: {int(counts)}"
                    self.message_printed.emit(message)
                    
                    # Update counts
                    total_counts += counts
                    max_counts = max(max_counts, counts)
                    
                    # Emit display update signal
                    if is_2d_scan:
                        self.scan_point_updated_2d.emit(idx_x, idx_y, counts)
                        # Store in grid for output file
                        counts_grid[idx_y, idx_x] = counts
                    elif not is_single_point_scan:
                        # 1D scan with actual scan values
                        if idx_1d >= 0:
                            self.scan_point_updated_1d.emit(idx_1d, counts)
                        # Store in arrays for output file
                        if idx_1d >= 0 and idx_1d < len(array_values1):
                            scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(counts)
                    # For single-point scans, we don't update scan arrays (handled separately)
                
                # Record scan time for this point
                scan_elapsed = time.time() - scan_start_time
                if simulated_point and not error_flags:
                    executed_scan_times.append(scan_elapsed)
                    if remaining_runtime_points > 0:
                        remaining_runtime_points -= 1
                processed_points += 1
                
                # Emit progress signals
                self.progress_updated.emit(processed_points, total_scans)
                self.counts_updated.emit(max_counts, total_counts)
                
                # Calculate elapsed time and remaining time - ignore first scan (compilation overhead)
                elapsed_time = time.time() - start_time
                # Emit elapsed time for UI
                try:
                    elapsed_str = RuntimeTracker.format_time(elapsed_time)
                    self.elapsed_time_updated.emit(elapsed_str)
                except Exception:
                    pass
                if len(executed_scan_times) <= 1:
                    # After first scan, use historical data for estimation if available
                    _, run_time_per_point = self.runtime_tracker.get_estimates(instrument_name, number_neutrons)
                    if run_time_per_point is not None and remaining_runtime_points > 0:
                        remaining_time = run_time_per_point * remaining_runtime_points
                    elif executed_scan_times and remaining_runtime_points > 0:
                        remaining_time = executed_scan_times[0] * remaining_runtime_points
                    else:
                        remaining_time = 0
                else:
                    # For subsequent scans, use average of scans 2+ (excluding first/compile scan)
                    subsequent_times = executed_scan_times[1:]  # Exclude first executed/compile scan
                    avg_time_per_scan = sum(subsequent_times) / len(subsequent_times)
                    remaining_time = avg_time_per_scan * remaining_runtime_points
                
                hours = int(remaining_time // 3600)
                minutes = int((remaining_time % 3600) // 60)
                seconds = int(remaining_time % 60)
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                self.remaining_time_updated.emit(time_str)

                postprocessing_duration = time.perf_counter() - postprocessing_stage_start
                if simulated_point and not error_flags:
                    simulation_stage_durations.append(simulation_duration)

                point_stage_timings.append({
                    'scan_index': i,
                    'prep_duration_s': prep_duration,
                    'prep_compute_duration_s': prep_compute_duration,
                    'prep_queue_wait_duration_s': prep_queue_wait_duration,
                    'simulation_duration_s': simulation_duration,
                    'postprocessing_duration_s': postprocessing_duration,
                    'execution_mode': execution_info.get('mode'),
                    'direct_returncode': execution_info.get('returncode'),
                    'direct_binary_path': execution_info.get('binary_path'),
                    'simulated': bool(simulated_point and not error_flags),
                    'error_flags': list(error_flags),
                })
                if simulated_point and not error_flags and first_successful_stage_record_index is None:
                    first_successful_stage_record_index = len(point_stage_timings) - 1
        except Exception as e:
            simulation_error_message = f"Simulation failed: {e}"
            self.message_printed.emit(simulation_error_message)
            self.stop_event.set()
        finally:
            if simulation_error_message is not None:
                self.stop_event.set()
            prep_thread.join(timeout=1)

        if simulation_stopped:
            self.message_printed.emit("Simulation stopped by user.")

        self._binary_reuse_cache = self._updated_binary_cache(
            self._binary_reuse_cache,
            reuse_binary,
            build_fingerprint,
            instrument,
            execution_state,
            os.path.join(data_folder, f"{self._mcstas_name}.instr"),
        )

        inferred_compile_duration = None
        if len(simulation_stage_durations) > 1:
            avg_subsequent_simulation_duration = sum(simulation_stage_durations[1:]) / len(simulation_stage_durations[1:])
            inferred_compile_duration = max(0.0, simulation_stage_durations[0] - avg_subsequent_simulation_duration)
        if inferred_compile_duration is not None and first_successful_stage_record_index is not None:
            point_stage_timings[first_successful_stage_record_index]['inferred_compile_duration_s'] = inferred_compile_duration

        if point_stage_timings:
            prep_durations = [record['prep_duration_s'] for record in point_stage_timings]
            prep_compute_durations = [record['prep_compute_duration_s'] for record in point_stage_timings]
            prep_queue_wait_durations = [record['prep_queue_wait_duration_s'] for record in point_stage_timings]
            postprocessing_durations = [record['postprocessing_duration_s'] for record in point_stage_timings]
            stage_summary = {
                'completed_normally': simulation_error_message is None and not self.stop_event.is_set(),
                'stopped': simulation_stopped or self.stop_event.is_set(),
                'simulation_error_message': simulation_error_message,
                'total_requested_points': total_scans,
                'total_simulated_points': len(executed_scan_times),
                'num_backengine_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'backengine'
                ),
                'num_direct_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'direct'
                ),
                'num_skipped_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'skipped'
                ),
                'compile_duration_s': inferred_compile_duration,
                'compile_duration_inferred': inferred_compile_duration is not None,
                'avg_prep_duration_s': sum(prep_durations) / len(prep_durations),
                'avg_prep_compute_duration_s': sum(prep_compute_durations) / len(prep_compute_durations),
                'avg_prep_queue_wait_duration_s': sum(prep_queue_wait_durations) / len(prep_queue_wait_durations),
                'avg_simulation_duration_s': (
                    sum(simulation_stage_durations) / len(simulation_stage_durations)
                    if simulation_stage_durations else 0.0
                ),
                'avg_postprocessing_duration_s': sum(postprocessing_durations) / len(postprocessing_durations),
                'point_timings': point_stage_timings,
            }
            try:
                summary_path = self._write_stage_timing_summary(data_folder, stage_summary)
                compile_message = (
                    f"compile={inferred_compile_duration:.3f}s"
                    if inferred_compile_duration is not None else "compile=unavailable"
                )
                self.message_printed.emit(
                    "Stage timings recorded: "
                    f"{compile_message}, avg prep={stage_summary['avg_prep_duration_s']:.3f}s "
                    f"(compute={stage_summary['avg_prep_compute_duration_s']:.3f}s, "
                    f"queue_wait={stage_summary['avg_prep_queue_wait_duration_s']:.3f}s), "
                    f"avg sim={stage_summary['avg_simulation_duration_s']:.3f}s, "
                    f"avg post={stage_summary['avg_postprocessing_duration_s']:.3f}s"
                )
                self.message_printed.emit(f"Stage timing summary written to: {summary_path}")
            except Exception as e:
                self.message_printed.emit(f"Warning: Failed to write stage timing summary: {e}")
        
        # Record runtime data for future estimates (only if scan completed normally)
        if executed_scan_times and simulation_error_message is None and not self.stop_event.is_set():
            total_time = time.time() - start_time
            first_scan_time = executed_scan_times[0]
            
            # Calculate average time for subsequent scans (excluding first)
            if len(executed_scan_times) > 1:
                avg_subsequent_time = sum(executed_scan_times[1:]) / len(executed_scan_times[1:])
                compilation_time = inferred_compile_duration if inferred_compile_duration is not None else max(0.0, first_scan_time - avg_subsequent_time)
            else:
                # Only one scan point - use first scan time as both
                avg_subsequent_time = first_scan_time
                compilation_time = 0.0
            
            self.runtime_tracker.add_record(
                instrument_name=instrument_name,
                num_points=len(executed_scan_times),
                num_neutrons=number_neutrons,
                first_scan_time=first_scan_time,
                avg_subsequent_time=avg_subsequent_time,
                total_time=total_time,
                compilation_time=compilation_time,
            )
            self.message_printed.emit(
                f"Timing data recorded: {len(executed_scan_times)} simulated points in {RuntimeTracker.format_time(total_time)}"
            )
            # Trigger update of scan time estimates on main thread
            self.runtime_data_updated.emit()
        
        # Simulation complete
        if simulation_error_message is None and not self.stop_event.is_set():
            self.message_printed.emit(f"Simulation complete! Data saved to: {data_folder}")
            self.message_printed.emit(f"Total counts: {total_counts}, Max counts: {max_counts}")
        
        # Write scan data to output files
        if not is_single_point_scan and simulation_error_message is None and not self.stop_event.is_set():
            try:
                if is_2d_scan:
                    # Write 2D scan data (include parameter labels if available)
                    x_label = variable_name1 if 'variable_name1' in locals() and variable_name1 else 'scan1'
                    y_label = variable_name2 if 'variable_name2' in locals() and variable_name2 else 'scan2'
                    write_2D_scan(
                        np.array(array_values1),
                        np.array(array_values2),
                        counts_grid,
                        data_folder,
                        "2D_scan_data.txt",
                        x_label=x_label,
                        y_label=y_label,
                    )
                    self.message_printed.emit(f"2D scan data written to: {os.path.join(data_folder, '2D_scan_data.txt')}")
                else:
                    # Write 1D scan data
                    if scan_x_values and scan_counts:
                        # Sort by x values for proper ordering
                        sorted_indices = np.argsort(scan_x_values)
                        sorted_x = np.array(scan_x_values)[sorted_indices]
                        sorted_counts = np.array(scan_counts)[sorted_indices]
                        x_label = variable_name1 if 'variable_name1' in locals() and variable_name1 else 'scan'
                        write_1D_scan(sorted_x, sorted_counts, data_folder, "1D_scan_data.txt", x_label=x_label, y_label='counts')
                        self.message_printed.emit(f"1D scan data written to: {os.path.join(data_folder, '1D_scan_data.txt')}")
            except Exception as e:
                self.message_printed.emit(f"Warning: Failed to write scan data file: {e}")
        
        # Handle display based on scan type
        if simulation_error_message is not None or self.stop_event.is_set():
            self.scan_completed.emit()
        elif is_single_point_scan:
            # For single-point scans, show results as text instead of plot
            self.single_point_result.emit(max_counts, total_counts)
        else:
            # For 1D/2D scans, signal completion and auto-save the plot
            self.scan_completed.emit()
            self.scan_auto_save.emit()
        
        # Display diagnostic subplots if in diagnostic mode and any monitors were enabled
        if diagnostic_mode and simulation_error_message is None and not self.stop_event.is_set():
            # Check if any diagnostic monitors were enabled (excluding Show Instrument Diagram)
            monitors_enabled = any(
                enabled for key, enabled in diagnostic_settings.items() 
                if key != "Show Instrument Diagram" and enabled
            )
            if monitors_enabled and retained_diagnostic_data is not None and retained_diagnostic_data is not math.nan:
                # Emit signal to display plots on main thread (matplotlib requires this)
                self.diagnostic_plot_requested.emit(retained_diagnostic_data)
        
        return data_folder


def main():
    """Main entry point for the application.

    Instrument selection (docs/CONFIGURABLE_INSTRUMENTS.md §7.1, §17.1): the
    --instrument CLI flag always wins; a picker dialog appears only when more
    than one instrument is registered and no flag was given; with a single
    registered instrument, startup is identical to the pre-registry app. The
    selection is fixed for the session.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="TAVI")
    parser.add_argument(
        "--instrument", metavar="ID", default=None,
        help="Instrument id to load (e.g. 'puma'); skips the startup picker.",
    )
    args, qt_args = parser.parse_known_args()  # leftover args go to Qt

    import instruments.builtin  # noqa: F401  (explicit built-in registration)
    from instruments.registry import available_instruments, get_instrument

    infos = available_instruments()
    if args.instrument is not None:
        instrument_id = args.instrument.lower()
        if instrument_id not in {info.id for info in infos}:
            print(
                f"Unknown instrument '{args.instrument}'. Available: "
                + ", ".join(info.id for info in infos),
                file=sys.stderr,
            )
            sys.exit(2)

    app = QApplication([sys.argv[0], *qt_args])

    if args.instrument is None:
        if len(infos) == 1:
            instrument_id = infos[0].id
        else:
            from gui.dialogs.instrument_picker_dialog import InstrumentPickerDialog

            instrument_id = InstrumentPickerDialog.pick(infos)
            if instrument_id is None:
                sys.exit(0)

    instrument = get_instrument(instrument_id)

    # Fail fast, with readable errors, if the registered descriptor is unrunnable.
    from instruments.validation import assert_valid_descriptor
    assert_valid_descriptor(instrument.descriptor(), runnable=True)

    window = TAVIMainWindow(instrument.descriptor())
    controller = TAVIController(window, instrument)
    # Store controller reference on window so closeEvent can access it
    window.controller = controller
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
