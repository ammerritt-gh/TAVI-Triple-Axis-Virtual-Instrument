"""Explicit registration of TAVI's built-in instruments.

Import this module once at startup (``main()`` in ``TAVI_PySide6.py``) to
populate the registry. Registration is deliberately explicit -- no package
scanning or import side effects (``docs/CONFIGURABLE_INSTRUMENTS.md`` §16.10) --
and importing this module must stay cheap: no mcstasscript, no PySide6, no
``instruments.PUMA_instrument_definition`` (guarded by
``tests/test_instrument_registry.py::test_listing_is_lazy_no_mcstas_import``).

To add an instrument: write its plugin module (see ``instruments/puma_plugin.py``
and ``docs/CONFIGURABLE_INSTRUMENTS.md`` §5), then register it here.
"""
from instruments.puma_plugin import PUMA_DISPLAY_NAME, PUMA_ID, PUMAPlugin
from instruments.registry import register

register(PUMA_ID, PUMA_DISPLAY_NAME, PUMAPlugin)  # the class itself is the factory
