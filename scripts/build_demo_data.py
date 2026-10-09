"""Build a SYNTHETIC demonstration data directory for the hosted review-only workspace.

    python scripts/build_demo_data.py --output demo-data

It writes the small synthetic delivery used by the test suite (no real
respondent, household or FSU), runs the unchanged batch pipeline on it in a
temporary directory, and copies only the files the review workspace reads
(scripts/export_serving_data.py) into ``--output``.  No audit trail is
copied.  The manifest is marked ``"synthetic": true`` so the workspace shows
a "synthetic demonstration data" notice on every page.

The real project data are never read.  An existing ``--output`` is refused
unless it is an earlier demo directory (``--replace``), so approved data
cannot be overwritten by accident.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.run import Inputs, run_pipeline  # noqa: E402
from pipeline.tests.synthetic import write_delivery  # noqa: E402
from scripts.export_serving_data import export  # noqa: E402

NOTICE = ("Synthetic demonstration data. Every record, household and FSU shown here was generated for testing; "
          "none is a PLFS respondent, and the figures say nothing about any real area.")


def build(output: Path, *, replace: bool = False, label: str = "demo") -> dict[str, object]:
    manifest_path = output / "SERVING_DATA_MANIFEST.json"
    if output.exists() and any(output.iterdir()):
        previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        if not (replace and previous.get("synthetic") is True):
            raise SystemExit(f"{output} is not empty. Use --replace only for an earlier synthetic demo directory.")
        shutil.rmtree(output)
    with tempfile.TemporaryDirectory(prefix="mospi-demo-") as scratch:
        root = Path(scratch)
        # Named <release>_<observation>_<run_id> so the serving layer finds it as the run's preparation run.
        prepared, _ = write_delivery(root / "preprocessing" / "runs" / "2024_first_visit_synthetic-prep")
        run_pipeline(Inputs(prepared), label, roots=root)
        manifest = export(root, output, include_v1=False, include_audit=False)
    manifest.update({"synthetic": True, "notice": NOTICE, "source_project": "synthetic delivery (pipeline/tests/synthetic.py)"})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a synthetic demonstration data directory for the review-only workspace.")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "demo-data")
    parser.add_argument("--replace", action="store_true", help="Replace an earlier synthetic demo directory at --output.")
    args = parser.parse_args()
    manifest = build(args.output, replace=args.replace)
    print(json.dumps({k: v for k, v in manifest.items() if k != "source_runs"}, indent=2))
    return 1 if manifest["missing_source_runs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
