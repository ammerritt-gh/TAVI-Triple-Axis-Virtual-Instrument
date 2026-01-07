"""
Sample Model - Holds the state of the sample configuration.
Includes lattice parameters, space group, and sample-specific settings.
"""
from typing import Dict, Any, Optional
from .base_model import BaseModel, Observable


class SampleModel(BaseModel):
    """
    Model for sample configuration state.
    
    This includes:
    - Lattice parameters (a, b, c, alpha, beta, gamma)
    - Space group (for future Bragg peak calculations)
    - Sample-specific settings (type, radius, height, mosaic, temperature)
    """
    
    def __init__(self):
        super().__init__()
        
        # Lattice parameters
        self.lattice_a = Observable(4.05)   # a in Angstroms
        self.lattice_b = Observable(4.05)   # b in Angstroms
        self.lattice_c = Observable(4.05)   # c in Angstroms
        self.lattice_alpha = Observable(90.0)  # alpha in degrees
        self.lattice_beta = Observable(90.0)   # beta in degrees
        self.lattice_gamma = Observable(90.0)  # gamma in degrees
        
        # Space group (for future use)
        self.space_group = Observable("")
        
        # Sample type and settings
        self.sample_type = Observable("None")  # Sample type selection
        self.sample_radius = Observable(0.5)   # Sample radius (cm)
        self.sample_height = Observable(1.0)   # Sample height (cm)
        self.sample_mosaic = Observable(0.1)   # Mosaic spread
        self.sample_temperature = Observable(300.0)  # Temperature (K)
        
        # Available sample types with their default settings
        self.available_samples = {
            "Aluminum rod Bragg": {"radius": 0.5, "yheight": 1.0, "mosaic": 0.1},
            "Aluminum rod acoustic phonon": {"radius": 0.5, "yheight": 1.0, "temperature": 300},
            "None": {}
        }
    
    def set_sample_type(self, sample_type: str):
        """Set the sample type and apply default settings."""
        if sample_type in self.available_samples:
            self.sample_type.set(sample_type)
            defaults = self.available_samples[sample_type]
            if "radius" in defaults:
                self.sample_radius.set(defaults["radius"])
            if "yheight" in defaults:
                self.sample_height.set(defaults["yheight"])
            if "mosaic" in defaults:
                self.sample_mosaic.set(defaults["mosaic"])
            if "temperature" in defaults:
                self.sample_temperature.set(defaults["temperature"])
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize sample state to dictionary."""
        return {
            "lattice_a": self.lattice_a.get(),
            "lattice_b": self.lattice_b.get(),
            "lattice_c": self.lattice_c.get(),
            "lattice_alpha": self.lattice_alpha.get(),
            "lattice_beta": self.lattice_beta.get(),
            "lattice_gamma": self.lattice_gamma.get(),
            "space_group": self.space_group.get(),
            "sample_type": self.sample_type.get(),
            "sample_radius": self.sample_radius.get(),
            "sample_height": self.sample_height.get(),
            "sample_mosaic": self.sample_mosaic.get(),
            "sample_temperature": self.sample_temperature.get(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load sample state from dictionary."""
        if "lattice_a" in data:
            self.lattice_a.set(data["lattice_a"])
        if "lattice_b" in data:
            self.lattice_b.set(data["lattice_b"])
        if "lattice_c" in data:
            self.lattice_c.set(data["lattice_c"])
        if "lattice_alpha" in data:
            self.lattice_alpha.set(data["lattice_alpha"])
        if "lattice_beta" in data:
            self.lattice_beta.set(data["lattice_beta"])
        if "lattice_gamma" in data:
            self.lattice_gamma.set(data["lattice_gamma"])
        if "space_group" in data:
            self.space_group.set(data["space_group"])
        if "sample_type" in data:
            self.sample_type.set(data["sample_type"])
        if "sample_radius" in data:
            self.sample_radius.set(data["sample_radius"])
        if "sample_height" in data:
            self.sample_height.set(data["sample_height"])
        if "sample_mosaic" in data:
            self.sample_mosaic.set(data["sample_mosaic"])
        if "sample_temperature" in data:
            self.sample_temperature.set(data["sample_temperature"])
