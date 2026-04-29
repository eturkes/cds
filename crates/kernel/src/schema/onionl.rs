//! `OnionL_IR_Tree` — the autoformalized intermediate representation.
//!
//! Recursive ADT lifted from natural-language guideline text by the
//! CLOVER + NL2LOGIC pipeline (ADR-005). Every leaf `Atom` carries a
//! `SourceSpan` so a downstream MUC can be projected back onto the original
//! textual fragment (constraint C4).
//!
//! Wire format uses internally-tagged discriminated unions: the variant
//! discriminator is the `snake_case` string `kind` (`scope`, `relation`,
//! `indicator_constraint`, `atom`). Term variants share the same convention
//! (`variable`, `constant`).

use serde::{Deserialize, Serialize};

/// Top-level IR envelope — schema version + a single root node.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OnionLIRTree {
    pub schema_version: String,
    pub root: OnionLNode,
}

/// One node of the `OnionL` recursive ADT.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum OnionLNode {
    /// A textual region: document / section / guideline / sub-clause.
    Scope {
        id: String,
        scope_kind: String,
        children: Vec<OnionLNode>,
    },
    /// An n-ary logical relation (e.g. conjunction, less-than).
    Relation { op: String, args: Vec<OnionLNode> },
    /// A guarded indicator: `guard ⇒ body`. Preserves LP relaxations
    /// downstream of the rule-execution stage.
    IndicatorConstraint {
        guard: Box<OnionLNode>,
        body: Box<OnionLNode>,
    },
    /// A first-order atom — the only variant that participates in the MUC
    /// → text projection (its `source_span` is the projection target).
    Atom {
        predicate: String,
        terms: Vec<Term>,
        source_span: SourceSpan,
    },
}

/// Variable or constant occurring as an argument to a predicate.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Term {
    Variable { name: String },
    Constant { value: String },
}

/// Projection target back to the originating natural-language document.
/// `start` and `end` are byte offsets; `doc_id` is the upstream document
/// identifier.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SourceSpan {
    pub start: usize,
    pub end: usize,
    pub doc_id: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> OnionLIRTree {
        OnionLIRTree {
            schema_version: "0.1.0".to_string(),
            root: OnionLNode::Scope {
                id: "doc-1".to_string(),
                scope_kind: "guideline".to_string(),
                children: vec![OnionLNode::IndicatorConstraint {
                    guard: Box::new(OnionLNode::Atom {
                        predicate: "has_diagnosis".to_string(),
                        terms: vec![
                            Term::Variable {
                                name: "P".to_string(),
                            },
                            Term::Constant {
                                value: "diabetes".to_string(),
                            },
                        ],
                        source_span: SourceSpan {
                            start: 0,
                            end: 30,
                            doc_id: "guideline-001".to_string(),
                        },
                    }),
                    body: Box::new(OnionLNode::Relation {
                        op: "less_than".to_string(),
                        args: vec![
                            OnionLNode::Atom {
                                predicate: "hba1c".to_string(),
                                terms: vec![Term::Variable {
                                    name: "P".to_string(),
                                }],
                                source_span: SourceSpan {
                                    start: 31,
                                    end: 60,
                                    doc_id: "guideline-001".to_string(),
                                },
                            },
                            OnionLNode::Atom {
                                predicate: "literal".to_string(),
                                terms: vec![Term::Constant {
                                    value: "7.0".to_string(),
                                }],
                                source_span: SourceSpan {
                                    start: 60,
                                    end: 65,
                                    doc_id: "guideline-001".to_string(),
                                },
                            },
                        ],
                    }),
                }],
            },
        }
    }

    #[test]
    fn round_trip_json() {
        let original = fixture();
        let serialized = serde_json::to_string(&original).expect("serialize");
        let deserialized: OnionLIRTree = serde_json::from_str(&serialized).expect("deserialize");
        assert_eq!(original, deserialized);
    }

    #[test]
    fn atom_carries_source_span() {
        // Constraint C4: every Atom MUST carry a source_span.
        let json = serde_json::to_string(&fixture()).expect("serialize");
        let atom_count = json.matches(r#""kind":"atom""#).count();
        let span_count = json.matches(r#""source_span""#).count();
        assert_eq!(
            atom_count, span_count,
            "every atom must serialize a source_span"
        );
    }

    #[test]
    fn variant_discriminator_is_kind() {
        let json = serde_json::to_string(&fixture()).expect("serialize");
        for tag in ["scope", "indicator_constraint", "atom", "relation"] {
            assert!(
                json.contains(&format!(r#""kind":"{tag}""#)),
                "expected discriminator kind={tag} in {json}"
            );
        }
    }
}
