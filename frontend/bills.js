'use strict';
const API_BASE='/api';
const $ = id => document.getElementById(id);
const state = {tab:'all',page:1,total:0,controller:null};
const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const prettyDate = s => s ? new Date(s+'T00:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : 'Not supplied';
function safeDocument(url){try{const u=new URL(url);return u.protocol==='https:' && ['sansad.in','www.sansad.in'].includes(u.hostname) && (!u.port || u.port==='443') && !u.username && !u.password && ['/getFile/','/uploads/'].some(p=>u.pathname.startsWith(p));}catch{return false;}}
const pdfVersions={introduced:'As introduced',ls_passed:'As passed by Lok Sabha',rs_passed:'As passed by Rajya Sabha',both_passed:'As passed by both Houses',gazette:'Gazette notification'};
const qaRequests=new WeakMap();
function questionPanel(r){
 const options=Object.entries(pdfVersions).filter(([key,label])=>r.documents.some(d=>d.label===label && safeDocument(d.url) && !/\.docx?$/i.test(new URL(d.url).pathname)));
 if(!options.length)return '<h4>Ask this bill</h4><p>No supported PDF version is linked for this record. Available official documents can still be opened above.</p>';
 return `<section class="bill-qa"><h4>Ask this bill</h4><p>Choose one document version. Answers use retrieved passages from that PDF only, with page citations.</p><form class="bill-qa-form" data-bill="${esc(r.id)}"><label>Document version<select name="version">${options.map(([key,label])=>`<option value="${key}">${esc(label)}</option>`).join('')}</select></label><button type="button" data-qa="load" class="bill-secondary">Load PDF</button><label class="bill-qa-question">Your question<input name="question" type="text" maxlength="700" placeholder="What does this version say about consent?" aria-label="Question about ${esc(r.title)}"></label><div class="bill-qa-actions"><button type="submit" data-qa="sources" class="bill-secondary">Find source passages</button><button type="submit" data-qa="answer" class="bill-primary">Ask AI</button></div><p class="bill-qa-status" aria-live="polite"></p><div class="bill-qa-output"></div></form><p class="bill-qa-note">First use downloads and processes the PDF. Scanned pages may require OCR, which is not included yet. AI answers use the server’s configured API key.</p></section>`;
}
function card(r){
 const act = !!(r.assent_date || r.act_number);
 const dates=[['Introduced',r.introduced_date],['Lok Sabha passage',r.ls_passed_date],['Rajya Sabha passage',r.rs_passed_date],['Presidential assent',r.assent_date]];
 const docs=r.documents.filter(d=>safeDocument(d.url)).map(d=>`<a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.label)} ↗</a>`).join('');
 const meta=[`Bill ${r.number || 'number not supplied'} · ${r.year || 'year not supplied'}`,r.origin_house ? `Introduced in ${r.origin_house}` : 'Introduction House not supplied',r.ministry,r.introduced_by ? `Introduced by: ${r.introduced_by}` : null].filter(Boolean);
 return `<details class="bill-card" id="${esc(r.id)}"><summary><div class="bill-card-top"><h3>${esc(r.title)}</h3><span class="bill-badge ${act?'act':''}">${esc(r.status)}</span></div><div class="bill-meta">${meta.map(m=>`<span>${esc(m)}</span>`).join('')}</div><div class="bill-preview"><span>LS: ${esc(prettyDate(r.ls_passed_date))}</span><span>RS: ${esc(prettyDate(r.rs_passed_date))}</span>${act?`<span>Act ${esc(r.act_number || 'number not supplied')}${r.act_year?' of '+esc(r.act_year):''}</span>`:''}</div><span class="bill-open">View timeline &amp; official documents ↓</span></summary>
 <div class="bill-detail"><ol class="bill-timeline">${dates.map(([label,d])=>`<li class="${d?'recorded':''}"><strong>${label}</strong><span>${esc(prettyDate(d))}</span></li>`).join('')}</ol>
 <section class="bill-people"><h4>Presented by</h4><div class="bill-people-content" aria-live="polite"><p>Checking the official presenter record…</p></div></section>
 <p>Official status: <strong>${esc(r.status)}</strong> · ${esc(r.type || 'Type not supplied')} · ${esc(r.category || 'Category not supplied')}</p>
 ${r.source_statuses?.length>1?'<p>The source lists this bill under multiple status labels. Identical bill details are combined here; all source labels are preserved above.</p>':''}
 ${r.committee_date?`<p>Referred to committee: ${esc(prettyDate(r.committee_date))}</p>`:''}
 ${r.report_date?`<p>Committee report presented: ${esc(prettyDate(r.report_date))}</p>`:''}
 ${act?`<p>Act number: ${esc(r.act_number || 'Not supplied')}${r.act_year?' of '+esc(r.act_year):''}. ${!r.assent_date?'Assent date is not supplied in this snapshot.':''}</p>`:''}
 ${/money/i.test(r.category || '')?'<p>Money Bill: Rajya Sabha considers recommendations under a special procedure; a missing RS passage date must not be treated as rejection.</p>':''}
 <h4>Official documents</h4><div class="bill-documents">${docs || '<p>No document link supplied for this record.</p>'}</div>
 ${questionPanel(r)}<h4>Source catalogue</h4><div class="bill-sources"><a href="https://sansad.in/ls/legislation/bills" target="_blank" rel="noopener noreferrer">Lok Sabha</a><a href="https://sansad.in/rs/legislation/bills" target="_blank" rel="noopener noreferrer">Rajya Sabha</a></div>
 <p>Dates and status are reproduced from the official snapshot. The milestones are separate recorded events, not a calculated progress score. Document versions can differ.</p></div></details>`;
}
function explanation(){
 const descriptions={all:'All imported bill records matching your filters. The badge preserves the official status.',introduced:'Records with an introduction date, including bills that later passed or received assent.',pending:'Only records explicitly marked pending by the official source. Missing passage dates alone do not mean pending.',passed:'Filters use recorded House-wise passage dates. “Both Houses” requires both dates; Money Bills may follow a different procedure.',acts:'Records with an Act number or Presidential assent date. Any missing assent date is shown explicitly; commencement dates are not tracked.'};
 $('bill-explanation').textContent=descriptions[state.tab];$('passed-filter').hidden=state.tab!=='passed';
}
async function load(){
 state.controller?.abort();const controller=new AbortController();state.controller=controller;
 $('bill-results').setAttribute('aria-busy','true');$('bill-error').hidden=true;
 $('bill-result-count').textContent='Loading bills…';$('bill-prev').disabled=true;$('bill-next').disabled=true;
 const params=new URLSearchParams({query:$('bill-query').value,tab:state.tab,house:$('bill-passage').value,origin:$('bill-origin').value,page:state.page,page_size:12});
 if($('bill-year').value)params.set('year',$('bill-year').value);
 if($('bill-ministry').value)params.set('ministry',$('bill-ministry').value);
 explanation();
 try{
  const response=await fetch('/api/bills?'+params,{signal:controller.signal});if(!response.ok)throw Error('Could not load bill records. Please try again.');
  const data=await response.json();if(controller.signal.aborted)return;
  state.total=data.total;$('bill-result-count').textContent=`${data.total.toLocaleString()} matching records`;
  $('bill-results').innerHTML=data.records.length?data.records.map(card).join(''):'<p class="bill-empty">No bills match these filters. Try a shorter title or reset the filters.</p>';
  document.querySelectorAll('[data-tab]').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.tab===state.tab));b.querySelector('span').textContent=data.counts[b.dataset.tab].toLocaleString();});
  $('bill-page').textContent=data.total?`Page ${state.page} of ${Math.ceil(data.total/12)}`:'No results';
  $('bill-prev').disabled=state.page<=1;$('bill-next').disabled=state.page*12>=data.total;
 }catch(e){if(e.name!=='AbortError'){$('bill-error').textContent=e.message;$('bill-error').hidden=false;$('bill-results').replaceChildren();$('bill-result-count').textContent='Records unavailable';$('bill-page').textContent='';}}
 finally{if(state.controller===controller)$('bill-results').setAttribute('aria-busy','false');}
}
function resetPage(){state.page=1;load();}
$('bill-search').addEventListener('submit',e=>{e.preventDefault();resetPage();});
['bill-origin','bill-year','bill-ministry','bill-passage'].forEach(id=>$(id).addEventListener('change',resetPage));
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{state.tab=b.dataset.tab;resetPage();}));
$('bill-reset').addEventListener('click',()=>{$('bill-search').reset();$('bill-passage').value='both';state.tab='all';resetPage();});
$('bill-prev').addEventListener('click',()=>{if(state.page>1){state.page--;load();}});
$('bill-next').addEventListener('click',()=>{if(state.page*12<state.total){state.page++;load();}});
async function init(){
 try{const response=await fetch('/api/bills/coverage');if(!response.ok)throw Error();const c=await response.json();
  if(c.status!=='ready')throw Error();
  const docs=c.document_coverage;
  $('bill-coverage').textContent=`${c.records.toLocaleString()} bill catalogue records · Introduction dates ${prettyDate(c.date_from)}–${prettyDate(c.date_to)} · Source snapshot ${prettyDate(c.imported_at.slice(0,10))}. `+(docs?`${(docs.records_with_cached_readable_text || 0).toLocaleString()} bills have cached readable PDF text across ${(docs.cached_readable_versions || 0).toLocaleString()} versions at the local audit (${prettyDate(c.coverage_checked_at?.slice(0,10))}). Other document links load on demand; not every bill PDF is already searchable or currently reachable. `:'PDF text coverage has not been audited. ')+`Catalogue dates do not establish complete coverage or live bill status.`;
  Object.keys(c.years).sort((a,b)=>b-a).forEach(y=>$('bill-year').add(new Option(y,y)));
  c.ministries.forEach(m=>$('bill-ministry').add(new Option(m,m)));
 }catch{$('bill-coverage').textContent='Catalogue coverage unavailable. Please refresh or check the official source.';}
 await load();
}
init();

