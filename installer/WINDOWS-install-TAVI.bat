@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: TAVI (Triple Axis Virtual Instrument) Installer for Windows
:: =============================================================================
:: This script installs TAVI along with McStas for neutron scattering simulations.
:: 
:: Prerequisites that must be installed manually:
::   - Visual Studio with C++ support (for McStas compilation)
::
:: What this script does:
::   1. Checks for Visual Studio C++ compiler
::   2. Installs micromamba (lightweight conda package manager)
::   3. Creates a 'tavi' environment with McStas and Python dependencies
::   4. Downloads the latest TAVI from GitHub
::   5. Configures McStasScript and default settings
::   6. Creates desktop shortcut for running TAVI
::
:: Usage: install-TAVI.bat [--verbose]
:: =============================================================================

:: Check for verbose mode
set "VERBOSE=0"
if "%1"=="--verbose" set "VERBOSE=1"
if "%1"=="-v" set "VERBOSE=1"

title TAVI Installer

echo ============================================================================
echo                    TAVI Installation Script
echo                 Triple Axis Virtual Instrument
echo ============================================================================
echo.
if "%VERBOSE%"=="1" echo [DEBUG] Verbose mode enabled.

:: Check for administrator privileges (recommended but not required)
if "%VERBOSE%"=="1" echo [DEBUG] Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Running without administrator privileges.
    echo [INFO] This should work fine for a user-local installation.
    echo.
)

:: Set installation directories
set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "ENV_NAME=tavi"

echo Installation directory: %INSTALL_DIR%
echo Micromamba directory: %MICROMAMBA_DIR%
echo Environment name: %ENV_NAME%
echo.

:: =============================================================================
:: Step 0: Check for C++ Compiler (Visual Studio)
:: =============================================================================
echo [Step 0/5] Checking for C++ compiler...

:: Check for Visual Studio Build Tools installation
set "VS_FOUND=0"
set "VCVARS="

:: Visual Studio 2022 (check multiple editions)
if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
)
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
)
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat"
)
if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"
)
:: Visual Studio 2019
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
)
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" (
    set "VS_FOUND=1"
    set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"
)

if "!VS_FOUND!"=="1" (
    echo [OK] Visual Studio with C++ support found.
    if "%VERBOSE%"=="1" echo [DEBUG] vcvarsall.bat: !VCVARS!
    goto :cpp_check_done
)

:: No compiler found - inform user
echo.
echo ============================================================================
echo [WARNING] Visual Studio C++ compiler not found!
echo ============================================================================
echo.
echo McStas requires Visual Studio with C++ support to compile simulations.
echo.
echo Please install Visual Studio with C++ support:
echo   1. Download from: https://visualstudio.microsoft.com/downloads/
echo   2. Run the installer and select "Desktop development with C++"
echo   3. Make sure to include MSVC v143 (VS 2022) build tools
echo.
echo After installation, re-run this installer.
echo.
choice /C YN /M "Do you want to bypass this check and continue anyway (Y) or exit (N)"
if errorlevel 2 goto :cpp_check_exit
if errorlevel 1 goto :cpp_check_bypass
goto :cpp_check_exit

:cpp_check_bypass
echo.
echo [INFO] Bypassing C++ compiler check. McStas compilation may fail later.
echo [INFO] Continuing with installation...
goto :cpp_check_done

:cpp_check_exit
echo [INFO] Opening download page...
start https://visualstudio.microsoft.com/downloads/
echo.
echo [INFO] Please install Visual Studio with C++ support and re-run this installer.
pause
exit /b 1

:cpp_check_done
echo.

:: =============================================================================
:: Step 1: Install Micromamba
:: =============================================================================
echo [Step 1/5] Setting up micromamba package manager...

