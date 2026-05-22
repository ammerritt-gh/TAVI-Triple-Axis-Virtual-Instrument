@echo off
setlocal DisableDelayedExpansion

:: TAVI Windows installer - fixed8
:: Conservative batch style: no micromamba shell init, no generated echo blocks,
:: no delayed expansion, and no nested cmd AutoRun dependency except where unavoidable.

set "TAVI_VERSION=main"
set "PYTHON_VERSION=3.11"
set "MCSTAS_VERSION=3.7.1"
set "MAMBA_VERSION=2.5.0-1"
set "EXPECTED_SHA256=56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"

set "INSTALL_DIR=%USERPROFILE%\TAVI"
set "MICROMAMBA_DIR=%USERPROFILE%\AppData\Local\micromamba"
set "MICROMAMBA_EXE=%MICROMAMBA_DIR%\micromamba.exe"
set "ENV_NAME=tavi"
set "MAMBA_ROOT_PREFIX=%USERPROFILE%\AppData\Roaming\mamba"
set "ENV_PREFIX=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%"
set "SHORTCUT=%USERPROFILE%\Desktop\TAVI Launcher.lnk"

title TAVI Installer

echo ============================================================================
echo                    TAVI Installation Script
echo                 Triple Axis Virtual Instrument
echo                 Release: %TAVI_VERSION%
echo ============================================================================
echo.

echo This installer will set up TAVI for this Windows user account.
echo.
echo It will do the following:
echo   1. Check for a Visual Studio C++ compiler bootstrap.
echo   2. Check for Microsoft MPI SDK headers/libraries.
echo   3. Install or reuse micromamba at:
echo      %MICROMAMBA_DIR%
echo   4. Create or update the micromamba environment:
echo      %ENV_NAME%
echo   5. Install or update TAVI at:
echo      %INSTALL_DIR%
echo   6. Configure McStas/McStasScript paths for the installed environment.
echo   7. Create run/update/launcher scripts inside the TAVI folder.
echo.
echo This installer will NOT run micromamba shell init.
echo This installer will NOT remove your whole micromamba installation.
echo This installer may remove a broken cmd.exe AutoRun hook only if it contains
echo micromamba or mamba text from a previous failed install.
echo.
echo If an existing '%ENV_NAME%' environment is found, you will be asked whether to
echo recreate it or update it in place before any removal occurs.
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

