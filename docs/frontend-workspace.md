# Frontend workspace, first design pass

The Questions & Debates and Bills & Acts pages now share a restrained green/ivory
design, compact brand header and navigation. The research homepage has a clearer
title, labelled search, optional topic suggestions, a short usage guide and a
collapsible coverage/availability panel. Technical coverage text is retained.
The header graphic is a local stylized Parliament illustration, not an official
government endorsement or seal.

Source cards use full-width titles above metadata, consistent spacing and shared
member/profile styling. Existing PDFs, people panels, citations, filters, settings
and bill document controls retain their existing IDs and handlers. New examples
only populate the query; they do not automatically submit or incur an AI call.
The loading status announces a search through a live region. Reduced-motion
preferences and keyboard focus indicators are supported.

Files: `frontend/workspace.css`, `frontend/workspace.js`,
`frontend/parliament-mark.svg`, plus the two page templates. The shared stylesheet
loads after the existing component sheets. No backend change or restart was
needed because static files are bind-mounted.

## Verification on 25 October 2026

- New JavaScript passes Node syntax checking; CSS endpoint responds HTTP 200.
- Browser: topic button fills Railway safety; explicit search (AI off) returns
  47 records; member panel opens.
- Bills: telecommunications search returns one record; expansion displays both
  House passage dates, assent, PDF links, the verified presenter portrait and
  existing bill-question controls.
- Visually inspected in the narrow in-app browser. Fixed a search button width
  collision with old mobile CSS and title/metadata compression in source cards.
- Both pages report no horizontal document overflow at the observed viewport.
- Desktop breakpoints are implemented; a separate wide-viewport visual inspection
  was not performed in this pass. AI answer generation was not re-run because its
  backend and generation code were unchanged.

This is the initial visual redesign, not a claim that all frontend usability,
accessibility or interaction work is complete.
