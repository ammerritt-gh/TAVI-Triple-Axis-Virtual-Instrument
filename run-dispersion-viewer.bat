@echo off
setlocal
cd /d "%~dp0"

rem Standalone dispersion viewer (gui\dispersion_viewer.py): plots a Phonon_DFT map
rem along a reciprocal-space path. Runs windowless via pythonw; errors go to
rem figures\dispersion-viewer.log and a dialog. Figures default to figures\.

set "ENV_PREFIX=%USERPROFILE%\AppData\Roaming\mamba\envs\tavi-dev"
if not exist "%ENV_PREFIX%\pythonw.exe" (
    echo [ERROR] tavi-dev environment not found at %ENV_PREFIX%
    echo [INFO] Run setup-tavi-dev.bat first.
    pause
    exit /b 1
)

rem Mimic conda activation far enough for numpy/scipy/Qt DLLs to resolve.
set "PATH=%ENV_PREFIX%;%ENV_PREFIX%\Library\bin;%ENV_PREFIX%\Scripts;%PATH%"
start "" "%ENV_PREFIX%\pythonw.exe" -m gui.dispersion_viewer
endlocal
