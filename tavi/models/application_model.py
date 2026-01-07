"""
Application Model - Central model that holds all sub-models and provides
a unified interface for state management and persistence.
"""
from typing import Dict, Any
import json
import os

from .base_model import BaseModel
from .instrument_model import InstrumentModel
from .sample_model import SampleModel
from .reciprocal_space_model import ReciprocalSpaceModel
from .scan_model import ScanModel
from .diagnostics_model import DiagnosticsModel
from .data_model import DataModel


class ApplicationModel(BaseModel):
    """
    Central application model that aggregates all domain models.
    
    Provides:
    - Unified access to all sub-models
    - State persistence (save/load)
    - Default values initialization
    """
    
    PARAMETERS_FILE = "parameters.json"
    
    def __init__(self):
        super().__init__()
        
        # Sub-models
        self.instrument = InstrumentModel()
        self.sample = SampleModel()
        self.reciprocal_space = ReciprocalSpaceModel()
        self.scan = ScanModel()
        self.diagnostics = DiagnosticsModel()
        self.data = DataModel()
        
        # Initialize default output folder
        self._initialize_output_folder()
    
    def _initialize_output_folder(self):
        """Initialize the default output folder."""
        output_dir = self.data.ensure_output_directory()
        default_folder = os.path.join(output_dir, "initial_testing")
        self.data.output_folder.set(default_folder)
        self.data.load_folder.set(default_folder)
    
    def set_defaults(self):
        """Set all models to default values."""
        # Instrument defaults
        self.instrument.mtt.set(30.0)
        self.instrument.stt.set(30.0)
        self.instrument.psi.set(30.0)
        self.instrument.att.set(30.0)
        self.instrument.Ki.set(2.662)
        self.instrument.Kf.set(2.662)
        self.instrument.Ei.set(14.7)
        self.instrument.Ef.set(14.7)
        self.instrument.monocris.set("PG[002]")
        self.instrument.anacris.set("PG[002]")
        self.instrument.alpha_1.set(40)
        self.instrument.alpha_2_30.set(False)
        self.instrument.alpha_2_40.set(True)
        self.instrument.alpha_2_60.set(False)
        self.instrument.alpha_3.set(30)
        self.instrument.alpha_4.set(30)
        self.instrument.rhmfac.set(1.0)
        self.instrument.rvmfac.set(1.0)
        self.instrument.rhafac.set(1.0)
        self.instrument.NMO_installed.set("None")
        self.instrument.V_selector_installed.set(False)
        
        # Sample defaults
        self.sample.lattice_a.set(3.78)
        self.sample.lattice_b.set(3.78)
        self.sample.lattice_c.set(5.49)
        self.sample.lattice_alpha.set(90.0)
        self.sample.lattice_beta.set(90.0)
        self.sample.lattice_gamma.set(90.0)
        
        # Reciprocal space defaults
        self.reciprocal_space.qx.set(2.0)
        self.reciprocal_space.qy.set(0.0)
        self.reciprocal_space.qz.set(0.0)
        self.reciprocal_space.deltaE.set(5.25)
        
        # Scan defaults
        self.scan.number_neutrons.set(1e6)
        self.scan.K_fixed.set("Kf Fixed")
        self.scan.fixed_E.set(14.7)
        self.scan.scan_command1.set("qx 2 2.2 0.1")
        self.scan.scan_command2.set("deltaE 3 7 0.25")
        self.scan.diagnostic_mode.set(True)
        
        # Diagnostics defaults - all disabled
        self.diagnostics.disable_all()
        
        # Update HKL from Q
        self._update_hkl_from_q()
    
    def _update_hkl_from_q(self):
        """Update HKL values from Q values using sample lattice parameters."""
        try:
            self.reciprocal_space.update_HKL_from_Q(
                self.sample.lattice_a.get(),
                self.sample.lattice_b.get(),
                self.sample.lattice_c.get(),
                self.sample.lattice_alpha.get(),
                self.sample.lattice_beta.get(),
                self.sample.lattice_gamma.get()
            )
        except (ValueError, Exception) as e:
            print(f"Error updating HKL from Q: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete application state to dictionary."""
        return {
            "instrument": self.instrument.to_dict(),
            "sample": self.sample.to_dict(),
            "reciprocal_space": self.reciprocal_space.to_dict(),
            "scan": self.scan.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "data": self.data.to_dict(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load complete application state from dictionary."""
        if "instrument" in data:
            self.instrument.from_dict(data["instrument"])
        if "sample" in data:
            self.sample.from_dict(data["sample"])
        if "reciprocal_space" in data:
            self.reciprocal_space.from_dict(data["reciprocal_space"])
        if "scan" in data:
            self.scan.from_dict(data["scan"])
        if "diagnostics" in data:
            self.diagnostics.from_dict(data["diagnostics"])
        if "data" in data:
            self.data.from_dict(data["data"])
    
    def save_parameters(self, filepath: str = None):
        """Save all parameters to a JSON file."""
        if filepath is None:
            filepath = self.PARAMETERS_FILE
        
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def load_parameters(self, filepath: str = None):
        """Load parameters from a JSON file."""
        if filepath is None:
            filepath = self.PARAMETERS_FILE
        
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                data = json.load(f)
                self.from_dict(data)
        else:
            self.set_defaults()
    
    def save_legacy_parameters(self, filepath: str = None):
        """Save parameters in the legacy format for backward compatibility."""
        if filepath is None:
            filepath = self.PARAMETERS_FILE
        
        # Convert to legacy format
        legacy_data = {
            "mtt_var": str(self.instrument.mtt.get()),
            "stt_var": self.instrument.stt.get(),
            "psi_var": self.instrument.psi.get(),
            "att_var": str(self.instrument.att.get()),
            "Ki_var": str(self.instrument.Ki.get()),
            "Kf_var": str(self.instrument.Kf.get()),
            "Ei_var": str(self.instrument.Ei.get()),
            "Ef_var": str(self.instrument.Ef.get()),
            "number_neutrons_var": self.scan.number_neutrons.get(),
            "K_fixed_var": self.scan.K_fixed.get(),
            "NMO_installed_var": self.instrument.NMO_installed.get(),
            "V_selector_installed_var": self.instrument.V_selector_installed.get(),
            "rhmfac_var": self.instrument.rhmfac.get(),
            "rvmfac_var": self.instrument.rvmfac.get(),
            "rhafac_var": self.instrument.rhafac.get(),
            "fixed_E_var": str(self.scan.fixed_E.get()),
            "qx_var": self.reciprocal_space.qx.get(),
            "qy_var": self.reciprocal_space.qy.get(),
            "qz_var": self.reciprocal_space.qz.get(),
            "deltaE_var": str(self.reciprocal_space.deltaE.get()),
            "monocris_var": self.instrument.monocris.get(),
            "anacris_var": self.instrument.anacris.get(),
            "alpha_1_var": self.instrument.alpha_1.get(),
            "alpha_2_30_var": self.instrument.alpha_2_30.get(),
            "alpha_2_40_var": self.instrument.alpha_2_40.get(),
            "alpha_2_60_var": self.instrument.alpha_2_60.get(),
            "alpha_3_var": self.instrument.alpha_3.get(),
            "alpha_4_var": self.instrument.alpha_4.get(),
            "diagnostic_mode_var": self.scan.diagnostic_mode.get(),
            "lattice_a_var": self.sample.lattice_a.get(),
            "lattice_b_var": self.sample.lattice_b.get(),
            "lattice_c_var": self.sample.lattice_c.get(),
            "lattice_alpha_var": self.sample.lattice_alpha.get(),
            "lattice_beta_var": self.sample.lattice_beta.get(),
            "lattice_gamma_var": self.sample.lattice_gamma.get(),
            "scan_command_var1": self.scan.scan_command1.get(),
            "scan_command_var2": self.scan.scan_command2.get(),
            "diagnostic_settings": self.diagnostics.to_dict(),
            "current_sample_settings": {
                "last_selected": self.sample.sample_type.get()
            }
        }
        
        with open(filepath, "w") as f:
            json.dump(legacy_data, f, indent=2)
    
    def load_legacy_parameters(self, filepath: str = None):
        """Load parameters from the legacy format."""
        if filepath is None:
            filepath = self.PARAMETERS_FILE
        
        if not os.path.exists(filepath):
            self.set_defaults()
            return
        
        with open(filepath, "r") as f:
            data = json.load(f)
        
        # Parse legacy format
        if "mtt_var" in data:
            try:
                self.instrument.mtt.set(float(data.get("mtt_var", 30)))
            except (ValueError, TypeError):
                self.instrument.mtt.set(30.0)
        
        if "stt_var" in data:
            self.instrument.stt.set(float(data.get("stt_var", 30)))
        if "psi_var" in data:
            self.instrument.psi.set(float(data.get("psi_var", 30)))
        if "att_var" in data:
            try:
                self.instrument.att.set(float(data.get("att_var", 30)))
            except (ValueError, TypeError):
                self.instrument.att.set(30.0)
        
        # Energy and wavevector
        if "Ki_var" in data:
            try:
                self.instrument.Ki.set(float(data.get("Ki_var", 2.662)))
            except (ValueError, TypeError):
                self.instrument.Ki.set(2.662)
        if "Kf_var" in data:
            try:
                self.instrument.Kf.set(float(data.get("Kf_var", 2.662)))
            except (ValueError, TypeError):
                self.instrument.Kf.set(2.662)
        if "Ei_var" in data:
            try:
                self.instrument.Ei.set(float(data.get("Ei_var", 14.7)))
            except (ValueError, TypeError):
                self.instrument.Ei.set(14.7)
        if "Ef_var" in data:
            try:
                self.instrument.Ef.set(float(data.get("Ef_var", 14.7)))
            except (ValueError, TypeError):
                self.instrument.Ef.set(14.7)
        
        # Crystal selections
        self.instrument.monocris.set(data.get("monocris_var", "PG[002]"))
        self.instrument.anacris.set(data.get("anacris_var", "PG[002]"))
        
        # Collimation
        self.instrument.alpha_1.set(data.get("alpha_1_var", 40))
        self.instrument.alpha_2_30.set(data.get("alpha_2_30_var", False))
        self.instrument.alpha_2_40.set(data.get("alpha_2_40_var", True))
        self.instrument.alpha_2_60.set(data.get("alpha_2_60_var", False))
        self.instrument.alpha_3.set(data.get("alpha_3_var", 30))
        self.instrument.alpha_4.set(data.get("alpha_4_var", 30))
        
        # Focusing
        self.instrument.rhmfac.set(data.get("rhmfac_var", 1))
        self.instrument.rvmfac.set(data.get("rvmfac_var", 1))
        self.instrument.rhafac.set(data.get("rhafac_var", 1))
        
        # Experimental modules
        self.instrument.NMO_installed.set(data.get("NMO_installed_var", "None"))
        self.instrument.V_selector_installed.set(data.get("V_selector_installed_var", False))
        
        # Scan parameters
        self.scan.number_neutrons.set(data.get("number_neutrons_var", 1e8))
        self.scan.K_fixed.set(data.get("K_fixed_var", "Kf Fixed"))
        try:
            self.scan.fixed_E.set(float(data.get("fixed_E_var", 14.7)))
        except (ValueError, TypeError):
            self.scan.fixed_E.set(14.7)
        self.scan.diagnostic_mode.set(data.get("diagnostic_mode_var", True))
        self.scan.scan_command1.set(data.get("scan_command_var1", ""))
        self.scan.scan_command2.set(data.get("scan_command_var2", ""))
        
        # Reciprocal space
        self.reciprocal_space.qx.set(data.get("qx_var", 2))
        self.reciprocal_space.qy.set(data.get("qy_var", 0))
        self.reciprocal_space.qz.set(data.get("qz_var", 0))
        try:
            self.reciprocal_space.deltaE.set(float(data.get("deltaE_var", 5.25)))
        except (ValueError, TypeError):
            self.reciprocal_space.deltaE.set(5.25)
        
        # Sample/lattice
        self.sample.lattice_a.set(data.get("lattice_a_var", 4.05))
        self.sample.lattice_b.set(data.get("lattice_b_var", 4.05))
        self.sample.lattice_c.set(data.get("lattice_c_var", 4.05))
        self.sample.lattice_alpha.set(data.get("lattice_alpha_var", 90))
        self.sample.lattice_beta.set(data.get("lattice_beta_var", 90))
        self.sample.lattice_gamma.set(data.get("lattice_gamma_var", 90))
        
        # Diagnostics
        if "diagnostic_settings" in data:
            self.diagnostics.from_dict(data["diagnostic_settings"])
        
        # Sample settings
        if "current_sample_settings" in data:
            sample_settings = data["current_sample_settings"]
            if "last_selected" in sample_settings:
                self.sample.sample_type.set(sample_settings["last_selected"])
        
        # Update HKL from Q
        self._update_hkl_from_q()
