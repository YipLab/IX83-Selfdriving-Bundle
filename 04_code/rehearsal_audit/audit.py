"""Re-verify a rehearsal report or run manifest against the files on disk.

Track D's evidence is spread across a report per stage and a digest manifest, and
some of it was written days before it was last read. This tool takes a saved
rehearsal report or run manifest, collects every artifact it declares, and
recomputes presence, byte count and digest today. A stage whose state claims
verification while one of its declared artifacts is gone is reported as a broken
claim, not as a pass.

It never edits the report or the manifest, and it creates no new evidence: it
answers "does the record still describe files that exist".

    python audit.py --source <report-or-manifest.json> [--out audit.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ix71.rehearsal-audit.1"

#: States that assert a verified result; a missing declared artifact breaks them.
VERIFIED_STATES = frozenset(
    {
        "implemented-and-verified-on-hardware",
        "verified",
        "pass",
    }
)


class AuditError(ValueError):
    """The source is not an auditable rehearsal record."""


def _sha256(path: Path) -> str:
    """Return the SHA-256 of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    """Read one JSON source, refusing by name when unreadable."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise AuditError(f"missing source: {path}") from error
    except json.JSONDecodeError as error:
        raise AuditError(f"unreadable JSON in {path}: {error}") from error


def _resolve(path_text: str) -> Path:
    """Resolve a declared path against the bundle root when it is relative."""
    path = Path(path_text)
    return path if path.is_absolute() else (ROOT / path)


def _artifact(
    path_text: str, *, digest: str | None = None, size: int | None = None
) -> dict[str, Any]:
    """Return one declared artifact."""
    return {"path": path_text, "sha256": digest, "bytes": size}


def _looks_like_path(text: str) -> bool:
    """Return whether a record string names a file rather than a note."""
    if any(character.isspace() for character in text):
        return False
    return "/" in text or "\\" in text or "." in text


def collect(source: Path) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Return the source format, its declared artifacts and any skipped notes."""
    document = _load(source)
    if not isinstance(document, dict):
        raise AuditError("source must be a JSON object")
    stages = document.get("stages")
    artifacts: list[dict[str, Any]] = []
    skipped: list[str] = []

    if (
        isinstance(stages, list)
        and stages
        and isinstance(stages[0], dict)
        and "artifacts" in stages[0]
    ):
        for stage in stages:
            label = f"{stage.get('number')}-{stage.get('stage')}"
            for item in stage.get("artifacts") or []:
                artifacts.append(
                    {
                        "stage": label,
                        "state": stage.get("state"),
                        **_artifact(
                            str(item.get("path")),
                            digest=item.get("sha256"),
                            size=item.get("bytes"),
                        ),
                    }
                )
        return "run-manifest", artifacts, skipped

    if (
        isinstance(stages, list)
        and stages
        and isinstance(stages[0], dict)
        and "artifact_check" in stages[0]
    ):
        for stage in stages:
            label = f"{stage.get('number')}-{stage.get('stage')}"
            check = stage.get("artifact_check") or {}
            for item in check.get("found") or []:
                if not isinstance(item, dict) or not item.get("path"):
                    # A prose note is not a file; keep it, do not call it missing.
                    skipped.append(f"{label}: {item}")
                    continue
                artifacts.append(
                    {
                        "stage": label,
                        "state": stage.get("state"),
                        **_artifact(
                            str(item.get("path")),
                            digest=item.get("sha256"),
                            size=item.get("bytes"),
                        ),
                    }
                )
            record = stage.get("record")
            if isinstance(record, str):
                if _looks_like_path(record):
                    artifacts.append(
                        {
                            "stage": label,
                            "state": stage.get("state"),
                            "kind": "record",
                            **_artifact(record),
                        }
                    )
                else:
                    skipped.append(f"{label}: record is a note: {record}")
        return "rehearsal-report-v2", artifacts, skipped

    if isinstance(stages, dict) and stages:
        manifest_path = document.get("artifact_manifest")
        if isinstance(manifest_path, str):
            manifest = _load(_resolve(manifest_path))
            for item in manifest.get("artifacts") or []:
                path_text = item.get("consolidated_path") or item.get("original_path")
                artifacts.append(
                    {
                        "stage": item.get("stage"),
                        "state": None,
                        **_artifact(
                            str(path_text),
                            digest=item.get("sha256"),
                            size=item.get("bytes"),
                        ),
                    }
                )
        else:
            for label, stage in stages.items():
                for path_text in stage.get("artifact_source_paths") or []:
                    artifacts.append(
                        {
                            "stage": label,
                            "state": stage.get("status"),
                            **_artifact(str(path_text)),
                        }
                    )
        return "rehearsal-report-v1", artifacts, skipped

    raise AuditError(
        "unrecognised rehearsal record: expected stages with artifacts, "
        "artifact_check, or artifact_source_paths"
    )


