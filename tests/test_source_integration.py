"""The four instruments run on Source_Maxwell_direct, and the source is run-time state.

Construction and per-point solving only -- no McStas compile or run. What this
guards, per instrument:

- the built tree has the component, bound to run-time instrument parameters
  that carry the default profile's numbers;
- in full-spectrum mode no scan setting (Ei, kf, the fixed side, the transfer)
  reaches those parameters;
- an edited component file changes the build fingerprint, and a changed source
  (mode, profile, T/I, dE) does not, so a source change never recompiles;
- a flat band that reaches zero energy is refused at the point, as the
  component would otherwise stop the whole McStas run.
"""
import functools
import importlib
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("mcstasscript")

import instruments.builtin  # noqa: F401,E402
from instruments import source  # noqa: E402
from instruments.descriptor import SOURCE_PARAMS  # noqa: E402
from instruments.registry import get_instrument  # noqa: E402
from instruments.tas_runtime import HKL_CALC, compute_scan_snapshot  # noqa: E402
from plan_helpers import hkl_point, plan_for  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "solver_baseline_cases", Path(__file__).resolve().parent / "data" / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)

# instrument id -> (baseline-case label, the facility entry it views)
DEFAULTS = {
    "puma": ("PUMA", "frm2_thermal"),
    "panda": ("PANDA", "frm2_cold"),
    "in8": ("IN8", "ill_thermal_h12"),
    "in12": ("IN12", "ill_vcs_cold"),
}
PARAM_TO_FIELD = {
    "moderator_t1_param": "moderator_t1_k", "moderator_i1_param": "moderator_i1",
    "moderator_t2_param": "moderator_t2_k", "moderator_i2_param": "moderator_i2",
    "moderator_t3_param": "moderator_t3_k", "moderator_i3_param": "moderator_i3",
}


def _config(instrument_id, **overrides):
    """(plugin, scan-config state, launch vals) at the instrument's defaults."""
    plugin = get_instrument(instrument_id)
    vals = cases._launch_vals(plugin.descriptor(), **overrides)
    state = plugin.default_state()
    return plugin, plugin.scan_config(state, vals, None, {}, state.sample_mount), vals


def _source_params(params):
    return {name: params[name] for name in (spec.name for spec in SOURCE_PARAMS)}


@pytest.mark.parametrize("instrument_id", DEFAULTS)
def test_instrument_builds_the_component_on_its_default_profile(instrument_id):
    plugin, config, _ = _config(instrument_id)
    profile = DEFAULTS[instrument_id][1]
    assert plugin.descriptor().default_moderator_profile == profile
    assert config.moderator_profile == profile and config.moderator_mode == "full_spectrum"

    instrument = plugin.build(config, False, {}, 1000)
    comp = {c.name: c for c in instrument.component_list}["source"]
    assert comp.component_name == "Source_Maxwell_direct"
    # Every value is an instrument parameter (a run-time setting), none a literal.
    assert [comp.T1, comp.I1, comp.T2, comp.I2, comp.T3, comp.I3] == [
        f"moderator_{kind}{n}_param" for n in (1, 2, 3) for kind in ("t", "i")]
    assert (comp.flat_band, comp.E0, comp.dE) == (
        "moderator_flat_band_param", "E0_param", "flat_band_de_param")
    declared = set(instrument.get_parameter_names())
    assert {spec.name for spec in SOURCE_PARAMS} | {"E0_param"} <= declared

    # ...and they carry the default profile's numbers.
    params = _source_params(config.build_point_params(0.0))
    table = source.profile_values(profile)
    assert params == {
        "moderator_flat_band_param": 0, "flat_band_de_param": 2.0,
        **{param: table[field] for param, field in PARAM_TO_FIELD.items()}}
    assert source.validate(config.source_values()) == []


@pytest.mark.parametrize("instrument_id", DEFAULTS)
def test_full_spectrum_source_ignores_the_scan(instrument_id):
    """Across fixed sides, Ei, kf and transfers, the source parameters never move."""
    label = DEFAULTS[instrument_id][0]
    snapshots = [snap for _note, snap in cases.build_cases(label).values()]
    energies = {(round(s.metadata["Ei"], 6), round(s.metadata["Ef"], 6)) for s in snapshots}
    assert len(energies) >= 4, "the cases must differ in Ei and kf, or this proves nothing"
    # E0_param (the flat band's centre) is deliberately not compared.
    assert len({tuple(sorted(_source_params(s.params).items())) for s in snapshots}) == 1

    # A different fixed energy and side, set directly on the state.
    _plugin, config, _vals = _config(instrument_id)
    reference = _source_params(config.build_point_params(0.0))
    for fixed_e, side in ((4.0, "Ki Fixed"), (35.0, "Kf Fixed")):
        config.fixed_E, config.K_fixed = fixed_e, side
        assert _source_params(config.build_point_params(-1.5)) == reference


@pytest.mark.parametrize("instrument_id", DEFAULTS)
def test_fingerprint_changes_when_the_component_file_changes(instrument_id, tmp_path, monkeypatch):
    plugin, config, _ = _config(instrument_id)
    same = plugin.build_fingerprint(config)
    assert plugin.build_fingerprint(config) == same

    edited = tmp_path / "Source_Maxwell_direct.comp"
    edited.write_bytes(source.COMPONENT_PATH.read_bytes() + b"/* edited */\n")
    monkeypatch.setattr(source, "component_stamp",
                        functools.partial(source.component_stamp, edited))
    assert plugin.build_fingerprint(config) != same


@pytest.mark.parametrize("instrument_id", DEFAULTS)
def test_fingerprint_ignores_a_change_of_source(instrument_id):
    plugin, config, _ = _config(instrument_id)
    before = plugin.build_fingerprint(config)
    for profile in ("ill_hot", "single_temperature"):
        config.apply_source_values({
            "moderator_mode": "flat_band", "moderator_profile": profile,
            **source.profile_values(profile), "flat_band_half_width_mev": 3.5})
        assert plugin.build_fingerprint(config) == before
    config.moderator_i2 = 7.0   # an edited field, "(modified)" in the dock
    assert plugin.build_fingerprint(config) == before


@pytest.mark.parametrize("instrument_id", DEFAULTS)
def test_flat_band_that_reaches_zero_energy_is_refused(instrument_id):
    ei = 14.7   # the launch state's fixed energy; Ki Fixed at deltaE 0 makes it Ei
    reason = "flat band reaches zero energy (Ei − dE ≤ 0); lower the flat-band half-width"

    def check(mode, half_width):
        plugin, config, vals = _config(instrument_id, K_fixed="Ki Fixed", moderator_mode=mode,
                                       flat_band_half_width_mev=half_width)
        plan = plan_for(plugin, config, vals, HKL_CALC)
        point = hkl_point(1.0, 0.0, 0.0, 0.0)
        return (plugin.check_point_feasibility(config, plan, point),
                compute_scan_snapshot(plan, point, 0, config, vals, data_folder="."))

    refused, snap = check("flat_band", ei + 1.0)
    assert not refused.feasible and refused.reason == reason
    assert refused.kind == "physical_infeasible"
    assert snap.params is None and snap.error_flags == ["flat_band"]   # the run skips it too

    # The other directions: a band that stays above zero, and the full spectrum
    # (which reads neither E0 nor dE), run.
    for mode, half_width in (("flat_band", ei - 1.0), ("full_spectrum", ei + 1.0)):
        ok, snap = check(mode, half_width)
        assert ok.feasible and snap.params is not None and not snap.error_flags
