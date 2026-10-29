"""Deduplication preserves distinct events and all questioners; FTS stays safe."""
import contextlib,csv,importlib.util,io,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from lok_sabha_rag.core import kaggle_store as k
spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build_kaggle_catalog.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class CatalogueTests(unittest.TestCase):
    def test_canonical_ignores_source_ids_but_preserves_date_and_type(self):
        row={'date':'2017-08-11','type':'UNSTARRED','ques_no':1}
        self.assertEqual(k.stable_id(row),k.stable_id({**row,'source_record_id':999}))
        self.assertNotEqual(k.stable_id(row),k.stable_id({**row,'date':'2017-08-10'}))
        self.assertNotEqual(k.stable_id(row),k.stable_id({**row,'type':'STARRED'}))

    def test_dedup_overlap_fts_and_authors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';source.mkdir();out=root/'rajya_sabha_kaggle'
            (source/'rajyasabha_session.csv').write_text('session_no,session_start_date,session_end_date\n243,2017-07-17,2017-08-11\n')
            fields=['id','answer_date','ministry','question_type','question_no','question_by','question_title','question_description','answer']
            row=dict(id='1',answer_date='11.08.2017',ministry='RAILWAYS',question_type='UNSTARRED',question_no='1',question_by='A',question_title='Railway safety',question_description='What are the railway safety measures?',answer='Government describes railway safety measures and the available evidence.')
            rows=[row,{**row,'id':'2','question_by':'B'}, {**row,'id':'3','answer_date':'10.08.2017'}, {**row,'id':'4','question_no':'2'}, {**row,'id':'5','question_no':'3','answer':''}]
            with (source/'rajyasabha_questions_and_answers_2017.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            hf=root/'hf.jsonl';hf.write_text(json.dumps({'house':'rajya_sabha','date':'2017-08-11','type':'UNSTARRED','ques_no':2}))
            with contextlib.redirect_stdout(io.StringIO()):b.build(source,out,hf)
            manifest=json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['records'],2)
            self.assertEqual(manifest['audit']['duplicate_rows'],1)
            self.assertEqual(manifest['audit']['overlap_with_active_hf'],1)
            with patch.object(k,'DATA_DIR',root):
                found=k.search('railway safety',limit=10)
                self.assertEqual(len(found),2)
                self.assertEqual(sorted(next(x for x in found if x['date']=='2017-08-11')['mp_names']),['A','B'])
                self.assertEqual(len(k.search('railway',ministry='RAILWAYS',mp_names=['B'])),1)
                k.search('" OR 1=1; DROP TABLE records; --',limit=1)
                self.assertEqual(len(k.search('railway safety',limit=10)),2)

if __name__=='__main__':unittest.main()
