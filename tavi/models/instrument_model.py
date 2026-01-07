"""
Instrument Model - Holds the state of the instrument configuration.
Includes angles, energies, crystals, collimations, focusing, and experimental modules.
"""
from typing import Dict, List, Any, Optional
from .base_model import BaseModel, Observable


class InstrumentModel(BaseModel):
    """
    Model for instrument configuration state.
    
    This includes:
    - Instrument angles (mtt, stt, psi, att)
    - Ki/Ei and Kf/Ef values
    - Monochromator and analyzer crystal selections
    - Collimation settings (alpha_1 through alpha_4)
    - Slit sizes
    - Focusing parameters (rhmfac, rvmfac, rhafac)
    - Experimental modules (NMO, velocity selector)
    """
    
    def __init__(self):
        super().__init__()
        
        # Instrument angles
        self.mtt = Observable(30.0)  # Monochromator 2-theta
        self.stt = Observable(30.0)  # Sample 2-theta
        self.psi = Observable(30.0)  # Sample theta (psi)
        self.att = Observable(30.0)  # Analyzer 2-theta
        
        # Wavevector and energy values
        self.Ki = Observable(2.662)  # Incident wavevector (1/Å)
        self.Kf = Observable(2.662)  # Final wavevector (1/Å)
        self.Ei = Observable(14.7)   # Incident energy (meV)
        self.Ef = Observable(14.7)   # Final energy (meV)
        
        # Crystal selections
        self.monocris = Observable("PG[002]")  # Monochromator crystal
        self.anacris = Observable("PG[002]")   # Analyzer crystal
        
        # Collimation settings (in arcminutes)
        self.alpha_1 = Observable(40)     # Source-mono collimation
        self.alpha_2_30 = Observable(False)  # 30' mono-sample collimator
        self.alpha_2_40 = Observable(True)   # 40' mono-sample collimator
        self.alpha_2_60 = Observable(False)  # 60' mono-sample collimator
        self.alpha_3 = Observable(30)     # Sample-analyzer collimation
        self.alpha_4 = Observable(30)     # Analyzer-detector collimation
        
        # Focusing parameters
        self.rhmfac = Observable(1.0)  # Monochromator horizontal focus factor
        self.rvmfac = Observable(1.0)  # Monochromator vertical focus factor
        self.rhafac = Observable(1.0)  # Analyzer horizontal focus factor
        
        # Experimental modules
        self.NMO_installed = Observable("None")  # NMO installation: None, Vertical, Horizontal, Both
        self.V_selector_installed = Observable(False)  # Velocity selector
        
    def get_alpha_2_list(self) -> List[int]:
        """Get the list of enabled alpha_2 collimators."""
        result = []
        if self.alpha_2_30.get():
            result.append(30)
        if self.alpha_2_40.get():
            result.append(40)
        if self.alpha_2_60.get():
            result.append(60)
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize instrument state to dictionary."""
        return {
            "mtt": self.mtt.get(),
            "stt": self.stt.get(),
            "psi": self.psi.get(),
            "att": self.att.get(),
            "Ki": self.Ki.get(),
            "Kf": self.Kf.get(),
            "Ei": self.Ei.get(),
            "Ef": self.Ef.get(),
            "monocris": self.monocris.get(),
            "anacris": self.anacris.get(),
            "alpha_1": self.alpha_1.get(),
            "alpha_2_30": self.alpha_2_30.get(),
            "alpha_2_40": self.alpha_2_40.get(),
            "alpha_2_60": self.alpha_2_60.get(),
            "alpha_3": self.alpha_3.get(),
            "alpha_4": self.alpha_4.get(),
            "rhmfac": self.rhmfac.get(),
            "rvmfac": self.rvmfac.get(),
            "rhafac": self.rhafac.get(),
            "NMO_installed": self.NMO_installed.get(),
            "V_selector_installed": self.V_selector_installed.get(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load instrument state from dictionary."""
        if "mtt" in data:
            self.mtt.set(data["mtt"])
        if "stt" in data:
            self.stt.set(data["stt"])
        if "psi" in data:
            self.psi.set(data["psi"])
        if "att" in data:
            self.att.set(data["att"])
        if "Ki" in data:
            self.Ki.set(data["Ki"])
        if "Kf" in data:
            self.Kf.set(data["Kf"])
        if "Ei" in data:
            self.Ei.set(data["Ei"])
        if "Ef" in data:
            self.Ef.set(data["Ef"])
        if "monocris" in data:
            self.monocris.set(data["monocris"])
        if "anacris" in data:
            self.anacris.set(data["anacris"])
        if "alpha_1" in data:
            self.alpha_1.set(data["alpha_1"])
        if "alpha_2_30" in data:
            self.alpha_2_30.set(data["alpha_2_30"])
        if "alpha_2_40" in data:
            self.alpha_2_40.set(data["alpha_2_40"])
        if "alpha_2_60" in data:
            self.alpha_2_60.set(data["alpha_2_60"])
        if "alpha_3" in data:
            self.alpha_3.set(data["alpha_3"])
        if "alpha_4" in data:
            self.alpha_4.set(data["alpha_4"])
        if "rhmfac" in data:
            self.rhmfac.set(data["rhmfac"])
        if "rvmfac" in data:
            self.rvmfac.set(data["rvmfac"])
        if "rhafac" in data:
            self.rhafac.set(data["rhafac"])
        if "NMO_installed" in data:
            self.NMO_installed.set(data["NMO_installed"])
        if "V_selector_installed" in data:
            self.V_selector_installed.set(data["V_selector_installed"])
