# `zk-kernel-guest` — Risc0 zkVM guest program (Phase 1, Task 12.3b1 body fill)

This crate is the **Risc0 zkVM guest program** for the CDS ZKSMT
post-quantum proof attestation axis. It is compiled for the
`riscv32im-risc0-zkvm-elf` target via the cargo-risczero cross-compiler
(`just fetch-zk` stages cargo-risczero v3.0.5 under `.bin/.zk/`;
`cargo risczero install` provisions the cross-compiler — Task 12.3b2
operator step) and executed inside the zkVM by Risc0's
`default_prover().prove(env, GUEST_ELF)` call site (host-side fill in
`crates/zk_kernel/src/prove.rs::prove`, Task 12.3b1 — this commit).

## Why this crate is excluded from the workspace

`crates/zk_kernel/guest/` is **not** a workspace member — the root
`Cargo.toml` lists it under `[workspace] exclude`. Two reasons:

1. **Toolchain isolation.** `cargo check --workspace` runs against the
   host target (`x86_64-unknown-linux-gnu`); pulling the guest in
   would either break the workspace build (when the host tries to
   link `risc0-zkvm`'s guest-only symbols) or silently mask guest-
   specific build errors.
2. **Foundation/usage split.** Per the FHIR-axis "first kernel-side
   consumer" precedent (ADR-025 §3 + §8) and the ZKSMT-axis split
   precedent (ADR-032 §5 → ADR-033 §3 → ADR-034 §3 → ADR-035 §3),
   heavy dependencies land at the first call site that actually
   consumes them. The guest body, the host `risc0-zkvm` dep, and the
   guest `risc0-zkvm` dep all landed together at Task 12.3b1; the
   workspace exclusion keeps the host build cost bounded by the
   `cargo check` graph (the guest's RISC-V cross-compile is operator-
   triggered).

## Task 12.3b1 body fill (this commit)

| Artefact                  | Status                                                |
| ------------------------- | ----------------------------------------------------- |
| `Cargo.toml` `[dependencies]` | `risc0-zkvm = "=3.0.5"` (`default-features = false`, `std`), `serde`, `serde_json` |
| `src/main.rs` body        | `env::read::<Vec<u8>>()` → ZKSM header validation → `serde_json::from_slice::<SmtTrace>` → minimal Alethe replay subset checker → `env::commit(&(theory_signature, muc_labels))` |
| Workspace exclusion       | Root `Cargo.toml` `[workspace] exclude` carries this path (unchanged) |
| `fetch-zk` install logic  | Sha-pinned `cargo-risczero` v3.0.5 Linux x86_64 tarball download (ADR-035 §2 — bumped from v3.0.1) |

## Schema duplication (host ↔ guest)

`SmtTrace` + the `WITNESS_*` constants are duplicated from
`crates/zk_kernel/src/witness.rs` because the guest crate is
workspace-excluded and cannot depend on the host `zk-kernel` crate
(which pulls `risc0-zkvm/prove`, a host-only feature that breaks for
the `riscv32im-risc0-zkvm-elf` target). The duplication is bounded by
ADR-033's wire-format invariant: any change to `SmtTrace` or the
header layout requires coordinated edits to BOTH sites + a fresh ADR.
Future ADR-?? may extract a tiny `witness-schema` shared crate (no
Risc0 deps) if drift becomes a maintenance burden — not done at
12.3b1 because the YAGNI bar is high (3 constants + 3 fields).

## Task 12.3b2 deliverables (next session)

1. Wire `zk-prove-smoke` Justfile recipe gated on
   `.bin/.zk/cargo-risczero` (mirrors the `rs-solver` `.bin/z3` gate
   from Phase 0).
2. End-to-end `extract → prove → verify` round-trip on the canonical
   `contradictory-bound` `SmtTrace` fixture
   (`crates/zk_kernel/tests/canonical_roundtrip.rs`). The integration
   test runs under `RISC0_DEV_MODE=1` (fast fake prover) by default;
   a `--no-default-features` opt-in path may run the real STARK
   prover for a deeper smoke.
3. Operator precondition: `just fetch-zk && cargo-risczero install`
   (the latter provisions the RISC-V cross-compiler that builds the
   guest ELF — `riscv32im-risc0-zkvm-elf` target).

## Cross-references

- ADR-032 (Task 12.1) — locked Risc0 v3.0.1 as the zkVM (bumped to
  v3.0.5 by ADR-035 §2; same major line per Plan §6 pre-authorization).
- ADR-033 (Task 12.2) — host-side witness encoding (`SmtTrace` →
  length-prefixed binary frame).
- ADR-034 (Task 12.3a) — sha-pinned cargo-risczero tarball + guest
  crate scaffolding decisions + `risc0-zkvm` re-deferral to 12.3b.
- ADR-035 (Task 12.3b1 — this commit) — body fills + coordinated
  v3.0.1 → v3.0.5 bump + further split into 12.3b1 + 12.3b2.
- `Plan.md` §8.2 rows 12.3a (DONE) + 12.3b1 (DONE) + 12.3b2 (TODO).
