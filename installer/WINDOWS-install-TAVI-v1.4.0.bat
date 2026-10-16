@echo off
setlocal DisableDelayedExpansion

:: mcrun launches the compiled instrument as a bare "NAME.exe" through the shell.
:: A shell with NoDefaultCurrentDirectoryInExePath set refuses to search the
:: working directory and the serial run dies with "is not recognized as an
:: internal or external command" -- a property of the shell, not the install.
set "NoDefaultCurrentDirectoryInExePath="

:: TAVI Windows installer - release-pinned v1.4.0
:: (build 1, 2026-10-16: an install log, one ending with three headlines, a
::  test simulation through TAVI itself, a desktop copy of the shortcut, and
::  the diagnostics collector among the launchers)
:: Derived from WINDOWS-install-TAVI-v1.3.2.bat build 1 per the release recipe
:: in TAVI_Windows_Installer_Uninstaller_Design_Document.md section 22.
:: Conservative batch style: no micromamba shell init, no generated echo blocks,
:: no delayed expansion, and no nested cmd AutoRun dependency except where
:: unavoidable.
::
:: What 1.4 adds:
:: - Every run writes %LOCALAPPDATA%\TAVI\logs\install-<yyyyMMdd-HHmmss>.log
::   (%TEMP% when that folder cannot be written; with neither, the run goes
::   on without a log and says so once). It opens with a snapshot of the
::   machine and records every question and answer, every step's start, end
::   and outcome, and the long steps' whole output, which goes to the log
::   rather than the screen. A log write never changes an outcome.
:: - While a long step runs, a heartbeat prints a "still running" line every
::   30 seconds (with the MB downloaded so far while the environment builds).
:: - After the launchers, TAVI_PySide6.py --self-test --instrument puma runs
::   one real McStas point through TAVI itself, offscreen. Any nonzero exit
::   (1: the point failed, 2: the command line was refused) is the third outcome.
:: - Every outcome ends in one routine, on one of three headlines:
::     INSTALLATION SUCCEEDED                          exit code 0
::     INSTALLATION FAILED                             exit code 1
::     TAVI INSTALLED, BUT THE TEST SIMULATION FAILED  exit code 2
::   (and INSTALLATION CANCELLED, exit code 0, when the answer to "Continue?"
::   is No). A failure shows the log's last 30 lines, opens the log in
::   Notepad and offers D, which collects diagnostics and comes back; only C
::   closes the window. Nothing is removed on any outcome.
::   install-status.txt in the install folder names the outcome.
:: - After a success or a failed test simulation the student is asked whether
::   to put a copy of the shortcut on the desktop Windows reports (default
::   Yes); the shortcut also stays in the install folder, which opens.
::
:: Switches:
::   /dir <path>  Unattended: answers the folder question with <path>, which
::                is validated exactly as a typed one, and asks nothing else.
::                It never removes an installation that is already there,
::                never waits for a key, never opens Explorer or Notepad and
::                never touches the desktop. The exit code is the outcome.
::   /validate-only <path>  Prints ACCEPT or REFUSE <reason>; changes nothing.
:: Test-only switches, for the release checklist and tests; never mentioned
:: to students:
::   /ref <branch>            Clone that branch instead of the release tag.
::   /test-fail <step>        micromamba, env or selftest: skip that step and
::                            record it as failed ("forced failure (test
::                            run)"), so each headline can be shown. A run
::                            with /test-fail reports a stale cmd AutoRun hook
::                            but does not remove it.
::   TAVI_TEST_DESKTOP, when set, replaces the desktop Windows reports, so a
::   test never reaches a real desktop.

set "TAVI_VERSION=v1.4.0"
set "INSTALLER_VERSION=v1.4.0-1"
set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"
set "LAYOUT=2"
set "STEPS=8"

:: /validate-only <path> prints ACCEPT or REFUSE <reason> and changes nothing,
:: so tests can drive :validate_base over a table of paths in this real file.
if /i "%~1"=="/validate-only" goto validate_only

set "PRESET_BASE="
set "REF="
set "TEST_FAIL="
set "ARG_IGNORED="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/dir" goto arg_dir
if /i "%~1"=="/ref" goto arg_ref
if /i "%~1"=="/test-fail" goto arg_test_fail
set "ARG_IGNORED=yes"
shift
goto parse_args

:arg_dir
set "PRESET_BASE=%~2"
shift
shift
goto parse_args

:arg_ref
set "REF=%~2"
shift
shift
goto parse_args

:arg_test_fail
set "TEST_FAIL=%~2"
shift
shift
goto parse_args

:args_done
set "UNATTENDED=no"
if defined PRESET_BASE set "UNATTENDED=yes"

title TAVI Installer

:: The log comes first, so that whatever happens after this line is in it.
set "OUTCOME="
set "STEP_NAME=Starting the installer"
set "BASE_OURS=no"
set "HB_FLAG="
set "HB_LIVE="
set "HB_WRITTEN="
set "HB_SEQ=0"
call :open_log
set "LOG_STAMP=%STAMP%"
call :snapshot

:: The two test switches become a git argument and a step name; each is
:: matched against what it may be, through "set NAME|", before anything
:: expands it. Characters are listed, not ranged: findstr resolves a range
:: through the machine collation.
if not defined REF goto ref_ok
set REF| findstr /r /x /c:"REF=[ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789][ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-]*" >nul
if errorlevel 1 goto bad_ref
>> "%LOG%" echo [TAVI] Test switch /ref: cloning branch %REF% instead of %TAVI_VERSION%.

:ref_ok
if not defined TEST_FAIL goto test_fail_ok
set TEST_FAIL| findstr /i /x /c:"TEST_FAIL=micromamba" /c:"TEST_FAIL=env" /c:"TEST_FAIL=selftest" >nul
if errorlevel 1 goto bad_test_fail
>> "%LOG%" echo [TAVI] Test switch /test-fail: the step %TEST_FAIL% will be recorded as failed.

:test_fail_ok
if defined ARG_IGNORED >> "%LOG%" echo [TAVI] An argument this installer does not know was ignored.
if "%UNATTENDED%"=="yes" >> "%LOG%" echo [TAVI] Unattended run (/dir): no questions, and no wait at the end.

:: Everything lives under one folder the user chooses. Layout 2:
::   <base>\app            the pinned checkout, output\ and config\
::   <base>\tavi-env       Python, McStas, GCC, MS-MPI
::   <base>\micromamba     micromamba.exe
::   <base>\mamba          package cache (root prefix)
::   <base>\compile_check  the install-time compile gate and its logs
::   <base>\*.bat          the five launchers, copied from the checkout
::
:: The environment folder is "tavi-env" and not "env" on purpose: McStas keys
:: its per-user configuration on the basename of CONDA_DEFAULT_ENV, and
:: micromamba sets that to the whole prefix path whenever the prefix's parent is
:: not literally "envs". A folder called "env" would key it 3.7.1_env, which
:: another prefix could easily collide with.
::
:: McStas cannot run from a path containing a space: its own launchers expand an
:: unquoted %BINDIR%, so with "C:\Users\Jane Doe" the mcrun.bat command splits at
:: the space and python is handed "C:\Users\Jane" as the script to run (measured
:: on a user's machine, 2026-09-17; upstream bug, not TAVI's). The folder is
:: therefore validated, and the default moves off a profile that cannot hold it.

set "DEFAULT_BASE=%USERPROFILE%\TAVI"
set "RELOCATED=no"
call :validate_base "%DEFAULT_BASE%"
if not defined VB_REASON goto default_ready
set "DEFAULT_BASE=%SystemDrive%\TAVI-Data"
set "RELOCATED=yes"

:default_ready
>> "%LOG%" echo [TAVI] Suggested install folder: %DEFAULT_BASE% (moved off the profile: %RELOCATED%)

echo ============================================================================
echo                    TAVI Installation Script
echo                 Triple Axis Virtual Instrument
echo                 Release: %TAVI_VERSION%
echo ============================================================================
echo Installer version: %INSTALLER_VERSION%
echo TAVI version:      %TAVI_VERSION%
echo Python version:    %PYTHON_VERSION%
echo McStas version:    %MCSTAS_VERSION%
echo Micromamba:        %MAMBA_VERSION%
echo.
if defined LOGFILE echo Everything this installer does is written to a log file:
if defined LOGFILE echo     %LOGFILE%
if defined LOGFILE echo.
if defined REF echo [INFO] Test run: installing branch %REF% instead of %TAVI_VERSION%.
if defined TEST_FAIL echo [INFO] Test run: the step "%TEST_FAIL%" will be recorded as failed.
if "%RELOCATED%"=="no" goto ask_base
echo [INFO] Your Windows profile folder cannot hold TAVI:
echo            %USERPROFILE%
echo        McStas cannot compile or run from a path with a space or an
echo        accented character in it, so the suggested folder below is outside
echo        your profile. This is normal, and nothing else is affected.
echo.

:ask_base
set "STEP_NAME=Choosing the install folder"
set "VBPATH="
if defined PRESET_BASE goto base_given
echo Where should TAVI be installed?
echo.
echo   Everything goes inside this one folder: the program, its Python
echo   environment, McStas, the compiler and the downloaded packages. About
echo   3 GB in total, and one folder to remove when you are finished with it.
echo.
echo   The path may contain only letters, digits, dot, dash and underscore -
echo   no spaces and no accented characters, because McStas cannot compile
echo   from such a path.
echo.
echo   Press Enter to use:
echo       %DEFAULT_BASE%
echo   or type a full path, for example D:\TAVI
echo.
:: Straight into VBPATH: set /p stores what was typed without parsing it, and
:: :validate_base_var vets it there. Going through `call :validate_base "%VAR%"`
:: would expand the raw value onto a command line first, where a quote in it
:: ends the quoted region and the rest becomes commands.
set /p "VBPATH=Install folder: "
:: The answer goes into the log through "set", never "echo %VBPATH%": it has
:: not been vetted yet.
>> "%LOG%" echo [TAVI] Asked: Where should TAVI be installed? Answer:
if not defined VBPATH >> "%LOG%" echo [TAVI]     Enter, for the suggested folder
if defined VBPATH >> "%LOG%" set VBPATH
goto base_answered

