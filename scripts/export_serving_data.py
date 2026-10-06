"""Copy the stored runs the review workspace reads into a portable data directory.

    python scripts/export_serving_data.py --output ../mospi-data            # V2 runs, with their audit trails
    python scripts/export_serving_data.py --output ../mospi-data --include-v1

The output keeps the project layout (<module>/runs/<run>/...), so it can be
mounted into the container as MOSPI_DATA_DIR.  Only the files the API and case
pages read are copied (resolved with the same SourceResolver the server uses);
raw PLFS CSVs, intermediate runs and peer-group tables are not.  Nothing is
recomputed and no source file is modified.  The result contains unit-level
survey records: store and transfer it under the applicable GoI data controls.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fusion.explain import SourceResolver  # noqa: E402

# Files the serving layer reads from each source run (fusion/api.py, fusion/explain.py).
SERVED_FILES = {
    "preprocessing": ["prepared_persons.parquet", "run_metadata.json"],
    "statistical": ["statistical_evidence.parquet", "statistical_report.json", "run_metadata.json"],
    "contextual": ["contextual_evidence.parquet", "run_metadata.json"],
    "ml": ["isolation_forest_evidence.parquet", "lof_evidence.parquet", "conditional_model_evidence.parquet", "similarity_evidence.parquet",
           "ml_report.json", "run_metadata.json"],
    "pattern": ["pattern_evidence.parquet", "pattern_report.json", "run_metadata.json"],
    "historical": ["historical_record_evidence.parquet", "aggregate_indicators.parquet", "historical_report.json", "run_metadata.json"],
    "integrity": ["integrity_violations.parquet", "integrity_report.json", "run_metadata.json"],
}
FUSION_FILES = ["fused_cases.parquet", "evidence_cards.parquet", "group_priorities.parquet", "influence_components.parquet",
                "fusion_report.json", "fusion_report.md", "run_metadata.json"]


def _copy(source: Path, destination: Path, keep_existing: bool = False) -> int:
    if keep_existing and destination.exists():
        return 0  # e.g. a review_audit.sqlite that already holds decisions: never overwritten
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return source.stat().st_size


def export(project: Path, output: Path, *, include_v1: bool, include_audit: bool, keep_existing: bool = False) -> dict[str, object]:
    resolver = SourceResolver(project)
    fusion_root = project / "fusion" / "runs"
    copied, missing, total = [], [], 0
    for run in sorted(p for p in fusion_root.iterdir() if (p / "run_metadata.json").is_file() and (p / "fused_cases.parquet").is_file()):
        metadata = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
        if not include_v1 and "v2" not in str(metadata.get("fusion_version", "")):
            continue
        names = FUSION_FILES + (["review_audit.sqlite"] if include_audit else [])
        for name in names:
            if (run / name).is_file():
                total += _copy(run / name, output / "fusion" / "runs" / run.name / name, keep_existing)
        copied.append(f"fusion/runs/{run.name}")
        release, observation = str(metadata["release"]), str(metadata["observation"])
        wanted = {"preprocessing": metadata.get("input_preprocessing_run_id"), **metadata.get("source_runs", {})}
        for module, run_id in wanted.items():
            directory = resolver.run_dir(module, release, observation, run_id)
            if directory is None:
                missing.append(f"{module}:{run_id} (for {run.name})")
                continue
            for name in SERVED_FILES.get(module, ["run_metadata.json"]):
                if (directory / name).is_file() and not (output / module / "runs" / directory.name / name).is_file():
                    total += _copy(directory / name, output / module / "runs" / directory.name / name, keep_existing)
            copied.append(f"{module}/runs/{directory.name}")
    results = project / "evaluation" / "results"
    for path in sorted(results.glob("*.json")) if results.is_dir() else []:
        total += _copy(path, output / "evaluation" / "results" / path.name)  # small, refreshed each time
    manifest = {"source_project": str(project.resolve().name), "fusion_runs": sorted({c for c in copied if c.startswith("fusion/")}),
                "source_runs": sorted({c for c in copied if not c.startswith("fusion/")}), "missing_source_runs": missing,
                "review_audit_included": include_audit, "existing_files_kept": keep_existing, "bytes_copied": total}
    (output / "SERVING_DATA_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the stored runs the review workspace needs into a portable directory.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-v1", action="store_true", help="Also export superseded V1 Fusion runs.")
    parser.add_argument("--without-audit", action="store_true", help="Do not copy review_audit.sqlite (the workspace then starts with an empty audit trail).")
    parser.add_argument("--keep-existing", action="store_true",
                        help="Skip files already present in --output (used to seed the Docker data volume without overwriting its audit trails).")
    args = parser.parse_args()
    if args.output.resolve() == args.project_root.resolve():
        parser.error("--output must differ from the project root.")
    manifest = export(args.project_root, args.output, include_v1=args.include_v1, include_audit=not args.without_audit, keep_existing=args.keep_existing)
    print(json.dumps({k: v for k, v in manifest.items() if k != "source_runs"}, indent=2))
    return 1 if manifest["missing_source_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
