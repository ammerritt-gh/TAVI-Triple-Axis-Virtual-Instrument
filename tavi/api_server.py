"""Standalone HTTP server for the TAVI remote API.

This module implements the stdlib-only HTTP/REST + Server-Sent Events (SSE)
layer described in ``docs/API_SERVER_DESIGN.md`` (see especially sections 4, 5,
6, 9, and 11). It deliberately has **zero Qt imports and zero controller
imports** so it can be imported and unit-tested standalone.

The server is driven by a duck-typed ``backend`` object supplied at
construction. The handler calls the following callables on it; each may raise
``ApiError`` to produce a structured error envelope. Write methods
(``patch_parameters``, ``submit_scan``, ``stop_job``, ``stop_all``) may not yet
exist on the backend during earlier implementation phases; if the attribute is
missing the handler returns HTTP 501 ``not_implemented`` rather than crashing.

Backend protocol
----------------
- ``get_health() -> dict``
- ``get_state() -> dict``
- ``get_parameters() -> dict``
- ``patch_parameters(patch: dict, force: bool) -> dict``
- ``submit_scan(body: dict) -> dict``   (returns the 202 payload)
- ``get_job(job_id: str) -> dict``
- ``get_job_data(job_id: str) -> dict``
- ``stop_job(job_id: str) -> dict``
- ``stop_all(clear_queue: bool) -> dict``
- ``list_jobs() -> list``

Any backend method may raise ``ApiError(status, code, message, details=None)``,
which the request handler converts into the standard error JSON envelope
``{"error": {"code": ..., "message": ..., "details": ...}}``.

The module owns no persistent state at import time (no side effects on import).
"""

import json
import math
import sys
import threading
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


# Sentinel pushed into every SSE client queue on shutdown so handler loops exit.
SSE_CLOSE = object()

# Maximum number of concurrent SSE clients before /events returns 503.
MAX_SSE_CLIENTS = 8

# Maximum number of concurrent long-poll waiters (GET /scan/{id}?wait=N) before
# the endpoint returns 429 too_many_waiters. Bounds handler-thread consumption.
MAX_WAITERS = 16

# Upper bound (seconds) on a long-poll ``wait`` request; larger values clamp.
MAX_WAIT_SECONDS = 120.0

# Constant Retry-After (seconds) hints per status class (see _retry_after).
RETRY_AFTER_GUI_BUSY = 2      # 503 gui_busy: GUI thread briefly unavailable
RETRY_AFTER_409 = 5           # 409 conflict/busy: short backoff
RETRY_AFTER_429_DEFAULT = 30  # 429 with no queue-drain estimate available

API_PREFIX = "/api/v1"

DEFAULT_CONFIG = {
    "enabled": True,
    "mode": "allow",
    "host": "127.0.0.1",
    "port": 8642,
    "token": None,
    "limits": {
        "max_queued": 10,
        "max_points": 200,
        "max_neutrons_per_point": 1e8,
        "queue_neutron_budget": 1e10,
    },
}


class ApiError(Exception):
    """Structured API error raised by backend callables or the handler.

    Carries the HTTP ``status`` code plus a machine-readable ``code`` and a
    human ``message``; ``details`` is any JSON-safe extra payload. The request
    handler turns this into the standard error envelope.
    """

    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
        self.details = details


