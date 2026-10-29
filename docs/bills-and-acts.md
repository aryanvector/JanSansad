# Bills & Acts catalogue

Open **http://localhost:8000/bills**, or use the Bills & Acts navigation link on
the existing search page. The design reuses the project's fonts and colours.

## Source and imported coverage

Both official House portals expose the shared bill catalogue:

- https://sansad.in/ls/legislation/bills
- https://sansad.in/rs/legislation/bills
- Public endpoint: https://sansad.in/api_rs/legislation/getBills

The importer fetched all 11 response pages (10,099 rows) and retained bill years
**2009–2026**. The published snapshot has **4,200 distinct bill identities**:
3,143 originating in Lok Sabha and 1,057 in Rajya Sabha. Their introduction
dates span **13 February 2009–10 August 2026**. This is the catalogue response's
coverage, not a guarantee that every bill or later status update is included.
The snapshot timestamp appears on the page; there is no automatic refresh.

One title-less row was excluded and 5,739 rows fell outside the bill-year range.
159 rows repeated otherwise identical bill details under different status
labels. These are combined into a single bill identity while preserving all
source labels. Some combinations conflict (for example Lapsed / Pending);
the application does not invent which label is latest. Different introductions,
members, dates, numbers or titles remain separate. No fuzzy title merge is used.

## Features and status semantics

- Search title, bill number, year, ministry, category, introducer and source status.
- Filter introduction House, bill year and ministry; paginate 12 records at a time.
- Introduced includes every record with an introduction date, including later Acts.
- Pending requires an explicit pending source label, not an absent passage date.
- Passed can be filtered by a recorded Lok Sabha date, Rajya Sabha date, or both.
  These filters are independent of the House of introduction.
- Acts & assent includes a supplied Act number or assent date. A missing assent
  date remains visible. This is not a full India Code or Act commencement database.
- Expand a bill for separate milestones and available official document versions:
  introduced, House-passed, both-Houses-passed, Gazette, committee report, errata,
  and synopsis. Not every record provides every version.
- Status and dates are source metadata. Money Bills carry a special-procedure
  note; the interface does not interpret a missing RS date as rejection.

Only HTTPS links on exact Sansad hosts and approved document paths are displayed.
The catalogue links open the official source. The optional **Ask this bill**
panel can additionally load and cache supported PDF versions for source retrieval
and question answering (see `bill-pdf-qa.md`). Three sample original PDFs were checked for valid PDF signatures. Other
links remain source-provided and may be broken or missing.

The catalogue and per-bill PDF questions are separate from the existing Q&A/debate
retrieval. The section does not automatically link debates, infer member votes,
calculate voting percentages, compare amendments, or track current legal commencement.

## Refreshing the snapshot

Run with Python 3.11+ (standard library only):

```powershell
python scripts/import_bills.py data/bills --from-year 2009 --to-year 2026
```

Source pages are cached in the output directory for reproducibility. Use a new
output directory for a fresh remote snapshot, rather than mixing old cached
pages with new ones. The importer checks reported page counts before publishing.
Keep the previous catalogue until the new import succeeds.

Docker reads `/app/data/bills/catalogue.json` from its persistent data volume.
Copy a completed host import to that volume with a temporary filename, then
rename it to `catalogue.json`. It reloads when the file modification time changes.
New Python routes require an app restart. No API key is needed for bill browsing.

## API and verification

- `GET /api/bills/coverage`
- `GET /api/bills?query=telecommunications&tab=all&origin=both&page=1`
- `GET /api/bills/{bill_id}`

Ten new unit tests passed: date parsing, safe links, conservative status merging,
identity preservation, independent House filters, pending/Act semantics,
pagination and snapshot refresh. Live HTTP checks passed all five categories,
filters, details, pagination, empty queries, invalid inputs, assets and existing
Lok Sabha Q&A search. The browser verified search, timeline expansion and the
390-pixel iframe layout. This is a phone-width rendering check, not a physical
mobile-device test.

Verified example: **The Telecommunications Bill, 2023**, introduced 18 December
2023; source passage dates 20 December (LS) and 21 December (RS), assent
24 December, Act number 44 of 2023. The displayed source status remains Passed,
even though the same source supplies assent details; no status is inferred.
