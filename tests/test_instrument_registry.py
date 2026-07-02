"""Registry contract tests (docs/CONFIGURABLE_INSTRUMENTS.md §17.7).

The subprocess-based lazy-import test is the doc's "list instruments without
importing/building McStas" guarantee: it stays hermetic even after other tests
in the same process have imported mcstasscript.
"""
import os
import subprocess
import sys

import pytest

from instruments import registry
from instruments.registry import InstrumentInfo, available_instruments, get_instrument, register

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _registry_snapshot():
    """Snapshot/restore the module-level registry dicts around every test."""
    factories = dict(registry._FACTORIES)
    display_names = dict(registry._DISPLAY_NAMES)
    yield
    registry._FACTORIES.clear()
    registry._FACTORIES.update(factories)
    registry._DISPLAY_NAMES.clear()
    registry._DISPLAY_NAMES.update(display_names)


class _DummyPlugin:
    id = "dummy"
    display_name = "Dummy"


def test_register_and_get_roundtrip():
    register("dummy", "Dummy", _DummyPlugin)
    infos = available_instruments()
    assert InstrumentInfo("dummy", "Dummy") in infos
    assert isinstance(get_instrument("dummy"), _DummyPlugin)
    # A fresh instance per resolution, not a shared singleton.
    assert get_instrument("dummy") is not get_instrument("dummy")


def test_register_duplicate_id_raises():
    register("dummy", "Dummy", _DummyPlugin)
    with pytest.raises(ValueError, match="already registered"):
        register("dummy", "Dummy again", _DummyPlugin)


def test_get_unknown_id_error_lists_available():
    register("dummy", "Dummy", _DummyPlugin)
    with pytest.raises(KeyError) as excinfo:
        get_instrument("nope")
    assert "nope" in str(excinfo.value)
    assert "dummy" in str(excinfo.value)


def test_builtin_registers_puma():
    import instruments.builtin  # noqa: F401  (registration side effect)

    if "puma" not in {i.id for i in available_instruments()}:
        # A previous test's snapshot/restore removed the cached registration;
        # re-execute the (idempotent-by-reload) registration module.
        import importlib

        importlib.reload(instruments.builtin)
    infos = available_instruments()
    assert InstrumentInfo("puma", "PUMA (FRM-II)") in infos


def test_listing_is_lazy_no_mcstas_import():
    """Listing instruments must not import mcstasscript, PySide6, or the heavy
    PUMA module (docs/CONFIGURABLE_INSTRUMENTS.md §16.10/§16.11)."""
    code = (
        "import sys\n"
        "import instruments.builtin\n"
        "from instruments.registry import available_instruments\n"
        "infos = available_instruments()\n"
        "assert any(i.id == 'puma' for i in infos), infos\n"
        "for banned in ('mcstasscript', 'PySide6',\n"
        "               'instruments.PUMA_instrument_definition'):\n"
        "    assert banned not in sys.modules, f'{banned} was imported'\n"
        "print('lazy-ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "lazy-ok" in result.stdout
