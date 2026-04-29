"""cds_harness — neurosymbolic CDS Python harness (Phase 0 placeholder).

Phase 0 placeholder. Real autoformalization (CLOVER + NL2LOGIC), ontology
alignment (GraphRAG + ELK + owlapy), defeasible reasoning (clingo), and SMT
orchestration (Z3 / cvc5) land in Tasks 4 and 6 respectively.
"""

from __future__ import annotations

__version__: str = "0.0.0"
HARNESS_ID: str = "cds-harness"
PHASE: int = 0

__all__ = ["HARNESS_ID", "PHASE", "__version__"]
