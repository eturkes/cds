//! Phase 0 kernel-service shared application state (Task 8.3b2a).
//!
//! [`KernelServiceState`] bundles the option floors that the three
//! pipeline handlers — [`crate::service::handlers::deduce`],
//! [`crate::service::handlers::solve`], [`crate::service::handlers::recheck`] —
//! consume via [`axum::extract::State`]. Per-request `options` envelopes
//! retain their replace-the-floor semantics: present fields win, absent
//! fields fall back to the corresponding field on the state. The state's
//! own field defaults match [`crate::solver::VerifyOptions::default`] and
//! [`crate::lean::LeanOptions::default`] when no environment overrides
//! are present, so the wire contract is byte-stable across the
//! 8.3b1 → 8.3b2a transition (ADR-020 §5).
//!
//! ## Resolution rules
//!
//! [`KernelServiceState::from_env`] reads five environment variables:
//!
//! | Env var                    | Lowers to                                 |
//! | -------------------------- | ----------------------------------------- |
//! | `CDS_Z3_PATH`              | `VerifyOptions::z3_path`                  |
//! | `CDS_CVC5_PATH`            | `VerifyOptions::cvc5_path`                |
//! | `CDS_SOLVER_TIMEOUT_MS`    | `VerifyOptions::timeout` (ms → `Duration`) |
//! | `CDS_KIMINA_URL`           | `LeanOptions::kimina_url`                 |
//! | `CDS_LEAN_TIMEOUT_MS`      | `LeanOptions::timeout` (ms → `Duration`)  |
//!
//! Unset / empty values fall back to the type-level defaults above.
//! Invalid values (non-UTF-8, non-numeric ms, overflowing u64) **panic at
//! boot** — operator typos surface immediately rather than silently
//! degrading clinical-evidence handling. This matches the fail-loud
//! discipline of [`crate::service::config::parse_port_raw`] (ADR-018 §1).
//!
//! ## Test isolation
//!
//! [`KernelServiceState::from_lookup`] is the pure parsing helper that
//! [`KernelServiceState::from_env`] delegates to. Unit tests construct
//! arbitrary lookups via closure injection, so the test suite never
//! mutates process-global environment state and never needs
//! `serial_test` / sub-process isolation (the two alternatives ADR-020
//! §4 explicitly listed). The constraint pinned by ADR-020 §4 — do not
//! rely on cargo's single-thread-integration-test default for env
//! isolation — is satisfied by construction.

use std::env::{self, VarError};
use std::path::PathBuf;
use std::time::Duration;

use crate::lean::LeanOptions;
use crate::solver::VerifyOptions;

/// Environment variable consulted for the Z3 binary path.
pub const Z3_PATH_ENV: &str = "CDS_Z3_PATH";

/// Environment variable consulted for the cvc5 binary path.
pub const CVC5_PATH_ENV: &str = "CDS_CVC5_PATH";

/// Environment variable consulted for the SMT solver wall-clock timeout
/// (milliseconds, parsed as `u64`).
pub const SOLVER_TIMEOUT_MS_ENV: &str = "CDS_SOLVER_TIMEOUT_MS";

/// Environment variable consulted for the Kimina REST endpoint.
pub const KIMINA_URL_ENV: &str = "CDS_KIMINA_URL";

/// Environment variable consulted for the Lean re-check wall-clock
/// timeout (milliseconds, parsed as `u64`).
pub const LEAN_TIMEOUT_MS_ENV: &str = "CDS_LEAN_TIMEOUT_MS";

/// Phase 0 kernel-service shared application state.
///
/// `Clone` because axum's [`axum::extract::State`] requires the state to
/// be cheaply cloneable per request; the underlying [`VerifyOptions`] /
/// [`LeanOptions`] both derive `Clone` over inexpensive (`Duration`,
/// `PathBuf`, short `String`) fields, so the per-request clone cost is
/// negligible.
#[derive(Debug, Clone)]
pub struct KernelServiceState {
    pub verify_options: VerifyOptions,
    pub lean_options: LeanOptions,
}

impl KernelServiceState {
    /// Build [`KernelServiceState`] by reading the five
    /// `CDS_*` environment variables documented at the module level.
    ///
    /// # Panics
    /// Panics on invalid env values (non-UTF-8 paths/URLs, non-numeric
    /// timeout strings, timeout values that exceed `u64::MAX`). Operator
    /// typos surface at boot rather than at first request — fail-loud
    /// discipline (ADR-020 §2 / parity with [`crate::service::config::parse_port_raw`]
    /// per ADR-018 §1).
    #[must_use]
    pub fn from_env() -> Self {
        Self::from_lookup(|key| match env::var(key) {
            Ok(value) => Some(value),
            Err(VarError::NotPresent) => None,
            Err(VarError::NotUnicode(raw)) => {
                panic!("env var {key} is not valid UTF-8: {raw:?}")
            }
        })
    }

