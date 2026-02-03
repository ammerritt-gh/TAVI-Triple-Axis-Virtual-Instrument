# =============================================================================
# TAVI (Triple Axis Virtual Instrument) Installer for Windows
# =============================================================================
# 
# This PowerShell script provides a one-line installation option:
#   irm https://raw.githubusercontent.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/main/install-tavi.ps1 | iex
#
# Or run directly: powershell -ExecutionPolicy Bypass -File install-tavi.ps1
#
# =============================================================================

$ErrorActionPreference = "Stop"

# Configuration
$INSTALL_DIR = "$env:USERPROFILE\TAVI"
$MICROMAMBA_DIR = "$env:LOCALAPPDATA\micromamba"
$ENV_NAME = "tavi"
$GITHUB_REPO = "https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git"

# Console colors
function Write-Status { param($Message) Write-Host "[STATUS] " -ForegroundColor Cyan -NoNewline; Write-Host $Message }
function Write-Success { param($Message) Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $Message }
function Write-Warning { param($Message) Write-Host "[WARNING] " -ForegroundColor Yellow -NoNewline; Write-Host $Message }
function Write-Error { param($Message) Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $Message }

# Header
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "                    TAVI Installation Script" -ForegroundColor White
Write-Host "                 Triple Axis Virtual Instrument" -ForegroundColor White
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Installation directory: $INSTALL_DIR"
Write-Host "Micromamba directory: $MICROMAMBA_DIR"
Write-Host ""

# =============================================================================
# Step 0: Check for C++ Compiler
# =============================================================================
Write-Status "Checking for C++ compiler..."

$vcvarsLocations = @(
    "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat",
    "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"
)

$vcvarsPath = $vcvarsLocations | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $vcvarsPath) {
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Warning "C++ compiler not found!"
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "McStas requires a C++ compiler to compile instrument simulations." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please install Visual Studio Build Tools:" -ForegroundColor White
    Write-Host "  1. Download from: " -NoNewline
    Write-Host "https://visualstudio.microsoft.com/downloads/" -ForegroundColor Cyan
    Write-Host "  2. Scroll down to 'Tools for Visual Studio'"
    Write-Host "  3. Download 'Build Tools for Visual Studio 2022'"
    Write-Host "  4. Run the installer and select 'Desktop development with C++'"
    Write-Host ""
    Write-Host "After installation, re-run this installer." -ForegroundColor Yellow
    Write-Host ""
    
    $response = Read-Host "Open download page now? (Y/N)"
    if ($response -eq 'Y' -or $response -eq 'y') {
        Start-Process "https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022"
    }
    exit 1
}

Write-Success "Visual Studio Build Tools found at: $vcvarsPath"
Write-Host ""

# =============================================================================
# Step 1: Install Micromamba
# =============================================================================
Write-Status "Setting up micromamba package manager..."

# Create directories
New-Item -ItemType Directory -Force -Path $MICROMAMBA_DIR | Out-Null

$micromambaExe = "$MICROMAMBA_DIR\micromamba.exe"

if (-not (Test-Path $micromambaExe)) {
    Write-Status "Downloading micromamba..."
    $mambaUrl = "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64"
    
    try {
        Invoke-WebRequest -Uri $mambaUrl -OutFile $micromambaExe
        Write-Success "Micromamba downloaded successfully."
    }
    catch {
        Write-Error "Failed to download micromamba: $_"
        exit 1
    }
}
else {
    Write-Success "Micromamba already installed."
}

# Configure channels
& $micromambaExe config append channels conda-forge 2>$null
& $micromambaExe config set channel_priority strict 2>$null
Write-Success "Micromamba configured."
Write-Host ""

# =============================================================================
# Step 2: Create/Update TAVI Environment
# =============================================================================
Write-Status "Creating Python environment with McStas..."

# Check if environment exists
$envList = & $micromambaExe env list 2>$null
$envExists = $envList -match $ENV_NAME

