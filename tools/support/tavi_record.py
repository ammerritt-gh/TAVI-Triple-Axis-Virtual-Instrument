"""Record the installed TAVI GUI, including errors it catches internally.

Stdlib-only supervisor: even an import failure or native GUI crash leaves a report.
Instrumentation is process-local; it does not patch the installed application.
"""
import dataclasses
import datetime
import faulthandler
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import threading
import time
import traceback


ENV_KEYS = (
    "PATH", "PATHEXT", "COMSPEC", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
    "MAMBA_ROOT_PREFIX", "MCSTAS", "MCSTAS_COMPONENT_PATH", "USERPROFILE",
    "TEMP", "TMP", "INCLUDE", "LIB", "TAVI_CONFIG_DIR", "TAVI_ROOT",
    "NoDefaultCurrentDirectoryInExePath", "QT_QPA_PLATFORM",
)
CONFIG_FILES = ("parameters.json", "mcstas_config.json", "instrument_selection.json",
                "view_layout.json", "runtimes.json")


def value(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {field.name: getattr(obj, field.name) for field in dataclasses.fields(obj)}
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return repr(obj)


class Recorder:
    def __init__(self, root, report):
        self.root = Path(root).resolve()
        self.report = Path(report).resolve()
        self.report.mkdir(parents=True, exist_ok=True)
        self.stream = (self.report / "events.jsonl").open(
            "a", encoding="utf-8", newline="\n", buffering=1)
        self.lock = threading.RLock()
        self.original_run = subprocess.run
        self.output_folders = set()
        self.calls = 0
        self.exception_counts = {}

    def event(self, kind, **fields):
        with self.lock:
            self.stream.write(json.dumps({"time": time.time(), "thread": threading.current_thread().name,
                                          "kind": kind, **fields}, default=value) + "\n")
            self.stream.flush()

    def copy_file(self, source, label):
        source = Path(source)
        try:
            if not source.is_file():
                self.event("absent", path=str(source))
                return
            # DFT grids / detector arrays are not needed to diagnose a launch.
            if source.stat().st_size > 16 * 1024 * 1024:
                self.event("oversize_not_copied", path=str(source), size=source.stat().st_size)
                return
            dest = self.report / "files" / label
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            self.event("copied", source=str(source), destination=str(dest),
                       size=source.stat().st_size, mtime_ns=source.stat().st_mtime_ns)
        except Exception:
            self.event("collection_error", path=str(source), traceback=traceback.format_exc())

    def inventory(self):
        self.event("environment", executable=sys.executable, prefix=sys.prefix, cwd=os.getcwd(),
                   python=sys.version, root=str(self.root), env={k: os.environ.get(k) for k in ENV_KEYS})
        for package in ("mcstasscript", "numpy", "PySide6", "matplotlib", "libpyvinyl", "ncrystal"):
            try:
                self.event("package", name=package, version=importlib.metadata.version(package))
            except Exception:
                self.event("package_error", name=package, traceback=traceback.format_exc())
        for command in ("python", "mcrun", "mcstas", "mpiexec", "x86_64-w64-mingw32-gcc", "cl"):
            self.event("which", command=command, path=shutil.which(command))
        for name in ("INSTALL_INFO.txt", "run-tavi.bat", "TAVI-Launcher.bat"):
            self.copy_file(self.root / name, "install/" + name)
        profile = Path(os.environ.get("USERPROFILE", str(self.root)))
        drive = Path(os.environ.get("SystemDrive", "C:") + "/")
        for i, candidate in enumerate((profile / "TAVI", drive / "TAVI", drive / "TAVI-Data/TAVI")):
            for name in ("INSTALL_INFO.txt", "run-tavi.bat", "TAVI-Launcher.bat"):
                self.copy_file(candidate / name, f"other-install-{i}/{name}")
        for i, desktop in enumerate((profile / "Desktop", profile / "OneDrive/Desktop",
                                     Path(os.environ.get("PUBLIC", str(profile))) / "Desktop")):
            for shortcut in desktop.glob("*TAVI*.lnk"):
                self.copy_file(shortcut, f"shortcuts-{i}/" + shortcut.name)
        configs = {self.root / "config", Path(os.environ.get("TAVI_CONFIG_DIR", str(self.root / "config")))}
        for i, directory in enumerate(sorted(configs)):
            for name in CONFIG_FILES:
                self.copy_file(directory / name, f"config-{i}/{name}")
        for name in ("TAVI_PySide6.py", "instruments/tas_runtime.py", "tavi/mcstas_config.py"):
            path = self.root / name
            try:
                self.event("source", path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            except Exception:
                self.event("source_error", path=str(path), traceback=traceback.format_exc())
        prefix = Path(sys.prefix)
        for name in ("Lib/site-packages/mcstasscript/configuration.yaml",
                     "share/mcstas/tools/Python/mccodelib/mccode_config.json", "bin/mcrun.bat"):
            self.copy_file(prefix / name, "environment/" + name)
        user_configs = Path(os.environ.get("USERPROFILE", str(self.root))) / "AppData" / "mcstas"
        for path in user_configs.glob("*/mccode_config.json"):
            self.copy_file(path, "user-mcstas/" + path.parent.name + "/" + path.name)
        for path in sorted((self.root / "components").glob("*")):
            if path.is_file():
                self.event("component_before", path=str(path), size=path.stat().st_size,
                           mtime_ns=path.stat().st_mtime_ns,
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest()
                           if path.suffix in (".instr", ".c", ".exe") else None)

    def run(self, *args, **kwargs):
        with self.lock:
            self.calls += 1
            number = self.calls
        self.event("command", number=number, args=args, kwargs={k: v for k, v in kwargs.items() if k != "env"},
                   cwd=kwargs.get("cwd", os.getcwd()),
                   env={k: (kwargs.get("env") or os.environ).get(k) for k in ENV_KEYS})
        try:
            result = self.original_run(*args, **kwargs)
        except BaseException as exc:
            self.event("command_exception", number=number, traceback=traceback.format_exc(),
                       stdout=getattr(exc, "stdout", None), stderr=getattr(exc, "stderr", None))
            raise
        self.event("command_result", number=number, returncode=result.returncode,
                   stdout=result.stdout, stderr=result.stderr)
        return result

    def trace(self, frame, event, arg):
        filename = os.path.normcase(frame.f_code.co_filename)
        selected = (filename.startswith(os.path.normcase(str(self.root)) + os.sep)
                    or "mcstasscript" + os.sep in filename)
        if not selected or filename == os.path.normcase(__file__):
            return None
        frame.f_trace_lines = False
        name = frame.f_code.co_name
        if event == "exception" and arg[0] not in (StopIteration, GeneratorExit):
            key = (filename, frame.f_lineno, arg[0].__name__, str(arg[1]))
            count = self.exception_counts.get(key, 0) + 1
            self.exception_counts[key] = count
            if count <= 3:
                self.event("caught_exception", file=filename, line=frame.f_lineno, function=name,
                           traceback="".join(traceback.format_exception(*arg)))
            elif count == 4:
                self.event("repeated_exception", file=filename, line=frame.f_lineno,
                           message=str(arg[1]), note="Further identical events suppressed")
        if name in ("run_simulation", "run_tas_point", "compute_scan_snapshot", "backengine",
                    "_collect_simulation_launch_state", "print_to_message_center"):
            if event == "call":
                fields = {k: v for k, v in frame.f_locals.items()
                          if k in ("launch_state", "params_snapshot", "output_folder", "number_neutrons",
                                   "execution_state", "mpi_count", "message", "scan_item", "vals", "data_folder")}
                # The frozen state includes hidden alignment and the sample mount,
                # which cannot be reconstructed from the visible GUI values alone.
                if isinstance(fields.get("launch_state"), dict):
                    launch = dict(fields["launch_state"])
                    config = launch.get("scan_config")
                    launch["scan_config"] = dict(vars(config)) if hasattr(config, "__dict__") else config
                    fields["launch_state"] = launch
                if name == "backengine":
                    instrument = frame.f_locals.get("self")
                    fields["instrument"] = {k: getattr(instrument, k, None)
                                            for k in ("name", "input_path", "output_path", "_run_settings")}
                self.event("call", file=filename, function=name, fields=fields)
                if frame.f_locals.get("output_folder"):
                    self.output_folders.add(str(frame.f_locals["output_folder"]))
            elif event == "return":
                details = arg
                if name == "run_tas_point" and isinstance(arg, tuple):
                    details = {"error_flags": arg[1], "execution_info": arg[2]}
                elif name in ("run_simulation", "backengine"):
                    details = repr(type(arg))
                self.event("return", function=name, result=details)
        return self.trace

    def artifacts(self):
        for path in (self.root / "components").glob("*_McScript.*"):
            if path.suffix in (".instr", ".c"):
                self.copy_file(path, "generated/" + path.name)
        for i, folder in enumerate(sorted(self.output_folders)):
            path = Path(folder)
            self.event("output", path=str(path), exists=path.exists(),
                       files=[p.name for p in path.iterdir()] if path.is_dir() else [])
            for name in ("mccode.sim", "scan_parameters.txt"):
                self.copy_file(path / name, f"point-{i}/{name}")
            for name in ("parameters.txt", "scan_parameters.txt"):
                self.copy_file(path.parent / name, f"scan-{i}/{name}")

    def install(self):
        subprocess.run = self.run
        threading.settrace(self.trace)
        sys.settrace(self.trace)

    def audit(self, event, args):
        if event == "subprocess.Popen":
            self.event("process_start", executable=args[0], args=args[1], cwd=args[2],
                       env={k: (args[3] or os.environ).get(k) for k in ENV_KEYS})

    def restore(self):
        sys.settrace(None)
        threading.settrace(None)
        subprocess.run = self.original_run


def child(root, report):
    os.chdir(root)
    sys.path.insert(0, str(root))
    recorder = Recorder(root, report)
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        recorder.inventory()
    except Exception:
        recorder.event("inventory_error", traceback=traceback.format_exc())
    sys.addaudithook(recorder.audit)
    recorder.install()
    try:
        sys.argv = [str(root / "TAVI_PySide6.py")]
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        recorder.restore()
        recorder.artifacts()
        faulthandler.cancel_dump_traceback_later()


def supervise(root, output):
    report = output / ("TAVI-report-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    report.mkdir(parents=True)
    start = time.monotonic()
    result = "not started"
    timeout = int(os.environ.get("TAVI_RECORD_TIMEOUT_SECONDS", "1800"))
    print("TAVI will open. Reproduce the Monte Carlo failure once, then close TAVI.", flush=True)
    print("Recording to:", report, flush=True)
    print("If TAVI hangs, return here and press Ctrl+C. Logs will still be saved.", flush=True)
    print(f"Automatic recording deadline: {timeout // 60} minutes.", flush=True)
    try:
        with (report / "console.txt").open("w", encoding="utf-8", newline="\n") as stream:
            process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()),
                                        "--child", str(root), str(report)], stdout=stream, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=timeout)
                result = f"{code} (0x{code & 0xffffffff:08X})"
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                result = type(exc).__name__
                print(result + ": stopping this diagnostic's process tree.", flush=True)
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=stream, stderr=subprocess.STDOUT, timeout=15)
                else:
                    process.kill()
                process.wait(timeout=15)
    except BaseException:
        with (report / "supervisor-error.txt").open("w", encoding="utf-8", newline="\n") as stream:
            traceback.print_exc(file=stream)
        result = "supervisor error; see log"
    finally:
        # The child may have died in native code, so collect build evidence here too.
        recorder = Recorder(root, report)
        try:
            recorder.artifacts()
        except Exception:
            recorder.event("collection_error", traceback=traceback.format_exc())
        recorder.stream.close()
        with (report / "SUMMARY.txt").open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(f"TAVI recording finished. Process result: {result}\nElapsed: {time.monotonic()-start:.1f}s\n"
                         "A zero GUI exit code does NOT mean the simulation succeeded.\n"
                         "Read events.jsonl command_result/caught_exception and console.txt.\n")
        archive = shutil.make_archive(str(report), "zip", report)
        print("SEND BACK:", archive, flush=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        child(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    else:
        raise SystemExit(supervise(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
