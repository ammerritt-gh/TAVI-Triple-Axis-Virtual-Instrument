"""The API 'modules' field must be validated against the instrument's own
descriptor, and an omitted module id must not KeyError at launch.

Ledger entry 1 (P1) in docs/audits/new-instruments-crystal-bending.md: the
API accepted any dict for 'modules' -- ``p_dict`` only checked it was a dict,
nothing inside it. A lowercase/undeclared PUMA NMO value ("vertical" instead
of "Vertical") was accepted, and instruments/puma/model.py's NMO predicate
(non-"None" => installed) and the two focusing-mirror predicates (exact
choice required) disagreed, producing a flat monochromator with the NMO
aperture installed and no focusing mirror.

Second, related hole (found by the plan-verifier reviewing slice 1): a
patched 'modules' dict replaces the previous one wholesale, and every
plugin's ``scan_config``/``apply_to_state`` indexes each id the descriptor
declares directly (``modules['nmo']``, ``modules['v_selector']`` in
instruments/puma/plugin.py) -- so a request naming only one of PUMA's two
module ids KeyErrors at launch today, even though the same request succeeds
through PATCH (``InstrumentDock.set_module_values`` does
``values.get(module.id, module.default)``, tolerating a partial dict).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.descriptor import ModuleKind  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.api_server import ApiError  # noqa: E402

_INSTRUMENT_IDS = [info.id for info in available_instruments()]
# Only PUMA currently declares any module (IN8's FlatCone/IMPS are deferred --
# ModuleSpec's own docstring). Parametrizing the partial-dict tests over this
# narrower set, decided at collection time, means an instrument with no
# modules is simply not a case for "omit one, keep the rest" rather than a
# runtime skip -- so the suite's only skip stays test_dispersion_map's.
_MODULE_INSTRUMENT_IDS = [
    info.id for info in available_instruments()
    if get_instrument(info.id).descriptor().modules
]


def _make_controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture(params=_INSTRUMENT_IDS)
def controller(request):
    yield from _make_controller(request.param)


@pytest.fixture(params=_MODULE_INSTRUMENT_IDS)
def module_controller(request):
    """Like ``controller``, but only instruments that declare a module --
    for the tests that need at least one declared id to omit/keep."""
    yield from _make_controller(request.param)


def _parse_modules(ctrl):
    return ctrl._api_field_map()['modules'][0]


def test_a_valid_declared_choice_is_accepted(controller):
    parse = _parse_modules(controller)
    for module in controller.descriptor.modules:
        if module.kind is not ModuleKind.CHOICE:
            continue
        option = module.options[0]
        assert parse({module.id: option}) == {module.id: option}


def test_the_wrong_case_variant_is_rejected(controller):
    parse = _parse_modules(controller)
    for module in controller.descriptor.modules:
        if module.kind is not ModuleKind.CHOICE:
            continue
        option = module.options[0]
        wrong_case = option.lower() if option != option.lower() else option.upper()
        if wrong_case == option:
            continue  # no case-bearing option on this instrument's spec
        with pytest.raises(ValueError):
            parse({module.id: wrong_case})


def test_an_undeclared_option_is_rejected(controller):
    parse = _parse_modules(controller)
    for module in controller.descriptor.modules:
        if module.kind is not ModuleKind.CHOICE:
            continue
        with pytest.raises(ValueError, match=module.id):
            parse({module.id: "definitely-not-a-declared-option"})


def test_an_unknown_module_id_is_rejected(controller):
    parse = _parse_modules(controller)
    with pytest.raises(ValueError, match="unknown module"):
        parse({"no_such_module": "anything"})


def test_a_non_bool_for_a_toggle_is_rejected(controller):
    parse = _parse_modules(controller)
    for module in controller.descriptor.modules:
        if module.kind is not ModuleKind.TOGGLE:
            continue
        with pytest.raises(ValueError, match=module.id):
            parse({module.id: "not-a-bool"})


def test_a_non_dict_value_is_rejected(controller):
    parse = _parse_modules(controller)
    with pytest.raises(ValueError, match="object/dict"):
        parse("not-a-dict")


def test_puma_lowercase_nmo_is_refused_by_build_api_launch_state():
    """The headline case: the exact request the audit reproducer submits."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("puma")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id="puma", save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        with pytest.raises(ApiError) as excinfo:
            ctrl.build_api_launch_state({
                "H": 1.0, "modules": {"nmo": "vertical", "v_selector": False},
                "scan_command1": "deltaE 0 1 1",
            })
        assert excinfo.value.status == 400
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def test_a_partial_modules_patch_succeeds_with_omitted_ids_at_defaults(module_controller):
    """The case that KeyErrors on launch today (defect B): name one declared
    module id and omit the rest; the launch state must still carry every
    declared id, the omitted ones at their descriptor default."""
    controller = module_controller
    modules = controller.descriptor.modules
    named = modules[0]
    value = named.options[0] if named.kind is ModuleKind.CHOICE else (not named.default)

    state = controller.build_api_launch_state({
        "scan_command1": "deltaE 0 1 1",
        "modules": {named.id: value},
    })

    result = state["vals"]["modules"]
    declared_ids = {m.id for m in modules}
    assert set(result) == declared_ids
    assert result[named.id] == value
    for module in modules:
        if module.id != named.id:
            assert result[module.id] == module.default


def test_a_partial_modules_patch_also_succeeds_through_apply_parameters(module_controller):
    """Same partial dict, PATCH path -- must keep working (today's contract)."""
    controller = module_controller
    modules = controller.descriptor.modules
    named = modules[0]
    value = named.options[0] if named.kind is ModuleKind.CHOICE else (not named.default)

    controller.apply_parameters({"modules": {named.id: value}})

    values = controller.window.instrument_dock.module_values()
    assert values[named.id] == value


def test_a_partial_patch_reaches_the_plugin_without_a_keyerror(module_controller):
    """The end defect B's KeyError was raised from: ``build_api_launch_state``
    itself calls ``self.instrument.scan_config(...)``, which indexes every
    module id the descriptor declares directly (e.g.
    ``modules['nmo']``/``modules['v_selector']`` in
    instruments/puma/plugin.py) -- so the KeyError, when it happened, was
    raised from inside this very call, before ``build_api_launch_state`` ever
    returned. Reaching the assertion below already proves it did not."""
    controller = module_controller
    modules = controller.descriptor.modules
    named = modules[0]
    value = named.options[0] if named.kind is ModuleKind.CHOICE else (not named.default)

    state = controller.build_api_launch_state({
        "scan_command1": "deltaE 0 1 1",
        "modules": {named.id: value},
    })
    assert state["scan_config"] is not None
