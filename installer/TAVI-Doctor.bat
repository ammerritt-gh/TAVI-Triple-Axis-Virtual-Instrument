@echo off
setlocal DisableDelayedExpansion

:: TAVI Doctor - collects one diagnostic report for a failing McStas install.
:: Double-click it. It changes nothing; it only reads, and runs three short test
:: simulations. It writes one log file and opens it in Notepad so it can be sent on.
::
:: It exists because remote diagnosis by screenshot costs a day per round trip.

set "ENV_NAME=tavi"
set "MCSTAS_VERSION=3.7.1"

:: mcrun launches the compiled instrument as a bare "NAME.exe" through the shell.
:: A shell with NoDefaultCurrentDirectoryInExePath set refuses to search the
:: working directory and the serial run dies with "is not recognized as an
:: internal or external command" -- a property of the shell, not the install.
set "NoDefaultCurrentDirectoryInExePath="

:: /resolve-only prints the installation it resolved (LAYOUT, then TAVI_BASE)
:: and exits before anything else runs; it changes nothing. It exists so that
:: tests/test_installer_launchers.py can drive the real resolution, as
:: /validate-only lets it drive :validate_base in the installer and uninstallers.
set "RESOLVE_ONLY="
if /i "%~1"=="/resolve-only" set "RESOLVE_ONLY=1"

:: layout 2 (1.3.2+): the base folder is user-chosen at install time and
:: cannot be computed by rule, so the installer leaves a locator behind at
:: %LOCALAPPDATA%\TAVI\install-record.txt. The record is ordinary
:: user-writable text, so it is trusted only as far as the uninstallers trust
:: it: its value goes straight into VBPATH and through :validate_base_var
:: before any line expands it (as in installer\WINDOWS-uninstall-TAVI.bat),
:: and the folder counts as an installation only when its marker's INSTALL_ID
:: matches its INSTALL_INFO.txt's (as in installer\launchers\uninstall-tavi.bat).
:: Anything else falls back to the layout-1 default. The resolution below is
:: the same in tools\support\Record-TAVI.bat -- keep the two in step.
set "LAYOUT=1"
set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
if not exist "%RECORD%" goto default_base
set "VBPATH="
for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "VBPATH=%%B"
if not defined VBPATH goto default_base
call :validate_base_var
if defined VB_REASON goto record_unusable
set "MARK_ID="
set "INFO_ID="
if exist "%VBPATH%\.tavi-install-root" for /f "usebackq tokens=1,* delims==" %%A in ("%VBPATH%\.tavi-install-root") do if /i "%%A"=="INSTALL_ID" set "MARK_ID=%%B"
if exist "%VBPATH%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%VBPATH%\INSTALL_INFO.txt") do if /i "%%A"=="INSTALL_ID" set "INFO_ID=%%B"
if not defined MARK_ID goto record_unusable
if not defined INFO_ID goto record_unusable
:: Both IDs come from text files in that folder. The installer writes
:: INSTALL_ID as four random numbers joined by dashes; anything else does not
:: check out, and is refused before the comparison expands it. "set NAME|"
:: hands the value to findstr without cmd parsing it; digits are listed, not
:: ranged, because findstr resolves a range through the machine collation.
set MARK_ID| findstr /r /x /c:"MARK_ID=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto record_unusable
set INFO_ID| findstr /r /x /c:"INFO_ID=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto record_unusable
if /i not "%MARK_ID%"=="%INFO_ID%" goto record_unusable
set "LAYOUT=2"
set "TAVI_BASE=%VBPATH%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MICROMAMBA_DIR=%TAVI_BASE%\micromamba"
set "MAMBA_ROOT_PREFIX=%TAVI_BASE%\mamba"
set "RELOCATED=n/a (layout 2: user-chosen base)"
echo [INFO] Installation found from the install record: %TAVI_BASE%
goto paths_ready

:record_unusable
:: Never print the value: it may be the one that failed validation.
echo [INFO] The install record does not name a TAVI installation that checks
echo        out, so the default location is used instead.

