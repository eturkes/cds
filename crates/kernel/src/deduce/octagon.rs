//! Octagon abstract domain over the canonical-vital namespace.
//!
//! Phase 0 implementation of the relational octagonal domain (Miné, 2006):
//! constraints have the form `±x ±y ≤ c` over real-valued canonical vitals.
//! The state is a `2n × 2n` Difference Bound Matrix (DBM) where
//! `v_{2k} = +x_k` and `v_{2k+1} = -x_k` are the encoded literals; cell
//! `m[i][j]` is the (currently-known) upper bound on `v_i - v_j`. `None`
//! denotes `+∞` (an unbounded cell, semantically `⊤`).
//!
//! Phase 0 only emits **single-variable interval constraints** (`+x ≤ c` and
//! `-x ≤ c`) from observed telemetry samples. Pairwise relational
//! tightening (`+x +y ≤ c`, etc.) and Floyd-Warshall closure are deferred
//! to a later phase per ADR-013; for the single-variable subset of the
//! octagonal lattice the cell-wise lattice operations already produce
//! closed forms.
//!
//! Streaming semantics: each telemetry sample yields a *point* octagon
//! (`top()` then `tighten_point` per vital); the streaming hull is the
//! cell-wise *join* (LUB) across point octagons. `tighten_*` therefore
//! has *meet* semantics — each invocation can only narrow the cell.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::canonical::{CANONICAL_VITALS, vital_index};

/// Octagon state — `2n × 2n` DBM over the canonical-vital namespace.
#[derive(Debug, Clone, PartialEq)]
pub struct Octagon {
    n: usize,
    /// `m[i][j]` = upper bound on `v_i - v_j`. `None` ≡ `+∞`.
    /// Diagonal (`m[i][i]`) is pinned to `0.0` for any consistent state.
    m: Vec<Vec<Option<f64>>>,
}

/// Closed scalar interval `[low, high]` for a single vital. Both endpoints
/// are finite by construction (the octagon only emits intervals when both
/// the `+x` and `-x` cells are bounded).
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct VitalInterval {
    pub low: f64,
    pub high: f64,
}

/// Errors raised when tightening or interrogating an `Octagon`.
#[derive(Debug, thiserror::Error, PartialEq)]
pub enum DomainError {
    /// The vital name is not in the canonical-vital allowlist.
    #[error("unknown vital: {0}")]
    UnknownVital(String),
    /// Caller passed `low > high` to `tighten_interval`.
    #[error("empty interval: low={low} > high={high}")]
    EmptyInterval { low: f64, high: f64 },
    /// Caller passed a non-finite scalar to a tighten operation.
    #[error("non-finite scalar: {0}")]
    NonFinite(f64),
}

impl Octagon {
    /// `⊤` over the full canonical-vital namespace — every cell is
    /// unbounded except the diagonal.
    #[must_use]
    pub fn top() -> Self {
        Self::top_with_arity(CANONICAL_VITALS.len())
    }

    fn top_with_arity(n: usize) -> Self {
        let dim = 2 * n;
        let mut m = vec![vec![None; dim]; dim];
        for (i, row) in m.iter_mut().enumerate().take(dim) {
            row[i] = Some(0.0);
        }
        Self { n, m }
    }

    fn pos(k: usize) -> usize {
        2 * k
    }

    fn neg(k: usize) -> usize {
        2 * k + 1
    }

    /// Returns the vital count (always `CANONICAL_VITALS.len()` in Phase 0).
    #[must_use]
    pub fn arity(&self) -> usize {
        self.n
    }

