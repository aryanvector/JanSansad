"""Metrics for required evidence groups, not exhaustive document relevance."""
from __future__ import annotations


def evidence_metrics(ranked_ids: list[str], groups: list[dict], k: int) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    if not groups or any(not g.get("any_of") for g in groups):
        raise ValueError("At least one nonempty evidence group is required")
    ranked = list(dict.fromkeys(ranked_ids))[:k]
    hits = [bool(set(g["any_of"]) & set(ranked)) for g in groups]
    relevant = {qid for g in groups for qid in g["any_of"]}
    first = next((i + 1 for i, qid in enumerate(ranked) if qid in relevant), None)
    return {
        "group_coverage": sum(hits) / len(hits),
        "complete_evidence": float(all(hits)),
        "reciprocal_rank": 1 / first if first else 0.0,
    }
