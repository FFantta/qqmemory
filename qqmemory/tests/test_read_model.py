import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from qqmemory.storage import Archive
from qqmemory.read_model import ArchiveView, normalize_social
from qqmemory.timeline import timeline
from qqmemory.thumbnails import thumbnail


def post(key, **values):
    return dict(source='visible', record_key=key, source_id=key, content=key,
                photos=[], **values)


class ReadModelTests(unittest.TestCase):
    def test_filters_share_one_snapshot_and_external_writes_invalidate(self):
        with tempfile.TemporaryDirectory() as root:
            archive = Archive(root)
            archive.ingest([post('one', category='blogs', interaction_time=1400000000), post('two')])
            view = ArchiveView()
            with patch('qqmemory.read_model.timeline', wraps=timeline) as build:
                self.assertEqual(view.page(archive)['total'], 2)
                self.assertEqual(view.page(archive, category='blogs')['total'], 1)
                self.assertEqual(view.page(archive, search='two')['total'], 1)
                self.assertEqual(view.page(archive, year='2014')['total'], 1)
                self.assertEqual(build.call_count, 1)
                writer = Archive(root)
                writer.ingest([post('three')])
                writer.close()
                self.assertEqual(view.page(archive)['total'], 3)
                self.assertEqual(build.call_count, 2)
            archive.close()

    def test_cache_does_not_mix_accounts(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Archive(Path(root)/'1'), Archive(Path(root)/'2')
            a.ingest([post('first')]); b.ingest([post('second')])
            view = ArchiveView()
            self.assertEqual(view.page(a)['posts'][0]['content'], 'first')
            self.assertEqual(view.page(b)['posts'][0]['content'], 'second')
            a.close(); b.close()

    def test_parser_migration_runs_once_and_preserves_raw_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            archive = Archive(root)
            html = '<span class="state">赞</span><a class="f-name">好友</a>'
            archive.ingest([post('old', evidence_html=html)])
            self.assertEqual(normalize_social(archive), 1)
            self.assertEqual(normalize_social(archive), 0)
            import json
            record = json.loads(archive.db.execute('SELECT payload FROM evidence').fetchone()[0])
            self.assertEqual(record['evidence_html'], html)
            self.assertEqual(record['social_version'], 2)
            archive.close()

    def test_thumbnail_is_small_cached_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)/'original.png'
            Image.new('RGBA', (2400, 1200), (210, 100, 80, 255)).save(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = thumbnail(source, digest, Path(root)/'thumbs')
            with Image.open(target) as image:
                self.assertEqual(image.size, (768, 384))
            with patch('qqmemory.thumbnails.Image.open', side_effect=AssertionError('must reuse thumbnail')):
                self.assertEqual(thumbnail(source, digest, Path(root)/'thumbs'), target)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_thumbnail_endpoint_and_original_have_separate_cache_urls(self):
        from qqmemory.mac_app import Controller,create_server
        import io
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root)/'123')
            a.ingest([dict(source='visible',record_key='v',source_id='p',content='post',photos=[['https://a.qpic.cn/image']])])
            source=a.root/'media/photo.png';source.parent.mkdir();Image.new('RGB',(1600,900),'red').save(source)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            mid=a.db.execute('SELECT id FROM media').fetchone()[0]
            with a.db:
                a.db.execute("UPDATE media SET state='saved',local_path='media/photo.png',sha256=? WHERE id=?",(digest,mid))
            a.close()
            controller=Controller(root)
            _,url,app=create_server(controller,bind=False)
            prefix='/' + url.split('/')[-2]
            client=app.test_client()
            preview=client.get(prefix+'/media/'+mid+'?v='+digest+'&thumb=1')
            original=client.get(prefix+'/media/'+mid+'?v='+digest)
            self.assertIn('immutable',preview.headers['Cache-Control'])
            with Image.open(io.BytesIO(preview.data)) as img:self.assertEqual(img.size,(768,432))
            with Image.open(io.BytesIO(original.data)) as img:self.assertEqual(img.size,(1600,900))
            self.assertEqual(hashlib.sha256(original.data).hexdigest(),digest)
            self.assertIn('no-store',client.get(prefix+'/api/state').headers['Cache-Control'])
            preview.close(); original.close()