    /// Tighten using a single-vital interval observation.
    ///
    /// Adds the octagonal constraints `+x ≤ high` and `-x ≤ -low`, encoded
    /// in the DBM as:
    /// - `m[+x][-x] = +x − (−x) = 2x ≤ 2·high` → `m[2k][2k+1] ≤ 2·high`
    /// - `m[-x][+x] = −x − (+x) = −2x ≤ −2·low` → `m[2k+1][2k] ≤ −2·low`
    ///
    /// # Errors
    /// Returns [`DomainError::UnknownVital`] if `name` is outside
    /// [`CANONICAL_VITALS`], [`DomainError::EmptyInterval`] when
    /// `low > high`, and [`DomainError::NonFinite`] if either endpoint is
    /// not finite.
    pub fn tighten_interval(&mut self, name: &str, low: f64, high: f64) -> Result<(), DomainError> {
        let k = vital_index(name).ok_or_else(|| DomainError::UnknownVital(name.to_owned()))?;
        if !low.is_finite() {
            return Err(DomainError::NonFinite(low));
        }
        if !high.is_finite() {
            return Err(DomainError::NonFinite(high));
        }
        if low > high {
            return Err(DomainError::EmptyInterval { low, high });
        }
        let p = Self::pos(k);
        let n = Self::neg(k);
        update_min(&mut self.m[p][n], 2.0 * high);
        update_min(&mut self.m[n][p], -2.0 * low);
        Ok(())
    }

    /// Tighten with a degenerate interval — observe the vital at exactly
    /// `value`. Equivalent to `tighten_interval(name, value, value)`.
    ///
    /// # Errors
    /// See [`tighten_interval`](Self::tighten_interval).
    pub fn tighten_point(&mut self, name: &str, value: f64) -> Result<(), DomainError> {
        self.tighten_interval(name, value, value)
    }

    /// Octagonal least upper bound — cell-wise max of two states. `None`
    /// (`+∞`) absorbs any finite cell.
    ///
    /// # Panics
    /// Panics if `self.arity() != other.arity()`. In Phase 0 every
    /// `Octagon` is constructed with the canonical-vital arity so this is
    /// effectively unreachable; the assertion exists to surface a future
    /// arity-mismatch refactor immediately rather than producing silently
    /// wrong joins.
    #[must_use]
    pub fn join(self, other: &Self) -> Self {
        assert_eq!(
            self.n, other.n,
            "octagon join: arity mismatch ({} vs {})",
            self.n, other.n
        );
        let mut out = self;
        let dim = 2 * out.n;
        for i in 0..dim {
            for j in 0..dim {
                out.m[i][j] = max_opt(out.m[i][j], other.m[i][j]);
            }
        }
        out
    }

    /// Recover the closed scalar interval for `name`. Returns `None` if
    /// either bound is still `+∞` or if `name` is non-canonical.
    #[must_use]
    pub fn bounds(&self, name: &str) -> Option<VitalInterval> {
        let k = vital_index(name)?;
        let p = Self::pos(k);
        let n = Self::neg(k);
        let high = self.m[p][n].map(|c| c / 2.0)?;
        let neg_low = self.m[n][p].map(|c| c / 2.0)?;
        let low = -neg_low;
        Some(VitalInterval { low, high })
    }

    /// Lexicographically-keyed snapshot of every bounded vital in the state.
    /// Vitals that are still `⊤` (no observations recorded) are omitted.
    #[must_use]
    pub fn snapshot(&self) -> BTreeMap<String, VitalInterval> {
        let mut out = BTreeMap::new();
        for name in CANONICAL_VITALS {
            if let Some(interval) = self.bounds(name) {
                out.insert(name.to_owned(), interval);
            }
        }
        out
    }
}

impl Default for Octagon {
    fn default() -> Self {
        Self::top()
    }
}

fn update_min(slot: &mut Option<f64>, candidate: f64) {
    *slot = Some(match *slot {
        Some(c) if c <= candidate => c,
        _ => candidate,
    });
}

