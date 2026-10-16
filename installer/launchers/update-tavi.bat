@echo off
setlocal DisableDelayedExpansion

:: TAVI repair script (layout 2).
::
:: Re-fetches and re-checks-out the release tag this installation is pinned to,
:: then confirms the GUI toolkit and McStasScript still load. It never changes
:: which release is installed and never installs or upgrades packages: to move
:: to a newer TAVI, download that release's installer.
::
:: Lives in the base folder, not in app\, so the git checkout below cannot
:: rewrite this file while cmd is reading it.
::
:: Every micromamba call passes -r and -p. See run-tavi.bat for why.
::
:: 1.4: each repair writes %LOCALAPPDATA%\TAVI\logs\repair-<yyyyMMdd-HHmmss>.log
:: (%TEMP% when that folder cannot be written) holding the steps' output, and
:: ends on REPAIR SUCCEEDED or REPAIR FAILED with the log's path and, on a
:: failed step, its last 30 lines; the window waits for C. With no log at all
:: the steps print in this window instead.

set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MAMBA_ROOT=%TAVI_BASE%\mamba"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"

echo ============================================================================
echo                       TAVI Repair
echo ============================================================================
echo.

call :open_log
>> "%LOG%" echo [TAVI] Repair started %STAMP% in %TAVI_BASE%

set "FAILED_STEP=Checking the installation"
set "SHOW_TAIL="
if not exist "%MICROMAMBA_EXE%" goto no_micromamba
if not exist "%ENV_PREFIX%\python.exe" goto no_env
if not exist "%INSTALL_DIR%\.git" goto no_repo

set "TAVI_VERSION="
for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="TAVI_VERSION" set "TAVI_VERSION=%%B"
if not defined TAVI_VERSION goto no_version
:: Keep this check identical to the ones in TAVI-Repair-Launchers.bat and
:: TAVI-Launcher.bat.
:: TAVI_VERSION comes from a text file and becomes a git argument, so it must
:: be a release tag (v<digits>.<digits>.<digits>) or main before any line
:: expands it. "set NAME|" hands the value to findstr without cmd parsing it,
:: where "echo %NAME%" would run whatever follows an & in it. Digits are
:: listed, not ranged: findstr resolves a range through the machine collation.
set TAVI_VERSION| findstr /r /x /c:"TAVI_VERSION=v[0123456789][0123456789]*\.[0123456789][0123456789]*\.[0123456789][0123456789]*" /c:"TAVI_VERSION=main" >nul
if errorlevel 1 goto bad_version

set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"

echo Installation : %TAVI_BASE%
echo Environment  : %ENV_PREFIX%
echo Pinned to    : %TAVI_VERSION%
echo.
echo This repairs and re-checks the release above. It does not upgrade TAVI and
echo does not change any package.
echo.
>> "%LOG%" echo [TAVI] Environment: %ENV_PREFIX%
>> "%LOG%" echo [TAVI] Pinned to: %TAVI_VERSION%

cd /d "%INSTALL_DIR%"
if errorlevel 1 goto no_repo

:: From here each step runs a command, and its output is the reason it failed.
set "SHOW_TAIL=yes"
set "FAILED_STEP=Fetching the release from GitHub"
echo [INFO] Fetching tags from GitHub...
>> "%LOG%" echo.
>> "%LOG%" echo [Step] %FAILED_STEP%
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git fetch --tags origin
if errorlevel 1 goto fetch_failed

set "FAILED_STEP=Restoring the program files to %TAVI_VERSION%"
echo [INFO] Checking out %TAVI_VERSION%...
>> "%LOG%" echo.
>> "%LOG%" echo [Step] %FAILED_STEP%
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git checkout "%TAVI_VERSION%"
if errorlevel 1 goto checkout_failed

set "FAILED_STEP=Checking that the GUI toolkit and McStasScript load"
echo [INFO] Checking that the GUI toolkit and McStasScript load...
>> "%LOG%" echo.
>> "%LOG%" echo [Step] %FAILED_STEP%
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
if errorlevel 1 goto env_failed

>> "%LOG%" echo.
>> "%LOG%" echo [TAVI] REPAIR SUCCEEDED
echo.
echo ============================================================================
echo  REPAIR SUCCEEDED
echo ============================================================================
echo The installed program is still pinned to %TAVI_VERSION%.
echo To move to a newer TAVI release, download that release's installer.
if defined LOGFILE echo The repair log is saved in:
if defined LOGFILE echo     %LOGFILE%
echo.
choice /C C /N /M "Press C to continue."
endlocal
exit /b 0

:fetch_failed
set "HINT1=TAVI could not reach GitHub. Check your internet connection, then"
set "HINT2=choose Repair TAVI again."
goto fail

