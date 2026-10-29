"""Download a pinned public HF parquet with bounded parallel HTTP ranges."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen

REVISION='508b2411283162fdd52ee2c3e8ccaefbabfe9581'
SIZE=508851734
SHA256='9cf145189c89470da82324013b6510e462bbb3a2d6e4f68cebe90c318f1c2189'
URL=f'https://huggingface.co/datasets/anudit/rajyasabha-qa/resolve/{REVISION}/train-00000-of-00000.parquet'

def download(destination, workers=8):
    path=Path(destination)
    path.parent.mkdir(parents=True,exist_ok=True)
    parts=path.parent/(path.name+'.parts')
    parts.mkdir(exist_ok=True)
    block=8*1024*1024
    spans=[(start,min(start+block,SIZE)-1) for start in range(0,SIZE,block)]
    def fetch(span):
        start,end=span
        part=parts/str(start)
        if part.exists() and part.stat().st_size==end-start+1:
            return part
        for attempt in range(4):
            try:
                req=Request(URL+f'?range_start={start}',headers={'Range':f'bytes={start}-{end}'})
                with urlopen(req,timeout=40) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{SIZE}':
                        raise RuntimeError('Unexpected content range')
                    with part.open('wb') as output:
                        while chunk:=response.read(262144):
                            output.write(chunk)
                if part.stat().st_size!=end-start+1:
                    raise RuntimeError('Incomplete range')
                return part
            except Exception:
                if attempt==3: raise
                time.sleep(1+attempt)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(fetch,span) for span in spans]
        for n,future in enumerate(as_completed(futures),1):
            future.result()
            if n%5==0 or n==len(spans): print(f'Complete source blocks: {n}/{len(spans)}',flush=True)
    digest=hashlib.sha256()
    temp=path.with_suffix('.assembling')
    with temp.open('wb') as output:
        for start,end in spans:
            with (parts/str(start)).open('rb') as source:
                while chunk:=source.read(1024*1024):
                    output.write(chunk);digest.update(chunk)
    if digest.hexdigest()!=SHA256:
        raise RuntimeError('Source SHA-256 mismatch; refusing to publish download')
    temp.replace(path)
    print(json.dumps({'path':str(path),'bytes':path.stat().st_size,'sha256':digest.hexdigest(),'revision':REVISION}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--workers',type=int,default=8)
    a=p.parse_args();download(a.destination,a.workers)