fn max_opt(a: Option<f64>, b: Option<f64>) -> Option<f64> {
    match (a, b) {
        (Some(x), Some(y)) => Some(x.max(y)),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::{DomainError, Octagon, VitalInterval};

    fn approx_eq(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn top_has_no_finite_bounds() {
        let o = Octagon::top();
        assert!(o.bounds("heart_rate_bpm").is_none());
        assert!(o.snapshot().is_empty());
    }

    #[test]
    fn point_observation_yields_degenerate_interval() {
        let mut o = Octagon::top();
        o.tighten_point("heart_rate_bpm", 72.5).unwrap();
        let i = o.bounds("heart_rate_bpm").unwrap();
        assert!(approx_eq(i.low, 72.5));
        assert!(approx_eq(i.high, 72.5));
    }

    #[test]
    fn sequential_tighten_intersects() {
        // tighten ≡ meet — two overlapping observations should narrow the cell,
        // never widen it.
        let mut o = Octagon::top();
        o.tighten_interval("spo2_percent", 90.0, 100.0).unwrap();
        o.tighten_interval("spo2_percent", 92.0, 98.0).unwrap();
        let i = o.bounds("spo2_percent").unwrap();
        assert!(approx_eq(i.low, 92.0));
        assert!(approx_eq(i.high, 98.0));
    }

    #[test]
    fn join_widens_to_convex_hull() {
        // Two point observations joined → convex hull (interval [a, b]).
        let mut a = Octagon::top();
        a.tighten_point("heart_rate_bpm", 72.5).unwrap();
        let mut b = Octagon::top();
        b.tighten_point("heart_rate_bpm", 76.0).unwrap();
        let hull = a.join(&b);
        let i = hull.bounds("heart_rate_bpm").unwrap();
        assert!(approx_eq(i.low, 72.5));
        assert!(approx_eq(i.high, 76.0));
    }

    #[test]
    fn join_with_top_yields_top_for_unobserved_vital() {
        let mut observed = Octagon::top();
        observed.tighten_point("heart_rate_bpm", 70.0).unwrap();
        let hull = observed.join(&Octagon::top());
        // heart rate was observed in `observed` only; in `top` it is +∞ — so
        // the join (cell-wise max) is +∞ for the +x cell, i.e. unbounded.
        assert!(hull.bounds("heart_rate_bpm").is_none());
    }

    #[test]
    fn unknown_vital_is_rejected() {
        let mut o = Octagon::top();
        let err = o.tighten_point("glucose_mgdl", 5.5).unwrap_err();
        assert_eq!(err, DomainError::UnknownVital("glucose_mgdl".to_string()));
    }

    #[test]
    fn empty_interval_is_rejected() {
        let mut o = Octagon::top();
        let err = o.tighten_interval("temp_celsius", 38.0, 36.0).unwrap_err();
        assert_eq!(
            err,
            DomainError::EmptyInterval {
                low: 38.0,
                high: 36.0
            }
        );
    }

    #[test]
    fn non_finite_scalar_is_rejected() {
        let mut o = Octagon::top();
        assert!(matches!(
            o.tighten_point("heart_rate_bpm", f64::NAN),
            Err(DomainError::NonFinite(_))
        ));
        assert!(matches!(
            o.tighten_point("heart_rate_bpm", f64::INFINITY),
            Err(DomainError::NonFinite(_))
        ));
    }

    #[test]
    fn snapshot_keys_are_lexicographic() {
        let mut o = Octagon::top();
        o.tighten_point("temp_celsius", 36.7).unwrap();
        o.tighten_point("heart_rate_bpm", 72.5).unwrap();
        o.tighten_point("diastolic_mmhg", 82.0).unwrap();
        let snap: Vec<String> = o.snapshot().keys().cloned().collect();
        let mut sorted = snap.clone();
        sorted.sort();
        assert_eq!(snap, sorted);
    }

    #[test]
    fn vital_interval_round_trips_json() {
        let i = VitalInterval {
            low: 70.0,
            high: 80.0,
        };
        let s = serde_json::to_string(&i).unwrap();
        let back: VitalInterval = serde_json::from_str(&s).unwrap();
        assert_eq!(i, back);
    }
}
