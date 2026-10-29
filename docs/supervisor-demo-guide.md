# Sansad AI — supervisor demo guide

Prepared for Aryan Sen, 23MIM10056, Integrated M.Tech Artificial Intelligence. Supervisor: Dr. Pradeep Kumar Mishra.

## Start on this computer

Open PowerShell and run:

```powershell
& "C:\Users\admin\Documents\Codex\2026-10-05\referenced-chatgpt-conversation-this-is-an\outputs\Start_Sansad_AI.cmd"
```

The launcher uses `C:\Users\admin\lok-sabha-rag`, starts the existing Ubuntu/Docker services, waits for the homepage and opens your browser. It does not rebuild the research index. Keep its status visible until it says the app is available. Start several minutes before the meeting.

Open [Sansad AI](http://localhost:8000/). Opening this address alone does not start the server. The address works on this computer while its local services are running; it is not a public deployment.

The launch command was checked with `--no-browser`. Service-start recovery is checked separately in the accompanying readiness report; a full Windows reboot and clean-machine installation are not certified. After moving the repository, the launcher's configured repository path must be updated.

## A six-minute walkthrough

| Time | Show | Say |
|---|---|---|
| 0:00–0:40 | Homepage and coverage disclosure | “Sansad AI helps users find and understand imported parliamentary records. Its answers should be checked against the supplied sources.” |
| 0:40–2:00 | Lok Sabha, Questions & answers, AI answer enabled; paste the prepared question below | “The system retrieves passages first, then asks Gemini to explain that evidence. It does not train a new foundation model.” |
| 2:00–3:00 | Expand source Q80 and People behind this record | “This passage supports the figures. The questioner and answering minister are different roles. Biography details have a separate fetch date.” |
| 3:00–3:50 | Bills & Acts; search Digital Personal Data Protection | “Introduction, passage and assent are separate events. Available document versions matter. Catalogue coverage is broader than cached readable text.” |
| 3:50–4:25 | Ministers; search Vishnu Deo Sai | “This directory searches imported Union/state/UT records. It is a dated snapshot with incomplete jurisdiction coverage, not a live guarantee of every appointment.” |
| 4:25–5:15 | Explain comparison-source checks and missing evidence | “For supported dated comparisons, each side is checked separately by topic, date and House. Missing evidence stays missing; it is not proof that a parliamentary record does not exist.” |
| 5:15–6:00 | Explain measured research status and next steps | “The provisional development experiment measured retrieval improvements. Independent answer review and new confirmation questions remain before general accuracy or publication claims.” |

### Prepared main question

Select **Lok Sabha → Questions & answers → AI answer on**:

> In the Lok Sabha reply of 4 February 2026, how many coach manufacturing units were operational and what was the setting-up expenditure for MCF Raebareli?

The earlier live demo returned **three units** and **Rs. 3,042.83 crore incurred setting-up expenditure**, with sources Q789/Q80. Expand the record titled **Railway Coach Manufacturing Units in the Country**, Q80, and compare its actual passage with the answer. Do not imply the three units all have that individual setting-up cost. Generated wording and provider availability can vary on a later run.

This is a rehearsed, previously inspected example, not an unseen research test. Screenshots of its answer and people panel are saved in `research/demo-readiness/`.

For the bill demonstration, open the **2023** result rather than a similarly named amendment bill. Its timeline, document-version controls and source-only retrieval were checked. Select **As introduced**, enter “How is personal data defined?” and use **Find source passages** to demonstrate page links without a Gemini call. Retrieved passages still need relevance review; do not claim every excerpt directly answers the question. Presenter lookup may explicitly report that no person could be verified.

### Optional comparison example

Select **Both Houses → Questions & answers**:

> Compare DFC status in the Rajya Sabha answer of 20 March 2015 and Lok Sabha answer of 19 March 2025. Report the route extents and target versus operational status; is a simple like-for-like completion-growth claim justified?

Source recovery was checked as a development regression after the fix. A new live generated answer to this exact question is not certified in this walkthrough. Explain that the changed route scope and target-versus-operational distinction prevent a simple like-for-like growth claim. Skip this extra generation if time is short.

### Missing-evidence example

> Compare Meridian bridge capacity in Lok Sabha replies of 30 December 2027 and 31 December 2027.

Select **Both Houses → Questions & answers**. These are deliberately future source dates for this 27 October 2026 demo. Expect a scoped no-matching-evidence response, not invented figures or substitution of an earlier date. This is an easy control, not a general hallucination benchmark.

## Explain the architecture on paper

```text
Imported official/dataset records
       ↓
Clean and split documents; preserve identity, House, date and source links
       ↓
Local Q&A search: semantic retrieval + historical keyword records
       ↓
Apply supported source-date/topic/House constraints
       ↓
Select complementary passages within the retrieval budget
       ↓
Gemini writes an evidence-based draft with source IDs
       ↓
Limited numeric/date checks → at most one revision → remaining warnings
       ↓
Answer + source passages + available original documents
```

Bills use their own document-version/page workflow. Debate metadata and extracted text have separate coverage. Do not claim every website section uses the same vector index.

## What the research result means

The frozen v1 development comparison used 30 questions, of which 24 were answerable positive cases. Complete known-reference evidence at rank 10 was 13/24 for the base and 19/24 for both the scope-only and full improved versions. This is **retrieval completeness on provisional labels**, not 79% chatbot accuracy. The extra recovery/table/unit bundle did not demonstrate an incremental retrieval gain over scope-only on that set. Later revisions were evaluated as development fixes; do not assign v1 scores to the current revised system.

Software: the website, imported data, documents, profiles and directory. Research candidate: source-aware comparison/evidence selection and measured reliability tradeoffs. Independent reference/claim/citation scoring and fresh source-disjoint confirmation are still pending. Scopus publication is not guaranteed.

## Known limits to disclose

- The local archive has missing years/records. An observed first/last date does not establish continuous or complete coverage.
- Rajya Sabha combines a small semantic HF slice and historical Kaggle keyword records; it is not a complete 2009–2026 Q&A archive.
- Debate catalogue records are not all extracted speech text. Background extraction can continue separately.
- Bill catalogue links are not all cached readable documents. A PDF or presenter lookup can be unavailable.
- The minister directory is a dated, incomplete snapshot. Source-named historical roles and fetched biographies must not be conflated.
- Lexical source/passage planning can miss synonyms or incidental matches. Clear automatic checks do not establish semantic truth; some false warnings remain.
- Gemini needs a working configured key, provider availability and suitable quota. The key stays server-side; do not open `.env` or show keys during the demo.

## If something fails

| Symptom | Action |
|---|---|
| Browser says connection refused | Run the launcher; wait for “Sansad AI is available”. Opening the URL alone is insufficient. |
| Launcher times out | Containers are left running. Wait and retry once; check `wsl -d Ubuntu -u root --cd /mnt/c/Users/admin/lok-sabha-rag -- docker compose ps`. Do not delete Docker volumes or re-import data during the meeting. |
| Homepage loads but Gemini fails | Turn **AI answer off** and demonstrate source retrieval. Explain the provider failure; do not present retrieval-only results as a newly generated answer. |
| No evidence for a question | Confirm House/content filters and use a precise topic/date. Missing retrieval is not proof of real-world absence. |
| A PDF or profile is slow | Continue with the already displayed local passage and source identity; skip optional biography/presenter panels. |
| Network/provider unavailable | Use the saved screenshots as a clearly labelled previous successful run, not a live result. |

Do not repeatedly submit the same generation request while it is processing. Use normal English for the prepared demo; Hinglish retrieval has not received equivalent validation.

## After the meeting

Leave Docker running if background extraction should continue. The existing Stop_Sansad_AI.cmd stops the app/database while preserving stored volumes, but also interrupts the separate extraction worker. That worker does not automatically resume merely by reopening the website. No stop command was executed as part of this walkthrough.

## Likely supervisor questions

**Why not just ChatGPT?** The project adds a bounded local parliamentary corpus, source/date/House constraints and inspectable evidence. A general model can answer broadly; this project makes the evidence trail explicit. It can still fail.

**What did you train?** We use existing embeddings/retrieval and a configured Gemini model; we did not train Gemini. The work is in data integration, retrieval constraints, passage selection and evaluation.

**Is the output correct because checks passed?** No. The checks are narrow. Units, scope, status, interpretation and citation entailment still require review.

**What is left?** Independent scoring, fresh confirmation examples, documented remaining errors and paper writing from verified experiments.