:default_base
:: Pre-1.3.2 layout: same space-safe base resolution as that installer
:: (build 4). Keep these in step.
set "TAVI_BASE=%USERPROFILE%"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "RELOCATED=no"

if not "%USERPROFILE%"=="%USERPROFILE: =%" goto relocate_base
goto default_ready

:relocate_base
set "TAVI_BASE=%SystemDrive%\TAVI-Data"
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_DIR=%SystemDrive%\TAVI-Data\micromamba"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"
set "RELOCATED=yes"

:default_ready
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
echo [INFO] Installation found at the default location: %INSTALL_DIR%

:paths_ready
if defined RESOLVE_ONLY goto resolve_only
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
:: Layout 2 keeps INSTALL_INFO.txt beside the launchers in the base; layout 1
:: kept it inside the program folder. Looking in the wrong one made every
:: healthy 1.3.2 installation report "[PROBLEM] No INSTALL_INFO.txt".
set "INFO_FILE=%INSTALL_DIR%\INSTALL_INFO.txt"
if exist "%TAVI_BASE%\.tavi-install-root" set "INFO_FILE=%TAVI_BASE%\INSTALL_INFO.txt"
:: A folder of the operator's that happens to be called tavi_doctor is not
:: ours to delete, and this file is a read-only diagnostic.
set "WORK_DIR=%TAVI_BASE%\tavi_doctor_%RANDOM%%RANDOM%"
set "LOG=%WORK_DIR%\TAVI-doctor-report.txt"
set "SUMMARY=%WORK_DIR%\TAVI-doctor-summary.txt"

title TAVI Doctor

mkdir "%WORK_DIR%" 2>nul
if not exist "%WORK_DIR%" (
    echo [ERROR] Could not create the working folder: %WORK_DIR%
    pause
    exit /b 1
)

echo.
echo Collecting a TAVI diagnostic report. This runs three short test
echo simulations and takes a few minutes. Please leave the window open.
echo.

call :diagnostics > "%LOG%" 2>&1

:: The full log is mostly Visual Studio activation noise that conda prints on every
:: command. The summary pulls out the lines that decide the diagnosis.
> "%SUMMARY%" echo TAVI DOCTOR SUMMARY - %DATE% %TIME%
>> "%SUMMARY%" echo Full log: %LOG%
>> "%SUMMARY%" echo.
findstr /c:"[OK]" /c:"[PROBLEM]" /c:"detect_mcstas" /c:"resolve_mpi_launcher" /c:"which('mpiexec')" /c:"DEFAULT_MPI_COUNT" /c:"mpi_count" /c:"INSTALLER_VERSION" /c:"LAYOUT" /c:"RELOCATED" /c:"ENV_PREFIX" "%LOG%" >> "%SUMMARY%"
>> "%SUMMARY%" echo.
>> "%SUMMARY%" echo (Visual Studio "cannot find the path" lines in the full log are expected
>> "%SUMMARY%" echo  and harmless; McStas compiles with GCC, not Visual Studio.)
type "%SUMMARY%"

echo.
echo ============================================================================
echo Summary  : %SUMMARY%
echo Full log : %LOG%
echo Please send BOTH files back.
echo ============================================================================
:: /quiet suppresses the Notepad window and the prompt, for scripted checks.
if /i "%~1"=="/quiet" exit /b 0
start "" notepad "%SUMMARY%"
pause
exit /b 0

:resolve_only
:: Through "set", never "echo %VAR%": the base may have come from the record.
echo LAYOUT=%LAYOUT%
set TAVI_BASE
endlocal
exit /b 0


:diagnostics
echo ============================================================================
echo TAVI DOCTOR REPORT
echo ============================================================================
echo Generated : %DATE% %TIME%
echo Computer  : %COMPUTERNAME%
echo.

