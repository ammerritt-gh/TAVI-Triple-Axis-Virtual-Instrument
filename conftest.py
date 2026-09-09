"""Repo-root pytest configuration.

Its whole job is to stop a test run from putting windows on the operator's
screen. McStasScript's ``McStas_instr.__init__`` shells out twice on every
construction -- and the build-tree tests construct one per instrument, per
module:

1. ``subprocess.check_output("mcrun --showcfg=resourcedir", shell=True)``,
   taken only when ``MCSTAS`` is absent from the environment; ``shell=True``
   means a real ``cmd.exe``.
2. ``subprocess.check_output([<executable_path>/mcstas, "-v"])`` to read the
   McStas major version -- unconditional, and wrapped in a bare ``except`` so
   it fails invisibly.

On Windows a subprocess launched from a parent with no console gets a new one,
so each of those flashes a console window, and a failing binary can raise an
error dialog on top. Measured 2026-09-09: a few dozen test runs in an
afternoon buried the desktop in them.

Two guards, because either alone leaves a hole:

- ``MCSTAS`` is set if absent, which removes the ``shell=True`` launch
  entirely and is what ``run-tavi-dev.bat`` does for the GUI.
- Every subprocess started during the session gets ``CREATE_NO_WINDOW``. That
  one covers the version probe, which no environment variable can switch off,
  and anything added later by us or by a dependency.

``CREATE_NO_WINDOW`` suppresses the console without detaching the process, so
stdout/stderr capture, exit codes and timeouts all behave exactly as before.
"""
import inspect
import os
import subprocess
import sys

import pytest


def _resolve_mcstas_resources():
    """The McStas resource dir, resolved as run-tavi-dev.bat resolves it."""
    prefix = os.environ.get("CONDA_PREFIX") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming", "mamba", "envs", "tavi-dev"
    )
    for candidate in (
        os.path.join(prefix, "share", "mcstas", "resources"),
        os.path.join(prefix, "Library", "share", "mcstas", "resources"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return None


# Windows creates a console for a child process whose parent has none, and
# that console is what appears on screen. CREATE_NO_WINDOW suppresses it
# without detaching, so capture, exit codes and timeouts are unaffected.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _creationflags_position():
    """Where `creationflags` sits in Popen.__init__'s positional parameters.

    Read from the signature rather than hardcoded: it has moved between Python
    versions, and a wrong index would silently OR the flag into somebody else's
    argument. A caller passing it positionally must have its value merged in
    place -- adding the keyword as well raises "multiple values for argument
    'creationflags'" before the child ever starts.
    """
    try:
        names = list(inspect.signature(subprocess.Popen.__init__).parameters)
        return names.index("creationflags") - 1   # discount self
    except (ValueError, TypeError):      # pragma: no cover - not on this Python
        return None


_CREATIONFLAGS_POS = _creationflags_position()


def apply_no_window(args, kwargs):
    """Add CREATE_NO_WINDOW to a Popen call, wherever the flags were passed.

    Returns the (args, kwargs) to forward, preserving any flags already set.
    """
    if _CREATIONFLAGS_POS is not None and len(args) > _CREATIONFLAGS_POS:
        args = list(args)
        args[_CREATIONFLAGS_POS] = (args[_CREATIONFLAGS_POS] or 0) | CREATE_NO_WINDOW
        return tuple(args), kwargs
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    return args, kwargs


def install_no_window_guard():
    """Patch Popen so nothing started this session can open a console.

    Returns True if the guard is in place. check_output, run and Popen all
    funnel through Popen.__init__, so one patch covers every caller --
    including McStasScript's version probe, which no environment variable
    switches off.
    """
    if sys.platform != "win32":
        return False

    original_init = subprocess.Popen.__init__
    if getattr(original_init, "_tavi_no_window", False):
        return True

    def windowless_init(self, *args, **kwargs):
        args, kwargs = apply_no_window(args, kwargs)
        return original_init(self, *args, **kwargs)

    windowless_init._tavi_no_window = True
    subprocess.Popen.__init__ = windowless_init
    return True


def pytest_configure(config):
    # Guard 1: MCSTAS present -> McStasScript skips its shell=True probe.
    if "MCSTAS" not in os.environ:
        resources = _resolve_mcstas_resources()
        if resources:
            os.environ["MCSTAS"] = resources

    # Guard 2: nothing this session starts may open a console window.
    install_no_window_guard()


@pytest.fixture(scope="session", autouse=True)
def _no_console_windows():
    """Fail loudly if the guard was undone, rather than silently spawning."""
    if sys.platform == "win32":
        assert getattr(subprocess.Popen.__init__, "_tavi_no_window", False), (
            "the CREATE_NO_WINDOW guard is not installed; see conftest.py"
        )
