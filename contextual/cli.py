"""CLI for the PLFS contextual categorical evidence layer."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .engine import ContextualEngine, ContextualFailure, RunConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate PLFS conditional categorical evidence using existing peer groups.")
    parser.add_argument("--prepared-persons", type=Path, required=True)
    parser.add_argument("--peer-group-run", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        destination = ContextualEngine(RunConfig(args.prepared_persons, args.peer_group_run, args.output_root, args.run_id)).run()
    except (ContextualFailure, ValueError) as error:
        logging.error("%s", error)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