echo ---------------------------------------------------------------- [1] PATHS
echo USERPROFILE       = %USERPROFILE%
echo TEMP              = %TEMP%
echo SystemDrive       = %SystemDrive%
echo LAYOUT            = %LAYOUT%
echo RECORD            = %RECORD%
echo RELOCATED         = %RELOCATED%
echo TAVI_BASE         = %TAVI_BASE%
echo INSTALL_DIR       = %INSTALL_DIR%
echo MICROMAMBA_EXE    = %MICROMAMBA_EXE%
echo MAMBA_ROOT_PREFIX = %MAMBA_ROOT_PREFIX%
echo ENV_PREFIX        = %ENV_PREFIX%
echo.
if not "%ENV_PREFIX%"=="%ENV_PREFIX: =%" echo [PROBLEM] The environment path contains a space. McStas cannot run from it.
if not "%INSTALL_DIR%"=="%INSTALL_DIR: =%" echo [PROBLEM] The install path contains a space. McStas cannot run from it.
if exist "%MICROMAMBA_EXE%" (echo [OK] micromamba.exe found.) else (echo [PROBLEM] micromamba.exe NOT found at the path above.)
if exist "%ENV_PREFIX%\conda-meta\history" (echo [OK] Environment exists.) else (echo [PROBLEM] Environment NOT found at the path above.)
echo.

echo ------------------------------------------------------- [2] INSTALL RECORD
echo Locator at %RECORD%:
if exist "%RECORD%" (
    type "%RECORD%"
) else (
    echo    (not present)
)
echo.
if exist "%INFO_FILE%" (
    type "%INFO_FILE%"
) else (
    echo [PROBLEM] No INSTALL_INFO.txt at %INFO_FILE%
    echo           Either TAVI is not installed there, or an older installer was used.
)
echo.

echo -------------------------------------------------- [3] OTHER TAVI INSTALLS
echo Anything listed here is a leftover that may be launched by mistake:
if "%LAYOUT%"=="2" echo    found (layout 2, from install record): %TAVI_BASE%
if exist "%USERPROFILE%\TAVI\TAVI_PySide6.py" echo    found (layout 1): %USERPROFILE%\TAVI
if exist "%SystemDrive%\TAVI\TAVI_PySide6.py" echo    found (layout 1): %SystemDrive%\TAVI
if exist "%SystemDrive%\TAVI-Data\TAVI\TAVI_PySide6.py" echo    found (layout 1): %SystemDrive%\TAVI-Data\TAVI
if exist "%USERPROFILE%\AppData\Roaming\mamba\envs\%ENV_NAME%\conda-meta\history" echo    found env (layout 1): %USERPROFILE%\AppData\Roaming\mamba\envs\%ENV_NAME%
if exist "%SystemDrive%\TAVI-Data\mamba\envs\%ENV_NAME%\conda-meta\history" echo    found env (layout 1): %SystemDrive%\TAVI-Data\mamba\envs\%ENV_NAME%
echo.

echo ------------------------------------------------------ [4] McSTAS BINARIES
echo Looking for mcrun:
if exist "%ENV_PREFIX%\bin\mcrun.bat" echo    %ENV_PREFIX%\bin\mcrun.bat
if exist "%ENV_PREFIX%\Library\bin\mcrun.bat" echo    %ENV_PREFIX%\Library\bin\mcrun.bat
if exist "%ENV_PREFIX%\Scripts\mcrun.bat" echo    %ENV_PREFIX%\Scripts\mcrun.bat
echo Looking for mpiexec:
if exist "%ENV_PREFIX%\bin\mpiexec.exe" echo    %ENV_PREFIX%\bin\mpiexec.exe
if exist "%ENV_PREFIX%\Library\bin\mpiexec.exe" echo    %ENV_PREFIX%\Library\bin\mpiexec.exe
where mpiexec 2>nul
echo.
echo Contents of mcrun.bat (the unquoted %%BINDIR%% bug lives here):
if exist "%ENV_PREFIX%\bin\mcrun.bat" type "%ENV_PREFIX%\bin\mcrun.bat"
echo.

