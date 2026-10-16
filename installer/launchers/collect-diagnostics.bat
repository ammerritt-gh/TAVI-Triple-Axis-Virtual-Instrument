@echo off
setlocal DisableDelayedExpansion

:: TAVI diagnostics for support (layout 2, 1.4).
::
:: Gathers everything that diagnoses an installation into ONE zip file in
:: %LOCALAPPDATA%\TAVI\logs\TAVI-diagnostics-<yyyyMMdd-HHmmss>.zip, for the
:: student to send: the install, launch, repair and uninstall logs, the crash
:: log, install-status.txt, INSTALL_INFO.txt, the compile-check logs and the
:: TAVI Doctor's report. The launcher menu's "Collect diagnostics for support"
:: runs it, and so does the installer's D on a failure screen.
::
:: The logs are zipped BEFORE the Doctor runs, so a Doctor that hangs on a
:: McStas run never costs them; the zip is rewritten with the Doctor's report
:: added when it ends. Whatever is missing (a failed install may have no app\
:: and no Doctor) is listed and skipped. The zip is made with Windows' own
:: tar.exe; without it the collected files stay in a folder, which is opened
:: instead.
::
:: /quiet: no Explorer and no wait, for scripted and test runs. Exit code 0
:: when the zip was made, 1 when it was not.
::
:: Every path is derived from this file's own location. It normally sits in
:: the base folder; run from the checkout's installer\launchers\ (the installer
:: does that when the install died before the launchers were copied), the base
:: is three folders up.

set "SCRIPT_DIR=%~dp0"
set "TAVI_BASE=%~dp0"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
if /i "%SCRIPT_DIR:~-21%"=="\installer\launchers\" if exist "%SCRIPT_DIR%..\..\TAVI_PySide6.py" for %%I in ("%SCRIPT_DIR%..\..\..") do set "TAVI_BASE=%%~fI"
if "%TAVI_BASE:~-1%"=="\" set "TAVI_BASE=%TAVI_BASE:~0,-1%"
set "INSTALL_DIR=%TAVI_BASE%\app"
set "DOCTOR=%INSTALL_DIR%\installer\TAVI-Doctor.bat"
:: Named in full: a GNU tar from Git or MSYS earlier on PATH cannot write a zip.
set "TAR_EXE=%SystemRoot%\System32\tar.exe"
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"

echo.
echo ============================================================================
echo                 Collecting diagnostics for support
echo ============================================================================
echo.
echo TAVI installation: %TAVI_BASE%
echo.

call :stamp
set "NAME=TAVI-diagnostics-%STAMP%"

:: The zip goes in the logs folder, or in %TEMP% when that cannot be written.
:: The files are collected in a folder beside it, made fresh here and removed
:: once the zip holds them.
set "LOG_HOME="
if defined LOCALAPPDATA set "LOG_HOME=%LOCALAPPDATA%\TAVI\logs"
if defined LOG_HOME if not exist "%LOG_HOME%\" mkdir "%LOG_HOME%" >nul 2>nul
set "STAGE="
set "OUT_DIR=%LOG_HOME%"
if defined OUT_DIR call :make_stage
if defined STAGE goto staged
set "OUT_DIR=%TEMP%"
if defined OUT_DIR call :make_stage
if not defined STAGE goto no_folder

:staged
set "ZIP=%OUT_DIR%\%NAME%.zip"
> "%STAGE%\collected.txt" echo TAVI diagnostics %STAMP%
>> "%STAGE%\collected.txt" echo Installation: %TAVI_BASE%
>> "%STAGE%\collected.txt" echo.

echo Collecting the log files...
:: The logs folder holds only TAVI's own logs. In %TEMP%, where each log falls
:: back when that folder cannot be written, only TAVI's own shapes are taken: a
:: stamp, the same with a %RANDOM% suffix when two runs shared a second, or
:: tavi-rnd-digits-digits when PowerShell gave no clock. Another program's
:: install-*.log is not ours to send.
set "FOUND="
set "SRC=%LOG_HOME%"
set "DST=%STAGE%"
set "PATTERN=*"
if defined LOG_HOME call :copy_logs
set "SRC=%TEMP%"
set "DST=%STAGE%\temp-fallback"
set "PATTERN=????????-??????*"
if defined TEMP call :copy_logs
set "PATTERN=tavi-rnd-*"
if defined TEMP call :copy_logs
set "MISSED="
if not defined FOUND goto no_logs_found
>> "%STAGE%\collected.txt" echo found: install, launch, repair and uninstall logs
goto logs_done

