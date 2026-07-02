import copy
import mcstasscript as ms
import math
import numpy as np
import os
import subprocess

from instruments.contract import PointSnapshot, RunExecutionState
from tavi.mcstas_config import resolve_mpi_launcher_argv
from tavi.sample_mount import SampleMount
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    q_instrument_from_angles,
    solve_instrument_angles,
)

N_MASS = 1.67492749804e-27 # neutron mass
E_CHARGE = 1.602176634e-19 # electron charge
K_B = 0.08617333262 # Boltzmann's constant in meV/K
HBAR_meV = 6.582119569e-13 # H-bar in meV*s
HBAR = 1.05459e-34  #H-bar in J*s

# Get the directory containing this module, then find the components folder
_module_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_module_dir)  # Go up one level from instruments/
data_dir = os.path.join(_project_dir, "components")

# McStas instrument name: drives the generated .instr/.c/.exe filenames and must
# match the descriptor's mcstas_name (instruments/puma_plugin.py).
MCSTAS_NAME = "PUMA_McScript"


# Energy/angle/momentum conversions live in tavi.neutron_conversions; re-exported
# here so existing `from instruments.PUMA_instrument_definition import ...` works.
from tavi.neutron_conversions import (  # noqa: F401  (re-export)
    angle2k,
    energy2k,
    energy2lambda,
    k2angle,
    k2energy,
)

def _crystal_spec_to_info(spec, d_key):
    """Legacy crystal-info dict from a descriptor CrystalSpec.

    ``reflect``/``transmit`` carry embedded quotes because they are emitted
    verbatim as McStas string literals by build().
    """
    return {
        d_key: spec.d_spacing,
        'slabwidth': spec.slab_width,
        'slabheight': spec.slab_height,
        'ncolumns': spec.n_columns,
        'nrows': spec.n_rows,
        'gap': spec.gap,
        'mosaic': spec.mosaic,
        'r0': spec.r0,
        'reflect': f'"{spec.reflect_file}"',
        'transmit': f'"{spec.transmit_file}"',
    }


def _find_crystal_spec(specs, crystal_id):
    for spec in specs:
        if spec.id == crystal_id:
            return spec
    return None


def mono_ana_crystals_setup(monocris, anacris):
    """Crystal parameter dicts for the mono/analyzer, sourced from the descriptor.

    The descriptor (instruments/puma_plugin.py) is the single source of truth for
    crystal data; lookups are by CrystalSpec id ("pg002"). Unknown ids return
    empty dicts.
    """
    from instruments.puma_plugin import puma_descriptor

    descriptor = puma_descriptor()
    mono_spec = _find_crystal_spec(descriptor.mono_crystals, monocris)
    ana_spec = _find_crystal_spec(descriptor.ana_crystals, anacris)
    monochromator_info = _crystal_spec_to_info(mono_spec, 'dm') if mono_spec else {}
    analyzer_info = _crystal_spec_to_info(ana_spec, 'da') if ana_spec else {}
    return monochromator_info, analyzer_info

## This function adds a Union material with incoherent scattering and powder lines
def add_union_powder(name, data_name, sigma_inc, sigma_abs, unit_V, instr):
    material_incoherent = instr.add_component(name + "_inc", "Incoherent_process")
    material_incoherent.sigma = sigma_inc
    material_incoherent.unit_cell_volume = unit_V
    material_powder = instr.add_component(name + "_pow", "Powder_process")
    material_powder.reflections = '"' + data_name + '"'  # Need quotes when describing a filename
    material = instr.add_component(name, "Union_make_material")
    material.my_absorption = 100*sigma_abs/unit_V
    material.process_string = '"' + name + "_inc," + name + "_pow" + '"'

