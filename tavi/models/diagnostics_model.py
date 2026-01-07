"""
Diagnostics Model - Holds the state of diagnostic monitor settings.
"""
from typing import Dict, Any, List
from .base_model import BaseModel, Observable


class DiagnosticsModel(BaseModel):
    """
    Model for diagnostic configuration state.
    
    This includes settings for various Position Sensitive Detectors (PSD),
    Divergence Sensitive Detectors (DSD), and Energy Monitors (Emonitor)
    throughout the beamline.
    """
    
    # List of all available diagnostic options
    DIAGNOSTIC_OPTIONS = [
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
    
    def __init__(self):
        super().__init__()
        
        # Create an observable for each diagnostic option
        self.settings: Dict[str, Observable] = {}
        for option in self.DIAGNOSTIC_OPTIONS:
            self.settings[option] = Observable(False)
    
    def get_setting(self, name: str) -> bool:
        """Get the value of a diagnostic setting."""
        if name in self.settings:
            return self.settings[name].get()
        return False
    
    def set_setting(self, name: str, value: bool):
        """Set the value of a diagnostic setting."""
        if name in self.settings:
            self.settings[name].set(value)
    
    def get_enabled_diagnostics(self) -> List[str]:
        """Get a list of all enabled diagnostic options."""
        return [name for name, obs in self.settings.items() if obs.get()]
    
    def enable_all(self):
        """Enable all diagnostic options."""
        for obs in self.settings.values():
            obs.set(True)
    
    def disable_all(self):
        """Disable all diagnostic options."""
        for obs in self.settings.values():
            obs.set(False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize diagnostics state to dictionary."""
        return {name: obs.get() for name, obs in self.settings.items()}
    
    def from_dict(self, data: Dict[str, Any]):
        """Load diagnostics state from dictionary."""
        for name, value in data.items():
            if name in self.settings:
                self.settings[name].set(value)