async function fetchBillPeople(id, timeoutMs=20000) {
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),timeoutMs);
 try {
  const response=await fetch(`/api/bills/${encodeURIComponent(id)}/people`,{signal:controller.signal});
  if(!response.ok)throw Error('Presenter details could not be loaded. Reopen this bill to retry.');
  return await response.json();
 }catch(error){
  if(error.name==='AbortError')throw Error('Presenter lookup timed out. Official documents remain available. Close and reopen this bill to retry.');
  throw error;
 }finally{clearTimeout(timer);}
}

$('bill-results').addEventListener('toggle',async event=>{
 const card=event.target;if(!card.matches('details.bill-card') || !card.open)return;
 const panel=card.querySelector('.bill-people-content');if(!panel || panel.dataset.loaded || panel.dataset.loading)return;
 panel.dataset.loading='1';
 try{
  const data=await fetchBillPeople(card.id);if(!card.isConnected)return;
  panel.innerHTML=recordPeopleHTML(data);wirePersonCards(panel);panel.dataset.loaded='1';
 }catch(error){panel.textContent=error.message;}finally{delete panel.dataset.loading;}
},true);

fetch('/api/ai-status').then(r=>r.json()).then(config=>{
 $('bill-ai-status').textContent=config.configured
  ? `Bill answers use ${config.provider === 'gemini'?'Gemini':'OpenAI'} (${config.model}). Source retrieval does not require an AI call.`
  : 'AI credentials are not configured. PDF loading and source retrieval remain available.';
}).catch(()=>{$('bill-ai-status').textContent='AI configuration status is currently unavailable.';});