# The TAS class is a general tool for any TAS instrument
class TAS_Instrument:
    """The general setup of a triple-axes spectrometer (TAS) instrument, with useful functions for setting the geometries."""
    def __init__(self, L1=1.0, L2=1.0, L3=1.0, L4=1.0, A1=0, A2=0, A3=0, A4=0, saz=0, **kwargs):
        self.parameters = kwargs
        self.L1 = L1 # source-mono arm length
        self.L2 = L2 # mono-sample arm length
        self.L3 = L3 # sample-ana arm length
        self.L4 = L4 # ana-det arm length
        self.A1 = A1 # mono two-theta angle
        self.A2 = A2 # sample two-theta angle (phi)
        self.A3 = A3 # sample theta angle (psi)
        self.A4 = A4 # ana two-theta angle
        self.saz = saz # sample z-angle
        # Sample orientation angles (user-controllable)
        self.omega = 0  # in-plane sample rotation (about vertical Y axis) - actual instrument angle
        self.chi = 0    # static out-of-plane sample orientation offset
        # Sample alignment offsets (user-controllable)
        self.psi = 0    # omega alignment offset (in-plane) - set during alignment
        self.kappa = 0  # chi alignment offset (out-of-plane) - set during alignment
        # Hidden misalignment angles (for training exercises)
        self.mis_omega = 0  # hidden misalignment in omega (in-plane)
        self.mis_chi = 0    # hidden misalignment in chi (out-of-plane)
        self.K_fixed = "Ki_fixed" # working in Ki- or Kf-fixed mode
        self.monocris = None # must have some monochromator crystal
        self.anacris = None # must have some analyzer crystal
        self.fixed_E = 0 # The fixed energy to work with, for the source.
        self.sample_mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90)
 
    def set_parameters(self, **kwargs):
        """Method to set general parameters."""
        for key, value in kwargs.items():
            if key in self.parameters:
                self.parameters[key] = value
            else:
                print(f"Parameter '{key}' not found.")
    
    def set_angles(self, A1=None, A2=None, A3=None, A4=None, omega=None, chi=None, kappa=None, psi=None):
        """Method to set A1-A4 angles and sample orientation angles."""
        if A1 is not None:
            self.A1 = A1
        if A2 is not None:
            self.A2 = A2
        if A3 is not None:
            self.A3 = A3
        if A4 is not None:
            self.A4 = A4
        if omega is not None:
            self.omega = omega
        if chi is not None:
            self.chi = chi
        if kappa is not None:
            self.kappa = kappa
        if psi is not None:
            self.psi = psi
    
    def set_misalignment(self, mis_omega=None, mis_chi=None):
        """Method to set hidden misalignment angles for training exercises.
        
        Args:
            mis_omega: In-plane misalignment angle (degrees) - corrected by psi offset
            mis_chi: Out-of-plane misalignment angle (degrees) - corrected by kappa offset
        """
        if mis_omega is not None:
            self.mis_omega = mis_omega
        if mis_chi is not None:
            self.mis_chi = mis_chi
    
    def get_effective_sample_angles(self):
        """Return effective sample angle OFFSETS (not including calculated A3).
        
        The total in-plane rotation is: A3 (calculated) + psi (offset) + mis_omega
        The total out-of-plane tilt is: chi + kappa (offset) + mis_chi
        
        Note: omega is NOT added here because omega IS the calculated A3 (just displayed).
        
        Returns:
            tuple: (effective_omega_offset, effective_chi) for backwards compatibility
        """
        # Effective in-plane OFFSET: psi offset + omega misalignment (added to calculated A3)
        effective_omega_offset = self.psi + self.mis_omega
        # Effective out-of-plane tilt: chi + kappa offset + chi misalignment
        effective_chi = self.chi + self.kappa + self.mis_chi
        return effective_omega_offset, effective_chi
    
    def get_sample_angle_components(self):
        """Return all individual sample angle components for clear tracking.
        
        This method provides explicit access to each angle component separately,
        making it easier to understand how each angle contributes to the final
        sample orientation in the instrument.
        
        Returns:
            dict: Dictionary containing all individual angle components:
                - 'omega': Sample rotation angle (in-plane, user-controllable)
                - 'chi': Sample tilt angle (out-of-plane, user-controllable)
                - 'psi': Omega alignment offset (in-plane, set during alignment)
                - 'kappa': Chi alignment offset (out-of-plane, set during alignment)
                - 'mis_omega': Hidden omega misalignment (in-plane, for training)
                - 'mis_chi': Hidden chi misalignment (out-of-plane, for training)
                - 'effective_omega_offset': Combined in-plane offset (psi + mis_omega)
                - 'effective_chi': Combined out-of-plane tilt (chi + kappa + mis_chi)
        """
        effective_omega_offset = self.psi + self.mis_omega
        effective_chi = self.chi + self.kappa + self.mis_chi
        
        return {
            'omega': self.omega,
            'chi': self.chi,
            'psi': self.psi,
            'kappa': self.kappa,
            'mis_omega': self.mis_omega,
            'mis_chi': self.mis_chi,
            'effective_omega_offset': effective_omega_offset,
            'effective_chi': effective_chi,
        }
            
    def set_crystal_bending(self, rhm=None, rvm=None, rha=None, rva=None):
        """Method to set rhm, rvm, rha, and rva values."""
        if rhm is not None:
            self.rhm = rhm
        if rvm is not None:
            self.rvm = rvm
        if rha is not None:
            self.rha = rha
        if rva is not None:
            self.rva = rva

    def calculate_angles(self, qx, qy, qz, deltaE, fixed_E, K_fixed, monocris, anacris):
        """Sets up the mono-sample-analyzer-detector angles based on the scattering parameters"""
        error_flags = []
        
        # Check for zero momentum transfer early to avoid division by zero
        if qx == 0 and qy == 0 and qz == 0:
            print("\nInvalid: zero momentum transfer (qx=qy=qz=0)")
            error_flags.append("zero_q")
            return [0, 0, 0, 0, 0], error_flags
        
        # Retrieve mono/ana crystal information
        monochromator_info, analyzer_info = mono_ana_crystals_setup(monocris, anacris)
         
        # pre-calculate values from parameters
        q = math.sqrt(qx**2 + qy**2 + qz**2)

        K = energy2k(fixed_E)

        if K_fixed == "Ki Fixed":
            mtt = 2 * k2angle(K, monochromator_info['dm'])
            Ei = fixed_E
            ki = energy2k(Ei)
            Ef = Ei - deltaE
            kf = energy2k(Ef)
            att = 2 * k2angle(kf, analyzer_info['da'])
            if mtt == math.inf:
                print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
                error_flags.append("mtt")
            if att == math.inf:
                print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
                error_flags.append("att")
        elif K_fixed == "Kf Fixed":
            att = 2 * k2angle(K, analyzer_info['da'])
            Ef = fixed_E
            kf = energy2k(Ef)
            Ei = Ef + deltaE
            ki = energy2k(Ei)
            mtt = 2 * k2angle(ki, monochromator_info['dm'])
            if mtt == math.inf:
                print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
                error_flags.append("mtt")
            if att == math.inf:
                print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
                error_flags.append("att")

        try:
            sample_angles = solve_instrument_angles(np.array([qx, qy, qz], dtype=float), ki, kf)
            stt = sample_angles.stt
        except ValueError as exc:
            print("\nSample two theta angle invalid")
            stt = 0
            error_flags.append("stt")
            sample_angles = None

        if "stt" in error_flags:
            print("\nCannot compute sample theta angle as sample two theta angle invalid")
            sth = 0
            saz = 0
        else:
            sth = sample_angles.sth
            saz = sample_angles.saz


        print(f"\nmtt: {mtt:.2f} ki: {ki:.3f} Ei: {Ei:.3f} stt: {stt:.3f} sth: {sth:.3f} saz: {saz:.3f} Q: {q:.2f} kf: {kf:.3f} Ef: {Ef:.3f} att: {att:.2f}")
    
        angles_array = [mtt, stt, sth, saz, att]
        return(angles_array, error_flags)

    def calculate_q_and_deltaE(self, mtt, stt, sth, saz, att, fixed_E, K_fixed, monocris, anacris):
        """Computes qx, qy, qz, and deltaE based on the given angles and fixed energy configuration"""
        error_flags = []

        # Retrieve mono/ana crystal information
        monochromator_info, analyzer_info = mono_ana_crystals_setup(monocris, anacris)

        # Calculate incident and scattered wavevectors based on the fixed energy
        if K_fixed == "Ki Fixed":
            ki = energy2k(fixed_E)
            Ei = fixed_E
            kf = angle2k(att / 2, analyzer_info['da'])  # Compute scattered wavevector from analyzer angle
            Ef = k2energy(kf)
            deltaE = Ei - Ef
        elif K_fixed == "Kf Fixed":
            kf = energy2k(fixed_E)
            Ef = fixed_E
            ki = angle2k(mtt / 2, monochromator_info['dm'])  # Compute incident wavevector from monochromator angle
            Ei = k2energy(ki)
            deltaE = Ei - Ef
        else:
            error_flags.append("K_fixed")
            print("Invalid K_fixed value")
            return [0, 0, 0, 0], error_flags

        # Compute Q in the public instrument/GUI convention:
        # qx and qy span the horizontal scattering plane; qz is vertical.
        try:
            qx, qy, qz = q_instrument_from_angles(sth, saz, stt, ki, kf)
        except Exception as exc:
            error_flags.append("q")
            print(f"Invalid Q from sample angles: {exc}")
            qx = qy = qz = 0.0

        # Validate Q magnitude
        q = math.sqrt(qx**2 + qy**2 + qz**2)
        if q <= 0:
            error_flags.append("q")
            print("Invalid Q magnitude")

        # Debugging output
        print(f"\nqx: {qx:.3f}, qy: {qy:.3f}, qz: {qz:.3f}, deltaE: {deltaE:.3f}, Q: {q:.3f}")
    
        return [qx, qy, qz, deltaE], error_flags
    
    