:base_given
set "VBPATH=%PRESET_BASE%"
>> "%LOG%" echo [TAVI] Install folder given by /dir:
>> "%LOG%" set VBPATH

:base_answered
if not defined VBPATH set "VBPATH=%DEFAULT_BASE%"
call :validate_base_var
if defined VB_REASON goto base_refused
:: take the normalised value back (a trailing backslash has been stripped)
set "TAVI_BASE=%VBPATH%"
goto base_check

:base_refused
echo.
echo [ERROR] That folder cannot be used: %VB_REASON%
echo.
>> "%LOG%" echo [TAVI] Refused that folder: %VB_REASON%
goto retry_base

:: Every path that would ask for another folder comes through here. An
:: unattended run has nobody to ask, and must not loop on the one folder it was
:: given - including when a confirmation it cannot answer leaves an existing
:: installation in place, which is the behaviour we want: /dir never removes one.
:retry_base
if "%UNATTENDED%"=="yes" goto unattended_stop
goto ask_base

:unattended_stop
set "ERR1=Started with /dir, so there is nobody to ask for another folder."
set "ERR2=The reason is given above."
set "ERR3="
goto failed

:base_check
if not exist "%TAVI_BASE%\" goto base_ready
if exist "%TAVI_BASE%\.tavi-install-root" goto base_has_tavi
if exist "%TAVI_BASE%\TAVI_PySide6.py" goto base_maybe_legacy
:: An install that died partway leaves a folder with no ownership marker - the
:: marker is written last - so without this it would be refused below as "some
:: other folder" and the user would be stuck. The record says STATE=installing
:: precisely so this case is recognisable.
call :read_record_state "%TAVI_BASE%"
if "%REC_PARTIAL%"=="yes" goto base_has_partial
dir /b /a "%TAVI_BASE%" 2>nul | findstr /r "." >nul
if errorlevel 1 goto base_ready
echo.
echo [ERROR] That folder already contains other files:
echo             %TAVI_BASE%
echo         Uninstalling TAVI later removes this folder, so it must be a new
echo         or empty folder, or an existing TAVI installation.
echo.
>> "%LOG%" echo [TAVI] Refused %TAVI_BASE%: it already contains other files.
goto retry_base

:base_has_tavi
:: The same identity test the uninstaller applies before it deletes anything.
:: The marker's presence alone is not proof: its INSTALL_ID has to match
:: INSTALL_INFO.txt's, and the layout has to be one this installer built.
call :read_install_identity
if "%ID_OK%"=="yes" goto base_has_tavi_ok
echo.
echo [ERROR] %TAVI_BASE% carries a TAVI marker whose identity does not check
echo         out against its INSTALL_INFO.txt, or records a folder layout this
echo         installer did not build. Nothing in it will be touched.
echo         Remove it with the uninstaller that installed it, or choose
echo         another folder.
echo.
>> "%LOG%" echo [TAVI] Refused %TAVI_BASE%: its TAVI marker does not check out.
goto retry_base

:base_has_tavi_ok
echo.
echo [INFO] There is already a TAVI installation in:
echo            %TAVI_BASE%
echo        It will be removed and installed again from scratch.
>> "%LOG%" echo [TAVI] %TAVI_BASE% holds a TAVI installation; asking before removing it.
set "OLD_APP=%TAVI_BASE%\app"
call :confirm_wipe "%TAVI_BASE%" "%OLD_APP%"
if not "%WIPE_OK%"=="yes" goto retry_base
set "BASE_OURS=yes"
if exist "%TAVI_BASE%\app" rd /s /q "%TAVI_BASE%\app" 2>nul
if exist "%TAVI_BASE%\tavi-env" rd /s /q "%TAVI_BASE%\tavi-env" 2>nul
if exist "%TAVI_BASE%\compile_check" rd /s /q "%TAVI_BASE%\compile_check" 2>nul
if exist "%TAVI_BASE%\app" goto wipe_failed
if exist "%TAVI_BASE%\tavi-env" goto wipe_failed
set "OLD_REMOVED=yes"
>> "%LOG%" echo [TAVI] Removed the old program, environment and compile check.
goto base_ready

:base_has_partial
echo.
echo [INFO] An earlier installation into this folder did not finish:
echo            %TAVI_BASE%
echo        Its half-built program folder and environment will be cleared and
echo        built again. The packages already downloaded are kept, so this is
echo        much quicker than starting over.
>> "%LOG%" echo [TAVI] %TAVI_BASE% holds an unfinished installation; asking before clearing it.
call :confirm_wipe "%TAVI_BASE%" "%TAVI_BASE%\app"
if not "%WIPE_OK%"=="yes" goto retry_base
set "BASE_OURS=yes"
if exist "%TAVI_BASE%\app" rd /s /q "%TAVI_BASE%\app" 2>nul
if exist "%TAVI_BASE%\tavi-env" rd /s /q "%TAVI_BASE%\tavi-env" 2>nul
if exist "%TAVI_BASE%\compile_check" rd /s /q "%TAVI_BASE%\compile_check" 2>nul
if exist "%TAVI_BASE%\app" goto wipe_failed
if exist "%TAVI_BASE%\tavi-env" goto wipe_failed
set "OLD_REMOVED=yes"
>> "%LOG%" echo [TAVI] Cleared the unfinished program folder and environment.
goto base_ready

:base_maybe_legacy
:: TAVI_PySide6.py alone proves nothing. Every checkout of this project has
:: one, including a developer's own clone, and the branch below offers to
:: delete the whole folder. An INSTALLATION also carries an INSTALL_INFO.txt
:: and a generated run-tavi.bat, neither of which is in the repository.
if not exist "%TAVI_BASE%\INSTALL_INFO.txt" goto base_is_a_checkout
if not exist "%TAVI_BASE%\run-tavi.bat" goto base_is_a_checkout
goto base_has_legacy

:base_is_a_checkout
echo.
echo [ERROR] That folder holds TAVI's source code, but it is not a TAVI
echo         installation: it has no INSTALL_INFO.txt and no run-tavi.bat.
echo         It looks like a copy of the project's repository, and this
echo         installer will not delete one.
echo         Choose a new or empty folder instead.
echo.
>> "%LOG%" echo [TAVI] Refused %TAVI_BASE%: it is a copy of the repository, not an installation.
goto retry_base

:base_has_legacy
echo.
echo [INFO] There is a TAVI installation from before version 1.3.2 in:
echo            %TAVI_BASE%
echo        Since version 1.3.2 the program lives in an "app" folder inside
echo        it, so the old installation has to be removed first.
>> "%LOG%" echo [TAVI] %TAVI_BASE% holds an installation from before 1.3.2; asking before removing it.
call :confirm_wipe "%TAVI_BASE%" "%TAVI_BASE%"
if not "%WIPE_OK%"=="yes" goto retry_base
set "BASE_OURS=yes"
rd /s /q "%TAVI_BASE%" 2>nul
if exist "%TAVI_BASE%" goto wipe_failed
set "OLD_REMOVED=yes"
>> "%LOG%" echo [TAVI] Removed the installation from before 1.3.2.
:: An installation from before 1.3.2 also put a shortcut on the desktop; it
:: would dangle now that the launcher lives in the install folder. Only a
:: shortcut that opens the installation just removed goes: its target is
:: <that folder>\TAVI-Launcher.bat. Anything else of that name is left.
set "DESK_LEGACY=%USERPROFILE%\Desktop"
call :remove_desktop_shortcut
set "DESK_LEGACY="
goto base_ready

:wipe_failed
:: Some of the old installation may already be gone; the screen says so, and
:: never that nothing was removed.
set "OLD_REMOVED=partly"
set "ERR1=The old installation could not be removed. Close TAVI, Explorer"
set "ERR2=windows and command prompts using that folder, then try again."
set "ERR3=Folder: %TAVI_BASE%"
goto failed

:base_ready
set "INSTALL_DIR=%TAVI_BASE%\app"
set "ENV_PREFIX=%TAVI_BASE%\tavi-env"
set "MAMBA_ROOT_PREFIX=%TAVI_BASE%\mamba"
set "MICROMAMBA_DIR=%TAVI_BASE%\micromamba"
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "GATE_DIR=%TAVI_BASE%\compile_check"
:: Helper scripts run from a folder this installer owns, never %TEMP%:
:: python puts a script's own directory first on sys.path, so any stray .py
:: left in the user's temp folder shadows a standard-library module of the
:: same name. Measured on a cold install - a leftover copy.py broke
:: mcstasscript's "import copy" and the McStasScript configuration below.
set "WORK_DIR=%TAVI_BASE%\install_work"
set "HB_SCRIPT=%WORK_DIR%\heartbeat.bat"
set "SHORTCUT=%TAVI_BASE%\TAVI Launcher.lnk"
set "MARKER=%TAVI_BASE%\.tavi-install-root"
set "RECORD_DIR=%LOCALAPPDATA%\TAVI"
set "RECORD=%RECORD_DIR%\install-record.txt"
set "INSTALL_ID=%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"
set "CLONE_REF=%TAVI_VERSION%"
if defined REF set "CLONE_REF=%REF%"
call :snapshot_base

