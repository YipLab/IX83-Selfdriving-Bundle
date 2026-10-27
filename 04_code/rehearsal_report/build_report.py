"""Assemble one rehearsal report from a declared stage chain (skill close-out).

The rehearsal skill asks for one report that names every stage's actual outcome,
with its artifacts and digests, and that keeps partial, refused and not-applied
stages visible instead of forcing a pass/fail summary. This module builds that
report from a declaration: each stage lists either artifacts with their declared
digests, or a reason it was not applied.

Three rules make the result trustworthy rather than decorative:

* A stage is `verified` only when every declared artifact exists and matches its
  digest. A missing or changed artifact is blocking, because the report would
  otherwise link a file that is not the one the claim was made about.
* A directory artifact (a Zarr store, for instance) cannot be digested as one
  file; it is recorded as `present-not-digested` and never counts as verified.
* A `not-applied` stage must carry a reason. The report counts those stages
  separately, so a reader cannot mistake a modality that never ran for one that
  passed.

The tool reads files and hashes; it does not execute any stage, and it does not
decide whether a stage's method was right.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DECLARATION_SCHEMA = "ix71.rehearsal-declaration.v1"
REPORT_SCHEMA = "ix71.rehearsal-report.v1"

STAGE_ORDER = (
    "acquisition",
    "pose-registration",
    "review-decision",
    "revisit-survey",
    "stitching-mosaic",
    "handoff-storage",
    "reconstruction",
    "anisotropy",
    "spt-tracking",
)

STAGE_STATUSES = ("verified", "partial", "not-applied")
BLOCKING_ARTIFACT = ("missing", "digest_mismatch")


class ReportError(ValueError):
    """A declaration that cannot produce a report."""


def _sha256(path: Path) -> str:
    """Return the file digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any, name: str) -> str:
    """Return a nonempty string."""
    if not isinstance(value, str) or not value.strip():
        raise ReportError(f"{name} must be a nonempty string")
    return value.strip()


@dataclass(frozen=True)
class Artifact:
    """One declared artifact and its expected digest, if it is a file."""

    path: Path
    digest: str | None


