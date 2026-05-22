@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows uninstaller - safe version
:: Removes only the user TAVI install and the 'tavi' env.
:: It never removes the micromamba installation directory or unrelated envs.

set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "ENV_NAME=tavi"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"

title TAVI Safe Uninstaller

echo ============================================================================
echo                    TAVI Safe Uninstaller
echo ============================================================================
echo.
echo This will remove:
echo   TAVI directory   : %INSTALL_DIR%
echo   Environment      : %ENV_NAME%
echo   Desktop shortcut : %SHORTCUT%
echo.
echo This will NOT remove:
echo   micromamba itself
echo   tavi-dev or any other environment
echo   Visual Studio / Build Tools
echo   Microsoft MPI SDK
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

echo.
echo [OK] Safe uninstall complete.
pause
endlocal
