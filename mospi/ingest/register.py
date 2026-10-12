"""Register a delivery that already sits on this server (for example under data/raw), so periodic checks can
fingerprint it and a changed delivery can be validated again (operation B).  The files are read, never copied or changed.

    python -m mospi.ingest.register --contract 2024_first --input-root data/raw [--synthetic] [--preflight]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from mospi.db.connection import Database
from mospi.pipeline.stages.preprocessing.config import CONTRACTS

from .service import Operations, OperationError
from .settings import UPLOADABLE_CONTRACTS
from .storage import fingerprint_file, new_id

SYSTEM_USER = {"name": "system", "role": "admin"}


def register_delivery(ops: Operations, *, contract: str, input_root: Path, synthetic: bool, user: dict[str, Any] = SYSTEM_USER,
                      run_preflight: bool = True) -> dict[str, Any]:
    if contract not in UPLOADABLE_CONTRACTS:
        raise OperationError(f"Choose one of: {', '.join(UPLOADABLE_CONTRACTS)}.")
    c = CONTRACTS[contract]
    input_root = Path(input_root).resolve()
    paths = {level: c.file_path(input_root, level) for level in ("household", "person")}
    missing = [str(p.relative_to(input_root)) for p in paths.values() if not p.is_file()]
    if missing:
        raise OperationError("Delivery files not found: " + ", ".join(missing), 404)
    dataset_id = new_id()
    with ops.db.transaction() as connection:
        connection.execute("""INSERT INTO datasets (dataset_id, contract_name, release, observation, source, data_class, status, input_root, created_by,
                              created_by_verified) VALUES (%s, %s, %s, %s, 'REGISTERED_PATH', %s, 'RECEIVING', %s, %s, TRUE)""",
                           (dataset_id, contract, c.release, c.observation, "SYNTHETIC" if synthetic else "INTERNAL_REAL", str(input_root), user["name"]))
        for level, path in paths.items():
            info = fingerprint_file(path)
            connection.execute("""INSERT INTO dataset_files (file_id, dataset_id, level, display_name, relative_path, size_bytes, sha256, content_fingerprint,
                                  encoding, stored_path, mtime_ns) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                               (new_id(), dataset_id, level, path.name, path.relative_to(input_root).as_posix(), info["size_bytes"], info["sha256"],
                                info["content_fingerprint"], info["encoding"] + ("+nul" if info["nul_bytes"] else ""), str(path), info["mtime_ns"]))
        ops.audit.append_operation("DATASET_REGISTERED", subject=dataset_id, actor=user["name"], actor_authenticated=True, actor_role=user.get("role"),
                                   connection=connection, details={"contract": contract, "files": [p.name for p in paths.values()]})
    return ops.preflight(dataset_id, profile_id=None, user=user) if run_preflight else ops.dataset(dataset_id)


def main() -> int:
    from mospi.db.connection import database_from_env
    parser = argparse.ArgumentParser(description="Register a delivery already on this server for periodic checks and re-validation.")
    parser.add_argument("--contract", choices=UPLOADABLE_CONTRACTS, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    args = parser.parse_args()
    db: Database | None = database_from_env(application_name="mospi-register")
    if db is None:
        print("error: MOSPI_DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        dataset = register_delivery(Operations(db), contract=args.contract, input_root=args.input_root, synthetic=args.synthetic,
                                    run_preflight=not args.no_preflight)
    except OperationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print({k: dataset.get(k) for k in ("dataset_id", "status", "contract_name", "record_counts")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