if ($envExists) {
    Write-Warning "Environment '$ENV_NAME' already exists."
    $response = Read-Host "Recreate it (Y) or keep existing (N)?"
    
    if ($response -eq 'Y' -or $response -eq 'y') {
        Write-Status "Removing existing environment..."
        & $micromambaExe env remove -n $ENV_NAME -y 2>$null
        $createEnv = $true
    }
    else {
        $createEnv = $false
    }
}
else {
    $createEnv = $true
}

if ($createEnv) {
    Write-Status "Creating new environment with McStas and dependencies..."
    Write-Host "This may take 5-15 minutes depending on your internet connection..." -ForegroundColor Yellow
    Write-Host ""
    
    & $micromambaExe create -n $ENV_NAME `
        python=3.11 `
        mcstas `
        mcstas-core `
        numpy `
        scipy `
        matplotlib `
        h5py `
        pyyaml `
        git `
        -c conda-forge -c nodefaults -y
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create environment."
        exit 1
    }
    
    Write-Success "Conda environment created successfully."
}

# Install pip packages
Write-Status "Installing PySide6 and mcstasscript via pip..."
& $micromambaExe run -n $ENV_NAME pip install --upgrade pip 2>$null
& $micromambaExe run -n $ENV_NAME pip install PySide6 mcstasscript

Write-Success "Python packages installed."
Write-Host ""

# =============================================================================
# Step 3: Download/Update TAVI
# =============================================================================
Write-Status "Downloading TAVI from GitHub..."

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Set-Location $INSTALL_DIR

if (Test-Path "$INSTALL_DIR\.git") {
    Write-Status "TAVI repository already exists. Updating..."
    & $micromambaExe run -n $ENV_NAME git pull origin main
    if ($LASTEXITCODE -eq 0) {
        Write-Success "TAVI updated to latest version."
    }
    else {
        Write-Warning "Could not update TAVI. Will use existing version."
    }
}
else {
    Write-Status "Cloning TAVI repository..."
    & $micromambaExe run -n $ENV_NAME git clone $GITHUB_REPO .
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to clone TAVI repository."
        Write-Host "Please check your internet connection and try again."
        exit 1
    }
    
    Write-Success "TAVI downloaded successfully."
}
Write-Host ""

# =============================================================================
# Step 4: Configure McStasScript
# =============================================================================
Write-Status "Configuring McStasScript for McStas..."

# Get Python path and derive McStas paths
$pythonPath = & $micromambaExe run -n $ENV_NAME python -c "import os, sys; print(os.path.dirname(sys.executable))"
$mcstasBin = Join-Path (Split-Path $pythonPath -Parent) "Library\bin"
$mcstasLib = Join-Path (Split-Path $pythonPath -Parent) "Library\share\mcstas"

# Create configuration script
$configScript = @"
import mcstasscript as ms
configurator = ms.Configurator()
configurator.set_mcrun_path(r"$mcstasBin\\")
configurator.set_mcstas_path(r"$mcstasLib\\")
print("McStasScript configured successfully!")
print("  mcrun path:", r"$mcstasBin")
print("  mcstas path:", r"$mcstasLib")
"@

$configScript | Out-File -FilePath "$INSTALL_DIR\configure_mcstas.py" -Encoding UTF8
& $micromambaExe run -n $ENV_NAME python "$INSTALL_DIR\configure_mcstas.py"
Write-Host ""

# =============================================================================
# Step 5: Create Launcher Scripts
# =============================================================================
Write-Status "Creating launcher scripts..."

# Run script
$runScript = @"
@echo off
setlocal

:: Find Visual Studio vcvarsall.bat
set "VCVARS="
if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvarsall.bat"

:: Initialize Visual Studio environment if found
if defined VCVARS (
    call "%VCVARS%" x64 >nul 2>&1
)

:: Activate the TAVI environment and run
cd /d "$INSTALL_DIR"
"$micromambaExe" run -n $ENV_NAME python TAVI_PySide6.py

:: Keep window open if there was an error
if errorlevel 1 pause
endlocal
"@

