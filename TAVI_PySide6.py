"""Main application controller for TAVI with PySide6 GUI."""
import sys
import os
import json
import time
import datetime
import threading
import queue
import math
import mcstasscript as ms

from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit
from PySide6.QtCore import QObject, Signal, Slot, QTimer

# Import existing backend modules
from instruments.PUMA_instrument_definition import PUMA_Instrument, run_PUMA_instrument, validate_angles, mono_ana_crystals_setup

# Import TAVI core modules
from tavi.data_processing import (read_1Ddetector_file, write_parameters_to_file, 
                                   simple_plot_scan_commands, display_existing_data,
                                   read_parameters_from_file, write_1D_scan, write_2D_scan)
from tavi.utilities import parse_scan_steps, incremented_path_writing
from tavi.reciprocal_space import update_Q_from_HKL_direct, update_HKL_from_Q_direct
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
    scan_current_index_1d = Signal(int)  # current index
    scan_current_index_2d = Signal(int, int)  # idx_x, idx_y
    scan_completed = Signal()  # scan finished
    scan_auto_save = Signal()  # trigger auto-save of plot
    single_point_result = Signal(float, float)  # max_counts, total_counts for single-point scan
    
    # Signals for diagnostic plots (must run on main thread)
    diagnostic_plot_requested = Signal(object)  # McStasData object
    instrument_diagram_requested = Signal(object)  # McStas instrument object
    
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.PUMA = PUMA_Instrument()
        
        # Global variables
        self.stop_flag = False
        self.diagnostic_settings = {}
        self.current_sample_settings = {}
        
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
        
        # Initialize crystal info with default values
        self.monocris_info, self.anacris_info = mono_ana_crystals_setup("PG[002]", "PG[002]")
        
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

        # Apply initial sample frame mode state
        self.update_sample_frame_mode()
        
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
        self.window.simulation_dock.validation_button.clicked.connect(self.open_validation_window)
        
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
        self.scan_current_index_1d.connect(self.window.display_dock.set_current_scan_index)
        self.scan_current_index_2d.connect(self.window.display_dock.set_current_scan_index_2d)
        self.scan_completed.connect(self.window.display_dock.scan_complete)
        self.scan_auto_save.connect(self.window.display_dock.auto_save_plot)
        self.single_point_result.connect(self.window.display_dock.show_single_point_result)
        
        # Connect diagnostic plot signals (runs on main thread for matplotlib)
        self.diagnostic_plot_requested.connect(self._show_diagnostic_plots)
        self.instrument_diagram_requested.connect(self._show_instrument_diagram)
        
        # Connect crystal selection changes
        self.window.instrument_dock.monocris_combo.currentTextChanged.connect(self.update_monocris_info)
        self.window.instrument_dock.anacris_combo.currentTextChanged.connect(self.update_anacris_info)

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
        
        # Lattice parameters - update HKL/Q conversions
        self.window.sample_dock.lattice_a_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_b_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_c_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_alpha_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_beta_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_gamma_edit.editingFinished.connect(self.on_lattice_changed)
        # Sample frame mode toggle (HKL vs Q)
        try:
            self.window.sample_dock.sample_frame_mode_check.toggled.connect(self.on_sample_frame_mode_toggled)
        except Exception:
            pass
        # Sample alignment offsets (kappa and psi)
        self.window.sample_dock.kappa_edit.editingFinished.connect(self.on_alignment_offset_changed)
        self.window.sample_dock.psi_edit.editingFinished.connect(self.on_alignment_offset_changed)
        # Sample selection change -> update PUMA and show status
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
        # Also update on editingFinished to catch committed changes
        try:
            self.window.simulation_dock.number_neutrons_edit.editingFinished.connect(self._trigger_scan_update)
        except Exception:
            pass
    
    def setup_visual_feedback(self):
        """Set up visual feedback for all input fields to show pending/saved states."""
        # Collect all QLineEdit widgets from all docks
        line_edits = []
        
        # Instrument dock
        line_edits.extend([
            self.window.instrument_dock.mtt_edit,
            self.window.instrument_dock.stt_edit,
            self.window.instrument_dock.omega_edit,
            self.window.instrument_dock.chi_edit,
            self.window.instrument_dock.att_edit,
            self.window.instrument_dock.Ki_edit,
            self.window.instrument_dock.Ei_edit,
            self.window.instrument_dock.Kf_edit,
            self.window.instrument_dock.Ef_edit,
            self.window.instrument_dock.rhm_edit,
            self.window.instrument_dock.rvm_edit,
            self.window.instrument_dock.rha_edit,
            self.window.instrument_dock.vbl_hgap_edit,
            self.window.instrument_dock.pbl_hgap_edit,
            self.window.instrument_dock.pbl_vgap_edit,
            self.window.instrument_dock.dbl_hgap_edit,
        ])
        
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
        
        # Sample dock
        line_edits.extend([
            self.window.sample_dock.lattice_a_edit,
            self.window.sample_dock.lattice_b_edit,
            self.window.sample_dock.lattice_c_edit,
            self.window.sample_dock.lattice_alpha_edit,
            self.window.sample_dock.lattice_beta_edit,
            self.window.sample_dock.lattice_gamma_edit,
            self.window.sample_dock.kappa_edit,
            self.window.sample_dock.psi_edit,
        ])
        
        # Scan controls dock
        line_edits.extend([
            self.window.simulation_dock.number_neutrons_edit,
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
        self.stop_flag = True
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
        
        # Set data folder and metadata
        data_folder = self.window.data_control_dock.save_folder_edit.text()
        actual_folder = self.window.data_control_dock.actual_folder_label.text()
        if actual_folder:
            self.window.display_dock.set_data_folder(actual_folder)
        elif data_folder:
            self.window.display_dock.set_data_folder(
                os.path.join(self.output_directory, data_folder) if self.output_directory else data_folder
            )
        
        # Set scan metadata from current GUI values
        self.window.display_dock.set_scan_metadata(self._build_current_scan_metadata())
    
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
    
    def _build_current_scan_metadata(self):
        """Build scan metadata from current GUI values."""
        vals = self.get_gui_values()
        if not vals:
            return {}
        
        metadata = {}
        
        # Number of neutrons
        metadata['number_neutrons'] = vals.get('number_neutrons', 1000000)
        
        # Ki/Kf fixed mode
        metadata['K_fixed'] = vals.get('K_fixed', 'Ki Fixed')
        
        # Fixed E
        metadata['fixed_E'] = vals.get('fixed_E', 0)
        
        # Collimations
        metadata['alpha_1'] = vals.get('alpha_1', 'open')
        # Build alpha_2 string from checkboxes
        alpha_2_parts = []
        if vals.get('alpha_2_30'):
            alpha_2_parts.append("30'")
        if vals.get('alpha_2_40'):
            alpha_2_parts.append("40'")
        if vals.get('alpha_2_60'):
            alpha_2_parts.append("60'")
        metadata['alpha_2'] = "+".join(alpha_2_parts) if alpha_2_parts else "open"
        metadata['alpha_3'] = vals.get('alpha_3', 'open')
        metadata['alpha_4'] = vals.get('alpha_4', 'open')
        
        # Crystals
        metadata['monocris'] = vals.get('monocris', 'PG[002]')
        metadata['anacris'] = vals.get('anacris', 'PG[002]')
        
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
        
        # Sample frame mode
        try:
            metadata['sample_frame_mode'] = 'HKL' if self.window.sample_dock.sample_frame_mode_check.isChecked() else 'Q'
        except:
            metadata['sample_frame_mode'] = 'Q'
        
        # NMO and velocity selector
        metadata['NMO_installed'] = vals.get('NMO_installed', 'None')
        metadata['V_selector_installed'] = vals.get('V_selector_installed', False)
        
        return metadata
    
    def update_monocris_info(self):
        """Update monochromator crystal information."""
        monocris = self.window.instrument_dock.monocris_combo.currentText()
        anacris = self.window.instrument_dock.anacris_combo.currentText()
        self.monocris_info, _ = mono_ana_crystals_setup(monocris, anacris)
        self.update_all_variables()
    
    def update_anacris_info(self):
        """Update analyzer crystal information."""
        monocris = self.window.instrument_dock.monocris_combo.currentText()
        anacris = self.window.instrument_dock.anacris_combo.currentText()
        _, self.anacris_info = mono_ana_crystals_setup(monocris, anacris)
        self.update_all_variables()
    
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
                'monocris': self.window.instrument_dock.monocris_combo.currentText(),
                'anacris': self.window.instrument_dock.anacris_combo.currentText(),
                'rhm': float(self.window.instrument_dock.rhm_edit.text() or 0),
                'rvm': float(self.window.instrument_dock.rvm_edit.text() or 0),
                'rha': float(self.window.instrument_dock.rha_edit.text() or 0),
                'NMO_installed': self.window.instrument_dock.nmo_combo.currentText(),
                'V_selector_installed': self.window.instrument_dock.v_selector_check.isChecked(),
                'alpha_1': self.window.instrument_dock.alpha_1_combo.currentText(),
                'alpha_2_30': self.window.instrument_dock.alpha_2_30_check.isChecked(),
                'alpha_2_40': self.window.instrument_dock.alpha_2_40_check.isChecked(),
                'alpha_2_60': self.window.instrument_dock.alpha_2_60_check.isChecked(),
                'alpha_3': self.window.instrument_dock.alpha_3_combo.currentText(),
                'alpha_4': self.window.instrument_dock.alpha_4_combo.currentText(),
                # Slit apertures (in mm, convert to m for PUMA)
                'vbl_hgap': float(self.window.instrument_dock.vbl_hgap_edit.text() or 88) / 1000,
                'pbl_hgap': float(self.window.instrument_dock.pbl_hgap_edit.text() or 100) / 1000,
                'pbl_vgap': float(self.window.instrument_dock.pbl_vgap_edit.text() or 100) / 1000,
                'dbl_hgap': float(self.window.instrument_dock.dbl_hgap_edit.text() or 50) / 1000,
                'number_neutrons': int(self.window.simulation_dock.number_neutrons_edit.text() or 1000000),
                'scan_command1': self.window.simulation_dock.scan_command_1_edit.text(),
                'scan_command2': self.window.simulation_dock.scan_command_2_edit.text(),
                'diagnostic_mode': self.window.simulation_dock.diagnostic_mode_check.isChecked(),
            }
        except ValueError:
            return None
    
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
            
            from instruments.PUMA_instrument_definition import energy2k, k2angle
            
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
        """Compute ideal absolute bending radii from current angles."""
        try:
            if mtt is None:
                mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            if att is None:
                att = float(self.window.instrument_dock.att_edit.text() or 0)

            denom_m = (1 / self.PUMA.L1 + 1 / self.PUMA.L2)
            denom_a = (1 / self.PUMA.L3 + 1 / self.PUMA.L4)
            sin_m = math.sin(math.radians(mtt))
            sin_a = math.sin(math.radians(att))

            if denom_m == 0 or denom_a == 0 or sin_m == 0 or sin_a == 0:
                return None

            rhm = 2 / sin_m / denom_m
            rvm = 2 * sin_m / denom_m
            rha = 2 / sin_a / denom_a
            rva = 0.8

            if rhm < 2.0:
                rhm = 2.0
            if rvm < 0.5:
                rvm = 0.5
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

        self.window.instrument_dock.rhm_ideal_button.setText(
            f"Ideal ({'L' if rhm_locked else 'U'}): {ideal['rhm']:.3f} m"
        )
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
        """Load bending parameters from file (supports old factor-based values)."""
        ideal = self._compute_ideal_bending_values()

        if any(key in parameters for key in ("rhm_var", "rvm_var", "rha_var")):
            self.window.instrument_dock.rhm_edit.setText(str(parameters.get("rhm_var", "")))
            self.window.instrument_dock.rvm_edit.setText(str(parameters.get("rvm_var", "")))
            self.window.instrument_dock.rha_edit.setText(str(parameters.get("rha_var", "")))
            return

        if ideal:
            try:
                rhmfac = float(parameters.get("rhmfac_var", 1) or 1)
                rvmfac = float(parameters.get("rvmfac_var", 1) or 1)
                rhafac = float(parameters.get("rhafac_var", 1) or 1)
                self.window.instrument_dock.rhm_edit.setText(f"{ideal['rhm'] * rhmfac:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.rvm_edit.setText(f"{ideal['rvm'] * rvmfac:.4f}".rstrip('0').rstrip('.'))
                self.window.instrument_dock.rha_edit.setText(f"{ideal['rha'] * rhafac:.4f}".rstrip('0').rstrip('.'))
                return
            except Exception:
                pass

        self.window.instrument_dock.rhm_edit.setText("0")
        self.window.instrument_dock.rvm_edit.setText("0")
        self.window.instrument_dock.rha_edit.setText("0")

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
            from instruments.PUMA_instrument_definition import angle2k, k2energy
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
            from instruments.PUMA_instrument_definition import angle2k, k2energy
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
            from instruments.PUMA_instrument_definition import k2energy, k2angle
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
            from instruments.PUMA_instrument_definition import energy2k, k2angle
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
            from instruments.PUMA_instrument_definition import k2energy, k2angle
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
            from instruments.PUMA_instrument_definition import energy2k, k2angle
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

            q_vals, error_flags = self.PUMA.calculate_q_and_deltaE(
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
            H, K, L = update_HKL_from_Q_direct(
                vals['qx'], vals['qy'], vals['qz'],
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
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
            qx, qy, qz = update_Q_from_HKL_direct(
                H, K, L,
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
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
        """Update Q/HKL conversion when lattice parameters change."""
        # Recalculate based on sample frame mode
        if self.window.sample_dock.sample_frame_mode_check.isChecked():
            self.on_HKL_changed()
        else:
            self.on_Q_changed()

    def on_sample_frame_mode_toggled(self, checked):
        """Handle sample frame mode toggling to lock HKL or Q fields."""
        self.update_sample_frame_mode(checked)

    def update_sample_frame_mode(self, checked=None):
        """Enable/disable HKL vs Q inputs based on sample frame mode."""
        if checked is None:
            checked = self.window.sample_dock.sample_frame_mode_check.isChecked()

        hkl_enabled = bool(checked)
        q_enabled = not hkl_enabled

        self.window.scattering_dock.H_edit.setEnabled(hkl_enabled)
        self.window.scattering_dock.K_edit.setEnabled(hkl_enabled)
        self.window.scattering_dock.L_edit.setEnabled(hkl_enabled)

        self.window.scattering_dock.qx_edit.setEnabled(q_enabled)
        self.window.scattering_dock.qy_edit.setEnabled(q_enabled)
        self.window.scattering_dock.qz_edit.setEnabled(q_enabled)

        # Recalculate the dependent variables when mode changes
        if hkl_enabled:
            self.on_HKL_changed()
        else:
            self.on_Q_changed()

    def update_angles_from_q(self):
        """Update instrument/sample angles based on current Q and deltaE."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        try:
            self.updating = True
            angles_array, error_flags = self.PUMA.calculate_angles(
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
        monocris = self.window.instrument_dock.monocris_combo.currentText()
        anacris = self.window.instrument_dock.anacris_combo.currentText()
        self.monocris_info, _ = mono_ana_crystals_setup(monocris, anacris)
        self.update_all_variables()
    
    def update_anacris_info(self):
        """Update analyzer crystal information."""
        monocris = self.window.instrument_dock.monocris_combo.currentText()
        anacris = self.window.instrument_dock.anacris_combo.currentText()
        _, self.anacris_info = mono_ana_crystals_setup(monocris, anacris)
        self.update_all_variables()
    
    def on_alignment_offset_changed(self):
        """Handle changes to alignment offsets (kappa=chi offset, psi=omega offset)."""
        if self.updating:
            return
        try:
            kappa = float(self.window.sample_dock.kappa_edit.text() or 0)
            psi = float(self.window.sample_dock.psi_edit.text() or 0)
            self.PUMA.kappa = kappa
            self.PUMA.psi = psi
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
        # Instrument angles (omega = A3, 2theta = A2)
        elif var == 'a1':
            return float(self.window.instrument_dock.mtt_edit.text() or 0)
        elif var == 'a2' or var == '2theta':
            return float(self.window.instrument_dock.stt_edit.text() or 0)
        elif var == 'a3' or var == 'omega':
            return float(self.window.instrument_dock.omega_edit.text() or 0)
        elif var == 'a4':
            return float(self.window.instrument_dock.att_edit.text() or 0)
        # Sample orientation (chi, kappa, psi)
        elif var == 'chi':
            return scan_point_template[8] if len(scan_point_template) > 8 else 0
        elif var == 'kappa':
            return scan_point_template[9] if len(scan_point_template) > 9 else 0
        elif var == 'psi':
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
            num_neutrons = int(self.window.simulation_dock.number_neutrons_edit.text() or 1000000)
        except ValueError:
            num_neutrons = 1000000
        
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        
        # Get instrument name
        instrument_name = "PUMA"  # Currently only PUMA is supported
        
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
            vals.get('chi', 0), vals.get('kappa', 0), vals.get('psi', 0),
            vals.get('H', 0), vals.get('K', 0), vals.get('L', 0)
        ]
        
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltae': 3,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7,
            'chi': 8, 'kappa': 9, 'psi': 10,
            'h': 11, 'k': 12, 'l': 13,
            'a1': 0, 'a2': 1, 'a3': 2, 'a4': 3,  # Angle mode
            '2theta': 1, 'omega': 2,
        }
        
        # Determine scan mode
        scan_mode = self._determine_scan_mode(cmd1, cmd2)
        
        # Create temp PUMA for validation - use GUI values, not self.PUMA
        # (self.PUMA may not be updated until run_simulation is called)
        puma_instance = PUMA_Instrument()
        puma_instance.monocris = vals.get('monocris', 'PG[002]')
        puma_instance.anacris = vals.get('anacris', 'PG[002]')
        puma_instance.K_fixed = vals.get('K_fixed', 'Kf Fixed')
        puma_instance.fixed_E = vals.get('fixed_E', 14.7)
        
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
                    
                    valid = self._validate_scan_point(scan_point, scan_mode, vals, puma_instance)
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
                        
                        valid = self._validate_scan_point(scan_point, scan_mode, vals, puma_instance)
                        if valid:
                            valid_count += 1
                        else:
                            invalid_count += 1
        except Exception as e:
            # If parsing fails, return 0 valid points
            return (0, 0)
        
        return (valid_count, invalid_count)
    
    def _validate_scan_point(self, scan_point: list, scan_mode: str, vals: dict, puma_instance) -> bool:
        """Validate a single scan point.
        
        Args:
            scan_point: List of scan parameters
            scan_mode: One of 'momentum', 'rlu', 'angle', 'orientation'
            vals: GUI values dictionary
            puma_instance: PUMA instrument instance (configured with GUI values)
            
        Returns:
            True if point is valid, False otherwise
        """
        try:
            if scan_mode == "momentum":
                qx, qy, qz, deltaE = scan_point[:4]
                _, error_flags = puma_instance.calculate_angles(
                    qx, qy, qz, deltaE, puma_instance.fixed_E, puma_instance.K_fixed,
                    puma_instance.monocris, puma_instance.anacris
                )
                return not error_flags
            elif scan_mode == "rlu":
                H, K, L = scan_point[11], scan_point[12], scan_point[13]
                deltaE = scan_point[3]
                qx, qy, qz = update_Q_from_HKL_direct(
                    H, K, L,
                    vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                    vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
                )
                _, error_flags = puma_instance.calculate_angles(
                    qx, qy, qz, deltaE, puma_instance.fixed_E, puma_instance.K_fixed,
                    puma_instance.monocris, puma_instance.anacris
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
            # Default based on sample frame mode
            try:
                if self.window.sample_dock.sample_frame_mode_check.isChecked():
                    return "rlu"
            except Exception:
                pass
            return "momentum"
    
    def _check_current_point_validity(self) -> tuple:
        """Check if the current single point (no scan) is valid.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            vals = self.get_gui_values()
            if not vals:
                return (False, "Could not get GUI values")
            
            # Use GUI values directly, not self.PUMA (may not be updated)
            puma_instance = PUMA_Instrument()
            puma_instance.monocris = vals.get('monocris', 'PG[002]')
            puma_instance.anacris = vals.get('anacris', 'PG[002]')
            puma_instance.K_fixed = vals.get('K_fixed', 'Kf Fixed')
            puma_instance.fixed_E = vals.get('fixed_E', 14.7)
            
            _, error_flags = puma_instance.calculate_angles(
                vals['qx'], vals['qy'], vals['qz'], vals['deltaE'],
                puma_instance.fixed_E, puma_instance.K_fixed,
                puma_instance.monocris, puma_instance.anacris
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
            self.PUMA.omega = omega
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
            self.PUMA.chi = chi
            self.print_to_message_center(f"Sample χ updated: {chi}° (out-of-plane)")
            # Chi affects qz - trigger recalculation
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid chi value")
    
    def on_load_misalignment_hash(self):
        """Handle loading misalignment from hash - apply hidden values to instrument."""
        if self.window.misalignment_dock.has_misalignment():
            mis_omega, mis_chi = self.window.misalignment_dock.get_loaded_misalignment()
            self.PUMA.set_misalignment(mis_omega=mis_omega, mis_chi=mis_chi)
            self.print_to_message_center("Hidden misalignment loaded and applied to instrument")
    
    def on_clear_misalignment(self):
        """Handle clearing misalignment - reset hidden values on instrument."""
        self.PUMA.set_misalignment(mis_omega=0, mis_chi=0)
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
    
    def configure_diagnostics(self):
        """Open diagnostics configuration window."""
        dialog = DiagnosticConfigDialog(self.window, self.diagnostic_settings)
        if dialog.exec():
            # User clicked Save and Close
            self.diagnostic_settings = dialog.get_settings()
            # Update PUMA instrument with new settings
            self.PUMA.update_diagnostic_settings(self.diagnostic_settings)
            # Save parameters to persist the settings
            self.save_parameters()
            self.print_to_message_center("Diagnostic settings saved")
        else:
            self.print_to_message_center("Diagnostic configuration cancelled")
    
    def configure_sample(self):
        """Open sample configuration window."""
        # TODO: Implement sample configuration dialog
        self.print_to_message_center("Sample configuration window not yet implemented")
    
    def open_validation_window(self):
        """Open validation window."""
        # TODO: Implement validation window
        self.print_to_message_center("Validation window not yet implemented")
    
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
        
        # Sample frame mode
        if 'sample_frame_mode' in params:
            metadata['sample_frame_mode'] = params['sample_frame_mode']
        
        # NMO and velocity selector
        if 'NMO_installed' in params:
            metadata['NMO_installed'] = params['NMO_installed']
        if 'V_selector_installed' in params:
            metadata['V_selector_installed'] = params.get('V_selector_installed', False)
        
        return metadata
    
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
            "number_neutrons_var": self.window.simulation_dock.number_neutrons_edit.text(),
            "K_fixed_var": self.window.scattering_dock.K_fixed_combo.currentText(),
            "NMO_installed_var": self.window.instrument_dock.nmo_combo.currentText(),
            "V_selector_installed_var": self.window.instrument_dock.v_selector_check.isChecked(),
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
            "monocris_var": self.window.instrument_dock.monocris_combo.currentText(),
            "anacris_var": self.window.instrument_dock.anacris_combo.currentText(),
            "alpha_1_var": self.window.instrument_dock.alpha_1_combo.currentText(),
            "alpha_2_30_var": self.window.instrument_dock.alpha_2_30_check.isChecked(),
            "alpha_2_40_var": self.window.instrument_dock.alpha_2_40_check.isChecked(),
            "alpha_2_60_var": self.window.instrument_dock.alpha_2_60_check.isChecked(),
            "alpha_3_var": self.window.instrument_dock.alpha_3_combo.currentText(),
            "alpha_4_var": self.window.instrument_dock.alpha_4_combo.currentText(),
            # Slit apertures (stored in mm)
            "vbl_hgap_var": self.window.instrument_dock.vbl_hgap_edit.text(),
            "pbl_hgap_var": self.window.instrument_dock.pbl_hgap_edit.text(),
            "pbl_vgap_var": self.window.instrument_dock.pbl_vgap_edit.text(),
            "dbl_hgap_var": self.window.instrument_dock.dbl_hgap_edit.text(),
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
            "sample_frame_mode_var": self.window.sample_dock.sample_frame_mode_check.isChecked(),
            "scan_command_var1": self.window.simulation_dock.scan_command_1_edit.text(),
            "scan_command_var2": self.window.simulation_dock.scan_command_2_edit.text(),
            "save_folder_var": self.window.data_control_dock.save_folder_edit.text(),
            "load_folder_var": self.window.data_control_dock.load_folder_edit.text(),
            "diagnostic_settings": self.diagnostic_settings,
            "current_sample_settings": self.current_sample_settings,
            "sample_label_var": self.window.sample_dock.sample_combo.currentText() if hasattr(self.window.sample_dock, 'sample_combo') else "None"
        }
        # Ensure config directory exists
        os.makedirs("config", exist_ok=True)
        with open("config/parameters.json", "w") as file:
            json.dump(parameters, file)
        self.print_to_message_center("Parameters saved successfully")
    
    def load_parameters(self):
        """Load parameters from JSON file."""
        if os.path.exists("config/parameters.json"):
            with open("config/parameters.json", "r") as file:
                parameters = json.load(file)
                
                # Block signals during loading to prevent premature validation
                self.window.simulation_dock.scan_command_1_edit.blockSignals(True)
                self.window.simulation_dock.scan_command_2_edit.blockSignals(True)
                
                # Set GUI values from parameters
                self.window.instrument_dock.monocris_combo.setCurrentText(parameters.get("monocris_var", "PG[002]"))
                self.window.instrument_dock.anacris_combo.setCurrentText(parameters.get("anacris_var", "PG[002]"))
                self.window.instrument_dock.mtt_edit.setText(str(parameters.get("mtt_var", "30")))
                self.window.instrument_dock.stt_edit.setText(str(parameters.get("stt_var", "30")))
                self.window.instrument_dock.omega_edit.setText(str(parameters.get("omega_var", 0)))
                self.window.instrument_dock.chi_edit.setText(str(parameters.get("chi_var", 0)))
                self.window.instrument_dock.att_edit.setText(str(parameters.get("att_var", 30)))
                self.window.instrument_dock.Ki_edit.setText(str(parameters.get("Ki_var", "2.662")))
                self.window.instrument_dock.Kf_edit.setText(str(parameters.get("Kf_var", "2.662")))
                self.window.instrument_dock.Ei_edit.setText(str(parameters.get("Ei_var", "14.7")))
                self.window.instrument_dock.Ef_edit.setText(str(parameters.get("Ef_var", "14.7")))
                self.window.instrument_dock.nmo_combo.setCurrentText(parameters.get("NMO_installed_var", "None"))
                self.window.instrument_dock.v_selector_check.setChecked(parameters.get("V_selector_installed_var", False))
                self.window.instrument_dock.alpha_1_combo.setCurrentText(str(parameters.get("alpha_1_var", 40)))
                self.window.instrument_dock.alpha_2_30_check.setChecked(parameters.get("alpha_2_30_var", False))
                self.window.instrument_dock.alpha_2_40_check.setChecked(parameters.get("alpha_2_40_var", True))
                self.window.instrument_dock.alpha_2_60_check.setChecked(parameters.get("alpha_2_60_var", False))
                self.window.instrument_dock.alpha_3_combo.setCurrentText(str(parameters.get("alpha_3_var", 30)))
                self.window.instrument_dock.alpha_4_combo.setCurrentText(str(parameters.get("alpha_4_var", 30)))
                # Slit apertures (in mm)
                self.window.instrument_dock.vbl_hgap_edit.setText(str(parameters.get("vbl_hgap_var", "88")))
                self.window.instrument_dock.pbl_hgap_edit.setText(str(parameters.get("pbl_hgap_var", "100")))
                self.window.instrument_dock.pbl_vgap_edit.setText(str(parameters.get("pbl_vgap_var", "100")))
                self.window.instrument_dock.dbl_hgap_edit.setText(str(parameters.get("dbl_hgap_var", "50")))

                # Load absolute bending values (backward-compatible with factor-based params)
                self._load_bending_parameters(parameters)

                # Restore ideal lock state
                self._apply_bending_lock_state(
                    parameters.get("rhm_ideal_locked", False),
                    parameters.get("rvm_ideal_locked", False),
                    parameters.get("rha_ideal_locked", False),
                )
                
                self.window.simulation_dock.number_neutrons_edit.setText(str(parameters.get("number_neutrons_var", 1e8)))
                self.window.scattering_dock.K_fixed_combo.setCurrentText(parameters.get("K_fixed_var", "Kf Fixed"))
                self.window.scattering_dock.fixed_E_edit.setText(str(parameters.get("fixed_E_var", 14.7)))
                self.window.scattering_dock.qx_edit.setText(str(parameters.get("qx_var", 2)))
                self.window.scattering_dock.qy_edit.setText(str(parameters.get("qy_var", 0)))
                self.window.scattering_dock.qz_edit.setText(str(parameters.get("qz_var", 0)))
                # HKL values
                self.window.scattering_dock.H_edit.setText(str(parameters.get("H_var", 1)))
                self.window.scattering_dock.K_edit.setText(str(parameters.get("K_var", 0)))
                self.window.scattering_dock.L_edit.setText(str(parameters.get("L_var", 0)))
                self.window.scattering_dock.deltaE_edit.setText(str(parameters.get("deltaE_var", 5.25)))
                self.window.simulation_dock.diagnostic_mode_check.setChecked(parameters.get("diagnostic_mode_var", True))
                self.window.simulation_dock.scan_command_1_edit.setText(parameters.get("scan_command_var1", ""))
                self.window.simulation_dock.scan_command_2_edit.setText(parameters.get("scan_command_var2", ""))
                
                self.window.sample_dock.lattice_a_edit.setText(str(parameters.get("lattice_a_var", 4.05)))
                self.window.sample_dock.lattice_b_edit.setText(str(parameters.get("lattice_b_var", 4.05)))
                self.window.sample_dock.lattice_c_edit.setText(str(parameters.get("lattice_c_var", 4.05)))
                self.window.sample_dock.lattice_alpha_edit.setText(str(parameters.get("lattice_alpha_var", 90)))
                self.window.sample_dock.lattice_beta_edit.setText(str(parameters.get("lattice_beta_var", 90)))
                self.window.sample_dock.lattice_gamma_edit.setText(str(parameters.get("lattice_gamma_var", 90)))
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
                        self.PUMA.set_misalignment(omega_m, chi_m, psi_m)
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
                self.window.sample_dock.sample_frame_mode_check.setChecked(
                    parameters.get("sample_frame_mode_var", False)
                )
                # Restore sample selection if present
                try:
                    sample_label = parameters.get("sample_label_var", "None")
                    if hasattr(self.window.sample_dock, 'sample_combo'):
                        self.window.sample_dock.sample_combo.setCurrentText(sample_label)
                except Exception:
                    pass
                # Set display and folder fields (use sensible defaults if missing)
                folder_suggestion = os.path.join(self.output_directory, "initial_testing")
                self.window.data_control_dock.save_folder_edit.setText(parameters.get("save_folder_var", folder_suggestion))
                self.window.data_control_dock.load_folder_edit.setText(parameters.get("load_folder_var", folder_suggestion))
                
                # Load diagnostic settings with defaults for any missing keys
                default_diag = DiagnosticConfigDialog.get_default_settings()
                loaded_diag = parameters.get("diagnostic_settings", {})
                # Merge: use loaded value if present, else default
                self.diagnostic_settings = {**default_diag, **loaded_diag}
                self.current_sample_settings = parameters.get("current_sample_settings", {})

                self.update_sample_frame_mode()

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
        
        self.window.instrument_dock.monocris_combo.setCurrentText("PG[002]")
        self.window.instrument_dock.anacris_combo.setCurrentText("PG[002]")
        self.window.instrument_dock.mtt_edit.setText("30")
        self.window.instrument_dock.stt_edit.setText("30")
        self.window.instrument_dock.omega_edit.setText("0")
        self.window.instrument_dock.chi_edit.setText("0")
        self.window.instrument_dock.att_edit.setText("30")
        self.window.instrument_dock.Ki_edit.setText("2.662")
        self.window.instrument_dock.Kf_edit.setText("2.662")
        self.window.instrument_dock.Ei_edit.setText("14.7")
        self.window.instrument_dock.Ef_edit.setText("14.7")
        self.window.instrument_dock.nmo_combo.setCurrentText("None")
        self.window.instrument_dock.v_selector_check.setChecked(False)
        self.window.instrument_dock.alpha_1_combo.setCurrentText("40")
        self.window.instrument_dock.alpha_2_30_check.setChecked(False)
        self.window.instrument_dock.alpha_2_40_check.setChecked(True)
        self.window.instrument_dock.alpha_2_60_check.setChecked(False)
        self.window.instrument_dock.alpha_3_combo.setCurrentText("30")
        self.window.instrument_dock.alpha_4_combo.setCurrentText("30")
        # Slit apertures (in mm) - PUMA defaults
        self.window.instrument_dock.vbl_hgap_edit.setText("88")
        self.window.instrument_dock.pbl_hgap_edit.setText("100")
        self.window.instrument_dock.pbl_vgap_edit.setText("100")
        self.window.instrument_dock.dbl_hgap_edit.setText("50")

        # Set default absolute bending to ideal values
        self.update_ideal_bending_buttons()
        self.apply_ideal_bending_values()
        
        self.window.simulation_dock.number_neutrons_edit.setText("1000000")
        self.window.scattering_dock.K_fixed_combo.setCurrentText("Kf Fixed")
        self.window.scattering_dock.fixed_E_edit.setText("14.7")
        self.window.scattering_dock.qx_edit.setText("2")
        self.window.scattering_dock.qy_edit.setText("0")
        self.window.scattering_dock.qz_edit.setText("0")
        # Set HKL defaults (computed from Q and lattice)
        self.window.scattering_dock.H_edit.setText("1")
        self.window.scattering_dock.K_edit.setText("0")
        self.window.scattering_dock.L_edit.setText("0")
        self.window.scattering_dock.deltaE_edit.setText("5.25")
        self.window.simulation_dock.diagnostic_mode_check.setChecked(True)
        
        self.window.sample_dock.lattice_a_edit.setText("3.78")
        self.window.sample_dock.lattice_b_edit.setText("3.78")
        self.window.sample_dock.lattice_c_edit.setText("5.49")
        self.window.sample_dock.lattice_alpha_edit.setText("90")
        self.window.sample_dock.lattice_beta_edit.setText("90")
        self.window.sample_dock.lattice_gamma_edit.setText("90")
        # Sample alignment offset defaults
        self.window.sample_dock.kappa_edit.setText("0")
        self.window.sample_dock.psi_edit.setText("0")
        self.window.sample_dock.sample_frame_mode_check.setChecked(False)
        self.window.simulation_dock.scan_command_1_edit.setText("qx 2 2.2 0.1")
        self.window.simulation_dock.scan_command_2_edit.setText("deltaE 3 7 0.25")
        
        # Set default folder paths
        folder_suggestion = os.path.join(self.output_directory, "initial_testing")
        self.window.data_control_dock.save_folder_edit.setText(folder_suggestion)
        self.window.data_control_dock.load_folder_edit.setText(folder_suggestion)
        
        self.diagnostic_settings = DiagnosticConfigDialog.get_default_settings()
        self.current_sample_settings = {}
        self.update_sample_frame_mode()
        # Ensure sample defaults to None in GUI
        try:
            if hasattr(self.window.sample_dock, 'sample_combo'):
                self.window.sample_dock.sample_combo.setCurrentText("None")
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
        
        self.stop_flag = False
        
        # Reset progress bar and show initializing state
        self.window.simulation_dock.progress_bar.setValue(0)
        self.window.simulation_dock.progress_label.setText("Initializing...")
        self.window.simulation_dock.remaining_time_label.setText("Estimated Remaining Time: calculating...")
        
        data_folder = self.window.data_control_dock.save_folder_edit.text()
        simulation_thread = threading.Thread(target=self.run_simulation, args=(data_folder,))
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
            self.PUMA.sample_key = key
            self.current_sample_settings = {"sample_label": label, "sample_key": key}
            self.print_to_message_center(f"Sample selection changed: {label} ({key})")
        except Exception as e:
            self.print_to_message_center(f"Sample selection change failed: {e}")
    
    def stop_simulation(self):
        """Stop the running simulation."""
        self.stop_flag = True
        self.print_to_message_center("Stop requested...")
    
    def run_simulation(self, data_folder):
        """Run the full simulation."""
        self.message_printed.emit("Starting simulation...")
        self.save_parameters()
        
        # Get the output folder from the text box
        data_folder = self.window.data_control_dock.save_folder_edit.text()
        # If the folder already exists, increment instead
        new_data_folder = incremented_path_writing(self.output_directory, data_folder)
        # Update actual folder label
        self.window.data_control_dock.actual_folder_label.setText(new_data_folder)
        data_folder = new_data_folder
        
        # Get all parameters from GUI
        vals = self.get_gui_values()
        if not vals:
            self.message_printed.emit("Error: Could not get GUI values")
            return
        
        # Configure PUMA instrument
        self.PUMA.K_fixed = vals['K_fixed']
        self.PUMA.NMO_installed = vals['NMO_installed']
        self.PUMA.V_selector_installed = vals['V_selector_installed']
        self.PUMA.rhm = vals['rhm']
        self.PUMA.rvm = vals['rvm']
        self.PUMA.rha = vals['rha']
        self.PUMA.rva = 0.8
        if self.PUMA.NMO_installed != "None":
            self.PUMA.rhm = 0
            self.PUMA.rvm = 0
        self.PUMA.fixed_E = vals['fixed_E']
        self.PUMA.monocris = vals['monocris']
        self.PUMA.anacris = vals['anacris']
        # Set selected sample key from GUI sample dropdown (internal instrument name)
        try:
            self.PUMA.sample_key = self.window.sample_dock.get_selected_sample_key()
        except Exception:
            self.PUMA.sample_key = None
        self.PUMA.alpha_1 = float(vals['alpha_1'])
        self.PUMA.alpha_2 = [
            30 if vals['alpha_2_30'] else 0,
            40 if vals['alpha_2_40'] else 0,
            60 if vals['alpha_2_60'] else 0
        ]
        self.PUMA.alpha_3 = float(vals['alpha_3'])
        self.PUMA.alpha_4 = float(vals['alpha_4'])
        # Slit apertures (already in meters from get_gui_values)
        self.PUMA.vbl_hgap = vals['vbl_hgap']
        self.PUMA.pbl_hgap = vals['pbl_hgap']
        self.PUMA.pbl_vgap = vals['pbl_vgap']
        self.PUMA.dbl_hgap = vals['dbl_hgap']
        
        number_neutrons = vals['number_neutrons']
        scan_command1 = vals['scan_command1']
        scan_command2 = vals['scan_command2']
        diagnostic_mode = vals['diagnostic_mode']
        
        # Check if relative scan mode is enabled for each command
        relative_mode_1 = self.window.simulation_dock.relative_1_button.isChecked()
        relative_mode_2 = self.window.simulation_dock.relative_2_button.isChecked()
        
        # Write parameters to file
        write_parameters_to_file(data_folder, vals)
        
        # Initialize scan arrays
        scan_parameter_input = []
        
        # Determine scan mode
        scan_mode = "momentum"  # Default
        if scan_command1:
            try:
                var_name_probe, _ = parse_scan_steps(scan_command1)
                var_name_probe = self.normalize_scan_variable(var_name_probe)
                if var_name_probe in ["qx", "qy", "qz"]:
                    scan_mode = "momentum"
                elif var_name_probe in ["H", "K", "L"]:
                    scan_mode = "rlu"
                elif var_name_probe in ["A1", "A2", "A3", "A4", "omega", "2theta"]:
                    scan_mode = "angle"
                elif var_name_probe in ["chi"]:
                    scan_mode = "orientation"
            except Exception:
                pass
        
        # Mapping for scannable parameters
        # Indices: 0-3: Q/HKL/angles, 4-7: bending, 8-10: sample orientation (chi, kappa, psi)
        # Note: omega maps to same index as A3, 2theta maps to same index as A2
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
            'H': 0, 'K': 1, 'L': 2, 'deltaE': 3,
            'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,
            'omega': 2, '2theta': 1,  # omega = A3 (index 2), 2theta = A2 (index 1)
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
            # For angle scans, use current instrument angles from GUI
            try:
                A1_current = float(self.window.instrument_dock.mtt_edit.text() or 0)
                A2_current = float(self.window.instrument_dock.stt_edit.text() or 0)
                A3_current = float(self.window.instrument_dock.omega_edit.text() or 0)
                A4_current = float(self.window.instrument_dock.att_edit.text() or 0)
                scan_point_template[:4] = [A1_current, A2_current, A3_current, A4_current]
            except ValueError:
                scan_point_template[:4] = [0, 0, 0, 0]
        elif scan_mode == "orientation":
            # For orientation scans, use current Q values but scan chi/kappa/psi
            # Note: omega is normalized to A3, so omega scans work via angle mode
            scan_point_template[:4] = [vals['qx'], vals['qy'], vals['qz'], vals['deltaE']]
        # Set default chi from instrument_dock, kappa/psi from sample_dock
        # Note: omega is same as A3, no separate storage needed
        try:
            scan_point_template[8] = float(self.window.instrument_dock.chi_edit.text() or 0)
            scan_point_template[9] = float(self.window.sample_dock.kappa_edit.text() or 0)
            scan_point_template[10] = float(self.window.sample_dock.psi_edit.text() or 0)
        except ValueError:
            pass
        
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
        
        puma_instance = PUMA_Instrument()
        variable_name1 = ""
        variable_name2 = ""
        
        # Arrays to track valid/invalid points for display
        valid_mask_1d = []  # For 1D: bool list - True if point is valid
        valid_mask_2d = None  # For 2D: 2D list of bools
        array_values1 = []
        array_values2 = []
        
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
                if scan_mode == "momentum":
                    _, error_flags = puma_instance.calculate_angles(
                        *scan_point[:4], self.PUMA.fixed_E, self.PUMA.K_fixed, 
                        self.PUMA.monocris, self.PUMA.anacris
                    )
                elif scan_mode == "rlu":
                    qx, qy, qz = update_Q_from_HKL_direct(
                        scan_point[0], scan_point[1], scan_point[2],
                        vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                        vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
                    )
                    _, error_flags = puma_instance.calculate_angles(
                        qx, qy, qz, scan_point[3], self.PUMA.fixed_E, 
                        self.PUMA.K_fixed, self.PUMA.monocris, self.PUMA.anacris
                    )
                else:
                    error_flags = []
                if not error_flags:
                    valid_mask_1d[idx] = True
                    # Store as tuple (scan_point, idx_1d) for consistency with 2D
                    scan_parameter_input.append((scan_point, idx))
            
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
            
            # Initialize 2D valid mask
            valid_mask_2d = [[False] * len(array_values1) for _ in range(len(array_values2))]
            
            for idx_y, value2 in enumerate(array_values2):
                for idx_x, value1 in enumerate(array_values1):
                    scan_point = scan_point_template[:]
                    scan_point[variable_to_index[variable_name1]] = value1
                    scan_point[variable_to_index[variable_name2]] = value2
                    if scan_mode == "momentum":
                        _, error_flags = puma_instance.calculate_angles(
                            *scan_point[:4], self.PUMA.fixed_E, self.PUMA.K_fixed,
                            self.PUMA.monocris, self.PUMA.anacris
                        )
                    elif scan_mode == "rlu":
                        qx, qy, qz = update_Q_from_HKL_direct(
                            scan_point[0], scan_point[1], scan_point[2],
                            vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                            vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
                        )
                        _, error_flags = puma_instance.calculate_angles(
                            qx, qy, qz, scan_point[3], self.PUMA.fixed_E,
                            self.PUMA.K_fixed, self.PUMA.monocris, self.PUMA.anacris
                        )
                    else:
                        error_flags = []
                    if not error_flags:
                        valid_mask_2d[idx_y][idx_x] = True
                        scan_parameter_input.append((scan_point, idx_x, idx_y))
            
            # Initialize display dock for 2D scan
            self.scan_initialized.emit('2D', list(array_values1), [], variable_name1,
                                       variable_name2, list(array_values2), valid_mask_2d)
        
        # Track if this is a 2D scan
        is_2d_scan = scan_command2 and scan_command1
        
        # Run the scans
        start_time = time.time()
        total_scans = len(scan_parameter_input)
        self.message_printed.emit(f"Running {total_scans} scan points...")
        
        # Show pre-scan estimate based on historical data
        instrument_name = "PUMA"
        total_est, compile_est, _ = self.runtime_tracker.estimate_total_time(
            instrument_name, total_scans, number_neutrons
        )
        if total_est is not None:
            est_str = RuntimeTracker.format_time(total_est)
            self.window.simulation_dock.update_pre_scan_estimate(est_str)
            self.message_printed.emit(f"Estimated total time: {est_str}")
        
        total_counts = 0
        max_counts = 0
        
        # Track individual scan times for runtime recording
        scan_times = []  # List of (scan_index, elapsed_time_for_this_scan)
        
        # Data collection for output files
        import numpy as np
        if is_2d_scan:
            # For 2D scans: store counts in a 2D grid
            counts_grid = np.full((len(array_values2), len(array_values1)), np.nan)
        else:
            # For 1D scans: store x values and counts as parallel arrays
            scan_x_values = []
            scan_counts = []
        
        for i, scan_item in enumerate(scan_parameter_input):
            scan_start_time = time.time()  # Track start time for this scan point
            
            if self.stop_flag:
                self.message_printed.emit("Simulation stopped by user.")
                self.scan_completed.emit()
                return data_folder
            
            # Extract scan point and indices (both 1D and 2D now use tuples)
            if is_2d_scan:
                scans, idx_x, idx_y = scan_item
                # Emit current scan position for 2D
                self.scan_current_index_2d.emit(idx_x, idx_y)
                idx_1d = -1  # Not used for 2D
            else:
                scans, idx_1d = scan_item
                # Emit current scan position for 1D
                self.scan_current_index_1d.emit(idx_1d)
                idx_x, idx_y = -1, -1  # Not used for 1D
            
            # Extract scannable parameters and calculate angles
            error_flags = []
            if scan_mode == "momentum":
                qx, qy, qz, deltaE = scans[:4]
                angles_array, error_flags = self.PUMA.calculate_angles(
                    qx, qy, qz, deltaE, self.PUMA.fixed_E, self.PUMA.K_fixed,
                    self.PUMA.monocris, self.PUMA.anacris
                )
                if not error_flags:
                    mtt, stt, sth, saz, att = angles_array
                    self.PUMA.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
            elif scan_mode == "rlu":
                H, K, L, deltaE = scans[:4]
                qx, qy, qz = update_Q_from_HKL_direct(
                    H, K, L, vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                    vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
                )
                angles_array, error_flags = self.PUMA.calculate_angles(
                    qx, qy, qz, deltaE, self.PUMA.fixed_E, self.PUMA.K_fixed,
                    self.PUMA.monocris, self.PUMA.anacris
                )
                if not error_flags:
                    mtt, stt, sth, saz, att = angles_array
                    self.PUMA.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
            elif scan_mode == "orientation":
                # Orientation scan: calculate angles from Q, then apply omega/chi from scan
                qx, qy, qz, deltaE = scans[:4]
                angles_array, error_flags = self.PUMA.calculate_angles(
                    qx, qy, qz, deltaE, self.PUMA.fixed_E, self.PUMA.K_fixed,
                    self.PUMA.monocris, self.PUMA.anacris
                )
                if not error_flags:
                    mtt, stt, sth, saz, att = angles_array
                    self.PUMA.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
            else:  # Angle mode
                A1, A2, A3, A4 = scans[:4]
                self.PUMA.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)
                # In angle mode, use deltaE from GUI since we're not calculating from Q
                deltaE = vals['deltaE']
                # Set placeholder variables for logging (not calculated in angle mode)
                mtt, stt, sth, att = A1, A2, A3, A4
                qx, qy, qz = 0, 0, 0  # Not applicable in angle mode
            
            rhm, rvm, rha, rva = scans[4], scans[5], scans[6], scans[7]
            chi_scan, kappa_scan, psi_scan = scans[8], scans[9], scans[10]
            
            # omega = A3 (they are the same angle)
            # In angle mode, omega comes from A3; in momentum/rlu modes, from calculated sth
            if scan_mode == "angle":
                omega_scan = scans[2]  # A3 position in scans array
            elif scan_mode in ["momentum", "rlu"] and not error_flags:
                omega_scan = sth  # omega displays the calculated sample theta
            elif scan_mode == "orientation":
                omega_scan = sth if not error_flags else vals.get('omega', 0)
            else:
                omega_scan = 0
            
            # Check if bending parameters are part of scan commands; if not, use current PUMA values
            if 'rhm' not in [variable_name1, variable_name2]:
                rhm = self.PUMA.rhm
            if 'rvm' not in [variable_name1, variable_name2]:
                rvm = self.PUMA.rvm
            if 'rha' not in [variable_name1, variable_name2]:
                rha = self.PUMA.rha
            if 'rva' not in [variable_name1, variable_name2]:
                rva = self.PUMA.rva
            
            # Set orientation parameters - always apply to PUMA
            # If scanning, use scan value; otherwise use value from scan_point_template (from GUI)
            self.PUMA.omega = omega_scan
            self.PUMA.chi = chi_scan
            self.PUMA.kappa = kappa_scan
            self.PUMA.psi = psi_scan
            
            # Update crystal bending
            self.PUMA.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)
            
            # Generate scan folder name (simple sequential format)
            scan_folder = os.path.join(data_folder, f"scan_{i:04d}")
            
            # Log scan parameters before running
            orientation_info = f"ω={omega_scan:.2f}, χ={chi_scan:.2f}, ψ={psi_scan:.2f}, κ={kappa_scan:.2f}"
            if scan_mode == "momentum":
                message = (f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
                           f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
                           f"Orientation: {orientation_info}")
            elif scan_mode == "rlu":
                message = (f"Scan parameters - H: {H}, K: {K}, L: {L}, deltaE: {deltaE}\n"
                           f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
                           f"Orientation: {orientation_info}")
            elif scan_mode == "orientation":
                message = (f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
                           f"Orientation: {orientation_info}\n"
                           f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}")
            else:  # angle mode
                message = (f"Scan parameters - A1: {self.PUMA.A1}, A2: {self.PUMA.A2}, A3: {self.PUMA.A3}, A4: {self.PUMA.A4}\n"
                           f"rhm: {rhm:.2f}, rvm: {rvm:.2f}, rha: {rha:.2f}, rva: {rva:.2f}\n"
                           f"Orientation: {orientation_info}")
            self.message_printed.emit(message)
            
            # Run the PUMA simulation
            # Returns (data, error_flags, instrument) where instrument is set if diagram display is requested
            if diagnostic_mode:
                data, error_flags, instrument_for_diagram = run_PUMA_instrument(
                    self.PUMA, number_neutrons, deltaE, diagnostic_mode, 
                    self.diagnostic_settings, scan_folder, i
                )
            else:
                data, error_flags, instrument_for_diagram = run_PUMA_instrument(
                    self.PUMA, number_neutrons, deltaE, False, {}, scan_folder, i
                )
            
            # Show instrument diagram if requested (via signal to main thread)
            if instrument_for_diagram is not None:
                self.instrument_diagram_requested.emit(instrument_for_diagram)
            
            # Check for errors
            if error_flags:
                message = f"Scan failed, error flags: {error_flags}"
                self.message_printed.emit(message)
            else:
                # Build scan-specific parameters for this point
                scan_point_params = {
                    'scan_index': i,
                    'qx': qx if scan_mode in ["momentum", "orientation"] else None,
                    'qy': qy if scan_mode in ["momentum", "orientation"] else None,
                    'qz': qz if scan_mode in ["momentum", "orientation"] else None,
                    'deltaE': deltaE,
                    'H': H if scan_mode == "rlu" else None,
                    'K': K if scan_mode == "rlu" else None,
                    'L': L if scan_mode == "rlu" else None,
                    'mtt': mtt,
                    'stt': stt,
                    'sth': sth,
                    'att': att,
                    'rhm': rhm,
                    'rvm': rvm,
                    'rha': rha,
                    'rva': rva,
                    'omega': omega_scan,
                    'chi': chi_scan,
                    'psi': psi_scan,
                    'kappa': kappa_scan,
                    'scan_mode': scan_mode,
                    'scan_command1': scan_command1,
                    'scan_command2': scan_command2,
                    'number_neutrons': number_neutrons,
                }
                # Merge with full GUI vals for completeness
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
            scan_times.append(scan_elapsed)
            
            # Emit progress signals
            self.progress_updated.emit(i + 1, total_scans)
            self.counts_updated.emit(max_counts, total_counts)
            
            # Calculate elapsed time and remaining time - ignore first scan (compilation overhead)
            elapsed_time = time.time() - start_time
            # Emit elapsed time for UI
            try:
                elapsed_str = RuntimeTracker.format_time(elapsed_time)
                self.elapsed_time_updated.emit(elapsed_str)
            except Exception:
                pass
            if i == 0:
                # After first scan, use historical data for estimation if available
                _, run_time_per_point = self.runtime_tracker.get_estimates(instrument_name, number_neutrons)
                if run_time_per_point is not None and total_scans > 1:
                    remaining_time = run_time_per_point * (total_scans - 1)
                else:
                    remaining_time = scan_elapsed * (total_scans - 1)
            else:
                # For subsequent scans, use average of scans 2+ (excluding first/compile scan)
                subsequent_times = scan_times[1:]  # Exclude first scan
                avg_time_per_scan = sum(subsequent_times) / len(subsequent_times)
                remaining_scans = total_scans - (i + 1)
                remaining_time = avg_time_per_scan * remaining_scans
            
            hours = int(remaining_time // 3600)
            minutes = int((remaining_time % 3600) // 60)
            seconds = int(remaining_time % 60)
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.remaining_time_updated.emit(time_str)
        
        # Record runtime data for future estimates (only if scan completed normally)
        if scan_times and not self.stop_flag:
            total_time = time.time() - start_time
            first_scan_time = scan_times[0] if scan_times else 0
            
            # Calculate average time for subsequent scans (excluding first)
            if len(scan_times) > 1:
                avg_subsequent_time = sum(scan_times[1:]) / len(scan_times[1:])
            else:
                # Only one scan point - use first scan time as both
                avg_subsequent_time = first_scan_time
            
            self.runtime_tracker.add_record(
                instrument_name=instrument_name,
                num_points=total_scans,
                num_neutrons=number_neutrons,
                first_scan_time=first_scan_time,
                avg_subsequent_time=avg_subsequent_time,
                total_time=total_time
            )
            self.message_printed.emit(f"Timing data recorded: {total_scans} points in {RuntimeTracker.format_time(total_time)}")
        
        # Simulation complete
        self.message_printed.emit(f"Simulation complete! Data saved to: {data_folder}")
        self.message_printed.emit(f"Total counts: {total_counts}, Max counts: {max_counts}")
        
        # Write scan data to output files
        if not is_single_point_scan and not self.stop_flag:
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
        if is_single_point_scan:
            # For single-point scans, show results as text instead of plot
            self.single_point_result.emit(max_counts, total_counts)
        else:
            # For 1D/2D scans, signal completion and auto-save the plot
            self.scan_completed.emit()
            self.scan_auto_save.emit()
        
        # Display diagnostic subplots if in diagnostic mode and any monitors were enabled
        if diagnostic_mode:
            # Check if any diagnostic monitors were enabled (excluding Show Instrument Diagram)
            monitors_enabled = any(
                enabled for key, enabled in self.diagnostic_settings.items() 
                if key != "Show Instrument Diagram" and enabled
            )
            if monitors_enabled and data is not None and data is not math.nan:
                # Emit signal to display plots on main thread (matplotlib requires this)
                self.diagnostic_plot_requested.emit(data)
        
        return data_folder


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    controller = TAVIController(window)
    # Store controller reference on window so closeEvent can access it
    window.controller = controller
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
