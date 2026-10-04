"""Compare the original Python segmentation baseline with installed ImageJ."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import tifffile
from samplescout.detection import (
    DetectionConfig,
    _otsu_threshold,
    detect_bright_objects,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fiji", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    java_roots = sorted((args.fiji / "java/win64").glob("*/bin/javac.exe"))
    jars = sorted((args.fiji / "jars").glob("ij-*.jar"))
    if len(java_roots) != 1 or len(jars) != 1:
        raise ValueError("select a Fiji installation with one JDK and one ImageJ core jar")
    javac, jar = java_roots[0], jars[0]
    java = javac.with_name("java.exe")
    args.output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("ImageJComponentCheck.java")
    subprocess.run([str(javac), "-cp", str(jar), "-d", str(args.output), str(source)],
                   check=True, timeout=60)
    inputs = sorted(args.input.glob("*.tif"))
    if not inputs:
        raise ValueError("no TIFF inputs")
    records = []
    lines = []
    for path in inputs:
        image = tifffile.imread(path)
        if image.ndim != 2 or image.dtype != np.uint8:
            raise ValueError(f"expected uint8 YX: {path}")
        threshold = _otsu_threshold(image.astype(np.float64))
        objects = detect_bright_objects(image, DetectionConfig(threshold=threshold,
                                                             min_area_px=12, max_area_px=100))
        records.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "threshold": threshold, "python_count": len(objects),
                        "python_areas": sorted(obj.area_px for obj in objects)})
        lines.append(f"{path}\t{threshold}")
    input_tsv, output_tsv = args.output / "input.tsv", args.output / "imagej.tsv"
    input_tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([str(java), "-Djava.awt.headless=true", "-cp", f"{jar};{args.output}",
                    "ImageJComponentCheck", str(input_tsv), str(output_tsv)], check=True, timeout=60)
    results = output_tsv.read_text(encoding="utf-8").splitlines()
    for record, line in zip(records, results, strict=True):
        fields = line.split("\t")
        if fields[0] != record["path"]:
            raise ValueError("ImageJ output input order mismatch")
        record["imagej_count"] = int(fields[1])
        record["imagej_areas"] = sorted(float(area) for area in fields[2].split(",") if area) if len(fields) > 2 else []
        record["counts_match"] = record["python_count"] == record["imagej_count"]
        record["areas_match"] = record["python_areas"] == record["imagej_areas"]
    report = {"method": "same explicit threshold mask; 8-connected particles; 12-100 pixel area",
              "imagej_jar": str(jar), "imagej_jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
              "input_count": len(records), "python_total": sum(r["python_count"] for r in records),
              "imagej_total": sum(r["imagej_count"] for r in records),
              "all_counts_match": all(r["counts_match"] for r in records),
              "all_areas_match": all(r["areas_match"] for r in records), "images": records}
    (args.output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "images"}, indent=2))
    if not report["all_counts_match"] or not report["all_areas_match"]:
        raise SystemExit("ImageJ component comparison differs; inspect report")


if __name__ == "__main__":
    main()
