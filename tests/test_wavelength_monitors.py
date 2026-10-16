"""Energy monitors recorded as wavelength monitors (u1 of job j43f00d74e4b3).

With the diagnostic setting "Wavelength Monitors" true, each enabled E_monitor
is emitted as an L_monitor at the same placement and size, its name carrying
"Lmonitor" for "Emonitor" (job j7e540e562b4f); absent or
false is today's tree. The fake-instrument tests cover all four plugin monitor
tables and need no McStasScript. The real PUMA build is skipped where
mcstasscript does not import. Construction only: no McStas compile or run.
"""
from types import SimpleNamespace

import pytest

from instruments.descriptor import MonitorSpec
from instruments.in8.plugin import _IN8_MONITORS
from instruments.in12.plugin import _IN12_MONITORS
from instruments.panda.plugin import _PANDA_MONITORS
from instruments.puma.plugin import _PUMA_MONITORS
from tavi.instrument_helpers import emit_monitors
from tavi.neutron_conversions import energy2lambda

WAVELENGTH = "Wavelength Monitors"
TABLES = [_PUMA_MONITORS, _IN8_MONITORS, _IN12_MONITORS, _PANDA_MONITORS]


class _FakeInstrument:
    """Duck-typed McStas_instr: records each component's name, type and placement."""

    def __init__(self):
        self.components = []

    def add_component(self, name, component_type, AT, ROTATED, RELATIVE):
        comp = SimpleNamespace(name=name, component_type=component_type,
                               AT=AT, ROTATED=ROTATED, RELATIVE=RELATIVE)
        self.components.append(comp)
        return comp


def _emit(specs, enabled):
    instrument = _FakeInstrument()
    emit_monitors(instrument, specs, enabled)
    return instrument.components


def _enabled(specs, wavelength=None):
    enabled = {m.id: True for m in specs}
    if wavelength is not None:
        enabled[WAVELENGTH] = wavelength
    return enabled


def _probe(**settings):
    """One E_monitor spec; defaults are the PUMA source monitor's range (-2..200 meV)."""
    base = {"xwidth": 0.2, "yheight": 0.2, "nE": 100, "Emin": -2, "Emax": 200,
            "restore_neutron": 1}
    base.update(settings)
    return MonitorSpec("probe", "E_monitor", (0.0, 0.0, 0.1), "origin",
                       settings=base, component_name="probe_Emonitor")


def _one(spec, wavelength):
    return _emit([spec], _enabled([spec], wavelength))[0]


def _wave_name(spec):
    """The name a spec's component carries in wavelength mode."""
    if spec.component_type != "E_monitor":
        return spec.component_name
    return spec.component_name.replace("Emonitor", "Lmonitor")


@pytest.mark.parametrize("table", TABLES)
def test_key_absent_and_false_emit_energy_monitors_unchanged(table):
    absent = _emit(table, _enabled(table))
    off = _emit(table, _enabled(table, wavelength=False))
    assert [vars(c) for c in absent] == [vars(c) for c in off]
    by_name = {c.name: c for c in absent}
    for spec in table:
        comp = by_name[spec.component_name]
        assert comp.component_type == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value


@pytest.mark.parametrize("table", TABLES)
def test_key_true_swaps_each_energy_monitor_in_place(table):
    energy = _emit(table, _enabled(table))
    wave = _emit(table, _enabled(table, wavelength=True))
    assert ([(c.AT, c.ROTATED, c.RELATIVE) for c in wave]
            == [(c.AT, c.ROTATED, c.RELATIVE) for c in energy])
    assert [c.name for c in wave] == [_wave_name(spec) for spec in table]
    by_name = {c.name: c for c in wave}
    for spec in table:
        comp = by_name[_wave_name(spec)]
        if spec.component_type != "E_monitor":
            assert comp.component_type == spec.component_type
            continue
        assert spec.settings["Emin"] <= 0  # every current E_monitor gets the 10 A cap
        assert comp.component_type == "L_monitor"
        assert comp.nL == spec.settings["nE"]
        for key in ("nE", "Emin", "Emax"):
            assert not hasattr(comp, key)
        assert comp.Lmin == pytest.approx(energy2lambda(spec.settings["Emax"]))
        assert comp.Lmax == 10.0
        for key in ("xwidth", "yheight", "restore_neutron"):
            assert getattr(comp, key) == spec.settings[key]


@pytest.mark.parametrize("table", TABLES)
def test_key_true_names_every_wavelength_monitor_lmonitor(table):
    wave = _emit(table, _enabled(table, wavelength=True))
    energy_names = {spec.component_name for spec in table if spec.component_type == "E_monitor"}
    lmonitors = [c.name for c in wave if c.component_type == "L_monitor"]
    assert lmonitors and all("Lmonitor" in n and n not in energy_names for n in lmonitors)
    assert len({c.name for c in wave}) == len(wave)


