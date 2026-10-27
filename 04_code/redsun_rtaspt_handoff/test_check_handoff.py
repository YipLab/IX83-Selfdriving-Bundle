"""Hardware-free tests for the handoff bundle checker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import check_handoff
import numpy as np
import pytest
import tifffile
import yaml
from check_handoff import HandoffError


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path, **overrides: Any) -> Path:
    """Write a minimal, valid handoff bundle and return its handoff.json."""
    frames = [[0, 0.0, 0.0, 0.0], [1, 1.0, 0.0, 0.5]]
    (tmp_path / "frames.csv").write_text(
        "frame,x_um,y_um,time_s\n"
        + "\n".join(",".join(str(v) for v in row) for row in frames)
        + "\n",
        encoding="utf-8",
    )
    request = {
        "kind": "settled",
        "frames": "frames.csv",
        "searchscan": {},
        "transform": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        "tile_shape": [4, 5],
        "order": "as_given",
        "lattice_spacing_um": [1.0, 1.0],
        "snap_to_lattice": False,
        "images": {},
        "detection": {},
        "duplicates": {},
        "notes": [],
    }
    (tmp_path / "request.yaml").write_text(yaml.safe_dump(request), encoding="utf-8")
    tifffile.imwrite(
        tmp_path / "stack.ome.tif",
        np.zeros((2, 4, 5), dtype=np.uint16),
        ome=True,
        metadata={"axes": "TYX"},
    )
    outputs = {
        "movie": {
            "path": "stack.ome.tif",
            "sha256": _digest(tmp_path / "stack.ome.tif"),
        },
        "frames": {"path": "frames.csv", "sha256": _digest(tmp_path / "frames.csv")},
        "request": {
            "path": "request.yaml",
            "sha256": _digest(tmp_path / "request.yaml"),
        },
    }
    handoff = {
        "schema": check_handoff.HANDOFF_SCHEMA,
        "frame_count": 2,
        "tile_shape": [4, 5],
        "order": {"mode": "as_given"},
        "request": {"path": "request.yaml", "sha256": outputs["request"]["sha256"]},
        "outputs": outputs,
        "provenance": {"path": "provenance.json"},
        "checks": [
            {"id": identifier, "detail": f"declared {identifier}"}
            for identifier in check_handoff.WRITER_CHECK_IDS
        ],
        "warnings": [],
        "limits": [],
    }
    handoff.update(overrides)
    provenance = {
        "schema": "redsun-rtaspt-handoff-provenance-v1",
        "outputs": {
            name: {"sha256": entry["sha256"]} for name, entry in outputs.items()
        },
    }
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(handoff), encoding="utf-8")
    return path


def _codes(report: dict[str, Any]) -> set[str]:
    return {finding["code"] for finding in report["findings"]}


def test_a_valid_bundle_passes_every_check(tmp_path: Path) -> None:
    report = check_handoff.check_handoff(_bundle(tmp_path))
    assert report["accepted"] is True
    assert report["findings"] == []
    assert all(check["ok"] for check in report["checks"])
    assert len(report["checks"]) >= 15
    assert len(report["declared_checks"]) == 7


def test_a_missing_output_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    (tmp_path / "request.yaml").unlink()
    report = check_handoff.check_handoff(path)
    assert "output_missing" in _codes(report)
    assert report["accepted"] is False


def test_a_changed_output_digest_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    (tmp_path / "frames.csv").write_text(
        "frame,x_um,y_um,time_s\n0,0,0,0\n", encoding="utf-8"
    )
    report = check_handoff.check_handoff(path)
    assert "output_digest_mismatch" in _codes(report)


def test_a_frame_table_count_mismatch_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path, frame_count=3)
    report = check_handoff.check_handoff(path)
    assert "frame_table_count_mismatch" in _codes(report)


def test_frame_ids_must_be_sequential_with_finite_values(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    (tmp_path / "frames.csv").write_text(
        "frame,x_um,y_um,time_s\n2,0,0,0\n3,1,0,0.5\n", encoding="utf-8"
    )
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["frames"]["sha256"] = _digest(tmp_path / "frames.csv")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "frame_table_values_invalid" in _codes(report)


def test_decreasing_frame_time_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    (tmp_path / "frames.csv").write_text(
        "frame,x_um,y_um,time_s\n0,0,0,0.5\n1,1,0,0.0\n", encoding="utf-8"
    )
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["frames"]["sha256"] = _digest(tmp_path / "frames.csv")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "frame_table_time_order" in _codes(report)


def test_the_request_order_must_stay_pinned(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    document = yaml.safe_load((tmp_path / "request.yaml").read_text(encoding="utf-8"))
    document["order"] = "raster"
    (tmp_path / "request.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["request"]["sha256"] = _digest(tmp_path / "request.yaml")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "request_order_not_pinned" in _codes(report)


def test_an_unknown_request_key_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    document = yaml.safe_load((tmp_path / "request.yaml").read_text(encoding="utf-8"))
    document["anisotropy"] = {}
    (tmp_path / "request.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["request"]["sha256"] = _digest(tmp_path / "request.yaml")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "request_key_unknown" in _codes(report)


def test_a_movie_that_is_not_t_yx_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    tifffile.imwrite(
        tmp_path / "stack.ome.tif",
        np.zeros((2, 4, 5), dtype=np.uint16),
        ome=True,
        metadata={"axes": "CYX"},
    )
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["movie"]["sha256"] = _digest(tmp_path / "stack.ome.tif")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "movie_axes_not_t" in _codes(report)


def test_a_movie_shape_mismatch_is_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    tifffile.imwrite(
        tmp_path / "stack.ome.tif",
        np.zeros((2, 3, 5), dtype=np.uint16),
        ome=True,
        metadata={"axes": "TYX"},
    )
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["outputs"]["movie"]["sha256"] = _digest(tmp_path / "stack.ome.tif")
    path.write_text(json.dumps(handoff), encoding="utf-8")
    report = check_handoff.check_handoff(path)
    assert "movie_shape_mismatch" in _codes(report)


def test_a_schema_mismatch_and_missing_provenance_are_reported(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["schema"] = "other"
    path.write_text(json.dumps(handoff), encoding="utf-8")
    (tmp_path / "provenance.json").unlink()
    report = check_handoff.check_handoff(path)
    assert {"schema_mismatch", "provenance_missing"} <= _codes(report)


def test_missing_writer_checks_are_a_warning_not_a_blocker(tmp_path: Path) -> None:
    path = _bundle(tmp_path, checks=[])
    report = check_handoff.check_handoff(path)
    findings = {finding["code"]: finding["severity"] for finding in report["findings"]}
    assert findings["writer_check_missing"] == "warning"
    assert report["accepted"] is True


def test_an_unreadable_handoff_is_refused(tmp_path: Path) -> None:
    with pytest.raises(HandoffError, match="missing file"):
        check_handoff.check_handoff(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(HandoffError, match="unreadable JSON"):
        check_handoff.check_handoff(bad)


def test_cli_reports_and_writes(tmp_path: Path) -> None:
    path = _bundle(tmp_path)
    out = tmp_path / "report.json"
    assert check_handoff.main(["--handoff", str(path), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["accepted"] is True

    handoff = json.loads(path.read_text(encoding="utf-8"))
    handoff["schema"] = "other"
    path.write_text(json.dumps(handoff), encoding="utf-8")
    assert check_handoff.main(["--handoff", str(path)]) == 1
    assert check_handoff.main(["--handoff", str(tmp_path / "absent.json")]) == 2
