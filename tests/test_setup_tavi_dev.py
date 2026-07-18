"""Static safety contract for the Windows developer-environment installer."""
from pathlib import Path


SCRIPT = Path("setup-tavi-dev.bat").read_text(encoding="utf-8")
DIGEST = "56e3a55be1d8858f51ec9902bbc0825d7a18dc43c8558cd8d8b4e1f3d9af7bb4"


def test_micromamba_download_is_pinned_and_verified_before_move():
    assert f'set "MAMBA_SHA256={DIGEST}"' in SCRIPT
    checksum = SCRIPT.index('certutil -hashfile "%MICROMAMBA_EXE%.tmp" SHA256')
    move = SCRIPT.index('move /Y "%MICROMAMBA_EXE%.tmp" "%MICROMAMBA_EXE%"')
    assert checksum < move


def test_failed_download_or_checksum_removes_temporary_executable():
    download = SCRIPT.index("curl -L")
    checksum = SCRIPT.index("certutil -hashfile", download)
    move = SCRIPT.index("move /Y", checksum)
    download_block = SCRIPT[download:checksum]
    checksum_block = SCRIPT[checksum:move]
    assert 'del "%MICROMAMBA_EXE%.tmp"' in download_block
    assert 'del "%MICROMAMBA_EXE%.tmp"' in checksum_block
    assert "exit /b 1" in checksum_block


def test_mcstasscript_configuration_captures_exit_before_cleanup():
    run = SCRIPT.index('python "%TEMP%\\tavidev_config.py"')
    capture = SCRIPT.index('set "MCSTAS_CONFIG_EXIT=%ERRORLEVEL%"', run)
    cleanup = SCRIPT.index('del "%TEMP%\\tavidev_config.py"', capture)
    failure = SCRIPT.index('if not "%MCSTAS_CONFIG_EXIT%"=="0"', cleanup)
    assert run < capture < cleanup < failure
    assert "exit /b %MCSTAS_CONFIG_EXIT%" in SCRIPT[failure:]
