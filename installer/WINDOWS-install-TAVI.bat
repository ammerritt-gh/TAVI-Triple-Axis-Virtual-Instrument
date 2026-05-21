@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: TAVI (Triple Axis Virtual Instrument) Installer for Windows
:: =============================================================================
:: Prerequisites that must be installed manually:
::   - Visual Studio Build Tools with "Desktop development with C++"
::     (C++/CLI support, MSVC v143, MSVC v142)
::
:: What this script does:
::   1.  Detects Visual Studio C++ compiler via vswhere.exe
::   2.  Detects Microsoft MPI SDK (optional; required for NMO/MPI workflows)
::   3.  Installs micromamba (pinned version with checksum verification)
::   4.  Creates or fully reconciles the 'tavi' conda environment
::   5.  Clones TAVI at a pinned release tag, or checks out that tag on update
::   6.  Configures McStasScript
::   7.  Creates launcher scripts that bootstrap the compiler environment,
::       and a desktop shortcut
::
:: Usage: WINDOWS-install-TAVI.bat [--verbose]
:: =============================================================================

:: ---------------------------------------------------------------------------
:: RELEASE PINS  — update these when cutting a new installer release
:: ---------------------------------------------------------------------------
::
:: TAVI_VERSION: the GitHub tag to install.
::   Set to "main" only during active development; published installers should
::   always pin a release tag such as "v1.0.0".
::
:: PYTHON_VERSION: must match the version used in run-tavi-dev.bat.
::   Confirm with: micromamba run -n tavi-dev python --version
::
:: MAMBA_VERSION / EXPECTED_SHA256: micromamba release to pin.
::   Find the correct SHA256 at:
::   https://github.com/mamba-org/micromamba-releases/releases
::
set "TAVI_VERSION=main"
set "PYTHON_VERSION=3.11"
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"
:: ---------------------------------------------------------------------------

set "VERBOSE=0"
if "%1"=="--verbose" set "VERBOSE=1"
if "%1"=="-v" set "VERBOSE=1"

title TAVI Installer

echo ============================================================================
echo                    TAVI Installation Script
echo                 Triple Axis Virtual Instrument
echo                 Release: %TAVI_VERSION%
echo ============================================================================
echo.
if "%VERBOSE%"=="1" echo [DEBUG] Verbose mode enabled.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Running without administrator privileges.
    echo [INFO] This is fine for a user-local installation.
    echo.
)

set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "ENV_NAME=tavi"

echo Installation directory : %INSTALL_DIR%
echo Micromamba directory   : %MICROMAMBA_DIR%
echo Environment name       : %ENV_NAME%
echo Python version         : %PYTHON_VERSION%
echo TAVI release           : %TAVI_VERSION%
echo.

:: =============================================================================
:: Step 0: Check prerequisites
:: =============================================================================
echo [Step 0/6] Checking prerequisites...

:: ---------------------------------------------------------------------------
:: 0a: Visual Studio — detect via vswhere.exe
::     vswhere ships with VS 2017+ and handles non-year directory names
::     (e.g. VS 2026 installs to \18\ rather than \2026\).
:: ---------------------------------------------------------------------------
set "VS_FOUND=0"
set "VCVARS="

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "!VSWHERE!" set "VSWHERE=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"

if exist "!VSWHERE!" (
    if "%VERBOSE%"=="1" echo [DEBUG] Using vswhere: !VSWHERE!
    for /f "usebackq tokens=*" %%I in (
        `"!VSWHERE!" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2^>nul`
    ) do set "VS_INSTALL=%%I"
    if defined VS_INSTALL (
        set "VCVARS=!VS_INSTALL!\VC\Auxiliary\Build\vcvarsall.bat"
        if exist "!VCVARS!" set "VS_FOUND=1"
    )
) else (
    echo [WARN] vswhere.exe not found. Falling back to fixed-path search.
    for %%Y in (2026 2025 2022 2019) do (
        for %%E in (Community Professional Enterprise BuildTools) do (
            if "!VS_FOUND!"=="0" (
                set "_C=C:\Program Files\Microsoft Visual Studio\%%Y\%%E\VC\Auxiliary\Build\vcvarsall.bat"
                if exist "!_C!" ( set "VCVARS=!_C!" & set "VS_FOUND=1" )
            )
            if "!VS_FOUND!"=="0" (
                set "_C=C:\Program Files (x86)\Microsoft Visual Studio\%%Y\%%E\VC\Auxiliary\Build\vcvarsall.bat"
                if exist "!_C!" ( set "VCVARS=!_C!" & set "VS_FOUND=1" )
            )
        )
    )
)

