"""CLI for the historical (cross-period) evidence layer."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .engine import HistoricalEngine, HistoricalFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare records with preceding periods of the same PLFS design period, and screen aggregate change.")
    parser.add_argument("--target-prepared-persons", type=Path, required=True)
    parser.add_argument("--reference-prepared-persons", type=Path, nargs="*", default=[],
                        help="Other releases of the SAME design period, earliest first (e.g. 2023-24 for a 2024 target).")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        print(HistoricalEngine(RunConfig(args.target_prepared_persons, tuple(args.reference_prepared_persons), args.output_root, args.run_id)).run())
    except (HistoricalFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
