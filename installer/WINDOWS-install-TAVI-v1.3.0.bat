@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows installer - release-pinned v1.3.0
:: (build 4, 2026-09-17: space-safe install paths)
:: (build 3, 2026-09-15: conda-forge GCC, no Visual Studio)
:: Conservative batch style: no micromamba shell init, no generated echo blocks,
:: no delayed expansion, and no nested cmd AutoRun dependency except where unavoidable.

set "TAVI_VERSION=v1.3.0"
set "INSTALLER_VERSION=v1.3.0-4"
set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"

set "ENV_NAME=tavi"

:: McStas cannot run from a path containing a space. Its own launchers expand an
:: unquoted %BINDIR%: with a profile like "C:\Users\Jane Doe" the mcrun.bat command
:: splits at the space and python is handed "C:\Users\Jane" as the script to run.
:: Every .bat in the McStas bin directory has this (measured on a user's machine,
:: 2026-09-17; upstream bug, not TAVI's). So when the profile carries a space, the
:: environment, the source and the compile gate all move to a space-free base.
::
:: INSTALL_DIR must stay a directory of its own with nothing nested inside it:
:: the clone requires it empty, and the "not a Git repository" branch below moves
:: whatever it finds there aside -- which would carry off the environment.
set "TAVI_BASE=%USERPROFILE%"
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "GATE_DIR=%TEMP%\tavi_compile_check"
set "RELOCATED=no"

if not "%USERPROFILE%"=="%USERPROFILE: =%" goto relocate_base
if not "%TEMP%"=="%TEMP: =%" goto relocate_gate
goto paths_ready

:relocate_base
set "TAVI_BASE=%SystemDrive%\TAVI-Data"
set "INSTALL_DIR=%SystemDrive%\TAVI-Data\TAVI"
set "MICROMAMBA_DIR=%SystemDrive%\TAVI-Data\micromamba"
set "MAMBA_ROOT_PREFIX=%SystemDrive%\TAVI-Data\mamba"
set "GATE_DIR=%SystemDrive%\TAVI-Data\compile_check"
set "RELOCATED=yes"
goto paths_ready

:relocate_gate
:: Profile is clean but %TEMP% is not; only the compile gate needs moving.
set "GATE_DIR=%SystemDrive%\TAVI-Data\compile_check"
set "RELOCATED=gate"
goto paths_ready

:paths_ready
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"

if not exist "%TAVI_BASE%" mkdir "%TAVI_BASE%" 2>nul
if not exist "%TAVI_BASE%" (
    echo [ERROR] Could not create the TAVI base folder:
    echo         %TAVI_BASE%
    echo [INFO] Create that folder manually, then run this installer again.
    pause
    exit /b 1
)

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

if "%RELOCATED%"=="yes" (
    echo [INFO] Your Windows profile folder contains a space:
    echo            %USERPROFILE%
    echo        McStas cannot compile or run from a path containing a space, so
    echo        TAVI and its environment will be installed under:
    echo            %TAVI_BASE%
    echo        This is normal and nothing else on your machine is affected.
    echo.
)
if "%RELOCATED%"=="gate" (
    echo [INFO] Your temporary folder contains a space, so the compile check will
    echo        run under %TAVI_BASE% instead.
    echo.
)

echo This installer will set up TAVI for this Windows user account.
echo.
echo It will do the following:
echo   1. Install or reuse micromamba at:
echo      %MICROMAMBA_DIR%
echo   2. Create or rebuild the micromamba environment:
echo      %ENV_NAME%
echo      A C compiler (GCC from conda-forge) is installed with it; Visual Studio is not needed.
echo   3. Install or update TAVI at:
echo      %INSTALL_DIR%
echo   4. Configure McStas/McStasScript paths for the installed environment.
echo   5. Configure and compile-check the McStas compiler.
echo   6. Build the lead-sample dispersion map (150 MB, a few minutes).
echo   7. Create run/update/launcher scripts inside the TAVI folder.
echo.
echo This installer will NOT run micromamba shell init.
echo This installer will NOT remove your whole micromamba installation.
echo This installer may remove a broken cmd.exe AutoRun hook only if it contains
echo micromamba or mamba text from a previous failed install.
echo.
echo If an existing '%ENV_NAME%' environment is found it is removed and rebuilt
echo from scratch. Package downloads are cached, so a rebuild is much faster
echo than the first install.
echo If a broken non-conda folder exists at the target environment path, you will
echo be asked whether to move it aside before creating a new environment.
echo.
choice /C YN /M "Continue with TAVI installation"
if errorlevel 2 (
    echo Installation cancelled.
    pause
    exit /b 0
)
echo.
echo [Step 0/7] Cleaning broken cmd.exe AutoRun hooks...
reg query "HKCU\Software\Microsoft\Command Processor" /v AutoRun > "%TEMP%\tavi_autorun_hkcu.txt" 2>nul
findstr /i "micromamba mamba" "%TEMP%\tavi_autorun_hkcu.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    reg delete "HKCU\Software\Microsoft\Command Processor" /v AutoRun /f >nul 2>nul
    echo [OK] Removed HKCU cmd AutoRun hook containing micromamba/mamba.
) else (
    echo [OK] No stale HKCU micromamba AutoRun hook found.
)
del "%TEMP%\tavi_autorun_hkcu.txt" >nul 2>nul
echo.

