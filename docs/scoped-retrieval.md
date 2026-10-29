# Answer-date, named-anchor and passage retrieval

This feature applies to AI answers over Q&A records. Debates, mixed-content queries and requests with no recognised source scope keep their existing paths, including the calendar-year comparison feature.

## Implementation

1. `core/scoped_retrieval.py` recognises common English answer/reply-date forms, including ISO dates, Indian day/month/year notation, and English month names. It validates calendar dates and separates common as-of/advisory dates from record dates.
2. Exact dates become Qdrant payload filters and parameterized date constraints in the historical Rajya Sabha lexical store. Existing House, Lok Sabha, session, ministry and MP filters are retained.
3. Named text anchors are inferred conservatively from capitalised phrases and explicitly labelled constituency/district names. A small programme-alias list covers common scheme spellings. These are text heuristics, not a national geographic gazetteer or a general-purpose NER model.
4. The initial M budget is divided between requested dates or named-anchor subqueries. Candidate Q&A records are then inspected through at most 64 existing indexed chunks per record. No PDFs are downloaded or reparsed during a user search.
5. Candidate records must match the active programme and named-anchor conditions. Source ranking favours query terms and names in the title/opening text. The final N records reserve slots for requested dates/anchors where available.
6. A lexical passage ranking selects at most C matching passages per record. The first passage of the document is no longer mandatory on this path. Each selected source receives one passage before extra passages are added, within M.
7. The generator receives the original user question, source-scope metadata and selected passages. The interface displays the requested date/name/scheme scope and shows the same passages behind citations. Lexical rank is labelled “Scoped source”, not a confidence percentage.
8. When no matching evidence is retrieved, the API returns a clear 404 rather than generating from another date or location. The message does not assert that the user's date/place is wrong or that Parliament has no such record.

### Bounded no-match recovery (26 October follow-up)

If an initial source-date/anchor slot lacks an eligible record and a recognised programme is present, one extra search pass uses just programme and named-anchor terms. The exact source dates and all user filters remain in force. New candidates undergo the same programme/name checks, bounded 64-passage scan and original-query passage ranking. Previously inspected records are not fetched again. Recovery is not attempted when a slot already has a valid record, or when the simplified query is unchanged. At most M additional search results are requested across missing slots; the final M/N/C limits remain unchanged. This increases retrieval work, so evaluation must account for the extra pass.

This fixes the observed short Bihar PM SHRI paraphrase. It does not guarantee paraphrase recall or rescue unsupported schemes, and it never proves archive-wide absence. Missing anchors within a date slot that already has an eligible record still rely on the existing partial-coverage notice; this recovery is not a general multi-entity completeness guarantee.

For numeric requests, a table containing numeric cells and at least two original query terms receives an additional passage-ranking weight. An explicit short currency-unit heading immediately before a table chunk is copied with an attribution label into that table's context. No unit is inferred from a distant passage or another record. This preserves the C passage limit but adds the adjacent source heading; it is not an equal-context ablation and does not guarantee correct table interpretation.

## Important boundaries

- Answer date, observation date, advisory date, scheme period and financial year are different concepts. The parser handles common forms; it does not solve arbitrary temporal language.
- Up to four parsed dates and four named anchors are considered. Ambiguous wording, unusual capitalisation, lower-case locations without explicit tags, non-English dates and names may be missed or misclassified.
- Named matches are not verified constituency identities. Names can occur in country-wide annexures or have multiple meanings. Title/opening-text ranking helps, but does not eliminate these ambiguities.
- Programme aliases are a bounded list, not coverage of every government scheme. Multi-scheme queries can be too restrictive because matching currently requires all recognised programme aliases in an eligible record.
- The scan cap can omit later content in very long records. Context C still limits how many relevant passages reach Gemini.
- Although initial candidate M and final N/C caps are retained, scanning candidate records adds payload reads and lexical reranking. This is not an equal-compute comparison against the previous pipeline.
- Source constraints, reference-document recovery and a valid citation ID do not certify every generated claim. Arithmetic, status interpretation and extra source-date statements can still be wrong.

## Verification

74 focused tests passed, covering the new scope path together with prior temporal retrieval, grounding, provider and cross-House tests. They cover source/as-of date separation, calendar validity, existing-filter intersections, later-passage selection, scheme/name mismatches, budgets, preservation of two requested dates and no-generation failure handling.

Live checks include 12 selected failed development cases, five fresh reference-source-separated cases with before/after outputs, two negative API cases, and a browser check. The narrow-screen source notice was inspected at 360 pixels without page overflow. Background debate indexing was resumed after the app restart.

See [the development report](../research/scoped-retrieval-check/report.md) for measured outcomes and remaining errors.

## Explicit comparison revision v2

Supported English comparisons with two to four full answer dates now receive per-side topic/date/House checks instead of applying every topic globally. A single shared House/topic can be inherited, but conflicting user filters are not relaxed. The system reserves sources across sides, marks missing sides explicitly and rejects same-date unrelated candidates by conservative lexical criteria. Matched records still do not guarantee complete fact/citation support. Single-date and calendar-year paths remain separate.

61 selected tests passed; three inspected v1 examples were checked as development regressions, not independent accuracy evidence. The app was restarted and live missing-evidence behavior checked; background debate indexing resumed. See `research/comparison-slot-v2/report.md`. Complementary passage/table selection and checker false warnings remain pending.

## Complementary numeric passages v3

Scoped record ranking now prioritises passages adding requested numeric facets not yet covered, with original relevance order as tie-breaker. Plain extracted count tables and separate financial paragraphs can therefore both fit within C=2. No source text is merged across records, no unit is inferred, and M/N/C limits are unchanged. The finite lexical facet list is a heuristic, not a completeness guarantee. Single-facet/non-numeric ordering stays unchanged.

69 selected tests passed. An inspected Odisha regression now supplies counts and allocation together in chunks 1 and 2; no generated-answer score is claimed. The running app was restarted and background indexing resumed. See `research/complementary-passages-v3/report.md`. Checker false warnings and independent answer validation remain pending.
