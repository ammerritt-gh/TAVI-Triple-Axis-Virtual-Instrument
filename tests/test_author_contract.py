"""The instrument author contract, exercised through its public surface only.

``contract_plugin_fixture`` is built from the documented contract alone: it loads
through the registry, plans an H scan with ``build_plan`` and expands it, and a copy
declaring another ``CONTRACT_VERSION`` is refused at load. No McStas is built or run.
"""
import pytest

from contract_plugin_fixture import (
    ContractFixturePlugin,
    UndeclaredVersionPlugin,
    WrongVersionPlugin,
    fixture_descriptor,
    plan_context,
)
import instruments.builtin  # noqa: F401  (registers the four built-in plugins)
from instruments import registry
from instruments.contract import Capabilities
from instruments.rules import build_plan, expand
from instruments.validation import (
    assert_valid_capabilities,
    validate_capabilities,
    validate_descriptor,
)


@pytest.fixture(autouse=True)
def _registry_snapshot():
    factories = dict(registry._FACTORIES)
    display_names = dict(registry._DISPLAY_NAMES)
    yield
    registry._FACTORIES.clear()
    registry._FACTORIES.update(factories)
    registry._DISPLAY_NAMES.clear()
    registry._DISPLAY_NAMES.update(display_names)


def test_fixture_descriptor_is_structurally_valid():
    assert validate_descriptor(fixture_descriptor()) == []


def test_h_scan_plans_and_expands_through_the_public_contract():
    registry.register("contract_fixture", "Contract fixture", ContractFixturePlugin)
    plugin = registry.get_instrument("contract_fixture")
    assert_valid_capabilities(plugin.capabilities(), plugin.id)

    plan = build_plan([("H 0.9 1.1 0.02", False), ("", False)], plan_context(plugin))
    assert plan.scanned == {"h"}
    expansion = expand(plan, {qid: 0.0 for qid in plan.inputs})
    hs = [point["h"] for point in expansion.points]
    assert len(hs) == 11
    assert hs[0] == pytest.approx(0.9)
    assert hs[-1] == pytest.approx(1.1)


def test_wrong_contract_version_is_refused_at_load():
    with pytest.raises(ValueError) as excinfo:
        registry.register("contract_fixture", "Contract fixture", WrongVersionPlugin)
    message = str(excinfo.value)
    assert "WrongVersionPlugin" in message
    assert "CONTRACT_VERSION 2" in message
    assert "TAVI supports CONTRACT_VERSION 1" in message
    assert "contract_fixture" not in {info.id for info in registry.available_instruments()}


def test_undeclared_contract_version_is_refused_at_load():
    with pytest.raises(ValueError, match="declares no CONTRACT_VERSION"):
        registry.register("contract_fixture", "Contract fixture", UndeclaredVersionPlugin)


def test_instrument_extras_live_under_the_instrument_namespace():
    assert_valid_capabilities(
        Capabilities(inputs=frozenset({"instrument.contract_fixture.cell_gain",
                                       "sample_two_theta_deg"}),
                     observables=frozenset(), bindings={}),
        "contract_fixture")


@pytest.mark.parametrize("qid", [
    "instrument.other.cell_gain",          # another instrument's namespace
    "instrument.contract_fixture.Cell",    # a capital letter in the name
    "A4",                                  # an alias, not a canonical ID
    "psi",                                 # a retired alias
    "mono_theta_deg",                      # derived: no input may set A1
])
def test_undeclared_or_derived_quantities_are_refused(qid):
    with pytest.raises(ValueError, match="contract_fixture"):
        assert_valid_capabilities(
            Capabilities(inputs=frozenset({qid}), observables=frozenset(), bindings={}),
            "contract_fixture")


@pytest.mark.parametrize("instrument_id", [info.id for info in registry.available_instruments()])
def test_builtin_plugins_declare_version_one_and_valid_capabilities(instrument_id):
    plugin = registry.get_instrument(instrument_id)
    assert plugin.CONTRACT_VERSION == 1
    assert validate_capabilities(plugin.capabilities(), instrument_id) == []
