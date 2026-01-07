import mcstasscript as ms
import os
import pathlib
import re
import numpy as np
import matplotlib.pyplot as plt
import math
import tkinter as tk
from tkinter import ttk

def create_empty_folder(folder_path):
    try:
        os.makedirs(folder_path, exist_ok=True)
        print(f"Folder '{folder_path}' created successfully.")
    except Exception as e:
        print(f"Error creating folder '{folder_path}': {e}")

def letter_encode_number(number):
    # Convert negative sign to 'm' and decimal point to 'p'
    encoded_str = str(number).replace('-', 'm').replace('.', 'p')
    return encoded_str

def letter_decode_string(encoded_str):
    # Convert 'm' back to negative sign and 'p' back to decimal point
    decoded_str = encoded_str.replace('m', '-').replace('p', '.')
    # Convert the string back to a float
    decoded_number = float(decoded_str)
    return decoded_number

def extract_variable_values(folder_name):
    # Define the pattern to match variable values
    pattern = (r"qx_([\dmp]+)_qy_([\dmp]+)_qz_([\dmp]+)_dE_([\dmp]+)"
               r"(?:_rhm_([\dmp]+)_rvm_([\dmp]+)_rha_([\dmp]+)_rva_([\dmp]+))?"
               r"(?:_H_([\dmp]+)_K_([\dmp]+)_L_([\dmp]+))?")
    
    # Use regular expression to find matches
    match = re.match(pattern, folder_name)
    
    # Extract variable values if there's a match
    if match:
        qx = letter_decode_string(match.group(1))
        qy = letter_decode_string(match.group(2))
        qz = letter_decode_string(match.group(3))
        deltaE = letter_decode_string(match.group(4))
        
        # Check if optional variables are present
        rhm = letter_decode_string(match.group(5)) if match.group(5) else None
        rvm = letter_decode_string(match.group(6)) if match.group(6) else None
        rha = letter_decode_string(match.group(7)) if match.group(7) else None
        rva = letter_decode_string(match.group(8)) if match.group(8) else None

        # Check if HKL variables are present
        H = letter_decode_string(match.group(1)) if match.group(1) else None
        K = letter_decode_string(match.group(2)) if match.group(2) else None
        L = letter_decode_string(match.group(3)) if match.group(3) else None
        
        # Return all extracted values as a tuple
        return qx, qy, qz, deltaE, rhm, rvm, rha, rva, H, K, L
    else:
        return None
      
def parse_scan_steps(input_string):
    # Split the input string into words
    words = input_string.split()

    # Check if the input has the correct format
    #if len(words) != 4 or words[0] != 'Variable':
    #    print("Invalid input format. Please use 'Variable XXX YYY ZZZ'")
    #    return None

    # Extract variable name and numerical values
    variable_name = words[0]
    start_value = float(words[1])
    end_value = float(words[2])
    step_size = float(words[3])

    # Create an array using numpy
    array_values = np.arange(start_value, end_value + step_size, step_size)
    array_values = np.round(array_values, 3)

    return variable_name, array_values

# This should take a folder path and create a new folder that increments
def incremented_path_writing(base_path, folder_name):
    # Create the base folder if it doesn't exist
    pathlib.Path(base_path).mkdir(parents=True, exist_ok=True)

    # Check if the initial folder exists
    initial_folder_path = os.path.join(base_path, folder_name)
    if not os.path.exists(initial_folder_path):
        # Create the initial folder
        pathlib.Path(initial_folder_path).mkdir(parents=True, exist_ok=True)
        return initial_folder_path

    # Append an underscore to the folder name for checking existing folders
    folder_name_with_underscore = folder_name + '_'

    # Find the latest existing folder with an incrementing counter
    folder_pattern = re.compile(rf"{re.escape(folder_name_with_underscore)}(\d+)")
    folder_numbers = [int(folder_pattern.match(name).group(1)) for name in os.listdir(base_path) if folder_pattern.match(name)]
    
    if folder_numbers:
        latest_folder_number = max(folder_numbers)
    else:
        latest_folder_number = 0

    # Determine the next folder name
    next_folder_name = folder_name_with_underscore + str(latest_folder_number + 1)

    # Check if the folder already exists, if so, increment the number until finding a non-existing folder
    while os.path.exists(os.path.join(base_path, next_folder_name)):
        latest_folder_number += 1
        next_folder_name = folder_name_with_underscore + str(latest_folder_number + 1)

    # Create the full folder path
    folder_path = os.path.join(base_path, next_folder_name)

    # Create the folder
    pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)

    return folder_path