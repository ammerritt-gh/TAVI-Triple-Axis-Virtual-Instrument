"""Tests for deterministic-engine dispatch (milestone 7).

Pure stdlib + Qt-free. Three surfaces are covered without importing the
Qt-bound controller:

  * ``tavi.api_server.parse_scan_engine`` -- the real, importable engine/seed/
    noiseless body validator the production ``submit_scan`` calls (accept /
    echo / 400 with the allowed list). This is the actual code path, not a
    reproduction.
  * ``ScanJob._launch_summary`` -- engine/seed/noiseless provenance passthrough,
    exercised directly on the Qt-free job model.
  * ``GET /schema`` advertising ``engines`` -- driven through a real
    ``TaviApiServer`` with a fake backend, mirroring ``test_api_validation_schema``.

The worker branch itself (``TAVIController._run_scan_deterministic``) is
Qt-bound (it imports ``TAVI_PySide6``, which imports PySide6 + mcstasscript);
it is verified statically via ``py_compile`` only -- see the task notes.
"""
import json
import urllib.error
import urllib.request

import pytest

from tavi.api_server import (
    ApiError, TaviApiServer, API_PREFIX,
    ALLOWED_ENGINES, DEFAULT_ENGINE, parse_scan_engine,
)
from tavi.scan_jobs import JobRegistry, ScanJob, ScanResult


# ==========================================================================
# parse_scan_engine -- the real body validator
# ==========================================================================

def test_engine_defaults_to_mcstas_when_absent():
    engine, seed, noiseless = parse_scan_engine({})
    assert engine == "mcstas" == DEFAULT_ENGINE
    assert seed is None
    assert noiseless is False


def test_engine_none_falls_back_to_default():
    engine, _, _ = parse_scan_engine({"engine": None})
    assert engine == "mcstas"


def test_engine_deterministic_accepted_and_echoed():
    engine, seed, noiseless = parse_scan_engine(
        {"engine": "deterministic", "seed": 7, "noiseless": True}
    )
    assert engine == "deterministic"
    assert seed == 7
    assert noiseless is True


def test_unknown_engine_is_400_with_allowed_list():
    with pytest.raises(ApiError) as ei:
        parse_scan_engine({"engine": "quantum"})
    err = ei.value
    assert err.status == 400
    assert err.code == "bad_request"
    assert err.details == {"allowed": list(ALLOWED_ENGINES)}
    assert "quantum" in err.message


def test_non_string_engine_is_400():
    with pytest.raises(ApiError) as ei:
        parse_scan_engine({"engine": 3})
    assert ei.value.status == 400


def test_seed_must_be_integer():
    with pytest.raises(ApiError) as ei:
        parse_scan_engine({"seed": "17"})
    assert ei.value.status == 400
    assert "seed" in ei.value.message


def test_seed_bool_rejected():
    # bool is an int subclass; a True/False seed is a client mistake, not 1/0.
    with pytest.raises(ApiError):
        parse_scan_engine({"seed": True})


def test_seed_none_is_allowed():
    _, seed, _ = parse_scan_engine({"engine": "deterministic", "seed": None})
    assert seed is None


def test_seed_negative_rejected():
    # numpy default_rng((seed, i)) requires non-negative entries; reject at
    # submit (400) instead of failing the job at the first scan point.
    with pytest.raises(ApiError):
        parse_scan_engine({"engine": "deterministic", "seed": -1})


def test_noiseless_must_be_bool():
    with pytest.raises(ApiError) as ei:
        parse_scan_engine({"noiseless": "yes"})
    assert ei.value.status == 400
    assert "noiseless" in ei.value.message


def test_non_dict_body_rejected():
    with pytest.raises(ApiError) as ei:
        parse_scan_engine([1, 2, 3])
    assert ei.value.status == 400


def test_allowed_engines_contract():
    assert ALLOWED_ENGINES == ("mcstas", "deterministic")


# ==========================================================================
# _launch_summary provenance passthrough (Qt-free job model)
# ==========================================================================

def _job(launch_state):
    return ScanJob(job_id="j-0001", source="api", launch_state=launch_state)


def test_launch_summary_defaults_engine_to_mcstas():
    summary = _job({"vals": {}})._launch_summary()
    assert summary["engine"] == "mcstas"
    # seed / noiseless omitted for an ordinary McStas job.
    assert "seed" not in summary
    assert "noiseless" not in summary


