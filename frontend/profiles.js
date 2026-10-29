// Official profiles; escape source text and restrict remote links to Sansad.
function profileEscape(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function profileURL(value) {
    try { const u = new URL(value); return u.protocol === 'https:' && u.hostname === 'sansad.in' ? u.href : ''; }
    catch { return ''; }
}
function profileDate(value) {
    const d = new Date(value); return Number.isNaN(d.getTime()) ? 'Unknown' : d.toLocaleDateString('en-GB');
}
function personCard(person, label) {
    const rs = person.profile_house === 'rajya_sabha';
    const photo = profileURL(person.photo_url), source = profileURL(person.profile_url);
    const facts = [person.party, [person.constituency, person.state].filter(Boolean).join(', ')].filter(Boolean);
    return `<article class="person-card"><div class="person-label">${profileEscape(label)}</div>
        <div class="person-header"><div class="person-avatar"><span aria-hidden="true">${profileEscape(person.name?.charAt(0) || '?')}</span>
          ${photo && person.matched ? `<img src="${API_BASE}/${rs ? 'rs-profile-photo' : 'profile-photo'}/${person.id}" alt="Portrait of ${profileEscape(person.name)}" loading="lazy">` : ''}</div>
          <div><h4>${profileEscape(person.name)}</h4>${facts.map(f => `<p>${profileEscape(f)}</p>`).join('')}</div></div>
        ${person.role_in_record ? `<p class="person-role"><strong>Role in this record:</strong> ${profileEscape(person.role_in_record)}</p>` : ''}
        ${person.matched ? `<div class="person-actions"><button type="button" class="profile-details-toggle" data-member="${person.id}" data-house="${rs ? 'rajya_sabha' : 'lok_sabha'}" aria-expanded="false">Career &amp; details</button>
          <a href="${profileEscape(source)}" target="_blank" rel="noopener noreferrer">Official profile ↗</a></div>
          <div class="person-details" hidden></div><p class="person-fetched">Profile fetched ${profileDate(person.retrieved_at)}</p>` : `<p class="person-note">${profileEscape(person.profile_note || 'No unambiguous Lok Sabha profile match. See the original record for this person’s identity.')}</p>`}
        ${recordSourceURL(person.attribution_source_url) ? `<a class="people-source" href="${profileEscape(recordSourceURL(person.attribution_source_url))}" target="_blank" rel="noopener noreferrer">Verify role in official record ↗</a>` : ''}
        ${person.attribution_excerpt ? `<details class="person-attribution"><summary>Source excerpt</summary><p>${profileEscape(person.attribution_excerpt)}</p></details>` : ''}</article>`;
}

function recordSourceURL(value){
    try{const u=new URL(value);return u.protocol==='https:' && !u.username && !u.password && (!u.port || u.port==='443') && ['sansad.in','www.sansad.in','elibrary.sansad.in','bucketapi.rajyasabha.digital','cms.rajyasabha.nic.in'].includes(u.hostname)?u.href:'';}catch{return '';}
}
function recordPeopleHTML(data){
    return `<p class="people-record">${profileEscape(data.record_date || '')}</p><div class="people-grid">${data.people.map(entry=>personCard(entry.profile,data.kind==='bill'?'BILL PRESENTER':'DEBATE PARTICIPANT / SPEAKER')).join('')}</div>${!data.people.length?'<p class="person-note">No person could be verified from the available official records.</p>':''}<p class="person-note">${profileEscape(data.note)}</p><p class="person-note">${profileEscape(data.profile_note)}</p>`;
}
function wirePersonCards(panel) {
    panel.querySelectorAll('.person-avatar img').forEach(img => img.addEventListener('error', () => img.remove()));
    panel.querySelectorAll('.profile-details-toggle').forEach(button => {
        button.addEventListener('click', async () => {
            const details = button.closest('.person-card').querySelector('.person-details');
            if (!details.hidden) { details.hidden = true; button.setAttribute('aria-expanded', 'false'); return; }
            details.hidden = false; button.setAttribute('aria-expanded', 'true');
            if (details.dataset.loaded) return;
            button.disabled = true; details.textContent = 'Loading official biography…';
            try {
                const response = await fetch(`${API_BASE}/${button.dataset.house === 'rajya_sabha' ? 'rs-profiles' : 'profiles'}/${button.dataset.member}`);
                if (!response.ok) throw new Error('Official biography is temporarily unavailable. Use the official profile link.');
                const p = await response.json();
                const fields = [['Education', p.education], ['Date of birth', p.date_of_birth], [button.dataset.house === 'rajya_sabha' ? 'Rajya Sabha membership' : 'Lok Sabha memberships', p.terms]];
                details.innerHTML = `<dl>${fields.filter(([,v]) => v).map(([k,v]) => `<dt>${profileEscape(k)}</dt><dd>${profileEscape(v)}</dd>`).join('')}</dl><h5>Political career / positions held</h5>
                   ${p.career.length ? `<ol class="career-timeline">${p.career.map(x => `<li><strong>${profileEscape(x.period || 'Period not specified')}</strong><span>${profileEscape(x.position)}</span></li>`).join('')}</ol>` : '<p>No positions available from the official source.</p>'}
                   <p class="person-note">Source: Digital Sansad. Biography fetched ${profileDate(p.retrieved_at)}${p.career_retrieved_at ? `; positions fetched ${profileDate(p.career_retrieved_at)}` : ''}. “Onwards” dates are reproduced from the source, not independently confirmed current appointments.</p>`;
                details.dataset.loaded = '1';
            } catch (error) { details.textContent = error.message; }
            finally { button.disabled = false; }
        });
    });
}
function attachParliamentaryProfiles(card, group) {
    if (group.content_type === 'debate') {
        const section=document.createElement('section');section.className='parliamentary-people';
        const button=document.createElement('button');button.type='button';button.className='people-toggle';button.textContent='People in this debate';button.setAttribute('aria-expanded','false');
        const panel=document.createElement('div');panel.className='people-panel';panel.hidden=true;
        button.addEventListener('click',async event=>{
            event.stopPropagation();panel.hidden=!panel.hidden;button.setAttribute('aria-expanded',String(!panel.hidden));
            if(panel.hidden || panel.dataset.loaded)return;
            button.disabled=true;panel.textContent='Checking listed participants, speaker headings and official profiles…';
            try{
                const response=await fetch(`${API_BASE}/debates/${encodeURIComponent(group.question_id)}/people`);
                if(!response.ok)throw Error('People could not be loaded. Please retry or open the original record.');
                const data=await response.json();if(!section.isConnected)return;
                panel.innerHTML=recordPeopleHTML(data);wirePersonCards(panel);panel.dataset.loaded='1';
            }catch(error){panel.textContent=error.message;}finally{button.disabled=false;}
        });
        section.append(button,panel);card.appendChild(section);return;
    }
    if (group.house === 'rajya_sabha') {
        const note = document.createElement('p'); note.className = 'person-note parliamentary-people';
        note.textContent = group.pdf_url || group.document_url
            ? 'Rajya Sabha · Original document identity verified. Official member profiles are available below.'
            : 'Rajya Sabha · Dataset source available. The original government document can be checked on demand. ';
        if (!group.pdf_url && !group.document_url && group.question_id) {
            const button=document.createElement('button');button.type='button';button.className='people-toggle';
            button.textContent='Check official document';
            button.addEventListener('click',async event=>{
                event.stopPropagation();button.disabled=true;button.textContent='Checking official source…';
                try {
                    const response=await fetch(`${API_BASE}/rs-document`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_id:group.question_id})});
                    if (!response.ok) throw new Error('Check unavailable. Please try again.');
                    const result=await response.json();const url=profileURL(result.url);
                    if (result.status==='verified' && url) {
                        group.document_url=url;if(result.format==='pdf')group.pdf_url=url;
                        const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener noreferrer';
                        link.textContent=result.format==='pdf'?'View PDF ↗':'View official document (Word) ↗';
                        link.addEventListener('click',e=>e.stopPropagation());button.replaceWith(link);
                    } else {button.textContent='No verified document match';}
                } catch {button.textContent='Retry document check';button.disabled=false;}
            });
            note.appendChild(button);
        }
        card.appendChild(note);
    }
    const section = document.createElement('section'); section.className = 'parliamentary-people';
    const button = document.createElement('button'); button.type = 'button'; button.className = 'people-toggle';
    button.textContent = 'People behind this record'; button.setAttribute('aria-expanded', 'false');
    const panel = document.createElement('div'); panel.className = 'people-panel'; panel.hidden = true;
    section.append(button, panel); card.appendChild(section);
    button.addEventListener('click', async event => {
        event.stopPropagation();
        if (!panel.hidden) { panel.hidden = true; button.setAttribute('aria-expanded', 'false'); return; }
        panel.hidden = false; button.setAttribute('aria-expanded', 'true');
        if (panel.dataset.loaded) return;
        button.disabled = true; panel.textContent = 'Checking parliamentary record and profiles…';
        const body = group.question_id ? {question_id:group.question_id} : {lok_no:group.lok_no,session_no:group.session_no,ques_no:group.ques_no,type:group.type};
        try {
            const response = await fetch(`${API_BASE}/parliamentary-context`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            if (!response.ok) throw new Error('Could not load people for this record. Please try again or open its PDF.');
            const data = await response.json();
            panel.innerHTML = `<p class="people-record">${data.record_date ? `Parliamentary answer: ${profileEscape(data.record_date)} · ` : ''}${profileEscape(data.ministry || '')}</p>
              <div class="people-grid">${data.asked_by.map(p => personCard(p, 'QUESTION ASKED BY')).join('')}
              ${data.answered_by ? personCard(data.answered_by, 'ANSWER GIVEN BY') : '<article class="person-card"><div class="person-label">ANSWER GIVEN BY</div><p>'+profileEscape(data.answerer_note)+'</p></article>'}</div>
              ${!data.asked_by.length ? '<p class="person-note">Questioner not available in the indexed metadata.</p>' : ''}
              <p class="person-note">${profileEscape(data.profile_note)}</p>
              ${profileURL(data.source_url) ? `<a class="people-source" href="${profileEscape(profileURL(data.source_url))}" target="_blank" rel="noopener noreferrer">Verify names and role in the original answer ↗</a>` : ''}`;
            wirePersonCards(panel); panel.dataset.loaded = '1';
        } catch (error) { panel.textContent = error.message; }
        finally { button.disabled = false; }
    });
}