def test_name_without_emonitor_still_gets_a_wavelength_name():
    spec = MonitorSpec("probe", "E_monitor", (0.0, 0.0, 0.1), "origin",
                       settings=_probe().settings, component_name="probe_energy")
    assert _one(spec, True).name == "probe_energy_Lmonitor"
    assert _one(spec, False).name == "probe_energy"


@pytest.mark.parametrize("emax, lambda_a", [(200, 0.64), (120, 0.83), (60, 1.17), (30, 1.65)])
def test_short_end_is_wavelength_at_emax(emax, lambda_a):
    assert _one(_probe(Emax=emax), True).Lmin == pytest.approx(lambda_a, abs=0.005)


def test_long_end_is_wavelength_at_emin_below_the_cap():
    assert _one(_probe(Emin=1), True).Lmax == pytest.approx(9.04, abs=0.005)


def test_long_end_capped_at_10_angstrom_when_emin_gives_longer():
    assert _one(_probe(Emin=0.5), True).Lmax == 10.0


@pytest.mark.parametrize("table", TABLES)
def test_psd_and_dsd_untouched_with_key_true(table):
    others = [m for m in table if m.component_type != "E_monitor"]
    emitted = _emit(others, _enabled(others, wavelength=True))
    assert len(emitted) == len(others)
    for comp, spec in zip(emitted, others):
        assert comp.component_type == spec.component_type
        for key, value in spec.settings.items():
            assert getattr(comp, key) == value


def _build_puma(diagnostic_settings):
    pytest.importorskip("mcstasscript")
    import instruments.builtin  # noqa: F401
    from instruments.registry import get_instrument

    plugin = get_instrument("puma")
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Mono",
        "source_dE": 2,
        "rhm": 13.0272,
        "rvm": 1.6102,
        "rha": 2.3034,
        "rva": 0.8,
        "fixed_E": 14.7,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {"nmo": "None", "v_selector": False},
        "collimation": {"alpha_1": "40", "alpha_2": {"30", "40", "60"},
                        "alpha_3": "30", "alpha_4": "30"},
        "slits_mm": {"vbl_hgap": 88.0, "pbl": (100.0, 100.0), "dbl_hgap": 50.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, "Al_bragg", diagnostic_settings,
                                state.sample_mount)
    return plugin.build(config, True, diagnostic_settings, 100000)


@pytest.fixture(scope="module")
def puma_absent():
    return _build_puma(_enabled(_PUMA_MONITORS))


@pytest.fixture(scope="module")
def puma_false():
    return _build_puma(_enabled(_PUMA_MONITORS, wavelength=False))


@pytest.fixture(scope="module")
def puma_wave():
    return _build_puma(_enabled(_PUMA_MONITORS, wavelength=True))


def _tree(instrument):
    return [(c.name, c.component_name, c.AT_data, c.ROTATED_data,
             {k: getattr(c, k) for k in c.get_parameter_names()})
            for c in instrument.component_list]


def test_real_build_key_absent_and_false_are_the_same_tree(puma_absent, puma_false):
    assert _tree(puma_absent) == _tree(puma_false)


def test_real_build_key_true_swaps_the_six_puma_energy_monitors(puma_absent, puma_wave):
    before = {c.name: c for c in puma_absent.component_list}
    after = {c.name: c for c in puma_wave.component_list}
    assert {_wave_name(spec) for spec in _PUMA_MONITORS} <= set(after)
    assert len(after) == len(before)
    for spec in _PUMA_MONITORS:
        comp = after[_wave_name(spec)]
        if spec.component_type != "E_monitor":
            assert comp.component_name == spec.component_type
            continue
        assert comp.component_name == "L_monitor"
        assert "nE" not in comp.get_parameter_names()
        assert comp.nL == spec.settings["nE"]
        assert comp.Lmin == pytest.approx(energy2lambda(spec.settings["Emax"]))
        assert comp.Lmax == 10.0
        assert comp.restore_neutron == 1
        assert comp.AT_data == before[spec.component_name].AT_data
        assert comp.xwidth == before[spec.component_name].xwidth
        assert comp.yheight == before[spec.component_name].yheight


def test_real_build_postmono_keeps_crystal_size_as_wavelength_monitor(puma_wave):
    comp = {c.name: c for c in puma_wave.component_list}["postmono_Lmonitor"]
    assert comp.component_name == "L_monitor"
    assert comp.xwidth == 0.0202 * 13
    assert comp.yheight == 0.018 * 9
