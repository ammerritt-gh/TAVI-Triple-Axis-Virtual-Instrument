"""Main application controller for TAVI with PySide6 GUI."""
import sys
import os
import json
import time
import datetime
import threading
import queue

from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit
from PySide6.QtCore import QObject, Signal, Slot, QTimer

# Import existing backend modules
from PUMA_instrument_definition import PUMA_Instrument, run_PUMA_instrument, validate_angles, mono_ana_crystals_setup
from McScript_DataProcessing import (read_1Ddetector_file, write_parameters_to_file, 
                                      simple_plot_scan_commands, display_existing_data,
                                      read_parameters_from_file)
from McScript_Functions import parse_scan_steps, letter_encode_number, incremented_path_writing, extract_variable_values
from McScript_Sample_Definition import update_Q_from_HKL_direct, update_HKL_from_Q_direct
import PUMA_GUI_calculations as GUIcalc

# Import GUI
from gui.main_window import TAVIMainWindow

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
    counts_updated = Signal(float, float)  # max_counts, total_counts
    message_printed = Signal(str)
    
    # Variable index mapping for scan parameters (shared constant)
    VARIABLE_INDEX_MAP = {
        'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
        'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7,
        'H': 8, 'K': 9, 'L': 10
    }
    
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
        
        # Set up visual feedback for all input fields
        self.setup_visual_feedback()
        
        # Print initialization message
        self.print_to_message_center("GUI initialized.")
    
    def connect_signals(self):
        """Connect all GUI signals to controller methods."""
        # Scan control buttons
        self.window.scan_controls_dock.run_button.clicked.connect(self.run_simulation_thread)
        self.window.scan_controls_dock.stop_button.clicked.connect(self.stop_simulation)
        self.window.scan_controls_dock.quit_button.clicked.connect(self.quit_application)
        self.window.scan_controls_dock.validation_button.clicked.connect(self.open_validation_window)
        
        # Parameter buttons
        self.window.scan_controls_dock.save_button.clicked.connect(self.save_parameters)
        self.window.scan_controls_dock.load_button.clicked.connect(self.load_parameters)
        self.window.scan_controls_dock.defaults_button.clicked.connect(self.set_default_parameters)
        
        # Diagnostics button
        self.window.diagnostics_dock.config_diagnostics_button.clicked.connect(self.configure_diagnostics)
        
        # Sample configuration button
        self.window.sample_dock.config_sample_button.clicked.connect(self.configure_sample)
        
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
        self.counts_updated.connect(self.update_counts_entry)
        self.message_printed.connect(self.window.output_dock.message_text.append)
        
        # Connect crystal selection changes
        self.window.instrument_dock.monocris_combo.currentTextChanged.connect(self.update_monocris_info)
        self.window.instrument_dock.anacris_combo.currentTextChanged.connect(self.update_anacris_info)
        
        # Connect field editing events for linked updates
        # Instrument angles - update energies and Q-space
        self.window.instrument_dock.mtt_edit.editingFinished.connect(self.on_mtt_changed)
        self.window.instrument_dock.att_edit.editingFinished.connect(self.on_att_changed)
        self.window.instrument_dock.stt_edit.editingFinished.connect(self.on_angles_changed)
        self.window.instrument_dock.psi_edit.editingFinished.connect(self.on_angles_changed)
        
        # Energies - update related energies and angles
        self.window.instrument_dock.Ki_edit.editingFinished.connect(self.on_Ki_changed)
        self.window.instrument_dock.Ei_edit.editingFinished.connect(self.on_Ei_changed)
        self.window.instrument_dock.Kf_edit.editingFinished.connect(self.on_Kf_changed)
        self.window.instrument_dock.Ef_edit.editingFinished.connect(self.on_Ef_changed)
        
        # K fixed mode and fixed E - update all related values
        self.window.scan_controls_dock.K_fixed_combo.currentTextChanged.connect(self.on_K_fixed_changed)
        self.window.scan_controls_dock.fixed_E_edit.editingFinished.connect(self.on_fixed_E_changed)
        
        # Q-space - update HKL and angles
        self.window.reciprocal_space_dock.qx_edit.editingFinished.connect(self.on_Q_changed)
        self.window.reciprocal_space_dock.qy_edit.editingFinished.connect(self.on_Q_changed)
        self.window.reciprocal_space_dock.qz_edit.editingFinished.connect(self.on_Q_changed)
        
        # HKL - update Q-space and angles
        self.window.reciprocal_space_dock.H_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.reciprocal_space_dock.K_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.reciprocal_space_dock.L_edit.editingFinished.connect(self.on_HKL_changed)
        
        # DeltaE - update energies
        self.window.reciprocal_space_dock.deltaE_edit.editingFinished.connect(self.on_deltaE_changed)
        
        # Lattice parameters - update HKL/Q conversions
        self.window.sample_dock.lattice_a_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_b_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_c_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_alpha_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_beta_edit.editingFinished.connect(self.on_lattice_changed)
        self.window.sample_dock.lattice_gamma_edit.editingFinished.connect(self.on_lattice_changed)
    
    def setup_visual_feedback(self):
        """Set up visual feedback for all input fields to show pending/saved states."""
        # Collect all QLineEdit widgets from all docks
        line_edits = []
        
        # Instrument dock
        line_edits.extend([
            self.window.instrument_dock.mtt_edit,
            self.window.instrument_dock.stt_edit,
            self.window.instrument_dock.psi_edit,
            self.window.instrument_dock.att_edit,
            self.window.instrument_dock.Ki_edit,
            self.window.instrument_dock.Ei_edit,
            self.window.instrument_dock.Kf_edit,
            self.window.instrument_dock.Ef_edit,
            self.window.instrument_dock.rhmfac_edit,
            self.window.instrument_dock.rvmfac_edit,
            self.window.instrument_dock.rhafac_edit,
        ])
        
        # Reciprocal space dock
        line_edits.extend([
            self.window.reciprocal_space_dock.qx_edit,
            self.window.reciprocal_space_dock.qy_edit,
            self.window.reciprocal_space_dock.qz_edit,
            self.window.reciprocal_space_dock.H_edit,
            self.window.reciprocal_space_dock.K_edit,
            self.window.reciprocal_space_dock.L_edit,
            self.window.reciprocal_space_dock.deltaE_edit,
        ])
        
        # Sample dock
        line_edits.extend([
            self.window.sample_dock.lattice_a_edit,
            self.window.sample_dock.lattice_b_edit,
            self.window.sample_dock.lattice_c_edit,
            self.window.sample_dock.lattice_alpha_edit,
            self.window.sample_dock.lattice_beta_edit,
            self.window.sample_dock.lattice_gamma_edit,
        ])
        
        # Scan controls dock
        line_edits.extend([
            self.window.scan_controls_dock.number_neutrons_edit,
            self.window.scan_controls_dock.fixed_E_edit,
            self.window.scan_controls_dock.scan_command_1_edit,
            self.window.scan_controls_dock.scan_command_2_edit,
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
        self.window.output_dock.progress_bar.setValue(percentage)
        self.window.output_dock.progress_label.setText(f"{percentage}% ({current}/{total})")
    
    @Slot(str)
    def update_remaining_time(self, remaining_time):
        """Update remaining time label."""
        self.window.output_dock.remaining_time_label.setText(f"Remaining Time: {remaining_time}")
    
    @Slot(float, float)
    def update_counts_entry(self, max_counts, total_counts):
        """Update counts display."""
        self.window.scan_controls_dock.max_counts_label.setText(str(int(max_counts)))
        self.window.scan_controls_dock.total_counts_label.setText(str(int(total_counts)))
    
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
                'psi': float(self.window.instrument_dock.psi_edit.text() or 0),
                'att': float(self.window.instrument_dock.att_edit.text() or 0),
                'Ki': float(self.window.instrument_dock.Ki_edit.text() or 0),
                'Ei': float(self.window.instrument_dock.Ei_edit.text() or 0),
                'Kf': float(self.window.instrument_dock.Kf_edit.text() or 0),
                'Ef': float(self.window.instrument_dock.Ef_edit.text() or 0),
                'K_fixed': self.window.scan_controls_dock.K_fixed_combo.currentText(),
                'fixed_E': float(self.window.scan_controls_dock.fixed_E_edit.text() or 0),
                'qx': float(self.window.reciprocal_space_dock.qx_edit.text() or 0),
                'qy': float(self.window.reciprocal_space_dock.qy_edit.text() or 0),
                'qz': float(self.window.reciprocal_space_dock.qz_edit.text() or 0),
                'H': float(self.window.reciprocal_space_dock.H_edit.text() or 0),
                'K': float(self.window.reciprocal_space_dock.K_edit.text() or 0),
                'L': float(self.window.reciprocal_space_dock.L_edit.text() or 0),
                'deltaE': float(self.window.reciprocal_space_dock.deltaE_edit.text() or 0),
                'lattice_a': float(self.window.sample_dock.lattice_a_edit.text() or 1),
                'lattice_b': float(self.window.sample_dock.lattice_b_edit.text() or 1),
                'lattice_c': float(self.window.sample_dock.lattice_c_edit.text() or 1),
                'lattice_alpha': float(self.window.sample_dock.lattice_alpha_edit.text() or 90),
                'lattice_beta': float(self.window.sample_dock.lattice_beta_edit.text() or 90),
                'lattice_gamma': float(self.window.sample_dock.lattice_gamma_edit.text() or 90),
                'monocris': self.window.instrument_dock.monocris_combo.currentText(),
                'anacris': self.window.instrument_dock.anacris_combo.currentText(),
                'rhmfac': float(self.window.instrument_dock.rhmfac_edit.text() or 1),
                'rvmfac': float(self.window.instrument_dock.rvmfac_edit.text() or 1),
                'rhafac': float(self.window.instrument_dock.rhafac_edit.text() or 1),
                'NMO_installed': self.window.instrument_dock.nmo_combo.currentText(),
                'V_selector_installed': self.window.instrument_dock.v_selector_check.isChecked(),
                'alpha_1': self.window.instrument_dock.alpha_1_combo.currentText(),
                'alpha_2_30': self.window.instrument_dock.alpha_2_30_check.isChecked(),
                'alpha_2_40': self.window.instrument_dock.alpha_2_40_check.isChecked(),
                'alpha_2_60': self.window.instrument_dock.alpha_2_60_check.isChecked(),
                'alpha_3': self.window.instrument_dock.alpha_3_combo.currentText(),
                'alpha_4': self.window.instrument_dock.alpha_4_combo.currentText(),
                'number_neutrons': int(self.window.scan_controls_dock.number_neutrons_edit.text() or 1000000),
                'scan_command1': self.window.scan_controls_dock.scan_command_1_edit.text(),
                'scan_command2': self.window.scan_controls_dock.scan_command_2_edit.text(),
                'diagnostic_mode': self.window.diagnostics_dock.diagnostic_mode_check.isChecked(),
                'auto_display': self.window.scan_controls_dock.auto_display_check.isChecked(),
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
    
    def update_all_variables(self):
        """
        Comprehensive update of all instrument variables based on K_fixed mode.
        This is the central method that ensures all fields stay in sync.
        """
        if self.updating:
            return
        
        vals = self.get_gui_values()
        if not vals or not self.monocris_info or not self.anacris_info:
            return
        
        try:
            self.updating = True
            
            from PUMA_instrument_definition import energy2k, k2angle
            
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
            
            # Calculate angles from wave vectors
            mtt = 2 * k2angle(Ki, self.monocris_info['dm'])
            att = 2 * k2angle(Kf, self.anacris_info['da'])
            
            # Recalculate deltaE to ensure consistency
            deltaE = Ei - Ef
            
            # Update all GUI fields
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
            
        except (ValueError, KeyError) as e:
            pass
        finally:
            self.updating = False
    
    def on_mtt_changed(self):
        """Update energies when mono 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        try:
            self.updating = True
            # Update Ki and Ei from mtt
            from PUMA_instrument_definition import angle2k, k2energy
            Ki = angle2k(vals['mtt'] / 2, self.monocris_info['dm'])
            Ei = k2energy(Ki)
            
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_att_changed(self):
        """Update energies when analyzer 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        try:
            self.updating = True
            # Update Kf and Ef from att
            from PUMA_instrument_definition import angle2k, k2energy
            Kf = angle2k(vals['att'] / 2, self.anacris_info['da'])
            Ef = k2energy(Kf)
            
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_Ki_changed(self):
        """Update Ei and mtt when Ki changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        try:
            self.updating = True
            from PUMA_instrument_definition import k2energy, k2angle
            Ei = k2energy(vals['Ki'])
            mtt = 2 * k2angle(vals['Ki'], self.monocris_info['dm'])
            
            self.window.instrument_dock.Ei_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{Ei:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_Ei_changed(self):
        """Update Ki and mtt when Ei changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        try:
            self.updating = True
            from PUMA_instrument_definition import energy2k, k2angle
            Ki = energy2k(vals['Ei'])
            mtt = 2 * k2angle(Ki, self.monocris_info['dm'])
            
            self.window.instrument_dock.Ki_edit.setText(f"{Ki:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.mtt_edit.setText(f"{mtt:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{vals['Ei']:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = vals['Ei'] - Ef
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_Kf_changed(self):
        """Update Ef and att when Kf changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        try:
            self.updating = True
            from PUMA_instrument_definition import k2energy, k2angle
            Ef = k2energy(vals['Kf'])
            att = 2 * k2angle(vals['Kf'], self.anacris_info['da'])
            
            self.window.instrument_dock.Ef_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{Ef:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_Ef_changed(self):
        """Update Kf and att when Ef changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        try:
            self.updating = True
            from PUMA_instrument_definition import energy2k, k2angle
            Kf = energy2k(vals['Ef'])
            att = 2 * k2angle(Kf, self.anacris_info['da'])
            
            self.window.instrument_dock.Kf_edit.setText(f"{Kf:.4f}".rstrip('0').rstrip('.'))
            self.window.instrument_dock.att_edit.setText(f"{att:.4f}".rstrip('0').rstrip('.'))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scan_controls_dock.fixed_E_edit.setText(f"{vals['Ef']:.4f}".rstrip('0').rstrip('.'))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - vals['Ef']
            self.window.reciprocal_space_dock.deltaE_edit.setText(f"{deltaE:.4f}".rstrip('0').rstrip('.'))
        finally:
            self.updating = False
    
    def on_K_fixed_changed(self):
        """Update all when K fixed mode changes."""
        self.update_all_variables()
    
    def on_fixed_E_changed(self):
        """Update all when fixed E changes."""
        self.update_all_variables()
    
    def on_deltaE_changed(self):
        """Update energies when deltaE changes."""
        self.update_all_variables()
    
    def on_angles_changed(self):
        """Update Q-space when angles change."""
        # Placeholder for angle-to-Q conversion if needed
        pass
    
    def on_Q_changed(self):
        """Update HKL when Q changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        try:
            self.updating = True
            H, K, L = update_HKL_from_Q_direct(
                vals['qx'], vals['qy'], vals['qz'],
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
            self.window.reciprocal_space_dock.H_edit.setText(f"{H:.4f}".rstrip('0').rstrip('.'))
            self.window.reciprocal_space_dock.K_edit.setText(f"{K:.4f}".rstrip('0').rstrip('.'))
            self.window.reciprocal_space_dock.L_edit.setText(f"{L:.4f}".rstrip('0').rstrip('.'))
        except:
            pass
        finally:
            self.updating = False
    
    def on_HKL_changed(self):
        """Update Q when HKL changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        try:
            self.updating = True
            H = float(self.window.reciprocal_space_dock.H_edit.text() or 0)
            K = float(self.window.reciprocal_space_dock.K_edit.text() or 0)
            L = float(self.window.reciprocal_space_dock.L_edit.text() or 0)
            
            qx, qy, qz = update_Q_from_HKL_direct(
                H, K, L,
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
            self.window.reciprocal_space_dock.qx_edit.setText(f"{qx:.4f}".rstrip('0').rstrip('.'))
            self.window.reciprocal_space_dock.qy_edit.setText(f"{qy:.4f}".rstrip('0').rstrip('.'))
            self.window.reciprocal_space_dock.qz_edit.setText(f"{qz:.4f}".rstrip('0').rstrip('.'))
        except:
            pass
        finally:
            self.updating = False
    
    def on_lattice_changed(self):
        """Update Q/HKL conversion when lattice parameters change."""
        # Re-calculate Q from current HKL with new lattice parameters
        self.on_HKL_changed()
    
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
    def configure_diagnostics(self):
        """Open diagnostics configuration window."""
        # TODO: Implement diagnostics configuration dialog
        self.print_to_message_center("Diagnostics configuration window not yet implemented")
    
    def configure_sample(self):
        """Open sample configuration window."""
        # TODO: Implement sample configuration dialog
        self.print_to_message_center("Sample configuration window not yet implemented")
    
    def open_validation_window(self):
        """Open validation window."""
        # TODO: Implement validation window
        self.print_to_message_center("Validation window not yet implemented")
    
    def load_and_display_data(self):
        """Load and display existing data using PySide6-compatible wrapper."""
        folder = self.window.data_control_dock.load_folder_edit.text()
        if folder and os.path.exists(folder):
            self.print_to_message_center(f"Loading data from: {folder}")
            try:
                # Call the PySide6-compatible wrapper function
                self.display_existing_data_pyside6(folder)
            except Exception as e:
                self.print_to_message_center(f"Error loading data: {str(e)}")
        else:
            self.print_to_message_center("Invalid folder path for loading data")
    
    def display_existing_data_pyside6(self, data_folder_path):
        """PySide6-compatible wrapper for display_existing_data."""
        import matplotlib
        matplotlib.use('Qt5Agg')  # Use Qt backend compatible with PySide6
        import matplotlib.pyplot as plt
        import numpy as np
        
        scan_parameters = read_parameters_from_file(data_folder_path)
        if scan_parameters.get('scan_command1') and not scan_parameters.get('scan_command2'):
            # 1D scan
            self.plot_1D_scan_non_blocking(data_folder_path, scan_parameters.get('scan_command1'), scan_parameters, plt, np)
            self.print_to_message_center("1D plot displayed and saved to data folder")
        elif scan_parameters.get('scan_command1') and scan_parameters.get('scan_command2'):
            # 2D scan
            self.plot_2D_scan_non_blocking(data_folder_path, scan_parameters.get('scan_command1'), scan_parameters.get('scan_command2'), scan_parameters, plt, np)
            self.print_to_message_center("2D plot displayed and saved to data folder")
        else:
            self.print_to_message_center("No scan commands found in parameters file")
    
    def save_parameters(self):
        """Save all parameters to JSON file."""
        parameters = {
            "mtt_var": self.window.instrument_dock.mtt_edit.text(),
            "stt_var": self.window.instrument_dock.stt_edit.text(),
            "psi_var": self.window.instrument_dock.psi_edit.text(),
            "att_var": self.window.instrument_dock.att_edit.text(),
            "Ki_var": self.window.instrument_dock.Ki_edit.text(),
            "Kf_var": self.window.instrument_dock.Kf_edit.text(),
            "Ei_var": self.window.instrument_dock.Ei_edit.text(),
            "Ef_var": self.window.instrument_dock.Ef_edit.text(),
            "number_neutrons_var": self.window.scan_controls_dock.number_neutrons_edit.text(),
            "K_fixed_var": self.window.scan_controls_dock.K_fixed_combo.currentText(),
            "NMO_installed_var": self.window.instrument_dock.nmo_combo.currentText(),
            "V_selector_installed_var": self.window.instrument_dock.v_selector_check.isChecked(),
            "rhmfac_var": self.window.instrument_dock.rhmfac_edit.text(),
            "rvmfac_var": self.window.instrument_dock.rvmfac_edit.text(),
            "rhafac_var": self.window.instrument_dock.rhafac_edit.text(),
            "fixed_E_var": self.window.scan_controls_dock.fixed_E_edit.text(),
            "qx_var": self.window.reciprocal_space_dock.qx_edit.text(),
            "qy_var": self.window.reciprocal_space_dock.qy_edit.text(),
            "qz_var": self.window.reciprocal_space_dock.qz_edit.text(),
            "deltaE_var": self.window.reciprocal_space_dock.deltaE_edit.text(),
            "monocris_var": self.window.instrument_dock.monocris_combo.currentText(),
            "anacris_var": self.window.instrument_dock.anacris_combo.currentText(),
            "alpha_1_var": self.window.instrument_dock.alpha_1_combo.currentText(),
            "alpha_2_30_var": self.window.instrument_dock.alpha_2_30_check.isChecked(),
            "alpha_2_40_var": self.window.instrument_dock.alpha_2_40_check.isChecked(),
            "alpha_2_60_var": self.window.instrument_dock.alpha_2_60_check.isChecked(),
            "alpha_3_var": self.window.instrument_dock.alpha_3_combo.currentText(),
            "alpha_4_var": self.window.instrument_dock.alpha_4_combo.currentText(),
            "diagnostic_mode_var": self.window.diagnostics_dock.diagnostic_mode_check.isChecked(),
            "lattice_a_var": self.window.sample_dock.lattice_a_edit.text(),
            "lattice_b_var": self.window.sample_dock.lattice_b_edit.text(),
            "lattice_c_var": self.window.sample_dock.lattice_c_edit.text(),
            "lattice_alpha_var": self.window.sample_dock.lattice_alpha_edit.text(),
            "lattice_beta_var": self.window.sample_dock.lattice_beta_edit.text(),
            "lattice_gamma_var": self.window.sample_dock.lattice_gamma_edit.text(),
            "scan_command_var1": self.window.scan_controls_dock.scan_command_1_edit.text(),
            "scan_command_var2": self.window.scan_controls_dock.scan_command_2_edit.text(),
            "diagnostic_settings": self.diagnostic_settings,
            "current_sample_settings": self.current_sample_settings
        }
        with open("parameters.json", "w") as file:
            json.dump(parameters, file)
        self.print_to_message_center("Parameters saved successfully")
    
    def load_parameters(self):
        """Load parameters from JSON file."""
        if os.path.exists("parameters.json"):
            with open("parameters.json", "r") as file:
                parameters = json.load(file)
                
                # Set GUI values from parameters
                self.window.instrument_dock.monocris_combo.setCurrentText(parameters.get("monocris_var", "PG[002]"))
                self.window.instrument_dock.anacris_combo.setCurrentText(parameters.get("anacris_var", "PG[002]"))
                self.window.instrument_dock.mtt_edit.setText(str(parameters.get("mtt_var", "30")))
                self.window.instrument_dock.stt_edit.setText(str(parameters.get("stt_var", "30")))
                self.window.instrument_dock.psi_edit.setText(str(parameters.get("psi_var", 30)))
                self.window.instrument_dock.att_edit.setText(str(parameters.get("att_var", 30)))
                self.window.instrument_dock.Ki_edit.setText(str(parameters.get("Ki_var", "2.662")))
                self.window.instrument_dock.Kf_edit.setText(str(parameters.get("Kf_var", "2.662")))
                self.window.instrument_dock.Ei_edit.setText(str(parameters.get("Ei_var", "14.7")))
                self.window.instrument_dock.Ef_edit.setText(str(parameters.get("Ef_var", "14.7")))
                self.window.instrument_dock.nmo_combo.setCurrentText(parameters.get("NMO_installed_var", "None"))
                self.window.instrument_dock.v_selector_check.setChecked(parameters.get("V_selector_installed_var", False))
                self.window.instrument_dock.rhmfac_edit.setText(str(parameters.get("rhmfac_var", 1)))
                self.window.instrument_dock.rvmfac_edit.setText(str(parameters.get("rvmfac_var", 1)))
                self.window.instrument_dock.rhafac_edit.setText(str(parameters.get("rhafac_var", 1)))
                self.window.instrument_dock.alpha_1_combo.setCurrentText(str(parameters.get("alpha_1_var", 40)))
                self.window.instrument_dock.alpha_2_30_check.setChecked(parameters.get("alpha_2_30_var", False))
                self.window.instrument_dock.alpha_2_40_check.setChecked(parameters.get("alpha_2_40_var", True))
                self.window.instrument_dock.alpha_2_60_check.setChecked(parameters.get("alpha_2_60_var", False))
                self.window.instrument_dock.alpha_3_combo.setCurrentText(str(parameters.get("alpha_3_var", 30)))
                self.window.instrument_dock.alpha_4_combo.setCurrentText(str(parameters.get("alpha_4_var", 30)))
                
                self.window.scan_controls_dock.number_neutrons_edit.setText(str(parameters.get("number_neutrons_var", 1e8)))
                self.window.scan_controls_dock.K_fixed_combo.setCurrentText(parameters.get("K_fixed_var", "Kf Fixed"))
                self.window.scan_controls_dock.fixed_E_edit.setText(str(parameters.get("fixed_E_var", 14.7)))
                self.window.reciprocal_space_dock.qx_edit.setText(str(parameters.get("qx_var", 2)))
                self.window.reciprocal_space_dock.qy_edit.setText(str(parameters.get("qy_var", 0)))
                self.window.reciprocal_space_dock.qz_edit.setText(str(parameters.get("qz_var", 0)))
                self.window.reciprocal_space_dock.deltaE_edit.setText(str(parameters.get("deltaE_var", 5.25)))
                self.window.diagnostics_dock.diagnostic_mode_check.setChecked(parameters.get("diagnostic_mode_var", True))
                self.window.scan_controls_dock.scan_command_1_edit.setText(parameters.get("scan_command_var1", ""))
                self.window.scan_controls_dock.scan_command_2_edit.setText(parameters.get("scan_command_var2", ""))
                
                self.window.sample_dock.lattice_a_edit.setText(str(parameters.get("lattice_a_var", 4.05)))
                self.window.sample_dock.lattice_b_edit.setText(str(parameters.get("lattice_b_var", 4.05)))
                self.window.sample_dock.lattice_c_edit.setText(str(parameters.get("lattice_c_var", 4.05)))
                self.window.sample_dock.lattice_alpha_edit.setText(str(parameters.get("lattice_alpha_var", 90)))
                self.window.sample_dock.lattice_beta_edit.setText(str(parameters.get("lattice_beta_var", 90)))
                self.window.sample_dock.lattice_gamma_edit.setText(str(parameters.get("lattice_gamma_var", 90)))
                
                self.diagnostic_settings = parameters.get("diagnostic_settings", {})
                self.current_sample_settings = parameters.get("current_sample_settings", {})
                
            self.print_to_message_center("Parameters loaded successfully")
        else:
            self.set_default_parameters()
    
    def set_default_parameters(self):
        """Set default parameters."""
        self.window.instrument_dock.monocris_combo.setCurrentText("PG[002]")
        self.window.instrument_dock.anacris_combo.setCurrentText("PG[002]")
        self.window.instrument_dock.mtt_edit.setText("30")
        self.window.instrument_dock.stt_edit.setText("30")
        self.window.instrument_dock.psi_edit.setText("30")
        self.window.instrument_dock.att_edit.setText("30")
        self.window.instrument_dock.Ki_edit.setText("2.662")
        self.window.instrument_dock.Kf_edit.setText("2.662")
        self.window.instrument_dock.Ei_edit.setText("14.7")
        self.window.instrument_dock.Ef_edit.setText("14.7")
        self.window.instrument_dock.nmo_combo.setCurrentText("None")
        self.window.instrument_dock.v_selector_check.setChecked(False)
        self.window.instrument_dock.rhmfac_edit.setText("1")
        self.window.instrument_dock.rvmfac_edit.setText("1")
        self.window.instrument_dock.rhafac_edit.setText("1")
        self.window.instrument_dock.alpha_1_combo.setCurrentText("40")
        self.window.instrument_dock.alpha_2_30_check.setChecked(False)
        self.window.instrument_dock.alpha_2_40_check.setChecked(True)
        self.window.instrument_dock.alpha_2_60_check.setChecked(False)
        self.window.instrument_dock.alpha_3_combo.setCurrentText("30")
        self.window.instrument_dock.alpha_4_combo.setCurrentText("30")
        
        self.window.scan_controls_dock.number_neutrons_edit.setText("1000000")
        self.window.scan_controls_dock.K_fixed_combo.setCurrentText("Kf Fixed")
        self.window.scan_controls_dock.fixed_E_edit.setText("14.7")
        self.window.reciprocal_space_dock.qx_edit.setText("2")
        self.window.reciprocal_space_dock.qy_edit.setText("0")
        self.window.reciprocal_space_dock.qz_edit.setText("0")
        self.window.reciprocal_space_dock.deltaE_edit.setText("5.25")
        self.window.diagnostics_dock.diagnostic_mode_check.setChecked(True)
        
        self.window.sample_dock.lattice_a_edit.setText("3.78")
        self.window.sample_dock.lattice_b_edit.setText("3.78")
        self.window.sample_dock.lattice_c_edit.setText("5.49")
        self.window.sample_dock.lattice_alpha_edit.setText("90")
        self.window.sample_dock.lattice_beta_edit.setText("90")
        self.window.sample_dock.lattice_gamma_edit.setText("90")
        self.window.scan_controls_dock.scan_command_1_edit.setText("qx 2 2.2 0.1")
        self.window.scan_controls_dock.scan_command_2_edit.setText("deltaE 3 7 0.25")
        
        # Set default folder paths
        folder_suggestion = os.path.join(self.output_directory, "initial_testing")
        self.window.data_control_dock.save_folder_edit.setText(folder_suggestion)
        self.window.data_control_dock.load_folder_edit.setText(folder_suggestion)
        
        self.diagnostic_settings = {}
        self.current_sample_settings = {}
        
        self.print_to_message_center("Default parameters loaded")
    
    def run_simulation_thread(self):
        """Start simulation in a separate thread."""
        self.stop_flag = False
        data_folder = self.window.data_control_dock.save_folder_edit.text()
        simulation_thread = threading.Thread(target=self.run_simulation, args=(data_folder,))
        simulation_thread.start()
    
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
        self.PUMA.rhmfac = vals['rhmfac']
        self.PUMA.rvmfac = vals['rvmfac']
        self.PUMA.rhafac = vals['rhafac']
        self.PUMA.fixed_E = vals['fixed_E']
        self.PUMA.monocris = vals['monocris']
        self.PUMA.anacris = vals['anacris']
        self.PUMA.alpha_1 = float(vals['alpha_1'])
        self.PUMA.alpha_2 = [
            30 if vals['alpha_2_30'] else 0,
            40 if vals['alpha_2_40'] else 0,
            60 if vals['alpha_2_60'] else 0
        ]
        self.PUMA.alpha_3 = float(vals['alpha_3'])
        self.PUMA.alpha_4 = float(vals['alpha_4'])
        
        number_neutrons = vals['number_neutrons']
        scan_command1 = vals['scan_command1']
        scan_command2 = vals['scan_command2']
        diagnostic_mode = vals['diagnostic_mode']
        auto_display = vals['auto_display']
        
        # Write parameters to file
        write_parameters_to_file(data_folder, vals)
        
        # Initialize scan arrays
        scan_parameter_input = []
        
        # Determine scan mode
        scan_mode = "momentum"  # Default
        if scan_command1:
            if "qx" in scan_command1 or "qy" in scan_command1 or "qz" in scan_command1:
                scan_mode = "momentum"
            elif "H" in scan_command1 or "K" in scan_command1 or "L" in scan_command1:
                scan_mode = "rlu"
            elif "A1" in scan_command1 or "A2" in scan_command1 or "A3" in scan_command1 or "A4" in scan_command1:
                scan_mode = "angle"
        
        # Mapping for scannable parameters
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
            'H': 0, 'K': 1, 'L': 2, 'deltaE': 3,
            'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7
        }
        
        # Initialize scan point template
        scan_point_template = [0] * 8
        if scan_mode == "momentum":
            scan_point_template[:4] = [vals['qx'], vals['qy'], vals['qz'], vals['deltaE']]
        elif scan_mode == "rlu":
            scan_point_template[:4] = [vals['H'], vals['K'], vals['L'], vals['deltaE']]
        elif scan_mode == "angle":
            scan_point_template[:4] = [0, 0, 0, 0]
        
        # Handle no scan commands
        if not scan_command1 and not scan_command2:
            scan_parameter_input.append(scan_point_template[:])
        
        # Swap if only second command provided
        if scan_command2 and not scan_command1:
            scan_command1 = scan_command2
            scan_command2 = None
        
        puma_instance = PUMA_Instrument()
        variable_name1 = ""
        variable_name2 = ""
        
        # Single scan command
        if scan_command1 and not scan_command2:
            variable_name1, array_values1 = parse_scan_steps(scan_command1)
            for value1 in array_values1:
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
                    scan_parameter_input.append(scan_point)
        
        # Double scan command
        if scan_command2 and scan_command1:
            variable_name1, array_values1 = parse_scan_steps(scan_command1)
            variable_name2, array_values2 = parse_scan_steps(scan_command2)
            for value1 in array_values1:
                for value2 in array_values2:
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
                        scan_parameter_input.append(scan_point)
        
        # Run the scans
        start_time = time.time()
        total_scans = len(scan_parameter_input)
        self.message_printed.emit(f"Running {total_scans} scan points...")
        
        total_counts = 0
        max_counts = 0
        
        for i, scans in enumerate(scan_parameter_input):
            if self.stop_flag:
                self.message_printed.emit("Simulation stopped by user.")
                return data_folder
            
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
            else:  # Angle mode
                A1, A2, A3, A4 = scans[:4]
                self.PUMA.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)
            
            rhm, rvm, rha, rva = scans[4], scans[5], scans[6], scans[7]
            
            # Check if bending parameters are part of scan commands
            if 'rhm' not in [variable_name1, variable_name2]:
                rhm = self.PUMA.calculate_crystal_bending(
                    self.PUMA.rhmfac, self.PUMA.rvmfac, self.PUMA.rhafac,
                    self.PUMA.A1, self.PUMA.A4
                )[0]
            if 'rvm' not in [variable_name1, variable_name2]:
                rvm = self.PUMA.calculate_crystal_bending(
                    self.PUMA.rhmfac, self.PUMA.rvmfac, self.PUMA.rhafac,
                    self.PUMA.A1, self.PUMA.A4
                )[1]
            if 'rha' not in [variable_name1, variable_name2]:
                rha = self.PUMA.calculate_crystal_bending(
                    self.PUMA.rhmfac, self.PUMA.rvmfac, self.PUMA.rhafac,
                    self.PUMA.A1, self.PUMA.A4
                )[2]
            if 'rva' not in [variable_name1, variable_name2]:
                rva = self.PUMA.calculate_crystal_bending(
                    self.PUMA.rhmfac, self.PUMA.rvmfac, self.PUMA.rhafac,
                    self.PUMA.A1, self.PUMA.A4
                )[3]
            
            # Update crystal bending
            self.PUMA.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)
            
            # Generate scan folder name (match McScript_Runner convention)
            scan_description = []
            if scan_mode == "momentum":
                scan_description.extend([
                    f"qx_{letter_encode_number(qx)}",
                    f"qy_{letter_encode_number(qy)}",
                    f"qz_{letter_encode_number(qz)}",
                    f"dE_{letter_encode_number(deltaE)}",
                ])
            elif scan_mode == "rlu":
                scan_description.extend([
                    f"H_{letter_encode_number(H)}",
                    f"K_{letter_encode_number(K)}",
                    f"L_{letter_encode_number(L)}",
                    f"dE_{letter_encode_number(deltaE)}",
                ])
            else:  # Angle mode
                scan_description.extend([
                    f"A1_{letter_encode_number(A1)}",
                    f"A2_{letter_encode_number(A2)}",
                    f"A3_{letter_encode_number(A3)}",
                    f"A4_{letter_encode_number(A4)}",
                ])

            scan_description.extend([
                f"rhm_{letter_encode_number(rhm)}",
                f"rvm_{letter_encode_number(rvm)}",
                f"rha_{letter_encode_number(rha)}",
                f"rva_{letter_encode_number(rva)}",
            ])

            scan_folder = os.path.join(data_folder, "_".join(scan_description))
            
            # Log scan parameters before running
            if scan_mode == "momentum":
                message = (f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
                           f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}")
            elif scan_mode == "rlu":
                message = (f"Scan parameters - H: {H}, K: {K}, L: {L}, deltaE: {deltaE}\n"
                           f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}")
            else:
                message = (f"Scan parameters - A1: {A1}, A2: {A2}, A3: {A3}, A4: {A4}\n"
                           f"rhm: {rhm:.2f}, rvm: {rvm:.2f}, rha: {rha:.2f}, rva: {rva:.2f}")
            self.message_printed.emit(message)
            
            # Run the PUMA simulation
            if diagnostic_mode:
                data, error_flags = run_PUMA_instrument(
                    self.PUMA, number_neutrons, deltaE, diagnostic_mode, 
                    self.diagnostic_settings, scan_folder, i
                )
            else:
                data, error_flags = run_PUMA_instrument(
                    self.PUMA, number_neutrons, deltaE, False, {}, scan_folder, i
                )
            
            # Check for errors
            if error_flags:
                message = f"Scan failed, error flags: {error_flags}"
                self.message_printed.emit(message)
            else:
                # Write parameters to scan folder
                write_parameters_to_file(scan_folder, vals)
                
                # Read detector file to get counts
                intensity, intensity_error, counts = read_1Ddetector_file(scan_folder)
                message = f"Final counts at detector: {int(counts)}"
                self.message_printed.emit(message)
                
                # Update counts
                total_counts += counts
                max_counts = max(max_counts, counts)
            
            # Emit progress signals
            self.progress_updated.emit(i + 1, total_scans)
            self.counts_updated.emit(max_counts, total_counts)
            
            # Calculate remaining time
            elapsed_time = time.time() - start_time
            avg_time_per_scan = elapsed_time / (i + 1)
            remaining_scans = total_scans - (i + 1)
            remaining_time = avg_time_per_scan * remaining_scans
            
            hours = int(remaining_time // 3600)
            minutes = int((remaining_time % 3600) // 60)
            seconds = int(remaining_time % 60)
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            self.remaining_time_updated.emit(time_str)
        
        # Simulation complete
        self.message_printed.emit(f"Simulation complete! Data saved to: {data_folder}")
        self.message_printed.emit(f"Total counts: {total_counts}, Max counts: {max_counts}")
        
        # Generate and display plots if auto_display is enabled
        if auto_display and (scan_command1 or scan_command2):
            try:
                self.generate_plots_non_blocking(data_folder, scan_command1, scan_command2)
                self.message_printed.emit("Plots generated and saved successfully")
                self.message_printed.emit(f"Plot files saved to: {data_folder}")
            except Exception as e:
                self.message_printed.emit(f"Plot generation failed: {e}")
        elif not auto_display:
            self.message_printed.emit("Auto-display disabled. Plots not generated.")
            self.message_printed.emit("You can manually generate plots from the data folder.")
        
        return data_folder
    
    def generate_plots_non_blocking(self, data_folder, scan_command1, scan_command2):
        """Generate plots without showing them (save to file only)."""
        # Use Qt backend compatible with PySide6
        import matplotlib
        matplotlib.use('Qt5Agg')  # Use Qt backend compatible with PySide6
        import matplotlib.pyplot as plt
        import numpy as np
        
        # Read scan parameters from file
        scan_parameters = read_parameters_from_file(data_folder)
        
        if not scan_command1 and not scan_command2:
            # Single point - no plot needed
            return
        
        if scan_command1 and not scan_command2:
            # 1D scan
            self.plot_1D_scan_non_blocking(data_folder, scan_command1, scan_parameters, plt, np)
        
        if scan_command2 and scan_command1:
            # 2D scan
            self.plot_2D_scan_non_blocking(data_folder, scan_command1, scan_command2, scan_parameters, plt, np)
    
    def plot_1D_scan_non_blocking(self, data_folder, scan_command1, scan_parameters, plt, np):
        """Generate 1D plot and display it in a window."""
        from McScript_DataProcessing import write_1D_scan
        
        variable_name, array_values = parse_scan_steps(scan_command1)
        scan_params = []
        counts_array = []
        
        for folder_name in os.listdir(data_folder):
            full_path = os.path.join(data_folder, folder_name)
            if os.path.isdir(full_path):
                extracted_values = extract_variable_values(folder_name)
                if extracted_values:
                    variable_index = self.VARIABLE_INDEX_MAP.get(variable_name)
                    
                    if variable_index is not None:
                        scan_params.append(extracted_values[variable_index])
                        intensity, intensity_error, counts = read_1Ddetector_file(full_path)
                        counts_array.append(counts)
        
        if not scan_params:
            return
        
        scan_params = np.array(scan_params)
        counts_array = np.array(counts_array)
        
        # Sort by scan parameter
        sorted_indices = np.argsort(scan_params)
        scan_params = scan_params[sorted_indices]
        counts_array = counts_array[sorted_indices]
        
        # Create plot
        plt.figure(figsize=(10, 6))
        plt.plot(scan_params, counts_array, marker='o', linestyle='-', color='b', label='Counts')
        
        # Set labels
        if variable_name in ['qx', 'qy', 'qz']:
            plt.xlabel(f'{variable_name} (1/Å)')
        elif variable_name == 'deltaE':
            plt.xlabel(f'{variable_name} (meV)')
        elif variable_name in ['H', 'K', 'L']:
            plt.xlabel(f'{variable_name} (r.l.u.)')
        else:
            plt.xlabel(variable_name)
        
        plt.ylabel('Counts')
        
        # Build title
        plot_title = f"N: {np.format_float_scientific(scan_parameters.get('number_neutrons'), unique=True, precision=2)}"
        if variable_name != 'qx' and 'qx' in scan_parameters:
            plot_title += f" qx={scan_parameters.get('qx')}"
        if variable_name != 'qy' and 'qy' in scan_parameters:
            plot_title += f" qy={scan_parameters.get('qy')}"
        if variable_name != 'qz' and 'qz' in scan_parameters:
            plot_title += f" qz={scan_parameters.get('qz')}"
        if variable_name != 'deltaE' and 'deltaE' in scan_parameters:
            plot_title += f" dE={scan_parameters.get('deltaE')}"
        
        plt.title(plot_title)
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        # Save plot
        plot_file = os.path.join(data_folder, "1D_plot.png")
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        
        # Display the plot in a window
        plt.show(block=False)
        
        # Write data to file
        write_1D_scan(scan_params, counts_array, data_folder, "1D_data.txt")
    
    def plot_2D_scan_non_blocking(self, data_folder, scan_command1, scan_command2, scan_parameters, plt, np):
        """Generate 2D heatmap and display it in a window."""
        from McScript_DataProcessing import write_2D_scan
        
        variable_name1, array_values1 = parse_scan_steps(scan_command1)
        variable_name2, array_values2 = parse_scan_steps(scan_command2)
        
        scan_data = []
        
        for folder_name in os.listdir(data_folder):
            full_path = os.path.join(data_folder, folder_name)
            if os.path.isdir(full_path):
                extracted_values = extract_variable_values(folder_name)
                if extracted_values:
                    variable_index1 = self.VARIABLE_INDEX_MAP.get(variable_name1)
                    variable_index2 = self.VARIABLE_INDEX_MAP.get(variable_name2)
                    
                    if variable_index1 is not None and variable_index2 is not None:
                        x = extracted_values[variable_index1]
                        y = extracted_values[variable_index2]
                        intensity, intensity_error, counts = read_1Ddetector_file(full_path)
                        scan_data.append((x, y, counts))
        
        if not scan_data:
            return
        
        # Create grid for heatmap
        x_vals = np.unique([d[0] for d in scan_data])
        y_vals = np.unique([d[1] for d in scan_data])
        
        grid = np.full((len(y_vals), len(x_vals)), np.nan)
        
        for x, y, counts in scan_data:
            x_idx = np.abs(x_vals - x).argmin()
            y_idx = np.abs(y_vals - y).argmin()
            grid[y_idx, x_idx] = counts
        
        # Create heatmap
        plt.figure(figsize=(10, 8))
        plt.imshow(grid, cmap='viridis', origin='lower', 
                   extent=[x_vals.min(), x_vals.max(), y_vals.min(), y_vals.max()],
                   aspect='auto')
        plt.colorbar(label='Counts')
        
        # Set labels
        x_label = f'{variable_name1} (1/Å)' if variable_name1 in ['qx', 'qy', 'qz'] else \
                  f'{variable_name1} (meV)' if variable_name1 == 'deltaE' else variable_name1
        y_label = f'{variable_name2} (1/Å)' if variable_name2 in ['qx', 'qy', 'qz'] else \
                  f'{variable_name2} (meV)' if variable_name2 == 'deltaE' else variable_name2
        
        plt.xlabel(x_label)
        plt.ylabel(y_label)
        
        plot_title = f"N: {np.format_float_scientific(scan_parameters.get('number_neutrons'), unique=True, precision=2)}"
        plt.title(plot_title)
        
        # Save plot
        plot_file = os.path.join(data_folder, "Heatmap.png")
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        
        # Display the plot in a window
        plt.show(block=False)
        
        # Write data to file
        write_2D_scan(x_vals, y_vals, grid, data_folder, "2D_data.txt")


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    controller = TAVIController(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
