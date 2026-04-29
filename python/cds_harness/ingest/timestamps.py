"""Strict RFC-3339 / ISO-8601 UTC wall-clock parsing + canonicalization.

ADR-010 fixes wall-clock strings as RFC-3339 UTC with an explicit ``Z``
suffix. Phase 0 ingestion enforces that contract at the boundary so the
downstream pipeline never sees naive datetimes, non-UTC offsets, or
locale-dependent formatting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cds_harness.ingest.errors import InvalidTimestampError

_CANONICAL_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def parse_utc_timestamp(raw: str) -> datetime:
    """Parse a strict RFC-3339 UTC timestamp string ending in ``Z``.

    Rejects naive datetimes, non-UTC offsets (e.g. ``+02:00``), and any
    string the standard library cannot decode via
    :meth:`datetime.fromisoformat`.
    """
    if not isinstance(raw, str):
        raise InvalidTimestampError(f"timestamp must be a string; got {type(raw).__name__}")
    if not raw.endswith("Z"):
        raise InvalidTimestampError(f"timestamp must end with 'Z' (UTC); got {raw!r}")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidTimestampError(f"unparseable timestamp {raw!r}: {exc}") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise InvalidTimestampError(f"timestamp must be UTC zero-offset; got {raw!r}")
    return dt


def canonicalize_utc(raw: str) -> str:
    """Validate and re-emit a timestamp in canonical microsecond-UTC form.

    Output shape: ``YYYY-MM-DDTHH:MM:SS.ffffffZ``. Inputs without a
    fractional component are padded to six microsecond digits so that
    byte-level diffing of two equivalent payloads succeeds.
    """
    dt = parse_utc_timestamp(raw)
    naive = dt.astimezone(UTC).replace(tzinfo=None)
    return naive.strftime(_CANONICAL_FMT) + "Z"


__all__ = ["canonicalize_utc", "parse_utc_timestamp"]