def test_launch_summary_passes_through_deterministic_engine():
    summary = _job({
        "vals": {"scan_command1": "deltaE 3 7 0.25", "number_neutrons": 1e8},
        "engine": "deterministic",
        "seed": 42,
        "noiseless": True,
    })._launch_summary()
    assert summary["engine"] == "deterministic"
    assert summary["seed"] == 42
    assert summary["noiseless"] is True


def test_launch_summary_seed_present_without_noiseless():
    summary = _job({"vals": {}, "engine": "deterministic",
                    "seed": 5})._launch_summary()
    assert summary["seed"] == 5
    assert "noiseless" not in summary  # noiseless falsey -> omitted


def test_launch_summary_survives_json_snapshot():
    job = _job({
        "vals": {"scan_command1": "H 1 2 0.5"},
        "engine": "deterministic", "seed": 99, "noiseless": False,
    })
    snap = job.snapshot()
    json.dumps(snap, allow_nan=False)
    assert snap["launch"]["engine"] == "deterministic"
    assert snap["launch"]["seed"] == 99
    # noiseless False -> not surfaced.
    assert "noiseless" not in snap["launch"]


def test_launch_summary_reaches_job_data_snapshot():
    # Provenance must ride along on the /data (include_data=True) view too.
    job = _job({"vals": {}, "engine": "deterministic", "seed": 3})
    job.result = ScanResult(
        mode="1D", variable_1="deltaE", variable_2=None,
        scan_values_1=[3.0], scan_values_2=None,
        valid_mask_1=[True], valid_mask_2d=None,
        counts=[None], counts_grid=None,
    )
    snap = job.snapshot(include_data=True)
    assert snap["launch"]["engine"] == "deterministic"


# ==========================================================================
# GET /schema advertises engines (real server, fake backend)
# ==========================================================================

def _request(url, method="GET", data=None, timeout=5):
    hdrs = {}
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw, status = resp.read(), resp.getcode()
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    return status, (json.loads(raw.decode("utf-8")) if raw else None)


class _SchemaBackend:
    """Minimal fake backend whose get_schema mirrors the production shape."""

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}

    def submit_scan(self, body, idempotency_key=None):
        # Reuse the real validator so a bad engine 400s exactly as production.
        engine, seed, noiseless = parse_scan_engine(body)
        return {"job_id": "j-0001", "state": "queued", "position": 0,
                "engine": engine, "seed": seed, "noiseless": noiseless}

    def get_schema(self):
        return {
            "instrument": "puma",
            "fields": [{"name": "Ei", "type": "number"}],
            "engines": list(ALLOWED_ENGINES),
            "scan_body_fields": [
                {"name": "engine", "type": "string",
                 "allowed": list(ALLOWED_ENGINES), "default": "mcstas"},
                {"name": "seed", "type": "integer", "default": None},
                {"name": "noiseless", "type": "boolean", "default": False},
            ],
            "scan_variables": ["H"],
            "endpoints": [],
        }


def _start(backend, mode="allow"):
    srv = TaviApiServer(host="127.0.0.1", port=0, token=None, mode=mode,
                        backend=backend)
    srv.start()
    port = srv._httpd.server_address[1]
    return srv, "http://127.0.0.1:%d%s" % (port, API_PREFIX)


def test_schema_advertises_engines_and_body_fields():
    srv, base = _start(_SchemaBackend())
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        assert body["engines"] == ["mcstas", "deterministic"]
        names = {f["name"] for f in body["scan_body_fields"]}
        assert names == {"engine", "seed", "noiseless"}
        eng = next(f for f in body["scan_body_fields"] if f["name"] == "engine")
        assert eng["allowed"] == ["mcstas", "deterministic"]
    finally:
        srv.stop()


def test_scan_accepts_and_echoes_engine():
    srv, base = _start(_SchemaBackend())
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"engine": "deterministic", "seed": 11})
        assert status == 202
        assert body["engine"] == "deterministic"
        assert body["seed"] == 11
    finally:
        srv.stop()


def test_scan_rejects_unknown_engine_400():
    srv, base = _start(_SchemaBackend())
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"engine": "bogus"})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
        assert body["error"]["details"]["allowed"] == ["mcstas", "deterministic"]
    finally:
        srv.stop()
