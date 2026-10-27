"""Audit digests that Markdown records declare for their artifacts (Track D / S1).

Several records declare `| [path](target) | `sha256` |` rows for the files they
rely on. Those claims silently rot when a file is edited: the record still reads
as verified while the digest no longer matches. This module reads the declared
rows, resolves each target against the record, recomputes the digest and reports
`verified`, `missing`, `digest_mismatch` or `unreadable`.

It also distinguishes a **historical** table from a current one. A table under a
heading whose text mentions a commit or history records what the artifact hashed
to at a point in time; a mismatch there is reported as `historical_mismatch` and
does not block. That keeps an old commit record honest without pretending it
describes today's file, and it keeps blocking attention for current claims.

The module reads Markdown and files only; it makes no claim about the evidence
itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ix71.declared-digest-audit.v1"

ROW = re.compile(
    r"^\|\s*\[[^\]]*\]\((?P<link>[^)\s]+)\)[^|]*\|\s*`?(?P<digest>[0-9a-f]{64})`?\s*\|"
)
HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+)$")
HISTORICAL_HINT = re.compile(r"commit|historical|history|snapshot", re.IGNORECASE)

VERIFIED = "verified"
MISSING = "missing"
MISMATCH = "digest_mismatch"
HISTORICAL = "historical_mismatch"
UNREADABLE = "unreadable"
EXTERNAL = "external_skipped"


def _sha256(path: Path) -> str:
    """Return the file digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Declared:
    """One digest a Markdown record declares for a linked artifact."""

    source: Path
    line: int
    link: str
    digest: str
    historical: bool


def collect(paths: Iterable[Path]) -> list[Declared]:
    """Read every declared digest from the given Markdown files."""
    found: list[Declared] = []
    for path in paths:
        headings: list[tuple[int, str]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            heading = HEADING.match(line)
            if heading:
                level = len(heading.group("level"))
                headings = [item for item in headings if item[0] < level]
                headings.append((level, heading.group("text")))
                continue
            match = ROW.match(line)
            if not match:
                continue
            historical = any(
                HISTORICAL_HINT.search(text) for _level, text in headings
            )
            found.append(
                Declared(
                    source=path,
                    line=number,
                    link=match.group("link"),
                    digest=match.group("digest"),
                    historical=historical,
                )
            )
    return found


def audit(paths: Iterable[Path], *, root: Path) -> dict[str, Any]:
    """Verify every declared digest and return a JSON-safe report."""
    resolved_root = root.resolve()
    rows: list[dict[str, Any]] = []
    for declaration in collect(paths):
        link = declaration.link
        if link.startswith(("http://", "https://", "mailto:", "#")):
            rows.append(
                {
                    "source": str(declaration.source),
                    "line": declaration.line,
                    "link": link,
                    "expected_sha256": declaration.digest,
                    "status": EXTERNAL,
                }
            )
            continue
        target_text = link.split("#", 1)[0]
        target = (declaration.source.parent / target_text).resolve()
        status: str
        actual: str | None = None
        if not target.exists():
            status = MISSING
        elif not target.is_file():
            status = UNREADABLE
        else:
            try:
                actual = _sha256(target)
            except OSError:
                status = UNREADABLE
            else:
                if actual == declaration.digest:
                    status = VERIFIED
                elif declaration.historical:
                    status = HISTORICAL
                else:
                    status = MISMATCH
        rows.append(
            {
                "source": str(declaration.source),
                "line": declaration.line,
                "link": link,
                "target": str(target),
                "inside_root": str(target).startswith(str(resolved_root)),
                "expected_sha256": declaration.digest,
                "actual_sha256": actual,
                "status": status,
            }
        )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    blocking = [
        row
        for row in rows
        if row["status"] in {MISSING, MISMATCH, UNREADABLE}
    ]
    return {
        "schema": SCHEMA,
        "root": str(resolved_root),
        "files": sorted({row["source"] for row in rows}),
        "declared": len(rows),
        "counts": counts,
        "ok": not blocking,
        "findings": rows,
    }


def main(argv: list[str] | None = None) -> int:
    """Audit the digests declared by the given Markdown records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="workspace root the links should stay inside",
    )
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    paths = arguments.paths
    if not paths:
        root = arguments.root
        paths = sorted(
            [
                *root.glob("08_session_logs/*/README.md"),
                *root.glob("04_code/*/README.md"),
                *root.glob("02_docs_offline/*.md"),
            ]
        )
    report = audit(paths, root=arguments.root)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0 if report["ok"] else 1


__all__ = [
    "Declared",
    "SCHEMA",
    "audit",
    "collect",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())