class PUMA_Instrument(TAS_Instrument):
    """All the specific settings for the PUMA TAS instrument are initialized here, with geometries hard-coded and
    instrument-specific parameters functions defined."""
    def __init__(self, diagnostic_mode=False, diagnostic_settings=None):
        super().__init__()
        self.L1 = 2.150  # source-mono
        self.L2 = 2.290  # mono-sample # this includes the 0.2 m pull-out of the sample table for the NMO
        self.L3 = 0.880  # sample-ana
        self.L4 = 0.750  # ana-det
        self.hbl_vgap = 150e-3
        self.hbl_hgap = 78e-3
        self.vbl_hgap = 88e-3
        self.pbl_voffset = 0
        self.pbl_vgap = 100e-3
        self.pbl_hoffset = 0
        self.pbl_hgap = 100e-3
        self.dbl_hgap = 50e-3
        self.alpha_1 = 0 # source-mono collimation
        self.alpha_2 = [] # mono-sample collimation # note that there are multiple options available in series!
        self.alpha_3 = 0 # sample-ana collimation
        self.alpha_4 = 0 # ana-det collimation
        self.rhmfac = 1 # monochromator mirror radius of curvature factor - horizontal
        self.rvmfac = 1 # monochromator mirror radius of curvature factor - vertical
        self.rhafac = 1 # analyzer mirror radius of curvature factor - horizontal
        self.rhm = 0  # monochromator mirror radius of curvature - horizontal
        self.rvm = 0 # monochromator mirror radius of curvature - vertical
        self.rha = 0 # analyzer mirror radius of curvature - horizontal
        self.rva = 0 # analyzer mirror radius of curvature - vertical
        self.NMO_installed = "None"
        self.V_selector_installed = False
        self.source_type = "Maxwellian"  # "Mono" or "Maxwellian"
        self.source_dE = 2  # Energy half-spread for Mono source (meV)
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_settings = diagnostic_settings if diagnostic_settings else {}

    def activate_diagnostic_mode(self):
        """Activate diagnostic mode and display relevant settings."""
        if self.diagnostic_mode:
            print("Diagnostic Mode Activated!")
            self.display_diagnostic_settings()

    def update_diagnostic_settings(self, settings):
        """Update the diagnostic settings."""
        self.diagnostic_settings.update(settings)

    def display_diagnostic_settings(self):
        """Display the diagnostic settings."""
        if self.diagnostic_settings:
            print("Diagnostic Settings:")
            for key, value in self.diagnostic_settings.items():
                print(f"{key}: {value}")
        else:
            print("No diagnostic settings provided.")
        
    def calculate_crystal_bending(self, rhmfac, rvmfac, rhafac, mth, ath):
        """Calculates the required bending for the monochromator and analyzer crystals based on their angles of rotation and the arm distances.
        
        Parameters:
            mth: Monochromator theta angle (Bragg angle = A1/2, NOT the 2-theta)
            ath: Analyzer theta angle (Bragg angle = A4/2, NOT the 2-theta)
            
        Note: The formulas follow McStas Monochromator_curved convention:
            RV = 2*L*sin(theta) and RH = 2*L/sin(theta)
        
        For monochromator: Uses parallel beam formula (L = L2 only) since the 
        neutron guide produces a quasi-parallel beam (source effectively at infinity).
        
        For analyzer: Uses point-source formula with L = 1/(1/L3 + 1/L4) since
        the sample is a real point source.
        """
        # Monochromator: parallel beam formula (source at infinity from guide)
        # RH = 2*L2/sin(theta), RV = 2*L2*sin(theta)
        rhm = rhmfac * 2 * self.L2 / math.sin(math.radians(mth))
        rvm = rvmfac * 2 * self.L2 * math.sin(math.radians(mth))
        
        # Analyzer: point-source formula (sample is real source)
        # RH = 2/sin(theta)/(1/L3 + 1/L4), RV = 2*sin(theta)/(1/L3 + 1/L4)
        rha = rhafac * 2 / math.sin(math.radians(ath)) / (1/self.L3 + 1/self.L4)
        rva = 0.8 # Said to be fixed at 0.8 m

        print(f"\nrhm: {rhm:.2f} rvm: {rvm:.2f} rha: {rha:.2f} rva: {rva:.2f}")

        if rhm < 2.0 and rhmfac != 0:
            print("\nRequested Rh (mono) is {:.2f} m, but minimum Rh is 2.0 m".format(rhm))
            rhm = 2.0

        if rvm < 0.5 and rvmfac != 0:
            print("\nRequested Rv (mono) is {:.2f} m, but minimum Rv is 0.5 m".format(rvm))
            rvm = 0.5

        if rha < 2.0:
            print(f"\nRequested Rh (ana) is {rha:.2f} m, but minimum Rh is 2.0 m")
            rha = 2.0

        return rhm, rvm, rha, rva



def _get_E0_param_value(PUMA, deltaE):
    """Return the runtime source-energy parameter for the current point."""
    if PUMA.source_type == "Mono":
        if PUMA.K_fixed == "Kf Fixed":
            return PUMA.fixed_E + deltaE
        return PUMA.fixed_E

    return PUMA.fixed_E


def _get_v_selector_frequency(PUMA, deltaE):
    """Return the runtime velocity-selector frequency for the current point."""
    selector_alpha_rad = math.radians(48.3)
    selector_length = 0.25
    if PUMA.K_fixed == "Ki Fixed":
        selector_energy = PUMA.fixed_E
    else:
        selector_energy = PUMA.fixed_E + deltaE

    selector_energy = max(selector_energy, 1e-9)
    return 3956 * selector_alpha_rad / 2 / math.pi / selector_length / energy2lambda(selector_energy)


def _get_point_energy_metadata(PUMA, deltaE):
    """Return the per-point energy values recorded with the scan output."""
    if PUMA.source_type == "Mono":
        if PUMA.K_fixed == "Kf Fixed":
            E0_param = PUMA.fixed_E + deltaE
            Ei = E0_param
            Ki = energy2k(Ei)
            Ef = PUMA.fixed_E
            Kf = energy2k(Ef)
        else:
            E0_param = PUMA.fixed_E
            Ei = PUMA.fixed_E
            Ki = energy2k(Ei)
            Ef = PUMA.fixed_E - deltaE
            Kf = energy2k(max(Ef, 1e-9))
    else:
        E0_param = PUMA.fixed_E
        Ei = PUMA.fixed_E
        Ki = energy2k(Ei)
        Ef = PUMA.fixed_E - deltaE
        Kf = energy2k(max(Ef, 1e-9))

    return {
        "E0_param": E0_param,
        "Ei": Ei,
        "Ki": Ki,
        "Ef": Ef,
        "Kf": Kf,
    }


def build_puma_point_params(PUMA, deltaE):
    """Build the runtime parameter snapshot for one instrument point."""
    sample_angles = PUMA.get_sample_angle_components()
    mount_rx, mount_ry, mount_rz = PUMA.sample_mount.mount_euler_deg
    return {
        "A1_param": PUMA.A1,
        "A2_param": PUMA.A2,
        "A3_param": PUMA.A3,
        "A4_param": PUMA.A4,
        "E0_param": _get_E0_param_value(PUMA, deltaE),
        "nu_param": _get_v_selector_frequency(PUMA, deltaE),
        "saz_param": PUMA.saz,
        "rhm_param": PUMA.rhm,
        "rvm_param": PUMA.rvm,
        "rha_param": PUMA.rha,
        "rva_param": PUMA.rva,
        "vbl_hgap_param": PUMA.vbl_hgap,
        "pbl_hgap_param": PUMA.pbl_hgap,
        "pbl_vgap_param": PUMA.pbl_vgap,
        "dbl_hgap_param": PUMA.dbl_hgap,
        "chi_param": sample_angles["chi"],
        "kappa_param": sample_angles["kappa"],
        "mis_chi_param": sample_angles["mis_chi"],
        "psi_param": sample_angles["psi"],
        "mis_omega_param": sample_angles["mis_omega"],
        "chi_total": sample_angles["effective_chi"],
        "omega_offset_total": sample_angles["effective_omega_offset"],
        "mount_rx_param": mount_rx,
        "mount_ry_param": mount_ry,
        "mount_rz_param": mount_rz,
    }


