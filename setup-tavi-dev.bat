@echo off
setlocal DisableDelayedExpansion

:: TAVI developer environment setup.
:: Builds the 'tavi-dev' micromamba environment from scratch on any Windows user
:: account. Portable: every path derives from %USERPROFILE% and this script's own
:: location (%~dp0). Run run-tavi-dev.bat afterwards to launch the GUI.

set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"
set "MAMBA_VERSION=2.5.0-1"
set "MAMBA_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"
set "ENV_NAME=tavi-dev"

set "REPO_DIR=%~dp0"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"

set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git"

title TAVI Dev Environment Setup

echo ============================================================================
echo                  TAVI Developer Environment Setup
echo                  Environment: %ENV_NAME%
echo ============================================================================
echo.
echo This builds a self-contained micromamba environment for TAVI development:
echo   micromamba : %MICROMAMBA_DIR%
echo   env prefix : %ENV_PREFIX%
echo   repo       : %REPO_DIR%
echo.

echo [Step 1/5] Checking Visual Studio compiler (advisory)...
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    "%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%TEMP%\tavidev_vs.txt" 2>nul
    set /p VSINSTALLDIR=<"%TEMP%\tavidev_vs.txt"
    del "%TEMP%\tavidev_vs.txt" >nul 2>nul
)
if exist "%ProgramFiles(x86)%\Microsoft SDKs\MPI\Include\mpi.h" (
    echo [OK] Microsoft MPI SDK found.
) else (
    echo [WARN] Microsoft MPI SDK not found. Basic simulations may still work.
)
echo.

echo [Step 2/5] Setting up micromamba...
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
    certutil -hashfile "%MICROMAMBA_EXE%.tmp" SHA256 | findstr /i /c:"%MAMBA_SHA256%" >nul
    if errorlevel 1 (
        echo [ERROR] Micromamba checksum verification failed.
        del "%MICROMAMBA_EXE%.tmp" >nul 2>nul
        pause
        exit /b 1
    )
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

echo [Step 3/5] Creating or updating environment '%ENV_NAME%'...
echo [INFO] Packages:
echo        %CONDA_PACKAGES%
"%MICROMAMBA_EXE%" env list > "%TEMP%\tavidev_envs.txt" 2>nul
findstr /r /c:"^%ENV_NAME%[ ]" "%TEMP%\tavidev_envs.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    del "%TEMP%\tavidev_envs.txt" >nul 2>nul
    echo [INFO] Environment '%ENV_NAME%' exists; updating in place.
    "%MICROMAMBA_EXE%" install -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
    if errorlevel 1 echo [WARN] Conda update reported an error; continuing to pip step.
) else (
    del "%TEMP%\tavidev_envs.txt" >nul 2>nul
    echo [INFO] Creating environment '%ENV_NAME%'.
    "%MICROMAMBA_EXE%" create -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
    if errorlevel 1 (
        echo [ERROR] Failed to create environment.
        pause
        exit /b 1
    )
)
echo.

echo [Step 4/5] Installing Python packages from requirements...
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python -m pip install --upgrade pip
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python -m pip install -r "%REPO_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install runtime requirements.
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python -m pip install -r "%REPO_DIR%requirements-dev.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dev requirements.
    pause
    exit /b 1
)
echo [OK] Python packages ready.
echo.

echo [Step 5/5] Configuring McStas / McStasScript paths...
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
echo [OK] McStas resources: %MCSTAS_RESOURCES%
echo [OK] mcrun directory : %MCRUN_DIR%

> "%TEMP%\tavidev_config.py" echo import mcstasscript as ms
>> "%TEMP%\tavidev_config.py" echo c = ms.Configurator()
>> "%TEMP%\tavidev_config.py" echo c.set_mcrun_path(r"%MCRUN_DIR%")
>> "%TEMP%\tavidev_config.py" echo c.set_mcstas_path(r"%MCSTAS_RESOURCES%")
>> "%TEMP%\tavidev_config.py" echo print("[TAVI] McStasScript configured")
"%MICROMAMBA_EXE%" run -n %ENV_NAME% python "%TEMP%\tavidev_config.py"
set "MCSTAS_CONFIG_EXIT=%ERRORLEVEL%"
del "%TEMP%\tavidev_config.py" >nul 2>nul
if not "%MCSTAS_CONFIG_EXIT%"=="0" (
    echo [ERROR] McStasScript path configuration failed.
    pause
    exit /b %MCSTAS_CONFIG_EXIT%
)

echo [INFO] Writing config\mcstas_config.json to point at this environment...
set "MCSTAS_JSON=%MCSTAS_RESOURCES:\=/%"
set "MCRUN_JSON=%MCRUN_DIR:\=/%"
if not exist "%REPO_DIR%config" mkdir "%REPO_DIR%config"
> "%REPO_DIR%config\mcstas_config.json" echo {
>> "%REPO_DIR%config\mcstas_config.json" echo     "mcstas_path": "%MCSTAS_JSON%",
>> "%REPO_DIR%config\mcstas_config.json" echo     "mcrun_path": "%MCRUN_JSON%",
>> "%REPO_DIR%config\mcstas_config.json" echo     "auto_detect": true
>> "%REPO_DIR%config\mcstas_config.json" echo }
echo [OK] config\mcstas_config.json -^> %MCSTAS_JSON%
echo.

echo ============================================================================
echo Setup complete.
echo Environment : %ENV_NAME%
echo McStas      : %MCSTAS_VERSION%
echo.
echo Run the GUI    : run-tavi-dev.bat
echo Run the tests  : "%MICROMAMBA_EXE%" run -n %ENV_NAME% python -m pytest tests -q
echo ============================================================================
echo.
pause
endlocal
