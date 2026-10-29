"""Save paired drafts/checker outputs; never score semantic correctness here."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from unittest.mock import patch

from .validate_set import validate
from lok_sabha_rag.core import ai_provider
from lok_sabha_rag.core.answer_checks import audit_answer, generate_checked
from lok_sabha_rag.core.synthesizer import Synthesizer, validate_citations, extract_citations


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.pending')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


class ProviderTrace:
    """Observe safe usage/version metadata, never headers or raw error bodies."""
    def __init__(self,path,max_calls=90):
        self.path=path;self.max_calls=max_calls;self.tag='';self.halt=None;self.consecutive_errors=0
        self.events=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        self.started={e['tag'] for e in self.events if e['event']=='start'}
        self.calls=sum(e['event']=='start' for e in self.events)
        if any(e.get('http_status') in (401,403,429) for e in self.events):self.halt='prior_authentication_or_quota_rejection'

    def event(self,event,**fields):
        row={'event':event,'tag':self.tag,'at':datetime.now(timezone.utc).isoformat(),**fields}
        self.events.append(row)
        with self.path.open('a',encoding='utf-8') as file:file.write(json.dumps(row)+'\n')

    def allowed(self,tag):
        if self.halt:return False,self.halt
        if self.calls>=self.max_calls:return False,'generation_call_cap'
        if tag in self.started:return False,'previous_attempt_already_recorded'
        return True,None

    def observe_builder(self,original):
        trace=self
        class Response:
            def __init__(self,response):self.response=response
            def __enter__(self):self.response.__enter__();return self
            def __exit__(self,*args):return self.response.__exit__(*args)
            def read(self,*args,**kwargs):
                try:
                    raw=self.response.read(*args,**kwargs)
                    data=json.loads(raw)
                    usage={k:v for k,v in data.get('usageMetadata',{}).items() if isinstance(v,(int,float))}
                    trace.event('response',http_status=200,model_version=data.get('modelVersion'),usage=usage)
                    return raw
                except Exception as error:
                    trace.event('response_error',error_type=type(error).__name__)
                    raise
        class Opener:
            def __init__(self,opener):self.opener=opener
            def open(self,*args,**kwargs):
                allowed,reason=trace.allowed(trace.tag)
                if not allowed:raise ai_provider.GenerationError('Evaluation generation stopped: '+reason,'evaluation_stopped')
                trace.calls+=1;trace.started.add(trace.tag);trace.event('start',attempt=trace.calls)
                try:return Response(self.opener.open(*args,**kwargs))
                except Exception as error:
                    status=getattr(error,'code',None)
                    trace.event('transport_error',http_status=status,error_type=type(error).__name__)
                    if status in (401,403,429):trace.halt='authentication_or_quota_rejection'
                    raise
        return lambda *a,**kw:Opener(original(*a,**kw))


class TaggedSynthesizer:
    def __init__(self,trace,tag):self.trace=trace;self.tag=tag;self.synth=Synthesizer()
    def generate(self,query,context):
        allowed,reason=self.trace.allowed(self.tag)
        if not allowed:raise ai_provider.GenerationError('Evaluation generation stopped: '+reason,'evaluation_stopped')
        self.trace.tag=self.tag
        try:
            result=self.synth.generate(query=query,context=context)
            self.trace.consecutive_errors=0
            return result
        except ai_provider.GenerationError:
            self.trace.consecutive_errors+=1
            if self.trace.consecutive_errors>=3:self.trace.halt='three_consecutive_generation_errors'
            raise


class DraftReplay:
    def __init__(self,draft,repair):self.draft=draft;self.repair=repair;self.replayed=False
    def generate(self,query,context):
        if not self.replayed:self.replayed=True;return self.draft
        return self.repair.generate(query=query,context=context)


def main(root,repo,out):
    validate(root,repo)
    config=ai_provider.configuration()
    if config['provider']!='gemini' or not config['configured']:
        raise ValueError('This safe metadata observer is defined for the configured Gemini provider only')
    setup={'generator_runner_sha256':digest(Path(__file__)), 'reference_manifest_sha256':digest(root/'manifest.json'),
           'retrieval_execution_sha256':digest(out/'execution-freeze.json'),
           'provider':config['provider'],'model_alias':config['model'],'max_provider_calls':90,
           'frozen_at':datetime.now(timezone.utc).isoformat(),'semantic_scoring':'pending independent review'}
    setup_file=out/'generation-freeze.json'
    if setup_file.exists():
        old=json.loads(setup_file.read_text())
        for k in setup:
            if k!='frozen_at' and old.get(k)!=setup[k]:raise ValueError('Generation resume would change frozen setup')
    else:save(setup_file,setup)
    trace=ProviderTrace(out/'provider-events.jsonl')
    questions=[json.loads(line) for line in (root/'questions.jsonl').read_text(encoding='utf-8').splitlines() if line]
    original=ai_provider.build_opener
    with patch.object(ai_provider,'build_opener',trace.observe_builder(original)):
        for index,q in enumerate(questions):
            order=('base','improved') if index%2==0 else ('improved','base')
            for method in order:
                target=out/'answers'/method/(q['id']+'.json')
                if target.exists():continue
                retrieval=json.loads((out/'retrieval'/method/(q['id']+'.json')).read_text())
                row={'id':q['id'],'method':method,'query':q['query'],'created_at':datetime.now(timezone.utc).isoformat(),
                     'retrieval_status':retrieval['status'],'source_records':[g['question_id'] for g in retrieval.get('groups',[])]}
                groups=retrieval.get('groups',[])
                tag=q['id']+'/'+method+'/draft'
                allowed,reason=trace.allowed(tag)
                if retrieval['status']!='ok':row.update(status='not_run_retrieval_error',answer=None)
                elif not groups:row.update(status='no_evidence',answer=None,message='No matching indexed source evidence for this request; no generation attempted.')
                elif not allowed:row.update(status='not_run_provider_guard',answer=None,reason=reason)
                else:
                    start=time.perf_counter()
                    try:
                        answer=TaggedSynthesizer(trace,tag).generate(q['query'],retrieval['context'])
                        row.update(status='generated',answer=answer,citation_id_errors=validate_citations(answer,len(groups)),
                            citations_used=extract_citations(answer,len(groups)),automatic_checks=audit_answer(answer,groups))
                    except ai_provider.GenerationError as error:
                        row.update(status='generation_error',answer=None,error_code=error.code)
                    row['generation_seconds']=round(time.perf_counter()-start,4)
                save(target,row)
                print(q['id'],method,row['status'],flush=True)
            target=out/'answers'/'improved_checked'/(q['id']+'.json')
            if target.exists():continue
            raw=json.loads((out/'answers'/'improved'/(q['id']+'.json')).read_text())
            row={**raw,'method':'improved_checked','paired_draft_path':'../improved/'+q['id']+'.json'}
            if raw['status']=='generated':
                retrieval=json.loads((out/'retrieval'/'improved'/(q['id']+'.json')).read_text())
                replay=DraftReplay(raw['answer'],TaggedSynthesizer(trace,q['id']+'/improved/repair'))
                start=time.perf_counter()
                answer,report=generate_checked(replay,q['query'],retrieval['context'],retrieval['groups'])
                row.update(answer=answer,automatic_checks=report,citation_id_errors=validate_citations(answer,len(retrieval['groups'])),
                    citations_used=extract_citations(answer,len(retrieval['groups'])),extra_check_seconds=round(time.perf_counter()-start,4))
                if trace.halt:row['provider_guard_reason']=trace.halt
            save(target,row)
            print(q['id'],'improved_checked',row['status'],'repair',row.get('automatic_checks',{}).get('repair_attempted',False),flush=True)
    summary={'attempted_provider_calls':trace.calls,'provider_halt':trace.halt,'by_method':{},
             'model_versions':sorted({e['model_version'] for e in trace.events if e.get('model_version')}),
             'usage_totals':{},'semantic_accuracy':'not scored; independent review pending'}
    for event in trace.events:
        for k,v in event.get('usage',{}).items():summary['usage_totals'][k]=summary['usage_totals'].get(k,0)+v
    for method in ('base','improved','improved_checked'):
        rows=[json.loads((out/'answers'/method/(q['id']+'.json')).read_text()) for q in questions]
        summary['by_method'][method]={'cases':len(rows),'statuses':{status:sum(r['status']==status for r in rows) for status in sorted({r['status'] for r in rows})},
            'generated_answers_with_invalid_citation_ids':sum(bool(r.get('citation_id_errors')) for r in rows),
            'generated_answers_with_automatic_issues':sum(bool(r.get('automatic_checks',{}).get('issues')) for r in rows)}
    save(out/'generation-summary.json',summary)
    with (out/'manual-answer-review.csv').open('w',newline='',encoding='utf-8-sig') as file:
        fields=['question_id','domain','task_type','method','status','reference_answer','generated_answer','citation_id_errors','reviewer','reference_checkpoint_score','claim_citation_support','unsupported_extra_claims','appropriate_abstention','notes']
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for q in questions:
            for method in ('base','improved','improved_checked'):
                row=json.loads((out/'answers'/method/(q['id']+'.json')).read_text())
                data={'question_id':q['id'],'domain':q['domain'],'task_type':q['task_type'],'method':method,
                      'status':row['status'],'reference_answer':q['reference_answer'],'generated_answer':row.get('answer') or row.get('message') or '',
                      'citation_id_errors':'; '.join(row.get('citation_id_errors',[]))}
                for k,v in data.items():
                    if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')):data[k]="'"+v
                writer.writerow(data)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--set',dest='root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.root,a.repo,a.output)
