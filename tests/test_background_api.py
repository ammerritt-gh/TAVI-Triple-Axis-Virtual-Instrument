"""Qt-free HTTP and source-wiring tests for ``tavi.background/2``."""
import copy
import json
import os
import urllib.error
import urllib.request

import pytest

from tavi import background
from tavi.api_server import (
    API_PREFIX,
    ApiError,
    BACKGROUND_SPEC_KEYS,
    SCAN_BODY_KEYS,
    VALIDATE_BODY_KEYS,
    TaviApiServer,
    parse_scan_background,
    parse_scan_engine,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")
SIMULATION_DOCK_PATH = os.path.join(
    REPO_ROOT, "gui", "docks", "unified_simulation_dock.py"
)
DIALOG_PATH = os.path.join(
    REPO_ROOT, "gui", "dialogs", "background_config_dialog.py"
)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _spec(enabled=True, sources=None):
    return {
        "catalog_version": background.CATALOG_VERSION,
        "enabled": enabled,
        "sources": sources if sources is not None else {
            "environment_flat": {"enabled": True, "scale": 1.0},
        },
    }


def test_background_absent_or_null_uses_config_default():
    assert parse_scan_background({}) is None
    assert parse_scan_background({"background": None}) is None


def test_background_v2_shape_is_accepted_without_deep_resolution():
    spec = _spec(sources={
        "future_source": {"enabled": True, "scale": "resolved later"},
    })
    assert parse_scan_background({"background": spec}) == spec
    with pytest.raises(ValueError):
        background.resolve(spec)


@pytest.mark.parametrize("legacy_field", ["preset", "overrides", "terms", "scale"])
def test_remote_v1_fields_are_rejected(legacy_field):
    with pytest.raises(ApiError) as caught:
        parse_scan_background({"background": {legacy_field: None}})
    assert caught.value.status == 400
    assert caught.value.details["unknown"] == [legacy_field]


def test_background_non_object_and_unknown_field_are_400():
    with pytest.raises(ApiError):
        parse_scan_background({"background": "flat"})
    with pytest.raises(ApiError) as caught:
        parse_scan_background({"background": {**_spec(), "rate": 1.0}})
    assert caught.value.details["unknown"] == ["rate"]
    assert caught.value.details["allowed"] == sorted(BACKGROUND_SPEC_KEYS)


def test_background_contract_keys_and_scan_validate_parity():
    assert BACKGROUND_SPEC_KEYS == frozenset(
        {"catalog_version", "enabled", "sources"}
    )
    assert "background" in SCAN_BODY_KEYS
    assert "background" in VALIDATE_BODY_KEYS


def _request(url, method="GET", data=None, timeout=5):
    headers = {}
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
        raw, status = response.read(), response.getcode()
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    return status, json.loads(raw.decode("utf-8")) if raw else None


class _BackgroundBackend:
    def __init__(self):
        self.spec = background.default_spec()

    def get_health(self):
        return {"status": "ok"}

    def _state(self):
        resolved = background.resolve(self.spec)
        return {
            "spec": background.normalized_spec(resolved),
            "resolved": background.metadata_block(resolved, "config_default"),
        }

    def get_background(self):
        return self._state()

    def set_background(self, body):
        try:
            resolved = background.resolve(body)
        except ValueError as exc:
            raise ApiError(400, "invalid_background", str(exc))
        self.spec = background.normalized_spec(resolved)
        return self._state()

    def submit_scan(self, body, idempotency_key=None):
        parse_scan_engine(body)
        spec = parse_scan_background(body)
        if spec is not None:
            spec = background.normalized_spec(background.resolve(spec))
        return {
            "job_id": "j-0001",
            "state": "queued",
            "position": 0,
            "background": spec,
            "background_source": (
                "per_scan_override" if spec is not None else "config_default"
            ),
        }

    def submit_validate(self, body):
        spec = parse_scan_background(body)
        resolved = background.resolve(spec if spec is not None else self.spec)
        delivery = "per_scan_override" if spec is not None else "config_default"
        return {
            "would_queue": True,
            "blockers": [],
            "background": background.metadata_block(resolved, delivery),
        }

    def get_schema(self):
        return {
            "scan_body_fields": [{"name": "background", "type": "object"}],
            "endpoints": [
                {"method": "GET", "path": "/background"},
                {"method": "PUT", "path": "/background"},
            ],
            "background": {
                "background_schema": background.BACKGROUND_SCHEMA,
                "catalog_version": background.CATALOG_VERSION,
                "categories": list(background.CATEGORIES),
                "sources": background.source_catalog(),
                "spec_fields": sorted(BACKGROUND_SPEC_KEYS),
            },
        }


class _BareBackend:
    def get_health(self):
        return {"status": "ok"}


def _start(backend, mode="allow"):
    server = TaviApiServer(
        host="127.0.0.1", port=0, token=None, mode=mode, backend=backend
    )
    server.start()
    port = server._httpd.server_address[1]
    return server, f"http://127.0.0.1:{port}{API_PREFIX}"


def test_get_put_background_normalizes_sparse_sources_wholesale():
    server, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/background")
        assert status == 200
        assert body["spec"] == background.default_spec()

        sparse = _spec(sources={
            "sample_elastic": {"enabled": True, "scale": 0.5},
        })
        status, body = _request(
            base + "/background", method="PUT", data=sparse
        )
        assert status == 200
        assert set(body["spec"]["sources"]) == set(background.SOURCES)
        assert body["spec"]["sources"]["sample_elastic"]["scale"] == 0.5
        assert body["spec"]["sources"]["environment_flat"] == {
            "enabled": False,
            "scale": 1.0,
        }
        assert body["resolved"]["background_schema"] == "tavi.background/2"
        assert "sample_scale" not in body["resolved"]
        assert "skipped_terms" not in body["resolved"]
    finally:
        server.stop()


@pytest.mark.parametrize(
    "bad_spec",
    [
        {"enabled": True, "preset": "flat"},
        _spec(sources={"environment_flat": {"enabled": True, "scale": -1.0}}),
        _spec(sources={"unknown": {"enabled": True, "scale": 1.0}}),
        {"catalog_version": 1, "enabled": True, "sources": {}},
        {"catalog_version": 999, "enabled": True, "sources": {}},
    ],
)
def test_put_background_rejects_invalid_v2_or_v1(bad_spec):
    server, base = _start(_BackgroundBackend())
    try:
        status, body = _request(
            base + "/background", method="PUT", data=bad_spec
        )
        assert status == 400
        assert body["error"]["code"] in {"bad_request", "invalid_background"}
    finally:
        server.stop()


def test_background_readonly_and_missing_backend_behavior():
    server, base = _start(_BackgroundBackend(), mode="readonly")
    try:
        assert _request(base + "/background")[0] == 200
        assert _request(
            base + "/background", method="PUT", data=_spec()
        )[0] == 403
    finally:
        server.stop()
    server, base = _start(_BareBackend())
    try:
        assert _request(base + "/background")[0] == 501
    finally:
        server.stop()


def test_scan_and_validate_accept_v2_override_and_report_delivery_source():
    server, base = _start(_BackgroundBackend())
    try:
        spec = _spec(sources={
            "instrument_aluminum_powder": {"enabled": True, "scale": 2.0},
            "environment_cosmic_spikes": {"enabled": True, "scale": 0.5},
        })
        status, body = _request(
            base + "/scan",
            method="POST",
            data={"engine": "deterministic", "background": spec},
        )
        assert status == 202
        assert body["background_source"] == "per_scan_override"
        assert set(body["background"]["sources"]) == set(background.SOURCES)

        status, body = _request(
            base + "/validate", method="POST", data={"background": spec}
        )
        assert status == 200
        block = body["background"]
        assert block["delivery_source"] == "per_scan_override"
        assert block["catalog_version"] == 2
        assert set(block) >= {
            "profile_fingerprint", "effective_fingerprint", "sources",
        }
    finally:
        server.stop()


def test_schema_advertises_versioned_source_catalog():
    server, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        block = body["background"]
        assert block["background_schema"] == "tavi.background/2"
        assert block["catalog_version"] == 2
        assert block["categories"] == ["environment", "instrument", "sample"]
        assert set(block["sources"]) == set(background.SOURCES)
        for source in block["sources"].values():
            assert set(source) == {
                "category", "label", "description", "scale_meaning", "shape",
                "base_numerics", "units",
            }
    finally:
        server.stop()


def test_controller_schema_and_runtime_use_v2_core_contract():
    source = _read(CONTROLLER_PATH)
    assert '"catalog_version": _background.CATALOG_VERSION' in source
    assert '"sources": _background.source_catalog()' in source
    assert "_background.normalized_spec(resolved)" in source
    assert "def _background_sample_scale" not in source
    assert "SampleScaleUnavailable" not in source
    assert "sample_scale=" not in source
    assert "skipped_terms=" not in source


def test_controller_injects_and_validates_background_before_queueing():
    source = _read(CONTROLLER_PATH)
    assert "'background': copy.deepcopy(self.background_profile)" in source
    assert "self._apply_background_to_launch_state(controller, launch_state, background)" in source
    submit = source.split("def _submit_scan_on_gui", 1)[1].split(
        "def submit_validate", 1
    )[0]
    assert submit.index("_background_validation") < submit.index(
        "controller.submit_scan_job"
    )


def test_simulation_row_and_dialog_expose_staged_independent_controls():
    dock = _read(SIMULATION_DOCK_PATH)
    dialog = _read(DIALOG_PATH)
    assert "engine_row.addWidget(self.engine_combo)" in dock
    assert "self.background_enable_check = QCheckBox()" in dock
    assert 'QPushButton("Background configuration…")' in dock
    assert "background_preset_combo" not in dock
    assert "background_scale_spin" not in dock
    assert "background_summary_label" not in dock
    assert "item[\"scale_meaning\"]" in dialog
    assert "QDialogButtonBox.StandardButton.Apply" in dialog
    assert ").clicked.connect(self.accept)" in dialog
    assert "buttons.rejected.connect(self.reject)" in dialog
    assert "Scale ×1 uses the catalog reference setting." in dialog
    assert "scale_spin.setDecimals(12)" in dialog


def test_dialog_scale_precision_survives_normalized_state_conversion():
    spec = {
        "catalog_version": background.CATALOG_VERSION,
        "enabled": True,
        "sources": {
            "environment_flat": {"enabled": True, "scale": 0.0004},
            "sample_elastic": {"enabled": True, "scale": 1.23456},
        },
    }
    converted = background.normalized_spec(background.resolve(spec))
    assert converted["sources"]["environment_flat"]["scale"] == 0.0004
    assert converted["sources"]["sample_elastic"]["scale"] == 1.23456


def test_controller_applies_global_gate_immediately_but_dialog_on_accept_only():
    source = _read(CONTROLLER_PATH)
    assert "background_enable_check.toggled.connect(" in source
    assert "background_config_button.clicked.connect(" in source
    toggle = source.split("def _on_background_enabled_toggled", 1)[1].split(
        "def configure_background", 1
    )[0]
    assert 'spec["enabled"] = bool(enabled)' in toggle
    configure = source.split("def configure_background", 1)[1].split(
        "def ", 1
    )[0]
    assert "if spec is None:" in configure
    assert "self.set_background_profile(spec)" in configure
