@echo off
setlocal DisableDelayedExpansion
title TAVI - record the Monte Carlo failure
set "SUPPORT_DIR=%~dp0"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_EXE=%USERPROFILE%\AppData\Local\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
if "%USERPROFILE%"=="%USERPROFILE: =%" goto paths_ready
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_EXE=%SystemDrive%\TAVI-Data\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"
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
>> "%BOOTSTRAP%" echo INSTALL_DIR=%INSTALL_DIR%
>> "%BOOTSTRAP%" echo MICROMAMBA_EXE=%MICROMAMBA_EXE%
>> "%BOOTSTRAP%" echo MAMBA_ROOT_PREFIX=%MAMBA_ROOT_PREFIX%
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto missing
if not exist "%MICROMAMBA_EXE%" goto missing
if not exist "%SUPPORT_DIR%tavi_record.py" goto missing
set "MCSTAS=%MAMBA_ROOT_PREFIX%\envs\tavi\share\mcstas\resources"
if not exist "%MCSTAS%" set "MCSTAS=%MAMBA_ROOT_PREFIX%\envs\tavi\Library\share\mcstas\resources"
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
"%MICROMAMBA_EXE%" run -p "%MAMBA_ROOT_PREFIX%\envs\tavi" python -u "%SUPPORT_DIR%tavi_record.py" "%INSTALL_DIR%" "%REPORTS%" >> "%BOOTSTRAP%" 2>&1
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
