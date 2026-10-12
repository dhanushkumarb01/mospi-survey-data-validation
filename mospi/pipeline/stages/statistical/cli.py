"""CLI for the PLFS Statistical Evidence Layer."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import StatisticalParameters
from .engine import RunConfig, StatisticalEngine, StatisticalFailure


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate robust statistical evidence inside existing PLFS peer groups.")
    parser.add_argument("--prepared-persons", type=Path, required=True)
    parser.add_argument("--peer-group-run", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--lower-tail-quantile", type=float, default=.05)
    parser.add_argument("--upper-tail-quantile", type=float, default=.95)
    parser.add_argument("--minimum-revisit-change-group-size", type=int, default=30)
    parser.add_argument("--revisit-prepared-persons", type=Path)
    parser.add_argument("--revisit-peer-group-run", type=Path)
    args = parser.parse_args()
    parameters = StatisticalParameters(args.lower_tail_quantile, args.upper_tail_quantile, args.minimum_revisit_change_group_size)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        destination = StatisticalEngine(RunConfig(args.prepared_persons, args.peer_group_run, args.output_root, args.run_id, parameters, args.revisit_prepared_persons, args.revisit_peer_group_run)).run()
    except (StatisticalFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
