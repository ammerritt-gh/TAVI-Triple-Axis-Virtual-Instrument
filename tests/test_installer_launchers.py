"""Windows installer/launcher batch scripts added for the 1.3.1 release.

The defect being repaired: pre-1.3.1 launchers picked the TAVI environment by
NAME ("micromamba run -n tavi"), which resolves against whatever root
micromamba happens to inherit. A relocated install could then load its
program files from one place and its Python/mcrun from a stale same-named
environment elsewhere. The fix pins every micromamba call to an explicit
``-r <root> -p <prefix>``, both quoted. These tests hold that fix in place and
exercise the path-validation and destructive-uninstall behaviour it depends
on.

Pure Python + cmd.exe. No McStas, no Qt, no network, no micromamba binary.
Every subprocess call below carries an explicit timeout: a ``choice`` prompt
reading from an exhausted pipe re-prompts forever and would hang the suite.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch/cmd.exe behaviour")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER_DIR = os.path.join(ROOT, "installer")
LAUNCHERS_DIR = os.path.join(INSTALLER_DIR, "launchers")

INSTALL_1_3_1 = os.path.join(INSTALLER_DIR, "WINDOWS-install-TAVI-v1.3.1.bat")
UNINSTALL_STANDALONE = os.path.join(INSTALLER_DIR, "WINDOWS-uninstall-TAVI.bat")
REPAIR_LAUNCHERS = os.path.join(INSTALLER_DIR, "TAVI-Repair-Launchers.bat")
RUN_TAVI = os.path.join(LAUNCHERS_DIR, "run-tavi.bat")
UPDATE_TAVI = os.path.join(LAUNCHERS_DIR, "update-tavi.bat")
TAVI_LAUNCHER = os.path.join(LAUNCHERS_DIR, "TAVI-Launcher.bat")
UNINSTALL_TAVI = os.path.join(LAUNCHERS_DIR, "uninstall-tavi.bat")

# installer/WINDOWS-install-TAVI-v1.3.0.bat (the previous release, still kept
# in the tree for reference) is deliberately EXCLUDED from every table below:
# it is the old, name-selecting installer this release replaces, and it
# legitimately still says "run -n"/"create -n". test_old_v1_3_0_still_uses_
# named_selection (below) proves that file trips the same check this module
# asserts is clean everywhere else -- i.e. the check can fail.
NAMED_SELECTION_FILES = [INSTALL_1_3_1, UNINSTALL_STANDALONE, REPAIR_LAUNCHERS,
                          RUN_TAVI, UPDATE_TAVI, TAVI_LAUNCHER, UNINSTALL_TAVI]
INSTALL_1_3_0 = os.path.join(INSTALLER_DIR, "WINDOWS-install-TAVI-v1.3.0.bat")

# The four files that each carry their own standalone copy of :validate_base
# (installer/WINDOWS-install-TAVI-v1.3.1.bat's own comment names these same
# four -- installer/TAVI_Windows_Installer_Uninstaller_Design_Document.md
# section 22 is why it can't be a shared include: each has to keep working
# when the others are missing or stale).
VALIDATE_BASE_COPIES = [INSTALL_1_3_1, UNINSTALL_TAVI, UNINSTALL_STANDALONE, REPAIR_LAUNCHERS]

LABEL_FILES = [INSTALL_1_3_1, UNINSTALL_STANDALONE, REPAIR_LAUNCHERS,
               RUN_TAVI, UPDATE_TAVI, TAVI_LAUNCHER, UNINSTALL_TAVI]


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Helpers: run a real .bat file through cmd.exe without losing &, ^ or ;.
#
# subprocess's list-argument quoting (list2cmdline) only protects a value for
# the target program's own argv parser; it does NOT escape cmd.exe's own
# metacharacters (& ^ | < >), and cmd.exe recognises those even inside a
# double-quoted argument. Measured directly against this repo's echoarg
# probe while building this file: `["script.bat", r"C:\TAVI&rem"]` with
# shell=False reaches the script as just "C:\TAVI" -- the "&calc" is peeled
# off and handed to cmd.exe as a second, separate command. Wrapping the same
# value in quotes and using shell=True is not enough either: unescaped `^`
# is silently dropped by cmd.exe's own parser even inside quotes. Only
# caret-escaping cmd's metacharacters *before* quoting survives both cmd.exe
# parsing and the target program's argv parsing. test_naive_quoting_loses_
# ampersand below pins the failure mode this exists to avoid.
# ---------------------------------------------------------------------------
_CMD_METACHARS = set("&^|<>")


def _cmd_quote(arg):
    escaped = "".join("^" + ch if ch in _CMD_METACHARS else ch for ch in arg)
    return f'"{escaped}"'


def run_bat(path, *args, cwd=None, env=None, timeout=20, input_text=None):
    """Run a .bat file through cmd.exe with every argument intact.

    Builds one command-line string with every argument caret-escaped and
    quoted (see _cmd_quote), then runs it via shell=True so cmd.exe parses
    it the same way a double-click or a "start" call would.
    """
    cmdline = " ".join(_cmd_quote(str(a)) for a in [path, *args])
    return subprocess.run(
        cmdline, shell=True, cwd=cwd, env=env, timeout=timeout,
        capture_output=True, text=True,
        input=input_text, stdin=None if input_text is not None else subprocess.DEVNULL,
    )


def run_validate_only(path, value, **kwargs):
    return run_bat(path, "/validate-only", value, **kwargs)


# ===========================================================================
# 1. No named environment selection anywhere; every micromamba invocation is
#    pinned with a quoted -p.
# ===========================================================================

NAMED_SELECTION_PATTERNS = ("run -n", "create -n", "env remove -n")

# An "invocation" is a line that actually calls micromamba with a subcommand
# (run/create/env...), as opposed to a mere existence check
# (`if exist "%MICROMAMBA_EXE%"`) or a path assembled into a comment.
_INVOKE_RE = re.compile(r'"%MICROMAMBA_EXE%"\s+(?:-r\s+"[^"]*"\s+)?(run|create|env)\b')


def _code_lines(text):
    """Lines that are real batch code, not a "::" comment describing one."""
    return [line for line in text.splitlines() if not line.strip().startswith("::")]


def _named_selection_violations(text):
    code = "\n".join(_code_lines(text))
    return [p for p in NAMED_SELECTION_PATTERNS if p in code]


def _unpinned_invocations(text):
    """Invocation lines missing a quoted -p flag."""
    bad = []
    for line in text.splitlines():
        if _INVOKE_RE.search(line) and not re.search(r'-p\s+"[^"]+"', line):
            bad.append(line.strip())
    return bad


def test_no_named_environment_selection():
    for path in NAMED_SELECTION_FILES:
        text = _read(path)
        violations = _named_selection_violations(text)
        assert not violations, f"{path} still selects an environment by name: {violations}"


def test_every_micromamba_invocation_is_pinned_with_quoted_p():
    for path in NAMED_SELECTION_FILES:
        text = _read(path)
        bad = _unpinned_invocations(text)
        assert not bad, f"{path} invokes micromamba without a quoted -p: {bad}"


def test_old_v1_3_0_still_uses_named_selection():
    """Proves the two checks above can fail: run them against the release
    this one replaces, which legitimately still selects by name and is
    excluded from every other assertion in this module."""
    assert os.path.exists(INSTALL_1_3_0), "the old installer this test contrasts against is missing"
    text = _read(INSTALL_1_3_0)
    violations = _named_selection_violations(text)
    assert violations, "expected the v1.3.0 installer to still use named selection"
    assert "run -n" in violations and "create -n" in violations


# ===========================================================================
# 2. :validate_base is byte-identical across its four copies, and every file
#    with goto/call targets has a matching label for each one.
# ===========================================================================

_LABEL_RE = re.compile(r"(?m)^\s*:([A-Za-z_][A-Za-z0-9_]*)\s*$")
_GOTO_RE = re.compile(r"goto\s+:?([A-Za-z_][A-Za-z0-9_]*)")
_CALL_RE = re.compile(r"call\s+:([A-Za-z_][A-Za-z0-9_]*)")


def _labels_and_targets(text):
    # TAVI-Repair-Launchers.bat writes whole launcher scripts a line at a
    # time via "> "%TARGET%" echo ..."; those lines are text destined for a
    # DIFFERENT file's control flow (e.g. "echo goto run"), not a real goto
    # in this one, and would otherwise look like a dangling target here.
    real_flow = "\n".join(
        line for line in text.splitlines()
        if not re.match(r'^\s*>>?\s*"%TARGET%"', line)
    )
    labels = {m.group(1).lower() for m in _LABEL_RE.finditer(text)}
    labels.add("eof")  # built in
    targets = {m.group(1).lower() for m in _GOTO_RE.finditer(real_flow)}
    targets |= {m.group(1).lower() for m in _CALL_RE.finditer(real_flow)}
    return labels, targets


@pytest.mark.parametrize("path", LABEL_FILES)
def test_every_goto_and_call_target_has_a_label(path):
    text = _read(path)
    labels, targets = _labels_and_targets(text)
    missing = sorted(targets - labels)
    assert not missing, f"{path}: goto/call target(s) with no matching label: {missing}"


def _validate_base_body(path):
    """The routine itself, from its label line to end of file -- not the
    comments that name it."""
    text = _read(path)
    match = re.search(r"(?m)^:validate_base\s*$", text)
    assert match, f"{path} has no :validate_base label"
    return text[match.start():].strip()


def test_validate_base_is_byte_identical_across_its_four_copies():
    reference_path = VALIDATE_BASE_COPIES[0]
    reference = _validate_base_body(reference_path)
    for path in VALIDATE_BASE_COPIES[1:]:
        other = _validate_base_body(path)
        if other != reference:
            diff = "\n".join(difflib.unified_diff(
                reference.splitlines(), other.splitlines(),
                fromfile=reference_path, tofile=path, lineterm=""))
            pytest.fail(f":validate_base differs between {reference_path} and {path}:\n{diff}")


# ===========================================================================
# 3. Path validation, table-driven, through the real /validate-only switch.
# ===========================================================================

VALIDATE_ONLY_FILES = [INSTALL_1_3_1, UNINSTALL_TAVI]

ACCEPT_CASES = [
    "C:\\TAVI",
    "C:\\TAVI\\",  # trailing backslash, stripped and still accepted
    "D:\\Sci\\TAVI-Data",
]

REFUSE_CASES = [
    ("C:\\TAVI Data", "space"),
    ("C:\\TAVI\\..", "dot-dot"),
    ("C:\\Windows.", "trailing dot"),
    ("C:\\", "drive root"),
    ("TAVI", "bare relative name"),
    ("\\\\server\\share\\TAVI", "UNC path"),
    ("C:\\Data(old)\\TAVI", "parentheses"),
    # "&rem" and not "&calc": if the guard ever regresses, an injected `rem` is a
    # no-op, where an injected `calc` opens a window on whoever ran the suite.
    ("C:\\TAVI&rem", "ampersand"),
    ("C:\\TAVI^x", "caret"),
    ("C:\\TAVI;x", "semicolon"),
    ("C:\\TAVI'x", "apostrophe"),
    # These three are the regression guard for a defect this test found. The
    # validator used the range [A-Za-z0-9...], and findstr resolves a range
    # through the machine's collation order, which places accented Latin
    # letters inside A-Z: C:\TAVE-with-an-acute was measured ACCEPTED, while a
    # non-Latin character (euro sign, CJK, Cyrillic) was correctly refused. The
    # class is now written out character by character, so no range is involved.
    ("C:\\TAV\u00c9", "accented Latin capital"),
    ("C:\\T\u00e4vi", "accented Latin lowercase"),
    ("C:\\TAVI\u20ac", "non-Latin symbol"),
]


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
@pytest.mark.parametrize("value", ACCEPT_CASES)
def test_validate_only_accepts_well_formed_paths(script, value):
    result = run_validate_only(script, value)
    assert result.stdout.strip() == "ACCEPT", (script, value, result.stdout, result.stderr)
    assert result.returncode == 0


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
def test_validate_only_accepts_an_existing_directory(script, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    result = run_validate_only(script, str(target))
    assert result.stdout.strip() == "ACCEPT", (script, result.stdout, result.stderr)
    assert result.returncode == 0


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
@pytest.mark.parametrize("value,label", REFUSE_CASES)
def test_validate_only_refuses_bad_paths(script, value, label):
    result = run_validate_only(script, value)
    assert result.stdout.startswith("REFUSE"), (script, label, value, result.stdout, result.stderr)
    assert result.returncode == 1


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
def test_validate_only_refuses_userprofile_itself(script):
    result = run_validate_only(script, os.environ["USERPROFILE"])
    assert result.stdout.startswith("REFUSE"), result.stdout
    assert "user folder" in result.stdout


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
def test_validate_only_refuses_systemroot(script):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    result = run_validate_only(script, system_root)
    assert result.stdout.startswith("REFUSE"), result.stdout
    assert "Windows folder" in result.stdout


@pytest.mark.parametrize("script", VALIDATE_ONLY_FILES)
def test_validate_only_refuses_a_junction(script, tmp_path):
    target = tmp_path / "real-target"
    target.mkdir()
    link = tmp_path / "TAVI"
    mk = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True, timeout=20)
    assert mk.returncode == 0, mk.stdout + mk.stderr
    result = run_validate_only(script, str(link))
    assert result.stdout.startswith("REFUSE"), result.stdout
    assert "junction" in result.stdout


def test_naive_quoting_loses_ampersand_where_ours_does_not():
    """Pins the exact bug the CRITICAL GOTCHA in this module's docstring
    describes: with plain list-argument quoting, "C:\\TAVI&rem" is silently
    truncated by cmd.exe to the clean path "C:\\TAVI" before the script ever
    sees it, so a broken test harness would have ACCEPTed a value the real
    installer must refuse. Demonstrates the failure mode our run_bat/_cmd_quote
    helper (used everywhere else in this module) avoids.
    """
    naive = subprocess.run(
        [INSTALL_1_3_1, "/validate-only", "C:\\TAVI&rem"],
        capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
    )
    correct = run_validate_only(INSTALL_1_3_1, "C:\\TAVI&rem")
    assert naive.stdout.strip() == "ACCEPT", (
        "expected the naively-quoted call to be fooled by the truncation; "
        f"got {naive.stdout!r} instead -- if this changed, the gotcha this "
        "test documents may no longer apply and the comment should be revisited"
    )
    assert correct.stdout.startswith("REFUSE")
    assert naive.stdout.strip() != correct.stdout.strip()


# ===========================================================================
# 4. Behavioural: run-tavi.bat, update-tavi.bat and the menu's "Open TAVI
#    shell" all resolve the environment from their own folder, never from an
#    inherited MAMBA_ROOT_PREFIX.
# ===========================================================================

_STUB_CS = textwrap.dedent(r"""
    using System;
    using System.IO;

    class MicromambaStub
    {
        static int Main(string[] args)
        {
            string log = Environment.GetEnvironmentVariable("MICROMAMBA_STUB_LOG");
            if (log != null)
            {
                File.AppendAllText(log, string.Join("\u0001", args) + "\n");
            }
            return 0;
        }
    }
    """)

CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not os.path.exists(CSC):
    CSC = r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"


@pytest.fixture(scope="module")
def micromamba_stub_exe(tmp_path_factory):
    """A tiny real .exe (not a .bat) that records its argv and exits 0.

    The launchers hardcode "%TAVI_BASE%\\micromamba\\micromamba.exe" as a
    literal filename with the .exe extension already attached, so Windows
    looks for exactly that file and does not fall back to a same-named .bat
    via PATHEXT. A genuine PE binary is the only thing that lands there
    without changing the launchers themselves. csc.exe (the .NET Framework
    compiler that ships with Windows) builds it in well under a second, with
    no network access and no project/toolchain beyond what the OS carries.
    """
    if not os.path.exists(CSC):
        pytest.skip("no .NET Framework csc.exe found to build the micromamba stub")
    work = tmp_path_factory.mktemp("stub_src")
    src = work / "Stub.cs"
    src.write_text(_STUB_CS, encoding="utf-8", newline="\n")
    exe = work / "micromamba.exe"
    result = subprocess.run(
        [CSC, "/nologo", f"/out:{exe}", str(src)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f"could not build the micromamba stub: {result.stdout}{result.stderr}")
    return str(exe)


def _make_layout2_base(tmp_path, name, stub_exe, with_python=True):
    """A minimal layout-2 install tree under tmp_path, real enough for the
    three launchers to run their checks and reach a micromamba call."""
    base = tmp_path / name
    app = base / "app"
    app.mkdir(parents=True)
    (app / "TAVI_PySide6.py").write_text("# stub\n", encoding="utf-8", newline="\n")
    (app / ".git").mkdir()

    env_prefix = base / "tavi-env"
    (env_prefix / "share" / "mcstas" / "resources").mkdir(parents=True)
    if with_python:
        (env_prefix / "python.exe").write_bytes(b"")

    micromamba_dir = base / "micromamba"
    micromamba_dir.mkdir()
    shutil.copy2(stub_exe, micromamba_dir / "micromamba.exe")

    (base / "mamba").mkdir()

    (base / "INSTALL_INFO.txt").write_text(
        "TAVI_VERSION=v1.3.1\nLAYOUT=2\nINSTALL_ID=test-id\n", encoding="utf-8", newline="\n")

    for launcher in ("run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat"):
        shutil.copy2(os.path.join(LAUNCHERS_DIR, launcher), base / launcher)

    return base, env_prefix, base / "mamba"


def _read_stub_log(log_path):
    if not os.path.exists(log_path):
        return []
    with open(log_path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\n").split("\u0001") for line in fh if line.strip()]


def _stub_env(log_path, wrong_root):
    env = dict(os.environ)
    env["MICROMAMBA_STUB_LOG"] = str(log_path)
    env["MAMBA_ROOT_PREFIX"] = str(wrong_root)
    return env


def test_run_tavi_ignores_inherited_mamba_root_prefix(tmp_path, micromamba_stub_exe):
    base, env_prefix, own_root = _make_layout2_base(tmp_path, "base1", micromamba_stub_exe)
    wrong_root = tmp_path / "wrong-inherited-root"
    wrong_root.mkdir()
    log = tmp_path / "stub1.log"

    result = run_bat(str(base / "run-tavi.bat"), env=_stub_env(log, wrong_root), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

    calls = _read_stub_log(log)
    assert calls, "run-tavi.bat never invoked micromamba"
    argv = calls[0]
    assert "-r" in argv and "-p" in argv
    assert argv[argv.index("-r") + 1] == str(own_root)
    assert argv[argv.index("-p") + 1] == str(env_prefix)
    assert str(wrong_root) not in argv


def test_update_tavi_ignores_inherited_mamba_root_prefix(tmp_path, micromamba_stub_exe):
    base, env_prefix, own_root = _make_layout2_base(tmp_path, "base2", micromamba_stub_exe)
    wrong_root = tmp_path / "wrong-inherited-root"
    wrong_root.mkdir()
    log = tmp_path / "stub2.log"

    result = run_bat(str(base / "update-tavi.bat"), env=_stub_env(log, wrong_root), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

    calls = _read_stub_log(log)
    assert len(calls) >= 3, f"expected fetch/checkout/smoke-test calls, got {calls}"
    for argv in calls:
        assert "-r" in argv and "-p" in argv
        assert argv[argv.index("-r") + 1] == str(own_root)
        assert argv[argv.index("-p") + 1] == str(env_prefix)
        assert str(wrong_root) not in argv


def test_launcher_shell_option_ignores_inherited_mamba_root_prefix(tmp_path, micromamba_stub_exe):
    base, env_prefix, own_root = _make_layout2_base(tmp_path, "base3", micromamba_stub_exe)
    wrong_root = tmp_path / "wrong-inherited-root"
    wrong_root.mkdir()
    log = tmp_path / "stub3.log"

    # [4] Open TAVI shell, then [5] Exit.
    result = run_bat(str(base / "TAVI-Launcher.bat"), env=_stub_env(log, wrong_root),
                      timeout=30, input_text="4\n5\n")
    assert result.returncode == 0, result.stdout + result.stderr

    calls = _read_stub_log(log)
    assert calls, "the menu's Open TAVI shell option never invoked micromamba"
    argv = calls[0]
    assert "-r" in argv and "-p" in argv
    assert argv[argv.index("-r") + 1] == str(own_root)
    assert argv[argv.index("-p") + 1] == str(env_prefix)
    assert str(wrong_root) not in argv


def test_run_tavi_fails_visibly_when_python_is_missing(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base4", micromamba_stub_exe, with_python=False)
    result = run_bat(str(base / "run-tavi.bat"), timeout=30)
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout


def test_update_tavi_fails_visibly_when_python_is_missing(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base5", micromamba_stub_exe, with_python=False)
    result = run_bat(str(base / "update-tavi.bat"), timeout=30)
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout


def test_launcher_shell_option_fails_visibly_when_python_is_missing(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base6", micromamba_stub_exe, with_python=False)
    # [4] Open TAVI shell -> "[ERROR]" + pause (consumes the blank line) ->
    # back to the menu -> [5] Exit. The menu recovers by design (it loops
    # back rather than terminating the process), so unlike run-tavi.bat and
    # update-tavi.bat above there is no non-zero exit to assert here -- only
    # that the failure was reported before the menu let the user continue.
    result = run_bat(str(base / "TAVI-Launcher.bat"), timeout=30, input_text="4\n\n5\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[ERROR]" in result.stdout


# ===========================================================================
# 5. The menu dispatches on exact ERRORLEVEL comparisons, never a descending
#    ladder; Exit is 5, Uninstall is 6.
# ===========================================================================

def test_menu_dispatch_has_no_if_errorlevel_ladder():
    """Scoped to the PICK dispatch block itself (choice -> goto menu): the
    file legitimately uses "if errorlevel 1 goto ..." elsewhere, after copy
    commands, to check a command's own exit code -- that idiom is fine. What
    must never happen is dispatching the choice/PICK result with a
    descending "if errorlevel" ladder, since choice returns 255 on error and
    0 on Ctrl-C, and a ladder would route both into whatever branch sits at
    the top -- which must never be Uninstall.
    """
    text = _read(TAVI_LAUNCHER)
    start = text.index("choice /C 123456")
    end = text.index("goto menu", start)
    dispatch_block = text[start:end]
    offenders = [l for l in dispatch_block.splitlines() if re.match(r"^\s*if\s+errorlevel\b", l, re.I)]
    assert not offenders, f"menu dispatch uses an errorlevel ladder: {offenders}"


def test_exit_is_five_and_uninstall_is_six():
    text = _read(TAVI_LAUNCHER)
    assert 'if "%PICK%"=="5" goto quit' in text
    assert 'if "%PICK%"=="6" goto uninstall' in text
    assert "[5] Exit" in text
    assert "[6] Uninstall TAVI" in text


def test_menu_exits_cleanly_on_five():
    result = run_bat(TAVI_LAUNCHER, timeout=20, input_text="5\n")
    assert result.returncode == 0, result.stdout + result.stderr


# ===========================================================================
# 6. Destructive uninstall path, sandboxed under tmp_path.
#
# uninstall-tavi.bat relaunches itself via "start" (a detached process) only
# when it finds itself running from *inside* the folder it targets (the
# normal double-click case, matching where the installer places it). Called
# with an explicit target directory from anywhere else -- exactly how these
# tests call it, from its real installer/launchers/ location -- it validates
# and acts synchronously, which is what tests/test_installer_launchers.py is
# told (by the file's own comment) it exists to make possible. Tests here
# therefore never run it in-place: doing so would hand off to a detached,
# interactive "pause"d console we could not safely wait on or clean up.
#
# A genuinely empty base argument is a special case: "%~1" being empty
# unsets TAVI_BASE entirely, and the script always then defaults it to its
# own directory before validate_base ever sees it -- so the real CLI can
# never reach ":validate_base """ synchronously; it can only be reached via
# the in-place relaunch this module avoids for the reason above. The
# /validate-only switch calls the identical :validate_base routine the real
# CLI does, so it is used here to prove the same gate refuses an empty path.
# ===========================================================================

