@echo off
setlocal DisableDelayedExpansion
title TAVI - record the Monte Carlo failure
set "SUPPORT_DIR=%~dp0"

:: /resolve-only prints the installation it resolved (LAYOUT, then TAVI_BASE)
:: and exits before anything else runs; it changes nothing. It exists so that
:: tests/test_installer_launchers.py can drive the real resolution, as
:: /validate-only lets it drive :validate_base in the installer and uninstallers.
set "RESOLVE_ONLY="
if /i "%~1"=="/resolve-only" set "RESOLVE_ONLY=1"

:: layout 2 (1.3.2+): the base folder is user-chosen at install time and
:: cannot be computed by rule, so the installer leaves a locator behind at
:: %LOCALAPPDATA%\TAVI\install-record.txt. The record is ordinary
:: user-writable text, so it is trusted only as far as the uninstallers trust
:: it: its value goes straight into VBPATH and through :validate_base_var
:: before any line expands it (as in installer\WINDOWS-uninstall-TAVI.bat),
:: and the folder counts as an installation only when its marker's INSTALL_ID
:: matches its INSTALL_INFO.txt's (as in installer\launchers\uninstall-tavi.bat).
:: Anything else falls back to the layout-1 default. The resolution below is
:: the same in installer\TAVI-Doctor.bat -- keep the two in step.
set "LAYOUT=1"
set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
if not exist "%RECORD%" goto default_base
set "VBPATH="
for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "VBPATH=%%B"
if not defined VBPATH goto default_base
call :validate_base_var
if defined VB_REASON goto record_unusable
set "MARK_ID="
set "INFO_ID="
if exist "%VBPATH%\.tavi-install-root" for /f "usebackq tokens=1,* delims==" %%A in ("%VBPATH%\.tavi-install-root") do if /i "%%A"=="INSTALL_ID" set "MARK_ID=%%B"
if exist "%VBPATH%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%VBPATH%\INSTALL_INFO.txt") do if /i "%%A"=="INSTALL_ID" set "INFO_ID=%%B"
if not defined MARK_ID goto record_unusable
if not defined INFO_ID goto record_unusable
:: Both IDs come from text files in that folder. The installer writes
:: INSTALL_ID as four random numbers joined by dashes; anything else does not
:: check out, and is refused before the comparison expands it. "set NAME|"
:: hands the value to findstr without cmd parsing it; digits are listed, not
:: ranged, because findstr resolves a range through the machine collation.
set MARK_ID| findstr /r /x /c:"MARK_ID=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto record_unusable
set INFO_ID| findstr /r /x /c:"INFO_ID=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto record_unusable
if /i not "%MARK_ID%"=="%INFO_ID%" goto record_unusable
set "LAYOUT=2"
set "TAVI_BASE=%VBPATH%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MICROMAMBA_EXE=%TAVI_BASE%\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%TAVI_BASE%\mamba"
echo [INFO] Installation found from the install record: %TAVI_BASE%
goto paths_ready

:record_unusable
:: Never print the value: it may be the one that failed validation.
echo [INFO] The install record does not name a TAVI installation that checks
echo        out, so the default location is used instead.

:default_base
:: Pre-1.3.2 layout: fixed locations under the profile (or the space-safe
:: relocation when the profile path itself contains a space).
set "TAVI_BASE=%USERPROFILE%"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_EXE=%USERPROFILE%\AppData\Local\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
if not "%USERPROFILE%"=="%USERPROFILE: =%" goto relocate_default
goto default_ready

:relocate_default
set "TAVI_BASE=%SystemDrive%\TAVI-Data"
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_EXE=%SystemDrive%\TAVI-Data\micromamba\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"

:default_ready
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\tavi"
echo [INFO] Installation found at the default location: %INSTALL_DIR%

