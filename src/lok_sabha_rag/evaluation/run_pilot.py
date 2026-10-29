"""Read-only frozen-corpus retrieval references. No Qdrant writes or LLM calls.

python -m lok_sabha_rag.evaluation.run_pilot --pilot /tmp/pilot-v1
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import time

from .metrics import evidence_metrics


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def rank_documents(scores, chunks) -> list[dict]:
    """Keep the highest scoring chunk per document; stable ID tie break."""
    best = {}
    for score, (qid, chunk) in zip(scores, chunks):
        score = float(score)
        if not math.isfinite(score):
            raise ValueError("Non-finite retrieval score")
        if qid not in best or score > best[qid]["score"]:
            best[qid] = {"question_id": qid, "score": score,
                         "point_id": chunk["point_id"],
                         "excerpt": chunk["payload"]["text"][:600]}
    return sorted(best.values(), key=lambda row: (-row["score"], row["question_id"]))


def bm25_scores(query: str, counters: list[Counter], lengths: list[int], df: Counter):
    """Okapi BM25, chunk level, k1=1.5 and b=.75; no tuned stopword list."""
    n = len(counters)
    avg = sum(lengths) / n
    terms = set(tokenize(query))
    scores = []
    for counter, length in zip(counters, lengths):
        score = 0.0
        for term in terms:
            freq = counter[term]
            if freq:
                idf = math.log(1 + (n - df[term] + .5) / (df[term] + .5))
                score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * length / avg))
        scores.append(score)
    return scores


def run(pilot: Path, output: Path, cache: str) -> dict:
    import numpy as np
    from fastembed import TextEmbedding
    from lok_sabha_rag.config import EMBEDDING_MODEL

    manifest_bytes = (pilot / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    for filename, digest in manifest["files"].items():
        if hashlib.sha256((pilot / filename).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Frozen file hash mismatch: {filename}")
    docs = [json.loads(line) for line in (pilot / "documents.jsonl").read_text(encoding="utf8").splitlines()]
    questions = [json.loads(line) for line in (pilot / "questions.jsonl").read_text(encoding="utf8").splitlines()]
    known = {d["question_id"] for d in docs}
    for q in questions:
        for group in q["evidence_groups"]:
            assert set(group["any_of"]) <= known
            doc = next(d for d in docs if d["question_id"] == group["checked_record"])
            text = "\n".join(c["payload"]["text"] for c in doc["chunks"])
            assert group["quote"] in text
            assert hashlib.sha256(group["quote"].encode()).hexdigest() == group["quote_sha256"]
    chunks = [(doc["question_id"], chunk) for doc in docs for chunk in doc["chunks"]]
    vectors = np.asarray([chunk["vector"] for _, chunk in chunks], dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[1] != 384 or not np.isfinite(vectors).all():
        raise ValueError("Invalid source vectors")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("Zero source vector")
    vectors /= norms
    counters = [Counter(tokenize(chunk["payload"]["text"])) for _, chunk in chunks]
    lengths = [sum(c.values()) for c in counters]
    df = Counter(term for c in counters for term in c)
    start = time.perf_counter()
    model = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=cache, local_files_only=True)
    query_vectors = np.asarray(list(model.query_embed([q["query"] for q in questions])), dtype=np.float32)
    encoding_seconds = time.perf_counter() - start
    query_norms = np.linalg.norm(query_vectors, axis=1, keepdims=True)
    if not np.isfinite(query_vectors).all() or (query_norms == 0).any():
        raise ValueError("Invalid query embeddings")
    query_vectors /= query_norms
    output.mkdir(parents=True, exist_ok=True)
    # Reuse precisely the measured query embeddings for reproduction.
    np.save(output / "query-vectors.npy", query_vectors)
    rows = []
    for i, q in enumerate(questions):
        for name in ("bm25_reference", "dense_reference"):
            start = time.perf_counter()
            scores = (bm25_scores(q["query"], counters, lengths, df) if name == "bm25_reference"
                      else vectors @ query_vectors[i])
            ranking = rank_documents(scores, chunks)
            row = {"id": q["id"], "kind": q["kind"], "method": name, "query": q["query"],
                   "retrieval_seconds": time.perf_counter() - start,
                   "answerable": q["answerable"], "ranking": ranking[:10], "metrics": {}}
            if q["answerable"]:
                for k in (1, 3, 5, 10):
                    row["metrics"][str(k)] = evidence_metrics(
                        [r["question_id"] for r in ranking], q["evidence_groups"], k)
            rows.append(row)
    (output / "per-question.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf8")
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
               "model": EMBEDDING_MODEL, "fastembed_version": importlib.metadata.version("fastembed"),
               "documents": len(docs), "chunks": len(chunks),
               "answerable_questions": sum(q["answerable"] for q in questions),
               "unanswerable_questions_not_scored": sum(not q["answerable"] for q in questions),
               "encoding_and_model_load_seconds": encoding_seconds,
               "query_vectors_sha256": hashlib.sha256((output / "query-vectors.npy").read_bytes()).hexdigest(),
               "methods": {}, "limitations": [
                   "Development pilot, purposive railway selection, provisional labels; no held-out test.",
                   "Only known evidence groups are judged; relevance is not exhaustive.",
                   "References are not the current production hybrid search system.",
                   "No generated answers, correctness, faithfulness or abstention evaluated.",
                   "Record-level coverage does not prove the winning chunk or final context contains the supporting passage.",
                   "Dense source vectors were exported from existing indexes; index encoder provenance is not independently reconstructed.",
               ]}
    for method in ("bm25_reference", "dense_reference"):
        summary["methods"][method] = {}
        for kind in ("all_answerable", "single", "multi_evidence"):
            selected = [r for r in rows if r["method"] == method and r["answerable"]
                        and (kind == "all_answerable" or r["kind"] == kind)]
            summary["methods"][method][kind] = {"n": len(selected), "at_k": {}}
            for k in (1, 3, 5, 10):
                summary["methods"][method][kind]["at_k"][str(k)] = {
                    metric: sum(r["metrics"][str(k)][metric] for r in selected) / len(selected)
                    for metric in ("group_coverage", "complete_evidence", "reciprocal_rank")}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf8")
    lines = ["# Frozen railway development pilot: measured retrieval references", "",
             f"{summary['answerable_questions']} answerable questions; {summary['unanswerable_questions_not_scored']} unanswerable prompts retained for later human/generation review.",
             "Provisional labels and a small, topic-selected corpus: these are diagnostic results, not general accuracy.", "",
             "| Reference | Group coverage @5 | Complete evidence @5 | MRR @10 |", "|---|---:|---:|---:|"]
    for name, slices in summary["methods"].items():
        m5 = slices["all_answerable"]["at_k"]["5"]
        m10 = slices["all_answerable"]["at_k"]["10"]
        lines.append(f"| {name} | {m5['group_coverage']:.3f} | {m5['complete_evidence']:.3f} | {m10['reciprocal_rank']:.3f} |")
    lines += ["", "## Missing required evidence at k=5", ""]
    for row in rows:
        if row["answerable"] and row["metrics"]["5"]["complete_evidence"] < 1:
            lines.append(f"- {row['method']} / {row['id']}: {row['query']}")
    lines += ["", "## Interpretation limits", ""] + [f"- {s}" for s in summary["limitations"]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", default="/tmp/fastembed_cache")
    args = parser.parse_args()
    result = run(args.pilot, args.output or args.pilot / "baseline-results", args.cache)
    print(json.dumps(result, indent=2))
