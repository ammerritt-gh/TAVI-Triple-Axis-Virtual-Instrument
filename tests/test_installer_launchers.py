"""Windows installer/launcher batch scripts added for the 1.3.2 release.

The defect being repaired: pre-1.3.2 launchers picked the TAVI environment by
NAME ("micromamba run -n tavi"), which resolves against whatever root
micromamba happens to inherit. A relocated install could then load its
program files from one place and its Python/mcrun from a stale same-named
environment elsewhere. The fix pins every micromamba call to an explicit
``-r <root> -p <prefix>``, both quoted. These tests hold that fix in place and
exercise the path-validation and destructive-uninstall behaviour it depends
on.

Pure Python + cmd.exe. No McStas, no Qt, no network, no micromamba binary.
Every subprocess call below carries an explicit timeout, in case a prompt
ever waits for input that never comes.

No test here may make a console beep. ``choice`` calls kernel32 ``Beep`` (a
blocking half second at the sound device, nothing on stdout) for every input
character outside its /C list, and that includes the CR LF a test sends after
a key. ``choice`` takes one character per prompt and leaves the rest in the
pipe, so a test feeds exactly the keys the prompts accept, in order, with no
line ending, and a ``set /p`` prompt is the only place a line ending belongs.
The ``choice_sensor`` fixture enforces this: a stand-in ``choice.exe`` first on
PATH logs every character it would have beeped at, and a test fails if any.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import warnings
import zipfile

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch/cmd.exe behaviour")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER_DIR = os.path.join(ROOT, "installer")
LAUNCHERS_DIR = os.path.join(INSTALLER_DIR, "launchers")

INSTALL_1_3_2 = os.path.join(INSTALLER_DIR, "WINDOWS-install-TAVI-v1.3.2.bat")
INSTALL_1_4_0 = os.path.join(INSTALLER_DIR, "WINDOWS-install-TAVI-v1.4.0.bat")
UNINSTALL_STANDALONE = os.path.join(INSTALLER_DIR, "WINDOWS-uninstall-TAVI.bat")
REPAIR_LAUNCHERS = os.path.join(INSTALLER_DIR, "TAVI-Repair-Launchers.bat")
RUN_TAVI = os.path.join(LAUNCHERS_DIR, "run-tavi.bat")
UPDATE_TAVI = os.path.join(LAUNCHERS_DIR, "update-tavi.bat")
TAVI_LAUNCHER = os.path.join(LAUNCHERS_DIR, "TAVI-Launcher.bat")
UNINSTALL_TAVI = os.path.join(LAUNCHERS_DIR, "uninstall-tavi.bat")
COLLECT_DIAG = os.path.join(LAUNCHERS_DIR, "collect-diagnostics.bat")

# LAST_NAMED_INSTALLER (the last release's installer, still kept in the tree
# for reference) is deliberately EXCLUDED from every table below: it is the
# old, name-selecting installer the 1.3.2 one replaced, and it legitimately
# still says "run -n"/"create -n". test_the_last_named_installer_still_uses_
# named_selection (below) proves that file trips the same check this module
# asserts is clean everywhere else -- i.e. the check can fail.
NAMED_SELECTION_FILES = [INSTALL_1_3_2, INSTALL_1_4_0, UNINSTALL_STANDALONE, REPAIR_LAUNCHERS,
                          RUN_TAVI, UPDATE_TAVI, TAVI_LAUNCHER, UNINSTALL_TAVI, COLLECT_DIAG]
# Its version is assembled rather than written out: the release tool refuses a
# tracked file that still names the version being bumped away from, and this
# reference to a historical file is deliberate, not a leftover.
LAST_NAMED_INSTALLER = os.path.join(
    INSTALLER_DIR, "WINDOWS-install-TAVI-v%s.bat" % ".".join(("1", "3", "0")))

# The files that each carry their own standalone copy of :validate_base (each
# copy's comment points here -- installer/TAVI_Windows_Installer_Uninstaller_
# Design_Document.md section 22 is why it can't be a shared include: each has
# to keep working when the others are missing or stale).
DOCTOR = os.path.join(INSTALLER_DIR, "TAVI-Doctor.bat")
RECORD_TAVI = os.path.join(ROOT, "tools", "support", "Record-TAVI.bat")
VALIDATE_BASE_COPIES = [INSTALL_1_3_2, INSTALL_1_4_0, UNINSTALL_TAVI, UNINSTALL_STANDALONE,
                        REPAIR_LAUNCHERS, DOCTOR, RECORD_TAVI]

LABEL_FILES = [INSTALL_1_3_2, INSTALL_1_4_0, UNINSTALL_STANDALONE, REPAIR_LAUNCHERS,
               RUN_TAVI, UPDATE_TAVI, TAVI_LAUNCHER, UNINSTALL_TAVI, COLLECT_DIAG]


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _sandboxed_localappdata(tmp_path_factory, monkeypatch):
    """Since 1.4 the launchers write logs under %LOCALAPPDATA%\\TAVI\\logs, and
    run-tavi.bat deletes all but the ten newest launch logs there. A child that
    inherits this process's environment must never reach the operator's real
    folder, so every test here starts with LOCALAPPDATA in a temp folder; a
    test that builds its own environment from os.environ inherits that too.

    The uninstallers remove a "TAVI Launcher" shortcut from the desktop Windows
    reports. TAVI_TEST_DESKTOP, which they honour for tests only, points that
    lookup at a temp folder too, so no test here ever reaches a real desktop."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata-guard")))
    monkeypatch.setenv("TAVI_TEST_DESKTOP", str(tmp_path_factory.mktemp("desktop-guard")))


# A stand-in for choice.exe that behaves like it for every use in these files
# (/C list, /N, /M, one character at a time, 255 and a message at end of input)
# and records each character outside the /C list instead of beeping at it.
# Test-only: nothing in installer/ refers to it.
_CHOICE_CS = textwrap.dedent(r"""
    using System;
    using System.IO;

    class ChoiceSensor
    {
        static int Main(string[] args)
        {
            string keys = "", message = "";
            string log = Environment.GetEnvironmentVariable("TAVI_CHOICE_LOG");
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToUpperInvariant();
                if (a == "/C" && i + 1 < args.Length) keys = args[++i].ToUpperInvariant();
                else if (a == "/M" && i + 1 < args.Length) message = args[++i];
                else if (a != "/N" && log != null)
                    File.AppendAllText(log, "UNSUPPORTED choice argument " + args[i] + "\n");
            }
            Console.Out.Write(message + " ");
            Console.Out.Flush();
            Stream input = Console.OpenStandardInput();
            while (true)
            {
                int b = input.ReadByte();
                if (b < 0)
                {
                    Console.Error.Write("\r\nERROR: The file is either empty or does not contain the valid choices.\r\n");
                    return 255;
                }
                int at = keys.IndexOf(char.ToUpperInvariant((char)b));
                if (at >= 0)
                {
                    Console.Out.Write(keys[at] + "\r\n");
                    return at + 1;
                }
                if (log != null)
                    File.AppendAllText(log, "BEEP at 0x" + b.ToString("X2") + " in /C " + keys + "\n");
            }
        }
    }
    """)