:: Create micromamba directory
if "%VERBOSE%"=="1" echo [DEBUG] Creating micromamba directory: %MICROMAMBA_DIR%
if not exist "%MICROMAMBA_DIR%" (
    mkdir "%MICROMAMBA_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create micromamba directory: %MICROMAMBA_DIR%
        echo [INFO] Please check you have write permissions to this location.
        pause
        exit /b 1
    )
)
cd /d "%MICROMAMBA_DIR%"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to change to micromamba directory: %MICROMAMBA_DIR%
    pause
    exit /b 1
)
if "%VERBOSE%"=="1" echo [DEBUG] Working directory: %CD%

:: Download micromamba if not present or if checksum verification fails
:: Pin to specific version for reproducibility and security
set "MAMBA_VERSION=2.5.0-1"
set "MAMBA_URL=https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
set "MAMBA_SHA256_URL=https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64.sha256"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"

:: Function to verify SHA256 checksum
set "NEEDS_DOWNLOAD=0"
if not exist "%MICROMAMBA_DIR%\micromamba.exe" (
    set "NEEDS_DOWNLOAD=1"
    echo [INFO] Micromamba not found. Will download.
) else (
    echo [INFO] Verifying existing micromamba installation...
    if "%VERBOSE%"=="1" echo [DEBUG] Computing SHA256 checksum...
    
    :: Compute SHA256 of existing file using certutil
    certutil -hashfile "%MICROMAMBA_DIR%\micromamba.exe" SHA256 > "%TEMP%\mamba_hash.txt" 2>nul
    if !errorlevel! neq 0 (
        echo [WARN] Failed to compute checksum. Will re-download micromamba.
        set "NEEDS_DOWNLOAD=1"
    ) else (
        :: Extract hash from certutil output (hash is on second line)
        set "ACTUAL_SHA256="
        set "LINE_NUM=0"
        for /f "skip=1 tokens=*" %%H in (%TEMP%\mamba_hash.txt) do (
            if !LINE_NUM! equ 0 (
                set "ACTUAL_SHA256=%%H"
                set "LINE_NUM=1"
            )
        )
        :: Remove spaces from hash
        set "ACTUAL_SHA256=!ACTUAL_SHA256: =!"
        
        if "%VERBOSE%"=="1" echo [DEBUG] Expected: %EXPECTED_SHA256%
        if "%VERBOSE%"=="1" echo [DEBUG] Actual:   !ACTUAL_SHA256!
        
        if /I "!ACTUAL_SHA256!"=="%EXPECTED_SHA256%" (
            echo [OK] Micromamba checksum verified.
        ) else (
            echo [WARN] Micromamba checksum mismatch. Will re-download.
            set "NEEDS_DOWNLOAD=1"
        )
        del "%TEMP%\mamba_hash.txt" 2>nul
    )
)

