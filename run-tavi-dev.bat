@echo off
setlocal
cd /d "%~dp0"

set "ENV_PREFIX=%USERPROFILE%\AppData\Roaming\mamba\envs\tavi-dev"
set "MCSTAS=%ENV_PREFIX%\share\mcstas\resources"
if not exist "%MCSTAS%" set "MCSTAS=%ENV_PREFIX%\Library\share\mcstas\resources"
if not exist "%MCSTAS%" (
    echo [ERROR] McStas resources not found under the tavi-dev environment:
    echo         %ENV_PREFIX%
    echo [INFO] Run setup-tavi-dev.bat to build the dev environment first.
    pause
    exit /b 1
)

set "INCLUDE=%INCLUDE%;C:\Program Files (x86)\Microsoft SDKs\MPI\Include"
set "LIB=%LIB%;C:\Program Files (x86)\Microsoft SDKs\MPI\Lib\x64"

"%USERPROFILE%\AppData\Local\micromamba\micromamba.exe" run -n tavi-dev python TAVI_PySide6.py %*
if errorlevel 1 pause
endlocal
