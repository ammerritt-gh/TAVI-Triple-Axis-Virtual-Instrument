"""PUMA (FRM-II) as an ``InstrumentPlugin`` -- the first registered instrument.

Wraps the existing imperative implementation in
``instruments/PUMA_instrument_definition.py`` behind the contract of
``instruments/contract.py`` (Phase 1 of ``docs/CONFIGURABLE_INSTRUMENTS.md`` §17):
``build``/``compute_snapshot``/``run_point``/``default_state``/``crystal_info``
are thin delegations; ``scan_config`` carries the GUI->config mapping that used to
live in the controller's ``_build_scan_puma_config``.

IMPORT-LIGHT RULE: this module's top level must import nothing heavier than
``instruments.descriptor`` (no mcstasscript, no PySide6, and no
``instruments.PUMA_instrument_definition``, which imports mcstasscript at module
level). Every reference to the heavy module is function-local so that listing
instruments in the registry stays cheap. Guarded by
``tests/test_instrument_registry.py::test_listing_is_lazy_no_mcstas_import``.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

import copy

from instruments.descriptor import (
    CollimationSlot,
    CrystalSpec,
    Geometry,
    InstrumentDescriptor,
    ModuleKind,
    ModuleSpec,
    MonitorSpec,
    ParameterSpec,
    Sense,
    SlitSpec,
    SourceType,
)
from tavi.sample_library import default_sample_library

PUMA_ID = "puma"
PUMA_DISPLAY_NAME = "PUMA (FRM-II)"

# Must equal PUMA_instrument_definition.MCSTAS_NAME (asserted by
# tests/test_puma_plugin.py); duplicated here because importing the heavy module
# to read one string would break the import-light rule.
PUMA_MCSTAS_NAME = "PUMA_McScript"

# The full McStas parameter set the builder declares via add_parameter() -- the
# per-point snapshot dict shape. Kept 1:1 with the add_parameter calls in
# PUMA_instrument_definition.py (asserted by
# tests/test_descriptor_validation.py::test_puma_build_declares_descriptor_params).
_PUMA_PARAMS = (
    ParameterSpec("A1_param", "Monochromator 2-theta angle"),
    ParameterSpec("A2_param", "Sample 2-theta angle"),
    ParameterSpec("A3_param", "Sample phi angle"),
    ParameterSpec("A4_param", "Analyzer 2-theta angle"),
    ParameterSpec("E0_param", "Source energy for monochromatic source", unit="meV"),
    ParameterSpec("nu_param", "Velocity selector frequency"),
    ParameterSpec("saz_param", "Sample azimuthal angle (out-of-plane)"),
    ParameterSpec("rhm_param", "Monochromator horizontal bending"),
    ParameterSpec("rvm_param", "Monochromator vertical bending"),
    ParameterSpec("rha_param", "Analyzer horizontal bending"),
    ParameterSpec("rva_param", "Analyzer vertical bending"),
    ParameterSpec("vbl_hgap_param", "Post-mono slit horizontal gap", unit="m"),
    ParameterSpec("pbl_hgap_param", "Pre-sample slit horizontal gap", unit="m"),
    ParameterSpec("pbl_vgap_param", "Pre-sample slit vertical gap", unit="m"),
    ParameterSpec("dbl_hgap_param", "Detector slit horizontal gap", unit="m"),
    # Sample-orientation / mount hierarchy (generic TAS; every TAVI instrument
    # using the shared sample-orientation arms declares these).
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


# Fixed PUMA geometry used to compute monitor placements numerically -- the
# build() z-expressions (L1-0.003, L2/4, L2-0.5, ...) are evaluated here so
# MonitorSpec.at stays plain floats.
_L1, _L2, _L3, _L4 = 2.150, 2.290, 0.880, 0.750
_HBL_HGAP, _HBL_VGAP = 78e-3, 150e-3            # source beam-tube gaps
_MONO_W, _MONO_H = 0.0202 * 13, 0.018 * 9       # pg002 mono slab extents (w*ncols, h*nrows)
_ANA_W, _ANA_H = 0.01 * 21, 0.0295 * 5          # pg002 analyzer slab extents

_SAMPLE_REGION = ("sample_region",)

# Diagnostic monitors, 1:1 with the diagnostic_settings gates in build()
# (anti-drift test: tests/test_descriptor_validation.py). Ids double as the
# diagnostic-settings keys and dialog labels. NOTE: build() has two pre-existing
# copy-paste bugs -- 'Postmono Emonitor' and 'Post-analyzer EMonitor' set the
# xwidth/yheight of the WRONG component -- the settings below record the
# INTENDED sizes; build() is fixed in Phase 3 when it loops over this table.
_PUMA_MONITORS = (
    MonitorSpec("Source EMonitor", "E_monitor", (0.0, 0.0, 0.144), "origin",
                settings={"xwidth": 0.2, "yheight": 0.2, "nE": 100, "Emin": -2,
                          "Emax": 200, "restore_neutron": 1},
                component_name="source_Emonitor"),
    MonitorSpec("Source PSD", "PSD_monitor", (0.0, 0.0, 0.145), "origin",
                settings={"xwidth": _HBL_HGAP * 1.5, "yheight": _HBL_VGAP * 1.5,
                          "nx": 100, "ny": 100, "restore_neutron": 1},
                component_name="source_PSD"),
    MonitorSpec("Source DSD", "Divergence_monitor", (0.0, 0.0, 0.924), "origin",
                settings={"xwidth": _HBL_HGAP * 1.5, "yheight": _HBL_VGAP * 1.5,
                          "nh": 100, "nv": 100, "restore_neutron": 1},
                component_name="source_DSD"),
    MonitorSpec("Postcollimation PSD", "PSD_monitor", (0.0, 0.0, _L1 - 0.003), "origin",
                settings={"xwidth": 0.05, "yheight": 0.25, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="postcollimation_PSD"),
    MonitorSpec("Postcollimation DSD", "Divergence_monitor", (0.0, 0.0, _L1 - 0.002), "origin",
                settings={"xwidth": 0.1, "yheight": 0.1, "nh": 100, "nv": 100,
                          "restore_neutron": 1},
                component_name="postcollimation_DSD"),
    MonitorSpec("Premono Emonitor", "E_monitor", (0.0, 0.0, _L1 - 0.001), "origin",
                settings={"xwidth": _MONO_W, "yheight": _MONO_H, "nE": 400,
                          "Emin": 0, "Emax": 200, "restore_neutron": 1},
                component_name="premono_Emonitor"),
    MonitorSpec("Postmono Emonitor", "E_monitor", (0.0, 0.0, 0.1), "sample_arm",
                settings={"xwidth": _MONO_W, "yheight": _MONO_H, "nE": 400,
                          "Emin": 0, "Emax": 200, "restore_neutron": 1},
                component_name="postmono_Emonitor"),
    MonitorSpec("Pre-sample collimation PSD", "PSD_monitor", (0.0, 0.0, _L2 / 4), "sample_arm",
                settings={"xwidth": 0.06, "yheight": 0.15, "nx": 200, "ny": 200,
                          "restore_neutron": 1},
                component_name="sample1_PSD"),
    MonitorSpec("Sample PSD @ L2-0.5", "PSD_monitor", (0.0, 0.0, _L2 - 0.5), "sample_arm",
                settings={"xwidth": 0.10, "yheight": 0.10, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample2_PSD"),
    MonitorSpec("Sample PSD @ L2-0.3", "PSD_monitor", (0.0, 0.0, _L2 - 0.3), "sample_arm",
                settings={"xwidth": 0.10, "yheight": 0.10, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                tags=_SAMPLE_REGION, component_name="sample3_PSD"),
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
    MonitorSpec("Pre-analyzer collimation PSD", "PSD_monitor", (0.0, 0.0, 0.49), "analyzer_arm",
                settings={"xwidth": 1.0, "yheight": 1.0, "nx": 200, "ny": 200,
                          "restore_neutron": 1},
                component_name="precollim_PSD"),
    MonitorSpec("Pre-analyzer EMonitor", "E_monitor", (0.0, 0.0, _L3 - 0.1), "analyzer_arm",
                settings={"xwidth": _ANA_W, "yheight": _ANA_H, "nE": 100,
                          "Emin": -2, "Emax": 30, "restore_neutron": 1},
                component_name="preanalyzer_Emonitor"),
    MonitorSpec("Pre-analyzer PSD", "PSD_monitor", (0.0, 0.0, _L3 - 0.1), "analyzer_arm",
                settings={"xwidth": _ANA_W, "yheight": _ANA_H, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="preanalyzer_PSD"),
    MonitorSpec("Post-analyzer EMonitor", "E_monitor", (0.0, 0.0, 0.1), "detector_arm",
                settings={"xwidth": _ANA_W, "yheight": _ANA_H, "nE": 100,
                          "Emin": -2, "Emax": 30, "restore_neutron": 1},
                component_name="postanalyzer_Emonitor"),
    MonitorSpec("Post-analyzer PSD", "PSD_monitor", (0.0, 0.0, 0.5), "detector_arm",
                settings={"xwidth": _ANA_W, "yheight": _ANA_H, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="postanalyzer_PSD"),
    MonitorSpec("Detector PSD", "PSD_monitor", (0.0, 0.0, _L4 - 0.005), "detector_arm",
                settings={"xwidth": 0.0254, "yheight": 1.0, "nx": 100, "ny": 100,
                          "restore_neutron": 1},
                component_name="detector_PSD"),
)


def puma_descriptor() -> InstrumentDescriptor:
    """PUMA (FRM-II) -- the GUI-facing knobs, fully specified.

    Values mirror ``PUMA_instrument_definition.py`` (crystal tables, geometry,
    modules) and the current ``gui/docks/instrument_dock.py`` option lists.
    """
    return InstrumentDescriptor(
        id=PUMA_ID,
        display_name=PUMA_DISPLAY_NAME,
        institute="FRM-II",
        geometry=Geometry(
            l1_source_mono=2.150,
            l2_mono_sample=2.290,
            l3_sample_ana=0.880,
            l4_ana_det=0.750,
            # TAVI-PUMA's solver branch produces mtt > 0, stt < 0, att > 0
            # (locked by tests/test_sign_conventions.py), i.e. senses
            # (+1, -1, +1). Whether the physical PUMA hall matches is an open
            # instrument-scientist question; TAVI's existing behavior is the
            # contract here.
            sense_mono=Sense.LEFT,
            sense_sample=Sense.RIGHT,
            sense_ana=Sense.LEFT,
        ),
        mono_crystals=(
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.0202, slab_height=0.018, n_columns=13, n_rows=9,
                gap=0.0005, mosaic=35, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
            # Development variant: PG[002] geometry with a deliberately wrong
            # d-spacing, kept for A1/A2 sanity checks in the GUI.
            CrystalSpec(
                id="pg002_test", display_name="PG[002] test", d_spacing=2.355,
                slab_width=0.0202, slab_height=0.018, n_columns=13, n_rows=9,
                gap=0.0005, mosaic=35, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
        ),
        ana_crystals=(
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
                slab_width=0.01, slab_height=0.0295, n_columns=21, n_rows=5,
                gap=0.0005, mosaic=35, r0=1.0,
                reflect_file="HOPG.rfl", transmit_file="HOPG.trm",
            ),
        ),
        # Samples come from the shared, instrument-independent library --
        # samples move between instruments (tavi/sample_library.py, §19).
        samples=default_sample_library(),
        scannable_parameters=_PUMA_PARAMS,
        primary_detector="detector",
        mcstas_name=PUMA_MCSTAS_NAME,
        monitors=_PUMA_MONITORS,
        modules=(
            ModuleSpec("nmo", "NMO installed", ModuleKind.CHOICE,
                       options=("None", "Vertical", "Horizontal", "Both"), default="None"),
            ModuleSpec("v_selector", "Velocity selector", ModuleKind.TOGGLE, default=False),
        ),
        # Defaults mirror the GUI's historical reset values.
        collimation=(
            CollimationSlot("alpha_1", "α1 (src-mono)", ("0", "20", "40", "60"),
                            default="40"),
            CollimationSlot("alpha_2", "α2 (mono-smp)", ("30", "40", "60"),
                            multi_select=True, default="40"),
            CollimationSlot("alpha_3", "α3 (smp-ana)", ("0", "10", "20", "30", "45", "60"),
                            default="30"),
            CollimationSlot("alpha_4", "α4 (ana-det)", ("0", "10", "20", "30", "45", "60"),
                            default="30"),
        ),
        slits=(
            SlitSpec("vbl_hgap", "Post-mono (width)", default_width_mm=88),
            SlitSpec("pbl", "Pre-sample (W×H)", has_height=True,
                     default_width_mm=100, default_height_mm=100),
            SlitSpec("dbl_hgap", "Detector (width)", default_width_mm=50),
        ),
        source_types=(
            SourceType("Maxwellian", "Maxwellian"),
            SourceType("Mono", "Mono", extra_params=("source_dE",)),
        ),
        # Vertical (out-of-plane) Soller divergences BET1..4 (arcmin, FWHM). The
        # McStas PUMA definition and vTAS carry no per-blade vertical Soller data;
        # 120 arcmin is a documented uniform default (recorded as such in the
        # resolution adapter's provenance).
        vertical_divergence=(120.0, 120.0, 120.0, 120.0),
    )


class PUMAPlugin:
    """``InstrumentPlugin`` implementation for PUMA."""

    id = PUMA_ID
    display_name = PUMA_DISPLAY_NAME

    def descriptor(self):
        return puma_descriptor()

    def default_state(self):
        """Fresh ``PUMA_Instrument`` with PUMA's defaults."""
        from instruments.PUMA_instrument_definition import PUMA_Instrument

        return PUMA_Instrument()

    def scan_config(self, base_state, gui_values, sample_key, diagnostic_settings,
                    sample_mount):
        """Create a scan-local PUMA configuration from frozen launch state.

        Maps the generic GUI value containers (``modules``/``collimation``/
        ``slits_mm``, produced by the descriptor-driven dock) onto PUMA's state
        fields. The resulting state is identical to the pre-Phase-2 mapping.
        """
        vals = gui_values
        modules = vals['modules']
        collimation = vals['collimation']
        slits_mm = vals['slits_mm']

        scan_config = copy.deepcopy(base_state)
        scan_config.K_fixed = vals['K_fixed']
        scan_config.NMO_installed = modules['nmo']
        scan_config.V_selector_installed = modules['v_selector']
        scan_config.source_type = vals['source_type']
        scan_config.source_dE = vals['source_dE']
        scan_config.rhm = vals['rhm']
        scan_config.rvm = vals['rvm']
        scan_config.rha = vals['rha']
        scan_config.rva = 0.8
        if scan_config.NMO_installed != "None":
            scan_config.rhm = 0
            scan_config.rvm = 0
        scan_config.fixed_E = vals['fixed_E']
        scan_config.monocris = vals['monocris']
        scan_config.anacris = vals['anacris']
        scan_config.sample_key = sample_key
        scan_config.alpha_1 = float(collimation['alpha_1'])
        alpha_2_selected = collimation['alpha_2']
        scan_config.alpha_2 = [
            30 if "30" in alpha_2_selected else 0,
            40 if "40" in alpha_2_selected else 0,
            60 if "60" in alpha_2_selected else 0,
        ]
        scan_config.alpha_3 = float(collimation['alpha_3'])
        scan_config.alpha_4 = float(collimation['alpha_4'])
        pbl_width_mm, pbl_height_mm = slits_mm['pbl']
        scan_config.vbl_hgap = slits_mm['vbl_hgap'] / 1000.0
        scan_config.pbl_hgap = pbl_width_mm / 1000.0
        scan_config.pbl_vgap = pbl_height_mm / 1000.0
        scan_config.dbl_hgap = slits_mm['dbl_hgap'] / 1000.0
        scan_config.sample_mount = sample_mount
        scan_config.update_diagnostic_settings(diagnostic_settings)
        return scan_config

    def crystal_info(self, mono_label, ana_label):
        """TRANSITIONAL: delegate to the legacy crystal table (see contract)."""
        from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

        return mono_ana_crystals_setup(mono_label, ana_label)

    def build_fingerprint(self, config, diagnostic_mode=False, diagnostic_settings=None):
        """Stable hash of the build-time (ChangeImpact.BUILD) state.

        Hashes the same effective inputs as ``build``: the config's build-time
        fields plus the diagnostic mode/settings the controller would pass.
        The controller reuses the previous scan's compiled binary when this
        matches and the binary still exists (design record §18.5).
        """
        import hashlib
        import json

        build_state = {
            "monocris": config.monocris,
            "anacris": config.anacris,
            "sample_key": getattr(config, "sample_key", None),
            "NMO_installed": config.NMO_installed,
            "V_selector_installed": bool(config.V_selector_installed),
            "source_type": config.source_type,
            "source_dE": config.source_dE,
            "alpha_1": config.alpha_1,
            "alpha_2": list(config.alpha_2),
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
        from instruments.PUMA_instrument_definition import build_PUMA_instrument

        return build_PUMA_instrument(
            config, diagnostic_mode, diagnostic_settings, number_neutrons
        )

    def compute_snapshot(self, scan_item, scan_index, scan_mode, config, vals,
                         data_folder, *, is_2d_scan=False, variable_name1="",
                         variable_name2="", scan_command1="", scan_command2=""):
        from instruments.PUMA_instrument_definition import compute_scan_snapshot

        return compute_scan_snapshot(
            scan_item, scan_index, scan_mode, config, vals, data_folder,
            is_2d_scan=is_2d_scan,
            variable_name1=variable_name1,
            variable_name2=variable_name2,
            scan_command1=scan_command1,
            scan_command2=scan_command2,
        )

    def run_point(self, instrument, snapshot, output_folder, number_neutrons,
                  execution_state, mpi_count=30):
        from instruments.PUMA_instrument_definition import run_PUMA_point

        return run_PUMA_point(
            instrument, snapshot, output_folder, number_neutrons,
            execution_state, mpi_count,
        )

    def check_point_feasibility(self, config, scan_mode, scan_point, vals):
        """Return ``(feasible, reason)`` for one scan point (see contract).

        Delegates to the shared TAS feasibility helper, which reuses the exact
        per-point angle math ``compute_snapshot`` runs. Used by the remote API
        to reject or (with ``allow_partial``) skip geometrically unreachable
        scan points before queueing.
        """
        from instruments.PUMA_instrument_definition import check_point_feasibility

        return check_point_feasibility(config, scan_mode, scan_point, vals)

    def resolution_config(self, vals, q0, w):
        """Build a theoretical-resolution config for PUMA (see contract).

        Pure function of the descriptor + ``vals``; imports no mcstasscript. NMO
        selection is recorded as an invalidation (``cn_valid`` -> False); the
        velocity selector and a monochromatic source add warnings.
        """
        from instruments.resolution_adapter import build_resolution_config

        return build_resolution_config(puma_descriptor(), vals, q0, w)
