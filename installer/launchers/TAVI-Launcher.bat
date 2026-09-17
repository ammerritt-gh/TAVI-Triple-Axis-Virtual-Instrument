@echo off
setlocal DisableDelayedExpansion

:: TAVI launcher menu (layout 2).
::
:: Lives in the base folder and derives every path from its own location.
:: The desktop shortcut created by the installer points here.

set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MAMBA_ROOT=%TAVI_BASE%\mamba"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"

set "TAVI_VERSION=unknown"
if exist "%TAVI_BASE%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="TAVI_VERSION" set "TAVI_VERSION=%%B"

title TAVI Launcher

:menu
cls
echo ============================================================================
echo                         TAVI Launcher
echo                  Triple Axis Virtual Instrument
echo                  Release: %TAVI_VERSION%
echo ============================================================================
echo.
echo   Installed in: %TAVI_BASE%
echo.
echo   [1] Run TAVI
echo   [2] Repair TAVI
echo   [3] Open TAVI folder
echo   [4] Open TAVI shell
echo   [5] Exit
echo   [6] Uninstall TAVI
echo.
choice /C 123456 /N /M "Select option (1-6): "
:: Exact comparisons, never an "if errorlevel" ladder: choice returns 255 on
:: error and 0 when the user presses Ctrl-C, and a descending ladder with the
:: destructive option at the top would route both of those straight into it.
set "PICK=%ERRORLEVEL%"
if "%PICK%"=="1" goto run
if "%PICK%"=="2" goto update
if "%PICK%"=="3" goto folder
if "%PICK%"=="4" goto shell
if "%PICK%"=="5" goto quit
if "%PICK%"=="6" goto uninstall
goto menu

:run
call "%TAVI_BASE%\run-tavi.bat"
goto menu

:update
call "%TAVI_BASE%\update-tavi.bat"
goto menu

:folder
explorer "%TAVI_BASE%"
goto menu

:shell
if not exist "%ENV_PREFIX%\python.exe" goto shell_missing
cd /d "%INSTALL_DIR%"
set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" cmd /k
goto menu

:shell_missing
echo.
echo [ERROR] The TAVI environment was not found at:
echo         %ENV_PREFIX%
pause
goto menu

:uninstall
cls
echo ============================================================================
echo                       Uninstall TAVI
echo ============================================================================
echo.
echo This removes the TAVI installation in:
echo     %TAVI_BASE%
echo.
echo Everything below is deleted and CANNOT be recovered:
echo     %INSTALL_DIR%          the program
echo     %INSTALL_DIR%\output   your scan results
echo     %INSTALL_DIR%\config   your saved settings
echo     %ENV_PREFIX%           Python, McStas and the compiler
echo     %MAMBA_ROOT%           the downloaded package cache
echo.
echo Anything else you have put in the folder is left alone.
echo Reinstalling later downloads about 1.5 GB of packages again.
echo.
echo Copy out any scan results you want to keep BEFORE answering Yes.
echo.
choice /C YN /N /M "Remove TAVI and everything listed above? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto menu

dir /b "%INSTALL_DIR%\output" 2>nul | findstr /r "." >nul
if errorlevel 1 goto uninstall_go
echo.
echo [WARNING] There are saved scan results in:
echo               %INSTALL_DIR%\output
echo           They will be deleted.
echo.
choice /C YN /N /M "Delete your scan results too? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto menu

:uninstall_go
if not exist "%TAVI_BASE%\uninstall-tavi.bat" goto uninstall_missing
set "UNINST_COPY=%TEMP%\tavi-uninstall-%RANDOM%%RANDOM%.bat"
copy /Y "%TAVI_BASE%\uninstall-tavi.bat" "%UNINST_COPY%" >nul
if errorlevel 1 goto uninstall_copy_failed
echo.
echo [INFO] Starting the uninstaller in a new window and closing this one, so
echo        that nothing here holds the folder open.
:: /d puts the new process's working directory outside the tree it deletes:
:: Windows refuses to remove a directory that is some process's current one,
:: and this window's own working directory is inside the installation.
start "" /d "%TEMP%" "%UNINST_COPY%" "%TAVI_BASE%" /y
endlocal
exit /b 0

:uninstall_missing
echo.
echo [ERROR] uninstall-tavi.bat was not found in:
echo         %TAVI_BASE%
echo         Download WINDOWS-uninstall-TAVI.bat from the TAVI releases page.
pause
goto menu

:uninstall_copy_failed
echo.
echo [ERROR] Could not copy the uninstaller to a temporary folder.
pause
goto menu

:quit
endlocal
exit /b 0
