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

:: layout 2 (1.3.1+): the base folder is user-chosen at install time and
:: cannot be computed by rule, so the installer leaves a locator behind at
:: %LOCALAPPDATA%\TAVI\install-record.txt. Same resolution order as
:: tools/support/Record-TAVI.bat and installer/launchers/uninstall-tavi.bat --
:: keep these in step.
set "LAYOUT=1"
set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
set "REC_BASE="
if exist "%RECORD%" for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "REC_BASE=%%B"
if not defined REC_BASE goto default_base
if not exist "%REC_BASE%\.tavi-install-root" goto default_base

set "LAYOUT=2"
set "TAVI_BASE=%REC_BASE%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MICROMAMBA_DIR=%TAVI_BASE%\micromamba"
set "MAMBA_ROOT_PREFIX=%TAVI_BASE%\mamba"
set "RELOCATED=n/a (layout 2: user-chosen base)"
echo [INFO] Installation found from the install record: %TAVI_BASE%
goto paths_ready

:default_base
:: Pre-1.3.1 layout: same space-safe base resolution as that installer
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
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "WORK_DIR=%TAVI_BASE%\tavi_doctor"
set "LOG=%WORK_DIR%\TAVI-doctor-report.txt"
set "SUMMARY=%WORK_DIR%\TAVI-doctor-summary.txt"

title TAVI Doctor

if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%"
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
findstr /c:"[OK]" /c:"[PROBLEM]" /c:"detect_mcstas" /c:"resolve_mpi_launcher" /c:"which('mpiexec')" /c:"DEFAULT_MPI_COUNT" /c:"INSTALLER_VERSION" /c:"LAYOUT" /c:"RELOCATED" /c:"ENV_PREFIX" "%LOG%" >> "%SUMMARY%"
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
if exist "%INSTALL_DIR%\INSTALL_INFO.txt" (
    type "%INSTALL_DIR%\INSTALL_INFO.txt"
) else (
    echo [PROBLEM] No INSTALL_INFO.txt at %INSTALL_DIR%
    echo           Either TAVI is not installed there, or an older installer was used.
)
echo.

echo -------------------------------------------------- [3] OTHER TAVI INSTALLS
echo Anything listed here is a leftover that may be launched by mistake:
if exist "%REC_BASE%\.tavi-install-root" echo    found (layout 2, from install record): %REC_BASE%
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
echo --- 7c: MPI with 30 ranks (what TAVI actually uses for every scan point) ---
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" mcrun -c --mpi=30 PSI_DMC.instr -n 1000 -d mpi30 lambda=2.5666
if errorlevel 1 (echo [PROBLEM] 30-rank MPI run FAILED -- this is the rank count TAVI uses) else (echo [OK] 30-rank MPI run passed)

echo.
echo --- 7d: direct launch, exactly as TAVI runs every point after the first ---
:: Mirrors _run_point_direct in instruments/tas_runtime.py: the MPI launcher is
:: invoked on the compiled binary directly, bypassing mcrun entirely.
set "MPIEXEC=%ENV_PREFIX%\Library\bin\mpiexec.exe"
if not exist "%MPIEXEC%" set "MPIEXEC=mpiexec"
echo Launcher: %MPIEXEC%
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" "%MPIEXEC%" -np 30 PSI_DMC.exe --ncount=1000 --dir=direct30 lambda=2.5666
if errorlevel 1 (echo [PROBLEM] direct 30-rank launch FAILED -- this is TAVI's own run path) else (echo [OK] direct 30-rank launch passed)

echo.
echo Output folders created:
dir /b /ad "%WORK_DIR%" 2>nul
echo.
echo ============================================================================
echo END OF REPORT
echo ============================================================================
goto :eof