$runScript | Out-File -FilePath "$INSTALL_DIR\run-tavi.bat" -Encoding ASCII

# Update script
$updateScript = @"
@echo off
setlocal
echo ============================================================================
echo                       TAVI Update Script
echo ============================================================================
echo.
cd /d "$INSTALL_DIR"
echo [INFO] Updating TAVI from GitHub...
"$micromambaExe" run -n $ENV_NAME git pull origin main
if errorlevel 1 (
    echo [ERROR] Update failed. Please check your internet connection.
) else (
    echo [OK] TAVI updated successfully!
)
echo.
echo [INFO] Updating Python packages...
"$micromambaExe" run -n $ENV_NAME pip install --upgrade PySide6 mcstasscript
echo.
echo Update complete!
pause
endlocal
"@

$updateScript | Out-File -FilePath "$INSTALL_DIR\update-tavi.bat" -Encoding ASCII

# Launcher script
$launcherScript = @"
@echo off
setlocal
title TAVI Launcher
:menu
cls
echo ============================================================================
echo                         TAVI Launcher
echo                  Triple Axis Virtual Instrument
echo ============================================================================
echo.
echo   [1] Run TAVI
echo   [2] Update TAVI (download latest version)
echo   [3] Open TAVI folder
echo   [4] Open TAVI shell (for debugging)
echo   [5] Exit
echo.
echo ============================================================================
echo.
choice /C 12345 /M "Select option"

if errorlevel 5 exit /b 0
if errorlevel 4 goto :shell
if errorlevel 3 goto :folder
if errorlevel 2 goto :update
if errorlevel 1 goto :run
goto :menu

:run
call "$INSTALL_DIR\run-tavi.bat"
goto :menu

:update
call "$INSTALL_DIR\update-tavi.bat"
goto :menu

:folder
explorer "$INSTALL_DIR"
goto :menu

:shell
:: Find Visual Studio vcvarsall.bat
set "VCVARS="
if exist "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvarsall.bat"
if exist "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat" set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvarsall.bat"

:: Initialize Visual Studio environment if found
if defined VCVARS (
    call "%VCVARS%" x64 >nul 2>&1
)

cd /d "$INSTALL_DIR"
"$micromambaExe" run -n $ENV_NAME cmd /k "echo TAVI Shell Ready && echo Type 'python TAVI_PySide6.py' to run TAVI"
goto :menu
endlocal
"@

$launcherScript | Out-File -FilePath "$INSTALL_DIR\TAVI-Launcher.bat" -Encoding ASCII

# Create desktop shortcut
Write-Status "Creating desktop shortcut..."
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\TAVI Launcher.lnk")
$Shortcut.TargetPath = "$INSTALL_DIR\TAVI-Launcher.bat"
$Shortcut.WorkingDirectory = $INSTALL_DIR
$Shortcut.Description = "TAVI - Triple Axis Virtual Instrument"
$Shortcut.Save()

Write-Success "Desktop shortcut created."
Write-Host ""

# =============================================================================
# Installation Complete
# =============================================================================
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "                    Installation Complete!" -ForegroundColor White
Write-Host "============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "TAVI has been installed to: " -NoNewline
Write-Host $INSTALL_DIR -ForegroundColor Cyan
Write-Host ""
Write-Host "To run TAVI:"
Write-Host "  - Double-click 'TAVI Launcher' on your desktop"
Write-Host "  - Or run: " -NoNewline
Write-Host "$INSTALL_DIR\TAVI-Launcher.bat" -ForegroundColor Cyan
Write-Host ""
Write-Host "The launcher provides options to:"
Write-Host "  [1] Run TAVI"
Write-Host "  [2] Update to the latest version"
Write-Host "  [3] Open the TAVI folder"
Write-Host "  [4] Open a debugging shell"
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Green
Write-Host ""

$response = Read-Host "Launch TAVI now? (Y/N)"
if ($response -eq 'Y' -or $response -eq 'y') {
    & "$INSTALL_DIR\TAVI-Launcher.bat"
}
