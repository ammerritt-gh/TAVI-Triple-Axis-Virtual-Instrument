from instruments.PUMA_instrument_definition import k2angle, k2energy, angle2k, energy2k, PUMA_Instrument
import tkinter as tk
from decimal import Decimal, InvalidOperation
import math
import numpy as np
from numpy.linalg import inv

updating = False

def format_value(value, precision=4):
    """Rounds the value to "precision" decimal points."""
    try:
        value = Decimal(value).quantize(Decimal(f"1.{'0'*precision}")).normalize()
        return str(value)
    except (ValueError, InvalidOperation):
        return value

def is_valid_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False
    
def update_all_variables(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    global updating
    if updating:
        return
    try:
        fixed_E = float(fixed_E_var.get())
        deltaE = float(deltaE_var.get())
        K_fixed = K_fixed_var.get()
        
        updating = True
        if K_fixed == "Ki Fixed":
            Ei = fixed_E
            Ef = Ei - deltaE
        else: # Kf fixed
            Ef = fixed_E
            Ei = Ef + deltaE

        Ki = energy2k(Ei)
        Kf = energy2k(Ef)
        
        mtt = 2*k2angle(Ki, monocris_info['dm'])
        att = 2*k2angle(Kf, anacris_info['da'])
        
        Ei_var.set(format_value(Ei))
        Ef_var.set(format_value(Ef))
        Ki_var.set(format_value(Ki))
        Kf_var.set(format_value(Kf))
        mtt_var.set(format_value(mtt))
        att_var.set(format_value(att))
        updating = False
    except ValueError:
        # Handle error for invalid input
        updating = True
        Ei_var.set(format_value(0))
        Ef_var.set(format_value(0))
        Ki_var.set(format_value(0))
        Kf_var.set(format_value(0))
        mtt_var.set(format_value(0))
        att_var.set(format_value(0))
        updating = False
                
def update_mtt_from_Ei(Ei_var, mtt_var, Ki_var, monocris_info):
    global updating
    if updating:
        return
    Ei_str = Ei_var.get()
    if not is_valid_number(Ei_str):
        return
    updating = True
    Ei = float(Ei_str)
    Ki = energy2k(Ei)
    mtt = 2*k2angle(Ki, monocris_info['dm'])
    mtt_var.set(format_value(mtt))
    Ki_var.set(format_value(Ki))
    updating = False
    
def update_att_from_Ef(Ef_var, att_var, Kf_var, anacris_info):
    global updating
    if updating:
        return
    Ef_str = Ef_var.get()
    if not is_valid_number(Ef_str):
        return
    updating = True
    Ef = float(Ef_str)
    Kf = energy2k(Ef)
    att = 2*k2angle(Kf, anacris_info['da'])
    att_var.set(format_value(att))
    Kf_var.set(format_value(Kf))
    updating = False

def update_from_mtt(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        mtt = float(mtt_var.get())
        Ki = angle2k(mtt/2, monocris_info['dm'])
        Ei = k2energy(Ki)
        Ki_var.set(format_value(Ki))
        Ei_var.set(format_value(Ei))
        if K_fixed_var.get() == "Ki Fixed":
            fixed_E_var.set(format_value(Ei))
            Ef = Ei - float(deltaE_var.get())
            Kf = energy2k(Ef)
            att = 2*k2angle(Kf, anacris_info['da'])
            Ef_var.set(format_value(Ef))
            Kf_var.set(format_value(Kf))
            att_var.set(format_value(att))
        else: # Kf fixed
            deltaE = Ei - float(fixed_E_var.get())
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass

def update_from_att(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        att = float(att_var.get())
        Kf = angle2k(att/2, anacris_info['da'])
        Ef = k2energy(Kf)
        Kf_var.set(format_value(Kf))
        Ef_var.set(format_value(Ef))
        if K_fixed_var.get() == "Kf Fixed":
            fixed_E_var.set(format_value(Ef))
            Ei = Ef + float(deltaE_var.get())
            Ki = energy2k(Ei)
            mtt = 2*k2angle(Ki, monocris_info['dm'])
            Ei_var.set(format_value(Ei))
            Kf_var.set(format_value(Kf))
            mtt_var.set(format_value(mtt))
        else: # Ki fixed
            deltaE = float(fixed_E_var.get()) - Ef
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass
    
def update_from_Ki(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        Ki = float(Ki_var.get())
        mtt = 2*k2angle(Ki, monocris_info['dm'])
        Ei = k2energy(Ki)
        mtt_var.set(format_value(mtt))
        Ei_var.set(format_value(Ei))
        if K_fixed_var.get() == "Ki Fixed":
            fixed_E_var.set(format_value(Ei))
            Ef = Ei - float(deltaE_var.get())
            Kf = energy2k(Ef)
            att = 2*k2angle(Kf, anacris_info['da'])
            Ef_var.set(format_value(Ef))
            Kf_var.set(format_value(Kf))
            att_var.set(format_value(att))
        else: # Kf fixed
            deltaE = Ei - float(fixed_E_var.get())
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass

def update_from_Kf(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        Kf = float(Kf_var.get())
        att = 2*k2angle(Kf, anacris_info['da'])
        Ef = k2energy(Kf)
        att_var.set(format_value(att))
        Ef_var.set(format_value(Ef))
        if K_fixed_var.get() == "Kf Fixed":
            fixed_E_var.set(format_value(Ef))
            Ei = Ef + float(deltaE_var.get())
            Ki = energy2k(Ei)
            mtt = 2*k2angle(Ki, monocris_info['dm'])
            Ei_var.set(format_value(Ei))
            Kf_var.set(format_value(Kf))
            mtt_var.set(format_value(mtt))
        else: # Ki fixed
            deltaE = float(fixed_E_var.get()) - Ef
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass

def update_from_Ei(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        Ei = float(Ei_var.get())
        Ki = energy2k(Ei)
        mtt = 2*k2angle(Ki, monocris_info['dm'])
        Ki_var.set(format_value(Ki))
        mtt_var.set(format_value(mtt))
        if K_fixed_var.get() == "Ki Fixed":
            fixed_E_var.set(format_value(Ei))
            Ef = Ei - float(deltaE_var.get())
            Kf = energy2k(Ef)
            att = 2*k2angle(Kf, anacris_info['da'])
            Ef_var.set(format_value(Ef))
            Kf_var.set(format_value(Kf))
            att_var.set(format_value(att))
        else: # Kf fixed
            deltaE = Ei - float(fixed_E_var.get())
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass

def update_from_Ef(fixed_E_var, deltaE_var, K_fixed_var, Ei_var, Ef_var, Ki_var, Kf_var, mtt_var, att_var, monocris_info, anacris_info):
    try:
        Ef = float(Ef_var.get())
        att = 2*k2angle(Kf, anacris_info['da'])
        Kf = energy2k(Ef)
        att_var.set(format_value(att))
        Kf_var.set(format_value(Kf))
        if K_fixed_var.get() == "Kf Fixed":
            fixed_E_var.set(format_value(Ef))
            Ei = Ef + float(deltaE_var.get())
            Ki = energy2k(Ei)
            mtt = 2*k2angle(Ki, monocris_info['dm'])
            Ei_var.set(format_value(Ei))
            Kf_var.set(format_value(Kf))
            mtt_var.set(format_value(mtt))
        else: # Ki fixed
            deltaE = float(fixed_E_var.get()) - Ef
            deltaE_var.set(format_value(deltaE))
    except ValueError:
        pass

def update_HKL_from_Q(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var):
    # Convert angles from degrees to radians
    alpha = math.radians(lattice_alpha_var.get())
    beta = math.radians(lattice_beta_var.get())
    gamma = math.radians(lattice_gamma_var.get())
    
    # Get the real-space lattice parameters (a, b, c)
    a = lattice_a_var.get()
    b = lattice_b_var.get()
    c = lattice_c_var.get()
    
    # Compute the unit cell volume (V_cell)
    V_cell = a * b * c * math.sqrt(
        1 - math.cos(alpha)**2 - math.cos(beta)**2 - math.cos(gamma)**2 +
        2 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
    )
    
    if V_cell <= 0:
        raise ValueError("Invalid lattice parameters: Unit cell volume is zero or negative.")
    
    # Reciprocal lattice vectors
    b1 = np.array([
        2 * math.pi * b * c * math.sin(alpha) / V_cell,
        0,
        0
    ])
    b2 = np.array([
        2 * math.pi * c * math.cos(beta) / V_cell,
        2 * math.pi * a * c * math.sin(beta) / V_cell,
        0
    ])
    b3 = np.array([
        2 * math.pi * a * b * math.sin(gamma) / V_cell,
        2 * math.pi * b * math.cos(alpha) / V_cell,
        2 * math.pi * c / V_cell
    ])
    
    # Assemble the reciprocal lattice matrix
    reciprocal_matrix = np.array([b1, b2, b3]).T
    
    # The momentum transfer vector
    q_vector = np.array([qx_var.get(), qy_var.get(), qz_var.get()])
    
    # Solve for H, K, L
    try:
        HKL = np.linalg.solve(reciprocal_matrix, q_vector)
    except np.linalg.LinAlgError:
        raise ValueError("Matrix inversion failed. Check lattice parameters and input data.")
    
    # Assign the result to the corresponding lattice variables
    lattice_H_var.set(HKL[0])
    lattice_K_var.set(HKL[1])
    lattice_L_var.set(HKL[2])

def update_Q_from_HKL(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var):
    # Convert angles from degrees to radians
    alpha = math.radians(float(lattice_alpha_var.get()))
    beta = math.radians(float(lattice_beta_var.get()))
    gamma = math.radians(float(lattice_gamma_var.get()))
    
    # Get the real-space lattice parameters (a, b, c)
    a = float(lattice_a_var.get())
    b = float(lattice_b_var.get())
    c = float(lattice_c_var.get())
    
    # Compute the unit cell volume (V_cell)
    V_cell = a * b * c * math.sqrt(
        1 - math.cos(alpha)**2 - math.cos(beta)**2 - math.cos(gamma)**2 +
        2 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
    )
    
    if V_cell <= 0:
        raise ValueError("Invalid lattice parameters: Unit cell volume is zero or negative.")
    
    # Reciprocal lattice vectors
    b1 = np.array([
        2 * math.pi * b * c * math.sin(alpha) / V_cell,
        0,
        0
    ])
    b2 = np.array([
        2 * math.pi * c * math.cos(beta) / V_cell,
        2 * math.pi * a * c * math.sin(beta) / V_cell,
        0
    ])
    b3 = np.array([
        2 * math.pi * a * b * math.sin(gamma) / V_cell,
        2 * math.pi * b * math.cos(alpha) / V_cell,
        2 * math.pi * c / V_cell
    ])
    
    # Assemble the reciprocal lattice matrix
    reciprocal_matrix = np.array([b1, b2, b3]).T
    
    # Get H, K, L values and convert to float
    H = float(lattice_H_var.get())
    K = float(lattice_K_var.get())
    L = float(lattice_L_var.get())
    HKL = np.array([H, K, L])
    
    # Compute qx, qy, qz
    q_vector = reciprocal_matrix @ HKL  # Matrix-vector multiplication
    
    # Assign the result to the corresponding variables
    qx_var.set(q_vector[0])
    qy_var.set(q_vector[1])
    qz_var.set(q_vector[2])

def update_angles_from_Q(mtt_var, stt_var, sth_var, saz_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var):
    #angles_array = [mtt, stt, sth, saz, att]
    angles_array = [0,0,0,0,0]
    qx = float(qx_var.get())
    qy = float(qy_var.get())
    qz = float(qz_var.get())
    deltaE = float(deltaE_var.get())
    fixed_E = float(fixed_E_var.get())
    K_fixed = K_fixed_var.get()
    monocris = monocris_var.get()
    anacris = anacris_var.get()
    print(qx, qy, qz, deltaE, fixed_E, K_fixed, monocris, anacris)

    puma_instance = PUMA_Instrument()
    angles_array, error_flags = puma_instance.calculate_angles(qx, qy, qz, deltaE, fixed_E, K_fixed, monocris, anacris)
    if not error_flags:
        mtt_var.set(round(angles_array[0],4))
        stt_var.set(round(angles_array[1],4))
        sth_var.set(round(angles_array[2],4))
        #saz_var.set(round(angles_array[3],4))
        att_var.set(round(angles_array[4],4))

def update_Q_from_angles(mtt_var, stt_var, sth_var, att_var, qx_var, qy_var, qz_var, deltaE_var, fixed_E_var, K_fixed_var, monocris_var, anacris_var):
    """Updates qx, qy, qz, and deltaE based on the instrument angles and scattering parameters."""
    # Retrieve angle and parameter values
    mtt = float(mtt_var.get())
    stt = float(stt_var.get())
    sth = float(sth_var.get())
    saz = 0 # set to 0 right now
    att = float(att_var.get())
    fixed_E = float(fixed_E_var.get())
    K_fixed = K_fixed_var.get()
    monocris = monocris_var.get()
    anacris = anacris_var.get()

    print(mtt, stt, sth, saz, att, fixed_E, K_fixed, monocris, anacris)

    # Create PUMA instrument instance
    puma_instance = PUMA_Instrument()

    # Calculate Q and deltaE from the angles
    q_array, error_flags = puma_instance.calculate_q_and_deltaE(
        mtt, stt, sth, saz, att, fixed_E, K_fixed, monocris, anacris
    )

    if not error_flags:
        # Update Q and deltaE variables
        qx_var.set(round(q_array[0],3))
        qy_var.set(round(q_array[1],3))
        qz_var.set(round(q_array[2],3))
        deltaE_var.set(round(q_array[3],3))
    else:
        print(f"Errors encountered during calculation: {error_flags}")