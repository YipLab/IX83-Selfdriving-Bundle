"""Build one run-evidence record for a recorded Redsun acquisition run.

Q01 of the 2026-10-27 increment asks for a run manifest that links source hashes,
software revisions, camera/ROI/binning, objective, illumination mode, stage
conversion, coordinate convention, calibration IDs, specimen/field IDs and output
products. The bundle already had two manifests - a rehearsal digest manifest and
a release-gate manifest - but neither records that scientific/technical identity,
and neither re-check the sources it names.

This tool reads a finished run directory and writes one JSON record in which
every field carries its own value, source path and status:

``declared``
    A named source states the value.
``derived``
    The value is computed from named sources (a digest, a frame count, a match).
``unresolved``
    No source in the run supplies it. The record says so instead of guessing, and
    the field is listed under ``unresolved``.
``mismatch``
    Two sources disagree, or a source is malformed. The field is listed under
    ``findings`` with a severity.

It is read-only with respect to the run: it never edits, moves or re-registers
the recorded files, opens no device and imports no acquisition host. It hashes
small JSON/text sources only; a Zarr store is recorded by shape and named as not
digested, because a directory digest of an immutable store is a separate tool.

    python build_run_evidence.py --run 08_session_logs/<session>/<run> \\
        --profile <profile.yaml> --out 04_code/run_evidence/records/<name>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ix71.run-evidence.v1"
GENERATOR = "04_code/run_evidence/build_run_evidence.py"

#: Fields whose absence makes a record unusable for an endpoint claim.
BLOCKING_FINDINGS = frozenset(
    {
        "run_outcome_failed",
        "frame_count_mismatch",
        "frame_id_not_monotonic",
        "missing_run_manifest",
        "profile_unreadable",
    }
)

#: Files the recorder writes beside each Zarr store; each is small and hashed.
SIDECAR_SUFFIXES = (".positions.json", ".timing.json")


class EvidenceError(RuntimeError):
    """A source the record requires is missing or unreadable."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of one file, streaming it in 1 MiB blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    """Return a bundle-relative path when possible, otherwise the absolute path."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def git_revision(path: Path) -> dict[str, Any]:
    """Return the revision and dirty state of one checkout, never raising."""

    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return result.stdout.strip()

    revision = run("rev-parse", "HEAD")
    if revision is None:
        return {"revision": None, "status": "unavailable", "dirty": None}
    porcelain = run("status", "--porcelain")
    return {
        "revision": revision,
        "dirty": bool(porcelain),
        "dirty_entries": len(porcelain.splitlines()) if porcelain else 0,
    }


def field(value: Any, source: Path | str | None, status: str) -> dict[str, Any]:
    """Return one value/source/status cell."""
    return {
        "value": value,
        "source": None
        if source is None
        else (source if isinstance(source, str) else relative(source)),
        "status": status,
    }