if "!NEEDS_DOWNLOAD!"=="1" (
    echo [INFO] Downloading micromamba version %MAMBA_VERSION%...
    if "%VERBOSE%"=="1" echo [DEBUG] URL: !MAMBA_URL!
    
    :: Download micromamba binary
    curl -L -o "%MICROMAMBA_DIR%\micromamba.exe.tmp" "!MAMBA_URL!"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to download micromamba.
        echo [INFO] Please check your internet connection and try again.
        del "%MICROMAMBA_DIR%\micromamba.exe.tmp" 2>nul
        pause
        exit /b 1
    )
    
    :: Verify checksum of downloaded file
    echo [INFO] Verifying downloaded file...
    certutil -hashfile "%MICROMAMBA_DIR%\micromamba.exe.tmp" SHA256 > "%TEMP%\mamba_hash.txt" 2>nul
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to compute checksum of downloaded file.
        del "%MICROMAMBA_DIR%\micromamba.exe.tmp" 2>nul
        del "%TEMP%\mamba_hash.txt" 2>nul
        pause
        exit /b 1
    )
    
    :: Extract and verify hash
    set "ACTUAL_SHA256="
    set "LINE_NUM=0"
    for /f "skip=1 tokens=*" %%H in (%TEMP%\mamba_hash.txt) do (
        if !LINE_NUM! equ 0 (
            set "ACTUAL_SHA256=%%H"
            set "LINE_NUM=1"
        )
    )
    set "ACTUAL_SHA256=!ACTUAL_SHA256: =!"
    del "%TEMP%\mamba_hash.txt" 2>nul
    
    if "%VERBOSE%"=="1" echo [DEBUG] Expected: %EXPECTED_SHA256%
    if "%VERBOSE%"=="1" echo [DEBUG] Actual:   !ACTUAL_SHA256!
    
    if /I "!ACTUAL_SHA256!"=="%EXPECTED_SHA256%" (
        :: Checksum matches, replace old file with new one
        del "%MICROMAMBA_DIR%\micromamba.exe" 2>nul
        move /Y "%MICROMAMBA_DIR%\micromamba.exe.tmp" "%MICROMAMBA_DIR%\micromamba.exe" >nul
        echo [OK] Micromamba downloaded and verified successfully.
    ) else (
        echo [ERROR] Downloaded file checksum mismatch!
        echo [ERROR] Expected: %EXPECTED_SHA256%
        echo [ERROR] Actual:   !ACTUAL_SHA256!
        echo [ERROR] This could indicate a corrupted download or security issue.
        del "%MICROMAMBA_DIR%\micromamba.exe.tmp" 2>nul
        pause
        exit /b 1
    )
)

:: Initialize shell (if not already done)
echo [INFO] Initializing micromamba for command prompt...
"%MICROMAMBA_DIR%\micromamba.exe" shell init --shell cmd.exe -p "%MICROMAMBA_DIR%" >nul 2>&1

:: Configure conda-forge channel
"%MICROMAMBA_DIR%\micromamba.exe" config append channels conda-forge 2>nul
"%MICROMAMBA_DIR%\micromamba.exe" config set channel_priority strict 2>nul
echo [OK] Micromamba configured.
echo.

:: =============================================================================
:: Step 2: Create/Update TAVI Environment
:: =============================================================================
echo [Step 2/5] Creating Python environment with McStas...
if "%VERBOSE%"=="1" echo [DEBUG] Checking if environment '%ENV_NAME%' exists...

:: Check if environment exists by matching the exact environment name
set "ENV_EXISTS=0"
for /f "tokens=1" %%E in ('"%MICROMAMBA_DIR%\micromamba.exe" env list 2^>nul') do (
    if /I "%%E"=="%ENV_NAME%" (
        set "ENV_EXISTS=1"
    )
)
if "%ENV_EXISTS%"=="1" (
    echo [INFO] Environment '%ENV_NAME%' already exists.
    
    choice /C YN /M "Do you want to recreate it (Y) or keep existing (N)"
    if errorlevel 2 goto :update_env
    if errorlevel 1 goto :remove_env
    goto :update_env
)
goto :create_env

:remove_env
echo [INFO] Removing existing environment...
"%MICROMAMBA_DIR%\micromamba.exe" env remove -n %ENV_NAME% -y >nul 2>&1
if "%VERBOSE%"=="1" echo [DEBUG] Environment removed.
goto :create_env

:create_env
echo [INFO] Creating new environment with McStas and dependencies...
echo [INFO] This may take 5-15 minutes depending on your internet connection...
echo.
if "%VERBOSE%"=="1" echo [DEBUG] Running micromamba create...

:: Create environment with McStas and essential packages
:: Note: We install mcstasscript via pip because conda-forge version may conflict with PySide6
"%MICROMAMBA_DIR%\micromamba.exe" create -n %ENV_NAME% ^
    python=3.11 ^
    mcstas ^
    mcstas-core ^
    numpy ^
    scipy ^
    matplotlib ^
    h5py ^
    pyyaml ^
    git ^
    -c conda-forge -c nodefaults -y

