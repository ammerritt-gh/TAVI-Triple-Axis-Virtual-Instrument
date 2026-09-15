"""Repo-root pytest configuration.

Two jobs, neither optional.

First: stop a test run from putting windows on the operator's screen.
McStasScript's ``McStas_instr.__init__`` shells out twice on every
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

Second: stop a test run from writing the operator's local state. On
2026-09-14, closing a real offscreen main window during a release test run
(``tests/test_api_partial_collimation.py``) saved the layout into the
operator's real ``config/view_layout.json`` with every dock hidden --
``closeEvent`` in ``gui/main_window.py`` does that on any window close, test
or not. Every config reader/writer in the app resolves its path through
``tavi.local_state.config_path()``, which honors the ``TAVI_CONFIG_DIR``
environment variable; this file points that variable at a temp copy of
``config/`` for the whole session, so nothing a test does can reach the real
files. A session-scoped tripwire fixture below re-hashes the real
``config/`` directory at teardown and fails the session if anything changed
regardless -- a test that bypassed the override, or a second process writing
beside this one.
"""
import hashlib
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


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
    if _CREATIONFLAGS_POS is None:
        # The signature could not be read, so a positional flags argument
        # cannot be recognised. Adding the keyword blind would raise "multiple
        # values for argument 'creationflags'" and kill a legitimate call, and
        # a guard that breaks the thing it guards is worse than no guard: leave
        # the call alone.
        return args, kwargs
    if len(args) > _CREATIONFLAGS_POS:
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
    # Guard 0: local state isolation -- must run before anything imports
    # tavi.local_state, so every reader/writer this session touches resolves
    # to the temp copy instead of the operator's real config/.
    tmp_dir = tempfile.mkdtemp(prefix="tavi-test-config-")
    real_config = os.path.join(REPO_ROOT, "config")
    tmp_config = os.path.join(tmp_dir, "config")
    if os.path.isdir(real_config):
        shutil.copytree(real_config, tmp_config, dirs_exist_ok=True)
    else:
        os.makedirs(tmp_config, exist_ok=True)
    os.environ["TAVI_CONFIG_DIR"] = tmp_config
    config._tavi_config_tmp_dir = tmp_dir
    # The tripwire baseline is taken here, before collection, so a module
    # that writes local state at import time cannot become its own baseline.
    config._tavi_local_state_before = _snapshot_local_state()

    # Guard 1: MCSTAS present -> McStasScript skips its shell=True probe.
    if "MCSTAS" not in os.environ:
        resources = _resolve_mcstas_resources()
        if resources:
            os.environ["MCSTAS"] = resources

    # Guard 2: nothing this session starts may open a console window.
    install_no_window_guard()


def pytest_unconfigure(config):
    tmp_dir = getattr(config, "_tavi_config_tmp_dir", None)
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _snapshot_local_state():
    """{relative path: sha256} of the real config/, plus output/'s entries.

    ``config/`` is walked recursively (skipping ``.pytest_cache`` and
    ``__pycache__``) so a changed file anywhere under it is caught; ``output/``
    is listed one level deep only -- a whole scan folder appearing or
    vanishing there is the signal, not its contents.
    """
    files = {}
    config_dir = os.path.join(REPO_ROOT, "config")
    if os.path.isdir(config_dir):
        for root, dirs, names in os.walk(config_dir):
            dirs[:] = [
                d for d in dirs if d not in (".pytest_cache", "__pycache__")
            ]
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, REPO_ROOT).replace(os.sep, "/")
                try:
                    with open(full, "rb") as fh:
                        files[rel] = hashlib.sha256(fh.read()).hexdigest()
                except OSError:
                    continue
    output_dir = os.path.join(REPO_ROOT, "output")
    output_entries = set(os.listdir(output_dir)) if os.path.isdir(output_dir) else set()
    return files, output_entries


@pytest.fixture(scope="session", autouse=True)
def _local_state_untouched(request):
    """Fail the session if anything reached the operator's real config/ or output/.

    Isolation (``TAVI_CONFIG_DIR``, set in ``pytest_configure``) should make
    this impossible; the tripwire exists for the case where isolation itself
    has a hole -- a reader/writer that still resolves its own path, or a
    second process running beside this one.
    """
    before_files, before_output = request.config._tavi_local_state_before
    yield
    after_files, after_output = _snapshot_local_state()
    changed = sorted(
        rel for rel in set(before_files) | set(after_files)
        if before_files.get(rel) != after_files.get(rel)
    )
    added_output = sorted(after_output - before_output)
    removed_output = sorted(before_output - after_output)
    if changed or added_output or removed_output:
        lines = ["tests wrote the operator's local state:"]
        lines.extend(f"  {rel}" for rel in changed)
        lines.extend(f"  output/{name} (added)" for name in added_output)
        lines.extend(f"  output/{name} (removed)" for name in removed_output)
        lines.append(
            "if TAVI or a second pytest was running beside this suite, that "
            "is the writer; otherwise a test bypassed TAVI_CONFIG_DIR."
        )
        pytest.fail("\n".join(lines))


@pytest.fixture(scope="session", autouse=True)
def _no_console_windows():
    """Fail loudly if the guard was undone, rather than silently spawning."""
    if sys.platform == "win32":
        assert getattr(subprocess.Popen.__init__, "_tavi_no_window", False), (
            "the CREATE_NO_WINDOW guard is not installed; see conftest.py"
        )
