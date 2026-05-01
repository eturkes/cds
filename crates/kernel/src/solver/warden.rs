//! Subprocess warden — owns every external solver / theorem-prover child.
//!
//! Honours **ADR-004** + **ADR-021 §2** (Task 8.4a):
//!
//! 1. `tokio::process::Command::kill_on_drop(true)` is set on every spawned
//!    [`Child`](tokio::process::Child) so a panic / cancellation upstream
//!    triggers `SIGKILL` instead of leaking a zombie.
//! 2. Every spawn carries an explicit wall-clock timeout. On expiry the
//!    warden runs a **two-stage** shutdown — `SIGTERM` first via
//!    `nix::sys::signal::kill`, wait up to [`SIGTERM_GRACE`] for the child
//!    to flush partial state and exit cleanly, then drop the `wait_with_output`
//!    future to engage `kill_on_drop` for the `SIGKILL` fallback. The
//!    long-deferred SIGTERM-first escalation (ADR-014 §9 → ADR-015 §8 →
//!    ADR-016 §7 → ADR-018 §6 → ADR-019 §11 → ADR-020 §6) is closed by
//!    ADR-021 §4 — Workflow's retry-against-long-running-proof failure
//!    mode is the operational pressure that finally tips the trade.
//! 3. Workers communicate exclusively via async message-passing
//!    (`tokio::process` channels: stdin write + `wait_with_output`).
//!    No UNIX-signal handlers are installed in worker tasks.
//!
//! The warden is intentionally **solver-agnostic** — Z3, cvc5 and (Task 7)
//! Lean all funnel through [`run_with_input`].

use std::path::Path;
use std::pin::pin;
use std::process::{ExitStatus, Stdio};
use std::time::Duration;

use nix::sys::signal::{Signal, kill};
use nix::unistd::Pid;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

/// Grace window between `SIGTERM` and `SIGKILL` on the wall-clock timeout
/// path. Phase 0 default: 500 ms — long enough for cvc5 / Z3 to flush
/// partial proof state on `SIGTERM`, short enough that a stuck solver
/// doesn't hold a Workflow retry budget operationally (ADR-021 §2).
pub const SIGTERM_GRACE: Duration = Duration::from_millis(500);

/// Errors raised by the warden when spawning, communicating with, or
/// waiting on a child process.
#[derive(Debug, thiserror::Error)]
pub enum WardenError {
    /// `Command::spawn` failed — typically the binary is not on `$PATH`
    /// or the supplied path does not point at an executable.
    #[error("warden: failed to spawn `{bin}`: {source}")]
    Spawn {
        bin: String,
        #[source]
        source: std::io::Error,
    },
    /// Child exceeded its wall-clock budget. The handle has been
    /// `SIGTERM`-then-`SIGKILL`-ed via the two-stage escalation
    /// (ADR-021 §2). The error variant is unchanged from the
    /// pre-8.4a SIGKILL-only contract — the escalation is an
    /// implementation detail and callers (`solver::z3`,
    /// `solver::cvc5`, `service::handlers`, `service::errors`)
    /// continue to consume the same shape.
    #[error("warden: `{bin}` exceeded wall-clock timeout {}ms", .timeout.as_millis())]
    Timeout { bin: String, timeout: Duration },
    /// Stream IO failed while writing stdin or collecting stdout/stderr.
    #[error("warden: i/o error talking to `{bin}`: {source}")]
    Io {
        bin: String,
        #[source]
        source: std::io::Error,
    },
}

/// Captured outcome of a warden-supervised subprocess invocation.
#[derive(Debug, Clone)]
pub struct RunOutcome {
    pub stdout: String,
    pub stderr: String,
    pub status: ExitStatus,
}

