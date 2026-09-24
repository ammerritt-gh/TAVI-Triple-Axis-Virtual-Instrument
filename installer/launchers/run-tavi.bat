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

echo [TAVI] Environment: %ENV_PREFIX%
echo [TAVI] MCSTAS=%MCSTAS%
echo.
cd /d "%INSTALL_DIR%"
if errorlevel 1 goto no_source
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python TAVI_PySide6.py
if errorlevel 1 goto run_failed
endlocal
exit /b 0

:run_failed
echo.
echo [ERROR] TAVI exited with an error. The lines above are the reason.
pause
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
pause
endlocal
exit /b 1
