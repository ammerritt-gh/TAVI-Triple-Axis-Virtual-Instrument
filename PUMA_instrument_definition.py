from cgi import test
from tracemalloc import take_snapshot
import mcstasscript as ms
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

def mono_ana_crystals_setup(monocris, anacris):
    """Holds the available monochromator and analyzer crystals to recall"""
    monochromator_info = {}
    analyzer_info = {}

    # Monochromator crystal
    if monocris == "PG[002]":
        #print("\nPG[002] monochromator crystal")
        monochromator_info['dm'] = 3.355
        monochromator_info['slabwidth'] = 0.0202
        monochromator_info['slabheight'] = 0.018
        monochromator_info['ncolumns'] = 13
        monochromator_info['nrows'] = 9
        monochromator_info['gap'] = 0.0005
        monochromator_info['mosaic'] = 35
        monochromator_info['r0'] = 1.0 #0.7
    if monocris == "PG[002] test":
        #print("\nPG[002] monochromator crystal")
        monochromator_info['dm'] = 2.355
        monochromator_info['slabwidth'] = 0.0202
        monochromator_info['slabheight'] = 0.018
        monochromator_info['ncolumns'] = 13
        monochromator_info['nrows'] = 9
        monochromator_info['gap'] = 0.0005
        monochromator_info['mosaic'] = 35
        monochromator_info['r0'] = 1.0 #0.7
    # else:
    #     print("\nNo monochromator crystal selected")

    # Analyzer crystal
    if anacris == "PG[002]":
        #print("\nPG[002] analyzer crystal")
        analyzer_info['da'] = 3.355
        analyzer_info['slabwidth'] = 0.01
        analyzer_info['slabheight'] = 0.0295
        analyzer_info['ncolumns'] = 21
        analyzer_info['nrows'] = 5
        analyzer_info['gap'] = 0.0005
        analyzer_info['mosaic'] = 35
        analyzer_info['r0'] = 1.0 #0.7
    # else:
    #     print("\nNo analyzer crystal selected")

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
        self.K_fixed = "Ki_fixed" # working in Ki- or Kf-fixed mode
        self.monocris = None # must have some monochromator crystal
        self.anacris = None # must have some analyzer crystal
        self.fixed_E = 0 # The fixed energy to work with, for the source.
 
    def set_parameters(self, **kwargs):
        """Method to set general parameters."""
        for key, value in kwargs.items():
            if key in self.parameters:
                self.parameters[key] = value
            else:
                print(f"Parameter '{key}' not found.")
    
    def set_angles(self, A1=None, A2=None, A3=None, A4=None):
        """Method to set A1-A4 angles."""
        if A1 is not None:
            self.A1 = A1
        if A2 is not None:
            self.A2 = A2
        if A3 is not None:
            self.A3 = A3
        if A4 is not None:
            self.A4 = A4
            
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
        
        # Retrieve mono/ana crystal information
        monochromator_info, analyzer_info = mono_ana_crystals_setup(monocris, anacris)
         
        # pre-calculate values from parameters
        q = math.sqrt(qx**2 + qy**2 + qz**2)
        ## TODO: error if q=0

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

        if -1 <= ((q**2 - ki**2 - kf**2) / (-2 * ki * kf)) <= 1:
            stt = -math.degrees(math.acos((q**2 - ki**2 - kf**2) / (-2 * ki * kf))) # This comes from the ki-kf-q triangle and law of cosines
        else:
            print("\nSample two theta angle invalid")
            stt = 0
            error_flags.append("stt")

        if "stt" in error_flags:
            print("\nCannot compute sample theta angle as sample two theta angle invalid")
            sth = 0
        else:
            if qx == 0:
                sth = stt / 2 + math.degrees(math.pi / 2)
            else:
                sth = stt / 2 + math.degrees(math.atan(qy/qx))
        
        ## TODO: error if qx=qy=0
        saz = -math.degrees(math.atan(qz/math.sqrt(qx**2 + qy**2)))


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

        # Compute Q components
        stt_rad = math.radians(stt)
        sth_rad = math.radians(sth)
        saz_rad = math.radians(saz)

        qx = ki * math.cos(sth_rad) - kf * math.cos(sth_rad + stt_rad)
        qy = ki * math.sin(sth_rad) - kf * math.sin(sth_rad + stt_rad)
        qz = -kf * math.tan(saz_rad)  # Based on azimuthal angle definition

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
        Note that the monochromator has particular trouble because the source is virtual."""
        # These are the old focusing formulas, from the initial files
        #rhm = rhmfac * 2 * (1 / self.L1 + 1 / self.L2) / math.sin(math.radians(mth))
        #rvm = rvmfac * 2 * (1 / self.L1 + 1 / self.L2) * math.sin(math.radians(mth))
        #rha = rhafac * 2 * (1 / self.L3 + 1 / self.L4) / math.sin(math.radians(ath))
        # rva = 0.8 # 1.6  # Said to be fixed at 0.8 m ##TODO double check whether this radius is correct or if it should be doubled
        
        
        rhm = rhmfac * 2 / math.sin(math.radians(mth)) / (1/self.L1 + 1/self.L2)
        rvm = rvmfac * 2 * math.sin(math.radians(mth)) / (1/self.L1 + 1/self.L2)
        rha = rhafac * 2 / math.sin(math.radians(ath)) / (1/self.L3 + 1/self.L4)
        rva = 0.8 # Said to be fixed at 0.8 m ##TODO double check whether this radius is correct or if it should be doubled
        
        #rhm = rhmfac * 2 / math.sin(math.radians(mth)) / (1/self.L2)
        #rvm = rvmfac * 2 * math.sin(math.radians(mth)) / (1/self.L2)

        # print(f"\nOld rhm: {rhm_old:.2f}, rvm: {rvm_old:.2f}, New rhm: {rhm:.2f}, rvm: {rvm:.2f}")
        
        print(f"\nrhm: {rhm:.2f} rvm: {rvm:.2f} rha: {rha:.2f} rva: {rva:.2f}")

        if rhm < 2.0 and rhmfac != 0:
            print("\nRequested Rh (mono) is {:.2f} m, but minimum Rh is 2.0 m".format(rhm))
            rhm = 2.0

        if rvm < 0.5 and rvmfac != 0:
            print("\nRequeste d Rv (mono) is {:.2f} m, but minimum Rv is 0.5 m".format(rvm))
            rvm = 0.5

        if rha < 2.0:
            print(f"\nRequested Rh (ana) is {rha:.2f} m, but minimum Rh is 2.0 m")
            rha = 2.0

        return rhm, rvm, rha, rva



def run_PUMA_instrument(PUMA, number_neutrons, deltaE, diagnostic_mode, diagnostic_settings, output_folder, run_number):
    """Runs a simulation using a PUMA instrument, needing only simulation parameters; the configuration of the instrument is passed to it automatically"""

    #QE_parameter_array = [qx, qy, qz, deltaE]
    #instrument_parameter_array = [number_neutrons, K_fixed, NMO_installed, fixed_E, monocris, anacris, alpha_1, alpha_2, alpha_3, alpha_4]

    # error flag array
    error_flag_array = []

    # focusing; use 1 for optimal focusing, 0 for flat monochromator
    if PUMA.NMO_installed != "None":
        PUMA.rhmfac = 0 # radius factor in the horizontal for the monochromator
        PUMA.rvmfac = 0 # radius factor in the vertical for the monochromator

    ## start the instrument

    instrument = ms.McStas_instr("PUMA_McScript", input_path="C:\\mcstas-3.4\\python_test")
    instrument.settings(openacc=False) #uses nvc, must be set up on linux
    
    ## Add parameters
    instrument.add_parameter("A1_param", comment="Monochromator 2-theta angle.")
    instrument.add_parameter("A2_param", comment="Sample 2-theta angle.")
    instrument.add_parameter("A3_param", comment="Sample phi angle.")
    instrument.add_parameter("A4_param", comment="Analyzer 2-theta angle.")
    instrument.add_parameter("rhm_param", comment="Monochromator horizontal bending.")
    instrument.add_parameter("rvm_param", comment="Monochromator vertical bending.")
    instrument.add_parameter("rha_param", comment="Analyzer horizontal bending.")
    instrument.add_parameter("rva_param", comment="Analyzer vertical bending.")
    

    # Monochromator crystal
    monochromator_info, analyzer_info = mono_ana_crystals_setup(PUMA.monocris, PUMA.anacris)    

    #rhm, rvm, rha, rva = PUMA.calculate_crystal_bending(PUMA.rhmfac, PUMA.rvmfac, PUMA.rhafac, PUMA.A1/2, PUMA.A4/2, )

    if not error_flag_array: #check if the error flags are empty before running

        ## start adding components

        origin = instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])

        ## source-to-monochromator

        mono_width = monochromator_info['slabwidth']*monochromator_info['ncolumns'] + monochromator_info['gap']*(monochromator_info['ncolumns']-1)
        mono_height  =  monochromator_info['slabheight']*monochromator_info['nrows'] + monochromator_info['gap']*(monochromator_info['nrows']-1)

        source = instrument.add_component("source", "Source_div_Maxwellian")
        source.xwidth= 0.05 #PUMA.hbl_hgap*1.5
        source.yheight=0.1 #PUMA.hbl_vgap*1.5
        source.focus_aw=4 #2*math.degrees(math.atan(mono_width/2/PUMA.L1)) # Want to completely illuminate the monochromator # FULL width half maximum, so multiply angle by x2
        source.focus_ah=4 #2*math.degrees(math.atan(mono_height/2/PUMA.L1))
        if PUMA.K_fixed == "Ki Fixed":
            source.E0=PUMA.fixed_E
        if PUMA.K_fixed == "Kf Fixed":
            source.E0=PUMA.fixed_E + deltaE
        source.dE=5
        source.energy_distribution=2
        source.E0 = 25
        source.divergence_distribution=0

        hblende = instrument.add_component("hblende", "Slit", AT=[0, 0, 0.0001], RELATIVE="origin")
        hblende.xwidth=PUMA.hbl_hgap
        hblende.yheight=PUMA.hbl_vgap

        if diagnostic_mode and diagnostic_settings.get('Source PSD'):
            source_PSD = instrument.add_component("source_PSD", "PSD_monitor", AT=[0,0,0.145], RELATIVE="origin")
            source_PSD.xwidth = PUMA.hbl_hgap*1.5
            source_PSD.yheight = PUMA.hbl_vgap*1.5
            source_PSD.nx = 100
            source_PSD.ny = 100
            source_PSD.restore_neutron = 1
            
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
            if PUMA.K_fixed == "Ki Fixed":
                V_selector.nu =  3956*math.radians(V_selector.alpha)/2/math.pi/V_selector.length/energy2lambda(PUMA.fixed_E)
            if PUMA.K_fixed == "Kf Fixed":
                V_selector.nu =  3956*math.radians(V_selector.alpha)/2/math.pi/V_selector.length/energy2lambda(PUMA.fixed_E + deltaE)
        
            
        if diagnostic_mode and diagnostic_settings.get('Source DSD'):
            source_DSD = instrument.add_component("source_DSD", "Divergence_monitor", AT=[0,0,0.924], RELATIVE="origin")
            source_DSD.xwidth = PUMA.hbl_hgap*1.5
            source_DSD.yheight = PUMA.hbl_vgap*1.5
            source_DSD.nh = 100
            source_DSD.nv = 100
            source_DSD.restore_neutron = 1

        mono_collimator = instrument.add_component("mono_collimator", "Collimator_linear", AT=[0,0,0.925], RELATIVE="origin")
        mono_collimator.xwidth = 40e-3
        mono_collimator.yheight = 220e-3
        mono_collimator.length = 0.2
        mono_collimator.divergence = PUMA.alpha_1
        
        

        if diagnostic_mode and diagnostic_settings.get('Postcollimation PSD'):
            postcollimation_PSD = instrument.add_component("postcollimation_PSD", "PSD_monitor", AT=[0,0,0.21], RELATIVE="PREVIOUS")
            postcollimation_PSD.xwidth = 0.05
            postcollimation_PSD.yheight = 0.25
            postcollimation_PSD.nx = 100
            postcollimation_PSD.ny = 100
            postcollimation_PSD.restore_neutron = 1
            
        if diagnostic_mode and diagnostic_settings.get('Postcollimation DSD'):
            postcollimation_DSD = instrument.add_component("postcollimation_DSD", "Divergence_monitor", AT=[0,0,PUMA.L1-0.002], RELATIVE="origin")
            postcollimation_DSD.xwidth = 0.1
            postcollimation_DSD.yheight = 0.1
            postcollimation_DSD.nh = 100
            postcollimation_DSD.nv = 100
            postcollimation_DSD.restore_neutron = 1

        if diagnostic_mode and diagnostic_settings.get('Premono Emonitor'):  
            premono_Emonitor = instrument.add_component("premono_Emonitor", "E_monitor", AT=[0,0,PUMA.L1-0.001], RELATIVE="origin")
            premono_Emonitor.xwidth = monochromator_info['slabwidth'] * monochromator_info['ncolumns']
            premono_Emonitor.yheight = monochromator_info['slabheight'] * monochromator_info['nrows']
            premono_Emonitor.nE = 400
            premono_Emonitor.Emin = 0
            premono_Emonitor.Emax = 200
            premono_Emonitor.restore_neutron = 1


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
        monochromator.append_EXTEND("if(!SCATTERED) ABSORB;")

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0,0,PUMA.L1], RELATIVE="origin", ROTATED=[0,"A1_param",0])

        if diagnostic_mode and diagnostic_settings.get('Postmono Emonitor'):
            postmono_Emonitor = instrument.add_component("postmono_Emonitor", "E_monitor", AT=[0,0,0.1], ROTATED=[0,0,0], RELATIVE="sample_arm")
            premono_Emonitor.xwidth = monochromator_info['slabwidth'] * monochromator_info['ncolumns']
            premono_Emonitor.yheight = monochromator_info['slabheight'] * monochromator_info['nrows']
            postmono_Emonitor.nE = 400
            postmono_Emonitor.Emin = 0
            postmono_Emonitor.Emax = 200
            postmono_Emonitor.restore_neutron = 1

        postmono_slit = instrument.add_component("postmono_slit", "Slit", AT=[0,0,0.286], ROTATED=[0,0,0], RELATIVE="sample_arm")
        postmono_slit.xwidth = PUMA.vbl_hgap
        postmono_slit.yheight = 0.142

        # # This is just an entrance slit
        sample_collimator_dia = instrument.add_component("sample_collimator_dia", "Collimator_linear", AT=[0,0,0.398], RELATIVE="sample_arm")
        sample_collimator_dia.xwidth = 39e-3
        sample_collimator_dia.ymin = -70e-3
        sample_collimator_dia.ymax = 77e-3
        sample_collimator_dia.length = 0.112
        sample_collimator_dia.divergence = 0
        
        if diagnostic_mode and diagnostic_settings.get('Pre-sample collimation PSD'):
            sample1_PSD = instrument.add_component("sample1_PSD", "PSD_monitor", AT=[0,0,PUMA.L2/4], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample1_PSD.xwidth = 0.06
            sample1_PSD.yheight = 0.15
            sample1_PSD.nx = 200
            sample1_PSD.ny = 200
            sample1_PSD.restore_neutron = 1
        
        if 40 in PUMA.alpha_2:
            sample_collimator_40 = instrument.add_component("sample_collimator_40", "Collimator_linear", AT=[0,0,0.550], RELATIVE="sample_arm")
            sample_collimator_40.xwidth = 39e-3
            sample_collimator_40.ymin = -70e-3
            sample_collimator_40.ymax = 84e-3
            sample_collimator_40.length = 0.152
            sample_collimator_40.divergence = 40
            
        if 60 in PUMA.alpha_2:
            sample_collimator_60 = instrument.add_component("sample_collimator_60", "Collimator_linear", AT=[0,0,0.6520], RELATIVE="sample_arm")
            sample_collimator_60.xwidth = 39e-3
            sample_collimator_60.ymin = -70e-3
            sample_collimator_60.ymax = 78e-3
            sample_collimator_60.length = 0.102
            sample_collimator_60.divergence = 60
        
        if 30 in PUMA.alpha_2:
            sample_collimator_30 = instrument.add_component("sample_collimator_30", "Collimator_linear", AT=[0,0,0.854], RELATIVE="sample_arm")
            sample_collimator_30.xwidth = 39e-3
            sample_collimator_30.ymin = -70e-3
            sample_collimator_30.ymax = 69e-3
            sample_collimator_30.length = 0.202
            sample_collimator_30.divergence = 30
            
        # # This is the exit beam tube
        # exit_beam_tube = instrument.add_component("exit_beam_tube", "Collimator_linear", AT=[0,0,0.9965], RELATIVE="sample_arm") 
        # exit_beam_tube.xwidth = 0.105
        # exit_beam_tube.yheight = 0.18
        # exit_beam_tube.length = 0.142
        # exit_beam_tube.divergence = 0
        
        # This is the exit beam tube
        exit_beam_tube = instrument.add_component("exit_beam_tube", "Slit", AT=[0,0,1.1385], RELATIVE="sample_arm") 
        exit_beam_tube.xwidth = 0.105
        exit_beam_tube.yheight = 0.18
            
        ## NMO
        
        b0 = 0.2076
        mf = 100
        mb = 0
        mirror_width= 0.003
        focal_length = 1
        mirror_sidelength = 0.06
        lStart = -0.075 * 0
        lEnd = 0.075 * 2
        rs_at_zero_str = '"NULL"'
        vertical_mirror_array_str = '"C://NMO_McStas//PUMA_NMO_VerticalFocusing.txt"'
        horizontal_mirror_array_str = '"C://NMO_McStas//PUMA_NMO_HorizontalFocusing.txt"'
        focal_offset = -0.15

        numVerticalMirrors = 76
        numHorizontalMirrors = 62
        
        if PUMA.NMO_installed != "None":
            NMO_slit = instrument.add_component("NMO_slit", "Slit", AT=[0,0,PUMA.L2-focal_length-lStart-0.01], RELATIVE="sample_arm")
            NMO_slit.xwidth = 0.06
            NMO_slit.yheight = 0.06
        
        if PUMA.NMO_installed == "Vertical" or PUMA.NMO_installed == "Both": #FlatEllipse_finite_mirror_mVal
            vertical_focusing_NMO = instrument.add_component("vertical_focusing_NMO", "FlatEllipse_finite_mirror", AT=[0, 0, PUMA.L2-focal_length], ROTATED=[0,0,90], RELATIVE="sample_arm")
            vertical_focusing_NMO.sourceDist=-(1000)
            vertical_focusing_NMO.LStart=-(1000)
            vertical_focusing_NMO.LEnd=focal_length + focal_offset
            vertical_focusing_NMO.lStart=lStart
            vertical_focusing_NMO.lEnd=lEnd
            vertical_focusing_NMO.r_0 = b0
            vertical_focusing_NMO.mirror_width = mirror_width
            vertical_focusing_NMO.mirror_sidelength = mirror_sidelength
            vertical_focusing_NMO.nummirror = numVerticalMirrors
            vertical_focusing_NMO.doubleReflections = 1
            vertical_focusing_NMO.mf = mf
            vertical_focusing_NMO.mb = mb
            #vertical_focusing_NMO.rfront_inner_file = rs_at_zero_str
            #vertical_focusing_NMO.mirror_mvalue_file = vertical_mirror_array_str

        
        if PUMA.NMO_installed == "Horizontal" or PUMA.NMO_installed == "Both":
            horizontal_focusing_NMO = instrument.add_component("horizontal_focusing_NMO", "FlatEllipse_finite_mirror", AT=[0, 0, PUMA.L2-(focal_length-(lEnd-lStart))+0.001], ROTATED=[0,0,0], RELATIVE="sample_arm")
            horizontal_focusing_NMO.sourceDist=-(1000)
            horizontal_focusing_NMO.LStart=-(1000)
            horizontal_focusing_NMO.LEnd=focal_length-(lEnd-lStart)+0.001 + focal_offset
            horizontal_focusing_NMO.lStart=lStart
            horizontal_focusing_NMO.lEnd=lEnd
            horizontal_focusing_NMO.r_0 = b0
            horizontal_focusing_NMO.mirror_width = mirror_width
            horizontal_focusing_NMO.mirror_sidelength = mirror_sidelength
            horizontal_focusing_NMO.nummirror = numHorizontalMirrors
            horizontal_focusing_NMO.doubleReflections = 1
            horizontal_focusing_NMO.mf = mf
            horizontal_focusing_NMO.mb = mb
            #horizontal_focusing_NMO.rfront_inner_file = rs_at_zero_str
            #horizontal_focusing_NMO.mirror_mvalue_file = horizontal_mirror_array_str

        ## sample table
        
        # sample_slit = instrument.add_component("sample_slit", "Slit", AT=[0,0,PUMA.L2-0.674], RELATIVE="sample_arm")
        # sample_slit.xwidth = PUMA.pbl_hgap
        # sample_slit.yheight = PUMA.pbl_vgap
           
        if diagnostic_mode and diagnostic_settings.get('Sample PSD @ L2-0.5'):
            sample2_PSD = instrument.add_component("sample2_PSD", "PSD_monitor", AT=[0,0,PUMA.L2-0.5], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample2_PSD.xwidth = 0.10
            sample2_PSD.yheight = 0.10
            sample2_PSD.nx = 100
            sample2_PSD.ny = 100
            sample2_PSD.restore_neutron = 1
            
        if diagnostic_mode and diagnostic_settings.get('Sample PSD @ L2-0.3'):
            sample3_PSD = instrument.add_component("sample3_PSD", "PSD_monitor", AT=[0,0,PUMA.L2-0.3], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample3_PSD.xwidth = 0.10
            sample3_PSD.yheight = 0.10
            sample3_PSD.nx = 100
            sample3_PSD.ny = 100
            sample3_PSD.restore_neutron = 1

        if diagnostic_mode and diagnostic_settings.get('Sample PSD @ Sample'):
            sample_PSD = instrument.add_component("sample_PSD", "PSD_monitor", AT=[0,0,PUMA.L2-0.03], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample_PSD.xwidth = 0.10
            sample_PSD.yheight = 0.10
            sample_PSD.nx = 100
            sample_PSD.ny = 100
            sample_PSD.restore_neutron = 1

        if diagnostic_mode and diagnostic_settings.get('Sample DSD @ Sample'):
            sample_DSD = instrument.add_component("sample_DSD", "Divergence_monitor", AT=[0,0,PUMA.L2-0.02], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample_DSD.xwidth = 0.1
            sample_DSD.yheight = 0.1
            sample_DSD.nh = 100
            sample_DSD.nv = 100
            sample_DSD.restore_neutron = 1

        if diagnostic_mode and diagnostic_settings.get('Sample EMonitor @ Sample'):
            sample_Emonitor = instrument.add_component("sample_Emonitor", "E_monitor", AT=[0,0,PUMA.L2-0.01], ROTATED=[0,0,0], RELATIVE="sample_arm")
            sample_Emonitor.xwidth = 0.2
            sample_Emonitor.yheight = 0.2
            sample_Emonitor.nE = 100
            sample_Emonitor.Emin = -2
            sample_Emonitor.Emax = 30
            sample_Emonitor.restore_neutron = 1

        instrument.add_component("sample_gonio", "Arm", AT=[0,0,PUMA.L2], ROTATED=[PUMA.saz,0,0], RELATIVE="sample_arm")
        instrument.add_component("sample_cradle", "Arm", AT=[0,0,0], ROTATED=[0,"A3_param",0], RELATIVE="sample_gonio")


        
        # # Union Initialization
        # init = instrument.add_component("init", "Union_init")
        # #instrument.component_help("PhononSimple_process")

        # # Define Phonon Scattering Process
        # Al_phonon = instrument.add_component("Al_phonon", "PhononSimple_process")
        # Al_phonon.a = 4.05
        # Al_phonon.b = 345
        # Al_phonon.M = 27
        # Al_phonon.c = 4
        # Al_phonon.DW = 1
        # Al_phonon.T = 200
        
        # # Add incoherent scattering
        # Al_incoherent = instrument.add_component("Al_incoherent", "Incoherent_process")
        # Al_incoherent.sigma = 4.0*0.0082
        # Al_incoherent.unit_cell_volume = 66.4

        # # Define Bragg Scattering Process
        # Al_Bragg = instrument.add_component("Al_Bragg", "Single_crystal_process")
        # Al_Bragg.reflections = '"Al.lau"'
        # Al_Bragg.mosaic = 5

        # # Combine Processes into a Material
        # Al_crystal = instrument.add_component("Al_crystal", "Union_make_material")
        # Al_crystal.my_absorption = 0 #100.0*4.0*0.231/100
        # Al_crystal.process_string = '"Al_incoherent,Al_Bragg,Al_phonon"'

        # # Define Geometry and Attach Material
        # Al_rod = instrument.add_component("Al_rod", "Union_cylinder", AT=[0, 0, 0], ROTATED=[0, 0, 0], RELATIVE="sample_cradle")
        # Al_rod.radius = 20e-3
        # Al_rod.yheight = 30e-3
        # Al_rod.material_string = '"Al_crystal"'
        # Al_rod.priority = 10
        # Al_rod.p_interact = 0.4

        # # Union Master and Stop
        # master = instrument.add_component("master", "Union_master")
        # stop = instrument.add_component("stop", "Union_stop")

         

        Al_rod_phonon = instrument.add_component("Al_rod_phonon", "Phonon_simple_SCATTER", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle") # Sample cradle or sample gonio? Was cradle, H8 example has gonio
        Al_rod_phonon.radius = 20e-3
        Al_rod_phonon.yheight = 30e-3
        Al_rod_phonon.sigma_abs = 0*0.231 #0.23 for Al
        Al_rod_phonon.sigma_inc = 0*0.0082 #0.0082 for Al
        Al_rod_phonon.a = 4.05 #4.05 for Al
        Al_rod_phonon.b = 345 #3.45 for Al
        Al_rod_phonon.M = 27 #atomic mass of Al
        Al_rod_phonon.c = 4
        Al_rod_phonon.DW = 1
        Al_rod_phonon.T = 200
        Al_rod_phonon.target_index = +2
        Al_rod_phonon.focus_aw = 5 #horizontal focus region in degrees, 5
        Al_rod_phonon.focus_ah = 15 #vertical focus region in degrees, 15
        Al_rod_phonon.append_EXTEND("if(!SCATTERED) ABSORB;") # The phonon_simple does not contain the keyword SCATTER normally, is added

        # Al_Bragg = instrument.add_component("Al_Bragg", "Single_crystal", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle") # Sample cradle or sample gonio? Was cradle, H8 example has gonio
        # Al_Bragg.reflections = '"Al.lau"'
        # Al_Bragg.radius = 20e-3
        # Al_Bragg.yheight = 30e-3
        # Al_Bragg.mosaic = 5
        # Al_Bragg.sigma_inc = -1


        # powder_test = instrument.add_component("powder_test", "Powder1", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle") # Sample cradle or sample gonio? Was cradle, H8 example has gonio
        # powder_test.radius = 20e-3
        # powder_test.yheight = 30e-3
        # powder_test.d_phi = 0.07
        # powder_test.sigma_abs = 0.231 #0.23 for Al
        # powder_test.Vc = 30.96
        # powder_test.pack = 1
        # powder_test.q = 2
        # powder_test.j = 6
        # powder_test.F2 = 100
        # powder_test.DW = 1
        # powder_test.append_EXTEND("if(!SCATTERED) ABSORB;") # The phonon_simple does not contain the keyword SCATTER normally, is added

        # Al_rod_phonon = instrument.add_component("Al_rod_phonon", "Phonon_simple", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle") # Sample cradle or sample gonio? Was cradle, H8 example has gonio
        # Al_rod_phonon.radius = 2e-2
        # Al_rod_phonon.yheight = 3e-2
        # Al_rod_phonon.sigma_abs = 0 #0.23 for Al
        # Al_rod_phonon.sigma_inc = 0 #0.0082 for Al
        # Al_rod_phonon.a = 3.14 #4.05 for Al
        # Al_rod_phonon.b = 345 #3.45 for Al
        # Al_rod_phonon.M = 27 #atomic mass of Al
        # Al_rod_phonon.c = 4
        # Al_rod_phonon.DW = 1
        # Al_rod_phonon.T = 300
        #Al_rod_phonon.target_index = +2	#relative index of component to focus at, e.g. next is +1	#set for the analyzer collimator
        #Al_rod_phonon.focus_aw = 5 #horizontal focus region in degrees, 5
        #Al_rod_phonon.focus_ah = 15 #vertical focus region in degrees, 15
        #Al_rod_phonon.append_EXTEND("if(!SCATTERED) ABSORB;") # The phonon_simple does not contain the keyword SCATTER normally, is added
        
        # Al_rod_phonon_optic = instrument.add_component("Al_rod_phonon_optic", "Optic_Phonon_simple", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle") # Sample cradle or sample gonio? Was cradle, H8 example has gonio
        # Al_rod_phonon_optic.radius = 2e-2
        # Al_rod_phonon_optic.yheight = 3e-2
        # Al_rod_phonon_optic.sigma_abs = 0 #0.23 for Al
        # Al_rod_phonon_optic.sigma_inc = 0 #0.0082 for Al
        # Al_rod_phonon_optic.a = 3.14 #4.05 for Al
        # Al_rod_phonon_optic.b = 345 #3.45 for Al
        # Al_rod_phonon_optic.M = 27 #atomic mass of Al
        # Al_rod_phonon_optic.c = 4
        # Al_rod_phonon_optic.DW = 1
        # Al_rod_phonon_optic.T = 300
        # Al_rod_phonon_optic.zero_energy = 4
        # Al_rod_phonon_optic.maximum_energy = 1
        # Al_rod_phonon_optic.append_EXTEND("if(!SCATTERED) ABSORB;") # The phonon_simple does not contain the keyword SCATTER normally, is added
        # Al_rod_phonon_optic.target_index = +2	#relative index of component to focus at, e.g. next is +1	#set for the analyzer collimator
        # Al_rod_phonon_optic.focus_aw = 5 #horizontal focus region in degrees, 5
        # Al_rod_phonon_optic.focus_ah = 15 #vertical focus region in degrees, 15
        
        # Al_ball = instrument.add_component("Al_ball", "PowderN", AT=[0,0,0], ROTATED=[0,0,0], RELATIVE="sample_cradle")
        # Al_ball.reflections = '"Al.laz"'
        # Al_ball.radius = 20E-3
        # Al_ball.append_EXTEND("if(!SCATTERED) ABSORB;")

        ## All commented out, example of union sample with multiple powders available.
        # def add_union_powder(name, data_name, sigma_inc, sigma_abs, unit_V, instr):
        #     """
        #     This function adds a Union material with incoherent scattering and powder lines
        #     """
        #     material_incoherent = instr.add_component(name + "_inc", "Incoherent_process")
        #     material_incoherent.sigma = sigma_inc
        #     material_incoherent.unit_cell_volume = unit_V
        #     material_powder = instr.add_component(name + "_pow", "Powder_process")
        #     material_powder.reflections = '"' + data_name + '"'  # Need quotes when describing a filename
        #     material = instr.add_component(name, "Union_make_material")
        #     material.my_absorption = 100*sigma_abs/unit_V
        #     material.process_string = '"' + name + "_inc," + name + "_pow" + '"'
    
        # # Add a number of standard powders to our instrument (datafiles included with McStas)
        # add_union_powder("Al", "Al.laz", 4*0.0082, 4*0.231, 66.4, instr)
        # add_union_powder("Cu", "Cu.laz", 4*0.55, 4*3.78, 47.24, instr)
        # add_union_powder("Ni", "Ni.laz", 4*5.2, 4*4.49, 43.76, instr)
        # add_union_powder("Ti", "Ti.laz", 2*2.87, 2*6.09, 35.33, instr)
        # add_union_powder("Pb", "Pb.laz", 4*0.003, 4*0.17, 121.29, instr)
        # add_union_powder("Fe", "Fe.laz", 2*0.4, 2*2.56, 24.04, instr)

        ## analyzer

        analyzer_arm = instrument.add_component("analyzer_arm", "Arm", AT=[0,0,PUMA.L2], ROTATED=[0,"A2_param",0], RELATIVE="sample_arm")
        
        if diagnostic_mode and diagnostic_settings.get('Pre-analyzer collimation PSD'):
            precollim_PSD = instrument.add_component("precollim_PSD", "PSD_monitor", AT=[0,0,0.49], ROTATED=[0,0,0], RELATIVE="analyzer_arm")
            precollim_PSD.xwidth = 1000e-3
            precollim_PSD.yheight = 1000e-3
            precollim_PSD.nx = 200
            precollim_PSD.ny = 200
            precollim_PSD.restore_neutron = 1

        analyzer_collimator = instrument.add_component("analyzer_collimator", "Collimator_linear", AT=[0,0,0.497], RELATIVE="analyzer_arm")
        analyzer_collimator.xwidth = 0.05 #38e-3
        analyzer_collimator.yheight = 1.28 #128.5e-3
        analyzer_collimator.length = 0.2
        analyzer_collimator.divergence = PUMA.alpha_3

        if diagnostic_mode and diagnostic_settings.get('Pre-analyzer EMonitor'):
            preanalyzer_Emonitor = instrument.add_component("preanalyzer_Emonitor", "E_monitor", AT=[0,0,PUMA.L3-0.1], ROTATED=[0,0,0], RELATIVE="analyzer_arm")
            preanalyzer_Emonitor.xwidth = analyzer_info['slabwidth'] * analyzer_info['ncolumns']
            preanalyzer_Emonitor.yheight = analyzer_info['slabheight'] * analyzer_info['nrows']
            preanalyzer_Emonitor.nE = 100
            preanalyzer_Emonitor.Emin = -2
            preanalyzer_Emonitor.Emax = 30
            preanalyzer_Emonitor.restore_neutron = 1
            
        if diagnostic_mode and diagnostic_settings.get('Pre-analyzer PSD'):
            preanalyzer_PSD = instrument.add_component("preanalyzer_PSD", "PSD_monitor", AT=[0,0,PUMA.L3-0.1], ROTATED=[0,0,0], RELATIVE="analyzer_arm")
            preanalyzer_PSD.xwidth = analyzer_info['slabwidth'] * analyzer_info['ncolumns']
            preanalyzer_PSD.yheight = analyzer_info['slabheight'] * analyzer_info['nrows']
            preanalyzer_PSD.nx = 100
            preanalyzer_PSD.ny = 100
            preanalyzer_PSD.restore_neutron = 1

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
        analyzer.order = 0 # all orders

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0,0,PUMA.L3], ROTATED=[0,"A4_param",0], RELATIVE="analyzer_arm")

        if diagnostic_mode and diagnostic_settings.get('Post-analyzer EMonitor'):
            postanalyzer_Emonitor = instrument.add_component("postanalyzer_Emonitor", "E_monitor", AT=[0,0,0.1], ROTATED=[0,0,0], RELATIVE="detector_arm")
            preanalyzer_Emonitor.xwidth = analyzer_info['slabwidth'] * analyzer_info['ncolumns']
            preanalyzer_Emonitor.yheight = analyzer_info['slabheight'] * analyzer_info['nrows']
            postanalyzer_Emonitor.nE = 100
            postanalyzer_Emonitor.Emin = -2
            postanalyzer_Emonitor.Emax = 30
            postanalyzer_Emonitor.restore_neutron = 1
            
        if diagnostic_mode and diagnostic_settings.get('Post-analyzer PSD'):
            postanalyzer_PSD = instrument.add_component("postanalyzer_PSD", "PSD_monitor", AT=[0,0,0.5], ROTATED=[0,0,0], RELATIVE="detector_arm")
            postanalyzer_PSD.xwidth = analyzer_info['slabwidth'] * analyzer_info['ncolumns']
            postanalyzer_PSD.yheight = analyzer_info['slabheight'] * analyzer_info['nrows']
            postanalyzer_PSD.nx = 100
            postanalyzer_PSD.ny = 100
            postanalyzer_PSD.restore_neutron = 1

        detector_collimator = instrument.add_component("detector_collimator", "Collimator_linear", AT=[0,0,0.509], RELATIVE="detector_arm")
        detector_collimator.xwidth = 30e-3
        detector_collimator.yheight = 79e-3
        detector_collimator.length = 0.2
        detector_collimator.divergence = PUMA.alpha_4

        detector_slit = instrument.add_component("detector_slit", "Slit", AT=[0,0,PUMA.L4-0.03], ROTATED=[0,0,0], RELATIVE="detector_arm")
        detector_slit.xwidth = PUMA.dbl_hgap
        detector_slit.yheight = 0.07

        if diagnostic_mode and diagnostic_settings.get('Detector PSD'):
            detector_PSD = instrument.add_component("detector_PSD", "PSD_monitor", AT=[0,0,PUMA.L4-0.001], RELATIVE="detector_arm")
            detector_PSD.xwidth = 0.0254
            detector_PSD.yheight = 1.0
            detector_PSD.nx = 100
            detector_PSD.ny = 100
            detector_PSD.restore_neutron = 1

        detector = instrument.add_component("detector", "Monitor", AT=[0,0,PUMA.L4], ROTATED=[0,0,0], RELATIVE="detector_arm")
        detector.xwidth = 0.0254
        detector.yheight = 1.0

        if run_number==0:
            instrument.settings(output_path=output_folder, ncount=number_neutrons, mpi=10, force_compile=True)
            print("Compiled")
        else:
            instrument.settings(output_path=output_folder, ncount=number_neutrons, mpi=10, force_compile=False)
            print("Not compiled")
        if not error_flag_array: #check if the error flags are empty
            instrument.set_parameters(
                A1_param=PUMA.A1,
                A2_param=PUMA.A2,
                A3_param=PUMA.A3,
                A4_param=PUMA.A4,
                rhm_param=PUMA.rhm,
                rvm_param=PUMA.rvm,
                rha_param=PUMA.rha,
                rva_param=PUMA.rva
            )
            data = instrument.backengine()
        else:
            data = math.nan
        
        #if diagnostic_mode is True:
            #instrument.show_diagram()

        #print(parameter_array)
        #print("\n")
        #print(parameter_array_header)
    else:
        data = math.nan
    return(data, error_flag_array)

