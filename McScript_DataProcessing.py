import mcstasscript as ms
import os
import pathlib
import re
import numpy as np
import matplotlib.pyplot as plt
import math
import tkinter as tk
from tkinter import ttk
from McScript_Functions import parse_scan_steps, extract_variable_values

def read_2Ddetector_file(data_folder): # TODO: Check this 2D-detector reading function
    for folder_name in os.listdir(data_folder):
            if folder_name == "figures":
                continue  # Skip the "figures" folder
        
            full_folder_path = os.path.join(data_folder, folder_name)
            if os.path.isdir(full_folder_path):
                # Construct the path to the file PSD.dat within the current folder
                file_path = os.path.join(full_folder_path, "detector.dat")
        
                # Check if the file exists before attempting to load it
                if os.path.exists(file_path):
                    # Load the file
                    with open(file_path, 'r') as file:
                        content = file.read()
                        # Extract the portion between "# Data [PSD/PSD.dat] I:" and "# Errors [PSD/PSD.dat] I_err:" which is the intensity heatmap
                        match = re.search(r'# Data \[PSD/PSD\.dat\] I:(.*?)# Errors \[PSD/PSD\.dat\] I_err:', content, re.DOTALL)
                        if match:
                            data_block = match.group(1).strip()
                        else:
                            raise ValueError("Data block not found in the file.")
        
                        # Convert the extracted data block to a numpy array
                        data_array = np.fromstring(data_block, sep=' ').reshape((100, 100)) # TODO: the 100,100 should take size of data array

    return(data_array)

# takes a particular folder where the detector file is located and returns the intensity, error and raw counts at the detector
def read_1Ddetector_file(scan_folder):

    if os.path.isdir(scan_folder):
        # Construct the path to the file detector.dat within the current folder
        file_path = os.path.join(scan_folder, "detector.dat")
        
        # Check if the file exists before attempting to load it
        if os.path.exists(file_path):
            # Load the file
            with open(file_path, 'r') as file:
                content = file.read()
                         
                # Split the content into lines
                lines = content.split('\n')
        
                # Find the index of the target entry
                target_index = None
                for i, line in enumerate(lines):
                    if line.startswith('# variables: I I_err N'):
                        target_index = i
                        break
        
                # If the target entry is found, extract the third number from the following line
                if target_index is not None and target_index + 1 < len(lines):
                    following_line = lines[target_index + 1]
                    intensity = float(following_line.split()[0])
                    intensity_error = float(following_line.split()[1])
                    counts = float(following_line.split()[2])

                else:
                    print("Unable to find the detector data, check the header lines")
        else:
            print(f"\nFile {file_path} not found.")
    else:
        print(f"\nFolder {scan_folder} invalid.")
    return(intensity, intensity_error, counts)

def read_all_scans(data_folder):
    counts_array = []
    for folder_name in os.listdir(data_folder):
            if folder_name == "figures":
                continue  # Skip the "figures" folder
        
            full_folder_path = os.path.join(data_folder, folder_name)
            if os.path.isdir(full_folder_path):
                # Construct the path to the file PSD.dat within the current folder
                file_path = os.path.join(full_folder_path, "detector.dat")
        
                # Check if the file exists before attempting to load it
                if os.path.exists(file_path):
                    # Load the file
                    with open(file_path, 'r') as file:
                        content = file.read()
                         
                        # Split the content into lines
                        lines = content.split('\n')
        
                        # Find the index of the target entry
                        target_index = None
                        for i, line in enumerate(lines):
                            if line.startswith('# variables: I I_err N'):
                                target_index = i
                                break
        
                        # If the target entry is found, extract the third number from the following line
                        if target_index is not None and target_index + 1 < len(lines):
                            following_line = lines[target_index + 1]
                            counts = following_line.split()[-1]
                            Ierror = following_line.split()[-2]
                        else:
                            print("Unable to find the detector data, check the header lines")
                else:
                    print(f"\nFile {file_path} not found.")

    numbers_array = np.array([int(num) for num in counts_array])
    print(f"Final counts at detector: {numbers_array}")
    return()

def write_parameters_to_file(target_folder, parameters):
    file_path = os.path.join(target_folder, "scan_parameters.txt")
    with open(file_path, 'w') as file:
        for key in parameters.__dict__.keys():
            value = getattr(parameters, key)
            file.write(f"{key}: {value}\n")

def read_parameters_from_file(target_folder):
    file_path = os.path.join(target_folder, "scan_parameters.txt")
    parameters = {}
    with open(file_path, 'r') as file: ##TODO: add an exception if there is no scan_parameters file
        for line in file:
            key_value = line.strip().split(': ')
            if len(key_value) == 2:
                key, value = key_value
            else:
                key = key_value[0]
                value = None
            if value is not None and value.replace('.', '', 1).isdigit():
                value = float(value)
            parameters[key] = value
    return parameters

