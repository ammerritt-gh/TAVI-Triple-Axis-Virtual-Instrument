@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: TAVI (Triple Axis Virtual Instrument) Installer for Windows
:: =============================================================================
:: This script installs TAVI along with McStas for neutron scattering simulations.
:: 
:: Prerequisites that must be installed manually:
::   - Visual Studio Build Tools with C++ support (for McStas compilation)
::
:: What this script does:
::   1. Installs micromamba (lightweight conda package manager)
::   2. Creates a 'tavi' environment with McStas and Python dependencies
::   3. Downloads the latest TAVI from GitHub
::   4. Creates desktop shortcuts for running and updating TAVI
:: =============================================================================

title TAVI Installer

echo ============================================================================
echo                    TAVI Installation Script
echo                 Triple Axis Virtual Instrument
echo ============================================================================
echo.

:: Check for administrator privileges (recommended but not required)
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
:: Step 0: Check for C++ Compiler
:: =============================================================================
echo [Step 0/5] Checking for C++ compiler...

where cl >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] C++ compiler found in PATH.
) else (
    :: Check for Visual Studio Build Tools installation
    set "VS_FOUND=0"
    if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VS_FOUND=1"
    
    if "!VS_FOUND!"=="1" (
        echo [OK] Visual Studio Build Tools found.
        echo [INFO] The compiler will be available when running from the TAVI launcher.
    ) else (
        echo.
        echo ============================================================================
        echo [WARNING] C++ compiler not found!
        echo ============================================================================
        echo.
        echo McStas requires a C++ compiler to compile instrument simulations.
        echo.
        echo Please install Visual Studio Build Tools:
        echo   1. Download from: https://visualstudio.microsoft.com/downloads/
        echo   2. Scroll down to "Tools for Visual Studio"
        echo   3. Download "Build Tools for Visual Studio 2022"
        echo   4. Run the installer and select "Desktop development with C++"
        echo.
        echo After installation, re-run this installer.
        echo.
        echo Press any key to open the download page and exit...
        pause >nul
        start https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
        exit /b 1
    )
)
echo.

:: =============================================================================
:: Step 1: Install Micromamba
:: =============================================================================
echo [Step 1/5] Setting up micromamba package manager...

:: Create micromamba directory
if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
cd /d "%MICROMAMBA_DIR%"

:: Download micromamba if not present or if it's outdated
if not exist "%MICROMAMBA_DIR%\micromamba.exe" (
    echo [INFO] Downloading micromamba...
    set "MAMBA_URL=https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64"
    curl -L -o micromamba.exe "%MAMBA_URL%"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to download micromamba.
        echo [INFO] Please check your internet connection and try again.
        pause
        exit /b 1
    )
    echo [OK] Micromamba downloaded successfully.
) else (
    echo [OK] Micromamba already installed.
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

:: Check if environment exists
"%MICROMAMBA_DIR%\micromamba.exe" env list 2>nul | findstr /C:"%ENV_NAME%" >nul
if %errorlevel% equ 0 (
    echo [INFO] Environment '%ENV_NAME%' already exists.
    
    choice /C YN /M "Do you want to recreate it (Y) or keep existing (N)?"
    if !errorlevel!==1 (
        echo [INFO] Removing existing environment...
        "%MICROMAMBA_DIR%\micromamba.exe" env remove -n %ENV_NAME% -y >nul 2>&1
        goto :create_env
    ) else (
        echo [INFO] Keeping existing environment.
        goto :update_env
    )
) else (
    goto :create_env
)

:create_env
echo [INFO] Creating new environment with McStas and dependencies...
echo [INFO] This may take 5-15 minutes depending on your internet connection...
echo.

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

if %errorlevel% neq 0 (
    echo [ERROR] Failed to create environment.
    pause
    exit /b 1
)

echo [OK] Conda environment created successfully.

:update_env
:: Install pip packages (PySide6 and mcstasscript)
echo [INFO] Installing PySide6 and mcstasscript via pip...
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade pip >nul 2>&1
"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install PySide6 mcstasscript

if %errorlevel% neq 0 (
    echo [WARNING] Some pip packages may not have installed correctly.
    echo [INFO] You can try installing them manually later.
)

echo [OK] Python packages installed.
echo.

:: =============================================================================
:: Step 3: Download/Update TAVI
:: =============================================================================
echo [Step 3/5] Downloading TAVI from GitHub...

:: Create TAVI directory
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
cd /d "%INSTALL_DIR%"

:: Check if TAVI is already cloned
if exist "%INSTALL_DIR%\.git" (
    echo [INFO] TAVI repository already exists. Updating...
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git pull origin main
    if %errorlevel% neq 0 (
        echo [WARNING] Could not update TAVI. Will use existing version.
    ) else (
        echo [OK] TAVI updated to latest version.
    )
) else (
    echo [INFO] Cloning TAVI repository...
    "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git clone https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to clone TAVI repository.
        echo [INFO] Please check your internet connection and try again.
        echo [INFO] You can also manually download from:
        echo        https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument
        pause
        exit /b 1
    )
    echo [OK] TAVI downloaded successfully.
)
echo.

:: =============================================================================
:: Step 4: Configure McStasScript
:: =============================================================================
echo [Step 4/5] Configuring McStasScript for McStas...