echo.
echo This installer will set up TAVI for this Windows user account.
echo.
echo It will do the following, all inside %TAVI_BASE%:
echo   1. Install micromamba.
echo   2. Create the Python/McStas environment, including a C compiler (GCC
echo      from conda-forge); Visual Studio is not needed.
echo   3. Install TAVI itself.
echo   4. Configure McStas/McStasScript paths for that environment.
echo   5. Configure and compile-check the McStas compiler.
echo   6. Build the lead-sample dispersion map (150 MB, a few minutes).
echo   7. Put the launchers and a shortcut in %TAVI_BASE%.
echo   8. Run one test simulation with TAVI, to check that it works.
echo.
echo This installer will NOT run micromamba shell init.
echo This installer will NOT touch any other conda or micromamba environment.
echo This installer may remove a broken cmd.exe AutoRun hook only if it contains
echo micromamba or mamba text from a previous failed install.
echo.
echo Note: the installation cannot be moved afterwards - the environment stores
echo its own location internally. The shortcut can be moved anywhere you like.
echo.
if "%UNATTENDED%"=="yes" goto confirmed
choice /C YN /N /M "Continue with TAVI installation? (Y/N): "
set "ANSWER=%ERRORLEVEL%"
if not "%ANSWER%"=="1" goto cancelled
>> "%LOG%" echo [TAVI] Asked: Continue with TAVI installation? Answer: Y
goto start_install

:confirmed
>> "%LOG%" echo [TAVI] Started with /dir, so "Continue with TAVI installation?" is not asked.

:start_install
set "STEP_NAME=Creating the install folder"
if not exist "%TAVI_BASE%" mkdir "%TAVI_BASE%" 2>nul
if not exist "%TAVI_BASE%" goto base_uncreatable
set "BASE_OURS=yes"
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%" 2>nul

:: The record is written now, not at the end: an install that dies after the
:: environment solve has 3 GB on disk in a folder only the user knows about,
:: and the uninstaller and the Doctor need to be able to find it.
if not exist "%RECORD_DIR%" mkdir "%RECORD_DIR%" 2>nul
:: An unwritable %LOCALAPPDATA% costs the record, never raw cmd errors on screen.
if not exist "%RECORD_DIR%\" goto record_start_skipped
> "%RECORD%" echo TAVI_BASE=%TAVI_BASE%
>> "%RECORD%" echo STATE=installing
>> "%RECORD%" echo INSTALL_ID=%INSTALL_ID%
goto record_start_done
:record_start_skipped
>> "%LOG%" echo [TAVI] [WARN] %RECORD_DIR% could not be created; no install record is kept.
:record_start_done

call :step 0 "Cleaning broken cmd.exe AutoRun hooks" "5 seconds"
reg query "HKCU\Software\Microsoft\Command Processor" /v AutoRun > "%WORK_DIR%\tavi_autorun_hkcu.txt" 2>nul
findstr /i "micromamba mamba" "%WORK_DIR%\tavi_autorun_hkcu.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" goto autorun_clean
call :step_ok "No stale HKCU micromamba AutoRun hook found."
goto autorun_done

:autorun_clean
:: A test run must never change the registry of the machine it runs on.
if defined TEST_FAIL goto autorun_kept
reg delete "HKCU\Software\Microsoft\Command Processor" /v AutoRun /f >nul 2>nul
call :step_ok "Removed HKCU cmd AutoRun hook containing micromamba/mamba."
goto autorun_done

:autorun_kept
call :step_ok "Test run: an HKCU cmd AutoRun hook naming micromamba/mamba was found and left in place."

:autorun_done
del "%WORK_DIR%\tavi_autorun_hkcu.txt" >nul 2>nul

call :step 1 "Setting up micromamba" "30 seconds"
if /i "%TEST_FAIL%"=="micromamba" goto forced_failure
if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
if exist "%MICROMAMBA_EXE%" goto micromamba_ready
echo [INFO] Downloading micromamba %MAMBA_VERSION%...
call :run_logged curl -sS -L -o "%MICROMAMBA_EXE%.tmp" "https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto micromamba_download_failed
certutil -hashfile "%MICROMAMBA_EXE%.tmp" SHA256 | findstr /i /c:"%EXPECTED_SHA256%" >nul
if errorlevel 1 goto micromamba_hash_failed
echo [OK] Micromamba checksum verified.
>> "%LOG%" echo [TAVI] Micromamba checksum verified.
move /Y "%MICROMAMBA_EXE%.tmp" "%MICROMAMBA_EXE%" >nul
if errorlevel 1 goto micromamba_move_failed

:micromamba_ready
if not exist "%MICROMAMBA_EXE%" goto micromamba_missing
call :run_logged "%MICROMAMBA_EXE%" --version
call :step_ok "Micromamba ready."

call :step 2 "Creating the TAVI environment" "15 minutes, longer on a slow internet connection"
if /i "%TEST_FAIL%"=="env" goto forced_failure
echo [INFO] Environment folder: %ENV_PREFIX%
echo [INFO] The download and installation messages go to the log file; a line
echo        below every 30 seconds shows that it is still working.
set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git pyside6 mcstasscript gcc_win-64=16.2.0 msmpi"
>> "%LOG%" echo [TAVI] Environment folder: %ENV_PREFIX%
>> "%LOG%" echo [TAVI] Packages: %CONDA_PACKAGES%
:: Every micromamba call passes -r and -p. A command-line value outranks
:: MAMBA_ROOT_PREFIX, CONDA_PREFIX and every .mambarc, so an inherited conda or
:: mamba setting cannot redirect either choice; --no-rc keeps the user's channel
:: and cache policy out of this environment as well.
:: The heartbeat is stopped on the very next line, before anything reads the
:: exit code, so no way out of the step leaves it printing.
call :hb_start "%MAMBA_ROOT_PREFIX%\pkgs"
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" create -p "%ENV_PREFIX%" %CONDA_PACKAGES% -c conda-forge -c nodefaults -y --no-rc
set "RC=%ERRORLEVEL%" & call :hb_stop
if not "%RC%"=="0" goto env_create_failed

echo [INFO] Checking that the GUI toolkit and McStasScript load...
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto env_smoke_failed
call :step_ok "The TAVI environment is ready."

call :step 3 "Installing TAVI" "a minute"
mkdir "%INSTALL_DIR%" 2>nul
cd /d "%INSTALL_DIR%"
if errorlevel 1 goto install_dir_failed
>> "%LOG%" echo [TAVI] Cloning %CLONE_REF%
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" git clone --branch "%CLONE_REF%" --depth 1 --single-branch https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto clone_failed
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto source_incomplete
if not exist "%INSTALL_DIR%\tavi\mcstas_config.py" goto source_incomplete
:: The launchers come from the checkout, so a release older than 1.4.0 cannot
:: produce this installation. Say so rather than half-building one.
if not exist "%INSTALL_DIR%\installer\launchers\LAYOUT" goto launchers_missing
findstr /x /c:"LAYOUT=%LAYOUT%" "%INSTALL_DIR%\installer\launchers\LAYOUT" >nul
if errorlevel 1 goto launchers_missing
if not exist "%INSTALL_DIR%\installer\launchers\run-tavi.bat" goto launchers_missing
if not exist "%INSTALL_DIR%\installer\launchers\update-tavi.bat" goto launchers_missing
if not exist "%INSTALL_DIR%\installer\launchers\TAVI-Launcher.bat" goto launchers_missing
if not exist "%INSTALL_DIR%\installer\launchers\uninstall-tavi.bat" goto launchers_missing
if not exist "%INSTALL_DIR%\installer\launchers\collect-diagnostics.bat" goto launchers_missing
call :step_ok "TAVI source ready."

call :step 4 "Detecting McStas paths" "30 seconds"
set "MCSTAS_RESOURCES=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS_RESOURCES%" set "MCSTAS_RESOURCES=%ENV_PREFIX%\Library\share\mcstas\resources"
set "MCRUN_DIR=%ENV_PREFIX%\Library\bin"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\Scripts"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\bin"
if not exist "%MCSTAS_RESOURCES%" goto no_resources
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" goto no_mcrun
dir /s /b "%MCSTAS_RESOURCES%\Progress_bar.comp" > "%WORK_DIR%\tavi_progress.txt" 2>nul
findstr /r "." "%WORK_DIR%\tavi_progress.txt" >nul 2>nul
if not "%ERRORLEVEL%"=="0" goto no_progress_bar
del "%WORK_DIR%\tavi_progress.txt" >nul 2>nul
echo [OK] McStas resources: %MCSTAS_RESOURCES%
echo [OK] mcrun directory : %MCRUN_DIR%
>> "%LOG%" echo [TAVI] McStas resources: %MCSTAS_RESOURCES%
>> "%LOG%" echo [TAVI] mcrun directory: %MCRUN_DIR%

> "%WORK_DIR%\tavi_config_mcstas.py" echo import mcstasscript as ms
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c = ms.Configurator()
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c.set_mcrun_path(r"%MCRUN_DIR%")
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c.set_mcstas_path(r"%MCSTAS_RESOURCES%")
>> "%WORK_DIR%\tavi_config_mcstas.py" echo print("[TAVI] McStasScript configured")
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%WORK_DIR%\tavi_config_mcstas.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto mcstasscript_config_failed
del "%WORK_DIR%\tavi_config_mcstas.py" >nul 2>nul
call :step_ok "McStasScript configured."