if "!VS_FOUND!"=="1" (
    echo [OK] Visual Studio C++ compiler found.
    echo [INFO] vcvarsall.bat  : !VCVARS!
    echo [INFO] Generated launchers will call vcvarsall.bat x64 before starting TAVI.
) else (
    echo.
    echo ============================================================================
    echo [WARNING] Visual Studio C++ compiler not found!
    echo ============================================================================
    echo.
    echo McStas requires Visual Studio with C++ support to compile simulations.
    echo Install Visual Studio Build Tools and select "Desktop development with C++"
    echo including C++/CLI support, MSVC v143, and MSVC v142.
    echo Download: https://visualstudio.microsoft.com/downloads/
    echo.
    choice /C YN /M "Continue anyway (Y) or exit and install VS first (N)"
    if errorlevel 2 (
        start https://visualstudio.microsoft.com/downloads/
        pause
        exit /b 1
    )
    echo [INFO] Bypassing compiler check. McStas compilation may fail later.
)
echo.

:: ---------------------------------------------------------------------------
:: 0b: Microsoft MPI SDK — optional, required for NMO/MPI workflows
:: ---------------------------------------------------------------------------
set "MPI_FOUND=0"
set "MPI_INCLUDE=C:\Program Files (x86)\Microsoft SDKs\MPI\Include"
set "MPI_LIB=C:\Program Files (x86)\Microsoft SDKs\MPI\Lib\x64"

if exist "!MPI_INCLUDE!\mpi.h" (
    if exist "!MPI_LIB!\msmpi.lib" (
        set "MPI_FOUND=1"
        echo [OK] Microsoft MPI SDK found. MPI/NMO workflows will be enabled in launchers.
    )
)
if "!MPI_FOUND!"=="0" (
    echo [WARN] Microsoft MPI SDK not found.
    echo [WARN] Basic simulations will work. NMO/MPI workflows will be unavailable.
    echo [WARN] To enable MPI: https://learn.microsoft.com/en-us/message-passing-interface/microsoft-mpi
)
echo.

:: =============================================================================
:: Step 1: Install Micromamba
:: =============================================================================
echo [Step 1/6] Setting up micromamba...

if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
cd /d "%MICROMAMBA_DIR%"

set "MAMBA_URL=https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
set "NEEDS_DOWNLOAD=0"

if not exist "%MICROMAMBA_DIR%\micromamba.exe" (
    set "NEEDS_DOWNLOAD=1"
    echo [INFO] Micromamba not found. Will download version %MAMBA_VERSION%.
) else (
    echo [INFO] Verifying existing micromamba...
    certutil -hashfile "%MICROMAMBA_DIR%\micromamba.exe" SHA256 > "%TEMP%\mamba_hash.txt" 2>nul
    if !errorlevel! neq 0 (
        echo [WARN] Could not verify checksum. Will re-download.
        set "NEEDS_DOWNLOAD=1"
    ) else (
        call :extract_hash
        if /I "!ACTUAL_SHA256!"=="%EXPECTED_SHA256%" (
            echo [OK] Micromamba %MAMBA_VERSION% verified.
        ) else (
            echo [WARN] Checksum mismatch. Will re-download.
            set "NEEDS_DOWNLOAD=1"
        )
        del "%TEMP%\mamba_hash.txt" 2>nul
    )
)

