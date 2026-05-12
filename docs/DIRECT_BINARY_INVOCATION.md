# Direct McStas Binary Invocation — Bypassing mcrun.py

*Date: 2026-05-12*
*Status: First implementation slice landed. `TAVIController.run_simulation()` still executes through `run_PUMA_point()`, but that seam now arms and uses a direct-binary path after the first successful `backengine()` materializes the executable. This has not yet been integration-validated in a live McStas environment.*

## Problem

Each `backengine()` call goes through this chain per scan point:

```
McStasScript subprocess.run(shell=True)
  → cmd.exe
    → mcrun.bat
      → python -u mcrun.py  (imports numpy, psutil, yaml, mccode_config...)
        → McStas.prepare()  (timestamp checks on .c and .exe)
        → McStas.runMPI()
          → subprocess.run(shell=True)
            → cmd.exe
              → <resolved MPI launcher> -np 30 PUMA_McScript.exe ...
```

Two Python interpreters, two cmd.exe shells, full module import chain — all repeated every point. On Windows this is 300-700ms of overhead per point, which is ~10-15% of wall time for short simulations.

## Solution

Keep `run_PUMA_point()` in `instruments/PUMA_instrument_definition.py` as the execution seam called from `TAVIController.run_simulation()` in `TAVI_PySide6.py`. The landed slice keeps the first point on `backengine()` so the executable is materialized and diagnostic `McStasData` is retained, then uses direct process invocation with `subprocess.run` and a list (no shell) for later eligible points.

## Key Facts

- The compiled binary lives in the instrument `input_path` directory passed to `ms.McStas_instr("PUMA_McScript", input_path="./components")`
- `run_PUMA_point()` now takes a scan-local `PUMARunExecutionState` that tracks first-point materialization, whether direct execution is armed, the resolved binary path/cwd, and the MPI launcher argv
- After the first successful `backengine()` call materializes the executable, the code resolves and retains its absolute path from `instrument.input_path` + instrument name + `.exe`
- The direct path is not keyed off run number alone; it only activates once the first `backengine()` succeeded, direct execution is armed, the expected binary exists on disk, and MPI launcher resolution succeeded
- `tavi/mcstas_config.py` now centralizes MPI launcher resolution for direct execution. It resolves from McStasScript configuration with fallback to nearby `mccode_config.json`, and prefers a direct `mpiexec` binary over wrapper `.bat` / `.cmd` launchers when possible
- The binary accepts standard McStas CLI args: `--ncount=N --dir=PATH param=value param=value ...`
- `cwd` must be set to the directory containing the binary (so it finds component data files)

## Binary CLI Format

Confirmed from `mccode.sim` output and `mccode.py` source:

```
<mpi-launcher> -np 30 PUMA_McScript.exe --ncount=1000000 --dir=C:\path\to\scan_0001 A1_param=45.0 A2_param=-30.0 saz_param=0.0 ...
```

The params snapshot dict already carries the exact McStas runtime parameter names needed for CLI `name=value` arguments. The `--dir` flag specifies the output directory for detector files. McStas creates the directory if it doesn't exist.

## Implementation

Current implementation in `run_PUMA_point()`:

- Invalid snapshots still return through the existing skipped-point path.
- The first successful point uses `instrument.settings(...)`, `instrument.set_parameters(...)`, and `instrument.backengine()`, then records the binary path, binary cwd, MPI launcher argv, and whether direct execution became armed.
- Later eligible points build `args` as `[*launcher_argv, '-np', str(mpi_count), binary_path, f'--ncount={ncount}', f'--dir={output_folder}', ...params]` and call `subprocess.run(..., stdout=PIPE, stderr=STDOUT, text=True, cwd=binary_cwd)`.
- A non-zero direct return code or missing `detector.dat` is mapped into the existing per-point failure path through `execution_info` and `error_flags`.

Key details:
- Pass `args` as a **list**, not a string — this avoids spawning `cmd.exe` (`shell=False` is the default)
- Resolve the MPI launcher from McStas configuration state instead of embedding `mpiexec.exe`
- `cwd` must be the directory containing the resolved binary
- The first point still uses `backengine()` to guarantee compilation/materialization of the executable and preserve the retained diagnostic `McStasData`
- The direct path only becomes eligible after that first successful `backengine()` point, a direct-run-ready boolean is set, and the resolved binary exists
- Controller logging now reports both arming and successful direct execution mode transitions, and per-point stage timing records include `execution_mode`, `direct_returncode`, and `direct_binary_path`

## What Changes in the Pipeline

1. `TAVIController.run_simulation()` continues to call `run_PUMA_point()` once per snapshot; any direct path belongs behind that seam.
2. The first executed point still needs `instrument.set_parameters()` + `instrument.backengine()` to materialize the executable and preserve the retained diagnostic `McStasData`.
3. Later points can reuse `params_snapshot['params']` directly as CLI args because those keys (for example `A1_param`, `rhm_param`) are already the correct McStas parameter names.

## Post-run Data Loading

`backengine()` normally returns McStasData via `ManagedMcrun.load_results()`. TAVI's postprocessing already reads detector files directly via `read_1Ddetector_file(scan_folder)`, but diagnostic plotting still depends on the `data` object contract. Diagnostic mode should use Option B: first-point only. The first successful `backengine()` point retains the diagnostic McStasData and instrument object; later direct-invocation points do not replace that retained diagnostic data.

## Remaining Validation

- The code now creates the direct-run output folder before invocation and treats non-zero return codes or missing `detector.dat` as per-point failures surfaced through the existing message-center logging path.
- What remains unverified is end-to-end runtime behavior in a live McStas environment: MPI launcher resolution on a real install, direct executable startup after first-point materialization, and any platform-specific launcher quirks.
- If the instrument needs recompilation mid-scan (not expected while build-time config is frozen), the current seam still has the `backengine()` path available.

## In-Progress Note

Direct binary invocation is now partially implemented in the live run path. The controlling seam remains `run_PUMA_point()` in `instruments/PUMA_instrument_definition.py`, as called from `TAVIController.run_simulation()` in `TAVI_PySide6.py`; the current slice keeps first-point `backengine()`, arms direct invocation only after a successful first point plus binary/MPI resolution, retains first-point diagnostic McStasData for diagnostic mode, and maps non-zero direct exits or missing `detector.dat` into the existing per-point failure path while surfacing stdout/stderr through the message center. Live McStas integration validation is still pending.