def simple_plot_scan_commands(scan_point, target_folder):
    
    scan_parameters = read_parameters_from_file(target_folder)
    scan_command1 = scan_parameters.get('scan_command1')
    scan_command2 = scan_parameters.get('scan_command2')
        
    if not(scan_command1) and not(scan_command2):
        intensity, intensity_error, counts = read_1Ddetector_file(target_folder)
        print(f"Final counts at detector: {counts}")
      
    if scan_command1 and not(scan_command2):
        plot_1D_scan(target_folder, scan_command1)
        
    if scan_command2 and scan_command1:
        plot_2D_scan(target_folder, scan_command1, scan_command2)
    
    return
    
def plot_1D_scan(data_folder, scan_command1):
    variable_name, array_values = parse_scan_steps(scan_command1)
    scan_parameters = []
    counts_array = []

    for folder_name in os.listdir(data_folder):
        full_path = os.path.join(data_folder, folder_name)
        if os.path.isdir(full_path):
            extracted_values = extract_variable_values(folder_name)
            print(extracted_values)
            if extracted_values:
                # Find the index of the variable being scanned
                variable_index = {
                    'qx': 0,
                    'qy': 1,
                    'qz': 2,
                    'deltaE': 3,
                    'rhm': 4,
                    'rvm': 5,
                    'rha': 6,
                    'rva': 7,
                    'H': 8,
                    'K': 9,
                    'L': 10
                }.get(variable_name)  # Add HKL variables

                if variable_index is not None:
                    scan_parameters.append(extracted_values[variable_index])
                else:
                    print(f"Warning: Variable {variable_name} not found in extracted values.")
                    continue  # Skip to the next folder

                intensity, intensity_error, counts = read_1Ddetector_file(full_path)
                counts_array.append(counts)

    scan_parameters = np.array(scan_parameters)
    print(scan_parameters)
    print(counts_array)

    combined_array = np.hstack((scan_parameters.reshape(-1, 1), np.array(counts_array).reshape(-1, 1))) # Reshape scan_parameters to be a 2D column vector
    scan_parameters = read_parameters_from_file(data_folder)
    plot_title = f"N: {np.format_float_scientific(scan_parameters.get('number_neutrons'), unique=True, precision=2)}"

    numbers_array = np.array([float(num) for num in counts_array]) # Convert counts_array to float
    print(f"Final counts at detector: {numbers_array}")

    indices_ascending = np.argsort(combined_array[:, 0]) # Sort in ascending order
    combined_array = combined_array[indices_ascending] # Use the indices to sort the array

    q_values = combined_array[:, 0].astype(float)
    numbers_array = combined_array[:, -1].astype(float)

    # Sort based on q_values
    sorted_indices = np.argsort(q_values)
    q_values = q_values[sorted_indices]
    numbers_array = numbers_array[sorted_indices]
    plt.plot(q_values, numbers_array, marker='o', linestyle='-', color='b', label='Counts')
    plt.xlabel(f'{variable_name} (1/Å)' if variable_name in ['qx', 'qy', 'qz'] else f'{variable_name} (meV)' if variable_name == 'deltaE' else f'{variable_name} (r.l.u.)' if variable_name in ['H', 'K', 'L'] else f'{variable_name}')
    print(q_values, numbers_array, data_folder)
    write_1D_scan(q_values, numbers_array, data_folder, "1D_data.txt")

    # Get plot title set up
    if variable_name != 'qx':
        plot_title += f" qx={scan_parameters.get('qx')}"
    if variable_name != 'qy':
        plot_title += f" qy={scan_parameters.get('qy')}"
    if variable_name != 'qz':
        plot_title += f" qz={scan_parameters.get('qz')}"
    if variable_name != 'deltaE':
        plot_title += f" dE={scan_parameters.get('deltaE')}"
    if variable_name != 'H':
        plot_title += f" H={scan_parameters.get('H')}"
    if variable_name != 'K':
        plot_title += f" K={scan_parameters.get('K')}"
    if variable_name != 'L':
        plot_title += f" L={scan_parameters.get('L')}"

    plt.ylabel('Counts')
    plt.title(plot_title)
    plt.legend()
    plt.show()

    return()

