"""RuntimeTracker legacy-key migration tests ("PUMA" -> "puma", §17.5/§9)."""
import json

from tavi.runtime_tracker import RuntimeTracker


def _record(name, first=10.0, avg=5.0):
    return {
        "instrument_name": name,
        "num_points": 3,
        "num_neutrons": 100000,
        "first_scan_time": first,
        "avg_subsequent_time": avg,
        "total_time": first + 2 * avg,
        "timestamp": "2026-01-01T00:00:00",
        "compilation_time": 4.0,
    }


def _write_runtimes(path, records_by_key):
    path.write_text(json.dumps({"records": records_by_key}), encoding="utf-8")


def test_legacy_puma_key_migrates(tmp_path):
    config = tmp_path / "runtimes.json"
    _write_runtimes(config, {"PUMA": [_record("PUMA"), _record("PUMA", first=12.0)]})

    tracker = RuntimeTracker(config_path=str(config))

    assert tracker.get_record_count("puma") == 2
    assert tracker.get_record_count("PUMA") == 0
    assert all(rec.instrument_name == "puma" for rec in tracker.records["puma"])

    # The next write persists only the new key.
    tracker.add_record(
        instrument_name="puma", num_points=3, num_neutrons=100000,
        first_scan_time=11.0, avg_subsequent_time=5.0, total_time=21.0,
    )
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert set(saved["records"]) == {"puma"}
    assert len(saved["records"]["puma"]) == 3


def test_migration_merges_both_keys_present(tmp_path):
    config = tmp_path / "runtimes.json"
    _write_runtimes(config, {
        "PUMA": [_record("PUMA", first=1.0)],
        "puma": [_record("puma", first=2.0)],
    })

    tracker = RuntimeTracker(config_path=str(config))

    assert tracker.get_record_count("puma") == 2
    # Legacy records come first (older history), existing new-key records after.
    assert [rec.first_scan_time for rec in tracker.records["puma"]] == [1.0, 2.0]


def test_migration_respects_max_records(tmp_path):
    config = tmp_path / "runtimes.json"
    _write_runtimes(config, {
        "PUMA": [_record("PUMA", first=float(i)) for i in range(80)],
        "puma": [_record("puma", first=float(100 + i)) for i in range(40)],
    })

    tracker = RuntimeTracker(config_path=str(config))

    assert tracker.get_record_count("puma") == tracker.max_records == 100
    # Trim keeps the most recent entries (the tail of legacy + all new-key).
    assert tracker.records["puma"][-1].first_scan_time == 139.0
    assert tracker.records["puma"][0].first_scan_time == 20.0


def test_no_legacy_key_is_noop(tmp_path):
    config = tmp_path / "runtimes.json"
    _write_runtimes(config, {"puma": [_record("puma")]})

    tracker = RuntimeTracker(config_path=str(config))

    assert tracker.get_record_count("puma") == 1
