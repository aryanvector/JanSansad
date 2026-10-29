# Version-specific bill PDF questions

## Using the feature

Open http://localhost:8000/bills, search a bill and expand its card. In **Ask this
bill**, select an available document version. **Load PDF** downloads and prepares
it; **Find source passages** retrieves excerpts without an AI call; **Ask AI**
uses the configured provider to explain the retrieved excerpts with `[E#]`
references. Loading is also automatic when asking a question.

The answer panel and every evidence item retain the selected version. Opening a
citation takes the reader to the cached original PDF at its physical page
position. PDF page positions can differ from printed page labels. Changing the
version clears existing evidence and cancels the browser's previous request.

## Ingestion and provenance

Only version links already present on the selected catalogue bill are accepted.
Clients cannot submit an arbitrary download URL. Supported labels are introduced,
passed by LS, passed by RS, passed by both Houses and Gazette notification. A
catalogue label is the source's version designation, not an independently proven
revision history. Word documents, missing versions and invalid PDFs fail clearly.

HTTPS hosts, paths and redirect destinations are restricted to the Sansad source.
Downloads are limited to 20 MB. PDF extraction runs in a separate process with
a 45-second wall deadline, 150-page cap and 1.5-million-character limit. On Linux,
the worker also has 30-second CPU and 768 MB address-space limits. Title tokens
must substantially match the readable opening pages before content is cached.
This is a conservative mismatch check, not complete document-identity validation.

An on-demand cache under `/app/data/bills/documents` stores the original PDF and
page text, physical page number, extraction timestamp, SHA-256 and source URL.
The key includes bill ID, version, exact source URL and extractor version. It
therefore keeps different bill versions separate. Same-URL remote replacements
are not automatically detected; a deliberate cache refresh is needed for those.

Pages with little or evidently corrupted text are excluded from retrieval and
reported in the coverage warning. This heuristic cannot establish perfect text
quality. There is no OCR yet. No full-catalogue PDF download occurs in the
background; each selected document is processed on first use.

## Retrieval and answer generation

Page-local chunks have 1,800 characters and 240-character overlap. BM25 ranks
chunks within the selected document. Up to eight excerpts are sent to the model;
each retains its physical PDF page and text offset. This first implementation
does not use semantic embeddings, multilingual query translation or global bill
text search. Queries should use words appearing in the document. No keyword
match produces a limitation notice, not a claim that a provision does not exist.

Generic overview requests receive a labelled sample of distributed excerpts.
Long documents are not exhaustively summarised. The model must cite every
substantive document claim, distinguish proposed provisions from current law,
use only the selected version, and treat document instructions as untrusted data.
Clause numbers may appear only if present in the retrieved text.

Server credentials are reused through the common provider adapter. Gemini is now
supported and live-tested; see `gemini-provider.md`. `BILL_QA_MODEL` applies only
when OpenAI is selected. The optional OpenAI Responses call uses bounded output,
a request timeout, no automatic retries and `store=False`, following the
[official API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
No API key is exposed in browser requests or error messages.

Generated answers without citation IDs, or with IDs outside the retrieved
evidence set, are withheld. A successful reference check validates only that
those evidence items exist; it does not prove every claim is entailed. Human
evaluation of faithfulness and citation completeness remains necessary.
Provider failures retain source passages and show a safe, actionable error.

## Verified example and current limitation

The Telecommunications Bill, 2023 (`B_b591e262b9cf92da03573c6b`):

- Introduced version: 46 PDF pages; 45 passed the readability heuristic.
- As passed by both Houses: 36 PDF pages; 31 passed that heuristic.
- The files have different SHA-256 hashes and isolated caches.
- An authorisation query retrieved clause 3 on physical page 7 of the introduced
  version. Browser selection of the passed version changed the retrieved page
  links and cleared previous evidence.
- PDF and page-text endpoints, source-only search, absent-version errors and
  mocked synthesis response/citation serialization passed live integration checks.
- Sixteen document unit tests passed, including safe redirects, separate cache
  identities, no-match handling, citation failures, parser timeout, scanned-text
  rejection, title mismatch and safe quota messages.

The initial OpenAI-compatible provider test returned HTTP 429 with exhausted
credits. Gemini Flash-Lite has subsequently been integrated and a real bill answer
with valid evidence references has passed live verification. The earlier quota
block does not apply to the currently selected Gemini provider; its own quota
and availability still apply.

## Endpoints

- `GET /api/bills/{id}/versions`
- `POST /api/bills/{id}/document` with `{"version":"introduced"}`
- `POST /api/bills/{id}/ask` with `{"version":"introduced","question":"What authorisation is required?","synthesize":false}`
- `GET /api/bills/{id}/pdf?version=introduced` (after preparation)
- `GET /api/bills/{id}/pages/7?version=introduced` (after preparation)

Future stages can add semantic retrieval, OCR, bulk indexing and measured
version comparisons without conflating those capabilities with this release.