:no_logs_found
call :missing "install, launch, repair or uninstall logs"

:logs_done

set "ITEM=%INSTALL_DIR%\output\tavi-crash.log"
set "DEST=tavi-crash.log"
set "LABEL=crash log"
call :take
set "ITEM=%TAVI_BASE%\install-status.txt"
set "DEST=install-status.txt"
set "LABEL=install-status.txt"
call :take
set "ITEM=%TAVI_BASE%\INSTALL_INFO.txt"
set "DEST=INSTALL_INFO.txt"
set "LABEL=INSTALL_INFO.txt"
call :take
set "ITEM=%TAVI_BASE%\compile_check\serial.log"
set "DEST=compile_check-serial.log"
set "LABEL=compile check log, serial"
call :take
set "ITEM=%TAVI_BASE%\compile_check\mpi.log"
set "DEST=compile_check-mpi.log"
set "LABEL=compile check log, MPI"
call :take
if defined MISSED echo   That is normal: not every installation has every one of these files.

set "ZIP_MADE="
if exist "%TAR_EXE%" call :zip
echo.
if defined ZIP_MADE goto saved_first
echo Your logs are collected in this folder:
echo     %STAGE%
goto run_doctor

:saved_first
echo Your logs are saved in this file:
echo     %ZIP%

:run_doctor
echo.
if exist "%DOCTOR%" goto doctor_found
echo The TAVI Doctor was not found, because the program folder is missing or
echo incomplete. The logs above are all there is to collect.
>> "%STAGE%\collected.txt" echo missing: TAVI Doctor report - no Doctor in the program folder
if exist "%TAR_EXE%" call :zip
goto finish

:doctor_found
echo Now the TAVI Doctor checks the installation and runs four short test
echo simulations. This usually takes a few minutes.
echo If it is still running after ten minutes, you can close this window: your
echo logs are already saved, as shown above.
echo.
call :newest_doctor
set "PREV_DOC=%DOC_DIR%"
:: The Doctor's console is for support, not the student: it goes into the zip.
call "%DOCTOR%" /quiet /base "%TAVI_BASE%" > "%STAGE%\TAVI-doctor-console.txt" 2>&1
call :newest_doctor
if not defined DOC_DIR goto doctor_no_report
if /i "%DOC_DIR%"=="%PREV_DOC%" goto doctor_no_report
copy /y "%TAVI_BASE%\%DOC_DIR%\TAVI-doctor-report.txt" "%STAGE%\TAVI-doctor-report.txt" >nul 2>nul
copy /y "%TAVI_BASE%\%DOC_DIR%\TAVI-doctor-summary.txt" "%STAGE%\TAVI-doctor-summary.txt" >nul 2>nul
if not exist "%STAGE%\TAVI-doctor-report.txt" goto doctor_no_report
>> "%STAGE%\collected.txt" echo found: TAVI Doctor report
if exist "%TAR_EXE%" call :zip
goto finish

:doctor_no_report
echo.
echo The TAVI Doctor did not leave a report. The logs are still collected.
>> "%STAGE%\collected.txt" echo missing: TAVI Doctor report - the Doctor left none
if exist "%TAR_EXE%" call :zip

:finish
if not defined ZIP_MADE goto no_zip
rd /s /q "%STAGE%" >nul 2>nul
echo.
echo ============================================================================
echo  DIAGNOSTICS SAVED
echo ============================================================================
echo Please send this one file to the person who helps you with TAVI:
echo.
echo     %ZIP%
echo.
echo Attach it to an e-mail the way you would attach a photo or a document.
if defined QUIET goto done_ok
echo The folder that holds it is opening now, with the file selected.
explorer /select,"%ZIP%"
echo.
choice /c C /n /m "Press C to continue."

:done_ok
endlocal
exit /b 0

:no_zip
echo.
echo ============================================================================
echo  DIAGNOSTICS COLLECTED IN A FOLDER
echo ============================================================================
if not exist "%TAR_EXE%" echo Windows' zip tool tar.exe is not on this computer, so no zip was made.
if exist "%TAR_EXE%" echo Windows could not make the zip file.
echo The files are collected in this folder instead:
echo.
echo     %STAGE%
echo.
echo Please send everything in that folder to the person who helps you with TAVI.
if defined QUIET goto done_failed
echo The folder is opening now.
explorer "%STAGE%"
echo.
choice /c C /n /m "Press C to continue."
goto done_failed

