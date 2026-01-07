import math

def update_Q_from_HKL(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var):
    """
    Updates qx, qy, and qz based on H, K, L and lattice parameters.
    """
    try:
        H = float(lattice_H_var.get())
        K = float(lattice_K_var.get())
        L = float(lattice_L_var.get())
        a = float(lattice_a_var.get())
        b = float(lattice_b_var.get())
        c = float(lattice_c_var.get())
        alpha = float(lattice_alpha_var.get())
        beta = float(lattice_beta_var.get())
        gamma = float(lattice_gamma_var.get())

        # Convert lattice parameters to radians
        alpha_rad = math.radians(alpha)
        beta_rad = math.radians(beta)
        gamma_rad = math.radians(gamma)

        # Calculate reciprocal lattice parameters
        V = a * b * c * math.sqrt(1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad))
        a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
        b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
        c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
        alpha_star = math.degrees(math.acos((math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) / (math.sin(beta_rad) * math.sin(gamma_rad))))
        beta_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) / (math.sin(alpha_rad) * math.sin(gamma_rad))))
        gamma_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) / (math.sin(alpha_rad) * math.sin(beta_rad))))

        # Convert HKL to qx, qy, qz
        qx = H * a_star + K * b_star * math.cos(gamma_star) + L * c_star * math.cos(beta_star)
        qy = K * b_star * math.sin(gamma_star) + L * c_star * (math.cos(alpha_star) - math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)
        qz = L * c_star * math.sqrt(1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 - math.cos(gamma_star)**2 + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)

        qx_var.set(qx)
        qy_var.set(qy)
        qz_var.set(qz)

    except ValueError:
        print("Error: Invalid input for H, K, L or lattice parameters.")
        return

def update_HKL_from_Q(qx_var, qy_var, qz_var, lattice_a_var, lattice_b_var, lattice_c_var, lattice_alpha_var, lattice_beta_var, lattice_gamma_var, lattice_H_var, lattice_K_var, lattice_L_var):
    """
    Updates H, K, and L based on qx, qy, qz and lattice parameters.
    """
    try:
        qx = float(qx_var.get())
        qy = float(qy_var.get())
        qz = float(qz_var.get())
        a = float(lattice_a_var.get())
        b = float(lattice_b_var.get())
        c = float(lattice_c_var.get())
        alpha = float(lattice_alpha_var.get())
        beta = float(lattice_beta_var.get())
        gamma = float(lattice_gamma_var.get())

        # Convert lattice parameters to radians
        alpha_rad = math.radians(alpha)
        beta_rad = math.radians(beta)
        gamma_rad = math.radians(gamma)

        # Calculate reciprocal lattice parameters
        V = a * b * c * math.sqrt(1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad))
        a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
        b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
        c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
        alpha_star = math.degrees(math.acos((math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) / (math.sin(beta_rad) * math.sin(gamma_rad))))
        beta_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) / (math.sin(alpha_rad) * math.sin(gamma_rad))))
        gamma_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) / (math.sin(alpha_rad) * math.sin(beta_rad))))

        # Calculate H, K, L from qx, qy, qz (inverse transformation)
        H = (qx - K * b_star * math.cos(gamma_star) - L * c_star * math.cos(beta_star)) / a_star
        K = (qy - L * c_star * (math.cos(alpha_star) - math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)) / (b_star * math.sin(gamma_star))
        L = qz * math.sin(gamma_star) / (c_star * math.sqrt(1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 - math.cos(gamma_star)**2 + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)))

        lattice_H_var.set(H)
        lattice_K_var.set(K)
        lattice_L_var.set(L)

    except ValueError:
        print("Error: Invalid input for qx, qy, qz or lattice parameters.")
        return
    except ZeroDivisionError:
        print("Error: ZeroDivisionError encountered. Check lattice parameters.")
        return

def update_Q_from_HKL_direct(H, K, L, a, b, c, alpha, beta, gamma):
    """
    Directly converts HKL values to qx, qy, qz without using GUI elements.
    """
    # Convert lattice parameters to radians
    alpha_rad = math.radians(alpha)
    beta_rad = math.radians(beta)
    gamma_rad = math.radians(gamma)

    # Calculate reciprocal lattice parameters
    V = a * b * c * math.sqrt(1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad))
    a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
    b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
    c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
    alpha_star = math.degrees(math.acos((math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) / (math.sin(beta_rad) * math.sin(gamma_rad))))
    beta_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) / (math.sin(alpha_rad) * math.sin(gamma_rad))))
    gamma_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) / (math.sin(alpha_rad) * math.sin(beta_rad))))

    # Convert HKL to qx, qy, qz
    H = float(H)
    K = float(K)
    L = float(L)
    qx = H * a_star + K * b_star * math.cos(gamma_star) + L * c_star * math.cos(beta_star)
    qy = K * b_star * math.sin(gamma_star) + L * c_star * (math.cos(alpha_star) - math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)
    qz = L * c_star * math.sqrt(1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 - math.cos(gamma_star)**2 + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)

    return qx, qy, qz

def update_HKL_from_Q_direct(qx, qy, qz, a, b, c, alpha, beta, gamma):
    """
    Directly converts qx, qy, qz values to H, K, L without using GUI elements.
    """
    # Convert lattice parameters to radians
    alpha_rad = math.radians(alpha)
    beta_rad = math.radians(beta)
    gamma_rad = math.radians(gamma)

    # Calculate reciprocal lattice parameters
    V = a * b * c * math.sqrt(1 - math.cos(alpha_rad)**2 - math.cos(beta_rad)**2 - math.cos(gamma_rad)**2 + 2 * math.cos(alpha_rad) * math.cos(beta_rad) * math.cos(gamma_rad))
    a_star = 2 * math.pi * b * c * math.sin(alpha_rad) / V
    b_star = 2 * math.pi * a * c * math.sin(beta_rad) / V
    c_star = 2 * math.pi * a * b * math.sin(gamma_rad) / V
    alpha_star = math.degrees(math.acos((math.cos(beta_rad) * math.cos(gamma_rad) - math.cos(alpha_rad)) / (math.sin(beta_rad) * math.sin(gamma_rad))))
    beta_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(gamma_rad) - math.cos(beta_rad)) / (math.sin(alpha_rad) * math.sin(gamma_rad))))
    gamma_star = math.degrees(math.acos((math.cos(alpha_rad) * math.cos(beta_rad) - math.cos(gamma_rad)) / (math.sin(alpha_rad) * math.sin(beta_rad))))

    # Calculate H, K, L from qx, qy, qz (inverse transformation)
    H = (qx - K * b_star * math.cos(gamma_star) - L * c_star * math.cos(beta_star)) / a_star
    K = (qy - L * c_star * (math.cos(alpha_star) - math.cos(beta_star) * math.cos(gamma_star)) / math.sin(gamma_star)) / (b_star * math.sin(gamma_star))
    L = qz * math.sin(gamma_star) / (c_star * math.sqrt(1 - math.cos(alpha_star)**2 - math.cos(beta_star)**2 - math.cos(gamma_star)**2 + 2 * math.cos(alpha_star) * math.cos(beta_star) * math.cos(gamma_star)))

    return H, K, L

## TODO: A function to take abc coordinates and build rlu 

## TODO: A function to take space group and return Bragg peaks for a Bragg peak function