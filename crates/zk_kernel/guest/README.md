# `zk-kernel-guest` — Risc0 zkVM guest program (Phase 1, Task 12.3a scaffold)

This crate is the **Risc0 zkVM guest program** for the CDS ZKSMT
post-quantum proof attestation axis. It is compiled for the
`riscv32im-risc0-zkvm-elf` target via the rzup-installed cross-
compiler (`just fetch-zk` stages cargo-risczero v3.0.1 under
`.bin/.zk/`) and executed inside the zkVM by Risc0's
`default_prover().prove(env, GUEST_ELF)` call site (lands at Task
12.3b).

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
   precedent (ADR-032 §5 → ADR-033 §3 → ADR-034 §3), heavy
   dependencies land at the first call site that actually consumes
   them. The guest body is a Task 12.3b deliverable; the workspace
   exclusion keeps the host build cost flat at Task 12.3a.

## Task 12.3a scaffold (this commit)

| Artefact                  | Status                                                |
| ------------------------- | ----------------------------------------------------- |
| `Cargo.toml` + `[[bin]]`  | Declared; `[dependencies]` empty (no `risc0-zkvm` yet) |
| `src/main.rs` skeleton    | `#![no_main]` + `#![no_std]` under `target_os = "zkvm"`; body is `unreachable!()` |
| Workspace exclusion       | Root `Cargo.toml` `[workspace] exclude` carries this path |
| `fetch-zk` install logic  | Sha-pinned `cargo-risczero` v3.0.1 Linux x86_64 tarball download (ADR-034 §2) |

## Task 12.3b deliverables (next session)

1. Add `risc0-zkvm` to root `Cargo.toml` `[workspace.dependencies]`
   (matching the v3.0.1 pin; env-overridable via `ZK_TOOLCHAIN_VERSION`).
2. Add `risc0-zkvm = { workspace = true, default-features = false, features = ["std"] }`
   to this crate's `[dependencies]`.
3. Fill in `main()`:
   - `let bytes: Vec<u8> = risc0_zkvm::guest::env::read_slice();` →
     read the host-supplied witness blob.
   - Validate `WITNESS_MAGIC` / `WITNESS_VERSION` / `payload_len`
     header (re-uses the constants from `zk_kernel::witness`).
   - `serde_json::from_slice::<SmtTrace>` over the post-header bytes.
   - Run a minimal Alethe replay subset checker over the canonical
     `contradictory-bound` shape.
   - `risc0_zkvm::guest::env::commit(&verdict_hash);`
4. Fill in host-side `crates/zk_kernel/src/prove.rs::prove` body:
   - Build `ExecutorEnv::builder().write_slice(&blob.0).build()`.
   - `default_prover().prove(env, ZK_KERNEL_GUEST_ELF)`.
   - Return `ZkProof(receipt.seal_bytes())`.
5. Fill in host-side `crates/zk_kernel/src/verify.rs::verify` body:
   - `Receipt::from_bytes(&proof.0)?.verify(ZK_KERNEL_GUEST_IMAGE_ID)?;`
6. Wire `zk-prove-smoke` Justfile recipe gated on `.bin/.zk/cargo-risczero`
   (mirrors the `rs-solver` `.bin/z3` gate from Phase 0).
7. End-to-end `extract → prove → verify` round-trip on the canonical
   `contradictory-bound` `SmtTrace` fixture.

## Cross-references

- ADR-032 (Task 12.1) — locked Risc0 v3.0.1 as the zkVM.
- ADR-033 (Task 12.2) — host-side witness encoding (`SmtTrace` →
  length-prefixed binary frame).
- ADR-034 (Task 12.3a) — split rationale + sha-pinned tarball lock
  + guest crate scaffolding decisions.
- `Plan.md` §8.2 rows 12.3a (DONE) + 12.3b (TODO).
