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

set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MAMBA_ROOT=%TAVI_BASE%\mamba"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"

if not exist "%MICROMAMBA_EXE%" goto no_micromamba
if not exist "%ENV_PREFIX%\python.exe" goto no_env
if not exist "%INSTALL_DIR%\.git" goto no_repo

set "TAVI_VERSION="
for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="TAVI_VERSION" set "TAVI_VERSION=%%B"
if not defined TAVI_VERSION goto no_version

set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"

echo ============================================================================
echo                       TAVI Repair
echo ============================================================================
echo.
echo Installation : %TAVI_BASE%
echo Environment  : %ENV_PREFIX%
echo Pinned to    : %TAVI_VERSION%
echo.
echo This repairs and re-checks the release above. It does not upgrade TAVI and
echo does not change any package.
echo.

cd /d "%INSTALL_DIR%"
if errorlevel 1 goto no_repo

echo [INFO] Fetching tags from GitHub...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git fetch --tags origin
if errorlevel 1 goto fetch_failed

echo [INFO] Checking out %TAVI_VERSION%...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git checkout "%TAVI_VERSION%"
if errorlevel 1 goto checkout_failed

echo [INFO] Checking that the GUI toolkit and McStasScript load...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
if errorlevel 1 goto env_failed

echo.
echo [OK] Repair complete. The installed program is still pinned to %TAVI_VERSION%.
echo To move to a newer TAVI release, download that release's installer.
pause
endlocal
exit /b 0

:fetch_failed
echo.
echo [ERROR] Could not fetch from GitHub. Check your internet connection.
goto fail

:checkout_failed
echo.
echo [ERROR] Could not check out %TAVI_VERSION%. The tag may be missing, or
echo         files in the program folder may have been changed by hand.
goto fail

:env_failed
echo.
echo [ERROR] The TAVI environment is broken. Run the TAVI installer again; it
echo         rebuilds the environment from scratch.
goto fail

:no_micromamba
echo [ERROR] micromamba was not found at:
echo         %MICROMAMBA_EXE%
goto fail

:no_env
echo [ERROR] The TAVI environment was not found at:
echo         %ENV_PREFIX%
goto fail

:no_repo
echo [ERROR] %INSTALL_DIR% is not a Git checkout, so it cannot be repaired.
echo         Run the TAVI installer again.
goto fail

:no_version
echo [ERROR] Could not read TAVI_VERSION from:
echo         %TAVI_BASE%\INSTALL_INFO.txt
goto fail

:fail
pause
endlocal
exit /b 1
