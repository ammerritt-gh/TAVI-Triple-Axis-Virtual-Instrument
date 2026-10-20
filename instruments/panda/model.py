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
from there: primary Soller, horizontal virtual source, monochromator. An
experimental velocity selector can be inserted after the primary Soller. Guide
transport upstream of that plane is not simulated -- see the L1 note in
``instruments/panda/plugin.py``.

Values marked PLACEHOLDER affect intensity/resolution only, never angles.
"""
import math

import mcstasscript as ms

from instruments.paths import COMPONENTS_DIR
from tavi.quantities import crystal_theta
from instruments.tas_runtime import (
    TAS_Instrument,
    add_source,
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
        self.reset_source()
        # Experimental velocity selector (module "v_selector"); off by default.
        self.V_selector_installed = False
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
        return {
            "mono_two_theta_param": self.mono_two_theta_deg,
            "sample_two_theta_param": self.sample_two_theta_deg,
            "sample_rotation_param": self.sample_rotation_deg,
            "analyzer_two_theta_param": self.analyzer_two_theta_deg,
            "mono_theta_param": crystal_theta(self.mono_two_theta_deg),
            "analyzer_theta_param": crystal_theta(self.analyzer_two_theta_deg),
            "E0_param": self.e0_param_value(deltaE),
            "nu_param": self.v_selector_frequency(deltaE),
            "rhm_param": self.rhm,
            "rvm_param": self.rvm,
            "rha_param": self.rha,
            "rva_param": self.rva,
            "ms1_wgap_param": self.ms1_wgap,
            "ss1_wgap_param": self.ss1_wgap,
            "ss1_hgap_param": self.ss1_hgap,
            "ss2_wgap_param": self.ss2_wgap,
            "ss2_hgap_param": self.ss2_hgap,
            **self.source_point_params(),
            **self.sample_orientation_params(),
        }


def build_PANDA_instrument(panda_config, diagnostic_mode, diagnostic_settings,
                           number_neutrons):
    """Build a PANDA instrument object for repeated per-point execution."""

    PANDA = panda_config

    instrument = ms.McStas_instr(MCSTAS_NAME, input_path=data_dir)
    instrument.settings(output_path="./output", openacc=False)

    ## Add parameters
    instrument.add_parameter("mono_two_theta_param", comment="Monochromator 2-theta angle.")
    instrument.add_parameter("sample_two_theta_param", comment="Sample 2-theta angle.")
    instrument.add_parameter("sample_rotation_param", comment="Sample rotation (turntable) readout, inspection only.")
    instrument.add_parameter("analyzer_two_theta_param", comment="Analyzer 2-theta angle.")
    instrument.add_parameter("mono_theta_param", comment="Monochromator crystal theta (rotation).")
    instrument.add_parameter("analyzer_theta_param", comment="Analyzer crystal theta (rotation).")
    instrument.add_parameter("E0_param", comment="Flat-band centre energy (meV); read only in flat-band mode.")
    instrument.add_parameter("nu_param", comment="Velocity selector frequency.")
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
    # Crystal-face monitors track the SELECTED crystal's slab geometry, as
    # PUMA's do; the descriptor's PG(002) sizes are only the no-override default.
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

        origin = instrument.add_component("origin", "Progress_bar", AT=[0, 0, 0])

        ## guide exit to monochromator

        mono_width = monochromator_info['slabwidth'] * monochromator_info['ncolumns'] \
            + monochromator_info['gap'] * (monochromator_info['ncolumns'] - 1)
        mono_height = monochromator_info['slabheight'] * monochromator_info['nrows'] \
            + monochromator_info['gap'] * (monochromator_info['nrows'] - 1)

        # The source sits AT the SR-2 guide exit / beam-port reference plane
        # with the guide's exit aperture, illuminating the full monochromator
        # face at L1. The guide is not modelled: the source emits the
        # moderator's spectrum at this plane.
        add_source(instrument, PANDA.guide_exit_width, PANDA.guide_exit_height,
                   2 * math.degrees(math.atan(mono_width / 2 / PANDA.L1)),
                   2 * math.degrees(math.atan(mono_height / 2 / PANDA.L1)))

        emit_monitor_group(instrument, 'Source EMonitor', 'Source PSD')

        # Primary Soller (ca1), 0.50 m long, 0.10 m past the guide exit.
        # Automatic changer on the real instrument; open (0) withdraws it
        # from the beam and emits no component.
        emit_collimator(instrument, "primary_collimator", relative="origin",
                        at=(0, 0, 0.10), divergence=PANDA.alpha_1, length=0.50,
                        xwidth=0.108, yheight=0.160)

        # Experimental: PANDA has no velocity selector in this position. It sits
        # after the primary Soller (which stays at its real 0.10-0.60 m), housing
        # 0.645-0.955 m; its 40 mm window clips about 70% of the 138 mm guide-exit height.
        if PANDA.V_selector_installed:
            v_selector = instrument.add_component("v_selector", "V_selector",
                                                  AT=[0, 0, 0.80], RELATIVE="origin")
            v_selector.xwidth = 0.100
            v_selector.yheight = 0.040
            v_selector.zdepth = 0.310
            v_selector.radius = 0.290
            v_selector.length = 0.25
            v_selector.d = 0.004
            v_selector.nslit = 72
            v_selector.alpha = 48.3
            v_selector.nu = "nu_param"

        emit_monitor_group(instrument, 'Source DSD')

        # The horizontal virtual source (ms1): a variable-width slit 2.180 m
        # past the guide exit. This is what the monochromator images
        # horizontally onto the sample.
        emit_slit(instrument, "virtual_source", relative="origin",
                  at=(0, 0, PANDA.L1 - PANDA.l_virtual_source_mono),
                  xwidth="ms1_wgap_param", yheight=0.180)

        emit_monitor_group(instrument, 'Virtual source PSD', 'Virtual source DSD')

        emit_monitor_group(instrument, 'Premono PSD', 'Premono DSD', 'Premono Emonitor')

        ## monochromator section

        emit_crystal_assembly(instrument, cradle_name="mono_cradle",
                              crystal_name="monochromator", relative="origin",
                              distance=PANDA.L1, rotation_expr="mono_theta_param",
                              info=monochromator_info, d_key='dm',
                              rv_param="rvm_param", rh_param="rhm_param",
                              split=2, extend="if(!SCATTERED) ABSORB;")

        ## sample arm

        sample_arm = instrument.add_component("sample_arm", "Arm", AT=[0, 0, PANDA.L1],
                                              RELATIVE="origin", ROTATED=[0, "mono_two_theta_param", 0])

        emit_monitor_group(instrument, 'Postmono Emonitor', 'Pre-sample collimation PSD')

        # Second Soller (ca2), 0.20 m long at 0.90 m from the monochromator
        # (vPANDA PANDA_ca2). Open (0) withdraws it from the beam.
        emit_collimator(instrument, "sample_collimator", relative="sample_arm",
                        at=(0, 0, 0.90), divergence=PANDA.alpha_2, length=0.20,
                        xwidth=0.040, yheight=0.120)

        emit_monitor_group(instrument, 'Sample PSD @ L2-0.5')

        # Sample entrance slit ss1, 1.70 m from the monochromator (vPANDA).
        emit_slit(instrument, "sample_slit", relative="sample_arm",
                  at=(0, 0, 1.70),
                  xwidth="ss1_wgap_param", yheight="ss1_hgap_param")

        emit_monitor_group(instrument, 'Sample PSD @ L2-0.3', 'Sample PSD @ Sample',
                           'Sample DSD @ Sample', 'Sample EMonitor @ Sample')

        # Sample orientation (shared with every TAVI instrument): one
        # sample_mount Arm whose runtime rotation carries the goniometer at
        # its readout angles and the crystal mount; the arc readouts are
        # declared for inspection only.
        instrument.add_parameter("sgl_param", value=0, comment="Lower arc sgl readout")
        instrument.add_parameter("sgu_param", value=0, comment="Upper arc sgu readout")
        instrument.add_parameter("sample_rx_param", value=0, comment="Sample arm rotation about x (stage and mount)")
        instrument.add_parameter("sample_ry_param", value=0, comment="Sample arm rotation about y (stage and mount)")
        instrument.add_parameter("sample_rz_param", value=0, comment="Sample arm rotation about z (stage and mount)")

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
                                                ROTATED=[0, "sample_two_theta_param", 0], RELATIVE="sample_arm")

        # Sample exit slit ss2, 0.40 m past the sample (vPANDA PANDA_ss2).
        emit_slit(instrument, "sample_exit_slit", relative="analyzer_arm",
                  at=(0, 0, 0.40),
                  xwidth="ss2_wgap_param", yheight="ss2_hgap_param")

        emit_monitor_group(instrument, 'Pre-analyzer collimation PSD')

        # Third Soller (ca3) at L3 - 0.55 m (vPANDA PANDA_ca3).
        emit_collimator(instrument, "analyzer_collimator", relative="analyzer_arm",
                        at=(0, 0, PANDA.L3 - 0.55), divergence=PANDA.alpha_3, length=0.20,
                        xwidth=0.040, yheight=0.140)

        emit_monitor_group(instrument, 'Pre-analyzer EMonitor', 'Pre-analyzer PSD')

        # No analyzer-side filter. The real PANDA suppresses higher orders with
        # its PG / cold-Be / BeO filters and an unmodelled supermirror guide;
        # both crystals transport all orders (order=0, as PUMA does), so this
        # model's higher-order contamination overestimates the real one's.
        emit_crystal_assembly(instrument, cradle_name="analyzer_cradle",
                              crystal_name="analyzer", relative="analyzer_arm",
                              distance=PANDA.L3, rotation_expr="analyzer_theta_param",
                              info=analyzer_info, d_key='da',
                              rv_param="rva_param", rh_param="rha_param",
                              split=5)

        ## detector

        detector_arm = instrument.add_component("detector_arm", "Arm", AT=[0, 0, PANDA.L3],
                                                ROTATED=[0, "analyzer_two_theta_param", 0], RELATIVE="analyzer_arm")

        emit_monitor_group(instrument, 'Post-analyzer EMonitor', 'Post-analyzer PSD')

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
            force_compile=True,
            increment_folder_name=False,
            openacc=False,
        )

        return instrument

    return configure_component_tree()
