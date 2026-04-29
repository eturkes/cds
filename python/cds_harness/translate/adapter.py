"""Autoformalization adapters.

The :class:`AutoformalAdapter` protocol is the seam between the deterministic
translator pipeline and any LLM-backed formalization stage (CLOVER +
NL2LOGIC, ADR-005). Phase 0 ships:

* :class:`RecordedAdapter` — fixture-driven, no network, no LLM. Looks up a
  pre-authored ``<doc_id>.recorded.json`` envelope alongside the source
  guideline. This is the only adapter exercised by the test gate.
* :class:`LiveAdapter` — placeholder that raises ``NotImplementedError``;
  swap in a real ``anthropic`` (or equivalent) client in a later phase
  alongside prompt-cache wiring.

The contract: ``formalize(*, doc_id, text) -> OnionLNode`` returns the
*root* node of the formalized AST. The pipeline driver
(:func:`cds_harness.translate.clover.translate_guideline`) wraps the result
in an :class:`OnionLIRTree` envelope with the current ``SCHEMA_VERSION``
and validates source-span byte ranges against ``text``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from cds_harness.schema import OnionLIRTree, OnionLNode
from cds_harness.translate.errors import MissingFixtureError, TranslateError


class AutoformalAdapter(Protocol):
    """Lift natural-language guideline text into an :class:`OnionLNode` root."""

    def formalize(self, *, doc_id: str, text: str) -> OnionLNode:
        """Return the root :class:`OnionLNode` of the formalized AST."""
        ...


class RecordedAdapter:
    """Deterministic adapter backed by pre-authored OnionL fixtures.

    Looks up ``<fixtures_dir>/<doc_id>.recorded.json`` and returns
    ``tree.root``. The file must validate as a complete
    :class:`OnionLIRTree` envelope; mismatches raise
    :class:`MissingFixtureError` (file not found) or :class:`TranslateError`
    (validation failure).

    Phase 0 swaps this in for the live LLM call so the translator gate is
    deterministic and offline.
    """

    SUFFIX: str = ".recorded.json"

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures_dir = Path(fixtures_dir).resolve()

    @property
    def fixtures_dir(self) -> Path:
        return self._fixtures_dir

    def fixture_path(self, doc_id: str) -> Path:
        return self._fixtures_dir / f"{doc_id}{self.SUFFIX}"

    def formalize(self, *, doc_id: str, text: str) -> OnionLNode:
        del text  # unused by the recorded adapter; kept for protocol parity
        path = self.fixture_path(doc_id)
        if not path.is_file():
            raise MissingFixtureError(f"no recorded fixture for doc_id={doc_id!r} at {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            tree = OnionLIRTree.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise TranslateError(
                f"recorded fixture {path} failed schema validation: {exc}"
            ) from exc
        return tree.root


class LiveAdapter:
    """Placeholder live-LLM adapter — wired in a later phase.

    Constructor accepts the future client handle so call sites can be
    threaded through the harness today; the call itself raises
    :class:`NotImplementedError` to make accidental use loud rather than
    silent.
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client

    def formalize(self, *, doc_id: str, text: str) -> OnionLNode:
        del doc_id, text
        raise NotImplementedError(
            "LiveAdapter is a Phase 0 placeholder; swap in a real LLM client "
            "(anthropic SDK or equivalent) before invoking."
        )


__all__ = ["AutoformalAdapter", "LiveAdapter", "RecordedAdapter"]