    /// Pure parsing helper used by [`Self::from_env`] and the unit tests.
    ///
    /// `lookup` returns `Some(value)` for an env var that is set + valid
    /// UTF-8, or `None` for an unset env var. UTF-8 validity is enforced
    /// upstream by [`Self::from_env`] before the closure is invoked, so a
    /// closure that returns `Some(_)` always carries a parsed string.
    ///
    /// # Panics
    /// Panics on invalid timeout values (non-numeric, overflowing `u64`).
    /// Path / URL fields cannot panic at this layer — invalid file system
    /// paths or unreachable URLs fail at the warden / Kimina-client
    /// layer (the boundary that actually consults them).
    #[must_use]
    pub fn from_lookup<F: Fn(&str) -> Option<String>>(lookup: F) -> Self {
        let defaults_verify = VerifyOptions::default();
        let defaults_lean = LeanOptions::default();

        let z3_path = lookup_path(&lookup, Z3_PATH_ENV).unwrap_or(defaults_verify.z3_path);
        let cvc5_path = lookup_path(&lookup, CVC5_PATH_ENV).unwrap_or(defaults_verify.cvc5_path);
        let solver_timeout =
            lookup_duration(&lookup, SOLVER_TIMEOUT_MS_ENV).unwrap_or(defaults_verify.timeout);

        let kimina_url = lookup_string(&lookup, KIMINA_URL_ENV).unwrap_or(defaults_lean.kimina_url);
        let lean_timeout =
            lookup_duration(&lookup, LEAN_TIMEOUT_MS_ENV).unwrap_or(defaults_lean.timeout);

        Self {
            verify_options: VerifyOptions {
                timeout: solver_timeout,
                z3_path,
                cvc5_path,
            },
            lean_options: LeanOptions {
                kimina_url,
                timeout: lean_timeout,
                custom_id: defaults_lean.custom_id,
                extra_headers: defaults_lean.extra_headers,
            },
        }
    }
}

impl Default for KernelServiceState {
    /// Construct a state with no environment overrides applied — every
    /// field reads from [`VerifyOptions::default`] / [`LeanOptions::default`].
    /// Convenient for tests that don't need to exercise env-driven
    /// overrides.
    fn default() -> Self {
        Self::from_lookup(|_| None)
    }
}

fn lookup_string<F: Fn(&str) -> Option<String>>(lookup: &F, key: &'static str) -> Option<String> {
    lookup(key).filter(|raw| !raw.trim().is_empty())
}

fn lookup_path<F: Fn(&str) -> Option<String>>(lookup: &F, key: &'static str) -> Option<PathBuf> {
    lookup_string(lookup, key).map(PathBuf::from)
}

fn lookup_duration<F: Fn(&str) -> Option<String>>(
    lookup: &F,
    key: &'static str,
) -> Option<Duration> {
    let raw = lookup_string(lookup, key)?;
    let ms: u64 = raw.trim().parse().unwrap_or_else(|err| {
        panic!("env var {key}={raw:?} is not a non-negative integer (milliseconds): {err}")
    });
    Some(Duration::from_millis(ms))
}

#[cfg(test)]
mod tests {
    use super::{
        CVC5_PATH_ENV, KIMINA_URL_ENV, KernelServiceState, LEAN_TIMEOUT_MS_ENV,
        SOLVER_TIMEOUT_MS_ENV, Z3_PATH_ENV,
    };
    use crate::lean::LeanOptions;
    use crate::solver::VerifyOptions;
    use std::collections::HashMap;
    use std::path::PathBuf;
    use std::time::Duration;

    fn lookup_from(map: HashMap<&'static str, String>) -> impl Fn(&str) -> Option<String> {
        move |key: &str| map.get(key).cloned()
    }

    #[test]
    fn from_lookup_returns_defaults_when_unset() {
        let state = KernelServiceState::from_lookup(|_| None);
        let baseline_verify = VerifyOptions::default();
        let baseline_lean = LeanOptions::default();
        assert_eq!(state.verify_options.timeout, baseline_verify.timeout);
        assert_eq!(state.verify_options.z3_path, baseline_verify.z3_path);
        assert_eq!(state.verify_options.cvc5_path, baseline_verify.cvc5_path);
        assert_eq!(state.lean_options.kimina_url, baseline_lean.kimina_url);
        assert_eq!(state.lean_options.timeout, baseline_lean.timeout);
        assert_eq!(state.lean_options.custom_id, baseline_lean.custom_id);
        assert_eq!(
            state.lean_options.extra_headers,
            baseline_lean.extra_headers
        );
    }