@pytest.fixture(scope="session")
def _choice_sensor_dir(tmp_path_factory):
    if not os.path.exists(CSC):
        warnings.warn("no csc.exe: the suite cannot check that its input stays silent")
        return None
    work = tmp_path_factory.mktemp("choice_sensor")
    (work / "Choice.cs").write_text(_CHOICE_CS, encoding="utf-8", newline="\n")
    result = subprocess.run([CSC, "/nologo", f"/out:{work / 'choice.exe'}", str(work / "Choice.cs")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return str(work)


@pytest.fixture(autouse=True)
def choice_sensor(_choice_sensor_dir, tmp_path_factory, monkeypatch):
    """Fail the test if anything it ran beeped (see the module docstring).
    A child that sets its own PATH adds os.environ["TAVI_CHOICE_SENSOR_DIR"]."""
    log = tmp_path_factory.mktemp("choice-log") / "choice-sensor.log"
    if _choice_sensor_dir is not None:
        monkeypatch.setenv("TAVI_CHOICE_SENSOR_DIR", _choice_sensor_dir)
        monkeypatch.setenv("TAVI_CHOICE_LOG", str(log))
        monkeypatch.setenv("PATH", _choice_sensor_dir + os.pathsep + os.environ["PATH"])
    yield
    beeps = log.read_text(encoding="utf-8") if log.exists() else ""
    assert not beeps, "choice would have beeped:\n" + beeps


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


def run_bat(path, *args, cwd=None, env=None, timeout=20, input_text=None, input_file=None):
    """Run a .bat file through cmd.exe with every argument intact.

    Builds one command-line string with every argument caret-escaped and
    quoted (see _cmd_quote), then runs it via shell=True so cmd.exe parses
    it the same way a double-click or a "start" call would.

    input_file: the keys come from that file instead of a pipe. A `set /p`
    reading a pipe takes everything in it, not just its line, so a run that
    answers a `set /p` and then a `choice` needs a file, which `set /p`
    leaves positioned after its line.
    """
    cmdline = " ".join(_cmd_quote(str(a)) for a in [path, *args])
    if input_file is not None:
        with open(input_file, "rb") as stdin:
            result = subprocess.run(cmdline, shell=True, cwd=cwd, env=env, timeout=timeout,
                                    capture_output=True, text=True, stdin=stdin)
    else:
        result = subprocess.run(
            cmdline, shell=True, cwd=cwd, env=env, timeout=timeout,
            capture_output=True, text=True,
            input=input_text, stdin=None if input_text is not None else subprocess.DEVNULL,
        )
    # A literal BEL on the output beeps too. choice's own beep is not on stdout
    # (see the choice_sensor fixture), so this covers everything else.
    assert "\x07" not in result.stdout + result.stderr, f"{path} wrote a BEL character"
    return result


def run_validate_only(path, value, **kwargs):
    return run_bat(path, "/validate-only", value, **kwargs)


# ===========================================================================
# 1. No named environment selection anywhere; every micromamba invocation is
#    pinned with a quoted -p.
# ===========================================================================

# Match the *concept*, not today's spelling: `run --name tavi` is the same
# defect as `run -n tavi`. But only micromamba's OWN name flag counts - the
# program it launches has its own options, and `mcrun ... -n 1000` is a neutron
# count. So look only at the tokens that belong to micromamba: those before the
# subcommand, and the one directly after it.
_SUBCOMMANDS = {"run", "create", "install", "update", "remove", "env"}
_NAME_FLAGS = {"-n", "--name"}


def _micromamba_name_flag(line):
    """The micromamba name selector on this line, or None.

    Tokens are scanned from the executable up to and including the flag that
    directly follows the subcommand; anything past that belongs to the program
    micromamba is launching, not to micromamba.
    """
    marker = '"%MICROMAMBA_EXE%"'
    if marker not in line:
        return None
    tokens = line.split(marker, 1)[1].split()
    for index, token in enumerate(tokens):
        if token in _NAME_FLAGS:
            return token
        if token in _SUBCOMMANDS:
            # `env remove -n` puts the subcommand's own verb in between
            tail = tokens[index + 1:index + 3] if token == "env" else tokens[index + 1:index + 2]
            for candidate in tail:
                if candidate in _NAME_FLAGS:
                    return candidate
            return None
    return None

# An "invocation" is a line that actually calls micromamba with a subcommand
# (run/create/env...), as opposed to a mere existence check
# (`if exist "%MICROMAMBA_EXE%"`) or a path assembled into a comment.
_INVOKE_RE = re.compile(r'"%MICROMAMBA_EXE%"\s+(?:-r\s+"[^"]*"\s+)?(run|create|env)\b')


def _code_lines(text):
    """Lines that are real batch code, not a "::" comment describing one."""
    return [line for line in text.splitlines() if not line.strip().startswith("::")]


def _named_selection_violations(text):
    return [line.strip() for line in _code_lines(text) if _micromamba_name_flag(line)]


def _unpinned_invocations(text):
    """Invocation lines missing a quoted -r or a quoted -p.

    Both, not either: the stated invariant is that every call names the root
    AND the prefix explicitly, so that neither an inherited MAMBA_ROOT_PREFIX
    nor an inherited CONDA_PREFIX can reach the decision. An earlier version of
    this helper made -r optional, which would have passed a file that had
    quietly gone back to relying on the environment for it.
    """
    bad = []
    for line in _code_lines(text):
        if not _INVOKE_RE.search(line):
            continue
        if not re.search(r'-p\s+"[^"]+"', line) or not re.search(r'-r\s+"[^"]+"', line):
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


def test_the_last_named_installer_still_uses_named_selection():
    """Proves the two checks above can fail: run them against the release
    this one replaces, which legitimately still selects by name and is
    excluded from every other assertion in this module."""
    assert os.path.exists(LAST_NAMED_INSTALLER), "the old installer this test contrasts against is missing"
    text = _read(LAST_NAMED_INSTALLER)
    violations = _named_selection_violations(text)
    assert violations, "expected the last named installer to still use named selection"
    joined = "\n".join(violations)
    assert "run -n" in joined and "create -n" in joined
    # and the detector must not be fooled by a program's own -n: the old file's
    # compile gate passes "-n 1000" to mcrun on a line that selects by name too,
    # while these lines select nothing and must not be reported.
    assert _micromamba_name_flag('"%MICROMAMBA_EXE%" -r "%R%" run -p "%P%" mcrun -c x.instr -n 1000') is None
    assert _micromamba_name_flag('"%MICROMAMBA_EXE%" run -n tavi python x.py') == "-n"
    assert _micromamba_name_flag('"%MICROMAMBA_EXE%" run --name tavi python x.py') == "--name"
    assert _micromamba_name_flag('"%MICROMAMBA_EXE%" env remove -n tavi -y') == "-n"


# ===========================================================================
# 2. :validate_base is byte-identical across its copies, and every file
#    with goto/call targets has a matching label for each one.
# ===========================================================================

_LABEL_RE = re.compile(r"(?m)^\s*:([A-Za-z_][A-Za-z0-9_]*)\s*$")
_GOTO_RE = re.compile(r"goto\s+:?([A-Za-z_][A-Za-z0-9_]*)")
_CALL_RE = re.compile(r"call\s+:([A-Za-z_][A-Za-z0-9_]*)")


def _labels_and_targets(text):
    # TAVI-Repair-Launchers.bat writes whole launcher scripts a line at a
    # time via "> "%TARGET%" echo ...", and the 1.4 installer its heartbeat
    # script via ">> "%HB_SCRIPT%" echo ..."; those lines are text destined for
    # a DIFFERENT file's control flow (e.g. "echo goto run"), not a real goto
    # in this one, and would otherwise look like a dangling target here.
    real_flow = "\n".join(
        line for line in text.splitlines()
        if not re.match(r'^\s*>>?\s*"%(TARGET|HB_SCRIPT)%"', line)
    )
    labels = {m.group(1).lower() for m in _LABEL_RE.finditer(text)}
    labels.add("eof")  # built in
    targets = {m.group(1).lower() for m in _GOTO_RE.finditer(real_flow)}
    targets |= {m.group(1).lower() for m in _CALL_RE.finditer(real_flow)}
    return labels, targets


@pytest.mark.parametrize("path", LABEL_FILES + [DOCTOR, RECORD_TAVI])
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


def test_validate_base_is_byte_identical_across_its_copies():
    reference_path = VALIDATE_BASE_COPIES[0]
    reference = _validate_base_body(reference_path)
    for path in VALIDATE_BASE_COPIES[1:]:
        other = _validate_base_body(path)
        if other != reference:
            diff = "\n".join(difflib.unified_diff(
                reference.splitlines(), other.splitlines(),
                fromfile=reference_path, tofile=path, lineterm=""))
            pytest.fail(f":validate_base differs between {reference_path} and {path}:\n{diff}")


# Each value grammar is a "set NAME| findstr /r /x" line copied into every file
# that reads the value; the variable name differs per copy, the patterns after
# "NAME=" must not.
GRAMMAR_COPIES = {
    "TAVI_VERSION": [(UPDATE_TAVI, "TAVI_VERSION"), (REPAIR_LAUNCHERS, "TAVI_VERSION"),
                     (TAVI_LAUNCHER, "TAVI_VERSION")],
    "INSTALL_ID": [(INSTALL_1_3_2, "RI_MARK"), (INSTALL_1_3_2, "RI_INFO"),
                   (INSTALL_1_4_0, "RI_MARK"), (INSTALL_1_4_0, "RI_INFO"),
                   (UNINSTALL_TAVI, "MARK_ID"), (UNINSTALL_TAVI, "INFO_ID"),
                   (DOCTOR, "MARK_ID"), (DOCTOR, "INFO_ID"),
                   (RECORD_TAVI, "MARK_ID"), (RECORD_TAVI, "INFO_ID")],
}


def _findstr_grammar(path, name):
    """The /c: patterns of the one "set NAME| findstr /r /x" line, less "NAME="."""
    lines = re.findall(rf"(?m)^set {name}\| findstr /r /x (.*) >nul\r?$", _read(path))
    assert len(lines) == 1, f"{path}: expected one findstr grammar line for {name}, found {len(lines)}"
    patterns = re.findall(r'/c:"([^"]*)"', lines[0])
    assert patterns and all(p.startswith(f"{name}=") for p in patterns), f"{path}: {lines[0]}"
    return [p[len(name) + 1:] for p in patterns]


@pytest.mark.parametrize("grammar", sorted(GRAMMAR_COPIES))
def test_value_grammar_is_identical_across_its_copies(grammar):
    copies = GRAMMAR_COPIES[grammar]
    ref_path, ref_name = copies[0]
    reference = _findstr_grammar(ref_path, ref_name)
    for path, name in copies[1:]:
        assert _findstr_grammar(path, name) == reference, (
            f"{grammar} grammar differs: {path} ({name}) vs {ref_path} ({ref_name})")


# ===========================================================================
# 3. Path validation, table-driven, through the real /validate-only switch.
# ===========================================================================

VALIDATE_ONLY_FILES = [INSTALL_1_3_2, INSTALL_1_4_0, UNINSTALL_TAVI]

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
    # A double quote was the gap the PR review found: it ends the quoted region
    # of whatever line expands the value, so the rest becomes command text. It
    # is also what Explorer's "Copy as path" puts around a pasted path.
    ('C:\\TAVI"', "double quote"),
    ('"C:\\TAVI"', "path pasted with surrounding quotes"),
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
        [INSTALL_1_3_2, "/validate-only", "C:\\TAVI&rem"],
        capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
    )
    correct = run_validate_only(INSTALL_1_3_2, "C:\\TAVI&rem")
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
            // Optional: print numbered lines and exit with a given code, so a
            // launcher's log and its failure screen can be checked.
            string lines = Environment.GetEnvironmentVariable("MICROMAMBA_STUB_LINES");
            if (lines != null)
            {
                Console.WriteLine("PYTHONUNBUFFERED=" + Environment.GetEnvironmentVariable("PYTHONUNBUFFERED"));
                for (int i = 1; i <= int.Parse(lines); i++)
                {
                    Console.WriteLine("stub line " + i);
                }
            }
            string code = Environment.GetEnvironmentVariable("MICROMAMBA_STUB_EXIT");
            return code == null ? 0 : int.Parse(code);
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
        "TAVI_VERSION=v1.3.2\nLAYOUT=2\nINSTALL_ID=1-2-3-4\n", encoding="utf-8", newline="\n")

    for launcher in ("run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat",
                     "collect-diagnostics.bat"):
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

    # [4] Open TAVI shell, then [7] Exit.
    result = run_bat(str(base / "TAVI-Launcher.bat"), env=_stub_env(log, wrong_root),
                      timeout=30, input_text="47")
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
    result = run_bat(str(base / "run-tavi.bat"), timeout=30, input_text="C")
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout
    assert "Press C to continue." in result.stdout, "the incomplete-install message must end on C"


