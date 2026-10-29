# Parliamentary profile cards

Search for a topic, then expand **People behind this record** on a result.
Each card identifies questioners from indexed metadata and the answering
minister from the original answer heading. **Career & details** opens the
official biography and positions held. No OpenAI request is needed for these
cards; document-only search works with them too.

Profiles, portraits and career entries come from Digital Sansad. The dataset
member lists supply additional name spellings. Public JSON responses are
cached in `DATA_DIR/profiles` for 24 hours; a previous cache can be served if
the source is unavailable. Fetch dates are displayed. Portraits are fetched
through a bounded endpoint that accepts member IDs, never arbitrary URLs.

## Interpretation and coverage

- The role beside an answer belongs to that parliamentary record.
- Profile party and constituency reflect the source when fetched; they are
  not proof of historical affiliation on the answer date.
- Career entries reproduce the official source, including “onwards” dates.
  They do not independently establish current appointments.
- Identity matching preserves initial order and rejects ambiguous matches.
  Lok Sabha membership can distinguish shared initials. A unique full first
  name and surname can resolve omitted middle names.
- Directory coverage is Lok Sabha 16–18. A Rajya Sabha minister or a heading
  absent from the indexed text may lack a matched profile. The original PDF
  remains available; missing evidence is reported instead of invented.
- Source outages can leave photographs unavailable; initials remain visible.

## Validation

`tests/test_profiles.py` checks attribution, ambiguity, initial order,
term-based resolution, middle-name omission, multiple questioners, safe photo
hosts and text sanitization without network requests. Live checks used
`17_7_723_UNSTARRED` (Ramya Haridas / Raj Kumar Singh) and
`18_4_583_UNSTARRED` (answering minister Shripad Yesso Naik).

This is a useful software feature. It is not by itself evidence of a novel
research contribution or improved retrieval accuracy.
