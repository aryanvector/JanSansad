# Calendar-year comparison retrieval

Implemented for AI answers over parliamentary Q&A. The ordinary document search, debates, mixed-record searches and non-comparison questions retain their existing retrieval path.

## Behaviour

1. Detect an explicit comparison cue with two to four calendar years. English and selected Hinglish/Hindi comparison terms are supported. Small explicit ranges are expanded.
2. Keep the topic in the retrieval query; remove calendar-year tokens and secondary output/missing-evidence instructions. The original user question is still sent unchanged to Gemini.
3. Divide M between year subqueries. Apply exact record-date constraints to dense search and the historical Rajya Sabha lexical store. Keep House, Lok Sabha, session, ministry and member filters.
4. Interleave candidates and balance the N selected Q&A records across requested years. The existing C budget still preserves a matching passage plus opening context where space permits.
5. Return `period_coverage`, measured from the final selected records. Add a source-coverage note to the generator context and display it above the answer.
6. Preserve source dates, observation/as-of dates, units, version and operational/planned status in the answer. Missing source years are explicit; they are not backfilled with another year.

M remains a returned-candidate cap, not a promise that every query fills the budget. N and C remain caps too. Year-specific subqueries add request overhead; equal output budgets do not establish equal runtime or compute cost.

## Boundaries

- Retrieval uses the parliamentary record/answer date. That date is not necessarily the observation period of every fact in the document.
- No calendar-year split is applied to financial-year wording/shorthand, exact-date ranges, long year ranges, or milestone comparisons without an explicit record/report cue. These use the normal path. This is a conservative heuristic, not a general temporal-language parser.
- Records from both years do not prove that equivalent metrics or complete evidence were retrieved. A table of locomotive counts cannot be treated as route kilometres, and a tender is not commissioned coverage.
- A year with no selected source is a context gap; it is not proof that Parliament never discussed the topic.
- Existing ISO date-only payloads are filtered without changing stored records or rebuilding embeddings. No new production index or collection was created.
- Generation remains probabilistic. Prompt instructions encourage proper unit/status handling but are not a claim-level verifier.

## Implementation

- `core/temporal_retrieval.py`: detection, topic query, bounded retrieval, balanced selection and coverage metadata.
- `core/retriever.py`: record-year filtering, balanced grouping and per-client query locking.
- `core/kaggle_store.py`: parameterized filtering on the stored JSON record date.
- `api/routes/synthesize.py`: activates the new path and passes scope to Gemini.
- `frontend/app.js`, `frontend/workspace.css`: coverage notice and scrollable comparison tables on phones.

The query lock addresses a live concurrency failure in the Qdrant client's mutable local embedding accumulator. Concurrent requests sharing a client are serialized around its query operation; they can no longer change that accumulator during another query's iteration.

## Verification

55 focused tests passed, including detection boundaries, budgets, user-filter preservation, exact/leap-year dates, SQLite filtering, missing years, final N selection, synthesis coverage and concurrency. Two simultaneous live document-search requests subsequently returned HTTP 200 with results. Live comparison, missing-year, normal-query and browser checks are recorded in `research/period-retrieval-check/`.
