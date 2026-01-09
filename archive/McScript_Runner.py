import mcstasscript as ms
import os
import pathlib
import re
import numpy as np
import matplotlib.pyplot as plt
import math
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
import sys
import time
import datetime
from instruments.PUMA_instrument_definition import PUMA_Instrument, run_PUMA_instrument, validate_angles, mono_ana_crystals_setup
from McScript_DataProcessing import read_1Ddetector_file, write_parameters_to_file, simple_plot_scan_commands, display_existing_data
from McScript_Functions import parse_scan_steps, letter_encode_number, incremented_path_writing
from McScript_Sample_Definition import update_Q_from_HKL, update_HKL_from_Q, update_HKL_from_Q_direct, update_Q_from_HKL_direct
import PUMA_GUI_calculations as GUIcalc
import threading
import queue
import json
import cProfile

N_MASS = 1.67492749804e-27 # neutron mass
E_CHARGE = 1.602176634e-19 # electron charge
K_B = 0.08617333262 # Boltzmann's constant in meV/K
HBAR_meV = 6.582119569e-13 # H-bar in meV*s
HBAR = 1.05459e-34  # H-bar in J*s

# Global variable to hold the message center text widget
message_center_text = None
# Global variable to hold the stop flag
stop_flag = False
# Global variable to track the diagnostic configuration window
diagnostic_config_window = None
sample_config_window = None

diagnostic_settings = {}

# Queue for handling communication between threads
queue = queue.Queue()

# The Quit button closes everything, including the console.
def quit_application():
    root.quit() # Close the GUI window
    sys.exit() # Close the Python interpreter

# Open the diagnostic window to configure monitors
def configure_diagnostics(puma_instrument):
    global diagnostic_config_window

    # Check if the window is already open
    if diagnostic_config_window and tk.Toplevel.winfo_exists(diagnostic_config_window):
        diagnostic_config_window.lift()  # Bring the existing window to the front
        return

    # Create a new window
    diagnostic_config_window = tk.Toplevel(root)
    diagnostic_config_window.title("Diagnostic Options")

    # Add explanatory text at the top
    explanation_text = (
        "Please select the diagnostic options you wish to enable. "
        "These settings will be saved and applied in your diagnostics upon close."
        "\n\nPSD: Position Sensitive Detector\n"
        "DSD: Divergence Sensitive Detector\n"
        "Emonitor: Energy Monitor"
    )
    explanation_label = tk.Label(diagnostic_config_window, text=explanation_text, wraplength=400, justify="left")
    explanation_label.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

    # List of diagnostic options to display with checkboxes
    options = [
        "Source PSD",
        "Source DSD",
        "Postcollimation PSD",
        "Postcollimation DSD",
        "Premono Emonitor",
        "Postmono Emonitor",
        "Pre-sample collimation PSD",
        "Sample PSD @ L2-0.5",
        "Sample PSD @ L2-0.3",
        "Sample PSD @ Sample",
        "Sample DSD @ Sample",
        "Sample EMonitor @ Sample",
        "Pre-analyzer collimation PSD",
        "Pre-analyzer EMonitor",
        "Pre-analyzer PSD",
        "Post-analyzer EMonitor",
        "Post-analyzer PSD",
        "Detector PSD"
    ]

    # Dictionary to store checkbox variables
    monitor_config_vars = {}

    # Create a series of labels and checkboxes
    for i, option in enumerate(options):
        # Create a variable for each checkbox, fetch the value from diagnostic_settings or default to False
        monitor_config_var = tk.BooleanVar(value=diagnostic_settings.get(option, False))  # Fetch saved value or default
        monitor_config_vars[option] = monitor_config_var

        # Create a label and checkbox for each option
        label = tk.Label(diagnostic_config_window, text=option)
        label.grid(row=i + 1, column=0, padx=10, pady=5)

        checkbox = tk.Checkbutton(diagnostic_config_window, variable=monitor_config_var)
        checkbox.grid(row=i + 1, column=1, padx=10, pady=5)

    # Function to save the selected options and close the window
    def save_and_close():
        global diagnostic_settings
        global diagnostic_config_window
        # Update diagnostic_settings with the current checkbox values
        diagnostic_settings = {option: var.get() for option, var in monitor_config_vars.items()}
        puma_instrument.update_diagnostic_settings(diagnostic_settings)  # Update PUMA's settings
        # Call save_parameters to persist the settings
        save_parameters()
        # Close the diagnostic window
        diagnostic_config_window.destroy()
        # Reset the window tracking variable
        diagnostic_config_window = None

    # Save button at the bottom of the window
    save_button = ttk.Button(diagnostic_config_window, text="Save and Close", command=save_and_close)
    save_button.grid(row=len(options) + 1, column=0, columnspan=2, pady=10)

    # Handle window close event to reset the variable
    def on_close_diagnostics():
        global diagnostic_config_window
        if diagnostic_config_window:  # Ensure the window exists before trying to destroy it
            diagnostic_config_window.destroy()
        diagnostic_config_window = None  # Reset the window tracking variable

    diagnostic_config_window.protocol("WM_DELETE_WINDOW", on_close_diagnostics)

# Default sample settings
default_sample_settings = {
    "Aluminum rod Bragg": {"radius": 0.5, "yheight": 1.0, "mosaic": 0.1},
    "Aluminum rod acoustic phonon": {"radius": 0.5, "yheight": 1.0, "temperature": 300},
    "None": {}
}

#current_sample_settings = {}

# Function to open the sample configuration window
def configure_sample():
    global sample_config_window

    # Check if the window is already open
    if sample_config_window and tk.Toplevel.winfo_exists(sample_config_window):
        sample_config_window.lift()  # Bring the existing window to the front
        return

    # Create a new window
    sample_config_window = tk.Toplevel(root)
    sample_config_window.title("Sample Configuration")

    # Explanatory text
    explanation_text = (
        "Select a sample type from the dropdown menu, and configure the parameters specific to the sample."
    )
    explanation_label = tk.Label(sample_config_window, text=explanation_text, wraplength=400, justify="left")
    explanation_label.grid(row=0, column=0, columnspan=2, padx=10, pady=10)

    # Determine the last selected sample, defaulting to "None" if not found
    selected_sample_name = current_sample_settings.get("last_selected", "None")

    # Sample selection dropdown
    sample_type_var = tk.StringVar(value=selected_sample_name)
    sample_type_combobox = ttk.Combobox(
        sample_config_window, textvariable=sample_type_var, state="readonly",
        values=list(default_sample_settings.keys())  # Use default keys
    )
    sample_type_combobox.grid(row=1, column=0, columnspan=2, padx=10, pady=10)

    # Frame to hold dynamic options
    options_frame = tk.Frame(sample_config_window)
    options_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=10)

    # Dictionary to hold parameter variables (cleared and repopulated per sample)
    parameter_vars = {}

    # Function to update the options when the sample type changes
    def update_options():
        # Clear existing widgets in the options frame
        for widget in options_frame.winfo_children():
            widget.destroy()
        
        # Clear existing parameter variables
        parameter_vars.clear()

        # Get the selected sample type
        selected_sample = sample_type_var.get()

        # Reset current_sample_settings[selected_sample] to avoid carryover
        if selected_sample not in current_sample_settings:
            current_sample_settings[selected_sample] = {}

        # Fetch stored settings and default values
        stored_params = current_sample_settings[selected_sample]
        default_params = default_sample_settings.get(selected_sample, {})

        # Create a fresh dictionary containing only valid parameters
        combined_params = {param: stored_params.get(param, default_params.get(param, 0)) for param in default_params}

        # Create input fields for the selected sample's parameters
        for i, (param, value) in enumerate(combined_params.items()):
            tk.Label(options_frame, text=param).grid(row=i, column=0, padx=10, pady=5)
            param_var = tk.DoubleVar(value=value)
            parameter_vars[param] = param_var
            tk.Entry(options_frame, textvariable=param_var).grid(row=i, column=1, padx=10, pady=5)

    # Bind the combobox to update the options dynamically
    sample_type_combobox.bind("<<ComboboxSelected>>", lambda e: update_options())

    # Initially populate the options for the last selected sample
    update_options()

    # Function to save the selected sample and its parameters
    def save_and_close():
        global sample_config_window, current_sample_settings

        # Get the selected sample type
        selected_sample_name = sample_type_var.get()

        # Overwrite only the selected sample’s settings
        current_sample_settings[selected_sample_name] = {param: var.get() for param, var in parameter_vars.items()}

        # Update last selected sample
        current_sample_settings["last_selected"] = selected_sample_name

        # Call save_parameters to persist the settings
        save_parameters()

        # Close the sample configuration window
        sample_config_window.destroy()
        sample_config_window = None

    # Save button at the bottom of the window
    save_button = ttk.Button(sample_config_window, text="Save and Close", command=save_and_close)
    save_button.grid(row=3, column=0, columnspan=2, pady=10)

    # Handle window close event to reset the variable
    def on_close_sample():
        global sample_config_window
        if sample_config_window:
            sample_config_window.destroy()
        sample_config_window = None

    sample_config_window.protocol("WM_DELETE_WINDOW", on_close_sample)

