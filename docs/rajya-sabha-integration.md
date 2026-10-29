# Rajya Sabha pilot

The active system now combines this HF pilot with the full deduplicated Kaggle
keyword catalogue. See `kaggle-combined-corpus.md` for current total coverage,
deduplication, retrieval methods and original-document support. The details below
describe the HF pilot and its initial PDF audit.

## Implemented scope

- Separate RS Qdrant collection chosen from the active manifest; the Lok Sabha collection is unchanged.
- Website selection: Lok Sabha, Rajya Sabha pilot, or Both Houses.
- House, answer date, session and dataset citation on results and in generation context.
- Stable RS-prefixed question IDs for grouping and full-text lookup.
- House-specific autocomplete; Lok Sabha activity totals disabled for RS/Both.
- Actual imported coverage exposed at `/api/corpus-coverage` and displayed in the UI.
- Verified original PDF links are available for 495/500 pilot records. Unconfirmed
  records retain their dataset-source link. RS biographies are not yet available.

The active source is `anudit/rajyasabha-qa` on Hugging Face. The verified
migration indexes 500 usable English Q&A records from Session 267,
2–4 April 2025, in `rajya_sabha_hf_questions_v1`. The active source is always
reported by `/api/corpus-coverage`; the new index is activated only after its
point count, records and provenance are verified. The old 2017 Kaggle index
is retained for rollback, not mixed into the HF results.

The full 508,851,734-byte upstream Parquet was downloaded and verified against
the Hugging Face LFS SHA-256. Downloading all rows does not mean indexing all
rows: this remains a limited 500-record English pilot.

Pinned revision: `508b2411283162fdd52ee2c3e8ccaefbabfe9581`.
Source SHA-256: `9cf145189c89470da82324013b6510e462bbb3a2d6e4f68cebe90c318f1c2189`.

## Source and attribution

Requested source: https://huggingface.co/datasets/anudit/rajyasabha-qa
The publisher's dataset card lists MIT. Its minimal card does not establish
complete provenance or flawless extraction; preserve upstream attribution and
do not equate this listing with independent verification of every record.

Retired pilot: Rajanand Ilangovan, Kaggle `rajanand/rajyasabha`, version 4,
listed CC BY-SA 4.0. That source's attribution/share-alike requirements still
apply if its adapted records are redistributed; changing sources does not
relicense the archived Kaggle-derived data.

Question/answer text is sourced from the HF dataset. Separately matched official
PDFs have their metadata and identity checked; this does not mean every factual
claim in their answers was independently verified. Questioner names come from `name` metadata;
these are not necessarily ministers. No votes or bill-status data are inferred.

## Import and verification

Run inside the existing app container/environment:

```text
.venv/bin/python -m lok_sabha_rag.pipeline.import_rajya_sabha --parquet /app/data/rajya_sabha_hf/hf-verified.parquet --revision 508b2411283162fdd52ee2c3e8ccaefbabfe9581 --folder rajya_sabha_hf --collection rajya_sabha_hf_questions_v1 --session 267 --limit 500
```

The importer writes normalized records and a manifest including input SHA-256,
source version, date range, rejection counts, record/chunk counts and fetch time.
It skips missing/short answers, invalid dates, missing session mapping,
metadata/text date mismatches and duplicate IDs. These checks are structural;
they do not independently verify all historical claims.

After staging, validate and activate with the provided script inside the
app environment (copy `scripts/activate_rs_index.py` into the container first):

```text
.venv/bin/python /tmp/activate_rs_index.py /app/data/rajya_sabha_hf/manifest.json
```

Do not mix dataset identities in the same RS collection: the importer rejects
a source change when an existing manifest identifies another dataset. A newer
source needs a new collection and regression checks. Activation atomically
replaces the active manifest and preserves a timestamped previous manifest.
Restart the app afterward so its retrievers select the activated collection.

Cross-House scores use the same embedding model, with top-k queried per House
and merged by score. Both Houses mode does not guarantee balanced coverage or
implement the proposed coverage-aware research method. Evaluate that separately.

Paid OpenAI generation is not required to search. Integration tests should mock
generation; live paid generation depends on the existing account configuration.

## Verified original PDFs

The official Digital Sansad RS page uses
`https://rsdoc.nic.in/Question/Search_Questions` for recent-session metadata.
The matching script obtains `eng_file_dsp` / `files` links from that response;
it does not construct PDF filenames. The 267-session record IDs are retained
in the official service and can be matched to the pinned HF data.

`scripts/match_rs_pdfs.py` requires pypdf. It checks session, number, type,
answer date, source record ID and title similarity (at least 0.92). Only a
unique official candidate is downloaded. It restricts URLs and redirects to
HTTPS `sansad.in/getFile/annex/<session>/...pdf`, checks the PDF signature and
size, then extracts the opening pages and verifies House, question number/type
and the answer date heading. Hashes and verification times are recorded.
Typographic variants in official headings (joined RAJYASABHA, UN-STARRED,
Unicode dashes and the observed RAJAY spelling) are supported explicitly.

Example, using the exported active records:

```text
uv run --with pypdf scripts/match_rs_pdfs.py active-hf-records.jsonl official-metadata.json pdf-links.json --refresh-metadata
```

Publish the completed mapping atomically as `DATA_DIR/rajya_sabha/pdf-links.json`
after checking its dataset revision and counts against the active manifest.
Search applies mappings only when the pinned revision, record ID, session,
question number, type, date and subject still match the indexed payload.
Existing Lok Sabha URLs are unchanged. No remote PDF lookup occurs during
search. Coverage is exposed as `pdf_verified_records` in the coverage endpoint.

Five records could not pass identity checks in this run; their buttons remain
`Dataset source`. For example, HF/official metadata for question 3668 says
2 April 2025 while the official PDF heading says 26 March 2025. The system
does not silently equate these dates. Mapping coverage may change when sources
are corrected and the audit is rerun.
