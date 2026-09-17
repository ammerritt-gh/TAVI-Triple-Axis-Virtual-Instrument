@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows uninstaller - standalone fallback.
::
::   WINDOWS-uninstall-TAVI.bat [<install folder>]
::
:: The normal way to remove TAVI is the launcher's "Uninstall TAVI" option.
:: This file exists for the case where that is not available: a damaged
:: installation, a deleted launcher, or an installation made before 1.3.1.
::
:: It locates the installation - from the argument, then the install record,
:: then the folders older installers used, then by asking - and hands over to
:: <base>\uninstall-tavi.bat, which was installed alongside that installation
:: and therefore matches its layout. Only when there is no such file does it
:: remove anything itself, and then only a layout it recognises.
::
:: It never removes micromamba installed anywhere else, any environment other
:: than the one this installation created, or the developer environment
:: tavi-dev.

if /i "%~1"=="/validate-only" goto validate_only

title TAVI Uninstaller

echo ============================================================================
echo                    TAVI Uninstaller
echo ============================================================================
echo.

set "TAVI_BASE=%~1"
if defined TAVI_BASE goto have_base

set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"
if not exist "%RECORD%" goto try_defaults
for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "TAVI_BASE=%%B"
if not defined TAVI_BASE goto try_defaults
:: The record locates an installation; it never authorises deleting one. It is
:: an ordinary user-writable file, so its value is validated before anything -
:: including this message - expands it onto a command line.
call :validate_base "%TAVI_BASE%"
if defined VB_REASON goto record_unusable
set "TAVI_BASE=%VBPATH%"
if exist "%TAVI_BASE%\" goto have_base
echo [INFO] The install record points at a folder that no longer exists.
set "TAVI_BASE="
goto try_defaults

:record_unusable
echo [INFO] The install record does not hold a usable path; ignoring it.
set "TAVI_BASE="

:try_defaults
if exist "%USERPROFILE%\TAVI\TAVI_PySide6.py" set "TAVI_BASE=%USERPROFILE%\TAVI"
if defined TAVI_BASE goto have_base
if exist "%USERPROFILE%\TAVI\.tavi-install-root" set "TAVI_BASE=%USERPROFILE%\TAVI"
if defined TAVI_BASE goto have_base
if exist "%SystemDrive%\TAVI-Data\TAVI\TAVI_PySide6.py" set "TAVI_BASE=%SystemDrive%\TAVI-Data\TAVI"
if defined TAVI_BASE goto have_base
if exist "%SystemDrive%\TAVI-Data\.tavi-install-root" set "TAVI_BASE=%SystemDrive%\TAVI-Data"
if defined TAVI_BASE goto have_base

echo [INFO] No TAVI installation was found in the usual places.
echo.
set /p "TAVI_BASE=Type the full path of the TAVI folder (or press Enter to stop): "
if not defined TAVI_BASE goto nothing_to_do

:have_base
call :validate_base "%TAVI_BASE%"
if defined VB_REASON goto refused
set "TAVI_BASE=%VBPATH%"
if not exist "%TAVI_BASE%\" goto nothing_to_do

echo [INFO] TAVI installation: %TAVI_BASE%
echo.

:: An installation from 1.3.1 onwards carries its own uninstaller, which knows
:: the layout that installer built. Prefer it: this file ships with whatever
:: release the user happened to download, which need not be the one installed.
set "DELEGATE=%TAVI_BASE%\uninstall-tavi.bat"
if exist "%DELEGATE%" goto delegate
:: The installed copy can be missing while the installation is otherwise sound.
:: The checkout carries the same file, so use that before giving up.
set "DELEGATE=%TAVI_BASE%\app\installer\launchers\uninstall-tavi.bat"
if exist "%DELEGATE%" goto delegate
goto legacy

:delegate
set "UNINST_COPY=%TEMP%\tavi-uninstall-%RANDOM%%RANDOM%.bat"
copy /Y "%DELEGATE%" "%UNINST_COPY%" >nul
if errorlevel 1 goto copy_failed
echo [INFO] Handing over to the uninstaller that came with this installation.
echo.
start "" /d "%TEMP%" "%UNINST_COPY%" "%TAVI_BASE%"
endlocal
exit /b 0

:legacy
:: No installed uninstaller. Either this predates 1.3.1, or the file is gone.
set "LAYOUT="
if exist "%TAVI_BASE%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="LAYOUT" set "LAYOUT=%%B"
if defined LAYOUT goto unknown_layout
if not exist "%TAVI_BASE%\TAVI_PySide6.py" goto not_an_install

set "ENV_PREFIX="
if exist "%TAVI_BASE%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="ENV_PREFIX" set "ENV_PREFIX=%%B"
set "MICROMAMBA_EXE="
if exist "%TAVI_BASE%\INSTALL_INFO.txt" for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="MICROMAMBA_DIR" set "MICROMAMBA_EXE=%%B\micromamba.exe"