echo [Step 1/7] Checking Visual Studio compiler...
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VCVARS="
if exist "%VSWHERE%" (
    "%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%TEMP%\tavi_vs.txt" 2>nul
    set /p VSINSTALLDIR=<"%TEMP%\tavi_vs.txt"
    del "%TEMP%\tavi_vs.txt" >nul 2>nul
    if not "%VSINSTALLDIR%"=="" (
        if exist "%VSINSTALLDIR%\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%VSINSTALLDIR%\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if "%VCVARS%"=="" (
    echo [WARN] Visual Studio compiler bootstrap not found. McStas compilation may fail.
) else (
    echo [OK] Visual Studio bootstrap: %VCVARS%
)
echo.

echo [Step 2/7] Checking Microsoft MPI SDK...
set "MPI_INCLUDE="
set "MPI_LIB="
if exist "%ProgramFiles(x86)%\Microsoft SDKs\MPI\Include\mpi.h" (
    set "MPI_INCLUDE=%ProgramFiles(x86)%\Microsoft SDKs\MPI\Include"
    set "MPI_LIB=%ProgramFiles(x86)%\Microsoft SDKs\MPI\Lib\x64"
    echo [OK] Microsoft MPI SDK found.
) else (
    echo [WARN] Microsoft MPI SDK not found. Basic simulations may still work.
)
echo.

echo [Step 3/7] Setting up micromamba...
if not exist "%MICROMAMBA_DIR%" mkdir "%MICROMAMBA_DIR%"
if not exist "%MICROMAMBA_EXE%" (
    echo [INFO] Downloading micromamba %MAMBA_VERSION%...
    curl -L -o "%MICROMAMBA_EXE%.tmp" "https://github.com/mamba-org/micromamba-releases/releases/download/%MAMBA_VERSION%/micromamba-win-64"
    if errorlevel 1 (
        echo [ERROR] Failed to download micromamba.
        pause
        exit /b 1
    )
    move /Y "%MICROMAMBA_EXE%.tmp" "%MICROMAMBA_EXE%" >nul
)
if not exist "%MICROMAMBA_EXE%" (
    echo [ERROR] micromamba.exe not found at %MICROMAMBA_EXE%
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" --version
echo [OK] Micromamba ready.
echo.

echo [Step 4/7] Creating or updating environment '%ENV_NAME%'...
set "CONDA_PACKAGES=python=%PYTHON_VERSION% mcstas=%MCSTAS_VERSION% mcstas-core=%MCSTAS_VERSION% mcstas-data=%MCSTAS_VERSION% mcstas-mcgui=%MCSTAS_VERSION% mcstas-vis=%MCSTAS_VERSION% numpy scipy matplotlib h5py pyyaml git"

"%MICROMAMBA_EXE%" env list > "%TEMP%\tavi_envs.txt" 2>nul
findstr /r /c:"^%ENV_NAME%[ ]" "%TEMP%\tavi_envs.txt" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    echo [INFO] Environment '%ENV_NAME%' already exists.
    choice /C YN /M "Recreate from scratch (Y) or update in place (N)"
    if errorlevel 2 goto update_env
    if errorlevel 1 goto remove_env
)

if exist "%ENV_PREFIX%" (
    if exist "%ENV_PREFIX%\conda-meta\history" (
        echo [WARN] Environment folder exists but was not listed by micromamba:
        echo        %ENV_PREFIX%
        choice /C YN /M "Treat this as an existing environment and update in place"
        if errorlevel 2 goto broken_prefix
        if errorlevel 1 goto update_env
    ) else (
        goto broken_prefix
    )
)
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
if exist "%ENV_PREFIX%" (
    set "REMOVED_ENV_BACKUP=%MAMBA_ROOT_PREFIX%\envs\%ENV_NAME%_old_%RANDOM%_%RANDOM%"
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
goto pip_packages

:update_env
echo [INFO] Updating environment with packages:
echo        %CONDA_PACKAGES%
"%MICROMAMBA_EXE%" install -n %ENV_NAME% %CONDA_PACKAGES% -c conda-forge -c nodefaults -y
if errorlevel 1 echo [WARN] Conda update reported an error; continuing to pip step.

:pip_packages
echo [INFO] Installing/upgrading pip packages...
"%MICROMAMBA_EXE%" run -n %ENV_NAME% pip install --upgrade pip
"%MICROMAMBA_EXE%" run -n %ENV_NAME% pip install --upgrade PySide6 mcstasscript
if errorlevel 1 (
    echo [ERROR] Pip package install failed.
    pause
    exit /b 1
)
echo [OK] Python packages ready.
echo.

echo [Step 5/7] Installing or updating TAVI source...
if exist "%INSTALL_DIR%\.git" goto update_repo
if exist "%INSTALL_DIR%" goto backup_existing
goto clone_repo

:backup_existing
echo [WARN] %INSTALL_DIR% exists but is not a Git repository.
set "BACKUP_DIR=%USERPROFILE%\TAVI_backup_%RANDOM%_%RANDOM%"
echo [INFO] Moving existing folder to: %BACKUP_DIR%
ren "%INSTALL_DIR%" "%~nx0_TAVI_BACKUP_DO_NOT_USE" >nul 2>nul
if exist "%INSTALL_DIR%" (
    move "%INSTALL_DIR%" "%BACKUP_DIR%" >nul 2>nul
)
if exist "%INSTALL_DIR%" (
    echo [ERROR] Could not move existing TAVI folder.
    echo [INFO] Close Explorer/editors/terminals using %INSTALL_DIR%, or manually rename it.
    pause
    exit /b 1
)
goto clone_repo

:update_repo
echo [INFO] Existing TAVI Git repository found. Updating...
cd /d "%INSTALL_DIR%"
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git fetch origin
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git checkout %TAVI_VERSION%
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git pull --ff-only origin %TAVI_VERSION%
if errorlevel 1 echo [WARN] Git update reported an error; continuing with current checkout.
goto verify_repo

:clone_repo
mkdir "%INSTALL_DIR%" 2>nul
cd /d "%INSTALL_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not enter install directory: %INSTALL_DIR%
    pause
    exit /b 1
)
"%MICROMAMBA_EXE%" run -n %ENV_NAME% git clone --branch %TAVI_VERSION% --single-branch https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument.git .
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
echo [OK] TAVI source ready.
echo.

echo [Step 6/7] Detecting McStas paths...
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

echo [Step 7/7] Creating launchers...
set "RUN_SCRIPT=%INSTALL_DIR%\run-tavi.bat"
set "UPDATE_SCRIPT=%INSTALL_DIR%\update-tavi.bat"
set "LAUNCHER_SCRIPT=%INSTALL_DIR%\TAVI-Launcher.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCmNkIC9kICJfX0lOU1RBTExfRElSX18iCnNldCAiTUNTVEFTPV9fTUNTVEFTX1JFU09VUkNFU19fIgpzZXQgIk1DU1RBU19DT01QT05FTlRfUEFUSD0lTUNTVEFTJSIKZWNobyBbVEFWSV0gTUNTVEFTPSVNQ1NUQVMlCgppZiBub3QgZXhpc3QgIiVNQ1NUQVMlIiAoCiAgICBlY2hvIFtFUlJPUl0gTWNTdGFzIHJlc291cmNlIGRpcmVjdG9yeSBub3QgZm91bmQ6CiAgICBlY2hvICAgICAgICAgJU1DU1RBUyUKICAgIHBhdXNlCiAgICBleGl0IC9iIDEKKQoKaWYgbm90ICJfX1ZDVkFSU19fIj09IiIgKAogICAgY2FsbCAiX19WQ1ZBUlNfXyIgeDY0CikKCmlmIG5vdCAiX19NUElfSU5DTFVERV9fIj09IiIgc2V0ICJJTkNMVURFPSVJTkNMVURFJTtfX01QSV9JTkNMVURFX18iCmlmIG5vdCAiX19NUElfTElCX18iPT0iIiBzZXQgIkxJQj0lTElCJTtfX01QSV9MSUJfXyIKCiJfX01JQ1JPTUFNQkFfRVhFX18iIHJ1biAtbiBfX0VOVl9OQU1FX18gcHl0aG9uIFRBVklfUHlTaWRlNi5weQppZiBlcnJvcmxldmVsIDEgcGF1c2UKZW5kbG9jYWwK')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__MCSTAS_RESOURCES__',$env:MCSTAS_RESOURCES).Replace('__VCVARS__',$env:VCVARS).Replace('__MPI_INCLUDE__',$env:MPI_INCLUDE).Replace('__MPI_LIB__',$env:MPI_LIB); Set-Content -Path $env:RUN_SCRIPT -Value $s -Encoding ASCII"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCmNkIC9kICJfX0lOU1RBTExfRElSX18iCmVjaG8gPT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PQplY2hvICAgICAgICAgICAgICAgICAgICAgICBUQVZJIFVwZGF0ZSBTY3JpcHQKZWNobyAgICAgICAgICAgICAgICAgICAgICAgUmVsZWFzZTogX19UQVZJX1ZFUlNJT05fXwplY2hvID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0KZWNoby4KZWNobyBbSU5GT10gRmV0Y2hpbmcgZnJvbSBHaXRIdWIuLi4KIl9fTUlDUk9NQU1CQV9FWEVfXyIgcnVuIC1uIF9fRU5WX05BTUVfXyBnaXQgZmV0Y2ggb3JpZ2luCmlmIGVycm9ybGV2ZWwgMSBnb3RvIDpmYWlsCgplY2hvIFtJTkZPXSBDaGVja2luZyBvdXQgX19UQVZJX1ZFUlNJT05fXy4uLgoiX19NSUNST01BTUJBX0VYRV9fIiBydW4gLW4gX19FTlZfTkFNRV9fIGdpdCBjaGVja291dCBfX1RBVklfVkVSU0lPTl9fCmlmIGVycm9ybGV2ZWwgMSBnb3RvIDpmYWlsCgoiX19NSUNST01BTUJBX0VYRV9fIiBydW4gLW4gX19FTlZfTkFNRV9fIGdpdCBwdWxsIC0tZmYtb25seSBvcmlnaW4gX19UQVZJX1ZFUlNJT05fXwppZiBlcnJvcmxldmVsIDEgZ290byA6ZmFpbAoKZWNobyBbSU5GT10gVXBkYXRpbmcgcGlwIHBhY2thZ2VzLi4uCiJfX01JQ1JPTUFNQkFfRVhFX18iIHJ1biAtbiBfX0VOVl9OQU1FX18gcGlwIGluc3RhbGwgLS11cGdyYWRlIFB5U2lkZTYgbWNzdGFzc2NyaXB0CgplY2hvLgplY2hvIFtPS10gVXBkYXRlIGNvbXBsZXRlLgpwYXVzZQpleGl0IC9iIDAKCjpmYWlsCmVjaG8gW0VSUk9SXSBVcGRhdGUgZmFpbGVkLiBDaGVjayB5b3VyIGludGVybmV0IGNvbm5lY3Rpb24gb3IgbG9jYWwgY2hhbmdlcy4KcGF1c2UKZXhpdCAvYiAxCg==')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__TAVI_VERSION__',$env:TAVI_VERSION); Set-Content -Path $env:UPDATE_SCRIPT -Value $s -Encoding ASCII"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('QGVjaG8gb2ZmCnNldGxvY2FsCnRpdGxlIFRBVkkgTGF1bmNoZXIKCjptZW51CmNscwplY2hvID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0KZWNobyAgICAgICAgICAgICAgICAgICAgICAgICBUQVZJIExhdW5jaGVyCmVjaG8gICAgICAgICAgICAgICAgICBUcmlwbGUgQXhpcyBWaXJ0dWFsIEluc3RydW1lbnQKZWNobyAgICAgICAgICAgICAgICAgIFJlbGVhc2U6IF9fVEFWSV9WRVJTSU9OX18KZWNobyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09CmVjaG8uCmVjaG8gICBbMV0gUnVuIFRBVkkKZWNobyAgIFsyXSBVcGRhdGUgVEFWSQplY2hvICAgWzNdIE9wZW4gVEFWSSBmb2xkZXIKZWNobyAgIFs0XSBPcGVuIFRBVkkgc2hlbGwKZWNobyAgIFs1XSBFeGl0CmVjaG8uCmNob2ljZSAvQyAxMjM0NSAvTSAiU2VsZWN0IG9wdGlvbiIKaWYgZXJyb3JsZXZlbCA1IGV4aXQgL2IgMAppZiBlcnJvcmxldmVsIDQgZ290byA6c2hlbGwKaWYgZXJyb3JsZXZlbCAzIGdvdG8gOmZvbGRlcgppZiBlcnJvcmxldmVsIDIgZ290byA6dXBkYXRlCmlmIGVycm9ybGV2ZWwgMSBnb3RvIDpydW4KZ290byA6bWVudQoKOnJ1bgpjYWxsICJfX1JVTl9TQ1JJUFRfXyIKZ290byA6bWVudQoKOnVwZGF0ZQpjYWxsICJfX1VQREFURV9TQ1JJUFRfXyIKZ290byA6bWVudQoKOmZvbGRlcgpleHBsb3JlciAiX19JTlNUQUxMX0RJUl9fIgpnb3RvIDptZW51Cgo6c2hlbGwKY2QgL2QgIl9fSU5TVEFMTF9ESVJfXyIKIl9fTUlDUk9NQU1CQV9FWEVfXyIgcnVuIC1uIF9fRU5WX05BTUVfXyBjbWQgL2sKZ290byA6bWVudQo=')); $s=$s.Replace('__INSTALL_DIR__',$env:INSTALL_DIR).Replace('__MICROMAMBA_EXE__',$env:MICROMAMBA_EXE).Replace('__ENV_NAME__',$env:ENV_NAME).Replace('__TAVI_VERSION__',$env:TAVI_VERSION).Replace('__RUN_SCRIPT__',$env:RUN_SCRIPT).Replace('__UPDATE_SCRIPT__',$env:UPDATE_SCRIPT); Set-Content -Path $env:LAUNCHER_SCRIPT -Value $s -Encoding ASCII"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($env:SHORTCUT); $s.TargetPath=$env:LAUNCHER_SCRIPT; $s.WorkingDirectory=$env:INSTALL_DIR; $s.Description='TAVI Launcher'; $s.Save()" 2>nul

echo [OK] Launcher scripts created.
echo.
echo ============================================================================
echo Installation complete.
echo Installed to: %INSTALL_DIR%
echo Environment : %ENV_NAME%
echo McStas      : %MCSTAS_VERSION%
echo ============================================================================
echo.
echo Run:
echo   %LAUNCHER_SCRIPT%
echo.
pause
endlocal
