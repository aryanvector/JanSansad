"""Bounded, read-only comparison on an immutable provisional reference set."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from .metrics import evidence_metrics
from .validate_set import validate, check_files
from lok_sabha_rag.core import scoped_retrieval, kaggle_store
from lok_sabha_rag.core.retriever import Retriever
from lok_sabha_rag.core.temporal_retrieval import retrieve_comparison, period_coverage, coverage_context

METHODS=('base','scope_ablation','improved')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ablation():
    source=Path(scoped_retrieval.__file__).read_text(encoding='utf-8')
    tree=ast.parse(source);counts=Counter()
    class Disable(ast.NodeTransformer):
        def visit_Assign(self,node):
            self.generic_visit(node)
            names={n.id for n in node.targets if isinstance(n,ast.Name)}
            if 'numeric_request' in names:
                node.value=ast.Constant(False);counts['table_bonus']+=1
            if 'missing_slots' in names:
                node.value=ast.List(elts=[],ctx=ast.Load());counts['recovery']+=1
            return node
        def visit_If(self,node):
            self.generic_visit(node)
            if ast.unparse(node.test)=="'|' in chunk.text and previous":
                node.test=ast.Constant(False);counts['unit_carryover']+=1
            return node
    tree=Disable().visit(tree);ast.fix_missing_locations(tree)
    if counts!={'table_bonus':1,'recovery':1,'unit_carryover':1}:
        raise ValueError('Ablation source blocks differ from the frozen method definition')
    namespace={'__name__':'frozen_scope_ablation'}
    exec(compile(tree,'<frozen_scope_ablation>','exec'),namespace)
    return namespace['retrieve_scoped'],dict(counts)


class ReadClient:
    def __init__(self,client,cost):self.client=client;self.cost=cost
    def __getattr__(self,name):
        value=getattr(self.client,name)
        if name not in ('query_points','scroll','count'):return value
        def call(*args,**kwargs):
            self.cost['qdrant_'+name+'_calls']+=1
            return value(*args,**kwargs)
        return call


class MeteredRetriever:
    def __init__(self,base):
        self.base=base;self.cost=Counter();self.original_client=base.client
        base.client=ReadClient(self.original_client,self.cost)
    def __getattr__(self,name):return getattr(self.base,name)
    def search(self,*args,**kwargs):
        self.cost['backend_search_calls']+=1
        result=Retriever.search(self,*args,**kwargs)
        self.cost['returned_search_chunks']+=len(result)
        return result
    def _fetch_leading_chunks(self,*args,**kwargs):
        self.cost['passage_fetch_calls']+=1
        result=Retriever._fetch_leading_chunks(self,*args,**kwargs)
        self.cost['fetched_passages_including_repeats']+=len(result)
        return result
    def _count_total_chunks(self,*args,**kwargs):return Retriever._count_total_chunks(self,*args,**kwargs)
    def group_evidence(self,*args,**kwargs):return Retriever.group_evidence(self,*args,**kwargs)
    def restore(self):self.base.client=self.original_client


def run_retrieval(base,question,method,ablation,m=45,n=10,c=2):
    metered=MeteredRetriever(base);years=[];scope=None
    original_keyword=kaggle_store.search
    def keyword(*args,**kwargs):
        metered.cost['historical_keyword_search_calls']+=1
        return original_keyword(*args,**kwargs)
    start=time.perf_counter()
    try:
        with patch.object(kaggle_store,'search',keyword):
            scoped=None
            if method!='base':
                planner=scoped_retrieval.retrieve_scoped if method=='improved' else ablation
                scoped=planner(metered,question['query'],m,n,c,**question['filters'])
            if method=='base':items=metered.search(query=question['query'],top_k=m,**question['filters'])
            elif scoped is not None:items,scope=scoped
            else:items,years=retrieve_comparison(metered,question['query'],m,**question['filters'])
            groups=metered.group_evidence(items,top_n=n,chunks_per_question=c,prefer_matches=True,
                required_years=years,answer_passages_only=scope is not None)
            context=base.build_context_grouped(groups)
            coverage=period_coverage(groups,years)
            if coverage:context=coverage_context(coverage)+'\n\n'+context
            if scope:context=scoped_retrieval.scope_context(scope)+'\n\n'+context
        return {'status':'ok','groups':[asdict(g) for g in groups], 'source_scope':scope,
                'period_coverage':coverage,'context':context,'retrieved_chunks':len(items),
                'delivered_passages':sum(len(g.chunks) for g in groups),
                'context_characters':len(context),'cost':dict(metered.cost),
                'seconds':round(time.perf_counter()-start,6)}
    finally:metered.restore()


def context_support(question,groups):
    # Conservative full-reference-span presence; partial semantic support can miss.
    normalize=lambda text:' '.join(text.split())
    by_record={g['question_id']:normalize('\n'.join(c['text'] for c in g['chunks'])) for g in groups}
    checks=[{'reference_record':f['evidence']['question_id'],
             'quote_present':normalize(f['evidence']['quote']) in by_record.get(f['evidence']['question_id'],'')}
            for f in question['required_facts']]
    return {'checkpoints':checks,'coverage':sum(c['quote_present'] for c in checks)/len(checks) if checks else None}


def score(question,result):
    ids=[g['question_id'] for g in result.get('groups',[])]
    scores={str(k):evidence_metrics(ids,question['evidence_groups'],k) for k in (5,10)} if question['evidence_groups'] else {}
    return {'retrieval':scores,'reference_quote_context_support':context_support(question,result.get('groups',[]))}


def state(base):
    from lok_sabha_rag.config import DATA_DIR
    return {'checked_at':datetime.now(timezone.utc).isoformat(),
        'collection_points':{name:base.client.get_collection(name).points_count for name in (base.collection,base.rs_collection)},
        'historical_store_sha256':digest(kaggle_store.path()),
        'rs_manifest_sha256':digest(DATA_DIR/'rajya_sabha/manifest.json'),
        'embedding_model':base.model,'note':'Counts/store hashes are diagnostics, not a byte-level vector-corpus freeze.'}


def retrieval_main(root,repo,out):
    validation=validate(root,repo)
    out.mkdir(parents=True,exist_ok=True)
    method_file=Path(__file__)
    setup={'reference_manifest_sha256':digest(root/'manifest.json'),'runner_sha256':digest(method_file),
           'budgets':{'M':45,'N':10,'C':2},'methods':list(METHODS),'labels':'provisional; independent review pending',
           'frozen_at':datetime.now(timezone.utc).isoformat()}
    setup_file=out/'execution-freeze.json'
    if setup_file.exists():
        old=json.loads(setup_file.read_text())
        if any(old[k]!=setup[k] for k in ('reference_manifest_sha256','runner_sha256','budgets','methods')):
            raise ValueError('Do not resume with changed methods or references')
    else:setup_file.write_text(json.dumps(setup,indent=2))
    ablation,disabled=load_ablation();base=Retriever()
    if not (out/'corpus-before.json').exists():(out/'corpus-before.json').write_text(json.dumps(state(base),indent=2))
    # Warm-up is not an evaluated question and its results are not inspected.
    base.search('parliamentary research',top_k=1,house='lok_sabha',content_type='qa')
    questions=[json.loads(line) for line in (root/'questions.jsonl').read_text(encoding='utf-8').splitlines() if line]
    for index,q in enumerate(questions):
        order=METHODS[index%3:]+METHODS[:index%3]
        for method in order:
            folder=out/'retrieval'/method;folder.mkdir(parents=True,exist_ok=True)
            target=folder/(q['id']+'.json')
            if target.exists():continue
            try:result=run_retrieval(base,q,method,ablation)
            except Exception as error:result={'status':'error','error_type':type(error).__name__,'groups':[]}
            row={'id':q['id'],'method':method,'domain':q['domain'],'task_type':q['task_type'],
                 'request':{'query':q['query'],**q['filters']},**result,'scores':score(q,result)}
            target.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
            print(q['id'],method,result['status'],'groups',len(result.get('groups',[])),flush=True)
    (out/'corpus-after-retrieval.json').write_text(json.dumps(state(base),indent=2))
    summary=summarize_retrieval(questions,out)
    (out/'retrieval-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)


def summarize_retrieval(questions,out):
    summary={}
    for method in METHODS:
        method_rows=[json.loads((out/'retrieval'/method/(q['id']+'.json')).read_text()) for q in questions]
        strata={}
        for label,selected in [('answerable',[r for r in method_rows if r['task_type'] in ('single','multi')]),
                              ('source_scope',[r for r in method_rows if r['task_type']=='insufficient_scope'])]+[(d,[r for r in method_rows if r['domain']==d and r['task_type'] in ('single','multi')]) for d in ('railways','education','health')]:
            metrics={}
            for k in ('5','10'):
                metrics[k]={key:sum(r['scores']['retrieval'][k][key] for r in selected)/len(selected)
                            for key in ('group_coverage','complete_evidence','reciprocal_rank')}
            strata[label]={'questions':len(selected),'metrics':metrics,
                'quote_context_coverage':sum(r['scores']['reference_quote_context_support']['coverage'] or 0 for r in selected)/len(selected)}
        future=[r for r in method_rows if r['task_type']=='future_source_control']
        summary[method]={'strata':strata,'errors':sum(r['status']!='ok' for r in method_rows),
            'future_controls_with_no_groups':sum(r['status']=='ok' and not r['groups'] for r in future),
            'future_control_count':len(future),'total_cost':dict(sum((Counter(r.get('cost',{})) for r in method_rows),Counter())),
            'total_seconds':sum(r.get('seconds',0) for r in method_rows),
            'mean_context_characters':sum(r.get('context_characters',0) for r in method_rows)/len(method_rows)}
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--set',dest='root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();retrieval_main(args.root,args.repo,args.output)