call :step 5 "Configuring and checking the McStas compiler" "2 minutes"
> "%WORK_DIR%\tavi_gcc_config.py" echo import json, pathlib, shutil, sys
>> "%WORK_DIR%\tavi_gcc_config.py" echo cfg = pathlib.Path(sys.argv[1])          # env's mccode_config.json
>> "%WORK_DIR%\tavi_gcc_config.py" echo backup = cfg.with_name("mccode_config.msvc.json")
>> "%WORK_DIR%\tavi_gcc_config.py" echo if not backup.exists():
>> "%WORK_DIR%\tavi_gcc_config.py" echo     shutil.copy2(cfg, backup)            # the package's MSVC original
>> "%WORK_DIR%\tavi_gcc_config.py" echo data = json.loads(backup.read_text(encoding="utf-8"))
>> "%WORK_DIR%\tavi_gcc_config.py" echo c = data["compilation"]
>> "%WORK_DIR%\tavi_gcc_config.py" echo gcc = "${CONDA_PREFIX}/Library/bin/x86_64-w64-mingw32-gcc.exe"
>> "%WORK_DIR%\tavi_gcc_config.py" echo c["CC"] = gcc
>> "%WORK_DIR%\tavi_gcc_config.py" echo c["MPICC"] = gcc
>> "%WORK_DIR%\tavi_gcc_config.py" echo # paths quoted: mcrun splits these with mslex and a profile may contain a space
>> "%WORK_DIR%\tavi_gcc_config.py" echo c["CFLAGS"] = '-O2 -DNDEBUG -D_POSIX_SOURCE -B"${CONDA_PREFIX}/Library/x86_64-w64-mingw32/sysroot/usr/lib/" -I"${CONDA_PREFIX}/Library/include" -L"${CONDA_PREFIX}/Library/lib"'
>> "%WORK_DIR%\tavi_gcc_config.py" echo c["MPIFLAGS"] = "-DUSE_MPI -lmsmpi"
>> "%WORK_DIR%\tavi_gcc_config.py" echo c["NCRYSTALFLAGS"] = '-I"${CONDA_PREFIX}/include" "${CONDA_PREFIX}/Lib/NCrystal.lib"'
>> "%WORK_DIR%\tavi_gcc_config.py" echo # conda hardlinks package files into the cache and every other env;
>> "%WORK_DIR%\tavi_gcc_config.py" echo # an in-place write would edit them all, so give this env its own file.
>> "%WORK_DIR%\tavi_gcc_config.py" echo cfg.unlink()
>> "%WORK_DIR%\tavi_gcc_config.py" echo cfg.write_text(json.dumps(data, indent=4), encoding="utf-8")
>> "%WORK_DIR%\tavi_gcc_config.py" echo print("[TAVI] McStas compiler set to conda-forge GCC")
:: mcrun reads a per-user config for this environment ahead of the environment's
:: own file. Its name is the basename of CONDA_DEFAULT_ENV, which for a prefix
:: outside an "envs" folder is the prefix's own last component - "tavi-env"
:: here, not "tavi". Getting this name wrong means a stale config from an
:: earlier McStas setup silently overrides the compiler configured below.
set "USER_MCCODE=%USERPROFILE%\AppData\mcstas\%MCSTAS_VERSION%_tavi-env\mccode_config.json"
if not exist "%USER_MCCODE%" goto user_mccode_clear
echo [INFO] Moving aside a per-user McStas config that would override this environment:
echo        %USER_MCCODE%
>> "%LOG%" echo [TAVI] Moving aside %USER_MCCODE%
move /Y "%USER_MCCODE%" "%USER_MCCODE%.bak-%RANDOM%" >nul
if exist "%USER_MCCODE%" goto user_mccode_stuck

:user_mccode_clear
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%WORK_DIR%\tavi_gcc_config.py" "%ENV_PREFIX%\share\mcstas\tools\Python\mccodelib\mccode_config.json"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto gcc_config_failed
del "%WORK_DIR%\tavi_gcc_config.py" >nul 2>nul

if exist "%GATE_DIR%" rd /s /q "%GATE_DIR%"
mkdir "%GATE_DIR%"
:: PSI_DMC rather than PSI_DMC_simple: its PowderN sample requests the NCrystal
:: flags, so the gate exercises every override, not just CC/CFLAGS/MPIFLAGS.
copy /Y "%MCSTAS_RESOURCES%\examples\PSI\PSI_DMC\PSI_DMC.instr" "%GATE_DIR%\" >nul
if errorlevel 1 goto no_example
cd /d "%GATE_DIR%"
:: Each run keeps its own log in compile_check\, which the diagnostics
:: collector and the Doctor read, and is then copied into the install log.
echo [INFO] Compiling and running a test instrument, serial...
call :hb_start
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" mcrun -c PSI_DMC.instr -n 1000 -d serial lambda=2.5666 > "%GATE_DIR%\serial.log" 2>&1 <nul
set "RC=%ERRORLEVEL%" & call :hb_stop
call :append_to_log "%GATE_DIR%\serial.log"
if not "%RC%"=="0" goto gate_serial_failed
echo [INFO] Compiling and running a test instrument, MPI...
call :hb_start
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" mcrun -c --mpi=2 PSI_DMC.instr -n 1000 -d mpi lambda=2.5666 > "%GATE_DIR%\mpi.log" 2>&1 <nul
set "RC=%ERRORLEVEL%" & call :hb_stop
call :append_to_log "%GATE_DIR%\mpi.log"
if not "%RC%"=="0" goto gate_mpi_failed
cd /d "%INSTALL_DIR%"
call :step_ok "Compiler check passed, serial and MPI."

call :step 6 "Building the lead-sample dispersion map" "5 minutes"
set "PB_MAP=ok"
set "PB_MAP_FILE=%INSTALL_DIR%\components\Pb_dft_phonons.dat"
set "PB_MAP_SIZE=0"
if exist "%PB_MAP_FILE%" for %%A in ("%PB_MAP_FILE%") do set "PB_MAP_SIZE=%%~zA"
if %PB_MAP_SIZE% GEQ 100000000 goto pb_map_present
if exist "%PB_MAP_FILE%" del "%PB_MAP_FILE%" >nul 2>nul
echo [INFO] Building components\Pb_dft_phonons.dat: about 150 MB.
call :hb_start
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%INSTALL_DIR%\tools\make_pb_assets.py"
set "RC=%ERRORLEVEL%" & call :hb_stop
if not "%RC%"=="0" goto pb_map_failed
call :step_ok "Lead-sample dispersion map built."
goto pb_map_done

:pb_map_present
call :step_ok "components\Pb_dft_phonons.dat already present."
goto pb_map_done

:pb_map_failed
set "PB_MAP=missing"
del "%PB_MAP_FILE%" >nul 2>nul
echo [WARN] Building the lead-sample dispersion map failed.
echo        TAVI still works. The "Pb: Phonon DFT" sample stays listed, but a run
echo        with it fails at asset load until the map exists. To retry, open the
echo        TAVI shell from the launcher and run:
echo            python tools\make_pb_assets.py
>> "%LOG%" echo [TAVI] [WARN] Building the lead-sample dispersion map failed; the install goes on without it.

:pb_map_done

call :step 7 "Installing the launchers" "5 seconds"
copy /Y "%INSTALL_DIR%\installer\launchers\run-tavi.bat" "%TAVI_BASE%\run-tavi.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\update-tavi.bat" "%TAVI_BASE%\update-tavi.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\TAVI-Launcher.bat" "%TAVI_BASE%\TAVI-Launcher.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\uninstall-tavi.bat" "%TAVI_BASE%\uninstall-tavi.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\collect-diagnostics.bat" "%TAVI_BASE%\collect-diagnostics.bat" >nul
if errorlevel 1 goto launcher_copy_failed

> "%TAVI_BASE%\INSTALL_INFO.txt" echo TAVI_VERSION=%TAVI_VERSION%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo LAYOUT=%LAYOUT%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo INSTALL_ID=%INSTALL_ID%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo INSTALLER_VERSION=%INSTALLER_VERSION%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo PYTHON_VERSION=%PYTHON_VERSION%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo MCSTAS_VERSION=%MCSTAS_VERSION%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo MAMBA_VERSION=%MAMBA_VERSION%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo TAVI_BASE=%TAVI_BASE%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo INSTALL_DIR=%INSTALL_DIR%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo ENV_PREFIX=%ENV_PREFIX%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo MICROMAMBA_DIR=%MICROMAMBA_DIR%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo MAMBA_ROOT_PREFIX=%MAMBA_ROOT_PREFIX%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo RELOCATED=%RELOCATED%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo REPO_URL=https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo PB_MAP=%PB_MAP%
>> "%TAVI_BASE%\INSTALL_INFO.txt" echo COMPILER=gcc_win-64
:: A test install of a branch says so, since TAVI_VERSION names the release.
if defined REF >> "%TAVI_BASE%\INSTALL_INFO.txt" echo CLONED_BRANCH=%REF%

:: The ownership marker is what the uninstaller requires before it deletes
:: anything: a TAVI_PySide6.py sentinel is not enough, because every checkout of
:: the project has one.
> "%MARKER%" echo LAYOUT=%LAYOUT%
>> "%MARKER%" echo INSTALL_ID=%INSTALL_ID%
>> "%MARKER%" echo THIS FOLDER BELONGS TO TAVI. Uninstalling TAVI deletes what is in it.

:: The shortcut's target must be <base>\TAVI-Launcher.bat: the uninstallers
:: remove a desktop copy only when it points there.
set "LNK_TARGET=%TAVI_BASE%\TAVI-Launcher.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($env:SHORTCUT); $s.TargetPath=$env:LNK_TARGET; $s.WorkingDirectory=$env:TAVI_BASE; $s.Description='TAVI Launcher'; $s.Save()" <nul 2>nul

if not exist "%RECORD_DIR%\" goto record_end_done
> "%RECORD%" echo TAVI_BASE=%TAVI_BASE%
>> "%RECORD%" echo STATE=complete
>> "%RECORD%" echo INSTALL_ID=%INSTALL_ID%
:record_end_done

if exist "%SHORTCUT%" goto shortcut_made
echo [WARN] The "TAVI Launcher" shortcut could not be made. Start TAVI by
echo        double-clicking TAVI-Launcher.bat in %TAVI_BASE% instead.
>> "%LOG%" echo [TAVI] [WARN] The shortcut could not be made.
call :step_ok "Launchers installed."
goto launchers_done

:shortcut_made
call :step_ok "Launchers and shortcut created."

:launchers_done

call :step 8 "Running a test simulation with TAVI" "2 minutes"
if /i "%TEST_FAIL%"=="selftest" goto forced_selftest_failure
echo [INFO] TAVI starts without showing a window and simulates one point with
echo        McStas, exactly as it does when you use it.
:: The same environment run-tavi.bat gives TAVI, so the test runs what the
:: student will run.
set "MCSTAS=%MCSTAS_RESOURCES%"
set "MCSTAS_COMPONENT_PATH=%MCSTAS_RESOURCES%"
set "MCSTAS_OVERRIDE="
set "MCSTAS_CFLAGS_OVERRIDE="
set "MCSTAS_CC_OVERRIDE="
set "MCSTAS_MPICC_OVERRIDE="
set "MCSTAS_MPIRUN_OVERRIDE="
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%INSTALL_DIR%"
call :hb_start
call :run_logged "%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python TAVI_PySide6.py --self-test --instrument puma
set "RC=%ERRORLEVEL%" & call :hb_stop
if not "%RC%"=="0" goto selftest_failed
call :step_ok "The test simulation ran."
set "OUTCOME=ok"
goto the_end

