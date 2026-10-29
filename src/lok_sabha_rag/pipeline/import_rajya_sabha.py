"""Reproducible, bounded RS pilot. Never deletes or overwrites the LS index."""
import argparse
import csv
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode

from huggingface_hub import hf_hub_download, HfApi
import pyarrow.parquet as pq
from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models
from lok_sabha_rag.config import DATA_DIR, QDRANT_HOST, QDRANT_PORT, EMBEDDING_MODEL

REPO = 'anudit/rajyasabha-qa'
COLLECTION = 'rajya_sabha_questions'
FILENAME = 'train-00000-of-00000.parquet'


def normalize(row):
    text = str(row.get('english') or '').strip()
    date = str(row.get('adate') or '')[:10]
    if len(text) < 150 or not re.search(r'\bANSWER\b', text, re.I):
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        return None
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return None
    # Do not silently use metadata when the extracted heading contradicts it.
    heading = re.search(r'(\d{2})[./](\d{2})[./](\d{4})', text[:350])
    if heading and f'{heading[3]}-{heading[2]}-{heading[1]}' != date:
        return None
    if not row.get('qslno') or not row.get('ses_no'):
        return None
    qid = f"RS_{row['ses_no']}_{row['qslno']}"
    return dict(question_id=qid, house='rajya_sabha', lok_no=None,
                session_no=int(row['ses_no']), ques_no=row.get('qno'),
                type=str(row.get('qtype') or '').strip().upper(), date=date,
                ministry=str(row.get('min_name') or '').strip(),
                mp_names=[str(row.get('name') or '').strip()],
                subject=str(row.get('qtitle') or '').strip(), text=text,
                source_record_id=row['qslno'])


def chunks(text, size=1400, overlap=180):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield text[start:end]
        if end == len(text):
            break
        start = end - overlap


def run(session=267, limit=500, csv_path=None, sessions_path=None, parquet_path=None,
        revision_override=None, folder_name='rajya_sabha', collection=COLLECTION):
    folder = DATA_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    dataset, license_name = REPO, 'mit'
    if csv_path:
        source = csv_path
        revision = 'kaggle-version-4'
        dataset, license_name = 'rajanand/rajyasabha', 'CC-BY-SA-4.0'
        sessions = list(csv.DictReader(open(sessions_path,encoding='utf-8-sig')))
        rows = []
        for r in csv.DictReader(open(source,encoding='utf-8-sig')):
            if len((r.get('answer') or '').strip()) < 30:
                continue
            date = datetime.strptime(r['answer_date'].strip(), '%d.%m.%Y').date().isoformat()
            term = next((x['session_no'] for x in sessions if x['session_start_date'] <= date <= x['session_end_date']), None)
            if term is None:
                continue
            rows.append(dict(english=f"RAJYA SABHA\nANSWERED ON {r['answer_date']}\n{r['question_title']}\n{r['question_description']}\nANSWER\n{r['answer']}", adate=date,
                qslno=int(r['id']), ses_no=int(term), qno=int(r['question_no']), qtype=r['question_type'],
                name=r['question_by'], min_name=r['ministry'], qtitle=r['question_title']))
        batches = [rows]
    else:
        revision = revision_override or HfApi().dataset_info(REPO).sha
        print(f'Using source snapshot {revision}', flush=True)
        source = parquet_path or hf_hub_download(REPO, FILENAME, repo_type='dataset', revision=revision)
        batches = (batch.to_pylist() for batch in pq.ParquetFile(source).iter_batches(batch_size=2048))
    print('Auditing rows and selecting pilot', flush=True)
    existing_manifest = folder/'manifest.json'
    if existing_manifest.exists() and json.loads(existing_manifest.read_text()).get('dataset') != dataset:
        raise RuntimeError('A different RS dataset is already indexed; use an explicit migration rather than mixing source identities.')
    records, seen, rejected, duplicates = [], set(), 0, 0
    for batch in batches:
        for row in batch:
            if row.get('ses_no') != session:
                continue
            item = normalize(row)
            if item is None:
                rejected += 1
                continue
            if item['question_id'] in seen:
                duplicates += 1
                continue
            seen.add(item['question_id'])
            records.append(item)
    records.sort(key=lambda x: (x['date'], x['question_id']), reverse=True)
    eligible = len(records)
    records = records[:limit]
    if not records:
        raise RuntimeError('No validated English records in requested session')
    raw = folder / 'records.jsonl'
    raw.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in records), encoding='utf-8')
    model = TextEmbedding(model_name=EMBEDDING_MODEL)
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=120)
    payloads = []
    for record in records:
        source_url = 'https://www.kaggle.com/datasets/rajanand/rajyasabha' if csv_path else f'https://huggingface.co/datasets/{REPO}/blob/{revision}/{FILENAME}'
        for index, text in enumerate(chunks(record['text'])):
            qid = record['question_id']
            payloads.append({**{k:v for k,v in record.items() if k != 'text'},
                'text':text, 'chunk_id':str(uuid.uuid5(uuid.NAMESPACE_URL, f'{qid}:{index}')),
                'source':{'chunk_index':index, 'pdf_url':None, 'source_url':source_url,
                          'source_record_id':record['source_record_id'], 'dataset_revision':revision}})
    # Same frozen embedding model as LS; named-vector key follows Qdrant FastEmbed.
    client.set_model(EMBEDDING_MODEL)
    vector_name = client.get_fastembed_vector_params()
    name, params = next(iter(vector_name.items()))
    if not client.collection_exists(collection):
        client.create_collection(collection, vectors_config=vector_name)
    if name not in client.get_collection(collection).config.params.vectors:
        raise RuntimeError('Unexpected existing vector configuration')
    print(f'Embedding {len(records)} records / {len(payloads)} chunks', flush=True)
    for start in range(0, len(payloads), 64):
        part = payloads[start:start+64]
        vectors = model.embed([x['text'] for x in part], batch_size=32)
        points = [models.PointStruct(id=p['chunk_id'], vector={name:v.tolist()}, payload=p) for p,v in zip(part,vectors)]
        client.upsert(collection, points, wait=True)
        print(f'Indexed {min(start+64,len(payloads))}/{len(payloads)}', flush=True)
    manifest = dict(status='ready', house='rajya_sabha', pilot=True, dataset=dataset,
        collection=collection,
        dataset_revision=revision, listed_license=license_name,
        source_sha256=hashlib.file_digest(open(source,'rb'),'sha256').hexdigest(),
        session=session, records=len(records), eligible_records=eligible,
        rejected_rows=rejected, duplicate_rows=duplicates, chunks=len(payloads),
        date_from=min(x['date'] for x in records), date_to=max(x['date'] for x in records),
        members=sorted({n for x in records for n in x['mp_names'] if n}),
        ministries=sorted({x['ministry'] for x in records if x['ministry']}),
        imported_at=datetime.now(timezone.utc).isoformat(),
        source_url=source_url,
        note='Limited English Q&A pilot, not complete Rajya Sabha coverage. Dataset citations; original PDFs are not yet linked or independently verified.')
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('members','ministries')},indent=2), flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--session',type=int,default=267)
    parser.add_argument('--limit',type=int,default=500)
    parser.add_argument('--csv')
    parser.add_argument('--sessions')
    parser.add_argument('--parquet')
    parser.add_argument('--revision')
    parser.add_argument('--folder',default='rajya_sabha')
    parser.add_argument('--collection',default=COLLECTION)
    args=parser.parse_args()
    run(args.session,args.limit,args.csv,args.sessions,args.parquet,args.revision,args.folder,args.collection)
