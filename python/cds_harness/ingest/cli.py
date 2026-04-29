"""CLI entrypoint: walk a path and emit payload JSON to stdout or a file.

Invocation::

    uv run python -m cds_harness.ingest <path> [--output OUT.json] [--pretty]

The CLI prints a JSON array of ``{"source_path": ..., "payload": {...}}``
records (one per ingested file). Errors derived from
:class:`cds_harness.ingest.errors.IngestError` exit with code ``1``;
missing-path errors exit with code ``2``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cds_harness.ingest.errors import IngestError
from cds_harness.ingest.loader import discover_payloads


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cds_harness.ingest",
        description=(
            "Ingest local CSV/JSON telemetry sources into "
            "ClinicalTelemetryPayload JSON envelopes."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="File or directory containing CSV (+ sidecar) or JSON envelopes.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write payload(s) to this file (default: stdout).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with 2-space indent (default: compact).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    records: list[dict[str, object]] = []
    try:
        for source_path, payload in discover_payloads(args.path):
            records.append(
                {
                    "source_path": str(source_path),
                    "payload": payload.model_dump(mode="json"),
                }
            )
    except IngestError as exc:
        print(f"error: ingestion failed: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    text = json.dumps(records, indent=indent, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    print(f"ingested {len(records)} payload(s)", file=sys.stderr)
    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["build_parser", "main", "run"]
