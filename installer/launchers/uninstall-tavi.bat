@echo off
setlocal DisableDelayedExpansion

:: TAVI uninstaller (layout 2).
::
::   uninstall-tavi.bat [<base folder>] [/y]
::
:: With no argument it uninstalls the installation it sits in. The launcher
:: menu copies it to %TEMP% and runs it with the base folder and /y, having
:: already confirmed; a copy outside the tree is what makes deleting the tree
:: possible at all.
::
:: It never runs "rd /s /q" on the base folder itself. It removes the children
:: the installer created, by name, and then a bare "rd" on the base, which
:: Windows refuses for a folder that still holds anything. Whatever the user
:: put beside app\ therefore survives and is reported.
::
:: Deleting requires an ownership token: <base>\.tavi-install-root must exist
:: and its INSTALL_ID must match INSTALL_INFO.txt. A TAVI_PySide6.py sentinel
:: is not enough - every checkout of the project has one.

:: /validate-only <path> prints ACCEPT or REFUSE <reason> and changes nothing.
:: It exists so that tests/test_installer_launchers.py can drive :validate_base
:: over a table of paths in the real file rather than in a copy of it.
if /i "%~1"=="/validate-only" goto validate_only

set "TAVI_BASE=%~1"
set "AUTO=%~2"
if not defined TAVI_BASE set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"

set "SELF_DIR=%~dp0"
if "%SELF_DIR:~-1%"=="\" set "SELF_DIR=%SELF_DIR:~0,-1%"

title TAVI Uninstaller

:: Running from inside the folder we are about to delete: Windows will not
:: remove a process's current directory, and cmd reads this file line by line
:: as it goes, so it could not read another line once the file is gone.
::
:: Hand over to a copy in %TEMP%, in THIS console. Not "start": that would
:: open a second window on the user for no reason, and a test driving this
:: script cannot suppress a console that cmd creates for a detached process.
:: `cd` first so nothing here holds the folder, then `call` - and the copy
:: ends the whole process with `exit`, so control never returns to this file.
if /i not "%SELF_DIR%"=="%TAVI_BASE%" goto not_in_place
set "SELF_COPY=%TEMP%\tavi-uninstall-%RANDOM%%RANDOM%.bat"
copy /Y "%~f0" "%SELF_COPY%" >nul
if errorlevel 1 goto copy_failed
cd /d "%TEMP%"
call "%SELF_COPY%" "%TAVI_BASE%" %AUTO%
:: Not reached when the copy runs, because it ends the process. Reached only if
:: the copy returned without doing so - and then falling through into the
:: removal below would be the one thing this hand-off exists to prevent, since
:: this file is inside the folder being deleted.
exit

:not_in_place
cd /d "%SystemDrive%\"

call :validate_base "%TAVI_BASE%"
if defined VB_REASON goto refused

set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MARKER=%TAVI_BASE%\.tavi-install-root"
set "INFO=%TAVI_BASE%\INSTALL_INFO.txt"
set "RECORD=%LOCALAPPDATA%\TAVI\install-record.txt"

if not exist "%TAVI_BASE%\" goto not_installed

set "MARK_ID="
set "INFO_ID="
set "LAYOUT="
if exist "%MARKER%" for /f "usebackq tokens=1,* delims==" %%A in ("%MARKER%") do if /i "%%A"=="INSTALL_ID" set "MARK_ID=%%B"
if exist "%INFO%" for /f "usebackq tokens=1,* delims==" %%A in ("%INFO%") do if /i "%%A"=="INSTALL_ID" set "INFO_ID=%%B"
if exist "%INFO%" for /f "usebackq tokens=1,* delims==" %%A in ("%INFO%") do if /i "%%A"=="LAYOUT" set "LAYOUT=%%B"

if not defined MARK_ID goto no_marker
if not defined INFO_ID goto no_marker
if /i not "%MARK_ID%"=="%INFO_ID%" goto id_mismatch
if not "%LAYOUT%"=="2" goto wrong_layout

echo ============================================================================
echo                       TAVI Uninstaller
echo ============================================================================
echo.
echo Removing the TAVI installation in:
echo     %TAVI_BASE%
echo.
if /i "%AUTO%"=="/y" goto remove
echo This deletes the program, your scan results in app\output, your saved
echo settings in app\config, the Python/McStas environment and the downloaded
echo package cache. None of it can be recovered, and reinstalling later
echo downloads about 1.5 GB of packages again.
echo Anything else you have put in the folder is left alone.
echo.
choice /C YN /N /M "Remove TAVI? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto cancelled

:remove
set "TRIES=0"

:remove_attempt
set /a TRIES+=1
echo [INFO] Removing TAVI files (attempt %TRIES%)...
if exist "%INSTALL_DIR%" rd /s /q "%INSTALL_DIR%" 2>nul
if exist "%ENV_PREFIX%" rd /s /q "%ENV_PREFIX%" 2>nul
if exist "%TAVI_BASE%\micromamba" rd /s /q "%TAVI_BASE%\micromamba" 2>nul
if exist "%TAVI_BASE%\mamba" rd /s /q "%TAVI_BASE%\mamba" 2>nul
if exist "%TAVI_BASE%\compile_check" rd /s /q "%TAVI_BASE%\compile_check" 2>nul
if exist "%TAVI_BASE%\run-tavi.bat" del /f /q "%TAVI_BASE%\run-tavi.bat" 2>nul
if exist "%TAVI_BASE%\update-tavi.bat" del /f /q "%TAVI_BASE%\update-tavi.bat" 2>nul
if exist "%TAVI_BASE%\TAVI-Launcher.bat" del /f /q "%TAVI_BASE%\TAVI-Launcher.bat" 2>nul
if exist "%TAVI_BASE%\TAVI Launcher.lnk" del /f /q "%TAVI_BASE%\TAVI Launcher.lnk" 2>nul

