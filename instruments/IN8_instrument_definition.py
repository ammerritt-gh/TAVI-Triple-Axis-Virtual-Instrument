"""IN8 (ILL) McStas instrument definition.

The second TAVI instrument, and the template for further ones: the TAS state
base class, the per-point snapshot pipeline, and the run layer are all shared
with ``instruments/PUMA_instrument_definition.py`` (accepted Phase-4 coupling;
relocation to a neutral module is deferred until a third instrument needs it,
design record §20). What lives here is only what is genuinely IN8's:

- ``IN8_Instrument``: geometry, verified scattering senses (+1, +1, -1),
  point-source focusing formulas, and the per-point parameter dict.
- ``build_IN8_instrument``: the component tree, emitted through the shared
  helpers in ``tavi/instrument_helpers.py`` wherever a category exists there
  (monitors, crystals, collimators, slits, sample + orientation arms); the
  literal remainder is the source block, the axis arms, the PG filter, and
  the detector.

Values marked PLACEHOLDER affect intensity/resolution only, never angles.
"""
import math
import os

import mcstasscript as ms

from instruments.PUMA_instrument_definition import (
    TAS_Instrument,
    compute_scan_snapshot,  # noqa: F401  (re-export: the IN8 plugin's snapshot path)
    data_dir,
    run_tas_point,  # noqa: F401  (re-export: the IN8 plugin's run path)
)
from tavi.instrument_helpers import (
    crystal_info_from_descriptor,
    emit_collimator,
    emit_crystal_assembly,
    emit_monitors,
    emit_sample,
    emit_sample_orientation_arms,
    emit_slit,
)

# McStas instrument name: drives the generated .instr/.c/.exe filenames and must
# match the descriptor's mcstas_name (instruments/in8_plugin.py).
MCSTAS_NAME = "IN8_McScript"


