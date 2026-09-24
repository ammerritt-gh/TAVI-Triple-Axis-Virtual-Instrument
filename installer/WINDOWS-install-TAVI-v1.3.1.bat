@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows installer - release-pinned v1.3.1
:: (build 1, 2026-09-17: one chosen install folder, environment selected by
::  prefix, launchers shipped instead of generated, uninstall from the menu)
:: Derived from WINDOWS-install-TAVI-v1.3.0.bat build 4 per the release recipe
:: in TAVI_Windows_Installer_Uninstaller_Design_Document.md section 22.
:: Conservative batch style: no micromamba shell init, no generated echo blocks,
:: no delayed expansion, and no nested cmd AutoRun dependency except where
:: unavoidable.

set "TAVI_VERSION=v1.3.1"
set "INSTALLER_VERSION=v1.3.1-1"
set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"
set "LAYOUT=2"

:: /validate-only <path> prints ACCEPT or REFUSE <reason> and changes nothing,
:: so tests can drive :validate_base over a table of paths in this real file.
if /i "%~1"=="/validate-only" goto validate_only

:: /dir <path> answers the install-folder question without asking, for an
:: unattended run - the cold install that the release checklist requires before
:: this file is published. The path is validated exactly as a typed one, and a
:: refusal stops rather than re-prompting, because there may be no one to ask.
:: It does not skip the confirmation, and it never approves removing an
:: installation that is already there.
set "PRESET_BASE="
if /i "%~1"=="/dir" set "PRESET_BASE=%~2"
set "UNATTENDED=no"
if defined PRESET_BASE set "UNATTENDED=yes"

:: Everything lives under one folder the user chooses. Layout 2:
::   <base>\app            the pinned checkout, output\ and config\
::   <base>\tavi-env       Python, McStas, GCC, MS-MPI
::   <base>\micromamba     micromamba.exe
::   <base>\mamba          package cache (root prefix)
::   <base>\compile_check  the install-time compile gate and its logs
::   <base>\*.bat          the four launchers, copied from the checkout
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
title TAVI Installer

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
if "%RELOCATED%"=="no" goto ask_base
echo [INFO] Your Windows profile folder cannot hold TAVI:
echo            %USERPROFILE%
echo        McStas cannot compile or run from a path with a space or an
echo        accented character in it, so the suggested folder below is outside
echo        your profile. This is normal, and nothing else is affected.
echo.

:ask_base
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
set "VBPATH="
if defined PRESET_BASE set "VBPATH=%PRESET_BASE%"
if defined VBPATH goto base_given
:: Straight into VBPATH: set /p stores what was typed without parsing it, and
:: :validate_base_var vets it there. Going through `call :validate_base "%VAR%"`
:: would expand the raw value onto a command line first, where a quote in it
:: ends the quoted region and the rest becomes commands.
set /p "VBPATH=Install folder: "

:base_given
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
goto retry_base

:: Every path that would ask for another folder comes through here. An
:: unattended run has nobody to ask, and must not loop on the one folder it was
:: given - including when a confirmation it cannot answer leaves an existing
:: installation in place, which is the behaviour we want: /dir never removes one.
:retry_base
if "%UNATTENDED%"=="yes" goto unattended_stop
goto ask_base

:unattended_stop
echo [INFO] Started with /dir, so there is nobody to ask for another folder.
pause
exit /b 1

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
goto retry_base

:base_has_tavi_ok
echo.
echo [INFO] There is already a TAVI installation in:
echo            %TAVI_BASE%
echo        It will be removed and installed again from scratch.
set "OLD_APP=%TAVI_BASE%\app"
call :confirm_wipe "%TAVI_BASE%" "%OLD_APP%"
if not "%WIPE_OK%"=="yes" goto retry_base
if exist "%TAVI_BASE%\app" rd /s /q "%TAVI_BASE%\app" 2>nul
if exist "%TAVI_BASE%\tavi-env" rd /s /q "%TAVI_BASE%\tavi-env" 2>nul
if exist "%TAVI_BASE%\compile_check" rd /s /q "%TAVI_BASE%\compile_check" 2>nul
if exist "%TAVI_BASE%\app" goto wipe_failed
if exist "%TAVI_BASE%\tavi-env" goto wipe_failed
goto base_ready

