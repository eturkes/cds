# syntax=docker/dockerfile:1.7
# cds-harness — Python 3.12 FastAPI service (Phase 1 cloud, Task 11.2, ADR-029).
#
# Multi-stage:
#   1. builder — python:3.12-slim-bookworm + uv (pinned), syncs the venv from
#      pyproject.toml + uv.lock with `--no-dev --frozen --no-install-project`,
#      then installs the project against the copied source.
#   2. runtime — python:3.12-slim-bookworm + the synced venv only, non-root.
#
# Per ADR-029 §"Why slim, not distroless": the runtime stays on
# `python:3.12-slim-bookworm` instead of `gcr.io/distroless/cc-debian12`
# because uv's managed Python interpreter has C-extension dependencies
# (z3-solver, pydantic-core) whose libstdc++ + libc symbol tables don't
# round-trip cleanly into distroless without per-build symlink curation.
# Slim bookworm is the conservative pin; revisit at Phase 2 if image-size
# regression motivates it.

ARG PYTHON_VERSION=3.12-slim-bookworm
ARG UV_VERSION=0.11.8

# ---- builder ----------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder

# Pin uv via the official distroless ghcr.io/astral-sh/uv image (Plan §10
# step 4 web-search 2026-05-04: astral-sh/uv canonical container pinning).
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Lockfile-first for cache friendliness: dep changes happen rarer than source
# edits, so the dep-only `uv sync` layer caches across most code-only rebuilds.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

# Source + project install.
COPY python ./python
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen

# ---- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runtime

# Non-root: cds (uid 10001) — parity with cds-kernel + cds-frontend images.
RUN groupadd --system --gid 10001 cds \
 && useradd --system --uid 10001 --gid cds --no-create-home --shell /sbin/nologin cds

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CDS_HARNESS_HOST=0.0.0.0 \
    CDS_HARNESS_PORT=8081

USER cds
WORKDIR /opt/venv
EXPOSE 8081
ENTRYPOINT ["cds-harness-service"]