echo [Step 1/7] Setting up micromamba...
if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
if not exist "%MICROMAMBA_EXE%" (
    echo [INFO] Downloading micromamba %MAMBA_VERSION%...
    curl -L -o "%MICROMAMBA_EXE%.tmp" "https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
    if errorlevel 1 (
        echo [ERROR] Failed to download micromamba.
        del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
        pause
        exit /b 1
    )
    certutil -hashfile "%MICROMAMBA_EXE%.tmp" SHA256 | findstr /i /c:"%EXPECTED_SHA256%" >nul
    if errorlevel 1 (
        echo [ERROR] Micromamba checksum verification failed.
        echo         Expected SHA256: %EXPECTED_SHA256%
        echo [INFO] The download is discarded. Check your network or proxy and retry.
        del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
        pause
        exit /b 1
    )
    echo [OK] Micromamba checksum verified.
    move /Y "%MICROMAMBA_EXE%.tmp" "%MICROMAMBA_EXE%" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to install verified micromamba executable.
        del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
        pause
        exit /b 1
    )
)
if not exist "%MICROMAMBA_EXE%" (
    echo [ERROR] micromamba.exe not found at %MICROMAMBA_EXE%
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" --version
echo [OK] Micromamba ready.
echo.

echo [Step 2/7] Creating or rebuilding environment '%ENV_NAME%'...
set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git pyside6 mcstasscript gcc_win-64=16.2.0 msmpi"

:: Detect by the conda-meta history file, not by "micromamba env list":
:: its lines are indented, so an anchored findstr never matched (found 2026-09-15).
if exist "%ENV_PREFIX%\conda-meta\history" (
    echo [INFO] Environment '%ENV_NAME%' already exists; rebuilding it from scratch.
    goto remove_env
)

if exist "%ENV_PREFIX%" goto broken_prefix
goto create_env

:broken_prefix
echo [WARN] A non-conda or incomplete folder already exists at:
echo        %ENV_PREFIX%
echo [INFO] This is the exact condition that causes libmamba's error:
echo        Non-conda folder exists at prefix - aborting.
choice /C YN /M "Move this broken folder aside and create a fresh environment"
if errorlevel 2 (
    echo [ERROR] Cannot create the environment while this folder exists.
    echo [INFO] Manually rename or delete:
    echo        %ENV_PREFIX%
    pause
    exit /b 1
)
set "BROKEN_ENV_BACKUP=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%_broken_%RANDOM%_%RANDOM%"
echo [INFO] Moving broken environment folder to:
echo        %BROKEN_ENV_BACKUP%
move "%ENV_PREFIX%" "%BROKEN_ENV_BACKUP%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to move broken environment folder.
    echo [INFO] Close terminals, Explorer windows, or editors using this path and retry.
    pause
    exit /b 1
)
goto create_env

