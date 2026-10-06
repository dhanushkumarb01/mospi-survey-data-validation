"""Command-line interface for the separate PLFS ML evidence components."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .engine import MLEngine, MLFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate separate PLFS ML anomaly evidence; never corrections or error probabilities.")
    parser.add_argument("--prepared-persons", type=Path, required=True)
    parser.add_argument("--peer-group-run", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        print(MLEngine(RunConfig(args.prepared_persons, args.peer_group_run, args.output_root, args.run_id)).run())
    except (MLFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
