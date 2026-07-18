"""PUMA (FRM-II) state, focusing physics, and McStas component tree."""
from __future__ import annotations

import math
import os

import mcstasscript as ms

from instruments.paths import COMPONENTS_DIR
from instruments.tas_runtime import TAS_Instrument
from tavi.neutron_conversions import energy2lambda
from tavi.instrument_helpers import (
    crystal_info_from_descriptor,
    crystal_spec_to_info as _crystal_spec_to_info,
    find_crystal_spec as _find_crystal_spec,
)

data_dir = COMPONENTS_DIR
MCSTAS_NAME = "PUMA_McScript"

def mono_ana_crystals_setup(monocris, anacris):
    """Crystal parameter dicts for the mono/analyzer, sourced from the descriptor.

    The descriptor (instruments/puma/plugin.py) is the single source of truth for
    crystal data; lookups are by CrystalSpec id ("pg002"). Unknown ids return
    empty dicts.
    """
    from instruments.puma.plugin import puma_descriptor

    return crystal_info_from_descriptor(puma_descriptor(), monocris, anacris)

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

    def crystal_info(self, monocris, anacris):
        return mono_ana_crystals_setup(monocris, anacris)

    def build_point_params(self, deltaE):
        return build_puma_point_params(self, deltaE)

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
    """Back-compat wrapper; the logic lives on TAS_Instrument.e0_param_value."""
    return PUMA.e0_param_value(deltaE)


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
    """Back-compat wrapper; the logic lives on TAS_Instrument.point_energy_metadata."""
    return PUMA.point_energy_metadata(deltaE)


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


# Human-readable limiting-constraint text for each TAS angle error flag emitted
# by ``TAS_Instrument.calculate_angles`` (see that method for where each is set).
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
    from instruments.puma.plugin import _PUMA_MONITORS
    from tavi.instrument_helpers import (
        emit_collimator,
        emit_crystal_assembly,
        emit_monitors,
        emit_sample,
        emit_sample_orientation_arms,
        emit_slit,
    )
    from tavi.sample_library import default_sample_library

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

        emit_crystal_assembly(instrument, cradle_name="mono_cradle",
                              crystal_name="monochromator", relative="origin",
                              distance=PUMA.L1, rotation_expr="A1_param/2",
                              info=monochromator_info, d_key='dm',
                              rv_param="rvm_param", rh_param="rhm_param",
                              split=2, extend="if(!SCATTERED) ABSORB;")

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
        
        sample_mount = emit_sample_orientation_arms(instrument,
                                                    relative="sample_arm",
                                                    distance=PUMA.L2)

        # Mount the selected sample from the shared library (samples move
        # between instruments; tavi/sample_library.py).
        sample_key = getattr(PUMA, 'sample_key', None)
        sample_spec = next(
            (s for s in default_sample_library() if s.id == sample_key), None
        )
        if sample_spec is not None and sample_spec.component_type is not None:
            emit_sample(instrument, sample_spec, relative=sample_mount)
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

        emit_crystal_assembly(instrument, cradle_name="analyzer_cradle",
                              crystal_name="analyzer", relative="analyzer_arm",
                              distance=PUMA.L3, rotation_expr="A4_param/2",
                              info=analyzer_info, d_key='da',
                              rv_param="rva_param", rh_param="rha_param",
                              split=5)

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
