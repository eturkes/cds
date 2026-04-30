//! Subprocess warden — owns every external solver / theorem-prover child.
//!
//! Honours **ADR-004**:
//!
//! 1. `tokio::process::Command::kill_on_drop(true)` is set on every spawned
//!    [`Child`](tokio::process::Child) so a panic / cancellation upstream
//!    triggers `SIGKILL` instead of leaking a zombie.
//! 2. Every spawn carries an explicit wall-clock timeout. On expiry the
//!    in-flight `wait_with_output` future is dropped, which drops the
//!    child handle, which delivers `SIGKILL` (single-stage escalation
//!    documented in ADR-014; the SIGTERM-first grace window is reinstated
//!    in Task 7 alongside the Lean / Kimina interop where shutdown hooks
//!    materially differ from a Z3/cvc5 batch run).
//! 3. Workers communicate exclusively via async message-passing
//!    (`tokio::process` channels: stdin write + `wait_with_output`).
//!    No UNIX-signal handlers are installed in worker tasks.
//!
//! The warden is intentionally **solver-agnostic** — Z3, cvc5 and (Task 7)
//! Lean all funnel through [`run_with_input`].

use std::path::Path;
use std::process::{ExitStatus, Stdio};
use std::time::Duration;

use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::time::timeout;

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
    /// `SIGKILL`-ed via `kill_on_drop`.
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

    let collect = child.wait_with_output();
    match timeout(wall_clock, collect).await {
        Ok(Ok(out)) => Ok(RunOutcome {
            stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
            stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
            status: out.status,
        }),
        Ok(Err(source)) => Err(WardenError::Io { bin: label, source }),
        Err(_elapsed) => Err(WardenError::Timeout {
            bin: label,
            timeout: wall_clock,
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::time::Duration;

    use super::{WardenError, run_with_input};

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
}