:: ---------------------------------------------------------------------------
:: Failure exits. Each says what failed and what to do, then goes to the one
:: ending; none removes anything.
:: ---------------------------------------------------------------------------

:bad_ref
set "STEP_NAME=Reading the test switches"
set "ERR1=The branch given with /ref is not a branch name this installer accepts."
set "ERR2=It may hold only letters, digits, dot, dash, underscore and slash."
set "ERR3="
goto failed

:bad_test_fail
set "STEP_NAME=Reading the test switches"
set "ERR1=/test-fail takes micromamba, env or selftest."
set "ERR2="
set "ERR3="
goto failed

:forced_failure
set "ERR1=forced failure (test run)"
set "ERR2="
set "ERR3="
goto failed

:base_uncreatable
set "ERR1=Could not create the folder: %TAVI_BASE%"
set "ERR2=Create it manually, or choose another folder, and run this again."
set "ERR3="
goto failed

:micromamba_download_failed
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
set "ERR1=Failed to download micromamba."
set "ERR2=Check your internet connection, then run this installer again."
set "ERR3="
goto failed

:micromamba_hash_failed
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
set "ERR1=Micromamba checksum verification failed. Expected SHA256:"
set "ERR2=%EXPECTED_SHA256%"
set "ERR3=The download is discarded. Check your network or proxy and retry."
goto failed

:micromamba_move_failed
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
set "ERR1=Failed to install the verified micromamba executable."
set "ERR2="
set "ERR3="
goto failed

:micromamba_missing
set "ERR1=micromamba.exe not found at %MICROMAMBA_EXE%"
set "ERR2="
set "ERR3="
goto failed

:env_create_failed
set "ERR1=Failed to create the TAVI environment."
set "ERR2=Check your internet connection and free disk space (about 3 GB),"
set "ERR3=then run this installer again."
goto failed

:env_smoke_failed
set "ERR1=PySide6 or McStasScript failed to load in the new environment."
set "ERR2=Run this installer again; it rebuilds the environment from scratch."
set "ERR3="
goto failed

:install_dir_failed
set "ERR1=Could not enter the program folder: %INSTALL_DIR%"
set "ERR2="
set "ERR3="
goto failed

:clone_failed
set "ERR1=Failed to download TAVI from GitHub."
set "ERR2=Check your internet connection, then run this installer again."
set "ERR3="
goto failed

:source_incomplete
set "ERR1=The downloaded TAVI release is incomplete."
set "ERR2=Confirm that %CLONE_REF% exists on GitHub."
set "ERR3="
goto failed

:launchers_missing
set "ERR1=This installer builds a version 1.4.0 installation, but the release it"
set "ERR2=downloaded (%CLONE_REF%) does not carry all of its launchers."
set "ERR3=Use the installer published with that release instead."
goto failed

:no_resources
set "ERR1=McStas resources not found."
set "ERR2=Tried: %MCSTAS_RESOURCES%"
set "ERR3="
goto failed

:no_mcrun
set "ERR1=mcrun not found in the environment."
set "ERR2=Last tried: %MCRUN_DIR%"
set "ERR3="
goto failed

:no_progress_bar
del "%WORK_DIR%\tavi_progress.txt" >nul 2>nul
set "ERR1=Progress_bar.comp was not found under: %MCSTAS_RESOURCES%"
set "ERR2=McStas is installed, but this package layout lacks a component TAVI needs."
set "ERR3="
goto failed

:user_mccode_stuck
set "ERR1=Could not move aside this file, which would override the compiler"
set "ERR2=configured by this installer: %USER_MCCODE%"
set "ERR3=Close programs that may hold it, or rename it by hand, and retry."
goto failed

:mcstasscript_config_failed
set "ERR1=Could not configure McStasScript's McStas paths."
set "ERR2=The lines above say why. Run this installer again; if it repeats,"
set "ERR3=send the diagnostics file."
goto failed

:gcc_config_failed
set "ERR1=Failed to configure the McStas compiler."
set "ERR2="
set "ERR3="
goto failed

:no_example
set "ERR1=Could not find the PSI_DMC example instrument to test-compile."
set "ERR2="
set "ERR3="
goto failed

:gate_serial_failed
cd /d "%TAVI_BASE%"
set "ERR1=The C compiler could not build a McStas instrument."
set "ERR2=Log: %GATE_DIR%\serial.log"
set "ERR3="
goto failed

:gate_mpi_failed
cd /d "%TAVI_BASE%"
set "ERR1=The MPI build or run of a McStas instrument failed. TAVI runs every"
set "ERR2=simulation under MPI, so this installation would not work."
set "ERR3=Log: %GATE_DIR%\mpi.log"
goto failed

:launcher_copy_failed
set "ERR1=Could not copy the launchers into %TAVI_BASE%."
set "ERR2="
set "ERR3="
goto failed

:forced_selftest_failure
set "ERR1=forced failure (test run)"
set "ERR2="
set "ERR3="
goto selftest_failed_said

:selftest_failed
set "ERR1=TAVI could not run its test simulation. The lines above say why."
set "ERR2="
set "ERR3="

:selftest_failed_said
echo [ERROR] %ERR1%
>> "%LOG%" echo [TAVI] [ERROR] %ERR1%
set "OUTCOME=selftest"
goto the_end

:failed
echo [ERROR] %ERR1%
if defined ERR2 echo         %ERR2%
if defined ERR3 echo         %ERR3%
>> "%LOG%" echo [TAVI] [ERROR] %ERR1%
if defined ERR2 >> "%LOG%" echo [TAVI]         %ERR2%
if defined ERR3 >> "%LOG%" echo [TAVI]         %ERR3%
set "OUTCOME=failed"
goto the_end

:cancelled
if "%ANSWER%"=="2" >> "%LOG%" echo [TAVI] Asked: Continue with TAVI installation? Answer: N
if not "%ANSWER%"=="2" >> "%LOG%" echo [TAVI] Asked: Continue with TAVI installation? No answer: the input ended.
set "OUTCOME=cancelled"
goto the_end

:: ---------------------------------------------------------------------------
:: The ending: one routine for every outcome. It never removes anything.
:: Attended, only C closes the window, and a failure also offers D (collect
:: diagnostics, then this screen again). Unattended (/dir) it never waits and
:: opens nothing; the exit code is the outcome.
:: ---------------------------------------------------------------------------
:the_end
:: Backstop: every step stops its own heartbeat, but nothing may print over
:: this screen.
call :hb_stop
set "RC=1"
set "HEADLINE=INSTALLATION FAILED"
if "%OUTCOME%"=="ok" set "RC=0"
if "%OUTCOME%"=="ok" set "HEADLINE=INSTALLATION SUCCEEDED"
if "%OUTCOME%"=="selftest" set "RC=2"
if "%OUTCOME%"=="selftest" set "HEADLINE=TAVI INSTALLED, BUT THE TEST SIMULATION FAILED"
if "%OUTCOME%"=="cancelled" set "RC=0"
if "%OUTCOME%"=="cancelled" set "HEADLINE=INSTALLATION CANCELLED"
set "FAILURE="
if "%OUTCOME%"=="failed" set "FAILURE=yes"
if "%OUTCOME%"=="selftest" set "FAILURE=yes"

:: The failed step's output is at the end of the log, so it is shown before
:: anything else is written there.
if not defined FAILURE goto end_logged
if not defined LOGFILE goto end_logged
echo.
echo The last lines of the installation log:
echo ----------------------------------------------------------------------------
call :show_tail
echo ----------------------------------------------------------------------------

:end_logged
>> "%LOG%" echo.
if defined FAILURE >> "%LOG%" echo [TAVI] Failed step: %STEP_NAME%
>> "%LOG%" echo [TAVI] %HEADLINE%
call :write_status
if "%OUTCOME%"=="ok" call :tidy_work
if "%OUTCOME%"=="selftest" call :tidy_work

call :end_screen
if "%UNATTENDED%"=="yes" goto end_exit
if "%OUTCOME%"=="ok" call :desktop_copy
if "%OUTCOME%"=="selftest" call :desktop_copy
if "%OUTCOME%"=="ok" explorer "%TAVI_BASE%"
if "%OUTCOME%"=="selftest" explorer "%TAVI_BASE%"
if defined FAILURE call :open_notepad
if defined FAILURE goto end_choice
echo.
choice /C C /N /M "Press C to close this window."
goto end_exit

:end_choice
echo.
choice /C CD /N /M "Press D to collect diagnostics for support, or C to close this window."
:: 2 is D. Anything else - C, or input that ran out - closes.
set "ANSWER=%ERRORLEVEL%"
if "%ANSWER%"=="1" >> "%LOG%" echo [TAVI] C pressed: closing.
if not "%ANSWER%"=="2" goto end_exit
>> "%LOG%" echo [TAVI] D pressed: collecting diagnostics.
call :collect
title TAVI Installer
call :end_screen
goto end_choice

:end_exit
endlocal & exit /b %RC%

