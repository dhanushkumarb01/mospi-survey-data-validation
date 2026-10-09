"""Batch orchestration of every MoSPI layer for one prepared PLFS delivery.

    python -m pipeline.run --release 2024 --suffix v2_1

Each stage writes its own immutable run directory.  A stage whose directory
already exists is reused (never overwritten), so an interrupted batch resumes.
After every stage a quality gate (pipeline.qa) checks the output; a failed
gate stops the batch before fusion, so nothing is published from a broken or
degraded stage.  A timing/provenance/QA report is written to pipeline/runs/.

Inputs are the stored prepared runs; nothing already stored is rewritten.

A method change in one stage does not need the whole batch again:

    python -m pipeline.run --release 2024 --suffix v2_2 --reuse-suffix v2_1 --rerun ml,fusion

re-runs only the named stages under the new suffix and reuses the earlier
suffix's directories for every other stage (they are read, never modified).
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .qa import QAGateFailure, check_stage, prepared_record_count

LOGGER = logging.getLogger("MoSPI.pipeline")

# Release presets: the immutable inputs already prepared in this repository.
# ``peer`` names the peer-group run to use; when it does not exist it is built
# (peer-group specification v1.1: pre-2025 quarter boundary, casual wages).
PRESETS = {
    "2023_24": {"prepared": "preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet",
                "revisit_prepared": "preprocessing/runs/2023_24_revisit_final_2023_24_revisit/prepared_persons.parquet",
                "revisit_peer": "peer_groups/runs/2023_24_revisit_2023_24_revisit_v1",
                "history": []},
    "2024": {"prepared": "preprocessing/runs/2024_first_visit_final_2024_first/prepared_persons.parquet",
             # Same pre-2025 design period; Jul-Dec 2023 quarters supply history.
             "history": ["preprocessing/runs/2023_24_first_visit_final_2023_24_first/prepared_persons.parquet"]},
    "2025": {"prepared": "preprocessing/runs/2025_first_visit_final_2025_first/prepared_persons.parquet",
             "history": []},  # post-2025: never compared with pre-2025 releases
}
STAGES = ("peer", "statistical", "contextual", "ml", "pattern", "historical", "integrity", "fusion")


@dataclass
class Inputs:
    prepared: Path
    peer: Path | None = None
    contextual: Path | None = None
    history: list[Path] = field(default_factory=list)
    revisit_prepared: Path | None = None
    revisit_peer: Path | None = None


def _dir(root: Path, metadata_path: Path, run_id: str) -> Path:
    meta = json.loads((metadata_path.parent / "run_metadata.json").read_text(encoding="utf-8"))
    return root / f"{meta['release']}_{meta['observation']}_{run_id}"


def code_version() -> str:
    """Git commit of the code that produced a run (or 'unknown' outside a repository)."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10).stdout.strip()
        return commit + ("+uncommitted-changes" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def run_pipeline(inputs: Inputs, suffix: str, *, roots: Path = Path("."), stages: tuple[str, ...] | None = None,
                 fusion_root: Path | None = None, contextual_rebuild: bool = True, qa: bool = True,
                 qa_baselines: dict[str, Path] | None = None, reuse_suffix: str | None = None,
                 rerun: tuple[str, ...] = ()) -> dict[str, object]:
    """Run (or reuse) every stage, gate each output, and return directories, timing and QA results."""
    from contextual.engine import ContextualEngine, RunConfig as ContextualConfig
    from fusion.engine import FusionEngine, RunConfig as FusionConfig
    from historical.engine import HistoricalEngine, RunConfig as HistoricalConfig
    from integrity.engine import RunConfig as IntegrityConfig, run as run_integrity
    from ml.engine import MLEngine, RunConfig as MLConfig
    from pattern.engine import PatternEngine, RunConfig as PatternConfig
    from peer_groups.engine import PeerGroupEngine, RunConfig as PeerConfig
    from statistical.engine import RunConfig as StatConfig, StatisticalEngine

    wanted = stages or STAGES
    out: dict[str, object] = {"timing_seconds": {}, "qa": {}}
    run_id = f"{suffix}"
    records = prepared_record_count(inputs.prepared)
    baselines = qa_baselines or {}

    def stage(name: str, root: Path, builder) -> Path:
        destination = _dir(root, inputs.prepared, run_id)
        if not destination.exists() and reuse_suffix and name not in rerun and _dir(root, inputs.prepared, reuse_suffix).exists():
            destination = _dir(root, inputs.prepared, reuse_suffix)   # unchanged stage: reuse the earlier run
        if destination.exists():
            if not (destination / "run_metadata.json").is_file():
                raise RuntimeError(f"{destination} exists but has no run_metadata.json (an interrupted run). Inspect and remove it before resuming.")
            LOGGER.info("reuse %s %s", name, destination)
            out["timing_seconds"][name] = "reused"
            result = destination
        else:
            if name not in wanted:
                raise RuntimeError(f"Stage {name} has no existing run {destination} and was not requested")
            started = time.perf_counter()
            LOGGER.info("run %s", name)
            result = builder()
            out["timing_seconds"][name] = round(time.perf_counter() - started, 1)
        if qa and name != "peer":
            out["qa"][name] = check_stage(name, Path(result), records, baseline=baselines.get(name))
        return Path(result)

    if rerun and not set(rerun) <= set(STAGES):
        raise ValueError(f"Unknown stage(s) to re-run: {sorted(set(rerun) - set(STAGES))}")
    peer = inputs.peer or _dir(roots / "peer_groups/runs", inputs.prepared, run_id)
    if inputs.peer is None:
        peer = stage("peer", roots / "peer_groups/runs", lambda: PeerGroupEngine(PeerConfig(inputs.prepared, roots / "peer_groups/runs", run_id)).run())
    out["peer"] = peer
    revisit = {}
    if inputs.revisit_prepared and inputs.revisit_peer:
        revisit = {"revisit_prepared_person_path": inputs.revisit_prepared, "revisit_peer_group_run_path": inputs.revisit_peer}
    out["statistical"] = stage("statistical", roots / "statistical/runs",
                               lambda: StatisticalEngine(StatConfig(inputs.prepared, peer, roots / "statistical/runs", run_id, **revisit)).run())
    if inputs.contextual and not contextual_rebuild:
        out["contextual"] = inputs.contextual
    else:
        out["contextual"] = stage("contextual", roots / "contextual/runs", lambda: ContextualEngine(ContextualConfig(inputs.prepared, peer, roots / "contextual/runs", run_id)).run())
    out["ml"] = stage("ml", roots / "ml/runs", lambda: MLEngine(MLConfig(inputs.prepared, peer, roots / "ml/runs", run_id, history=tuple(inputs.history))).run())
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
    parser.add_argument("--suffix", required=True, help="Run-id suffix for every new stage directory, e.g. v2_1.")
    parser.add_argument("--no-qa", action="store_true", help="Skip the quality gates (not recommended).")
    parser.add_argument("--reuse-suffix", help="Reuse this earlier suffix's stage runs for every stage not named in --rerun.")
    parser.add_argument("--rerun", default="", help="Comma-separated stages to run afresh under --suffix (with --reuse-suffix), e.g. ml,fusion.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    preset = PRESETS[args.release]
    inputs = Inputs(Path(preset["prepared"]), Path(preset["peer"]) if preset.get("peer") else None, None, [Path(p) for p in preset["history"]],
                    Path(preset["revisit_prepared"]) if preset.get("revisit_prepared") else None,
                    Path(preset["revisit_peer"]) if preset.get("revisit_peer") else None)
    started = time.perf_counter()
    rerun = tuple(x.strip() for x in args.rerun.split(",") if x.strip())
    report: dict[str, object] = {"release": args.release, "suffix": args.suffix, "code_version": code_version(),
                                 "reuse_suffix": args.reuse_suffix, "rerun": list(rerun)}
    try:
        result = run_pipeline(inputs, args.suffix, qa=not args.no_qa, reuse_suffix=args.reuse_suffix, rerun=rerun)
    except QAGateFailure as error:
        report.update({"status": "FAILED_QA_GATE", "error": str(error)})
        _write_report(args, report)
        LOGGER.error("%s", error)
        return 2
    report.update({"status": "COMPLETED", "finished_utc": datetime.now(timezone.utc).isoformat(), "total_seconds": round(time.perf_counter() - started, 1),
                   **{k: str(v) for k, v in result.items() if k not in ("timing_seconds", "qa")},
                   "timing_seconds": result["timing_seconds"], "qa": result["qa"]})
    _write_report(args, report)
    print(json.dumps(report, indent=2, default=str))
    return 0


def _write_report(args, report: dict[str, object]) -> None:
    folder = Path("pipeline/runs"); folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{args.release}_{args.suffix}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