def audit(source: Path) -> dict[str, Any]:
    """Audit one rehearsal record and return the report."""
    source = Path(source)
    fmt, declared, skipped = collect(source)
    rows = []
    for item in declared:
        path = _resolve(item["path"])
        row = {
            "stage": item.get("stage"),
            "state": item.get("state"),
            "kind": item.get("kind", "artifact"),
            "path": item["path"],
            "declared_sha256": item.get("sha256"),
            "declared_bytes": item.get("bytes"),
            "present": path.is_file(),
            "actual_bytes": None,
            "actual_sha256": None,
            "status": "missing",
        }
        if row["present"]:
            row["actual_bytes"] = path.stat().st_size
            if item.get("sha256"):
                row["actual_sha256"] = _sha256(path)
            if item.get("bytes") is not None and row["actual_bytes"] != item["bytes"]:
                row["status"] = "byte_mismatch"
            elif item.get("sha256") and row["actual_sha256"] != item["sha256"]:
                row["status"] = "digest_mismatch"
            else:
                row["status"] = "ok"
        rows.append(row)

    findings = []
    for row in rows:
        if row["status"] == "missing":
            findings.append(
                {
                    "code": "artifact_missing",
                    "severity": "blocking",
                    "stage": row["stage"],
                    "detail": f"declared file is gone: {row['path']}",
                }
            )
            if row["state"] in VERIFIED_STATES:
                findings.append(
                    {
                        "code": "stage_claim_broken",
                        "severity": "blocking",
                        "stage": row["stage"],
                        "detail": (
                            f"state {row['state']!r} claims verification while "
                            "an artifact is missing"
                        ),
                    }
                )
        elif row["status"] == "digest_mismatch":
            findings.append(
                {
                    "code": "artifact_digest_mismatch",
                    "severity": "blocking",
                    "stage": row["stage"],
                    "detail": f"digest differs from the record: {row['path']}",
                }
            )
        elif row["status"] == "byte_mismatch":
            findings.append(
                {
                    "code": "artifact_byte_mismatch",
                    "severity": "warning",
                    "stage": row["stage"],
                    "detail": f"size differs from the record: {row['path']}",
                }
            )

    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(source),
        "format": fmt,
        "artifact_count": len(rows),
        "skipped_entries": skipped,
        "by_status": dict(sorted(by_status.items())),
        "artifacts": rows,
        "findings": findings,
        "blocking": [
            item["code"] for item in findings if item["severity"] == "blocking"
        ],
        "accepted": False,
        "notes": [
            "the record is not edited; a missing or changed file is reported "
            "against it",
            "verification of a declared digest means the bytes still match the record, "
            "not that the record itself was correct when written",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Audit one or more rehearsal records and write the combined report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    reports = []
    try:
        for source in args.source:
            reports.append(audit(source))
    except AuditError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    combined = {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": reports,
        "summary": {
            "sources": len(reports),
            "artifacts": sum(report["artifact_count"] for report in reports),
            "missing": sum(report["by_status"].get("missing", 0) for report in reports),
            "digest_mismatch": sum(
                report["by_status"].get("digest_mismatch", 0) for report in reports
            ),
            "byte_mismatch": sum(
                report["by_status"].get("byte_mismatch", 0) for report in reports
            ),
            "ok": sum(report["by_status"].get("ok", 0) for report in reports),
        },
        "accepted": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(combined, indent=1) + "\n", encoding="utf-8")
    for report in reports:
        label = Path(report["source"]).parent.name
        print(
            f"{label}: {report['format']}, {report['artifact_count']} artifacts, "
            f"{report['by_status']}"
        )
        for finding in report["findings"]:
            print(
                f"  {finding['severity']:<8} {finding['code']} "
                f"[{finding['stage']}]: {finding['detail']}"
            )
    return 0 if not any(report["blocking"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
