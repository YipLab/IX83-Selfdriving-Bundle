"""Generate a T7 rehearsal report from one run directory, device-free.

T7 asks for `rehearsal_report.json` "regenerated from that one run with 10/10 stages
present and no 'spans several sessions' caveat". Two things were missing from the
bundle: the only producer was hard-coded to one 2026-10-24 session, and nothing
checked the one-session claim - a report could be assembled from several sessions and
still read as a single-session rehearsal.

This tool reads one run root and writes the report the skill's Close-out section
fixes, with two additions: every stage's status is derived from the artifacts that
exist *inside that root*, and the report **refuses the one-session claim** when the
root carries more than one session that ran a plan, naming the sessions it found. It
lives beside `audit.py` because that audit re-verifies the digests this report
declares, so producer and auditor share one directory and one contract.

What counts as a stage artifact
    Only files under the run root. An artifact outside it makes the stage `unknown`,
    because "every artifact in one run directory" is the property T7 tests; a report
    that reached into another session would pass T7 while failing its point.

What counts as a session
    A session log that carries a plan completion marker (`' ended` or `' failed`).
    The app writes one log per session under `logs/<session>/app/<stamp>_<pid>.log`,
    and a preflight session that launches no plan carries the marker count 0. So the
    count of logs with a marker is the count of sessions that actually ran something,
    which is the thing T7 means. Sessions without a marker are reported as idle, not
    as a second session.

Status vocabulary (the skill's Close-out set)
    completed    artifact inside the root and a figure was read from it
    unknown      artifact inside the root but it carries no figure this tool can read,
                 or a reader failed, or the artifact is outside the root
    not_applied  no artifact, with the reason it is missing
    failed       the reader raised on the artifact

The stage entry carries the Close-out names (`status`, `artifact`, `measured`,
`criterion`, `verdict`, `notes`) and the mirror fields (`state`, `artifact_check`)
that `audit.py`'s v2 collector already reads. Both are generated from one description;
neither is a second opinion.

    python assemble_report.py --run-root 08_session_logs/<record>/run08 \
        --specimen-id ix71-fixed-sample-20261015 \
        --calibration accepted-hand-eye-crop900.json \
        --profile ix71_asi_pvcam_sapphire.yaml --profile-revision 2026-10-28 \
        --authorization "operator session; bounded 3x3 survey" \
        --attempt t2chain08 --rehearsal "one-session chain attempt"

    python assemble_report.py --check <run-root>/rehearsal_report.json

Exit codes, matching `audit.py` where it applies: 0 written and the one-session claim
stands; 1 written but the one-session claim is refused; 2 nothing written because the
run root is unusable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "03_external" / "redsun-searching-is-imaging"
RTASPT = ROOT / "03_external" / "Realtime-Anisotropy-SPT-Analysis"
SCHEMA = "ix83.rehearsal-report/v3"
REPORT_NAME = "rehearsal_report.json"

#: A session log that ran a plan prints one of these when the plan finishes.
_PLAN_END = re.compile(r"' (ended|failed)")


def _sha256(path: Path) -> str:
    """Return the SHA-256 of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    """Return a deterministic digest over a directory's sorted relative paths."""
    digest = hashlib.sha256()
    for item in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = item.relative_to(root).as_posix()
        digest.update(f"{relative}\0{item.stat().st_size}\0{_sha256(item)}\n".encode())
    return digest.hexdigest()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    """Describe one artifact and whether it sits inside the run root."""
    if path.is_dir():
        described = {
            "path": str(path),
            "kind": "directory",
            "files": sum(1 for item in path.rglob("*") if item.is_file()),
            "bytes": sum(item.stat().st_size for item in path.rglob("*") if item.is_file()),
            "sha256": _tree_sha256(path),
        }
    else:
        described = {
            "path": str(path),
            "kind": "file",
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    described["inside_run_root"] = str(path.resolve()).startswith(str(root))
    return described


def _first(root: Path, patterns: list[str]) -> Path | None:
    """Return the first existing match, in pattern order then path order."""
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0]
    return None


