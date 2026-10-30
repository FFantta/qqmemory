import base64
import hashlib
import os
from pathlib import Path
import tempfile
import tracemalloc
import unittest
import zipfile
from qzone_memory.large_export import bundle_exports, standalone_html
from qzone_memory.parallel import MediaPipeline
from qzone_memory.storage import Archive
from qzone_memory.exporting import export_archive

class LargeExportTests(unittest.TestCase):
    def test_more_than_thousand_images_are_split_without_loss(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);source=root/'source';(source/'media').mkdir(parents=True)
            data=os.urandom(64*1024)
            first=source/'media/0.jpg';first.write_bytes(data)
            for i in range(1,1001):os.link(first,source/f'media/{i}.jpg')
            (source/'manifest.json').write_text('{}')
            index=source/'index.html';index.write_text('<!doctype html>'+''.join(f'<img src="media/{i}.jpg">' for i in range(1001)))
            tracemalloc.start()
            parts,inline=bundle_exports(index,root/'bundles',part_bytes=4*1024**2,single_html_bytes=1024)
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            self.assertFalse(inline)
            self.assertGreater(len(parts),1)
            self.assertLess(peak,24*1024**2)
            files=[]
            for part in parts:
                with zipfile.ZipFile(root/'bundles'/part['file']) as z:
                    self.assertIsNone(z.testzip())
                    files.extend(z.namelist())
            self.assertEqual(sum(p.endswith('.jpg') for p in files),1001)
            self.assertEqual(len(files),len(set(files)))
            self.assertIn('空间记忆/index.html',files)
            self.assertIn('空间记忆/其他/manifest.json',files)
            self.assertEqual({n.split('/')[1] for n in files},{'index.html','media','其他'})

    def test_base64_chunks_reassemble_exact_original(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);data=os.urandom(3*1024**2+17);(root/'a.jpg').write_bytes(data)
            source=root/'index.html';source.write_text('<img src="a.jpg">')
            standalone_html(source,root/'single.html')
            encoded=(root/'single.html').read_text().split('base64,',1)[1].split('"',1)[0]
            self.assertEqual(hashlib.sha256(base64.b64decode(encoded)).digest(),hashlib.sha256(data).digest())

    def test_bounded_pending_queue_and_compaction(self):
        pipeline=MediaPipeline(lambda mid:'saved',lambda *args:None,workers=2,limit=10000,max_pending=4)
        pipeline.enqueue(range(1200))
        self.assertLessEqual(len(pipeline.futures),5)
        self.assertEqual(pipeline.finish(),(1200,0,0))

    def test_cloud_export_repeated_media_uses_one_disk_file(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);archive=Archive(root/'123')
            try:
                archive.ingest([dict(source='test',record_key=str(i),source_id=str(i),content='record',photos=[['https://a.qpic.cn/'+str(i)]]) for i in range(2)])
                data=b'checked immutable bytes';digest=hashlib.sha256(data).hexdigest()
                source=archive.root/'media/test.jpg';source.parent.mkdir(exist_ok=True);source.write_bytes(data)
                with archive.db:archive.db.execute("UPDATE media SET state='saved',local_path='media/test.jpg',sha256=?",(digest,))
                result=export_archive(archive,root/'export',link_media=True)
                self.assertEqual((result/'media/test.jpg').stat().st_ino,source.stat().st_ino)
                self.assertEqual((result/'index.html').read_text().count('src="media/test.jpg"'),2)
            finally:archive.close()