:base_has_partial
echo.
echo [INFO] An earlier installation into this folder did not finish:
echo            %TAVI_BASE%
echo        Its half-built program folder and environment will be cleared and
echo        built again. The packages already downloaded are kept, so this is
echo        much quicker than starting over.
call :confirm_wipe "%TAVI_BASE%" "%TAVI_BASE%\app"
if not "%WIPE_OK%"=="yes" goto retry_base
if exist "%TAVI_BASE%\app" rd /s /q "%TAVI_BASE%\app" 2>nul
if exist "%TAVI_BASE%\tavi-env" rd /s /q "%TAVI_BASE%\tavi-env" 2>nul
if exist "%TAVI_BASE%\compile_check" rd /s /q "%TAVI_BASE%\compile_check" 2>nul
if exist "%TAVI_BASE%\app" goto wipe_failed
if exist "%TAVI_BASE%\tavi-env" goto wipe_failed
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
goto retry_base

:base_has_legacy
echo.
echo [INFO] There is a TAVI installation from before version 1.3.1 in:
echo            %TAVI_BASE%
echo        Version 1.3.1 keeps the program in an "app" folder inside it, so
echo        the old installation has to be removed first.
call :confirm_wipe "%TAVI_BASE%" "%TAVI_BASE%"
if not "%WIPE_OK%"=="yes" goto retry_base
rd /s /q "%TAVI_BASE%" 2>nul
if exist "%TAVI_BASE%" goto wipe_failed
:: An installation from before 1.3.1 also put a shortcut on the desktop; it
:: would dangle now that the launcher lives in the install folder.
if exist "%USERPROFILE%\Desktop\TAVI Launcher.lnk" del /f /q "%USERPROFILE%\Desktop\TAVI Launcher.lnk" >nul 2>nul
goto base_ready

:wipe_failed
echo.
echo [ERROR] The old installation could not be removed. Close TAVI, Explorer
echo         windows and command prompts using that folder, then try again.
echo         Folder: %TAVI_BASE%
pause
exit /b 1

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
set "SHORTCUT=%TAVI_BASE%\TAVI Launcher.lnk"
set "MARKER=%TAVI_BASE%\.tavi-install-root"
set "RECORD_DIR=%LOCALAPPDATA%\TAVI"
set "RECORD=%RECORD_DIR%\install-record.txt"
set "INSTALL_ID=%RANDOM%-%RANDOM%-%RANDOM%-%RANDOM%"

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
echo.
echo This installer will NOT run micromamba shell init.
echo This installer will NOT touch any other conda or micromamba environment.
echo This installer may remove a broken cmd.exe AutoRun hook only if it contains
echo micromamba or mamba text from a previous failed install.
echo.
echo Note: the installation cannot be moved afterwards - the environment stores
echo its own location internally. The shortcut can be moved anywhere you like.
echo.
choice /C YN /N /M "Continue with TAVI installation? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto cancelled

if not exist "%TAVI_BASE%" mkdir "%TAVI_BASE%" 2>nul
if not exist "%TAVI_BASE%" goto base_uncreatable
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%" 2>nul

:: The record is written now, not at the end: an install that dies after the
:: environment solve has 3 GB on disk in a folder only the user knows about,
:: and the uninstaller and the Doctor need to be able to find it.
if not exist "%RECORD_DIR%" mkdir "%RECORD_DIR%" 2>nul
> "%RECORD%" echo TAVI_BASE=%TAVI_BASE%
>> "%RECORD%" echo STATE=installing
>> "%RECORD%" echo INSTALL_ID=%INSTALL_ID%

echo.
echo [Step 0/7] Cleaning broken cmd.exe AutoRun hooks...
reg query "HKCU\Software\Microsoft\Command Processor" /v AutoRun > "%WORK_DIR%\tavi_autorun_hkcu.txt" 2>nul
findstr /i "micromamba mamba" "%WORK_DIR%\tavi_autorun_hkcu.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" goto autorun_clean
echo [OK] No stale HKCU micromamba AutoRun hook found.
goto autorun_done

