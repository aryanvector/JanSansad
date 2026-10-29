import pytest

from lok_sabha_rag.evaluation.metrics import evidence_metrics
from lok_sabha_rag.evaluation.run_pilot import bm25_scores, rank_documents, tokenize
from collections import Counter


def test_alternatives_are_not_all_required_and_duplicates_do_not_fill_k():
    groups = [{"any_of": ["a", "a_duplicate"]}, {"any_of": ["b"]}]
    m = evidence_metrics(["a_duplicate", "a_duplicate", "b"], groups, 2)
    assert m == {"group_coverage": 1, "complete_evidence": 1, "reciprocal_rank": 1}
    assert evidence_metrics(["a"], groups, 5)["complete_evidence"] == 0


def test_missing_group_and_cutoff():
    groups = [{"any_of": ["b"]}]
    assert evidence_metrics(["a", "b"], groups, 1)["group_coverage"] == 0
    assert evidence_metrics(["a", "b"], groups, 2)["reciprocal_rank"] == .5
    with pytest.raises(ValueError):
        evidence_metrics([], [], 5)
    with pytest.raises(ValueError):
        evidence_metrics([], groups, 0)


def test_document_dedup_keeps_best_chunk():
    chunks = [("a", {"point_id": "1", "payload": {"text": "one"}}),
              ("b", {"point_id": "2", "payload": {"text": "two"}}),
              ("a", {"point_id": "3", "payload": {"text": "three"}})]
    ranked = rank_documents([.1, .5, .9], chunks)
    assert [r["question_id"] for r in ranked] == ["a", "b"]
    assert ranked[0]["point_id"] == "3"


def test_bm25_prefers_matching_chunk_and_zero_for_no_overlap():
    counters = [Counter(tokenize("railway bridge inspection")), Counter(tokenize("minister appointment"))]
    df = Counter(t for c in counters for t in c)
    scores = bm25_scores("bridge", counters, [3, 2], df)
    assert scores[0] > scores[1] == 0
