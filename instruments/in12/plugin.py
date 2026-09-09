"""IN12 (ILL) as an ``InstrumentPlugin`` -- the third registered instrument.

The cold three-axis spectrometer IN12 (CRG-B, operated by JCNS/Forschungszentrum
Jülich with CEA Grenoble) on the ILL H144 guide, modeled in its conventional
post-2012 configuration: H144 virtual source, doubly focusing 11x11 PG(002)
monochromator, sample, horizontally focusing PG(002) (or Heusler(111)) analyser,
one vertical 3He tube. Sources, recorded per field below:

- "ILL": the current IN12 characteristics and instrument-layout pages -- axis
  limits, arm lengths, crystal faces, collimators, detector, operating envelope.
  Re-checked 2026-09-09 (``references/2026-09-09__ill-in12-web-status__v01.md``).
- "2016": Schmalzl et al., NIM A 819 (2016) 89-98, the upgrade paper
  (``references/2016-01-01__schmalzl-in12-upgrade__v01.md``) -- guide, virtual
  source, monochromator array/mosaic/curvature, flux and resolution.
- "2001": a historical IN12 raw scan header (dossier §14) -- secondary senses,
  practical mosaics, vertical Soller divergences.

Two things are NOT verified and are the model's real risk:

- **Senses are provisional (-1, +1, -1).** The monochromator's -1 branch is
  strongly established (ILL publishes the mono two-theta range as -140°..-10°,
  re-confirmed 2026-09-09). Sample +1 and analyser -1 come from a 2001 scan
  header and the fact that the 2012 upgrade retained the secondary spectrometer;
  they predate the upgrade and no modern readback has been obtained. IN8's
  senses were only settled by a live vTAS run -- IN12 wants the same treatment.
- **Slab geometry is derived, not published.** No source gives individual PG
  crystal sizes or gaps for either assembly; the values here divide the
  published overall face by the blade count with a nominal 1.5 mm gap.

Placeholder values that need instrument-scientist input are marked
"PLACEHOLDER" (they affect intensity/resolution, never angles).

IMPORT-LIGHT RULE (same as instruments/in8/plugin.py): the top level imports
nothing heavier than ``instruments.descriptor``; every reference to the heavy
``instruments.in12.model`` is function-local. Guarded by
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
    Geometry,
    InstrumentDescriptor,
    MonitorSpec,
    ParameterSpec,
    Sense,
    SlitSpec,
    SourceType,
)
from tavi.sample_library import default_sample_library

IN12_ID = "in12"
IN12_DISPLAY_NAME = "IN12 (ILL)"

# Must equal in12.model.MCSTAS_NAME (asserted by
# tests/test_in12_plugin.py); duplicated to preserve the import-light rule.
IN12_MCSTAS_NAME = "IN12_McScript"

# Arm lengths (m). L1 = H144 guide exit -> monochromator (ILL: 1.8 m); the
# guide exit IS the virtual source, so the ~115 m of H144 upstream of it is
# outside the model boundary. L2 = 1.8 m matches L1 by design (2016: the
# Rowland condition for the double-focusing mono). L3 ~ 1.3 m and L4 = 0.72 m
# are the ILL-current secondary values. L3 is described as variable but no
# source gives its limits, so it is fixed here (see MODEL_STATUS.md).
_L1, _L2, _L3, _L4 = 1.80, 1.80, 1.30, 0.72

# Overall monochromator face, 2016: 20 cm wide x 16 cm high (an ILL table
# swaps the labels; the paper's orientation is used -- the 16 cm vertical
# height is what the guide-exit optimisation was built around).
_MONO_FACE_W, _MONO_FACE_H = 0.200, 0.160
# Conventional PG analyser face, ILL: 12.2 x 11.8 cm.
_ANA_FACE_W, _ANA_FACE_H = 0.122, 0.118
# PLACEHOLDER slab gap; no source publishes it. Slab sizes below are the
# published face divided by the blade count with this gap removed -- they are
# pitch minus gap, NOT measured crystal dimensions.
_SLAB_GAP = 0.0015


def _slab_size(face, count, gap=_SLAB_GAP):
    """Per-slab dimension implied by an overall face, blade count, and gap."""
    return (face - gap * (count - 1)) / count


# H144 guide exit (2016): 20 mm wide x 140 mm high after the final 8 m
# focusing nose (vertical opening 105 -> 140 mm, horizontal 45 -> 20 mm).
_GUIDE_EXIT_W, _GUIDE_EXIT_H = 0.020, 0.140

# The full McStas parameter set build_IN12_instrument declares via
# add_parameter() -- the per-point snapshot dict shape. Identical in shape to
# IN8's: IN12 has no velocity selector or NMO inside the model boundary.
_IN12_PARAMS = (
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
    ParameterSpec("sbl_wgap_param", "Pre-sample slit horizontal gap", unit="m"),
    ParameterSpec("sbl_hgap_param", "Pre-sample slit vertical gap", unit="m"),
    ParameterSpec("dbl_hgap_param", "Detector slit horizontal gap", unit="m"),
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

# Minimal diagnostic set, same shape as IN8's: source pair, sample-position
# trio, detector PSD. Positions are PLACEHOLDER (sensible beam-order spots, not
# surveyed hardware); ids double as the diagnostic-settings keys and dialog
# labels. Apertures follow IN12's real envelopes (narrow tall guide exit, wide
# monochromator face) so the pictures are readable. Emin/Emax bracket IN12's
# published 2.1-42 meV incident range.
_IN12_MONITORS = (
    MonitorSpec("Source EMonitor", "E_monitor", (0.0, 0.0, 0.10), "origin",
                settings={"xwidth": 0.03, "yheight": 0.16, "nE": 100, "Emin": 0,
                          "Emax": 60, "restore_neutron": 1},
                component_name="source_Emonitor"),
    MonitorSpec("Source PSD", "PSD_monitor", (0.0, 0.0, 0.11), "origin",
                settings={"xwidth": 0.03, "yheight": 0.16, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="source_PSD"),
    MonitorSpec("Sample PSD @ Sample", "PSD_monitor", (0.0, 0.0, _L2 - 0.03), "sample_arm",
                settings={"xwidth": 0.08, "yheight": 0.08, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_PSD"),
    MonitorSpec("Sample DSD @ Sample", "Divergence_monitor", (0.0, 0.0, _L2 - 0.02), "sample_arm",
                settings={"xwidth": 0.08, "yheight": 0.08, "nh": 100, "nv": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_DSD"),
    MonitorSpec("Sample EMonitor @ Sample", "E_monitor", (0.0, 0.0, _L2 - 0.01), "sample_arm",
                settings={"xwidth": 0.15, "yheight": 0.15, "nE": 100, "Emin": 0,
                          "Emax": 60, "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_Emonitor"),
    MonitorSpec("Detector PSD", "PSD_monitor", (0.0, 0.0, _L4 - 0.005), "detector_arm",
                settings={"xwidth": 0.06, "yheight": 0.13, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="detector_PSD"),
)


def in12_descriptor() -> InstrumentDescriptor:
    """ILL IN12 -- runnable descriptor (conventional single-detector config).

    IN12-UFO (the fifteen-channel multi-analyser) is deliberately absent: ILL's
    own instrument-layout page still describes it in the future tense ("will be
    equipped with"), and no publication between 2016 and 2026 reports it
    commissioned (web status check, 2026-09-09). Multi-analyser secondary
    spectrometers are out of scope for v1 anyway
    (``docs/CONFIGURABLE_INSTRUMENTS.md`` §14) -- the same call already made for
    IN8's FlatCone/IMPS.
    """
    return InstrumentDescriptor(
        id=IN12_ID,
        display_name=IN12_DISPLAY_NAME,
        institute="ILL",
        geometry=Geometry(
            l1_source_mono=_L1,
            l2_mono_sample=_L2,
            l3_sample_ana=_L3,
            l4_ana_det=_L4,
            # PROVISIONAL (-1, +1, -1) -- see the module docstring. The mono
            # sits on the clockwise/negative branch: ILL publishes its
            # two-theta range as -140°..-10°, which no other TAVI instrument
            # does, so IN12 is the first exerciser of sense_mono = -1.
            sense_mono=Sense.RIGHT,
            sense_sample=Sense.LEFT,
            sense_ana=Sense.RIGHT,
            sample_table_radius=0.35,        # 2010 vTAS IN12 repository entry
        ),
        mono_crystals=(
            # 2016: PG(002), 11 columns x 11 rows over a 200 x 160 mm face,
            # mosaic 0.4 deg FWHM = 24 arcmin, 2.0 mm thick crystals on B4C +
            # aluminium backing (the backing is not modeled). Slab sizes are
            # face/count minus the PLACEHOLDER gap -- not published.
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=_slab_size(_MONO_FACE_W, 11),
                slab_height=_slab_size(_MONO_FACE_H, 11),
                n_columns=11, n_rows=11,
                gap=_SLAB_GAP, mosaic=24, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
        ),
        ana_crystals=(
            # Conventional analyser: PG(002), ILL face 122 x 118 mm. The 2012
            # upgrade retained the secondary spectrometer, so the historical
            # official McStas wrapper's 11 horizontal blades x 1 vertical row
            # (WA 0.121 / HA 0.118, near-identical to today's published face)
            # is carried forward. Mosaic 30 arcmin is the 2001 scan header's
            # ETAA -- PLACEHOLDER for a post-upgrade measurement.
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=_slab_size(_ANA_FACE_W, 11),
                slab_height=_ANA_FACE_H,      # one vertical row: no vertical gap
                n_columns=11, n_rows=1,
                gap=_SLAB_GAP, mosaic=30, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
            # Polarisation-analysis analyser: Heusler(111), d = 3.44 A, ILL
            # face 75 x 145 mm. TAVI models no polarisation, so this changes
            # the kinematics (d-spacing -> A4) and nothing else. Blade count,
            # mosaic and reflectivity are all PLACEHOLDER: no source gives
            # them, and the 2016 paper and the ILL page even disagree on
            # whether it focuses vertically or horizontally (MODEL_STATUS.md).
            # No stock McStas reflectivity data for Heusler -> constant r0 via
            # the "NULL" sentinel, at the ~0.3 typical of a Heusler face.
            CrystalSpec(
                id="heusler111", display_name="Heusler[111]", d_spacing=3.44,
                slab_width=_slab_size(0.075, 5),
                slab_height=0.145,
                n_columns=5, n_rows=1,
                gap=_SLAB_GAP, mosaic=30, r0=0.3,
                reflect_file="NULL", transmit_file="NULL",
            ),
        ),
        # Samples come from the shared, instrument-independent library --
        # samples move between instruments (tavi/sample_library.py, §19).
        samples=default_sample_library(),
        scannable_parameters=_IN12_PARAMS,
        primary_detector="detector",
        mcstas_name=IN12_MCSTAS_NAME,
        monitors=_IN12_MONITORS,
        # No selector or filter inside the model boundary -- see MODEL_STATUS.md.
        modules=(),
        # ILL: Gd-coated Soller collimators 10'/20'/30'/40'/60'/80', mountable
        # before the sample, between sample and analyser, and between analyser
        # and detector. IN12 also accepts an optional Soller in the short
        # guide-exit -> monochromator section, so unlike IN8 there IS an
        # alpha_1 slot. Nothing is permanently installed: the H144 exit plus
        # the focusing monochromator define the primary phase space, so every
        # slot defaults to open.
        collimation=tuple(
            CollimationSlot(slot_id, label,
                            ("0", "10", "20", "30", "40", "60", "80"), default="0")
            for slot_id, label in (
                ("alpha_1", "α1 (guide-mono)"),
                ("alpha_2", "α2 (mono-smp)"),
                ("alpha_3", "α3 (smp-ana)"),
                ("alpha_4", "α4 (ana-det)"),
            )
        ),
        # PLACEHOLDER apertures: IN12 has diaphragms before the monochromator
        # and around the sample, but no source gives their openings. Defaults
        # bracket the intended 2 x 3 cm focused spot at the sample and the
        # 50 mm detector tube.
        slits=(
            SlitSpec("sbl", "Pre-sample (W×H)", has_height=True,
                     default_width_mm=30, default_height_mm=60),
            SlitSpec("dbl_hgap", "Detector (width)", default_width_mm=50),
        ),
        source_types=(
            SourceType("Maxwellian", "Maxwellian"),
            SourceType("Mono", "Mono", extra_params=("source_dE",)),
        ),
        # ILL mechanical limits. The monochromator range is the signed evidence
        # for sense_mono = -1: it is entirely negative. Defaults are the
        # standard elastic Al (2,0,0) configuration at k = 2.0 A^-1 (E = 8.29
        # meV), the wavevector the 2016 flux figures are quoted at.
        axis_limits={
            "A1": AxisLimits(-140.0, -55.834469, -10.0),
            "A2": AxisLimits(-120.0, 101.737423, 120.0),
            "A4": AxisLimits(-140.0, -55.834469, 140.0),
        },
        # Vertical (out-of-plane) Soller divergences BET1..4 (arcmin, FWHM).
        # The 2001 IN12 scan header records BET1 = BET2 = BET3 = BET4 = 120'.
        vertical_divergence=(120.0, 120.0, 120.0, 120.0),
    )


class IN12Plugin:
    """``InstrumentPlugin`` implementation for IN12."""

    id = IN12_ID
    display_name = IN12_DISPLAY_NAME

    def descriptor(self):
        return in12_descriptor()

    def default_state(self):
        """Fresh ``IN12_Instrument`` with IN12's defaults."""
        from instruments.in12.model import IN12_Instrument

        return IN12_Instrument()

    def scan_config(self, base_state, gui_values, sample_key, diagnostic_settings,
                    sample_mount):
        """Create a scan-local IN12 configuration from frozen launch state.

        Same shape as IN8's, with two IN12 differences: a fourth collimation
        slot (alpha_1, in the guide-exit section) and a monochromator on the
        negative take-off branch, so BOTH mono radii are negated here.
        """
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
        # Curvature radii are signed by the scattering branch: the curvature
        # center must sit on the take-off side. IN12 takes off NEGATIVE at both
        # crystals (sense_mono = sense_ana = -1), so all three driven radii are
        # negative -- the first TAVI instrument whose monochromator is on the
        # negative branch. The GUI carries magnitudes; the branch sign is
        # instrument physics, applied here. (Wrong sign = ~7 orders of
        # magnitude peak loss; measured on IN8 in the Phase-4 smoke.)
        scan_config.rhm = -abs(vals['rhm'])
        scan_config.rvm = -abs(vals['rvm'])
        scan_config.rha = -abs(vals['rha'])
        # The conventional analyser is a single vertical row of blades, so it
        # has no vertical focusing to drive -- ILL lists its vertical curvature
        # as fixed. Flat.
        scan_config.rva = 0.0
        scan_config.sample_key = sample_key
        scan_config.alpha_1 = float(collimation['alpha_1'])
        scan_config.alpha_2 = float(collimation['alpha_2'])
        scan_config.alpha_3 = float(collimation['alpha_3'])
        scan_config.alpha_4 = float(collimation['alpha_4'])
        sbl_width_mm, sbl_height_mm = slits_mm['sbl']
        scan_config.sbl_wgap = sbl_width_mm / 1000.0
        scan_config.sbl_hgap = sbl_height_mm / 1000.0
        scan_config.dbl_hgap = slits_mm['dbl_hgap'] / 1000.0
        scan_config.sample_mount = sample_mount
        scan_config.update_diagnostic_settings(diagnostic_settings)
        return scan_config

    def crystal_info(self, mono_label, ana_label):
        from tavi.instrument_helpers import crystal_info_from_descriptor

        return crystal_info_from_descriptor(in12_descriptor(), mono_label, ana_label)

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
        from instruments.in12.model import build_IN12_instrument

        return build_IN12_instrument(
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
            axis_limits=in12_descriptor().axis_limits,
        )

    def resolution_config(self, vals, q0, w):
        """Build a theoretical-resolution config for IN12 (see contract).

        Pure function of the descriptor + ``vals``; imports no mcstasscript.
        IN12 has no modules, so no invalidations arise from them; a
        monochromatic source still warns. Unlike IN8, IN12 does declare an
        alpha_1 slot, so the adapter substitutes nothing for the primary
        collimation.
        """
        from instruments.resolution_adapter import build_resolution_config

        return build_resolution_config(in12_descriptor(), vals, q0, w)