if !errorlevel! neq 0 (
    echo [ERROR] Failed to create environment.
    echo [INFO] Check if you have sufficient disk space and internet connection.
    pause
    exit /b 1
)

echo [OK] Conda environment created successfully.
if "%VERBOSE%"=="1" echo [DEBUG] Environment creation complete.

:update_env
if "%VERBOSE%"=="1" echo [DEBUG] Starting pip package installation...
:: Install pip packages (PySide6 and mcstasscript)
echo [INFO] Installing PySide6 and mcstasscript via pip...
echo [INFO] Upgrading pip...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade pip
if !errorlevel! neq 0 (
    echo [WARNING] Failed to upgrade pip, continuing anyway...
)
echo [INFO] Installing PySide6...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install PySide6
if !errorlevel! neq 0 (
    echo [WARNING] Failed to install PySide6.
)
echo [INFO] Installing mcstasscript...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install mcstasscript

if !errorlevel! neq 0 (
    echo [WARNING] mcstasscript may not have installed correctly.
    echo [INFO] You can try installing it manually later.
)

echo [OK] Python packages installed.
if "%VERBOSE%"=="1" echo [DEBUG] Step 2 complete.
echo.

:: =============================================================================
:: Step 3: Download/Update TAVI
:: =============================================================================
echo [Step 3/5] Downloading TAVI from GitHub...
if "%VERBOSE%"=="1" echo [DEBUG] Install directory: %INSTALL_DIR%

:: Create TAVI directory
if not exist "%INSTALL_DIR%" (
    if "%VERBOSE%"=="1" echo [DEBUG] Creating install directory...
    mkdir "%INSTALL_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create install directory: %INSTALL_DIR%
        pause
        exit /b 1
    )
)
cd /d "%INSTALL_DIR%"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to change to install directory: %INSTALL_DIR%
    pause
    exit /b 1
)
if "%VERBOSE%"=="1" echo [DEBUG] Working directory: %CD%

:: Check if TAVI is already cloned
if exist "%INSTALL_DIR%\.git" (
    echo [INFO] TAVI repository already exists. Updating...
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git pull origin main
    if !errorlevel! neq 0 (
        echo [WARNING] Could not update TAVI. Will use existing version.
    ) else (
        echo [OK] TAVI updated to latest version.
    )
    goto :step3_done
)

:: Check if directory is empty (git clone requires empty directory)
if "%VERBOSE%"=="1" echo [DEBUG] Checking if directory is empty...
set "DIR_EMPTY=1"
for /f %%a in ('dir /b "%INSTALL_DIR%" 2^>nul') do set "DIR_EMPTY=0"

if "!DIR_EMPTY!"=="0" (
    echo [WARNING] Installation directory is not empty.
    echo [INFO] Cloning to temporary folder and moving files...
    set "TEMP_CLONE=%TEMP%\TAVI_clone_%RANDOM%"
    if "%VERBOSE%"=="1" echo [DEBUG] Temp clone directory: !TEMP_CLONE!
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git clone https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git "!TEMP_CLONE!"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to clone TAVI repository.
        echo [INFO] Please check your internet connection and try again.
        echo [INFO] You can also manually download from:
        echo        https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument
        pause
        exit /b 1
    )
    :: Move files from temp to install dir
    if "%VERBOSE%"=="1" echo [DEBUG] Moving files from temp to install directory...
    xcopy /E /Y /Q "!TEMP_CLONE!\*" "%INSTALL_DIR%\" >nul 2>&1
    rd /s /q "!TEMP_CLONE!" >nul 2>&1
    echo [OK] TAVI downloaded successfully.
) else (
    echo [INFO] Cloning TAVI repository...
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git clone https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to clone TAVI repository.
        echo [INFO] Please check your internet connection and try again.
        echo [INFO] You can also manually download from:
        echo        https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument
        pause
        exit /b 1
    )
    echo [OK] TAVI downloaded successfully.
)

