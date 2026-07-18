"""Tests for the always-on scan validation, allow_partial, POST /validate, and
GET /schema API features.

Pure stdlib + Qt-free. Like ``test_api_server.py`` these spin up a real
``TaviApiServer`` on an ephemeral port with a duck-typed fake backend and drive
the HTTP surface. They exercise the SERVER routing/status-code/response-shape
contract and the ``ScanResult.skipped_points`` data model.

The controller-internal angle math (``check_point_feasibility`` /
``validate_scan_launch_state``) and the real ``build_api_schema`` string cannot
be imported here: ``instruments.puma.model`` imports
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
from tavi.sample_library import default_sample_library
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
    infeasible = list(infeasible)
    bad_indices = {point["index"] for point in infeasible}
    mask = [index not in bad_indices for index in range(3)]
    segments = []
    segment_start = None
    for index, feasible in enumerate(mask + [False]):
        if feasible and segment_start is None:
            segment_start = index
        elif not feasible and segment_start is not None:
            segments.append({"start_index": segment_start, "end_index": index - 1})
            segment_start = None
    return {
        "requested_points": 3,
        "feasible_points": sum(mask),
        "partial": 0 < sum(mask) < 3,
        "planned_feasible_mask": mask,
        "feasible_segments": segments,
        "point_manifest": [],
        "per_command": [
            {"variable": "H", "count": 3, "values": [1.99, 2.0, 2.01]},
        ],
        "cost": {
            "pending_neutrons": 0.0, "budget": 1e10,
            "queued_jobs": 0, "max_queued": 10,
            "requested_points": 3, "feasible_points": sum(mask),
            "neutrons_per_point": 1e5,
            "job_neutrons": sum(mask) * 1e5,
        },
        "eta": {"estimated_seconds": 42.0, "confidence": "high", "samples": 11},
        "infeasible": infeasible,
    }


_INFEASIBLE_ONE = [{
    "index": 2, "values": {"H": 2.01},
    "kind": "physical_infeasible",
    "reason": "scattering triangle does not close (|Q| unreachable for Ki, Kf)",
}]


class ValidationBackend:
    """Fake backend mirroring the point-level partial-feasibility contract."""

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
        allow_partial = body.get("allow_partial", False)
        if not isinstance(allow_partial, bool):
            raise ApiError(
                400, "bad_request", "'allow_partial' must be a boolean"
            )
        validation = _validation_block(self.infeasible)
        if validation["feasible_points"] == 0:
            raise ApiError(
                400, "all_points_infeasible",
                "No requested scan point is feasible",
                details=validation,
            )
        if validation["partial"] and not allow_partial:
            raise ApiError(
                400, "infeasible_points",
                "Some requested scan points are infeasible; set "
                "allow_partial=true to queue only feasible points",
                details=validation,
            )
        job = self._new_job(skipped_points=self.infeasible)
        return {
            "job_id": job.job_id, "state": "queued", "position": 0,
            "eta": validation["eta"], "validation": validation,
        }

    def submit_validate(self, body):
        self.validate_calls += 1
        validation = _validation_block(self.infeasible)
        blockers = []
        if validation["feasible_points"] == 0:
            blockers.append("all_points_infeasible: no requested point is reachable")
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
            "examples": ["align-on-bragg-peak", "elastic-h-scan",
                         "constant-q-energy-scan", "quick-look-vs-production"],
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
        assert set(v) >= {"requested_points", "feasible_points", "partial",
                          "per_command", "cost", "eta", "infeasible"}
        assert v["infeasible"] == []
        assert v["per_command"][0]["variable"] == "H"
        assert v["cost"]["job_neutrons"] == 3e5
        assert v["feasible_segments"] == [{"start_index": 0, "end_index": 2}]
        assert set(v["eta"]) == {"estimated_seconds", "confidence", "samples"}
    finally:
        srv.stop()


# --------------------------------------------------------------------------
# partial feasibility
# --------------------------------------------------------------------------

def test_scan_partial_feasibility_rejected_without_opt_in():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST", data={})
        assert status == 400
        assert body["error"]["code"] == "infeasible_points"
        assert body["error"]["details"]["partial"] is True
        assert backend.registry.recent() == []
    finally:
        srv.stop()


def test_scan_partial_feasibility_queues_with_explicit_opt_in():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(
            base + "/scan", method="POST", data={"allow_partial": True}
        )
        assert status == 202
        assert body["validation"]["partial"] is True
        assert body["validation"]["feasible_segments"] == [
            {"start_index": 0, "end_index": 1}
        ]
        job_id = body["job_id"]
        s_status, s_body = _request(base + "/scan/%s" % job_id)
        assert s_status == 200
        assert s_body["result"]["skipped_points"] == _INFEASIBLE_ONE
    finally:
        srv.stop()


def test_scan_rejects_non_boolean_allow_partial():
    backend = ValidationBackend(infeasible=[])
    srv, base = _start(backend)
    try:
        status, body = _request(
            base + "/scan", method="POST", data={"allow_partial": "true"}
        )
        assert status == 400
        assert body["error"]["code"] == "bad_request"
        assert backend.registry.recent() == []
    finally:
        srv.stop()


def test_scan_all_points_infeasible_rejected():
    all_bad = [dict(_INFEASIBLE_ONE[0], index=i) for i in range(3)]
    backend = ValidationBackend(infeasible=all_bad)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST", data={})
        assert status == 400
        assert body["error"]["code"] == "all_points_infeasible"
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


def test_validate_would_queue_true_on_partial_feasibility():
    backend = ValidationBackend(infeasible=_INFEASIBLE_ONE)
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/validate", method="POST", data={})
        assert status == 200
        assert body["would_queue"] is True
        assert body["blockers"] == []
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
            "align-on-bragg-peak", "elastic-h-scan", "constant-q-energy-scan",
            "quick-look-vs-production"
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


# --------------------------------------------------------------------------
# Sample selection via the API (B2)
#
# The real selection logic lives in the Qt-bound controller (_api_field_map /
# apply_parameters / build_api_schema), which cannot be imported here (its
# mcstasscript dependency crashes the interpreter) -- it is covered by
# py_compile. These tests drive the HTTP contract through a fake backend that
# reproduces the production behavior, grounded in the REAL shared sample library
# (import-light: stdlib + instruments.descriptor) so the allowed-id set and the
# unknown-id rejection are checked against genuine data, not a hand-copy.
# --------------------------------------------------------------------------

_SAMPLE_IDS = [s.id for s in default_sample_library()]


class SampleBackend:
    """Fake backend mirroring the sample-selection API contract.

    GET /schema lists a ``sample`` field whose ``allowed`` comes from the sample
    library; PATCH /parameters and POST /scan accept a valid id and reject an
    unknown one with 400 ``invalid_parameters`` (as apply_parameters' p_choice
    does); the selected sample is stamped into the job's launch.parameters.
    """

    def __init__(self):
        self.registry = JobRegistry()
        self.current_sample = "none"

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle", "busy": False}

    def get_parameters(self):
        return {"sample": self.current_sample}

    def get_schema(self):
        return {
            "instrument": "puma",
            "fields": [
                {"name": "sample", "type": "string", "allowed": list(_SAMPLE_IDS)},
                {"name": "Ei", "type": "number", "units": "meV"},
            ],
            "scan_variables": ["H"],
            "scan_command_grammar": "STEP SIZE, not the number of points",
            "limits": {"max_points": 200},
            "endpoints": [],
            "examples": [],
        }

    def _apply_sample(self, patch):
        """Mirror apply_parameters: unknown id -> 400 invalid_parameters."""
        sample = patch.get("sample")
        if sample is None:
            return
        if sample not in _SAMPLE_IDS:
            raise ApiError(
                400, "invalid_parameters", "One or more fields failed",
                details={"applied": [], "errors": {
                    "sample": "invalid value: sample must be one of %s"
                              % sorted(_SAMPLE_IDS)}},
            )
        self.current_sample = sample

    def patch_parameters(self, patch, force):
        self._apply_sample(patch)
        return {"applied": list(patch), "errors": {}}

    def submit_scan(self, body, idempotency_key=None):
        # GUI-independent: the sample is overlaid onto the defaults for THIS job
        # only (unknown id -> 400), never mutating self.current_sample.
        patch = body.get("parameters") or {}
        sample = patch.get("sample", "none")
        if sample not in _SAMPLE_IDS:
            raise ApiError(
                400, "invalid_parameters", "One or more fields failed",
                details={"errors": {
                    "sample": "invalid value: sample must be one of %s"
                              % sorted(_SAMPLE_IDS)}},
            )
        key = None if sample == "none" else sample
        job = ScanJob(
            job_id=self.registry.next_id(), source="api",
            launch_state={"vals": {"sample": sample, "sample_key": key}},
        )
        self.registry.add(job)
        return {"job_id": job.job_id, "state": "queued", "position": 0}

    def get_job(self, job_id):
        job = self.registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        return job.snapshot()


def test_sample_library_exposes_expected_ids():
    # Grounds the schema/allowed contract in the real library.
    assert "none" in _SAMPLE_IDS
    assert "Al_bragg" in _SAMPLE_IDS
    assert "Al_phonon_DFT" in _SAMPLE_IDS


def test_schema_lists_sample_with_library_allowed_values():
    backend = SampleBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        sample = next(f for f in body["fields"] if f["name"] == "sample")
        assert sample["type"] == "string"
        assert sample["allowed"] == _SAMPLE_IDS
        assert "none" in sample["allowed"]
    finally:
        srv.stop()


def test_patch_sample_accepted():
    backend = SampleBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/parameters", method="PATCH",
                                data={"sample": "Al_phonon_DFT"})
        assert status == 200
        assert backend.current_sample == "Al_phonon_DFT"
    finally:
        srv.stop()


def test_patch_unknown_sample_400():
    backend = SampleBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/parameters", method="PATCH",
                                data={"sample": "Nonexistent"})
        assert status == 400
        assert body["error"]["code"] == "invalid_parameters"
        assert "sample" in body["error"]["details"]["errors"]
    finally:
        srv.stop()


def test_scan_stamps_selected_sample_in_launch_parameters():
    backend = SampleBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"parameters": {"sample": "Al_bragg"}})
        assert status == 202
        job_id = body["job_id"]
        s_status, s_body = _request(base + "/scan/%s" % job_id)
        assert s_status == 200
        params = s_body["launch"]["parameters"]
        assert params["sample"] == "Al_bragg"
        assert params["sample_key"] == "Al_bragg"
    finally:
        srv.stop()


def test_scan_unknown_sample_400():
    backend = SampleBackend()
    srv, base = _start(backend)
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"parameters": {"sample": "bogus"}})
        assert status == 400
        assert body["error"]["code"] == "invalid_parameters"
        # A sample nested under "parameters" is not a top-level key, so B1's
        # unknown-top-level-key check does not fire here.
        assert backend.registry.recent() == []
    finally:
        srv.stop()
