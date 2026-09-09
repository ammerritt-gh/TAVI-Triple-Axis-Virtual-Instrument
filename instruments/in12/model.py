"""IN12 (ILL) McStas instrument definition.

The third TAVI instrument, built on the IN8 template: the TAS state base class,
the per-point snapshot pipeline, and the run layer are all shared with
``instruments/tas_runtime.py``. What lives here is only what is genuinely
IN12's:

- ``IN12_Instrument``: geometry, the confirmed scattering senses (-1, +1, -1),
  Rowland-matched point-source focusing with the published mechanical radius
  clamps, and the per-point parameter dict.
- ``build_IN12_instrument``: the component tree, emitted through the shared
  helpers in ``tavi/instrument_helpers.py`` wherever a category exists there
  (monitors, crystals, collimators, slits, sample + orientation arms); the
  literal remainder is the source block, the axis arms, and the detector.

Model boundary: the source is an *effective* source at the H144 guide exit,
1.8 m upstream of the monochromator. The ~115 m of H144 above it -- including
the velocity selector (>36 m upstream) and the transmission polarising cavity
(~35 m upstream) -- is not modeled. Neither is the optional cooled Be filter:
the source emits a band around E0, so there are no higher orders for a
suppressor to remove, and inserting one would only attenuate. See
``MODEL_STATUS.md``.

Values marked PLACEHOLDER affect intensity/resolution only, never angles.
"""
import math

import mcstasscript as ms

