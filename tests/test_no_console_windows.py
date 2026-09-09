"""The test run must not put windows on the operator's screen.

McStasScript's ``McStas_instr.__init__`` shells out twice per construction --
``mcrun --showcfg=resourcedir`` with ``shell=True`` when ``MCSTAS`` is unset,
and ``mcstas -v`` unconditionally, inside a bare ``except``. The build-tree
tests construct one instrument per module, so a few dozen runs in an afternoon
buried the desktop in console windows and error dialogs (measured 2026-09-09).

``conftest.py`` guards both. These tests fail if either guard is removed.
"""
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console behaviour")
def test_the_guard_is_installed():
    assert getattr(subprocess.Popen.__init__, "_tavi_no_window", False), (
        "conftest.py's CREATE_NO_WINDOW guard is missing; a subprocess "
        "started during the suite would open a console window"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only constants")
def test_the_guard_adds_the_flag_and_keeps_any_others():
    """Pins the transformation, since the absence of a window on the operator's
    screen is not observable from inside the harness -- the evidence for the
    flag being the right one is the 121 orphaned conhost.exe processes an
    afternoon of unguarded runs left behind (2026-09-09)."""
    from conftest import CREATE_NO_WINDOW, _CREATIONFLAGS_POS, apply_no_window

    _, kwargs = apply_no_window((), {})
    assert kwargs["creationflags"] & CREATE_NO_WINDOW

    group = subprocess.CREATE_NEW_PROCESS_GROUP
    _, kwargs = apply_no_window((), {"creationflags": group})
    assert kwargs["creationflags"] & CREATE_NO_WINDOW
    assert kwargs["creationflags"] & group

    # Passed positionally, it must be merged in place rather than duplicated
    # as a keyword -- that would raise before the child ever starts.
    positional = [None] * (_CREATIONFLAGS_POS + 1)
    positional[_CREATIONFLAGS_POS] = group
    args, kwargs = apply_no_window(tuple(positional), {})
    assert "creationflags" not in kwargs
    assert args[_CREATIONFLAGS_POS] & CREATE_NO_WINDOW
    assert args[_CREATIONFLAGS_POS] & group


def test_mcstas_env_var_is_set_so_mcstasscript_skips_its_shell_probe():
    """McStasScript only runs `mcrun --showcfg=resourcedir` when MCSTAS is unset.

    That branch uses shell=True, so it is a real cmd.exe. Setting the variable
    is what run-tavi-dev.bat does for the GUI, and conftest.py now does it for
    the suite.
    """
    resources = os.environ.get("MCSTAS")
    if resources is None:
        pytest.skip("no McStas resource directory found to point MCSTAS at")
    assert os.path.isdir(resources), f"MCSTAS points at a missing dir: {resources}"


def test_the_subprocess_guard_still_captures_output():
    """CREATE_NO_WINDOW must hide the console without detaching the process."""
    result = subprocess.run(
        [sys.executable, "-c", "print('captured')"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "captured" in result.stdout