echo --------------------------------------------------- [5] McSTAS COMPILER CONFIG
echo Per-user config that overrides the environment's own, if present.
echo Micromamba keys this file by the BASENAME of CONDA_DEFAULT_ENV, which is
echo the whole prefix path whenever the prefix's parent is not literally
echo "envs" (verified against micromamba 2.5.0) -- so layout 2 (env at
echo ^<base^>\tavi-env, parent is the base folder, not "envs") keys under
echo "_tavi-env", while layout 1 (env at .../envs/tavi) keys under "_tavi".
echo Both candidates are reported so this stays useful against either layout:
set "MCSTAS_CFG_L1=%USERPROFILE%\AppData\mcstas\%MCSTAS_VERSION%_%ENV_NAME%\mccode_config.json"
set "MCSTAS_CFG_L2=%USERPROFILE%\AppData\mcstas\%MCSTAS_VERSION%_tavi-env\mccode_config.json"
if exist "%MCSTAS_CFG_L1%" (
    echo [PROBLEM] (layout 1) %MCSTAS_CFG_L1% exists
    echo           and takes precedence over the compiler the installer configured.
) else (
    echo [OK] (layout 1) No overriding per-user McStas config at %MCSTAS_CFG_L1%
)
if exist "%MCSTAS_CFG_L2%" (
    echo [PROBLEM] (layout 2) %MCSTAS_CFG_L2% exists
    echo           and takes precedence over the compiler the installer configured.
) else (
    echo [OK] (layout 2) No overriding per-user McStas config.
)
echo.
echo Environment's own compiler settings:
> "%WORK_DIR%\show_config.py" echo import json, sys
>> "%WORK_DIR%\show_config.py" echo d = json.load(open(sys.argv[1], encoding="utf-8"))
>> "%WORK_DIR%\show_config.py" echo c = d.get("compilation", {})
>> "%WORK_DIR%\show_config.py" echo for k in ("CC", "MPICC", "MPIRUN", "MPIFLAGS", "CFLAGS", "NCRYSTALFLAGS"):
>> "%WORK_DIR%\show_config.py" echo     print("   ", k, "=", c.get(k))
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" python "%WORK_DIR%\show_config.py" "%ENV_PREFIX%\share\mcstas\tools\Python\mccodelib\mccode_config.json"
echo.

echo ------------------------------------------------ [6] WHAT TAVI ITSELF FINDS
:: Mirror run-tavi.bat exactly: it exports MCSTAS before starting the GUI, and
:: that variable is the first thing tavi.mcstas_config trusts. Probing without it
:: would report a resolution the running program never performs.
set "MCSTAS_RESOURCES=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS_RESOURCES%" set "MCSTAS_RESOURCES=%ENV_PREFIX%\Library\share\mcstas\resources"
set "MCSTAS=%MCSTAS_RESOURCES%"
set "MCSTAS_COMPONENT_PATH=%MCSTAS%"
echo MCSTAS = %MCSTAS%
> "%WORK_DIR%\probe.py" echo import shutil, sys
>> "%WORK_DIR%\probe.py" echo sys.path.insert(0, sys.argv[1])
>> "%WORK_DIR%\probe.py" echo import tavi.mcstas_config as m
>> "%WORK_DIR%\probe.py" echo print("   detect_mcstas()          =", m.detect_mcstas())
>> "%WORK_DIR%\probe.py" echo print("   resolve_mpi_launcher_argv=", m.resolve_mpi_launcher_argv())
>> "%WORK_DIR%\probe.py" echo print("   shutil.which('mpiexec')  =", shutil.which("mpiexec"))
>> "%WORK_DIR%\probe.py" echo print("   mcstasscript config      =", m._get_mcstasscript_config_path())
>> "%WORK_DIR%\probe.py" echo from instruments.contract import DEFAULT_MPI_COUNT
>> "%WORK_DIR%\probe.py" echo print("   DEFAULT_MPI_COUNT        =", DEFAULT_MPI_COUNT)
:: What TAVI actually runs per point (1.3.2+): the Config-menu setting, read
:: from this installation's config\settings.json, as the program reads it.
>> "%WORK_DIR%\probe.py" echo try:
>> "%WORK_DIR%\probe.py" echo     from tavi.settings import load_mpi_count
>> "%WORK_DIR%\probe.py" echo except ImportError:
>> "%WORK_DIR%\probe.py" echo     print("   configured mpi_count     = none: TAVI 1.3.0 and earlier run a fixed 30 ranks")
>> "%WORK_DIR%\probe.py" echo else:
>> "%WORK_DIR%\probe.py" echo     print("   configured mpi_count     =", load_mpi_count())
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" python "%WORK_DIR%\probe.py" "%INSTALL_DIR%"
echo.

