# Combined Rajya Sabha corpus

## Actual searchable coverage

- Hugging Face `anudit/rajyasabha-qa`: existing 500 English records, 2–4 April 2025,
  in the existing Qdrant vector collection.
- Kaggle `rajanand/rajyasabha`, version 4: 89,047 records, 20 November 2009–
  11 August 2017, in `DATA_DIR/rajya_sabha_kaggle/records.db` (SQLite FTS5).
- Total: 89,547 unique indexed question records. The union is not continuous
  2009–2025 coverage. The rest of the HF file is downloaded but not indexed.

Kaggle is keyword/full-text retrieval, not a claim that 89,047 new dense vectors
were created. When historical keyword candidates exist, question-level reciprocal
rank fusion merges the independently ranked providers; cosine and BM25 values
are not directly compared. Repeated chunks from one question receive one rank
contribution per provider. Fused results are labelled “Ranked result”, not a
percentage confidence or semantic similarity. Lok Sabha-only retrieval is unchanged.

## Deduplication and audit

The builder read all nine year CSVs, 89,093 rows:

- 28 repeated question entries merged;
- 18 missing/short answers excluded (fewer than 30 answer characters);
- 89,047 usable unique questions retained;
- no overlap with the currently active HF questions (the periods are disjoint).

Identity is **House + answer date + question type + question number**. Stable
question IDs are derived from this identity, not source-local IDs. A UNIQUE
constraint prevents duplicate catalogue rows. Same wording on different answer
dates is retained because it represents a different parliamentary event.

All questioner names from repeated entries are preserved. Twelve duplicate
entries had text variants: the more complete text was retained and their keys
were logged for audit. These are not presented as independently verified textual
corrections. CSV SHA-256 hashes and detected encodings are in the catalogue manifest;
older CSVs require a legacy encoding fallback. Original source files remain intact.

The builder excludes overlap against the supplied **active** HF records, not
against downloaded-but-unindexed HF rows. If HF coverage expands, rebuild the
Kaggle catalogue against the new active record list. Retrieval also deduplicates
cross-source question identities as an additional safeguard.

## Original documents

The initial 100 Kaggle records checked produced 86 verified original documents:
27 PDFs and 59 DOCX files. Fourteen records in that batch pointed to legacy binary
DOC files, which are not parsed by this verifier. They retain dataset fallback.
Additional on-demand checks can expand the cache; coverage totals are live.

Unknown originals expose **Check official document**. The server accepts an indexed
question ID only, obtains metadata from the official RS service, and verifies the
unique document candidate. PDF and DOCX headings must agree on House, question
number/type and answer date. DOCX text is reconstructed paragraph-by-paragraph,
preserving inline Word runs rather than inserting spurious spaces into numbers.

Verified PDFs are labelled **View PDF**. DOCX originals are labelled **View document**;
they are not called PDFs or silently converted into purported government PDFs.
Source outages return a retryable error. Confirmed missing/unsupported matches
are cached for six hours, with the dataset citation retained. At most two remote
checks run concurrently; search itself makes no external document lookup.

Existing HF PDF checks and citations are retained. Link entries are bound to
their source dataset/revision and the indexed identity. A source switch cannot
silently reuse a different record's link.

## Reproduction

```text
uv run python scripts/build_kaggle_catalog.py <csv-directory> <output-directory> <active-hf-records.jsonl>
uv run python scripts/match_rs_pdfs.py <records.jsonl> <official-metadata.json> <pdf-links.json> --refresh-metadata --dataset rajanand/rajyasabha --revision kaggle-version-4
```

The catalogue builder stages the database, checks SQLite integrity and unique
identities, and publishes the finished file. Publish the database before its
manifest. Merge new source-specific link entries into the existing PDF map;
do not replace HF entries with a Kaggle-only mapping. Restart the app after code
changes. Dependencies and `uv.lock` include pypdf for live document checks;
rebuild the app image when recreating the deployment from scratch.

## Attribution

Kaggle: Rajanand Ilangovan, *Q & A Discussed in Parliament of India*,
https://www.kaggle.com/datasets/rajanand/rajyasabha — listed CC BY-SA 4.0.
Normalized text, merged names and the derived catalogue are adaptations; preserve
attribution and applicable share-alike terms when redistributing that data.

HF: https://huggingface.co/datasets/anudit/rajyasabha-qa — publisher lists MIT.
Keep these source licences distinct. The application code's licence does not
automatically relicense either dataset. Original documents are linked from
Digital Sansad; individual answer claims are not independently fact-checked.
