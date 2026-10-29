/* Coverage copy uses audited identities, never upstream dataset sizes. */
function coverageLines(data, house, contentType) {
    const inventory = data.inventory || {};
    if (inventory.status !== 'ready') return ['Local coverage audit is unavailable. Do not assume the complete parliamentary archive is searchable.'];
    const number = n => Number(n || 0).toLocaleString('en-IN');
    const range = s => `${s.date_from || 'date unknown'} to ${s.date_to || 'date unknown'}`;
    const lines = [];
    const qa = inventory.qa || {};
    if (contentType !== 'debate') {
        if (house !== 'rajya_sabha') {
            const s = qa.lok_sabha || {};
            lines.push(`Lok Sabha Q&A: ${number(s.records)} questions in the search index; ${number(s.chunks)} text passages. Answer dates: ${range(s)}.`);
            if (s.metadata_without_index || s.indexed_without_metadata) lines.push(`Metadata/search difference: ${number(s.metadata_without_index)} catalogue questions lack indexed passages; ${number(s.indexed_without_metadata)} indexed questions lack matching local metadata.`);
        }
        if (house !== 'lok_sabha') {
            for (const [key, label] of [['rajya_sabha_hf', 'Rajya Sabha Hugging Face pilot'], ['rajya_sabha_kaggle', 'Rajya Sabha Kaggle archive']]) {
                const s = qa[key] || {};
                lines.push(`${label}: ${number(s.records)} Q&A records; ${range(s)}; ${s.retrieval || 'unknown'} search. Snapshot: ${s.snapshot_at || 'unknown'}.`);
            }
            const years = [...new Set(['rajya_sabha_hf', 'rajya_sabha_kaggle'].flatMap(k => Object.keys(qa[k]?.years || {})))].sort();
            lines.push(`Rajya Sabha Q&A years present: ${years.join(', ') || 'unknown'}. Other years are not established by these imports.`);
            lines.push(`Dataset sources: anudit/rajyasabha-qa (Hugging Face; listed licence MIT); rajanand/rajyasabha (Kaggle; listed licence CC-BY-SA-4.0). Some original-document links were mapped earlier; this audit does not recheck their current availability.`);
        }
    }
    if (contentType !== 'qa') {
        for (const h of house === 'both' ? ['lok_sabha', 'rajya_sabha'] : [house]) {
            const c = inventory.debate_catalogues?.[h] || {};
            const f = data.debate_fulltext?.houses?.[h] || {};
            const label = h === 'lok_sabha' ? 'Lok Sabha' : 'Rajya Sabha';
            lines.push(`${label} debates: ${number(c.records)} catalogue entries (${range(c)}); ${number(f.indexed)} have indexed speech text (${range(f)}). Other entries can match catalogue metadata; their speech content is not necessarily searchable.`);
        }
    }
    lines.push('Date endpoints and years present do not mean complete or continuous coverage. Source dates are not the dates of every statistic inside the records.');
    lines.push(`Index/catalogue audit: ${inventory.checked_at || 'unknown'}. Debate text counts checked: ${data.debate_fulltext?.checked_at || 'unknown'}. These are local checks, not live government updates.`);
    return lines;
}

function renderCoverageInventory(data, house, contentType) {
    const note = document.getElementById('coverage-note');
    note.textContent = 'Actual local coverage · catalogue records and searchable text are counted separately.';
    let list = document.getElementById('coverage-list');
    if (!list) {
        list = document.createElement('ul');
        list.id = 'coverage-list';
        list.className = 'coverage-note';
        note.after(list);
    }
    list.replaceChildren();
    for (const line of coverageLines(data, house, contentType)) {
        const li = document.createElement('li');
        li.textContent = line;
        list.appendChild(li);
    }
}