:step3_done
if "%VERBOSE%"=="1" echo [DEBUG] Step 3 complete.
echo.

:: =============================================================================
:: Step 4: Configure McStasScript
:: =============================================================================
echo [Step 4/5] Configuring McStasScript...
if "%VERBOSE%"=="1" echo [DEBUG] Detecting McStas installation paths...

:: Use Python to find the actual McStas paths within the conda environment
:: This is more reliable than guessing the path structure
echo [INFO] Detecting McStas component paths...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python -c "import os, sys; env_prefix = os.path.dirname(os.path.dirname(sys.executable)); bin_path = os.path.join(env_prefix, 'bin'); mcstas_resources = os.path.join(env_prefix, 'share', 'mcstas', 'resources'); alt_resources = os.path.join(env_prefix, 'Library', 'share', 'mcstas', 'resources'); lib_path = mcstas_resources if os.path.exists(mcstas_resources) else (alt_resources if os.path.exists(alt_resources) else None); print(f'MCRUN_PATH={bin_path}'); print(f'MCSTAS_PATH={lib_path}')"
if !errorlevel! neq 0 (
    echo [WARNING] Could not detect McStas paths automatically.
)

:: Configure McStasScript using Python to find and set correct paths
echo [INFO] Configuring McStasScript...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python -c "import os, sys, mcstasscript as ms; env_prefix = os.path.dirname(os.path.dirname(sys.executable)); bin_path = os.path.join(env_prefix, 'bin'); mcstas_resources = os.path.join(env_prefix, 'share', 'mcstas', 'resources'); alt_resources = os.path.join(env_prefix, 'Library', 'share', 'mcstas', 'resources'); lib_path = mcstas_resources if os.path.exists(mcstas_resources) else alt_resources; c = ms.Configurator(); c.set_mcrun_path(bin_path); c.set_mcstas_path(lib_path); print('McStasScript configured successfully!'); print('  mcrun path:', bin_path); print('  mcstas path:', lib_path)"
if !errorlevel! neq 0 (
    echo [WARNING] McStasScript configuration may need manual adjustment.
    echo [INFO] You can manually configure using:
    echo        python -c "import mcstasscript as ms; c = ms.Configurator(); c.set_mcrun_path('PATH_TO_BIN'); c.set_mcstas_path('PATH_TO_COMPONENTS')"
)
if "%VERBOSE%"=="1" echo [DEBUG] Step 4 complete.
echo.

:: =============================================================================
:: Step 5: Configure Default Settings and Create Shortcuts
:: =============================================================================
echo [Step 5/5] Creating launcher and configuring defaults...
if "%VERBOSE%"=="1" echo [DEBUG] Creating launcher scripts...

:: Ensure output directory exists
echo [INFO] Creating output directory...
if not exist "!INSTALL_DIR!\output" mkdir "!INSTALL_DIR!\output"

:: Create the run script
set "RUN_SCRIPT=%INSTALL_DIR%\run-tavi.bat"
if "%VERBOSE%"=="1" echo [DEBUG] Creating run script: !RUN_SCRIPT!
>"!RUN_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo.
    echo :: Activate the TAVI environment and run
    echo cd /d "!INSTALL_DIR!"
    echo "!MICROMAMBA_DIR!\micromamba.exe" run -n !ENV_NAME! python TAVI_PySide6.py
    echo.
    echo :: Keep window open if there was an error
    echo if errorlevel 1 pause
    echo endlocal
)

