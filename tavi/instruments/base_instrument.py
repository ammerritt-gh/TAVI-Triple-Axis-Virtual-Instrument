"""
Base Instrument Definition - Abstract base class for instrument definitions.
Different instruments (PUMA, etc.) can inherit from this.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, List, Optional
import math


# Physical constants
N_MASS = 1.67492749804e-27  # neutron mass (kg)
E_CHARGE = 1.602176634e-19  # electron charge (C)
K_B = 0.08617333262  # Boltzmann's constant (meV/K)
HBAR_MEV = 6.582119569e-13  # H-bar (meV*s)
HBAR = 1.05459e-34  # H-bar (J*s)


class InvalidAngleError(ValueError):
    """Raised when a Bragg angle calculation produces an invalid result."""
    pass


def k_to_angle(k: float, d: float) -> float:
    """
    Convert a k value to a Bragg scattering 2-theta angle.
    
    Args:
        k: Wavevector magnitude (1/Å)
        d: Crystal d-spacing (Å)
        
    Returns:
        2-theta angle in degrees
        
    Raises:
        InvalidAngleError: If the momentum transfer is outside the valid range
    """
    if k == 0 or d == 0:
        raise InvalidAngleError(f"Invalid k ({k}) or d ({d}) value: cannot be zero")
    arg = 2 * math.pi / (2 * k * d)
    if -1 <= arg <= 1:
        return math.degrees(math.asin(arg))
    raise InvalidAngleError(f"Momentum transfer {k} with d-spacing {d} produces invalid angle (sin={arg})")


def angle_to_k(angle: float, d: float) -> float:
    """Convert a Bragg scattering 2-theta angle to a k value."""
    sin_val = math.sin(math.radians(angle))
    if d * sin_val != 0:
        return abs(math.pi / (d * sin_val))
    return 0


def k_to_energy(k: float) -> float:
    """Convert momentum k (1/Å) to energy (meV)."""
    return 1e3 * pow((k * 1e10 * HBAR), 2) / (2 * N_MASS * E_CHARGE)


def energy_to_k(energy: float) -> float:
    """Convert energy (meV) to momentum k (1/Å)."""
    import numpy as np
    return np.sqrt(energy * 1e-3 * E_CHARGE * 2 * N_MASS) * 1e-10 / HBAR


def energy_to_lambda(energy: float) -> float:
    """Convert energy (meV) to wavelength (Å)."""
    return 9.044567 / math.sqrt(energy)


class CrystalInfo:
    """Information about a monochromator or analyzer crystal."""
    
    def __init__(self, name: str, d_spacing: float, slab_width: float, slab_height: float,
                 n_columns: int, n_rows: int, gap: float, mosaic: float, r0: float):
        self.name = name
        self.d_spacing = d_spacing  # d-spacing in Angstroms
        self.slab_width = slab_width
        self.slab_height = slab_height
        self.n_columns = n_columns
        self.n_rows = n_rows
        self.gap = gap
        self.mosaic = mosaic  # in arcminutes
        self.r0 = r0  # reflectivity


class BaseInstrument(ABC):
    """
    Abstract base class for Triple-Axis Spectrometer instruments.
    
    Subclasses should implement the specific geometry and components
    for their particular instrument.
    """
    
    def __init__(self):
        # Arm lengths (meters)
        self.L1 = 0.0  # source-mono
        self.L2 = 0.0  # mono-sample
        self.L3 = 0.0  # sample-analyzer
        self.L4 = 0.0  # analyzer-detector
        
        # Angles (degrees)
        self.A1 = 0.0  # mono two-theta
        self.A2 = 0.0  # sample two-theta (phi)
        self.A3 = 0.0  # sample theta (psi)
        self.A4 = 0.0  # analyzer two-theta
        self.saz = 0.0  # sample z-angle
        
        # Operating mode
        self.K_fixed = "Kf Fixed"
        self.fixed_E = 14.7  # meV
        
        # Crystal selections
        self.monocris = "PG[002]"
        self.anacris = "PG[002]"
        
        # Collimation (arcminutes)
        self.alpha_1 = 0  # source-mono
        self.alpha_2 = []  # mono-sample (list for multiple collimators)
        self.alpha_3 = 0  # sample-analyzer
        self.alpha_4 = 0  # analyzer-detector
        
        # Focusing factors
        self.rhmfac = 1.0  # mono horizontal
        self.rvmfac = 1.0  # mono vertical
        self.rhafac = 1.0  # analyzer horizontal
        
        # Crystal bending radii (meters)
        self.rhm = 0.0
        self.rvm = 0.0
        self.rha = 0.0
        self.rva = 0.0
        
        # Available crystals
        self._monochromator_crystals: Dict[str, CrystalInfo] = {}
        self._analyzer_crystals: Dict[str, CrystalInfo] = {}
        
        # Diagnostic settings
        self.diagnostic_mode = False
        self.diagnostic_settings: Dict[str, bool] = {}
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the instrument name."""
        pass
    
    @abstractmethod
    def get_available_monochromators(self) -> List[str]:
        """Return list of available monochromator crystals."""
        pass
    
    @abstractmethod
    def get_available_analyzers(self) -> List[str]:
        """Return list of available analyzer crystals."""
        pass
    
    def get_monochromator_info(self, name: str) -> Optional[CrystalInfo]:
        """Get information about a monochromator crystal."""
        return self._monochromator_crystals.get(name)
    
    def get_analyzer_info(self, name: str) -> Optional[CrystalInfo]:
        """Get information about an analyzer crystal."""
        return self._analyzer_crystals.get(name)
    
    def set_angles(self, A1: float = None, A2: float = None, 
                   A3: float = None, A4: float = None):
        """Set instrument angles."""
        if A1 is not None:
            self.A1 = A1
        if A2 is not None:
            self.A2 = A2
        if A3 is not None:
            self.A3 = A3
        if A4 is not None:
            self.A4 = A4
    
    def set_crystal_bending(self, rhm: float = None, rvm: float = None,
                            rha: float = None, rva: float = None):
        """Set crystal bending radii."""
        if rhm is not None:
            self.rhm = rhm
        if rvm is not None:
            self.rvm = rvm
        if rha is not None:
            self.rha = rha
        if rva is not None:
            self.rva = rva
    
    def calculate_angles(self, qx: float, qy: float, qz: float, deltaE: float,
                         fixed_E: float, K_fixed: str, monocris: str, anacris: str
                         ) -> Tuple[List[float], List[str]]:
        """
        Calculate instrument angles from scattering parameters.
        
        Args:
            qx, qy, qz: Momentum transfer components (1/Å)
            deltaE: Energy transfer (meV)
            fixed_E: Fixed energy value (meV)
            K_fixed: "Ki Fixed" or "Kf Fixed"
            monocris: Monochromator crystal name
            anacris: Analyzer crystal name
            
        Returns:
            Tuple of (angles_array, error_flags)
            angles_array: [mtt, stt, sth, saz, att]
            error_flags: List of error identifiers
        """
        error_flags = []
        
        # Get crystal d-spacings
        mono_info = self.get_monochromator_info(monocris)
        ana_info = self.get_analyzer_info(anacris)
        
        if mono_info is None or ana_info is None:
            return [0, 0, 0, 0, 0], ["crystal_not_found"]
        
        dm = mono_info.d_spacing
        da = ana_info.d_spacing
        
        # Calculate Q magnitude
        q = math.sqrt(qx**2 + qy**2 + qz**2)
        if q == 0:
            return [0, 0, 0, 0, 0], ["q_zero"]
        
        K = energy_to_k(fixed_E)
        
        mtt = 0
        att = 0
        ki = 0
        kf = 0
        Ei = 0
        Ef = 0
        
        try:
            if K_fixed == "Ki Fixed":
                mtt = 2 * k_to_angle(K, dm)
                Ei = fixed_E
                ki = energy_to_k(Ei)
                Ef = Ei - deltaE
                if Ef <= 0:
                    return [0, 0, 0, 0, 0], ["negative_Ef"]
                kf = energy_to_k(Ef)
                att = 2 * k_to_angle(kf, da)
            else:  # Kf Fixed
                att = 2 * k_to_angle(K, da)
                Ef = fixed_E
                kf = energy_to_k(Ef)
                Ei = Ef + deltaE
                if Ei <= 0:
                    return [0, 0, 0, 0, 0], ["negative_Ei"]
                ki = energy_to_k(Ei)
                mtt = 2 * k_to_angle(ki, dm)
        except InvalidAngleError as e:
            if "mtt" not in str(e).lower() and K_fixed == "Ki Fixed":
                error_flags.append("att")
            else:
                error_flags.append("mtt")
            # Set to 0 for invalid angles
            if mtt == 0:
                mtt = 0
            if att == 0:
                att = 0
        
        # Calculate sample two-theta (law of cosines)
        cos_stt = (q**2 - ki**2 - kf**2) / (-2 * ki * kf)
        if -1 <= cos_stt <= 1:
            stt = -math.degrees(math.acos(cos_stt))
        else:
            stt = 0
            error_flags.append("stt")
        
        # Calculate sample theta
        if "stt" in error_flags:
            sth = 0
        else:
            if qx == 0:
                sth = stt / 2 + 90
            else:
                sth = stt / 2 + math.degrees(math.atan(qy / qx))
        
        # Calculate sample azimuth
        qxy = math.sqrt(qx**2 + qy**2)
        if qxy > 0:
            saz = -math.degrees(math.atan(qz / qxy))
        else:
            saz = 0
        
        return [mtt, stt, sth, saz, att], error_flags
    
    def calculate_q_and_deltaE(self, mtt: float, stt: float, sth: float,
                                saz: float, att: float, fixed_E: float,
                                K_fixed: str, monocris: str, anacris: str
                                ) -> Tuple[List[float], List[str]]:
        """
        Calculate Q and deltaE from instrument angles.
        
        Returns:
            Tuple of ([qx, qy, qz, deltaE], error_flags)
        """
        error_flags = []
        
        mono_info = self.get_monochromator_info(monocris)
        ana_info = self.get_analyzer_info(anacris)
        
        if mono_info is None or ana_info is None:
            return [0, 0, 0, 0], ["crystal_not_found"]
        
        dm = mono_info.d_spacing
        da = ana_info.d_spacing
        
        if K_fixed == "Ki Fixed":
            ki = energy_to_k(fixed_E)
            Ei = fixed_E
            kf = angle_to_k(att / 2, da)
            Ef = k_to_energy(kf)
            deltaE = Ei - Ef
        else:  # Kf Fixed
            kf = energy_to_k(fixed_E)
            Ef = fixed_E
            ki = angle_to_k(mtt / 2, dm)
            Ei = k_to_energy(ki)
            deltaE = Ei - Ef
        
        # Calculate Q components
        stt_rad = math.radians(stt)
        sth_rad = math.radians(sth)
        saz_rad = math.radians(saz)
        
        qx = ki * math.cos(sth_rad) - kf * math.cos(sth_rad + stt_rad)
        qy = ki * math.sin(sth_rad) - kf * math.sin(sth_rad + stt_rad)
        qz = -kf * math.tan(saz_rad) if saz_rad != 0 else 0
        
        return [qx, qy, qz, deltaE], error_flags
    
    @abstractmethod
    def calculate_crystal_bending(self, rhmfac: float, rvmfac: float,
                                   rhafac: float, mth: float, ath: float
                                   ) -> Tuple[float, float, float, float]:
        """
        Calculate crystal bending radii.
        
        Returns:
            Tuple of (rhm, rvm, rha, rva)
        """
        pass
    
    def update_diagnostic_settings(self, settings: Dict[str, bool]):
        """Update diagnostic settings."""
        self.diagnostic_settings.update(settings)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize instrument state to dictionary."""
        return {
            "name": self.name,
            "L1": self.L1,
            "L2": self.L2,
            "L3": self.L3,
            "L4": self.L4,
            "A1": self.A1,
            "A2": self.A2,
            "A3": self.A3,
            "A4": self.A4,
            "saz": self.saz,
            "K_fixed": self.K_fixed,
            "fixed_E": self.fixed_E,
            "monocris": self.monocris,
            "anacris": self.anacris,
            "alpha_1": self.alpha_1,
            "alpha_2": self.alpha_2,
            "alpha_3": self.alpha_3,
            "alpha_4": self.alpha_4,
            "rhmfac": self.rhmfac,
            "rvmfac": self.rvmfac,
            "rhafac": self.rhafac,
            "rhm": self.rhm,
            "rvm": self.rvm,
            "rha": self.rha,
            "rva": self.rva,
            "diagnostic_mode": self.diagnostic_mode,
            "diagnostic_settings": self.diagnostic_settings,
        }