if "!NEEDS_DOWNLOAD!"=="1" (
    echo [INFO] Downloading micromamba %MAMBA_VERSION%...
    curl -L -o "%MICROMAMBA_DIR%\micromamba.exe.tmp" "%MAMBA_URL%"
    if !errorlevel! neq 0 (
        echo [ERROR] Download failed. Check internet connection.
        del "%MICROMAMBA_DIR%\micromamba.exe.tmp" 2>nul
        pause
        exit /b 1
    )
    certutil -hashfile "%MICROMAMBA_DIR%\micromamba.exe.tmp" SHA256 > "%TEMP%\mamba_hash.txt" 2>nul
    call :extract_hash
    del "%TEMP%\mamba_hash.txt" 2>nul
    if /I "!ACTUAL_SHA256!"=="%EXPECTED_SHA256%" (
        del "%MICROMAMBA_DIR%\micromamba.exe" 2>nul
        move /Y "%MICROMAMBA_DIR%\micromamba.exe.tmp" "%MICROMAMBA_DIR%\micromamba.exe" >nul
        echo [OK] Micromamba %MAMBA_VERSION% downloaded and verified.
    ) else (
        echo [ERROR] Checksum mismatch on downloaded file.
        echo [ERROR] Expected : %EXPECTED_SHA256%
        echo [ERROR] Actual   : !ACTUAL_SHA256!
        del "%MICROMAMBA_DIR%\micromamba.exe.tmp" 2>nul
        pause
        exit /b 1
    )
)

"%MICROMAMBA_DIR%\micromamba.exe" shell init --shell cmd.exe -p "%MICROMAMBA_DIR%" >nul 2>&1
"%MICROMAMBA_DIR%\micromamba.exe" config append channels conda-forge 2>nul
"%MICROMAMBA_DIR%\micromamba.exe" config set channel_priority strict 2>nul
echo [OK] Micromamba ready.
echo.

:: =============================================================================
:: Step 2: Create or fully reconcile the 'tavi' conda environment
:: =============================================================================
:: The CONDA_PACKAGES list is the single source of truth for the environment.
:: Both fresh creates and in-place reconciles use the same list, so re-running
:: this installer on an existing environment converges to the same state.
:: =============================================================================
echo [Step 2/6] Setting up Python environment with McStas...

set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas mcstas-core numpy scipy matplotlib h5py pyyaml git"

set "ENV_EXISTS=0"
for /f "tokens=1" %%E in ('"%MICROMAMBA_DIR%\micromamba.exe" env list 2^>nul') do (
    if /I "%%E"=="%ENV_NAME%" set "ENV_EXISTS=1"
)

if "%ENV_EXISTS%"=="1" (
    echo [INFO] Environment '%ENV_NAME%' already exists.
    choice /C YN /M "Recreate from scratch (Y) or reconcile/update in place (N)"
    if errorlevel 2 goto :reconcile_env
    if errorlevel 1 goto :remove_env
    goto :reconcile_env
)
goto :create_env

:remove_env
echo [INFO] Removing existing environment...
"%MICROMAMBA_DIR%\micromamba.exe" env remove -n %ENV_NAME% -y >nul 2>&1
echo [OK] Environment removed.

:create_env
echo [INFO] Creating new environment...
echo [INFO] Packages: %CONDA_PACKAGES%
echo [INFO] This may take 5-15 minutes...
"%MICROMAMBA_DIR%\micromamba.exe" create -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
if !errorlevel! neq 0 (
    echo [ERROR] Failed to create environment. Check disk space and internet connection.
    pause
    exit /b 1
)
echo [OK] Conda environment created.
goto :install_pip

:reconcile_env
echo [INFO] Reconciling environment to current package manifest...
echo [INFO] Packages: %CONDA_PACKAGES%
"%MICROMAMBA_DIR%\micromamba.exe" install -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
if !errorlevel! neq 0 (
    echo [WARN] Conda reconcile reported errors. Continuing with pip packages...
)

:install_pip
echo [INFO] Installing/upgrading pip packages...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade pip >nul
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade PySide6
if !errorlevel! neq 0 echo [WARN] PySide6 install reported errors.
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade mcstasscript
if !errorlevel! neq 0 echo [WARN] mcstasscript install reported errors.
echo [OK] Python packages ready.
echo.

