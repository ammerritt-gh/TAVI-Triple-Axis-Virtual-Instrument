@echo off
setlocal DisableDelayedExpansion

:: TAVI launcher repair - for an installation made before version 1.3.1.
::
:: Those installations start TAVI with "micromamba run -n tavi", which selects
:: the environment by NAME against whatever root micromamba happens to inherit.
:: Where a second environment of that name exists - for instance because the
:: installer had to move the installation off a user profile containing a space,
:: leaving the original behind - a normal double-click can load TAVI's program
:: files from one place and its Python and mcrun from the other. McStas then
:: fails on every simulation while the deterministic engine still works.
::
:: This rewrites the three launcher scripts so that each one names the exact
:: environment folder recorded in INSTALL_INFO.txt. It changes nothing else: not
:: the environment, not the program, not any setting. The originals are kept
:: beside them as .bak-<number> files.
::
:: Installing version 1.3.1 or later fixes this properly; this is for a machine
:: that should not have to reinstall 3 GB to get a working launcher.

title TAVI Launcher Repair

echo ============================================================================
echo                    TAVI Launcher Repair
echo ============================================================================
echo.

set "INSTALL_DIR=%~1"
if defined INSTALL_DIR goto have_dir

set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
if not exist "%RECORD%" goto try_defaults
for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "INSTALL_DIR=%%B"
if not defined INSTALL_DIR goto try_defaults
if exist "%INSTALL_DIR%\app\TAVI_PySide6.py" set "INSTALL_DIR=%INSTALL_DIR%\app"
if exist "%INSTALL_DIR%\TAVI_PySide6.py" goto have_dir
set "INSTALL_DIR="

:try_defaults
if exist "%USERPROFILE%\TAVI\TAVI_PySide6.py" set "INSTALL_DIR=%USERPROFILE%\TAVI"
if defined INSTALL_DIR goto have_dir
if exist "%SystemDrive%\TAVI-Data\TAVI\TAVI_PySide6.py" set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
if defined INSTALL_DIR goto have_dir
echo [INFO] No TAVI installation was found in the usual places.
echo.
set /p "INSTALL_DIR=Type the full path of the TAVI program folder: "
if not defined INSTALL_DIR goto no_install

:have_dir
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto no_install
if not exist "%INSTALL_DIR%\INSTALL_INFO.txt" goto no_info

set "ENV_PREFIX="
set "MAMBA_ROOT="
set "MICROMAMBA_EXE="
for /f "usebackq tokens=1,* delims==" %%A in ("%INSTALL_DIR%\INSTALL_INFO.txt") do if /i "%%A"=="ENV_PREFIX" set "ENV_PREFIX=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%INSTALL_DIR%\INSTALL_INFO.txt") do if /i "%%A"=="MAMBA_ROOT_PREFIX" set "MAMBA_ROOT=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%INSTALL_DIR%\INSTALL_INFO.txt") do if /i "%%A"=="MICROMAMBA_DIR" set "MICROMAMBA_EXE=%%B\micromamba.exe"

if not defined ENV_PREFIX goto no_env_recorded
if not defined MICROMAMBA_EXE goto no_env_recorded
if not exist "%ENV_PREFIX%\python.exe" goto env_missing
if not exist "%MICROMAMBA_EXE%" goto micromamba_missing
:: %%~fI collapses the .. before validation rather than writing one into a
:: generated launcher.
if not defined MAMBA_ROOT for %%I in ("%ENV_PREFIX%\..\..") do set "MAMBA_ROOT=%%~fI"

:: Everything below is written verbatim into new batch files, so every value
:: read out of INSTALL_INFO.txt is checked first: that file is ordinary text on
:: disk, and a path carrying & or ^ would produce a launcher that does
:: something other than launching TAVI.
call :validate_base "%INSTALL_DIR%"
if defined VB_REASON goto value_refused
call :validate_base "%ENV_PREFIX%"
if defined VB_REASON goto value_refused
call :validate_base "%MAMBA_ROOT%"
if defined VB_REASON goto value_refused
call :validate_base "%MICROMAMBA_EXE%"
if defined VB_REASON goto value_refused

