//! Kimina Lean Server HTTP client (REST, JSON-over-TCP, ADR-002 / C6).
//!
//! Talks to the open-source `project-numina/kimina-lean-server` via its
//! single `POST /verify` endpoint. The request payload is shaped per
//! the Kimina README:
//!
//! ```json
//! { "codes": [ { "custom_id": "...", "proof": "...lean..." } ],
//!   "infotree_type": "original" }
//! ```
//!
//! The response shape is a per-`code` array of result envelopes; the
//! Kimina technical report (arXiv:2504.21230) documents that each
//! envelope carries:
//!
//! - **Lean messages** — list of `{ severity, data, ... }` records with
//!   `severity ∈ {info, warning, error}`. `#eval` lines surface as
//!   `info` messages whose `data` carries the printed string.
//! - **Environment id** — REPL environment label (opaque).
//! - **Elapsed time** — verification wall-clock in seconds.
//! - **Infotree** — full Lean proof tree (only when `infotree_type !=
//!   none`; we ignore it in Phase 0).
//!
//! The exact field names vary across Kimina releases (the project tracks
//! Lean REPL upstream which itself is in flux). The decoder here is
//! deliberately permissive — it accepts both `messages` (REPL canonical)
//! and `lean_messages` (some Kimina builds), and handles the v1
//! `severity`/`data` shape as well as a `level`/`text` legacy alias.

use std::collections::BTreeMap;
use std::time::Duration;

use serde::Deserialize;
use serde_json::{Value, json};

use super::{LeanError, LeanMessage, LeanRecheck, LeanSeverity};

/// Send `lean_source` to a Kimina server's `POST /verify` and return
/// the parsed re-check outcome.
///
/// `custom_id` is round-tripped on the response so callers can correlate
/// concurrent submissions (Phase 0 always submits one code per call).
///
/// # Errors
/// See [`LeanError`].
pub async fn post_verify(
    base_url: &str,
    custom_id: &str,
    lean_source: &str,
    timeout: Duration,
    extra_headers: &BTreeMap<String, String>,
) -> Result<LeanRecheck, LeanError> {
    let endpoint = build_endpoint(base_url);
    let body = json!({
        "codes": [ { "custom_id": custom_id, "proof": lean_source } ],
        "infotree_type": "none",
    });

    let client = reqwest::Client::builder()
        .timeout(timeout)
        .build()
        .map_err(|source| LeanError::Transport {
            url: endpoint.clone(),
            detail: source.to_string(),
        })?;

    let mut request = client.post(&endpoint).json(&body);
    for (name, value) in extra_headers {
        request = request.header(name, value);
    }

    let resp = request
        .send()
        .await
        .map_err(|source| LeanError::Transport {
            url: endpoint.clone(),
            detail: source.to_string(),
        })?;

    let status = resp.status();
    let body_text = resp.text().await.map_err(|source| LeanError::Transport {
        url: endpoint.clone(),
        detail: source.to_string(),
    })?;

    if !status.is_success() {
        return Err(LeanError::ServerError {
            url: endpoint,
            status: status.as_u16(),
            body: body_text,
        });
    }

    if !body_text.trim().is_empty() {
        tracing::debug!(
            target = "cds_kernel::lean::client",
            url = %endpoint,
            response_bytes = body_text.len(),
        );
    }

    parse_response(&body_text, custom_id)
}

/// Saturating conversion of `seconds` (Kimina's elapsed-time wire format)
/// to whole milliseconds. Negative or NaN inputs collapse to `0` so the
/// outer envelope decoder can fall back to the next field gracefully.
/// Inputs above `~5.84e8` years saturate to [`u64::MAX`] — well outside
/// any realistic Lean wall-clock measurement.
#[must_use]
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)]
pub fn seconds_to_ms(seconds: f64) -> u64 {
    // 2^63 fits exactly in f64; anything ≥ that becomes u64::MAX.
    const SATURATION: f64 = 9_223_372_036_854_775_808.0;
    let ms = seconds * 1000.0;
    if !ms.is_finite() || ms <= 0.0 {
        0
    } else if ms >= SATURATION {
        u64::MAX
    } else {
        ms.round() as u64
    }
}

