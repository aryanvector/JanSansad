# Local coverage audit

Audited 26 October 2026. This checks local files and active indexes, not the entire government archive or the current reachability of every external PDF.

## Confirmed inventory

| Corpus | Actual local coverage | Meaning |
|---|---|---|
| Lok Sabha Q&A | 106,857 unique indexed questions; 611,915 chunks; 2 February 2018–17 March 2026 | Semantic text search. Local metadata has 106,896 questions; 39 have no indexed chunks. |
| Rajya Sabha Hugging Face | 500 questions; 2,187 chunks; 2–4 April 2025 | Active semantic pilot, not the complete upstream dataset. |
| Rajya Sabha Kaggle | 89,047 records; 20 November 2009–11 August 2017 | Keyword search. These imports do not cover all intervening years through 2025. |
| Lok Sabha debates | 47,767 catalogue entries; 12 February 2009–3 August 2026 | Catalogue coverage; indexed speech text is a smaller, changing subset. |
| Rajya Sabha debates | 25,442 catalogue entries; 12 February 2009–4 April 2025 | Requested import endpoint 2026 does not establish 2026 records. |
| Bills | 4,200 catalogue entries; introduction dates 13 February 2009–10 August 2026 | 4,197 records have supported document-version links. Links are not all downloaded/verified as reachable. |
| Cached bill text | 2 bills / 4 readable versions / 138 readable pages at audit | Document QA can load other supported PDFs on demand. Not every bill is already text searchable. |
| Minister directory | 474 records; 25 of 37 jurisdiction entries have records | A dated snapshot, not complete current nationwide coverage. Some UT entries describe administrations rather than elected cabinets. |

Date endpoints do not prove completeness or continuity. A parliamentary answer date is distinct from a statistic's reporting date.

## Implementation

- `core.coverage_inventory` performs an explicit read-only audit. It uses an exact question-id facet for the active Lok Sabha collection and checks that its hit counts equal all chunk points. Active RS pilot identities are obtained by scrolling payload IDs without vectors. Metadata-only questions do not inflate the active index count.
- SQLite record dates/counts are read from stored rows. Bill versions are counted only when the current extractor's cache and original PDF exist with readable pages; this is not a fresh remote/PDF integrity verification.
- Snapshot is stored atomically in the data volume as `coverage_inventory.json`. The website reads it without an expensive vector audit on every request. Its timestamp is shown explicitly; it must be refreshed after corpus changes.
- Debate text counts and extracted date ranges are computed from current local extraction status. The background worker can change these while the page is open. They are labelled separately from the static catalogue audit and are not a full government update feed.
- Main coverage panel filters the displayed sources by House/content, separates catalogue from indexed speech text, shows RS years present and timestamps, and avoids complete-archive claims.
- Bills page distinguishes catalogue records from cached readable document versions.
- Legacy `all_records` no longer uses the old RS-only partial sum: it now explicitly totals audited Q&A identities plus both debate catalogues, excluding bills/ministers and labelled as not all full text. No such total is substituted for searchable speech coverage.

## Refresh command

From the Windows terminal with the app running:

```powershell
wsl -d Ubuntu -u root --exec /usr/bin/docker exec lok-sabha-rag-app-1 .venv/bin/python -m lok_sabha_rag.core.coverage_inventory
```

No API model calls, new imports or external PDF downloads are made. If an audit fails, fix the cause before treating an older snapshot as current. The missing 39 Lok Sabha index entries and absent RS periods are disclosed; this audit does not import or invent them.

## Checks

100 selected Python tests passed, including six new coverage tests and previous answer/retrieval regressions. A further 21 debate/bill tests passed after preserving their expected test/import-script folder layout in the container. Initial collection errors in the temporary test layout were corrected; no source-code failure was hidden. Six Node assertions check House/content-specific coverage copy, missing-audit handling and catalogue/text separation. JavaScript syntax checks passed.

Inventory evidence is saved under `research/coverage-audit/`. Local live speech counts may differ from that snapshot because indexing continues.