set "MCSTAS_RES=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS_RES%" set "MCSTAS_RES=%ENV_PREFIX%\Library\share\mcstas\resources"
if not exist "%MCSTAS_RES%" goto no_resources

echo This repairs the launcher scripts in:
echo     %INSTALL_DIR%
echo.
echo so that they always use this exact environment:
echo     %ENV_PREFIX%
echo.
echo The current scripts are kept as .bak files beside them. Nothing else is
echo changed: not the environment, not the program, not any of your settings.
echo.
choice /C YN /N /M "Repair the launcher scripts? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto cancelled

set "STAMP=%RANDOM%%RANDOM%"
echo.

set "TARGET=%INSTALL_DIR%\run-tavi.bat"
if exist "%TARGET%" copy /Y "%TARGET%" "%TARGET%.bak-%STAMP%" >nul
> "%TARGET%" echo @echo off
>> "%TARGET%" echo setlocal
>> "%TARGET%" echo :: Repaired by TAVI-Repair-Launchers.bat: the environment is named by its
>> "%TARGET%" echo :: exact folder, so no inherited setting can select a different one.
>> "%TARGET%" echo cd /d "%INSTALL_DIR%"
>> "%TARGET%" echo set "MCSTAS=%MCSTAS_RES%"
>> "%TARGET%" echo set "MCSTAS_COMPONENT_PATH=%MCSTAS_RES%"
>> "%TARGET%" echo set "MCSTAS_OVERRIDE="
>> "%TARGET%" echo set "MCSTAS_CFLAGS_OVERRIDE="
>> "%TARGET%" echo set "MCSTAS_CC_OVERRIDE="
>> "%TARGET%" echo set "MCSTAS_MPICC_OVERRIDE="
>> "%TARGET%" echo set "MCSTAS_MPIRUN_OVERRIDE="
>> "%TARGET%" echo set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"
>> "%TARGET%" echo if not exist "%ENV_PREFIX%\python.exe" goto noenv
>> "%TARGET%" echo echo [TAVI] Environment: %ENV_PREFIX%
>> "%TARGET%" echo "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python TAVI_PySide6.py
>> "%TARGET%" echo if errorlevel 1 pause
>> "%TARGET%" echo endlocal
>> "%TARGET%" echo exit /b 0
>> "%TARGET%" echo :noenv
>> "%TARGET%" echo echo [ERROR] The TAVI environment is missing: %ENV_PREFIX%
>> "%TARGET%" echo echo         Run the TAVI installer again.
>> "%TARGET%" echo pause
>> "%TARGET%" echo endlocal
>> "%TARGET%" echo exit /b 1
echo [OK] run-tavi.bat repaired.

set "TARGET=%INSTALL_DIR%\update-tavi.bat"
set "TAVI_VERSION="
for /f "usebackq tokens=1,* delims==" %%A in ("%INSTALL_DIR%\INSTALL_INFO.txt") do if /i "%%A"=="TAVI_VERSION" set "TAVI_VERSION=%%B"
if not defined TAVI_VERSION goto skip_update
if exist "%TARGET%" copy /Y "%TARGET%" "%TARGET%.bak-%STAMP%" >nul
> "%TARGET%" echo @echo off
>> "%TARGET%" echo setlocal
>> "%TARGET%" echo :: Repaired by TAVI-Repair-Launchers.bat.
>> "%TARGET%" echo cd /d "%INSTALL_DIR%"
>> "%TARGET%" echo set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"
>> "%TARGET%" echo echo [INFO] Fetching tags from GitHub...
>> "%TARGET%" echo "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git fetch --tags origin
>> "%TARGET%" echo if errorlevel 1 goto fail
>> "%TARGET%" echo echo [INFO] Checking out %TAVI_VERSION%...
>> "%TARGET%" echo "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" git checkout "%TAVI_VERSION%"
>> "%TARGET%" echo if errorlevel 1 goto fail
>> "%TARGET%" echo "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
>> "%TARGET%" echo if errorlevel 1 goto fail
>> "%TARGET%" echo echo [OK] Repair complete.
>> "%TARGET%" echo pause
>> "%TARGET%" echo endlocal
>> "%TARGET%" echo exit /b 0
>> "%TARGET%" echo :fail
>> "%TARGET%" echo echo [ERROR] Repair failed. Check your internet connection.
>> "%TARGET%" echo pause
>> "%TARGET%" echo endlocal
>> "%TARGET%" echo exit /b 1
echo [OK] update-tavi.bat repaired.