def _install_id_files(base, install_id="test-id", info_id=None):
    (base / ".tavi-install-root").write_text(
        f"LAYOUT=2\nINSTALL_ID={install_id}\n", encoding="utf-8", newline="\n")
    (base / "INSTALL_INFO.txt").write_text(
        f"TAVI_VERSION=v1.3.1\nLAYOUT=2\nINSTALL_ID={info_id or install_id}\n",
        encoding="utf-8", newline="\n")


def _uninstallable_base(tmp_path, name, install_id="test-id", info_id=None, extra_file=None):
    base = tmp_path / name
    app = base / "app"
    app.mkdir(parents=True)
    (app / "TAVI_PySide6.py").write_text("# stub\n", encoding="utf-8", newline="\n")
    (base / "tavi-env").mkdir()
    (base / "tavi-env" / "python.exe").write_bytes(b"")
    (base / "micromamba").mkdir()
    (base / "mamba").mkdir()
    (base / "compile_check").mkdir()
    (base / "compile_check" / "PSI_DMC.instr").write_text("x", encoding="utf-8", newline="\n")
    for launcher in ("run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat", "uninstall-tavi.bat"):
        shutil.copy2(os.path.join(LAUNCHERS_DIR, launcher), base / launcher)
    _install_id_files(base, install_id=install_id, info_id=info_id)
    if extra_file:
        (base / extra_file).write_text("keep me\n", encoding="utf-8", newline="\n")
    return base


