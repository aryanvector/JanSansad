# Official Rajya Sabha debate archive integration

## Imported scope

The requested range is 2009–2026 inclusive. The official Part-2 catalogue returned
25,443 entries for this range. After excluding one entry without a title, **25,442
unique records** are searchable. Their actual dates run from **12 February 2009
to 4 April 2025**. No 2026 records were returned by this source during import;
this is a statement about this catalogue response, not Parliament's activity.

Part 2 covers business other than Questions and Answers. Part-1 Q&A is excluded
because the app already has separate Rajya Sabha Q&A sources. This integration
does not replace or reindex the existing Lok Sabha or Rajya Sabha Q&A collections.

## Sources and reproducibility

- Archive entry point: https://rsdebate.nic.in/ (redirects to Digital Sansad).
- Current catalogue: https://sansad.in/rs/debates/officials
- Public catalogue API: https://integration.rajyasabha.digital/rsdebate/api/restv4/fetch/all
- Parameters: `collectionId=2`, `year=2009#2026`, `start=0`, `rows=1000`,
  and `sessionNo=(267)` for a complete session batch.

The importer caches source responses and verifies counts before publication.
Initial offset pagination produced 290 repeated IDs at page boundaries because
the upstream ordering was unstable. Complete session batches (215–267) resolved
this: their counts sum to the reported 25,443, with no repeated resource IDs.
The 290 preliminary repeats are not duplicate parliamentary documents.

Run inside the app's Python environment, targeting a writable directory:

```powershell
python scripts/import_rs_debates.py data/rs_debates --from-year 2009 --to-year 2026
```

The running Docker deployment reads `/app/data/rs_debates/debates.db` and
`manifest.json` from its persistent data volume. A host import must be copied
there before it becomes active. Restart the app after publishing an update.

## Retrieval and original documents

Choose **Content → Debates** and **Rajya Sabha**, or **All records** to combine
Q&A and debates. Debates use SQLite FTS5 keyword search over titles, categories,
participants and ministries, plus incrementally indexed speech text. The new
cross-House catalogue, scope checks and live indexing coverage are described in
`fulltext-debates.md`. This is not a dense index of every spoken word.
The existing cross-source rank fusion combines result ranks rather than mixing
incompatible BM25 and vector similarity scores.

Each debate has a stable `RS_D_<resourceId>` identity. Distinct debates on the
same date remain separate. Catalogue participant lists are labelled as such;
they do not establish who spoke a particular sentence or how anyone voted.

**View PDF** points to the original government archive document. Opening source
text, or preparing synthesis evidence, downloads the item's PDF and extracts
its text on demand. Successful extraction is cached with source URL, SHA-256,
page count and extraction timestamp. Only HTTPS URLs on exact approved official
hosts and paths are accepted, including redirect destinations. Downloads are
bounded to 20 MB, 150 pages and four concurrent transfers.

If extraction fails or a PDF is scanned, the system returns an explicit
metadata-only notice. No OCR is included. Where a filename encodes a date and
session, it must agree with catalogue metadata. Catalogue-only information must
not be used to invent speeches, positions or votes. Synthesis receives these
restrictions and extraction status in its evidence context.

## Verification and limitations

- 46 automated checks passed across the Rajya Sabha, profiles, PDF, activation,
  deduplication and debate test suites.
- Live HTTP search verified Q&A, debates, mixed results and Lok Sabha regression.
- The 13 February 2025 record “Demand for special drive to encourage Sanskrit
  education” (`RS_D_746171`) yielded an extractable one-page PDF; cache reuse and
  the source-text HTTP endpoint were verified.
- Synthesis context/citation evidence serialization was checked with a mocked
  language model, without a paid API call. Generated-answer quality was not
  measured by that check. Browser appearance was not visually verified.

This is catalogue integration with on-demand transcripts, not a completed
full-text archive ingestion. Search can miss topics mentioned only in a speech
body. Original availability, PDF text quality, language extraction quality and
upstream catalogue completeness remain source-dependent. Leading chunks may
not cover every part of a long debate. There is no member-wise voting inference,
bill passage percentage calculation, OCR or automatic scheduled refresh.
