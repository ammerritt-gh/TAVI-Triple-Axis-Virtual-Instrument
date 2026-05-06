@echo off
cd /d C:\Users\AMM\Documents\Github\TAVI
set MCSTAS=C:\Users\AMM\AppData\Roaming\mamba\envs\tavi-dev\share\mcstas\resources
set INCLUDE=%INCLUDE%;C:\Program Files (x86)\Microsoft SDKs\MPI\Include
set LIB=%LIB%;C:\Program Files (x86)\Microsoft SDKs\MPI\Lib\x64
%USERPROFILE%\AppData\Local\micromamba\micromamba.exe run -n tavi-dev python TAVI_PySide6.py
if errorlevel 1 pause