def save_parameters():
    global diagnostic_settings, current_sample_settings
    parameters = {
        "mtt_var": mtt_var.get(),
        "stt_var": stt_var.get(),
        "psi_var": psi_var.get(),
        "att_var": att_var.get(),
        "Ki_var": Ki_var.get(),
        "Kf_var": Kf_var.get(),
        "Ei_var": Ei_var.get(),
        "Ef_var": Ef_var.get(),
        "number_neutrons_var": number_neutrons_var.get(),
        "K_fixed_var": K_fixed_var.get(),
        "NMO_installed_var": NMO_installed_var.get(),
        "V_selector_installed_var": V_selector_installed_var.get(),
        "rhmfac_var": rhmfac_var.get(),
        "rvmfac_var": rvmfac_var.get(),
        "rhafac_var": rhafac_var.get(),
        "fixed_E_var": fixed_E_var.get(),
        "qx_var": qx_var.get(),
        "qy_var": qy_var.get(),
        "qz_var": qz_var.get(),
        "deltaE_var": deltaE_var.get(),
        "monocris_var": monocris_var.get(),
        "anacris_var": anacris_var.get(),
        "alpha_1_var": alpha_1_var.get(),
        "alpha_2_30_var": alpha_2_30_var.get(),
        "alpha_2_40_var": alpha_2_40_var.get(),
        "alpha_2_60_var": alpha_2_60_var.get(),
        "alpha_3_var": alpha_3_var.get(),
        "alpha_4_var": alpha_4_var.get(),
        "diagnostic_mode_var": diagnostic_mode_var.get(),
        "lattice_a_var": lattice_a_var.get(),
        "lattice_b_var": lattice_b_var.get(),
        "lattice_c_var": lattice_c_var.get(),
        "lattice_alpha_var": lattice_alpha_var.get(),
        "lattice_beta_var": lattice_beta_var.get(),
        "lattice_gamma_var": lattice_gamma_var.get(),
        "scan_command_var1": scan_command_var1.get(),
        "scan_command_var2": scan_command_var2.get(),
        "diagnostic_settings": diagnostic_settings,
        "current_sample_settings": current_sample_settings
    }
    with open("parameters.json", "w") as file:
        json.dump(parameters, file)