:autorun_clean
reg delete "HKCU\Software\Microsoft\Command Processor" /v AutoRun /f >nul 2>nul
echo [OK] Removed HKCU cmd AutoRun hook containing micromamba/mamba.

:autorun_done
del "%WORK_DIR%\tavi_autorun_hkcu.txt" >nul 2>nul
echo.

echo [Step 1/7] Setting up micromamba...
if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
if exist "%MICROMAMBA_EXE%" goto micromamba_ready
echo [INFO] Downloading micromamba %MAMBA_VERSION%...
curl -L -o "%MICROMAMBA_EXE%.tmp" "https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
if errorlevel 1 goto micromamba_download_failed
certutil -hashfile "%MICROMAMBA_EXE%.tmp" SHA256 | findstr /i /c:"%EXPECTED_SHA256%" >nul
if errorlevel 1 goto micromamba_hash_failed
echo [OK] Micromamba checksum verified.
move /Y "%MICROMAMBA_EXE%.tmp" "%MICROMAMBA_EXE%" >nul
if errorlevel 1 goto micromamba_move_failed

:micromamba_ready
if not exist "%MICROMAMBA_EXE%" goto micromamba_missing
"%MICROMAMBA_EXE%" --version
echo [OK] Micromamba ready.
echo.

echo [Step 2/7] Creating the TAVI environment...
echo [INFO] Environment folder: %ENV_PREFIX%
set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git pyside6 mcstasscript gcc_win-64=16.2.0 msmpi"
echo [INFO] Packages:
echo        %CONDA_PACKAGES%
:: Every micromamba call passes -r and -p. A command-line value outranks
:: MAMBA_ROOT_PREFIX, CONDA_PREFIX and every .mambarc, so an inherited conda or
:: mamba setting cannot redirect either choice; --no-rc keeps the user's channel
:: and cache policy out of this environment as well.
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" create -p "%ENV_PREFIX%" %CONDA_PACKAGES% -c conda-forge -c nodefaults -y --no-rc
if errorlevel 1 goto env_create_failed

echo [INFO] Checking that the GUI toolkit and McStasScript load...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
if errorlevel 1 goto env_smoke_failed
echo.

echo [Step 3/7] Installing TAVI...
mkdir "%INSTALL_DIR%" 2>nul
cd /d "%INSTALL_DIR%"
if errorlevel 1 goto install_dir_failed
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" git clone --branch "%TAVI_VERSION%" --depth 1 --single-branch https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
if errorlevel 1 goto clone_failed
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" goto source_incomplete
if not exist "%INSTALL_DIR%\tavi\mcstas_config.py" goto source_incomplete
:: The launchers come from the checkout, so a release older than 1.3.1 cannot
:: produce a layout-2 installation. Say so rather than half-building one.
if not exist "%INSTALL_DIR%\installer\launchers\LAYOUT" goto launchers_missing
findstr /x /c:"LAYOUT=%LAYOUT%" "%INSTALL_DIR%\installer\launchers\LAYOUT" >nul
if errorlevel 1 goto launchers_missing
echo [OK] TAVI source ready.
echo.

echo [Step 4/7] Detecting McStas paths...
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

> "%WORK_DIR%\tavi_config_mcstas.py" echo import mcstasscript as ms
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c = ms.Configurator()
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c.set_mcrun_path(r"%MCRUN_DIR%")
>> "%WORK_DIR%\tavi_config_mcstas.py" echo c.set_mcstas_path(r"%MCSTAS_RESOURCES%")
>> "%WORK_DIR%\tavi_config_mcstas.py" echo print("[TAVI] McStasScript configured")
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%WORK_DIR%\tavi_config_mcstas.py"
if errorlevel 1 goto mcstasscript_config_failed
del "%WORK_DIR%\tavi_config_mcstas.py" >nul 2>nul
echo.

echo [Step 5/7] Configuring and checking the McStas compiler...
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
move /Y "%USER_MCCODE%" "%USER_MCCODE%.bak-%RANDOM%" >nul
if exist "%USER_MCCODE%" goto user_mccode_stuck

