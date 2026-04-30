//! Phase 0 kernel-service host/port resolution.
//!
//! Mirrors the Python harness's `resolve_host` / `resolve_port` shape
//! (ADR-017 §1) so the Justfile contract is symmetric:
//!
//! - [`HOST_ENV`] (`CDS_KERNEL_HOST`) defaults to [`DEFAULT_HOST`]
//!   (`127.0.0.1`).
//! - [`PORT_ENV`] (`CDS_KERNEL_PORT`) defaults to [`DEFAULT_PORT`]
//!   (`8082`); empty / whitespace strings collapse to the default.
//! - Garbage / out-of-range port values raise a [`ConfigError`] which
//!   the binary surfaces as a non-zero exit.
//!
//! Pure parsing lives in [`parse_port_raw`] so the unit tests do not
//! need to mutate the process environment.

use std::env;

/// Default bind address for the kernel service.
pub const DEFAULT_HOST: &str = "127.0.0.1";

/// Default bind port. The Python harness service holds 8081 (ADR-017
/// §1); the kernel service deliberately avoids that port so both can
/// run simultaneously under a single `just dapr-pipeline`.
pub const DEFAULT_PORT: u16 = 8082;

/// Environment variable consulted for the bind host.
pub const HOST_ENV: &str = "CDS_KERNEL_HOST";

/// Environment variable consulted for the bind port.
pub const PORT_ENV: &str = "CDS_KERNEL_PORT";

/// Errors raised by host/port resolution.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ConfigError {
    /// `CDS_KERNEL_PORT` (or another caller-named env var) was set but
    /// did not parse as a `u16`-range integer.
    #[error("{name}={raw:?} is not an integer")]
    PortParse { name: &'static str, raw: String },
    /// Parsed port was outside `[1, 65535]`.
    #[error("{name}={value} is outside [1, 65535]")]
    PortOutOfRange { name: &'static str, value: u32 },
}

/// Resolve the bind host: `$CDS_KERNEL_HOST` if non-empty, else
/// [`DEFAULT_HOST`].
#[must_use]
pub fn resolve_host() -> String {
    match env::var(HOST_ENV) {
        Ok(raw) if !raw.trim().is_empty() => raw,
        _ => DEFAULT_HOST.to_string(),
    }
}

/// Resolve the bind port from `$CDS_KERNEL_PORT`.
///
/// Empty / unset / whitespace-only values fall back to [`DEFAULT_PORT`].
/// Parsing or range failures lift to [`ConfigError`] so the binary can
/// exit non-zero with a useful message.
///
/// # Errors
/// See [`ConfigError`].
pub fn resolve_port() -> Result<u16, ConfigError> {
    match env::var(PORT_ENV) {
        Err(_) => Ok(DEFAULT_PORT),
        Ok(raw) => parse_port_raw(&raw),
    }
}

/// Pure port parser used by [`resolve_port`] and the unit tests.
///
/// # Errors
/// See [`ConfigError`].
pub fn parse_port_raw(raw: &str) -> Result<u16, ConfigError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(DEFAULT_PORT);
    }
    let parsed: u32 = trimmed.parse().map_err(|_| ConfigError::PortParse {
        name: PORT_ENV,
        raw: raw.to_string(),
    })?;
    let port = u16::try_from(parsed).map_err(|_| ConfigError::PortOutOfRange {
        name: PORT_ENV,
        value: parsed,
    })?;
    if port == 0 {
        return Err(ConfigError::PortOutOfRange {
            name: PORT_ENV,
            value: 0,
        });
    }
    Ok(port)
}

#[cfg(test)]
mod tests {
    use super::{ConfigError, DEFAULT_PORT, PORT_ENV, parse_port_raw};

    #[test]
    fn parse_port_returns_default_for_empty_input() {
        assert_eq!(parse_port_raw("").unwrap(), DEFAULT_PORT);
        assert_eq!(parse_port_raw("   ").unwrap(), DEFAULT_PORT);
        assert_eq!(parse_port_raw("\t\n").unwrap(), DEFAULT_PORT);
    }

    #[test]
    fn parse_port_accepts_valid_u16() {
        assert_eq!(parse_port_raw("1").unwrap(), 1);
        assert_eq!(parse_port_raw("8082").unwrap(), 8082);
        assert_eq!(parse_port_raw("65535").unwrap(), 65535);
        assert_eq!(parse_port_raw("  4242  ").unwrap(), 4242);
    }

    #[test]
    fn parse_port_rejects_garbage() {
        let err = parse_port_raw("eighty-eighty-two").unwrap_err();
        assert_eq!(
            err,
            ConfigError::PortParse {
                name: PORT_ENV,
                raw: "eighty-eighty-two".to_string()
            }
        );
    }

    #[test]
    fn parse_port_rejects_zero_and_overflow() {
        assert_eq!(
            parse_port_raw("0").unwrap_err(),
            ConfigError::PortOutOfRange {
                name: PORT_ENV,
                value: 0
            }
        );
        assert_eq!(
            parse_port_raw("65536").unwrap_err(),
            ConfigError::PortOutOfRange {
                name: PORT_ENV,
                value: 65536
            }
        );
        assert_eq!(
            parse_port_raw("999999").unwrap_err(),
            ConfigError::PortOutOfRange {
                name: PORT_ENV,
                value: 999_999
            }
        );
    }

    #[test]
    fn parse_port_rejects_negative_input() {
        let err = parse_port_raw("-1").unwrap_err();
        assert_eq!(
            err,
            ConfigError::PortParse {
                name: PORT_ENV,
                raw: "-1".to_string()
            }
        );
    }
}
