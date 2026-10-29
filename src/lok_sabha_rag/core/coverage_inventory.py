"""Audited local coverage. Refresh explicitly; no expensive scans per request."""
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timezone

from lok_sabha_rag.config import DATA_DIR, METADATA_DB_PATH


def path():
    return DATA_DIR / 'coverage_inventory.json'


def snapshot():
    try:
        return json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'not_audited', 'checked_at': None, 'qa': {}, 'debate_catalogues': {},
                'note': 'Local index coverage has not been audited. Counts must not be inferred from upstream dataset size.'}


def dated(rows):
    valid = []
    for value in rows:
        try:
            valid.append(date.fromisoformat(str(value)[:10]).isoformat())
        except (TypeError, ValueError):
            continue
    valid.sort()
    counts = Counter(d[:4] for d in valid)
    return {'date_from': valid[0] if valid else None, 'date_to': valid[-1] if valid else None,
            'years': dict(sorted(counts.items())), 'undated_records': len(rows)-len(valid),
            'continuity': 'Dates are observed record dates; endpoints do not establish complete coverage.'}


def database_summary(dbpath, table='records', json_date=False):
    if not dbpath.exists():
        return {'status': 'unavailable', 'records': 0, **dated([])}
    expr = "json_extract(record,'$.date')" if json_date else 'date'
    with closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        dates = [r[0] for r in db.execute(f'SELECT {expr} FROM {table}')]
    return {'status': 'ready', 'records': len(dates), **dated(dates)}


def indexed_qa(retriever):
    """Exact identities, not embedding chunk counts or upstream row counts."""
    client = retriever.client
    info = client.get_collection(retriever.collection)
    facets = client.facet(collection_name=retriever.collection, key='question_id', limit=200000, exact=True)
    ids = {str(hit.value) for hit in facets.hits}
    if len(ids) >= 200000 or sum(hit.count for hit in facets.hits) != info.points_count:
        raise ValueError('Unique-question facet did not cover every indexed chunk')
    with closing(sqlite3.connect(METADATA_DB_PATH.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        metadata = {f'{lok}_{session}_{number}_{kind}': date for lok, session, number, kind, date in
                    db.execute('SELECT lok_no,session_no,ques_no,type,date FROM questions')}
    ls = {'status': 'ready', 'records': len(ids), 'chunks': info.points_count,
          'collection': retriever.collection, 'retrieval': 'semantic',
          'metadata_records': len(metadata), 'metadata_without_index': len(metadata.keys()-ids),
          'indexed_without_metadata': len(ids-metadata.keys()),
          **dated([metadata.get(qid) for qid in ids])}
    # The small active RS pilot has no question-id facet index. Read payload
    # identities without embedding vectors; do not mutate indexes for an audit.
    rs_ids, offset, rs_points = {}, None, 0
    while True:
        points, offset = client.scroll(collection_name=retriever.rs_collection,
            limit=1000, offset=offset, with_payload=['question_id', 'date'], with_vectors=False)
        for point in points:
            payload = point.payload or {}
            qid = payload.get('question_id')
            if not qid:
                raise ValueError('Active RS chunk lacks a question identity')
            rs_ids[str(qid)] = payload.get('date')
        rs_points += len(points)
        if offset is None:
            break
    rs = {'status': 'ready', 'records': len(rs_ids), 'chunks': rs_points,
          'collection': retriever.rs_collection, 'retrieval': 'semantic', **dated(list(rs_ids.values()))}
    return ls, rs


def audit(retriever):
    from lok_sabha_rag.core import debate_store, kaggle_store, bill_store, bill_documents, minister_store
    ls, rs = indexed_qa(retriever)
    kg = database_summary(kaggle_store.path(), json_date=True)
    kg.update(retrieval='keyword', snapshot_at=kaggle_store.manifest().get('imported_at'))
    rs['snapshot_at'] = json.loads((DATA_DIR/'rajya_sabha/manifest.json').read_text()).get('imported_at')
    catalogues = {h: {**database_summary(p), 'snapshot_at': debate_store.manifest(h).get('imported_at')}
                  for h, p in [('lok_sabha', debate_store.ls_path()), ('rajya_sabha', debate_store.path())]}
    bills = bill_store.catalogue()
    rows = bills['records']
    counts = Counter()
    linked_records = set()
    cached_records = set()
    cache_dates = []
    for row in rows:
        versions = bill_documents.versions(row)
        if versions:
            linked_records.add(row['id'])
        counts['supported_version_links'] += len(versions)
        for version in versions:
            if not version.get('pdf_supported'):
                counts['word_version_links'] += 1
                continue
            data = bill_documents.cached(row, version['key'])
            if data and data.get('readable_pages', 0) > 0:
                counts['cached_readable_versions'] += 1
                counts['readable_pages'] += data['readable_pages']
                cached_records.add(row['id'])
                if data.get('extracted_at'):
                    cache_dates.append(data['extracted_at'])
    ministers = minister_store.catalogue()
    scopes = ministers.get('jurisdictions', [])
    result = {'status': 'ready', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'qa': {'lok_sabha': ls, 'rajya_sabha_hf': rs, 'rajya_sabha_kaggle': kg},
        'debate_catalogues': catalogues,
        'bills': {'records': len(rows), 'records_with_supported_links': len(linked_records),
                  'records_with_cached_readable_text': len(cached_records), **dict(counts),
                  'snapshot_at': bills.get('manifest', {}).get('imported_at'),
                  **dated([row.get('introduced_date') for row in rows]),
                  'latest_extraction_at': max(cache_dates) if cache_dates else None,
                  'note': 'Catalogue links are not all downloaded or currently reachable. Cached readable versions support document QA; this is not a full-text index of every bill.'},
        'ministers': {'records': len(ministers.get('records', [])), 'jurisdictions': len(scopes),
                     'jurisdictions_with_records': sum(s.get('record_count', 0)>0 for s in scopes),
                     'snapshot_at': ministers.get('generated_at'),
                     'note': 'Dated directory snapshot, not live verification of every current portfolio.'},
        'note': 'Local coverage audit, not a claim of a complete parliamentary archive. Index identities and catalogue counts are different measures.'}
    path().parent.mkdir(parents=True, exist_ok=True)
    temporary = path().with_suffix('.json.pending')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path())
    return result


if __name__ == '__main__':
    from lok_sabha_rag.core.retriever import Retriever
    print(json.dumps(audit(Retriever()), ensure_ascii=False, indent=2))