:: =============================================================================
:: Step 3: Clone TAVI at the pinned release, or update to it
:: =============================================================================
echo [Step 3/6] Setting up TAVI (release: %TAVI_VERSION%)...

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"

if exist "%INSTALL_DIR%\.git" (
    echo [INFO] Existing repository found. Fetching and checking out %TAVI_VERSION%...
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git fetch origin
    if !errorlevel! neq 0 (
        echo [WARN] Could not fetch from remote. Keeping existing local version.
        goto :step3_done
    )
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git checkout %TAVI_VERSION%
    if !errorlevel! neq 0 (
        echo [WARN] Could not check out %TAVI_VERSION%. Keeping current state.
        goto :step3_done
    )
    :: For a branch (e.g. main), pull latest; for a tag, this is a no-op
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git pull origin %TAVI_VERSION% >nul 2>&1
    echo [OK] TAVI updated to %TAVI_VERSION%.
    goto :step3_done
)

:: Fresh clone
set "DIR_EMPTY=1"
for /f %%a in ('dir /b "%INSTALL_DIR%" 2^>nul') do set "DIR_EMPTY=0"

if "!DIR_EMPTY!"=="0" (
    echo [INFO] Install directory is not empty. Cloning to temp folder first...
    set "TEMP_CLONE=%TEMP%\TAVI_clone_%RANDOM%"
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git clone --branch %TAVI_VERSION% https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git "!TEMP_CLONE!"
    if !errorlevel! neq 0 goto :clone_failed
    xcopy /E /Y /Q "!TEMP_CLONE!\*" "%INSTALL_DIR%\" >nul 2>&1
    rd /s /q "!TEMP_CLONE!" >nul 2>&1
) else (
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git clone --branch %TAVI_VERSION% https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
    if !errorlevel! neq 0 goto :clone_failed
)
echo [OK] TAVI %TAVI_VERSION% cloned.
goto :step3_done

:clone_failed
echo [ERROR] Failed to clone TAVI from GitHub.
echo [INFO] Check your internet connection, or download manually from:
echo        https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument
pause
exit /b 1

:step3_done
echo.

:: =============================================================================
:: Step 4: Configure McStasScript
:: =============================================================================
echo [Step 4/6] Configuring McStasScript...

"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python -c ^
"import os, sys, mcstasscript as ms;" ^
"env = sys.prefix;" ^
"bin_candidates = [os.path.join(env, d) for d in ['Library\\bin', 'bin']];" ^
"bin_path = next((d for d in bin_candidates if any(os.path.exists(os.path.join(d, e)) for e in ['mcrun.exe', 'mcrun.bat', 'mcrun'])), bin_candidates[-1]);" ^
"lib_path = None;" ^
"[lib_path := next((os.path.join(base, v) for v in sorted(os.listdir(base), reverse=True) if os.path.isdir(os.path.join(base, v))), base) for base in [os.path.join(env, 'Library', 'share', 'mcstas'), os.path.join(env, 'share', 'mcstas')] if os.path.isdir(base) and lib_path is None];" ^
"c = ms.Configurator(); c.set_mcrun_path(bin_path); c.set_mcstas_path(lib_path);" ^
"print('[TAVI] McStasScript configured:'); print('[TAVI]   mcrun: ', bin_path); print('[TAVI]   mcstas:', lib_path)"

if !errorlevel! neq 0 (
    echo [WARN] McStasScript auto-configuration failed.
    echo [INFO] Configure manually after launch:
    echo        python -c "import mcstasscript as ms; c = ms.Configurator(); c.set_mcrun_path('...'); c.set_mcstas_path('...')"
)
echo.

:: =============================================================================
:: Step 5: Output directory
:: =============================================================================
if not exist "%INSTALL_DIR%\output" mkdir "%INSTALL_DIR%\output"

:: =============================================================================
:: Step 6: Generate launcher scripts with compiler + MPI bootstrap
:: =============================================================================
:: All generated launchers share a common bootstrap helper (tavi-bootstrap.bat)
:: that calls vcvarsall.bat x64 and injects MPI paths before launching TAVI.
:: This means compile-on-first-run works correctly from any entry point.
:: =============================================================================
echo [Step 6/6] Creating launcher scripts...