:user_mccode_clear
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%WORK_DIR%\tavi_gcc_config.py" "%ENV_PREFIX%\share\mcstas\tools\Python\mccodelib\mccode_config.json"
if errorlevel 1 goto gcc_config_failed
del "%WORK_DIR%\tavi_gcc_config.py" >nul 2>nul

if exist "%GATE_DIR%" rd /s /q "%GATE_DIR%"
mkdir "%GATE_DIR%"
:: PSI_DMC rather than PSI_DMC_simple: its PowderN sample requests the NCrystal
:: flags, so the gate exercises every override, not just CC/CFLAGS/MPIFLAGS.
copy /Y "%MCSTAS_RESOURCES%\examples\PSI\PSI_DMC\PSI_DMC.instr" "%GATE_DIR%\" >nul
if errorlevel 1 goto no_example
cd /d "%GATE_DIR%"
echo [INFO] Compiling and running a test instrument, serial...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" mcrun -c PSI_DMC.instr -n 1000 -d serial lambda=2.5666 > "%GATE_DIR%\serial.log" 2>&1
if errorlevel 1 goto gate_serial_failed
echo [INFO] Compiling and running a test instrument, MPI...
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" mcrun -c --mpi=2 PSI_DMC.instr -n 1000 -d mpi lambda=2.5666 > "%GATE_DIR%\mpi.log" 2>&1
if errorlevel 1 goto gate_mpi_failed
echo [OK] Compiler check passed, serial and MPI.
cd /d "%INSTALL_DIR%"
echo.

echo [Step 6/7] Building the lead-sample dispersion map...
set "PB_MAP=ok"
set "PB_MAP_FILE=%INSTALL_DIR%\components\Pb_dft_phonons.dat"
set "PB_MAP_SIZE=0"
if exist "%PB_MAP_FILE%" for %%A in ("%PB_MAP_FILE%") do set "PB_MAP_SIZE=%%~zA"
if %PB_MAP_SIZE% GEQ 100000000 goto pb_map_present
if exist "%PB_MAP_FILE%" del "%PB_MAP_FILE%" >nul 2>nul
echo [INFO] Building components\Pb_dft_phonons.dat: about 150 MB, a few minutes,
echo        with no output until it finishes. Please wait.
"%MICROMAMBA_EXE%" -r "%MAMBA_ROOT_PREFIX%" run -p "%ENV_PREFIX%" python "%INSTALL_DIR%\tools\make_pb_assets.py"
if errorlevel 1 goto pb_map_failed
echo [OK] Lead-sample dispersion map built.
goto pb_map_done

:pb_map_present
echo [OK] components\Pb_dft_phonons.dat already present.
goto pb_map_done

:pb_map_failed
set "PB_MAP=missing"
del "%PB_MAP_FILE%" >nul 2>nul
echo [WARN] Building the lead-sample dispersion map failed.
echo        TAVI still works. The "Pb: Phonon DFT" sample stays listed, but a run
echo        with it fails at asset load until the map exists. To retry, open the
echo        TAVI shell from the launcher and run:
echo            python tools\make_pb_assets.py

:pb_map_done
echo.

echo [Step 7/7] Installing the launchers...
copy /Y "%INSTALL_DIR%\installer\launchers\run-tavi.bat" "%TAVI_BASE%\run-tavi.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\update-tavi.bat" "%TAVI_BASE%\update-tavi.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\TAVI-Launcher.bat" "%TAVI_BASE%\TAVI-Launcher.bat" >nul
if errorlevel 1 goto launcher_copy_failed
copy /Y "%INSTALL_DIR%\installer\launchers\uninstall-tavi.bat" "%TAVI_BASE%\uninstall-tavi.bat" >nul
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

:: The ownership marker is what the uninstaller requires before it deletes
:: anything: a TAVI_PySide6.py sentinel is not enough, because every checkout of
:: the project has one.
> "%MARKER%" echo LAYOUT=%LAYOUT%
>> "%MARKER%" echo INSTALL_ID=%INSTALL_ID%
>> "%MARKER%" echo THIS FOLDER BELONGS TO TAVI. Uninstalling TAVI deletes what is in it.

