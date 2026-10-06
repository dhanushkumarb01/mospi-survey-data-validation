"""Batch orchestration of every MoSPI layer for one prepared PLFS delivery.

    python -m pipeline.run --release 2024 --suffix v2

Each stage writes its own immutable run directory.  A stage whose directory
already exists is reused (never overwritten), so an interrupted batch resumes.
Peer groups and contextual evidence are reused when their method is
unchanged.  A timing/provenance report is written to pipeline/runs/.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("MoSPI.pipeline")

# Release presets: the immutable inputs already prepared in this repository.
PRESETS = {
    "2023_24": {"prepared": "preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet",
                "peer": "peer_groups/runs/2023_24_first_visit_2023_24_first_v1",
                "contextual": "contextual/runs/2023_24_first_visit_2023_24_first_v1_final",
                "revisit_prepared": "preprocessing/runs/2023_24_revisit_final_2023_24_revisit/prepared_persons.parquet",
                "revisit_peer": "peer_groups/runs/2023_24_revisit_2023_24_revisit_v1",
                "history": []},
    "2024": {"prepared": "preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet",
             "peer": "peer_groups/runs/2024_first_visit_2024_first_v1",
             "contextual": "contextual/runs/2024_first_visit_2024_first_v1_final",
             # Same pre-2025 design period; Jul-Dec 2023 quarters supply history.
             "history": ["preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet"]},
    "2025": {"prepared": "preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet",
             "peer": "peer_groups/runs/2025_first_visit_2025_first_v1",
             "contextual": "contextual/runs/2025_first_visit_2025_first_v1_final",
             "history": []},  # post-2025: never compared with pre-2025 releases
}


@dataclass
class Inputs:
    prepared: Path
    peer: Path
    contextual: Path | None = None
    history: list[Path] = field(default_factory=list)
    revisit_prepared: Path | None = None
    revisit_peer: Path | None = None


def _dir(root: Path, metadata_path: Path, run_id: str) -> Path:
    meta = json.loads((metadata_path.parent / "run_metadata.json").read_text(encoding="utf-8"))
    return root / f"{meta['release']}_{meta['observation']}_{run_id}"


def run_pipeline(inputs: Inputs, suffix: str, *, roots: Path = Path("."), stages: tuple[str, ...] | None = None,
                 fusion_root: Path | None = None, contextual_rebuild: bool = False) -> dict[str, object]:
    """Run (or reuse) every stage; return the directories and per-stage timing."""
    from contextual.engine import ContextualEngine, RunConfig as ContextualConfig
    from fusion.engine import FusionEngine, RunConfig as FusionConfig
    from historical.engine import HistoricalEngine, RunConfig as HistoricalConfig
    from integrity.engine import RunConfig as IntegrityConfig, run as run_integrity
    from ml.engine import MLEngine, RunConfig as MLConfig
    from pattern.engine import PatternEngine, RunConfig as PatternConfig
    from statistical.engine import RunConfig as StatConfig, StatisticalEngine

    wanted = stages or ("statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion")
    out: dict[str, object] = {"timing_seconds": {}}
    run_id = f"{suffix}"

    def stage(name: str, root: Path, builder) -> Path:
        destination = _dir(root, inputs.prepared, run_id)
        if destination.exists():
            if not (destination / "run_metadata.json").is_file():
                raise RuntimeError(f"{destination} exists but has no run_metadata.json (an interrupted run). Inspect and remove it before resuming.")
            LOGGER.info("reuse %s %s", name, destination)
            out["timing_seconds"][name] = "reused"
            return destination
        if name not in wanted:
            raise RuntimeError(f"Stage {name} has no existing run {destination} and was not requested")
        started = time.perf_counter()
        LOGGER.info("run %s", name)
        result = builder()
        out["timing_seconds"][name] = round(time.perf_counter() - started, 1)
        return result

    revisit = {}
    if inputs.revisit_prepared and inputs.revisit_peer:
        revisit = {"revisit_prepared_person_path": inputs.revisit_prepared, "revisit_peer_group_run_path": inputs.revisit_peer}
    out["statistical"] = stage("statistical", roots / "statistical/runs",
                               lambda: StatisticalEngine(StatConfig(inputs.prepared, inputs.peer, roots / "statistical/runs", run_id, **revisit)).run())
    if inputs.contextual and not contextual_rebuild:
        out["contextual"] = inputs.contextual
    else:
        out["contextual"] = stage("contextual", roots / "contextual/runs", lambda: ContextualEngine(ContextualConfig(inputs.prepared, inputs.peer, roots / "contextual/runs", run_id)).run())
    out["ml"] = stage("ml", roots / "ml/runs", lambda: MLEngine(MLConfig(inputs.prepared, inputs.peer, roots / "ml/runs", run_id)).run())
    pattern_revisit = {}
    if inputs.revisit_prepared and revisit:
        pattern_revisit = {"revisit_prepared_person_path": inputs.revisit_prepared, "revisit_statistical_run_path": out["statistical"]}
    out["pattern"] = stage("pattern", roots / "pattern/runs", lambda: PatternEngine(PatternConfig(inputs.prepared, roots / "pattern/runs", run_id, **pattern_revisit)).run())
    out["historical"] = stage("historical", roots / "historical/runs",
                              lambda: HistoricalEngine(HistoricalConfig(inputs.prepared, tuple(inputs.history), roots / "historical/runs", run_id)).run())
    out["integrity"] = stage("integrity", roots / "integrity/runs", lambda: run_integrity(IntegrityConfig(inputs.prepared, roots / "integrity/runs", run_id=run_id)))
    fusion_root = fusion_root or roots / "fusion/runs"
    out["fusion"] = stage("fusion", fusion_root, lambda: FusionEngine(FusionConfig(
        inputs.prepared, Path(out["statistical"]), Path(out["contextual"]), Path(out["ml"]), fusion_root, Path(out["pattern"]), run_id,
        historical_run=Path(out["historical"]), integrity_run=Path(out["integrity"]))).run())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run every validation layer of the MoSPI survey data validation platform for one release (batch processing).")
    parser.add_argument("--release", choices=sorted(PRESETS), required=True)
    parser.add_argument("--suffix", required=True, help="Run-id suffix for every new stage directory, e.g. v2.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    preset = PRESETS[args.release]
    inputs = Inputs(Path(preset["prepared"]), Path(preset["peer"]), Path(preset["contextual"]), [Path(p) for p in preset["history"]],
                    Path(preset["revisit_prepared"]) if preset.get("revisit_prepared") else None,
                    Path(preset["revisit_peer"]) if preset.get("revisit_peer") else None)
    started = time.perf_counter()
    result = run_pipeline(inputs, args.suffix)
    report = {"release": args.release, "suffix": args.suffix, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "total_seconds": round(time.perf_counter() - started, 1), **{k: str(v) for k, v in result.items() if k != "timing_seconds"},
              "timing_seconds": result["timing_seconds"]}
    folder = Path("pipeline/runs"); folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{args.release}_{args.suffix}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