def compute_scan_snapshot(scan_item, scan_index, scan_mode, puma, vals, data_folder,
                          is_2d_scan=False, variable_name1="", variable_name2="",
                          scan_command1="", scan_command2=""):
    """Compute the complete runtime snapshot for one scan point."""
    point_puma = copy.deepcopy(puma)

    if is_2d_scan:
        scans, idx_x, idx_y = scan_item
        idx_1d = -1
    else:
        scans, idx_1d = scan_item
        idx_x, idx_y = -1, -1

    if len(scans) < 11:
        raise ValueError(
            f"Scan item for scan_index {scan_index} in mode {scan_mode} has {len(scans)} values; expected at least 11."
        )

    error_flags = []
    qx = qy = qz = None
    H = K = L = None
    deltaE = 0.0
    mtt = stt = sth = att = saz = 0.0

    if scan_mode == "momentum":
        qx, qy, qz, deltaE = scans[:4]
        angles_array, error_flags = point_puma.calculate_angles(
            qx, qy, qz, deltaE, point_puma.fixed_E, point_puma.K_fixed,
            point_puma.monocris, point_puma.anacris
        )
        if not error_flags:
            mtt, stt, sth, saz, att = angles_array
            point_puma.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
    elif scan_mode == "rlu":
        H, K, L, deltaE = scans[:4]
        q_component = point_puma.sample_mount.hkl_to_q(H, K, L)
        qx, qy, qz = component_q_to_instrument_q(np.array(q_component, dtype=float))
        angles_array, error_flags = point_puma.calculate_angles(
            qx, qy, qz, deltaE, point_puma.fixed_E, point_puma.K_fixed,
            point_puma.monocris, point_puma.anacris
        )
        if not error_flags:
            mtt, stt, sth, saz, att = angles_array
            point_puma.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
    elif scan_mode == "orientation":
        qx, qy, qz, deltaE = scans[:4]
        angles_array, error_flags = point_puma.calculate_angles(
            qx, qy, qz, deltaE, point_puma.fixed_E, point_puma.K_fixed,
            point_puma.monocris, point_puma.anacris
        )
        if not error_flags:
            mtt, stt, sth, saz, att = angles_array
            point_puma.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
    else:
        A1, A2, A3, A4 = scans[:4]
        point_puma.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)
        deltaE = vals['deltaE']
        mtt, stt, sth, att = A1, A2, A3, A4
        saz = vals.get('chi', 0.0)

    q_vector = (qx, qy, qz) if qx is not None and qy is not None and qz is not None else None

    rhm, rvm, rha, rva = scans[4], scans[5], scans[6], scans[7]
    chi_scan, kappa_scan, psi_scan = scans[8], scans[9], scans[10]

    if scan_mode == "angle":
        omega_scan = scans[2]
    elif scan_mode in ["momentum", "rlu"] and not error_flags:
        omega_scan = sth
    elif scan_mode == "orientation":
        omega_scan = sth if not error_flags else vals.get('omega', 0)
    else:
        omega_scan = 0

    if 'rhm' not in [variable_name1, variable_name2]:
        rhm = point_puma.rhm
    if 'rvm' not in [variable_name1, variable_name2]:
        rvm = point_puma.rvm
    if 'rha' not in [variable_name1, variable_name2]:
        rha = point_puma.rha
    if 'rva' not in [variable_name1, variable_name2]:
        rva = point_puma.rva

    point_puma.omega = omega_scan
    point_puma.chi = chi_scan
    point_puma.kappa = kappa_scan
    point_puma.psi = psi_scan
    point_puma.saz = saz
    point_puma.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)

    output_folder = os.path.join(data_folder, f"scan_{scan_index:04d}")
    orientation_info = f"ω={omega_scan:.2f}, χ={chi_scan:.2f}, ψ={psi_scan:.2f}, κ={kappa_scan:.2f}"
    if scan_mode == "momentum":
        log_message = (
            f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
            f"Orientation: {orientation_info}"
        )
    elif scan_mode == "rlu":
        log_message = (
            f"Scan parameters - H: {H}, K: {K}, L: {L}, deltaE: {deltaE}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}\n"
            f"Orientation: {orientation_info}"
        )
    elif scan_mode == "orientation":
        log_message = (
            f"Scan parameters - qx: {qx}, qy: {qy}, qz: {qz}, deltaE: {deltaE}\n"
            f"Orientation: {orientation_info}\n"
            f"mtt: {mtt:.2f}, stt: {stt:.2f}, sth: {sth:.2f}, att: {att:.2f}"
        )
    else:
        log_message = (
            f"Scan parameters - A1: {point_puma.A1}, A2: {point_puma.A2}, A3: {point_puma.A3}, A4: {point_puma.A4}\n"
            f"rhm: {rhm:.2f}, rvm: {rvm:.2f}, rha: {rha:.2f}, rva: {rva:.2f}\n"
            f"Orientation: {orientation_info}"
        )

    metadata = {
        'scan_mode': scan_mode,
        'scan_command1': scan_command1,
        'scan_command2': scan_command2,
        'deltaE': deltaE,
        'qx': qx if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'qy': qy if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'qz': qz if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'q_vector': q_vector if scan_mode in ["momentum", "orientation", "rlu"] else None,
        'H': H if scan_mode == "rlu" else None,
        'K': K if scan_mode == "rlu" else None,
        'L': L if scan_mode == "rlu" else None,
        'mtt': mtt,
        'stt': stt,
        'sth': sth,
        'att': att,
        'rhm': rhm,
        'rvm': rvm,
        'rha': rha,
        'rva': rva,
        'omega': omega_scan,
        'chi': chi_scan,
        'psi': psi_scan,
        'kappa': kappa_scan,
    }
    metadata.update(_get_point_energy_metadata(point_puma, deltaE))

    return PointSnapshot(
        params=None if error_flags else build_puma_point_params(point_puma, deltaE),
        output_folder=output_folder,
        scan_index=scan_index,
        deltaE=deltaE,
        error_flags=error_flags,
        metadata=metadata,
        indices={
            'idx_1d': idx_1d,
            'idx_x': idx_x,
            'idx_y': idx_y,
        },
        log_message=log_message,
    )


def _resolve_materialized_binary_path(instrument):
    """Resolve the compiled McStas binary path for the built PUMA instrument."""
    instrument_input_path = getattr(instrument, "input_path", None)
    instrument_name = getattr(instrument, "name", None)
    if instrument_input_path and instrument_name:
        return os.path.abspath(os.path.join(instrument_input_path, f"{instrument_name}.exe"))

    return os.path.abspath(os.path.join(data_dir, f"{MCSTAS_NAME}.exe"))


def _run_puma_point_direct(execution_state, params_snapshot, output_folder, number_neutrons, mpi_count):
    """Run the already-materialized PUMA binary directly without mcrun.py."""
    # McStas --dir creates the leaf folder itself and aborts if it already
    # exists (mcuse_dir), so only ensure the parent is present.
    parent_folder = os.path.dirname(os.path.abspath(output_folder))
    os.makedirs(parent_folder, exist_ok=True)
    args = [
        *(execution_state.mpi_launcher_argv or []),
        "-np",
        str(mpi_count),
        execution_state.binary_path,
        f"--ncount={number_neutrons}",
        f"--dir={output_folder}",
    ]
    for key, value in params_snapshot.params.items():
        args.append(f"{key}={value}")

    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=execution_state.binary_cwd,
    )


def _build_execution_info(mode, output_folder, binary_path=None, returncode=None, stdout=None, error_message=None,
                          launcher_argv=None, armed_direct_run=False):
    """Build execution metadata consumed by the controller for logging and timing."""
    return {
        "mode": mode,
        "returncode": returncode,
        "stdout": stdout,
        "binary_path": binary_path,
        "output_folder": output_folder,
        "error_message": error_message,
        "launcher_argv": list(launcher_argv or []),
        "armed_direct_run": armed_direct_run,
    }


