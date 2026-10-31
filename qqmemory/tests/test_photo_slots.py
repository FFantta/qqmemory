import json
import tempfile
import unittest
from qqmemory.storage import Archive

A='https://a.qpic.cn/psc?/first/m'
B='https://a.qpic.cn/psc?/second/m'

class PhotoSlotTests(unittest.TestCase):
    def test_partial_preview_cannot_replace_second_photo(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            a.ingest([dict(source='visible',record_key='v',source_id='post',content='post',photos=[[A],[B]])])
            a.ingest([dict(source='history',record_key='h',source_id='post',content='post',photos=[[A],[A]])])
            rows=list(a.db.execute('SELECT candidates FROM media ORDER BY position'))
            self.assertEqual([json.loads(r[0]) for r in rows],[[A],[B]])
            a.close()

    def test_partial_sources_align_by_identity_and_not_position(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            for key,photos in [('a',[[A]]),('b',[[B]]),('c',[[B],[A]])]:
                a.ingest([dict(source='history',record_key=key,source_id='post',content='post',photos=photos)])
            rows=list(a.db.execute('SELECT candidates FROM media ORDER BY position'))
            self.assertEqual([json.loads(r[0]) for r in rows],[[A],[B]])
            a.close()

    def test_legacy_contamination_is_backed_up_and_old_files_preserved(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            record=dict(source='visible',record_key='v',source_id='post',content='post',photos=[[A],[B]])
            a.ingest([record])
            old=Path(root)/'old.jpg';old.write_bytes(b'preserved')
            with a.db:
                a.db.execute("UPDATE media SET candidates=?,state='saved',local_path='old.jpg',sha256='old' WHERE position=1",(json.dumps([B,A]),))
            a.ingest([record])
            row=a.db.execute('SELECT * FROM media WHERE position=1').fetchone()
            self.assertEqual(json.loads(row['candidates']),[B])
            self.assertEqual(row['state'],'pending')
            self.assertEqual(old.read_bytes(),b'preserved')
            self.assertEqual(a.db.execute('SELECT count(*) FROM media_revisions').fetchone()[0],1)
            a.close()

    def test_identical_photos_explicitly_in_original_list_are_not_removed(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            a.ingest([dict(source='visible',record_key='v',source_id='post',content='post',photos=[[A],[A]])])
            self.assertEqual(a.db.execute('SELECT count(*) FROM media').fetchone()[0],2)
            a.close()