def test_validate_only_refuses_empty_path_same_gate_the_cli_uses():
    result = run_validate_only(UNINSTALL_TAVI, "")
    assert result.stdout.strip() == "REFUSE the path is empty", result.stdout
    assert result.returncode == 1


def test_uninstall_refuses_a_base_with_no_marker(tmp_path):
    base = tmp_path / "no_marker"
    base.mkdir()
    (base / "app").mkdir()
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=20)
    assert result.returncode == 1
    assert "ownership marker" in result.stdout
    assert (base / "app").exists(), "an unmarked folder must be left untouched"


def test_uninstall_refuses_on_install_id_mismatch(tmp_path):
    base = _uninstallable_base(tmp_path, "mismatch", install_id="AAA", info_id="BBB")
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=20)
    assert result.returncode == 1
    assert "does not match" in result.stdout
    assert (base / "app" / "TAVI_PySide6.py").exists(), "a mismatched marker must not delete anything"


def test_uninstall_refuses_a_junction_base(tmp_path):
    target = _uninstallable_base(tmp_path, "junction-target")
    link = tmp_path / "junction-link"
    mk = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True, timeout=20)
    assert mk.returncode == 0, mk.stdout + mk.stderr
    result = run_bat(UNINSTALL_TAVI, str(link), "/y", timeout=20)
    assert result.returncode == 1
    assert "junction" in result.stdout
    assert (target / "app").exists(), "a junction base must not be deleted through"


