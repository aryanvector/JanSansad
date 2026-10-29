"""Validate a reference packet without generating or scoring model answers."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def safe_file(root: Path, relative: str):
    path = (root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError('Artifact path escapes its root')
    return path


def check_files(root, entries):
    for relative, expected in entries.items():
        path = safe_file(root, relative)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Missing or changed frozen file: '+relative)


def check_quote(fact, sources):
    ev = fact['evidence']
    source = sources.get(ev['question_id'])
    if source is None:
        raise ValueError('Unknown reference source')
    chunk = next((c for c in source['chunks'] if c['chunk_index'] == ev['chunk_index']), None)
    if chunk is None or chunk['chunk_id'] != ev['chunk_id']:
        raise ValueError('Reference chunk identity mismatch')
    if not ev['quote'] or ev['quote'] not in chunk['text'] or sha(ev['quote']) != ev['quote_sha256']:
        raise ValueError('Reference quote absent or hash mismatch')
    if not fact.get('statement'):
        raise ValueError('Missing atomic reference statement')
    if fact.get('value') is not None and not fact.get('unit'):
        raise ValueError('Reference value requires a unit/scope description')


def check_future(question, corpus):
    requested = date.fromisoformat(question['negative_basis']['requested_date'])
    dates = [date.fromisoformat(s['date_to']) for s in corpus['qa'].values() if s.get('date_to')]
    if not dates or requested <= max(dates):
        raise ValueError('Future-date control is not justified by corpus date bounds')
    if question['required_facts'] or question['evidence_groups'] or question['required_record_ids']:
        raise ValueError('Missing-source control cannot silently include a substitute reference')


def validate(root: Path, repo: Path):
    rows = [json.loads(line) for line in (root/'sources.jsonl').read_text(encoding='utf-8').splitlines() if line]
    sources = {s['question_id']:s for s in rows}
    if len(sources) != len(rows):
        raise ValueError('Duplicate source identities')
    excluded = set(json.loads((root/'excluded-records.json').read_text())['records'])
    if excluded & sources.keys():
        raise ValueError('Reference source overlaps prior development records')
    for s in rows:
        date.fromisoformat(s['date'])
        if s['house'] not in ('lok_sabha','rajya_sabha') or not s['archived_all_indexed_chunks']:
            raise ValueError('Unsupported House or incomplete indexed-source archive')
        if s['total_indexed_chunks'] != len(s['chunks']):
            raise ValueError('Archived source count mismatch')
        if len({c['chunk_index'] for c in s['chunks']}) != len(s['chunks']):
            raise ValueError('Duplicate source passage indices')
        for c in s['chunks']:
            if sha(c['text']) != c['text_sha256']:
                raise ValueError('Source passage hash mismatch')
    questions=[json.loads(line) for line in (root/'questions.jsonl').read_text(encoding='utf-8').splitlines() if line]
    if len(questions)!=30 or len({q['id'] for q in questions})!=30:
        raise ValueError('Expected 30 unique question identities')
    if Counter(q['domain'] for q in questions) != {'railways':10,'education':10,'health':10}:
        raise ValueError('Domain allocation changed')
    expected={'single':18,'multi':6,'insufficient_scope':3,'future_source_control':3}
    if Counter(q['task_type'] for q in questions)!=expected:
        raise ValueError('Task allocation changed')
    corpus=json.loads((root/'corpus-scope.json').read_text())
    facts=0
    for q in questions:
        if q['task_type']=='future_source_control':
            check_future(q,corpus)
            continue
        fact_ids={f['evidence']['question_id'] for f in q['required_facts']}
        if not fact_ids or fact_ids!=set(q['required_record_ids']):
            raise ValueError('Required records and reference facts disagree')
        groups=q['evidence_groups']
        if not groups or any(not g.get('any_of') or not set(g['any_of'])<=sources.keys() for g in groups):
            raise ValueError('Empty/unknown required evidence group')
        group_ids={qid for g in groups for qid in g['any_of']}
        if not fact_ids<=group_ids:
            raise ValueError('A reference fact is missing from evidence groups')
        houses={sources[qid]['house'] for qid in fact_ids}
        if q['filters']['house']!='both' and houses!={q['filters']['house']}:
            raise ValueError('House filter excludes reference evidence')
        for f in q['required_facts']:
            check_quote(f,sources);facts+=1
    freeze=json.loads((root/'code-freeze-before-labels.json').read_text())
    # Restrict this registry to source files; do not permit configuration/secret reads.
    if any(not p.startswith('src/lok_sabha_rag/') or Path(p).suffix not in ('.py','.txt') for p in freeze['files']):
        raise ValueError('Unexpected non-source path in code registry')
    check_files(repo,freeze['files'])
    pdf_rows=json.loads((root/'official-pdf-check.json').read_text())
    pdf_count=0;quote_count=0
    for row in pdf_rows:
        if row['status']!='downloaded_and_extracted':continue
        qid=row['question_id']; pdf=safe_file(root,'source-pdfs/'+qid+'.pdf')
        if not pdf.read_bytes().startswith(b'%PDF-') or hashlib.sha256(pdf.read_bytes()).hexdigest()!=row['pdf_sha256']:
            raise ValueError('Official PDF hash mismatch')
        checked={r['quote_sha256']:r['normalized_quote_present'] for r in row['quote_checks']}
        for q in questions:
            for f in q['required_facts']:
                ev=f['evidence']
                if ev['question_id']==qid and checked.get(ev['quote_sha256']) is not True:
                    raise ValueError('Current reference quote lacks its official PDF cross-check')
        pdf_count+=1;quote_count+=len(checked)
    manifest=root/'manifest.json'
    if manifest.exists():
        check_files(root,json.loads(manifest.read_text())['files'])
    return {'status':'validated','questions':len(questions),'source_records':len(sources),
            'source_passages':sum(len(s['chunks']) for s in rows),'reference_checkpoints':facts,
            'overlap_with_prior_records':0,'official_pdfs_crosschecked':pdf_count,
            'unique_official_pdf_quotes_crosschecked':quote_count,
            'independent_review':'pending','system_outputs_collected':False,
            'note':'Integrity and source-text checks only; not independent label adjudication or measured model accuracy.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--set',dest='root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True)
    a=p.parse_args();print(json.dumps(validate(a.root,a.repo),indent=2))
