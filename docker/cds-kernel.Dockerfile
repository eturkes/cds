# syntax=docker/dockerfile:1.7
# cds-kernel — Rust 1.95 axum service (Phase 1 cloud, Task 11.2, ADR-029).
#
# Multi-stage:
#   1. builder — rust:1.95-slim-bookworm + cargo build --release of the
#      `cds-kernel-service` bin (workspace single-bin target).
#   2. runtime — debian:bookworm-slim + libstdc++6 + libgomp1 + ca-certificates
#      + the kernel binary + Z3 + cvc5 (copied from the project-local
#      .bin/{z3,cvc5} staged by `just fetch-bins`).
#
# Per ADR-029: Lean is intentionally NOT in the image — Kimina is an external
# REST endpoint addressed via $CDS_KIMINA_URL (the in-cluster Kimina Service
# address is wired at 11.4 close-out; left unset here so /v1/recheck cleanly
# fast-fails until 11.4 wires it). reqwest carries `rustls + webpki-roots`
# in workspace deps, so no system CA bundle is required for outbound HTTPS;
# ca-certificates is included anyway as belt-and-suspenders for any future
# tooling that expects a system bundle.

ARG RUST_VERSION=1.95-slim-bookworm
ARG DEBIAN_VERSION=bookworm-slim

# ---- builder ----------------------------------------------------------------
FROM rust:${RUST_VERSION} AS builder

# pkg-config keeps the build surface explicit + minimal so any future
# bindgen-using crate fails loudly instead of pulling in a stale system header.
RUN apt-get update \
 && apt-get install --no-install-recommends -y pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Cargo manifests + sources. rust-toolchain.toml is included so rustup's
# auto-selection inside the image agrees with the workspace's pin
# (channel = "stable" — the rust:1.95-slim-bookworm image already provides
# 1.95.x stable, so this is a no-op in practice).
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates

RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    cargo build --release --bin cds-kernel-service \
 && cp /build/target/release/cds-kernel-service /usr/local/bin/cds-kernel-service

# ---- runtime ---------------------------------------------------------------
FROM debian:${DEBIAN_VERSION} AS runtime

# Z3 + cvc5 from the upstream GitHub releases are dynamically linked against
# libstdc++ + libgomp; debian:bookworm-slim does not ship libstdc++6 by
# default. ca-certificates is harmless belt-and-suspenders for outbound HTTPS.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        libstdc++6 \
        libgomp1 \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get clean

# Non-root: cds (uid 10001) — parity with cds-harness + cds-frontend.
RUN groupadd --system --gid 10001 cds \
 && useradd --system --uid 10001 --gid cds --no-create-home --shell /sbin/nologin cds

COPY --from=builder /usr/local/bin/cds-kernel-service /usr/local/bin/cds-kernel-service

# Solver binaries staged via `just fetch-bins` (z3 + cvc5). Mounted under
# /opt/cds/bin and PATH-prefixed so the kernel's `Command::new("z3")` /
# `Command::new("cvc5")` defaults work; CDS_Z3_PATH / CDS_CVC5_PATH are also
# set explicitly so per-request VerifyOptions overrides stay symmetric across
# self-hosted + cloud deployments (ADR-020 §5).
COPY .bin/z3   /opt/cds/bin/z3
COPY .bin/cvc5 /opt/cds/bin/cvc5
RUN chmod 0755 /opt/cds/bin/z3 /opt/cds/bin/cvc5

ENV PATH="/opt/cds/bin:${PATH}" \
    CDS_KERNEL_HOST=0.0.0.0 \
    CDS_KERNEL_PORT=8082 \
    CDS_Z3_PATH=/opt/cds/bin/z3 \
    CDS_CVC5_PATH=/opt/cds/bin/cvc5

USER cds
WORKDIR /opt/cds
EXPOSE 8082
ENTRYPOINT ["/usr/local/bin/cds-kernel-service"]