fn build_endpoint(base_url: &str) -> String {
    let trimmed = base_url.trim_end_matches('/');
    if trimmed.ends_with("/verify") {
        trimmed.to_string()
    } else {
        format!("{trimmed}/verify")
    }
}

/// Parse a Kimina `/verify` response body into a [`LeanRecheck`].
///
/// Accepts the two response envelopes Kimina has shipped historically:
///
/// - `{ "results": [ { ... } ] }` (named array — Kimina ≥ technical-report).
/// - `[ { ... } ]` (top-level array — earlier prototype builds).
/// - `{ ...single result... }` (single-code shortcut).
///
/// # Errors
/// Returns [`LeanError::DecodeFailed`] when the body is not valid JSON
/// or does not match a recognisable Kimina envelope.
pub fn parse_response(body: &str, custom_id: &str) -> Result<LeanRecheck, LeanError> {
    let value: Value = serde_json::from_str(body).map_err(|source| LeanError::DecodeFailed {
        reason: format!("not valid JSON: {source}"),
    })?;

    let envelope = pick_result_envelope(&value, custom_id)?;
    decode_envelope(envelope, custom_id)
}

fn pick_result_envelope<'a>(value: &'a Value, custom_id: &str) -> Result<&'a Value, LeanError> {
    let array = value
        .get("results")
        .and_then(Value::as_array)
        .or_else(|| value.as_array());

    if let Some(arr) = array {
        if arr.is_empty() {
            return Err(LeanError::DecodeFailed {
                reason: "kimina response carried an empty results array".into(),
            });
        }
        let pick = arr
            .iter()
            .find(|v| v.get("custom_id").and_then(Value::as_str) == Some(custom_id))
            .unwrap_or(&arr[0]);
        return Ok(pick);
    }

    if value.get("messages").is_some() || value.get("lean_messages").is_some() {
        return Ok(value);
    }

    Err(LeanError::DecodeFailed {
        reason: "kimina response had no `results` array or recognisable single-result shape".into(),
    })
}

fn decode_envelope(envelope: &Value, custom_id: &str) -> Result<LeanRecheck, LeanError> {
    let raw_messages = envelope
        .get("messages")
        .or_else(|| envelope.get("lean_messages"))
        .or_else(|| envelope.pointer("/response/messages"))
        .cloned()
        .unwrap_or(Value::Array(Vec::new()));

    let messages = decode_messages(&raw_messages)?;

    // Kimina reports elapsed time variously; surface whichever is present.
    let elapsed_ms = envelope
        .get("elapsed_ms")
        .and_then(Value::as_u64)
        .or_else(|| envelope.get("time").and_then(Value::as_u64))
        .or_else(|| {
            envelope
                .get("time")
                .and_then(Value::as_f64)
                .map(seconds_to_ms)
        })
        .or_else(|| {
            envelope
                .get("elapsed")
                .and_then(Value::as_f64)
                .map(seconds_to_ms)
        })
        .unwrap_or(0);

    let env_id = envelope
        .get("env")
        .or_else(|| envelope.get("env_id"))
        .or_else(|| envelope.get("environment"))
        .and_then(|v| {
            v.as_str()
                .map(str::to_string)
                .or_else(|| v.as_u64().map(|n| n.to_string()))
        });

    let probes = extract_probes(&messages);
    let lean_errored = messages.iter().any(|m| m.severity == LeanSeverity::Error);
    let probes_ok = probes_satisfied(&probes);

    Ok(LeanRecheck {
        ok: probes_ok && !lean_errored,
        custom_id: custom_id.to_string(),
        env_id,
        elapsed_ms,
        messages,
        probes,
    })
}

fn decode_messages(value: &Value) -> Result<Vec<LeanMessage>, LeanError> {
    #[derive(Deserialize)]
    struct Msg {
        #[serde(default)]
        severity: Option<String>,
        #[serde(default)]
        level: Option<String>,
        #[serde(default)]
        data: Option<String>,
        #[serde(default)]
        text: Option<String>,
        #[serde(default)]
        message: Option<String>,
    }

    let raw: Vec<Msg> =
        serde_json::from_value(value.clone()).map_err(|source| LeanError::DecodeFailed {
            reason: format!("messages list not decodable: {source}"),
        })?;

    Ok(raw
        .into_iter()
        .map(|m| {
            let raw_sev = m.severity.or(m.level).unwrap_or_else(|| "info".to_string());
            let severity = match raw_sev.to_ascii_lowercase().as_str() {
                "error" => LeanSeverity::Error,
                "warning" | "warn" => LeanSeverity::Warning,
                _ => LeanSeverity::Info,
            };
            let body = m.data.or(m.text).or(m.message).unwrap_or_default();
            LeanMessage { severity, body }
        })
        .collect())
}

