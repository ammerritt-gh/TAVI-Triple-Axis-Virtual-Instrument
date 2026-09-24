@echo off
setlocal DisableDelayedExpansion
title TAVI - record the Monte Carlo failure
set "SUPPORT_DIR=%~dp0"

:: layout 2 (1.3.1+): the base folder is user-chosen at install time and
:: cannot be computed by rule, so the installer leaves a locator behind.
:: Same resolution order as installer/TAVI-Doctor.bat and
:: installer/launchers/uninstall-tavi.bat -- keep these in step.
set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
set "REC_BASE="
if exist "%RECORD%" for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "REC_BASE=%%B"
if not defined REC_BASE goto default_base
if not exist "%REC_BASE%\.tavi-install-root" goto default_base
set "TAVI_BASE=%REC_BASE%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%TAVI_BASE%\mamba"
echo [INFO] Installation found from the install record: %TAVI_BASE%
goto paths_ready

:default_base
:: Pre-1.3.1 layout: fixed locations under the profile (or the space-safe
:: relocation when the profile path itself contains a space).
set "TAVI_BASE=%USERPROFILE%"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_EXE=%USERPROFILE%\AppData\Local\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
if not "%USERPROFILE%"=="%USERPROFILE: =%" goto relocate_default
goto default_ready

:relocate_default
set "TAVI_BASE=%SystemDrive%\TAVI-Data"
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_EXE=%SystemDrive%\TAVI-Data\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"

:default_ready
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\tavi"
echo [INFO] Installation found at the default location: %INSTALL_DIR%

:paths_ready
set "REPORTS=%SUPPORT_DIR%Reports"
if not exist "%REPORTS%" mkdir "%REPORTS%"
set "BOOTSTRAP=%REPORTS%\STARTUP-%RANDOM%-%RANDOM%.txt"
> "%BOOTSTRAP%" echo TAVI support startup - %DATE% %TIME%
if not exist "%BOOTSTRAP%" (
    echo Cannot write reports beside the recorder. Extract it to your Desktop and run it there.
    pause
    exit /b 1
)
>> "%BOOTSTRAP%" echo TAVI_BASE=%TAVI_BASE%
>> "%BOOTSTRAP%" echo INSTALL_DIR=%INSTALL_DIR%
>> "%BOOTSTRAP%" echo ENV_PREFIX=%ENV_PREFIX%
>> "%BOOTSTRAP%" echo MICROMAMBA_EXE=%MICROMAMBA_EXE%
>> "%BOOTSTRAP%" echo MAMBA_ROOT_PREFIX=%MAMBA_ROOT_PREFIX%
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto missing
if not exist "%MICROMAMBA_EXE%" goto missing
if not exist "%SUPPORT_DIR%tavi_record.py" goto missing
set "MCSTAS=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS%" set "MCSTAS=%ENV_PREFIX%\Library\share\mcstas\resources"
set "MCSTAS_COMPONENT_PATH=%MCSTAS%"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
:: Increase only if a known slow first compile needs more than 30 minutes.
set "TAVI_RECORD_TIMEOUT_SECONDS=1800"
cd /d "%INSTALL_DIR%"
echo Close any existing TAVI window first.
echo This opens your installed TAVI and records one failed Monte Carlo run.
echo After the failure, close TAVI to finish the report.
echo Please keep this window open. If TAVI hangs, press Ctrl+C here.
echo The recording stops automatically after 30 minutes.
echo.
echo Reports will be saved in: %REPORTS%
echo.
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" python -u "%SUPPORT_DIR%tavi_record.py" "%INSTALL_DIR%" "%REPORTS%" >> "%BOOTSTRAP%" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%BOOTSTRAP%"
echo.
echo Copy the whole Reports folder back to the USB drive, even if TAVI did not open.
echo Reports: %REPORTS%
if not "%RESULT%"=="0" echo The recording launcher failed. The startup log is still useful.
pause
exit /b %RESULT%
:missing
>> "%BOOTSTRAP%" echo ERROR: Required TAVI installation, micromamba, or recorder file missing.
type "%BOOTSTRAP%"
echo Copy the Reports folder back, even though TAVI did not open.
pause
exit /b 1
