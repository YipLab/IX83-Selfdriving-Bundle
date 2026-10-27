"""Hardware-free tests for the rehearsal-record audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import audit
import pytest
from audit import AuditError


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(tmp_path: Path, name: str, content: str = "evidence\n") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _run_manifest(tmp_path: Path, **overrides: Any) -> Path:
    artifact = _file(tmp_path, "artifact.csv")
    document = {
        "schema": "ix71.run-manifest.v1",
        "stages": [
            {
                "number": 1,
                "stage": "acquisition",
                "state": "implemented-and-verified-on-hardware",
                "artifacts": [
                    {
                        "path": str(artifact),
                        "bytes": artifact.stat().st_size,
                        "sha256": _digest(artifact),
                    }
                ],
            }
        ],
    }
    document.update(overrides)
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _report_v2(tmp_path: Path, **overrides: Any) -> Path:
    artifact = _file(tmp_path, "stage.csv")
    document = {
        "schema": "ix71.rehearsal-report.v1",
        "stages": [
            {
                "number": 7,
                "stage": "handoff-storage",
                "state": "implemented-and-verified-on-hardware",
                "record": str(_file(tmp_path, "record.md", "record\n")),
                "artifact_check": {
                    "found": [
                        {"path": str(artifact), "bytes": artifact.stat().st_size}
                    ],
                    "missing": [],
                },
            }
        ],
    }
    document.update(overrides)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _report_v1(tmp_path: Path, **overrides: Any) -> Path:
    artifact = _file(tmp_path, "v1.csv")
    manifest = {
        "schema": "ix71.artifact-manifest.v1",
        "artifacts": [
            {
                "stage": "1-acquisition",
                "original_path": str(artifact),
                "consolidated_path": str(artifact),
                "bytes": artifact.stat().st_size,
                "sha256": _digest(artifact),
            }
        ],
    }
    (tmp_path / "artifact_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    document = {
        "schema": "ix71.rehearsal-report.v1",
        "artifact_manifest": str(tmp_path / "artifact_manifest.json"),
        "stages": {"1-acquisition": {"status": "pass", "artifact_source_paths": []}},
    }
    document.update(overrides)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _codes(report: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_a_clean_run_manifest_passes(tmp_path: Path) -> None:
    report = audit.audit(_run_manifest(tmp_path))
    assert report["format"] == "run-manifest"
    assert report["artifact_count"] == 1
    assert report["by_status"] == {"ok": 1}
    assert report["findings"] == []
    assert report["accepted"] is False


def test_a_missing_artifact_breaks_a_verified_claim(tmp_path: Path) -> None:
    path = _run_manifest(tmp_path)
    (tmp_path / "artifact.csv").unlink()
    report = audit.audit(path)
    assert "artifact_missing" in _codes(report)
    assert "stage_claim_broken" in _codes(report)
    assert report["blocking"]


def test_a_digest_mismatch_is_blocking(tmp_path: Path) -> None:
    path = _run_manifest(tmp_path)
    (tmp_path / "artifact.csv").write_text("changed!\n", encoding="utf-8")
    report = audit.audit(path)
    assert "artifact_digest_mismatch" in _codes(report)
    assert report["by_status"]["digest_mismatch"] == 1


def test_a_byte_mismatch_without_a_digest_is_a_warning(tmp_path: Path) -> None:
    path = _report_v2(tmp_path)
    (tmp_path / "stage.csv").write_text("a longer replacement\n", encoding="utf-8")
    report = audit.audit(path)
    findings = {item["code"]: item["severity"] for item in report["findings"]}
    assert findings["artifact_byte_mismatch"] == "warning"
    assert report["blocking"] == []


def test_the_report_v2_collector_keeps_a_prose_note_out_of_the_artifact_list(
    tmp_path: Path,
) -> None:
    path = _report_v2(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["stages"][0]["artifact_check"]["found"].append(
        "no analyser in this light path, so no coefficient exists to apply"
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    report = audit.audit(path)
    assert report["artifact_count"] == 2
    assert report["skipped_entries"]
    assert "artifact_missing" not in _codes(report)


def test_the_report_v2_record_path_is_checked(tmp_path: Path) -> None:
    path = _report_v2(tmp_path)
    (tmp_path / "stage.csv").unlink()
    report = audit.audit(path)
    missing = [row for row in report["artifacts"] if not row["present"]]
    assert missing and all(row["kind"] == "artifact" for row in missing)


def test_the_v1_report_uses_its_artifact_manifest(tmp_path: Path) -> None:
    report = audit.audit(_report_v1(tmp_path))
    assert report["format"] == "rehearsal-report-v1"
    assert report["artifact_count"] == 1
    assert report["by_status"] == {"ok": 1}


def test_an_unrecognised_record_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"schema": "other", "stages": []}), encoding="utf-8")
    with pytest.raises(AuditError, match="unrecognised"):
        audit.audit(path)
    with pytest.raises(AuditError, match="missing source"):
        audit.audit(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(AuditError, match="unreadable JSON"):
        audit.audit(bad)


def test_cli_combines_sources_and_reports_blocking(tmp_path: Path) -> None:
    clean = _run_manifest(tmp_path)
    out = tmp_path / "audit.json"
    assert audit.main(["--source", str(clean), "--out", str(out)]) == 0
    combined = json.loads(out.read_text(encoding="utf-8"))
    assert combined["summary"]["artifacts"] == 1
    assert combined["summary"]["ok"] == 1

    (tmp_path / "artifact.csv").unlink()
    assert audit.main(["--source", str(clean), "--out", str(out)]) == 1
    assert (
        audit.main(["--source", str(tmp_path / "absent.json"), "--out", str(out)]) == 2
    )
