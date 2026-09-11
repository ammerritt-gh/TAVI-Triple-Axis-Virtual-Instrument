"""PANDA (MLZ) as an ``InstrumentPlugin`` -- the third registered instrument.

The cold three-axes spectrometer PANDA at beam tube SR-2 of the FRM II
(MLZ, Garching), modeled as a plain single-analyzer/single-detector TAS.
BAMBUS -- the multiplexed secondary spectrometer, "currently under
commissioning" per the MLZ page -- is multi-detector and deferred exactly as
IN8's FlatCone/IMPS are.

Sources, recorded per field below:

- "MLZ": the current MLZ PANDA instrument page, captured as
  ``references/2026-09-09__mlz-panda-page__v01.md`` -- crystal menu, ki/kf
  ranges, axis travel, energy/momentum reach, detectors.
- "dossier": ``references/2026-07-18__panda-instrument-research__v01.md``,
  which reconciles the 2007 overview, the 2016 guide-optimization paper, the
  2015 instrument paper, the PANDA teaching notes and the instrument team's
  public McStas repository. Where two sources disagree it states which to
  prefer; those rulings are quoted at the field that uses them.
- "vPANDA": ``references/2026-07-03__vpanda-mcstas__v01.instr``, used for
  relative component placement and parameter naming only. Its known defects
  (sapphire thickness, stale analyzer array, zero focusing defaults) are
  listed in ``MODEL_STATUS.md`` and are NOT inherited here.

Values that still need instrument-scientist input are marked "PLACEHOLDER"
(they affect intensity/resolution, never angles).

IMPORT-LIGHT RULE (same as instruments/in8/plugin.py): the top level imports
nothing heavier than ``instruments.descriptor``; every reference to the heavy
``instruments.panda.model`` is function-local. Guarded by
``tests/test_instrument_registry.py::test_listing_is_lazy_no_mcstas_import``.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

import copy

from instruments.contract import DEFAULT_MPI_COUNT
from instruments.descriptor import (
    AxisLimits,
    CollimationSlot,
    CrystalSpec,
    CurvatureAxis,
    Geometry,
    InstrumentDescriptor,
    MonitorSpec,
    ParameterSpec,
    Sense,
    SlitSpec,
    SourceType,
)
from tavi.sample_library import default_sample_library

PANDA_ID = "panda"
PANDA_DISPLAY_NAME = "PANDA (MLZ)"

# Must equal panda.model.MCSTAS_NAME (asserted by
# tests/test_panda_plugin.py); duplicated to preserve the import-light rule.
PANDA_MCSTAS_NAME = "PANDA_McScript"

# Arm lengths (m).
#
# L1 is measured from the SR-2 guide exit / beam-port reference plane, which is
# where this model places its source: vPANDA puts the monochromator 5.000 m
# downstream of that plane. The published *physical* source-monochromator
# distance is ~7.8 m (2007 overview, 2015 instrument paper, 2016 guide paper)
# and the McStas models place the mono at ~8.81 m of model coordinate; the
# dossier records that discrepancy as unresolved and warns against silently
# adopting either number. Starting at the guide exit sidesteps it: everything
# upstream of that plane is beam transport this model does not simulate, and
# distances never affect angles.
#
# L2 = 2.10 m follows vPANDA and the 2016 guide study's "available distance";
# the 2007 and 2014 models say 2.15 m. Unresolved -- see MODEL_STATUS.md.
_L1, _L2, _L3, _L4 = 5.00, 2.10, 1.05, 0.95

# The horizontal virtual source (the ms1 aperture) sits at guide-exit +2.180 m,
# i.e. 2.82 m ahead of the monochromator. That is the real horizontal object
# distance for the monochromator's horizontal focusing and PANDA's defining
# primary optic; it is not a Geometry field, so the state class owns it
# (PANDA_Instrument.l_virtual_source_mono).

# Curvature: no minimum or maximum radius is applied for either crystal.
# MODEL_STATUS.md records this as confirmed absent from the literature, not
# merely unlocated -- the 2007 report confirms driven focusing existed but
# gives no travel, and inventing a clamp would be worse than applying none.
_PANDA_MONO_CURVATURE = {
    "rhm": CurvatureAxis(driven=True),
    "rvm": CurvatureAxis(driven=True),
}
_PANDA_ANA_CURVATURE = {
    "rha": CurvatureAxis(driven=True),
    # Fixed vertical / variable horizontal focusing is confirmed for THIS
    # assembly by two peer-reviewed PANDA papers (one ties the fixed vertical
    # geometry to the vertically oriented 1" 3He detector) and by the MLZ page
    # advertising only variable horizontal focusing. The RADIUS is still
    # unsourced -- only the fixedness is.
    "rva": CurvatureAxis(
        driven=False, fixed_radius_m=0.60,
        provenance=(
            "Fixedness confirmed by two peer-reviewed PANDA papers and the "
            "MLZ page (variable horizontal focusing advertised, vertical "
            "not); the 0.60 m radius is our own point-focus value for "
            "kf = 1.55 A^-1, not a sourced mechanical figure (MODEL_STATUS.md)."
        ),
    ),
}

# The full McStas parameter set build_PANDA_instrument declares via
# add_parameter() -- the per-point snapshot dict shape. The 16 shared core TAS
# parameters plus PANDA's bending and its three motorized apertures.
_PANDA_PARAMS = (
    ParameterSpec("A1_param", "Monochromator 2-theta angle"),
    ParameterSpec("A2_param", "Sample 2-theta angle"),
    ParameterSpec("A3_param", "Sample phi angle"),
    ParameterSpec("A4_param", "Analyzer 2-theta angle"),
    ParameterSpec("E0_param", "Source energy for monochromatic source", unit="meV"),
    ParameterSpec("saz_param", "Sample azimuthal angle (out-of-plane)"),
    ParameterSpec("rhm_param", "Monochromator horizontal bending"),
    ParameterSpec("rvm_param", "Monochromator vertical bending"),
    ParameterSpec("rha_param", "Analyzer horizontal bending"),
    ParameterSpec("rva_param", "Analyzer vertical bending"),
    ParameterSpec("ms1_wgap_param", "Horizontal virtual source width", unit="m"),
    ParameterSpec("ss1_wgap_param", "Pre-sample slit horizontal gap", unit="m"),
    ParameterSpec("ss1_hgap_param", "Pre-sample slit vertical gap", unit="m"),
    ParameterSpec("ss2_wgap_param", "Sample exit slit horizontal gap", unit="m"),
    ParameterSpec("ss2_hgap_param", "Sample exit slit vertical gap", unit="m"),
    # Sample-orientation / mount hierarchy (generic TAS; shared with PUMA/IN8).
    ParameterSpec("chi_param", "User chi - out-of-plane tilt", default=0.0),
    ParameterSpec("kappa_param", "Kappa - chi alignment offset", default=0.0),
    ParameterSpec("mis_chi_param", "Hidden chi misalignment (training)", default=0.0),
    ParameterSpec("psi_param", "Psi - omega alignment offset", default=0.0),
    ParameterSpec("mis_omega_param", "Hidden omega misalignment (training)", default=0.0),
    ParameterSpec("chi_total", "Total chi = chi + kappa + mis_chi", default=0.0),
    ParameterSpec("omega_offset_total", "Total omega offset = psi + mis_omega", default=0.0),
    ParameterSpec("mount_rx_param", "Static sample mount rotation about x", default=0.0),
    ParameterSpec("mount_ry_param", "Static sample mount rotation about y", default=0.0),
    ParameterSpec("mount_rz_param", "Static sample mount rotation about z", default=0.0),
)

_SAMPLE_REGION = ("sample_region",)

# Minimal diagnostic set (IN8's shape): guide-exit pair, sample-position trio,
# detector PSD. Apertures follow vPANDA's monitor windows where it has one;
# positions are sensible beam-order spots, not surveyed hardware.
# The energy window spans PANDA's whole reach: Cu111 at ki = 7 A^-1 is ~101 meV.
_PANDA_MONITORS = (
    MonitorSpec("Source EMonitor", "E_monitor", (0.0, 0.0, 0.10), "origin",
                settings={"xwidth": 0.11, "yheight": 0.14, "nE": 100, "Emin": -2,
                          "Emax": 120, "restore_neutron": 1},
                component_name="source_Emonitor"),
    MonitorSpec("Source PSD", "PSD_monitor", (0.0, 0.0, 0.11), "origin",
                settings={"xwidth": 0.11, "yheight": 0.14, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="source_PSD"),
    MonitorSpec("Sample PSD @ Sample", "PSD_monitor", (0.0, 0.0, _L2 - 0.03), "sample_arm",
                settings={"xwidth": 0.10, "yheight": 0.20, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_PSD"),
    MonitorSpec("Sample DSD @ Sample", "Divergence_monitor", (0.0, 0.0, _L2 - 0.02), "sample_arm",
                settings={"xwidth": 0.1, "yheight": 0.2, "nh": 100, "nv": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_DSD"),
    MonitorSpec("Sample EMonitor @ Sample", "E_monitor", (0.0, 0.0, _L2 - 0.01), "sample_arm",
                settings={"xwidth": 0.2, "yheight": 0.2, "nE": 100, "Emin": -2,
                          "Emax": 120, "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_Emonitor"),
    MonitorSpec("Detector PSD", "PSD_monitor", (0.0, 0.0, _L4 - 0.005), "detector_arm",
                settings={"xwidth": 0.06, "yheight": 0.20, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="detector_PSD"),
)


def panda_descriptor() -> InstrumentDescriptor:
    """MLZ PANDA -- runnable descriptor (plain TAS; BAMBUS deferred)."""
    return InstrumentDescriptor(
        id=PANDA_ID,
        display_name=PANDA_DISPLAY_NAME,
        institute="MLZ",
        geometry=Geometry(
            l1_source_mono=_L1,
            l2_mono_sample=_L2,
            l3_sample_ana=_L3,
            l4_ana_det=_L4,
            # vPANDA declares scatsense_mono/sample/ana = -1/+1/-1, and the
            # dossier reports the 2014 team model reaching the same effective
            # tuple through its component rotations. PANDA is therefore the
            # first TAVI instrument whose *monochromator* take-off is negative.
            # Not yet confirmed against current NICOS motor signs -- see
            # SCIENTIST_REVIEW.md question 4.
            sense_mono=Sense.RIGHT,
            sense_sample=Sense.LEFT,
            sense_ana=Sense.RIGHT,
        ),
        mono_crystals=(
            # PG(002) double-focusing face: 11x11 pieces of 20x18 mm on a 2 mm
            # gap, mosaic 20' (consistent across every PANDA McStas
            # generation). The 121-crystal count is confirmed by the PANDA
            # teaching material ("121 monochromator (55 analyzer) crystals");
            # the piece size, gap and mosaic are simulation values with no
            # measurement behind them. The 2016 guide paper quotes nominal
            # 20x20 mm pieces; the 18 mm model height is kept because it is
            # what the reflecting area is modeled as.
            # PRE-SHUTDOWN: the 2024-25 restart reports describe a NEW
            # double-focusing PG(002) monochromator. Everything here describes
            # the unit the literature documents, not the replacement -- see
            # MODEL_STATUS.md, "The model describes pre-shutdown PANDA".
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.020, slab_height=0.018, n_columns=11, n_rows=11,
                gap=0.002, mosaic=20, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
                curvature=_PANDA_MONO_CURVATURE,
            ),
            # Cu(111), the second current monochromator (MLZ: ki = 1.8-7.0
            # A^-1, d quoted as 2.08 A; 2.087 A is the crystallographic value
            # for a = 3.6149 A, which rounds to 2.09 -- MLZ's 2.08 is
            # unexplained and is probably a legacy figure). The unit itself is
            # real: MLZ reported a Cu-111 monochromator from IPC/Goettingen
            # under commissioning in 2021. No stock McStas reflectivity data
            # for Cu, so
            # constant r0 with the "NULL" sentinel. Slab subdivision, mosaic
            # and r0 are PLACEHOLDERs carried over from the PG holder -- no
            # source describes the Cu array.
            CrystalSpec(
                id="cu111", display_name="Cu[111]", d_spacing=2.087,
                slab_width=0.020, slab_height=0.018, n_columns=11, n_rows=11,
                gap=0.002, mosaic=30, r0=0.7,
                reflect_file="NULL", transmit_file="NULL",
                curvature=_PANDA_MONO_CURVATURE,
            ),
            # Si(111) and the Heusler polarizing face are current PANDA
            # hardware but are deliberately absent: Si(111) is a bent-perfect
            # crystal that Monochromator_curved's mosaic model misrepresents
            # (same call as IN8's Si faces), and a Heusler entry would emit an
            # unpolarized beam under a polarizing label -- TAVI models no
            # spin-dependent transport. Both are recorded in MODEL_STATUS.md.
        ),
        ana_crystals=(
            # PG(002) focusing analyzer, 55 crystals of 13x25 mm on a 3 mm gap,
            # mosaic 20'. The 55-crystal COUNT is confirmed by the PANDA
            # teaching material in more than one revision, and supersedes
            # vPANDA's 13x6 = 78 (inherited from the 2007 model). The 11x5
            # arrangement, the piece size and the gap are the 2014 team model's
            # implementation detail and are unverified. No restart report says
            # this analyzer was replaced.
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.013, slab_height=0.025, n_columns=11, n_rows=5,
                gap=0.003, mosaic=20, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
                curvature=_PANDA_ANA_CURVATURE,
            ),
        ),
        # Samples come from the shared, instrument-independent library --
        # samples move between instruments (tavi/sample_library.py, §19).
        samples=default_sample_library(),
        scannable_parameters=_PANDA_PARAMS,
        primary_detector="detector",
        mcstas_name=PANDA_MCSTAS_NAME,
        monitors=_PANDA_MONITORS,
        # No NMO, no velocity selector; BAMBUS deferred -> no modules.
        modules=(),
        # Four Soller positions. Unlike IN8, PANDA does have a primary
        # collimator ahead of the monochromator (an automatic changer; the
        # downstream three are changed by hand). vPANDA represents "open" as a
        # 120' divergence that its WHEN clauses then gate out -- here open is
        # simply 0, which emit_collimator renders as an open aperture.
        collimation=(
            CollimationSlot("alpha_1", "α1 (primary)", ("0", "20", "40", "60"),
                            default="0"),
            CollimationSlot("alpha_2", "α2 (mono-smp)", ("0", "15", "40", "60"),
                            default="0"),
            CollimationSlot("alpha_3", "α3 (smp-ana)", ("0", "15", "40", "60"),
                            default="0"),
            CollimationSlot("alpha_4", "α4 (ana-det)", ("0", "15", "40", "60"),
                            default="0"),
        ),
        # PANDA's three motorized apertures, defaults from vPANDA (ms1 = 40 mm,
        # ss1/ss2 = 40 x 80 mm). ms1 is the horizontal virtual source itself.
        slits=(
            SlitSpec("ms1", "Virtual source (width)", default_width_mm=40),
            SlitSpec("ss1", "Pre-sample (W×H)", has_height=True,
                     default_width_mm=40, default_height_mm=80),
            SlitSpec("ss2", "Sample exit (W×H)", has_height=True,
                     default_width_mm=40, default_height_mm=80),
        ),
        source_types=(
            SourceType("Maxwellian", "Maxwellian"),
            SourceType("Mono", "Mono", extra_params=("source_dE",)),
        ),
        # Axis travel. A2/A4 are the current MLZ figures verbatim
        # (5 < 2ThetaS < 125 deg, -130 < 2ThetaA < 100 deg); A4's asymmetric
        # range is a signed instrument range, not a magnitude. A1 is the 2007
        # table's PG(002) range 20 < 2ThetaM < 132 deg carried onto the
        # negative branch that sense_mono = -1 puts the monochromator on.
        # Defaults are the standard cold elastic setting: kf = 1.55 A^-1 with
        # PG(002) (A1 = A4 = -74.332 deg, matching vPANDA's own mtt/att
        # defaults) and Al (1,1,1) at the sample.
        axis_limits={
            "A1": AxisLimits(-132.0, -74.332, -20.0),
            "A2": AxisLimits(5.0, 120.180, 125.0),
            "A4": AxisLimits(-130.0, -74.332, 100.0),
        },
    )


class PANDAPlugin:
    """``InstrumentPlugin`` implementation for PANDA."""

    id = PANDA_ID
    display_name = PANDA_DISPLAY_NAME

    def descriptor(self):
        return panda_descriptor()

    def default_state(self):
        """Fresh ``PANDA_Instrument`` with PANDA's defaults."""
        from instruments.panda.model import PANDA_Instrument

        return PANDA_Instrument()

    def scan_config(self, base_state, gui_values, sample_key, diagnostic_settings,
                    sample_mount):
        """Create a scan-local PANDA configuration from frozen launch state."""
        vals = gui_values
        collimation = vals['collimation']
        slits_mm = vals['slits_mm']

        scan_config = copy.deepcopy(base_state)
        scan_config.K_fixed = vals['K_fixed']
        scan_config.source_type = vals['source_type']
        scan_config.source_dE = vals['source_dE']
        scan_config.fixed_E = vals['fixed_E']
        scan_config.monocris = vals['monocris']
        scan_config.anacris = vals['anacris']
        # Curvature radii are plain magnitudes here: the branch sign (a
        # crystal's take-off side) and any fixed-axis/mechanical-limit policy
        # are enforced once, in TAS_Instrument.set_crystal_bending, the
        # boundary every path to the instrument state crosses. Signing here
        # too would be the exact duplicated-policy bug that boundary exists
        # to prevent.
        scan_config.rhm = vals['rhm']
        scan_config.rvm = vals['rvm']
        scan_config.rha = vals['rha']
        scan_config.rva = vals['rva']
        scan_config.sample_key = sample_key
        scan_config.alpha_1 = float(collimation['alpha_1'])
        scan_config.alpha_2 = float(collimation['alpha_2'])
        scan_config.alpha_3 = float(collimation['alpha_3'])
        scan_config.alpha_4 = float(collimation['alpha_4'])
        scan_config.ms1_wgap = slits_mm['ms1'] / 1000.0
        ss1_width_mm, ss1_height_mm = slits_mm['ss1']
        scan_config.ss1_wgap = ss1_width_mm / 1000.0
        scan_config.ss1_hgap = ss1_height_mm / 1000.0
        ss2_width_mm, ss2_height_mm = slits_mm['ss2']
        scan_config.ss2_wgap = ss2_width_mm / 1000.0
        scan_config.ss2_hgap = ss2_height_mm / 1000.0
        scan_config.sample_mount = sample_mount
        scan_config.update_diagnostic_settings(diagnostic_settings)
        return scan_config

    def crystal_info(self, mono_label, ana_label):
        from tavi.instrument_helpers import crystal_info_from_descriptor

        return crystal_info_from_descriptor(panda_descriptor(), mono_label, ana_label)

    def build_fingerprint(self, config, diagnostic_mode=False, diagnostic_settings=None):
        """Stable hash of the build-time (ChangeImpact.BUILD) state.

        Slit gaps and bending radii are runtime McStas parameters -- excluded.
        """
        import hashlib
        import json

        build_state = {
            "monocris": config.monocris,
            "anacris": config.anacris,
            "sample_key": getattr(config, "sample_key", None),
            "source_type": config.source_type,
            "source_dE": config.source_dE,
            "alpha_1": config.alpha_1,
            "alpha_2": config.alpha_2,
            "alpha_3": config.alpha_3,
            "alpha_4": config.alpha_4,
            "diagnostic_mode": bool(diagnostic_mode),
            "diagnostic_settings": sorted(
                (key, bool(value))
                for key, value in (diagnostic_settings or {}).items()
            ),
        }
        payload = json.dumps(build_state, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def build(self, config, diagnostic_mode, diagnostic_settings, number_neutrons):
        from instruments.panda.model import build_PANDA_instrument

        return build_PANDA_instrument(
            config, diagnostic_mode, diagnostic_settings, number_neutrons
        )

    def compute_snapshot(self, scan_item, scan_index, scan_mode, config, vals,
                         data_folder, *, is_2d_scan=False, variable_name1="",
                         variable_name2="", scan_command1="", scan_command2=""):
        from instruments.tas_runtime import compute_scan_snapshot

        return compute_scan_snapshot(
            scan_item, scan_index, scan_mode, config, vals, data_folder,
            is_2d_scan=is_2d_scan,
            variable_name1=variable_name1,
            variable_name2=variable_name2,
            scan_command1=scan_command1,
            scan_command2=scan_command2,
        )

    def run_point(self, instrument, snapshot, output_folder, number_neutrons,
                  execution_state, mpi_count=DEFAULT_MPI_COUNT):
        from instruments.tas_runtime import run_tas_point

        return run_tas_point(
            instrument, snapshot, output_folder, number_neutrons,
            execution_state, mpi_count,
        )

    def check_point_feasibility(self, config, scan_mode, scan_point, vals):
        """Return ``(feasible, reason)`` for one scan point (see contract)."""
        from instruments.tas_runtime import check_point_feasibility

        return check_point_feasibility(
            config, scan_mode, scan_point, vals,
            axis_limits=panda_descriptor().axis_limits,
        )

    def resolution_config(self, vals, q0, w):
        """Build a theoretical-resolution config for PANDA (see contract).

        Pure function of the descriptor + ``vals``; imports no mcstasscript.
        PANDA has no modules, so no module invalidations arise; a monochromatic
        source still warns. Unlike IN8 it does carry an alpha_1 slot, so no
        primary-collimation substitution is needed when one is selected.
        """
        from instruments.resolution_adapter import build_resolution_config

        return build_resolution_config(panda_descriptor(), vals, q0, w)
