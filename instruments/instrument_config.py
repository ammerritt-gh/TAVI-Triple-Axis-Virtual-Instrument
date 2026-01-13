"""Instrument configuration loader for TAVI.

This module provides functionality to load instrument configurations from JSON files,
allowing dynamic definition of triple-axis spectrometers without modifying code.
"""

import json
import os
from typing import Dict, Any, List, Optional


class InstrumentConfig:
    """Container for instrument configuration parameters."""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """Initialize from configuration dictionary.
        
        Args:
            config_dict: Dictionary containing instrument configuration
        """
        # Basic instrument info
        self.name = config_dict.get('name', 'Unknown Instrument')
        self.description = config_dict.get('description', '')
        
        # Arm lengths (meters)
        arm_lengths = config_dict.get('arm_lengths', {})
        self.L1 = arm_lengths.get('L1', 1.0)  # source-mono
        self.L2 = arm_lengths.get('L2', 1.0)  # mono-sample
        self.L3 = arm_lengths.get('L3', 1.0)  # sample-ana
        self.L4 = arm_lengths.get('L4', 1.0)  # ana-det
        
        # Monochromator crystals
        self.monochromator_crystals = config_dict.get('monochromator_crystals', {})
        
        # Analyzer crystals
        self.analyzer_crystals = config_dict.get('analyzer_crystals', {})
        
        # Focusing options
        focusing = config_dict.get('focusing', {})
        self.rhm_range = focusing.get('rhm_range', [0, 10])
        self.rvm_range = focusing.get('rvm_range', [0, 10])
        self.rha_range = focusing.get('rha_range', [0, 10])
        self.rva_value = focusing.get('rva_value', 0.8)
        self.rhm_min = focusing.get('rhm_min', 2.0)
        self.rvm_min = focusing.get('rvm_min', 0.5)
        self.rha_min = focusing.get('rha_min', 2.0)
        
        # Experimental modules
        modules = config_dict.get('experimental_modules', {})
        self.nmo_options = modules.get('nmo_options', ['None'])
        self.v_selector_available = modules.get('v_selector_available', False)
        
        # Collimators
        collimators = config_dict.get('collimators', {})
        self.alpha_1_options = collimators.get('alpha_1_options', [0])
        self.alpha_2_options = collimators.get('alpha_2_options', [0])
        self.alpha_3_options = collimators.get('alpha_3_options', [0])
        self.alpha_4_options = collimators.get('alpha_4_options', [0])
        
        # Slits
        slits = config_dict.get('slits', {})
        self.hbl_hgap = slits.get('hbl_hgap', 0.078)
        self.hbl_vgap = slits.get('hbl_vgap', 0.150)
        self.vbl_hgap = slits.get('vbl_hgap', 0.088)
        self.pbl_hgap = slits.get('pbl_hgap', 0.100)
        self.pbl_vgap = slits.get('pbl_vgap', 0.100)
        self.pbl_hoffset = slits.get('pbl_hoffset', 0.0)
        self.pbl_voffset = slits.get('pbl_voffset', 0.0)
        self.dbl_hgap = slits.get('dbl_hgap', 0.050)
        
        # Slit ranges (for GUI controls)
        self.hbl_hgap_range = slits.get('hbl_hgap_range', [0.01, 0.20])
        self.hbl_vgap_range = slits.get('hbl_vgap_range', [0.01, 0.30])
        self.vbl_hgap_range = slits.get('vbl_hgap_range', [0.01, 0.20])
        self.pbl_hgap_range = slits.get('pbl_hgap_range', [0.01, 0.20])
        self.pbl_vgap_range = slits.get('pbl_vgap_range', [0.01, 0.20])
        self.dbl_hgap_range = slits.get('dbl_hgap_range', [0.01, 0.10])
    
    def get_monochromator_names(self) -> List[str]:
        """Get list of available monochromator crystal names."""
        return list(self.monochromator_crystals.keys())
    
    def get_analyzer_names(self) -> List[str]:
        """Get list of available analyzer crystal names."""
        return list(self.analyzer_crystals.keys())
    
    def get_monochromator_info(self, crystal_name: str) -> Optional[Dict[str, Any]]:
        """Get monochromator crystal information.
        
        Args:
            crystal_name: Name of the crystal
            
        Returns:
            Dictionary with crystal parameters or None if not found
        """
        return self.monochromator_crystals.get(crystal_name)
    
    def get_analyzer_info(self, crystal_name: str) -> Optional[Dict[str, Any]]:
        """Get analyzer crystal information.
        
        Args:
            crystal_name: Name of the crystal
            
        Returns:
            Dictionary with crystal parameters or None if not found
        """
        return self.analyzer_crystals.get(crystal_name)


def load_instrument_config(config_file: str) -> InstrumentConfig:
    """Load instrument configuration from JSON file.
    
    Args:
        config_file: Path to JSON configuration file
        
    Returns:
        InstrumentConfig object
        
    Raises:
        FileNotFoundError: If configuration file doesn't exist
        json.JSONDecodeError: If configuration file is invalid JSON
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Instrument configuration file not found: {config_file}")
    
    with open(config_file, 'r') as f:
        config_dict = json.load(f)
    
    return InstrumentConfig(config_dict)


def get_available_instruments(instruments_dir: str = None) -> List[str]:
    """Get list of available instrument configurations.
    
    Args:
        instruments_dir: Directory containing instrument configurations.
                        If None, uses the instruments directory.
        
    Returns:
        List of instrument names (without .json extension)
    """
    if instruments_dir is None:
        # Use the instruments directory where this file is located
        instruments_dir = os.path.dirname(os.path.abspath(__file__))
    
    instruments = []
    if os.path.exists(instruments_dir):
        for filename in os.listdir(instruments_dir):
            if filename.endswith('_config.json'):
                instrument_name = filename[:-12]  # Remove '_config.json'
                instruments.append(instrument_name)
    
    return instruments
