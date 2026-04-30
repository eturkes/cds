"""Entrypoint for ``python -m cds_harness.service`` and ``cds-harness-service``.

Boots the FastAPI app (:func:`cds_harness.service.app.create_app`) under
uvicorn. Host/port resolution honours the environment variables
``CDS_HARNESS_HOST`` (default ``127.0.0.1``) and ``CDS_HARNESS_PORT``
(default ``8081``), mirroring the Dapr ``--app-port`` wiring contract
documented in ADR-016 §5 and ADR-017 §3.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from cds_harness.service.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    create_app,
    resolve_host,
    resolve_port,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cds-harness-service",
        description=(
            "Run the CDS Phase 0 Python harness FastAPI service under uvicorn. "
            "Defaults pick up CDS_HARNESS_HOST / CDS_HARNESS_PORT from the env."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Bind address (default: $CDS_HARNESS_HOST or {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind port (default: $CDS_HARNESS_PORT or {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        help="uvicorn log level (default: info).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    host = args.host or resolve_host()
    port = args.port if args.port is not None else resolve_port()
    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=args.log_level,
        access_log=False,
        loop="asyncio",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    server.run()
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    sys.exit(run())


__all__ = ["main", "run"]