def unresolved(reason: str, *, attempted: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Return an unresolved cell that names what was checked."""
    return {
        "value": None,
        "source": None,
        "status": "unresolved",
        "reason": reason,
        "checked": [relative(path) for path in attempted],
    }


def declared_or_unresolved(value: Any, source: Path, run_dir: Path) -> dict[str, Any]:
    """Return a declared cell, or an unresolved one when the source is silent."""
    if value is None:
        return unresolved("no source declares this value", attempted=(run_dir,))
    return field(value, source, "declared")


def load_json(path: Path) -> Any:
    """Load one JSON source, refusing an unreadable file by name."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError(f"missing source: {relative(path)}") from error
    except json.JSONDecodeError as error:
        raise EvidenceError(f"unreadable JSON in {relative(path)}: {error}") from error


def find_one(directory: Path, pattern: str) -> Path | None:
    """Return the single file matching a pattern, refusing an ambiguous match."""
    matches = sorted(directory.glob(pattern))
    if len(matches) > 1:
        raise EvidenceError(
            f"ambiguous {pattern} under {relative(directory)}: "
            + ", ".join(relative(match) for match in matches)
        )
    return matches[0] if matches else None


def select_run_files(run_dir: Path) -> dict[str, Any]:
    """Locate the report, strip record, per-run manifest and sidecars."""
    if not run_dir.is_dir():
        raise EvidenceError(f"run directory not found: {relative(run_dir)}")
    reports = sorted(run_dir.glob("*-report.json"))
    if len(reports) != 1:
        raise EvidenceError(
            f"expected exactly one *-report.json in {relative(run_dir)}, "
            f"found {len(reports)}"
        )
    report_path = reports[0]
    report = load_json(report_path)
    attempt = str(report.get("confirmation_id") or "")
    if not attempt:
        raise EvidenceError(f"{relative(report_path)} names no confirmation_id")
    strip_path = find_one(run_dir / "strips", f"*-{attempt}-strips.json")
    candidates = [
        path
        for path in run_dir.glob("*")
        if path.is_dir() and path.name not in {"logs", "strips"}
    ]
    if len(candidates) != 1:
        raise EvidenceError(
            f"expected exactly one acquisition sub-directory in {relative(run_dir)}, "
            f"found {len(candidates)}"
        )
    sidecar_root = candidates[0]
    positions = sorted(sidecar_root.rglob("*.positions.json"))
    timing = sorted(sidecar_root.rglob("*.timing.json"))
    run_manifests = sorted(sidecar_root.rglob("run_manifest_*.json"))
    if not positions:
        raise EvidenceError(f"no *.positions.json under {relative(sidecar_root)}")
    return {
        "report_path": report_path,
        "report": report,
        "attempt": attempt,
        "strip_path": strip_path,
        "positions": positions,
        "timing": timing,
        "run_manifest": run_manifests[-1] if run_manifests else None,
    }


def first_present(values: list[Any]) -> Any:
    """Return the first non-None value, so a record prefers its richest source."""
    for value in values:
        if value is not None:
            return value
    return None


def build(
    run_dir: Path, profile_path: Path, calibrations: list[Path]
) -> dict[str, Any]:
    """Assemble one run-evidence record from a recorded run directory."""
    files = select_run_files(run_dir)
    report = files["report"]
    attempt = files["attempt"]
    findings: list[dict[str, Any]] = []

    profile = load_profile(profile_path)
    position_docs = [load_json(path) for path in files["positions"]]
    timing_docs = (
        [load_json(path) for path in files["timing"]] if files["timing"] else []
    )
    strip_doc = load_json(files["strip_path"]) if files["strip_path"] else None
    run_manifest = load_json(files["run_manifest"]) if files["run_manifest"] else None
    if run_manifest is None:
        findings.append(
            {
                "code": "missing_run_manifest",
                "severity": "blocking",
                "detail": "the recorder wrote no run_manifest_*.json beside the stores",
                "source": relative(run_dir),
            }
        )

    camera = camera_section(position_docs, profile, profile_path, files["positions"][0])
    coordinates = coordinate_section(
        position_docs, timing_docs, strip_doc, files["positions"][0]
    )
    stage = stage_section(profile, profile_path)
    geometry = geometry_section(
        report, strip_doc, files["report_path"], files["strip_path"]
    )
    rejected_poses = {
        code: count
        for code, count in coordinates["frame_status_counts"]["value"].items()
        if code != "associated_receipt"
    }
    if rejected_poses:
        findings.append(
            {
                "code": "pose_association_incomplete",
                "severity": "warning",
                "detail": rejected_poses,
                "source": relative(files["strip_path"])
                if files["strip_path"]
                else relative(files["positions"][0]),
            }
        )
    frames = frame_section(report, position_docs, files["positions"])
    findings.extend(frames.pop("findings"))
    outcome = report.get("session_outcome")
    complete_value = first_present(
        [
            run_manifest.get("complete") if run_manifest else None,
            strip_doc.get("complete") if strip_doc else None,
        ]
    )
    interrupted_value = first_present(
        [
            run_manifest.get("interrupted") if run_manifest else None,
            strip_doc.get("interrupted") if strip_doc else None,
        ]
    )
    if outcome != "success":
        findings.append(
            {
                "code": "run_outcome_failed",
                "severity": "blocking",
                "detail": report.get("error") or f"session_outcome is {outcome!r}",
                "source": relative(files["report_path"]),
            }
        )
    if complete_value and outcome != "success":
        findings.append(
            {
                "code": "complete_but_failed",
                "severity": "info",
                "detail": (
                    "the recorder finished writing every strip while the plan reported "
                    "a failed session; complete is not success"
                ),
                "source": relative(files["run_manifest"])
                if run_manifest
                else relative(files["report_path"]),
            }
        )

    calibration = calibration_section(calibrations, camera)
    specimen = {
        "specimen_id": unresolved(
            "no recorded source names the specimen; it is an operator/author fact",
        ),
        "field_id": unresolved(
            "the run names an anchor and a footprint, not a field identifier",
        ),
        "field_anchor_xy_um": geometry["anchor_xy_um"],
        "footprint_xy_um": geometry["footprint_xy_um"],
    }
    illumination = {
        "setpoint_mw": field(
            report.get("setpoint_mw"), files["report_path"], "declared"
        )
        if report.get("setpoint_mw") is not None
        else unresolved("the report declares no setpoint"),
        "mode": unresolved(
            "the run names a setpoint but not an optical mode; the profile's 488 "
            "channel is not evidence that this run emitted through it",
            attempted=(profile_path,),
        ),
        "objective": unresolved(
            "no recorded source names the objective or its magnification",
            attempted=(profile_path,),
        ),
    }
    software = software_section(profile_path)
    products = product_section(files, profile_path)
    route_mismatch = route_findings(report, strip_doc, files)
    findings.extend(route_mismatch)
    if any(item["code"] == "route_encoding_inconsistent" for item in route_mismatch):
        geometry["route_rows"]["status"] = "mismatch"
        geometry["route_rows"]["reason"] = (
            "the report's route entries are not numeric xy pairs; the strip record "
            "supplies the authoritative rows"
        )

    record: dict[str, Any] = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": {
            "run_dir": relative(run_dir),
            "confirmation_id": field(attempt, files["report_path"], "declared"),
            "attempt_id": (
                field(run_manifest.get("attempt_id"), files["run_manifest"], "declared")
                if run_manifest and run_manifest.get("attempt_id")
                else unresolved(
                    "the recorder wrote no attempt_id", attempted=(run_dir,)
                )
            ),
            "created_at": (
                field(run_manifest.get("created_at"), files["run_manifest"], "declared")
                if run_manifest and run_manifest.get("created_at")
                else unresolved(
                    "the recorder wrote no created_at", attempted=(run_dir,)
                )
            ),
            "session_outcome": field(outcome, files["report_path"], "declared"),
            "complete": declared_or_unresolved(
                complete_value,
                files["run_manifest"] if run_manifest else files["report_path"],
                run_dir,
            ),
            "interrupted": declared_or_unresolved(
                interrupted_value,
                files["run_manifest"] if run_manifest else files["report_path"],
                run_dir,
            ),
        },
        "software": software,
        "camera": camera,
        "illumination": illumination,
        "stage": stage,
        "coordinates": coordinates,
        "geometry": geometry,
        "calibration": calibration,
        "specimen": specimen,
        "frames": frames,
        "products": products,
        "findings": findings,
    }
    record["blocking"] = list(
        dict.fromkeys(
            item["code"] for item in findings if item["code"] in BLOCKING_FINDINGS
        )
    )
    record["unresolved"] = walk_field_paths(record)
    record["identity_complete"] = not record["unresolved"]
    record["accepted"] = False
    return record