:: Create the update script
set "UPDATE_SCRIPT=%INSTALL_DIR%\update-tavi.bat"
if "%VERBOSE%"=="1" echo [DEBUG] Creating update script: !UPDATE_SCRIPT!
>"!UPDATE_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo echo ============================================================================
    echo echo                       TAVI Update Script
    echo echo ============================================================================
    echo echo.
    echo cd /d "!INSTALL_DIR!"
    echo echo [INFO] Updating TAVI from GitHub...
    echo "!MICROMAMBA_DIR!\micromamba.exe" run -n !ENV_NAME! git pull origin main
    echo if errorlevel 1 ^(
    echo     echo [ERROR] Update failed. Please check your internet connection.
    echo ^) else ^(
    echo     echo [OK] TAVI updated successfully!
    echo ^)
    echo echo.
    echo echo [INFO] Updating Python packages...
    echo "!MICROMAMBA_DIR!\micromamba.exe" run -n !ENV_NAME! pip install --upgrade PySide6 mcstasscript
    echo echo.
    echo echo Update complete!
    echo pause
    echo endlocal
)

:: Create the launcher script (menu with options)
set "LAUNCHER_SCRIPT=%INSTALL_DIR%\TAVI-Launcher.bat"
if "%VERBOSE%"=="1" echo [DEBUG] Creating launcher script: !LAUNCHER_SCRIPT!
>"!LAUNCHER_SCRIPT!" (
    echo @echo off
    echo setlocal
    echo title TAVI Launcher
    echo :menu
    echo cls
    echo echo ============================================================================
    echo echo                         TAVI Launcher
    echo echo                  Triple Axis Virtual Instrument
    echo echo ============================================================================
    echo echo.
    echo echo   [1] Run TAVI
    echo echo   [2] Update TAVI ^(download latest version^)
    echo echo   [3] Open TAVI folder
    echo echo   [4] Open TAVI shell ^(for debugging^)
    echo echo   [5] Exit
    echo echo.
    echo echo ============================================================================
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
    echo cd /d "!INSTALL_DIR!"
    echo "!MICROMAMBA_DIR!\micromamba.exe" run -n !ENV_NAME! cmd /k "echo TAVI Shell Ready && echo Type 'python TAVI_PySide6.py' to run TAVI"
    echo goto :menu
    echo endlocal
)

:: Create desktop shortcut using PowerShell
echo [INFO] Creating desktop shortcut...
set "PS_DESKTOP=%USERPROFILE%\Desktop\TAVI Launcher.lnk"
set "PS_TARGET=!LAUNCHER_SCRIPT!"
set "PS_WORKDIR=!INSTALL_DIR!"
powershell -NoProfile -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([System.Environment]::ExpandEnvironmentVariables('!PS_DESKTOP!')); $Shortcut.TargetPath = '!PS_TARGET!'.Replace(\"'\", \"''\"); $Shortcut.WorkingDirectory = '!PS_WORKDIR!'.Replace(\"'\", \"''\"); $Shortcut.Description = 'TAVI - Triple Axis Virtual Instrument'; $Shortcut.Save()"

if !errorlevel! equ 0 (
    echo [OK] Desktop shortcut created.
) else (
    echo [INFO] Desktop shortcut not created. You can run TAVI from: !LAUNCHER_SCRIPT!
)

echo [OK] Launcher scripts created.
if "%VERBOSE%"=="1" echo [DEBUG] Step 5 complete.
echo.

:: =============================================================================
:: Installation Complete
:: =============================================================================
echo ============================================================================
echo                    Installation Complete!
echo ============================================================================
echo.
echo TAVI has been installed to: %INSTALL_DIR%
echo.
echo To run TAVI:
echo   - Double-click "TAVI Launcher" on your desktop
echo   - Or run: !LAUNCHER_SCRIPT!
echo.
echo The launcher provides options to:
echo   [1] Run TAVI
echo   [2] Update to the latest version
echo   [3] Open the TAVI folder
echo   [4] Open a debugging shell
echo.
echo ============================================================================
echo.
echo Press any key to launch TAVI now, or close this window to exit...
pause >nul

:: Launch TAVI
if "%VERBOSE%"=="1" echo [DEBUG] Launching TAVI...
call "!LAUNCHER_SCRIPT!"

endlocal