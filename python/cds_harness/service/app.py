"""FastAPI application factory for the Phase 0 Python harness service.

The app exposes three endpoints:

* ``GET  /healthz``     — liveness probe; returns ``{"status": "ok", ...}``.
* ``POST /v1/ingest``   — accept either a JSON envelope (``format="json"``)
  or an in-memory CSV body (``format="csv"``); return the validated +
  canonicalized :class:`~cds_harness.schema.ClinicalTelemetryPayload`.
* ``POST /v1/translate`` — accept ``(doc_id, text, root, logic,
  smt_check)`` and return ``{"tree", "matrix", "smt_check"}``.

Internal harness errors (:class:`~cds_harness.ingest.errors.IngestError`,
:class:`~cds_harness.translate.errors.TranslateError`) lift to HTTP
``422`` so callers see a structured failure mode without leaking stack
traces. Pydantic validation errors are handled by FastAPI's default
``422`` machinery.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Final, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cds_harness import HARNESS_ID, PHASE
from cds_harness.ingest import IngestError, load_csv_text, load_json_envelope
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
    OnionLIRTree,
    OnionLNode,
    SmtConstraintMatrix,
)
from cds_harness.translate import (
    DEFAULT_LOGIC,
    TranslateError,
    emit_smt,
    smt_sanity_check,
    translate_guideline,
)

SERVICE_APP_ID: Final[str] = "cds-harness"
HEALTHZ_PATH: Final[str] = "/healthz"
INGEST_PATH: Final[str] = "/v1/ingest"
TRANSLATE_PATH: Final[str] = "/v1/translate"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8081

PORT_ENV: Final[str] = "CDS_HARNESS_PORT"
HOST_ENV: Final[str] = "CDS_HARNESS_HOST"


def resolve_port(default: int = DEFAULT_PORT) -> int:
    raw = os.environ.get(PORT_ENV)
    if raw is None or not raw.strip():
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV}={raw!r} is not an integer") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"{PORT_ENV}={port} is outside [1, 65535]")
    return port


def resolve_host(default: str = DEFAULT_HOST) -> str:
    return os.environ.get(HOST_ENV) or default


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _IngestJsonRequest(_StrictModel):
    format: Literal["json"]
    envelope: dict[str, Any] = Field(
        ...,
        description="Whole-envelope ClinicalTelemetryPayload JSON (matching the schema).",
    )


class _IngestCsvRequest(_StrictModel):
    format: Literal["csv"]
    csv_text: str = Field(..., description="Raw CSV body (header row required).")
    meta: dict[str, Any] = Field(
        ...,
        description="Sidecar metadata: a 'source' object plus optional 'events' list.",
    )
    file_label: str = Field(
        default="<inline.csv>",
        description="Diagnostic label surfaced in malformed-row error messages.",
    )


_IngestRequest = Annotated[
    _IngestJsonRequest | _IngestCsvRequest,
    Field(discriminator="format"),
]


class _IngestResponse(BaseModel):
    payload: ClinicalTelemetryPayload


class _TranslateRequest(_StrictModel):
    doc_id: str = Field(..., min_length=1)
    text: str = Field(..., description="UTF-8 guideline body (used for source-span validation).")
    root: OnionLNode = Field(..., description="Pre-formalized OnionL root node.")
    logic: str = Field(
        default=DEFAULT_LOGIC,
        description="SMT-LIBv2 logic for the emitter preamble (default: QF_LRA).",
    )
    smt_check: bool = Field(
        default=False,
        description="If true, run the in-process Z3 sanity check and report the verdict.",
    )


class _TranslateResponse(BaseModel):
    tree: OnionLIRTree
    matrix: SmtConstraintMatrix
    smt_check: Literal["sat", "unsat", "unknown"] | None = None


class _Healthz(BaseModel):
    status: Literal["ok"] = "ok"
    harness_id: str = HARNESS_ID
    phase: int = PHASE
    schema_version: str = SCHEMA_VERSION


class _InlineAdapter:
    """:class:`AutoformalAdapter` returning a pre-supplied root unchanged.

    The translator validates source-span byte ranges against ``text`` (see
    :func:`cds_harness.translate.clover.translate_guideline`); supplying
    the root inline keeps the Phase 0 contract intact while moving the
    formalization step off the local filesystem. Structural conformance
    to :class:`AutoformalAdapter` is asserted by the test suite.
    """

    def __init__(self, root: OnionLNode) -> None:
        self._root = root

    def formalize(self, *, doc_id: str, text: str) -> OnionLNode:
        del doc_id, text  # unused; kept for protocol parity
        return self._root


def _ingest(payload: _IngestRequest) -> _IngestResponse:
    try:
        if isinstance(payload, _IngestJsonRequest):
            canonical = load_json_envelope(payload.envelope)
        else:
            canonical = load_csv_text(
                payload.csv_text,
                payload.meta,
                file_label=payload.file_label,
            )
    except ValidationError as exc:
        raise IngestError(f"envelope failed schema validation: {exc.errors()!r}") from exc
    return _IngestResponse(payload=canonical)


def _translate(request: _TranslateRequest) -> _TranslateResponse:
    adapter = _InlineAdapter(root=request.root)
    tree = translate_guideline(
        doc_id=request.doc_id,
        text=request.text,
        adapter=adapter,
    )
    matrix = emit_smt(tree, logic=request.logic)
    verdict = smt_sanity_check(matrix) if request.smt_check else None
    return _TranslateResponse(tree=tree, matrix=matrix, smt_check=verdict)


def create_app() -> FastAPI:
    """Construct the FastAPI app. One instance per process; no globals beyond env."""
    app = FastAPI(
        title="CDS Phase 0 Python harness",
        version=SCHEMA_VERSION,
        description=(
            "JSON-over-TCP service for the CDS Phase 0 ingest + translate "
            "stages. Bound under Dapr as app-id 'cds-harness'."
        ),
    )

    @app.exception_handler(IngestError)
    async def _ingest_error_handler(_request: Request, exc: IngestError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "ingest_error", "detail": str(exc)},
        )

    @app.exception_handler(TranslateError)
    async def _translate_error_handler(
        _request: Request, exc: TranslateError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "translate_error", "detail": str(exc)},
        )

    @app.get(HEALTHZ_PATH, response_model=_Healthz)
    async def healthz() -> _Healthz:
        return _Healthz()

    @app.post(INGEST_PATH, response_model=_IngestResponse)
    async def ingest(request: _IngestRequest) -> _IngestResponse:
        try:
            return _ingest(request)
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    @app.post(TRANSLATE_PATH, response_model=_TranslateResponse)
    async def translate(request: _TranslateRequest) -> _TranslateResponse:
        try:
            return _translate(request)
        except TranslateError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    return app


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HEALTHZ_PATH",
    "INGEST_PATH",
    "SERVICE_APP_ID",
    "TRANSLATE_PATH",
    "create_app",
]