    #[test]
    fn default_constructor_matches_from_lookup_with_no_env() {
        let from_default = KernelServiceState::default();
        let from_empty_lookup = KernelServiceState::from_lookup(|_| None);
        assert_eq!(
            from_default.verify_options.z3_path,
            from_empty_lookup.verify_options.z3_path
        );
        assert_eq!(
            from_default.verify_options.cvc5_path,
            from_empty_lookup.verify_options.cvc5_path
        );
        assert_eq!(
            from_default.verify_options.timeout,
            from_empty_lookup.verify_options.timeout
        );
        assert_eq!(
            from_default.lean_options.kimina_url,
            from_empty_lookup.lean_options.kimina_url
        );
        assert_eq!(
            from_default.lean_options.timeout,
            from_empty_lookup.lean_options.timeout
        );
    }

    #[test]
    fn from_lookup_picks_up_z3_and_cvc5_overrides() {
        let mut env = HashMap::new();
        env.insert(Z3_PATH_ENV, "/opt/cds/.bin/z3-pinned".to_string());
        env.insert(CVC5_PATH_ENV, "/opt/cds/.bin/cvc5-pinned".to_string());
        let state = KernelServiceState::from_lookup(lookup_from(env));
        assert_eq!(
            state.verify_options.z3_path,
            PathBuf::from("/opt/cds/.bin/z3-pinned")
        );
        assert_eq!(
            state.verify_options.cvc5_path,
            PathBuf::from("/opt/cds/.bin/cvc5-pinned")
        );
        // Unrelated fields stay at defaults.
        let baseline = VerifyOptions::default();
        assert_eq!(state.verify_options.timeout, baseline.timeout);
    }

    #[test]
    fn from_lookup_picks_up_kimina_url_override() {
        let mut env = HashMap::new();
        env.insert(KIMINA_URL_ENV, "http://kimina.example:9000".to_string());
        let state = KernelServiceState::from_lookup(lookup_from(env));
        assert_eq!(state.lean_options.kimina_url, "http://kimina.example:9000");
        let baseline = LeanOptions::default();
        assert_eq!(state.lean_options.timeout, baseline.timeout);
    }

    #[test]
    fn from_lookup_parses_solver_timeout_ms() {
        let mut env = HashMap::new();
        env.insert(SOLVER_TIMEOUT_MS_ENV, "500".to_string());
        let state = KernelServiceState::from_lookup(lookup_from(env));
        assert_eq!(state.verify_options.timeout, Duration::from_millis(500));
    }

    #[test]
    fn from_lookup_parses_lean_timeout_ms() {
        let mut env = HashMap::new();
        env.insert(LEAN_TIMEOUT_MS_ENV, "12345".to_string());
        let state = KernelServiceState::from_lookup(lookup_from(env));
        assert_eq!(state.lean_options.timeout, Duration::from_millis(12_345));
    }

    #[test]
    fn from_lookup_treats_empty_or_whitespace_as_unset() {
        let mut env = HashMap::new();
        env.insert(Z3_PATH_ENV, String::new());
        env.insert(CVC5_PATH_ENV, "   \t\n".to_string());
        env.insert(KIMINA_URL_ENV, "  ".to_string());
        env.insert(SOLVER_TIMEOUT_MS_ENV, String::new());
        env.insert(LEAN_TIMEOUT_MS_ENV, "\t".to_string());
        let state = KernelServiceState::from_lookup(lookup_from(env));
        let baseline_verify = VerifyOptions::default();
        let baseline_lean = LeanOptions::default();
        assert_eq!(state.verify_options.z3_path, baseline_verify.z3_path);
        assert_eq!(state.verify_options.cvc5_path, baseline_verify.cvc5_path);
        assert_eq!(state.verify_options.timeout, baseline_verify.timeout);
        assert_eq!(state.lean_options.kimina_url, baseline_lean.kimina_url);
        assert_eq!(state.lean_options.timeout, baseline_lean.timeout);
    }

    #[test]
    #[should_panic(expected = "is not a non-negative integer")]
    fn from_lookup_panics_on_non_numeric_solver_timeout() {
        let mut env = HashMap::new();
        env.insert(SOLVER_TIMEOUT_MS_ENV, "thirty-seconds".to_string());
        let _ = KernelServiceState::from_lookup(lookup_from(env));
    }

    #[test]
    #[should_panic(expected = "is not a non-negative integer")]
    fn from_lookup_panics_on_negative_lean_timeout() {
        let mut env = HashMap::new();
        env.insert(LEAN_TIMEOUT_MS_ENV, "-100".to_string());
        let _ = KernelServiceState::from_lookup(lookup_from(env));
    }
}