def test_uninstall_refuses_a_drive_root():
    # No filesystem fixture needed: validate_base refuses "C:\" before
    # anything is touched, so this is safe to run against a real drive.
    result = run_bat(UNINSTALL_TAVI, "C:\\", "/y", timeout=20)
    assert result.returncode == 1
    # "C:\" loses its trailing backslash in validate_base's own normalisation
    # before the drive-letter checks run, so the actual reason given is "it
    # must start with a drive letter" rather than "a whole drive cannot be
    # the TAVI folder" -- both are the drive-root gate refusing it.
    assert "drive" in result.stdout


def test_uninstall_succeeds_on_a_well_formed_installation(tmp_path):
    base = _uninstallable_base(tmp_path, "clean")
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "has been removed" in result.stdout
    for child in ("app", "tavi-env", "micromamba", "mamba", "compile_check",
                  "run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat", "uninstall-tavi.bat"):
        assert not (base / child).exists(), f"{child} should have been removed"
    assert not base.exists(), "a clean install's base folder must be removed entirely"


def test_uninstall_leaves_extra_user_files_and_the_base_folder_standing(tmp_path):
    base = _uninstallable_base(tmp_path, "leftover", extra_file="my_notes.txt")
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (base / "app").exists()
    assert not (base / "tavi-env").exists()
    assert not (base / "micromamba").exists()
    assert not (base / "mamba").exists()
    assert not (base / "compile_check").exists()
    assert base.exists(), "a base folder holding user files must survive"
    assert (base / "my_notes.txt").exists(), "the user's own file must survive"
    assert "were not TAVI's" in result.stdout


