"""Unit tests for tavi/api_server.py (routing, auth, SSE, config, broker).

Pure stdlib, no Qt. Spins up a real ``TaviApiServer`` on an ephemeral port
(port 0) with a fake duck-typed backend, and exercises the HTTP surface with
urllib / raw sockets. Also covers the SseBroker in isolation and the tolerant
config loader. See ``docs/API_SERVER_DESIGN.md`` §13 phase 5.

All network operations use short timeouts so a hung server can never hang the
suite; the server fixture always tears the server down.
"""
import json
import queue
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from tavi.api_server import (
    ApiError,
    SseBroker,
    TaviApiServer,
    load_api_config,
    _merge_config,
    _json_safe,
    DEFAULT_CONFIG,
    API_PREFIX,
    SSE_CLOSE,
    MAX_WAITERS,
)
from tavi.scan_jobs import JobRegistry, JobState, ScanJob


# ==========================================================================
# Fake backend
# ==========================================================================

class FakeBackend:
    """Duck-typed backend with canned returns and recorded calls."""

    def __init__(self):
        self.calls = []

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle", "busy": False}

    def get_parameters(self):
        return {"Ei": 14.0, "A3": 0.0}

    def patch_parameters(self, patch, force):
        self.calls.append(("patch_parameters", patch, force))
        return {"applied": patch, "force": force}

    def submit_scan(self, body):
        self.calls.append(("submit_scan", body))
        return {"job_id": "j-0001", "state": "queued"}

    def get_job(self, job_id):
        self.calls.append(("get_job", job_id))
        if job_id == "missing":
            raise ApiError(404, "not_found", "No such job: %s" % job_id)
        return {"job_id": job_id, "state": "running"}

    def get_job_data(self, job_id):
        return {"job_id": job_id, "complete": False}

    def stop_job(self, job_id):
        self.calls.append(("stop_job", job_id))
        return {"job_id": job_id, "state": "stopped"}

    def stop_all(self, clear_queue):
        self.calls.append(("stop_all", clear_queue))
        return {"stopped": True, "clear_queue": clear_queue}

    def list_jobs(self):
        return [{"job_id": "j-0001"}]


# A plain object exposing only reads -> write routes should 501.
class ReadOnlyBackend:
    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {"Ei": 14.0}
    # No submit_scan / patch_parameters / stop_* -> 501 on write routes.


class NaNBackend:
    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"x": float("nan"), "y": float("inf"), "z": 1.0}

    def get_parameters(self):
        return {"x": float("nan")}


# ==========================================================================
# Server harness
# ==========================================================================

def _start_server(backend=None, token=None, mode="allow"):
    """Start a TaviApiServer on an ephemeral port; return (server, base_url)."""
    backend = backend if backend is not None else FakeBackend()
    server = TaviApiServer(
        host="127.0.0.1", port=0, token=token, mode=mode, backend=backend,
    )
    server.start()
    port = server._httpd.server_address[1]
    base = "http://127.0.0.1:%d%s" % (port, API_PREFIX)
    return server, base


def _request(url, method="GET", data=None, headers=None, timeout=5):
    """Perform an HTTP request; return (status, body_dict_or_none, raw_bytes).

    4xx/5xx responses are captured (not raised) so error envelopes can be
    asserted on.
    """
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
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        body = None
    return status, body, raw


@pytest.fixture
def server():
    srv, base = _start_server()
    try:
        yield srv, base, srv.backend
    finally:
        srv.stop()


# ==========================================================================
# Routing (no auth)
# ==========================================================================