/// Spawn `bin args...`, pipe `stdin_payload` into the child's stdin,
/// wait up to `wall_clock` for it to terminate, and collect
/// stdout/stderr.
///
/// `bin` may be an absolute path or a bare command name resolved via
/// `$PATH`. The caller is responsible for ensuring the binary is on
/// the search path (Phase 0 convention: `.bin/` is `PATH`-prefixed by
/// the `Justfile`).
///
/// On wall-clock expiry the warden runs the ADR-021 §2 two-stage
/// shutdown: send `SIGTERM` to the child PID, wait up to
/// [`SIGTERM_GRACE`] for graceful exit, then drop the in-flight
/// `wait_with_output` future to trigger `kill_on_drop`'s `SIGKILL`.
/// The returned [`WardenError::Timeout`] does not distinguish the
/// two paths — the wall-clock budget was exceeded either way; only
/// the kill mechanism differs.
///
/// # Errors
/// See [`WardenError`].
pub async fn run_with_input(
    bin: &Path,
    args: &[&str],
    stdin_payload: &str,
    wall_clock: Duration,
) -> Result<RunOutcome, WardenError> {
    let label = bin.display().to_string();

    let mut cmd = Command::new(bin);
    cmd.args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);

    let mut child = cmd.spawn().map_err(|source| WardenError::Spawn {
        bin: label.clone(),
        source,
    })?;

    let child_pid = child.id();

    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(stdin_payload.as_bytes())
            .await
            .map_err(|source| WardenError::Io {
                bin: label.clone(),
                source,
            })?;
        // Drop closes stdin so the solver sees EOF and exits.
    }

    let mut collect = pin!(child.wait_with_output());

    // Stage 1 — wait the wall-clock budget. Happy path collects
    // stdout/stderr and returns.
    match timeout(wall_clock, collect.as_mut()).await {
        Ok(Ok(out)) => {
            return Ok(RunOutcome {
                stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
                stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
                status: out.status,
            });
        }
        Ok(Err(source)) => return Err(WardenError::Io { bin: label, source }),
        Err(_elapsed) => {}
    }

    // Stage 2 — wall-clock exceeded. SIGTERM the child, give it
    // SIGTERM_GRACE to flush partial state, then drop the future to
    // engage `kill_on_drop`'s SIGKILL fallback. The `wait_with_output`
    // future is still live and will resolve on graceful exit.
    if let Some(pid_u32) = child_pid {
        if let Ok(pid_i32) = i32::try_from(pid_u32) {
            // Errors here are silently ignored — ESRCH means the child
            // already exited (race with the timeout firing); EPERM is
            // structurally impossible since we own the child.
            let _ = kill(Pid::from_raw(pid_i32), Signal::SIGTERM);
        }
    }

    match timeout(SIGTERM_GRACE, collect.as_mut()).await {
        // Grace path — child exited cleanly within SIGTERM_GRACE.
        // The wall-clock budget was still exceeded, so we still
        // surface `WardenError::Timeout`; only the kill mechanism
        // differs from the SIGKILL fallback.
        Ok(_) => Err(WardenError::Timeout {
            bin: label,
            timeout: wall_clock,
        }),
        // SIGKILL fallback — returning here drops the pinned future,
        // which drops the inner `Child`, which delivers `SIGKILL` via
        // `kill_on_drop`. Explicit `drop(collect)` is unnecessary
        // because `collect` is a `Pin<&mut Future>` (clippy::drop_non_drop)
        // and the underlying temporary is dropped at end-of-scope anyway.
        Err(_grace_elapsed) => Err(WardenError::Timeout {
            bin: label,
            timeout: wall_clock,
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::time::{Duration, Instant};

    use super::{SIGTERM_GRACE, WardenError, run_with_input};

    fn bin(name: &str) -> PathBuf {
        PathBuf::from(name)
    }

    #[tokio::test]
    async fn echoes_stdin_through_cat() {
        // Skip if /bin/cat is unavailable (extremely portable on Linux dev hosts).
        let cat = PathBuf::from("/bin/cat");
        if !cat.exists() {
            return;
        }
        let out = run_with_input(&cat, &[], "hello\n", Duration::from_secs(2))
            .await
            .expect("cat run");
        assert!(out.status.success());
        assert_eq!(out.stdout, "hello\n");
    }

    #[tokio::test]
    async fn timeout_kills_long_running_child() {
        let sleep = PathBuf::from("/bin/sleep");
        if !sleep.exists() {
            return;
        }
        let err = run_with_input(&sleep, &["5"], "", Duration::from_millis(100))
            .await
            .expect_err("sleep should timeout");
        match err {
            WardenError::Timeout { bin: _, timeout } => {
                assert_eq!(timeout, Duration::from_millis(100));
            }
            other => panic!("expected timeout, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn missing_binary_yields_spawn_error() {
        let nope = bin("definitely-not-a-real-binary-xyz789");
        let err = run_with_input(&nope, &[], "", Duration::from_secs(1))
            .await
            .expect_err("spawn should fail");
        match err {
            WardenError::Spawn { bin, source: _ } => {
                assert!(bin.contains("definitely-not-a-real-binary-xyz789"));
            }
            other => panic!("expected spawn error, got {other:?}"),
        }
    }

    /// Child traps `SIGTERM` and exits cleanly inside the grace window.
    /// The wall-clock budget was still exceeded so the warden surfaces
    /// `WardenError::Timeout`, but the elapsed time is ≤ `wall_clock` +
    /// grace (no `SIGKILL` was needed). Validates the `SIGTERM`-first
    /// stage of the ADR-021 §2 two-stage escalation.
    #[tokio::test]
    async fn timeout_sigterm_first_when_child_traps_term() {
        let bash = PathBuf::from("/bin/bash");
        if !bash.exists() {
            return;
        }
        let wall_clock = Duration::from_millis(150);
        let started = Instant::now();
        let err = run_with_input(
            &bash,
            &["-c", "trap 'exit 0' TERM; while :; do sleep 1; done"],
            "",
            wall_clock,
        )
        .await
        .expect_err("wall-clock should still be exceeded");
        let elapsed = started.elapsed();
        match err {
            WardenError::Timeout { bin: _, timeout } => {
                assert_eq!(timeout, wall_clock);
            }
            other => panic!("expected timeout, got {other:?}"),
        }
        // Lower bound: the wall-clock budget itself.
        assert!(
            elapsed >= wall_clock,
            "elapsed {elapsed:?} < wall_clock {wall_clock:?}"
        );
        // Upper bound: wall_clock + grace (child exited on SIGTERM
        // before SIGKILL fallback). Generous slack for CI scheduling.
        assert!(
            elapsed < wall_clock + SIGTERM_GRACE + Duration::from_millis(500),
            "elapsed {elapsed:?} exceeded wall_clock + grace + slack"
        );
    }

    /// Child masks `SIGTERM` and ignores it; the warden falls through
    /// to `SIGKILL` via `kill_on_drop` when the grace window expires.
    /// Validates the `SIGKILL`-fallback stage of the ADR-021 §2
    /// two-stage escalation.
    #[tokio::test]
    async fn timeout_sigkill_fallback_when_child_ignores_term() {
        let bash = PathBuf::from("/bin/bash");
        if !bash.exists() {
            return;
        }
        let wall_clock = Duration::from_millis(150);
        let started = Instant::now();
        let err = run_with_input(
            &bash,
            &["-c", "trap '' TERM; while :; do sleep 1; done"],
            "",
            wall_clock,
        )
        .await
        .expect_err("wall-clock should be exceeded");
        let elapsed = started.elapsed();
        match err {
            WardenError::Timeout { bin: _, timeout } => {
                assert_eq!(timeout, wall_clock);
            }
            other => panic!("expected timeout, got {other:?}"),
        }
        // Lower bound: wall_clock + grace — SIGTERM was ignored, so
        // the warden waited the full grace window before falling
        // through to the SIGKILL drop path.
        assert!(
            elapsed >= wall_clock + SIGTERM_GRACE,
            "elapsed {elapsed:?} < wall_clock + grace = {:?}",
            wall_clock + SIGTERM_GRACE
        );
        // Upper bound: wall_clock + grace + reasonable margin
        // covering kill_on_drop SIGKILL delivery + reaper.
        assert!(
            elapsed < wall_clock + SIGTERM_GRACE + Duration::from_secs(2),
            "elapsed {elapsed:?} exceeded wall_clock + grace + 2s"
        );
    }
}
