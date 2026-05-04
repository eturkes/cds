# syntax=docker/dockerfile:1.7
# cds-frontend — SvelteKit adapter-node visualizer (Phase 1 cloud, Task 11.2,
# ADR-029).
#
# Multi-stage:
#   1. builder — oven/bun:1.3.13-alpine + `bun install --frozen-lockfile`
#      (honours frontend/bun.lock per ADR-022) + `bun run build`
#      (adapter-node emits frontend/build/index.js).
#   2. runtime — node:22-alpine + the build/ output + the full node_modules
#      tree from the builder stage (every dep currently lives in
#      `devDependencies` — see frontend/package.json — so a `--production`
#      install would yield an empty tree; the trade-off is image size vs
#      package.json refactor, and ADR-029 keeps it as-is for the foundation).
#
# Per ADR-029: bun for install + build (matches the project's bun.lock); node
# for runtime (adapter-node emits a node-runnable server, and `bun run` of
# adapter-node has known stalls — sveltejs/kit#15184).

ARG BUN_VERSION=1.3.13-alpine
ARG NODE_VERSION=22-alpine

# ---- builder ----------------------------------------------------------------
FROM oven/bun:${BUN_VERSION} AS builder

WORKDIR /build

# Lockfile-first cache layer: package.json / bun.lock change rarer than
# the SvelteKit source.
COPY frontend/package.json frontend/bun.lock frontend/bunfig.toml ./
RUN bun install --frozen-lockfile

# Now bring the source and run the production build. svelte-kit sync runs
# automatically as the `prepare` script during install; the build emits
# `build/index.js` (adapter-node) plus `build/handler.js` + assets.
COPY frontend ./
RUN bun run build

# ---- runtime ---------------------------------------------------------------
FROM node:${NODE_VERSION} AS runtime

# Non-root: cds (uid 10001) — parity with cds-harness + cds-kernel.
RUN addgroup --system --gid 10001 cds \
 && adduser --system --uid 10001 --ingroup cds --no-create-home --shell /sbin/nologin cds

WORKDIR /app
COPY --from=builder --chown=cds:cds /build/build         ./build
COPY --from=builder --chown=cds:cds /build/node_modules  ./node_modules
COPY --from=builder --chown=cds:cds /build/package.json  ./

ENV HOST=0.0.0.0 \
    PORT=3000 \
    NODE_ENV=production

USER cds
EXPOSE 3000
ENTRYPOINT ["node", "build"]
