"""MPI launcher resolution from mccode_config.json (tavi/mcstas_config.py).

Direct McStas execution was silently dead because conda-packaged McStas
(3.4.65+) nests MPIRUN under a section ({"run": {"MPIRUN": ...}}) while the
reader only checked the top level. These pin both schemas.
"""
import json

import pytest

pytest.importorskip("mcstasscript")

from tavi.mcstas_config import (
    _normalize_mpi_launcher_argv,
    _read_mpirun_from_mccode_config,
)


def _config_dir(tmp_path, payload):
    # The reader also scans the parent directory, so nest two levels to keep
    # the search inside this test's tmp tree.
    root = tmp_path / "install" / "bin"
    root.mkdir(parents=True)
    (root / "mccode_config.json").write_text(json.dumps(payload), encoding="utf-8")
    return str(root)


def test_read_mpirun_flat_schema(tmp_path):
    root = _config_dir(tmp_path, {"MPIRUN": "mpirun -np $NUMPROCS"})
    assert _read_mpirun_from_mccode_config(root, None) == "mpirun -np $NUMPROCS"


def test_read_mpirun_nested_schema(tmp_path):
    root = _config_dir(tmp_path, {
        "configuration": {"MCCODE": "mcstas"},
        "run": {"MPIRUN": "mpiexec"},
    })
    assert _read_mpirun_from_mccode_config(root, None) == "mpiexec"


def test_read_mpirun_missing(tmp_path):
    root = _config_dir(tmp_path, {"configuration": {"MCCODE": "mcstas"}})
    assert _read_mpirun_from_mccode_config(root, None) is None


def test_normalize_strips_size_arguments():
    assert _normalize_mpi_launcher_argv("mpiexec -np 4") == ["mpiexec"]
    assert _normalize_mpi_launcher_argv("") == []