class IN8_Instrument(TAS_Instrument):
    """IN8 instrument state: ILL-current geometry plus verified senses."""

    def __init__(self, diagnostic_mode=False, diagnostic_settings=None):
        super().__init__()
        self.L1 = 2.28   # virtual source - mono (ILL: 2280 mm; 2006 paper: 2284)
        self.L2 = 2.48   # mono - sample (ILL Thermes; vTAS reference says 2.5)
        self.L3 = 1.05   # sample - analyzer (ILL Thermes; vTAS says 1.35)
        self.L4 = 0.70   # analyzer - detector (ILL Thermes; vTAS says 0.65)
        # Verified live vTAS run 2026-07-02: senses (+1, +1, -1); see the
        # descriptor Geometry in instruments/in8_plugin.py.
        self.sense_mono = 1
        self.sense_sample = 1
        self.sense_ana = -1
        # Horizontal virtual source aperture (2006 paper: HVS; ILL: ~30 mm wide
        # for PG/Cu). Height is a PLACEHOLDER.
        self.hvs_width = 0.030
        self.hvs_height = 0.120
        # Single-value collimation slots (arcmin; 0 = open). No alpha_1: IN8's
        # primary collimation sits between mono and sample.
        self.alpha_2 = 0
        self.alpha_3 = 0
        self.alpha_4 = 0
        # Slit gaps (m; PLACEHOLDER defaults, runtime-scannable parameters).
        self.sbl_wgap = 0.040
        self.sbl_hgap = 0.100
        self.dbl_hgap = 0.040
        # Crystal bending (m; 0 = flat). Factors of 1 = optimal focusing.
        self.rhmfac = 1
        self.rvmfac = 1
        self.rhafac = 1
        self.rhm = 0
        self.rvm = 0
        self.rha = 0
        self.rva = 0
        self.source_dE = 2  # Energy half-spread for Mono source (meV)
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_settings = diagnostic_settings if diagnostic_settings else {}

    def crystal_info(self, monocris, anacris):
        from instruments.in8_plugin import in8_descriptor

        return crystal_info_from_descriptor(in8_descriptor(), monocris, anacris)

    def calculate_crystal_bending(self, rhmfac, rvmfac, rhafac, mth, ath):
        """Ideal bending radii for IN8's double-focusing crystals.

        Point-source formulas on BOTH sides (unlike PUMA, whose guide delivers
        a quasi-parallel beam to the mono): the horizontal virtual source at L1
        is a real focal point, so RH = 2/sin(theta)/(1/Lin + 1/Lout) and
        RV = 2*sin(theta)/(1/Lin + 1/Lout). IN8's analyzer is double-focusing,
        so rva is computed too (PUMA fixes it at 0.8).

        Angles arrive signed (IN8's A4 is negative); the radius is a magnitude.
        No minimum-radius clamps: IN8's mechanical limits are unknown
        (PLACEHOLDER; design record §20).
        """
        sin_mth = abs(math.sin(math.radians(mth)))
        sin_ath = abs(math.sin(math.radians(ath)))
        mono_focus = 1 / (1 / self.L1 + 1 / self.L2)
        ana_focus = 1 / (1 / self.L3 + 1 / self.L4)

        rhm = rhmfac * 2 * mono_focus / sin_mth
        rvm = rvmfac * 2 * mono_focus * sin_mth
        rha = rhafac * 2 * ana_focus / sin_ath
        rva = 2 * ana_focus * sin_ath

        print(f"\nrhm: {rhm:.2f} rvm: {rvm:.2f} rha: {rha:.2f} rva: {rva:.2f}")
        return rhm, rvm, rha, rva

    def build_point_params(self, deltaE):
        """Build the runtime parameter snapshot for one instrument point.

        Keys mirror instruments/in8_plugin.py::_IN8_PARAMS exactly.
        """
        sample_angles = self.get_sample_angle_components()
        mount_rx, mount_ry, mount_rz = self.sample_mount.mount_euler_deg
        return {
            "A1_param": self.A1,
            "A2_param": self.A2,
            "A3_param": self.A3,
            "A4_param": self.A4,
            "E0_param": self.e0_param_value(deltaE),
            "saz_param": self.saz,
            "rhm_param": self.rhm,
            "rvm_param": self.rvm,
            "rha_param": self.rha,
            "rva_param": self.rva,
            "sbl_wgap_param": self.sbl_wgap,
            "sbl_hgap_param": self.sbl_hgap,
            "dbl_hgap_param": self.dbl_hgap,
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


def build_IN8_instrument(in8_config, diagnostic_mode, diagnostic_settings, number_neutrons):
    """Build an IN8 instrument object for repeated per-point execution."""

    IN8 = in8_config

    instrument = ms.McStas_instr(MCSTAS_NAME, input_path=data_dir)
    instrument.settings(output_path="./output", openacc=False)

    ## Add parameters
    instrument.add_parameter("A1_param", comment="Monochromator 2-theta angle.")
    instrument.add_parameter("A2_param", comment="Sample 2-theta angle.")
    instrument.add_parameter("A3_param", comment="Sample phi angle.")
    instrument.add_parameter("A4_param", comment="Analyzer 2-theta angle.")
    instrument.add_parameter("E0_param", comment="Source energy (meV) for monochromatic source.")
    instrument.add_parameter("saz_param", comment="Sample azimuthal angle (out-of-plane).")
    instrument.add_parameter("rhm_param", comment="Monochromator horizontal bending.")
    instrument.add_parameter("rvm_param", comment="Monochromator vertical bending.")
    instrument.add_parameter("rha_param", comment="Analyzer horizontal bending.")
    instrument.add_parameter("rva_param", comment="Analyzer vertical bending.")
    # Slit aperture parameters (scannable)
    instrument.add_parameter("sbl_wgap_param", comment="Pre-sample slit horizontal gap (m).")
    instrument.add_parameter("sbl_hgap_param", comment="Pre-sample slit vertical gap (m).")
    instrument.add_parameter("dbl_hgap_param", comment="Detector slit horizontal gap (m).")

    monochromator_info, analyzer_info = IN8.crystal_info(IN8.monocris, IN8.anacris)

    from instruments.in8_plugin import _IN8_MONITORS
    from tavi.sample_library import default_sample_library

    monitor = {m.id: m for m in _IN8_MONITORS}
    enabled_monitors = diagnostic_settings if diagnostic_mode else {}

    def emit_monitor_group(instrument, *ids):
        emit_monitors(instrument, [monitor[i] for i in ids], enabled_monitors)

    def configure_component_tree():

        origin = instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])

        ## source-to-monochromator

        mono_width = monochromator_info['slabwidth'] * monochromator_info['ncolumns'] \
            + monochromator_info['gap'] * (monochromator_info['ncolumns'] - 1)
        mono_height = monochromator_info['slabheight'] * monochromator_info['nrows'] \
            + monochromator_info['gap'] * (monochromator_info['nrows'] - 1)

        # The source sits AT the horizontal virtual source (an adjustable slit
        # in reality); its aperture is the HVS opening, illuminating the full
        # monochromator face at L1.
        source = instrument.add_component("source", "Source_div_Maxwellian_v2")
        source.xwidth = IN8.hvs_width
        source.yheight = IN8.hvs_height
        source.focus_aw = 2 * math.degrees(math.atan(mono_width / 2 / IN8.L1))
        source.focus_ah = 2 * math.degrees(math.atan(mono_height / 2 / IN8.L1))
        if IN8.source_type == "Mono":
            source.energy_distribution = 0  # Uniform energy distribution
            source.dE = IN8.source_dE
            source.E0 = "E0_param"
        else:  # Maxwellian
            source.energy_distribution = 2  # Maxwellian energy distribution
            source.dE = 3
            source.E0 = "E0_param"
        source.divergence_distribution = 0

        emit_monitor_group(instrument, 'Source EMonitor', 'Source PSD')

        ## monochromator section

        emit_crystal_assembly(instrument, cradle_name="mono_cradle",
                              crystal_name="monochromator", relative="origin",
                              distance=IN8.L1, rotation_expr="A1_param/2",
                              info=monochromator_info, d_key='dm',
                              rv_param="rvm_param", rh_param="rhm_param",
                              split=2, extend="if(!SCATTERED) ABSORB;")

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0, 0, IN8.L1],
                                              RELATIVE="origin", ROTATED=[0, "A1_param", 0])

        # PLACEHOLDER position/aperture for the alpha_2 Soller (divergence 0 = open).
        emit_collimator(instrument, "sample_collimator", relative="sample_arm",
                        at=(0, 0, IN8.L2 / 2), divergence=IN8.alpha_2, length=0.2,
                        xwidth=0.05, yheight=0.15)

        emit_slit(instrument, "sample_slit", relative="sample_arm",
                  at=(0, 0, IN8.L2 - 0.35),
                  xwidth="sbl_wgap_param", yheight="sbl_hgap_param")

        emit_monitor_group(instrument, 'Sample PSD @ Sample', 'Sample DSD @ Sample',
                           'Sample EMonitor @ Sample')

        # Sample orientation hierarchy (shared with every TAVI instrument):
        # sample_gonio (saz) -> sample_chi_arm (chi) -> sample_cradle (A3) ->
        # sample_mount (static mount rotations).
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
                                                    distance=IN8.L2)

        # Mount the selected sample from the shared library (samples move
        # between instruments; tavi/sample_library.py).
        sample_key = getattr(IN8, 'sample_key', None)
        sample_spec = next(
            (s for s in default_sample_library() if s.id == sample_key), None
        )
        if sample_spec is not None and sample_spec.component_type is not None:
            emit_sample(instrument, sample_spec, relative=sample_mount)
        else:
            print("Warning: No sample selected for instrument run; running without sample component.")

        ## analyzer

        analyzer_arm = instrument.add_component("analyzer_arm", "Arm", AT=[0, 0, IN8.L2],
                                                ROTATED=[0, "A2_param", 0], RELATIVE="sample_arm")

        # One 5 cm PG higher-order filter (the 2023 paper describes two;
        # PLACEHOLDER single filter and position).
        analyzer_filter = instrument.add_component("analyzer_filter", "Filter_graphite",
                                                   AT=[0, 0, 0.5], ROTATED=[0, 0, 0],
                                                   RELATIVE="analyzer_arm")
        analyzer_filter.length = 0.05
        analyzer_filter.xwidth = 0.3
        analyzer_filter.yheight = 0.3

        emit_collimator(instrument, "analyzer_collimator", relative="analyzer_arm",
                        at=(0, 0, 0.7), divergence=IN8.alpha_3, length=0.2,
                        xwidth=0.05, yheight=0.25)

        emit_crystal_assembly(instrument, cradle_name="analyzer_cradle",
                              crystal_name="analyzer", relative="analyzer_arm",
                              distance=IN8.L3, rotation_expr="A4_param/2",
                              info=analyzer_info, d_key='da',
                              rv_param="rva_param", rh_param="rha_param",
                              split=5)

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0, 0, IN8.L3],
                                                ROTATED=[0, "A4_param", 0], RELATIVE="analyzer_arm")

        emit_collimator(instrument, "detector_collimator", relative="detector_arm",
                        at=(0, 0, 0.3), divergence=IN8.alpha_4, length=0.15,
                        xwidth=0.05, yheight=0.10)

        emit_slit(instrument, "detector_slit", relative="detector_arm",
                  at=(0, 0, IN8.L4 - 0.03),
                  xwidth="dbl_hgap_param", yheight=0.10)

        emit_monitor_group(instrument, 'Detector PSD')

        # Single 3He detector, maximum opening 42 mm (w) x 89 mm (h) (ILL).
        detector = instrument.add_component("detector", "Monitor", AT=[0, 0, IN8.L4],
                                            ROTATED=[0, 0, 0], RELATIVE="detector_arm")
        detector.xwidth = 0.042
        detector.yheight = 0.089

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
