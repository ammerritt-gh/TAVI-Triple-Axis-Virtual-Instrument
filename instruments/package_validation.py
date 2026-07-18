"""Validate the scientist-facing and runtime-facing instrument packages."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping


PACKAGE_SCHEMA_VERSION = 1
PACKAGE_STATUSES = {"runnable", "research", "retired"}
REQUIRED_DOCUMENTS = ("README.md", "MODEL_STATUS.md", "SCIENTIST_REVIEW.md")
_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_REFERENCE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})__[a-z0-9][a-z0-9-]*__v\d{2}\.[A-Za-z0-9.]+$"
)
_MARKDOWN_LINK_RE = re.compile(r"\[[^]]*]\(([^)]+)\)")


@dataclass(frozen=True, slots=True)
class PackageMetadata:
    path: Path
    id: str
    display_name: str
    facility: str
    status: str
    model_version: str
    model_date: str


def _load_metadata(path: Path, errors: list[str]) -> PackageMetadata | None:
    manifest = path / "instrument.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{manifest}: cannot read valid UTF-8 JSON: {exc}")
        return None

    required = {
        "schema_version", "id", "display_name", "facility", "status",
        "model_version", "model_date",
    }
    missing = sorted(required - set(data)) if isinstance(data, dict) else sorted(required)
    if not isinstance(data, dict):
        errors.append(f"{manifest}: top level must be a JSON object")
        return None
    if missing:
        errors.append(f"{manifest}: missing fields: {', '.join(missing)}")
        return None
    if data["schema_version"] != PACKAGE_SCHEMA_VERSION:
        errors.append(
            f"{manifest}: schema_version must be {PACKAGE_SCHEMA_VERSION}"
        )

    for key in ("id", "display_name", "facility", "status", "model_version", "model_date"):
        if not isinstance(data[key], str) or not data[key].strip():
            errors.append(f"{manifest}: {key} must be a non-empty string")

    instrument_id = data["id"] if isinstance(data["id"], str) else ""
    status = data["status"] if isinstance(data["status"], str) else ""
    version = data["model_version"] if isinstance(data["model_version"], str) else ""
    model_date = data["model_date"] if isinstance(data["model_date"], str) else ""
    if not _ID_RE.fullmatch(instrument_id):
        errors.append(f"{manifest}: id must match [a-z0-9_]+")
    if instrument_id and path.name != instrument_id:
        errors.append(f"{manifest}: id {instrument_id!r} must match directory {path.name!r}")
    if status not in PACKAGE_STATUSES:
        errors.append(f"{manifest}: status must be one of {sorted(PACKAGE_STATUSES)}")
    if not _SEMVER_RE.fullmatch(version):
        errors.append(f"{manifest}: model_version must be MAJOR.MINOR.PATCH")
    try:
        date.fromisoformat(model_date)
    except ValueError:
        errors.append(f"{manifest}: model_date must be an ISO date (YYYY-MM-DD)")

    return PackageMetadata(
        path=path,
        id=instrument_id,
        display_name=str(data["display_name"]),
        facility=str(data["facility"]),
        status=status,
        model_version=version,
        model_date=model_date,
    )


def _validate_markdown_links(path: Path, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: cannot read Markdown: {exc}")
        return
    for target in _MARKDOWN_LINK_RE.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (path.parent / target).resolve().exists():
            errors.append(f"{path}: broken local link: {target}")


def _validate_package_files(metadata: PackageMetadata, errors: list[str]) -> None:
    path = metadata.path
    for filename in REQUIRED_DOCUMENTS:
        document = path / filename
        if not document.is_file():
            errors.append(f"{path}: missing required document {filename}")
        else:
            _validate_markdown_links(document, errors)

    references = path / "references"
    sources = references / "SOURCES.md"
    if not sources.is_file():
        errors.append(f"{path}: missing references/SOURCES.md")
    else:
        _validate_markdown_links(sources, errors)
    if references.is_dir():
        for item in references.iterdir():
            if not item.is_file() or item.name == "SOURCES.md":
                continue
            match = _REFERENCE_RE.fullmatch(item.name)
            if not match:
                errors.append(
                    f"{item}: reference name must be YYYY-MM-DD__source-id__vNN.ext"
                )
                continue
            try:
                date.fromisoformat(match.group(1))
            except ValueError:
                errors.append(f"{item}: reference filename starts with an invalid date")

    for private_assets in ("components", "data"):
        if (path / private_assets).exists():
            errors.append(
                f"{path}: built-in instrument assets must remain in central components/"
            )

    if metadata.status == "runnable":
        for filename in ("__init__.py", "plugin.py", "model.py"):
            if not (path / filename).is_file():
                errors.append(f"{path}: runnable package is missing {filename}")
    elif metadata.status == "research":
        for filename in ("plugin.py", "model.py"):
            if (path / filename).exists():
                errors.append(f"{path}: research package must not contain {filename}")


def _live_plugins() -> dict[str, object]:
    import instruments.builtin  # noqa: F401  (explicit registration)
    from instruments.registry import available_instruments, get_instrument

    return {info.id: get_instrument(info.id) for info in available_instruments()}


def validate_packages(
    instruments_root: str | Path | None = None,
    *,
    check_runtime: bool = True,
    runtime_plugins: Mapping[str, object] | None = None,
) -> list[str]:
    """Return all package validation errors; an empty list means valid."""
    root = (
        Path(instruments_root)
        if instruments_root is not None
        else Path(__file__).resolve().parent
    )
    errors: list[str] = []
    packages: dict[str, PackageMetadata] = {}
    manifests = sorted(root.glob("*/instrument.json"))
    for manifest in manifests:
        metadata = _load_metadata(manifest.parent, errors)
        if metadata is None:
            continue
        if metadata.id in packages:
            errors.append(
                f"{manifest}: duplicate instrument id {metadata.id!r} also used by "
                f"{packages[metadata.id].path}"
            )
        else:
            packages[metadata.id] = metadata
        _validate_package_files(metadata, errors)

    if check_runtime:
        plugins = dict(runtime_plugins) if runtime_plugins is not None else _live_plugins()
        registered = set(plugins)
        runnable = {item.id for item in packages.values() if item.status == "runnable"}
        research = {item.id for item in packages.values() if item.status == "research"}
        for instrument_id in sorted(runnable - registered):
            errors.append(f"{instrument_id}: runnable package is not registered")
        for instrument_id in sorted(research & registered):
            errors.append(f"{instrument_id}: research package must not be registered")
        for instrument_id in sorted(registered - runnable):
            errors.append(f"{instrument_id}: registered instrument has no runnable package")
        for instrument_id in sorted(runnable & registered):
            metadata = packages[instrument_id]
            plugin = plugins[instrument_id]
            descriptor = plugin.descriptor()
            if getattr(plugin, "id", None) != metadata.id:
                errors.append(f"{instrument_id}: plugin id does not match instrument.json")
            if getattr(plugin, "display_name", None) != metadata.display_name:
                errors.append(
                    f"{instrument_id}: plugin display_name does not match instrument.json"
                )
            if descriptor.id != metadata.id:
                errors.append(f"{instrument_id}: descriptor id does not match instrument.json")
            if descriptor.display_name != metadata.display_name:
                errors.append(
                    f"{instrument_id}: descriptor display_name does not match instrument.json"
                )
    return errors


def main() -> int:
    errors = validate_packages()
    if errors:
        for error in errors:
            print(f"[instrument-package] {error}")
        return 1
    print("All instrument packages are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
