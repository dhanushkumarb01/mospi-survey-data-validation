"""Command-line entry point for deterministic PLFS preparation."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import CONTRACTS
from .pipeline import PLFSPreprocessor, PreprocessingFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare one documented PLFS release without altering raw data.")
    parser.add_argument("--input-root", type=Path, required=True, help="Project/data root containing the release folders")
    parser.add_argument("--output-root", type=Path, required=True, help="Directory for a new immutable run folder")
    parser.add_argument("--contract", choices=sorted(CONTRACTS), required=True)
    parser.add_argument("--run-id", help="Optional deterministic run identifier")
    parser.add_argument("--no-prepared-data", action="store_true", help="Run all validation/reporting without writing Parquet prepared tables")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        destination = PLFSPreprocessor(RunConfig(args.input_root, args.output_root, args.contract, args.run_id, write_prepared_data=not args.no_prepared_data)).run()
    except PreprocessingFailure as error:
        logging.error("%s", error)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