:remove_env
echo [INFO] Removing existing '%ENV_NAME%' environment...
"%MICROMAMBA_EXE%" env remove -n %ENV_NAME% -y
if errorlevel 1 echo [WARN] Environment removal reported an error; continuing.
set "REMOVED_ENV_BACKUP=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%_old_%RANDOM%_%RANDOM%"
if exist "%ENV_PREFIX%" (
    echo [WARN] Environment folder still exists after removal.
    echo [INFO] Moving leftover folder to:
    echo        %REMOVED_ENV_BACKUP%
    move "%ENV_PREFIX%" "%REMOVED_ENV_BACKUP%" >nul
    if errorlevel 1 (
        echo [ERROR] Failed to move leftover environment folder.
        pause
        exit /b 1
    )
)

:create_env
echo [INFO] Creating environment with packages:
echo        %CONDA_PACKAGES%
"%MICROMAMBA_EXE%" create -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
if errorlevel 1 (
    echo [ERROR] Failed to create environment.
    pause
    exit /b 1
)
goto smoke_check

:smoke_check
echo [INFO] Checking that the GUI toolkit and McStasScript load...
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python -c "from PySide6.QtWidgets import QApplication; import mcstasscript; QApplication([]); print('[OK] PySide6 and McStasScript load.')"
if errorlevel 1 (
    echo [ERROR] PySide6 or McStasScript failed to load in environment '%ENV_NAME%'.
    echo [INFO] Run this installer again; it rebuilds the environment from scratch.
    pause
    exit /b 1
)
echo.

echo [Step 3/7] Installing or updating TAVI source...
if exist "%INSTALL_DIR%\.git" goto update_repo
if exist "%INSTALL_DIR%" goto backup_existing
goto clone_repo

:backup_existing
echo [WARN] %INSTALL_DIR% exists but is not a Git repository.
set "BACKUP_DIR=%TAVI_BASE%\TAVI_backup_%RANDOM%_%RANDOM%"
echo [INFO] Moving existing folder to: %BACKUP_DIR%
move "%INSTALL_DIR%" "%BACKUP_DIR%" >nul 2>nul
if exist "%INSTALL_DIR%" (
    echo [ERROR] Could not move existing TAVI folder.
    echo [INFO] Close Explorer/editors/terminals using %INSTALL_DIR%, or manually rename it.
    pause
    exit /b 1
)
goto clone_repo