set "BOOTSTRAP_SCRIPT=%INSTALL_DIR%\tavi-bootstrap.bat"
set "RUN_SCRIPT=%INSTALL_DIR%\run-tavi.bat"
set "UPDATE_SCRIPT=%INSTALL_DIR%\update-tavi.bat"
set "LAUNCHER_SCRIPT=%INSTALL_DIR%\TAVI-Launcher.bat"

:: ------------------------------------------------------------------
:: tavi-bootstrap.bat  — shared compiler + MPI setup helper
:: Called as: tavi-bootstrap.bat python TAVI_PySide6.py
::            tavi-bootstrap.bat git fetch origin
:: ------------------------------------------------------------------
>"!BOOTSTRAP_SCRIPT!" (
    echo @echo off
    echo :: tavi-bootstrap.bat
    echo :: Shared bootstrap helper for all TAVI launcher scripts.
    echo :: Calls vcvarsall.bat, injects MPI paths, then runs the command in %%*.
    echo :: Do not run this script directly.
    echo setlocal
    echo.
)
if "!VS_FOUND!"=="1" (
    >>"!BOOTSTRAP_SCRIPT!" (
        echo :: Bootstrap Visual Studio compiler environment
        echo call "!VCVARS!" x64 ^>nul
        echo if errorlevel 1 echo [WARN] vcvarsall.bat returned an error. Compilation may fail.
        echo.
    )
) else (
    >>"!BOOTSTRAP_SCRIPT!" (
        echo :: No Visual Studio compiler was detected at install time.
        echo :: Re-run WINDOWS-install-TAVI.bat after installing Visual Studio Build Tools.
        echo.
    )
)
if "!MPI_FOUND!"=="1" (
    >>"!BOOTSTRAP_SCRIPT!" (
        echo :: Append Microsoft MPI SDK paths for NMO/MPI workflows
        echo set "INCLUDE=%%INCLUDE%%;!MPI_INCLUDE!"
        echo set "LIB=%%LIB%%;!MPI_LIB!"
        echo.
    )
) else (
    >>"!BOOTSTRAP_SCRIPT!" (
        echo :: Microsoft MPI SDK was not found at install time.
        echo :: NMO/MPI workflows will be unavailable.
        echo.
    )
)
>>"!BOOTSTRAP_SCRIPT!" (
    echo :: Run the requested command inside the tavi conda environment
    echo cd /d "!INSTALL_DIR!"
    echo "!MICROMAMBA_DIR!\micromamba.exe" run -n !ENV_NAME! %%*
    echo endlocal
)

:: ------------------------------------------------------------------
:: run-tavi.bat
:: ------------------------------------------------------------------
>"!RUN_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo call "!BOOTSTRAP_SCRIPT!" python TAVI_PySide6.py
    echo if errorlevel 1 pause
    echo endlocal
)

:: ------------------------------------------------------------------
:: update-tavi.bat
:: ------------------------------------------------------------------
>"!UPDATE_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo echo ============================================================================
    echo echo                       TAVI Update Script
    echo echo                       Pinned release: %TAVI_VERSION%
    echo echo ============================================================================
    echo echo.
    echo echo [INFO] Fetching from GitHub...
    echo call "!BOOTSTRAP_SCRIPT!" git fetch origin
    echo echo [INFO] Checking out %TAVI_VERSION%...
    echo call "!BOOTSTRAP_SCRIPT!" git checkout %TAVI_VERSION%
    echo call "!BOOTSTRAP_SCRIPT!" git pull origin %TAVI_VERSION%
    echo if errorlevel 1 ^(
    echo     echo [ERROR] Update failed. Check your internet connection.
    echo ^) else ^(
    echo     echo [OK] TAVI updated to %TAVI_VERSION%.
    echo ^)
    echo echo.
    echo echo [INFO] Updating pip packages...
    echo call "!BOOTSTRAP_SCRIPT!" pip install --upgrade PySide6 mcstasscript
    echo echo.
    echo echo Update complete. Press any key to exit.
    echo pause ^>nul
    echo endlocal
)