def validate_angles(K_fixed, fixed_E, qx, qy, qz, deltaE, monocris, anacris):

    # error flag array
    error_flag_array = []

    # base instrument parameters
    # distances in meters
    # arm lengths
    L1 = 2.150  # source-mono
    L2 = 2.290  # mono-sample
    L3 = 0.880  # sample-ana
    L4 = 0.750  # ana-det

    # focusing; use 1 for optimal focusing, 0 for flat monochromator
    rhmfac = 1 # radius factor in the horizontal for the monochromator
    rvmfac = 1 # radius factor in the vertical for the monochromator
    rhafac = 1 # radius factor in the horizontal for the analyzer (vertical is fixed)

    ## start the instrument

    # Monochromator crystal
    if monocris == "PG[002]":
        #print("\nPG[002] monochromator crystal")
        dm = 3.355
        slabwidth_M = 0.018
        slabheight_M = 0.02
        ncolumn_M = 13
        nrows_M = 9
        eth_M = 35
    else:
        print("\nNo monochromator crystal selected")

    # Analyzer crystal
    if anacris == "PG[002]":
        #print("\nPG[002] analyzer crystal")
        da = 3.355
        slabwidth_A = 0.01
        slabheight_A = 0.03
        ncolumn_A = 5
        nrows_A = 21
        eth_A = 35
    else:
        print("\nNo analyzer crystal selected")


    # pre-calculate values from paramters
    q = math.sqrt(qx**2 + qy**2 + qz**2)

    K = energy2k(fixed_E)

    if K_fixed == "Ki Fixed":
        mtt = 2 * k2angle(K, dm)
        Ei = fixed_E
        ki = energy2k(Ei)
        Ef = Ei - deltaE
        kf = energy2k(Ef)
        att = 2 * k2angle(kf, da)
        if mtt == math.inf:
            #print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
            error_flag_array.append("mtt")
        if att == math.inf:
            #print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
            att = 0
            error_flag_array.append("att")
    elif K_fixed == "Kf Fixed":
        att = 2 * k2angle(K, da)
        Ef = fixed_E
        kf = energy2k(Ef)
        Ei = Ef + deltaE
        ki = energy2k(Ei)
        mtt = 2 * k2angle(ki, dm)
        if mtt == math.inf:
            #print("\nCannot compute monochromator two theta angle as momentum transfer invalid")
            error_flag_array.append("mtt")
        if att == math.inf:
            #print("\nCannot compute analyzer two theta angle as momentum transfer invalid")
            error_flag_array.append("att")

    if -1 <= ((q * q - ki * ki - kf * kf) / (-2 * ki * kf)) <= 1:
        stt = -math.degrees(math.acos((q * q - ki * ki - kf * kf) / (-2 * ki * kf)))
    else:
        print("\nSample two theta angle invalid")
        stt = 0
        error_flag_array.append("stt")

    if "stt" in error_flag_array:
        #print("\nCannot compute sample theta angle as sample two theta angle invalid")
        sth = 0
    else:
        if qx == 0:
            sth = stt / 2 + math.degrees(math.pi / 2)
        else:
            sth = stt / 2 + math.degrees(math.atan(qy/qx))
    
    # TODO: set check for qx, qy=0
    saz = -math.degrees(math.atan(qz/math.sqrt(qx*qx + qy*qy)))

    # set crystal rotations
    mth = mtt/2
    ath = att/2

    # TODO: add in NMO component to validation
    rhmfac, rvmfac = 1, 1
    rhafac = 1

    if not error_flag_array: #check if the error flags are empty
        # set crystal bending
        rhm = rhmfac*2*(1/L1 + 1/L2)/math.sin(math.radians(mth))
        rvm = rvmfac*2*(1/L1 + 1/L2)*math.sin(math.radians(mth))

        # check if the mirror focus is too short
        if rhm < 2.0:
            #print("\nRequested Rh (mono) is {:.2f} m, but minimum Rh is 2.0 m".format(rhm))
            rhm = 2.0

        if rvm < 0.5:
            #print("\nRequested Rv (mono) is {:.2f} m, but minimum Rv is 0.5 m".format(rvm))
            rvm = 0.5

        rha = rhafac*2*(1/L3 + 1/L4)/math.sin(math.radians(ath))
        rva = 0.8 # fixed at 0.8 m

        if rha < 2.0:
            print(f"\nRequested Rh (ana) is {rha:.2f} m, but minimum Rh is 2.0 m")
            rha = 2.0

        #print(f"\nmtt: {mtt:.2f} ki: {ki:.3f} Ei: {Ei:.3f} stt: {stt:.3f} saz: {saz:.3f} Q: {q:.2f} kf: {kf:.3f} Ef: {Ef:.3f} att: {att:.2f}")
 
    return(error_flag_array)