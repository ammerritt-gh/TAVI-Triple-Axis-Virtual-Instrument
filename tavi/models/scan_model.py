"""
Scan Model - Holds the state of scan configuration.
Includes scan parameters, commands, and execution settings.
"""
from typing import Dict, Any, List, Tuple, Optional
from .base_model import BaseModel, Observable
import numpy as np


class ScanModel(BaseModel):
    """
    Model for scan configuration state.
    
    This includes:
    - Number of neutrons
    - Ki/Kf fixed mode
    - Fixed energy value
    - Scan commands (up to 2 for 2D scans)
    - Diagnostic mode flag
    """
    
    def __init__(self):
        super().__init__()
        
        # Scan parameters
        self.number_neutrons = Observable(1e8)
        self.K_fixed = Observable("Kf Fixed")  # "Ki Fixed" or "Kf Fixed"
        self.fixed_E = Observable(14.7)  # meV
        
        # Scan commands
        self.scan_command1 = Observable("")  # e.g., "qx 2 2.2 0.1"
        self.scan_command2 = Observable("")  # e.g., "deltaE 3 7 0.25"
        
        # Diagnostic mode
        self.diagnostic_mode = Observable(True)
        
        # Sample frame mode (HKL vs Q mode)
        self.sample_frame_mode = Observable(False)
        
    def parse_scan_command(self, command: str) -> Optional[Tuple[str, np.ndarray]]:
        """
        Parse a scan command string into variable name and values array.
        
        Args:
            command: Scan command string, e.g., "qx 2 2.2 0.1"
            
        Returns:
            Tuple of (variable_name, array_values) or None if invalid
        """
        if not command or not command.strip():
            return None
            
        words = command.split()
        if len(words) != 4:
            return None
        
        try:
            variable_name = words[0]
            start_value = float(words[1])
            end_value = float(words[2])
            step_size = float(words[3])
            
            array_values = np.arange(start_value, end_value + step_size, step_size)
            array_values = np.round(array_values, 3)
            
            return variable_name, array_values
        except (ValueError, IndexError):
            return None
    
    def get_scan_mode(self) -> str:
        """
        Determine the scan mode based on scan commands.
        
        Returns:
            "momentum", "rlu", or "angle"
        """
        command = self.scan_command1.get()
        if not command:
            return "momentum"
        
        if "qx" in command or "qy" in command or "qz" in command:
            return "momentum"
        elif "H" in command or "K" in command or "L" in command:
            return "rlu"
        elif "A1" in command or "A2" in command or "A3" in command or "A4" in command:
            return "angle"
        
        return "momentum"
    
    def get_scan_points(self) -> List[List[float]]:
        """
        Generate all scan points from the scan commands.
        
        Returns:
            List of scan point arrays
        """
        command1 = self.scan_command1.get()
        command2 = self.scan_command2.get()
        
        # Parse commands
        parsed1 = self.parse_scan_command(command1)
        parsed2 = self.parse_scan_command(command2)
        
        # Variable to index mapping
        variable_to_index = {
            'qx': 0, 'qy': 1, 'qz': 2, 'deltaE': 3,
            'H': 0, 'K': 1, 'L': 2,
            'A1': 0, 'A2': 1, 'A3': 2, 'A4': 3,
            'rhm': 4, 'rvm': 5, 'rha': 6, 'rva': 7
        }
        
        # Initialize scan point template
        scan_point_template = [0.0] * 8
        
        scan_points = []
        
        if not parsed1 and not parsed2:
            # Single point scan
            scan_points.append(scan_point_template[:])
        elif parsed1 and not parsed2:
            # 1D scan
            var_name1, values1 = parsed1
            for val1 in values1:
                point = scan_point_template[:]
                if var_name1 in variable_to_index:
                    point[variable_to_index[var_name1]] = val1
                scan_points.append(point)
        elif parsed1 and parsed2:
            # 2D scan
            var_name1, values1 = parsed1
            var_name2, values2 = parsed2
            for val1 in values1:
                for val2 in values2:
                    point = scan_point_template[:]
                    if var_name1 in variable_to_index:
                        point[variable_to_index[var_name1]] = val1
                    if var_name2 in variable_to_index:
                        point[variable_to_index[var_name2]] = val2
                    scan_points.append(point)
        
        return scan_points
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize scan state to dictionary."""
        return {
            "number_neutrons": self.number_neutrons.get(),
            "K_fixed": self.K_fixed.get(),
            "fixed_E": self.fixed_E.get(),
            "scan_command1": self.scan_command1.get(),
            "scan_command2": self.scan_command2.get(),
            "diagnostic_mode": self.diagnostic_mode.get(),
            "sample_frame_mode": self.sample_frame_mode.get(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load scan state from dictionary."""
        if "number_neutrons" in data:
            self.number_neutrons.set(data["number_neutrons"])
        if "K_fixed" in data:
            self.K_fixed.set(data["K_fixed"])
        if "fixed_E" in data:
            self.fixed_E.set(data["fixed_E"])
        if "scan_command1" in data:
            self.scan_command1.set(data["scan_command1"])
        if "scan_command2" in data:
            self.scan_command2.set(data["scan_command2"])
        if "diagnostic_mode" in data:
            self.diagnostic_mode.set(data["diagnostic_mode"])
        if "sample_frame_mode" in data:
            self.sample_frame_mode.set(data["sample_frame_mode"])
