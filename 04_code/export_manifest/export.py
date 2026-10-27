"""Figure export manifest: link a manuscript figure to its real inputs (Q12).

Q12 of the 2026-10-27 increment asks for one rebuildable manifest linking run
products, analysis versions and configurations, exclusions, uncertainty and the
CSV/SVG/PNG figure outputs, rejecting incompatible units, missing source
identities and placeholder-versus-recorded status mismatches. It also says to
extend the existing handoff/verifier rather than create a second transport: this
tool reads the same saved products, hashes them, and refuses a claim it cannot
support.

The unit of the document is one figure. A declaration lists the figure's inputs
(path, kind, quantity, unit, status), the slots it fills, the analysis version
and configuration, and any exclusions. The builder emits a manifest with
digests, software revisions and derived status; the verifier re-hashes a saved
manifest and reports every changed or missing input.

Nothing here plots, re-processes or invents a value.

    python export.py --sources figure_sources.json --out figure_manifest.json
    python export.py --verify figure_manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = "redsun-bundle.figure-export/v1"
SOURCE_SCHEMA = "redsun-bundle.figure-sources/v1"

INPUT_STATUSES = ("measured", "recorded", "synthetic", "placeholder")
FIGURE_STATUSES = ("measured", "recorded", "synthetic", "placeholder", "not-applied")
SLOT_PATTERN = re.compile(r"^[DM]\d{2}$")
KINDS = ("csv", "png", "svg", "json", "tif", "zarr")


class ExportError(ValueError):
    """A declaration or manifest cannot support the claim it makes."""


def _text(value: Any, name: str) -> str:
    """Return a nonempty string."""
    if not isinstance(value, str) or not value.strip():
        raise ExportError(f"{name} is required")
    return value.strip()


def _sha256(path: Path) -> str:
    """Return the SHA-256 of one file."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(path: Path) -> dict[str, Any]:
    """Return a checkout's revision and dirty flag, never raising."""

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
        return {"revision": None, "status": "unavailable"}
    porcelain = run("status", "--porcelain")
    return {"revision": revision, "dirty": bool(porcelain)}


