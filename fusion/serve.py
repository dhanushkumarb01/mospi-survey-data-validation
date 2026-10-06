"""Start the MoSPI survey data validation review workspace.

Every option can also be set by environment variable (used by the Docker image):
MOSPI_FUSION_ROOT, MOSPI_PROJECT_ROOT, MOSPI_USERS_FILE, MOSPI_HOST, MOSPI_PORT.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from .api import create_app

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the MoSPI survey data validation review workspace.")
    parser.add_argument("--fusion-root", type=Path, default=_env_path("MOSPI_FUSION_ROOT") or Path("fusion/runs"))
    parser.add_argument("--project-root", type=Path, default=_env_path("MOSPI_PROJECT_ROOT"),
                        help="Directory holding preprocessing/, statistical/, contextual/, ml/ and pattern/ runs (default: two levels above --fusion-root).")
    parser.add_argument("--users-file", type=Path, default=_env_path("MOSPI_USERS_FILE"),
                        help="Optional JSON of users {name, role, token_sha256}; when given, every /api request needs a bearer token.")
    parser.add_argument("--host", default=os.environ.get("MOSPI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MOSPI_PORT", "8000")))
    args = parser.parse_args()
    if args.host not in LOCAL_HOSTS and args.users_file is None:
        # Inside a container the server must listen on the container interface; whether that is
        # reachable beyond this computer is decided by the host port mapping (docker-compose.yml
        # publishes on 127.0.0.1 only).  This is an explicit opt-in, never a default.
        if os.environ.get("MOSPI_CONTAINER") == "1":
            logging.getLogger("uvicorn.error").warning(
                "Listening on %s without authentication (MOSPI_CONTAINER=1). Publish the port on 127.0.0.1 only, "
                "or supply MOSPI_USERS_FILE before exposing it to a network.", args.host)
        else:
            parser.error("Refusing to listen beyond this computer without --users-file authentication.")
    uvicorn.run(create_app(args.fusion_root, args.project_root, args.users_file), host=args.host, port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