echo ---------------------------------------------------- [7] TEST SIMULATIONS
echo Resources: %MCSTAS_RESOURCES%
copy /Y "%MCSTAS_RESOURCES%\examples\PSI\PSI_DMC\PSI_DMC.instr" "%WORK_DIR%\" >nul
if errorlevel 1 (
    echo [PROBLEM] Could not copy the PSI_DMC example instrument. Stopping here.
    goto :eof
)
cd /d "%WORK_DIR%"

echo.
echo --- 7a: serial (compile and run) ---
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" mcrun -c PSI_DMC.instr -n 1000 -d serial lambda=2.5666
if errorlevel 1 (echo [PROBLEM] serial run FAILED) else (echo [OK] serial run passed)

echo.
echo --- 7b: MPI with 2 ranks (what the installer checks) ---
:: -c is mandatory on every MPI run. Without it mcrun reuses the serial binary
:: from 7a, every rank then believes it is the master, and the run dies in a
:: storm of "unable to create directory (mcuse_dir)" -- a fault in the test, not
:: in the machine. Found 2026-09-17 by shipping exactly that mistake.
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" mcrun -c --mpi=2 PSI_DMC.instr -n 1000 -d mpi2 lambda=2.5666
if errorlevel 1 (echo [PROBLEM] 2-rank MPI run FAILED) else (echo [OK] 2-rank MPI run passed)

echo.
:: 30 ranks is a stress test: the fixed count of TAVI 1.3.0 and earlier. 1.3.2+
:: runs the configured count printed in [6], 4 unless changed in the Config menu.
echo --- 7c: MPI with 30 ranks (stress test: the fixed count of TAVI 1.3.0 and earlier) ---
echo     TAVI 1.3.2 and later run the configured count shown in [6] instead.
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" mcrun -c --mpi=30 PSI_DMC.instr -n 1000 -d mpi30 lambda=2.5666
if errorlevel 1 (echo [PROBLEM] 30-rank MPI run FAILED -- fatal for TAVI 1.3.0 and earlier, 1.3.2+ needs only the configured count) else (echo [OK] 30-rank MPI run passed)

