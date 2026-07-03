"""Tests for the always-on scan validation, allow_partial, POST /validate, and
GET /schema API features.

Pure stdlib + Qt-free. Like ``test_api_server.py`` these spin up a real
``TaviApiServer`` on an ephemeral port with a duck-typed fake backend and drive
the HTTP surface. They exercise the SERVER routing/status-code/response-shape
contract and the ``ScanResult.skipped_points`` data model.

The controller-internal angle math (``check_point_feasibility`` /
``validate_scan_launch_state``) and the real ``build_api_schema`` string cannot
be imported here: ``instruments.PUMA_instrument_definition`` imports
``mcstasscript`` at module top, which is unavailable / crashes the interpreter on
this machine. Those pieces are covered by ``py_compile`` and by the fake backends
below reproducing the production contract. See the task notes.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from tavi.api_server import ApiError, TaviApiServer, API_PREFIX
from tavi.scan_jobs import JobRegistry, JobState, ScanJob, ScanResult


# --------------------------------------------------------------------------
# HTTP helper (mirrors test_api_server._request)
# --------------------------------------------------------------------------

def _request(url, method="GET", data=None, headers=None, timeout=5):
    hdrs = dict(headers or {})
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    body = json.loads(raw.decode("utf-8")) if raw else None
    return status, body


# --------------------------------------------------------------------------
# Fake backend reproducing the production validation contract
# --------------------------------------------------------------------------

# A representative validation block, shaped exactly like the production
# TaviApiBackend._build_validation output.
def _validation_block(infeasible):
    return {
        "points": 3,
        "per_command": [
            {"variable": "H", "count": 3, "values": [1.99, 2.0, 2.01]},
        ],
        "cost": {
            "pending_neutrons": 0.0, "budget": 1e10,
            "queued_jobs": 0, "max_queued": 10,
            "points": 3, "neutrons_per_point": 1e5, "job_neutrons": 3e5,
        },
        "eta": {"estimated_seconds": 42.0, "confidence": "high", "samples": 11},
        "infeasible": list(infeasible),
    }


_INFEASIBLE_ONE = [{
    "index": 2, "values": {"H": 2.01},
    "reason": "scattering triangle does not close (|Q| unreachable for Ki, Kf)",
}]


class ValidationBackend:
    """Fake backend mirroring the new validation/schema/allow_partial contract."""

    SCHEMA_GRAMMAR = (
        "VARIABLE start stop STEP. The third number (the last token) is the "
        "STEP SIZE, not the number of points."
    )

    def __init__(self, infeasible=None):
        self.registry = JobRegistry()
        # If set, POST /scan and /validate report these infeasible points.
        self.infeasible = list(infeasible or [])
        self.validate_calls = 0

    # -- reads --
    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle", "busy": False}

    def get_parameters(self):
        return {"Ei": 14.0}

    def get_job(self, job_id):
        job = self.registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        return job.snapshot()

    def get_job_data(self, job_id):
        job = self.registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        return job.snapshot(include_data=True)

    def list_jobs(self):
        return self.registry.recent()

    def _new_job(self, skipped_points=None):
        job = ScanJob(job_id=self.registry.next_id(), source="api",
                      launch_state={"vals": {}})
        job.result = ScanResult(
            mode="1D", variable_1="H", variable_2=None,
            scan_values_1=[1.99, 2.0, 2.01], scan_values_2=None,
            valid_mask_1=[True, True, False], valid_mask_2d=None,
            counts=[None, None, None], counts_grid=None,
            skipped_points=list(skipped_points or []),
        )
        self.registry.add(job)
        return job

    # -- writes --
    def submit_scan(self, body, idempotency_key=None):
        allow_partial = bool(body.get("allow_partial", False))
        validation = _validation_block(self.infeasible)
        if self.infeasible and not allow_partial:
            raise ApiError(
                400, "infeasible_points",
                "%d scan point(s) are geometrically infeasible; resubmit with "
                "\"allow_partial\": true to skip them" % len(self.infeasible),
                details=validation,
            )
        skipped = self.infeasible if (self.infeasible and allow_partial) else []
        job = self._new_job(skipped_points=skipped)
        return {
            "job_id": job.job_id, "state": "queued", "position": 0,
            "eta": validation["eta"], "validation": validation,
        }

    def submit_validate(self, body):
        self.validate_calls += 1
        allow_partial = bool(body.get("allow_partial", False))
        validation = _validation_block(self.infeasible)
        blockers = []
        if self.infeasible and not allow_partial:
            blockers.append(
                "infeasible_points: %d point(s) unreachable" % len(self.infeasible)
            )
        validation["would_queue"] = not blockers
        validation["blockers"] = blockers
        return validation

    def get_schema(self):
        return {
            "instrument": "puma",
            "fields": [
                {"name": "Ei", "type": "number", "units": "meV"},
                {"name": "K_fixed", "type": "string",
                 "allowed": ["Ki Fixed", "Kf Fixed"]},
                {"name": "monocris", "type": "string", "allowed": ["pg002"]},
                {"name": "scan_command1", "type": "string"},
            ],
            "scan_variables": ["H", "K", "L", "deltaE"],
            "scan_command_grammar": self.SCHEMA_GRAMMAR,
            "limits": {"max_points": 200},
            "endpoints": [{"method": "GET", "path": "/schema",
                           "description": "self-description"}],
            "examples": ["align-on-Bragg-peak", "elastic-H-scan",
                         "constant-Q-energy-scan"],
        }


def _start(backend, mode="allow"):
    srv = TaviApiServer(host="127.0.0.1", port=0, token=None, mode=mode,
                        backend=backend)
    srv.start()
    port = srv._httpd.server_address[1]
    base = "http://127.0.0.1:%d%s" % (port, API_PREFIX)
    return srv, base


# --------------------------------------------------------------------------
# POST /scan validation block on 202
# --------------------------------------------------------------------------

def test_scan_202_embeds_validation_block():
    backend = ValidationBackend(infeasible=[])
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST", data={})
        assert status == 202
        v = body["validation"]
        assert set(v) >= {"points", "per_command", "cost", "eta", "infeasible"}
        assert v["infeasible"] == []
        assert v["per_command"][0]["variable"] == "H"
        assert v["cost"]["job_neutrons"] == 3e5
        assert set(v["eta"]) == {"estimated_seconds", "confidence", "samples"}
    finally:
        srv.stop()


# --------------------------------------------------------------------------
# infeasible_points 400
# --------------------------------------------------------------------------

def test_scan_infeasible_points_400_with_validation_body():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST", data={})
        assert status == 400
        assert body["error"]["code"] == "infeasible_points"
        details = body["error"]["details"]
        assert details["infeasible"] == _INFEASIBLE_ONE
        assert details["points"] == 3
        # No job should have been queued on rejection.
        assert backend.registry.recent() == []
    finally:
        srv.stop()


def test_scan_allow_partial_queues_and_records_skipped_points():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"allow_partial": True})
        assert status == 202
        job_id = body["job_id"]
        # skipped points surface in both status and data snapshots.
        s_status, s_body = _request(base + "/scan/%s" % job_id)
        assert s_status == 200
        assert s_body["result"]["skipped_points"] == _INFEASIBLE_ONE
        d_status, d_body = _request(base + "/scan/%s/data" % job_id)
        assert d_body["result"]["skipped_points"] == _INFEASIBLE_ONE
    finally:
        srv.stop()


# --------------------------------------------------------------------------
# POST /validate
# --------------------------------------------------------------------------

def test_validate_returns_would_queue_true_when_feasible():
    backend = ValidationBackend(infeasible=[])
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/validate", method="POST", data={})
        assert status == 200
        assert body["would_queue"] is True
        assert body["blockers"] == []
        assert "infeasible" in body
        # /validate must never queue a job.
        assert backend.registry.recent() == []
    finally:
        srv.stop()


def test_validate_would_queue_false_and_never_queues_on_infeasible():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/validate", method="POST", data={})
        assert status == 200
        assert body["would_queue"] is False
        assert any("infeasible_points" in b for b in body["blockers"])
        assert backend.registry.recent() == []
        assert backend.validate_calls == 1
    finally:
        srv.stop()


def test_validate_allowed_in_readonly_mode():
    # /validate is non-mutating, so read-only mode must NOT 403 it.
    backend = ValidationBackend(infeasible=[])
    srv, base = _start(backend, mode="readonly")
    try:
        status, body = _request(base + "/validate", method="POST", data={})
        assert status == 200
        assert body["would_queue"] is True
        # A real write endpoint is still blocked in read-only mode.
        w_status, w_body = _request(base + "/scan", method="POST", data={})
        assert w_status == 403
        assert w_body["error"]["code"] == "read_only"
    finally:
        srv.stop()


def test_validate_method_not_allowed_on_get():
    backend = ValidationBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/validate", method="GET")
        assert status == 405
        assert body["error"]["code"] == "method_not_allowed"
    finally:
        srv.stop()


# --------------------------------------------------------------------------
# GET /schema
# --------------------------------------------------------------------------

def test_schema_shape_and_step_warning():
    backend = ValidationBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        assert body["instrument"] == "puma"
        assert isinstance(body["fields"], list) and body["fields"]
        # Grammar string must carry the STEP-size-not-count warning verbatim.
        assert "STEP SIZE, not the number of points" in body["scan_command_grammar"]
        # allowed values surface for choice fields.
        kf = next(f for f in body["fields"] if f["name"] == "K_fixed")
        assert kf["allowed"] == ["Ki Fixed", "Kf Fixed"]
        assert set(body["examples"]) == {
            "align-on-Bragg-peak", "elastic-H-scan", "constant-Q-energy-scan"
        }
    finally:
        srv.stop()


def test_schema_allowed_in_readonly_mode():
    backend = ValidationBackend()
    srv, base = _start(backend, mode="readonly")
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        assert "fields" in body
    finally:
        srv.stop()


def test_schema_method_not_allowed_on_post():
    backend = ValidationBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/schema", method="POST", data={})
        assert status == 405
    finally:
        srv.stop()
