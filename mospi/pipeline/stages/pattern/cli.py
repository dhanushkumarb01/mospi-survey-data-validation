"""CLI for aggregate PLFS Pattern V1 evidence."""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
from .config import PatternParameters
from .engine import PatternEngine, PatternFailure, RunConfig

def main() -> int:
    parser=argparse.ArgumentParser(description="Generate FSU/group/temporal Pattern evidence for one prepared PLFS delivery.")
    parser.add_argument("--prepared-persons",type=Path,required=True);parser.add_argument("--output-root",type=Path,required=True);parser.add_argument("--run-id")
    parser.add_argument("--minimum-fsu-population",type=int,default=10);parser.add_argument("--minimum-reference-population",type=int,default=30);parser.add_argument("--minimum-valid-target-population",type=int,default=10);parser.add_argument("--minimum-temporal-history",type=int,default=2);parser.add_argument("--minimum-revisit-linked-population",type=int,default=10)
    parser.add_argument("--revisit-prepared-persons",type=Path);parser.add_argument("--revisit-statistical-run",type=Path)
    args=parser.parse_args(); params=PatternParameters(minimum_fsu_population=args.minimum_fsu_population,minimum_reference_population=args.minimum_reference_population,minimum_valid_target_population=args.minimum_valid_target_population,minimum_temporal_history=args.minimum_temporal_history,minimum_revisit_linked_population=args.minimum_revisit_linked_population)
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try: print(PatternEngine(RunConfig(args.prepared_persons,args.output_root,args.run_id,params,args.revisit_prepared_persons,args.revisit_statistical_run)).run())
    except (PatternFailure,ValueError) as error: logging.error("%s",error);return 2
    return 0
if __name__=="__main__": raise SystemExit(main())
