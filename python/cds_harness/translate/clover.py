"""CLOVER pipeline driver — guideline text → :class:`OnionLIRTree`.

The driver is intentionally thin: it delegates the actual NL→AST work to
an :class:`~cds_harness.translate.adapter.AutoformalAdapter`, then wraps
the returned root in an :class:`OnionLIRTree` envelope (stamped with the
current ``SCHEMA_VERSION``) and **validates the source-span contract**
against the original UTF-8 bytes of the guideline.

Source-span contract (constraint C4, ADR-005, ADR-010 #6):

* Every :class:`Atom`'s :class:`SourceSpan` must satisfy
  ``0 <= start <= end <= len(text.encode("utf-8"))``.
* The :class:`SourceSpan`'s ``doc_id`` must equal the ``doc_id`` passed to
  the driver (and, by convention, the file stem of the source guideline).

Violations raise :class:`InvalidGuidelineError`. The driver also exposes
:func:`discover_translations` — a deterministic directory walk paralleling
``cds_harness.ingest.discover_payloads`` — so the CLI can stream every
``*.txt`` guideline under a directory through the same pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from cds_harness.schema import (
    SCHEMA_VERSION,
    Atom,
    IndicatorConstraint,
    OnionLIRTree,
    OnionLNode,
    Relation,
    Scope,
)
from cds_harness.translate.adapter import AutoformalAdapter, RecordedAdapter
from cds_harness.translate.errors import InvalidGuidelineError

GUIDELINE_SUFFIX = ".txt"
SIDECAR_SUFFIX = ".recorded.json"


def translate_guideline(
    *,
    doc_id: str,
    text: str,
    adapter: AutoformalAdapter,
) -> OnionLIRTree:
    """Lift guideline ``text`` into a validated :class:`OnionLIRTree`.

    Parameters
    ----------
    doc_id:
        Stable document identifier. Mirrored on every
        :class:`SourceSpan.doc_id` carried by the resulting tree.
    text:
        Raw guideline text. Used to bounds-check ``SourceSpan`` byte
        offsets; the adapter is free to ignore it (the recorded path
        does).
    adapter:
        Strategy that maps ``(doc_id, text)`` to the root
        :class:`OnionLNode`.

    Returns
    -------
    OnionLIRTree
        The wrapped, validated IR tree, stamped with the current
        ``SCHEMA_VERSION``.
    """
    root = adapter.formalize(doc_id=doc_id, text=text)
    tree = OnionLIRTree(schema_version=SCHEMA_VERSION, root=root)
    _validate_source_spans(tree.root, text=text, doc_id=doc_id)
    return tree


def translate_path(
    path: Path,
    adapter: AutoformalAdapter | None = None,
) -> OnionLIRTree:
    """Translate a single ``*.txt`` guideline file into an :class:`OnionLIRTree`.

    The default ``adapter`` is a :class:`RecordedAdapter` rooted at the
    parent directory of ``path``; this is the deterministic Phase 0
    behavior. Pass an explicit adapter to override (e.g. tests that swap
    in a recorded fixture from a different directory).
    """
    path = Path(path)
    if not path.is_file():
        raise InvalidGuidelineError(f"guideline not found: {path}")
    if path.suffix != GUIDELINE_SUFFIX:
        raise InvalidGuidelineError(
            f"unsupported guideline extension {path.suffix!r}; expected {GUIDELINE_SUFFIX!r}"
        )
    text = path.read_text(encoding="utf-8")
    doc_id = path.stem
    if adapter is None:
        adapter = RecordedAdapter(path.parent)
    return translate_guideline(doc_id=doc_id, text=text, adapter=adapter)


def discover_translations(
    path: Path,
    adapter: AutoformalAdapter | None = None,
) -> Iterator[tuple[Path, OnionLIRTree]]:
    """Yield ``(source_path, tree)`` for every guideline under ``path``.

    Mirrors :func:`cds_harness.ingest.discover_payloads`. ``path`` may be
    either a file or a directory. Iteration order is the sorted list of
    discovered guideline paths (lexicographic), so output is reproducible
    across runs and OSes.
    """
    path = Path(path)
    if path.is_file():
        yield path, translate_path(path, adapter=adapter)
        return
    if not path.is_dir():
        raise InvalidGuidelineError(f"path is neither a file nor a directory: {path}")

    if adapter is None:
        adapter = RecordedAdapter(path)

    for entry in sorted(path.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix != GUIDELINE_SUFFIX:
            # Skip recorded sidecars, READMEs, anything non-guideline.
            continue
        yield entry, translate_path(entry, adapter=adapter)


def _validate_source_spans(
    node: OnionLNode,
    *,
    text: str,
    doc_id: str,
) -> None:
    text_byte_len = len(text.encode("utf-8"))
    for atom in _walk_atoms(node):
        span = atom.source_span
        if span.doc_id != doc_id:
            raise InvalidGuidelineError(
                f"atom predicate={atom.predicate!r} span doc_id={span.doc_id!r} "
                f"does not match expected doc_id={doc_id!r}"
            )
        if not (0 <= span.start <= span.end <= text_byte_len):
            raise InvalidGuidelineError(
                f"atom predicate={atom.predicate!r} span [{span.start}, {span.end}) "
                f"is outside source bounds [0, {text_byte_len}]"
            )


def _walk_atoms(node: OnionLNode) -> Iterator[Atom]:
    if isinstance(node, Atom):
        yield node
    elif isinstance(node, Scope):
        for child in node.children:
            yield from _walk_atoms(child)
    elif isinstance(node, Relation):
        for arg in node.args:
            yield from _walk_atoms(arg)
    elif isinstance(node, IndicatorConstraint):
        yield from _walk_atoms(node.guard)
        yield from _walk_atoms(node.body)


__all__ = [
    "GUIDELINE_SUFFIX",
    "SIDECAR_SUFFIX",
    "discover_translations",
    "translate_guideline",
    "translate_path",
]
