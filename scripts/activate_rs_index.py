"""Validate a staged HF index, then atomically publish its manifest. Keeps old data."""
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from qdrant_client import QdrantClient, models
from lok_sabha_rag.config import DATA_DIR, QDRANT_HOST, QDRANT_PORT

def activate(staged):
    path=Path(staged)
    manifest=json.loads(path.read_text())
    if manifest.get('dataset') != 'anudit/rajyasabha-qa' or manifest.get('status') != 'ready':
        raise ValueError('Only a completed requested Hugging Face source can be activated')
    client=QdrantClient(host=QDRANT_HOST,port=QDRANT_PORT)
    collection=manifest['collection']
    count=client.count(collection,exact=True).count
    if count != manifest['chunks'] or count == 0:
        raise ValueError('Staged point count does not match the manifest')
    rows=[json.loads(x) for x in (path.parent/'records.jsonl').read_text().splitlines()]
    if len(rows)!=manifest['records'] or len({x['question_id'] for x in rows})!=len(rows):
        raise ValueError('Record count or uniqueness mismatch')
    expected={x['question_id']:x for x in rows}
    seen=set(); scanned=0; offset=None
    while True:
        points,offset=client.scroll(collection,limit=512,offset=offset,with_payload=True)
        for point in points:
            payload=point.payload or {}; source=payload.get('source',{})
            qid=payload.get('question_id')
            if (source.get('dataset_revision')!=manifest['dataset_revision'] or
                not str(source.get('source_url','')).startswith('https://huggingface.co/datasets/anudit/rajyasabha-qa/') or
                qid not in expected or payload.get('date')!=expected[qid]['date']):
                raise ValueError('Indexed provenance differs from the staged source')
            seen.add(qid); scanned+=1
        if offset is None: break
    if scanned!=count or seen!=set(expected):
        raise ValueError('Index does not cover precisely the selected source records')
    active=DATA_DIR/'rajya_sabha'/'manifest.json'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if active.exists(): shutil.copy2(active,active.with_name(f'manifest-before-hf-{stamp}.json'))
    temp=active.with_suffix('.pending')
    temp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    temp.replace(active)
    print(f'Activated {manifest["dataset"]}: {len(rows)} records, {count} chunks. Restart app to load new index.')

if __name__=='__main__':
    import sys
    activate(sys.argv[1])
