"""Hardware-free tests for the declared-digest audit (Track D / S1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import declared_digests


def _file(root: Path, name: str, content: str = "evidence\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(root: Path, rows: list[str], *, heading: str = "Artifacts") -> Path:
    body = [f"# Record", "", f"## {heading}", "", "| File | SHA-256 |", "| --- | --- |"]
    body.extend(rows)
    return _file(root, "record/README.md", "\n".join(body) + "\n")


def _report(root: Path, record: Path) -> dict:
    return declared_digests.audit([record], root=root)


def test_a_matching_digest_is_verified(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    record = _record(
        tmp_path, [f"| [`tool.py`](../tool.py) | `{_digest(target)}` |"]
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["counts"] == {"verified": 1}
    assert report["findings"][0]["line"] == 7


def test_a_changed_file_is_a_blocking_mismatch(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    digest = _digest(target)
    target.write_text("changed\n", encoding="utf-8")
    record = _record(tmp_path, [f"| [`tool.py`](../tool.py) | `{digest}` |"])

    report = _report(tmp_path, record)

    assert report["ok"] is False
    assert report["counts"] == {"digest_mismatch": 1}
    finding = report["findings"][0]
    assert finding["status"] == "digest_mismatch"
    assert finding["actual_sha256"] == _digest(target)


def test_a_missing_file_is_blocking(tmp_path: Path) -> None:
    record = _record(
        tmp_path, [f"| [`gone.py`](../gone.py) | `{'0' * 64}` |"]
    )

    report = _report(tmp_path, record)

    assert report["ok"] is False
    assert report["counts"] == {"missing": 1}


def test_a_mismatch_under_a_commit_heading_is_historical(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    digest = _digest(target)
    target.write_text("changed\n", encoding="utf-8")
    record = _record(
        tmp_path,
        [f"| [`tool.py`](../tool.py) | `{digest}` |"],
        heading="Files at commit 08248b1",
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["counts"] == {"historical_mismatch": 1}


def test_a_mismatch_under_a_snapshot_heading_is_historical(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    digest = _digest(target)
    target.write_text("changed\n", encoding="utf-8")
    record = _record(
        tmp_path,
        [f"| [`tool.py`](../tool.py) | `{digest}` |"],
        heading="Source audit (snapshot, 2026-10-27)",
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["counts"] == {"historical_mismatch": 1}

def test_an_http_link_is_skipped(tmp_path: Path) -> None:
    record = _record(
        tmp_path, [f"| [`upstream`](https://example.invalid/x) | `{'a' * 64}` |"]
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["counts"] == {"external_skipped": 1}


def test_a_row_annotation_after_the_link_is_ignored(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    record = _record(
        tmp_path, [f"| [`tool.py`](../tool.py) (new) | `{_digest(target)}` |"]
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["counts"] == {"verified": 1}

def test_a_row_without_a_digest_is_ignored(tmp_path: Path) -> None:
    record = _record(tmp_path, ["| [`tool.py`](../tool.py) | (not declared) |"])

    assert _report(tmp_path, record)["declared"] == 0


def test_an_anchor_link_resolves_to_its_file(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    record = _record(
        tmp_path, [f"| [`tool.py`](../tool.py#L2) | `{_digest(target)}` |"]
    )

    report = _report(tmp_path, record)

    assert report["ok"] is True
    assert report["findings"][0]["status"] == "verified"


def test_the_command_line_reports_and_sets_the_exit_code(tmp_path: Path) -> None:
    target = _file(tmp_path, "tool.py")
    good = _record(tmp_path, [f"| [`tool.py`](../tool.py) | `{_digest(target)}` |"])
    output = tmp_path / "audit.json"

    assert declared_digests.main([str(good), "--root", str(tmp_path), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is True

    target.write_text("changed\n", encoding="utf-8")
    assert declared_digests.main([str(good), "--root", str(tmp_path), "--output", str(output)]) == 1



