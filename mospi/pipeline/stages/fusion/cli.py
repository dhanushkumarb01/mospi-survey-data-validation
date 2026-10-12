"""CLI for strict, local MoSPI Fusion V1 runs."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import FusionParameters
from .engine import FusionEngine, FusionFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate and fuse existing validation evidence (MoSPI survey data validation platform) without recomputing source models.")
    parser.add_argument("--prepared-persons", type=Path, required=True)
    parser.add_argument("--statistical-run", type=Path, required=True)
    parser.add_argument("--contextual-run", type=Path, required=True)
    parser.add_argument("--ml-run", type=Path, required=True)
    parser.add_argument("--pattern-run", type=Path)
    parser.add_argument("--historical-run", type=Path)
    parser.add_argument("--integrity-run", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--override-rank-threshold", type=float, default=.995)
    parser.add_argument("--statistical-weight", type=float, default=.30)
    parser.add_argument("--contextual-weight", type=float, default=.20)
    parser.add_argument("--ml-weight", type=float, default=.25)
    parser.add_argument("--historical-weight", type=float, default=.25)
    args = parser.parse_args()
    parameters = FusionParameters(
        source_weights={"statistical": args.statistical_weight, "contextual": args.contextual_weight, "ml": args.ml_weight, "historical": args.historical_weight},
        override_rank_threshold=args.override_rank_threshold,
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        print(FusionEngine(RunConfig(args.prepared_persons, args.statistical_run, args.contextual_run, args.ml_run, args.output_root, args.pattern_run,
                                     args.run_id, parameters, args.historical_run, args.integrity_run)).run())
    except (FusionFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
