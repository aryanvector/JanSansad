# Light and dark mode

The header switch is shared by Questions & Debates, Bills & Acts and Ministers.

- `frontend/theme.js` applies the saved preference before styles paint, or follows the device appearance if no explicit choice is saved.
- The switch is a keyboard-operable button with switch semantics and an accessible checked state.
- Choice is stored locally under `sansad-ai-theme` and synchronized across tabs. If storage is blocked, switching still works for the current page.
- `frontend/theme.css` overrides shared colour tokens and component-specific surfaces without changing the existing light layout.
- All three HTML pages load both shared theme files. No server restart is required with the current mounted frontend setup.

Verified in the live app: switching both directions; keyboard Space; refresh persistence; cross-page preference; dark retrieval settings; real document-search result cards; light minister cards; desktop and phone-width layout. JavaScript syntax check passed. Document search was used to inspect results without making a generation API call.
