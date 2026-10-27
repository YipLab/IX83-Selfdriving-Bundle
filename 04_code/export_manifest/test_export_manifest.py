"""Hardware-free tests for the figure export manifest."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import export
import pytest
from export import ExportError

HERE = Path(__file__).resolve().parent


def _declare(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "schema": export.SOURCE_SCHEMA,
        "figure_id": "figure-test",
        "title": "test figure",
        "status": "measured",
        "slots": [{"slot": "D06", "claim": "filled"}],
        "inputs": [
            {
                "path": "input.csv",
                "kind": "csv",
                "status": "measured",
                "quantity": "residual",
                "unit": "px",
            }
        ],
        "unit_registry": {"residual": "px"},
        "analysis": {"name": "reducer", "version": "1.0", "config": "config.json"},
        "exclusions": [],
    }
    for key, value in overrides.items():
        spec[key] = value
    return spec


def _tree(
    tmp_path: Path, spec: dict[str, Any] | None = None
) -> tuple[dict[str, Any], Path]:
    (tmp_path / "input.csv").write_text(
        "quantity,value\nresidual,0.178\n", encoding="utf-8"
    )
    (tmp_path / "config.json").write_text('{"threshold": 550}', encoding="utf-8")
    return (spec or _declare()), tmp_path


def test_a_coherent_declaration_validates() -> None:
    spec = export.validate_sources(_declare())
    assert spec["figure_id"] == "figure-test"
    assert spec["status"] == "measured"
    assert spec["slots"] == [{"slot": "D06", "claim": "filled", "reason": None}]
    assert spec["inputs"][0]["unit"] == "px"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "other"}, "schema"),
        ({"figure_id": ""}, "figure_id"),
        ({"title": " "}, "title"),
        ({"status": "guessed"}, "status"),
        ({"slots": []}, "slots"),
        ({"exclusions": [""]}, "exclusions"),
    ],
)
def test_invalid_declarations_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ExportError, match=message):
        export.validate_sources(_declare(**change))


def test_a_not_applied_figure_needs_a_reason() -> None:
    with pytest.raises(ExportError, match="reason"):
        export.validate_sources(_declare(status="not-applied", inputs=[]))
    spec = export.validate_sources(
        _declare(status="not-applied", inputs=[], reason="no analyser on this camera")
    )
    assert spec["reason"] == "no analyser on this camera"


def test_slot_identifiers_and_claims_are_checked() -> None:
    with pytest.raises(ExportError, match="Dnn or Mnn"):
        export.validate_sources(_declare(slots=[{"slot": "X01", "claim": "filled"}]))
    with pytest.raises(ExportError, match="declared twice"):
        export.validate_sources(
            _declare(
                slots=[
                    {"slot": "D06", "claim": "filled"},
                    {"slot": "D06", "claim": "filled"},
                ]
            )
        )
    with pytest.raises(ExportError, match="filled or not-applied"):
        export.validate_sources(_declare(slots=[{"slot": "D06", "claim": "maybe"}]))
    with pytest.raises(ExportError, match="reason is required"):
        export.validate_sources(
            _declare(slots=[{"slot": "D06", "claim": "not-applied"}])
        )


def test_a_delivered_figure_cannot_carry_a_not_applied_slot() -> None:
    with pytest.raises(ExportError, match="not-applied slot"):
        export.validate_sources(
            _declare(
                slots=[
                    {"slot": "D06", "claim": "filled"},
                    {"slot": "D07", "claim": "not-applied", "reason": "no repeat"},
                ]
            )
        )


def test_a_unit_registry_mismatch_is_refused() -> None:
    spec = _declare()
    spec["inputs"][0]["unit"] = "um"
    with pytest.raises(ExportError, match="registry requires"):
        export.validate_sources(spec)


def test_a_measured_figure_cannot_mix_in_synthetic_inputs() -> None:
    spec = _declare()
    spec["inputs"][0]["status"] = "synthetic"
    with pytest.raises(ExportError, match="every input measured"):
        export.validate_sources(spec)

    spec = _declare()
    spec["inputs"].append(
        {
            "path": "other.csv",
            "kind": "csv",
            "status": "placeholder",
            "quantity": "residual",
            "unit": "px",
        }
    )
    with pytest.raises(ExportError, match="measured figure cannot include"):
        export.validate_sources(spec)


def test_a_measured_figure_needs_every_input_measured() -> None:
    spec = _declare()
    spec["inputs"].append(
        {
            "path": "other.csv",
            "kind": "csv",
            "status": "recorded",
            "quantity": "residual",
            "unit": "px",
        }
    )
    with pytest.raises(ExportError, match="every input measured"):
        export.validate_sources(spec)


def test_a_recorded_figure_accepts_measured_inputs_but_not_synthetic_ones() -> None:
    spec = _declare(status="recorded")
    spec["inputs"].append(
        {
            "path": "other.csv",
            "kind": "csv",
            "status": "recorded",
            "quantity": "residual",
            "unit": "px",
        }
    )
    assert export.validate_sources(spec)["status"] == "recorded"

    spec["inputs"].append(
        {
            "path": "third.csv",
            "kind": "csv",
            "status": "synthetic",
            "quantity": "residual",
            "unit": "px",
        }
    )
    with pytest.raises(ExportError, match="cannot include synthetic"):
        export.validate_sources(spec)


def test_a_synthetic_figure_cannot_include_a_placeholder() -> None:
    spec = _declare(status="synthetic")
    spec["inputs"][0]["status"] = "synthetic"
    assert export.validate_sources(spec)["status"] == "synthetic"
    spec["inputs"].append(
        {
            "path": "other.csv",
            "kind": "csv",
            "status": "placeholder",
            "quantity": "residual",
            "unit": "px",
        }
    )
    with pytest.raises(ExportError, match="placeholder"):
        export.validate_sources(spec)


@pytest.mark.parametrize("key", ["status", "kind", "quantity", "unit"])
def test_each_input_field_is_required(key: str) -> None:
    spec = _declare()
    del spec["inputs"][0][key]
    with pytest.raises(ExportError):
        export.validate_sources(spec)


def test_an_unknown_input_kind_is_refused() -> None:
    spec = _declare()
    spec["inputs"][0]["kind"] = "xlsx"
    with pytest.raises(ExportError, match="kind"):
        export.validate_sources(spec)


def test_a_missing_analysis_config_is_refused_at_build(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    spec["analysis"]["config"] = "absent.json"
    with pytest.raises(ExportError, match="analysis.config is missing"):
        export.build_manifest(export.validate_sources(spec), base)


def test_build_resolves_digests_and_software_identity(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    manifest = export.build_manifest(export.validate_sources(spec), base)
    assert manifest["status"] == "measured"
    assert manifest["inputs"][0]["sha256"] == export._sha256(base / "input.csv")
    assert manifest["analysis"]["config_sha256"] == export._sha256(base / "config.json")
    assert manifest["accepted"] is False
    assert set(manifest["software"]) == {"bundle", "app", "planner", "rtaspt"}


def test_build_refuses_a_missing_input(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    (base / "input.csv").unlink()
    with pytest.raises(ExportError, match="input is missing"):
        export.build_manifest(export.validate_sources(spec), base)


def test_build_refuses_a_directory_input(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    (base / "input.csv").unlink()
    (base / "input.csv").mkdir()
    with pytest.raises(ExportError, match="directory"):
        export.build_manifest(export.validate_sources(spec), base)


def test_verify_reports_a_changed_input(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    manifest = export.build_manifest(export.validate_sources(spec), base)
    assert export.verify_manifest(manifest, base) == []

    (base / "input.csv").write_text("quantity,value\nresidual,9.9\n", encoding="utf-8")
    problems = export.verify_manifest(manifest, base)
    assert len(problems) == 1 and "changed input" in problems[0]


def test_verify_reports_a_missing_input_and_config(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    manifest = export.build_manifest(export.validate_sources(spec), base)
    (base / "input.csv").unlink()
    (base / "config.json").write_text("{}", encoding="utf-8")
    problems = export.verify_manifest(manifest, base)
    assert any("missing input" in problem for problem in problems)
    assert any("changed analysis config" in problem for problem in problems)


def test_verify_refuses_another_schema(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    manifest = export.build_manifest(export.validate_sources(spec), base)
    manifest = copy.deepcopy(manifest)
    manifest["schema"] = "other"
    with pytest.raises(ExportError, match="schema"):
        export.verify_manifest(manifest, base)


def test_cli_builds_verifies_and_refuses(tmp_path: Path) -> None:
    spec, base = _tree(tmp_path)
    sources = base / "figure.sources.json"
    sources.write_text(json.dumps(spec), encoding="utf-8")
    out = base / "manifest.json"
    assert (
        export.main(["--sources", str(sources), "--out", str(out), "--base", str(base)])
        == 0
    )
    assert export.main(["--verify", str(out), "--base", str(base)]) == 0

    (base / "input.csv").write_text("changed\n", encoding="utf-8")
    assert export.main(["--verify", str(out), "--base", str(base)]) == 1

    bad = base / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert export.main(["--sources", str(bad), "--out", str(out)]) == 2
