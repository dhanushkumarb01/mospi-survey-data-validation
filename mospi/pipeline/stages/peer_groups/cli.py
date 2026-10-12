"""Command-line entry point for PLFS peer-group construction."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .engine import PeerGroupEngine, PeerGroupFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Build release-aware PLFS peer-group reference populations.")
    parser.add_argument("--prepared-persons", type=Path, required=True, help="Prepared persons Parquet from preprocessing.")
    parser.add_argument("--output-root", type=Path, required=True, help="Directory for a new immutable peer-group run.")
    parser.add_argument("--run-id", help="Optional deterministic output run identifier.")
    parser.add_argument("--minimum-group-size", type=int, default=30, help="Configurable V1 minimum eligible reference count (default: 30).")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        destination = PeerGroupEngine(RunConfig(args.prepared_persons, args.output_root, args.run_id, args.minimum_group_size)).run()
    except (PeerGroupFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
