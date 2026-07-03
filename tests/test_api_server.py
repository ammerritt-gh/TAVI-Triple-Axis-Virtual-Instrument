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
)


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
                                    data={"foo": 1})
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
