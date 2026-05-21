@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: TAVI Uninstaller for Windows
:: =============================================================================
:: Removes the TAVI installation created by WINDOWS-install-TAVI.bat.
::
:: What this script removes:
::   - The TAVI code directory (%USERPROFILE%\TAVI)
::   - The 'tavi' conda environment inside micromamba
::   - Optionally: the micromamba installation itself
::   - The desktop shortcut
::
:: What this script does NOT remove:
::   - Visual Studio / Build Tools
::   - Microsoft MPI SDK
::   - Any other micromamba environments you may have created
::
:: Usage: WINDOWS-uninstall-TAVI.bat [--verbose]
:: =============================================================================

set "VERBOSE=0"
if "%1"=="--verbose" set "VERBOSE=1"
if "%1"=="-v" set "VERBOSE=1"

title TAVI Uninstaller

echo ============================================================================
echo                    TAVI Uninstaller
echo                 Triple Axis Virtual Instrument
echo ============================================================================
echo.

set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "ENV_NAME=tavi"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"

echo The following will be removed:
echo   TAVI directory    : %INSTALL_DIR%
echo   tavi environment  : %MICROMAMBA_DIR%\envs\%ENV_NAME%
echo   Desktop shortcut  : %SHORTCUT%
echo.
echo The following will NOT be removed:
echo   Visual Studio / Build Tools
echo   Microsoft MPI SDK
echo   Any other micromamba environments
echo.

choice /C YN /M "Proceed with uninstallation"
if errorlevel 2 (
    echo [INFO] Uninstallation cancelled.
    pause
    exit /b 0
)
echo.

:: =============================================================================
:: Step 1: Remove the tavi conda environment
:: =============================================================================
echo [Step 1/4] Removing 'tavi' conda environment...

if not exist "%MICROMAMBA_DIR%\micromamba.exe" (
    echo [INFO] micromamba not found. Skipping environment removal.
    goto :step1_done
)

:: Check whether the tavi env exists before trying to remove it
set "ENV_EXISTS=0"
for /f "tokens=1" %%E in ('"%MICROMAMBA_DIR%\micromamba.exe" env list 2^>nul') do (
    if /I "%%E"=="%ENV_NAME%" set "ENV_EXISTS=1"
)

if "%ENV_EXISTS%"=="1" (
    echo [INFO] Removing environment '%ENV_NAME%'...
    "%MICROMAMBA_DIR%\micromamba.exe" env remove -n %ENV_NAME% -y
    if !errorlevel! neq 0 (
        echo [WARN] Environment removal reported errors. Continuing...
    ) else (
        echo [OK] Environment '%ENV_NAME%' removed.
    )
) else (
    echo [INFO] Environment '%ENV_NAME%' not found. Nothing to remove.
)

:step1_done
echo.

:: =============================================================================
:: Step 2: Offer to remove micromamba itself
:: =============================================================================
echo [Step 2/4] Micromamba installation...

if not exist "%MICROMAMBA_DIR%" (
    echo [INFO] Micromamba directory not found. Skipping.
    goto :step2_done
)

:: Check whether any other environments exist
set "OTHER_ENVS=0"
for /f "skip=2 tokens=1" %%E in ('"%MICROMAMBA_DIR%\micromamba.exe" env list 2^>nul') do (
    if /I not "%%E"=="base" set "OTHER_ENVS=1"
)

if "%OTHER_ENVS%"=="1" (
    echo [INFO] Other micromamba environments were found:
    "%MICROMAMBA_DIR%\micromamba.exe" env list 2>nul
    echo.
    echo [INFO] Removing micromamba would also delete the environments listed above.
)

choice /C YN /M "Also remove micromamba from %MICROMAMBA_DIR% (Y) or leave it (N)"
if errorlevel 2 (
    echo [INFO] Leaving micromamba in place.
    goto :step2_done
)

echo [INFO] Removing micromamba directory: %MICROMAMBA_DIR%
rd /s /q "%MICROMAMBA_DIR%" 2>nul
if !errorlevel! neq 0 (
    echo [WARN] Could not fully remove %MICROMAMBA_DIR%.
    echo [WARN] Some files may be locked. Try again after closing all terminals.
) else (
    echo [OK] Micromamba removed.
)

:step2_done
echo.

:: =============================================================================
:: Step 3: Remove the TAVI directory
:: =============================================================================
echo [Step 3/4] Removing TAVI directory: %INSTALL_DIR%...

if not exist "%INSTALL_DIR%" (
    echo [INFO] TAVI directory not found. Nothing to remove.
    goto :step3_done
)

:: Safety check: confirm the directory looks like a TAVI install
:: before deleting it. We check for TAVI_PySide6.py as a sentinel.
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" (
    echo [WARN] %INSTALL_DIR% does not look like a TAVI installation.
    echo [WARN] TAVI_PySide6.py was not found there.
    choice /C YN /M "Delete it anyway"
    if errorlevel 2 (
        echo [INFO] Skipping TAVI directory removal.
        goto :step3_done
    )
)

rd /s /q "%INSTALL_DIR%" 2>nul
if !errorlevel! neq 0 (
    echo [WARN] Could not fully remove %INSTALL_DIR%.
    echo [WARN] Some files may be locked. Try again after closing TAVI.
) else (
    echo [OK] TAVI directory removed.
)

:step3_done
echo.

:: =============================================================================
:: Step 4: Remove desktop shortcut
:: =============================================================================
echo [Step 4/4] Removing desktop shortcut...

if exist "%SHORTCUT%" (
    del "%SHORTCUT%" 2>nul
    if !errorlevel! neq 0 (
        echo [WARN] Could not remove desktop shortcut: %SHORTCUT%
    ) else (
        echo [OK] Desktop shortcut removed.
    )
) else (
    echo [INFO] Desktop shortcut not found. Nothing to remove.
)
echo.

:: =============================================================================
:: Done
:: =============================================================================
echo ============================================================================
echo                    Uninstallation Complete
echo ============================================================================
echo.
echo The following were NOT removed (unrelated to TAVI):
echo   - Visual Studio / Build Tools
echo   - Microsoft MPI SDK
echo.
echo If you leave micromamba in place and later want to remove it manually:
echo   Delete: %MICROMAMBA_DIR%
echo.
pause
endlocal