:skip_update
set "TARGET=%INSTALL_DIR%\TAVI-Launcher.bat"
if exist "%TARGET%" copy /Y "%TARGET%" "%TARGET%.bak-%STAMP%" >nul
> "%TARGET%" echo @echo off
>> "%TARGET%" echo setlocal
>> "%TARGET%" echo :: Repaired by TAVI-Repair-Launchers.bat.
>> "%TARGET%" echo title TAVI Launcher
>> "%TARGET%" echo :menu
>> "%TARGET%" echo cls
>> "%TARGET%" echo echo ===============================================
>> "%TARGET%" echo echo                 TAVI Launcher
>> "%TARGET%" echo echo ===============================================
>> "%TARGET%" echo echo.
>> "%TARGET%" echo echo   [1] Run TAVI
>> "%TARGET%" echo echo   [2] Update TAVI
>> "%TARGET%" echo echo   [3] Open TAVI folder
>> "%TARGET%" echo echo   [4] Open TAVI shell
>> "%TARGET%" echo echo   [5] Exit
>> "%TARGET%" echo echo.
>> "%TARGET%" echo choice /C 12345 /N /M "Select option (1-5): "
>> "%TARGET%" echo set "PICK=%%ERRORLEVEL%%"
>> "%TARGET%" echo if "%%PICK%%"=="1" goto run
>> "%TARGET%" echo if "%%PICK%%"=="2" goto update
>> "%TARGET%" echo if "%%PICK%%"=="3" goto folder
>> "%TARGET%" echo if "%%PICK%%"=="4" goto shell
>> "%TARGET%" echo if "%%PICK%%"=="5" goto quit
>> "%TARGET%" echo goto menu
>> "%TARGET%" echo :run
>> "%TARGET%" echo call "%INSTALL_DIR%\run-tavi.bat"
>> "%TARGET%" echo goto menu
>> "%TARGET%" echo :update
>> "%TARGET%" echo call "%INSTALL_DIR%\update-tavi.bat"
>> "%TARGET%" echo goto menu
>> "%TARGET%" echo :folder
>> "%TARGET%" echo explorer "%INSTALL_DIR%"
>> "%TARGET%" echo goto menu
>> "%TARGET%" echo :shell
>> "%TARGET%" echo cd /d "%INSTALL_DIR%"
>> "%TARGET%" echo set "MAMBA_ROOT_PREFIX=%MAMBA_ROOT%"
>> "%TARGET%" echo "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT%" run -p "%ENV_PREFIX%" cmd /k
>> "%TARGET%" echo goto menu
>> "%TARGET%" echo :quit
>> "%TARGET%" echo endlocal
>> "%TARGET%" echo exit /b 0
echo [OK] TAVI-Launcher.bat repaired.

echo.
echo ============================================================================
echo [OK] Repair complete.
echo.
echo TAVI will now always start in this environment:
echo     %ENV_PREFIX%
echo.
echo Start TAVI the way you normally do and run a simulation. If anything is
echo wrong, the previous scripts are beside the new ones, named .bak-%STAMP%.
echo ============================================================================
echo.
pause
endlocal
exit /b 0

:no_install
echo [ERROR] That folder does not contain TAVI_PySide6.py, so it is not a TAVI
echo         program folder: %INSTALL_DIR%
goto failed

:no_info
echo [ERROR] %INSTALL_DIR%\INSTALL_INFO.txt is missing, so the environment this
echo         installation uses cannot be determined.
echo [INFO]  Run the TAVI installer again instead.
goto failed

:no_env_recorded
echo [ERROR] INSTALL_INFO.txt does not record the environment folder. This
echo         installation predates the information this repair needs.
echo [INFO]  Run the TAVI installer again instead.
goto failed

:env_missing
echo [ERROR] The recorded environment does not exist: %ENV_PREFIX%
echo [INFO]  Run the TAVI installer again; it rebuilds the environment.
goto failed

:micromamba_missing
echo [ERROR] micromamba was not found at: %MICROMAMBA_EXE%
goto failed

