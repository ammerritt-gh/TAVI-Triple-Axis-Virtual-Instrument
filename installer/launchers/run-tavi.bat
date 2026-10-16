@echo off
setlocal DisableDelayedExpansion

:: TAVI launcher (layout 2).
::
:: The installer copies this file into the installation's base folder. Every
:: path is derived from this file's own location, so the installation carries
:: no absolute paths written by a generator, and no environment can be selected
:: by name. Selecting by name is the defect this replaces: "micromamba run -n
:: tavi" resolves against whatever root the caller happens to have inherited,
:: so a relocated install could load its source from one place and its Python
:: and mcrun from a stale environment somewhere else.
::
:: This file lives in the base folder, NOT in app\, because app\ is a git
:: checkout that update-tavi.bat re-checks-out; cmd reads a .bat line by line
:: as it runs, so a launcher inside the checkout could be rewritten mid-run.
::
:: 1.4: TAVI's whole console output goes to a launch log,
:: %LOCALAPPDATA%\TAVI\logs\launch-<yyyyMMdd-HHmmss>.log (%TEMP% when that
:: folder cannot be written), and the ten newest are kept. When no log can be
:: opened TAVI runs with its output in this window, as before. Arguments given
:: to this file are passed to TAVI_PySide6.py unchanged; the launcher menu
:: passes none.

set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MAMBA_ROOT=%TAVI_BASE%\mamba"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"

if not exist "%MICROMAMBA_EXE%" goto no_micromamba
if not exist "%ENV_PREFIX%\python.exe" goto no_env
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto no_source

set "MCSTAS=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS%" set "MCSTAS=%ENV_PREFIX%\Library\share\mcstas\resources"
if not exist "%MCSTAS%" goto no_mcstas
set "MCSTAS_COMPONENT_PATH=%MCSTAS%"

:: McStas reads these five above its own configuration, so one left over in the
:: user's environment would silently replace the compiler the installer gated
:: on at install time. Clear them for this process only.
set "MCSTAS_OVERRIDE="
set "MCSTAS_CFLAGS_OVERRIDE="
set "MCSTAS_CC_OVERRIDE="
set "MCSTAS_MPICC_OVERRIDE="
set "MCSTAS_MPIRUN_OVERRIDE="

:: -r and -p are both passed on every micromamba call: a command-line value
:: outranks MAMBA_ROOT_PREFIX, CONDA_PREFIX and every .mambarc, so an inherited
:: conda or mamba setting cannot reach either choice. The variable below is
:: belt, not braces.
set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"

:: Python writes each line into the log as it prints it, so a crash keeps
:: everything printed before it.
set "PYTHONUNBUFFERED=1"
:: Output written to a file is encoded with the machine's ANSI code page unless
:: told otherwise, and one character outside it (an Angstrom sign, a Greek
:: letter) would stop TAVI with a UnicodeEncodeError. UTF-8 encodes anything.
set "PYTHONIOENCODING=utf-8"

cd /d "%INSTALL_DIR%"
if errorlevel 1 goto no_source

call :open_log
if not defined LAUNCH_LOG goto run_live

echo TAVI is running. Leave this window open while you use TAVI.
echo TAVI's messages are being written to:
echo     %LAUNCH_LOG%
>> "%LAUNCH_LOG%" echo [TAVI] Launched %STAMP% from %TAVI_BASE%
>> "%LAUNCH_LOG%" echo [TAVI] Environment: %ENV_PREFIX%
>> "%LAUNCH_LOG%" echo [TAVI] MCSTAS=%MCSTAS%
>> "%LAUNCH_LOG%" echo.
>> "%LAUNCH_LOG%" 2>&1 "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python TAVI_PySide6.py %*
set "RC=%ERRORLEVEL%"
>> "%LAUNCH_LOG%" echo.
>> "%LAUNCH_LOG%" echo [TAVI] Exit code: %RC%
if not "%RC%"=="0" goto run_failed
endlocal
exit /b 0

:run_live
echo [INFO] TAVI's messages could not be saved to a log file, so they appear in
echo        this window instead.
echo [TAVI] Environment: %ENV_PREFIX%
echo [TAVI] MCSTAS=%MCSTAS%
echo.
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python TAVI_PySide6.py %*
if errorlevel 1 goto run_failed_live
endlocal
exit /b 0

:run_failed
echo.
echo ============================================================================
echo  TAVI STOPPED WITH AN ERROR
echo ============================================================================
echo The last lines TAVI wrote before it stopped:
echo.
call :show_tail
echo.
echo All of TAVI's messages are saved in:
echo     %LAUNCH_LOG%
echo To get help, choose "Collect diagnostics for support" in the TAVI Launcher
echo and send the file it makes.
echo.
choice /c C /n /m "Press C to continue."
endlocal
exit /b 1