def load_profile(profile_path: Path) -> dict[str, Any]:
    """Load the instrument profile, refusing an unreadable YAML document."""
    try:
        parsed = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError(f"profile not found: {relative(profile_path)}") from error
    except yaml.YAMLError as error:
        raise EvidenceError(
            f"profile is not YAML: {relative(profile_path)}: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise EvidenceError(f"profile is not a mapping: {relative(profile_path)}")
    return parsed


def profile_service(profile: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one service declaration from the profile."""
    services = profile.get("services") or {}
    value = services.get(key)
    return value if isinstance(value, dict) else {}


def camera_section(
    position_docs: list[dict[str, Any]],
    profile: dict[str, Any],
    profile_path: Path,
    sidecar: Path,
) -> dict[str, Any]:
    """Record the delivered camera mode from the position sidecars and profile."""
    first = position_docs[0]
    adapted = profile_service(profile, "camera1_ioc").get("args") or {}
    return {
        "name": field(first.get("camera_name"), sidecar, "declared"),
        "exposure_ms": field(first.get("camera_exposure_ms"), sidecar, "declared"),
        "binning_xy": field(first.get("camera_binning_xy"), sidecar, "declared"),
        "roi_sensor_pixels": field(
            first.get("camera_roi_sensor_pixels"), sidecar, "declared"
        ),
        "roi_binned_pixels": field(
            first.get("camera_roi_binned_pixels"), sidecar, "declared"
        ),
        "properties": field(first.get("camera_properties"), sidecar, "declared"),
        "adapter": field(adapted.get("adapter"), profile_path, "declared"),
        "device": field(adapted.get("device"), profile_path, "declared"),
        "declared_properties": field(
            adapted.get("properties"), profile_path, "declared"
        ),
        "mode_source": relative(sidecar),
    }


def coordinate_section(
    position_docs: list[dict[str, Any]],
    timing_docs: list[dict[str, Any]],
    strip_doc: dict[str, Any] | None,
    sidecar: Path,
) -> dict[str, Any]:
    """Record the pose basis, clock and timestamp semantics the recorder declared."""
    first = position_docs[0]
    phase_counts: dict[str, int] = {}
    for document in position_docs:
        for frame in document.get("frames") or []:
            phase = str(frame.get("pose_phase") or "unknown")
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
    strip_frames = [
        frame
        for strip in (strip_doc or {}).get("strips") or []
        for frame in strip.get("frame_poses") or []
    ]
    statuses: dict[str, int] = {}
    for frame in strip_frames:
        status = str(frame.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    pose_sources = sorted(
        {
            str(source)
            for strip in (strip_doc or {}).get("strips") or []
            for source in strip.get("pose_sources") or []
        }
        | {
            str(frame.get("pose_source"))
            for frame in strip_frames
            if frame.get("pose_source") is not None
        }
    )
    timing_first = timing_docs[0] if timing_docs else None
    return {
        "basis": field(first.get("stage_coordinate_basis"), sidecar, "declared"),
        "readback_keys": field(first.get("stage_readback_keys"), sidecar, "declared"),
        "pose_sources": field(pose_sources, sidecar, "derived"),
        "frame_status_counts": field(statuses, sidecar, "derived"),
        "pose_phase_counts": field(phase_counts, sidecar, "derived"),
        "pose_clock": (
            field(timing_first.get("clock"), "timing sidecar", "declared")
            if timing_first
            else unresolved("no timing sidecar was written", attempted=(sidecar,))
        ),
        "timestamp_semantics": (
            field(timing_first.get("timestamp_semantics"), "timing sidecar", "declared")
            if timing_first
            else unresolved("no timing sidecar was written", attempted=(sidecar,))
        ),
        "frame_metadata_semantics": (
            field(
                timing_first.get("frame_metadata_semantics"),
                "timing sidecar",
                "declared",
            )
            if timing_first
            else unresolved("no timing sidecar was written", attempted=(sidecar,))
        ),
        "exposure_associated": {
            "value": False,
            "source": "timing sidecar",
            "status": "derived",
            "reason": (
                "the declared semantics associate a stage readback with service "
                "arrival, not with the exposure interval"
            ),
        },
    }


def stage_section(profile: dict[str, Any], profile_path: Path) -> dict[str, Any]:
    """Record the calibrated stage conversion and motion limits from the profile."""
    args = profile_service(profile, "asi_stage_ioc").get("args") or {}
    return {
        "port": field(args.get("port"), profile_path, "declared"),
        "counts_per_um": field(args.get("counts-per-um"), profile_path, "declared"),
        "speed_mm_s": field(args.get("speed-mm-s"), profile_path, "declared"),
        "ramp_ms": field(args.get("ramp-ms"), profile_path, "declared"),
        "backlash_mm": field(args.get("backlash-mm"), profile_path, "declared"),
        "absolute_takeup_um": field(
            args.get("absolute-takeup-um"), profile_path, "declared"
        ),
        "max_xy_offset_um": field(
            args.get("max-xy-offset-um"), profile_path, "declared"
        ),
        "conversion_note": (
            "counts_per_um is the service conversion; it is not an independently "
            "measured optical scale"
        ),
    }


def geometry_section(
    report: dict[str, Any],
    strip_doc: dict[str, Any] | None,
    report_path: Path,
    strip_path: Path | None,
) -> dict[str, Any]:
    """Record the route, footprint, overlap and anchor-return outcome."""
    rows = None
    if strip_doc and isinstance(strip_doc.get("strips"), list):
        rows = [
            {
                "row": strip.get("row"),
                "start_xy_um": strip.get("start_xy_um"),
                "end_xy_um": strip.get("end_xy_um"),
                "terminal_state": strip.get("terminal_state"),
                "captured_count": strip.get("captured_count"),
            }
            for strip in strip_doc["strips"]
        ]
    anchor = (strip_doc or {}).get("anchor") or {}
    geometric_source = strip_path if strip_doc is not None else report_path
    return {
        "strip_span_um": field(report.get("strip_span_um"), report_path, "declared"),
        "footprint_xy_um": field(
            (strip_doc or {}).get("footprint_xy_um", [report.get("field_um")] * 2),
            geometric_source,
            "declared",
        ),
        "overlap": field(
            first_present([(strip_doc or {}).get("overlap"), report.get("overlap")]),
            geometric_source,
            "declared",
        ),
        "anchor_xy_um": field(report.get("anchor_xy_um"), report_path, "declared"),
        "route_rows": field(
            rows,
            strip_path,
            "declared" if rows else "unresolved",
        ),
        "anchor_return": field(
            {
                "attempted": anchor.get("return_attempted"),
                "final_xy_um": anchor.get("final_xy_um"),
                "error_um": anchor.get("return_error_um"),
            },
            strip_path,
            "declared" if anchor else "unresolved",
        ),
    }


def frame_section(
    report: dict[str, Any], position_docs: list[dict[str, Any]], paths: list[Path]
) -> dict[str, Any]:
    """Reconcile the sidecar frame counts with the store shapes the report names."""
    stores = report.get("stores") or {}
    sidecars = []
    findings: list[dict[str, Any]] = []
    for path, document in zip(paths, position_docs):
        frames = document.get("frames") or []
        frame_ids = [frame.get("frame_id") for frame in frames]
        array_indices = [frame.get("array_index") for frame in frames]
        ordered = all(
            isinstance(left, int) and isinstance(right, int) and right > left
            for left, right in zip(frame_ids, frame_ids[1:])
        )
        contiguous = all(
            isinstance(value, int) and value == index
            for index, value in enumerate(array_indices)
        )
        sidecars.append(
            {
                "sidecar": relative(path),
                "store_uri": document.get("store_uri"),
                "frames_written": document.get("frames_written"),
                "exit_status": document.get("exit_status"),
                "frame_id_first": frame_ids[0] if frame_ids else None,
                "frame_id_last": frame_ids[-1] if frame_ids else None,
                "frame_ids_strictly_increasing": ordered,
                "array_index_contiguous": contiguous,
            }
        )
        if not ordered:
            findings.append(
                {
                    "code": "frame_id_not_monotonic",
                    "severity": "blocking",
                    "detail": {"sidecar": relative(path), "frame_ids": frame_ids},
                    "source": relative(path),
                }
            )
        if not contiguous:
            findings.append(
                {
                    "code": "array_index_gap",
                    "severity": "warning",
                    "detail": {
                        "sidecar": relative(path),
                        "array_indices": array_indices,
                        "reason": (
                            "the store holds frames with no pose record; the frame "
                            "count reconciliation decides whether that is blocking"
                        ),
                    },
                    "source": relative(path),
                }
            )
    mismatches: list[dict[str, Any]] = []
    shapes = {name: shape for name, shape in stores.items()}

    def key_for(item: dict[str, Any]) -> str:
        store_uri = item.get("store_uri")
        if store_uri:
            return str(store_uri)
        name = Path(str(item["sidecar"])).name
        return name.split(".positions.json")[0].split(".timing.json")[0]

    by_store = {key_for(item): item for item in sidecars}
    for name, shape in shapes.items():
        store = name.split(":", 1)[0]
        match = next(
            (item for key, item in by_store.items() if key and store.startswith(key)),
            None,
        )
        if match is None:
            mismatches.append({"store": store, "reason": "no positions sidecar"})
            continue
        frames = match.get("frames_written")
        if shape and frames is not None and int(shape[0]) != int(frames):
            mismatches.append(
                {
                    "store": store,
                    "sidecar_frames": frames,
                    "store_frames": int(shape[0]),
                    "reason": "frame count differs",
                }
            )
    if mismatches:
        findings.append(
            {
                "code": "frame_count_mismatch",
                "severity": "blocking",
                "detail": mismatches,
                "source": "report stores vs positions sidecars",
            }
        )
    return {
        "sidecars": sidecars,
        "stores": shapes,
        "accounting_ok": not mismatches,
        "mismatches": mismatches,
        "findings": findings,
    }


def calibration_section(
    calibrations: list[Path], camera: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a supplied calibration record and its camera-mode match."""
    if not calibrations:
        return {
            "id": unresolved(
                "no calibration record was supplied and the run references none",
            ),
            "mode_match": unresolved(
                "no calibration record was supplied, so no camera-mode match exists",
            ),
            "records": [],
        }
    records = []
    matching: list[str] = []
    for path in calibrations:
        document = load_json(path)
        camera_mode = document.get("camera_mode") or document.get("mode") or {}
        record = {
            "path": relative(path),
            "sha256": sha256_file(path),
            "calibration_id": document.get("calibration_id"),
            "camera_mode": camera_mode,
            "image_extent_um": document.get("image_extent_um"),
        }
        records.append(record)
        declared_exposure = (camera.get("exposure_ms") or {}).get("value")
        declared_binning = (camera.get("binning_xy") or {}).get("value")
        if (
            camera_mode.get("exposure_ms") == declared_exposure
            and camera_mode.get("binning_xy") == declared_binning
        ):
            matching.append(str(document.get("calibration_id")))
    return {
        "id": (
            field(matching[0], "calibration record", "declared")
            if len(matching) == 1
            else unresolved(
                "no supplied calibration record matches the run's camera mode",
                attempted=tuple(calibrations),
            )
        ),
        "mode_match": field(bool(matching), "calibration record", "derived"),
        "records": records,
    }


def software_section(profile_path: Path) -> dict[str, Any]:
    """Record the four relevant revisions plus the profile digest."""
    return {
        "bundle": field(git_revision(ROOT), "git", "derived"),
        "app": field(
            git_revision(ROOT / "03_external" / "redsun-searching-is-imaging"),
            "git",
            "derived",
        ),
        "planner": field(
            git_revision(ROOT / "03_external" / "sample_search"), "git", "derived"
        ),
        "rtaspt": field(
            git_revision(ROOT / "03_external" / "Realtime-Anisotropy-SPT-Analysis"),
            "git",
            "derived",
        ),
        "profile_path": relative(profile_path),
        "profile_sha256": field(sha256_file(profile_path), profile_path, "derived"),
    }


def product_section(files: dict[str, Any], profile_path: Path) -> dict[str, Any]:
    """Digest the small text sources and name the products that are not digested."""
    digests = []
    sources = [files["report_path"]]
    if files["strip_path"] is not None:
        sources.append(files["strip_path"])
    if files["run_manifest"] is not None:
        sources.append(files["run_manifest"])
    sources.extend(files["positions"])
    sources.extend(files["timing"])
    for path in sources:
        digests.append({"path": relative(path), "sha256": sha256_file(path)})
    return {
        "digests": digests,
        "zarr_stores": [
            {"path": name, "status": "not_digested", "shape": shape}
            for name, shape in (files["report"].get("stores") or {}).items()
        ],
        "profile": {
            "path": relative(profile_path),
            "sha256": sha256_file(profile_path),
        },
    }


def route_findings(
    report: dict[str, Any], strip_doc: dict[str, Any] | None, files: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report a route whose recorded encoding is not a numeric xy pair."""
    findings = []
    route = report.get("route") or []
    malformed = [
        row
        for row in route
        if not (
            isinstance(row, dict)
            and isinstance(row.get("start_xy_um"), list)
            and len(row["start_xy_um"]) == 2
            and all(isinstance(value, (int, float)) for value in row["start_xy_um"])
        )
    ]
    if malformed:
        findings.append(
            {
                "code": "route_encoding_inconsistent",
                "severity": "warning",
                "detail": (
                    f"{len(malformed)} of {len(route)} route rows encode the xy pair "
                    "as text rather than numbers; the strip record is authoritative"
                ),
                "source": relative(files["report_path"]),
            }
        )
    return findings


def walk_field_paths(node: Any, prefix: str = "") -> list[str]:
    """Return the dotted paths of every unresolved or mismatched field."""
    paths: list[str] = []
    if isinstance(node, dict):
        if node.get("status") in {"unresolved", "mismatch"} and "value" in node:
            return [prefix] if prefix else []
        for key, value in node.items():
            if key in {"unresolved", "blocking", "findings", "products", "software"}:
                continue
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(walk_field_paths(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            paths.extend(walk_field_paths(value, f"{prefix}[{index}]"))
    return paths


def main(argv: list[str] | None = None) -> int:
    """Build and write one run-evidence record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", type=Path, required=True, help="recorded run directory"
    )
    parser.add_argument(
        "--profile", type=Path, required=True, help="instrument profile YAML"
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        action="append",
        default=[],
        help="accepted calibration record; repeatable",
    )
    parser.add_argument("--out", type=Path, required=True, help="output JSON path")
    args = parser.parse_args(argv)

    run_dir = args.run if args.run.is_absolute() else (ROOT / args.run)
    profile_path = args.profile if args.profile.is_absolute() else (ROOT / args.profile)
    calibrations = [
        path if path.is_absolute() else (ROOT / path) for path in args.calibration
    ]
    out = args.out if args.out.is_absolute() else (ROOT / args.out)
    try:
        record = build(run_dir, profile_path, calibrations)
    except EvidenceError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(
        f"{record['run']['confirmation_id']['value']}: "
        f"outcome {record['run']['session_outcome']['value']}, "
        f"{len(record['blocking'])} blocking, {len(record['unresolved'])} unresolved, "
        f"{len(record['findings'])} findings"
    )
    print(f"wrote {relative(out)}")
    return 0 if not record["blocking"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