def plot_2D_scan(data_folder, scan_command1, scan_command2):
    # Parse scan commands
    variable_name1, array_values1 = parse_scan_steps(scan_command1)
    variable_name2, array_values2 = parse_scan_steps(scan_command2)
    
    # Initialize lists to store scan parameters and counts
    scan_parameters1 = []
    scan_parameters2 = []
    counts_array = []
    
    # Load data from files in the data folder
    for folder_name in os.listdir(data_folder):
        full_path = os.path.join(data_folder, folder_name)
        if os.path.isdir(full_path):
            extracted_values = extract_variable_values(folder_name)
            if extracted_values:
                # Find the indices of the variables being scanned
                variable_index1 = {
                    "qx": 0,
                    "qy": 1,
                    "qz": 2,
                    "deltaE": 3,
                    "rhm": 4,
                    "rvm": 5,
                    "rha": 6,
                    "rva": 7
                }.get(variable_name1)
                variable_index2 = {
                    "qx": 0,
                    "qy": 1,
                    "qz": 2,
                    "deltaE": 3,
                    "rhm": 4,
                    "rvm": 5,
                    "rha": 6,
                    "rva": 7
                }.get(variable_name2)
                
                if variable_index1 is not None and variable_index2 is not None:
                    scan_parameters1.append(extracted_values[variable_index1])
                    scan_parameters2.append(extracted_values[variable_index2])
                    intensity, intensity_error, counts = read_1Ddetector_file(full_path)
                    counts_array.append(counts)
                else:
                    print(f"Warning: Variable {variable_name1} or {variable_name2} not found in extracted values.")
                    continue  # Skip to the next folder
    
    # Convert lists to numpy arrays
    scan_parameters1 = np.array(scan_parameters1)
    scan_parameters2 = np.array(scan_parameters2)
    counts_array = np.array(counts_array)
    
    # Combine scan parameters and counts into a single array
    combined_array = np.column_stack((scan_parameters1, scan_parameters2, counts_array))
    
    # Extract axis values and counts
    axis1_values = combined_array[:, 0].astype(float)
    axis2_values = combined_array[:, 1].astype(float)
    counts_values = combined_array[:, 2].astype(float)
    
    # Read additional scan parameters for title
    scan_parameters_file = read_parameters_from_file(data_folder)
    plot_title = f"N: {np.format_float_scientific(scan_parameters_file.get('number_neutrons'), unique=True, precision=2)}"
    
    # Add unused parameters to the title dynamically
    for variable, index in {
        "qx": 0,
        "qy": 1,
        "qz": 2,
        "deltaE": 3,
        "rhm": 4,
        "rvm": 5,
        "rha": 6,
        "rva": 7
    }.items():
        if variable != variable_name1 and variable != variable_name2:
            plot_title += f" {variable}={scan_parameters_file.get(variable)}"
    
    # Create a regular grid of x and y values
    x_values = np.unique(axis1_values)
    y_values = np.unique(axis2_values)
    x_grid, y_grid = np.meshgrid(x_values, y_values)
    
    # Create a grid of NaN values
    nan_grid = np.full_like(x_grid, np.nan, dtype=float)
    
    # Fill in available data points
    for x, y, counts in zip(axis1_values, axis2_values, counts_values):
        # Find the indices of the closest grid points to the data points
        x_index = np.abs(x_values - x).argmin()
        y_index = np.abs(y_values - y).argmin()
        # Fill in the grid with counts at the corresponding grid point
        nan_grid[y_index, x_index] = counts
    
    # Plot the heatmap
    plt.imshow(nan_grid, cmap='viridis', origin='lower', extent=[x_values.min(), x_values.max(), y_values.min(), y_values.max()])
    plt.colorbar(label='Counts')
    if variable_name1 == "qx" or variable_name1 == "qy" or variable_name1 == "qz":
        x_axis_label = variable_name1 + " (1/Å)"
    elif variable_name1 == "deltaE":
        x_axis_label = variable_name1 + " (meV)"
    else:
        x_axis_label = variable_name1
    if variable_name2 == "qx" or variable_name2 == "qy" or variable_name2 == "qz":
        y_axis_label = variable_name2 + " (1/Å)"
    elif variable_name2 == "deltaE":
        y_axis_label = variable_name2 + " (meV)"
    else:
        y_axis_label = variable_name2
    plt.xlabel(x_axis_label)
    plt.ylabel(y_axis_label)
    plt.title(plot_title)
    file_name = os.path.join(data_folder, "Heatmap.png")
    plt.savefig(file_name)
    plt.show()
    
    # Write the 2D data to a file
    write_2D_scan(x_values, y_values, nan_grid, data_folder, "2D_data.txt")

def write_1D_scan(x_values, data_values, data_folder, file_name):
    with open(os.path.join(data_folder, file_name), 'w') as f:
      
        # Write X-axis values and data points in two columns
        for x, data in zip(x_values, data_values):
            f.write(f"{x} {data}\n")
    
def write_2D_scan(x_values, y_values, nan_grid, data_folder, file_name):
    with open(os.path.join(data_folder, file_name), 'w') as f:
        # Write the first spacer for the 0,0 position
        f.write('00 ')
        # Write X-axis values in the first row
        f.write(' '.join(map(str, x_values)) + '\n')
        
        # Write Y-axis values in the first column followed by data points
        for i, y_value in enumerate(y_values):
            row = [str(y_value)] + [str(value) for value in nan_grid[i]]
            f.write(' '.join(row) + '\n')
    
def display_existing_data(data_folder):
    data_folder_path = data_folder.get()
    scan_parameters = read_parameters_from_file(data_folder_path)
    if scan_parameters.get('scan_command1') and not scan_parameters.get('scan_command2'):
        plot_1D_scan(data_folder_path, scan_parameters.get('scan_command1'))
    if scan_parameters.get('scan_command1') and scan_parameters.get('scan_command2'):
        plot_2D_scan(data_folder_path, scan_parameters.get('scan_command1'), scan_parameters.get('scan_command2'))