def test_update_tavi_fails_visibly_when_python_is_missing(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base5", micromamba_stub_exe, with_python=False)
    result = run_bat(str(base / "update-tavi.bat"), timeout=30)
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout


def test_launcher_shell_option_fails_visibly_when_python_is_missing(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base6", micromamba_stub_exe, with_python=False)
    # [4] Open TAVI shell -> "[ERROR]" + "Press C" (consumes the C) ->
    # back to the menu -> [7] Exit. The menu recovers by design (it loops
    # back rather than terminating the process), so unlike run-tavi.bat and
    # update-tavi.bat above there is no non-zero exit to assert here -- only
    # that the failure was reported before the menu let the user continue.
    result = run_bat(str(base / "TAVI-Launcher.bat"), timeout=30, input_text="4C7")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[ERROR]" in result.stdout


# ===========================================================================
# 5. The menu dispatches on exact ERRORLEVEL comparisons, never a descending
#    ladder; diagnostics is 5, Uninstall 6, Exit 7 (1.4 moved Exit last).
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
    start = text.index("choice /C 1234567 ")
    end = text.index("goto menu", start)
    dispatch_block = text[start:end]
    offenders = [l for l in dispatch_block.splitlines() if re.match(r"^\s*if\s+errorlevel\b", l, re.I)]
    assert not offenders, f"menu dispatch uses an errorlevel ladder: {offenders}"


def test_diagnostics_is_five_uninstall_six_and_exit_seven():
    text = _read(TAVI_LAUNCHER)
    assert 'if "%PICK%"=="5" goto diagnostics' in text
    assert 'if "%PICK%"=="6" goto uninstall' in text
    assert 'if "%PICK%"=="7" goto quit' in text
    item = re.search(r"(?m)^echo   \[5\] (.*)$", text).group(1)
    assert item.startswith("Collect diagnostics for support")
    assert "Doctor" in item and "few minutes" in item, item
    assert "[6] Uninstall TAVI" in text
    assert "[7] Exit" in text


def test_menu_exits_cleanly_on_seven():
    result = run_bat(TAVI_LAUNCHER, timeout=20, input_text="7")
    assert result.returncode == 0, result.stdout + result.stderr


def _launch_env(tmp_path, **extra):
    """os.environ with LOCALAPPDATA and TEMP in tmp_path, plus extra."""
    env = dict(os.environ)  # Windows: os.environ keys are upper case
    for name in ("LOCALAPPDATA", "TEMP", "TMP"):
        folder = tmp_path / f"{name.lower()}-sandbox"
        folder.mkdir(exist_ok=True)
        env[name] = str(folder)
    env.update(extra)
    return env


def _logs_dir(env):
    return os.path.join(env["LOCALAPPDATA"], "TAVI", "logs")


def test_menu_one_runs_tavi_with_no_arguments(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    stub_log = tmp_path / "stub.log"
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LOG=str(stub_log))
    result = run_bat(str(base / "TAVI-Launcher.bat"), env=env, timeout=30, input_text="17")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _read_stub_log(stub_log)
    assert calls and calls[0][-1] == "TAVI_PySide6.py", calls


def test_menu_five_runs_the_diagnostics_collector_attended(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    # A stand-in: the real collector, run attended, opens Explorer.
    (base / "collect-diagnostics.bat").write_text(
        '@echo off\n> "%~dp0collector-ran.txt" echo args=[%*]\n', encoding="utf-8", newline="\r\n")
    result = run_bat(str(base / "TAVI-Launcher.bat"), env=_launch_env(tmp_path),
                     timeout=30, input_text="57")
    assert result.returncode == 0, result.stdout + result.stderr
    ran = base / "collector-ran.txt"
    assert ran.exists(), "menu item 5 did not run collect-diagnostics.bat"
    # No /quiet: the student gets Explorer and the wait on C.
    assert ran.read_text(encoding="utf-8").strip() == "args=[]"


# ===========================================================================
# 5a. run-tavi.bat's launch log (1.4): TAVI's whole output goes to
#     %LOCALAPPDATA%\TAVI\logs\launch-<stamp>.log, ten are kept, an error shows
#     the last 30 lines and waits on C, and with no log TAVI runs live.
# ===========================================================================

def test_run_tavi_writes_a_launch_log_and_passes_arguments_through(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    stub_log = tmp_path / "stub.log"
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LOG=str(stub_log), MICROMAMBA_STUB_LINES="3")
    result = run_bat(str(base / "run-tavi.bat"), "--self-test", env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

    argv = _read_stub_log(stub_log)[0]
    assert argv[-2:] == ["TAVI_PySide6.py", "--self-test"], argv

    logs = os.listdir(_logs_dir(env))
    assert len(logs) == 1 and re.fullmatch(r"launch-\d{8}-\d{6}\.log", logs[0]), logs
    log_path = os.path.join(_logs_dir(env), logs[0])
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    assert "PYTHONUNBUFFERED=1" in text and "stub line 3" in text, text
    assert "[TAVI] Exit code: 0" in text, text
    # The window says only that TAVI runs and where its messages go.
    assert "stub line" not in result.stdout, result.stdout
    assert log_path in result.stdout, result.stdout


def test_run_tavi_keeps_the_ten_newest_launch_logs(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    env = _launch_env(tmp_path)
    logs = _logs_dir(env)
    os.makedirs(logs)
    old = [f"launch-20200101-0000{i:02d}.log" for i in range(12)]
    now = time.time()
    for age, name in zip(range(12, 0, -1), old):
        path = os.path.join(logs, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("old\n")
        os.utime(path, (now - 3600 * age, now - 3600 * age))

    result = run_bat(str(base / "run-tavi.bat"), env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    remaining = set(os.listdir(logs))
    new = remaining - set(old)
    assert len(new) == 1, remaining
    assert remaining == set(old[-9:]) | new, sorted(remaining)


def test_run_tavi_shows_the_last_30_lines_and_waits_on_c_after_an_error(tmp_path,
                                                                         micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LINES="50", MICROMAMBA_STUB_EXIT="3")
    result = run_bat(str(base / "run-tavi.bat"), env=env, timeout=30, input_text="C")
    assert result.returncode == 1, result.stdout + result.stderr
    out = result.stdout
    assert "TAVI STOPPED WITH AN ERROR" in out, out
    # The log ends "stub line 50", a blank line, "[TAVI] Exit code: 3": its
    # last 30 lines start at stub line 23.
    assert re.search(r"(?m)^stub line 23\r?$", out), out
    assert re.search(r"(?m)^stub line 50\r?$", out), out
    assert not re.search(r"(?m)^stub line 22\r?$", out), out
    assert "[TAVI] Exit code: 3" in out, out
    assert "Press C to continue." in out, out
    assert "Press any key" not in out, out


def test_run_tavi_runs_live_when_no_log_can_be_opened(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    blocker = tmp_path / "a-file-not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LINES="2")
    for name in ("LOCALAPPDATA", "TEMP", "TMP"):
        env[name] = str(blocker)
    result = run_bat(str(base / "run-tavi.bat"), env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "could not be saved to a log file" in result.stdout, result.stdout
    assert "stub line 2" in result.stdout, result.stdout


# ===========================================================================
# 5b. collect-diagnostics.bat (1.4): one zip in the logs folder, made before
#     the Doctor runs and rewritten with its report; /quiet never waits and
#     never opens Explorer. The Doctor runs for real against the stub
#     micromamba and stops at its first simulation, which has no McStas here.
# ===========================================================================

def _diagnostics_base(tmp_path, stub_exe, with_app=True):
    base, _, _ = _make_layout2_base(tmp_path, "inst", stub_exe)
    if with_app:
        (base / "app" / "installer").mkdir()
        shutil.copy2(DOCTOR, base / "app" / "installer" / "TAVI-Doctor.bat")
        (base / "app" / "output").mkdir()
        (base / "app" / "output" / "tavi-crash.log").write_text(
            "Traceback: the crash\n", encoding="utf-8", newline="\n")
    else:
        shutil.rmtree(base / "app")
    (base / "compile_check").mkdir()
    (base / "compile_check" / "serial.log").write_text("serial ok\n", encoding="utf-8", newline="\n")
    (base / "install-status.txt").write_text("OUTCOME=failed\n", encoding="utf-8", newline="\n")
    return base


def _diagnostics_env(tmp_path):
    env = _launch_env(tmp_path)
    logs = _logs_dir(env)
    os.makedirs(logs)
    with open(os.path.join(logs, "install-20261016-101500.log"), "w", encoding="utf-8") as fh:
        fh.write("[Step 1/8] the install log\n")
    # The %TEMP% fallback: a stamp-shaped log is TAVI's, anything else is not.
    with open(os.path.join(env["TEMP"], "install-20261016-091500.log"), "w", encoding="utf-8") as fh:
        fh.write("fallback\n")
    with open(os.path.join(env["TEMP"], "install-other.log"), "w", encoding="utf-8") as fh:
        fh.write("another program's log\n")
    # The fallback when PowerShell gives no clock: TAVI's own shape, taken.
    with open(os.path.join(env["TEMP"], "install-tavi-rnd-12345-6789.log"), "w", encoding="utf-8") as fh:
        fh.write("fallback, no clock\n")
    # A bare %RANDOM% name is not TAVI's shape, so it is left alone.
    with open(os.path.join(env["TEMP"], "install-12345-6789.log"), "w", encoding="utf-8") as fh:
        fh.write("another program's log\n")
    return env


def _the_zip(env):
    logs = _logs_dir(env)
    zips = [name for name in os.listdir(logs) if name.endswith(".zip")]
    assert len(zips) == 1 and re.fullmatch(r"TAVI-diagnostics-\d{8}-\d{6}\.zip", zips[0]), zips
    leftovers = [name for name in os.listdir(logs) if os.path.isdir(os.path.join(logs, name))]
    assert not leftovers, f"the collecting folder must be removed once zipped: {leftovers}"
    return os.path.join(logs, zips[0])


def test_collect_diagnostics_quiet_zips_the_logs_and_the_doctor_report(tmp_path,
                                                                       micromamba_stub_exe):
    base = _diagnostics_base(tmp_path, micromamba_stub_exe)
    env = _diagnostics_env(tmp_path)
    result = run_bat(str(base / "collect-diagnostics.bat"), "/quiet", env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr

    path = _the_zip(env)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        by_tail = {name.split("/", 1)[-1]: name for name in names}
        assert "install-20261016-101500.log" in by_tail, names
        assert archive.read(by_tail["tavi-crash.log"]).decode() == "Traceback: the crash\n"
        for expected in ("INSTALL_INFO.txt", "install-status.txt", "compile_check-serial.log",
                         "TAVI-doctor-report.txt", "TAVI-doctor-summary.txt", "collected.txt",
                         "temp-fallback/install-20261016-091500.log",
                         "temp-fallback/install-tavi-rnd-12345-6789.log"):
            assert expected in by_tail, (expected, names)
        assert not any(name.endswith(("install-other.log", "install-12345-6789.log"))
                       for name in names), names
        assert b"missing: compile check log, MPI" in archive.read(by_tail["collected.txt"])
    assert "DIAGNOSTICS SAVED" in result.stdout, result.stdout
    assert path in result.stdout, result.stdout
    assert "Press C" not in result.stdout, "/quiet must not wait"


def test_collect_diagnostics_works_without_the_program_folder(tmp_path, micromamba_stub_exe):
    base = _diagnostics_base(tmp_path, micromamba_stub_exe, with_app=False)
    env = _diagnostics_env(tmp_path)
    result = run_bat(str(base / "collect-diagnostics.bat"), "/quiet", env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "The TAVI Doctor was not found" in result.stdout, result.stdout
    with zipfile.ZipFile(_the_zip(env)) as archive:
        by_tail = {name.split("/", 1)[-1]: name for name in archive.namelist()}
        assert "install-20261016-101500.log" in by_tail, by_tail
        collected = archive.read(by_tail["collected.txt"]).decode()
    assert "missing: crash log" in collected, collected
    assert "missing: TAVI Doctor report" in collected, collected


def test_collect_diagnostics_run_from_the_checkout_finds_the_base(tmp_path, micromamba_stub_exe):
    """The installer's D runs the checkout's copy when an install died before
    the launchers were copied into the base folder."""
    base = _diagnostics_base(tmp_path, micromamba_stub_exe)
    launchers = base / "app" / "installer" / "launchers"
    launchers.mkdir()
    shutil.copy2(COLLECT_DIAG, launchers / "collect-diagnostics.bat")
    env = _diagnostics_env(tmp_path)
    result = run_bat(str(launchers / "collect-diagnostics.bat"), "/quiet", env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"TAVI installation: {base}" in result.stdout, result.stdout
    with zipfile.ZipFile(_the_zip(env)) as archive:
        tails = {name.split("/", 1)[-1] for name in archive.namelist()}
    assert {"tavi-crash.log", "INSTALL_INFO.txt", "TAVI-doctor-report.txt"} <= tails, tails


def test_collect_diagnostics_leaves_a_folder_when_tar_is_missing(tmp_path, micromamba_stub_exe):
    base = _diagnostics_base(tmp_path, micromamba_stub_exe, with_app=False)
    env = _diagnostics_env(tmp_path)
    # tar.exe is looked up under %SystemRoot%\System32; point that elsewhere.
    env["SYSTEMROOT"] = str(tmp_path / "no-windows-here")
    result = run_bat(str(base / "collect-diagnostics.bat"), "/quiet", env=env, timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "tar.exe is not on this computer" in result.stdout, result.stdout
    logs = _logs_dir(env)
    folders = [name for name in os.listdir(logs) if os.path.isdir(os.path.join(logs, name))]
    assert len(folders) == 1, os.listdir(logs)
    assert os.path.exists(os.path.join(logs, folders[0], "install-20261016-101500.log"))
    assert not [name for name in os.listdir(logs) if name.endswith(".zip")]


# ===========================================================================
# 5c. The Doctor's /base: the installation that started it, vetted by
#     :validate_base_var before any line expands it.
# ===========================================================================

def _doctor_resolve(env, *args):
    result = run_bat(DOCTOR, *args, "/resolve-only", env=env, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    found = dict(line.split("=", 1) for line in result.stdout.splitlines()
                 if line.startswith(("LAYOUT=", "TAVI_BASE=")))
    return result, found


def test_doctor_base_wins_over_the_install_record(tmp_path):
    recorded = _marked_base(tmp_path)
    mine = tmp_path / "mine"
    mine.mkdir()
    env = _sandbox_env(tmp_path, record_value=str(recorded))
    _, found = _doctor_resolve(env, "/base", str(mine))
    assert found == {"LAYOUT": "2", "TAVI_BASE": str(mine)}


def test_doctor_base_that_does_not_check_out_falls_back(tmp_path):
    spaced = tmp_path / "with space"
    spaced.mkdir()
    env = _sandbox_env(tmp_path)
    result, found = _doctor_resolve(env, "/quiet", "/base", str(spaced))
    assert found == {"LAYOUT": "1", "TAVI_BASE": env["USERPROFILE"]}, result.stdout
    assert "[INFO]" in result.stdout
    assert str(spaced) not in result.stdout, "the refused value was printed"


def test_doctor_does_not_expand_a_hostile_base(tmp_path):
    marker = tmp_path / "marker.txt"
    env = _sandbox_env(tmp_path)
    result, found = _doctor_resolve(env, "/base", f"C:\\x&type nul> {marker}")
    assert not marker.exists(), ("a line expanded the /base value", result.stdout)
    assert found.get("LAYOUT") == "1", result.stdout


# ===========================================================================
# 5d. No v1.4 outcome file ends on, or contains, a bare `pause`: attended
#     runs close on `choice /c C`, quiet ones never wait. The Doctor keeps its
#     standalone pauses (collect-diagnostics.bat runs it with /quiet) and the
#     legacy TAVI-Repair-Launchers.bat keeps generating v1.3 launchers.
# ===========================================================================

NO_PAUSE_FILES = [INSTALL_1_4_0, TAVI_LAUNCHER, COLLECT_DIAG, RUN_TAVI, UPDATE_TAVI,
                  UNINSTALL_TAVI, UNINSTALL_STANDALONE]


def _pause_commands(path):
    return [
        f"{number}: {line.strip()}"
        for number, line in enumerate(_read(path).splitlines(), 1)
        if not re.match(r"^\s*(::|rem\b|@?echo\b|>>?\s*\"[^\"]*\"\s+echo\b)", line, re.I)
        and re.search(r"(?i)\bpause\b", line)
    ]


@pytest.mark.parametrize("script", NO_PAUSE_FILES, ids=os.path.basename)
def test_no_pause_in_a_v14_outcome_file(script):
    offenders = _pause_commands(script)
    assert not offenders, f"{os.path.basename(script)} still pauses: {offenders}"


# ===========================================================================
# 6. Destructive uninstall path, sandboxed under tmp_path.
#
# uninstall-tavi.bat hands over to a copy of itself in %TEMP%, in the same
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

def _install_id_files(base, install_id="1-2-3-4", info_id=None, layout="2"):
    # The installer writes INSTALL_ID as four %RANDOM% numbers joined by dashes.
    (base / ".tavi-install-root").write_text(
        f"LAYOUT=2\nINSTALL_ID={install_id}\n", encoding="utf-8", newline="\n")
    (base / "INSTALL_INFO.txt").write_text(
        f"TAVI_VERSION=v1.3.2\nLAYOUT={layout}\nINSTALL_ID={info_id or install_id}\n",
        encoding="utf-8", newline="\n")


def _uninstallable_base(tmp_path, name, install_id="1-2-3-4", info_id=None, extra_file=None,
                        layout="2"):
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
    for launcher in ("run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat", "uninstall-tavi.bat",
                     "collect-diagnostics.bat"):
        shutil.copy2(os.path.join(LAUNCHERS_DIR, launcher), base / launcher)
    _install_id_files(base, install_id=install_id, info_id=info_id, layout=layout)
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
    assert "UNINSTALL FAILED" in result.stdout and "Nothing was removed." in result.stdout
    assert (base / "app").exists(), "an unmarked folder must be left untouched"


def test_uninstall_refuses_on_install_id_mismatch(tmp_path):
    base = _uninstallable_base(tmp_path, "mismatch", install_id="1-2-3-4", info_id="5-6-7-8")
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
                  "run-tavi.bat", "update-tavi.bat", "TAVI-Launcher.bat", "uninstall-tavi.bat",
                  "collect-diagnostics.bat"):
        assert not (base / child).exists(), f"{child} should have been removed"
    assert not base.exists(), "a clean install's base folder must be removed entirely"
    assert "TAVI WAS UNINSTALLED" in result.stdout, result.stdout
    assert "Press C" not in result.stdout, "/y must never wait"


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


# ===========================================================================
# 6a. Uninstall (1.4): its own log in %LOCALAPPDATA%\TAVI\logs, a folder that
#     outlives the installation; a headline; C to close unless /y; and the
#     desktop copy of the shortcut removed only when it opens this
#     installation. "The desktop" here is TAVI_TEST_DESKTOP, a temp folder
#     set by the autouse fixture, never the real one.
# ===========================================================================

def _make_shortcut(lnk, target):
    """A real .lnk written by WScript.Shell, in a PowerShell child that
    conftest.py starts with no window. The target need not exist."""
    env = dict(os.environ, TAVI_LNK=str(lnk), TAVI_LNK_TARGET=str(target))
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TAVI_LNK); "
              "$s.TargetPath=$env:TAVI_LNK_TARGET; $s.Save()")
    made = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          env=env, capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL)
    assert made.returncode == 0 and os.path.exists(lnk), made.stdout + made.stderr


def _desktop_shortcut():
    return os.path.join(os.environ["TAVI_TEST_DESKTOP"], "TAVI Launcher.lnk")


def _new_logs(kind, env=None):
    logs = os.path.join((env or os.environ)["LOCALAPPDATA"], "TAVI", "logs")
    return [os.path.join(logs, name) for name in os.listdir(logs)
            if re.fullmatch(rf"{kind}-\d{{8}}-\d{{6}}\.log", name)]


def _text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def test_uninstall_writes_its_log_and_keeps_the_logs_folder(tmp_path):
    base = _uninstallable_base(tmp_path, "logged")
    tavi_dir = os.path.join(os.environ["LOCALAPPDATA"], "TAVI")
    os.makedirs(os.path.join(tavi_dir, "logs"))
    earlier = os.path.join(tavi_dir, "logs", "install-20261016-101500.log")
    with open(earlier, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("the install\n")
    # The record names this installation, so it goes, and with it the attempt
    # to remove %LOCALAPPDATA%\TAVI - which the logs folder must stop.
    record = os.path.join(tavi_dir, "install-record.txt")
    with open(record, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(f"TAVI_BASE={base}\nSTATE=complete\n")

    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    assert not os.path.exists(record), result.stdout
    assert os.path.exists(earlier), "the uninstaller removed an earlier log"
    logs = _new_logs("uninstall")
    assert len(logs) == 1, os.listdir(os.path.join(tavi_dir, "logs"))
    text = _text(logs[0])
    assert f"Installation: {base}" in text and "[TAVI] TAVI WAS UNINSTALLED" in text, text
    assert logs[0] in result.stdout, result.stdout


@pytest.mark.parametrize("answer,headline", [("Y", "TAVI WAS UNINSTALLED"),
                                             ("N", "UNINSTALL CANCELLED")])
def test_uninstall_asked_in_person_ends_on_its_headline_and_c(tmp_path, answer, headline):
    base = _uninstallable_base(tmp_path, "asked")
    result = run_bat(UNINSTALL_TAVI, str(base), timeout=60, input_text=f"{answer}C")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert headline in out and "Press C to close this window." in out, out
    assert out.rindex("Press C") > out.rindex(headline), "C is asked for after the headline"
    assert "Press any key" not in out, out
    assert base.exists() == (answer == "N"), out


CLOSE_PROMPT_ANSWERED = "Press C to close this window. C"  # the prompt, then choice's echo of the key


def test_uninstall_confirmed_skips_its_question_but_waits_for_c(tmp_path):
    """/confirmed is the launcher menu's switch: the menu has asked already, so
    no second question, but the run is attended and ends on the headline and C."""
    base = _uninstallable_base(tmp_path, "confirmed")
    result = run_bat(UNINSTALL_TAVI, str(base), "/confirmed", timeout=60, input_text="C")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert not base.exists(), out
    assert "Remove TAVI? (Y/N)" not in out, "/confirmed must not ask again"
    assert CLOSE_PROMPT_ANSWERED in out, out
    assert out.rindex("Press C") > out.rindex("TAVI WAS UNINSTALLED"), "C comes after the headline"


def test_uninstall_y_never_waits_even_when_it_is_fed_a_c(tmp_path):
    base = _uninstallable_base(tmp_path, "unattended")
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=60, input_text="C")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Press C" not in result.stdout and "Remove TAVI? (Y/N)" not in result.stdout, result.stdout


def test_the_menu_hands_the_uninstaller_confirmed_not_y():
    text = _read(TAVI_LAUNCHER)
    assert 'call "%UNINST_COPY%" "%TAVI_BASE%" /confirmed' in text
    assert "/y" not in text.replace("copy /Y", ""), "the attended menu must not pass the unattended switch"


def test_the_menu_uninstall_asks_once_and_then_waits_for_c(tmp_path):
    """Menu 6, Y at the menu's own question, and then the uninstaller: no
    second question, the headline, and C to close."""
    base = _uninstallable_base(tmp_path, "menu-uninstall")
    result = run_bat(str(base / "TAVI-Launcher.bat"), env=_launch_env(tmp_path), timeout=60,
                     input_text="6YC")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert not base.exists(), out
    assert "Remove TAVI and everything listed above? (Y/N):" in out, out
    assert "Remove TAVI? (Y/N)" not in out, "the uninstaller asked a second time"
    assert CLOSE_PROMPT_ANSWERED in out, out
    assert out.rindex("Press C") > out.rindex("TAVI WAS UNINSTALLED"), "C comes after the headline"


@pytest.mark.parametrize("whose", ["this installation", "another installation"])
def test_uninstall_removes_only_its_own_desktop_shortcut(tmp_path, whose):
    base = _uninstallable_base(tmp_path, "mine")
    if whose == "this installation":
        target = base / "TAVI-Launcher.bat"
    else:
        target = tmp_path / "mine2" / "TAVI-Launcher.bat"
    lnk = _desktop_shortcut()
    _make_shortcut(lnk, target)

    result = run_bat(UNINSTALL_TAVI, str(base), "/y", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    if whose == "this installation":
        assert not os.path.exists(lnk), result.stdout
        assert f"Removed the TAVI Launcher shortcut from the desktop: {lnk}" in result.stdout
    else:
        assert os.path.exists(lnk), "another installation's shortcut was removed"
        assert f"Left the shortcut {lnk} in place" in result.stdout, result.stdout
    assert lnk in _text(_new_logs("uninstall")[0]), "the desktop step is not in the log"


def test_uninstall_without_powershell_leaves_the_desktop_alone(tmp_path):
    """No PowerShell (missing, or locked down by a managed laptop): the desktop
    step is one line, nothing there changes, and the uninstall still ends
    well, with a log named from %RANDOM% instead of the clock."""
    base = _uninstallable_base(tmp_path, "nops")
    lnk = _desktop_shortcut()
    _make_shortcut(lnk, base / "TAVI-Launcher.bat")
    env = dict(os.environ)
    # System32 alone has no PowerShell; the choice stand-in's folder is only there
    # so that anything that did ask would be heard by the suite.
    env["PATH"] = os.pathsep.join(filter(None, [os.environ.get("TAVI_CHOICE_SENSOR_DIR"),
                                                os.path.join(os.environ["SYSTEMROOT"], "System32")]))
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    assert os.path.exists(lnk), result.stdout
    assert "The desktop could not be checked" in result.stdout, result.stdout
    assert "TAVI WAS UNINSTALLED" in result.stdout, result.stdout
    logs = os.listdir(os.path.join(env["LOCALAPPDATA"], "TAVI", "logs"))
    assert len(logs) == 1 and re.fullmatch(r"uninstall-tavi-rnd-\d+-\d+\.log", logs[0]), logs


@pytest.mark.parametrize("whose", ["this installation", "another installation"])
def test_a_legacy_removal_removes_only_its_own_desktop_shortcut(tmp_path, whose):
    """Installers before 1.3.2 wrote %USERPROFILE%\\Desktop\\TAVI Launcher.lnk
    with <base>\\TAVI-Launcher.bat as its target."""
    base = _legacy_base(tmp_path)
    env = _sandbox_env(tmp_path)
    legacy_desktop = tmp_path / "userprofile" / "Desktop"
    legacy_desktop.mkdir()
    lnk = legacy_desktop / "TAVI Launcher.lnk"
    target = base / "TAVI-Launcher.bat" if whose == "this installation" else (
        tmp_path / "elsewhere" / "TAVI-Launcher.bat")
    _make_shortcut(lnk, target)

    result = run_bat(UNINSTALL_STANDALONE, str(base), env=env, timeout=60, input_text="YC")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    assert lnk.exists() == (whose == "another installation"), result.stdout
    assert "TAVI WAS UNINSTALLED" in result.stdout, result.stdout
    assert "Press C to close this window." in result.stdout, result.stdout
    logs = _new_logs("uninstall", env)
    assert len(logs) == 1 and "[TAVI] TAVI WAS UNINSTALLED" in _text(logs[0]), logs


def _desktop_routine(path):
    text = _read(path)
    start = re.search(r"(?m)^:remove_desktop_shortcut\r?$", text).start()
    end = text.index("goto :eof", text.index("PowerShell did not answer", start))
    return text[start:end]


def test_the_desktop_routine_is_identical_in_both_uninstallers_and_the_installer():
    assert _desktop_routine(UNINSTALL_TAVI) == _desktop_routine(UNINSTALL_STANDALONE)
    assert _desktop_routine(UNINSTALL_TAVI) == _desktop_routine(INSTALL_1_4_0)


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

    The 1.4 installer has the two forms that open no console: `start "" /b`,
    which runs its heartbeat in the console already open, and `start ""
    "%NOTEPAD%"`, a window program (Notepad on the install log, attended
    failures only), which a batch file would otherwise wait for.
    """
    with open(script, encoding="utf-8", errors="replace", newline="") as stream:
        offenders = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(stream, 1)
            if re.match(r"^\s*start\s", line)
            and not re.match(r'^\s*start ""\s+(/b\s|"%NOTEPAD%"\s)', line)
        ]
    assert not offenders, (
        f"{os.path.basename(script)} opens a console window: {offenders}"
    )


@pytest.mark.parametrize("script", LABEL_FILES)
def test_no_bare_exit_line(script):
    """A bare `exit` keeps the last command's errorlevel, often 0.

    The fall-through `exit` after a hand-off is reached only when the hand-off
    failed to end the process, so it must say so: `exit 1`.
    """
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(_read(script).splitlines(), 1)
        if not re.match(r"^\s*(::|rem\b)", line, re.I) and re.match(r"^\s*exit\s*$", line, re.I)
    ]
    assert not offenders, f"{os.path.basename(script)} has a bare exit: {offenders}"


@pytest.mark.parametrize("script", LABEL_FILES)
def test_no_redirection_follows_a_value_on_an_echo_line(script):
    """`echo NAME=%VALUE%> "file"` eats a value that ends in a digit.

    cmd reads the digit immediately before a redirection operator as the
    stream number, so `echo LAYOUT=2>> "file"` appends *stderr* and writes
    `LAYOUT=` to the console instead. Measured on the first cold install of
    v1.3.2: INSTALL_INFO.txt and the ownership marker came out with no LAYOUT
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


@pytest.mark.parametrize("installer", [INSTALL_1_3_2, INSTALL_1_4_0], ids=os.path.basename)
def test_the_installer_writes_a_layout_line_the_uninstaller_can_read(installer):
    """The ownership gate is keyed on LAYOUT, so it has to reach the file."""
    # newline="" keeps the CRLF that .gitattributes pins for *.bat, so the
    # end-of-line anchor has to allow the \r before it.
    with open(installer, encoding="utf-8", newline="") as stream:
        text = stream.read()
    assert re.search(r'(?m)^>>? "%TAVI_BASE%\\INSTALL_INFO\.txt" echo LAYOUT=%LAYOUT%\r?$', text), \
        "INSTALL_INFO.txt must get a LAYOUT line, written with the redirection first"
    assert re.search(r'(?m)^>>? "%MARKER%" echo LAYOUT=%LAYOUT%\r?$', text), \
        "the ownership marker must get a LAYOUT line, written with the redirection first"


# ===========================================================================
# 7. TAVI_VERSION from INSTALL_INFO.txt is a release tag or main before
#    update-tavi.bat or TAVI-Repair-Launchers.bat use it.
#
# INSTALL_INFO.txt is ordinary text on disk, and the value becomes a git
# argument and, in the repair, a line of a generated batch file. "&rem" and
# not "&calc", as in REFUSE_CASES: a regression must not open a window.
# ===========================================================================

GOOD_VERSIONS = ["v1.3.2", "main"]
BAD_VERSIONS = [
    ("v1.3.2&rem x", "ampersand"),
    ("--orphan", "git option"),
    ("v1.3", "two parts"),
    ("v1.3.2 x", "trailing word"),
    ('v1.3.2"&rem x', "double quote"),
    ("..\\x", "path"),
]


def _write_install_info(folder, version, **extra):
    # CRLF, as the installer's own "> file echo" lines write it.
    lines = [f"TAVI_VERSION={version}"] + [f"{key}={value}" for key, value in extra.items()]
    (folder / "INSTALL_INFO.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")


def _run_update_with_version(tmp_path, stub_exe, version):
    base, _, _ = _make_layout2_base(tmp_path, "base", stub_exe)
    _write_install_info(base, version, LAYOUT="2", INSTALL_ID="1-2-3-4")
    log = tmp_path / "stub.log"
    env = dict(os.environ)
    env["MICROMAMBA_STUB_LOG"] = str(log)
    result = run_bat(str(base / "update-tavi.bat"), env=env, timeout=30)
    return result, _read_stub_log(log)


@pytest.mark.parametrize("version", GOOD_VERSIONS)
def test_update_tavi_checks_out_a_well_formed_version(tmp_path, micromamba_stub_exe, version):
    result, calls = _run_update_with_version(tmp_path, micromamba_stub_exe, version)
    assert result.returncode == 0, result.stdout + result.stderr
    checkouts = [argv for argv in calls if "checkout" in argv]
    assert checkouts, f"update-tavi.bat never reached git checkout: {calls}"
    argv = checkouts[0]
    assert argv[argv.index("checkout") + 1] == version


def test_repair_succeeds_with_its_log_and_closes_on_c(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LINES="2")
    result = run_bat(str(base / "update-tavi.bat"), env=env, timeout=60, input_text="C")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "REPAIR SUCCEEDED" in out and "Press C to continue." in out, out
    assert "stub line" not in out, "the steps' output belongs in the log"
    logs = _new_logs("repair", env)
    assert len(logs) == 1 and logs[0] in out, (logs, out)
    text = _text(logs[0])
    assert text.count("stub line 2") == 3, text  # fetch, checkout, the load check
    assert "[TAVI] REPAIR SUCCEEDED" in text, text


def test_repair_failure_names_the_step_and_shows_the_last_30_lines(tmp_path, micromamba_stub_exe):
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    env = _launch_env(tmp_path, MICROMAMBA_STUB_LINES="50", MICROMAMBA_STUB_EXIT="3")
    result = run_bat(str(base / "update-tavi.bat"), env=env, timeout=60, input_text="C")
    assert result.returncode == 1, result.stdout + result.stderr
    out = result.stdout
    assert "REPAIR FAILED" in out, out
    assert "Failed step: Fetching the release from GitHub" in out, out
    # The fetch's output ends the log at "stub line 50": its last 30 lines
    # start at stub line 21.
    assert re.search(r"(?m)^stub line 21\r?$", out), out
    assert re.search(r"(?m)^stub line 50\r?$", out), out
    assert not re.search(r"(?m)^stub line 20\r?$", out), out
    assert out.rindex("REPAIR FAILED") > out.rindex("stub line 50"), "the headline comes last"
    logs = _new_logs("repair", env)
    assert len(logs) == 1 and logs[0] in out, (logs, out)
    assert "REPAIR FAILED at: Fetching the release from GitHub" in _text(logs[0])
    assert "Press C to continue." in out and "Press any key" not in out, out


@pytest.mark.parametrize("version,label", BAD_VERSIONS)
def test_update_tavi_refuses_a_malformed_version(tmp_path, micromamba_stub_exe, version, label):
    result, calls = _run_update_with_version(tmp_path, micromamba_stub_exe, version)
    assert result.returncode != 0, (label, result.stdout)
    assert "[ERROR]" in result.stdout, (label, result.stdout)
    assert version not in result.stdout, (label, "the refusal printed the raw value", result.stdout)
    assert not [argv for argv in calls if "checkout" in argv], (label, calls)


def _repair_target(tmp_path, version, **override):
    """A pre-1.3.2 program folder under tmp_path, with everything the repair
    checks for present. The repair is pointed at it by argument, so it never
    reads the real install record or touches the real profile. ``override``
    replaces an INSTALL_INFO.txt path field; None leaves it out."""
    prog = tmp_path / "prog"
    prog.mkdir()
    (prog / "TAVI_PySide6.py").write_text("# stub\n", encoding="utf-8", newline="\n")
    env_prefix = tmp_path / "env"
    (env_prefix / "share" / "mcstas" / "resources").mkdir(parents=True)
    (env_prefix / "python.exe").write_bytes(b"")
    micromamba_dir = tmp_path / "mm"
    micromamba_dir.mkdir()
    (micromamba_dir / "micromamba.exe").write_bytes(b"")
    fields = dict(ENV_PREFIX=env_prefix, MAMBA_ROOT_PREFIX=tmp_path / "root",
                  MICROMAMBA_DIR=micromamba_dir)
    fields.update(override)
    _write_install_info(prog, version,
                        **{key: value for key, value in fields.items() if value is not None})
    return prog


@pytest.mark.parametrize("version", GOOD_VERSIONS)
def test_repair_launchers_writes_a_well_formed_version(tmp_path, version):
    prog = _repair_target(tmp_path, version)
    # "Y" answers the repair's own confirmation prompt; the Enter is the key the
    # closing pause takes: pause accepts any key.
    result = run_bat(REPAIR_LAUNCHERS, str(prog), timeout=30, input_text="Y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'git checkout "{version}"' in _read(str(prog / "update-tavi.bat"))


@pytest.mark.parametrize("version,label", BAD_VERSIONS)
def test_repair_launchers_refuses_a_malformed_version(tmp_path, version, label):
    prog = _repair_target(tmp_path, version)
    result = run_bat(REPAIR_LAUNCHERS, str(prog), timeout=30, input_text="Y\n")
    assert result.returncode != 0, (label, result.stdout)
    assert "[ERROR]" in result.stdout, (label, result.stdout)
    assert version not in result.stdout, (label, "the refusal printed the raw value", result.stdout)
    # Refused before anything is written, so no launcher is half-repaired.
    for name in ("update-tavi.bat", "run-tavi.bat", "TAVI-Launcher.bat"):
        assert not (prog / name).exists(), (label, f"{name} was written")


@pytest.mark.parametrize("where", ["in the folder given", "in the base folder above app"])
def test_repair_launchers_refuses_a_v14_installation(tmp_path, where):
    """A 1.4 installation has collect-diagnostics.bat beside its launchers;
    rewriting them would put the 1.3 menu back."""
    prog = _repair_target(tmp_path, "v1.3.2")
    holder = prog if where == "in the folder given" else prog.parent
    (holder / "collect-diagnostics.bat").write_text("@echo off\n", encoding="utf-8", newline="\r\n")
    result = run_bat(REPAIR_LAUNCHERS, str(prog), timeout=30, input_text="\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert ("[ERROR] This installation is newer than this repair tool; "
            "use Repair TAVI in its launcher menu.") in result.stdout, result.stdout
    for name in ("update-tavi.bat", "run-tavi.bat", "TAVI-Launcher.bat"):
        assert not (prog / name).exists(), f"{name} was written"


# The launcher menu prints the same value in its banner. A refused value is
# shown as "unknown" and the menu keeps working. Each hostile value would
# create a marker file if its banner line ran it; the second gets there past a
# pair of double quotes.
HOSTILE_BANNER_VERSIONS = [
    ('v1.3.2&type nul> "{marker}"', "ampersand"),
    ('v1.3.2""&type nul> "{marker}"', "double quote"),
]


def _run_launcher_with_version(tmp_path, stub_exe, version):
    base, _, _ = _make_layout2_base(tmp_path, "base", stub_exe)
    _write_install_info(base, version, LAYOUT="2", INSTALL_ID="1-2-3-4")
    # [7] Exit, so the menu never waits on its prompt.
    return run_bat(str(base / "TAVI-Launcher.bat"), timeout=20, input_text="7")


def test_launcher_banner_shows_a_well_formed_version(tmp_path, micromamba_stub_exe):
    result = _run_launcher_with_version(tmp_path, micromamba_stub_exe, "v1.3.2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Release: v1.3.2" in result.stdout, result.stdout


@pytest.mark.parametrize("template,label", HOSTILE_BANNER_VERSIONS)
def test_launcher_banner_refuses_a_malformed_version(tmp_path, micromamba_stub_exe, template, label):
    marker = tmp_path / "marker.txt"
    version = template.format(marker=marker)
    result = _run_launcher_with_version(tmp_path, micromamba_stub_exe, version)
    assert not marker.exists(), (label, "the banner ran part of the value as a command")
    assert result.returncode == 0, (label, result.stdout + result.stderr)
    assert "Release: unknown" in result.stdout, (label, result.stdout)


# ===========================================================================
# 8. A path read from the install record or typed at a prompt reaches
#    :validate_base_var through VBPATH, never through a quoted argument.
#
# %LOCALAPPDATA%\TAVI\install-record.txt is ordinary user-writable text, and
# "call :validate_base "%VALUE%"" ends the quoted argument at the value's own
# double quote and runs the rest. Each hostile value creates a marker file if
# any line expands it; the two shapes defeat a quoted argument and an "if"
# comparison respectively. LOCALAPPDATA, USERPROFILE and SystemDrive all point
# into tmp_path, so no real installation can be found or touched.
# ===========================================================================

HOSTILE_PATHS = [
    ('C:\\x"&type nul> "{marker}"&rem "', "ampersand after a quote"),
    ('x"=="y" type nul> "{marker}" & rem "', "completes an if comparison"),
]


def _sandbox_env(tmp_path, record_value=None, state="complete"):
    env = dict(os.environ)  # Windows: os.environ keys are upper case
    # TEMP too: the hand-off to an installed uninstaller copies it there.
    for name in ("LOCALAPPDATA", "USERPROFILE", "SYSTEMDRIVE", "TEMP", "TMP"):
        folder = tmp_path / name.lower()
        folder.mkdir()
        env[name] = str(folder)
    if record_value is not None:
        (tmp_path / "localappdata" / "TAVI").mkdir()
        (tmp_path / "localappdata" / "TAVI" / "install-record.txt").write_text(
            f"TAVI_BASE={record_value}\nSTATE={state}\n", encoding="utf-8", newline="\r\n")
    return env


ENTRY_SCRIPTS = [UNINSTALL_STANDALONE, REPAIR_LAUNCHERS]
ENTRY_IDS = [os.path.basename(path) for path in ENTRY_SCRIPTS]
HOSTILE_IDS = [label for _, label in HOSTILE_PATHS]


@pytest.mark.parametrize("script", ENTRY_SCRIPTS, ids=ENTRY_IDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_a_hostile_install_record_is_not_expanded(tmp_path, script, template, label):
    marker = tmp_path / "marker.txt"
    env = _sandbox_env(tmp_path, record_value=template.format(marker=marker))
    # An empty line for the folder prompt (nothing found), C for the closing one.
    result = run_bat(script, env=env, timeout=20, input_text="\nC")
    assert not marker.exists(), (label, "a line expanded the record's value", result.stdout)
    assert "does not hold a usable path" in result.stdout, (label, result.stdout)


@pytest.mark.parametrize("script", ENTRY_SCRIPTS, ids=ENTRY_IDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_a_hostile_typed_path_is_not_expanded(tmp_path, script, template, label):
    marker = tmp_path / "marker.txt"
    env = _sandbox_env(tmp_path)
    result = run_bat(script, env=env, timeout=20,
                     input_text=template.format(marker=marker) + "\nC")
    assert not marker.exists(), (label, "a line expanded the typed value", result.stdout)
    assert result.returncode == 1, (label, result.stdout)
    assert "[ERROR]" in result.stdout, (label, result.stdout)


def _legacy_base(tmp_path):
    """A pre-1.3.2 program folder with no uninstaller of its own, so the
    standalone uninstaller removes it itself. Every pinned installer before
    1.3.2 wrote INSTALL_INFO.txt beside TAVI_PySide6.py."""
    base = tmp_path / "legacy"
    base.mkdir()
    (base / "TAVI_PySide6.py").write_text("# stub\n", encoding="utf-8", newline="\n")
    _write_install_info(base, "v1.1.0")
    return base


@pytest.mark.parametrize("which", ["standalone", "installed"])
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_dropping_the_record_does_not_expand_it(tmp_path, which, template, label):
    """After a removal, each uninstaller compares the record's TAVI_BASE with
    the folder it removed, to decide whether to delete the record."""
    marker = tmp_path / "marker.txt"
    env = _sandbox_env(tmp_path, record_value=template.format(marker=marker))
    if which == "standalone":
        base = _legacy_base(tmp_path)
        # Y removes the legacy installation; C closes the window.
        result = run_bat(UNINSTALL_STANDALONE, str(base), env=env, timeout=30, input_text="YC")
    else:
        base = _uninstallable_base(tmp_path, "installed")
        result = run_bat(UNINSTALL_TAVI, str(base), "/y", env=env, timeout=30)
    assert not marker.exists(), (label, "the record's value was expanded", result.stdout)
    assert result.returncode == 0, (label, result.stdout + result.stderr)
    assert "has been removed" in result.stdout, (label, result.stdout)
    assert not base.exists(), label
    # It names some other folder, so it stays.
    assert (tmp_path / "localappdata" / "TAVI" / "install-record.txt").exists(), label


# The good paths through the same lines: a record naming a real installation
# still finds it, and is removed with it.

def test_the_standalone_uninstaller_follows_a_good_record(tmp_path):
    base = _uninstallable_base(tmp_path, "installed")
    env = _sandbox_env(tmp_path, record_value=str(base))
    # Y answers the installed uninstaller it hands over to; C closes it.
    result = run_bat(UNINSTALL_STANDALONE, env=env, timeout=30, input_text="YC")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    assert not (tmp_path / "localappdata" / "TAVI" / "install-record.txt").exists(), result.stdout


def test_a_legacy_removal_drops_a_record_that_names_it(tmp_path):
    base = _legacy_base(tmp_path)
    env = _sandbox_env(tmp_path, record_value=str(base))
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=env, timeout=30, input_text="YC")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    assert not (tmp_path / "localappdata" / "TAVI" / "install-record.txt").exists(), result.stdout


def test_repair_launchers_follows_a_good_record(tmp_path):
    prog = _repair_target(tmp_path, "v1.3.2")
    env = _sandbox_env(tmp_path, record_value=str(prog))
    result = run_bat(REPAIR_LAUNCHERS, env=env, timeout=30, input_text="Y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (prog / "update-tavi.bat").exists(), result.stdout


# The installer reads the same record in :read_record_state, to tell a folder
# an install died in (offer to clear it) from some other folder (refuse it).
# Driven through /dir at a folder holding a stray file and no marker, which is
# where that routine runs; N declines the clearing and /dir then stops rather
# than ask again, so nothing is deleted or installed either way.

PARTIAL_NOTICE = "An earlier installation into this folder did not finish"


def _install_into_occupied_folder(tmp_path, record_base=None, state="installing",
                                  installer=INSTALL_1_3_2):
    base = tmp_path / "base"
    base.mkdir()
    (base / "stray.txt").write_text("x\n", encoding="utf-8", newline="\n")
    record = str(base) if record_base is None else record_base
    env = _sandbox_env(tmp_path, record_value=record, state=state)
    # 1.3.2 asks before clearing and is answered N; 1.4.0 under /dir asks nothing.
    keys = "N\n\n" if installer == INSTALL_1_3_2 else None
    result = run_bat(installer, "/dir", str(base), env=env, timeout=60, input_text=keys)
    assert (base / "stray.txt").exists(), result.stdout
    return result


def _never_waited(result):
    """A 1.4.0 /dir run ends on its headline and asks for no key."""
    assert "INSTALLATION FAILED" in result.stdout, result.stdout + result.stderr
    assert "Press" not in result.stdout, result.stdout
    assert "does not contain the valid choices" not in result.stderr, "a choice prompt ran"


@pytest.mark.parametrize("installer", [INSTALL_1_3_2, INSTALL_1_4_0], ids=os.path.basename)
def test_the_installer_recognises_a_partial_install_the_record_names(tmp_path, installer):
    result = _install_into_occupied_folder(tmp_path, installer=installer)
    assert PARTIAL_NOTICE in result.stdout, result.stdout + result.stderr
    assert result.returncode == 1, result.stdout
    if installer == INSTALL_1_4_0:
        _never_waited(result)
        assert "never removes an installation" in result.stdout, result.stdout


@pytest.mark.parametrize("field", ["TAVI_BASE", "STATE"])
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_the_installer_does_not_expand_a_hostile_record(tmp_path, field, template, label):
    marker = tmp_path / "marker.txt"
    value = template.format(marker=marker)
    if field == "TAVI_BASE":
        result = _install_into_occupied_folder(tmp_path, record_base=value)
    else:  # names this very folder, so the STATE comparison is reached
        result = _install_into_occupied_folder(tmp_path, state=value)
    assert not marker.exists(), (label, "a line expanded the record's value", result.stdout)
    assert result.returncode == 1, (label, result.stdout + result.stderr)
    assert "already contains other files" in result.stdout, (label, result.stdout)
    assert PARTIAL_NOTICE not in result.stdout, (label, result.stdout)


# ===========================================================================
# 9. The Doctor and the support recorder trust the install record only as far
#    as the uninstallers do: a validated path whose marker's INSTALL_ID
#    matches its INSTALL_INFO.txt's. Anything else falls back to the layout-1
#    default. Driven through /resolve-only, which prints the resolution and
#    exits before the Doctor runs a simulation or opens Notepad.
# ===========================================================================

RESOLVERS = [DOCTOR, RECORD_TAVI]
RESOLVER_IDS = [os.path.basename(path) for path in RESOLVERS]


def _resolve(script, env):
    result = run_bat(script, "/resolve-only", env=env, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    found = dict(line.split("=", 1) for line in result.stdout.splitlines()
                 if line.startswith(("LAYOUT=", "TAVI_BASE=")))
    return result, found


def _marked_base(tmp_path, install_id="1-2-3-4", info_id=None):
    base = tmp_path / "base"
    base.mkdir()
    _install_id_files(base, install_id=install_id, info_id=info_id)
    return base


@pytest.mark.parametrize("script", RESOLVERS, ids=RESOLVER_IDS)
def test_resolver_follows_a_record_to_a_matching_installation(tmp_path, script):
    base = _marked_base(tmp_path)
    _, found = _resolve(script, _sandbox_env(tmp_path, record_value=str(base)))
    assert found == {"LAYOUT": "2", "TAVI_BASE": str(base)}


@pytest.mark.parametrize("script", RESOLVERS, ids=RESOLVER_IDS)
def test_resolver_refuses_a_marker_whose_install_id_does_not_match(tmp_path, script):
    base = _marked_base(tmp_path, install_id="1-2-3-4", info_id="5-6-7-8")
    env = _sandbox_env(tmp_path, record_value=str(base))
    result, found = _resolve(script, env)
    assert found == {"LAYOUT": "1", "TAVI_BASE": env["USERPROFILE"]}, result.stdout
    assert "[INFO]" in result.stdout


@pytest.mark.parametrize("script", RESOLVERS, ids=RESOLVER_IDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_resolver_does_not_expand_a_hostile_record(tmp_path, script, template, label):
    marker = tmp_path / "marker.txt"
    value = template.format(marker=marker)
    env = _sandbox_env(tmp_path, record_value=value)
    result = run_bat(script, "/resolve-only", env=env, timeout=20)
    assert not marker.exists(), (label, "a line expanded the record's value", result.stdout)
    assert result.returncode == 0, (label, result.stdout + result.stderr)
    assert "LAYOUT=1" in result.stdout.splitlines(), (label, result.stdout)
    assert "[INFO]" in result.stdout, (label, result.stdout)
    assert value not in result.stdout, (label, "the raw value was printed", result.stdout)


# ===========================================================================
# 10. Values read from INSTALL_INFO.txt and the ownership marker are vetted
#     before any line expands them, as the install record's are (section 8).
#
# Both files sit in a folder the user can edit. A path goes into VBPATH and
# through :validate_base_var; INSTALL_ID must match the grammar the installer
# writes (four %RANDOM% numbers joined by dashes) and LAYOUT a number, both
# read through "set NAME|", before a comparison or a message expands them. A
# value that fails takes the routine's own refusal. Same hostile values and
# sandbox as section 8.
# ===========================================================================

REPAIR_PATH_FIELDS = ["ENV_PREFIX", "MAMBA_ROOT_PREFIX", "MICROMAMBA_DIR"]


@pytest.mark.parametrize("field", REPAIR_PATH_FIELDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_repair_launchers_does_not_expand_a_hostile_install_info_path(tmp_path, field, template,
                                                                      label):
    marker = tmp_path / "marker.txt"
    env = _sandbox_env(tmp_path)
    prog = _repair_target(tmp_path, "v1.3.2", **{field: template.format(marker=marker)})
    # A refusal never reaches the repair prompt: only the closing pause reads.
    result = run_bat(REPAIR_LAUNCHERS, str(prog), env=env, timeout=30, input_text="\n")
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 1, (label, result.stdout + result.stderr)
    assert "will not write into" in result.stdout, (label, result.stdout)
    for name in ("update-tavi.bat", "run-tavi.bat", "TAVI-Launcher.bat"):
        assert not (prog / name).exists(), (label, f"{name} was written")


def test_repair_launchers_derives_a_missing_mamba_root(tmp_path):
    prog = _repair_target(tmp_path, "v1.3.2", MAMBA_ROOT_PREFIX=None)
    result = run_bat(REPAIR_LAUNCHERS, str(prog), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="Y\n")
    assert result.returncode == 0, result.stdout + result.stderr
    # ENV_PREFIX\..\.. - the root an environment named under <root>\envs has.
    assert f'-r "{tmp_path.parent}"' in _read(str(prog / "run-tavi.bat"))


@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_a_legacy_removal_does_not_expand_a_hostile_env_prefix(tmp_path, template, label):
    marker = tmp_path / "marker.txt"
    base = _legacy_base(tmp_path)
    _write_install_info(base, "main", ENV_PREFIX=template.format(marker=marker))
    # Y removes the legacy installation; C closes the window.
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="YC")
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 0, (label, result.stdout + result.stderr)
    assert "Not removing the recorded environment path" in result.stdout, (label, result.stdout)
    assert not base.exists(), (label, result.stdout)


def test_a_legacy_removal_removes_its_recorded_environment(tmp_path):
    base = _legacy_base(tmp_path)
    env_prefix = tmp_path / "envs" / "tavi"
    (env_prefix / "conda-meta").mkdir(parents=True)
    (env_prefix / "conda-meta" / "history").write_text("", encoding="utf-8", newline="\n")
    _write_install_info(base, "main", ENV_PREFIX=env_prefix)
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="YC")
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Removing the environment: {env_prefix}" in result.stdout, result.stdout
    assert not env_prefix.exists(), result.stdout
    assert not base.exists(), result.stdout


def test_a_legacy_removal_keeps_a_recorded_path_that_is_no_environment(tmp_path):
    """ENV_PREFIX is editable text: a stale or mistaken value naming some other
    folder must be neither offered for removal nor removed."""
    base = _legacy_base(tmp_path)
    other = tmp_path / "Research"
    other.mkdir()
    (other / "data.txt").write_text("keep\n", encoding="utf-8", newline="\n")
    _write_install_info(base, "v1.1.0", ENV_PREFIX=other)
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="YC")
    assert (other / "data.txt").exists(), result.stdout
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    listing = result.stdout.split("Remove this TAVI installation?")[0]
    assert str(other) not in listing, ("offered for removal", result.stdout)
    assert "Not removing the recorded environment path" in result.stdout, result.stdout
    assert "no conda environment there" in result.stdout, result.stdout


def test_a_legacy_removal_keeps_another_conda_environment(tmp_path):
    """Every installer before 1.3.2 put its environment at <root>\\envs\\tavi. A
    recorded path to any other environment is not TAVI's and stays."""
    base = _legacy_base(tmp_path)
    other = tmp_path / "envs" / "analysis"
    (other / "conda-meta").mkdir(parents=True)
    (other / "conda-meta" / "history").write_text("", encoding="utf-8", newline="\n")
    _write_install_info(base, "v1.1.0", ENV_PREFIX=other)
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="YC")
    assert (other / "conda-meta" / "history").exists(), result.stdout
    assert result.returncode == 0, result.stdout + result.stderr
    assert not base.exists(), result.stdout
    listing = result.stdout.split("Remove this TAVI installation?")[0]
    assert str(other) not in listing, ("offered for removal", result.stdout)
    assert "not the environment a TAVI installer created" in result.stdout, result.stdout


@pytest.mark.parametrize("how", ["by argument", "at the default folder"])
def test_a_source_checkout_is_not_removed_as_a_legacy_installation(tmp_path, how):
    """A git clone has TAVI_PySide6.py too, but never INSTALL_INFO.txt."""
    env = _sandbox_env(tmp_path)
    checkout = tmp_path / "userprofile" / "TAVI"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "TAVI_PySide6.py").write_text("# stub\n", encoding="utf-8", newline="\n")
    args = [str(checkout)] if how == "by argument" else []
    # Neither run reaches the removal question, so only C is fed to the closing
    # prompt. With no argument the folder prompt (set /p) comes first and takes
    # a line, which is empty here.
    keys = "C" if how == "by argument" else "\nC"
    result = run_bat(UNINSTALL_STANDALONE, *args, env=env, timeout=30, input_text=keys)
    assert (checkout / ".git").is_dir(), (how, result.stdout)
    assert (checkout / "TAVI_PySide6.py").exists(), (how, result.stdout)
    assert "from before version 1.3.2" not in result.stdout, (how, result.stdout)
    if how == "by argument":
        assert result.returncode == 1, result.stdout + result.stderr
        assert "does not look like a TAVI installation" in result.stdout, result.stdout
        assert "UNINSTALL FAILED" in result.stdout, result.stdout
    else:  # not taken for an installation, so the search goes on to ask
        assert "No TAVI installation was found" in result.stdout, result.stdout


@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_the_standalone_uninstaller_does_not_expand_a_hostile_layout(tmp_path, template, label):
    marker = tmp_path / "marker.txt"
    base = _legacy_base(tmp_path)
    value = template.format(marker=marker)
    _write_install_info(base, "main", LAYOUT=value)
    result = run_bat(UNINSTALL_STANDALONE, str(base), env=_sandbox_env(tmp_path), timeout=30,
                     input_text="C")
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 1, (label, result.stdout + result.stderr)
    assert 'folder layout "unrecognised"' in result.stdout, (label, result.stdout)
    assert value not in result.stdout, (label, "the raw value was printed", result.stdout)
    assert (base / "TAVI_PySide6.py").exists(), label


# Which file carries the hostile value: each INSTALL_ID is checked on its own,
# so a check on one cannot cover for a missing check on the other.
IDENTITY_FIELDS = ["marker INSTALL_ID", "INSTALL_INFO INSTALL_ID", "INSTALL_INFO LAYOUT"]


def _identity(field, value):
    return {
        "marker INSTALL_ID": dict(install_id=value, info_id="1-2-3-4"),
        "INSTALL_INFO INSTALL_ID": dict(install_id="1-2-3-4", info_id=value),
        "INSTALL_INFO LAYOUT": dict(layout=value),
    }[field]


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_uninstall_does_not_expand_a_hostile_identity(tmp_path, field, template, label):
    marker = tmp_path / "marker.txt"
    value = template.format(marker=marker)
    base = _uninstallable_base(tmp_path, "installed", **_identity(field, value))
    result = run_bat(UNINSTALL_TAVI, str(base), "/y", env=_sandbox_env(tmp_path), timeout=20)
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 1, (label, result.stdout + result.stderr)
    assert "[ERROR]" in result.stdout, (label, result.stdout)
    assert value not in result.stdout, (label, "the raw value was printed", result.stdout)
    assert (base / "app" / "TAVI_PySide6.py").exists(), (label, "it deleted something")


# The installer makes the same identity test before it offers to remove an
# installation already in the chosen folder. /dir at that folder; N declines
# the removal and /dir then stops, so nothing is deleted either way.

def _install_over_marked_folder(tmp_path, installer=INSTALL_1_3_2, **identity):
    base = tmp_path / "base"
    base.mkdir()
    _install_id_files(base, **identity)
    keys = "N\n\n" if installer == INSTALL_1_3_2 else None
    result = run_bat(installer, "/dir", str(base), env=_sandbox_env(tmp_path), timeout=60,
                     input_text=keys)
    assert (base / ".tavi-install-root").exists(), result.stdout
    assert (base / "INSTALL_INFO.txt").exists(), result.stdout
    return result


@pytest.mark.parametrize("installer", [INSTALL_1_3_2, INSTALL_1_4_0], ids=os.path.basename)
def test_the_installer_recognises_its_own_installation(tmp_path, installer):
    result = _install_over_marked_folder(tmp_path, installer=installer)
    assert "There is already a TAVI installation" in result.stdout, result.stdout + result.stderr
    assert result.returncode == 1, result.stdout
    if installer == INSTALL_1_4_0:
        _never_waited(result)
        # A folder this run refused is not its to write into.
        assert not (tmp_path / "base" / "install-status.txt").exists()


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_the_installer_does_not_expand_a_hostile_identity(tmp_path, field, template, label):
    marker = tmp_path / "marker.txt"
    result = _install_over_marked_folder(tmp_path,
                                         **_identity(field, template.format(marker=marker)))
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 1, (label, result.stdout + result.stderr)
    assert "identity does not check" in result.stdout, (label, result.stdout)


@pytest.mark.parametrize("script", RESOLVERS, ids=RESOLVER_IDS)
@pytest.mark.parametrize("field", IDENTITY_FIELDS[:2])
@pytest.mark.parametrize("template,label", HOSTILE_PATHS, ids=HOSTILE_IDS)
def test_resolver_does_not_expand_a_hostile_install_id(tmp_path, script, field, template, label):
    marker = tmp_path / "marker.txt"
    base = _marked_base(tmp_path, **_identity(field, template.format(marker=marker)))
    result = run_bat(script, "/resolve-only", env=_sandbox_env(tmp_path, record_value=str(base)),
                     timeout=20)
    assert not marker.exists(), (label, "a line expanded the value", result.stdout)
    assert result.returncode == 0, (label, result.stdout + result.stderr)
    assert "LAYOUT=1" in result.stdout.splitlines(), (label, result.stdout)
    assert "[INFO]" in result.stdout, (label, result.stdout)


# ===========================================================================
# 12. The choice stand-in that keeps this suite silent is itself checked: it
#     must agree with the real choice.exe wherever the real one is silent, and
#     it must record what the real one would beep at.
# ===========================================================================

REAL_CHOICE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "choice.exe")

# Each case ends in valid keys or at end of input, so the real choice does not
# beep for any of them. The second batch line shows that both read one
# character per prompt and leave the rest of the pipe alone.
CHOICE_BATCH = (
    "@echo off\r\n"
    '"%CHOICE_EXE%" /C AB /N /M "First?"\r\n'
    "echo first=%ERRORLEVEL%\r\n"
    '"%CHOICE_EXE%" /C XYZ /N /M "Second?"\r\n'
    "echo second=%ERRORLEVEL%\r\n"
)


@pytest.mark.skipif(not os.path.exists(REAL_CHOICE), reason="no System32\\choice.exe")
@pytest.mark.parametrize("keys", ["BZ", "az", "B", "", "AY", "bx"])
def test_the_choice_stand_in_agrees_with_the_real_choice(tmp_path, keys, _choice_sensor_dir):
    if _choice_sensor_dir is None:
        pytest.skip("no stand-in was built")
    script = tmp_path / "two-prompts.bat"
    script.write_text(CHOICE_BATCH, encoding="utf-8", newline="")
    outcomes = []
    for exe in (REAL_CHOICE, os.path.join(_choice_sensor_dir, "choice.exe")):
        env = dict(os.environ, CHOICE_EXE=exe)
        done = run_bat(str(script), env=env, timeout=30, input_text=keys or None)
        outcomes.append((done.returncode, done.stdout, done.stderr))
    assert outcomes[0] == outcomes[1], outcomes


def test_the_choice_stand_in_records_a_stray_line_ending(tmp_path, _choice_sensor_dir):
    """The sensor can fail: a line ending after a key is two characters the
    next prompt would beep at, and that is the mistake this suite had."""
    if _choice_sensor_dir is None:
        pytest.skip("no stand-in was built")
    script = tmp_path / "one-prompt.bat"
    script.write_text('@echo off\r\nchoice /C C /N /M "Press C"\r\n', encoding="utf-8", newline="")
    log = tmp_path / "own-log.txt"
    env = dict(os.environ, TAVI_CHOICE_LOG=str(log))
    done = run_bat(str(script), env=env, timeout=30, input_text="\nC")
    assert done.returncode == 1, done.stdout + done.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        "BEEP at 0x0D in /C C", "BEEP at 0x0A in /C C"]


def test_run_bat_fails_on_a_bel_character_in_the_output(tmp_path):
    script = tmp_path / "bell.bat"
    script.write_bytes(b"@echo off\r\necho \x07\r\n")
    with pytest.raises(AssertionError, match="BEL"):
        run_bat(str(script), timeout=20)


# ===========================================================================
# 13. The 1.4.0 installer's log and endings. Driven through the test-only
#     /test-fail switch, so nothing is downloaded: the run stops at the named
#     step. LOCALAPPDATA, USERPROFILE and TEMP are sandboxed (section 8), and
#     the desktop is TAVI_TEST_DESKTOP (the autouse fixture).
# ===========================================================================

def _install_logs(env):
    logs = os.path.join(env["LOCALAPPDATA"], "TAVI", "logs")
    return [os.path.join(logs, name) for name in os.listdir(logs)
            if re.fullmatch(r"install-\d{8}-\d{6}\.log", name)]


def test_an_unattended_install_that_fails_says_so_logs_it_and_does_not_wait(tmp_path):
    base = tmp_path / "base"
    env = _sandbox_env(tmp_path)
    result = run_bat(INSTALL_1_4_0, "/dir", str(base), "/ref", "acs/j6c1ef11cf2ba",
                     "/test-fail", "micromamba", env=env, timeout=60)
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    _never_waited(result)
    assert "Failed step : Setting up micromamba" in out, out
    assert "forced failure (test run)" in out, out
    # The step's last log lines first, then the headline with the step and error.
    tail = out.index("The last lines of the installation log:")
    assert tail < out.rindex("INSTALLATION FAILED") < out.rindex("Failed step :"), out
    logs = _install_logs(env)
    assert len(logs) == 1, os.listdir(os.path.dirname(logs[0]) if logs else env["LOCALAPPDATA"])
    assert logs[0] in out, "the screen names the log"
    text = _text(logs[0])
    for expected in ("---- System snapshot ----", f"Install folder: {base}",
                     "Test switch /ref: cloning branch acs/j6c1ef11cf2ba",
                     "[Step 1/8] Setting up micromamba: started",
                     "[TAVI] Failed step: Setting up micromamba", "[TAVI] INSTALLATION FAILED"):
        assert expected in text, (expected, text)
    status = (base / "install-status.txt").read_text(encoding="utf-8")
    assert "OUTCOME=INSTALLATION FAILED" in status, status
    assert "FAILED_STEP=Setting up micromamba" in status, status
    assert "ERROR=forced failure (test run)" in status, status
    assert f"LOG={logs[0]}" in status, status
    assert not (base / "micromamba").exists(), "the forced step ran anyway"


def test_a_malformed_ref_is_refused_before_anything_is_made(tmp_path):
    base = tmp_path / "base"
    env = _sandbox_env(tmp_path)
    result = run_bat(INSTALL_1_4_0, "/dir", str(base), "/ref", "-upload-pack=x",
                     "/test-fail", "micromamba", env=env, timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    _never_waited(result)
    assert "Failed step : Reading the test switches" in result.stdout, result.stdout
    assert not base.exists(), "a refused switch must stop before the folder is made"
    assert "[TAVI] INSTALLATION FAILED" in _text(_install_logs(env)[0])


@pytest.mark.parametrize("whose", ["this installation", "another installation"])
def test_replacing_a_legacy_installation_removes_only_its_own_desktop_shortcut(tmp_path, whose):
    """v1.3.2 deleted %USERPROFILE%\\Desktop\\TAVI Launcher.lnk whatever it pointed
    at. Attended: the folder is typed, Y removes the legacy installation, N at
    "Continue?" stops before anything is installed, C closes."""
    base = _legacy_base(tmp_path)
    (base / "run-tavi.bat").write_text("rem stub\n", encoding="utf-8", newline="\n")
    env = _sandbox_env(tmp_path)
    legacy_desktop = tmp_path / "userprofile" / "Desktop"
    legacy_desktop.mkdir()
    lnk = legacy_desktop / "TAVI Launcher.lnk"
    target = base / "TAVI-Launcher.bat" if whose == "this installation" else (
        tmp_path / "elsewhere" / "TAVI-Launcher.bat")
    _make_shortcut(lnk, target)

    # The folder for set /p, then Y (remove it), N (do not continue), C (close).
    keys = tmp_path / "keys.txt"
    keys.write_bytes(f"{base}\r\nYNC".encode("ascii"))
    result = run_bat(INSTALL_1_4_0, env=env, timeout=60, input_file=keys)
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    assert "from before version 1.3.2" in out, out
    assert not base.exists(), out
    assert lnk.exists() == (whose == "another installation"), out
    assert "INSTALLATION CANCELLED" in out, out
    assert out.rindex("Press C to close this window.") > out.rindex("INSTALLATION CANCELLED")
    text = _text(_install_logs(env)[0])
    assert "Delete the old installation and continue? Answer: Y" in text, text
    assert "Continue with TAVI installation? Answer: N" in text, text
    assert str(lnk) in text, "the desktop step is not in the log"


@pytest.mark.parametrize("layout", ["current", "legacy"])
def test_cancelling_after_an_old_installation_was_removed_says_so(tmp_path, layout):
    """Y deletes the old installation, then N at "Continue?" installs nothing.
    The cancelled screen must say the removal happened, not that nothing was."""
    if layout == "current":
        base = _uninstallable_base(tmp_path, "base")
    else:
        base = _legacy_base(tmp_path)
        (base / "run-tavi.bat").write_text("rem stub\n", encoding="utf-8", newline="\n")
    env = _sandbox_env(tmp_path)
    # The folder for set /p, then Y (delete it), N (do not continue), C (close).
    keys = tmp_path / "keys.txt"
    keys.write_bytes(f"{base}\r\nYNC".encode("ascii"))
    result = run_bat(INSTALL_1_4_0, env=env, timeout=60, input_file=keys)
    out = result.stdout
    assert result.returncode == 0, out + result.stderr
    assert "INSTALLATION CANCELLED" in out, out
    assert "The old TAVI installation was removed. Nothing new was installed." in out, out
    assert "Nothing was installed and nothing was removed." not in out, out
    assert "Continue with TAVI installation? Answer: N" in _text(_install_logs(env)[0])


def _fixed_clock(tmp_path, env, stamp="20260101-000000"):
    """The launchers take their log stamp from powershell. A stub on PATH fixes
    it, so a log name can be known in advance and a clash made on purpose."""
    stub = tmp_path / "clock-stub"
    stub.mkdir(exist_ok=True)
    (stub / "powershell.bat").write_text(f"@echo off\necho {stamp}\n", encoding="ascii",
                                         newline="\r\n")
    env["PATH"] = f"{stub}{os.pathsep}{env['PATH']}"
    return env


@pytest.mark.parametrize("script,kind", [("run-tavi.bat", "launch"),
                                         ("update-tavi.bat", "repair")])
def test_a_second_run_in_the_same_second_gets_its_own_log(tmp_path, micromamba_stub_exe,
                                                          script, kind):
    """Two runs in one second share a stamp. The second must not truncate the
    first's log: it gets a suffixed name, as the install and uninstall logs do."""
    base, _, _ = _make_layout2_base(tmp_path, "base", micromamba_stub_exe)
    env = _fixed_clock(tmp_path, _launch_env(tmp_path, MICROMAMBA_STUB_LINES="1"))
    logs = _logs_dir(env)
    os.makedirs(logs)
    first = os.path.join(logs, f"{kind}-20260101-000000.log")
    with open(first, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("the first run\n")
    result = run_bat(str(base / script), env=env, timeout=60, input_text="C")
    assert result.returncode == 0, result.stdout + result.stderr
    with open(first, encoding="utf-8", newline="") as fh:
        assert fh.read() == "the first run\n", "the second run truncated the first log"
    fresh = [name for name in os.listdir(logs) if name != os.path.basename(first)]
    assert len(fresh) == 1 and re.fullmatch(rf"{kind}-20260101-000000-\d+\.log", fresh[0]), fresh
    with open(os.path.join(logs, fresh[0]), encoding="utf-8", newline="") as fh:
        assert "stub line 1" in fh.read()


# The %RANDOM% stamp used when PowerShell gives no clock has TAVI's own shape,
# so the diagnostics collector can take it from %TEMP% while no other
# program's install-*.log can pass for it.
LOG_NAMING_FILES = [INSTALL_1_4_0, RUN_TAVI, UPDATE_TAVI, UNINSTALL_TAVI, UNINSTALL_STANDALONE,
                    COLLECT_DIAG]


@pytest.mark.parametrize("path", LOG_NAMING_FILES, ids=os.path.basename)
def test_the_random_fallback_stamp_has_tavi_shape(path):
    assert 'set "STAMP=tavi-rnd-%RANDOM%-%RANDOM%"' in _read(path), path