# Function to load parameters from a file
def load_parameters():
    global diagnostic_settings, current_sample_settings
    if os.path.exists("parameters.json"):
        with open("parameters.json", "r") as file:
            parameters = json.load(file)
            monocris_var.set(parameters.get("monocris_var", "PG[002]"))
            anacris_var.set(parameters.get("anacris_var", "PG[002]"))
            mtt_var.set(parameters.get("mtt_var", "30"))
            stt_var.set(parameters.get("stt_var", "30"))
            psi_var.set(parameters.get("psi_var", 30))
            att_var.set(parameters.get("att_var", 30))
            Ki_var.set(parameters.get("Ki_var", "2.662"))
            Kf_var.set(parameters.get("Kf_var", "2.662"))
            Ei_var.set(parameters.get("Ei_var", "14.7"))
            Ef_var.set(parameters.get("Ef_var", "14.7"))
            GUIcalc.update_mtt_from_Ei(Ei_var, mtt_var, Ki_var, monocris_info)
            GUIcalc.update_att_from_Ef(Ef_var, att_var, Kf_var, anacris_info)
            NMO_installed_var.set(parameters.get("NMO_installed_var", "None"))
            V_selector_installed_var.set(parameters.get("V_selector_installed_var", False))
            rhmfac_var.set(parameters.get("rhmfac_var", 1))
            rvmfac_var.set(parameters.get("rvmfac_var", 1))
            rhafac_var.set(parameters.get("rhafac_var", 1))
            alpha_1_var.set(parameters.get("alpha_1_var", 40))
            alpha_2_30_var.set(parameters.get("alpha_2_30_var", False))
            alpha_2_40_var.set(parameters.get("alpha_2_40_var", True))
            alpha_2_60_var.set(parameters.get("alpha_2_60_var", False))
            alpha_3_var.set(parameters.get("alpha_3_var", 30))
            alpha_4_var.set(parameters.get("alpha_4_var", 30))

            number_neutrons_var.set(parameters.get("number_neutrons_var", 1e8))
            K_fixed_var.set(parameters.get("K_fixed_var", "Kf Fixed"))
            fixed_E_var.set(parameters.get("fixed_E_var", 14.7))
            qx_var.set(parameters.get("qx_var", 2))
            qy_var.set(parameters.get("qy_var", 0))
            qz_var.set(parameters.get("qz_var", 0))
            deltaE_var.set(parameters.get("deltaE_var", 5.25))
            diagnostic_mode_var.set(parameters.get("diagnostic_mode_var", True))
            scan_command_var1.set(parameters.get("scan_command_var1", ""))
            scan_command_var2.set(parameters.get("scan_command_var2", ""))

            lattice_a_var.set(parameters.get("lattice_a_var", 4.05))
            lattice_b_var.set(parameters.get("lattice_b_var", 4.05))
            lattice_c_var.set(parameters.get("lattice_c_var", 4.05))
            lattice_alpha_var.set(parameters.get("lattice_alpha_var", 90))
            lattice_beta_var.set(parameters.get("lattice_beta_var", 90))
            lattice_gamma_var.set(parameters.get("lattice_gamma_var", 90))
            GUIcalc.update_HKL_from_Q(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
            
            diagnostic_settings = parameters.get("diagnostic_settings", {
                "Source PSD": False,
                "Source DSD": False,
                "Postcollimation PSD": False,
                "Postcollimation DSD": False,
                "Premono Emonitor": False,
                "Postmono Emonitor": False,
                "Pre-sample collimation PSD": False,
                "Sample PSD @ L2-0.5": False,
                "Sample PSD @ L2-0.3": False,
                "Sample PSD @ Sample": False,
                "Sample DSD @ Sample": False,
                "Sample EMonitor @ Sample": False,
                "Pre-analyzer collimation PSD": False,
                "Pre-analyzer EMonitor": False,
                "Pre-analyzer PSD": False,
                "Post-analyzer EMonitor": False,
                "Post-analyzer PSD": False,
                "Detector PSD": False
            })

            # Load current sample settings or default to empty
            current_sample_settings = parameters.get("current_sample_settings", {})

    else:
        set_default_parameters()
        current_sample_settings = {}  # Initialize empty sample settings if no file exists

# Function to set default parameters
def set_default_parameters():
    global diagnostic_settings
    
    monocris_var.set("PG[002]")
    anacris_var.set("PG[002]")
    mtt_var.set("30")
    stt_var.set("30")
    psi_var.set(30)
    att_var.set(30)
    Ki_var.set("2.662")
    Kf_var.set("2.662")
    Ei_var.set("14.7")
    Ef_var.set("14.7")
    NMO_installed_var.set("None")
    V_selector_installed_var.set(False)
    rhmfac_var.set(1)
    rvmfac_var.set(1)
    rhafac_var.set(1)
    alpha_1_var.set(40)
    alpha_2_30_var.set(False)
    alpha_2_40_var.set(True)
    alpha_2_60_var.set(False)
    alpha_3_var.set(30)
    alpha_4_var.set(30)
    
    number_neutrons_var.set(1e6)
    K_fixed_var.set("Kf Fixed")
    fixed_E_var.set(14.7)
    qx_var.set(2)
    qy_var.set(0)
    qz_var.set(0)
    deltaE_var.set(5.25)
    diagnostic_mode_var.set(True)
    
    lattice_a_var.set(3.78)
    lattice_b_var.set(3.78)
    lattice_c_var.set(5.49)
    lattice_alpha_var.set(90)
    lattice_beta_var.set(90)
    lattice_gamma_var.set(90)
    scan_command_var1.set("qx 2 2.2 0.1")
    scan_command_var2.set("deltaE 3 7 0.25")
    GUIcalc.update_HKL_from_Q(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)

    diagnostic_settings = {
            "Source PSD": False,
            "Source DSD": False,
            "Postcollimation PSD": False,
            "Postcollimation DSD": False,
            "Premono Emonitor": False,
            "Postmono Emonitor": False,
            "Pre-sample collimation PSD": False,
            "Sample PSD @ L2-0.5": False,
            "Sample PSD @ L2-0.3": False,
            "Sample PSD @ Sample": False,
            "Sample DSD @ Sample": False,
            "Sample EMonitor @ Sample": False,
            "Pre-analyzer collimation PSD": False,
            "Pre-analyzer EMonitor": False,
            "Pre-analyzer PSD": False,
            "Post-analyzer EMonitor": False,
            "Post-analyzer PSD": False,
            "Detector PSD": False
            }

def open_validation_window(validation_K_fixed, validation_fixed_E, validation_qx, validation_qy, validation_qz, validation_deltaE, validation_monocris, validation_anacris):

    validation_gui = tk.Toplevel()
    validation_gui.title("Validation GUI")
    validation_gui.focus()
    validation_gui.update()

    validation_frame = ttk.Frame(validation_gui, padding="10")
    validation_frame.pack(padx=10, pady=10)

    # command line 1, x axis
    ttk.Label(validation_frame, text="X axis:").grid(row=0, column=0, sticky="w")
    validation_xAxis_line = ttk.Entry(validation_frame)
    validation_xAxis_line.insert(0, "qx 0.1 0.5 0.05")  # a generic test value for now
    validation_xAxis_line.grid(row=0, column=1, pady=5)

    # command line 2, y axis
    ttk.Label(validation_frame, text="Y axis:").grid(row=1, column=0, sticky="w")
    validation_yAxis_line = ttk.Entry(validation_frame)
    validation_yAxis_line.insert(1, "deltaE -2 12 0.25")  # a generic test value for now
    validation_yAxis_line.grid(row=1, column=1, pady=5)

    # display everything below it
    # Label and Entry for validation_K_fixed
    ttk.Label(validation_frame, text="Ki or Kf fixed:").grid(row=2, column=0, sticky="w")
    validation_K_fixed_label = ttk.Label(validation_frame, text=str(validation_K_fixed))
    validation_K_fixed_label.grid(row=2, column=1, pady=5)

    # Label and Entry for validation_fixed_E
    ttk.Label(validation_frame, text="fixed E:").grid(row=3, column=0, sticky="w")
    validation_fixed_E_label = ttk.Label(validation_frame, text=str(validation_fixed_E))
    validation_fixed_E_label.grid(row=3, column=1, pady=5)

    # Label and Entry for validation_qx
    ttk.Label(validation_frame, text="qx:").grid(row=4, column=0, sticky="w")
    validation_qx_label = ttk.Label(validation_frame, text=str(validation_qx))
    validation_qx_label.grid(row=4, column=1, pady=5)

    # Label and Entry for validation_qy
    ttk.Label(validation_frame, text="qy:").grid(row=5, column=0, sticky="w")
    validation_qy_label = ttk.Label(validation_frame, text=str(validation_qy))
    validation_qy_label.grid(row=5, column=1, pady=5)

    # Label and Entry for validation_qz
    ttk.Label(validation_frame, text="qz:").grid(row=6, column=0, sticky="w")
    validation_qz_label = ttk.Label(validation_frame, text=str(validation_qz))
    validation_qz_label.grid(row=6, column=1, pady=5)

    # Label and Entry for validation_deltaE
    ttk.Label(validation_frame, text="deltaE:").grid(row=7, column=0, sticky="w")
    validation_deltaE_label = ttk.Label(validation_frame, text=str(validation_deltaE))
    validation_deltaE_label.grid(row=7, column=1, pady=5)

    # Label and Entry for validation_monocris
    ttk.Label(validation_frame, text="Monochromator crystal:").grid(row=8, column=0, sticky="w")
    validation_monocris_label = ttk.Label(validation_frame, text=str(validation_monocris))
    validation_monocris_label.grid(row=8, column=1, pady=5)

    # Label and Entry for validation_anacris
    ttk.Label(validation_frame, text="Analyzer crystal:").grid(row=9, column=0, sticky="w")
    validation_anacris_label = ttk.Label(validation_frame, text=str(validation_anacris))
    validation_anacris_label.grid(row=9, column=1, pady=5)

    validation_gui.update_idletasks()

    # Button to run validation
    run_validation_button = ttk.Button(validation_frame, text="Run Validation", command=lambda: validate_scans(validation_xAxis_line.get(), validation_yAxis_line.get(),
    validation_qx, validation_qy, validation_qz, validation_deltaE, validation_K_fixed, validation_fixed_E, validation_monocris, validation_anacris               
    ))
    run_validation_button.grid(row=10, column=0, columnspan=2, pady=10)

def validate_scans(x_axis_command, y_axis_command, qx_validate, qy_validate, qz_validate, deltaE_validate, K_fixed, fixed_E, monocris, anacris):

    xAxis_variable_name, xAxis_array_values = parse_scan_steps(x_axis_command)
    yAxis_variable_name, yAxis_array_values = parse_scan_steps(y_axis_command)

    # Create a 2D array to store validation results (0: valid, 1: not valid)
    validation_results = np.zeros((len(xAxis_array_values), len(yAxis_array_values)))
    print(x_axis_command)
    for i, xvariable_value in enumerate(xAxis_array_values):
        if xAxis_variable_name == 'deltaE':
            deltaE_validate = xvariable_value
        elif xAxis_variable_name == 'qx':
            qx_validate = xvariable_value
        elif xAxis_variable_name == 'qy':
            qy_validate = xvariable_value
        elif xAxis_variable_name == 'qz':
            qz_validate = xvariable_value
        for j, yvariable_value in enumerate(yAxis_array_values):
            if yAxis_variable_name == 'deltaE':
                deltaE_validate = yvariable_value
            elif yAxis_variable_name == 'qx':
                qx_validate = yvariable_value
            elif yAxis_variable_name == 'qy':
                qy_validate = yvariable_value
            elif yAxis_variable_name == 'qz':
                qz_validate = yvariable_value

            validation_error_flags = validate_angles(K_fixed, fixed_E, qx_validate, qy_validate, qz_validate, deltaE_validate, monocris, anacris)
            # Check if validation result is not empty (not valid)
            if validation_error_flags:
                validation_results[i, j] = 1
            validation_results_transposed = np.transpose(validation_results)

    # Plot the 2D array (white: valid, black: not valid)
    plt.imshow(validation_results_transposed, cmap='binary', origin='lower')
    plt.xlabel(xAxis_variable_name)
    plt.ylabel(yAxis_variable_name)
    plt.title('Validation Results')
    x_ticks = np.linspace(0, len(xAxis_array_values) - 1, 3, dtype=int)  # Adjust the number of ticks as needed
    x_axis_ticks = np.around([xAxis_array_values[i] for i in x_ticks], decimals=3)
    y_ticks = np.linspace(0, len(yAxis_array_values) - 1, 5, dtype=int)  # Adjust the number of ticks as needed
    plt.xticks(x_ticks, x_axis_ticks)
    plt.yticks(y_ticks, [yAxis_array_values[i] for i in y_ticks])
    plt.show()
       
class SimulationParameters:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        if name in self.__dict__:
            return self.__dict__[name]
        else:
            raise AttributeError(f"'SimulationParameters' object has no attribute '{name}'")


def get_simulation_parameters():
    parameters = SimulationParameters(
        number_neutrons=number_neutrons_var.get(),
        K_fixed=K_fixed_var.get(),
        NMO_installed=NMO_installed_var.get(),
        V_selector_installed=V_selector_installed_var.get(),
        rhmfac = rhmfac_var.get(),
        rvmfac = rvmfac_var.get(),
        rhafac = rhafac_var.get(),
        fixed_E=fixed_E_var.get(),
        lattice_a=lattice_a_var.get(),
        lattice_b=lattice_b_var.get(),
        lattice_c=lattice_c_var.get(),
        lattice_alpha = lattice_alpha_var.get(),
        lattice_beta = lattice_beta_var.get(),
        lattice_gamma = lattice_gamma_var.get(),
        qx=qx_var.get(),
        qy=qy_var.get(),
        qz=qz_var.get(),
        deltaE=deltaE_var.get(),
        monocris=monocris_var.get(),
        anacris=anacris_var.get(),
        alpha_1=alpha_1_var.get(),
        alpha_2_30=alpha_2_30_var.get(),
        alpha_2_40=alpha_2_40_var.get(),
        alpha_2_60=alpha_2_60_var.get(),
        alpha_3=alpha_3_var.get(),
        alpha_4=alpha_4_var.get(),
        scan_command1=scan_command_var1.get().strip(),
        scan_command2=scan_command_var2.get().strip(),
        diagnostic_mode=diagnostic_mode_var.get(),
        H=lattice_H_var.get(),
        K=lattice_K_var.get(),
        L=lattice_L_var.get()
    )
    return parameters

# Updates the progress bar of the tkinker window
def update_progress(current, total):
    percentage = int(current * 100 / total)
    progress_bar["value"] = percentage
    progress_label.config(text=f"{percentage}% ({current}/{total})")
    
# Define the update_remaining_time function to update the label
def update_remaining_time(remaining_time):
    remaining_time_label.config(text="Remaining Time: " + remaining_time)
    
# Function to update the total counts entry
def update_counts_entry(max_counts, total_counts):
    max_counts_entry.config(text=max_counts)
    total_counts_entry.config(text=total_counts)
    
# Define printing messages to the message center
def print_to_message_center(message, target='both'):
    global message_center_text
    if message_center_text:
        if target in ('both', 'GUI'):
            message_center_text.insert(tk.END, message + '\n')
            message_center_text.see(tk.END)  # Scroll to the end to always show the latest message
        if target in ('both', 'console'):
            print(message)
            
# Open file explorer dialog
def open_folder_dialog(entry_widget):
    default_folder = os.getcwd()
    folder_selected = filedialog.askdirectory(initialdir=default_folder)
    if folder_selected:
        entry_widget.delete(0, tk.END)  # Clear the existing content
        entry_widget.insert(0, folder_selected)  # Insert the selected folder path into the entry widget
         
# Function to run the simulation in a separate thread
def run_simulation_thread():
    global simulation_thread
    global stop_flag
    stop_flag = False
    simulation_thread = threading.Thread(target=run_simulation, args=(PUMA, save_folder_label_var.get(),))
    simulation_thread.start()
    
# Function to stop the simulation
def stop_simulation():
    global stop_flag
    stop_flag = True

def run_simulation(PUMA, data_folder):
    save_parameters()

    global stop_flag
    total_counts = 0
    max_counts = 0
    # Get the output folder from the text box
    data_folder = save_folder_label_var.get()
    # If the folder already exists, increment instead
    new_data_folder = incremented_path_writing(output_directory, data_folder)
    # Inside the `run_simulation` function after creating or incrementing the folder
    folder_label_actual_var.set(new_data_folder)
    data_folder = new_data_folder

    # Get values from the GUI and run the simulation
    parameters = get_simulation_parameters()
    number_neutrons = parameters.number_neutrons
    PUMA.K_fixed = parameters.K_fixed
    PUMA.NMO_installed = parameters.NMO_installed
    PUMA.V_selector_installed = parameters.V_selector_installed
    PUMA.rhmfac = parameters.rhmfac
    PUMA.rvmfac = parameters.rvmfac
    PUMA.rhafac = parameters.rhafac
    PUMA.fixed_E = float(parameters.fixed_E)
    lattice_a = parameters.lattice_a
    lattice_b = parameters.lattice_b
    lattice_c = parameters.lattice_c
    lattice_alpha = parameters.lattice_alpha
    lattice_beta = parameters.lattice_beta
    lattice_gamma = parameters.lattice_gamma
    qx = parameters.qx
    qy = parameters.qy
    qz = parameters.qz
    deltaE = float(parameters.deltaE)
    PUMA.monocris = parameters.monocris
    PUMA.anacris = parameters.anacris
    PUMA.alpha_1 = parameters.alpha_1
    alpha_2_30 = parameters.alpha_2_30
    alpha_2_40 = parameters.alpha_2_40
    alpha_2_60 = parameters.alpha_2_60
    PUMA.alpha_3 = parameters.alpha_3
    PUMA.alpha_4 = parameters.alpha_4
    scan_command1 = parameters.scan_command1
    scan_command2 = parameters.scan_command2
    diagnostic_mode = parameters.diagnostic_mode
    H = parameters.H
    K = parameters.K
    L = parameters.L

    PUMA.alpha_2 = [alpha_2_30*30, alpha_2_40*40, alpha_2_60*60]

    write_parameters_to_file(data_folder, parameters)

    QE_parameter_array = []
    counts_array = []
    error_flag_array = []

    QE_parameter_array_header = ["qx", "qy", "qz", "deltaE"]
    instrument_parameter_array_header = ["number_neutrons", "K_fixed", "NMO_installed", "V_selector_installed", "fixed_E", "monocris", "anacris", "alpha_1", "alpha_2", "alpha_3", "alpha_4", "mtt", "stt", "saz", "att"]

    ## a function to take two scan commands and build a 2D array of scans
    scan_parameter_input = [] #should be an array of qx,qy,qz,deltaE for all scan points
    # Mode: 'momentum' or 'angle'
    scan_mode = "momentum"  # Change to "angle" for angle mode or "rlu" for rlu mode
    if "qx" in scan_command1 or "qy" in scan_command1 or "qz" in scan_command1:
        scan_mode = "momentum"
    elif "H" in scan_command1 or "K" in scan_command1 or "L" in scan_command1:
        scan_mode = "rlu"
    elif "A1" in scan_command1 or "A2" in scan_command1 or "A3" in scan_command1 or "A4" in scan_command1:
        scan_mode = "angle"

    # Mapping for scannable parameters
    variable_to_index = {
        'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,  # Momentum mode
        'H': 0, 'K': 1, 'L': 2, 'deltaE': 3,  # rlu mode
        'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,     # Angle mode
        'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7  # Always scannable
    }

    # Initialize scan point template for all parameters
    scan_point_template = [0] * 8  # qx, qy, qz, H, K, L, deltaE, rhm, rvm, rha, rva
    if scan_mode == "momentum":
        scan_point_template[:4] = [qx, qy, qz, deltaE]
    elif scan_mode == "rlu":
        scan_point_template[:4] = [H, K, L, deltaE]
    elif scan_mode == "angle":
        scan_point_template[:4] = [0, 0, 0, 0]  # Angles explicitly set during scan

    if not(scan_command1) and not(scan_command2):
        scan_parameter_input.append(scan_point_template[:])

    if scan_command2 and not(scan_command1):
        scan_command1 = scan_command2
        scan_command2 = None
        
    angle_commands = ["A1", "A2", "A3", "A4"]
    momentum_commands = ["qx", "qy", "qz"]
    rlu_commands = ["H", "K", "L"]

    puma_instance = PUMA_Instrument()
    
    variable_name1 = ""
    variable_name2 = ""

    # Single scan command
    if scan_command1 and not(scan_command2):
        variable_name1, array_values1 = parse_scan_steps(scan_command1)
        for value1 in array_values1:
            scan_point = scan_point_template[:]
            scan_point[variable_to_index[variable_name1]] = value1
            if scan_mode == "momentum":
                _, error_flags = puma_instance.calculate_angles(
                    *scan_point[:4], PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
                )
            elif scan_mode == "rlu":
                # Convert HKL to qx, qy, qz
                qx, qy, qz = update_Q_from_HKL_direct(scan_point[0], scan_point[1], scan_point[2], parameters.lattice_a, parameters.lattice_b, parameters.lattice_c, parameters.lattice_alpha, parameters.lattice_beta, parameters.lattice_gamma)
                _, error_flags = puma_instance.calculate_angles(
                    qx, qy, qz, scan_point[3], PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
                )
            else:  # angle mode
                error_flags = []  # No validation required for angle mode
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
                        *scan_point[:4], PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
                    )
                elif scan_mode == "rlu":
                    # Convert HKL to qx, qy, qz
                    qx, qy, qz = update_Q_from_HKL_direct(scan_point[0], scan_point[1], scan_point[2], parameters.lattice_a, parameters.lattice_b, parameters.lattice_c, parameters.lattice_alpha, parameters.lattice_beta, parameters.lattice_gamma)
                    _, error_flags = puma_instance.calculate_angles(
                        qx, qy, qz, scan_point[3], PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
                    )
                else:
                    error_flags = []  # No validation required for angle mode
                if not error_flags:
                    scan_parameter_input.append(scan_point)

    # Running the scans
    start_time = time.time()
    total_time = 0
    last_iteration_time = start_time
    progress_bar.start(10)
    total_scans = len(scan_parameter_input)

    for i, scans in enumerate(scan_parameter_input):
        if stop_flag:
            print_to_message_center("Simulation stopped by user.", 'both')
            return data_folder

        # Extract scannable parameters
        if scan_mode == "momentum":
            qx, qy, qz, deltaE = scans[:4]
            angles_array, error_flags = PUMA.calculate_angles(
                qx, qy, qz, deltaE, PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
            )
            mtt, stt, sth, saz, att = angles_array
            if not error_flags:
                PUMA.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
        elif scan_mode == "rlu":
            H, K, L, deltaE = scans[:4]
            qx, qy, qz = update_Q_from_HKL_direct(H, K, L, parameters.lattice_a, parameters.lattice_b, parameters.lattice_c, parameters.lattice_alpha, parameters.lattice_beta, parameters.lattice_gamma)
            angles_array, error_flags = PUMA.calculate_angles(
                qx, qy, qz, deltaE, PUMA.fixed_E, PUMA.K_fixed, PUMA.monocris, PUMA.anacris
            )
            mtt, stt, sth, saz, att = angles_array
            if not error_flags:
                PUMA.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
        else:  # Angle mode
            A1, A2, A3, A4 = scans[:4]
            PUMA.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)

        rhm, rvm, rha, rva = scans[4], scans[5], scans[6], scans[7]  # Use value from scan

        # Check if 'rhm', 'rvm', 'rha', 'rva' are part of the scan commands
        if 'rhm' not in [variable_name1, variable_name2]:
            rhm = PUMA.calculate_crystal_bending(PUMA.rhmfac, PUMA.rvmfac, PUMA.rhafac, PUMA.A1, PUMA.A4)[0]
        if 'rvm' not in [variable_name1, variable_name2]:
            rvm = PUMA.calculate_crystal_bending(PUMA.rhmfac, PUMA.rvmfac, PUMA.rhafac, PUMA.A1, PUMA.A4)[1]
        if 'rha' not in [variable_name1, variable_name2]:
            rha = PUMA.calculate_crystal_bending(PUMA.rhmfac, PUMA.rvmfac, PUMA.rhafac, PUMA.A1, PUMA.A4)[2]
        if 'rva' not in [variable_name1, variable_name2]:
            rva = PUMA.calculate_crystal_bending(PUMA.rhmfac, PUMA.rvmfac, PUMA.rhafac, PUMA.A1, PUMA.A4)[3]

        # Update crystal bending parameters
        PUMA.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)

        # Generate dynamic scan folder name
        scan_description = []
        if scan_mode == "momentum":
            scan_description.extend([
                f"qx_{letter_encode_number(qx)}",
                f"qy_{letter_encode_number(qy)}",
                f"qz_{letter_encode_number(qz)}",
                f"dE_{letter_encode_number(deltaE)}"
            ])
        elif scan_mode == "rlu":
            scan_description.extend([
                f"H_{letter_encode_number(H)}",
                f"K_{letter_encode_number(K)}",
                f"L_{letter_encode_number(L)}",
                f"dE_{letter_encode_number(deltaE)}"
            ])
        else:  # Angle mode
            scan_description.extend([
                f"A1_{letter_encode_number(A1)}",
                f"A2_{letter_encode_number(A2)}",
                f"A3_{letter_encode_number(A3)}",
                f"A4_{letter_encode_number(A4)}"
            ])
    
        # Include crystal bending parameters
        scan_description.extend([
            f"rhm_{letter_encode_number(rhm)}",
            f"rvm_{letter_encode_number(rvm)}",
            f"rha_{letter_encode_number(rha)}",
            f"rva_{letter_encode_number(rva)}"
        ])

        # Combine description for folder
        scan_folder = os.path.join(data_folder, "_".join(scan_description))

        # Log parameters and start simulation
        if scan_mode == "momentum":
            message = (f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
                       f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}")
        elif scan_mode == "rlu":
            message = (f"Scan parameters - H: {H}, K: {K}, L: {L}, deltaE: {deltaE}\n"
                       f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}")
        else:
            message = (f"Scan parameters - A1: {A1}, A2: {A2}, A3: {A3}, A4: {A4}\n"
                       f"rhm: {rhm:.2f}, rvm: {rvm:.2f}, rha: {rha:.2f}, rva: {rva:.2f}")
        print_to_message_center(message, 'GUI')

        data, error_flags = run_PUMA_instrument(
            PUMA, number_neutrons, deltaE, diagnostic_mode, diagnostic_settings, scan_folder, i
        )
        if error_flags:
            message = f"Scan failed, error flags: {error_flags}"
            print_to_message_center(message, 'both')
        else:
            write_parameters_to_file(scan_folder, parameters)
            intensity, intensity_error, counts = read_1Ddetector_file(scan_folder)
            message = f"Final counts at detector: {int(counts)}"
            max_counts = max(max_counts, counts)
            total_counts += counts
            print_to_message_center(message, 'GUI')

        update_progress(i + 1, total_scans)
        progress_bar.update()
        update_counts_entry(max_counts, total_counts)
        root.update()

        # Update time tracking
        current_iteration_time = time.time()
        iteration_time = current_iteration_time - last_iteration_time
        last_iteration_time = current_iteration_time

        # Update the total time taken so far
        total_time += iteration_time

        # Calculate average time per scan dynamically
        average_time_per_scan = total_time / (i + 1) if i + 1 > 0 else 0

        # Estimate remaining time
        remaining_scans = total_scans - (i + 1)
        remaining_time = remaining_scans * average_time_per_scan

        # Convert remaining time to datetime format for better readability and update
        remaining_time_formatted = str(datetime.timedelta(seconds=int(remaining_time)))
        update_remaining_time(remaining_time_formatted)

    total_time_formatted = str(datetime.timedelta(seconds=int(total_time)))
    message = "Scans finished, total time taken: " + total_time_formatted
    print_to_message_center(message, 'GUI')

    progress_bar.stop()
    
    if scan_command1:
        simple_plot_scan_commands(scan_point, data_folder)

    if diagnostic_mode is True and not scan_command1 and not scan_command2:
        #ms.make_plot(data) # This makes a plot for each detector
        ms.make_sub_plot(data, log=False) # This makes one plot for all detectors

    return data_folder 

