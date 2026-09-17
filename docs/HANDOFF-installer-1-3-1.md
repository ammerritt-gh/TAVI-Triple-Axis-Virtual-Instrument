# Handoff — installer 1.3.1

> **Status:** live

**Start here: PR #46 is open and ready for review, with seven known items left
undone (§6). Nothing is uncommitted. Do not upload the installer to a release
until §5's gate is met.**

**Date:** 2026-09-17
**Workstream:** Windows installer 1.3.1 / the spaced-profile remote failure

## Fresh-session brief

- **What this was for.** Three things: repair the confirmed launcher defect from
  [the spaced-profile handoff](HANDOFF-spaced-profile-install.md) §11–§12; let
  the user choose where TAVI is installed, open that folder and leave a movable
  shortcut in it; and move uninstall into the launcher menu.
- **Where the work is.** PR #46, branch `installer-1.3.1` (durable) and
  `worktree-installer-1-3-1` (the PR head; same commit). 15 commits from
  `75cf9d1c`. Both branches pushed. `main` is clean.
- **State.** Full suite 1355 passed / 1 skipped in 124.6 s. A cold 3 GB install
  of the shipping file succeeded, a real Monte Carlo point ran through the
  installed launcher, and an uninstall through the menu removed everything TAVI
  owned while leaving a planted user file. Details in §4.
- **Next action.** Disposition §6's seven open items, then merge. Two of them
  (an automated test of the in-place uninstall hand-off, and the McStas
  per-user-config fixture) need another cold install to be meaningful.
- **Do not repeat:** the environment-selection defect is settled and verified.
  Do not re-derive it or re-run the plan seats. The five plan-stage seats and
  the external PR review are all folded in; §3 lists what each found.

---

## 1. What changed

