"""Validation of the unified runnable and research instrument packages."""
import json
from types import SimpleNamespace

from instruments.package_validation import validate_packages


def _write_package(root, name, *, instrument_id=None, status="research"):
    path = root / name
    path.mkdir()
    metadata = {
        "schema_version": 1,
        "id": instrument_id or name,
        "display_name": name.upper(),
        "facility": "TEST",
        "status": status,
        "model_version": "0.1.0",
        "model_date": "2026-07-18",
    }
    (path / "instrument.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    for filename in ("README.md", "MODEL_STATUS.md", "SCIENTIST_REVIEW.md"):
        (path / filename).write_text(f"# {filename}\n", encoding="utf-8")
    references = path / "references"
    references.mkdir()
    (references / "SOURCES.md").write_text("# Sources\n", encoding="utf-8")
    if status == "runnable":
        for filename in ("__init__.py", "plugin.py", "model.py"):
            (path / filename).write_text("", encoding="utf-8")
    return path, metadata


def test_live_packages_are_valid():
    assert validate_packages() == []


def test_manifest_version_and_date_are_validated(tmp_path):
    path, metadata = _write_package(tmp_path, "demo")
    metadata["model_version"] = "version one"
    metadata["model_date"] = "last Tuesday"
    (path / "instrument.json").write_text(json.dumps(metadata), encoding="utf-8")

    errors = validate_packages(tmp_path, check_runtime=False)
    assert any("MAJOR.MINOR.PATCH" in error for error in errors)
    assert any("ISO date" in error for error in errors)


def test_required_documents_references_and_links_are_validated(tmp_path):
    path, _ = _write_package(tmp_path, "demo")
    (path / "SCIENTIST_REVIEW.md").unlink()
    (path / "README.md").write_text("[missing](not-there.md)\n", encoding="utf-8")
    (path / "references" / "bad-name.pdf").write_bytes(b"pdf")

    errors = validate_packages(tmp_path, check_runtime=False)
    assert any("missing required document SCIENTIST_REVIEW.md" in error for error in errors)
    assert any("broken local link" in error for error in errors)
    assert any("reference name" in error for error in errors)


def test_duplicate_ids_are_rejected(tmp_path):
    _write_package(tmp_path, "first", instrument_id="same")
    _write_package(tmp_path, "second", instrument_id="same")
    errors = validate_packages(tmp_path, check_runtime=False)
    assert any("duplicate instrument id" in error for error in errors)


def test_research_package_cannot_be_registered(tmp_path):
    _write_package(tmp_path, "demo", status="research")
    plugin = SimpleNamespace(
        id="demo",
        display_name="DEMO",
        descriptor=lambda: SimpleNamespace(id="demo", display_name="DEMO"),
    )
    errors = validate_packages(tmp_path, runtime_plugins={"demo": plugin})
    assert any("research package must not be registered" in error for error in errors)


def test_runnable_manifest_must_match_plugin_and_descriptor(tmp_path):
    _write_package(tmp_path, "demo", status="runnable")
    plugin = SimpleNamespace(
        id="demo",
        display_name="Wrong name",
        descriptor=lambda: SimpleNamespace(id="demo", display_name="Also wrong"),
    )
    errors = validate_packages(tmp_path, runtime_plugins={"demo": plugin})
    assert any("plugin display_name" in error for error in errors)
    assert any("descriptor display_name" in error for error in errors)
