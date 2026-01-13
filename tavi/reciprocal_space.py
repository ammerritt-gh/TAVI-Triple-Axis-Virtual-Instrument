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

    # Convert reciprocal lattice angles to radians for trigonometric calculations
    alpha_star_rad = math.radians(alpha_star)
    beta_star_rad = math.radians(beta_star)
    gamma_star_rad = math.radians(gamma_star)

    # Convert HKL to qx, qy, qz
    H = float(H)
    K = float(K)
    L = float(L)
    
    qx = (H * a_star + K * b_star * math.cos(gamma_star_rad) 
          + L * c_star * math.cos(beta_star_rad))
    qy = (K * b_star * math.sin(gamma_star_rad) 
          + L * c_star * (math.cos(alpha_star_rad) - math.cos(beta_star_rad) * math.cos(gamma_star_rad)) 
          / math.sin(gamma_star_rad))
    qz = (L * c_star * math.sqrt(
        1 - math.cos(alpha_star_rad)**2 - math.cos(beta_star_rad)**2 
        - math.cos(gamma_star_rad)**2 
        + 2 * math.cos(alpha_star_rad) * math.cos(beta_star_rad) * math.cos(gamma_star_rad)
    ) / math.sin(gamma_star_rad))

    return qx, qy, qz


def update_HKL_from_Q_direct(qx, qy, qz, a, b, c, alpha, beta, gamma):
    """Convert qx, qy, qz values to H, K, L in reciprocal lattice units.
    
    Args:
        qx, qy, qz: Wave vector components in inverse Angstroms
        a, b, c: Lattice parameters in Angstroms
        alpha, beta, gamma: Lattice angles in degrees
        
    Returns:
        tuple: (H, K, L) Miller indices
        
    Warning: This function contains a bug carried over from the original archive code.
    The equations use undefined variables K and L on the right-hand side, which will
    cause a NameError when executed. This is preserved exactly as it existed in the
    archive for backward compatibility. A proper implementation would require matrix
    inversion or solving the system of equations correctly.
    
    TODO: Fix the circular dependency by implementing proper inverse transformation.
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

    # Convert reciprocal lattice angles to radians for trigonometric calculations
    alpha_star_rad = math.radians(alpha_star)
    beta_star_rad = math.radians(beta_star)
    gamma_star_rad = math.radians(gamma_star)

    # Calculate H, K, L from qx, qy, qz (inverse transformation)
    # WARNING: Circular dependency bug from original code preserved here
    H = ((qx - K * b_star * math.cos(gamma_star_rad) 
          - L * c_star * math.cos(beta_star_rad)) / a_star)
    K = ((qy - L * c_star * (math.cos(alpha_star_rad) 
                              - math.cos(beta_star_rad) * math.cos(gamma_star_rad)) 
          / math.sin(gamma_star_rad)) 
         / (b_star * math.sin(gamma_star_rad)))
    L = (qz * math.sin(gamma_star_rad) 
         / (c_star * math.sqrt(
             1 - math.cos(alpha_star_rad)**2 - math.cos(beta_star_rad)**2 
             - math.cos(gamma_star_rad)**2 
             + 2 * math.cos(alpha_star_rad) * math.cos(beta_star_rad) * math.cos(gamma_star_rad)
         )))

    return H, K, L