:checkout_failed
set "HINT1=The release may be missing, or files in the program folder may have"
set "HINT2=been changed by hand. Run the TAVI installer again."
goto fail

:env_failed
set "HINT1=The TAVI environment is broken. Run the TAVI installer again; it"
set "HINT2=rebuilds the environment from scratch."
goto fail

:no_micromamba
set "HINT1=micromamba was not found at: %MICROMAMBA_EXE%"
set "HINT2=Run the TAVI installer again."
goto fail

:no_env
set "HINT1=The TAVI environment was not found at: %ENV_PREFIX%"
set "HINT2=Run the TAVI installer again."
goto fail

:no_repo
set "HINT1=%INSTALL_DIR% is not a Git checkout, so it cannot be repaired."
set "HINT2=Run the TAVI installer again."
goto fail

:no_version
set "HINT1=Could not read TAVI_VERSION from %TAVI_BASE%\INSTALL_INFO.txt."
set "HINT2=Run the TAVI installer again."
goto fail

:bad_version
:: Never print the value itself: it failed the check above.
set "HINT1=The TAVI_VERSION in %TAVI_BASE%\INSTALL_INFO.txt is not a release"
set "HINT2=tag such as vX.Y.Z, or main, so it is not used. Run the TAVI installer again."
goto fail

:: One ending for every failure: the failed step's last lines when it ran a
:: command, then the headline, the step, what to do and where the log is.
:fail
if not defined SHOW_TAIL goto fail_screen
if not defined LOGFILE goto fail_screen
echo.
echo The last lines of the repair log:
echo.
call :show_tail

:fail_screen
>> "%LOG%" echo.
>> "%LOG%" echo [TAVI] REPAIR FAILED at: %FAILED_STEP%
>> "%LOG%" echo [TAVI] %HINT1%
>> "%LOG%" echo [TAVI] %HINT2%
echo.
echo ============================================================================
echo  REPAIR FAILED
echo ============================================================================
echo Failed step: %FAILED_STEP%
echo [ERROR] %HINT1%
echo         %HINT2%
if defined LOGFILE echo The repair log is saved in:
if defined LOGFILE echo     %LOGFILE%
if not defined LOGFILE if defined SHOW_TAIL echo The lines above the headline are the reason.
echo To get help, choose "Collect diagnostics for support" in the TAVI Launcher
echo and send the file it makes.
echo.
choice /C C /N /M "Press C to continue."
endlocal
exit /b 1

:: A step's output goes to the log, or to this window when there is no log.
:: Its exit code is what this returns.
:run_logged
if not defined LOGFILE goto run_live
>> "%LOG%" 2>&1 %*
goto :eof

:run_live
%*
goto :eof

:: ---------------------------------------------------------------------------
:: The repair log. It must never be what stops a repair: each folder that
:: cannot be written falls through to the next, and with none left LOG is nul
:: and the steps print in this window.
:: ---------------------------------------------------------------------------
:open_log
set "LOGFILE="
call :stamp
set "LOG_DIR="
if defined LOCALAPPDATA set "LOG_DIR=%LOCALAPPDATA%\TAVI\logs"
if defined LOG_DIR if not exist "%LOG_DIR%\" mkdir "%LOG_DIR%" >nul 2>nul
if defined LOG_DIR call :try_log
if defined LOGFILE goto log_opened
set "LOG_DIR=%TEMP%"
if defined LOG_DIR call :try_log

:log_opened
set "LOG=nul"
if defined LOGFILE set "LOG=%LOGFILE%"
if not defined LOGFILE echo [INFO] This repair could not be saved to a log file, so its messages appear here.
goto :eof

:try_log
if not exist "%LOG_DIR%\" goto :eof
set "TRY_LOG=%LOG_DIR%\repair-%STAMP%.log"
:: Two repairs in the same second share a stamp: never truncate the other's log.
if exist "%TRY_LOG%" set "TRY_LOG=%LOG_DIR%\repair-%STAMP%-%RANDOM%.log"
copy /y nul "%TRY_LOG%" >nul 2>nul
if exist "%TRY_LOG%" set "LOGFILE=%TRY_LOG%"
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

:: The last 30 lines of the repair log, with cmd's own tools only: some managed
:: laptops lock PowerShell down, and this runs when something is already
:: wrong. System32 is named because Git's find.exe can come first on PATH;
:: "| findstr" stops more from pausing at a full screen.
:show_tail
set "LINES=0"
for /f %%N in ('type "%LOGFILE%" ^| "%SystemRoot%\System32\find.exe" /c /v ""') do set "LINES=%%N"
set /a SKIP=LINES-30
if %SKIP% lss 0 set "SKIP=0"
"%SystemRoot%\System32\more.com" +%SKIP% "%LOGFILE%" | findstr "^"
goto :eof