from instruments.in12.plugin import ANA_FIXED_RV
from instruments.paths import COMPONENTS_DIR
from instruments.tas_runtime import (
    TAS_Instrument,
    compute_scan_snapshot,  # noqa: F401  (re-export: the IN12 plugin's snapshot path)
    run_tas_point,  # noqa: F401  (re-export: the IN12 plugin's run path)
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
# match the descriptor's mcstas_name (instruments/in12/plugin.py).
MCSTAS_NAME = "IN12_McScript"
data_dir = COMPONENTS_DIR

# Published mechanical bending limits (2016): the monochromator's horizontal
# curvature is continuously adjustable from ~1.7 m radius to flat, and its
# vertical curvature from ~0.5 m to flat. "To flat" is an unbounded radius, so
# only the minima clamp. With L1 = L2 = 1.8 m the ideal RH never reaches 1.7 m
# at any Bragg angle, so that limit does not bind today -- it is kept because it
# is the real hardware envelope and would start to matter if L1/L2 ever moved.
# The vertical limit does bind, above roughly |A1| = 32 deg (ki > ~3.7 A^-1).
# No analyser radius limits are published; its fixed vertical radius
# (``ANA_FIXED_RV``, imported from the descriptor) is not a limit but hardware.
MONO_MIN_RH = 1.7
MONO_MIN_RV = 0.5


def _clamp_radius(radius, minimum):
    """Clamp |radius| up to a mechanical minimum, preserving the branch sign."""
    if radius == 0 or abs(radius) >= minimum:
        return radius
    return math.copysign(minimum, radius)


class IN12_Instrument(TAS_Instrument):
    """IN12 instrument state: ILL-current geometry plus provisional senses."""

    def __init__(self, diagnostic_mode=False, diagnostic_settings=None):
        super().__init__()
        self.L1 = 1.80   # H144 guide exit (virtual source) - mono (ILL)
        self.L2 = 1.80   # mono - sample (2016: matched to L1 for Rowland focusing)
        self.L3 = 1.30   # sample - analyzer (ILL "about 1.3 m"; genuinely variable)
        self.L4 = 0.72   # analyzer - detector (ILL)
        # Senses (-1, +1, -1) -- the "W" configuration, confirmed on three
        # independent sources (ILL's entirely negative mono travel, the public
        # Takin preset's 0/1/0 senses, and a post-upgrade IN12 configuration
        # reported as SM=-1/SS=+1/SA=-1). See the descriptor Geometry in
        # instruments/in12/plugin.py and MODEL_STATUS.md.
        self.sense_mono = -1
        self.sense_sample = 1
        self.sense_ana = -1
        # Effective source = the H144 guide exit after the final 8 m focusing
        # nose: 20 mm wide x 140 mm high (2016).
        self.guide_exit_width = 0.020
        self.guide_exit_height = 0.140
        # Single-value collimation slots (arcmin; 0 = open). IN12 has four:
        # unlike IN8 it can take an optional Soller in the guide-exit section.
        self.alpha_1 = 0
        self.alpha_2 = 0
        self.alpha_3 = 0
        self.alpha_4 = 0
        # Slit gaps (m; PLACEHOLDER defaults, runtime-scannable parameters).
        self.sbl_wgap = 0.030
        self.sbl_hgap = 0.060
        self.dbl_hgap = 0.050
        # Crystal bending (m; 0 = flat). Factors of 1 = optimal focusing.
        self.rhmfac = 1
        self.rvmfac = 1
        self.rhafac = 1
        self.rhm = 0
        self.rvm = 0
        self.rha = 0
        self.rva = 0
        # Energy half-spread for the Mono source (meV). Narrower than IN8's 3:
        # IN12 is cold, with a 2.1-42 meV incident range.
        self.source_dE = 2
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_settings = diagnostic_settings if diagnostic_settings else {}

    def crystal_info(self, monocris, anacris):
        from instruments.in12.plugin import in12_descriptor

        return crystal_info_from_descriptor(in12_descriptor(), monocris, anacris)

    def calculate_crystal_bending(self, rhmfac, rvmfac, rhafac, mth, ath):
        """Ideal bending radii for IN12's focusing crystals.

        Point-source formulas at the monochromator (the H144 exit at L1 is a
        real focal point -- the virtual source the 2016 upgrade was built
        around), so RH = 2/sin(theta)/(1/L1 + 1/L2) and RV = 2*sin(theta)/(1/L1
        + 1/L2). With L1 = L2 = 1.8 m this is the Rowland condition the
        instrument was designed to satisfy.

        Only rha is driven at the analyzer. Its vertical focus is fixed
        hardware -- 1998 describes it as produced by permanently tilting the
        top and bottom crystal rows -- so rva returns the fixed radius
        (``ANA_FIXED_RV``) on the take-off branch rather than a computed one.
        It is deliberately not the Rowland optimum: that is what "fixed" means.

        The radii are SIGNED: theta arrives signed (IN12's A1 *and* A4 are both
        negative), and ``Monochromator_curved`` needs the curvature center on
        the scattering side -- feeding a positive radius to a negative take-off
        branch defocuses by ~7 orders of magnitude in peak intensity (measured
        on IN8 in the Phase-4 smoke run). Magnitudes are clamped up to the
        published mechanical minima; the analyzer has no published limits.
        """
        sin_mth = math.sin(math.radians(mth))
        sin_ath = math.sin(math.radians(ath))
        mono_focus = 1 / (1 / self.L1 + 1 / self.L2)
        ana_focus = 1 / (1 / self.L3 + 1 / self.L4)

        rhm = _clamp_radius(rhmfac * 2 * mono_focus / sin_mth, MONO_MIN_RH)
        rvm = _clamp_radius(rvmfac * 2 * mono_focus * sin_mth, MONO_MIN_RV)
        rha = rhafac * 2 * ana_focus / sin_ath
        rva = math.copysign(ANA_FIXED_RV, sin_ath)

        print(f"\nrhm: {rhm:.2f} rvm: {rvm:.2f} rha: {rha:.2f} rva: {rva:.2f}")
        return rhm, rvm, rha, rva

    def build_point_params(self, deltaE):
        """Build the runtime parameter snapshot for one instrument point.

        Keys mirror instruments/in12/plugin.py::_IN12_PARAMS exactly.
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


def build_IN12_instrument(in12_config, diagnostic_mode, diagnostic_settings, number_neutrons):
    """Build an IN12 instrument object for repeated per-point execution."""

    IN12 = in12_config

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

    monochromator_info, analyzer_info = IN12.crystal_info(IN12.monocris, IN12.anacris)

    from instruments.in12.plugin import _IN12_MONITORS
    from tavi.sample_library import default_sample_library

    monitor = {m.id: m for m in _IN12_MONITORS}
    enabled_monitors = diagnostic_settings if diagnostic_mode else {}

    def emit_monitor_group(instrument, *ids):
        emit_monitors(instrument, [monitor[i] for i in ids], enabled_monitors)

    def configure_component_tree():

        origin = instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])

        ## guide exit to monochromator

        mono_width = monochromator_info['slabwidth'] * monochromator_info['ncolumns'] \
            + monochromator_info['gap'] * (monochromator_info['ncolumns'] - 1)
        mono_height = monochromator_info['slabheight'] * monochromator_info['nrows'] \
            + monochromator_info['gap'] * (monochromator_info['nrows'] - 1)

        # The source sits AT the H144 guide exit, which the 2016 upgrade made
        # the instrument's virtual source: a 20 x 140 mm aperture 1.8 m from
        # the monochromator. Everything upstream (115 m of guide, the velocity
        # selector, the polarising cavity) is outside the model boundary.
        source = instrument.add_component("source", "Source_div_Maxwellian_v2")
        source.xwidth = IN12.guide_exit_width
        source.yheight = IN12.guide_exit_height
        source.focus_aw = 2 * math.degrees(math.atan(mono_width / 2 / IN12.L1))
        source.focus_ah = 2 * math.degrees(math.atan(mono_height / 2 / IN12.L1))
        if IN12.source_type == "Mono":
            source.energy_distribution = 0  # Uniform energy distribution
            source.dE = IN12.source_dE
            source.E0 = "E0_param"
        else:  # Maxwellian
            source.energy_distribution = 2  # Maxwellian energy distribution
            source.dE = 2                   # cold instrument: narrower than IN8's 3 meV
            source.E0 = "E0_param"
        source.divergence_distribution = 0

        emit_monitor_group(instrument, 'Source EMonitor', 'Source PSD')

        # Optional Soller in the short guide-exit -> monochromator section
        # (divergence 0 = open). PLACEHOLDER position/length/aperture; the
        # clear aperture is set to the guide exit envelope.
        emit_collimator(instrument, "mono_collimator", relative="origin",
                        at=(0, 0, IN12.L1 / 2), divergence=IN12.alpha_1, length=0.2,
                        xwidth=0.03, yheight=0.15)

        ## monochromator section

        emit_crystal_assembly(instrument, cradle_name="mono_cradle",
                              crystal_name="monochromator", relative="origin",
                              distance=IN12.L1, rotation_expr="A1_param/2",
                              info=monochromator_info, d_key='dm',
                              rv_param="rvm_param", rh_param="rhm_param",
                              split=2, extend="if(!SCATTERED) ABSORB;")

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0, 0, IN12.L1],
                                              RELATIVE="origin", ROTATED=[0, "A1_param", 0])

        # PLACEHOLDER position/aperture for the alpha_2 Soller.
        emit_collimator(instrument, "sample_collimator", relative="sample_arm",
                        at=(0, 0, IN12.L2 / 2), divergence=IN12.alpha_2, length=0.2,
                        xwidth=0.06, yheight=0.16)

        emit_slit(instrument, "sample_slit", relative="sample_arm",
                  at=(0, 0, IN12.L2 - 0.25),
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
                                                    distance=IN12.L2)

        # Mount the selected sample from the shared library (samples move
        # between instruments; tavi/sample_library.py).
        sample_key = getattr(IN12, 'sample_key', None)
        sample_spec = next(
            (s for s in default_sample_library() if s.id == sample_key), None
        )
        if sample_spec is not None and sample_spec.component_type is not None:
            emit_sample(instrument, sample_spec, relative=sample_mount)
        else:
            print("Warning: No sample selected for instrument run; running without sample component.")

        ## analyzer

        analyzer_arm = instrument.add_component("analyzer_arm", "Arm", AT=[0, 0, IN12.L2],
                                                ROTATED=[0, "A2_param", 0], RELATIVE="sample_arm")

        # No permanent filter: IN12's higher-order suppression is the velocity
        # selector, far upstream of the model boundary, and the optional cooled
        # Be filter is not modeled (see the module docstring).
        emit_collimator(instrument, "analyzer_collimator", relative="analyzer_arm",
                        at=(0, 0, 0.65), divergence=IN12.alpha_3, length=0.2,
                        xwidth=0.06, yheight=0.14)

        emit_crystal_assembly(instrument, cradle_name="analyzer_cradle",
                              crystal_name="analyzer", relative="analyzer_arm",
                              distance=IN12.L3, rotation_expr="A4_param/2",
                              info=analyzer_info, d_key='da',
                              rv_param="rva_param", rh_param="rha_param",
                              split=5)

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0, 0, IN12.L3],
                                                ROTATED=[0, "A4_param", 0], RELATIVE="analyzer_arm")

        emit_collimator(instrument, "detector_collimator", relative="detector_arm",
                        at=(0, 0, 0.3), divergence=IN12.alpha_4, length=0.15,
                        xwidth=0.06, yheight=0.13)

        emit_slit(instrument, "detector_slit", relative="detector_arm",
                  at=(0, 0, IN12.L4 - 0.03),
                  xwidth="dbl_hgap_param", yheight=0.13)

        emit_monitor_group(instrument, 'Detector PSD')

        # Single vertical 3He tube: ~12 cm active height, ~5 cm diameter (ILL).
        detector = instrument.add_component("detector", "Monitor", AT=[0, 0, IN12.L4],
                                            ROTATED=[0, 0, 0], RELATIVE="detector_arm")
        detector.xwidth = 0.050
        detector.yheight = 0.120

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