:paths_ready
if defined RESOLVE_ONLY goto resolve_only
set "REPORTS=%SUPPORT_DIR%Reports"
if not exist "%REPORTS%" mkdir "%REPORTS%"
set "BOOTSTRAP=%REPORTS%\STARTUP-%RANDOM%-%RANDOM%.txt"
> "%BOOTSTRAP%" echo TAVI support startup - %DATE% %TIME%
if not exist "%BOOTSTRAP%" (
    echo Cannot write reports beside the recorder. Extract it to your Desktop and run it there.
    pause
    exit /b 1
)
>> "%BOOTSTRAP%" echo TAVI_BASE=%TAVI_BASE%
>> "%BOOTSTRAP%" echo INSTALL_DIR=%INSTALL_DIR%
>> "%BOOTSTRAP%" echo ENV_PREFIX=%ENV_PREFIX%
>> "%BOOTSTRAP%" echo MICROMAMBA_EXE=%MICROMAMBA_EXE%
>> "%BOOTSTRAP%" echo MAMBA_ROOT_PREFIX=%MAMBA_ROOT_PREFIX%
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto missing
if not exist "%MICROMAMBA_EXE%" goto missing
if not exist "%SUPPORT_DIR%tavi_record.py" goto missing
set "MCSTAS=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS%" set "MCSTAS=%ENV_PREFIX%\Library\share\mcstas\resources"
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
"%MICROMAMBA_EXE%" run -r "%MAMBA_ROOT_PREFIX%" -p "%ENV_PREFIX%" python -u "%SUPPORT_DIR%tavi_record.py" "%INSTALL_DIR%" "%REPORTS%" >> "%BOOTSTRAP%" 2>&1
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

:resolve_only
:: Through "set", never "echo %VAR%": the base may have come from the record.
echo LAYOUT=%LAYOUT%
set TAVI_BASE
endlocal
exit /b 0

:: ---------------------------------------------------------------------------
:: Keep :validate_base byte-identical in every file that carries it; the
:: list is VALIDATE_BASE_COPIES in tests\test_installer_launchers.py, which
:: asserts that they match. It is duplicated rather than shared because each
:: of those files has to work alone:
:: the Doctor and the support recorder are handed to a user on their own.
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

:validate_base_var
:: Entry point for a caller that has already put the raw value in VBPATH -
:: `set /p` does that without parsing it. Everything below is ordered so that
:: the whitelist, which reads the value through a pipe rather than expanding
:: it, runs before any line expands %VBPATH% at all.
set "VB_REASON="
if not defined VBPATH set "VB_REASON=the path is empty"
if defined VB_REASON goto :eof
:: Every allowed character is listed rather than given as a range: findstr
:: resolves a range like A-Z through the machine's collation order, which
:: places accented Latin letters inside it. C:\TAVE-with-an-acute was
:: measured passing the range form, and McStas cannot compile from it.
:: A double quote is not in this set either, which is what stops a pasted
:: "C:\..." or a crafted value from ending a quoted region further down.
set VBPATH| findstr /r /c:"[^ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:=\\-]" >nul
if not errorlevel 1 set "VB_REASON=it contains a character McStas cannot handle - use only letters, digits, dot, dash and underscore, with no quotes"
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
:: Walk every existing component, not just the last one. A junction anywhere
:: above the base makes the real target different from the path on screen, and
:: this routine authorises a recursive delete. Checking only the leaf let
:: C:\SomeJunction\TAVI through, and a base that did not exist yet was not
:: checked at all.
set "VB_WALK=%VBPATH%"

:vb_walk
if not defined VB_WALK goto :eof
if "%VB_WALK:~3%"=="" goto :eof
for %%I in ("%VB_WALK%") do set "VB_LEAF=%%~nxI"
for %%I in ("%VB_WALK%") do set "VB_PARENT=%%~dpI"
if not exist "%VB_WALK%\" goto vb_walk_up
dir /a:l /b "%VB_PARENT%" 2>nul | findstr /i /x /c:"%VB_LEAF%" >nul
if not errorlevel 1 set "VB_REASON=%VB_WALK% is a junction or a symbolic link, which may point somewhere else entirely"
if defined VB_REASON goto :eof

:vb_walk_up
if "%VB_PARENT:~-1%"=="\" set "VB_PARENT=%VB_PARENT:~0,-1%"
if /i "%VB_PARENT%"=="%VB_WALK%" goto :eof
set "VB_WALK=%VB_PARENT%"
goto vb_walk