function renderBillAnswer(data){
 const evidence=data.evidence || [];
 const answer=data.answer?esc(data.answer).replace(/\[E(\d+)\]/g,(tag,n)=>{const item=evidence[Number(n)-1];return item?`<a href="${esc(item.pdf_url)}" target="_blank" rel="noopener noreferrer" title="${esc(data.version_label)} · PDF page ${item.page}">${tag}</a>`:tag;}):'';
 const notices={sources_only:'Source passages retrieved. Select Ask AI to generate an explanation.',insufficient_evidence:'No matching passage found. Try a clause number or words used in the document.',ai_unavailable:'AI answer unavailable; source passages are shown below.',citation_check_failed:'The answer was withheld because its evidence references failed validation.'};
 return `<div class="bill-answer-scope"><strong>${esc(data.version_label)}</strong> · ${data.readable_pages}/${data.page_count} pages have readable text. <a href="/api/bills/${encodeURIComponent(data.bill_id)}/pdf?version=${encodeURIComponent(data.version)}" target="_blank" rel="noopener noreferrer">Open loaded PDF ↗</a></div>${answer?`<div class="bill-answer-text">${answer}</div>`:`<p>${esc(data.ai_message || notices[data.answer_status] || 'Document ready.')}</p>`}<div class="bill-evidence">${evidence.map(e=>`<details><summary>[${esc(e.citation)}] · PDF page ${e.page} · ${esc(data.version_label)}</summary><p class="bill-passage">${esc(e.text)}</p><a href="${esc(e.pdf_url)}" target="_blank" rel="noopener noreferrer">Open PDF at page ${e.page} ↗</a></details>`).join('')}</div>${data.warnings?.length?`<details class="bill-answer-limits"><summary>Coverage &amp; answer limitations</summary><ul>${data.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}`;
}
async function runBillQuestion(form,action){
 qaRequests.get(form)?.abort();const controller=new AbortController();qaRequests.set(form,controller);
 const version=form.elements.version.value;const id=form.dataset.bill;
 const output=form.querySelector('.bill-qa-output');const status=form.querySelector('.bill-qa-status');
 const question=form.elements.question.value.trim();
 if(action!=='load' && question.length<3){status.textContent='Please enter a question with at least three characters.';form.elements.question.focus();return;}
 output.replaceChildren();status.textContent=action==='load'?'Loading official PDF and extracting page text…':'Retrieving passages from the selected PDF…';
 form.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{
  const response=await fetch(`/api/bills/${encodeURIComponent(id)}/${action==='load'?'document':'ask'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,...(action==='load'?{}:{question,synthesize:action==='answer'})}),signal:controller.signal});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'The document request failed. Please try again.');
  if(controller.signal.aborted || !form.isConnected || form.elements.version.value!==version)return;
  if(action==='load'){
   status.textContent=`${data.version_label} loaded: ${data.readable_pages} of ${data.page_count} PDF pages have readable text.`;
   output.innerHTML=`<p><a href="/api/bills/${encodeURIComponent(id)}/pdf?version=${encodeURIComponent(version)}" target="_blank" rel="noopener noreferrer">Open loaded PDF ↗</a></p><p>${data.warnings.map(esc).join(' ')}</p>`;
  }else{status.textContent=data.answer_status==='generated'?'Answer generated from the selected version. Check the cited passages.':'Source retrieval complete.';output.innerHTML=renderBillAnswer(data);}
 }catch(e){if(e.name!=='AbortError')status.textContent=e.message;}
 finally{if(qaRequests.get(form)===controller)form.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
$('bill-results').addEventListener('submit',e=>{const form=e.target.closest('.bill-qa-form');if(!form)return;e.preventDefault();runBillQuestion(form,e.submitter?.dataset.qa || 'sources');});
$('bill-results').addEventListener('click',e=>{const button=e.target.closest('[data-qa="load"]');if(button)runBillQuestion(button.closest('form'),'load');});
$('bill-results').addEventListener('change',e=>{if(e.target.name!=='version')return;const form=e.target.closest('.bill-qa-form');if(!form)return;qaRequests.get(form)?.abort();form.querySelector('.bill-qa-output').replaceChildren();form.querySelector('.bill-qa-status').textContent='Version changed. Load this version or ask a new question.';form.querySelectorAll('button').forEach(b=>b.disabled=false);});