def _read_json(path: Path) -> Any:
    """Return parsed JSON, or None when the file is not readable JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _iso(seconds: float | None) -> str | None:
    """Render a file mtime as an ISO-8601 UTC string."""
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds")


def _software() -> dict[str, Any]:
    """Record each repository's revision and whether its worktree was clean."""

    def revision(repository: Path) -> dict[str, Any]:
        try:
            commit = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "-C", str(repository), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return {"commit": None, "worktree_clean": None}
        return {"commit": commit or None, "worktree_clean": not status}

    return {
        "bundle": revision(ROOT),
        "app": revision(APP),
        "rtaspt": revision(RTASPT),
    }


# --------------------------------------------------------------------------- readers
# Each reader returns (measured, status, note). `status` is None to mean "the figure
# stands, decide from placement"; "unknown" and "failed" are the reader's own calls.


def _grid(sidecar: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(sidecar)
    if not isinstance(record, dict):
        return None, "unknown", "the sidecar is not readable JSON"
    frames = record.get("frames_written")
    if not frames:
        return None, "unknown", "the sidecar records no frames_written"
    outcome = record.get("exit_status")
    measured = f"{frames} frames written, exit_status {outcome!r}"
    if outcome != "success":
        # A capture whose own record says it failed has not completed the stage,
        # however many frames it wrote before it stopped.
        return measured, "failed", f"the sidecar records exit_status {outcome!r}"
    return measured, None, None


def _illumination(sidecar: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(sidecar)
    if not isinstance(record, dict):
        return None, "unknown", "the sidecar is not readable JSON"
    exposure = record.get("camera_exposure_ms")
    if exposure is None:
        return None, "unknown", "the sidecar records no camera exposure"
    # As shipped, the snap sidecar carries the exposure but not the illumination device
    # or its setpoint; those live in the run start document. When a sidecar does carry
    # them the stage is established; otherwise report the exposure and say what is
    # missing rather than scoring the stage on half of its criterion.
    setpoint = record.get("illumination_intensity_mw")
    device = record.get("illumination_device")
    if setpoint is None or not device:
        return (
            f"{exposure} ms exposure recorded per frame",
            "unknown",
            "the sidecar carries the exposure but not the illumination device or "
            "setpoint, so 'exposure and setpoint recorded per frame' is not established "
            "by this artifact",
        )
    return (
        f"{exposure} ms exposure at {setpoint} mW on {device}",
        None,
        None,
    )


def _registration(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the registration record is not readable JSON"
    passed = record.get("passed_pair_count")
    if passed is None:
        return None, "unknown", "the registration record has no passed_pair_count"
    outcome = record.get("status")
    measured = (
        f"{passed} of {record.get('pair_count')} pairs accepted, "
        f"status {outcome!r}, backend {record.get('registration_backend')}"
    )
    if outcome == "complete":
        return measured, None, None
    if not passed:
        return measured, "failed", f"the registration accepted no pair (status {outcome!r})"
    # A partial graph has measured pairs but not the connected one the checkpoint
    # requires, so the stage is not established either way.
    return measured, "unknown", f"the registration graph is {outcome!r}, not 'complete'"


def _decision(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the decision is not readable JSON"
    accepted = record.get("accepted_target_ids") or []
    if not accepted:
        return None, "unknown", "the decision accepted no target"
    return (
        f"{len(accepted)} accepted target(s), source {record.get('decision_source')!r}",
        None,
        None,
    )


def _revisit(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the revisit result is not readable JSON"
    selected = record.get("selected_targets") or record.get("targets") or []
    if not selected:
        return None, "unknown", "the revisit result names no revisited target"
    return f"{len(selected)} target(s) revisited, status {record.get('status')!r}", None, None


def _compose(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the compose report is not readable JSON"
    canvas = (record.get("canvas") or {}).get("shape_yx")
    if not canvas:
        return None, "unknown", "the compose report has no canvas shape"
    joins = (record.get("registration") or {}).get("measured_join_count")
    return f"canvas {canvas}, {joins} joins measured", None, None


def _handoff(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the manifest is not readable JSON"
    entries = record.get("artifacts") or record.get("files") or []
    digested = [item for item in entries if isinstance(item, dict) and item.get("sha256")]
    if not digested:
        return None, "unknown", "the manifest declares no digest for any artifact"
    return f"{len(digested)} artifact digest(s) declared", None, None


def _products(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the dataset record is not readable JSON"
    frames = record.get("frame_count") or record.get("frames")
    if not frames:
        return None, "unknown", "the dataset record names no frame count"
    return f"{frames} frames processed", None, None


def _anisotropy(path: Path) -> tuple[str | None, str | None, str | None]:
    record = _read_json(path)
    if not isinstance(record, dict):
        return None, "unknown", "the processing summary is not readable JSON"
    applied = record.get("anisotropy_computed")
    if applied is None:
        return None, "unknown", "the processing summary records no anisotropy outcome"
    return f"anisotropy_computed={applied!r}", None, None


def _tracks(path: Path) -> tuple[str | None, str | None, str | None]:
    rows = sum(1 for _ in path.open(encoding="utf-8", errors="replace")) - 1
    if rows < 1:
        return None, "unknown", "the track table has no data rows"
    return f"{rows} track row(s)", None, None


def _stages(attempt: str) -> list[dict[str, Any]]:
    """Return the ten stages of the stationary-sample chain, in artifact order."""
    return [
        {
            "number": 1,
            "stage": "acquisition (grid)",
            "patterns": ["**/*.positions.json"],
            "criterion": (
                "every planned tile captured, every frame paired with a stage readback"
            ),
            "reader": _grid,
            "reason": "no snap positions sidecar under the run root",
        },
        {
            "number": 2,
            "stage": "acquisition (illumination)",
            "patterns": ["**/*.positions.json"],
            "criterion": "exposure and setpoint recorded per frame",
            "reader": _illumination,
            "reason": "no snap sidecar, so no per-frame illumination record",
        },
        {
            "number": 3,
            "stage": "pose-registration",
            "patterns": ["**/registration.json"],
            "criterion": (
                "every planned neighbour pair measured, residual inside the mode's gate"
            ),
            "reader": _registration,
            "reason": "no registration record under the run root",
        },
        {
            "number": 4,
            "stage": "review-decision",
            "patterns": ["**/decision*.json", "**/*decision*.json"],
            "criterion": (
                "checkpoint loads, page lists every tile, decision names a target"
            ),
            "reader": _decision,
            "reason": "no decision document under the run root",
        },
        {
            "number": 5,
            "stage": "revisit/survey",
            "patterns": ["**/result*.json", "**/revisit*/**/*.json"],
            "criterion": "every decided target inside 2 um, anchor back within 0.5 um",
            "reader": _revisit,
            "reason": "no revisit result under the run root",
        },
        {
            "number": 6,
            "stage": "stitching-mosaic",
            "patterns": ["**/compose_report.json"],
            "criterion": "the join geometry states its own residual and coverage",
            "reader": _compose,
            "reason": "no compose report under the run root",
        },
        {
            "number": 7,
            "stage": "handoff-storage",
            "patterns": ["**/manifest.json", "**/*manifest*.json"],
            "criterion": (
                "every stage artifact present with a digest, calibration and attempt "
                "ids named"
            ),
            "reader": _handoff,
            "reason": (
                "no digest manifest under the run root; the app writes per-run "
                "documents, not a rehearsal manifest"
            ),
        },
        {
            "number": 8,
            "stage": "reconstruction",
            "patterns": ["**/dataset_record.json"],
            "criterion": (
                "the product is written from this run and its coverage identity matches"
            ),
            "reader": _products,
            "reason": "no RTASPT dataset record under the run root",
        },
        {
            "number": 9,
            "stage": "anisotropy",
            "patterns": ["**/processing_summary.json"],
            "criterion": (
                "an applied correction whose id and camera mode match, or an explicit "
                "not-applied with its reason"
            ),
            "reader": _anisotropy,
            "reason": "no processing summary carrying the anisotropy outcome",
        },
        {
            "number": 10,
            "stage": "SPT-tracking",
            "patterns": ["**/tracks.csv"],
            "criterion": (
                "table written with the declared schema; a static field declares "
                "no_motion rather than inferring motion"
            ),
            "reader": _tracks,
            "reason": "no track table under the run root",
        },
    ]


# ------------------------------------------------------------------- session evidence


def session_evidence(root: Path) -> dict[str, Any]:
    """Return the sessions the run root carries, split into working and idle.

    A session log that ran a plan prints a completion marker; the app writes one log
    per session, so a log with a marker is a session that did something. A preflight
    session that launched no plan has none and is reported as idle rather than as a
    second session.
    """
    working: list[str] = []
    idle: list[str] = []
    for log in sorted(root.glob("**/logs/**/app/*.log")):
        text = ""
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        session = f"{log.parent.parent.name}/{log.stem}"
        if _PLAN_END.search(text):
            working.append(session)
        else:
            idle.append(session)
    return {"working": working, "idle": idle}


def one_session_claim(evidence: dict[str, Any]) -> dict[str, Any]:
    """Decide whether the artifacts can be claimed as one session, and say why."""
    working = evidence["working"]
    if len(working) == 1:
        return {
            "claimed": True,
            "established": True,
            "session_ids": working,
            "reason": f"one session ran a plan: {working[0]}",
        }
    if len(working) > 1:
        return {
            "claimed": False,
            "established": False,
            "session_ids": working,
            "reason": (
                f"the run root carries {len(working)} sessions that ran a plan, so a "
                "one-session claim would be false: " + ", ".join(working)
            ),
        }
    return {
        "claimed": False,
        "established": False,
        "session_ids": [],
        "reason": (
            "no session log under the run root carries a plan completion marker, so "
            "one session cannot be established from these artifacts"
            + (f"; {len(evidence['idle'])} idle log(s) are present" if evidence["idle"] else "")
        ),
    }


# ------------------------------------------------------------------------- assembly


def assemble(
    run_root: Path,
    *,
    rehearsal: str,
    specimen_id: str,
    calibration_id: str,
    profile: str,
    profile_revision: str,
    authorization: str,
    attempt: str,
    resolved_backends: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the report for one run root without asserting any stage."""
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"run root does not exist: {root}")
    stages: list[dict[str, Any]] = []
    not_covered: list[str] = []
    for definition in _stages(attempt):
        found = _first(root, definition["patterns"])
        label = definition["stage"]
        entry: dict[str, Any] = {
            "number": definition["number"],
            "stage": label,
            "attempt_id": f"{attempt}-{definition['number']:02d}",
            "criterion": definition["criterion"],
        }
        if found is None:
            entry.update(
                {
                    "status": "not_applied",
                    "state": "not_applied",
                    "artifact": None,
                    "artifact_check": {"found": [], "missing": True},
                    "measured": None,
                    "verdict": "not_applied",
                    "notes": definition["reason"],
                }
            )
            not_covered.append(f"stage {definition['number']} ({label}): {definition['reason']}")
            stages.append(entry)
            continue
        described = _artifact(found, root)
        measured: str | None = None
        status: str | None = None
        note: str | None = None
        if found.is_file():
            try:
                measured, status, note = definition["reader"](found)
            except (OSError, ValueError) as error:
                status = "failed"
                note = f"the reader raised on the artifact: {error}"
        else:
            status = "unknown"
            note = "the matched artifact is a directory this reader cannot open"
        if not described["inside_run_root"]:
            status = "unknown"
            note = (
                "the artifact is outside the run root, so this run does not carry it; "
                "T7 wants every artifact in one run directory"
            )
        elif status is None and measured is None:
            status = "unknown"
            note = "the artifact carries no figure this tool can read"
        entry.update(
            {
                "status": status or "completed",
                "state": status or "completed",
                "artifact": described,
                "artifact_check": {"found": [described]},
                "measured": measured,
                "verdict": status or "completed",
                "notes": note,
            }
        )
        stages.append(entry)
    evidence = session_evidence(root)
    claim = one_session_claim(evidence)
    mtimes = [
        item.stat().st_mtime
        for item in root.rglob("*")
        if item.is_file() and item.name != REPORT_NAME
    ]
    counts: dict[str, int] = {}
    for stage in stages:
        counts[stage["status"]] = counts.get(stage["status"], 0) + 1
    return {
        "schema": SCHEMA,
        "rehearsal": rehearsal,
        "run_root": str(root),
        "specimen_id": specimen_id,
        "calibration_id": calibration_id,
        "profile": profile,
        "profile_revision": profile_revision,
        "resolved_backends": resolved_backends or {"note": "not resolved by this tool"},
        "authorization": authorization,
        "started_at": _iso(min(mtimes, default=None)),
        "finished_at": _iso(max(mtimes, default=None)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "software": _software(),
        "one_session": {
            **claim,
            "session_logs_working": evidence["working"],
            "session_logs_idle": evidence["idle"],
        },
        "stage_summary": {"total": len(stages), "by_status": counts},
        "stages": stages,
        "not_covered": not_covered,
        "honesty": (
            "Every stage status is derived from the artifacts under run_root and "
            "nothing else. A stage is 'completed' only when its artifact is inside the "
            "run root and a figure was read from it; a missing artifact is "
            "'not_applied' with its reason, never 'completed'; an artifact outside the "
            "root is 'unknown'. The one-session claim is refused when more than one "
            "session log carries a plan completion marker."
            if claim["established"]
            else (
                "Every stage status is derived from the artifacts under run_root and "
                "nothing else. A stage is 'completed' only when its artifact is inside "
                "the run root and a figure was read from it; a missing artifact is "
                "'not_applied' with its reason, never 'completed'; an artifact outside "
                "the root is 'unknown'. The one-session claim is refused here, so a "
                "stage's artifact may come from any of the sessions named in "
                "one_session.session_ids: this report describes the root, not one "
                "session."
            )
        ),
    }


def verify(report_path: Path) -> int:
    """Re-compute every digest the report declares; return the number of problems."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    problems = 0
    checked = 0
    for stage in report.get("stages", []):
        # `artifact` and `artifact_check.found` hold the same description, so collect
        # by path: one declaration of one file is one thing to re-hash.
        declared: dict[str, dict[str, Any]] = {}
        artifact = stage.get("artifact")
        if isinstance(artifact, dict) and artifact.get("path"):
            declared[str(artifact["path"])] = artifact
        for item in (stage.get("artifact_check") or {}).get("found", []):
            if isinstance(item, dict) and item.get("path"):
                declared.setdefault(str(item["path"]), item)
        for item in declared.values():
            path = Path(item["path"])
            checked += 1
            if not path.exists():
                print(f"MISSING  stage {stage['number']}: {path}")
                problems += 1
                continue
            actual = _tree_sha256(path) if path.is_dir() else _sha256(path)
            if actual != item.get("sha256"):
                print(f"MISMATCH stage {stage['number']}: {path}")
                problems += 1
    print(f"{checked} declared artifact(s), {problems} problem(s)")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Write the report for one run root, or re-verify an existing one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rehearsal", default="one-session chain")
    parser.add_argument("--specimen-id", default="unspecified")
    parser.add_argument("--calibration", default="unspecified")
    parser.add_argument("--profile", default="unspecified")
    parser.add_argument("--profile-revision", default="unspecified")
    parser.add_argument("--authorization", default="unspecified")
    parser.add_argument("--attempt", default="t7")
    parser.add_argument("--check", type=Path, help="re-verify an existing report")
    args = parser.parse_args(argv)
    if args.check is not None:
        return 1 if verify(args.check) else 0
    if args.run_root is None:
        parser.error("--run-root is required unless --check is used")
    try:
        report = assemble(
            args.run_root,
            rehearsal=args.rehearsal,
            specimen_id=args.specimen_id,
            calibration_id=args.calibration,
            profile=args.profile,
            profile_revision=args.profile_revision,
            authorization=args.authorization,
            attempt=args.attempt,
        )
    except FileNotFoundError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    output = args.output or (Path(args.run_root) / REPORT_NAME)
    output.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    counts = report["stage_summary"]["by_status"]
    claim = report["one_session"]
    print(
        f"{output}: {counts.get('completed', 0)} of {report['stage_summary']['total']} "
        f"stages completed, statuses {counts}"
    )
    print(f"one-session claim: {'established' if claim['established'] else 'REFUSED'}")
    print(f"  {claim['reason']}")
    for stage in report["stages"]:
        print(
            f"  {stage['number']:>2} {stage['stage']:<24} {stage['status']:<12} "
            f"{stage['measured'] or ''}"
        )
    return 0 if claim["established"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
