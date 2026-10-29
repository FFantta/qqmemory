import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from qzone_memory.storage import Archive
from qzone_memory.parsing import images_from_html, unwrap_jsonp
from qzone_memory.media import download, fetch, validate_image
from qzone_memory.exporting import export_archive


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = Archive(self.root / 'archive')

    def tearDown(self):
        self.archive.close()
        self.tmp.cleanup()

    def record(self, key='1', **changes):
        value = dict(source='fixture', record_key=key, source_id=key,
                     content='同样的正文', photos=[])
        value.update(changes)
        return value

    def test_identity_and_replay(self):
        self.archive.ingest([self.record(), self.record('2')])
        self.archive.ingest([self.record(source='other', content='同样的正文，完整版本')])
        posts = self.archive.posts()
        self.assertEqual(len(posts), 2)
        self.assertTrue(any(p['content'].endswith('完整版本') for p in posts))
        self.assertTrue(all(p['published_at'] is None for p in posts))

    def test_unknown_ids_not_merged_by_text(self):
        self.archive.ingest([self.record(source_id=None), self.record('2', source_id=None)])
        self.assertEqual(len(self.archive.posts()), 2)

    def test_lazy_nine_photos(self):
        photos = images_from_html(''.join(f'<img src="/ac/b.gif" trueSrc="https://a.qpic.cn/{i}" data-src="https://a.qpic.cn/small/{i}">' for i in range(9)))
        self.archive.ingest([self.record(photos=photos)])
        self.assertEqual(len(self.archive.posts()[0]['media']), 9)
        self.assertEqual(len(photos[0]), 2)

    def test_jsonp_error_not_executed(self):
        self.assertEqual(unwrap_jsonp('cb({"code":-3});')['code'], -3)
        with self.assertRaises(ValueError):
            unwrap_jsonp('alert(1);cb({})')

    def test_atomic_checkpoint_and_restart(self):
        key = self.archive.create_job()
        self.archive.transition(key, 'running')
        with self.assertRaises(ValueError):
            self.archive.ingest([self.record(), self.record('2', published_at='invalid')], key, 1)
        self.assertEqual(self.archive.posts(), [])
        self.archive.ingest([self.record()], key, 1)
        self.archive.close()
        self.archive = Archive(self.root / 'archive')
        self.assertEqual(self.archive.recover_jobs(), 1)
        self.assertEqual(self.archive.db.execute('SELECT cursor FROM jobs').fetchone()[0], '1')
        self.assertEqual(len(self.archive.posts()), 1)
        self.archive.transition(key, 'running')
        self.archive.ingest([self.record()], key, 2)
        self.assertEqual(len(self.archive.posts()), 1)

    def test_media_fallback_cache_and_export(self):
        self.archive.ingest([self.record(content='<script>alert(1)</script>', photos=[['https://a.qpic.cn/bad','https://a.qpic.cn/good']])])
        stream = io.BytesIO()
        Image.new('RGB', (3, 3), 'red').save(stream, format='PNG')
        calls = []
        def transport(url):
            calls.append(url)
            return b'<html>login</html>' if url.endswith('bad') else stream.getvalue()
        mid = self.archive.posts()[0]['media'][0]['id']
        path = download(self.archive, mid, transport)
        self.assertEqual(len(calls), 2)
        self.assertTrue(path)
        self.assertEqual(download(self.archive, mid, lambda _: self.fail('cache requested network')), path)
        out = export_archive(self.archive, self.root / 'export')
        document = (out / 'index.html').read_text()
        self.assertIn('&lt;script&gt;', document)
        self.assertTrue((out / path).is_file())
        self.assertNotIn('qpic.cn', (out / 'data.json').read_text())

    def test_failed_media_preserves_candidates(self):
        self.archive.ingest([self.record(photos=[['https://a.qpic.cn/bad']])])
        mid = self.archive.posts()[0]['media'][0]['id']
        self.assertIsNone(download(self.archive, mid, lambda _: b'not image'))
        media = self.archive.posts()[0]['media'][0]
        self.assertEqual(media['state'], 'failed')
        self.assertEqual(len(media['candidates']), 1)
        self.assertIsNone(media['local_path'])

    def test_origin_policy(self):
        for url in ['https://evil.example/a', 'https://a.qpic.cn.evil.example/a', 'http://a.qpic.cn/a']:
            with self.assertRaises(ValueError):
                fetch(url)

    def test_partial_export_nine_slots(self):
        self.archive.ingest([self.record(photos=[[f'https://a.qpic.cn/{i}'] for i in range(9)])])
        out = export_archive(self.archive, self.root / 'partial')
        self.assertEqual((out / 'index.html').read_text().count('<span>图片尚未保存</span>'), 9)
        self.assertEqual(len(json.loads((out / 'report.json').read_text())), 9)
        with self.assertRaises(FileExistsError):
            export_archive(self.archive, out)


if __name__ == '__main__':
    unittest.main()

class HistoryTimeTests(unittest.TestCase):
    def test_export_labels_interaction_without_inventing_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Archive(Path(directory)/'archive')
            try:
                archive.ingest([dict(source='history', record_key='h', source_id='h', content='old', photos=[], interaction_time='1451606400')])
                out = export_archive(archive, Path(directory)/'export')
                document = (out/'index.html').read_text()
                self.assertIn('2016年01月01日 08:00 · ≈ 最早互动', document)
                self.assertIsNone(archive.posts()[0]['published_at'])
            finally:
                archive.close()
