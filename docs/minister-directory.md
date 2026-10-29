# National minister directory — source snapshot

The `/ministers` section searches by name or portfolio and filters by Union,
state/UT, jurisdiction and source portfolio label. All 28 states and eight UTs
have explicit coverage entries, alongside the Union Government. Pagination,
reset, loading/error/empty states and a source-coverage panel are included.
The existing Q&A, debates and Bills navigation now links to this section.

## Actual coverage on 25 October 2026

**474 distinct minister records across 25 governments**, including the Union
roster. **Nationwide minister data is not complete.** The interface states this
before results, rather than representing an empty roster as a vacant ministry.

Seven state rosters remain unimported: Andhra Pradesh, Assam,
Gujarat, Jharkhand, Punjab, Rajasthan and Uttar Pradesh. Attempts encountered
empty/dynamic pages, certificate/DNS failures, timeouts, historical documents or
documents listing roles without names. Those sources have not been replaced
with inferred names or unverified internet lists. The relevant official portals
remain linked in coverage entries.

Chhattisgarh now has one verified individual record: **Shri Vishnu Deo Sai,
Chief Minister**, from https://yuvaayog.cg.gov.in/en/cm-corner.php. Its remaining
cabinet roster and detailed portfolios are still pending. The scope remains
explicitly partial. Reviewed individual additions live in
`scripts/minister_verified_supplements.json` and survive snapshot re-imports.
Exact aliases support Vishnu Dev Sai and the Hindi name; CM searches filter
Chief Ministers without accidentally returning Deputy Chief Ministers.

Five UT administration portals are separate from minister rosters: Andaman and
Nicobar Islands, Chandigarh, Dadra and Nagar Haveli and Daman and Diu, Ladakh and
Lakshadweep. Administrators/LGs and local hill-council executives are not mixed
into state Council-of-Ministers lists.

Imported rosters are also **not guaranteed exhaustive/current**. Examples:
Arunachal Pradesh and MP source responses have names but no portfolios; Odisha
listing lacks portfolios; Maharashtra eCabinet lists Marathi names and lacks
minister-of-state coverage/portfolios. These records preserve missing data.
English-name search does not automatically transliterate Marathi names.
Some official lists lack an explicit source date. Fetch time is shown separately
and never substituted for an appointment date.

## Union source qualification

The Cabinet Secretariat listing was fetched through its own observed public
`ajax_page_data.php?page_id=18` endpoint (`year_id=2026`). Its latest document:

https://cabsec.gov.in/writereaddata/councilofministers/english/1_Upload_4295.pdf

It is dated **15 October 2026**. Embedded PDF text identifies the PM and 67
numbered ministers. All 68 imported identities were checked against this roster.
The importer fails closed if this identity check no longer matches.

Readable portfolio transcription currently uses the PMO HTML table dated
**25 July 2026**:

https://www.pmindia.gov.in/en/news_updates/portfolios-of-the-union-council-of-ministers-2/

Subsequent portfolio wording has **not been independently checked for every
minister**. Both dates and both sources are displayed on every Union card; the
newer source must be checked for changes. The directory does not claim this is a
fully reconciled live appointment database.

## Provenance and safe behavior

- Snapshot: `src/lok_sabha_rag/resources/ministers.json`, versionable public data.
- Source configurations: `scripts/minister_sources.json`.
- Reviewed-snapshot importer: `scripts/import_minister_directory.py` (BeautifulSoup
  needed for importing only; the serving API uses standard-library JSON).
- Sources retain fetch date, explicit source date where known and input SHA256.
- Identical source names merge within one jurisdiction; names in different
  governments remain distinct. A minister can have several portfolios.
- Contact numbers, emails and addresses are not part of the serving schema.
- API never generates roster names, responsibilities or biographies using an LLM.
- Union member profiles resolve on demand through separate LS/RS identity
  directories. Two conflicting matches remain unresolved. State ministers are
  never automatically assigned a parliamentary biography.
- The snapshot survives container rebuilds because it is included in the source
  package. No Docker dependency/image rebuild was needed for this feature.
- This is a manual snapshot import, not a scheduled refresh system. Re-imports
  need source/layout review and coverage checks.

## API

`GET /api/minister-directory` accepts `query`, `level`, `jurisdiction`,
`portfolio`, `rank`, `page` and `page_size`. Ministry searches include all matching
listed ranks. Source spellings and compound portfolio labels are preserved;
labels are not claimed to be a uniform nationwide ministry taxonomy.

`GET /api/minister-directory/{record_id}/profile` provides an optional verified
parliamentary identity for Union ministers only.

## Verification

Full available test suite: **147 passed, 2 existing source-file checks skipped**.
Thirteen new tests cover name/ministry searches, junior ministers, government
boundaries, pagination, unknown queries, missing coverage, API validation,
snapshot consistency, deduplication, public-field limits and no inferred MP
identity for state ministers. New JavaScript passed Node syntax checking.

Live API checks: directory/page HTTP 200, 473 records, 24 governments with data,
35 Tamil Nadu records, and the Union Railways search returns the listed Cabinet
Minister plus Minister of State. The service was restarted after pausing speech
indexing; indexing was then resumed without resetting corpus data.

Follow-up: 19 minister-directory tests passed after the Chhattisgarh correction.
The exact reported name search, its Dev spelling variant, Hindi spelling and
`cm of chhattisgarh` are regression checked. Browser verification confirmed
the reported search now displays the Chief Minister and official source link.