echo.
echo --- 7d: direct launch at 30 ranks, the way TAVI runs every point after the first ---
:: Mirrors _run_point_direct in instruments/tas_runtime.py: the MPI launcher is
:: invoked on the compiled binary directly, bypassing mcrun entirely.
set "MPIEXEC=%ENV_PREFIX%\Library\bin\mpiexec.exe"
if not exist "%MPIEXEC%" set "MPIEXEC=mpiexec"
echo Launcher: %MPIEXEC%
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" "%MPIEXEC%" -np 30 PSI_DMC.exe --ncount=1000 --dir=direct30 lambda=2.5666
if errorlevel 1 (echo [PROBLEM] direct 30-rank launch FAILED -- TAVI's own run path, at the count of 1.3.0 and earlier) else (echo [OK] direct 30-rank launch passed)

echo.
echo Output folders created:
dir /b /ad "%WORK_DIR%" 2>nul
echo.
echo ============================================================================
echo END OF REPORT
echo ============================================================================
goto :eof

:: ---------------------------------------------------------------------------
:: Keep :validate_base byte-identical in every file that carries it; the
:: list is VALIDATE_BASE_COPIES in tests\test_installer_launchers.py, which
:: asserts that they match. It is duplicated rather than shared because each
:: of those files has to work alone:
:: the Doctor and the support recorder are handed to a user on their own.
::
:: The character whitelist is fed from "set VBPATH" through a pipe, never from
:: "echo %VBPATH%". A value containing & or ^ splits the command line the moment
:: it is expanded there, so the test meant to catch those characters is the one
:: they break: C:\TAVI&calc was measured passing an echo-based check. "set NAME"
:: writes the value to stdout without it ever being parsed as a command, so one
:: whitelist can reject every character at once, and nothing after it has to
:: expand an unvetted value.
:: Ceiling: this guards against a mistyped or stale path, not against a hostile
:: local user; a single-user install has no trust boundary here.
:: ---------------------------------------------------------------------------
:validate_base
set "VBPATH=%~1"

:validate_base_var
:: Entry point for a caller that has already put the raw value in VBPATH -
:: `set /p` does that without parsing it. Everything below is ordered so that
:: the whitelist, which reads the value through a pipe rather than expanding
:: it, runs before any line expands %VBPATH% at all.
set "VB_REASON="
if not defined VBPATH set "VB_REASON=the path is empty"
if defined VB_REASON goto :eof
:: Every allowed character is listed rather than given as a range: findstr
:: resolves a range like A-Z through the machine's collation order, which
:: places accented Latin letters inside it. C:\TAVE-with-an-acute was
:: measured passing the range form, and McStas cannot compile from it.
:: A double quote is not in this set either, which is what stops a pasted
:: "C:\..." or a crafted value from ending a quoted region further down.
set VBPATH| findstr /r /c:"[^ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:=\\-]" >nul
if not errorlevel 1 set "VB_REASON=it contains a character McStas cannot handle - use only letters, digits, dot, dash and underscore, with no quotes"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"=="\" set "VBPATH=%VBPATH:~0,-1%"
if not defined VBPATH set "VB_REASON=the path is empty"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"=="." set "VB_REASON=it ends with a dot"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"==" " set "VB_REASON=it ends with a space"
if defined VB_REASON goto :eof
if "%VBPATH:~0,2%"=="\\" set "VB_REASON=network and device paths are not supported"
if defined VB_REASON goto :eof
if not "%VBPATH%"=="%VBPATH: =%" set "VB_REASON=it contains a space, and McStas cannot compile from a path with a space in it"
if defined VB_REASON goto :eof
if not "%VBPATH%"=="%VBPATH:..=%" set "VB_REASON=it contains .."
if defined VB_REASON goto :eof
if not "%VBPATH:~1,1%"==":" set "VB_REASON=it must start with a drive letter, like C:\TAVI"
if defined VB_REASON goto :eof
if not "%VBPATH:~2,1%"=="\" set "VB_REASON=it must start with a drive letter, like C:\TAVI"
if defined VB_REASON goto :eof
if "%VBPATH:~3%"=="" set "VB_REASON=a whole drive cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%USERPROFILE%" set "VB_REASON=your user folder itself cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%SystemRoot%" set "VB_REASON=the Windows folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%LOCALAPPDATA%" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%APPDATA%" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%ProgramFiles%" set "VB_REASON=Program Files cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%SystemDrive%\Users" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
:: Walk every existing component, not just the last one. A junction anywhere
:: above the base makes the real target different from the path on screen, and
:: this routine authorises a recursive delete. Checking only the leaf let
:: C:\SomeJunction\TAVI through, and a base that did not exist yet was not
:: checked at all.
set "VB_WALK=%VBPATH%"

:vb_walk
if not defined VB_WALK goto :eof
if "%VB_WALK:~3%"=="" goto :eof
for %%I in ("%VB_WALK%") do set "VB_LEAF=%%~nxI"
for %%I in ("%VB_WALK%") do set "VB_PARENT=%%~dpI"
if not exist "%VB_WALK%\" goto vb_walk_up
dir /a:l /b "%VB_PARENT%" 2>nul | findstr /i /x /c:"%VB_LEAF%" >nul
if not errorlevel 1 set "VB_REASON=%VB_WALK% is a junction or a symbolic link, which may point somewhere else entirely"
if defined VB_REASON goto :eof

:vb_walk_up
if "%VB_PARENT:~-1%"=="\" set "VB_PARENT=%VB_PARENT:~0,-1%"
if /i "%VB_PARENT%"=="%VB_WALK%" goto :eof
set "VB_WALK=%VB_PARENT%"
goto vb_walk