set "LNK_TARGET=%TAVI_BASE%\TAVI-Launcher.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($env:SHORTCUT); $s.TargetPath=$env:LNK_TARGET; $s.WorkingDirectory=$env:TAVI_BASE; $s.Description='TAVI Launcher'; $s.Save()" 2>nul

> "%RECORD%" echo TAVI_BASE=%TAVI_BASE%
>> "%RECORD%" echo STATE=complete
>> "%RECORD%" echo INSTALL_ID=%INSTALL_ID%

if exist "%WORK_DIR%" rd /s /q "%WORK_DIR%" 2>nul
echo [OK] Launchers and shortcut created.
echo.
echo ============================================================================
echo Installation complete.
echo.
echo Installed in : %TAVI_BASE%
echo Program      : %INSTALL_DIR%
echo Environment  : %ENV_PREFIX%
echo TAVI version : %TAVI_VERSION%
echo Installer    : %INSTALLER_VERSION%
echo McStas       : %MCSTAS_VERSION%
echo Compiler     : GCC (conda-forge)
echo ============================================================================
echo.
echo To start TAVI, double-click "TAVI Launcher" in the folder that is about to
echo open. You can move that shortcut anywhere you like - your desktop, for
echo instance - and it will still work. The folder itself must stay where it is.
echo.
echo To remove TAVI later, start the launcher and choose "Uninstall TAVI".
echo.
if "%PB_MAP%"=="missing" echo [WARN] The lead-sample dispersion map was not built; see the message above.
if "%UNATTENDED%"=="no" explorer "%TAVI_BASE%"
:: Opening the folder is the point of the feature, but a run started with
:: /dir has no one watching, and a test should never put a window on screen.
pause
endlocal
exit /b 0

:: ---------------------------------------------------------------------------
:: Failure exits. Each says what failed and what to do; none leaves the user
:: guessing which step they are in.
:: ---------------------------------------------------------------------------

:cancelled
echo Installation cancelled.
pause
exit /b 0

:base_uncreatable
echo [ERROR] Could not create the folder:
echo         %TAVI_BASE%
echo [INFO] Create it manually, or choose another folder, and run this again.
pause
exit /b 1

:micromamba_download_failed
echo [ERROR] Failed to download micromamba.
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
pause
exit /b 1

:micromamba_hash_failed
echo [ERROR] Micromamba checksum verification failed.
echo         Expected SHA256: %EXPECTED_SHA256%
echo [INFO] The download is discarded. Check your network or proxy and retry.
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
pause
exit /b 1

:micromamba_move_failed
echo [ERROR] Failed to install the verified micromamba executable.
del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
pause
exit /b 1

:micromamba_missing
echo [ERROR] micromamba.exe not found at %MICROMAMBA_EXE%
pause
exit /b 1

:env_create_failed
echo [ERROR] Failed to create the TAVI environment.
echo [INFO] Check your internet connection and free disk space (about 3 GB),
echo        then run this installer again.
pause
exit /b 1

:env_smoke_failed
echo [ERROR] PySide6 or McStasScript failed to load in the new environment.
echo [INFO] Run this installer again; it rebuilds the environment from scratch.
pause
exit /b 1

:install_dir_failed
echo [ERROR] Could not enter the program folder: %INSTALL_DIR%
pause
exit /b 1

:clone_failed
echo [ERROR] Failed to download TAVI from GitHub.
echo [INFO] Check your internet connection, then run this installer again.
pause
exit /b 1

:source_incomplete
echo [ERROR] The downloaded TAVI release is incomplete.
echo [INFO] Confirm that the tag %TAVI_VERSION% exists on GitHub.
pause
exit /b 1

:launchers_missing
echo [ERROR] This installer builds the version 1.3.1 folder layout, but the
echo         release it downloaded (%TAVI_VERSION%) does not carry the matching
echo         launchers.
echo [INFO] Use the installer published with that release instead.
pause
exit /b 1

:no_resources
echo [ERROR] McStas resources not found.
echo         Tried: %MCSTAS_RESOURCES%
pause
exit /b 1