:end_screen
echo.
echo ============================================================================
echo  %HEADLINE%
echo ============================================================================
if "%OUTCOME%"=="ok" goto end_screen_ok
if "%OUTCOME%"=="cancelled" goto end_screen_cancelled
if "%OUTCOME%"=="selftest" echo TAVI is installed and can be started, but its test simulation did not
if "%OUTCOME%"=="selftest" echo work, so simulations will probably fail too.
echo Failed step : %STEP_NAME%
echo [ERROR] %ERR1%
if defined ERR2 echo         %ERR2%
if defined ERR3 echo         %ERR3%
if "%BASE_OURS%"=="yes" echo TAVI folder : %TAVI_BASE%
if "%BASE_OURS%"=="yes" if "%OLD_REMOVED%"=="yes" echo The old TAVI installation was removed before this install began. Nothing of the new install was removed: what was installed so far is still in that folder.
if "%BASE_OURS%"=="yes" if "%OLD_REMOVED%"=="partly" echo Part of the old TAVI installation could not be removed, and part of it may already have gone. Nothing of the new install was removed: what was installed so far is still in that folder.
if "%BASE_OURS%"=="yes" if not "%OLD_REMOVED%"=="yes" if not "%OLD_REMOVED%"=="partly" echo Nothing was removed: what was installed so far is still in that folder.
call :end_screen_log
if "%UNATTENDED%"=="yes" goto :eof
echo.
echo To get help: press D. It collects everything needed into one file and
echo shows you where it is; send that one file to the person who helps you
echo with TAVI. If D does not work, send the log file named above instead.
goto :eof

:end_screen_ok
echo Installed in : %TAVI_BASE%
echo Program      : %INSTALL_DIR%
echo Environment  : %ENV_PREFIX%
echo TAVI version : %TAVI_VERSION%
if defined REF echo Branch       : %REF% (test installation)
echo Installer    : %INSTALLER_VERSION%
echo McStas       : %MCSTAS_VERSION%
echo Compiler     : GCC (conda-forge)
call :end_screen_log
echo.
if "%PB_MAP%"=="missing" echo [WARN] The lead-sample dispersion map was not built; see the message above.
echo To start TAVI, double-click "TAVI Launcher" in the folder that is about to
echo open. You can move that shortcut anywhere you like - your desktop, for
echo instance - and it will still work. The folder itself must stay where it is.
echo.
echo To remove TAVI later, start the launcher and choose "Uninstall TAVI".
goto :eof

:end_screen_cancelled
if "%OLD_REMOVED%"=="yes" echo The old TAVI installation was removed. Nothing new was installed.
if not "%OLD_REMOVED%"=="yes" echo Nothing was installed and nothing was removed.
call :end_screen_log
goto :eof

:end_screen_log
if defined LOGFILE echo The full record of this installation is saved in:
if defined LOGFILE echo     %LOGFILE%
if not defined LOGFILE echo No log file could be written for this installation.
goto :eof

:: install-status.txt names the outcome, in the install folder - only once this
:: run has made that folder, or been told it may clear it: a folder it refused
:: is not TAVI's to write into.
:write_status
if not "%BASE_OURS%"=="yes" goto :eof
if not exist "%TAVI_BASE%\" goto :eof
set "STATUS=%TAVI_BASE%\install-status.txt"
(> "%STATUS%" echo OUTCOME=%HEADLINE%) 2>nul
if not exist "%STATUS%" goto :eof
if defined FAILURE >> "%STATUS%" echo FAILED_STEP=%STEP_NAME%
if defined FAILURE >> "%STATUS%" echo ERROR=%ERR1%
>> "%STATUS%" echo TAVI_VERSION=%TAVI_VERSION%
>> "%STATUS%" echo INSTALLER_VERSION=%INSTALLER_VERSION%
if defined LOGFILE >> "%STATUS%" echo LOG=%LOGFILE%
>> "%STATUS%" echo STARTED=%LOG_STAMP%
goto :eof

:: The helper scripts' folder goes once the install has finished, after the
:: last heartbeat has let go of its script.
:tidy_work
call :hb_wait
if exist "%WORK_DIR%" rd /s /q "%WORK_DIR%" 2>nul
goto :eof

:open_notepad
if "%UNATTENDED%"=="yes" goto :eof
if not defined LOGFILE goto :eof
set "NOTEPAD=%SystemRoot%\System32\notepad.exe"
if not exist "%NOTEPAD%" set "NOTEPAD=%SystemRoot%\notepad.exe"
if not exist "%NOTEPAD%" goto :eof
:: start, because a batch file waits for a program it runs directly. Notepad
:: is a window of its own, not a console.
start "" "%NOTEPAD%" "%LOGFILE%"
goto :eof

:: ---------------------------------------------------------------------------
:: D on a failure screen: the launcher menu's "Collect diagnostics for
:: support". The installed copy, else the checkout's (it finds the install
:: from there), else - when the install died before TAVI was downloaded - a
:: zip of this log alone.
:: ---------------------------------------------------------------------------
:collect
set "COLLECTOR="
if not "%BASE_OURS%"=="yes" goto collect_log_only
if exist "%TAVI_BASE%\collect-diagnostics.bat" set "COLLECTOR=%TAVI_BASE%\collect-diagnostics.bat"
if not defined COLLECTOR if exist "%TAVI_BASE%\app\installer\launchers\collect-diagnostics.bat" set "COLLECTOR=%TAVI_BASE%\app\installer\launchers\collect-diagnostics.bat"
if not defined COLLECTOR goto collect_log_only
call "%COLLECTOR%"
goto :eof

:collect_log_only
echo.
if not defined LOGFILE echo There is no log file to send; please describe what this window shows.
if not defined LOGFILE goto :eof
call :stamp
set "ZIP_NAME=TAVI-diagnostics-%STAMP%.zip"
set "ZIP=%LOG_HOME%\%ZIP_NAME%"
set "TAR_EXE=%SystemRoot%\System32\tar.exe"
if not exist "%TAR_EXE%" goto collect_no_tar
:: From inside the folder, so tar sees only short ASCII names whatever the
:: user name is.
pushd "%LOG_HOME%"
"%TAR_EXE%" -a -c -f "%ZIP_NAME%" "%LOG_NAME%" >nul 2>nul
popd
if not exist "%ZIP%" goto collect_no_tar
echo The installation log is saved in one file for support:
echo     %ZIP%
echo Please send this one file to the person who helps you with TAVI.
explorer /select,"%ZIP%"
goto :eof

:collect_no_tar
echo Please send this file to the person who helps you with TAVI:
echo     %LOGFILE%
explorer /select,"%LOGFILE%"
goto :eof

:: ---------------------------------------------------------------------------
:: The desktop copy of the shortcut: asked after a success or a failed test
:: simulation, attended only. Enter or Y is Yes. It goes to the desktop
:: Windows reports, which follows OneDrive and policy redirection, unlike
:: %USERPROFILE%\Desktop; TAVI_TEST_DESKTOP replaces it for tests. A failure is
:: one line and changes nothing else.
:: ---------------------------------------------------------------------------
:desktop_copy
if not exist "%SHORTCUT%" goto :eof
echo.
echo Also put a copy of the TAVI Launcher shortcut on your desktop?
set "DESK_ANS="
set /p "DESK_ANS=Press Enter for Yes, or type N and Enter for No: "
if not defined DESK_ANS goto desktop_yes
set DESK_ANS| findstr /i /x /c:"DESK_ANS=N" /c:"DESK_ANS=NO" >nul
if errorlevel 1 goto desktop_yes
>> "%LOG%" echo [TAVI] Asked: Also put a copy of the shortcut on the desktop? Answer: No
goto :eof

:desktop_yes
>> "%LOG%" echo [TAVI] Asked: Also put a copy of the shortcut on the desktop? Answer: Yes
set "DESK_SAID="
for /f "delims=" %%L in ('powershell -NoProfile -NonInteractive -Command "try { $d=$env:TAVI_TEST_DESKTOP; if (-not $d) { $d=[Environment]::GetFolderPath('Desktop') }; if (-not $d) { throw 'Windows reports no desktop folder.' }; $t=[IO.Path]::Combine($d,'TAVI Launcher.lnk'); Copy-Item -LiteralPath $env:SHORTCUT -Destination $t -Force -ErrorAction Stop; '[OK] A copy of the TAVI Launcher shortcut is on your desktop: '+$t } catch { '[INFO] The shortcut could not be copied to your desktop: '+$_.Exception.Message }" ^<nul 2^>nul') do (
    set "DESK_SAID=yes"
    echo %%L
    >> "%LOG%" echo [TAVI] %%L
)
if defined DESK_SAID goto :eof
echo [INFO] The shortcut could not be copied to your desktop; it is in the TAVI folder that opens next.
>> "%LOG%" echo [TAVI] PowerShell did not answer; no desktop copy was made.
goto :eof

:: ---------------------------------------------------------------------------
:: A step's start and end, on screen and in the log.
:: ---------------------------------------------------------------------------
:step
:: %1 = number, %2 = what, %3 = about how long
set "STEP_NAME=%~2"
call :now
echo.
echo [Step %~1/%STEPS%] %~2: about %~3. Started %NOW%.
>> "%LOG%" echo.
>> "%LOG%" echo [TAVI] [Step %~1/%STEPS%] %~2: started %NOW%
goto :eof

:step_ok
call :now
echo [OK] %~1
>> "%LOG%" echo [TAVI] [OK] %~1 Ended %NOW%.
goto :eof

:: HH:MM for the screen only; file names take the PowerShell stamp below.
:now
set "NOW=%TIME:~0,5%"
if "%NOW:~0,1%"==" " set "NOW=0%NOW:~1%"
goto :eof

:: A step's output goes to the log, or to this window when there is no log or
:: the log can no longer be written: a command whose redirection fails is not
:: run at all, and would look like a success. Its input is nul, so no step
:: can stop on a question or take a key meant for one. Its exit code is what
:: this returns.
:run_logged
if not defined LOGFILE goto run_live
(>> "%LOG%" echo.) 2>nul || goto run_live
>> "%LOG%" 2>&1 <nul %*
goto :eof

:run_live
<nul %*
goto :eof

:append_to_log
if not defined LOGFILE goto :eof
if exist "%~1" type "%~1" >> "%LOG%" 2>nul
goto :eof

