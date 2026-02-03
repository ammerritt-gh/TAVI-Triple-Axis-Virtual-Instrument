@mkdir %USERPROFILE%\AppData\Roaming\micromamba
@cd %USERPROFILE%\AppData\Roaming\micromamba
@echo Downloading latest micromamba
@set URL=https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64
@curl -L -o micromamba.exe %URL%
@echo Requesting init of micromamba on the shell
@.\micromamba.exe shell init --shell cmd.exe
@.\micromamba.exe shell hook -s cmd.exe
@.\micromamba config append channels conda-forge
@.\micromamba config set channel_priority strict
@echo Checking for existing mcstas environment
@.\micromamba env list > tmpfile
@setlocal

@set FOUND=N
@for /f %%i in ('@findstr mcstas tmpfile') do (
  @echo Found existing environment called %%i!
  @set FOUND=Y
)

@if /I %FOUND%==N goto INSTALL

:CHOICE
@choice /C YIN /M "Press Y to remove above env, I to ignore, or N to Cancel."
@if '%ERRORLEVEL%'=='1' goto REMOVE
@if '%ERRORLEVEL%'=='2' goto INSTALL
@if '%ERRORLEVEL%'=='3' goto END

:REMOVE
@echo Removing mcstas env
@.\micromamba env remove -n mcstas -y

:INSTALL
@echo Starting installation of McStas and dependencies
@.\micromamba.exe create -n mcstas mcstas -c conda-forge -c nodefaults -y

@echo Creating desktop shortcut to new environment

@echo start %USERPROFILE%\AppData\Roaming\mamba\condabin\micromamba activate mcstas > %USERPROFILE%\Desktop\mcstas-shell-conda.bat

:END
@echo End of script
@pause
@endlocal
