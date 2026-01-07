"""
Reciprocal Space Model - Holds the state of reciprocal space coordinates.
Includes absolute Q-space (qx, qy, qz) and relative HKL units, plus deltaE.
"""
from typing import Dict, Any
from .base_model import BaseModel, Observable
import math
import numpy as np


class ReciprocalSpaceModel(BaseModel):
    """
    Model for reciprocal space state.
    
    This includes:
    - Absolute momentum transfer (qx, qy, qz in 1/Å)
    - Relative reciprocal lattice units (H, K, L)
    - Energy transfer (deltaE in meV)
    """
    
    def __init__(self):
        super().__init__()
        
        # Absolute momentum transfer (1/Å)
        self.qx = Observable(2.0)
        self.qy = Observable(0.0)
        self.qz = Observable(0.0)
        
        # Relative reciprocal lattice units (r.l.u.)
        self.H = Observable(0.0)
        self.K = Observable(0.0)
        self.L = Observable(0.0)
        
        # Energy transfer (meV)
        self.deltaE = Observable(5.25)
        
    def update_HKL_from_Q(self, a: float, b: float, c: float, 
                          alpha: float, beta: float, gamma: float):
        """
        Update H, K, L from qx, qy, qz using lattice parameters.
        
        Args:
            a, b, c: Lattice parameters in Angstroms
            alpha, beta, gamma: Lattice angles in degrees
        """
        # Convert angles to radians
        alpha_rad = math.radians(alpha)
        beta_rad = math.radians(beta)
        gamma_rad = math.radians(gamma)
        
        # Calculate unit cell volume
        V_cell = a * b * c * math.sqrt(
            1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 +
            2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad)
        )
        
        if V_cell <= 0:
            raise ValueError("Invalid lattice parameters: Unit cell volume is zero or negative.")
        
        # Reciprocal lattice vectors
        b1 = np.array([2 * math.pi * b * c * math.sin(alpha_rad) / V_cell, 0, 0])
        b2 = np.array([
            2 * math.pi * c * math.cos(beta_rad) / V_cell,
            2 * math.pi * a * c * math.sin(beta_rad) / V_cell,
            0
        ])
        b3 = np.array([
            2 * math.pi * a * b * math.sin(gamma_rad) / V_cell,
            2 * math.pi * b * math.cos(alpha_rad) / V_cell,
            2 * math.pi * c / V_cell
        ])
        
        # Assemble the reciprocal lattice matrix
        reciprocal_matrix = np.array([b1, b2, b3]).T
        
        # The momentum transfer vector
        q_vector = np.array([self.qx.get(), self.qy.get(), self.qz.get()])
        
        # Solve for H, K, L with robust error handling
        try:
            # Check matrix condition before solving
            cond_num = np.linalg.cond(reciprocal_matrix)
            if cond_num > 1e10:
                raise ValueError(f"Matrix is ill-conditioned (condition number: {cond_num:.2e})")
            
            HKL = np.linalg.solve(reciprocal_matrix, q_vector)
            self.H.set(HKL[0])
            self.K.set(HKL[1])
            self.L.set(HKL[2])
        except np.linalg.LinAlgError as e:
            raise ValueError(f"Matrix inversion failed: {e}. Check lattice parameters.")
    
    def update_Q_from_HKL(self, a: float, b: float, c: float,
                          alpha: float, beta: float, gamma: float):
        """
        Update qx, qy, qz from H, K, L using lattice parameters.
        
        Args:
            a, b, c: Lattice parameters in Angstroms
            alpha, beta, gamma: Lattice angles in degrees
        """
        # Convert angles to radians
        alpha_rad = math.radians(alpha)
        beta_rad = math.radians(beta)
        gamma_rad = math.radians(gamma)
        
        # Calculate unit cell volume
        V_cell = a * b * c * math.sqrt(
            1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 +
            2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad)
        )
        
        if V_cell <= 0:
            raise ValueError("Invalid lattice parameters: Unit cell volume is zero or negative.")
        
        # Reciprocal lattice vectors
        b1 = np.array([2 * math.pi * b * c * math.sin(alpha_rad) / V_cell, 0, 0])
        b2 = np.array([
            2 * math.pi * c * math.cos(beta_rad) / V_cell,
            2 * math.pi * a * c * math.sin(beta_rad) / V_cell,
            0
        ])
        b3 = np.array([
            2 * math.pi * a * b * math.sin(gamma_rad) / V_cell,
            2 * math.pi * b * math.cos(alpha_rad) / V_cell,
            2 * math.pi * c / V_cell
        ])
        
        # Assemble the reciprocal lattice matrix
        reciprocal_matrix = np.array([b1, b2, b3]).T
        
        # Get H, K, L values
        HKL = np.array([self.H.get(), self.K.get(), self.L.get()])
        
        # Compute qx, qy, qz
        q_vector = reciprocal_matrix @ HKL
        
        self.qx.set(q_vector[0])
        self.qy.set(q_vector[1])
        self.qz.set(q_vector[2])
    
    def get_Q_magnitude(self) -> float:
        """Calculate the magnitude of the momentum transfer vector."""
        return math.sqrt(self.qx.get()**2 + self.qy.get()**2 + self.qz.get()**2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize reciprocal space state to dictionary."""
        return {
            "qx": self.qx.get(),
            "qy": self.qy.get(),
            "qz": self.qz.get(),
            "H": self.H.get(),
            "K": self.K.get(),
            "L": self.L.get(),
            "deltaE": self.deltaE.get(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load reciprocal space state from dictionary."""
        if "qx" in data:
            self.qx.set(data["qx"])
        if "qy" in data:
            self.qy.set(data["qy"])
        if "qz" in data:
            self.qz.set(data["qz"])
        if "H" in data:
            self.H.set(data["H"])
        if "K" in data:
            self.K.set(data["K"])
        if "L" in data:
            self.L.set(data["L"])
        if "deltaE" in data:
            self.deltaE.set(data["deltaE"])