def validate_sources(document: Any) -> dict[str, Any]:
    """Validate one figure declaration and return its parsed form.

    A declaration must state every input's status. "Measured" is a claim about
    the value, so mixing it with a synthetic or placeholder input is refused
    rather than averaged into a figure.
    """
    spec = document
    if not isinstance(spec, dict):
        raise ExportError("declaration must be an object")
    if spec.get("schema") != SOURCE_SCHEMA:
        raise ExportError(f"schema must be {SOURCE_SCHEMA!r}")
    figure_id = _text(spec.get("figure_id"), "figure_id")
    title = _text(spec.get("title"), "title")
    status = spec.get("status")
    if status not in FIGURE_STATUSES:
        raise ExportError(f"status must be one of {list(FIGURE_STATUSES)}")
    if status == "not-applied" and not _text(spec.get("reason"), "reason"):
        raise ExportError("a not-applied figure needs a reason")

    slots = spec.get("slots")
    if not isinstance(slots, list) or not slots:
        raise ExportError("slots must be a nonempty list")
    parsed_slots = []
    seen_slots = set()
    for index, slot in enumerate(slots):
        entry = slot if isinstance(slot, dict) else {}
        slot_id = _text(entry.get("slot"), f"slots[{index}].slot")
        if not SLOT_PATTERN.match(slot_id):
            raise ExportError(f"slots[{index}].slot {slot_id!r} is not Dnn or Mnn")
        if slot_id in seen_slots:
            raise ExportError(f"slot {slot_id} is declared twice")
        seen_slots.add(slot_id)
        claim = entry.get("claim")
        if claim not in ("filled", "not-applied"):
            raise ExportError(f"slots[{index}].claim must be filled or not-applied")
        if claim == "not-applied" and not _text(
            entry.get("reason"), f"slots[{index}].reason"
        ):
            raise ExportError(f"slots[{index}] is not-applied without a reason")
        parsed_slots.append(
            {"slot": slot_id, "claim": claim, "reason": entry.get("reason")}
        )

    inputs = spec.get("inputs")
    if status == "not-applied":
        inputs = inputs or []
    if not isinstance(inputs, list) or (status != "not-applied" and not inputs):
        raise ExportError("a delivered figure needs at least one input")
    units = spec.get("unit_registry") or {}
    if not isinstance(units, dict):
        raise ExportError("unit_registry must be an object")
    parsed_inputs = []
    for index, item in enumerate(inputs):
        entry = item if isinstance(item, dict) else {}
        path = _text(entry.get("path"), f"inputs[{index}].path")
        kind = entry.get("kind")
        if kind not in KINDS:
            raise ExportError(f"inputs[{index}].kind must be one of {list(KINDS)}")
        input_status = entry.get("status")
        if input_status not in INPUT_STATUSES:
            raise ExportError(
                f"inputs[{index}].status must be one of {list(INPUT_STATUSES)}"
            )
        quantity = _text(entry.get("quantity"), f"inputs[{index}].quantity")
        unit = _text(entry.get("unit"), f"inputs[{index}].unit")
        if quantity in units and units[quantity] != unit:
            raise ExportError(
                f"inputs[{index}] declares {unit!r} for {quantity!r}, but the "
                f"registry requires {units[quantity]!r}"
            )
        parsed_inputs.append(
            {
                "path": path,
                "kind": kind,
                "status": input_status,
                "quantity": quantity,
                "unit": unit,
                "produced_by": entry.get("produced_by"),
            }
        )

    statuses = {item["status"] for item in parsed_inputs}
    if "measured" in statuses and statuses & {"synthetic", "placeholder"}:
        raise ExportError(
            "a measured figure cannot include synthetic or placeholder inputs: "
            f"{sorted(statuses)}"
        )
    if status == "measured" and statuses - {"measured"}:
        raise ExportError(
            f"a measured figure needs every input measured, found {sorted(statuses)}"
        )
    if status == "recorded" and statuses - {"recorded", "measured"}:
        raise ExportError(
            "a recorded figure cannot include synthetic or placeholder inputs: "
            f"{sorted(statuses)}"
        )
    if status == "synthetic" and "placeholder" in statuses:
        raise ExportError("a synthetic figure cannot include placeholder inputs")
    if status != "not-applied" and any(
        item["claim"] == "not-applied" for item in parsed_slots
    ):
        raise ExportError(
            "a delivered figure declares a not-applied slot; deliver that slot "
            "separately or mark the figure not-applied"
        )

    analysis = spec.get("analysis")
    if status != "not-applied":
        analysis = analysis if isinstance(analysis, dict) else {}
        _text(analysis.get("name"), "analysis.name")
        _text(analysis.get("version"), "analysis.version")
        _text(analysis.get("config"), "analysis.config")

    exclusions = spec.get("exclusions") or []
    if not isinstance(exclusions, list) or any(
        not isinstance(item, str) or not item.strip() for item in exclusions
    ):
        raise ExportError("exclusions must be a list of nonempty strings")

    return {
        "schema": SOURCE_SCHEMA,
        "figure_id": figure_id,
        "title": title,
        "status": status,
        "reason": spec.get("reason"),
        "slots": parsed_slots,
        "inputs": parsed_inputs,
        "unit_registry": dict(units),
        "analysis": analysis if isinstance(analysis, dict) else None,
        "exclusions": list(exclusions),
    }