/// Extract the four `PROBE name=value` payloads from Lean info messages.
#[must_use]
pub fn extract_probes(messages: &[LeanMessage]) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for msg in messages {
        for line in msg.body.lines() {
            // Lean wraps `#eval`-of-`String` output in surrounding quotes —
            // strip them before scanning for the probe prefix.
            let stripped = line.trim().trim_matches('"');
            if let Some(rest) = stripped.strip_prefix("PROBE ") {
                if let Some((name, value)) = rest.split_once('=') {
                    out.insert(name.trim().to_string(), value.trim().to_string());
                }
            }
        }
    }
    out
}

/// Returns `true` iff the four Phase 0 probes all landed and pass.
#[must_use]
pub fn probes_satisfied(probes: &BTreeMap<String, String>) -> bool {
    let starts_paren = probes.get("starts_paren").map(String::as_str) == Some("true");
    let has_assume = probes.get("has_assume").map(String::as_str) == Some("true");
    let has_rule = probes.get("has_rule").map(String::as_str) == Some("true");
    let byte_len_pos = probes
        .get("byte_len")
        .and_then(|v| v.parse::<u64>().ok())
        .is_some_and(|n| n > 0);
    starts_paren && has_assume && has_rule && byte_len_pos
}

#[cfg(test)]
mod tests {
    use super::{
        build_endpoint, decode_messages, extract_probes, parse_response, probes_satisfied,
    };
    use crate::lean::{LeanError, LeanSeverity};
    use serde_json::json;
    use std::collections::BTreeMap;

    #[test]
    fn endpoint_builder_appends_verify_when_missing() {
        assert_eq!(
            build_endpoint("http://localhost:8000"),
            "http://localhost:8000/verify"
        );
        assert_eq!(
            build_endpoint("http://localhost:8000/"),
            "http://localhost:8000/verify"
        );
        assert_eq!(
            build_endpoint("http://kimina.local:8000/verify"),
            "http://kimina.local:8000/verify"
        );
        assert_eq!(
            build_endpoint("http://kimina.local:8000/verify/"),
            "http://kimina.local:8000/verify"
        );
    }

    #[test]
    fn parse_response_accepts_results_array_envelope() {
        let body = json!({
            "results": [{
                "custom_id": "cds-0",
                "env": 7,
                "time": 0.42,
                "messages": [
                    { "severity": "info", "data": "\"PROBE byte_len=42\"" },
                    { "severity": "info", "data": "\"PROBE starts_paren=true\"" },
                    { "severity": "info", "data": "\"PROBE has_assume=true\"" },
                    { "severity": "info", "data": "\"PROBE has_rule=true\"" },
                ],
            }]
        })
        .to_string();
        let recheck = parse_response(&body, "cds-0").expect("decode");
        assert!(recheck.ok);
        assert_eq!(recheck.custom_id, "cds-0");
        assert_eq!(recheck.env_id.as_deref(), Some("7"));
        assert_eq!(recheck.elapsed_ms, 420);
        assert_eq!(
            recheck.probes.get("byte_len").map(String::as_str),
            Some("42")
        );
    }

    #[test]
    fn parse_response_accepts_top_level_array() {
        let body = json!([{
            "custom_id": "cds-0",
            "messages": [
                { "level": "info", "text": "PROBE byte_len=10" },
                { "level": "info", "text": "PROBE starts_paren=true" },
                { "level": "info", "text": "PROBE has_assume=true" },
                { "level": "info", "text": "PROBE has_rule=true" },
            ],
        }])
        .to_string();
        let recheck = parse_response(&body, "cds-0").expect("decode");
        assert!(recheck.ok);
    }