**One folder.** Everything an installation owns lives under a base the user
names: `app\` (the pinned checkout, with `output\` and `config\`), `tavi-env\`,
`micromamba\`, `mamba\` (package cache), `compile_check\`, the four launchers,
`INSTALL_INFO.txt` and `.tavi-install-root`. Default `%USERPROFILE%\TAVI`, or
`%SystemDrive%\TAVI-Data` when the profile itself fails validation. The
`%TEMP%`-contains-a-space special case is gone with it.

**Selection by prefix, never by name.** Every micromamba call passes a quoted
`-r <root>` and `-p <prefix>`. The environment folder is `tavi-env` and not
`env` on purpose: McStas keys its per-user config on the basename of
`CONDA_DEFAULT_ENV`, and micromamba reports the whole prefix path when the
prefix's parent is not literally `envs` — verified directly against micromamba
2.5.0, not taken on trust. The installer's stale-config step and the Doctor were
corrected from a hardcoded `_tavi` to `_tavi-env`.

**Launchers are shipped, not generated.** Ordinary files in
`installer/launchers/`, copied into the base, deriving every path from `%~dp0`.
They live in the base rather than in `app\` so that `update-tavi.bat`'s own
`git checkout` cannot rewrite a batch file cmd is reading line by line.

**Uninstall never runs `rd /s /q` on the base.** It removes the children it
created by name, decides success by existence tests rather than `ERRORLEVEL`,
retries a bounded number of times, then does a bare `rd` which Windows refuses
for a non-empty folder — so user content survives and is reported. Deleting
requires `.tavi-install-root` with an `INSTALL_ID` matching `INSTALL_INFO.txt`.

**A locator record** at `%LOCALAPPDATA%\TAVI\install-record.txt` holds
`TAVI_BASE`, `STATE` and `INSTALL_ID`, written as soon as the base exists so a
half-finished multi-GB install is still findable. It locates; it never
authorises a delete.

**`installer/TAVI-Repair-Launchers.bat`** is a one-shot field repair for a
machine already running 1.3.0, which shipping a new installer does not help.

---

## 2. Files

| Path | What |
|---|---|
| `installer/WINDOWS-install-TAVI-v1.3.1.bat` | new; `TAVI_VERSION=v1.3.1`, `INSTALLER_VERSION=v1.3.1-1` |
| `installer/launchers/{run-tavi,update-tavi,TAVI-Launcher,uninstall-tavi}.bat` | new; shipped, self-locating |
| `installer/launchers/LAYOUT` | `LAYOUT=2`; the installer refuses a release that lacks it |
| `installer/WINDOWS-uninstall-TAVI.bat` | rewritten as locator → delegator → legacy handler |
| `installer/TAVI-Repair-Launchers.bat` | new |
| `installer/TAVI-Doctor.bat`, `tools/support/Record-TAVI.bat` | read the record, fall back to the old rule |
| `tests/test_installer_launchers.py` | new; 89 tests, ~6 s |
| `installer/TAVI_Windows_Installer_Uninstaller_Design_Document.md` | §1, §3, §4, §5, §16, §17, §18, §22, recipe (h) |
| `installer/TAVI-Installation-README.md` | quick start, menu, paths, uninstalling, troubleshooting |
| `changelog.d/{install-location,uninstall-from-launcher,launcher-environment}.md` | harvest under `v1.3.1` |
| `.gitattributes` | new; `*.bat text eol=crlf` |

The first commit (`e62f592b`) carries the operator's previously-uncommitted
build-4 installer/uninstaller edits and the standalone Doctor, unchanged. That
closes the board's "commit and PR the three installer files" item.

---

## 3. Defects found, and by what

Everything here is written up in the design document §18 with its reproduction.
The point of this list is that **five review seats passed the plan, and the
defects below were still found afterwards — most of them by running the thing.**

Found by a cold install:

1. `echo LAYOUT=%LAYOUT%>> "file"` expands to `echo LAYOUT=2>> "file"`, and cmd
   reads the digit before a redirection as the stream number. The layout line
   was never written, so the uninstaller refused **every** real installation.
2. A stray `copy.py` in `%TEMP%` shadowed the standard library for the
   installer's helper scripts (Python puts a script's own directory first on
   `sys.path`). McStasScript configuration failed silently — that step had no
   `errorlevel` check. Helpers now run from a folder the installer owns.
   **Note for the operator: that `copy.py` is still in `%TEMP%` and will break
   any Python run from there, not just ours.**
3. A half-finished install had no ownership marker yet, so the next run refused
   the folder as somebody else's.

Found by the validator's own test table:

4. `findstr` character ranges follow locale collation, so `[A-Za-z]` matched
   accented Latin letters and `C:\TAVÉ` was accepted. Enumerated now.
5. Refusal messages echoed the path that had just failed validation, so `&` in
   it split the command line. **This launched Calculator repeatedly on the
   operator's machine while the test table ran.** The marker in the table is
   now `&rem`, and refusals print through `set VBPATH`.

Found by the external PR review (ChatGPT, extra-high, ticket `8114505e5425`):

6. **`:base_has_legacy` treated `TAVI_PySide6.py` alone as proof of an
   installation.** Pointing the installer at any checkout of this project —
   including the maintainer's own clone — offered to `rd /s /q` the whole
   folder. A pre-1.3.1 install must now also carry `INSTALL_INFO.txt` and a
   generated `run-tavi.bat`, neither tracked in the repo.
7. `:validate_base` only reparse-checked the final component, so
   `C:\SomeJunction\TAVI` passed, and a not-yet-existing base was not checked at
   all. It now walks every existing component to the drive root.
8. `call :validate_base "%VAR%"` expands the raw value before anything vets it;
   a double quote ends the quoted region. The whitelist now runs first and reads
   the value through `set NAME |`; the prompt reads into `VBPATH` with `set /p`.
9. The standalone uninstaller's legacy lane deleted the global record
   unconditionally, orphaning a layout-2 installation that owned it.
10. `:base_has_tavi` entered on the marker's presence without the `INSTALL_ID`
    or `LAYOUT` check the uninstaller makes.
11. The Doctor looked for `INSTALL_INFO.txt` in `<base>\app`; layout 2 puts it
    at `<base>\`. Every healthy install would have reported a false `[PROBLEM]`.

Found because the operator said so:

12. The uninstall hand-off used `start`, which gives the detached process its
    own console. It now `cd`s out of the tree and `call`s the copy in the
    console already open, with the copy ending the process via `exit`. There is
    a test that fails if `start` reappears in any shipped install/uninstall
    script. Measured: console process count unchanged across a full menu-driven
    uninstall and across the whole test file.

---

## 4. Acceptance already done

- `micromamba run -n tavi-dev python -m pytest tests -q -ra` → **1355 passed,
  1 skipped, 124.6 s.** The skip is `test_dispersion_map.py`, which needs the
  gitignored `components/Pb_dft_phonons.dat`.
- `tests/test_installer_launchers.py` → **89 passed, ~6 s.** Drives the real
  batch files. Shown red against the v1.3.0 file.
- **Cold install** of the shipping file into `C:\tavi-it` (~3 GB): compile gate
  passed serial and MPI, lead-sample map built, `LAYOUT`/`INSTALL_ID` written
  and consistent across all three files, helper folder cleaned up.
- **One real Monte Carlo point through the installed `run-tavi.bat`**, with a
  hostile `MAMBA_ROOT_PREFIX` *and* `CONDA_PREFIX` inherited: selected
  `C:\tavi-it\tavi-env`, mcrun and resources from there, fresh compilation, a
  detector file written. Deterministic-engine success alone would not have
  shown this. The harness is driven through a copy of the installed
  `run-tavi.bat` with only the entrypoint swapped, so every
  environment-selection line is the launcher's own.
- **Uninstall through the launcher menu** against that real installation: every
  TAVI child removed, a planted user file and the base left standing and named,
  the record removed.

The machine was left clean: no `C:\tavi-it`, no install record, no temp copies.

---

## 5. Release gate — do not skip

The installer file is committed but **must not be uploaded as a release asset**
until both hold:

1. The `v1.3.1` tag exists.
2. A cold install has been run against **that real tag** — recipe §22(b). The
   cold run described above used the pushed branch, because the tag did not
   exist yet, and the installer refuses a release whose tree lacks
   `installer/launchers/LAYOUT`, so an older tag cannot stand in.

Merging the PR is not blocked by this. Publishing is.

Useful for an unattended cold run: `WINDOWS-install-TAVI-v1.3.1.bat /dir <path>`
answers the folder question without asking (it does not skip the confirmation,
and never approves removing an existing installation). Needed because `set /p`
drains a redirected stdin, so a following `choice` gets nothing.

---

## 6. Open items

Numbered for the next session to disposition. 1–5 come from the external PR
review and are recorded as accepted-but-not-done; 6 is a docs sweep; 7 is the
oldest.

1. **The `exit` hand-off is not composable.** `call`ing the uninstaller from
   another batch kills the caller too. The reviewer's judgement: "not a bug if
   the contract is that uninstall is terminal for this interpreter, but it
   should be documented." It is in code comments; not in the design document.
2. **The fall-through `exit` guards carry no numeric code.** Reviewer wanted
   `exit 1` so an unexpected return is unambiguous. Three one-word edits.
3. **The in-place hand-off has no automated test.** Every uninstall test runs
   the repository copy against a different base, so `SELF_DIR != TAVI_BASE` and
   the self-relaunch path is never exercised. Only cold-install and manual
   evidence covers it.
4. **`TAVI_VERSION` is read from `INSTALL_INFO.txt` and used unvalidated** in
   `git checkout` by `update-tavi.bat`, and written wholesale into generated
   launchers by `TAVI-Repair-Launchers.bat`. Validate it to a small grammar.
5. **`TAVI-Doctor.bat` and `tools/support/Record-TAVI.bat` trust `REC_BASE`**
   from the user-writable record after only checking that the marker exists —
   not the validated, ID-matched resolution the uninstaller uses, despite
   comments claiming the three are kept in step.
6. **Design document §§19–21, §23 and §24 are still layout-1 material**: fixed
   `%USERPROFILE%`/AppData locations, an environment named `tavi`, `run -n tavi`
   diagnostics, and a §23 manifest proposing `env: "tavi"`. §24 still says
   "generate launchers safely".
7. **From the plan review, never done:** a fixture proving *which* McStas
   per-user config `mcrun` actually reads — a stale
   `%APPDATA%\mcstas\3.7.1_tavi` alongside a deliberately poisoned
   `3.7.1_tavi-env`, with distinguishable compiler settings. The filename was
   corrected and the mechanism reasoned through, but not demonstrated. This is
   the weakest link in the chain, because being wrong there reproduces the
   original user's symptom.

Items 3 and 7 need a real installation to mean anything, i.e. another cold run.

---

## 7. Seats

| Seat | Outcome |
|---|---|
| Critic (plan) | returned — 17 objections, all adopted |
| Plan-verifier (risk trigger) | returned — REVISE, 3 blockers, all adopted |
| Panel, 5 models / 5 lenses | returned — 4 yea / 1 nay; the nay (`rd` returns 0 after skipping locked files) adopted |
| Codex critique (plan) | returned — 5 findings, all adopted |
| External reader (plan), ticket `2b3a31a2c8f0` | returned — 10 findings, all adopted |
| Per-slice `review_files` smoke | ran twice; both rounds' findings adopted |
| **Pre-PR reviewer** | **launched and never reported. Its findings were never seen.** Re-run it against `installer-1.3.1` if that seat matters before merge. |
| External reader (PR #46), ticket `8114505e5425` | returned — findings above; §6 is what is left of it |

The Codex budget used one critique of the tier's three calls.

---

## 8. Traps for whoever picks this up

- **Do not put a command with a visible side effect in a test table.** The
  validator table originally used `C:\TAVI&calc` to prove ampersands are
  rejected; every loop of the suite opened Calculator on the operator's
  machine. Use `&rem`.
- **Nothing in the install or uninstall path may use `start`.** It gives the new
  process its own console, which the test session's `CREATE_NO_WINDOW` cannot
  suppress because cmd, not the session, creates it. A test enforces this.
- **Python's `subprocess` list quoting does not escape cmd metacharacters.**
  `["script.bat", r"C:\TAVI&rem"]` reaches the script as `C:\TAVI`. The test
  file's `run_bat`/`_cmd_quote` caret-escape before quoting; use them.
- **`set /p` drains a redirected stdin**, so a `choice` after it gets nothing
  and returns 255.
- **The tool shells set `NoDefaultCurrentDirectoryInExePath`**, which breaks
  `mcrun`'s bare `NAME.exe` launch. Empty it before any cold install, or the
  compile gate fails in a way that looks like a compiler problem.
- **The Bash tool refuses commands containing "git"** in a worktree session,
  and the repo path contains `Github`. Use the PowerShell tool or a script file.

---

## 9. Board

`WIP.md` is not yet updated for this work; do it at closeout, on `main`. The
entry "Remote Windows Monte Carlo installation failure" should record that the
launcher repair is built and on PR #46, and that the remote acceptance is
unchanged: the affected user's ordinary shortcut and her usual Monte Carlo run,
after the field repair — no new probe.