:: Get the McStas paths from the conda environment
for /f "tokens=*" %%i in ('"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python -c "import os, sys; print(os.path.dirname(sys.executable))"') do set "PYTHON_BIN=%%i"
set "MCSTAS_BIN=%PYTHON_BIN%\..\Library\bin"
set "MCSTAS_LIB=%PYTHON_BIN%\..\Library\share\mcstas"

:: Create configuration script
echo import mcstasscript as ms > "%INSTALL_DIR%\configure_mcstas.py"
echo configurator = ms.Configurator() >> "%INSTALL_DIR%\configure_mcstas.py"
echo configurator.set_mcrun_path(r"%MCSTAS_BIN%\\") >> "%INSTALL_DIR%\configure_mcstas.py"
echo configurator.set_mcstas_path(r"%MCSTAS_LIB%\\") >> "%INSTALL_DIR%\configure_mcstas.py"
echo print("McStasScript configured successfully!") >> "%INSTALL_DIR%\configure_mcstas.py"
echo print("  mcrun path:", r"%MCSTAS_BIN%") >> "%INSTALL_DIR%\configure_mcstas.py"
echo print("  mcstas path:", r"%MCSTAS_LIB%") >> "%INSTALL_DIR%\configure_mcstas.py"

"%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python "%INSTALL_DIR%\configure_mcstas.py"
if %errorlevel% neq 0 (
    echo [WARNING] McStasScript configuration may need manual adjustment.
)
echo.

:: =============================================================================
:: Step 5: Create Desktop Shortcuts
:: =============================================================================
echo [Step 5/5] Creating desktop shortcuts...

:: Create the run script
set "RUN_SCRIPT=%INSTALL_DIR%\run-tavi.bat"
(
echo @echo off
echo setlocal
echo.
echo :: Find Visual Studio vcvarsall.bat
echo set "VCVARS="
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files ^(x86^)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files ^(x86^)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files ^(x86^)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files ^(x86^)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"
echo.
echo :: Initialize Visual Studio environment if found
echo if defined VCVARS ^(
echo     call "%%VCVARS%%" x64 ^>nul 2^>^&1
echo ^)
echo.
echo :: Activate the TAVI environment and run
echo cd /d "%INSTALL_DIR%"
echo "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% python TAVI_PySide6.py
echo.
echo :: Keep window open if there was an error
echo if errorlevel 1 pause
echo endlocal
) > "%RUN_SCRIPT%"

:: Create the update script
set "UPDATE_SCRIPT=%INSTALL_DIR%\update-tavi.bat"
(
echo @echo off
echo setlocal
echo echo ============================================================================
echo echo                       TAVI Update Script
echo echo ============================================================================
echo echo.
echo cd /d "%INSTALL_DIR%"
echo echo [INFO] Updating TAVI from GitHub...
echo "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% git pull origin main
echo if errorlevel 1 ^(
echo     echo [ERROR] Update failed. Please check your internet connection.
echo ^) else ^(
echo     echo [OK] TAVI updated successfully!
echo ^)
echo echo.
echo echo [INFO] Updating Python packages...
echo "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% pip install --upgrade PySide6 mcstasscript
echo echo.
echo echo Update complete!
echo pause
echo endlocal
) > "%UPDATE_SCRIPT%"

:: Create the launcher script (menu with options)
set "LAUNCHER_SCRIPT=%INSTALL_DIR%\TAVI-Launcher.bat"
(
echo @echo off
echo setlocal
echo title TAVI Launcher
echo :menu
echo cls
echo ============================================================================
echo                         TAVI Launcher
echo                  Triple Axis Virtual Instrument
echo ============================================================================
echo.
echo   [1] Run TAVI
echo   [2] Update TAVI ^(download latest version^)
echo   [3] Open TAVI folder
echo   [4] Open TAVI shell ^(for debugging^)
echo   [5] Exit
echo.
echo ============================================================================
echo.
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
echo call "%RUN_SCRIPT%"
echo goto :menu
echo.
echo :update
echo call "%UPDATE_SCRIPT%"
echo goto :menu
echo.
echo :folder
echo explorer "%INSTALL_DIR%"
echo goto :menu
echo.
echo :shell
echo :: Find Visual Studio vcvarsall.bat
echo set "VCVARS="
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat"
echo if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"
echo.
echo :: Initialize Visual Studio environment if found
echo if defined VCVARS ^(
echo     call "%%VCVARS%%" x64 ^>nul 2^>^&1
echo ^)
echo.
echo cd /d "%INSTALL_DIR%"
echo "%MICROMAMBA_DIR%\micromamba.exe" run -n %ENV_NAME% cmd /k "echo TAVI Shell Ready && echo Type 'python TAVI_PySide6.py' to run TAVI"
echo goto :menu
echo endlocal
) > "%LAUNCHER_SCRIPT%"

:: Create desktop shortcut using PowerShell
echo [INFO] Creating desktop shortcut...
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%USERPROFILE%\Desktop\TAVI Launcher.lnk'); $Shortcut.TargetPath = '%LAUNCHER_SCRIPT%'; $Shortcut.WorkingDirectory = '%INSTALL_DIR%'; $Shortcut.Description = 'TAVI - Triple Axis Virtual Instrument'; $Shortcut.Save()"

if %errorlevel% equ 0 (
    echo [OK] Desktop shortcut created.
) else (
    echo [WARNING] Could not create desktop shortcut.
    echo [INFO] You can run TAVI from: %LAUNCHER_SCRIPT%
)
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
echo   - Or run: %LAUNCHER_SCRIPT%
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
call "%LAUNCHER_SCRIPT%"

endlocal
