# Gemini AI integration

Both parliamentary synthesis (`/api/synthesize`) and bill PDF answers
(`/api/bills/{id}/ask`) use a common server-side generation provider. The Gemini
implementation uses Google's native REST `generateContent` endpoint with
`x-goog-api-key` authentication, system instructions, bounded output and a
60-second request timeout. No Gemini SDK or new runtime dependency is needed.

## Local configuration

Set these names in the ignored project `.env` file; never put a key in frontend
JavaScript, a screenshot, a report or Git:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=YOUR_LOCAL_KEY
GEMINI_MODEL=gemini-flash-lite-latest
```

The selected key authenticated successfully. `gemini-flash-latest` was available
in the model list but generation timed out in this environment. The live-tested
`gemini-flash-lite-latest` alias is therefore selected. Aliases can change their
underlying model over time. `GEMINI_MODEL` can be changed explicitly for future
experiments; this integration does not silently fall back to another provider.

OpenAI remains optional through `AI_PROVIDER=openai` and `OPENAI_API_KEY`.
`OPENAI_MODEL` defaults to the previous `gpt-4o-mini`; `BILL_QA_MODEL` is an
OpenAI-only bill override. `AI_PROVIDER=auto` prefers Gemini when a Gemini key
is present, otherwise OpenAI. Google keys are never sent to OpenAI endpoints.

Compose reads `.env` at container creation. After configuration changes, recreate
the app rather than only restarting its existing container:

```text
docker compose up -d --no-deps --force-recreate app
```

Pause an active debate-index job before recreating the app and resume afterward,
as described in `fulltext-debates.md`. Persistent volumes retain existing indexes
and cached documents. The image must include dependencies from the current
`pyproject.toml` / `uv.lock`, including pypdf for newly downloaded PDFs.

## Behaviour and credential handling

- `/api/ai-status` returns provider, model and credential-presence status only.
  This is configuration status, not a live quota or uptime guarantee.
- Both pages display the active provider. API keys stay on the server.
- Native Gemini requests send retrieved public evidence and the user's question
  to Google; the existing local retrieval/indexing pipeline stays in place.
- Grouped references such as `[E1, E2]` become separate clickable references.
  Bill reference IDs are checked; invalid or malformed references withhold the
  answer. Parliamentary out-of-range citation IDs are also rejected. These are
  reference checks, not automated proof of semantic faithfulness.
- Upstream error bodies are not displayed. Authentication, quota/rate-limit,
  model availability, timeout, blocked and incomplete responses have safe messages.
- Bill source passages remain available when generation fails. No paid model
  calls are used for background PDF indexing.
- `scripts/configure_gemini_local.py` provides a one-use, password-field setup
  page bound only to 127.0.0.1, with an Origin check, Host check and random form
  token. It closes after saving and never logs or returns the submitted key.

## Verification

Live Gemini responses were verified for Lok Sabha Q&A, a Lok Sabha debate and
the introduced Telecommunications Bill, 2023. The bill answer retained its
introduced-version label and linked authorisation provisions to `[E1]` on PDF
page 7. Browser verification checked the generated answer and source links.

102 tests passed, with two existing tests skipped because local source chunk
files were unavailable. Tests cover routing, no-key operation, private-thought
exclusion, credential redaction, safe errors, redirect prevention and citation
normalization, plus the existing retrieval/document suites. Live tests are smoke
checks, not a benchmark of answer quality or guaranteed future provider uptime.

Debate text ingestion remains incremental. OCR, exhaustive speech processing,
bill-version comparison and other proposed features are not made complete by
adding an AI provider.

Official API references:

- https://ai.google.dev/api/generate-content
- https://ai.google.dev/api/
- https://ai.google.dev/gemini-api/docs/models