def _json_safe(obj):
    """Recursively convert NaN/inf floats to ``None`` so output is valid JSON.

    ``json.dumps(..., allow_nan=False)`` raises on NaN/inf; the design requires
    unmeasured/invalid points to serialize as ``null`` rather than bare ``NaN``
    (which breaks strict JSON parsers). This walks dicts/lists/tuples and
    replaces any non-finite float with ``None``.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((_json_safe(v) for v in obj), key=str)
    return obj


def _merge_config(defaults, overrides):
    """Merge a validated config dict over defaults; ``limits`` merged per-key."""
    merged = dict(defaults)
    merged["limits"] = dict(defaults.get("limits", {}))
    if not isinstance(overrides, dict):
        return merged
    for key, value in overrides.items():
        if key == "limits":
            if isinstance(value, dict):
                for lk, lv in value.items():
                    merged["limits"][lk] = lv
        else:
            merged[key] = value
    return merged


def load_api_config(config_path=None):
    """Load the API config tolerantly, merging file values over defaults.

    Reads ``config/api_config.json`` relative to the repo root by default. An
    absent, unreadable, or invalid file yields the defaults (with a console
    warning for invalid JSON, matching this layer's visibility pattern). Valid
    keys from the file win per-key; ``limits`` is merged per-key too.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "api_config.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return _merge_config(DEFAULT_CONFIG, {})

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[TAVI API] Warning: Could not parse {config_path}: {e}; using defaults")
        return _merge_config(DEFAULT_CONFIG, {})

    if not isinstance(data, dict):
        print(f"[TAVI API] Warning: {config_path} is not a JSON object; using defaults")
        return _merge_config(DEFAULT_CONFIG, {})

    return _merge_config(DEFAULT_CONFIG, data)


class SseBroker:
    """Thread-safe fan-out broker for Server-Sent Events.

    Each subscriber gets a bounded ``queue.Queue``. ``publish`` pre-serializes
    the frame once and non-blockingly enqueues it to every client; a client
    whose queue is full (a slow consumer) is dropped. All registry mutations are
    guarded by a lock.
    """

    def __init__(self, on_client_dropped=None):
        self._clients = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._on_client_dropped = on_client_dropped

    def subscribe(self):
        """Register a new client; return ``(client_id, queue)``."""
        q = queue.Queue(maxsize=1000)
        with self._lock:
            client_id = self._next_id
            self._next_id += 1
            self._clients[client_id] = q
        return client_id, q

    def unsubscribe(self, client_id):
        """Remove a client from the registry (idempotent)."""
        with self._lock:
            self._clients.pop(client_id, None)

    def client_count(self):
        """Return the current number of subscribed clients."""
        with self._lock:
            return len(self._clients)

    def publish(self, event, data):
        """Serialize once and enqueue an SSE frame to every client.

        A client whose queue is full is dropped (unsubscribed) and, if a
        callback was supplied, ``on_client_dropped(client_id)`` is invoked.
        """
        frame = "event: {}\ndata: {}\n\n".format(
            event, json.dumps(_json_safe(data), allow_nan=False)
        )
        dropped = []
        with self._lock:
            for client_id, q in list(self._clients.items()):
                try:
                    q.put_nowait(frame)
                except queue.Full:
                    self._clients.pop(client_id, None)
                    dropped.append(client_id)
        for client_id in dropped:
            if self._on_client_dropped is not None:
                self._on_client_dropped(client_id)

    def close(self):
        """Push the ``SSE_CLOSE`` sentinel to every client and clear registry."""
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for q in clients:
            try:
                q.put_nowait(SSE_CLOSE)
            except queue.Full:
                # Queue full: the client already has frames buffered and its
                # handler will notice the closed connection / next get.
                pass


class ApiRequestHandler(BaseHTTPRequestHandler):
    """Routes ``/api/v1`` requests to backend callables.

    Reads server-scoped configuration (``backend``, ``token``, ``mode``,
    ``broker``, ``log_callback``) from ``self.server``. Enforces bearer-token
    auth (all endpoints except ``/health``), access-mode gating (writes rejected
    with 403 in ``readonly`` mode), and emits the standard error envelope for
    every failure path.
    """

    server_version = "TAVI-API/1"
    protocol_version = "HTTP/1.1"

    # ---- logging -------------------------------------------------------

    def log_message(self, format, *args):
        """Route selected log lines to ``server.log_callback`` instead of stderr.

        Only errors (4xx/5xx) are logged here; successful 2xx/3xx responses are
        suppressed to avoid console noise. SSE connect/disconnect is logged
        explicitly from the events handler.
        """
        callback = getattr(self.server, "log_callback", None)
        if callback is None:
            return
        try:
            code = args[1] if len(args) >= 2 else ""
            code_str = str(code)
            if code_str[:1] in ("4", "5"):
                callback("%s - %s" % (self.address_string(), format % args))
        except Exception:
            # Never let logging break request handling.
            pass

    def _log(self, text):
        callback = getattr(self.server, "log_callback", None)
        if callback is not None:
            try:
                callback(text)
            except Exception:
                pass

    # ---- response helpers ---------------------------------------------

    def _send_json(self, status, obj, extra_headers=None):
        """Serialize ``obj`` (NaN-sanitized) and write a JSON response."""
        payload = json.dumps(_json_safe(obj), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _retry_after(self, status, code):
        """Return a Retry-After hint (int seconds) for a status/code, or None.

        503 -> a short constant (GUI briefly busy). 429 -> a queue-drain
        estimate from the backend when it can supply one, else a constant.
        409 -> a short constant backoff. Other statuses -> no header.
        """
        if status == 503:
            return RETRY_AFTER_GUI_BUSY
        if status == 429:
            backend = getattr(self.server, "backend", None)
            fn = getattr(backend, "estimate_queue_drain_seconds", None)
            if callable(fn):
                try:
                    secs = fn()
                except Exception:
                    secs = None
                if secs is not None and secs > 0:
                    return max(1, int(math.ceil(secs)))
            return RETRY_AFTER_429_DEFAULT
        if status == 409:
            return RETRY_AFTER_409
        return None

    def _send_error_envelope(self, status, code, message, details=None):
        """Write the standard ``{"error": {...}}`` envelope (+ Retry-After)."""
        err = {"code": code, "message": message}
        if details is not None:
            err["details"] = details
        retry_after = self._retry_after(status, code)
        headers = {"Retry-After": retry_after} if retry_after is not None else None
        self._send_json(status, {"error": err}, extra_headers=headers)

    def _read_json_body(self):
        """Parse a JSON request body using Content-Length.

        Returns a dict (empty dict for an empty body). Raises ``ApiError`` 400
        ``bad_request`` on malformed JSON or a non-object body.
        """
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ApiError(400, "bad_request", "Malformed JSON body: %s" % e)
        if not isinstance(parsed, dict):
            raise ApiError(400, "bad_request", "Request body must be a JSON object")
        return parsed

    # ---- auth / gating -------------------------------------------------

    def _check_auth(self):
        """Return True if authorized; else send 401 and return False.

        No auth is required when the server has no token configured. ``/health``
        never requires auth (checked by the caller).
        """
        token = getattr(self.server, "token", None)
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        expected = "Bearer %s" % token
        if header == expected:
            return True
        self._send_error_envelope(401, "unauthorized", "Missing or invalid bearer token")
        return False

    def _check_writable(self):
        """Return True if writes are allowed; else send 403 and return False."""
        mode = getattr(self.server, "mode", "allow")
        if mode == "readonly":
            self._send_error_envelope(
                403, "read_only", "Server is in read-only mode; writes are rejected"
            )
            return False
        return True

    # ---- backend invocation -------------------------------------------

    def _call_backend(self, method_name, *args):
        """Invoke a backend callable, mapping a missing attribute to 501.

        Returns the callable's result. Raises ``ApiError`` 501
        ``not_implemented`` if the backend lacks the method (a write endpoint
        that does not exist yet); any ``ApiError`` the callable raises
        propagates to the dispatcher, which sends the error envelope.
        """
        backend = self.server.backend
        fn = getattr(backend, method_name, None)
        if not callable(fn):
            raise ApiError(
                501, "not_implemented", "Endpoint not implemented: %s" % method_name
            )
        return fn(*args)

    # ---- HTTP verbs ----------------------------------------------------

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def _dispatch(self, method):
        """Top-level dispatcher with a catch-all 500 for unexpected errors."""
        try:
            parts = urlsplit(self.path)
            path = parts.path.rstrip("/") or parts.path
            if path != "/" and path.endswith("/"):
                path = path[:-1]
            query = parse_qs(parts.query)
            self._route(method, path, query)
        except ApiError as e:
            self._send_error_envelope(e.status, e.code, e.message, e.details)
        except Exception as e:
            # Never silently swallow: log and return a structured 500.
            self._log("[TAVI API] Internal error handling %s %s: %s"
                      % (method, self.path, e))
            self._send_error_envelope(
                500, "internal_error", "Internal server error", str(e)
            )

    def _route(self, method, path, query):
        """Match ``path`` against the /api/v1 route table."""
        if not path.startswith(API_PREFIX):
            raise ApiError(404, "not_found", "Unknown path: %s" % path)

        sub = path[len(API_PREFIX):]  # e.g. "/health", "/scan/j-0001/data"
        if sub == "":
            sub = "/"
        segments = [s for s in sub.split("/") if s != ""]

        # /health is public (no auth).
        if segments == ["health"]:
            self._require_method(method, "GET")
            result = self._call_backend("get_health")
            self._send_json(200, result)
            return

        # Everything else requires auth (if a token is configured).
        if not self._check_auth():
            return

        if segments == ["state"]:
            self._require_method(method, "GET")
            self._send_json(200, self._call_backend("get_state"))
            return

        if segments == ["parameters"]:
            if method == "GET":
                self._send_json(200, self._call_backend("get_parameters"))
                return
            if method == "PATCH":
                if not self._check_writable():
                    return
                body = self._read_json_body()
                force = _query_flag(query, "force")
                self._send_json(200, self._call_backend("patch_parameters", body, force))
                return
            raise ApiError(405, "method_not_allowed", "Method not allowed: %s" % method)

        if segments == ["jobs"]:
            self._require_method(method, "GET")
            self._send_json(200, self._call_backend("list_jobs"))
            return

        if segments == ["events"]:
            self._require_method(method, "GET")
            self._handle_sse()
            return

        if segments == ["scan"]:
            self._require_method(method, "POST")
            if not self._check_writable():
                return
            body = self._read_json_body()
            idem_key = self.headers.get("Idempotency-Key")
            if idem_key:
                payload = self._call_backend("submit_scan", body, idem_key)
            else:
                payload = self._call_backend("submit_scan", body)
            # A replayed idempotent submission returns the existing job's status
            # with HTTP 200 (flagged privately by the backend); a fresh job -> 202.
            status = 202
            if isinstance(payload, dict) and payload.pop("_idempotent_reuse", False):
                status = 200
            self._send_json(status, payload)
            return

        if segments == ["stop"]:
            self._require_method(method, "POST")
            if not self._check_writable():
                return
            body = self._read_json_body()
            clear_queue = bool(body.get("clear_queue", False))
            self._send_json(200, self._call_backend("stop_all", clear_queue))
            return

        if len(segments) >= 2 and segments[0] == "scan":
            job_id = segments[1]
            if len(segments) == 2:
                self._require_method(method, "GET")
                wait_seconds = self._parse_wait(query)
                if wait_seconds is None:
                    # No ?wait= -> current behavior exactly.
                    self._send_json(200, self._call_backend("get_job", job_id))
                else:
                    self._send_json(
                        200, self._call_backend("wait_for_job", job_id, wait_seconds)
                    )
                return
            if len(segments) == 3 and segments[2] == "data":
                self._require_method(method, "GET")
                self._send_json(200, self._call_backend("get_job_data", job_id))
                return
            if len(segments) == 3 and segments[2] == "stop":
                self._require_method(method, "POST")
                if not self._check_writable():
                    return
                self._send_json(200, self._call_backend("stop_job", job_id))
                return
            raise ApiError(404, "not_found", "Unknown path: %s" % path)

        raise ApiError(404, "not_found", "Unknown path: %s" % path)

    def _require_method(self, method, expected):
        """Raise 405 if ``method`` is not ``expected`` on a known path."""
        if method != expected:
            raise ApiError(
                405, "method_not_allowed", "Method not allowed: %s" % method
            )

    @staticmethod
    def _parse_wait(query):
        """Parse the ``?wait=N`` long-poll param, clamped to [0, MAX_WAIT_SECONDS].

        Returns ``None`` when the param is absent (caller uses current behavior).
        Raises ``ApiError`` 400 for a non-numeric value.
        """
        values = query.get("wait")
        if not values:
            return None
        raw = values[0].strip()
        if raw == "":
            return None
        try:
            wait_seconds = float(raw)
        except (TypeError, ValueError):
            raise ApiError(400, "bad_request", "wait must be a number of seconds")
        if wait_seconds < 0:
            wait_seconds = 0.0
        return min(wait_seconds, MAX_WAIT_SECONDS)

    # ---- SSE -----------------------------------------------------------

    def _handle_sse(self):
        """Serve the long-lived ``GET /events`` stream."""
        broker = self.server.broker
        if broker.client_count() >= MAX_SSE_CLIENTS:
            self._send_error_envelope(
                503, "too_many_clients", "Too many SSE clients connected"
            )
            return

        client_id, q = broker.subscribe()
        self._log("[TAVI API] SSE client %d connected (%s)"
                  % (client_id, self.address_string()))
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue

                if item is SSE_CLOSE:
                    break
                self.wfile.write(item.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client disconnected; fall through to cleanup.
            pass
        finally:
            broker.unsubscribe(client_id)
            self._log("[TAVI API] SSE client %d disconnected" % client_id)


def _query_flag(query, name):
    """Return True if ``?name=`` is a truthy flag (1/true/yes/on)."""
    values = query.get(name)
    if not values:
        return False
    val = values[0].strip().lower()
    return val in ("1", "true", "yes", "on", "")


class _TaviHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with daemon request threads and server-scoped state."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """Quiet routine client disconnects; keep full tracebacks for real errors.

        A client dropping a keep-alive connection (killed curl, closed SSE tab)
        surfaces as ConnectionResetError/BrokenPipeError in the request-line
        read, outside any handler code. socketserver's default prints a full
        traceback to stderr for these; that is console noise, not a fault.
        """
        exc = sys.exception()
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            log_callback = getattr(self, "log_callback", None)
            if log_callback is not None:
                log_callback("client %s:%s disconnected (%s)" % (
                    client_address[0], client_address[1], type(exc).__name__))
            return
        super().handle_error(request, client_address)


class TaviApiServer:
    """Owns the HTTP server lifecycle, the SSE broker, and live mode/token state.

    Constructed with a duck-typed ``backend``. ``start()`` binds and serves on a
    daemon thread (bind failures propagate as ``OSError``). ``stop()`` is
    idempotent. ``set_mode`` and ``publish`` may be called live.
    """

    def __init__(self, host, port, token, mode, backend, log_callback=None):
        self.host = host
        self.port = int(port)
        self.token = token
        self.mode = self._validate_mode(mode)
        self.backend = backend
        self.log_callback = log_callback
        self.broker = SseBroker(on_client_dropped=self._on_client_dropped)
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()

    @staticmethod
    def _validate_mode(mode):
        if mode not in ("allow", "readonly"):
            raise ValueError("Invalid API mode: %r (expected 'allow' or 'readonly')" % mode)
        return mode

    def _log(self, text):
        if self.log_callback is not None:
            try:
                self.log_callback(text)
            except Exception:
                pass

    def _on_client_dropped(self, client_id):
        self._log("[TAVI API] Dropped slow SSE client %d" % client_id)

    def start(self):
        """Bind the socket and serve on a daemon thread.

        Raises ``OSError`` on bind failure (e.g. port in use); the caller decides
        how to surface it.
        """
        with self._lock:
            if self._httpd is not None:
                return
            httpd = _TaviHTTPServer((self.host, self.port), ApiRequestHandler)
            # Attach server-scoped state read by the handler.
            httpd.backend = self.backend
            httpd.token = self.token
            httpd.mode = self.mode
            httpd.broker = self.broker
            httpd.log_callback = self.log_callback
            self._httpd = httpd
            self._thread = threading.Thread(
                target=httpd.serve_forever,
                name="tavi-api-server",
                daemon=True,
            )
            self._thread.start()
        self._log("[TAVI API] Listening on http://%s:%d%s" % (self.host, self.port, API_PREFIX))

    def stop(self):
        """Shut down the broker, the HTTP server, and join the thread (idempotent)."""
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None

        # Wake and release SSE handler loops first.
        try:
            self.broker.close()
        except Exception as e:
            self._log("[TAVI API] Error closing SSE broker: %s" % e)

        # Wake any long-poll waiters so their handler threads return promptly
        # instead of blocking until their individual timeouts elapse.
        wake = getattr(self.backend, "shutdown_waiters", None)
        if callable(wake):
            try:
                wake()
            except Exception as e:
                self._log("[TAVI API] Error waking long-poll waiters: %s" % e)

        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception as e:
                self._log("[TAVI API] Error during httpd.shutdown(): %s" % e)
            try:
                httpd.server_close()
            except Exception as e:
                self._log("[TAVI API] Error during httpd.server_close(): %s" % e)

        if thread is not None:
            thread.join(timeout=2)

    def set_mode(self, mode):
        """Validate and update the access mode live."""
        mode = self._validate_mode(mode)
        self.mode = mode
        with self._lock:
            if self._httpd is not None:
                self._httpd.mode = mode
        self._log("[TAVI API] Access mode set to '%s'" % mode)

    def publish(self, event, data):
        """Publish an SSE event via the broker (no-op if the server is stopped)."""
        self.broker.publish(event, data)
