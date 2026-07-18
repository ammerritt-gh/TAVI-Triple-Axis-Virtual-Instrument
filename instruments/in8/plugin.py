"""IN8 (ILL) as an ``InstrumentPlugin`` -- the second registered instrument.

The thermal three-axis spectrometer IN8 at the ILL, modeled as a plain
single-analyzer/single-detector TAS (FlatCone and IMPS multiplexing are
deferred; design record §14). Geometry and hardware values come from three
sources, recorded per field below:

- "vTAS": the ILL vTAS reference (``examples/vTAS/vtas_reference/
  instruments_repository.xml``) -- axis limits and scattering senses.
  NOTE the senses here are from the user's live vTAS run (2026-07-02):
  SM +1 / SS +1 / SA -1, which overrides the stale repository XML values.
- "ILL": the IN8 characteristics page (current Thermes hardware) -- arm
  lengths, crystal faces, collimators, detector aperture.
- "paper": Hiess et al. 2006 / Piovano & Ivanov 2023 in ``instruments/in8/references/`` --
  virtual source, crystal slab subdivision.

Placeholder values that need instrument-scientist input are marked
"PLACEHOLDER" (they affect intensity/resolution, never angles).

IMPORT-LIGHT RULE (same as instruments/puma/plugin.py): the top level imports
nothing heavier than ``instruments.descriptor``; every reference to the heavy
``instruments.in8.model`` is function-local. Guarded by
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

IN8_ID = "in8"
IN8_DISPLAY_NAME = "IN8 (ILL)"

# Must equal in8.model.MCSTAS_NAME (asserted by
# tests/test_in8_plugin.py); duplicated to preserve the import-light rule.
IN8_MCSTAS_NAME = "IN8_McScript"

# Arm lengths (m): ILL-current Thermes values (virtual source->mono 2280 mm,
# mono->sample 2480, sample->analyser 1050, analyser->detector 700). These
# deliberately deviate from the vTAS reference (2.5/1.35/0.65) -- distances
# never affect angles, and the running simulation should match today's
# hardware. Design record §20.
_L1, _L2, _L3, _L4 = 2.28, 2.48, 1.05, 0.70

# The full McStas parameter set build_IN8_instrument declares via
# add_parameter() -- the per-point snapshot dict shape. 16 shared core TAS
# parameters + IN8's bending and slit extras (no velocity selector, no NMO).
_IN8_PARAMS = (
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
    # Sample-orientation / mount hierarchy (generic TAS; shared with PUMA).
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

# Minimal diagnostic set: source pair, sample-position trio, detector PSD.
# Positions are PLACEHOLDER (sensible beam-order spots, not surveyed hardware);
# ids double as the diagnostic-settings keys and dialog labels.
_IN8_MONITORS = (
    MonitorSpec("Source EMonitor", "E_monitor", (0.0, 0.0, 0.10), "origin",
                settings={"xwidth": 0.06, "yheight": 0.15, "nE": 100, "Emin": -2,
                          "Emax": 200, "restore_neutron": 1},
                component_name="source_Emonitor"),
    MonitorSpec("Source PSD", "PSD_monitor", (0.0, 0.0, 0.11), "origin",
                settings={"xwidth": 0.045, "yheight": 0.18, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="source_PSD"),
    MonitorSpec("Sample PSD @ Sample", "PSD_monitor", (0.0, 0.0, _L2 - 0.03), "sample_arm",
                settings={"xwidth": 0.10, "yheight": 0.10, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_PSD"),
    MonitorSpec("Sample DSD @ Sample", "Divergence_monitor", (0.0, 0.0, _L2 - 0.02), "sample_arm",
                settings={"xwidth": 0.1, "yheight": 0.1, "nh": 100, "nv": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_DSD"),
    MonitorSpec("Sample EMonitor @ Sample", "E_monitor", (0.0, 0.0, _L2 - 0.01), "sample_arm",
                settings={"xwidth": 0.2, "yheight": 0.2, "nE": 100, "Emin": -2,
                          "Emax": 200, "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample_Emonitor"),
    MonitorSpec("Detector PSD", "PSD_monitor", (0.0, 0.0, _L4 - 0.005), "detector_arm",
                settings={"xwidth": 0.05, "yheight": 0.11, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="detector_PSD"),
)


def in8_descriptor() -> InstrumentDescriptor:
    """ILL IN8 -- runnable descriptor (plain TAS; FlatCone/IMPS deferred)."""
    return InstrumentDescriptor(
        id=IN8_ID,
        display_name=IN8_DISPLAY_NAME,
        institute="ILL",
        geometry=Geometry(
            l1_source_mono=_L1,
            l2_mono_sample=_L2,
            l3_sample_ana=_L3,
            l4_ana_det=_L4,
            # Verified against a live vTAS run (2026-07-02): a2 positive, a4
            # positive, a6 NEGATIVE for the standard elastic configuration,
            # i.e. senses (+1, +1, -1). The vTAS repository XML records
            # ss=-1/sa=+1 -- stale; the live readout wins.
            sense_mono=Sense.LEFT,
            sense_sample=Sense.LEFT,
            sense_ana=Sense.RIGHT,
            sample_table_radius=0.3,           # vTAS str
        ),
        mono_crystals=(
            # PG002 double-focusing face: 11x11 = 121 crystals of 25x17 mm
            # (paper 2023: mosaic faces ~290x200 mm), mosaic 30' (ILL).
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.025, slab_height=0.017, n_columns=11, n_rows=11,
                gap=0.0015, mosaic=30, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
            # Cu200 face, same subdivision (paper 2023). No stock McStas
            # reflectivity data for Cu: constant r0 with the McStas "NULL"
            # sentinel (= no file). Mosaic is actually anisotropic 25'/10'
            # (ILL); PLACEHOLDER isotropic 25' and r0=0.7 until measured
            # values are available.
            CrystalSpec(
                id="cu200", display_name="Cu[200]", d_spacing=1.807,
                slab_width=0.025, slab_height=0.017, n_columns=11, n_rows=11,
                gap=0.0015, mosaic=25, r0=0.7,
                reflect_file="NULL", transmit_file="NULL",
            ),
            # Si111/Si311 bent-perfect faces exist on IN8 but cannot be
            # represented by the mosaic Monochromator_curved model; deferred.
        ),
        ana_crystals=(
            # Thermes PG002 analyzer, active area ~180x140 mm (ILL).
            # PLACEHOLDER subdivision 9x7 of 20x20 mm slabs (~184x143 mm).
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.02, slab_height=0.02, n_columns=9, n_rows=7,
                gap=0.0005, mosaic=30, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
        ),
        # Samples come from the shared, instrument-independent library --
        # samples move between instruments (tavi/sample_library.py, §19).
        samples=default_sample_library(),
        scannable_parameters=_IN8_PARAMS,
        primary_detector="detector",
        mcstas_name=IN8_MCSTAS_NAME,
        monitors=_IN8_MONITORS,
        # No NMO, no velocity selector; FlatCone/IMPS deferred -> no modules.
        modules=(),
        # Soller collimators 20'/30'/40' (+60' on the secondary spectrometer);
        # IN8 normally runs open with double focusing, hence default "0".
        # There is no alpha_1 slot: the primary collimation sits after the mono.
        collimation=(
            CollimationSlot("alpha_2", "α2 (mono-smp)", ("0", "20", "30", "40", "60"),
                            default="0"),
            CollimationSlot("alpha_3", "α3 (smp-ana)", ("0", "20", "30", "40", "60"),
                            default="0"),
            CollimationSlot("alpha_4", "α4 (ana-det)", ("0", "20", "30", "40", "60"),
                            default="0"),
        ),
        # PLACEHOLDER apertures.
        slits=(
            SlitSpec("sbl", "Pre-sample (W×H)", has_height=True,
                     default_width_mm=40, default_height_mm=100),
            SlitSpec("dbl_hgap", "Detector (width)", default_width_mm=40),
        ),
        source_types=(
            SourceType("Maxwellian", "Maxwellian"),
            SourceType("Mono", "Mono", extra_params=("source_dE",)),
        ),
        # vTAS a2/a4/a6 mechanical limits; defaults are the standard elastic
        # Al (2,0,0) configuration at kf = 2.662 (signs per verified senses).
        axis_limits={
            "A1": AxisLimits(-40.0, 41.19, 110.0),
            "A2": AxisLimits(-120.0, 71.30, 120.0),
            "A4": AxisLimits(-120.0, -41.19, 120.0),
        },
        # Vertical (out-of-plane) Soller divergences BET1..4 (arcmin, FWHM). IN8's
        # secondary spectrometer carries no surveyed per-blade vertical Soller
        # data; 120 arcmin is a documented uniform default (recorded as such in
        # the resolution adapter's provenance).
        vertical_divergence=(120.0, 120.0, 120.0, 120.0),
    )


class IN8Plugin:
    """``InstrumentPlugin`` implementation for IN8."""

    id = IN8_ID
    display_name = IN8_DISPLAY_NAME

    def descriptor(self):
        return in8_descriptor()

    def default_state(self):
        """Fresh ``IN8_Instrument`` with IN8's defaults."""
        from instruments.in8.model import IN8_Instrument

        return IN8_Instrument()

    def scan_config(self, base_state, gui_values, sample_key, diagnostic_settings,
                    sample_mount):
        """Create a scan-local IN8 configuration from frozen launch state.

        Much smaller than PUMA's mapping: no NMO, no velocity selector, no
        stacked alpha_2 list -- each collimation slot is a single selection.
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
        # center must sit on the take-off side, and IN8's analyzer take-off is
        # the negative branch (sense_ana = -1). The GUI carries magnitudes;
        # the branch sign is instrument physics, applied here. (Wrong sign =
        # ~7 orders of magnitude peak loss; measured in the Phase-4 smoke.)
        scan_config.rhm = abs(vals['rhm'])       # mono take-off: +1 branch
        scan_config.rvm = abs(vals['rvm'])
        scan_config.rha = -abs(vals['rha'])      # analyzer take-off: -1 branch
        # PLACEHOLDER magnitude: vertical analyzer curvature held at the
        # point-source value for kf = 2.662 (Thermes is variable
        # double-focusing).
        scan_config.rva = -0.31
        scan_config.sample_key = sample_key
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

        return crystal_info_from_descriptor(in8_descriptor(), mono_label, ana_label)

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
        from instruments.in8.model import build_IN8_instrument

        return build_IN8_instrument(
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
        """Return ``(feasible, reason)`` for one scan point (see contract).

        IN8 shares PUMA's TAS angle math, so this delegates to the same shared
        feasibility helper (which reuses the per-point ``compute_snapshot``
        solve). Used by the remote API's always-on scan validation.
        """
        from instruments.tas_runtime import check_point_feasibility

        return check_point_feasibility(
            config, scan_mode, scan_point, vals,
            axis_limits=in8_descriptor().axis_limits,
        )

    def resolution_config(self, vals, q0, w):
        """Build a theoretical-resolution config for IN8 (see contract).

        Pure function of the descriptor + ``vals``; imports no mcstasscript. IN8
        has no NMO and no velocity selector, so no invalidations arise from
        modules; a monochromatic source still warns. IN8's collimation has no
        alpha_1 slot (open primary) -> the adapter substitutes 60 arcmin for it
        with a recorded warning.
        """
        from instruments.resolution_adapter import build_resolution_config

        return build_resolution_config(in8_descriptor(), vals, q0, w)
