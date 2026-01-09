"""Reciprocal space calculations for TAVI.

This module contains functions for converting between HKL reciprocal lattice
coordinates and Cartesian Q-space coordinates.
"""
import math


def update_Q_from_HKL_direct(H, K, L, a, b, c, alpha, beta, gamma):
    """Convert HKL values to qx, qy, qz in Cartesian coordinates.
    
    Args:
        H, K, L: Miller indices in reciprocal lattice units
        a, b, c: Lattice parameters in Angstroms
        alpha, beta, gamma: Lattice angles in degrees
        
    Returns:
        tuple: (qx, qy, qz) in inverse Angstroms
    """
    # Convert lattice parameters to radians
    alpha_rad = math.radians(alpha)
    beta_rad = math.radians(beta)
    gamma_rad = math.radians(gamma)

    # Calculate unit cell volume
    V = a * b * c * math.sqrt(
        1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 
        + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad)
    )
    
    # Calculate reciprocal lattice parameters
    a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
    b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
    c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
    
    # Calculate reciprocal lattice angles (in degrees)
    alpha_star = math.degrees(math.acos(
        (math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) 
        / (math.sin(beta_rad) * math.sin(gamma_rad))
    ))
    beta_star = math.degrees(math.acos(
        (math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) 
        / (math.sin(alpha_rad) * math.sin(gamma_rad))
    ))
    gamma_star = math.degrees(math.acos(
        (math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) 
        / (math.sin(alpha_rad) * math.sin(beta_rad))
    ))

    # Convert HKL to qx, qy, qz
    # Note: Original code uses angles in degrees with trig functions - preserving exact behavior
    H = float(H)
    K = float(K)
    L = float(L)
    
    qx = (H * a_star + K * b_star * math.cos(gamma_star) 
          + L * c_star * math.cos(beta_star))
    qy = (K * b_star * math.sin(gamma_star) 
          + L * c_star * (math.cos(alpha_star) - math.cos(beta_star) * math.cos(gamma_star)) 
          / math.sin(gamma_star))
    qz = (L * c_star * math.sqrt(
        1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 
        - math.cos(gamma_star)**2 
        + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)
    ) / math.sin(gamma_star))

    return qx, qy, qz


def update_HKL_from_Q_direct(qx, qy, qz, a, b, c, alpha, beta, gamma):
    """Convert qx, qy, qz values to H, K, L in reciprocal lattice units.
    
    Args:
        qx, qy, qz: Wave vector components in inverse Angstroms
        a, b, c: Lattice parameters in Angstroms
        alpha, beta, gamma: Lattice angles in degrees
        
    Returns:
        tuple: (H, K, L) Miller indices
        
    Note: This implements the inverse transformation as in the original code.
    The system has circular dependencies which may lead to unexpected results.
    """
    # Convert lattice parameters to radians
    alpha_rad = math.radians(alpha)
    beta_rad = math.radians(beta)
    gamma_rad = math.radians(gamma)

    # Calculate unit cell volume
    V = a * b * c * math.sqrt(
        1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 
        + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad)
    )
    
    # Calculate reciprocal lattice parameters
    a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
    b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
    c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
    
    # Calculate reciprocal lattice angles (in degrees)
    alpha_star = math.degrees(math.acos(
        (math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) 
        / (math.sin(beta_rad) * math.sin(gamma_rad))
    ))
    beta_star = math.degrees(math.acos(
        (math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) 
        / (math.sin(alpha_rad) * math.sin(gamma_rad))
    ))
    gamma_star = math.degrees(math.acos(
        (math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) 
        / (math.sin(alpha_rad) * math.sin(beta_rad))
    ))

    # Calculate H, K, L from qx, qy, qz (inverse transformation)
    # Note: Original code has circular dependencies - preserving exact behavior
    H = ((qx - K * b_star * math.cos(gamma_star) 
          - L * c_star * math.cos(beta_star)) / a_star)
    K = ((qy - L * c_star * (math.cos(alpha_star) 
                              - math.cos(beta_star) * math.cos(gamma_star)) 
          / math.sin(gamma_star)) 
         / (b_star * math.sin(gamma_star)))
    L = (qz * math.sin(gamma_star) 
         / (c_star * math.sqrt(
             1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 
             - math.cos(gamma_star)**2 
             + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)
         )))

    return H, K, L