:: ---------------------------------------------------------------------------
:: The heartbeat: a small script this installer writes into install_work and
:: starts with "start /b", so it shares this window and needs no console of
:: its own. Every 5 seconds it looks for its stop flag; every 30 it prints how
:: long the step has run and, given a package cache, how many MB of packages
:: are in it. It stops itself after six hours whatever happens. Each step
:: gets its own flag, so a heartbeat that has not yet noticed its flag can
:: never be confused with the next step's.
:: Sizes are summed in KB, the last three digits of each byte count dropped:
:: set /a is 32-bit and the cache passes 2 GB. ping waits, because timeout
:: fails when input is redirected; -w 1000 keeps each wait near a second
:: where loopback echo is blocked, which otherwise costs 4 s a ping.
:: shortcut: elapsed time is counted in 5-second ticks and runs a little
:: slow by each loop's own overhead; read the clock if that ever matters.
:: ---------------------------------------------------------------------------
:hb_start
:: %1 = the package cache whose downloads to count, or nothing.
set "HB_CACHE=%~1"
set /a HB_SEQ+=1
set "HB_FLAG=%WORK_DIR%\heartbeat-%HB_SEQ%.stop"
if not defined HB_WRITTEN call :hb_write
if not exist "%HB_SCRIPT%" goto :eof
del /f /q "%HB_FLAG%" >nul 2>nul
set "HB_LIVE=yes"
start "" /b cmd /d /c "%HB_SCRIPT%"
goto :eof

:hb_stop
if not defined HB_LIVE goto :eof
set "HB_LIVE="
(> "%HB_FLAG%" echo stop) 2>nul
goto :eof

:: Up to ten seconds for the last heartbeat to see its flag (it deletes it as
:: it stops), so that its script is not deleted while it runs.
:hb_wait
if not defined HB_FLAG goto :eof
set "HB_TRIES=0"

:hb_wait_loop
if not exist "%HB_FLAG%" goto :eof
set /a HB_TRIES+=1
if %HB_TRIES% GTR 10 goto :eof
"%SystemRoot%\System32\ping.exe" -n 2 -w 1000 127.0.0.1 >nul 2>nul
goto hb_wait_loop

:hb_write
set "HB_WRITTEN=yes"
(> "%HB_SCRIPT%" echo @echo off) 2>nul
if not exist "%HB_SCRIPT%" goto :eof
>> "%HB_SCRIPT%" echo setlocal DisableDelayedExpansion
>> "%HB_SCRIPT%" echo set "T=0"
>> "%HB_SCRIPT%" echo set "N=0"
>> "%HB_SCRIPT%" echo :hb_loop
>> "%HB_SCRIPT%" echo "%%SystemRoot%%\System32\ping.exe" -n 6 -w 1000 127.0.0.1 ^>nul 2^>nul
>> "%HB_SCRIPT%" echo if exist "%%HB_FLAG%%" goto hb_done
>> "%HB_SCRIPT%" echo set /a T+=5
>> "%HB_SCRIPT%" echo if %%T%% GEQ 21600 goto hb_done
>> "%HB_SCRIPT%" echo set /a N+=1
>> "%HB_SCRIPT%" echo if %%N%% LSS 6 goto hb_loop
>> "%HB_SCRIPT%" echo set "N=0"
>> "%HB_SCRIPT%" echo set /a M=T/60
>> "%HB_SCRIPT%" echo set /a S=T-M*60
>> "%HB_SCRIPT%" echo set "MB="
>> "%HB_SCRIPT%" echo if defined HB_CACHE call :hb_mb
>> "%HB_SCRIPT%" echo if exist "%%HB_FLAG%%" goto hb_done
>> "%HB_SCRIPT%" echo if defined MB echo        ... still running, %%M%% min %%S%% s, %%MB%% MB downloaded so far
>> "%HB_SCRIPT%" echo if not defined MB echo        ... still running, %%M%% min %%S%% s
>> "%HB_SCRIPT%" echo goto hb_loop
>> "%HB_SCRIPT%" echo :hb_mb
>> "%HB_SCRIPT%" echo set "KB=0"
>> "%HB_SCRIPT%" echo for %%%%F in ("%%HB_CACHE%%\*.conda" "%%HB_CACHE%%\*.tar.bz2") do call :hb_add "%%%%~zF"
>> "%HB_SCRIPT%" echo set /a MB=KB/1000
>> "%HB_SCRIPT%" echo goto :eof
>> "%HB_SCRIPT%" echo :hb_add
>> "%HB_SCRIPT%" echo set "Z=%%~1"
>> "%HB_SCRIPT%" echo set "Z=%%Z:~0,-3%%"
>> "%HB_SCRIPT%" echo if defined Z set /a KB+=Z
>> "%HB_SCRIPT%" echo goto :eof
>> "%HB_SCRIPT%" echo :hb_done
>> "%HB_SCRIPT%" echo del /f /q "%%HB_FLAG%%" ^>nul 2^>nul
>> "%HB_SCRIPT%" echo exit /b 0
goto :eof

:: ---------------------------------------------------------------------------
:: The install log. It must never be what stops an install: each folder that
:: cannot be written falls through to the next, and with none left LOG is nul
:: and the install goes ahead without one.
:: ---------------------------------------------------------------------------
:open_log
set "LOGFILE="
set "LOG_HOME="
set "LOG_NAME="
call :stamp
set "LOG_DIR="
if defined LOCALAPPDATA set "LOG_DIR=%LOCALAPPDATA%\TAVI\logs"
if defined LOG_DIR if not exist "%LOG_DIR%\" mkdir "%LOG_DIR%" >nul 2>nul
if defined LOG_DIR call :try_log
if defined LOGFILE goto log_opened
set "LOG_DIR=%TEMP%"
if defined LOG_DIR call :try_log

:log_opened
set "LOG=nul"
if defined LOGFILE set "LOG=%LOGFILE%"
if not defined LOGFILE echo [INFO] This installation could not be saved to a log file; it goes ahead without one.
goto :eof

:try_log
if not exist "%LOG_DIR%\" goto :eof
set "TRY_NAME=install-%STAMP%.log"
if exist "%LOG_DIR%\%TRY_NAME%" set "TRY_NAME=install-%STAMP%-%RANDOM%.log"
copy /y nul "%LOG_DIR%\%TRY_NAME%" >nul 2>nul
if not exist "%LOG_DIR%\%TRY_NAME%" goto :eof
set "LOGFILE=%LOG_DIR%\%TRY_NAME%"
set "LOG_HOME=%LOG_DIR%"
set "LOG_NAME=%TRY_NAME%"
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

:: The last 30 lines of the install log, with cmd's own tools only: some
:: managed laptops lock PowerShell down, and this runs when something is
:: already wrong. System32 is named because Git's find.exe can come first on
:: PATH; "| findstr" stops more from pausing at a full screen.
:show_tail
set "LINES=0"
for /f %%N in ('type "%LOGFILE%" ^| "%SystemRoot%\System32\find.exe" /c /v ""') do set "LINES=%%N"
set /a SKIP=LINES-30
if %SKIP% lss 0 set "SKIP=0"
"%SystemRoot%\System32\more.com" +%SKIP% "%LOGFILE%" | findstr "^"
goto :eof