def load_declaration(document: Any) -> dict[str, Any]:
    """Validate a rehearsal declaration and return it normalized."""
    if not isinstance(document, dict):
        raise ReportError("a rehearsal declaration must be a JSON object")
    if document.get("schema") != DECLARATION_SCHEMA:
        raise ReportError(
            f"expected schema {DECLARATION_SCHEMA!r}, found {document.get('schema')!r}"
        )
    run_id = _text(document.get("run_id"), "run_id")
    scope = _text(document.get("scope"), "scope")
    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ReportError("stages must be a nonempty list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ReportError(f"stages[{index}] must be an object")
        name = _text(stage.get("stage"), f"stages[{index}].stage")
        if name not in STAGE_ORDER:
            raise ReportError(f"stages[{index}].stage {name!r} is not a known stage")
        if name in seen:
            raise ReportError(f"stage {name!r} is declared twice")
        seen.add(name)
        status = stage.get("status")
        if status not in STAGE_STATUSES:
            raise ReportError(f"stages[{index}].status {status!r} is not declared")
        reason = stage.get("reason")
        if status == "not-applied":
            if not isinstance(reason, str) or not reason.strip():
                raise ReportError(
                    f"the not-applied stage {name!r} needs a reason"
                )
            if stage.get("artifacts"):
                raise ReportError(
                    f"the not-applied stage {name!r} cannot declare artifacts"
                )
        artifacts: list[Artifact] = []
        raw_artifacts = stage.get("artifacts") or []
        if not isinstance(raw_artifacts, list):
            raise ReportError(f"stages[{index}].artifacts must be a list")
        for artifact_index, artifact in enumerate(raw_artifacts):
            if not isinstance(artifact, dict):
                raise ReportError(
                    f"stages[{index}].artifacts[{artifact_index}] must be an object"
                )
            path = Path(_text(artifact.get("path"), "artifact path"))
            digest = artifact.get("sha256")
            if digest is not None:
                _text(digest, "artifact sha256")
                if len(digest) != 64 or any(
                    character not in "0123456789abcdef" for character in digest
                ):
                    raise ReportError("artifact sha256 must be 64 lowercase hex digits")
            artifacts.append(Artifact(path=path, digest=digest))
        normalized.append(
            {
                "stage": name,
                "status": status,
                "reason": reason,
                "artifacts": artifacts,
            }
        )
    return {
        "schema": DECLARATION_SCHEMA,
        "run_id": run_id,
        "scope": scope,
        "attempts": document.get("attempts") or {},
        "calibration_id": document.get("calibration_id"),
        "stages": normalized,
    }


def _evaluate(artifact: Artifact, root: Path) -> dict[str, Any]:
    """Return one artifact's resolved path and verification status."""
    target = artifact.path if artifact.path.is_absolute() else root / artifact.path
    entry: dict[str, Any] = {
        "path": artifact.path.as_posix(),
        "resolved": str(target),
        "declared_sha256": artifact.digest,
    }
    if not target.exists():
        entry.update({"status": "missing", "actual_sha256": None})
        return entry
    if target.is_dir():
        files = sum(1 for item in target.rglob("*") if item.is_file())
        entry.update({"status": "present-not-digested", "files": files})
        return entry
    actual = _sha256(target)
    entry["actual_sha256"] = actual
    if artifact.digest is None:
        entry["status"] = "present-not-digested"
    elif actual == artifact.digest:
        entry["status"] = "verified"
    else:
        entry["status"] = "digest_mismatch"
    return entry


def build_report(declaration: Any, *, root: Path) -> dict[str, Any]:
    """Verify a declaration and return the rehearsal report."""
    normalized = load_declaration(declaration)
    stages: list[dict[str, Any]] = []
    not_applied: list[str] = []
    for stage in normalized["stages"]:
        artifacts = [_evaluate(item, root) for item in stage["artifacts"]]
        problems = [
            entry for entry in artifacts if entry["status"] in BLOCKING_ARTIFACT
        ]
        if stage["status"] == "not-applied":
            not_applied.append(stage["stage"])
            stage_status = "not-applied"
        elif problems:
            stage_status = "partial"
        elif all(entry["status"] == "verified" for entry in artifacts):
            stage_status = "verified"
        elif artifacts:
            stage_status = "partial"
        else:
            stage_status = "partial"
        stages.append(
            {
                "stage": stage["stage"],
                "declared_status": stage["status"],
                "status": stage_status,
                "reason": stage["reason"],
                "artifacts": artifacts,
                "blocking": [entry["path"] for entry in problems],
            }
        )
    blocking = [
        {"stage": stage["stage"], "artifacts": stage["blocking"]}
        for stage in stages
        if stage["blocking"]
    ]
    return {
        "schema": REPORT_SCHEMA,
        "run_id": normalized["run_id"],
        "scope": normalized["scope"],
        "attempts": normalized["attempts"],
        "calibration_id": normalized["calibration_id"],
        "stages": stages,
        "summary": {
            "stages": len(stages),
            "verified": sum(1 for stage in stages if stage["status"] == "verified"),
            "partial": sum(1 for stage in stages if stage["status"] == "partial"),
            "not_applied": len(not_applied),
            "not_applied_stages": not_applied,
            "artifacts": sum(len(stage["artifacts"]) for stage in stages),
            "artifacts_verified": sum(
                1
                for stage in stages
                for entry in stage["artifacts"]
                if entry["status"] == "verified"
            ),
        },
        "blocking": blocking,
        "accepted": not blocking,
    }


def main(argv: list[str] | None = None) -> int:
    """Build one rehearsal report from a declaration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("declaration", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    document = json.loads(arguments.declaration.read_text(encoding="utf-8"))
    report = build_report(document, root=arguments.root)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0 if report["accepted"] else 1


__all__ = [
    "DECLARATION_SCHEMA",
    "REPORT_SCHEMA",
    "STAGE_ORDER",
    "Artifact",
    "ReportError",
    "build_report",
    "load_declaration",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())