def run_PUMA_point(instrument, params_snapshot, output_folder, number_neutrons, execution_state, mpi_count=30):
    """Run one point on an already-built PUMA instrument."""
    error_flag_array = list(params_snapshot.error_flags)

    if error_flag_array:
        execution_state.last_execution_mode = "skipped"
        return math.nan, error_flag_array, _build_execution_info("skipped", output_folder)

    can_run_direct = bool(
        execution_state.direct_run_ready
        and execution_state.binary_path
        and execution_state.binary_cwd
        and execution_state.mpi_launcher_argv
        and os.path.isfile(execution_state.binary_path)
    )

    if can_run_direct:
        result = _run_puma_point_direct(
            execution_state,
            params_snapshot,
            output_folder,
            number_neutrons,
            mpi_count,
        )
        execution_state.last_execution_mode = "direct"
        execution_info = _build_execution_info(
            "direct",
            output_folder,
            binary_path=execution_state.binary_path,
            returncode=result.returncode,
            stdout=result.stdout,
            launcher_argv=execution_state.mpi_launcher_argv,
        )
        if result.returncode != 0:
            error_flag_array.append("direct_run_failed")
            execution_info["error_message"] = (
                f"Direct McStas run failed with return code {result.returncode}."
            )
            return math.nan, error_flag_array, execution_info

        detector_path = os.path.join(output_folder, "detector.dat")
        if not os.path.exists(detector_path):
            error_flag_array.append("detector_output_missing")
            execution_info["error_message"] = (
                "Direct McStas run completed without writing detector.dat."
            )
            return math.nan, error_flag_array, execution_info

        return None, error_flag_array, execution_info

    force_compile = not execution_state.first_backengine_succeeded

    instrument.settings(
        output_path=output_folder,
        ncount=number_neutrons,
        mpi=mpi_count,
        force_compile=force_compile,
        increment_folder_name=False,
    )

    instrument.set_parameters(**params_snapshot.params)
    data = instrument.backengine()
    execution_state.last_execution_mode = "backengine"

    was_direct_run_ready = execution_state.direct_run_ready
    resolved_binary_path = _resolve_materialized_binary_path(instrument)
    execution_state.first_backengine_succeeded = True
    execution_state.binary_path = resolved_binary_path
    execution_state.binary_cwd = os.path.dirname(resolved_binary_path)
    if not execution_state.mpi_launcher_argv:
        execution_state.mpi_launcher_argv = resolve_mpi_launcher_argv()
    execution_state.direct_run_ready = bool(
        execution_state.mpi_launcher_argv and os.path.isfile(resolved_binary_path)
    )

    execution_info = _build_execution_info(
        "backengine",
        output_folder,
        binary_path=resolved_binary_path,
        launcher_argv=execution_state.mpi_launcher_argv,
        armed_direct_run=not was_direct_run_ready and execution_state.direct_run_ready,
    )

    if not execution_state.direct_run_ready and execution_state.first_backengine_succeeded:
        if not os.path.isfile(resolved_binary_path):
            execution_info["error_message"] = (
                f"Compiled PUMA binary not found after backengine materialization: {resolved_binary_path}"
            )
        elif not execution_state.mpi_launcher_argv:
            execution_info["error_message"] = "MPI launcher could not be resolved for direct PUMA execution."

    return data, error_flag_array, execution_info


# alpha_2 stacked collimators: (divergence_arcmin, component_name, at_z, ymax, length).
# Shared geometry: xwidth = 39e-3, ymin = -70e-3. Tuple order = physical beam order.
# Divergences mirror the descriptor's alpha_2 slot values
# (tests/test_puma_build_tree.py keeps them in sync).
_ALPHA2_COLLIMATORS = (
    (40, "sample_collimator_40", 0.550, 84e-3, 0.152),
    (60, "sample_collimator_60", 0.6520, 78e-3, 0.102),
    (30, "sample_collimator_30", 0.854, 69e-3, 0.202),
)


