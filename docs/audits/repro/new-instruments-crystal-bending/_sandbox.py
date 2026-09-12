"""Run an audit check on copied source with all writes confined to TEMP."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def run(check):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.dont_write_bytecode = True
    if "--worker" in sys.argv:
        sys.path.insert(0, str(Path.cwd()))
        import conftest
        conftest.pytest_configure(None)
        import mcstasscript as ms
        config = Path.cwd() / "mcstasscript-config.yaml"
        shutil.copy2(Path(ms.__file__).parent / "configuration.yaml", config)
        original_init = ms.Configurator.__init__

        def isolated_init(self, *args):
            original_init(self, str(config.with_suffix("")))

        ms.Configurator.__init__ = isolated_init
        check()
        return

    repo = Path(__file__).resolve().parents[4]
    root = Path(tempfile.mkdtemp(prefix="tavi-audit-repro-"))
    for directory in ("instruments", "tavi", "gui", "components"):
        shutil.copytree(repo / directory, root / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.dat"))
    for source in repo.glob("*.py"):
        shutil.copy2(source, root / source.name)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
               QT_QPA_PLATFORM="offscreen", MPLCONFIGDIR=str(root / "mpl-cache"))
    prefix = Path.home() / "AppData/Roaming/mamba/envs/tavi-dev"
    interpreter = prefix / "python.exe"
    if not interpreter.exists():
        interpreter = Path(sys.executable)
    else:
        env["PATH"] = os.pathsep.join([
            str(prefix / "Library/bin"), str(prefix / "Scripts"), str(prefix), env["PATH"]])
        env["MCSTAS"] = str(prefix / "share/mcstas/resources")
    started = time.monotonic()
    process = subprocess.Popen(
        [str(interpreter), "-B", str(Path(sys.argv[0]).resolve()), "--worker"],
        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        output, _ = process.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        print("TIMEOUT: stopping probe after 90 seconds")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           check=False, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()
        output, _ = process.communicate()
    print(output.decode("utf-8", errors="replace"))
    print(f"Exit {process.returncode}; {time.monotonic() - started:.2f}s; temporary files: {root}")
    raise SystemExit(process.returncode)