echo This is a TAVI installation from before version 1.3.1.
echo.
echo It removes:
echo     %TAVI_BASE%
echo         the program, your scan results in output\ and your settings in config\
if defined ENV_PREFIX echo     %ENV_PREFIX%
if defined ENV_PREFIX echo         the Python, McStas and compiler environment
echo     the desktop shortcut, if there is one
echo.
echo It does not remove micromamba itself or any other environment, and never
echo the developer environment tavi-dev.
echo.
echo None of this can be recovered. Copy out any scan results you want to keep
echo BEFORE answering Yes.
echo.
choice /C YN /N /M "Remove this TAVI installation? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto cancelled

dir /b "%TAVI_BASE%\output" 2>nul | findstr /r "." >nul
if errorlevel 1 goto legacy_remove
echo.
echo [WARNING] There are saved scan results in %TAVI_BASE%\output - they will be deleted.
choice /C YN /N /M "Delete your scan results too? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto cancelled

:legacy_remove
if not defined ENV_PREFIX goto legacy_no_env
call :validate_base "%ENV_PREFIX%"
if defined VB_REASON goto legacy_env_refused
:: Belt and braces: never the developer environment, whatever a file says.
if /i "%VBPATH:~-9%"=="\tavi-dev" goto legacy_env_refused
echo [INFO] Removing the environment: %ENV_PREFIX%
rd /s /q "%ENV_PREFIX%" 2>nul
goto legacy_remove_dir

:legacy_env_refused
echo [WARN] Not removing the recorded environment path, because it does not
echo        look like one this installer created (%VB_REASON%). It was:
:: Through "set", never "echo %VAR%": this path failed validation, so it is
:: exactly the string that must not reach a command line. See :validate_base.
set VBPATH
goto legacy_remove_dir

:legacy_no_env
echo [WARN] No environment path was recorded for this installation, so only the
echo        program folder is removed. Any environment it used is left in place.

:legacy_remove_dir
echo [INFO] Removing the program folder: %TAVI_BASE%
rd /s /q "%TAVI_BASE%" 2>nul
if exist "%USERPROFILE%\Desktop\TAVI Launcher.lnk" del /f /q "%USERPROFILE%\Desktop\TAVI Launcher.lnk" >nul 2>nul
if exist "%LOCALAPPDATA%\TAVI\install-record.txt" del /f /q "%LOCALAPPDATA%\TAVI\install-record.txt" >nul 2>nul
rd "%LOCALAPPDATA%\TAVI" 2>nul
if exist "%TAVI_BASE%" goto legacy_stuck
echo.
echo [OK] TAVI has been removed.
goto finished

:legacy_stuck
echo.
echo [ERROR] Some files could not be deleted, because a program still has them
echo         open. Close TAVI and any window showing %TAVI_BASE%, then run this
echo         uninstaller again. Nothing else was changed.
goto failed

:unknown_layout
echo [ERROR] That installation records folder layout "%LAYOUT%", and the
echo         uninstaller that came with it is missing from both the folder
echo         itself and its app\installer\launchers\ copy. Removing a layout
echo         this file does not know by hand risks deleting the wrong things,
echo         so nothing has been touched.
echo [INFO]  Run that release's installer again - it restores the uninstaller -
echo         or download the uninstaller from its page on GitHub.
goto failed

:not_an_install
echo [ERROR] %TAVI_BASE% does not look like a TAVI installation: it has no
echo         uninstaller, no TAVI_PySide6.py and no install information.
echo         Refusing to delete anything in it.
goto failed

:refused
echo [ERROR] Refusing to uninstall from this path: %VB_REASON%
echo         The path was:
:: Printed through "set", never "echo %VAR%". This message exists precisely
:: because the path failed validation, so it is the one string in the script
:: most likely to contain an ampersand - and echoing it would split the command
:: line and run whatever follows. Measured: a rejected C:\TAVI&calc launched
:: Calculator from this very line.
set VBPATH
goto failed

:copy_failed
echo [ERROR] Could not copy the installed uninstaller to a temporary folder.
goto failed

:nothing_to_do
echo [INFO] Nothing to remove.
goto finished

:cancelled
echo.
echo Uninstall cancelled. Nothing was removed.
goto finished

:finished
echo.
pause
endlocal
exit /b 0

:failed
echo.
pause
endlocal
exit /b 1

:validate_only
call :validate_base "%~2"
if defined VB_REASON goto validate_only_refused
echo ACCEPT
endlocal
exit /b 0

:validate_only_refused
echo REFUSE %VB_REASON%
endlocal
exit /b 1

:: ---------------------------------------------------------------------------
:: Keep :validate_base byte-identical to the copies in
:: WINDOWS-install-TAVI-v1.3.1.bat and installer\launchers\uninstall-tavi.bat.
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
:: Every allowed character is listed rather than given as a range: findstr
:: resolves a range like A-Z through the machine's collation order, which
:: places accented Latin letters inside it. C:\TAVE-with-an-acute was
:: measured passing the range form, and McStas cannot compile from it.
set VBPATH| findstr /r /c:"[^ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:=\\-]" >nul
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
