"""Directory-walk dispatcher for local telemetry sources.

Phase 0 enumerates ingestible files via a recursive directory walk
(no manifest file). Sidecar metadata files (``*.meta.json``) are
implicit and not yielded as standalone payloads.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from cds_harness.ingest.csv_loader import load_csv
from cds_harness.ingest.errors import IngestError
from cds_harness.ingest.json_loader import load_json
from cds_harness.schema import ClinicalTelemetryPayload

_SIDECAR_SUFFIX = ".meta.json"


def discover_payloads(
    root: Path,
) -> Iterator[tuple[Path, ClinicalTelemetryPayload]]:
    """Yield ``(source_path, payload)`` pairs for every ingestible file under ``root``.

    Recognised forms:

    * ``*.csv`` — paired with ``<stem>.meta.json`` (sidecar).
    * ``*.json`` — whole-envelope payload. Files ending in ``.meta.json``
      are treated as sidecars and skipped.

    Iteration order is deterministic (sorted by path).
    """
    root = Path(root)
    if not root.exists():
        raise IngestError(f"path not found: {root}")
    if root.is_file():
        yield root, _dispatch(root)
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".csv":
            yield path, load_csv(path)
        elif path.suffix == ".json" and not path.name.endswith(_SIDECAR_SUFFIX):
            yield path, load_json(path)


def _dispatch(path: Path) -> ClinicalTelemetryPayload:
    if path.suffix == ".csv":
        return load_csv(path)
    if path.suffix == ".json":
        if path.name.endswith(_SIDECAR_SUFFIX):
            raise IngestError(
                f"refusing to ingest sidecar metadata file directly: {path.name}"
            )
        return load_json(path)
    raise IngestError(f"unsupported file extension: {path.suffix!r} ({path.name})")


__all__ = ["discover_payloads"]