def load_sources(path: Path) -> dict[str, Any]:
    """Read and validate one figure declaration."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExportError(f"declaration not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ExportError(f"declaration is not JSON: {error}") from error
    return validate_sources(document)


def build_manifest(spec: dict[str, Any], base: Path | None = None) -> dict[str, Any]:
    """Resolve every input against the filesystem and emit the export manifest."""
    base = HERE if base is None else Path(base)
    resolved = []
    for item in spec["inputs"]:
        path = Path(item["path"])
        absolute = path if path.is_absolute() else (base / path)
        if not absolute.exists():
            raise ExportError(f"input is missing: {item['path']}")
        if absolute.is_dir():
            raise ExportError(
                f"input is a directory, not a figure artifact: {item['path']}"
            )
        resolved.append(
            {
                **item,
                "path": item["path"],
                "sha256": _sha256(absolute),
                "bytes": absolute.stat().st_size,
            }
        )
    analysis = spec["analysis"]
    config_digest = None
    if analysis is not None:
        config = Path(str(analysis["config"]))
        config_path = config if config.is_absolute() else (base / config)
        if not config_path.is_file():
            raise ExportError(f"analysis.config is missing: {analysis['config']}")
        config_digest = _sha256(config_path)
    return {
        "schema": SCHEMA,
        "figure_id": spec["figure_id"],
        "title": spec["title"],
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": spec["status"],
        "reason": spec["reason"],
        "slots": spec["slots"],
        "inputs": resolved,
        "unit_registry": spec["unit_registry"],
        "analysis": (
            None
            if analysis is None
            else {
                "name": analysis["name"],
                "version": analysis["version"],
                "config": analysis["config"],
                "config_sha256": config_digest,
            }
        ),
        "exclusions": spec["exclusions"],
        "software": {
            "bundle": _git(ROOT),
            "app": _git(ROOT / "03_external" / "redsun-searching-is-imaging"),
            "planner": _git(ROOT / "03_external" / "sample_search"),
            "rtaspt": _git(ROOT / "03_external" / "Realtime-Anisotropy-SPT-Analysis"),
        },
        "accepted": False,
    }


def verify_manifest(manifest: dict[str, Any], base: Path | None = None) -> list[str]:
    """Return every changed, missing or inconsistent input in a saved manifest."""
    base = HERE if base is None else Path(base)
    if manifest.get("schema") != SCHEMA:
        raise ExportError(f"manifest schema must be {SCHEMA!r}")
    problems: list[str] = []
    for item in manifest.get("inputs") or []:
        path = Path(item["path"])
        absolute = path if path.is_absolute() else (base / path)
        if not absolute.exists():
            problems.append(f"missing input: {item['path']}")
            continue
        digest = _sha256(absolute)
        if digest != item.get("sha256"):
            problems.append(
                f"changed input: {item['path']} is {digest[:12]}, manifest has "
                f"{str(item.get('sha256'))[:12]}"
            )
    analysis = manifest.get("analysis")
    if analysis is not None and analysis.get("config"):
        config = Path(analysis["config"])
        absolute = config if config.is_absolute() else (base / config)
        if not absolute.exists():
            problems.append(f"missing analysis config: {analysis['config']}")
        elif _sha256(absolute) != analysis.get("config_sha256"):
            problems.append(f"changed analysis config: {analysis['config']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Build a figure export manifest, or verify a saved one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, help="figure declaration JSON")
    parser.add_argument("--out", type=Path, help="output manifest JSON")
    parser.add_argument("--verify", type=Path, help="saved manifest to verify")
    parser.add_argument(
        "--base", type=Path, help="resolve declared paths against this directory"
    )
    args = parser.parse_args(argv)
    if args.verify is not None:
        try:
            manifest = json.loads(args.verify.read_text(encoding="utf-8"))
            problems = verify_manifest(manifest, args.base)
        except (FileNotFoundError, ExportError) as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        if problems:
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(
            f"{manifest.get('figure_id')}: "
            f"{len(manifest.get('inputs') or [])} inputs verified"
        )
        return 0
    if args.sources is None or args.out is None:
        parser.error("provide --sources and --out, or --verify")
        return 2
    try:
        spec = load_sources(args.sources)
        manifest = build_manifest(spec, args.base)
    except ExportError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(
        f"{manifest['figure_id']}: {manifest['status']}, "
        f"{len(manifest['inputs'])} input(s), {len(manifest['slots'])} slot(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