def build_PUMA_instrument(puma_config, diagnostic_mode, diagnostic_settings, number_neutrons):
    """Build a PUMA instrument object for repeated per-point execution."""

    PUMA = puma_config

    # focusing; use 1 for optimal focusing, 0 for flat monochromator
    if PUMA.NMO_installed != "None":
        PUMA.rhmfac = 0 # radius factor in the horizontal for the monochromator
        PUMA.rvmfac = 0 # radius factor in the vertical for the monochromator

    ## start the instrument

    instrument = ms.McStas_instr(MCSTAS_NAME, input_path=data_dir)
    instrument.settings(output_path="./output", openacc=False) #uses nvc, must be set up on linux
    
    ## Add parameters
    instrument.add_parameter("A1_param", comment="Monochromator 2-theta angle.")
    instrument.add_parameter("A2_param", comment="Sample 2-theta angle.")
    instrument.add_parameter("A3_param", comment="Sample phi angle.")
    instrument.add_parameter("A4_param", comment="Analyzer 2-theta angle.")
    instrument.add_parameter("E0_param", comment="Source energy (meV) for monochromatic source.")
    instrument.add_parameter("nu_param", comment="Velocity selector frequency.")
    instrument.add_parameter("saz_param", comment="Sample azimuthal angle (out-of-plane).")
    instrument.add_parameter("rhm_param", comment="Monochromator horizontal bending.")
    instrument.add_parameter("rvm_param", comment="Monochromator vertical bending.")
    instrument.add_parameter("rha_param", comment="Analyzer horizontal bending.")
    instrument.add_parameter("rva_param", comment="Analyzer vertical bending.")
    # Slit aperture parameters (scannable)
    instrument.add_parameter("vbl_hgap_param", comment="Post-mono slit horizontal gap (m).")
    instrument.add_parameter("pbl_hgap_param", comment="Pre-sample slit horizontal gap (m).")
    instrument.add_parameter("pbl_vgap_param", comment="Pre-sample slit vertical gap (m).")
    instrument.add_parameter("dbl_hgap_param", comment="Detector slit horizontal gap (m).")
    

    # Monochromator crystal
    monochromator_info, analyzer_info = mono_ana_crystals_setup(PUMA.monocris, PUMA.anacris)

    # Diagnostic monitors are emitted from the descriptor table at the exact
    # insertion points below (component order is physics in McStas). The
    # crystal-sized monitors track the SELECTED crystal's slab geometry, so
    # their sizes are computed here and override the descriptor's precomputed
    # defaults (identical for the current crystals).
    from instruments.puma_plugin import _PUMA_MONITORS
    from tavi.instrument_helpers import emit_collimator, emit_monitors, emit_slit

    monitor = {m.id: m for m in _PUMA_MONITORS}
    enabled_monitors = diagnostic_settings if diagnostic_mode else {}
    _mono_w = monochromator_info['slabwidth'] * monochromator_info['ncolumns']
    _mono_h = monochromator_info['slabheight'] * monochromator_info['nrows']
    _ana_w = analyzer_info['slabwidth'] * analyzer_info['ncolumns']
    _ana_h = analyzer_info['slabheight'] * analyzer_info['nrows']
    monitor_size_overrides = {
        "premono_Emonitor": {"xwidth": _mono_w, "yheight": _mono_h},
        "postmono_Emonitor": {"xwidth": _mono_w, "yheight": _mono_h},
        "preanalyzer_Emonitor": {"xwidth": _ana_w, "yheight": _ana_h},
        "preanalyzer_PSD": {"xwidth": _ana_w, "yheight": _ana_h},
        "postanalyzer_Emonitor": {"xwidth": _ana_w, "yheight": _ana_h},
        "postanalyzer_PSD": {"xwidth": _ana_w, "yheight": _ana_h},
    }

    def emit_monitor_group(instrument, *ids):
        emit_monitors(instrument, [monitor[i] for i in ids], enabled_monitors,
                      size_overrides=monitor_size_overrides)

    def configure_component_tree():

        ## start adding components

        origin = instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])

        ## source-to-monochromator

        mono_width = monochromator_info['slabwidth']*monochromator_info['ncolumns'] + monochromator_info['gap']*(monochromator_info['ncolumns']-1)
        mono_height  =  monochromator_info['slabheight']*monochromator_info['nrows'] + monochromator_info['gap']*(monochromator_info['nrows']-1)

        source = instrument.add_component("source", "Source_div_Maxwellian_v2")
        source.xwidth= PUMA.hbl_hgap
        source.yheight= PUMA.hbl_vgap
        source.focus_aw=2*math.degrees(math.atan(mono_width/2/PUMA.L1)) # Want to completely illuminate the monochromator # FULL width half maximum, so multiply angle by x2
        source.focus_ah=2*math.degrees(math.atan(mono_height/2/PUMA.L1))
        # Source type: Mono (uniform, energy_distribution=0) or Maxwellian (energy_distribution=2)
        if PUMA.source_type == "Mono":
            source.energy_distribution = 0  # Uniform energy distribution
            source.dE = PUMA.source_dE  # User-configurable energy half-spread for Mono
            # Use E0_param for source energy (allows runtime adjustment without recompilation)
            source.E0 = "E0_param"
        else:  # Maxwellian
            source.energy_distribution = 2  # Maxwellian energy distribution
            source.dE = 3  # Default for Maxwellian (not used for sampling but affects weight)
            source.E0 = "E0_param"  # Use E0_param for source energy (allows runtime adjustment without recompilation)
        source.divergence_distribution=0

        emit_monitor_group(instrument, 'Source EMonitor', 'Source PSD')

        if PUMA.V_selector_installed:
            V_selector = instrument.add_component("v_selector", "V_selector", AT=[0,0,0.6], RELATIVE="origin")
            V_selector.xwidth = .100 #
            V_selector.yheight = .040 #
            V_selector.zdepth = .310 #
            V_selector.radius = .290 #
            V_selector.length = .25 #
            V_selector.d = .004 #
            V_selector.nslit = 72 #
            V_selector.alpha = 	48.3 #
            V_selector.nu = "nu_param"

        emit_monitor_group(instrument, 'Source DSD')

        emit_collimator(instrument, "mono_collimator", relative="origin",
                        at=(0, 0, 0.925), divergence=PUMA.alpha_1, length=0.2,
                        xwidth=40e-3, yheight=220e-3)

        emit_monitor_group(instrument, 'Postcollimation PSD', 'Postcollimation DSD',
                           'Premono Emonitor')

        ## monochromator section

        mono_cradle = instrument.add_component("mono_cradle", "Arm", AT=[0,0,PUMA.L1], RELATIVE="origin", ROTATED=[0,"A1_param/2",0])

        monochromator = instrument.add_component("monochromator", "Monochromator_curved", AT=[0,0,0], RELATIVE="mono_cradle")
        monochromator.zwidth = monochromator_info['slabwidth']
        monochromator.yheight = monochromator_info['slabheight']
        monochromator.gap = monochromator_info['gap']
        monochromator.NH = monochromator_info['ncolumns']
        monochromator.NV = monochromator_info['nrows']
        monochromator.r0 = monochromator_info['r0']
        monochromator.DM = monochromator_info['dm']
        monochromator.RV = "rvm_param"
        monochromator.RH = "rhm_param"
        monochromator.mosaic = monochromator_info['mosaic']
        monochromator.order = 0 # all orders
        monochromator.reflect = monochromator_info['reflect']
        monochromator.transmit = monochromator_info['transmit']
        monochromator.append_EXTEND("if(!SCATTERED) ABSORB;")
        monochromator.set_SPLIT(2)

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0,0,PUMA.L1], RELATIVE="origin", ROTATED=[0,"A1_param",0])

        emit_monitor_group(instrument, 'Postmono Emonitor')

        emit_slit(instrument, "postmono_slit", relative="sample_arm",
                  at=(0, 0, 0.286), rotated=(0, 0, 0),
                  xwidth="vbl_hgap_param", yheight=0.142)

        # Entrance slit of the alpha_2 collimator housing
        emit_collimator(instrument, "sample_collimator_dia", relative="sample_arm",
                        at=(0, 0, 0.398), divergence=0, length=0.112,
                        xwidth=39e-3, ymin=-70e-3, ymax=77e-3)

        emit_monitor_group(instrument, 'Pre-sample collimation PSD')

        for divergence, name, at_z, ymax, length in _ALPHA2_COLLIMATORS:
            if divergence in PUMA.alpha_2:
                emit_collimator(instrument, name, relative="sample_arm",
                                at=(0, 0, at_z), divergence=divergence,
                                length=length, xwidth=39e-3, ymin=-70e-3,
                                ymax=ymax)

        # This is the exit beam tube
        emit_slit(instrument, "exit_beam_tube", relative="sample_arm",
                  at=(0, 0, 1.1385), xwidth=0.105, yheight=0.18)

        # There is no actual sample filter on PUMA.

        ##############################################################################
        # NESTED MIRROR OPTICS (NMO) CONFIGURATION
        ##############################################################################
        #
        # Physical NMO dimensions (in beam reference frame):
        #   Length: 150mm (along beam, z-direction)
        #   Width:  67mm  (horizontal, x-direction) 
        #   Height: 79mm  (vertical, y-direction)
        #
        # Two NMO units are installed with DIFFERENT orientations:
        #
        # VERTICAL FOCUSING NMO:
        #   - Rotated 90° so mirrors curve in vertical (y) direction
        #   - Mirrors are 67mm wide in x (non-focusing) direction
        #   - Focuses the 79mm vertical beam extent down to sample
        #   - r_0 = 79mm/2 = 39.5mm (half the VERTICAL beam extent)
        #   - mirror_sidelength = 67mm (horizontal extent, non-focusing)
        #
        # HORIZONTAL FOCUSING NMO:
        #   - No rotation, mirrors curve in horizontal (x) direction
        #   - Mirrors are 79mm tall in y (non-focusing) direction
        #   - Focuses the 67mm horizontal beam extent down to sample
        #   - r_0 = 67mm/2 = 33.5mm (half the HORIZONTAL beam extent)
        #   - mirror_sidelength = 79mm (vertical extent, non-focusing)
        #
        ##############################################################################

        # === MIRROR OPTICAL PARAMETERS ===
        
        # Focal length: distance from NMO exit to focal point (sample position)
        focal_length = 1.0  # [m] Distance from NMO to sample
        
        # Focal offset: fine adjustment to move focal point relative to sample
        #   = 0: focus exactly AT sample (optimal)
        #   > 0: focus BEYOND sample (underfocused)
        #   < 0: focus BEFORE sample (overfocused)
        focal_offset = 0.0  # [m] Keep at 0 for optimal focusing
        
        # Source distance: large negative value for quasi-parallel input beam
        source_distance = -1000  # [m] Effectively parallel beam from upstream
        
        # === MIRROR GEOMETRY (Physical Dimensions) ===
        
        # Mirror extent along beam (local z-coordinates)
        lStart = 0.0    # [m] Mirrors start at component origin
        lEnd = 0.150    # [m] Mirrors end 150mm downstream (mirror length)
        
        # Substrate thickness
        mirror_width = 0.0003  # [m] 0.3mm silicon substrate
        
        # === ORIENTATION-SPECIFIC PARAMETERS ===
        
        # Vertical focusing NMO (rotated 90°):
        #   - Focuses vertical extent (79mm) → r_0 = 39.5mm
        #   - Non-focusing horizontal extent (67mm) → mirror_sidelength
        b0_vertical = 0.0395           # [m] Half of 79mm vertical aperture
        mirror_sidelength_vertical = 0.067  # [m] 67mm horizontal extent
        
        # Horizontal focusing NMO (no rotation):
        #   - Focuses horizontal extent (67mm) → r_0 = 33.5mm
        #   - Non-focusing vertical extent (79mm) → mirror_sidelength
        b0_horizontal = 0.0335         # [m] Half of 67mm horizontal aperture
        mirror_sidelength_horizontal = 0.079  # [m] 79mm vertical extent
        
        # === MIRROR COATING PARAMETERS ===
        
        mf = 100  # [1] Front surface m-value (100 ≈ perfect reflection for testing)
        mb = 0    # [1] Back surface m-value (0 = no back reflection)
        
        # === NUMBER OF MIRROR SHELLS ===
        # Must match rows in the corresponding m-value data files
        
        numVerticalMirrors = 38   # Rows in PUMA_NMO_VerticalFocusing.txt
        numHorizontalMirrors = 31  # Rows in PUMA_NMO_HorizontalFocusing.txt
        
        # === FILE PATHS FOR PER-MIRROR M-VALUES ===
        
        vertical_mirror_array_str = '"' + os.path.join(data_dir, "PUMA_NMO_VerticalFocusing.txt").replace('\\', '/') + '"'
        horizontal_mirror_array_str = '"' + os.path.join(data_dir, "PUMA_NMO_HorizontalFocusing.txt").replace('\\', '/') + '"'
        
        ##############################################################################
        # NMO COMPONENT PLACEMENT
        ##############################################################################
        
        # Pre-NMO slit to match beam to NMO aperture
        if PUMA.NMO_installed != "None":
            NMO_slit = instrument.add_component("NMO_slit", "Slit", 
                AT=[0, 0, PUMA.L2 - focal_length - lStart - 0.01], 
                RELATIVE="sample_arm")
            NMO_slit.xwidth = 0.067   # [m] Match horizontal NMO aperture (67mm)
            NMO_slit.yheight = 0.079  # [m] Match vertical NMO aperture (79mm)
        
        # -------------------------------------------------------------------------
        # VERTICAL FOCUSING NMO
        # -------------------------------------------------------------------------
        # Rotated 90° about z-axis: component x-axis → beam y-axis
        # This makes the x-focusing of the component act in the vertical direction
        #
        # After rotation:
        #   - Component focuses in beam's VERTICAL (y) direction
        #   - r_0 corresponds to vertical beam half-height (79mm/2 = 39.5mm)
        #   - mirror_sidelength is horizontal beam width (67mm)
        #
        if PUMA.NMO_installed == "Vertical" or PUMA.NMO_installed == "Both":
            vertical_focusing_NMO = instrument.add_component(
                "vertical_focusing_NMO", 
                "FlatEllipse_finite_mirror_optimized", 
                AT=[0, 0, PUMA.L2 - focal_length], 
                ROTATED=[0, 0, 90],  # Rotate to focus vertically
                RELATIVE="sample_arm"
            )
            
            # Focal points
            vertical_focusing_NMO.sourceDist = source_distance
            vertical_focusing_NMO.LStart = source_distance
            vertical_focusing_NMO.LEnd = focal_length + focal_offset
            
            # Mirror geometry - VERTICAL FOCUSING specific
            vertical_focusing_NMO.lStart = lStart
            vertical_focusing_NMO.lEnd = lEnd
            vertical_focusing_NMO.r_0 = b0_vertical              # 39.5mm (half of 79mm height)
            vertical_focusing_NMO.mirror_sidelength = mirror_sidelength_vertical  # 67mm width
            vertical_focusing_NMO.mirror_width = mirror_width
            vertical_focusing_NMO.nummirror = numVerticalMirrors
            
            # Reflection parameters
            vertical_focusing_NMO.mf = mf
            vertical_focusing_NMO.mb = mb
            vertical_focusing_NMO.doubleReflections = 1
            vertical_focusing_NMO.mirror_mvalue_file = vertical_mirror_array_str
            vertical_focusing_NMO.enable_silicon_refraction = 1

        # -------------------------------------------------------------------------
        # HORIZONTAL FOCUSING NMO  
        # -------------------------------------------------------------------------
        # No rotation: component x-axis = beam x-axis
        # Focuses in beam's HORIZONTAL (x) direction
        #
        # Placement: downstream of vertical NMO by mirror_length + gap
        # to avoid physical overlap when both are installed
        #
        if PUMA.NMO_installed == "Horizontal" or PUMA.NMO_installed == "Both":
            # Offset to place horizontal NMO after vertical NMO
            mirror_length = lEnd - lStart  # 0.150m
            h_nmo_offset = mirror_length + 0.001  # Small gap to prevent overlap
            
            horizontal_focusing_NMO = instrument.add_component(
                "horizontal_focusing_NMO", 
                "FlatEllipse_finite_mirror_optimized", 
                AT=[0, 0, PUMA.L2 - focal_length + h_nmo_offset], 
                ROTATED=[0, 0, 0],  # No rotation - focus horizontally
                RELATIVE="sample_arm"
            )
            
            # Focal points - LEnd adjusted for closer position to sample
            horizontal_focusing_NMO.sourceDist = source_distance
            horizontal_focusing_NMO.LStart = source_distance
            horizontal_focusing_NMO.LEnd = focal_length - h_nmo_offset + focal_offset
            
            # Mirror geometry - HORIZONTAL FOCUSING specific
            horizontal_focusing_NMO.lStart = lStart
            horizontal_focusing_NMO.lEnd = lEnd
            horizontal_focusing_NMO.r_0 = b0_horizontal          # 33.5mm (half of 67mm width)
            horizontal_focusing_NMO.mirror_sidelength = mirror_sidelength_horizontal  # 79mm height
            horizontal_focusing_NMO.mirror_width = mirror_width
            horizontal_focusing_NMO.nummirror = numHorizontalMirrors
            
            # Reflection parameters
            horizontal_focusing_NMO.mf = mf
            horizontal_focusing_NMO.mb = mb
            horizontal_focusing_NMO.doubleReflections = 1
            horizontal_focusing_NMO.mirror_mvalue_file = horizontal_mirror_array_str
            horizontal_focusing_NMO.enable_silicon_refraction = 1

        ##############################################################################
        # END NMO CONFIGURATION
        ##############################################################################

        ## sample table
        
        emit_slit(instrument, "sample_slit", relative="sample_arm",
                  at=(0, 0, PUMA.L2 - 0.674),
                  xwidth="pbl_hgap_param", yheight="pbl_vgap_param")
           
        emit_monitor_group(instrument, 'Sample PSD @ L2-0.5', 'Sample PSD @ L2-0.3',
                           'Sample PSD @ Sample', 'Sample DSD @ Sample',
                           'Sample EMonitor @ Sample')

        # Sample orientation hierarchy:
        # 1. sample_gonio: applies calculated saz (out-of-plane tilt from qz)
        # 2. sample_chi_arm: applies user chi + kappa (chi offset) + hidden chi misalignment
        # 3. sample_cradle: applies A3 (calculated sample theta) + psi (omega offset) + hidden omega/psi misalignment
        #
        instrument.add_parameter("chi_param", value=0, comment="User chi - out-of-plane tilt")
        instrument.add_parameter("kappa_param", value=0, comment="Kappa - chi alignment offset")
        instrument.add_parameter("mis_chi_param", value=0, comment="Hidden chi misalignment (training)")
        instrument.add_parameter("psi_param", value=0, comment="Psi - omega alignment offset")
        instrument.add_parameter("mis_omega_param", value=0, comment="Hidden omega misalignment (training)")
        instrument.add_parameter("chi_total", value=0, comment="Total chi = chi + kappa + mis_chi")
        instrument.add_parameter("omega_offset_total", value=0, comment="Total omega offset = psi + mis_omega")
        instrument.add_parameter("mount_rx_param", value=0, comment="Static sample mount rotation about x")
        instrument.add_parameter("mount_ry_param", value=0, comment="Static sample mount rotation about y")
        instrument.add_parameter("mount_rz_param", value=0, comment="Static sample mount rotation about z")
        
        instrument.add_component("sample_gonio", "Arm", AT=[0,0,PUMA.L2], ROTATED=["saz_param",0,0], RELATIVE="sample_arm")
        instrument.add_component("sample_chi_arm", "Arm", AT=[0,0,0], ROTATED=["chi_total",0,0], RELATIVE="sample_gonio")
        instrument.add_component("sample_cradle", "Arm", AT=[0,0,0], ROTATED=[0,"A3_param + omega_offset_total",0], RELATIVE="sample_chi_arm")
        instrument.add_component("sample_mount", "Arm", AT=[0,0,0], ROTATED=["mount_rx_param","mount_ry_param","mount_rz_param"], RELATIVE="sample_cradle")

        # Add sample component according to selected sample_key on PUMA (if set)
        sample_key = getattr(PUMA, 'sample_key', None)
        if sample_key == "Al_rod_phonon":
            Al_rod_phonon = instrument.add_component("Al_rod_phonon", "Phonon_simple_SCATTER", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_mount")
            Al_rod_phonon.radius = 5e-3
            Al_rod_phonon.yheight = 30e-3
            Al_rod_phonon.sigma_abs = 0*0.231
            Al_rod_phonon.sigma_inc = 0*0.0082
            Al_rod_phonon.a = 4.05
            Al_rod_phonon.b = 345
            Al_rod_phonon.M = 27
            Al_rod_phonon.c = 4
            Al_rod_phonon.DW = 1
            Al_rod_phonon.T = 200
            Al_rod_phonon.target_index = +2
            Al_rod_phonon.focus_aw = 5
            Al_rod_phonon.focus_ah = 15
            Al_rod_phonon.set_SPLIT(10)
            try:
                Al_rod_phonon.append_EXTEND("if(!SCATTERED) ABSORB;")
            except Exception:
                pass
        elif sample_key == "Al_rod_phonon_optic":
            Al_rod_phonon_optic = instrument.add_component("Al_rod_phonon_optic", "Optic_Phonon_simple", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_mount")
            Al_rod_phonon_optic.radius = 5e-3
            Al_rod_phonon_optic.yheight = 30e-3
            Al_rod_phonon_optic.sigma_abs = 0
            Al_rod_phonon_optic.sigma_inc = 0
            Al_rod_phonon_optic.a = 3.14
            Al_rod_phonon_optic.b = 345
            Al_rod_phonon_optic.M = 27
            Al_rod_phonon_optic.c = 4
            Al_rod_phonon_optic.DW = 1
            Al_rod_phonon_optic.T = 300
            Al_rod_phonon_optic.zero_energy = 4
            Al_rod_phonon_optic.maximum_energy = 1
            Al_rod_phonon_optic.target_index = +2
            Al_rod_phonon_optic.focus_aw = 5
            Al_rod_phonon_optic.focus_ah = 15
            Al_rod_phonon_optic.set_SPLIT(10)
            try:
                Al_rod_phonon_optic.append_EXTEND("if(!SCATTERED) ABSORB;")
            except Exception:
                pass
        elif sample_key == "Al_bragg":
            Al_Bragg = instrument.add_component("Al_Bragg", "Single_crystal", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_mount")
            Al_Bragg.reflections = '"Al.lau"'
            Al_Bragg.radius = 5e-3
            Al_Bragg.yheight = 30e-3
            Al_Bragg.mosaic = 5
            Al_Bragg.sigma_inc = -1
            Al_Bragg.set_SPLIT(10)
        elif sample_key == "Al_phonon_DFT":
            Al_phonon_DFT = instrument.add_component(
                "Al_phonon_DFT", "Phonon_DFT",
                AT=[0, 0, 0], ROTATED=[0, 0, 0], RELATIVE="sample_mount"
            )
            # --- Bragg scattering (pre-converted LAZ, avoids cif2hkl dependency) ---
            Al_phonon_DFT.reflections = '"Al_mp-134_symmetrized.laz"'
            Al_phonon_DFT.delta_d_d = 1.45e-3
            Al_phonon_DFT.barns = 1
            # --- Phonon scattering from dispersion file ---
            Al_phonon_DFT.dispersion = '"Al_test_phonons_centered.dat"'
            Al_phonon_DFT.tessellate = 1
            Al_phonon_DFT.phonon_e_steps = 50
            # --- Sample geometry ---
            Al_phonon_DFT.radius = 5e-3
            Al_phonon_DFT.yheight = 30e-3
            # --- Material parameters ---
            Al_phonon_DFT.a = 4.03893
            Al_phonon_DFT.sigma_abs = 0
            Al_phonon_DFT.sigma_inc = 0.0
            Al_phonon_DFT.debye_waller = 1
            Al_phonon_DFT.T = 200
            # --- Channel balance ---
            Al_phonon_DFT.p_interact = 1.0
            Al_phonon_DFT.p_phonon = 0.95
            Al_phonon_DFT.phonon_gamma = 0.2
            # --- Focusing ---
            Al_phonon_DFT.target_index = +2
            Al_phonon_DFT.focus_aw = 5.0
            Al_phonon_DFT.focus_ah = 15.0
            Al_phonon_DFT.set_SPLIT(10)
        else:
            # No sample selected; proceed without adding a sample component.
            print("Warning: No sample selected for instrument run; running without sample component.")

        ## analyzer

        analyzer_arm = instrument.add_component("analyzer_arm", "Arm", AT=[0,0,PUMA.L2], ROTATED=[0,"A2_param",0], RELATIVE="sample_arm")
        
        emit_monitor_group(instrument, 'Pre-analyzer collimation PSD')

        emit_collimator(instrument, "analyzer_collimator", relative="analyzer_arm",
                        at=(0, 0, 0.497), divergence=PUMA.alpha_3, length=0.2,
                        xwidth=0.05, yheight=1.28)

        analyzer_filter = instrument.add_component("analyzer_filter", "Filter_graphite", AT=[0,0,0.7], ROTATED=[0,0,0], RELATIVE="analyzer_arm")
        analyzer_filter.length = 0.05
        analyzer_filter.xwidth = 0.5
        analyzer_filter.yheight = 0.5

        emit_monitor_group(instrument, 'Pre-analyzer EMonitor', 'Pre-analyzer PSD')

        analyzer_cradle = instrument.add_component("analyzer_cradle", "Arm", AT=[0,0,PUMA.L3], ROTATED=[0,"A4_param/2",0], RELATIVE="analyzer_arm")

        analyzer = instrument.add_component("analyzer", "Monochromator_curved", AT=[0,0,0], RELATIVE="analyzer_cradle")
        analyzer.zwidth = analyzer_info['slabwidth']
        analyzer.yheight = analyzer_info['slabheight']
        analyzer.gap = analyzer_info['gap']
        analyzer.NH = analyzer_info['ncolumns']
        analyzer.NV = analyzer_info['nrows']
        analyzer.r0 = analyzer_info['r0']
        analyzer.DM = analyzer_info['da']
        analyzer.RV = "rva_param"
        analyzer.RH = "rha_param"
        analyzer.mosaic = analyzer_info['mosaic']
        analyzer.r0 = analyzer_info['r0']
        analyzer.reflect = analyzer_info['reflect']
        analyzer.transmit = analyzer_info['transmit']
        analyzer.order = 0 # all orders
        analyzer.set_SPLIT(5)

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0,0,PUMA.L3], ROTATED=[0,"A4_param",0], RELATIVE="analyzer_arm")

        emit_monitor_group(instrument, 'Post-analyzer EMonitor', 'Post-analyzer PSD')

        emit_collimator(instrument, "detector_collimator", relative="detector_arm",
                        at=(0, 0, 0.509), divergence=PUMA.alpha_4, length=0.2,
                        xwidth=30e-3, yheight=79e-3)

        emit_slit(instrument, "detector_slit", relative="detector_arm",
                  at=(0, 0, PUMA.L4 - 0.03), rotated=(0, 0, 0),
                  xwidth="dbl_hgap_param", yheight=0.07)

        emit_monitor_group(instrument, 'Detector PSD')

        detector = instrument.add_component("detector", "Monitor", AT=[0,0,PUMA.L4], ROTATED=[0,0,0], RELATIVE="detector_arm")
        detector.xwidth = 0.0254
        detector.yheight = 1.0

        instrument.settings(
            output_path="./output",
            ncount=number_neutrons,
            mpi=30,
            force_compile=True,
            increment_folder_name=False,
            openacc=False,
        )

        return instrument

    return configure_component_tree()
