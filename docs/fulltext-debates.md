# Cross-House debate catalogue and incremental speech-text search

## Published catalogue coverage

| House | Usable Part-II records | Actual dates returned |
|---|---:|---|
| Lok Sabha | 47,767 | 12 February 2009–3 August 2026 |
| Rajya Sabha | 25,442 | 12 February 2009–4 April 2025 |

The requested range is 2009–2026. These dates describe the imported source
responses, not guaranteed complete parliamentary coverage. There are no 2026
Rajya Sabha entries in this imported source response. Q&A remains a separate
corpus and is excluded from both Part-II imports.

Lok Sabha's official debate page points to the eLibrary DSpace Part-II collection
`03c67f26-e547-4c6f-914d-e4b443281a8c`. The importer fetched 507 source pages,
checked their reported counts and unique item UUIDs, then applied strict local
date/type validation. Of 50,628 response items, 2,853 were outside the requested
date range and eight lacked titles; 47,767 usable records were published.
Server-side range querying alone is not trusted. Compressed source responses
remain available for reproducibility. Roman-numeral session numbers are converted
to integers while preserving the original source metadata in the source cache.

Sources:

- https://sansad.in/ls/debates/digitized
- https://elibrary.sansad.in/server/api/core/collections/03c67f26-e547-4c6f-914d-e4b443281a8c
- https://sansad.in/rs/debates/officials

## What changed in search

Choose House **Lok Sabha**, **Rajya Sabha** or **Both Houses**, and Content
**Debates** or **All records**. Search now combines:

1. Existing catalogue metadata search (title/category/participants/ministry).
2. FTS5 keyword retrieval over the speech text processed so far.

Ranks are combined, not raw BM25/vector similarity scores. A result badge
distinguishes **Speech text match** from **Catalogue match**. Speech matches
preserve the actual matching chunk in both the source expansion and synthesis
context; grouping does not replace it with an unrelated document opening.

Metadata coverage is complete for this published snapshot. **Full-text ingestion
is incremental and not complete.** A separate coverage line shows the number of
successfully indexed documents for each House and the background job status.
It refreshes every 20 seconds while a debate mode is selected. Keyword retrieval
is not semantic retrieval or Hindi/Hinglish translation, and it is not a measured
guarantee of retrieval completeness. Long speeches provide matching excerpts,
not exhaustive context.

## Document integrity and attribution

Lok Sabha original PDFs are resolved via the official item's ORIGINAL bundle.
The importer does not assume a TEXT bundle corresponds to the same PDF or
language. Original PDFs are parsed directly in the bounded extraction worker
introduced for bill PDFs (20 MB, 150 pages, 45-second extraction deadline).
eLibrary hosts, paths and redirects are restricted. Missing/scanned/unavailable
documents are reported as failed attempts and not indexed as speech text.

Rajya Sabha PDF filenames are checked against session/date where those identifiers
are encoded. Some source PDFs include adjacent speeches on the same physical
page. Before indexing, the selected debate heading must be located in the text;
the text is bounded by that heading and the next known heading from the same
day's catalogue. A missing heading produces **scope_unverified**, preserving the
metadata/PDF without indexing potentially misattributed text. This boundary
heuristic cannot prove perfect speech segmentation, and unknown/missing headings
can still limit coverage. There is no OCR.

Result participants remain **participants**, not automatically the speaker of
every sentence. Speaker attribution requires an explicit name in the transcript.
Participation does not establish a vote, party position or support/opposition.
Full-text debate links open the original PDF; this release does not invent
per-passage PDF page positions where only joined transcript text is available.

## Background indexing and operation

The job interleaves both Houses, newest documents first within each House. It
uses two workers and no paid AI/embedding calls. Successfully indexed and failed
attempt IDs are persisted in `/app/data/debate_fulltext/index.db`, so restarting
the command skips completed work. Failures require `--retry-failed` to retry.
The job stops if available storage drops below 2 GB. A process lock prevents
duplicate workers; progress is written atomically.

Inside the app container:

```text
.venv/bin/python -u -m lok_sabha_rag.pipeline.index_debates --log-file data/debate_fulltext/worker.log
```

For a bounded batch, add `--limit 100`. To stop gracefully, create
`/app/data/debate_fulltext/STOP`; remove it before resuming. The job survives a
chat turn but needs Docker/the computer to remain running. Container restart or
shutdown interrupts it; it does not automatically resume. The coverage endpoint
detects a missing worker process rather than silently showing a stale running
state. `/api/corpus-coverage` exposes indexed counts, failed statuses, queue
progress and the last processed record.

The complete catalogue has 73,209 records, so full PDF processing is substantial.
No completion time or fully searchable archive is claimed while this job runs.
Source availability, extraction limits and heading checks can prevent some
records from becoming full-text searchable even after all records are attempted.

Metadata refresh command (host Python, standard library only):

```text
python scripts/import_ls_debates.py NEW_OUTPUT_DIRECTORY --from-year 2009 --to-year 2026
```

Publish successful `debates.db` and `manifest.json` atomically into
`/app/data/ls_debates`. Use a fresh source-cache directory for a new snapshot.

## Verification

83 tests passed across the existing corpus/profile/document suites, bill
features and 11 new full-text/LS tests. The new tests cover body-only matching,
House/Lok Sabha/session/participant filters, replacement without duplication,
failed extraction, SQL-safe queries, actual matched-chunk preservation, LS type
and session normalization, official URL restrictions and adjacent-speech exclusion.

Live example: search **Namkhana**, House **Lok Sabha**, Content **Debates**, with
AI synthesis off. The 3 August 2026 railway-bridge speech by the explicitly named
Pratima Mondal contains that word in its body but not its catalogue title.
The result shows Speech text match and opens the official PDF. The browser also
verified the expanded matching passage and separate indexing-progress line.

The prior Sanskrit-education record no longer matches a mangrove passage from
the preceding speech after title bounding. Existing Lok Sabha Q&A search was
rechecked. Synthesis grouping/context can be tested with a mocked model; actual
AI answers still depend on restoring the configured provider's exhausted credits.