:no_mcrun
echo [ERROR] mcrun not found in the environment.
echo         Last tried: %MCRUN_DIR%
pause
exit /b 1

:no_progress_bar
echo [ERROR] Progress_bar.comp was not found under:
echo         %MCSTAS_RESOURCES%
echo [INFO] McStas is installed, but this package layout lacks a component TAVI needs.
del "%WORK_DIR%\tavi_progress.txt" >nul 2>nul
pause
exit /b 1

:user_mccode_stuck
echo [ERROR] Could not move aside this file:
echo         %USER_MCCODE%
echo         It would override the compiler configured by this installer.
echo [INFO] Close programs that may hold it, or rename it by hand, and retry.
pause
exit /b 1

:mcstasscript_config_failed
echo [ERROR] Could not configure McStasScript's McStas paths.
echo [INFO]  The message above says why. Run this installer again; if it
echo         repeats, report it with that message.
pause
exit /b 1

:gcc_config_failed
echo [ERROR] Failed to configure the McStas compiler.
pause
exit /b 1

:no_example
echo [ERROR] Could not find the PSI_DMC example instrument to test-compile.
pause
exit /b 1

:gate_serial_failed
echo [ERROR] The C compiler could not build a McStas instrument.
echo         Log: %GATE_DIR%\serial.log
cd /d "%TAVI_BASE%"
pause
exit /b 1

:gate_mpi_failed
echo [ERROR] The MPI build or run of a McStas instrument failed. TAVI runs every
echo         simulation under MPI, so this installation would not work.
echo         Log: %GATE_DIR%\mpi.log
cd /d "%TAVI_BASE%"
pause
exit /b 1

:launcher_copy_failed
echo [ERROR] Could not copy the launchers into %TAVI_BASE%.
pause
exit /b 1

:: ---------------------------------------------------------------------------
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
if /i not "%RI_MARK%"=="%RI_INFO%" goto :eof
if not "%RI_LAYOUT%"=="%LAYOUT%" goto :eof
set "ID_OK=yes"
goto :eof

:read_record_state
:: %1 = the base being considered. Sets REC_PARTIAL=yes when the install record
:: names this same folder and says an install was still in progress. The record
:: only ever locates; the decision it feeds is "offer to clear", never "delete".
set "REC_PARTIAL=no"
set "REC_BASE="
set "REC_STATE="
if not exist "%LOCALAPPDATA%\TAVI\install-record.txt" goto :eof
for /f "usebackq tokens=1,* delims==" %%A in ("%LOCALAPPDATA%\TAVI\install-record.txt") do if /i "%%A"=="TAVI_BASE" set "REC_BASE=%%B"
for /f "usebackq tokens=1,* delims==" %%A in ("%LOCALAPPDATA%\TAVI\install-record.txt") do if /i "%%A"=="STATE" set "REC_STATE=%%B"
if not defined REC_BASE goto :eof
if /i not "%REC_BASE%"=="%~1" goto :eof
if not "%REC_STATE%"=="installing" goto :eof
set "REC_PARTIAL=yes"
goto :eof

:confirm_wipe
:: %1 = folder that will be removed, %2 = the folder holding output\ and config\
:: Sets WIPE_OK=yes only on an explicit Y. Removing an old installation destroys
:: the same scan results an uninstall does, so it asks the same way.
set "WIPE_OK=no"
set "CW_BASE=%~1"
set "CW_APP=%~2"
echo.
echo This deletes everything in:
echo     %CW_BASE%
if exist "%CW_APP%\output" echo     including your scan results in %CW_APP%\output
if exist "%CW_APP%\config" echo     including your saved settings in %CW_APP%\config
echo None of it can be recovered. Copy out anything you want to keep first.
echo.
choice /C YN /N /M "Delete the old installation and continue? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto :eof
dir /b "%CW_APP%\output" 2>nul | findstr /r "." >nul
if errorlevel 1 goto confirm_wipe_yes
echo.
choice /C YN /N /M "Your saved scan results will be deleted too. Continue? (Y/N): "
if not "%ERRORLEVEL%"=="1" goto :eof

:confirm_wipe_yes
set "WIPE_OK=yes"
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