:update_repo
echo [INFO] Existing TAVI Git repository found.
echo [INFO] Pinning checkout to release tag %TAVI_VERSION%...
cd /d "%INSTALL_DIR%"
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git fetch --tags origin
if errorlevel 1 (
    echo [ERROR] Failed to fetch tags from GitHub.
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git checkout "%TAVI_VERSION%"
if errorlevel 1 (
    echo [ERROR] Failed to check out release tag %TAVI_VERSION%.
    echo [INFO] Confirm the tag exists on GitHub before running this installer.
    pause
    exit /b 1
)
goto verify_repo

:clone_repo
mkdir "%INSTALL_DIR%" 2>nul
cd /d "%INSTALL_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not enter install directory: %INSTALL_DIR%
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git clone --branch "%TAVI_VERSION%" --depth 1 --single-branch https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
if errorlevel 1 (
    echo [ERROR] Failed to clone TAVI.
    pause
    exit /b 1
)

:verify_repo
if not exist "%INSTALL_DIR%\TAVI_PySide6.py" (
    echo [ERROR] TAVI_PySide6.py not found after clone/update.
    pause
    exit /b 1
)
if not exist "%INSTALL_DIR%\tavi\mcstas_config.py" (
    echo [ERROR] tavi\mcstas_config.py not found after clone/update.
    echo [INFO] This release tag is incomplete or the file was not committed.
    pause
    exit /b 1
)
echo [OK] TAVI source ready.
echo.

echo [Step 4/7] Detecting McStas paths...
echo [INFO] Using environment prefix:
echo        %ENV_PREFIX%

set "MCSTAS_RESOURCES=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS_RESOURCES%" set "MCSTAS_RESOURCES=%ENV_PREFIX%\Library\share\mcstas\resources"

set "MCRUN_DIR=%ENV_PREFIX%\Library\bin"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\Scripts"
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" set "MCRUN_DIR=%ENV_PREFIX%\bin"

if not exist "%MCSTAS_RESOURCES%" (
    echo [ERROR] McStas resources not found.
    echo         Tried: %MCSTAS_RESOURCES%
    pause
    exit /b 1
)
if not exist "%MCRUN_DIR%\mcrun.bat" if not exist "%MCRUN_DIR%\mcrun.exe" (
    echo [ERROR] mcrun not found in expected environment directories.
    echo         Last tried: %MCRUN_DIR%
    pause
    exit /b 1
)

dir /s /b "%MCSTAS_RESOURCES%\Progress_bar.comp" > "%TEMP%\tavi_progress.txt" 2>nul
findstr /r "." "%TEMP%\tavi_progress.txt" >nul 2>nul
if not "%ERRORLEVEL%"=="0" (
    echo [ERROR] Progress_bar.comp was not found under:
    echo         %MCSTAS_RESOURCES%
    echo [INFO] McStas is installed, but this package layout/version lacks the component TAVI requests.
    del "%TEMP%\tavi_progress.txt" >nul 2>nul
    pause
    exit /b 1
)
del "%TEMP%\tavi_progress.txt" >nul 2>nul

echo [OK] McStas resources: %MCSTAS_RESOURCES%
echo [OK] mcrun directory : %MCRUN_DIR%

> "%TEMP%\tavi_config_mcstas.py" echo import mcstasscript as ms
>> "%TEMP%\tavi_config_mcstas.py" echo c = ms.Configurator()
>> "%TEMP%\tavi_config_mcstas.py" echo c.set_mcrun_path(r"%MCRUN_DIR%")
>> "%TEMP%\tavi_config_mcstas.py" echo c.set_mcstas_path(r"%MCSTAS_RESOURCES%")
>> "%TEMP%\tavi_config_mcstas.py" echo print("[TAVI] McStasScript configured")
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python "%TEMP%\tavi_config_mcstas.py"
del "%TEMP%\tavi_config_mcstas.py" >nul 2>nul
echo.

echo [Step 5/7] Configuring and checking the McStas compiler...
> "%TEMP%\tavi_gcc_config.py" echo import json, pathlib, shutil, sys
>> "%TEMP%\tavi_gcc_config.py" echo cfg = pathlib.Path(sys.argv[1])          # env's mccode_config.json
>> "%TEMP%\tavi_gcc_config.py" echo backup = cfg.with_name("mccode_config.msvc.json")
>> "%TEMP%\tavi_gcc_config.py" echo if not backup.exists():
>> "%TEMP%\tavi_gcc_config.py" echo     shutil.copy2(cfg, backup)            # the package's MSVC original
>> "%TEMP%\tavi_gcc_config.py" echo data = json.loads(backup.read_text(encoding="utf-8"))
>> "%TEMP%\tavi_gcc_config.py" echo c = data["compilation"]
>> "%TEMP%\tavi_gcc_config.py" echo gcc = "${CONDA_PREFIX}/Library/bin/x86_64-w64-mingw32-gcc.exe"
>> "%TEMP%\tavi_gcc_config.py" echo c["CC"] = gcc
>> "%TEMP%\tavi_gcc_config.py" echo c["MPICC"] = gcc
>> "%TEMP%\tavi_gcc_config.py" echo # paths quoted: mcrun splits these with mslex and a profile may contain a space
>> "%TEMP%\tavi_gcc_config.py" echo c["CFLAGS"] = '-O2 -DNDEBUG -D_POSIX_SOURCE -B"${CONDA_PREFIX}/Library/x86_64-w64-mingw32/sysroot/usr/lib/" -I"${CONDA_PREFIX}/Library/include" -L"${CONDA_PREFIX}/Library/lib"'
>> "%TEMP%\tavi_gcc_config.py" echo c["MPIFLAGS"] = "-DUSE_MPI -lmsmpi"
>> "%TEMP%\tavi_gcc_config.py" echo c["NCRYSTALFLAGS"] = '-I"${CONDA_PREFIX}/include" "${CONDA_PREFIX}/Lib/NCrystal.lib"'
>> "%TEMP%\tavi_gcc_config.py" echo # conda hardlinks package files into the cache and every other env;
>> "%TEMP%\tavi_gcc_config.py" echo # an in-place write would edit them all, so give this env its own file.
>> "%TEMP%\tavi_gcc_config.py" echo cfg.unlink()
>> "%TEMP%\tavi_gcc_config.py" echo cfg.write_text(json.dumps(data, indent=4), encoding="utf-8")
>> "%TEMP%\tavi_gcc_config.py" echo print("[TAVI] McStas compiler set to conda-forge GCC")
:: McStas reads a per-user config for this env name ahead of the env's own file;
:: a stale one (a previous McStas setup) would override the compiler set below.
set "USER_MCCODE=%USERPROFILE%\AppData\mcstas\%MCSTAS_VERSION%_%ENV_NAME%\mccode_config.json"
if exist "%USER_MCCODE%" (
    echo [INFO] Moving aside a per-user McStas config that would override this environment:
    echo        %USER_MCCODE%
    move /Y "%USER_MCCODE%" "%USER_MCCODE%.bak-%RANDOM%" >nul
)
if exist "%USER_MCCODE%" (
    echo [ERROR] Could not move that file aside. It would override the compiler
    echo         configured below. Close programs that may hold it, or rename it, and retry.
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python "%TEMP%\tavi_gcc_config.py" "%ENV_PREFIX%\share\mcstas\tools\Python\mccodelib\mccode_config.json"
if errorlevel 1 (
    echo [ERROR] Failed to configure the McStas compiler.
    pause
    exit /b 1
)
del "%TEMP%\tavi_gcc_config.py" >nul 2>nul

:: GATE_DIR is resolved at the top of this script: %TEMP% normally, or a
:: space-free folder when %TEMP% or the profile carries a space.
if exist "%GATE_DIR%" rmdir /s /q "%GATE_DIR%"
mkdir "%GATE_DIR%"
:: PSI_DMC rather than PSI_DMC_simple: its PowderN sample requests the NCrystal
:: flags, so the gate exercises every override, not just CC/CFLAGS/MPIFLAGS.
copy /Y "%MCSTAS_RESOURCES%\examples\PSI\PSI_DMC\PSI_DMC.instr" "%GATE_DIR%\" >nul
if errorlevel 1 (
    echo [ERROR] Could not find the PSI_DMC example instrument to test-compile.
    pause
    exit /b 1
)
cd /d "%GATE_DIR%"
echo [INFO] Compiling and running a test instrument, serial...
"%MICROMAMBA_EXE%" run -n %ENV_NAME% mcrun -c PSI_DMC.instr -n 1000 -d serial lambda=2.5666 > "%GATE_DIR%\serial.log" 2>&1
if errorlevel 1 (
    echo [ERROR] The C compiler could not build a McStas instrument.
    echo         Log: %GATE_DIR%\serial.log
    cd /d "%INSTALL_DIR%"
    pause
    exit /b 1
)
echo [INFO] Compiling and running a test instrument, MPI...
"%MICROMAMBA_EXE%" run -n %ENV_NAME% mcrun -c --mpi=2 PSI_DMC.instr -n 1000 -d mpi lambda=2.5666 > "%GATE_DIR%\mpi.log" 2>&1
if errorlevel 1 (
    echo [ERROR] The MPI build or run of a McStas instrument failed. TAVI runs every
    echo         simulation under MPI, so this installation would not work.
    echo         Log: %GATE_DIR%\mpi.log
    cd /d "%INSTALL_DIR%"
    pause
    exit /b 1
)
echo [OK] Compiler check passed, serial and MPI.
cd /d "%INSTALL_DIR%"
echo.

echo [Step 6/7] Building the lead-sample dispersion map...
set "PB_MAP=ok"
set "PB_MAP_FILE=%INSTALL_DIR%\components\Pb_dft_phonons.dat"
set "PB_MAP_SIZE=0"
if exist "%PB_MAP_FILE%" for %%A in ("%PB_MAP_FILE%") do set "PB_MAP_SIZE=%%~zA"
if %PB_MAP_SIZE% GEQ 100000000 (
    echo [OK] components\Pb_dft_phonons.dat already present.
    goto pb_map_done
)
if exist "%PB_MAP_FILE%" (
    echo [WARN] components\Pb_dft_phonons.dat is truncated; rebuilding it.
    del "%PB_MAP_FILE%" >nul 2>nul
)
echo [INFO] Building components\Pb_dft_phonons.dat: about 150 MB, a few minutes,
echo        with no output until it finishes. Please wait.
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python "%INSTALL_DIR%\tools\make_pb_assets.py"
if errorlevel 1 (
    set "PB_MAP=missing"
    del "%PB_MAP_FILE%" >nul 2>nul
    echo [WARN] Building the lead-sample dispersion map failed.
    echo        TAVI still works. The "Pb: Phonon DFT" sample stays listed, but a run
    echo        with it fails at asset load until the map exists. To retry, open the
    echo        TAVI shell from the launcher and run:
    echo            python tools\make_pb_assets.py
) else (
    echo [OK] Lead-sample dispersion map built.
)
:pb_map_done
echo.

echo [Step 7/7] Creating launchers...
set "RUN_SCRIPT=%INSTALL_DIR%\run-tavi.bat"
set "UPDATE_SCRIPT=%INSTALL_DIR%\update-tavi.bat"
set "LAUNCHER_SCRIPT=%INSTALL_DIR%\TAVI-Launcher.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCmNkIC9kICJfX0lOU1RBTExfRElSX18iCnNldCAiTUNTVEFTPV9fTUNTVEFTX1JFU09VUkNFU19fIgpzZXQgIk1DU1RBU19DT01QT05FTlRfUEFUSD0lTUNTVEFTJSIKZWNobyBbVEFWSV0gTUNTVEFTPSVNQ1NUQVMlCgppZiBub3QgZXhpc3QgIiVNQ1NUQVMlIiAoCiAgICBlY2hvIFtFUlJPUl0gTWNTdGFzIHJlc291cmNlIGRpcmVjdG9yeSBub3QgZm91bmQ6CiAgICBlY2hvICAgICAgICAgJU1DU1RBUyUKICAgIHBhdXNlCiAgICBleGl0IC9iIDEKKQoKIl9fTUlDUk9NQU1CQV9FWEVfXyIgcnVuIC1uIF9fRU5WX05BTUVfXyBweXRob24gVEFWSV9QeVNpZGU2LnB5CmlmIGVycm9ybGV2ZWwgMSBwYXVzZQplbmRsb2NhbAo=')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__MCSTAS_RESOURCES__',$env:MCSTAS_RESOURCES); Set-Content -Path $env:RUN_SCRIPT -Value $s -Encoding ASCII"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCmNkIC9kICJfX0lOU1RBTExfRElSX18iCmVjaG8gPT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PQplY2hvICAgICAgICAgICAgICAgICAgICAgICBUQVZJIFJlcGFpciBTY3JpcHQKZWNobyAgICAgICAgICAgICAgICAgICAgICAgUmVsZWFzZTogX19UQVZJX1ZFUlNJT05fXwplY2hvID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0KZWNoby4KZWNobyBUaGlzIGluc3RhbGxhdGlvbiBpcyBwaW5uZWQgdG8gcmVsZWFzZSB0YWcgX19UQVZJX1ZFUlNJT05fXy4KZWNobyBUaGlzIHNjcmlwdCByZXBhaXJzL3JlLWNoZWNrcyB0aGF0IGV4YWN0IHRhZy4gSXQgZG9lcyBub3QgcHVsbCBtYWluLgplY2hvLgplY2hvIFtJTkZPXSBGZXRjaGluZyB0YWdzIGZyb20gR2l0SHViLi4uCiJfX01JQ1JPTUFNQkFfRVhFX18iIHJ1biAtbiBfX0VOVl9OQU1FX18gZ2l0IGZldGNoIC0tdGFncyBvcmlnaW4KaWYgZXJyb3JsZXZlbCAxIGdvdG8gOmZhaWwKCmVjaG8gW0lORk9dIENoZWNraW5nIG91dCBfX1RBVklfVkVSU0lPTl9fLi4uCiJfX01JQ1JPTUFNQkFfRVhFX18iIHJ1biAtbiBfX0VOVl9OQU1FX18gZ2l0IGNoZWNrb3V0ICJfX1RBVklfVkVSU0lPTl9fIgppZiBlcnJvcmxldmVsIDEgZ290byA6ZmFpbAoKZWNobyBbSU5GT10gQ2hlY2tpbmcgdGhhdCB0aGUgR1VJIHRvb2xraXQgYW5kIE1jU3Rhc1NjcmlwdCBsb2FkLi4uCiJfX01JQ1JPTUFNQkFfRVhFX18iIHJ1biAtbiBfX0VOVl9OQU1FX18gcHl0aG9uIC1jICJmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRQXBwbGljYXRpb247IGltcG9ydCBtY3N0YXNzY3JpcHQ7IFFBcHBsaWNhdGlvbihbXSk7IHByaW50KCdbT0tdIFB5U2lkZTYgYW5kIE1jU3Rhc1NjcmlwdCBsb2FkLicpIgppZiBlcnJvcmxldmVsIDEgZ290byA6ZW52ZmFpbAoKZWNoby4KZWNobyBbT0tdIFJlcGFpciBjb21wbGV0ZS4gSW5zdGFsbGVkIHNvdXJjZSByZW1haW5zIHBpbm5lZCB0byBfX1RBVklfVkVSU0lPTl9fLgplY2hvIFRvIHVwZ3JhZGUgdG8gYSBuZXdlciBUQVZJIHJlbGVhc2UsIGRvd25sb2FkIHRoYXQgcmVsZWFzZSdzIGluc3RhbGxlci4KcGF1c2UKZXhpdCAvYiAwCgo6ZW52ZmFpbAplY2hvIFtFUlJPUl0gVGhlICdfX0VOVl9OQU1FX18nIGVudmlyb25tZW50IGlzIGJyb2tlbi4gUnVuIHRoZSBUQVZJIGluc3RhbGxlciBhZ2FpbjsgaXQgcmVidWlsZHMgdGhlIGVudmlyb25tZW50LgpwYXVzZQpleGl0IC9iIDEKCjpmYWlsCmVjaG8gW0VSUk9SXSBSZXBhaXIgZmFpbGVkLiBDaGVjayB5b3VyIGludGVybmV0IGNvbm5lY3Rpb24sIGxvY2FsIGNoYW5nZXMsIG9yIHdoZXRoZXIgdGhlIHRhZyBleGlzdHMgb24gR2l0SHViLgpwYXVzZQpleGl0IC9iIDEK')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__TAVI_VERSION__',$env:TAVI_VERSION); Set-Content -Path $env:UPDATE_SCRIPT -Value $s -Encoding ASCII"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCnRpdGxlIFRBVkkgTGF1bmNoZXIKCjptZW51CmNscwplY2hvID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0KZWNobyAgICAgICAgICAgICAgICAgICAgICAgICBUQVZJIExhdW5jaGVyCmVjaG8gICAgICAgICAgICAgICAgICBUcmlwbGUgQXhpcyBWaXJ0dWFsIEluc3RydW1lbnQKZWNobyAgICAgICAgICAgICAgICAgIFJlbGVhc2U6IF9fVEFWSV9WRVJTSU9OX18KZWNobyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09CmVjaG8uCmVjaG8gICBbMV0gUnVuIFRBVkkKZWNobyAgIFsyXSBVcGRhdGUgVEFWSQplY2hvICAgWzNdIE9wZW4gVEFWSSBmb2xkZXIKZWNobyAgIFs0XSBPcGVuIFRBVkkgc2hlbGwKZWNobyAgIFs1XSBFeGl0CmVjaG8uCmNob2ljZSAvQyAxMjM0NSAvTSAiU2VsZWN0IG9wdGlvbiIKaWYgZXJyb3JsZXZlbCA1IGV4aXQgL2IgMAppZiBlcnJvcmxldmVsIDQgZ290byA6c2hlbGwKaWYgZXJyb3JsZXZlbCAzIGdvdG8gOmZvbGRlcgppZiBlcnJvcmxldmVsIDIgZ290byA6dXBkYXRlCmlmIGVycm9ybGV2ZWwgMSBnb3RvIDpydW4KZ290byA6bWVudQoKOnJ1bgpjYWxsICJfX1JVTl9TQ1JJUFRfXyIKZ290byA6bWVudQoKOnVwZGF0ZQpjYWxsICJfX1VQREFURV9TQ1JJUFRfXyIKZ290byA6bWVudQoKOmZvbGRlcgpleHBsb3JlciAiX19JTlNUQUxMX0RJUl9fIgpnb3RvIDptZW51Cgo6c2hlbGwKY2QgL2QgIl9fSU5TVEFMTF9ESVJfXyIKIl9fTUlDUk9NQU1CQV9FWEVfXyIgcnVuIC1uIF9fRU5WX05BTUVfXyBjbWQgL2sKZ290byA6bWVudQo=')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__TAVI_VERSION__',$env:TAVI_VERSION).Replace('__RUN_SCRIPT__',$env:RUN_SCRIPT).Replace('__UPDATE_SCRIPT__',$env:UPDATE_SCRIPT); Set-Content -Path $env:LAUNCHER_SCRIPT -Value $s -Encoding ASCII"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($env:SHORTCUT); $s.TargetPath=$env:LAUNCHER_SCRIPT; $s.WorkingDirectory=$env:INSTALL_DIR; $s.Description='TAVI Launcher'; $s.Save()" 2>nul

echo [OK] Launcher scripts created.
echo TAVI_VERSION=%TAVI_VERSION%> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo INSTALLER_VERSION=%INSTALLER_VERSION%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo PYTHON_VERSION=%PYTHON_VERSION%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo MCSTAS_VERSION=%MCSTAS_VERSION%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo MAMBA_VERSION=%MAMBA_VERSION%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo ENV_NAME=%ENV_NAME%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo ENV_PREFIX=%ENV_PREFIX%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo TAVI_BASE=%TAVI_BASE%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo INSTALL_DIR=%INSTALL_DIR%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo MICROMAMBA_DIR=%MICROMAMBA_DIR%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo MAMBA_ROOT_PREFIX=%MAMBA_ROOT_PREFIX%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo RELOCATED=%RELOCATED%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo REPO_URL=https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo PB_MAP=%PB_MAP%>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo COMPILER=gcc_win-64>> "%INSTALL_DIR%\INSTALL_INFO.txt"
echo [OK] Wrote install metadata to %INSTALL_DIR%\INSTALL_INFO.txt
echo.
echo ============================================================================
echo Installation complete.
echo Installed to: %INSTALL_DIR%
echo Environment : %ENV_NAME%
echo Env folder  : %ENV_PREFIX%
echo TAVI version: %TAVI_VERSION%
echo Installer   : %INSTALLER_VERSION%
echo McStas      : %MCSTAS_VERSION%
echo Compiler    : GCC (conda-forge)
echo ============================================================================
if "%PB_MAP%"=="missing" (
    echo.
    echo [WARN] The lead-sample dispersion map was not built. The "Pb: Phonon DFT"
    echo        sample will not run until you open the TAVI shell and run:
    echo            python tools\make_pb_assets.py
)
echo.
echo Run:
echo   %LAUNCHER_SCRIPT%
echo.
pause
endlocal
