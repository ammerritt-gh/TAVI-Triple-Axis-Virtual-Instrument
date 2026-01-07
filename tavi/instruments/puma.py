"""
PUMA Instrument Definition - Specific implementation for the PUMA TAS.
"""
from typing import Dict, List, Tuple, Optional
import math

from .base_instrument import BaseInstrument, CrystalInfo


# Minimum angle epsilon to avoid division by zero
MIN_ANGLE_EPSILON = 0.001


class PUMAInstrument(BaseInstrument):
    """
    PUMA Triple-Axis Spectrometer instrument definition.
    
    PUMA is located at FRM II in Munich, Germany.
    This class defines all the specific geometry and parameters
    for the PUMA instrument.
    """
    
    def __init__(self, diagnostic_mode: bool = False, 
                 diagnostic_settings: Dict[str, bool] = None):
        super().__init__()
        
        # PUMA-specific arm lengths
        self.L1 = 2.150  # source-mono
        self.L2 = 2.290  # mono-sample (includes 0.2m pull-out for NMO)
        self.L3 = 0.880  # sample-analyzer
        self.L4 = 0.750  # analyzer-detector
        
        # Slit apertures
        self.hbl_vgap = 150e-3  # horizontal beam limiter vertical gap
        self.hbl_hgap = 78e-3   # horizontal beam limiter horizontal gap
        self.vbl_hgap = 88e-3   # vertical beam limiter horizontal gap
        self.pbl_voffset = 0
        self.pbl_vgap = 100e-3
        self.pbl_hoffset = 0
        self.pbl_hgap = 100e-3
        self.dbl_hgap = 50e-3
        
        # Experimental modules
        self.NMO_installed = "None"  # None, Vertical, Horizontal, Both
        self.V_selector_installed = False
        
        # Initialize crystals
        self._init_crystals()
        
        # Diagnostic settings
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_settings = diagnostic_settings if diagnostic_settings else {}
    
    def _init_crystals(self):
        """Initialize available monochromator and analyzer crystals."""
        # PG[002] Monochromator
        self._monochromator_crystals["PG[002]"] = CrystalInfo(
            name="PG[002]",
            d_spacing=3.355,
            slab_width=0.0202,
            slab_height=0.018,
            n_columns=13,
            n_rows=9,
            gap=0.0005,
            mosaic=35,
            r0=1.0
        )
        
        # PG[002] Test (different d-spacing for testing)
        self._monochromator_crystals["PG[002] test"] = CrystalInfo(
            name="PG[002] test",
            d_spacing=2.355,
            slab_width=0.0202,
            slab_height=0.018,
            n_columns=13,
            n_rows=9,
            gap=0.0005,
            mosaic=35,
            r0=1.0
        )
        
        # PG[002] Analyzer
        self._analyzer_crystals["PG[002]"] = CrystalInfo(
            name="PG[002]",
            d_spacing=3.355,
            slab_width=0.01,
            slab_height=0.0295,
            n_columns=21,
            n_rows=5,
            gap=0.0005,
            mosaic=35,
            r0=1.0
        )
    
    @property
    def name(self) -> str:
        return "PUMA"
    
    def get_available_monochromators(self) -> List[str]:
        return list(self._monochromator_crystals.keys())
    
    def get_available_analyzers(self) -> List[str]:
        return list(self._analyzer_crystals.keys())
    
    def calculate_crystal_bending(self, rhmfac: float, rvmfac: float,
                                   rhafac: float, mth: float, ath: float
                                   ) -> Tuple[float, float, float, float]:
        """
        Calculate crystal bending radii for PUMA.
        
        Args:
            rhmfac: Horizontal monochromator focus factor
            rvmfac: Vertical monochromator focus factor
            rhafac: Horizontal analyzer focus factor
            mth: Monochromator theta angle (degrees)
            ath: Analyzer theta angle (degrees)
            
        Returns:
            Tuple of (rhm, rvm, rha, rva) in meters
        """
        # Avoid division by zero with minimum angle epsilon
        if mth == 0:
            mth = MIN_ANGLE_EPSILON
        if ath == 0:
            ath = MIN_ANGLE_EPSILON
            
        sin_mth = math.sin(math.radians(mth))
        sin_ath = math.sin(math.radians(ath))
        
        # Calculate focusing radii
        rhm = rhmfac * 2 / sin_mth / (1/self.L1 + 1/self.L2)
        rvm = rvmfac * 2 * sin_mth / (1/self.L1 + 1/self.L2)
        rha = rhafac * 2 / sin_ath / (1/self.L3 + 1/self.L4)
        rva = 0.8  # Fixed at 0.8 m for PUMA
        
        # Apply minimum radius constraints
        if rhm < 2.0 and rhmfac != 0:
            print(f"Requested Rh (mono) is {rhm:.2f} m, using minimum 2.0 m")
            rhm = 2.0
        
        if rvm < 0.5 and rvmfac != 0:
            print(f"Requested Rv (mono) is {rvm:.2f} m, using minimum 0.5 m")
            rvm = 0.5
        
        if rha < 2.0:
            print(f"Requested Rh (ana) is {rha:.2f} m, using minimum 2.0 m")
            rha = 2.0
        
        print(f"Crystal bending: rhm={rhm:.2f}, rvm={rvm:.2f}, rha={rha:.2f}, rva={rva:.2f}")
        
        return rhm, rvm, rha, rva
    
    def get_diagnostic_options(self) -> List[str]:
        """Return all available diagnostic monitor options."""
        return [
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


def get_crystal_setup(monocris: str, anacris: str) -> Tuple[Dict, Dict]:
    """
    Get crystal setup information for backward compatibility.
    
    This function provides the same interface as the original
    mono_ana_crystals_setup function.
    
    Args:
        monocris: Monochromator crystal name
        anacris: Analyzer crystal name
        
    Returns:
        Tuple of (monochromator_info, analyzer_info) dictionaries
    """
    puma = PUMAInstrument()
    
    mono_info = puma.get_monochromator_info(monocris)
    ana_info = puma.get_analyzer_info(anacris)
    
    mono_dict = {}
    ana_dict = {}
    
    if mono_info:
        mono_dict = {
            'dm': mono_info.d_spacing,
            'slabwidth': mono_info.slab_width,
            'slabheight': mono_info.slab_height,
            'ncolumns': mono_info.n_columns,
            'nrows': mono_info.n_rows,
            'gap': mono_info.gap,
            'mosaic': mono_info.mosaic,
            'r0': mono_info.r0,
        }
    
    if ana_info:
        ana_dict = {
            'da': ana_info.d_spacing,
            'slabwidth': ana_info.slab_width,
            'slabheight': ana_info.slab_height,
            'ncolumns': ana_info.n_columns,
            'nrows': ana_info.n_rows,
            'gap': ana_info.gap,
            'mosaic': ana_info.mosaic,
            'r0': ana_info.r0,
        }
    
    return mono_dict, ana_dict