:: ---------------------------------------------------------------------------
:: The system snapshot at the top of the log: what the operator needs to read
:: a failure from far away. No value from the user's environment is expanded
:: onto a command line: paths go through "set NAME", proxy settings through
:: PowerShell, which also blanks any user:password@ part. Without PowerShell
:: the log says which lines are missing, and the install goes on.
:: ---------------------------------------------------------------------------
:snapshot
>> "%LOG%" echo [TAVI] TAVI installer %INSTALLER_VERSION% for TAVI %TAVI_VERSION%; log started %STAMP%
>> "%LOG%" echo [TAVI] ---- System snapshot ----
>> "%LOG%" ver
>> "%LOG%" set USERPROFILE
set "SNAP=no"
if not "%USERPROFILE%"=="%USERPROFILE: =%" set "SNAP=yes"
>> "%LOG%" echo [TAVI] The profile folder has a space in it: %SNAP%
set "SNAP=no"
set USERPROFILE| findstr /r /c:"[^ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:= \\-]" >nul
if not errorlevel 1 set "SNAP=yes"
>> "%LOG%" echo [TAVI] The profile folder has a character other than a letter A-Z, a digit, space, dot, dash or underscore, an accented or non-Latin letter for instance: %SNAP%
set "SNAP_PS="
for /f "delims=" %%L in ('powershell -NoProfile -NonInteractive -Command "try { $p=[Environment]::GetFolderPath('Desktop'); if (-not $p) { $p='none' }; 'Desktop, as Windows reports it: ' + $p } catch { 'Desktop: could not be read' }; foreach ($n in 'HTTP_PROXY','HTTPS_PROXY','NO_PROXY') { $v=[Environment]::GetEnvironmentVariable($n); if ($v) { $n + '=' + ($v -replace '(^|//)[^/]*@','$1<redacted>@') } else { $n + ' is not set' } }" ^<nul 2^>nul') do (
    set "SNAP_PS=yes"
    >> "%LOG%" echo [TAVI] %%L
)
if defined SNAP_PS goto snapshot_rest
>> "%LOG%" echo [TAVI] PowerShell did not answer, so the desktop folder and proxy variables are not recorded.
if defined HTTP_PROXY >> "%LOG%" echo [TAVI] HTTP_PROXY is set; its value is not recorded.
if defined HTTPS_PROXY >> "%LOG%" echo [TAVI] HTTPS_PROXY is set; its value is not recorded.
if defined NO_PROXY >> "%LOG%" echo [TAVI] NO_PROXY is set; its value is not recorded.

:snapshot_rest
if defined TAVI_TEST_DESKTOP >> "%LOG%" echo [TAVI] TAVI_TEST_DESKTOP is set: this is a test run, and it stands in for the desktop.
>> "%LOG%" echo [TAVI] WinHTTP proxy:
:: <nul on every program here: none of them may read an answer meant for a
:: question below.
>> "%LOG%" 2>&1 netsh winhttp show proxy <nul
>> "%LOG%" echo [TAVI] conda, mamba or micromamba on PATH:
>> "%LOG%" 2>&1 "%SystemRoot%\System32\where.exe" conda mamba micromamba <nul
if defined CONDA_PREFIX >> "%LOG%" set CONDA_PREFIX
if not defined CONDA_PREFIX >> "%LOG%" echo [TAVI] CONDA_PREFIX is not set
if defined MAMBA_ROOT_PREFIX >> "%LOG%" set MAMBA_ROOT_PREFIX
if not defined MAMBA_ROOT_PREFIX >> "%LOG%" echo [TAVI] MAMBA_ROOT_PREFIX is not set
>> "%LOG%" echo [TAVI] ---- End of the system snapshot ----
goto :eof

:: The rest of the snapshot, once the install folder is known and vetted.
:snapshot_base
>> "%LOG%" echo [TAVI] Install folder: %TAVI_BASE%
set "SNAP_PS="
for /f "delims=" %%L in ('powershell -NoProfile -NonInteractive -Command "try { $d=New-Object IO.DriveInfo($env:TAVI_BASE.Substring(0,1)); 'Free space on ' + $d.Name + ': ' + [math]::Round($d.AvailableFreeSpace/1GB,1) + ' GB' } catch { 'Free space: could not be read' }" ^<nul 2^>nul') do (
    set "SNAP_PS=yes"
    >> "%LOG%" echo [TAVI] %%L
)
if defined SNAP_PS goto :eof
:: Without PowerShell, dir's own summary line, in the system's language.
set "FREE_LINE="
for /f "delims=" %%L in ('dir "%TAVI_BASE:~0,2%\" 2^>nul') do set "FREE_LINE=%%L"
if defined FREE_LINE >> "%LOG%" set FREE_LINE
goto :eof

:read_install_identity
:: Sets ID_OK=yes only when <base>\.tavi-install-root and <base>\INSTALL_INFO.txt
:: agree on INSTALL_ID and the layout is this installer's. The same test the
:: uninstaller makes before it deletes anything: a marker on its own is not
:: proof of ownership, and this branch authorises a recursive delete.
set "ID_OK=no"
set "RI_MARK="
set "RI_INFO="
set "RI_LAYOUT="
if not exist "%TAVI_BASE%\.tavi-install-root" goto :eof
if not exist "%TAVI_BASE%\INSTALL_INFO.txt" goto :eof
for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\.tavi-install-root") do if /i "%%A"=="INSTALL_ID" set "RI_MARK=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="INSTALL_ID" set "RI_INFO=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%TAVI_BASE%\INSTALL_INFO.txt") do if /i "%%A"=="LAYOUT" set "RI_LAYOUT=%%B"
if not defined RI_MARK goto :eof
if not defined RI_INFO goto :eof
:: Both IDs come from text files in that folder. The installer writes
:: INSTALL_ID as four random numbers joined by dashes; anything else does not
:: check out, and is refused before the comparison expands it. "set NAME|"
:: hands the value to findstr without cmd parsing it; digits are listed, not
:: ranged, because findstr resolves a range through the machine collation.
set RI_MARK| findstr /r /x /c:"RI_MARK=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto :eof
set RI_INFO| findstr /r /x /c:"RI_INFO=[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*-[0123456789][0123456789]*" >nul
if errorlevel 1 goto :eof
if /i not "%RI_MARK%"=="%RI_INFO%" goto :eof
:: The layout too is read from the file: matched exactly, through the pipe.
set RI_LAYOUT 2>nul| findstr /x /c:"RI_LAYOUT=%LAYOUT%" >nul
if errorlevel 1 goto :eof
set "ID_OK=yes"
goto :eof

:read_record_state
:: %1 = the base being considered. Sets REC_PARTIAL=yes when the install record
:: names this same folder and says an install was still in progress. The record
:: only ever locates; the decision it feeds is "offer to clear", never "delete".
set "REC_PARTIAL=no"
set "VBPATH="
set "REC_STATE="
if not exist "%LOCALAPPDATA%\TAVI\install-record.txt" goto :eof
:: The record is a file the user can edit, so neither value is expanded raw:
:: the base goes straight into VBPATH and is vetted by :validate_base_var, and
:: the state is read through a pipe. %1 was validated before it got here, so a
:: record value that does not validate cannot name this folder.
for /f "usebackq tokens=1,* delims==" %%A in ("%LOCALAPPDATA%\TAVI\install-record.txt") do if /i "%%A"=="TAVI_BASE" set "VBPATH=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%LOCALAPPDATA%\TAVI\install-record.txt") do if /i "%%A"=="STATE" set "REC_STATE=%%B"
call :validate_base_var
if defined VB_REASON goto :eof
if /i not "%VBPATH%"=="%~1" goto :eof
set REC_STATE 2>nul| findstr /x /c:"REC_STATE=installing" >nul
if errorlevel 1 goto :eof
set "REC_PARTIAL=yes"
goto :eof

:confirm_wipe
:: %1 = folder that will be removed, %2 = the folder holding output\ and config\
:: Sets WIPE_OK=yes only on an explicit Y. Removing an old installation destroys
:: the same scan results an uninstall does, so it asks the same way. An
:: unattended run (/dir) never removes one, and never waits to be asked.
set "WIPE_OK=no"
set "CW_BASE=%~1"
set "CW_APP=%~2"
if "%UNATTENDED%"=="yes" goto confirm_wipe_unattended
echo.
echo This deletes everything in:
echo     %CW_BASE%
if exist "%CW_APP%\output" echo     including your scan results in %CW_APP%\output
if exist "%CW_APP%\config" echo     including your saved settings in %CW_APP%\config
echo None of it can be recovered. Copy out anything you want to keep first.
echo.
choice /C YN /N /M "Delete the old installation and continue? (Y/N): "
set "ANSWER=%ERRORLEVEL%"
if not "%ANSWER%"=="1" goto confirm_wipe_no
>> "%LOG%" echo [TAVI] Asked: Delete the old installation and continue? Answer: Y
dir /b "%CW_APP%\output" 2>nul | findstr /r "." >nul
if errorlevel 1 goto confirm_wipe_yes
echo.
choice /C YN /N /M "Your saved scan results will be deleted too. Continue? (Y/N): "
set "ANSWER=%ERRORLEVEL%"
if not "%ANSWER%"=="1" goto confirm_wipe_no
>> "%LOG%" echo [TAVI] Asked: Your saved scan results will be deleted too. Continue? Answer: Y

:confirm_wipe_yes
set "WIPE_OK=yes"
goto :eof

:confirm_wipe_no
if "%ANSWER%"=="2" >> "%LOG%" echo [TAVI] Answer: N, so nothing was removed.
if not "%ANSWER%"=="2" >> "%LOG%" echo [TAVI] No answer: the input ended, so nothing was removed.
goto :eof

:confirm_wipe_unattended
echo [INFO] Started with /dir, which never removes an installation that is
echo        already there. Nothing was removed.
>> "%LOG%" echo [TAVI] /dir never removes an existing installation; nothing was removed.
goto :eof

:: ---------------------------------------------------------------------------
:: The desktop copy of the shortcut, removed only when it is this
:: installation's: its target must be <base>\TAVI-Launcher.bat. Any other
:: "TAVI Launcher" shortcut there is another installation's or the user's, and
:: is named and left. Windows is asked where the desktop is, because OneDrive
:: and university policies move it away from %USERPROFILE%\Desktop. The whole
:: decision is made inside PowerShell from environment variables, so no path
:: is ever re-parsed by cmd. Without PowerShell, or where it is locked down,
:: this is one line and changes nothing. DESK_LEGACY, when a caller sets it,
:: is one more folder to look in.
:: Keep this routine identical in WINDOWS-uninstall-TAVI.bat.
:: ---------------------------------------------------------------------------
:remove_desktop_shortcut
set "DESK_SAID="
for /f "delims=" %%L in ('powershell -NoProfile -NonInteractive -Command "try { $want=[IO.Path]::GetFullPath([IO.Path]::Combine($env:TAVI_BASE,'TAVI-Launcher.bat')); $dirs=@(); if ($env:TAVI_TEST_DESKTOP) { $dirs+=$env:TAVI_TEST_DESKTOP } else { $dirs+=[Environment]::GetFolderPath('Desktop') }; if ($env:DESK_LEGACY) { $dirs+=$env:DESK_LEGACY }; $sh=New-Object -ComObject WScript.Shell; $seen=@{}; $found=$false; foreach ($d in $dirs) { if (-not $d) { continue }; $p=[IO.Path]::GetFullPath([IO.Path]::Combine($d,'TAVI Launcher.lnk')); if ($seen.ContainsKey($p) -or -not (Test-Path -LiteralPath $p)) { continue }; $seen[$p]=1; $found=$true; $t=$sh.CreateShortcut($p).TargetPath; if ($t -and [IO.Path]::GetFullPath($t) -eq $want) { Remove-Item -LiteralPath $p -Force -ErrorAction Stop; '[OK] Removed the TAVI Launcher shortcut from the desktop: '+$p } else { '[INFO] Left the shortcut '+$p+' in place: it does not open this TAVI installation.' } }; if (-not $found) { '[INFO] There is no TAVI Launcher shortcut on the desktop.' } } catch { '[WARN] The desktop could not be checked for a TAVI Launcher shortcut: '+$_.Exception.Message }" ^<nul 2^>nul') do (
    set "DESK_SAID=yes"
    echo %%L
    >> "%LOG%" echo %%L
)
if defined DESK_SAID goto :eof
echo [INFO] The desktop could not be checked for a TAVI Launcher shortcut, so any shortcut there was left in place.
>> "%LOG%" echo [TAVI] PowerShell did not answer; the desktop was not checked.
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
:: Keep :validate_base byte-identical in every file that carries it; the
:: list is VALIDATE_BASE_COPIES in tests\test_installer_launchers.py, which
:: asserts that they match. It is duplicated rather than shared because each
:: of those files has to work alone:
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