    #[test]
    fn parse_response_picks_envelope_by_custom_id() {
        let body = json!({
            "results": [
                { "custom_id": "other", "messages": [] },
                { "custom_id": "cds-0", "messages": [
                    { "severity": "info", "data": "PROBE byte_len=1" },
                    { "severity": "info", "data": "PROBE starts_paren=true" },
                    { "severity": "info", "data": "PROBE has_assume=true" },
                    { "severity": "info", "data": "PROBE has_rule=true" },
                ] }
            ]
        })
        .to_string();
        let recheck = parse_response(&body, "cds-0").expect("decode");
        assert_eq!(recheck.custom_id, "cds-0");
        assert!(recheck.ok);
    }

    #[test]
    fn parse_response_marks_lean_errors_as_not_ok() {
        let body = json!({
            "results": [{
                "custom_id": "cds-0",
                "messages": [
                    { "severity": "error", "data": "elaboration failed" },
                    { "severity": "info", "data": "PROBE byte_len=1" },
                    { "severity": "info", "data": "PROBE starts_paren=true" },
                    { "severity": "info", "data": "PROBE has_assume=true" },
                    { "severity": "info", "data": "PROBE has_rule=true" },
                ],
            }]
        })
        .to_string();
        let recheck = parse_response(&body, "cds-0").expect("decode");
        assert!(
            !recheck.ok,
            "lean errors must veto ok even when probes pass"
        );
        assert!(
            recheck
                .messages
                .iter()
                .any(|m| m.severity == LeanSeverity::Error)
        );
    }

    #[test]
    fn parse_response_marks_missing_probes_as_not_ok() {
        let body = json!({
            "results": [{
                "custom_id": "cds-0",
                "messages": [
                    { "severity": "info", "data": "PROBE byte_len=42" },
                    { "severity": "info", "data": "PROBE starts_paren=true" },
                    // has_assume missing
                    { "severity": "info", "data": "PROBE has_rule=true" },
                ],
            }]
        })
        .to_string();
        let recheck = parse_response(&body, "cds-0").expect("decode");
        assert!(!recheck.ok);
    }

    #[test]
    fn parse_response_rejects_invalid_json() {
        let err = parse_response("not json", "cds-0").expect_err("must fail");
        match err {
            LeanError::DecodeFailed { reason } => assert!(reason.contains("not valid JSON")),
            other => panic!("expected DecodeFailed, got {other:?}"),
        }
    }

    #[test]
    fn parse_response_rejects_empty_results_array() {
        let body = json!({"results": []}).to_string();
        let err = parse_response(&body, "cds-0").expect_err("must fail");
        match err {
            LeanError::DecodeFailed { reason } => assert!(reason.contains("empty results")),
            other => panic!("expected DecodeFailed, got {other:?}"),
        }
    }

    #[test]
    fn decode_messages_handles_severity_aliases() {
        let raw = json!([
            { "severity": "Info", "data": "x" },
            { "severity": "warning", "data": "y" },
            { "severity": "ERROR", "data": "z" },
            { "level": "warn", "text": "legacy" },
        ]);
        let msgs = decode_messages(&raw).expect("decode");
        assert_eq!(msgs[0].severity, LeanSeverity::Info);
        assert_eq!(msgs[1].severity, LeanSeverity::Warning);
        assert_eq!(msgs[2].severity, LeanSeverity::Error);
        assert_eq!(msgs[3].severity, LeanSeverity::Warning);
        assert_eq!(msgs[3].body, "legacy");
    }

    #[test]
    fn extract_probes_strips_lean_eval_quotes() {
        let msgs = vec![crate::lean::LeanMessage {
            severity: LeanSeverity::Info,
            body: "\"PROBE byte_len=128\"".to_string(),
        }];
        let probes = extract_probes(&msgs);
        assert_eq!(probes.get("byte_len").map(String::as_str), Some("128"));
    }

    #[test]
    fn probes_satisfied_requires_all_four_and_positive_byte_len() {
        let mut probes = BTreeMap::new();
        probes.insert("byte_len".to_string(), "0".to_string());
        probes.insert("starts_paren".to_string(), "true".to_string());
        probes.insert("has_assume".to_string(), "true".to_string());
        probes.insert("has_rule".to_string(), "true".to_string());
        assert!(!probes_satisfied(&probes), "byte_len=0 must not satisfy");

        probes.insert("byte_len".to_string(), "10".to_string());
        assert!(probes_satisfied(&probes));

        probes.insert("starts_paren".to_string(), "false".to_string());
        assert!(!probes_satisfied(&probes));
    }
}