@pytest.mark.parametrize("script", LABEL_FILES)
def test_nothing_in_the_install_path_opens_a_console(script):
    """`start` gives the new process its own console window.

    Two reasons that is wrong here. For the operator it is a window appearing
    for no reason in the middle of an uninstall. For this suite it is a window
    that cannot be suppressed: conftest.py puts CREATE_NO_WINDOW on processes
    the session creates, and a process cmd detaches with `start` is not one of
    them. The uninstall hand-off gets the same guarantees by changing directory
    out of the tree and `call`ing the copy in the console already open, with the
    copy ending the process so the caller never reads its deleted self.

    installer/TAVI-Doctor.bat is not in this list: it opens its own report in
    Notepad for a human who double-clicked it, and has a /quiet flag for
    everyone else.
    """
    with open(script, encoding="utf-8", errors="replace", newline="") as stream:
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(stream, 1)
            if re.match(r"^\s*start\s", line)
        ]
    assert not offenders, (
        f"{os.path.basename(script)} opens a console window: {offenders}"
    )


@pytest.mark.parametrize("script", LABEL_FILES)
def test_no_redirection_follows_a_value_on_an_echo_line(script):
    """`echo NAME=%VALUE%> "file"` eats a value that ends in a digit.

    cmd reads the digit immediately before a redirection operator as the
    stream number, so `echo LAYOUT=2>> "file"` appends *stderr* and writes
    `LAYOUT=` to the console instead. Measured on the first cold install of
    v1.3.1: INSTALL_INFO.txt and the ownership marker came out with no LAYOUT
    line, and the uninstaller then refused every genuine installation. The
    safe form puts the redirection first, which these files use throughout.
    """
    with open(script, encoding="utf-8", errors="replace", newline="") as stream:
        offenders = [
            line.strip()
            for line in stream
            if re.match(r"^\s*echo [^>|]*%[A-Za-z_][A-Za-z0-9_]*%\s*>>?\s*\"", line)
        ]
    assert not offenders, (
        f"{os.path.basename(script)} writes a variable's value immediately before a "
        f"redirection; put the redirection first: {offenders}"
    )


def test_the_installer_writes_a_layout_line_the_uninstaller_can_read():
    """The ownership gate is keyed on LAYOUT, so it has to reach the file."""
    with open(INSTALL_1_3_1, encoding="utf-8", newline="") as stream:
        text = stream.read()
    assert re.search(r'(?m)^>>? "%TAVI_BASE%\\INSTALL_INFO\.txt" echo LAYOUT=%LAYOUT%$', text), \
        "INSTALL_INFO.txt must get a LAYOUT line, written with the redirection first"
    assert re.search(r'(?m)^>>? "%MARKER%" echo LAYOUT=%LAYOUT%$', text), \
        "the ownership marker must get a LAYOUT line, written with the redirection first"