# Create a PUMA class to keep
PUMA = PUMA_Instrument()

# Create the main window
root = tk.Tk()
root.title("McStas Parameter Selection")

## PUMA variables
mtt_var = tk.StringVar() # mono 2theta
stt_var = tk.DoubleVar() # sample 2theta
psi_var = tk.DoubleVar() # sample theta, psi                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    
att_var = tk.StringVar() # analyzer 2theta
Ki_var = tk.StringVar()
Ei_var = tk.StringVar()
Kf_var = tk.StringVar()
Ef_var = tk.StringVar()
rhmfac_var = tk.DoubleVar()
rvmfac_var = tk.DoubleVar()
rhafac_var = tk.DoubleVar()
monocris_var = tk.StringVar()
anacris_var = tk.StringVar()
alpha_1_var = tk.DoubleVar()
alpha_2_30_var = tk.BooleanVar()
alpha_2_40_var = tk.BooleanVar()
alpha_2_60_var = tk.BooleanVar()
alpha_3_var = tk.DoubleVar()
alpha_4_var = tk.DoubleVar()
NMO_installed_var = tk.StringVar()
V_selector_installed_var = tk.BooleanVar()

## Scan variables
number_neutrons_var = tk.IntVar()
K_fixed_var = tk.StringVar()
fixed_E_var = tk.StringVar()
qx_var = tk.DoubleVar()
qy_var = tk.DoubleVar()
qz_var = tk.DoubleVar()
deltaE_var = tk.StringVar()
diagnostic_mode_var = tk.BooleanVar()
scan_command_var1 = tk.StringVar()
scan_command_var2 = tk.StringVar()

