# Handoff — Windows installer (shipped in v1.3.2)

> **Status:** live
> **Authority:** the frontier of the Windows installer workstream, rewritten at every closeout

**End condition:** the affected remote user's ordinary shortcut and usual Monte
Carlo run succeed after `TAVI-Repair-Launchers.bat` (or a fresh v1.3.2 install),
and the uninstaller's own self-relaunch has been exercised once.
**Board entry:** "Remote Windows Monte Carlo installation failure"

The file name keeps "1-3-1" so links stay valid. Version 1.3.1 was never
tagged: the operator ruled on 2026-10-07 to release v1.3.2 from `main`, with
the crystal-orientation work included.

## Frontier
- Landed: tag `v1.3.2` on `26c43f49` (release PR #52, 2026-10-07); the release
  page carries `WINDOWS-install-TAVI-v1.3.2.bat`, `POSIX-install-TAVI-v1.3.2.sh`,
  `POSIX-uninstall-TAVI.sh`, `TAVI-Repair-Launchers.bat` and
  `WINDOWS-uninstall-TAVI.bat`, each byte-identical to its blob in the tag.
- Landed: PR #51 (`57bce08b`) carries PR #46's commits merged with main and
  renamed to 1.3.2. It also brings the review items, values read from the
  install record, `INSTALL_INFO.txt` and the ownership marker checked before
  any line expands them, delete guards on the old-layout uninstall path, the
  Doctor reporting the configured MPI count, and the POSIX `--mpi=2` compile
  check. PR #46 is closed as superseded.
- Verified, 2026-10-07: a cold install from the `v1.3.2` tag on the
  development machine, into a fresh folder:
  - the install itself, in 114 s, with the serial and MPI compile gate passing;
  - one PUMA Monte Carlo point through the installed launcher's API (4 MPI
    processes, 51 counts);
  - item 7: with a stale `%USERPROFILE%\AppData\mcstas\3.7.1_tavi` beside a
    poisoned `3.7.1_tavi-env`, `mcrun` used the poisoned `_tavi-env` compiler
    and ignored `_tavi`; with only `_tavi` present the build ran cleanly. The
    per-user folder is `%USERPROFILE%\AppData\mcstas`, **not**
    `%APPDATA%\mcstas` (that is `AppData\Roaming`);
  - an uninstall through the launcher menu removed the whole folder, package
    cache included.

## Next
Wait for the affected user's run after the field repair. Nothing is to be asked
of her beyond that run: no new probe.

## Where
- Job: none
- Branch: none; `installer-1.3.1`, `worktree-installer-1-3-1` and the worktree
  `.claude\worktrees\installer-1-3-1` are merged leftovers awaiting the
  operator's word
- Worktree: none
- PR: none

## Verify before trusting
1. `gh release view v1.3.2 --json assets` lists the five files above.
2. `git rev-parse v1.3.2^{commit}` prints `26c43f49…`.

## Decisions since the plan
none

## Open items
- **Item 3, partly covered.** The launcher menu's hand-off (copy to `%TEMP%`,
  pass the base explicitly) is exercised. `uninstall-tavi.bat`'s own
  self-relaunch, when run from inside the install folder with no arguments,
  is not.
- **The uninstaller's temporary copy is never cleaned up.** The menu uninstall
  leaves `%TEMP%\tavi-uninstall-<random>.bat` behind, by design: the copy
  cannot delete itself.
- **The POSIX installer has never run** on Linux or macOS, MPI check included
  (board: "MPI rank default fails on small Linux hosts").
- **The spaced-profile defects are still unfixed:** §7.2–§7.5 of
  [the spaced-profile handoff](HANDOFF-spaced-profile-install.md).

## Traps
- Never put a command with a visible side effect in a test table: `C:\TAVI&calc`
  opened Calculator on every suite run. Use `&rem`.
- Nothing in the install or uninstall path may use `start`: it gets its own
  console, which `CREATE_NO_WINDOW` cannot suppress. A test enforces this.
- Python's `subprocess` list quoting does not escape cmd metacharacters; use
  the test file's `run_bat` and `_cmd_quote`.
- `set /p` drains a redirected stdin, so a following `choice` returns 255.
  `/dir <path>` answers the folder question; pipe `Y` for `Continue?`.
- The tool shells set `NoDefaultCurrentDirectoryInExePath`, which breaks
  `mcrun`'s bare `NAME.exe` launch. In Python, filter `os.environ`
  case-insensitively: Windows stores the key upper-cased, so
  `pop("NoDefaultCurrentDirectoryInExePath")` silently does nothing.