:no_folder
echo.
echo [ERROR] No folder could be created to collect the files in, neither in
echo         %LOCALAPPDATA%\TAVI\logs nor in %TEMP%.
echo         Free some disk space and try again.
if defined QUIET goto done_failed
echo.
choice /c C /n /m "Press C to continue."

:done_failed
endlocal
exit /b 1

:: ---------------------------------------------------------------------------
:: The collecting folder, OUT_DIR\NAME. A folder of that name already there is
:: not ours to fill and later delete, so the name gets a random suffix.
:: ---------------------------------------------------------------------------
:make_stage
if not exist "%OUT_DIR%\" goto :eof
if exist "%OUT_DIR%\%NAME%" set "NAME=%NAME%-%RANDOM%"
if exist "%OUT_DIR%\%NAME%" goto :eof
mkdir "%OUT_DIR%\%NAME%" >nul 2>nul
if exist "%OUT_DIR%\%NAME%\" set "STAGE=%OUT_DIR%\%NAME%"
goto :eof

:: Copy SRC\<kind>-PATTERN.log into DST for each kind of log. Paths travel in
:: variables, not call arguments: call expands a percent sign in a path twice.
:copy_logs
if not exist "%SRC%\" goto :eof
for %%F in ("%SRC%\install-%PATTERN%.log" "%SRC%\launch-%PATTERN%.log" "%SRC%\repair-%PATTERN%.log" "%SRC%\uninstall-%PATTERN%.log") do set "ONE=%%~fF" & call :copy_one
goto :eof

:copy_one
if not exist "%DST%\" mkdir "%DST%" >nul 2>nul
copy /y "%ONE%" "%DST%\" >nul 2>nul
if not errorlevel 1 set "FOUND=1"
goto :eof

:: Copy ITEM into the collecting folder as DEST, or note LABEL as missing.
:take
if not exist "%ITEM%" goto take_missing
copy /y "%ITEM%" "%STAGE%\%DEST%" >nul 2>nul
if errorlevel 1 goto take_missing
>> "%STAGE%\collected.txt" echo found: %LABEL%
goto :eof

:take_missing
call :missing "%LABEL%"
goto :eof

:missing
set "MISSED=1"
echo   Not found: %~1
>> "%STAGE%\collected.txt" echo missing: %~1
goto :eof

:: Zip the collecting folder from inside OUT_DIR, so tar sees only short ASCII
:: names whatever the user name is. It writes a new file and moves it over the
:: old one, so a failed second pass keeps the first zip.
:zip
pushd "%OUT_DIR%" || goto :eof
"%TAR_EXE%" -a -c -f "%NAME%-new.zip" "%NAME%" >nul 2>nul
set "TAR_RC=%ERRORLEVEL%"
popd
if not "%TAR_RC%"=="0" goto zip_failed
move /y "%OUT_DIR%\%NAME%-new.zip" "%ZIP%" >nul 2>nul
del /f /q "%OUT_DIR%\%NAME%-new.zip" >nul 2>nul
if not exist "%ZIP%" goto :eof
set "ZIP_MADE=1"
goto :eof

:zip_failed
del /f /q "%OUT_DIR%\%NAME%-new.zip" >nul 2>nul
goto :eof

:: The Doctor writes into <base>\tavi_doctor_<random>; the newest by creation
:: time is the one it just made, unless it made none.
:newest_doctor
set "DOC_DIR="
for /f "delims=" %%D in ('dir /b /ad /tc /o-d "%TAVI_BASE%\tavi_doctor_*" 2^>nul') do if not defined DOC_DIR set "DOC_DIR=%%D"
goto :eof

:: yyyyMMdd-HHmmss from PowerShell, which formats the clock the same way on
:: every locale; %DATE% and %TIME% change layout with the region setting and
:: wmic is gone from current Windows 11. "<nul" keeps PowerShell off this
:: console's input. Anything not shaped like a stamp, PowerShell missing or
:: locked down included, gives a %RANDOM% name instead.
:stamp
set "STAMP="
for /f "delims=" %%S in ('powershell -NoProfile -NonInteractive -Command "Get-Date -Format yyyyMMdd-HHmmss" ^<nul 2^>nul') do set "STAMP=%%S"
if not defined STAMP set "STAMP=none"
set STAMP| findstr /r /x /c:"STAMP=[0123456789][0123456789][0123456789][0123456789][0123456789][0123456789][0123456789][0123456789]-[0123456789][0123456789][0123456789][0123456789][0123456789][0123456789]" >nul
if errorlevel 1 set "STAMP=tavi-rnd-%RANDOM%-%RANDOM%"
goto :eof