:run_failed_live
echo.
echo ============================================================================
echo  TAVI STOPPED WITH AN ERROR
echo ============================================================================
echo The lines above are the reason.
echo.
choice /c C /n /m "Press C to continue."
endlocal
exit /b 1

:no_micromamba
echo [ERROR] micromamba was not found at:
echo         %MICROMAMBA_EXE%
goto broken

:no_env
echo [ERROR] The TAVI environment was not found at:
echo         %ENV_PREFIX%
goto broken

:no_source
echo [ERROR] TAVI_PySide6.py was not found in:
echo         %INSTALL_DIR%
goto broken

:no_mcstas
echo [ERROR] The McStas resource directory was not found under:
echo         %ENV_PREFIX%
goto broken

:broken
echo.
echo This installation is incomplete. Run the TAVI installer again; it
echo rebuilds the environment and reinstalls the program.
echo Base folder: %TAVI_BASE%
echo.
choice /c C /n /m "Press C to continue."
endlocal
exit /b 1

:: ---------------------------------------------------------------------------
:: The launch log. It must never be what stops TAVI: each folder that cannot
:: be written falls through to the next, and with none left TAVI runs live.
:: ---------------------------------------------------------------------------
:open_log
set "LAUNCH_LOG="
call :stamp
set "LOG_DIR="
if defined LOCALAPPDATA set "LOG_DIR=%LOCALAPPDATA%\TAVI\logs"
if defined LOG_DIR if not exist "%LOG_DIR%\" mkdir "%LOG_DIR%" >nul 2>nul
if defined LOG_DIR call :try_log
if defined LAUNCH_LOG goto prune_logs
set "LOG_DIR=%TEMP%"
if defined LOG_DIR call :try_log
goto :eof

:prune_logs
:: Ten newest by date, this launch's included, and only in TAVI's own logs
:: folder: in %TEMP% a launch-*.log may be another program's. A log another
:: TAVI still has open cannot be deleted and is simply left.
for /f "skip=10 delims=" %%F in ('dir /b /a-d /o-d "%LOG_DIR%\launch-*.log" 2^>nul') do del /f /q "%LOG_DIR%\%%F" >nul 2>nul
goto :eof

:try_log
if not exist "%LOG_DIR%\" goto :eof
set "TRY_LOG=%LOG_DIR%\launch-%STAMP%.log"
:: Two launches in the same second share a stamp: never truncate the other's log.
if exist "%TRY_LOG%" set "TRY_LOG=%LOG_DIR%\launch-%STAMP%-%RANDOM%.log"
copy /y nul "%TRY_LOG%" >nul 2>nul
if exist "%TRY_LOG%" set "LAUNCH_LOG=%TRY_LOG%"
goto :eof

:: yyyyMMdd-HHmmss from PowerShell, which formats the clock the same way on
:: every locale; %DATE% and %TIME% change layout with the region setting and
:: wmic is gone from current Windows 11. "<nul" keeps PowerShell off this
:: console's input. Anything not shaped like a stamp, PowerShell missing or
:: locked down included, gives a %RANDOM% name instead.
:stamp
set "STAMP="
for /f "delims=" %%S in ('powershell -NoProfile -NonInteractive -Command "Get-Date -Format yyyyMMdd-HHmmss" ^<nul 2^>nul') do set "STAMP=%%S"
if not defined STAMP set "STAMP=none"
set STAMP| findstr /r /x /c:"STAMP=[0123456789][0123456789][0123456789][0123456789][0123456789][0123456789][0123456789][0123456789]-[0123456789][0123456789][0123456789][0123456789][0123456789][0123456789]" >nul
if errorlevel 1 set "STAMP=%RANDOM%-%RANDOM%"
goto :eof

:: The last 30 lines of the launch log, with cmd's own tools only: some managed
:: laptops lock PowerShell down, and this runs when something is already
:: wrong. System32 is named because Git's find.exe can come first on PATH;
:: "| findstr" stops more from pausing at a full screen.
:show_tail
set "LINES=0"
for /f %%N in ('type "%LAUNCH_LOG%" ^| "%SystemRoot%\System32\find.exe" /c /v ""') do set "LINES=%%N"
set /a SKIP=LINES-30
if %SKIP% lss 0 set "SKIP=0"
"%SystemRoot%\System32\more.com" +%SKIP% "%LAUNCH_LOG%" | findstr "^"
goto :eof
