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
    ParameterSpec,
    SampleSpec,
    Sense,
    SlitSpec,
    SourceType,
)

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
            # PUMA's handedness is implicit in its arm rotations; encoded here
            # explicitly so the contract treats it uniformly with IN8.
            sense_mono=Sense.LEFT,
            sense_sample=Sense.LEFT,
            sense_ana=Sense.LEFT,
        ),
        mono_crystals=(
            CrystalSpec(
                id="pg002", display_name="PG[002]", d_spacing=3.355,
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
        samples=(
            SampleSpec("none", "No sample", None),
            SampleSpec("Al_rod_phonon", "AL: acoustic phonon", "Phonon_simple_SCATTER",
                       properties={"radius": 5e-3, "yheight": 30e-3, "T": 200}, split=10),
            SampleSpec("Al_rod_phonon_optic", "Al: optic phonon", "Phonon_simple_SCATTER",
                       properties={"radius": 5e-3, "yheight": 30e-3, "T": 200}, split=10),
            SampleSpec("Al_bragg", "AL: Bragg", "Single_crystal",
                       properties={"reflections": '"Al.lau"', "mosaic": 5}, split=10),
            SampleSpec("Al_phonon_DFT", "Al: Phonon DFT", "Phonon_DFT",
                       properties={"T": 200}, split=10),
        ),
        scannable_parameters=_PUMA_PARAMS,
        primary_detector="detector",
        mcstas_name=PUMA_MCSTAS_NAME,
        modules=(
            ModuleSpec("nmo", "NMO installed", ModuleKind.CHOICE,
                       options=("None", "Vertical", "Horizontal", "Both"), default="None"),
            ModuleSpec("v_selector", "Velocity selector", ModuleKind.TOGGLE, default=False),
        ),
        collimation=(
            CollimationSlot("alpha_1", "α1 (src-mono)", ("0", "20", "40", "60")),
            CollimationSlot("alpha_2", "α2 (mono-smp)", ("30", "40", "60"),
                            multi_select=True, default=""),
            CollimationSlot("alpha_3", "α3 (smp-ana)", ("0", "10", "20", "30", "45", "60")),
            CollimationSlot("alpha_4", "α4 (ana-det)", ("0", "10", "20", "30", "45", "60")),
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

        Body moved verbatim from the controller's ``_build_scan_puma_config``
        (behavior-identical Phase-1 migration; do not "improve" it here).
        """
        vals = gui_values
        scan_config = copy.deepcopy(base_state)
        scan_config.K_fixed = vals['K_fixed']
        scan_config.NMO_installed = vals['NMO_installed']
        scan_config.V_selector_installed = vals['V_selector_installed']
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
        scan_config.alpha_1 = float(vals['alpha_1'])
        scan_config.alpha_2 = [
            30 if vals['alpha_2_30'] else 0,
            40 if vals['alpha_2_40'] else 0,
            60 if vals['alpha_2_60'] else 0,
        ]
        scan_config.alpha_3 = float(vals['alpha_3'])
        scan_config.alpha_4 = float(vals['alpha_4'])
        scan_config.vbl_hgap = vals['vbl_hgap']
        scan_config.pbl_hgap = vals['pbl_hgap']
        scan_config.pbl_vgap = vals['pbl_vgap']
        scan_config.dbl_hgap = vals['dbl_hgap']
        scan_config.sample_mount = sample_mount
        scan_config.update_diagnostic_settings(diagnostic_settings)
        return scan_config

    def crystal_info(self, mono_label, ana_label):
        """TRANSITIONAL: delegate to the legacy crystal table (see contract)."""
        from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

        return mono_ana_crystals_setup(mono_label, ana_label)

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
