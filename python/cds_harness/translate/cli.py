"""CLI entrypoint for the CLOVER autoformalization translator.

Invocation::

    uv run python -m cds_harness.translate <path> [--output OUT.json]
                                                  [--pretty] [--smt-check]
                                                  [--logic QF_LRA]

``<path>`` may be a single ``*.txt`` guideline or a directory containing
guidelines + ``*.recorded.json`` sidecars (the directory walker mirrors
:func:`cds_harness.ingest.discover_payloads`).

The CLI prints a JSON array of records, one per guideline:

.. code-block:: json

    {
      "source_path": "data/guidelines/hypoxemia-trigger.txt",
      "doc_id": "hypoxemia-trigger",
      "tree": {...OnionLIRTree JSON...},
      "matrix": {...SmtConstraintMatrix JSON...},
      "smt_check": "sat" | "unsat" | "unknown" | null
    }

Errors derived from
:class:`cds_harness.translate.errors.TranslateError` exit with code ``1``;
missing-path errors exit with code ``2``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cds_harness.translate.clover import discover_translations
from cds_harness.translate.errors import TranslateError
from cds_harness.translate.smt_emitter import (
    DEFAULT_LOGIC,
    emit_smt,
    smt_sanity_check,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cds_harness.translate",
        description=(
            "Translate local clinical-guideline text into OnionL IR + SMT-LIBv2 "
            "constraint matrices via the CLOVER autoformalization pipeline."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="A *.txt guideline file or a directory of them (with *.recorded.json sidecars).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write records to this file (default: stdout).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON with 2-space indent (default: compact).",
    )
    parser.add_argument(
        "--smt-check",
        action="store_true",
        help="Run a sanity (check-sat) over each emitted matrix and include the result.",
    )
    parser.add_argument(
        "--logic",
        default=DEFAULT_LOGIC,
        help=f"SMT-LIBv2 logic to set in the preamble (default: {DEFAULT_LOGIC}).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.path.exists():
        print(f"error: path not found: {args.path}", file=sys.stderr)
        return 2

    records: list[dict[str, object]] = []
    try:
        for source_path, tree in discover_translations(args.path):
            matrix = emit_smt(tree, logic=args.logic)
            record: dict[str, object] = {
                "source_path": str(source_path),
                "doc_id": source_path.stem,
                "tree": tree.model_dump(mode="json"),
                "matrix": matrix.model_dump(mode="json"),
                "smt_check": smt_sanity_check(matrix) if args.smt_check else None,
            }
            records.append(record)
    except TranslateError as exc:
        print(f"error: translation failed: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    text = json.dumps(records, indent=indent, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    print(f"translated {len(records)} guideline(s)", file=sys.stderr)
    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = ["build_parser", "main", "run"]