## Sample variables
lattice_a_var = tk.DoubleVar()
lattice_b_var = tk.DoubleVar()
lattice_c_var = tk.DoubleVar()
lattice_alpha_var = tk.DoubleVar()
lattice_beta_var = tk.DoubleVar()
lattice_gamma_var = tk.DoubleVar()
lattice_H_var = tk.StringVar()
lattice_K_var = tk.StringVar()
lattice_L_var = tk.StringVar()

# Define variables to hold crystal information
monocris_info = {}
anacris_info = {}

# Callback functions to update crystal information
def update_monocris_info(*args):
    global monocris_info
    monocris_info, _ = mono_ana_crystals_setup(monocris_var.get(), anacris_var.get())
    GUIcalc.update_all_variables(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

def update_anacris_info(*args):
    global anacris_info
    _, anacris_info = mono_ana_crystals_setup(monocris_var.get(), anacris_var.get())
    GUIcalc.update_all_variables(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
     
def bind_update_events(widget, update_function, *args):
    widget.bind("<FocusOut>", lambda event: update_function(*args))
    widget.bind("<Return>", lambda event: update_function(*args))

# Traces to update cells when variables change
monocris_var.trace_add("write", update_monocris_info)
anacris_var.trace_add("write", update_anacris_info)

# Load parameters if available
load_parameters()
GUIcalc.update_all_variables(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

## PUMA instrument frame                                                                                                                                                                                         
instrument_frame = ttk.Frame(root, padding="10")
instrument_frame.grid(row=0, column=0, sticky="nsew")

angles_frame = ttk.Frame(instrument_frame)
angles_frame.grid(row=0, column=0, stick="nsew")
ttk.Label(angles_frame, text="Mono 2θ:").grid(row=0, column=0, sticky="w")
mtt_entry = ttk.Entry(angles_frame, textvariable=mtt_var, width=6)
mtt_entry.grid(row=0, column=1, pady=5)
bind_update_events(mtt_entry, GUIcalc.update_from_mtt, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
ttk.Label(angles_frame, text="Sample 2θ:").grid(row=0, column=2, sticky="w")
stt_entry = ttk.Entry(angles_frame, textvariable=stt_var, width=6)
stt_entry.grid(row=0, column=3, pady=5)
ttk.Label(angles_frame, text="Sample Ψ:").grid(row=0, column=4, sticky="w")
psi_entry = ttk.Entry(angles_frame, textvariable=psi_var, width=6)
psi_entry.grid(row=0, column=5, pady=5)
ttk.Label(angles_frame, text="Ana 2θ:").grid(row=0, column=6, sticky="w")
att_entry = ttk.Entry(angles_frame, textvariable=att_var, width=6)
att_entry.grid(row=0, column=7, pady=5)
bind_update_events(att_entry, GUIcalc.update_from_att, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

bind_update_events(mtt_entry, GUIcalc.update_Q_from_angles, mtt_var, stt_var, psi_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)
bind_update_events(stt_entry, GUIcalc.update_Q_from_angles, mtt_var, stt_var, psi_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)
bind_update_events(psi_entry, GUIcalc.update_Q_from_angles, mtt_var, stt_var, psi_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)
bind_update_events(att_entry, GUIcalc.update_Q_from_angles, mtt_var, stt_var, psi_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)

energies_frame = ttk.Frame(instrument_frame)
energies_frame.grid(row=1, column=0, sticky="nsew")
ttk.Label(energies_frame, text="Ki (1/Å):").grid(row=0, column=0, sticky="w")
Ki_entry = ttk.Entry(energies_frame, textvariable=Ki_var, width=7)
Ki_entry.grid(row=0, column=1, pady=5)
bind_update_events(Ki_entry, GUIcalc.update_from_Ki, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
ttk.Label(energies_frame, text="Ei (meV):").grid(row=0, column=2, sticky="w")
Ei_entry = ttk.Entry(energies_frame, textvariable=Ei_var, width=7)
Ei_entry.grid(row=0, column=3, pady=5)
bind_update_events(Ei_entry, GUIcalc.update_from_Ei, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
ttk.Label(energies_frame, text="Kf (1/Å):").grid(row=0, column=4, sticky="w")
Kf_entry = ttk.Entry(energies_frame, textvariable=Kf_var, width=7)
Kf_entry.grid(row=0, column=5, pady=5)
bind_update_events(Kf_entry, GUIcalc.update_from_Kf, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
ttk.Label(energies_frame, text="Ef (meV):").grid(row=0, column=6, sticky="w")
Ef_entry = ttk.Entry(energies_frame, textvariable=Ef_var, width=7)
Ef_entry.grid(row=0, column=7, pady=5)
bind_update_events(Ef_entry, GUIcalc.update_from_Ef, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

crystals_frame = ttk.Frame(instrument_frame)
crystals_frame.grid(row=2, column=0, sticky="nsew")
ttk.Label(crystals_frame, text="Monochromator crystal:").grid(row=0, column=0, sticky="w")
ttk.Combobox(crystals_frame, textvariable=monocris_var, values=["PG[002]", "PG[002] test"]).grid(row=0, column=1, pady=5)
ttk.Label(crystals_frame, text="Analyzer crystal:").grid(row=1, column=0, sticky="w")
ttk.Combobox(crystals_frame, textvariable=anacris_var, values=["PG[002]"]).grid(row=1, column=1, pady=5)

optics_frame = ttk.Frame(instrument_frame)
optics_frame.grid(row=3, column=0, sticky="nsew")

ttk.Label(optics_frame, text="NMO installed:").grid(row=0, column=0, sticky="w")
ttk.Combobox(optics_frame, textvariable=NMO_installed_var, values=["None", "Vertical", "Horizontal", "Both"]).grid(row=0, column=1, pady=5)
velocity_selector_checkbox = ttk.Checkbutton(optics_frame, text="Enable velocity selector", variable=V_selector_installed_var, onvalue=True, offvalue=False)
velocity_selector_checkbox.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 5))  # Added extra padding
ttk.Label(optics_frame, text="(Use in Ki fixed mode)").grid(row=1, column=1, columnspan=2, sticky="w")
ttk.Label(optics_frame, text="rhm factor:").grid(row=3, column=0, sticky="w")
ttk.Entry(optics_frame, textvariable=rhmfac_var).grid(row=3, column=1, pady=5)
ttk.Label(optics_frame, text="rvm factor:").grid(row=4, column=0, sticky="w")
ttk.Entry(optics_frame, textvariable=rvmfac_var).grid(row=4, column=1, pady=5)
ttk.Label(optics_frame, text="rha factor:").grid(row=5, column=0, sticky="w")
ttk.Entry(optics_frame, textvariable=rhafac_var).grid(row=5, column=1, pady=5)

collimations_frame = ttk.Frame(instrument_frame)
collimations_frame.grid(row=4, column=0, sticky="nsew")
ttk.Label(collimations_frame, text="Alpha 1 (source-mono) collimation:").grid(row=0, column=0, sticky="w")
ttk.Combobox(collimations_frame, textvariable=alpha_1_var, values=[0, 20, 40, 60]).grid(row=0, column=1, pady=5)
ttk.Label(collimations_frame, text="'").grid(row=0, column=2, sticky="w", padx=(5, 0))
# handling the alpha 2 collimators is a little more complicated because multiple collimators can be included
ttk.Label(collimations_frame, text="Alpha 2 (mono-sample) collimation:").grid(row=1, column=0, sticky="w")
alpha_2_frame = ttk.Frame(collimations_frame)
alpha_2_frame.grid(row=1, column=1, pady=5, sticky="w")
checkbutton_30 = ttk.Checkbutton(alpha_2_frame, text="30'", variable=alpha_2_30_var, onvalue=True, offvalue=False)
checkbutton_30.grid(row=0, column=0, sticky="w")
checkbutton_40 = ttk.Checkbutton(alpha_2_frame, text="40'", variable=alpha_2_40_var, onvalue=True, offvalue=False)
checkbutton_40.grid(row=0, column=1, sticky="w")
checkbutton_60 = ttk.Checkbutton(alpha_2_frame, text="60'", variable=alpha_2_60_var, onvalue=True, offvalue=False)
checkbutton_60.grid(row=0, column=2, sticky="w")
# Use invisible Label widgets to enforce minimum width
ttk.Label(collimations_frame, text="").grid(row=1, column=2, sticky="w")
ttk.Label(collimations_frame, text="").grid(row=1, column=3, sticky="w")
ttk.Label(collimations_frame, text="Alpha 3 (sample-analyzer) collimation:").grid(row=2, column=0, sticky="w")
ttk.Combobox(collimations_frame, textvariable=alpha_3_var, values=[0, 10, 20, 30, 45, 60]).grid(row=2, column=1, pady=5)
ttk.Label(collimations_frame, text="'").grid(row=2, column=2, sticky="w", padx=(5, 0))
ttk.Label(collimations_frame, text="Alpha 4 (analyer-detector) collimation:").grid(row=3, column=0, sticky="w")
ttk.Combobox(collimations_frame, textvariable=alpha_4_var, values=[0, 10, 20, 30, 45, 60]).grid(row=3, column=1, pady=5)
ttk.Label(collimations_frame, text="'").grid(row=3, column=2, sticky="w", padx=(5, 0))


## Parameter inputs section
# Create a frame for the parameter inputs
parameters_frame = ttk.Frame(root, padding="10")
parameters_frame.grid(row=0, column=1, sticky="nsew")

ttk.Label(parameters_frame, text="Number of neutrons:").grid(row=0, column=0, sticky="w")
ttk.Entry(parameters_frame, textvariable=number_neutrons_var).grid(row=0, column=1, pady=5)
ttk.Label(parameters_frame, text="n").grid(row=0, column=2, sticky="w")

ttk.Label(parameters_frame, text="Ki or Kf fixed:").grid(row=1, column=0, sticky="w")
K_fixed_entry = ttk.Combobox(parameters_frame, textvariable=K_fixed_var, values=["Ki Fixed", "Kf Fixed"])
K_fixed_entry.grid(row=1, column=1, pady=5)
bind_update_events(K_fixed_entry, GUIcalc.update_all_variables, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

ttk.Label(parameters_frame, text="fixed E:").grid(row=5, column=0, sticky="w")
fixed_E_entry = ttk.Entry(parameters_frame, textvariable=fixed_E_var)
fixed_E_entry.grid(row=5, column=1, pady=5)
ttk.Label(parameters_frame, text="meV").grid(row=5, column=2, sticky="w")
bind_update_events(fixed_E_entry, GUIcalc.update_all_variables, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)

# qx, qy, qz parameters section
ttk.Label(parameters_frame, text="qx:").grid(row=6, column=0, sticky="w")
qx_entry = ttk.Entry(parameters_frame, textvariable=qx_var, width=6)
qx_entry.grid(row=6, column=1, pady=5)
ttk.Label(parameters_frame, text="1/Å").grid(row=6, column=2, sticky="w")

ttk.Label(parameters_frame, text="qy:").grid(row=7, column=0, sticky="w")
qy_entry = ttk.Entry(parameters_frame, textvariable=qy_var, width=6)
qy_entry.grid(row=7, column=1, pady=5)
ttk.Label(parameters_frame, text="1/Å").grid(row=7, column=2, sticky="w")

ttk.Label(parameters_frame, text="qz:").grid(row=8, column=0, sticky="w")
qz_entry = ttk.Entry(parameters_frame, textvariable=qz_var, width=6)
qz_entry.grid(row=8, column=1, pady=5)
ttk.Label(parameters_frame, text="1/Å").grid(row=8, column=2, sticky="w")

bind_update_events(qx_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
bind_update_events(qy_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
bind_update_events(qz_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
bind_update_events(qx_entry, GUIcalc.update_angles_from_Q, mtt_var, stt_var, psi_var, 0, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)
bind_update_events(qy_entry, GUIcalc.update_angles_from_Q, mtt_var, stt_var, psi_var, 0, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)
bind_update_events(qz_entry, GUIcalc.update_angles_from_Q, mtt_var, stt_var, psi_var, 0, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)

ttk.Label(parameters_frame, text="deltaE:").grid(row=9, column=0, sticky="w")
deltaE_entry = ttk.Entry(parameters_frame, textvariable=deltaE_var)
deltaE_entry.grid(row=9, column=1, pady=5)
ttk.Label(parameters_frame, text="meV").grid(row=9, column=2, sticky="w")
bind_update_events(deltaE_entry, GUIcalc.update_all_variables, fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info)
bind_update_events(deltaE_entry, GUIcalc.update_angles_from_Q, mtt_var, stt_var, psi_var, 0, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var)

# Scan command section
scan_command_frame = ttk.Frame(parameters_frame, padding="10")
scan_command_frame.grid(row=10, column=0, sticky="nsew")

ttk.Label(scan_command_frame, text="Scan Command:").grid(row=0, column=0, sticky="w")
ttk.Entry(scan_command_frame, textvariable=scan_command_var1).grid(row=0, column=1, pady=5)
ttk.Entry(scan_command_frame, textvariable=scan_command_var2).grid(row=0, column=2, pady=5)

# Create a checkbox for diagnostic vs. non-diagnostic mode
ttk.Label(parameters_frame, text="Diagnostic mode:").grid(row=11, column=0, sticky="w")
config_diagnostics_button = ttk.Button(parameters_frame, text="Configuration", command=lambda: configure_diagnostics(PUMA))
config_diagnostics_button.grid(row=11, column=1, padx=5, pady=5)
checkbutton_diagnostic = ttk.Checkbutton(parameters_frame, text="", variable=diagnostic_mode_var, onvalue=True, offvalue=False)
checkbutton_diagnostic.grid(row=11, column=2, sticky="w")

sample_frame = ttk.Frame(parameters_frame)
sample_frame.grid(row=13, column=0, pady=10)

# Add the "Sample frame mode" checkbox
sample_frame_mode_var = tk.BooleanVar()
sample_frame_mode_checkbox = ttk.Checkbutton(sample_frame, text="Sample frame mode", variable=sample_frame_mode_var)
sample_frame_mode_checkbox.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))

# Lattice parameters section
ttk.Label(sample_frame, text="Lattice parameters:").grid(row=1, column=0, columnspan=6, sticky="w")

ttk.Label(sample_frame, text="a:").grid(row=2, column=0, sticky="w")
lattice_a_entry = ttk.Entry(sample_frame, textvariable=lattice_a_var, width=6)
lattice_a_entry.grid(row=2, column=1, pady=5)
ttk.Label(sample_frame, text="b:").grid(row=2, column=2, sticky="w")
lattice_b_entry = ttk.Entry(sample_frame, textvariable=lattice_b_var, width=6)
lattice_b_entry.grid(row=2, column=3, pady=5)
ttk.Label(sample_frame, text="c:").grid(row=2, column=4, sticky="w")
lattice_c_entry = ttk.Entry(sample_frame, textvariable=lattice_c_var, width=6)
lattice_c_entry.grid(row=2, column=5, pady=5)
ttk.Label(sample_frame, text="(Å)").grid(row=2, column=6, sticky="w")

ttk.Label(sample_frame, text="α:").grid(row=3, column=0, sticky="w")
lattice_alpha_entry = ttk.Entry(sample_frame, textvariable=lattice_alpha_var, width=6)
lattice_alpha_entry.grid(row=3, column=1, pady=5)
ttk.Label(sample_frame, text="β:").grid(row=3, column=2, sticky="w")
lattice_beta_entry = ttk.Entry(sample_frame, textvariable=lattice_beta_var, width=6)
lattice_beta_entry.grid(row=3, column=3, pady=5)
ttk.Label(sample_frame, text="γ:").grid(row=3, column=4, sticky="w")
lattice_gamma_entry = ttk.Entry(sample_frame, textvariable=lattice_gamma_var, width=6)
lattice_gamma_entry.grid(row=3, column=5, pady=5)
ttk.Label(sample_frame, text="(deg)").grid(row=3, column=6, sticky="w")

if sample_frame_mode_var:
    bind_update_events(lattice_a_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_b_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_c_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_alpha_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_beta_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_gamma_entry, GUIcalc.update_HKL_from_Q, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
else:
    bind_update_events(lattice_a_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_b_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_c_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_alpha_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_beta_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
    bind_update_events(lattice_gamma_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)


# H, K, L parameters section
ttk.Label(sample_frame, text="Reciprocal space:").grid(row=4, column=0, columnspan=6, sticky="w")

ttk.Label(sample_frame, text="H:").grid(row=5, column=0, sticky="w")
lattice_H_entry = ttk.Entry(sample_frame, textvariable=lattice_H_var, width=6)
lattice_H_entry.grid(row=5, column=1, pady=5)

ttk.Label(sample_frame, text="K:").grid(row=5, column=2, sticky="w")
lattice_K_entry = ttk.Entry(sample_frame, textvariable=lattice_K_var, width=6)
lattice_K_entry.grid(row=5, column=3, pady=5)

ttk.Label(sample_frame, text="L:").grid(row=5, column=4, sticky="w")
lattice_L_entry = ttk.Entry(sample_frame, textvariable=lattice_L_var, width=6)
lattice_L_entry.grid(row=5, column=5, pady=5)

bind_update_events(lattice_H_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
bind_update_events(lattice_K_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)
bind_update_events(lattice_L_entry, GUIcalc.update_Q_from_HKL, qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var)

# Create a window for sample configuration
config_sample_button = ttk.Button(sample_frame, text="Sample Configuration", command=configure_sample)
config_sample_button.grid(row=6, column=1, padx=5, pady=5)


# Add the callback to update the state of H, K, L entries
def update_hkl_entries():
    state = "normal" if sample_frame_mode_var.get() else "disabled"
    lattice_H_entry.config(state=state)
    lattice_K_entry.config(state=state)
    lattice_L_entry.config(state=state)

# Update function for qx, qy, qz entries
def update_q_entries():
    state = "disabled" if sample_frame_mode_var.get() else "normal"
    qx_entry.config(state=state)
    qy_entry.config(state=state)
    qz_entry.config(state=state)

# Attach the same checkbox's callback to update the q entries
def update_all():
    update_hkl_entries()  # Update H, K, L based on checkbox state
    update_q_entries()    # Update qx, qy, qz based on checkbox state

# Add the "Sample frame mode" checkbox
sample_frame_mode_var = tk.BooleanVar()
sample_frame_mode_checkbox = ttk.Checkbutton(
    sample_frame,
    text="Sample frame mode",
    variable=sample_frame_mode_var,
    command=update_all  # Attach the callback
)
sample_frame_mode_checkbox.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))

# Set initial state for H, K, L entries
update_hkl_entries()


## Command buttons section
# Create a frame for the buttons
buttons_frame = ttk.Frame(parameters_frame)
buttons_frame.grid(row=12, column=0, pady=10)

# Create a button to run the simulation
run_button = ttk.Button(buttons_frame, text="Run Simulation", command=run_simulation_thread)
run_button.grid(row=0, column=0, padx=5)

# Create a button to stop the simulation
stop_button = ttk.Button(buttons_frame, text="Stop Simulation", command=stop_simulation)
stop_button.grid(row=0, column=1, padx=5)

# Create a button to quit the application
quit_button = ttk.Button(buttons_frame, text="Quit", command=quit_application)
quit_button.grid(row=1, column=0, padx=5)

# Add a button to save parameters
save_button = ttk.Button(buttons_frame, text="Save Parameters", command=save_parameters)
save_button.grid(row=2, column=0, padx=5, pady=5)
load_button = ttk.Button(buttons_frame, text="Load Parameters", command=load_parameters)
load_button.grid(row=2, column=1, padx=5, pady=5)
defaults_button = ttk.Button(buttons_frame, text="Load Defaults", command=set_default_parameters)
defaults_button.grid(row=2, column=2, padx=5, pady=5)


# Make entries for total/max counts
ttk.Label(buttons_frame, text="max counts:").grid(row=3, column=0, sticky="ew")
max_counts_var = tk.StringVar()
max_counts_entry = ttk.Label(buttons_frame, text=0)
max_counts_entry.grid(row=3, column=1, sticky="ew")
ttk.Label(buttons_frame, text="total counts:").grid(row=3, column=2, sticky="ew")
total_counts_var = tk.StringVar()
total_counts_entry = ttk.Label(buttons_frame, text=0)
total_counts_entry.grid(row=3, column=3, sticky="ew")


# Create a button to open the validation GUI and place it in the frame
open_button = ttk.Button(buttons_frame, text="Open validation GUI", command=lambda: open_validation_window(
    K_fixed_var.get(), fixed_E_var.get(),
    qx_var.get(), qy_var.get(), qz_var.get(), deltaE_var.get(),
    monocris_var.get(), anacris_var.get()
))
open_button.grid(row=1, column=1, padx=5)

# Create a progress bar with frame
progress_frame = ttk.Frame(root)
progress_frame.grid(row=4, column=0, pady=10)
# Create a progress bar
progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=200, mode='determinate')
progress_bar.grid(row=2, column=0, padx=10, pady=5)
# Create a label to display progress text
progress_label = ttk.Label(progress_frame, text="0% (0/0)", font=("Arial", 10), background='')
progress_label.grid(row=2, column=1, padx=5)
# Add a label to display the estimated remaining time
remaining_time_label = tk.Label(progress_frame, text="Remaining Time: ")
remaining_time_label.grid(row=2, column=2, padx=5)

## Message frame
interface_frame = ttk.Frame(root, padding="10")
interface_frame.grid(row=0, column=2, sticky="nsew")
## Message center GUI
# Create a frame for the message center
message_center_frame = ttk.Frame(interface_frame, padding="10")
message_center_frame.grid(row=0, column=0, sticky="nsew")
message_center_text = tk.Text(message_center_frame, wrap=tk.WORD)
message_center_text.pack(side="left", expand=True, fill=tk.BOTH)
scrollbar = ttk.Scrollbar(message_center_frame, orient="vertical", command=message_center_text.yview)
scrollbar.pack(side="right", fill="y")
message_center_text.config(yscrollcommand=scrollbar.set)

## Saving/loading center
# Create a frame for the saving/loading section
folders_frame = ttk.Frame(interface_frame)
folders_frame.grid(row=1, column=0, pady=10)
# Make a frame for the buttons first
folder_save_buttons_frame = ttk.Frame(folders_frame)
folder_save_buttons_frame.grid(row=0, column=0, pady=10)
# Label for the folder path
save_folder_path = ttk.Label(folder_save_buttons_frame, text="Target output folder:")
save_folder_path.grid(row=0, column=0, sticky="w")
# Button to browse for the folder
save_browse_button = ttk.Button(folder_save_buttons_frame, text="Browse", command=lambda: open_folder_dialog(save_folder_label_entry))
save_browse_button.grid(row=0, column=0, padx=(120, 0), pady=5, sticky="w")
# Entry for displaying the selected folder path
save_folder_label_var = tk.StringVar()
save_folder_label_entry = ttk.Entry(folder_save_buttons_frame, textvariable=save_folder_label_var, width=110)
folder_label_suggestion = "initial_testing"
output_directory = os.path.join(os.getcwd(), "output")
if not os.path.exists(output_directory):
    os.makedirs(output_directory)
folder_label_suggestion = os.path.join(output_directory, folder_label_suggestion)
save_folder_label_entry.insert(1, folder_label_suggestion) 
save_folder_label_entry.grid(row=1, column=0, pady=5, columnspan=2)
# Add the actual output folder
ttk.Label(folders_frame, text="Actual output folder:").grid(row=2, column=0, sticky="w")
folder_label_actual_var = tk.StringVar()
folder_label_actual_entry = ttk.Label(folders_frame, textvariable=folder_label_actual_var, width=110, relief="sunken")
folder_label_actual_entry.grid(row=3, column=0, pady=5)
# Make a frame for the loading buttons
folder_load_buttons_frame = ttk.Frame(folders_frame)
folder_load_buttons_frame.grid(row=4, column=0, pady=10)
# Label for the folder path
load_folder_path = ttk.Label(folder_load_buttons_frame, text="Folder to load data:")
load_folder_path.grid(row=0, column=0, sticky="w")
# Button to browse for the folder to load
load_browse_button = ttk.Button(folder_load_buttons_frame, text="Browse", command=lambda: open_folder_dialog(load_folder_label_entry))
load_browse_button.grid(row=0, column=0, padx=(120, 0), pady=5, sticky="w")
# Button to load the data for display
load_data_button = ttk.Button(folder_load_buttons_frame, text="Load", command=lambda: display_existing_data(load_folder_label_entry))
load_data_button.grid(row=0, column=0, padx=(210, 0), pady=5, sticky="w")
# Entry for displaying the selected folder path
load_folder_label_var = tk.StringVar()
load_folder_label_entry = ttk.Entry(folder_load_buttons_frame, textvariable=load_folder_label_var, width=110)
folder_label_suggestion = "initial_testing"
output_directory = os.path.join(os.getcwd(), "output")
if not os.path.exists(output_directory):
    os.makedirs(output_directory)
folder_label_suggestion = os.path.join(output_directory, folder_label_suggestion)
load_folder_label_entry.insert(1, folder_label_suggestion) 
load_folder_label_entry.grid(row=1, column=0, pady=5, columnspan=2)

# Initialize printing (letting user know everything is running)
print_to_message_center("GUI initialized.", target='GUI')
print_to_message_center("Console messages initialized.", target='console')

# Start the GUI event loop
root.mainloop()