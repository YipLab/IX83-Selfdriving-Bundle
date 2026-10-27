"""Hardware-free tests for the rehearsal report builder (skill close-out)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import build_report as report_tool


def _file(root: Path, name: str, content: str = "artifact\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified(path: Path, name: str) -> dict[str, Any]:
    return {"path": name, "sha256": _digest(path)}


def _declaration(stages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": report_tool.DECLARATION_SCHEMA,
        "run_id": "run-fixture",
        "scope": "software-recorded-data",
        "attempts": {"acquisition": "attempt-1"},
        "calibration_id": "cal-fixture",
        "stages": stages,
    }


def test_a_fully_verified_chain_is_accepted(tmp_path: Path) -> None:
    table = _file(tmp_path, "stage/table.csv")
    image = _file(tmp_path, "stage/mosaic.tif")
    declaration = _declaration(
        [
            {"stage": "acquisition", "status": "verified", "artifacts": [_verified(table, "stage/table.csv")]},
            {"stage": "stitching-mosaic", "status": "verified", "artifacts": [_verified(image, "stage/mosaic.tif")]},
        ]
    )

    report = report_tool.build_report(declaration, root=tmp_path)

    assert report["accepted"] is True
    assert [stage["status"] for stage in report["stages"]] == ["verified", "verified"]
    assert report["summary"]["verified"] == 2
    assert report["summary"]["artifacts_verified"] == 2
    assert report["blocking"] == []


def test_a_missing_artifact_makes_the_stage_partial_and_blocks(tmp_path: Path) -> None:
    table = _file(tmp_path, "stage/table.csv")
    declaration = _declaration(
        [
            {
                "stage": "acquisition",
                "status": "verified",
                "artifacts": [
                    _verified(table, "stage/table.csv"),
                    {"path": "stage/absent.json", "sha256": "0" * 64},
                ],
            }
        ]
    )

    report = report_tool.build_report(declaration, root=tmp_path)

    assert report["accepted"] is False
    assert report["stages"][0]["status"] == "partial"
    assert report["stages"][0]["blocking"] == ["stage/absent.json"]
    assert report["blocking"] == [{"stage": "acquisition", "artifacts": ["stage/absent.json"]}]


def test_a_changed_artifact_is_blocking(tmp_path: Path) -> None:
    table = _file(tmp_path, "stage/table.csv")
    digest = _digest(table)
    table.write_text("changed\n", encoding="utf-8")
    declaration = _declaration(
        [
            {
                "stage": "acquisition",
                "status": "verified",
                "artifacts": [{"path": "stage/table.csv", "sha256": digest}],
            }
        ]
    )

    report = report_tool.build_report(declaration, root=tmp_path)

    assert report["accepted"] is False
    assert report["stages"][0]["artifacts"][0]["status"] == "digest_mismatch"
    assert report["stages"][0]["artifacts"][0]["actual_sha256"] == _digest(table)


def test_a_directory_is_present_but_not_digested(tmp_path: Path) -> None:
    store = tmp_path / "stage/store.zarr"
    store.mkdir(parents=True)
    (store / "zarr.json").write_text("{}\n", encoding="utf-8")
    declaration = _declaration(
        [
            {
                "stage": "acquisition",
                "status": "verified",
                "artifacts": [{"path": "stage/store.zarr"}],
            }
        ]
    )

    report = report_tool.build_report(declaration, root=tmp_path)

    artifact = report["stages"][0]["artifacts"][0]
    assert artifact["status"] == "present-not-digested"
    assert artifact["files"] == 1
    assert report["accepted"] is True
    assert report["stages"][0]["status"] == "partial"


def test_a_not_applied_stage_keeps_its_reason_and_is_counted(tmp_path: Path) -> None:
    table = _file(tmp_path, "stage/table.csv")
    declaration = _declaration(
        [
            {"stage": "acquisition", "status": "verified", "artifacts": [_verified(table, "stage/table.csv")]},
            {
                "stage": "anisotropy",
                "status": "not-applied",
                "reason": "no RTASPT analysis was run for this attempt",
            },
        ]
    )

    report = report_tool.build_report(declaration, root=tmp_path)

    assert report["stages"][1]["status"] == "not-applied"
    assert report["stages"][1]["reason"].startswith("no RTASPT")
    assert report["summary"]["not_applied"] == 1
    assert report["summary"]["not_applied_stages"] == ["anisotropy"]
    assert report["accepted"] is True


def test_the_declaration_is_validated() -> None:
    with pytest.raises(report_tool.ReportError, match="schema"):
        report_tool.load_declaration({"stages": []})
    with pytest.raises(report_tool.ReportError, match="run_id"):
        report_tool.load_declaration(_declaration([]) | {"run_id": " "})
    with pytest.raises(report_tool.ReportError, match="nonempty list"):
        report_tool.load_declaration(_declaration([]))
    with pytest.raises(report_tool.ReportError, match="known stage"):
        report_tool.load_declaration(_declaration([{"stage": "tuning", "status": "verified"}]))
    with pytest.raises(report_tool.ReportError, match="declared twice"):
        report_tool.load_declaration(
            _declaration(
                [
                    {"stage": "acquisition", "status": "verified"},
                    {"stage": "acquisition", "status": "verified"},
                ]
            )
        )
    with pytest.raises(report_tool.ReportError, match="needs a reason"):
        report_tool.load_declaration(
            _declaration([{"stage": "anisotropy", "status": "not-applied"}])
        )
    with pytest.raises(report_tool.ReportError, match="cannot declare artifacts"):
        report_tool.load_declaration(
            _declaration(
                [
                    {
                        "stage": "anisotropy",
                        "status": "not-applied",
                        "reason": "not run",
                        "artifacts": [{"path": "x"}],
                    }
                ]
            )
        )
    with pytest.raises(report_tool.ReportError, match="64 lowercase hex"):
        report_tool.load_declaration(
            _declaration(
                [
                    {
                        "stage": "acquisition",
                        "status": "verified",
                        "artifacts": [{"path": "x", "sha256": "abc"}],
                    }
                ]
            )
        )


def test_the_command_line_writes_a_report(tmp_path: Path) -> None:
    table = _file(tmp_path, "stage/table.csv")
    declaration_path = tmp_path / "declaration.json"
    declaration_path.write_text(
        json.dumps(
            _declaration(
                [
                    {
                        "stage": "acquisition",
                        "status": "verified",
                        "artifacts": [_verified(table, "stage/table.csv")],
                    }
                ]
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rehearsal_report.json"

    exit_code = report_tool.main(
        [str(declaration_path), "--root", str(tmp_path), "--output", str(output)]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema"] == report_tool.REPORT_SCHEMA
    assert report["summary"]["verified"] == 1
