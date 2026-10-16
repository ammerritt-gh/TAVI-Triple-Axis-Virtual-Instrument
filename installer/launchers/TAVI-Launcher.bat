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
:: Keep this check identical to the ones in update-tavi.bat and
:: TAVI-Repair-Launchers.bat. TAVI_VERSION comes from a text file and the
:: banner below expands it, so it must be a release tag
:: (v<digits>.<digits>.<digits>) or main first. "set NAME|" hands the value
:: to findstr without cmd parsing it, where "echo %NAME%" would run whatever
:: follows an & in it. Digits are listed, not ranged: findstr resolves a
:: range through the machine collation. A refused value shows as unknown.
set TAVI_VERSION| findstr /r /x /c:"TAVI_VERSION=v[0123456789][0123456789]*\.[0123456789][0123456789]*\.[0123456789][0123456789]*" /c:"TAVI_VERSION=main" >nul
if errorlevel 1 set "TAVI_VERSION=unknown"

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
echo   [5] Collect diagnostics for support - runs the TAVI Doctor, takes a few minutes
echo   [6] Uninstall TAVI
echo   [7] Exit
echo.
choice /C 1234567 /N /M "Select option (1-7): "
:: Exact comparisons, never an "if errorlevel" ladder: choice returns 255 on
:: error and 0 when the user presses Ctrl-C, and a descending ladder with the
:: destructive option at the top would route both of those straight into it.
:: Since 1.4 Exit is the last item, below Uninstall.
set "PICK=%ERRORLEVEL%"
if "%PICK%"=="1" goto run
if "%PICK%"=="2" goto update
if "%PICK%"=="3" goto folder
if "%PICK%"=="4" goto shell
if "%PICK%"=="5" goto diagnostics
if "%PICK%"=="6" goto uninstall
if "%PICK%"=="7" goto quit
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

:diagnostics
if not exist "%TAVI_BASE%\collect-diagnostics.bat" goto diagnostics_missing
call "%TAVI_BASE%\collect-diagnostics.bat"
:: The Doctor retitles the window.
title TAVI Launcher
goto menu

:diagnostics_missing
echo.
echo [ERROR] collect-diagnostics.bat was not found in:
echo         %TAVI_BASE%
echo         Run the TAVI installer again to restore it.
echo.
choice /C C /N /M "Press C to go back to the menu."
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
choice /C C /N /M "Press C to go back to the menu."
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
:: Hand over in THIS console rather than opening another window. `cd` first,
:: because Windows will not remove a directory that is some process's current
:: one and this one's is inside the installation; then `call`, and the copy
:: ends the process itself - this file is inside the folder being deleted, so
:: cmd could not read another line from it afterwards.
cd /d "%TEMP%"
call "%UNINST_COPY%" "%TAVI_BASE%" /confirmed
:: Not reached when the copy runs: it ends the process. Never fall through into
:: the menu from here - this file may already have been deleted.
exit 1

:uninstall_missing
echo.
echo [ERROR] uninstall-tavi.bat was not found in:
echo         %TAVI_BASE%
echo         Download WINDOWS-uninstall-TAVI.bat from the TAVI releases page.
choice /C C /N /M "Press C to go back to the menu."
goto menu

:uninstall_copy_failed
echo.
echo [ERROR] Could not copy the uninstaller to a temporary folder.
choice /C C /N /M "Press C to go back to the menu."
goto menu

:quit
endlocal
exit /b 0