def test_health_ok_no_auth(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/health")
    assert status == 200
    assert body == {"status": "ok"}


def test_state_ok(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/state")
    assert status == 200
    assert body["state"] == "idle"


def test_parameters_ok(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/parameters")
    assert status == 200
    assert body["Ei"] == 14.0


def test_unknown_path_404_envelope(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/nope")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def test_unprefixed_path_404(server):
    _srv, _base, _b = server
    # Hit a path outside /api/v1.
    root = _base_root(_base)
    status, body, _ = _request(root + "/random")
    assert status == 404
    assert body["error"]["code"] == "not_found"


def _base_root(base):
    # Strip the API prefix to hit the bare host.
    assert base.endswith(API_PREFIX)
    return base[: -len(API_PREFIX)]


def test_wrong_method_405_envelope(server):
    _srv, base, _b = server
    # /state only allows GET.
    status, body, _ = _request(base + "/state", method="POST", data={})
    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"


def test_scan_id_passthrough(server):
    _srv, base, backend = server
    status, body, _ = _request(base + "/scan/j-0042")
    assert status == 200
    assert body["job_id"] == "j-0042"
    assert ("get_job", "j-0042") in backend.calls


def test_scan_id_apierror_404_envelope(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/scan/missing")
    assert status == 404
    assert body["error"]["code"] == "not_found"
    assert "missing" in body["error"]["message"]


def test_scan_id_data_passthrough(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/scan/j-1/data")
    assert status == 200
    assert body == {"job_id": "j-1", "complete": False}


def test_jobs_list(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/jobs")
    assert status == 200
    assert body == [{"job_id": "j-0001"}]


def test_trailing_slash_normalized(server):
    _srv, base, _b = server
    status, body, _ = _request(base + "/state/")
    assert status == 200
    assert body["state"] == "idle"


# ==========================================================================
# Auth
# ==========================================================================

def test_auth_401_without_header():
    srv, base = _start_server(token="s3cret")
    try:
        status, body, _ = _request(base + "/state")
        assert status == 401
        assert body["error"]["code"] == "unauthorized"
    finally:
        srv.stop()


def test_auth_200_with_bearer():
    srv, base = _start_server(token="s3cret")
    try:
        status, body, _ = _request(
            base + "/state", headers={"Authorization": "Bearer s3cret"})
        assert status == 200
        assert body["state"] == "idle"
    finally:
        srv.stop()


def test_auth_wrong_token_401():
    srv, base = _start_server(token="s3cret")
    try:
        status, _body, _ = _request(
            base + "/state", headers={"Authorization": "Bearer nope"})
        assert status == 401
    finally:
        srv.stop()


def test_health_exempt_from_auth():
    srv, base = _start_server(token="s3cret")
    try:
        status, body, _ = _request(base + "/health")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        srv.stop()


# ==========================================================================
# Mode gating
# ==========================================================================

def test_readonly_rejects_post_scan():
    srv, base = _start_server(mode="readonly")
    try:
        status, body, _ = _request(base + "/scan", method="POST", data={})
        assert status == 403
        assert body["error"]["code"] == "read_only"
    finally:
        srv.stop()


def test_readonly_allows_get():
    srv, base = _start_server(mode="readonly")
    try:
        status, _body, _ = _request(base + "/state")
        assert status == 200
    finally:
        srv.stop()


def test_set_mode_allow_lets_post_through():
    srv, base = _start_server(mode="readonly")
    try:
        status, _b, _ = _request(base + "/scan", method="POST", data={})
        assert status == 403
        srv.set_mode("allow")
        status, body, _ = _request(base + "/scan", method="POST",
                                    data={"force": True})
        assert status == 202
        assert body["job_id"] == "j-0001"
    finally:
        srv.stop()


# ==========================================================================
# 501 when backend lacks a write method
# ==========================================================================

def test_missing_write_method_501():
    srv, base = _start_server(backend=ReadOnlyBackend(), mode="allow")
    try:
        status, body, _ = _request(base + "/scan", method="POST", data={})
        assert status == 501
        assert body["error"]["code"] == "not_implemented"
    finally:
        srv.stop()


# ==========================================================================
# NaN sanitization over HTTP
# ==========================================================================

def test_nan_sanitized_to_null_in_response():
    srv, base = _start_server(backend=NaNBackend(), mode="allow")
    try:
        status, body, raw = _request(base + "/state")
        assert status == 200
        assert body["x"] is None
        assert body["y"] is None
        assert body["z"] == 1.0
        # Raw bytes must be strict JSON: no bare NaN token.
        assert b"NaN" not in raw
        assert b"Infinity" not in raw
    finally:
        srv.stop()


# ==========================================================================
# Body handling
# ==========================================================================

def test_malformed_json_body_400():
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(
            base + "/scan", method="POST", data=b"{not valid json",
            headers={"Content-Type": "application/json"})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
    finally:
        srv.stop()


def test_non_object_json_body_400():
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(
            base + "/scan", method="POST", data=b"[1, 2, 3]",
            headers={"Content-Type": "application/json"})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
    finally:
        srv.stop()


# ==========================================================================
# Strict top-level POST body keys (unknown key -> 400)
# ==========================================================================

def test_reject_unknown_body_keys_helper():
    from tavi.api_server import reject_unknown_body_keys, SCAN_BODY_KEYS
    # A non-dict body is a no-op (the caller/backend rejects it on its own terms).
    reject_unknown_body_keys([1, 2, 3], SCAN_BODY_KEYS)
    # A body with only allowed keys passes.
    reject_unknown_body_keys({"parameters": {}, "force": True}, SCAN_BODY_KEYS)
    # Unknown keys raise 400 and are reported sorted in the details.
    with pytest.raises(ApiError) as exc:
        reject_unknown_body_keys(
            {"parameters": {}, "bogus": 1, "aaa": 2}, SCAN_BODY_KEYS)
    assert exc.value.status == 400
    assert exc.value.code == "bad_request"
    assert exc.value.details["unknown"] == ["aaa", "bogus"]


def test_scan_unknown_top_level_key_400():
    backend = FakeBackend()
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, body, _ = _request(base + "/scan", method="POST",
                                   data={"scan_commands": "H 1 2 0.5"})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
        assert "scan_commands" in body["error"]["message"]
        assert body["error"]["details"]["unknown"] == ["scan_commands"]
        # The offending body must never reach the backend / queue a job.
        assert not any(c[0] == "submit_scan" for c in backend.calls)
    finally:
        srv.stop()


def test_scan_known_top_level_keys_pass():
    # Every documented POST /scan top-level field is accepted together.
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(
            base + "/scan", method="POST",
            data={"parameters": {"Ei": 14.0}, "force": True,
                  "isolated": True,
                  "engine": "mcstas", "seed": 7, "noiseless": False})
        assert status == 202
        assert body["job_id"] == "j-0001"
    finally:
        srv.stop()


def test_validate_unknown_top_level_key_400():
    # /validate rejects an unknown key before dispatching to the backend, so a
    # backend lacking submit_validate still yields 400 (not 501).
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(base + "/validate", method="POST",
                                   data={"parameters": {}, "typo": 1})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
        assert "typo" in body["error"]["message"]
    finally:
        srv.stop()


def test_stop_unknown_top_level_key_400():
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(base + "/stop", method="POST",
                                   data={"clear_q": True})
        assert status == 400
        assert body["error"]["code"] == "bad_request"
        assert "clear_q" in body["error"]["message"]
    finally:
        srv.stop()


def test_stop_known_key_passes():
    srv, base = _start_server(mode="allow")
    try:
        status, body, _ = _request(base + "/stop", method="POST",
                                   data={"clear_queue": True})
        assert status == 200
        assert body["clear_queue"] is True
    finally:
        srv.stop()


# ==========================================================================
# ?force=1 flag reaches backend
# ==========================================================================

def test_force_flag_reaches_backend():
    backend = FakeBackend()
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, body, _ = _request(
            base + "/parameters?force=1", method="PATCH", data={"Ei": 15.0})
        assert status == 200
        assert body["force"] is True
        # Recorded call has force=True.
        patch_calls = [c for c in backend.calls if c[0] == "patch_parameters"]
        assert patch_calls == [("patch_parameters", {"Ei": 15.0}, True)]
    finally:
        srv.stop()


def test_no_force_flag_defaults_false():
    backend = FakeBackend()
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, body, _ = _request(
            base + "/parameters", method="PATCH", data={"Ei": 15.0})
        assert status == 200
        assert body["force"] is False
        patch_calls = [c for c in backend.calls if c[0] == "patch_parameters"]
        assert patch_calls == [("patch_parameters", {"Ei": 15.0}, False)]
    finally:
        srv.stop()


# ==========================================================================
# SseBroker (no HTTP)
# ==========================================================================

def test_broker_subscribe_publish_frame_format():
    broker = SseBroker()
    cid, q = broker.subscribe()
    assert broker.client_count() == 1
    broker.publish("point", {"n": 3})
    frame = q.get_nowait()
    assert frame == 'event: point\ndata: {"n": 3}\n\n'


def test_broker_publish_nan_becomes_null():
    broker = SseBroker()
    _cid, q = broker.subscribe()
    broker.publish("p", {"v": float("nan")})
    frame = q.get_nowait()
    assert '"v": null' in frame
    # data payload is strict JSON.
    data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
    json.loads(data_line[len("data: "):])


def test_broker_multiple_clients_all_receive():
    broker = SseBroker()
    _c1, q1 = broker.subscribe()
    _c2, q2 = broker.subscribe()
    broker.publish("e", {"a": 1})
    assert q1.get_nowait() == q2.get_nowait()


def test_broker_unsubscribe():
    broker = SseBroker()
    cid, _q = broker.subscribe()
    broker.unsubscribe(cid)
    assert broker.client_count() == 0
    # Idempotent.
    broker.unsubscribe(cid)


def test_broker_slow_client_dropped_on_full_queue():
    dropped = []
    broker = SseBroker(on_client_dropped=dropped.append)
    cid, _q = broker.subscribe()
    # Queue maxsize is 1000: fill it, then one more publish drops the client.
    for _ in range(1000):
        broker.publish("e", {"i": 1})
    assert broker.client_count() == 1
    broker.publish("e", {"i": 1})  # 1001st -> put_nowait raises Full -> drop
    assert broker.client_count() == 0
    assert dropped == [cid]


def test_broker_close_delivers_sentinel():
    broker = SseBroker()
    _cid, q = broker.subscribe()
    broker.close()
    assert q.get_nowait() is SSE_CLOSE
    assert broker.client_count() == 0


def test_broker_drop_without_callback_does_not_raise():
    broker = SseBroker()  # no on_client_dropped
    broker.subscribe()
    for _ in range(1002):
        broker.publish("e", {"i": 1})
    assert broker.client_count() == 0


# ==========================================================================
# SSE over HTTP (one fast test)
# ==========================================================================

def _read_until(sock, needle, deadline):
    """Read from sock until ``needle`` (bytes) is seen or deadline passes."""
    buf = b""
    while needle not in buf:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break  # EOF
        buf += chunk
    return buf


def test_sse_over_http_delivers_event_then_ends():
    srv, base = _start_server(mode="allow")
    host_port = srv._httpd.server_address
    try:
        sock = socket.create_connection(host_port, timeout=5)
        sock.sendall(
            b"GET %s/events HTTP/1.1\r\nHost: localhost\r\n\r\n"
            % API_PREFIX.encode("ascii"))

        deadline = time.time() + 5
        # Wait until the client is subscribed (": connected" preamble sent).
        buf = _read_until(sock, b": connected", deadline)
        assert b": connected" in buf

        # Give the handler a beat to register, then publish one event.
        assert _wait(lambda: srv.broker.client_count() == 1, 3)
        srv.publish("point", {"index": 5, "counts": 12.0})

        frame = _read_until(sock, b"data:", time.time() + 5)
        assert b"event: point" in frame
        assert b"data: " in frame
        # Extract the JSON data payload and validate it.
        text = frame.decode("utf-8", "replace")
        data_line = [ln for ln in text.splitlines()
                     if ln.startswith("data: ")][0]
        payload = json.loads(data_line[len("data: "):])
        assert payload == {"index": 5, "counts": 12.0}

        # Stopping the server pushes the SSE_CLOSE sentinel, which breaks the
        # handler's forward loop. After that, published events reach zero
        # clients: the stream must stop delivering. Verify no further event
        # frame arrives (either EOF or an idle, silent socket).
        srv.stop()
        srv.publish("afterstop", {"x": 1})
        sock.settimeout(1.5)
        extra = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break  # EOF: connection closed
                extra += chunk
        except socket.timeout:
            pass  # idle socket (kept alive) but no more events
        assert b"afterstop" not in extra
        sock.close()
    finally:
        srv.stop()


def _wait(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


# ==========================================================================
# load_api_config
# ==========================================================================

def test_config_absent_file_returns_defaults(tmp_path):
    cfg = load_api_config(tmp_path / "does_not_exist.json")
    assert cfg == _merge_config(DEFAULT_CONFIG, {})
    assert cfg["mode"] == "allow"
    assert cfg["port"] == 8642
    assert cfg["limits"]["max_points"] == 200


def test_config_partial_merges_per_key(tmp_path):
    p = tmp_path / "api_config.json"
    p.write_text(json.dumps({
        "port": 9000,
        "token": "abc",
        "limits": {"max_points": 5},
    }), encoding="utf-8")
    cfg = load_api_config(p)
    assert cfg["port"] == 9000
    assert cfg["token"] == "abc"
    # Overridden nested key.
    assert cfg["limits"]["max_points"] == 5
    # Un-overridden nested keys retain defaults.
    assert cfg["limits"]["max_queued"] == 10
    assert cfg["limits"]["queue_neutron_budget"] == 1e10
    # Un-overridden top-level keys retain defaults.
    assert cfg["mode"] == "allow"
    assert cfg["host"] == "127.0.0.1"


def test_config_invalid_json_returns_defaults(tmp_path):
    p = tmp_path / "api_config.json"
    p.write_text("{ this is not valid json", encoding="utf-8")
    cfg = load_api_config(p)
    assert cfg == _merge_config(DEFAULT_CONFIG, {})


def test_config_non_object_json_returns_defaults(tmp_path):
    p = tmp_path / "api_config.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = load_api_config(p)
    assert cfg == _merge_config(DEFAULT_CONFIG, {})


def test_merge_config_does_not_mutate_defaults():
    _merge_config(DEFAULT_CONFIG, {"limits": {"max_points": 1}})
    # DEFAULT_CONFIG must be untouched.
    assert DEFAULT_CONFIG["limits"]["max_points"] == 200


# ==========================================================================
# Lifecycle
# ==========================================================================

def test_stop_is_idempotent():
    srv, _base = _start_server()
    srv.stop()
    srv.stop()  # must not raise
    srv.stop()


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        TaviApiServer(host="127.0.0.1", port=0, token=None, mode="bogus",
                      backend=FakeBackend())


def test_json_safe_helper():
    assert _json_safe(float("nan")) is None
    assert _json_safe(float("inf")) is None
    assert _json_safe({"a": [1.0, float("nan")]}) == {"a": [1.0, None]}
    assert _json_safe(1.5) == 1.5
    assert _json_safe("s") == "s"


# ==========================================================================
# Long-poll, ETA, Retry-After, Idempotency  (features 1-3)
# ==========================================================================

def _request_h(url, method="GET", data=None, headers=None, timeout=10):
    """Like ``_request`` but also returns the response headers dict."""
    hdrs = dict(headers or {})
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.getcode()
        resp_headers = dict(resp.getheaders())
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        resp_headers = dict(e.headers.items())
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        body = None
    return status, body, resp_headers


class JobBackend:
    """Fake backend backed by a real JobRegistry/ScanJob for long-poll + eta.

    Mirrors the relevant slice of the production ``TaviApiBackend`` contract:
    wait_for_job (with the concurrent-waiter cap), an ``eta`` object on job/
    submit payloads, idempotent submit replay, and shutdown_waiters.
    """

    ETA = {"estimated_seconds": 12.5, "confidence": "high", "samples": 11}

    def __init__(self):
        self.registry = JobRegistry()
        self._waiter_lock = threading.Lock()
        self._waiter_count = 0
        self._wait_abort = threading.Event()
        self._idem = {}  # key -> job_id
        self.drain_estimate = None  # estimate_queue_drain_seconds() return

    # -- helpers --
    def _new_job(self, state=JobState.QUEUED):
        job = ScanJob(job_id=self.registry.next_id(), source="api",
                      launch_state={"vals": {}})
        job.state = state
        self.registry.add(job)
        return job

    def _get(self, job_id):
        job = self.registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        return job

    # -- read endpoints --
    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}

    def get_job(self, job_id):
        snap = self._get(job_id).snapshot()
        snap["eta"] = dict(self.ETA)
        return snap

    def get_job_data(self, job_id):
        return self._get(job_id).snapshot(include_data=True)

    def list_jobs(self):
        return self.registry.recent()

    # -- long-poll --
    def wait_for_job(self, job_id, timeout):
        job = self._get(job_id)
        with self._waiter_lock:
            if self._wait_abort.is_set():
                snap = job.snapshot()
                snap["eta"] = dict(self.ETA)
                snap["timed_out"] = False
                return snap
            if self._waiter_count >= MAX_WAITERS:
                raise ApiError(429, "too_many_waiters",
                               "Too many concurrent long-poll waiters")
            self._waiter_count += 1
        try:
            reached = job.wait_for_terminal(timeout, abort=self._wait_abort)
        finally:
            with self._waiter_lock:
                self._waiter_count -= 1
        snap = job.snapshot()
        snap["eta"] = dict(self.ETA)
        snap["timed_out"] = (not reached) and (not self._wait_abort.is_set())
        return snap

    def shutdown_waiters(self):
        self._wait_abort.set()
        self.registry.wake_all_waiters()

    # -- write endpoints --
    def submit_scan(self, body, idempotency_key=None):
        if idempotency_key and idempotency_key in self._idem:
            job = self.registry.get(self._idem[idempotency_key])
            if job is not None:
                snap = job.snapshot()
                snap["eta"] = dict(self.ETA)
                snap["_idempotent_reuse"] = True
                return snap
        job = self._new_job()
        if idempotency_key:
            self._idem[idempotency_key] = job.job_id
        return {"job_id": job.job_id, "state": "queued", "position": 0,
                "eta": dict(self.ETA)}

    def estimate_queue_drain_seconds(self):
        return self.drain_estimate


def _start_job_server(backend=None, mode="allow"):
    backend = backend if backend is not None else JobBackend()
    server = TaviApiServer(host="127.0.0.1", port=0, token=None, mode=mode,
                           backend=backend)
    server.start()
    port = server._httpd.server_address[1]
    base = "http://127.0.0.1:%d%s" % (port, API_PREFIX)
    return server, base, backend


# ---- long-poll -----------------------------------------------------------

def test_wait_immediate_return_on_terminal_job():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.DONE)
        t0 = time.time()
        status, body, _ = _request(base + "/scan/%s?wait=5" % job.job_id)
        assert status == 200
        assert body["state"] == "done"
        assert body["timed_out"] is False
        assert time.time() - t0 < 1.0
    finally:
        srv.stop()


def test_wait_timeout_returns_timed_out_true():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.RUNNING)
        status, body, _ = _request(base + "/scan/%s?wait=0.3" % job.job_id)
        assert status == 200
        assert body["state"] == "running"
        assert body["timed_out"] is True
    finally:
        srv.stop()


def test_wait_woken_by_state_change():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.RUNNING)

        def finish():
            time.sleep(0.2)
            with job.lock:
                job.state = JobState.DONE
                job.notify_state_change()

        threading.Thread(target=finish).start()
        t0 = time.time()
        status, body, _ = _request(base + "/scan/%s?wait=5" % job.job_id)
        elapsed = time.time() - t0
        assert status == 200
        assert body["state"] == "done"
        assert body["timed_out"] is False
        assert elapsed < 3.0
    finally:
        srv.stop()


def test_no_wait_param_omits_timed_out():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.RUNNING)
        status, body, _ = _request(base + "/scan/%s" % job.job_id)
        assert status == 200
        assert "timed_out" not in body
    finally:
        srv.stop()


def test_wait_invalid_value_400():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.RUNNING)
        status, body, _ = _request(base + "/scan/%s?wait=abc" % job.job_id)
        assert status == 400
        assert body["error"]["code"] == "bad_request"
    finally:
        srv.stop()


def test_waiter_cap_returns_429():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.RUNNING)
        threads = []
        # Saturate the waiter pool with blocking long-polls.
        for _ in range(MAX_WAITERS):
            t = threading.Thread(
                target=lambda: _request(base + "/scan/%s?wait=3" % job.job_id))
            t.start()
            threads.append(t)
        # Wait until all are registered as waiters.
        assert _wait(lambda: backend._waiter_count >= MAX_WAITERS, 3)
        status, body, headers = _request_h(base + "/scan/%s?wait=1" % job.job_id)
        assert status == 429
        assert body["error"]["code"] == "too_many_waiters"
        assert "Retry-After" in headers
        # Release the blocked waiters.
        with job.lock:
            job.state = JobState.DONE
            job.notify_state_change()
        for t in threads:
            t.join(timeout=3)
    finally:
        srv.stop()


def test_shutdown_wakes_waiters():
    srv, base, backend = _start_job_server()
    job = backend._new_job(state=JobState.RUNNING)
    done = {}

    def waiter():
        done["r"] = _request(base + "/scan/%s?wait=10" % job.job_id)

    t = threading.Thread(target=waiter)
    t.start()
    assert _wait(lambda: backend._waiter_count >= 1, 3)
    t0 = time.time()
    srv.stop()  # should wake the waiter promptly
    t.join(timeout=3)
    assert not t.is_alive()
    assert time.time() - t0 < 3.0


# ---- eta in responses ----------------------------------------------------

def test_eta_in_get_job_response():
    srv, base, backend = _start_job_server()
    try:
        job = backend._new_job(state=JobState.QUEUED)
        status, body, _ = _request(base + "/scan/%s" % job.job_id)
        assert status == 200
        assert set(body["eta"]) == {"estimated_seconds", "confidence", "samples"}
    finally:
        srv.stop()


def test_eta_in_submit_202_response():
    srv, base, backend = _start_job_server()
    try:
        status, body, _ = _request(base + "/scan", method="POST", data={})
        assert status == 202
        assert set(body["eta"]) == {"estimated_seconds", "confidence", "samples"}
    finally:
        srv.stop()


# ---- Retry-After ---------------------------------------------------------

class RetryBackend:
    """Raises specific ApiErrors so Retry-After headers can be asserted."""

    def __init__(self):
        self.drain = None

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        raise ApiError(503, "gui_busy", "GUI busy")

    def get_parameters(self):
        return {}

    def get_job(self, job_id):
        raise ApiError(409, "job_finished", "Job already finished")

    def submit_scan(self, body, idempotency_key=None):
        raise ApiError(429, "limit_exceeded", "queue full")

    def estimate_queue_drain_seconds(self):
        return self.drain


def test_retry_after_on_503():
    backend = RetryBackend()
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, _b, headers = _request_h(base + "/state")
        assert status == 503
        assert headers.get("Retry-After") == "2"
    finally:
        srv.stop()


def test_retry_after_on_409():
    backend = RetryBackend()
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, _b, headers = _request_h(base + "/scan/j-1")
        assert status == 409
        assert headers.get("Retry-After") == "5"
    finally:
        srv.stop()


def test_retry_after_on_429_default_constant():
    backend = RetryBackend()  # drain estimate None -> constant 30
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, _b, headers = _request_h(base + "/scan", method="POST", data={})
        assert status == 429
        assert headers.get("Retry-After") == "30"
    finally:
        srv.stop()


def test_retry_after_on_429_uses_queue_drain_estimate():
    backend = RetryBackend()
    backend.drain = 42.2  # -> ceil = 43
    srv, base = _start_server(backend=backend, mode="allow")
    try:
        status, _b, headers = _request_h(base + "/scan", method="POST", data={})
        assert status == 429
        assert headers.get("Retry-After") == "43"
    finally:
        srv.stop()


def test_no_retry_after_on_normal_error():
    # 404 must not carry a Retry-After header.
    srv, base, backend = _start_job_server()
    try:
        status, _b, headers = _request_h(base + "/scan/missing")
        assert status == 404
        assert "Retry-After" not in headers
    finally:
        srv.stop()


# ---- Idempotency-Key -----------------------------------------------------

def test_idempotency_dedupe_returns_same_job_200():
    srv, base, backend = _start_job_server()
    try:
        # First submission creates a job (202).
        status1, body1, _ = _request_h(
            base + "/scan", method="POST", data={},
            headers={"Idempotency-Key": "abc"})
        assert status1 == 202
        job_id = body1["job_id"]
        # Replay with the same key returns the existing job with 200.
        status2, body2, _ = _request_h(
            base + "/scan", method="POST", data={},
            headers={"Idempotency-Key": "abc"})
        assert status2 == 200
        assert body2["job_id"] == job_id
        # The private reuse marker must not leak to clients.
        assert "_idempotent_reuse" not in body2
    finally:
        srv.stop()


def test_idempotency_distinct_keys_create_distinct_jobs():
    srv, base, backend = _start_job_server()
    try:
        _s1, b1, _ = _request_h(base + "/scan", method="POST", data={},
                                headers={"Idempotency-Key": "k1"})
        _s2, b2, _ = _request_h(base + "/scan", method="POST", data={},
                                headers={"Idempotency-Key": "k2"})
        assert b1["job_id"] != b2["job_id"]
    finally:
        srv.stop()


def test_no_idempotency_key_always_new_job():
    srv, base, backend = _start_job_server()
    try:
        _s1, b1, _ = _request(base + "/scan", method="POST", data={})
        _s2, b2, _ = _request(base + "/scan", method="POST", data={})
        assert b1["job_id"] != b2["job_id"]
    finally:
        srv.stop()
