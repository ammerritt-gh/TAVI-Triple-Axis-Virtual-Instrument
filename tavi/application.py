"""
TAVI Application - Main application entry point.

This module provides the main Application class that wires together
the MVVM components (Models, Views, ViewModels, Controllers).
"""
import os
import sys
from typing import Optional

from .models import ApplicationModel
from .views import MainView
from .controllers import ScanController
from .instruments import PUMAInstrument

# Import legacy modules for backward compatibility during transition
try:
    from PUMA_instrument_definition import run_PUMA_instrument, mono_ana_crystals_setup
    from McScript_DataProcessing import read_1Ddetector_file, write_parameters_to_file, simple_plot_scan_commands
    from McScript_Functions import letter_encode_number, incremented_path_writing
    LEGACY_AVAILABLE = True
except ImportError:
    LEGACY_AVAILABLE = False


class Application:
    """
    Main TAVI application class.
    
    Coordinates between the model (state), view (GUI), and controllers (logic).
    """
    
    def __init__(self):
        # Create the application model (state)
        self.model = ApplicationModel()
        
        # Create the view (GUI)
        self.view = MainView()
        
        # Create the scan controller
        self.scan_controller = ScanController()
        
        # Create the instrument instance
        self.instrument = PUMAInstrument()
        
        # Wire up callbacks
        self._setup_callbacks()
        
        # Load saved parameters or defaults
        self._load_initial_state()
    
    def _setup_callbacks(self):
        """Wire up all the callbacks between view and controllers."""
        # Scan controls
        self.view.scan_dock.set_run_callback(self._on_run_simulation)
        self.view.scan_dock.set_stop_callback(self._on_stop_simulation)
        self.view.scan_dock.set_validate_callback(self._on_validate)
        self.view.scan_dock.set_configure_diagnostics_callback(self._on_configure_diagnostics)
        
        # Data controls
        self.view.data_dock.set_save_params_callback(self._on_save_params)
        self.view.data_dock.set_load_params_callback(self._on_load_params)
        self.view.data_dock.set_load_defaults_callback(self._on_load_defaults)
        self.view.data_dock.set_load_data_callback(self._on_load_data)
        
        # Sample controls
        self.view.sample_dock.set_configure_sample_callback(self._on_configure_sample)
        
        # Scan controller callbacks
        self.scan_controller.set_progress_callback(self._on_progress_update)
        self.scan_controller.set_message_callback(self._on_message)
        self.scan_controller.set_counts_callback(self._on_counts_update)
        self.scan_controller.set_time_callback(self._on_time_update)
        self.scan_controller.set_all_complete_callback(self._on_simulation_complete)
        
        # Quit callback
        self.view.set_quit_callback(self._on_quit)
    
    def _load_initial_state(self):
        """Load the initial application state."""
        # Try to load saved parameters
        try:
            self.model.load_legacy_parameters()
            self.view.log("Loaded saved parameters.", target='GUI')
        except Exception as e:
            self.model.set_defaults()
            self.view.log(f"Using default parameters: {e}", target='GUI')
        
        # Sync model to view
        self._sync_model_to_view()
        
        self.view.log("GUI initialized.", target='GUI')
    
    def _sync_model_to_view(self):
        """Synchronize model state to the view."""
        # Instrument config
        self.view.instrument_dock.set_values({
            "mtt": self.model.instrument.mtt.get(),
            "stt": self.model.instrument.stt.get(),
            "psi": self.model.instrument.psi.get(),
            "att": self.model.instrument.att.get(),
            "Ki": self.model.instrument.Ki.get(),
            "Kf": self.model.instrument.Kf.get(),
            "Ei": self.model.instrument.Ei.get(),
            "Ef": self.model.instrument.Ef.get(),
            "monocris": self.model.instrument.monocris.get(),
            "anacris": self.model.instrument.anacris.get(),
            "alpha_1": self.model.instrument.alpha_1.get(),
            "alpha_2_30": self.model.instrument.alpha_2_30.get(),
            "alpha_2_40": self.model.instrument.alpha_2_40.get(),
            "alpha_2_60": self.model.instrument.alpha_2_60.get(),
            "alpha_3": self.model.instrument.alpha_3.get(),
            "alpha_4": self.model.instrument.alpha_4.get(),
            "rhmfac": self.model.instrument.rhmfac.get(),
            "rvmfac": self.model.instrument.rvmfac.get(),
            "rhafac": self.model.instrument.rhafac.get(),
            "NMO_installed": self.model.instrument.NMO_installed.get(),
            "V_selector_installed": self.model.instrument.V_selector_installed.get(),
        })
        
        # Reciprocal space
        self.view.reciprocal_dock.set_values({
            "qx": self.model.reciprocal_space.qx.get(),
            "qy": self.model.reciprocal_space.qy.get(),
            "qz": self.model.reciprocal_space.qz.get(),
            "H": self.model.reciprocal_space.H.get(),
            "K": self.model.reciprocal_space.K.get(),
            "L": self.model.reciprocal_space.L.get(),
            "deltaE": self.model.reciprocal_space.deltaE.get(),
            "sample_frame_mode": self.model.scan.sample_frame_mode.get(),
        })
        
        # Sample control
        self.view.sample_dock.set_values({
            "lattice_a": self.model.sample.lattice_a.get(),
            "lattice_b": self.model.sample.lattice_b.get(),
            "lattice_c": self.model.sample.lattice_c.get(),
            "lattice_alpha": self.model.sample.lattice_alpha.get(),
            "lattice_beta": self.model.sample.lattice_beta.get(),
            "lattice_gamma": self.model.sample.lattice_gamma.get(),
            "space_group": self.model.sample.space_group.get(),
        })
        
        # Scan controls
        self.view.scan_dock.set_values({
            "number_neutrons": self.model.scan.number_neutrons.get(),
            "K_fixed": self.model.scan.K_fixed.get(),
            "fixed_E": self.model.scan.fixed_E.get(),
            "scan_command1": self.model.scan.scan_command1.get(),
            "scan_command2": self.model.scan.scan_command2.get(),
            "diagnostic_mode": self.model.scan.diagnostic_mode.get(),
        })
        
        # Data control
        self.view.data_dock.set_values({
            "output_folder": self.model.data.output_folder.get(),
            "load_folder": self.model.data.load_folder.get(),
        })
    
    def _sync_view_to_model(self):
        """Synchronize view state to the model."""
        # Instrument config
        inst_values = self.view.instrument_dock.get_values()
        try:
            self.model.instrument.mtt.set(float(inst_values["mtt"]))
        except (ValueError, TypeError):
            pass
        self.model.instrument.stt.set(inst_values["stt"])
        self.model.instrument.psi.set(inst_values["psi"])
        try:
            self.model.instrument.att.set(float(inst_values["att"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.instrument.Ki.set(float(inst_values["Ki"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.instrument.Kf.set(float(inst_values["Kf"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.instrument.Ei.set(float(inst_values["Ei"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.instrument.Ef.set(float(inst_values["Ef"]))
        except (ValueError, TypeError):
            pass
        self.model.instrument.monocris.set(inst_values["monocris"])
        self.model.instrument.anacris.set(inst_values["anacris"])
        self.model.instrument.alpha_1.set(inst_values["alpha_1"])
        self.model.instrument.alpha_2_30.set(inst_values["alpha_2_30"])
        self.model.instrument.alpha_2_40.set(inst_values["alpha_2_40"])
        self.model.instrument.alpha_2_60.set(inst_values["alpha_2_60"])
        self.model.instrument.alpha_3.set(inst_values["alpha_3"])
        self.model.instrument.alpha_4.set(inst_values["alpha_4"])
        self.model.instrument.rhmfac.set(inst_values["rhmfac"])
        self.model.instrument.rvmfac.set(inst_values["rvmfac"])
        self.model.instrument.rhafac.set(inst_values["rhafac"])
        self.model.instrument.NMO_installed.set(inst_values["NMO_installed"])
        self.model.instrument.V_selector_installed.set(inst_values["V_selector_installed"])
        
        # Reciprocal space
        recip_values = self.view.reciprocal_dock.get_values()
        self.model.reciprocal_space.qx.set(recip_values["qx"])
        self.model.reciprocal_space.qy.set(recip_values["qy"])
        self.model.reciprocal_space.qz.set(recip_values["qz"])
        try:
            self.model.reciprocal_space.H.set(float(recip_values["H"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.reciprocal_space.K.set(float(recip_values["K"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.reciprocal_space.L.set(float(recip_values["L"]))
        except (ValueError, TypeError):
            pass
        try:
            self.model.reciprocal_space.deltaE.set(float(recip_values["deltaE"]))
        except (ValueError, TypeError):
            pass
        self.model.scan.sample_frame_mode.set(recip_values["sample_frame_mode"])
        
        # Sample control
        sample_values = self.view.sample_dock.get_values()
        self.model.sample.lattice_a.set(sample_values["lattice_a"])
        self.model.sample.lattice_b.set(sample_values["lattice_b"])
        self.model.sample.lattice_c.set(sample_values["lattice_c"])
        self.model.sample.lattice_alpha.set(sample_values["lattice_alpha"])
        self.model.sample.lattice_beta.set(sample_values["lattice_beta"])
        self.model.sample.lattice_gamma.set(sample_values["lattice_gamma"])
        self.model.sample.space_group.set(sample_values["space_group"])
        
        # Scan controls
        scan_values = self.view.scan_dock.get_values()
        self.model.scan.number_neutrons.set(scan_values["number_neutrons"])
        self.model.scan.K_fixed.set(scan_values["K_fixed"])
        try:
            self.model.scan.fixed_E.set(float(scan_values["fixed_E"]))
        except (ValueError, TypeError):
            pass
        self.model.scan.scan_command1.set(scan_values["scan_command1"])
        self.model.scan.scan_command2.set(scan_values["scan_command2"])
        self.model.scan.diagnostic_mode.set(scan_values["diagnostic_mode"])
        
        # Data control
        data_values = self.view.data_dock.get_values()
        self.model.data.output_folder.set(data_values["output_folder"])
        self.model.data.load_folder.set(data_values["load_folder"])
    
    # Callback handlers
    def _on_run_simulation(self):
        """Handle run simulation request."""
        if not LEGACY_AVAILABLE:
            self.view.log("Legacy modules not available. Cannot run simulation.", target='both')
            return
        
        # Sync view to model
        self._sync_view_to_model()
        
        # Save parameters
        self.model.save_legacy_parameters()
        
        # Get output folder
        output_folder = self.model.data.output_folder.get()
        if not output_folder:
            # Use default output directory from data model
            output_folder = os.path.join(self.model.data.ensure_output_directory(), "initial_testing")
        output_dir = os.path.dirname(output_folder)
        folder_name = os.path.basename(output_folder)
        
        # Create incremented folder, using data model's output directory as fallback
        if not output_dir:
            output_dir = self.model.data.ensure_output_directory()
        actual_folder = incremented_path_writing(output_dir, folder_name)
        self.model.data.actual_output_folder.set(actual_folder)
        self.view.update_actual_folder(actual_folder)
        
        # Build scan parameters
        scan_params = {
            "K_fixed": self.model.scan.K_fixed.get(),
            "fixed_E": self.model.scan.fixed_E.get(),
            "monocris": self.model.instrument.monocris.get(),
            "anacris": self.model.instrument.anacris.get(),
            "alpha_1": self.model.instrument.alpha_1.get(),
            "alpha_2": self.model.instrument.get_alpha_2_list(),
            "alpha_3": self.model.instrument.alpha_3.get(),
            "alpha_4": self.model.instrument.alpha_4.get(),
            "rhmfac": self.model.instrument.rhmfac.get(),
            "rvmfac": self.model.instrument.rvmfac.get(),
            "rhafac": self.model.instrument.rhafac.get(),
            "NMO_installed": self.model.instrument.NMO_installed.get(),
            "V_selector_installed": self.model.instrument.V_selector_installed.get(),
            "number_neutrons": self.model.scan.number_neutrons.get(),
            "diagnostic_mode": self.model.scan.diagnostic_mode.get(),
            "diagnostic_settings": self.model.diagnostics.to_dict(),
            "scan_mode": self.model.scan.get_scan_mode(),
        }
        
        # Get scan points
        # For now, use a simple implementation
        scan_points = self._build_scan_points()
        
        # Update UI state
        self.view.set_running_state(True)
        self.view.output_dock.reset_progress()
        
        # Start simulation
        self.view.log(f"Starting simulation with {len(scan_points)} scan point(s)...", target='both')
        
        # Import the legacy instrument for running
        from PUMA_instrument_definition import PUMA_Instrument as LegacyPUMA
        legacy_puma = LegacyPUMA()
        
        # Copy settings to legacy instrument
        legacy_puma.K_fixed = scan_params["K_fixed"]
        legacy_puma.fixed_E = scan_params["fixed_E"]
        legacy_puma.monocris = scan_params["monocris"]
        legacy_puma.anacris = scan_params["anacris"]
        legacy_puma.alpha_1 = scan_params["alpha_1"]
        legacy_puma.alpha_2 = scan_params["alpha_2"]
        legacy_puma.alpha_3 = scan_params["alpha_3"]
        legacy_puma.alpha_4 = scan_params["alpha_4"]
        legacy_puma.rhmfac = scan_params["rhmfac"]
        legacy_puma.rvmfac = scan_params["rvmfac"]
        legacy_puma.rhafac = scan_params["rhafac"]
        legacy_puma.NMO_installed = scan_params["NMO_installed"]
        legacy_puma.V_selector_installed = scan_params["V_selector_installed"]
        
        self.scan_controller.run_simulation(
            legacy_puma,
            scan_params,
            scan_points,
            actual_folder,
            run_PUMA_instrument,
            read_1Ddetector_file,
            write_parameters_to_file,
            letter_encode_number
        )
    
    def _build_scan_points(self):
        """Build the list of scan points from the current configuration."""
        qx = self.model.reciprocal_space.qx.get()
        qy = self.model.reciprocal_space.qy.get()
        qz = self.model.reciprocal_space.qz.get()
        deltaE = self.model.reciprocal_space.deltaE.get()
        
        # Get scan commands
        cmd1 = self.model.scan.scan_command1.get().strip()
        cmd2 = self.model.scan.scan_command2.get().strip()
        
        # Base point
        base_point = [qx, qy, qz, deltaE, 0, 0, 0, 0]
        
        # Parse commands
        parsed1 = self.model.scan.parse_scan_command(cmd1)
        parsed2 = self.model.scan.parse_scan_command(cmd2)
        
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
            'H': 0, 'K': 1, 'L': 2,
            'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7
        }
        
        scan_points = []
        
        if not parsed1 and not parsed2:
            # Single point
            scan_points.append(base_point)
        elif parsed1 and not parsed2:
            # 1D scan
            var_name1, values1 = parsed1
            for val1 in values1:
                point = base_point[:]
                if var_name1 in variable_to_index:
                    point[variable_to_index[var_name1]] = val1
                scan_points.append(point)
        elif parsed1 and parsed2:
            # 2D scan
            var_name1, values1 = parsed1
            var_name2, values2 = parsed2
            for val1 in values1:
                for val2 in values2:
                    point = base_point[:]
                    if var_name1 in variable_to_index:
                        point[variable_to_index[var_name1]] = val1
                    if var_name2 in variable_to_index:
                        point[variable_to_index[var_name2]] = val2
                    scan_points.append(point)
        
        return scan_points
    
    def _on_stop_simulation(self):
        """Handle stop simulation request."""
        self.scan_controller.stop()
        self.view.log("Stopping simulation...", target='both')
    
    def _on_validate(self):
        """Handle validation request."""
        self.view.log("Validation not yet implemented in MVVM architecture.", target='GUI')
    
    def _on_configure_diagnostics(self):
        """Handle configure diagnostics request."""
        current_settings = self.model.diagnostics.to_dict()
        result = self.view.show_diagnostics_dialog(current_settings)
        if result is not None:
            self.model.diagnostics.from_dict(result)
            self.model.save_legacy_parameters()
            self.view.log("Diagnostic settings updated.", target='GUI')
    
    def _on_configure_sample(self):
        """Handle configure sample request."""
        self.view.log("Sample configuration not yet implemented in MVVM architecture.", target='GUI')
    
    def _on_save_params(self):
        """Handle save parameters request."""
        self._sync_view_to_model()
        self.model.save_legacy_parameters()
        self.view.log("Parameters saved.", target='GUI')
    
    def _on_load_params(self):
        """Handle load parameters request."""
        self.model.load_legacy_parameters()
        self._sync_model_to_view()
        self.view.log("Parameters loaded.", target='GUI')
    
    def _on_load_defaults(self):
        """Handle load defaults request."""
        self.model.set_defaults()
        self._sync_model_to_view()
        self.view.log("Default parameters loaded.", target='GUI')
    
    def _on_load_data(self, folder: str):
        """Handle load data request."""
        if LEGACY_AVAILABLE:
            try:
                from McScript_DataProcessing import display_existing_data
                import tkinter as tk
                # Create a temporary StringVar for compatibility with legacy function
                folder_var = tk.StringVar(value=folder)
                folder_entry = type('Entry', (), {'get': lambda self: folder})()
                display_existing_data(folder_entry)
                self.view.log(f"Loaded data from {folder}", target='GUI')
            except Exception as e:
                self.view.log(f"Error loading data: {e}", target='GUI')
        else:
            self.view.log("Legacy modules not available.", target='GUI')
    
    def _on_quit(self):
        """Handle quit request."""
        self._sync_view_to_model()
        self.model.save_legacy_parameters()
    
    # Scan controller callbacks
    def _on_progress_update(self, current: int, total: int):
        """Handle progress update from scan controller."""
        self.view.update_progress(current, total)
        self.view.update()
    
    def _on_message(self, message: str):
        """Handle message from scan controller."""
        self.view.log(message, target='GUI')
        self.view.update()
    
    def _on_counts_update(self, max_counts: float, total_counts: float):
        """Handle counts update from scan controller."""
        self.view.update_counts(max_counts, total_counts)
        self.view.update()
    
    def _on_time_update(self, time_str: str):
        """Handle time update from scan controller."""
        self.view.update_remaining_time(time_str)
        self.view.update()
    
    def _on_simulation_complete(self, output_folder: str):
        """Handle simulation complete from scan controller."""
        self.view.set_running_state(False)
        self.view.log(f"Simulation complete. Output: {output_folder}", target='both')
        
        # Plot results if we have scan commands
        if LEGACY_AVAILABLE and self.model.scan.scan_command1.get():
            try:
                simple_plot_scan_commands(None, output_folder)
            except Exception as e:
                self.view.log(f"Error plotting results: {e}", target='GUI')
    
    def run(self):
        """Start the application."""
        self.view.run()


def main():
    """Main entry point for the TAVI application."""
    app = Application()
    app.run()


if __name__ == "__main__":
    main()
