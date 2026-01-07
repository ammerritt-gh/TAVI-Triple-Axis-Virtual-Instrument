"""Main application controller for TAVI with PySide6 GUI."""
import sys
import os
import json
import time
import datetime
import threading
import queue

from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QObject, Signal, Slot

# Import existing backend modules
from PUMA_instrument_definition import PUMA_Instrument, run_PUMA_instrument, validate_angles, mono_ana_crystals_setup
from McScript_DataProcessing import read_1Ddetector_file, write_parameters_to_file, simple_plot_scan_commands, display_existing_data
from McScript_Functions import parse_scan_steps, letter_encode_number, incremented_path_writing
from McScript_Sample_Definition import update_Q_from_HKL_direct
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
    
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.PUMA = PUMA_Instrument()
        
        # Global variables
        self.stop_flag = False
        self.diagnostic_settings = {}
        self.current_sample_settings = {}
        self.monocris_info = {}
        self.anacris_info = {}
        
        # Initialize output directory
        self.output_directory = os.path.join(os.getcwd(), "output")
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        
        # Connect signals
        self.connect_signals()
        
        # Load parameters
        self.load_parameters()
        
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
        
        # TODO: Connect variable bindings for linked updates between docks
    
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
        # TODO: Update all related variables
    
    def update_anacris_info(self):
        """Update analyzer crystal information."""
        monocris = self.window.instrument_dock.monocris_combo.currentText()
        anacris = self.window.instrument_dock.anacris_combo.currentText()
        _, self.anacris_info = mono_ana_crystals_setup(monocris, anacris)
        # TODO: Update all related variables
    
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
        """Load and display existing data."""
        folder = self.window.data_control_dock.load_folder_edit.text()
        if folder and os.path.exists(folder):
            display_existing_data(self.window.data_control_dock.load_folder_edit)
        else:
            self.print_to_message_center("Invalid folder path for loading data")
    
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
        """Run the simulation (simplified version for now)."""
        self.print_to_message_center("Starting simulation...")
        self.print_to_message_center("Note: Full simulation integration is not yet complete")
        # TODO: Implement full simulation logic from original McScript_Runner.py
        # This would include all the scan logic, parameter extraction, etc.


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    window = TAVIMainWindow()
    controller = TAVIController(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
