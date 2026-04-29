"""Translator error hierarchy.

All translator errors derive from :class:`TranslateError` so the CLI can
convert them uniformly to a non-zero exit code.
"""

from __future__ import annotations


class TranslateError(ValueError):
    """Base class for all autoformalization-translation failures."""


class MissingFixtureError(TranslateError):
    """Raised when a recorded autoformalization fixture cannot be found for a doc_id."""


class InvalidGuidelineError(TranslateError):
    """Raised on a guideline whose recorded AST violates the source-span contract.

    Either the ``doc_id`` carried by an :class:`~cds_harness.schema.Atom`'s
    :class:`~cds_harness.schema.SourceSpan` does not match the source
    document, or the byte range falls outside the source's UTF-8 length, or
    the start/end ordering is inverted.
    """


class UnsupportedNodeError(TranslateError):
    """Raised when the SMT emitter encounters an OnionL node shape it cannot lower."""


class UnsupportedOpError(TranslateError):
    """Raised when a :class:`~cds_harness.schema.Relation` op is outside the OP map."""


__all__ = [
    "InvalidGuidelineError",
    "MissingFixtureError",
    "TranslateError",
    "UnsupportedNodeError",
    "UnsupportedOpError",
]