:no_resources
echo [ERROR] No McStas resources were found under %ENV_PREFIX%
echo [INFO]  Run the TAVI installer again; it rebuilds the environment.
goto failed

:cancelled
echo.
echo Nothing was changed.
echo.
pause
endlocal
exit /b 0

:failed
echo.
pause
endlocal
exit /b 1

:value_refused
echo [ERROR] INSTALL_INFO.txt holds a path this repair will not write into
echo         a launcher: %VB_REASON%
echo [INFO]  Run the TAVI installer again instead.
goto failed

:: ---------------------------------------------------------------------------
:: Keep :validate_base byte-identical to the copies in
:: installer\launchers\uninstall-tavi.bat and WINDOWS-uninstall-TAVI.bat.
:: tests\test_installer_launchers.py asserts that the three copies match. It is
:: duplicated rather than shared because each of those files has to work alone:
:: this one before anything is downloaded, and the uninstaller from a copy of
:: itself in %TEMP%.
::
:: The character whitelist is fed from "set VBPATH" through a pipe, never from
:: "echo %VBPATH%". A value containing & or ^ splits the command line the moment
:: it is expanded there, so the test meant to catch those characters is the one
:: they break: C:\TAVI&calc was measured passing an echo-based check. "set NAME"
:: writes the value to stdout without it ever being parsed as a command, so one
:: whitelist can reject every character at once, and nothing after it has to
:: expand an unvetted value.
:: Ceiling: this guards against a mistyped or stale path, not against a hostile
:: local user; a single-user install has no trust boundary here.
:: ---------------------------------------------------------------------------
:validate_base
set "VBPATH=%~1"
set "VB_REASON="
if not defined VBPATH set "VB_REASON=the path is empty"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"=="\" set "VBPATH=%VBPATH:~0,-1%"
if not defined VBPATH set "VB_REASON=the path is empty"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"=="." set "VB_REASON=it ends with a dot"
if defined VB_REASON goto :eof
if "%VBPATH:~-1%"==" " set "VB_REASON=it ends with a space"
if defined VB_REASON goto :eof
if "%VBPATH:~0,2%"=="\\" set "VB_REASON=network and device paths are not supported"
if defined VB_REASON goto :eof
if not "%VBPATH%"=="%VBPATH: =%" set "VB_REASON=it contains a space, and McStas cannot compile from a path with a space in it"
if defined VB_REASON goto :eof
set VBPATH| findstr /r /c:"[^A-Za-z0-9_.:=\\-]" >nul
if not errorlevel 1 set "VB_REASON=it contains a character McStas cannot handle - use only letters, digits, dot, dash and underscore"
if defined VB_REASON goto :eof
if not "%VBPATH%"=="%VBPATH:..=%" set "VB_REASON=it contains .."
if defined VB_REASON goto :eof
if not "%VBPATH:~1,1%"==":" set "VB_REASON=it must start with a drive letter, like C:\TAVI"
if defined VB_REASON goto :eof
if not "%VBPATH:~2,1%"=="\" set "VB_REASON=it must start with a drive letter, like C:\TAVI"
if defined VB_REASON goto :eof
if "%VBPATH:~3%"=="" set "VB_REASON=a whole drive cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%USERPROFILE%" set "VB_REASON=your user folder itself cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%SystemRoot%" set "VB_REASON=the Windows folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%LOCALAPPDATA%" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%APPDATA%" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%ProgramFiles%" set "VB_REASON=Program Files cannot be the TAVI folder"
if defined VB_REASON goto :eof
if /i "%VBPATH%"=="%SystemDrive%\Users" set "VB_REASON=that folder cannot be the TAVI folder"
if defined VB_REASON goto :eof
if not exist "%VBPATH%\" goto :eof
for %%I in ("%VBPATH%") do set "VB_LEAF=%%~nxI"
for %%I in ("%VBPATH%") do set "VB_PARENT=%%~dpI"
dir /a:l /b "%VB_PARENT%" 2>nul | findstr /i /x /c:"%VB_LEAF%" >nul
if not errorlevel 1 set "VB_REASON=it is a junction or a symbolic link, which may point somewhere else entirely"
goto :eof
