"""Instrument-independent neutron unit conversions (energy, momentum, Bragg angle).

Moved verbatim from the former PUMA definition module (Phase 1 of
``docs/CONFIGURABLE_INSTRUMENTS.md`` §17.2): these are pure Bragg / de-Broglie
relations that take crystal d-spacing as an argument, so they belong with the
general physics helpers in ``tavi/``. The PUMA module re-exports them so existing
import paths keep working.
"""
import math

import numpy as np

N_MASS = 1.67492749804e-27 # neutron mass
E_CHARGE = 1.602176634e-19 # electron charge
K_B = 0.08617333262 # Boltzmann's constant in meV/K
HBAR_meV = 6.582119569e-13 # H-bar in meV*s
HBAR = 1.05459e-34  #H-bar in J*s

##  some functions to convert between energies, angles and momenta ##
def k2angle(k, d):
    """Converts a k value to a Bragg scattering 2-theta angle"""
    if 2*math.pi/(2*k*d)<-1 or 2*math.pi/(2*k*d)>1: #check if the angle is valid
        return(math.inf)
    else:
        return(math.degrees(math.asin(2*math.pi/(2*k*d))))

def angle2k(angle, d):
    """Converts a Bragg scattering 2-theta angle to a k value"""
    if d*math.sin(math.radians(angle)) != 0:
        return(abs(math.pi/(d*math.sin(math.radians(angle)))))
    else:
        return(0)

# neutron momentum, in A/s, is converted to meV
def k2energy(k):
    """Converts a momentum k in A/s to energy in meV"""
    return(1e3*math.pow((k * 1e10 * HBAR), 2) / (2 * N_MASS * E_CHARGE))

def energy2k(energy):
    """Converts an energy in meV to a momentum k in A/s"""
    return(np.sqrt(energy * 1e-3 * E_CHARGE * 2 * N_MASS) * 1e-10/HBAR)

def energy2lambda(energy):
    """Converts an energy in meV to a wavelength lambda in A"""
    return(9.044567/math.sqrt(energy))
