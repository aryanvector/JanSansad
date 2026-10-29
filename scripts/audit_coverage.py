"""Read-only inventory; never reads configuration secrets or makes model calls."""
import json
import sqlite3
from pathlib import Path
from lok_sabha_rag.config import DATA_DIR, METADATA_DB_PATH
from lok_sabha_rag.core.retriever import Retriever


def main():
    result = {'databases': {}, 'manifests': {}, 'collections': {}}
    paths = [METADATA_DB_PATH, DATA_DIR/'rajya_sabha_kaggle/records.db',
             DATA_DIR/'rs_debates/debates.db', DATA_DIR/'ls_debates/debates.db',
             DATA_DIR/'debate_fulltext/index.db']
    for path in paths:
        if not path.exists():
            continue
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
            tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name IN ('questions','records','documents','passages')").fetchall()
            info = {}
            for name, sql in tables:
                info[name] = {'schema': sql, 'count': db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]}
                columns = [r[1] for r in db.execute(f'PRAGMA table_info({name})')]
                if 'date' in columns:
                    info[name]['dates'] = db.execute(f'SELECT min(date),max(date),count(distinct substr(date,1,4)) FROM {name}').fetchone()
                    info[name]['years'] = db.execute(f'SELECT substr(date,1,4),count(*) FROM {name} GROUP BY 1').fetchall()
                if 'status' in columns:
                    info[name]['statuses'] = db.execute(f'SELECT house,status,count(*),min(date),max(date) FROM {name} GROUP BY house,status').fetchall()
            result['databases'][str(path)] = info
    for path in [DATA_DIR/'rajya_sabha/manifest.json', DATA_DIR/'rajya_sabha_kaggle/manifest.json', DATA_DIR/'ls_debates/manifest.json', DATA_DIR/'rs_debates/manifest.json']:
        if path.exists():
            d = json.loads(path.read_text())
            result['manifests'][str(path)] = {k:v for k,v in d.items() if k not in ('members','ministries','audit')}
    r = Retriever()
    for name in [r.collection, r.rs_collection]:
        try:
            info = r.client.get_collection(name)
            result['collections'][name] = {'points': info.points_count, 'payload_schema': list(info.payload_schema), 'status': str(info.status)}
        except Exception as error:
            result['collections'][name] = {'error_type': type(error).__name__}
    for label, path in [('bills', DATA_DIR/'bills/catalogue.json'), ('ministers', DATA_DIR/'ministers/catalogue.json')]:
        if path.exists():
            d = json.loads(path.read_text())
            result[label] = {'records': len(d.get('records', [])), 'manifest': d.get('manifest', {})}
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
