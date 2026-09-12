"""PANDA (MLZ) McStas instrument definition.

The third TAVI instrument. As with IN8, the TAS state base class, the per-point
snapshot pipeline and the run layer are shared with
``instruments/tas_runtime.py``; what lives here is only what is genuinely
PANDA's:

- ``PANDA_Instrument``: geometry, the negative-monochromator scattering senses
  (-1, +1, -1), the split focusing formula that uses PANDA's horizontal virtual
  source, and the per-point parameter dict.
- ``build_PANDA_instrument``: the component tree, emitted through the shared
  helpers in ``tavi/instrument_helpers.py`` wherever a category exists there;
  the literal remainder is the source block, the axis arms and the detector.

The model starts at the SR-2 guide exit and simulates the primary spectrometer
from there: primary Soller, horizontal virtual source, monochromator. Guide
transport upstream of that plane is not simulated -- see the L1 note in
``instruments/panda/plugin.py``.

Values marked PLACEHOLDER affect intensity/resolution only, never angles.
"""
import math

import mcstasscript as ms

from instruments.paths import COMPONENTS_DIR
from instruments.tas_runtime import (
    TAS_Instrument,
    compute_scan_snapshot,  # noqa: F401  (re-export: the PANDA plugin's snapshot path)
    run_tas_point,  # noqa: F401  (re-export: the PANDA plugin's run path)
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
# match the descriptor's mcstas_name (instruments/panda/plugin.py).
MCSTAS_NAME = "PANDA_McScript"
data_dir = COMPONENTS_DIR


class PANDA_Instrument(TAS_Instrument):
    """PANDA instrument state: MLZ-current geometry and the vPANDA senses."""

    def __init__(self, diagnostic_mode=False, diagnostic_settings=None):
        super().__init__()
        self.L1 = 5.00   # SR-2 guide exit - mono (vPANDA model coordinate)
        self.L2 = 2.10   # mono - sample (vPANDA / 2016 guide study; 2007 & 2014 models: 2.15)
        self.L3 = 1.05   # sample - analyzer
        self.L4 = 0.95   # analyzer - detector
        # Horizontal virtual source (ms1) - mono. PANDA's defining primary
        # optic and the real horizontal object distance for the monochromator.
        self.l_virtual_source_mono = self.L1 - 2.180
        # vPANDA scatsense_mono/sample/ana; see the descriptor Geometry in
        # instruments/panda/plugin.py. Unlike PUMA and IN8, the monochromator
        # take-off is NEGATIVE.
        self.sense_mono = -1
        self.sense_sample = 1
        self.sense_ana = -1
        # Source aperture = the SR-2 guide exit (vPANDA NL_SR2_3 exit face).
        self.guide_exit_width = 0.107
        self.guide_exit_height = 0.138
        # Single-value collimation slots (arcmin; 0 = open). PANDA has a
        # primary collimator ahead of the monochromator, so alpha_1 exists.
        self.alpha_1 = 0
        self.alpha_2 = 0
        self.alpha_3 = 0
        self.alpha_4 = 0
        # Motorized apertures (m; runtime-scannable parameters). vPANDA
        # defaults: ms1 40 mm, ss1/ss2 40 x 80 mm.
        self.ms1_wgap = 0.040
        self.ss1_wgap = 0.040
        self.ss1_hgap = 0.080
        self.ss2_wgap = 0.040
        self.ss2_hgap = 0.080
        # Crystal bending (m; 0 = flat).
        self.rhm = 0
        self.rvm = 0
        self.rha = 0
        self.rva = 0
        # Energy half-spread for the Mono source (meV). 1, not IN8's 2: the
        # same E0 - dE > 0 guard applies, and PANDA runs down to E0 = 2.28 meV.
        self.source_dE = 1
        self.diagnostic_mode = diagnostic_mode
        self.diagnostic_settings = diagnostic_settings if diagnostic_settings else {}

    def crystal_info(self, monocris, anacris):
        from instruments.panda.plugin import panda_descriptor

        return crystal_info_from_descriptor(panda_descriptor(), monocris, anacris)

    def descriptor(self):
        from instruments.panda.plugin import panda_descriptor

        return panda_descriptor()

    def curvature_object_distances(self, modules=None):
        """PANDA's monochromator does not share an object distance between its
        two focusing planes: horizontally it images the virtual source ms1
        (2.82 m upstream) onto the sample -- the whole point of PANDA's
        primary optics; vertically there is no virtual source, so the guide
        exit at L1 is the object. The analyser keeps the base point-source
        pair (the sample is a real source on both planes)."""
        distances = dict(super().curvature_object_distances(modules=modules))
        distances["mono_h"] = (self.l_virtual_source_mono, self.L2)
        distances["mono_v"] = (self.L1, self.L2)
        return distances

    def build_point_params(self, deltaE):
        """Build the runtime parameter snapshot for one instrument point.

        Keys mirror instruments/panda/plugin.py::_PANDA_PARAMS exactly.
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
            "ms1_wgap_param": self.ms1_wgap,
            "ss1_wgap_param": self.ss1_wgap,
            "ss1_hgap_param": self.ss1_hgap,
            "ss2_wgap_param": self.ss2_wgap,
            "ss2_hgap_param": self.ss2_hgap,
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


def build_PANDA_instrument(panda_config, diagnostic_mode, diagnostic_settings,
                           number_neutrons):
    """Build a PANDA instrument object for repeated per-point execution."""

    PANDA = panda_config

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
    # Motorized aperture parameters (scannable)
    instrument.add_parameter("ms1_wgap_param", comment="Horizontal virtual source width (m).")
    instrument.add_parameter("ss1_wgap_param", comment="Pre-sample slit horizontal gap (m).")
    instrument.add_parameter("ss1_hgap_param", comment="Pre-sample slit vertical gap (m).")
    instrument.add_parameter("ss2_wgap_param", comment="Sample exit slit horizontal gap (m).")
    instrument.add_parameter("ss2_hgap_param", comment="Sample exit slit vertical gap (m).")

    monochromator_info, analyzer_info = PANDA.crystal_info(PANDA.monocris, PANDA.anacris)

    from instruments.panda.plugin import _PANDA_MONITORS
    from tavi.sample_library import default_sample_library

    monitor = {m.id: m for m in _PANDA_MONITORS}
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

        # The source sits AT the SR-2 guide exit / beam-port reference plane
        # with the guide's exit aperture, illuminating the full monochromator
        # face at L1. Everything the real guide does upstream of this plane is
        # folded into the Maxwellian spectrum.
        source = instrument.add_component("source", "Source_div_Maxwellian_v2")
        source.xwidth = PANDA.guide_exit_width
        source.yheight = PANDA.guide_exit_height
        source.focus_aw = 2 * math.degrees(math.atan(mono_width / 2 / PANDA.L1))
        source.focus_ah = 2 * math.degrees(math.atan(mono_height / 2 / PANDA.L1))
        if PANDA.source_type == "Mono":
            source.energy_distribution = 0  # Uniform energy distribution
            source.dE = PANDA.source_dE
            source.E0 = "E0_param"
        else:  # Maxwellian
            source.energy_distribution = 2  # Maxwellian energy distribution
            # Source_div_Maxwellian_v2 aborts in INITIALIZE when E0 - dE <= 0
            # (components/Source_div_Maxwellian_v2.comp), and in Maxwellian mode
            # dE is not sampled -- it only scales p_init. PANDA is COLD: its
            # published floor kf = 1.05 A^-1 is E0 = 2.28 meV, so IN8's thermal
            # dE = 3 would kill a routine cold run at initialization. 1 meV
            # clears the guard down to k = 0.69 A^-1 and, being constant, adds
            # no spurious energy trend across a scan that moves E0_param.
            source.dE = 1
            source.E0 = "E0_param"
        source.divergence_distribution = 0

        emit_monitor_group(instrument, 'Source EMonitor', 'Source PSD')

        # Primary Soller (ca1), 0.50 m long, 0.10 m past the guide exit.
        # Automatic changer on the real instrument; open (0) withdraws it
        # from the beam and emits no component.
        emit_collimator(instrument, "primary_collimator", relative="origin",
                        at=(0, 0, 0.10), divergence=PANDA.alpha_1, length=0.50,
                        xwidth=0.108, yheight=0.160)

        # The horizontal virtual source (ms1): a variable-width slit 2.180 m
        # past the guide exit. This is what the monochromator images
        # horizontally onto the sample.
        emit_slit(instrument, "virtual_source", relative="origin",
                  at=(0, 0, PANDA.L1 - PANDA.l_virtual_source_mono),
                  xwidth="ms1_wgap_param", yheight=0.180)

        ## monochromator section

        emit_crystal_assembly(instrument, cradle_name="mono_cradle",
                              crystal_name="monochromator", relative="origin",
                              distance=PANDA.L1, rotation_expr="A1_param/2",
                              info=monochromator_info, d_key='dm',
                              rv_param="rvm_param", rh_param="rhm_param",
                              split=2, extend="if(!SCATTERED) ABSORB;",
                              order=1)

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0, 0, PANDA.L1],
                                              RELATIVE="origin", ROTATED=[0, "A1_param", 0])

        # Second Soller (ca2), 0.20 m long at 0.90 m from the monochromator
        # (vPANDA PANDA_ca2). Open (0) withdraws it from the beam.
        emit_collimator(instrument, "sample_collimator", relative="sample_arm",
                        at=(0, 0, 0.90), divergence=PANDA.alpha_2, length=0.20,
                        xwidth=0.040, yheight=0.120)

        # Sample entrance slit ss1, 1.70 m from the monochromator (vPANDA).
        emit_slit(instrument, "sample_slit", relative="sample_arm",
                  at=(0, 0, 1.70),
                  xwidth="ss1_wgap_param", yheight="ss1_hgap_param")

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
                                                    distance=PANDA.L2)

        # Mount the selected sample from the shared library (samples move
        # between instruments; tavi/sample_library.py).
        sample_key = getattr(PANDA, 'sample_key', None)
        sample_spec = next(
            (s for s in default_sample_library() if s.id == sample_key), None
        )
        if sample_spec is not None and sample_spec.component_type is not None:
            emit_sample(instrument, sample_spec, relative=sample_mount)
        else:
            print("Warning: No sample selected for instrument run; running without sample component.")

        ## analyzer

        analyzer_arm = instrument.add_component("analyzer_arm", "Arm", AT=[0, 0, PANDA.L2],
                                                ROTATED=[0, "A2_param", 0], RELATIVE="sample_arm")

        # Sample exit slit ss2, 0.40 m past the sample (vPANDA PANDA_ss2).
        emit_slit(instrument, "sample_exit_slit", relative="analyzer_arm",
                  at=(0, 0, 0.40),
                  xwidth="ss2_wgap_param", yheight="ss2_hgap_param")

        # Third Soller (ca3) at L3 - 0.55 m (vPANDA PANDA_ca3).
        emit_collimator(instrument, "analyzer_collimator", relative="analyzer_arm",
                        at=(0, 0, PANDA.L3 - 0.55), divergence=PANDA.alpha_3, length=0.20,
                        xwidth=0.040, yheight=0.140)

        # No analyzer-side filter. PANDA's PG / cold-Be / BeO filters remove
        # higher-order contamination, and this model has no contamination to
        # remove -- not because a single-Q reflection cannot produce it (it
        # can: Monochromator_curved with order=0 transports every multiple of
        # the supplied reciprocal-lattice vector), but because both crystals
        # are pinned to order=1. That is an idealized, order-clean
        # spectrometer, and it is what MODEL_STATUS.md records; a broadband
        # model with real filters is the alternative, not a free upgrade.
        emit_crystal_assembly(instrument, cradle_name="analyzer_cradle",
                              crystal_name="analyzer", relative="analyzer_arm",
                              distance=PANDA.L3, rotation_expr="A4_param/2",
                              info=analyzer_info, d_key='da',
                              rv_param="rva_param", rh_param="rha_param",
                              split=5, order=1)

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0, 0, PANDA.L3],
                                                ROTATED=[0, "A4_param", 0], RELATIVE="analyzer_arm")

        # Fourth Soller (ca4) at 0.410 m past the analyzer (vPANDA PANDA_ca4).
        emit_collimator(instrument, "detector_collimator", relative="detector_arm",
                        at=(0, 0, 0.41), divergence=PANDA.alpha_4, length=0.20,
                        xwidth=0.040, yheight=0.140)

        emit_monitor_group(instrument, 'Detector PSD')

        # The 1" high-pressure 3He tube used in the focusing configuration:
        # 25 mm wide, ~100 mm active height (teaching notes; the 2" tube used
        # with collimation is not a selectable option yet).
        detector = instrument.add_component("detector", "Monitor", AT=[0, 0, PANDA.L4],
                                            ROTATED=[0, 0, 0], RELATIVE="detector_arm")
        detector.xwidth = 0.025
        detector.yheight = 0.100

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
