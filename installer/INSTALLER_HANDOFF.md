# TAVI Installer Handoff Document
*End of session: May 2026*

## What We Were Doing
Rewriting the TAVI Windows installer (`installer/WINDOWS-install-TAVI.bat`) to add:
- vswhere-based VS detection (handles VS 2026 installing to `\18\` not `\2026\`)
- Microsoft MPI SDK detection
- Pinned versioning (`TAVI_VERSION`, `MAMBA_VERSION` + SHA256)
- Micromamba isolation via `-r "%MICROMAMBA_DIR%"` on all calls (prevents collision with dev `tavi-dev` env)
- Upfront explanation + Y/N confirmation before install begins
- Compiler bootstrap (vcvarsall + MPI paths) baked into generated `run-tavi.bat`
- `WINDOWS-uninstall-TAVI.bat` (new, working)

## Hard Constraints (Do Not Violate)
- **The installer must be fully self-contained.** VS Build Tools is the only prerequisite the user installs manually. Everything else — Python, McStas, git, all dependencies — must come from micromamba/conda-forge. Do not add any new user-facing requirements.
- Python stays at **3.11** (confirmed: `tavi-dev` env runs 3.11.15).
- `git` stays in `CONDA_PACKAGES` — installed via conda-forge into the `tavi` env, not assumed present on the system.

## Current Broken State
The installer runs to completion and places a `.lnk` shortcut on the desktop, but `C:\Users\AMM\TAVI` is never created. The shortcut points at a non-existent `TAVI-Launcher.bat`.

**Root cause: the git clone step is silently failing and the installer continues anyway.**

Likely cause: conda-forge's `git` package for Windows is either failing to install into the env, or installing but not being invoked correctly via `micromamba run`. Not caught because there was no visible error — the installer continued after the clone failed and created a broken shortcut.

## The Correct Fix (NOT YET IMPLEMENTED)

### 1. Manually verify git in the tavi env first
Run this on the test user account to confirm the actual failure mode:
```bat
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe -r "%USERPROFILE%\AppData\Local\micromamba" run -n tavi git --version
```

### 2. Add git verification step in the installer
After env create/reconcile, before the clone, confirm git is actually runnable:
```bat
echo [INFO] Verifying git is available...
"%MICROMAMBA_DIR%\micromamba.exe" -r "%MICROMAMBA_DIR%" run -n %ENV_NAME% git --version >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] git is not available in the tavi environment.
    echo [ERROR] Try re-running the installer and choosing to recreate the environment.
    pause
    exit /b 1
)
echo [OK] git available.
```

### 3. Harden all error paths
Every `micromamba run ... git` call needs a visible `pause` + `exit /b 1` on failure. The `:clone_failed` label exists but may not be reached if errorlevel is not set correctly by micromamba on failure. Verify and fix each one.

## Environment Facts
- Python in tavi-dev env: **3.11.15**
- VS installation: **VS 2026 Community** at `C:\Program Files\Microsoft Visual Studio\18\Community\` — vswhere handles the `\18\` path correctly
- MPI SDK: present at `C:\Program Files (x86)\Microsoft SDKs\MPI\`
- Dev env root: `%APPDATA%\Roaming\mamba\envs\tavi-dev` — NOT touched by installer or uninstaller
- Installer env root: `%LOCALAPPDATA%\micromamba\envs\tavi` — isolated via `-r` flag
- `-r "%MICROMAMBA_DIR%"` on ALL micromamba calls is essential

## Known cmd.exe Pitfalls From This Session
1. **`::` comments inside parenthesised blocks** — parsed as commands, not comments. Remove them.
2. **`call` inside parenthesised `echo` blocks** — cmd.exe executes it rather than echoing. If `call vcvarsall.bat` fires it runs `endlocal` internally and wipes all installer variables. Fix: use nested `if` blocks within the parenthesised section to conditionally echo the call line as text.
3. **`!VAR!` passed to PowerShell** — PowerShell is a separate process, doesn't see delayed expansion. Set `set "PS_VAR=!VAR!"` then reference `!PS_VAR!` in the PowerShell command string.
4. **`shell init` call** — removed. Fails for new user accounts and registers the shared roaming root, defeating env isolation.

## Files Changed This Session
- `installer/WINDOWS-install-TAVI.bat` — full rewrite (broken at clone step, fix described above)
- `installer/TAVI-Installation-README.md` — full rewrite (good, no issues)
- `installer/WINDOWS-uninstall-TAVI.bat` — new file (working, confirmed safe re: dev env)

## Uninstaller (Confirmed Safe)
- Removes `tavi` env from `%LOCALAPPDATA%\micromamba`
- Optionally removes micromamba itself (asks user, lists other envs first)
- Removes `%USERPROFILE%\TAVI`
- Removes desktop shortcut
- Does NOT touch `tavi-dev`, VS, MPI, or any system tools

## Shortcut Generation (Proven Working Pattern)
From the original installer — preserve exactly:
```bat
set "PS_DESKTOP=%USERPROFILE%\Desktop\TAVI Launcher.lnk"
set "PS_TARGET=!LAUNCHER_SCRIPT!"
set "PS_WORKDIR=!INSTALL_DIR!"
powershell -NoProfile -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([System.Environment]::ExpandEnvironmentVariables('!PS_DESKTOP!')); $Shortcut.TargetPath = '!PS_TARGET!'; $Shortcut.WorkingDirectory = '!PS_WORKDIR!'; $Shortcut.Description = 'TAVI - Triple Axis Virtual Instrument'; $Shortcut.Save()"
```

## Next Steps (Priority Order)
1. Manually run `micromamba run -n tavi git --version` on the test account to confirm the failure mode
2. Add git verification step after env setup with a hard stop on failure
3. Harden all clone/git error paths so failures are visible and halt the installer
4. Re-test on the test user account

## Release recipe

For each new release `vX.Y.Z`:
1. Merge the release branch to `main` and cut the `vX.Y.Z` tag there.
2. Copy the previous pinned installer to `WINDOWS-install-TAVI-vX.Y.Z.bat` and bump
   the header comment plus `TAVI_VERSION`/`INSTALLER_VERSION` (nothing else changes).
3. Create the GitHub release from the tag and attach the pinned installer `.bat`
   as a release artifact. Done for `v1.1.0` and `v1.2.0`.