:: rd reports success even when it skipped a file another process had open, so
:: the only trustworthy check is whether the folders are still there - and it
:: has to cover all five, not just the obvious two: a locked package cache
:: would otherwise be reported below as "not TAVI's, left alone".
if exist "%INSTALL_DIR%" goto payload_left
if exist "%ENV_PREFIX%" goto payload_left
if exist "%TAVI_BASE%\micromamba" goto payload_left
if exist "%TAVI_BASE%\mamba" goto payload_left
if exist "%TAVI_BASE%\compile_check" goto payload_left
goto payload_gone

:payload_left
if %TRIES% GEQ 3 goto payload_stuck
echo [INFO] Something still had a file open; waiting and trying again...
ping -n 4 127.0.0.1 >nul
goto remove_attempt

:payload_gone
:: Reached only once all five payload folders are confirmed gone, so
:: INSTALL_INFO.txt and the marker have outlived every step that can fail and
:: leave something to retry. What remains below cannot strand anything: if the
:: base will not go, it is because the user's own files are in it.
if exist "%TAVI_BASE%\uninstall-tavi.bat" del /f /q "%TAVI_BASE%\uninstall-tavi.bat" 2>nul
if exist "%INFO%" del /f /q "%INFO%" 2>nul
if exist "%MARKER%" del /f /q "%MARKER%" 2>nul
rd "%TAVI_BASE%" 2>nul

if exist "%TAVI_BASE%" goto base_kept
call :drop_record
goto removed_clean

:base_kept
:: A bare rd refuses a folder that still holds something, so this is the user's
:: own content and is reported rather than removed.
call :drop_record
echo.
echo [OK] TAVI has been removed.
echo.
echo These files were not TAVI's, so they were left alone:
dir /b "%TAVI_BASE%"
echo.
echo They are in: %TAVI_BASE%
goto finished

:removed_clean
echo.
echo [OK] TAVI has been removed, and %TAVI_BASE% is gone.
goto finished

:payload_stuck
echo.
echo [ERROR] Some TAVI files could not be deleted, because a program still has
echo         them open. Nothing has been lost; the uninstall is unfinished.
echo.
echo         Close TAVI and any command window or Explorer window showing
echo         %TAVI_BASE%, then run this uninstaller again.
echo.
echo Still present:
if exist "%INSTALL_DIR%" echo     %INSTALL_DIR%
if exist "%ENV_PREFIX%" echo     %ENV_PREFIX%
echo.
pause
endlocal
exit 1

:not_installed
echo [INFO] Nothing to remove: %TAVI_BASE% does not exist.
goto finished

:no_marker
echo [ERROR] %TAVI_BASE% does not carry a TAVI ownership marker
echo         (.tavi-install-root and INSTALL_INFO.txt with a matching
echo         INSTALL_ID), so this uninstaller will not delete anything in it.
echo.
echo [INFO] If this really is a TAVI installation from before version 1.3.1,
echo        use the WINDOWS-uninstall-TAVI.bat from the releases page, which
echo        knows the older layout.
goto refused_end

:id_mismatch
echo [ERROR] The ownership marker in %TAVI_BASE% does not match its
echo         INSTALL_INFO.txt. Refusing to delete anything.
goto refused_end

:wrong_layout
echo [ERROR] %TAVI_BASE% was made by a different version of the TAVI
echo         installer (layout "%LAYOUT%", this uninstaller understands 2).
echo [INFO]  Use the uninstaller that came with that installation, or download
echo         the one from its release page.
goto refused_end

:refused
echo [ERROR] Refusing to uninstall from this path: %VB_REASON%
echo         The path was:
:: Printed through "set", never "echo %VAR%". This message exists precisely
:: because the path failed validation, so it is the one string in the script
:: most likely to contain an ampersand - and echoing it would split the command
:: line and run whatever follows. Measured: a rejected C:\TAVI&calc launched
:: Calculator from this very line.
set VBPATH
goto refused_end

:cancelled
echo.
echo Uninstall cancelled. Nothing was removed.
goto finished

:copy_failed
echo [ERROR] Could not copy the uninstaller to a temporary folder.
goto refused_end

:refused_end
echo.
pause
endlocal
exit 1

:finished
echo.
pause
endlocal
exit 0

:drop_record
:: There is one record for the user, not one per installation. Removing it
:: because some other installation was uninstalled would leave the one still on
:: the machine unfindable by the Doctor, the support recorder and the standalone
:: uninstaller. So it goes only when it names the folder just removed.
if not exist "%RECORD%" goto :eof
set "DR_BASE="
for /f "usebackq tokens=1,* delims==" %%A in ("%RECORD%") do if /i "%%A"=="TAVI_BASE" set "DR_BASE=%%B"
if not defined DR_BASE goto :eof
if /i not "%DR_BASE%"=="%TAVI_BASE%" goto :eof
del /f /q "%RECORD%" 2>nul
rd "%LOCALAPPDATA%\TAVI" 2>nul
goto :eof

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
:: Keep :validate_base byte-identical to the copy in
:: WINDOWS-install-TAVI-v1.3.1.bat and WINDOWS-uninstall-TAVI.bat.
:: tests/test_installer_launchers.py asserts that the three copies match.
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
