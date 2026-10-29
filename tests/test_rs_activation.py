"""Migration must reject incomplete/wrong-source indices and preserve rollback."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

spec=importlib.util.spec_from_file_location('activation',Path(__file__).resolve().parent.parent/'scripts'/'activate_rs_index.py')
if not spec.origin or not Path(spec.origin).exists():
    spec=importlib.util.spec_from_file_location('activation','/tmp/activate_rs_index.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class ActivationTests(unittest.TestCase):
    def setup_files(self,temp):
        root=Path(temp); active=root/'rajya_sabha';active.mkdir()
        (active/'manifest.json').write_text(json.dumps({'dataset':'rajanand/rajyasabha'}))
        stage=root/'rajya_sabha_hf';stage.mkdir()
        data=dict(dataset='anudit/rajyasabha-qa',status='ready',collection='hf',chunks=2,records=1,dataset_revision='pinned')
        (stage/'manifest.json').write_text(json.dumps(data))
        (stage/'records.jsonl').write_text(json.dumps({'question_id':'RS_267_1','date':'2025-04-04'}))
        return root,stage,data

    def client(self,count=2):
        client=Mock();client.count.return_value=NS(count=count)
        payload={'question_id':'RS_267_1','date':'2025-04-04','source':{'dataset_revision':'pinned','source_url':'https://huggingface.co/datasets/anudit/rajyasabha-qa/blob/pinned/source.parquet'}}
        client.scroll.return_value=([NS(payload=payload),NS(payload=payload)],None)
        return client

    def test_valid_activation_preserves_old_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root,stage,data=self.setup_files(temp)
            with patch.object(a,'DATA_DIR',root),patch.object(a,'QdrantClient',return_value=self.client()):
                a.activate(stage/'manifest.json')
            self.assertEqual(json.loads((root/'rajya_sabha'/'manifest.json').read_text())['dataset'],data['dataset'])
            self.assertEqual(len(list((root/'rajya_sabha').glob('manifest-before-hf-*.json'))),1)

    def test_count_mismatch_keeps_active_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root,stage,data=self.setup_files(temp)
            with patch.object(a,'DATA_DIR',root),patch.object(a,'QdrantClient',return_value=self.client(1)):
                with self.assertRaises(ValueError):a.activate(stage/'manifest.json')
            self.assertEqual(json.loads((root/'rajya_sabha'/'manifest.json').read_text())['dataset'],'rajanand/rajyasabha')

    def test_wrong_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root,stage,data=self.setup_files(temp); data['dataset']='other/source'
            (stage/'manifest.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):a.activate(stage/'manifest.json')

    def test_mixed_index_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root,stage,data=self.setup_files(temp)
            client=self.client()
            client.scroll.return_value[0][0].payload['source']['source_url']='https://www.kaggle.com/datasets/rajanand/rajyasabha'
            with patch.object(a,'DATA_DIR',root),patch.object(a,'QdrantClient',return_value=client):
                with self.assertRaises(ValueError):a.activate(stage/'manifest.json')

if __name__=='__main__':unittest.main()
