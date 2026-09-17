@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows uninstaller - safe version
:: Removes only the user TAVI install and the 'tavi' env.
:: It never removes the micromamba installation directory or unrelated envs.

set "ENV_NAME=tavi"

:: Mirror the installer's space-safe base exactly (installer build 4): a profile
:: path containing a space sends the whole install to %SystemDrive%\TAVI-Data,
:: and an uninstaller that assumed %USERPROFILE% would silently remove nothing.
set "TAVI_BASE=%USERPROFILE%"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
:: The root the installer created the env under; never the caller's own.
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "RELOCATED=no"

if not "%USERPROFILE%"=="%USERPROFILE: =%" goto relocate_base
goto paths_ready

:relocate_base
set "TAVI_BASE=%SystemDrive%\TAVI-Data"
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_DIR=%SystemDrive%\TAVI-Data\micromamba"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"
set "RELOCATED=yes"
goto paths_ready

:paths_ready
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"

title TAVI Safe Uninstaller

echo ============================================================================
echo                    TAVI Safe Uninstaller
echo ============================================================================
echo.
echo This will remove:
echo   TAVI directory   : %INSTALL_DIR%
echo   Environment      : %ENV_NAME%
echo   Env folder       : %ENV_PREFIX%
echo   Desktop shortcut : %SHORTCUT%
echo.
echo This will NOT remove:
echo   micromamba itself or any other environment
echo.
choice /C YN /M "Proceed"
if errorlevel 2 exit /b 0

echo.
echo [Step 1/3] Removing environment '%ENV_NAME%'...
if exist "%MICROMAMBA_EXE%" (
    "%MICROMAMBA_EXE%" env remove -n %ENV_NAME% -y
    if errorlevel 1 echo [WARN] Environment removal reported an error or env was already absent.
) else (
    echo [INFO] micromamba.exe not found; skipping environment removal.
)

echo.
echo [Step 2/3] Removing TAVI directory...
if exist "%INSTALL_DIR%" (
    if not exist "%INSTALL_DIR%\TAVI_PySide6.py" (
        echo [WARN] %INSTALL_DIR% does not contain TAVI_PySide6.py.
        choice /C YN /M "Delete this folder anyway"
        if errorlevel 2 goto skip_dir
    )
    rd /s /q "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [WARN] Could not fully remove %INSTALL_DIR%.
        echo [INFO] Close TAVI, Explorer, terminals, or editors using the folder and retry.
    ) else (
        echo [OK] Removed %INSTALL_DIR%.
    )
) else (
    echo [INFO] TAVI directory not found.
)
:skip_dir

echo.
echo [Step 3/3] Removing desktop shortcut...
if exist "%SHORTCUT%" del "%SHORTCUT%" >nul 2>nul

:: Tidy up the relocated base only when it is already empty; a plain rd refuses a
:: folder that still holds anything, so nothing of the user's can be caught here.
if "%RELOCATED%"=="yes" rd "%TAVI_BASE%" 2>nul

echo.
echo [OK] Safe uninstall complete.
pause
endlocal
