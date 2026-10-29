# Answer accuracy: first implementation

Implemented 26 October 2026. Applies to `/api/synthesize` (Q&A/debate answers), not the separate bill-document answer endpoint.

## Behaviour

1. Retrieve evidence and generate the draft as before.
2. Run deterministic checks against the selected passages and record dates.
3. If checks raise issues, attempt one evidence-grounded rewrite. Keep it only if the issue count decreases. There is no retry loop.
4. Return `answer_checks` with the answer. Unresolved findings appear in an expanded review notice. A clear check displays a collapsed notice explicitly stating that checks are limited; it is not a verified-answer badge.
5. Provider failure during the extra rewrite retains the initial answer with warnings. Existing invalid-citation withholding remains active.

## What is checked

- Literal numeric support for figures at least 10, with Indian/international comma formatting normalized. Where citations exist on a line, only those sources are used; otherwise all selected sources are used as a conservative heading check.
- Explicit addition/subtraction expressions with 2–8 operands, computed using Decimal. A derived result absent from a passage is accepted only when the expression balances and all operands occur in the selected/cited sources.
- Explicit full calendar dates directly labelled answer/reply/response/record dates versus cited record dates. Observation/advisory/launch dates are not treated as record dates.
- A narrow spending-status warning where an affirmative spent claim uses a figure occurring near approval/outlay wording but no nearby spending wording.
- Invalid citation IDs.

## Limits and cost

Number presence cannot prove the correct unit, period, population, attribution or meaning. The checks do not establish that operands belong together, that cohorts are disjoint, or that an inferred relationship is valid. The status rule is a heuristic and can miss paraphrases or produce false positives. Counts under 10, spelled-out numbers, unit conversions, general month/year attribution, implicit subtotals, multiplication and percentages are not fully checked. A supported derived total without a displayed equation can be flagged even when correct. The rewrite may omit such an unnecessary total.

This is the first portion of answer-accuracy work, not complete semantic verification or a measured overall accuracy gain. The extra rewrite can add one model call and latency; clean drafts use one call. Bill QA remains to be audited separately.

## Validation

89 selected automated tests passed, including 15 new checks covering known subtotal errors, valid calculations, Indian formatting, cross-source leakage, date boundaries, spending status, invalid citations and bounded repair/failure behaviour. JavaScript syntax check passed.

Three live development questions were rerun once with the same saved requests from the earlier scoped-retrieval run. Results and caveats: [development report](../research/answer-checks/report.md).
# Checker warning revision v4

Formatted explicit addition/subtraction can now use common unit labels, including LaTeX unit typography, and equals/yields wording. Supported operands and correct arithmetic are still required; mixed detected unit/scale families are not normalised into a false sum. This is not a general unit or semantic validator.

Narrowly recognised statements that a requested reply is missing from supplied evidence no longer treat that full date as a positive source-date claim. Other figures, invalid citations and positive wrong-date claims remain checked. Year-only references and parenthetical headings can still generate false warnings.

99 selected tests passed. Re-auditing 24 saved generated drafts resolved the known formatted DFC-sum warning and reduced two missing-date cases; no answers were regenerated and no original evaluation artifacts changed. See `research/checker-warnings-v4/report.md`. Independent claim/citation review remains pending.
