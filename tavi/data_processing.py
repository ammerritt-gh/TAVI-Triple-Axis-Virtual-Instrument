"""Data processing functions for TAVI.

This module contains functions for reading detector files, managing scan parameters,
and writing scan data to files.
"""
import os
import re
import json
import numpy as np


def read_1Ddetector_file(scan_folder):
    """Read detector data from a McStas 1D detector file.
    
    Args:
        scan_folder: Path to folder containing detector.dat file
        
    Returns:
        tuple: (intensity, intensity_error, counts) from the detector
    """
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
        
                # If the target entry is found, extract the values from the following line
                if target_index is not None and target_index + 1 < len(lines):
                    following_line = lines[target_index + 1]
                    intensity = float(following_line.split()[0])
                    intensity_error = float(following_line.split()[1])
                    counts = float(following_line.split()[2])
                else:
                    print("Unable to find the detector data, check the header lines")
                    return None, None, None
        else:
            print(f"\nFile {file_path} not found.")
            return None, None, None
    else:
        print(f"\nFolder {scan_folder} invalid.")
        return None, None, None
        
    return intensity, intensity_error, counts


def write_parameters_to_file(target_folder, parameters):
    """Write scan parameters to a file.
    
    Args:
        target_folder: Directory where parameter file will be written
        parameters: Dict or object containing parameters to save
    """
    file_path = os.path.join(target_folder, "scan_parameters.txt")
    os.makedirs(target_folder, exist_ok=True)

    # Determine all items before opening/truncating the file so that any
    # exception (e.g. from getattr in the fallback) does not leave a
    # partially written parameters file.
    if isinstance(parameters, dict):
        items = list(parameters.items())
    elif hasattr(parameters, "__dict__"):
        items = list(parameters.__dict__.items())
    else:
        # Fallback: try to iterate public attributes eagerly
        items = []
        for k in dir(parameters):
            if k.startswith('_'):
                continue
            try:
                value = getattr(parameters, k)
            except AttributeError:
                # Skip attributes that cannot be accessed
                continue
            items.append((k, value))

    with open(file_path, 'w') as file:
        for key, value in items:
            file.write(f"{key}: {value}\n")


def read_parameters_from_file(target_folder):
    """Read scan parameters from a file.
    
    Args:
        target_folder: Directory containing the parameter file
        
    Returns:
        dict: Parameters read from file
    """
    file_path = os.path.join(target_folder, "scan_parameters.txt")
    parameters = {}
    
    try:
        with open(file_path, 'r') as file:
            for line in file:
                key_value = line.strip().split(': ')
                if len(key_value) == 2:
                    key, value = key_value
                else:
                    key = key_value[0]
                    value = None

                if value is not None:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                parameters[key] = value
    except FileNotFoundError:
        print(f"Warning: Parameter file not found at {file_path}")
        
    return parameters


def simple_plot_scan_commands(scan_point, target_folder):
    """Simple wrapper to determine and execute appropriate plotting function.
    
    Args:
        scan_point: Scan point identifier
        target_folder: Folder containing scan data
    """
    from tavi.utilities import parse_scan_steps
    
    scan_parameters = read_parameters_from_file(target_folder)
    scan_command1 = scan_parameters.get('scan_command1')
    scan_command2 = scan_parameters.get('scan_command2')
        
    if not(scan_command1) and not(scan_command2):
        intensity, intensity_error, counts = read_1Ddetector_file(target_folder)
        if counts is not None:
            print(f"Final counts at detector: {counts}")
      
    # Note: The actual plotting functions plot_1D_scan and plot_2D_scan
    # are not included here as they require matplotlib and are used
    # for visualization only. They can be added if needed.


def display_existing_data(data_folder):
    """Display existing scan data from a folder.
    
    Args:
        data_folder: tkinter variable containing folder path
        
    Note: This function expects a tkinter variable. For non-GUI usage,
    pass the path directly to plot functions.
    """
    data_folder_path = data_folder.get() if hasattr(data_folder, 'get') else data_folder
    scan_parameters = read_parameters_from_file(data_folder_path)
    
    # Note: Actual plotting would require plot_1D_scan and plot_2D_scan functions
    print(f"Would display data from: {data_folder_path}")
    print(f"Scan parameters: {scan_parameters}")


def write_1D_scan(x_values, data_values, data_folder, file_name, x_label: str = 'x', y_label: str = 'counts'):
    """Write 1D scan data to a text file with a header describing columns.

    Args:
        x_values: Array of x-axis values
        data_values: Array of corresponding data points
        data_folder: Directory to write file
        file_name: Name of output file
        x_label: Human-readable label for the x-axis / scan parameter
        y_label: Human-readable label for the measurement (defaults to 'counts')
    """
    os.makedirs(data_folder, exist_ok=True)
    file_path = os.path.join(data_folder, file_name)
    with open(file_path, 'w') as f:
        # Header: column names
        f.write(f"# {x_label} {y_label}\n")
        # Write X-axis values and data points in two columns
        for x, data in zip(x_values, data_values):
            f.write(f"{x} {data}\n")


def write_2D_scan(x_values, y_values, nan_grid, data_folder, file_name, x_label: str = 'x', y_label: str = 'y'):
    """Write 2D scan data to a text file with a header describing the scanned parameters.

    The format preserves the previous layout where the first row contains x-axis
    values (preceded by a spacer) and each following row starts with the y-axis
    value followed by the row data. Header lines beginning with '#' are added
    at the top describing the column semantics.

    Args:
        x_values: Array of x-axis values
        y_values: Array of y-axis values
        nan_grid: 2D grid of data values
        data_folder: Directory to write file
        file_name: Name of output file
        x_label: Label for x-axis / scan parameter
        y_label: Label for y-axis / scan parameter
    """
    os.makedirs(data_folder, exist_ok=True)
    file_path = os.path.join(data_folder, file_name)
    with open(file_path, 'w') as f:
        # Header: describe scan axes and measurement
        f.write(f"# {x_label} vs {y_label}  (values arranged as rows: {y_label} then counts...)\n")
        # Write the first spacer for the 0,0 position
        f.write('00 ')
        # Write X-axis values in the first row
        f.write(' '.join(map(str, x_values)) + '\n')
        
        # Write Y-axis values in the first column followed by data points
        for i, y_value in enumerate(y_values):
            row = [str(y_value)] + [str(value) for value in nan_grid[i]]
            f.write(' '.join(row) + '\n')
