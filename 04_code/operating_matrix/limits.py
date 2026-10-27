"""Apply author-declared frozen limits to a built operating matrix (Q05).

Q05's remaining item is the author's frozen limits. The matrix cannot invent
them, but it can accept them: this module reads a declared limits document,
checks that it is an author declaration rather than a placeholder, and marks
every matrix row as within or outside the declared bounds with a typed violation
for each failed comparison.

Two rules keep the mechanism honest:

* A limit may only be declared for a quantity the matrix actually carries. A
  bound on a quantity no row reports is refused, because it would look checked
  while nothing was compared.
* A `provisional` declaration is retained as information and never presented as
  the instrument's frozen decision; the report says which status it applied.

This module changes no metric and removes no refusal. A row the matrix already
refused stays refused, and a row outside a declared bound gains a violation but
keeps its own reasons.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

LIMITS_SCHEMA = "ix71.frozen-limits.v1"
MATRIX_SCHEMA = "ix71.operating-matrix-report.1"
REPORT_SCHEMA = "ix71.frozen-limits-check.v1"

STATUSES = ("author-declared", "provisional")

#: Quantities a bound may be declared for; each must be a row field.
BOUND_QUANTITIES = (
    "speed_um_s",
    "exposure_ms",
    "frame_period_s",
    "width_um",
    "step_um",
    "retained_frames_per_strip",
)


class LimitsError(ValueError):
    """A declaration or matrix that cannot be checked."""


def _text(value: Any, name: str) -> str:
    """Return a nonempty string."""
    if not isinstance(value, str) or not value.strip():
        raise LimitsError(f"{name} must be a nonempty string")
    return value


def _bound(value: Any, name: str) -> float:
    """Return a finite numeric bound."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LimitsError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise LimitsError(f"{name} must be finite")
    return number


def validate_limits(document: Any) -> dict[str, Any]:
    """Validate a frozen-limits declaration and return it normalized."""
    if not isinstance(document, dict):
        raise LimitsError("a limits document must be a JSON object")
    if document.get("schema") != LIMITS_SCHEMA:
        raise LimitsError(
            f"expected schema {LIMITS_SCHEMA!r}, found {document.get('schema')!r}"
        )
    author = _text(document.get("author"), "author")
    date = _text(document.get("date"), "date")
    rationale = _text(document.get("rationale"), "rationale")
    status = document.get("status")
    if status not in STATUSES:
        raise LimitsError(f"status must be one of {', '.join(STATUSES)}")
    bounds = document.get("bounds")
    if not isinstance(bounds, dict) or not bounds:
        raise LimitsError("bounds must be a nonempty object")
    normalized: dict[str, dict[str, float]] = {}
    for quantity, bound in bounds.items():
        if quantity not in BOUND_QUANTITIES:
            raise LimitsError(f"unknown bound quantity {quantity!r}")
        if not isinstance(bound, dict) or not bound:
            raise LimitsError(f"bounds[{quantity!r}] must be an object")
        entry: dict[str, float] = {}
        for key, value in bound.items():
            if key not in ("min", "max"):
                raise LimitsError(f"bounds[{quantity!r}] has unknown key {key!r}")
            entry[key] = _bound(value, f"bounds[{quantity!r}].{key}")
        if "min" in entry and "max" in entry and entry["min"] > entry["max"]:
            raise LimitsError(f"bounds[{quantity!r}] min exceeds max")
        normalized[quantity] = entry
    return {
        "schema": LIMITS_SCHEMA,
        "author": author,
        "date": date,
        "rationale": rationale,
        "status": status,
        "bounds": normalized,
    }


def _violations(row: dict[str, Any], bounds: dict[str, dict[str, float]]) -> list[str]:
    """Return one violation code per failed comparison on a row."""
    found: list[str] = []
    for quantity, bound in bounds.items():
        value = row.get(quantity)
        if value is None:
            found.append(f"{quantity}_missing_in_row")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            found.append(f"{quantity}_not_numeric")
            continue
        number = float(value)
        if "max" in bound and number > bound["max"]:
            found.append(f"{quantity}_above_max")
        if "min" in bound and number < bound["min"]:
            found.append(f"{quantity}_below_min")
    return found


def check_matrix(matrix: Any, limits_document: Any) -> dict[str, Any]:
    """Mark every matrix row within or outside the declared bounds."""
    declared = validate_limits(limits_document)
    if not isinstance(matrix, dict):
        raise LimitsError("a matrix document must be a JSON object")
    if matrix.get("schema") != MATRIX_SCHEMA:
        raise LimitsError(
            f"expected matrix schema {MATRIX_SCHEMA!r}, found {matrix.get('schema')!r}"
        )
    rows = matrix.get("rows")
    if not isinstance(rows, list) or not rows:
        raise LimitsError("the matrix has no rows")
    first = rows[0]
    if not isinstance(first, dict):
        raise LimitsError("matrix rows must be objects")
    missing_quantities = [
        quantity for quantity in declared["bounds"] if quantity not in first
    ]
    if missing_quantities:
        raise LimitsError(
            "declared bounds have no matching row quantity: "
            + ", ".join(sorted(missing_quantities))
        )

    checked: list[dict[str, Any]] = []
    outside = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise LimitsError(f"rows[{index}] must be an object")
        violations = _violations(row, declared["bounds"])
        if violations:
            outside += 1
        checked.append(
            {
                "row_index": index,
                "detector_mode": row.get("detector_mode"),
                "speed_um_s": row.get("speed_um_s"),
                "exposure_ms": row.get("exposure_ms"),
                "width_um": row.get("width_um"),
                "within_limits": not violations,
                "violations": violations,
                "matrix_feasible": row.get("feasible"),
            }
        )
    issues: list[dict[str, Any]] = []
    if declared["status"] == "provisional":
        issues.append(
            {
                "code": "limits_provisional",
                "severity": "info",
                "detail": "the declaration is provisional, not the instrument's frozen decision",
            }
        )
    return {
        "schema": REPORT_SCHEMA,
        "matrix": {"rows": len(rows), "matrix_id": matrix.get("matrix_id")},
        "limits": {
            "author": declared["author"],
            "date": declared["date"],
            "status": declared["status"],
            "rationale": declared["rationale"],
            "bounds": declared["bounds"],
        },
        "rows": checked,
        "summary": {
            "rows": len(checked),
            "within_limits": len(checked) - outside,
            "outside_limits": outside,
            "outside_and_matrix_feasible": sum(
                1 for row in checked if row["matrix_feasible"] and not row["within_limits"]
            ),
        },
        "issues": issues,
        "accepted": not any(issue["severity"] == "blocking" for issue in issues),
    }


def main(argv: list[str] | None = None) -> int:
    """Check a built matrix against a declared limits document."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--limits", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    matrix = json.loads(arguments.matrix.read_text(encoding="utf-8"))
    limits = json.loads(arguments.limits.read_text(encoding="utf-8"))
    report = check_matrix(matrix, limits)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0 if report["accepted"] else 1


__all__ = [
    "BOUND_QUANTITIES",
    "LIMITS_SCHEMA",
    "MATRIX_SCHEMA",
    "REPORT_SCHEMA",
    "LimitsError",
    "check_matrix",
    "main",
    "validate_limits",
]


if __name__ == "__main__":
    raise SystemExit(main())