:: ------------------------------------------------------------------
:: TAVI-Launcher.bat
:: ------------------------------------------------------------------
>"!LAUNCHER_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo title TAVI Launcher
    echo :menu
    echo cls
    echo echo ============================================================================
    echo echo                         TAVI Launcher
    echo echo                  Triple Axis Virtual Instrument
    echo echo                  Release: %TAVI_VERSION%
    echo echo ============================================================================
    echo echo.
    echo echo   [1] Run TAVI
    echo echo   [2] Update TAVI
    echo echo   [3] Open TAVI folder
    echo echo   [4] Open TAVI shell ^(for debugging^)
    echo echo   [5] Exit
    echo echo.
    echo choice /C 12345 /M "Select option"
    echo.
    echo if errorlevel 5 exit /b 0
    echo if errorlevel 4 goto :shell
    echo if errorlevel 3 goto :folder
    echo if errorlevel 2 goto :update
    echo if errorlevel 1 goto :run
    echo goto :menu
    echo.
    echo :run
    echo call "!RUN_SCRIPT!"
    echo goto :menu
    echo.
    echo :update
    echo call "!UPDATE_SCRIPT!"
    echo goto :menu
    echo.
    echo :folder
    echo explorer "!INSTALL_DIR!"
    echo goto :menu
    echo.
    echo :shell
    echo call "!BOOTSTRAP_SCRIPT!" cmd /k "echo TAVI Shell Ready ^&^& echo Type 'python TAVI_PySide6.py' to run TAVI"
    echo goto :menu
    echo endlocal
)

:: Desktop shortcut
powershell -NoProfile -Command "$s = (New-Object -Com WScript.Shell).CreateShortcut([System.Environment]::ExpandEnvironmentVariables('%USERPROFILE%\Desktop\TAVI Launcher.lnk')); $s.TargetPath = '!LAUNCHER_SCRIPT!'; $s.WorkingDirectory = '!INSTALL_DIR!'; $s.Description = 'TAVI - Triple Axis Virtual Instrument'; $s.Save()"
if !errorlevel! equ 0 (
    echo [OK] Desktop shortcut created.
) else (
    echo [INFO] Desktop shortcut not created. Run TAVI from: !LAUNCHER_SCRIPT!
)
echo [OK] Launcher scripts created.
echo.

:: =============================================================================
:: Installation Complete
:: =============================================================================
echo ============================================================================
echo                    Installation Complete!
echo ============================================================================
echo.
echo TAVI %TAVI_VERSION% installed to: %INSTALL_DIR%
echo.
echo Compiler bootstrap : !VCVARS!
if "!VS_FOUND!"=="0" echo                  : [NOT FOUND - simulations may fail to compile]
echo MPI SDK            : !MPI_INCLUDE!
if "!MPI_FOUND!"=="0" echo                  : [NOT FOUND - NMO/MPI workflows unavailable]
echo.
echo To run TAVI:
echo   - Double-click "TAVI Launcher" on your desktop
echo   - Or run: !LAUNCHER_SCRIPT!
echo.
echo First-run note:
echo   The first simulation point compiles the McStas instrument (~10-30s).
echo   Later points in a multi-point scan reuse the compiled binary and are
echo   significantly faster.
echo.
echo Validation note:
echo   Run at least one 2-point scan after installation to confirm both the
echo   first-point compile and subsequent direct-binary execution work correctly.
echo.
echo ============================================================================
echo.
echo Press any key to launch TAVI now, or close this window to exit...
pause >nul
call "!LAUNCHER_SCRIPT!"
goto :eof

:: =============================================================================
:: Subroutines
:: =============================================================================

:extract_hash
set "ACTUAL_SHA256="
set "_LN=0"
for /f "skip=1 tokens=*" %%H in (%TEMP%\mamba_hash.txt) do (
    if !_LN! equ 0 (
        set "ACTUAL_SHA256=%%H"
        set /a _LN+=1
    )
)
set "ACTUAL_SHA256=!ACTUAL_SHA256: =!"
goto :eof

endlocal
