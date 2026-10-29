import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from qzone_memory.emoji import emoji_html, get_emoji


class EmojiTests(unittest.TestCase):
    def test_tokens_escaped_text_and_unicode(self):
        value = emoji_html('<script>x</script>🥹[em]e142[/em][em]e402399[/em]', lambda c:'assets/emoji/'+c+'.gif')
        self.assertIn('&lt;script&gt;',value)
        self.assertIn('🥹',value)
        self.assertEqual(value.count('class="qq-emoji"'),2)
        self.assertNotIn('[em]',value)
        self.assertIn('e402399.gif',value)

    def test_missing_asset_is_visible_and_paths_are_rejected(self):
        self.assertIn('〔表情〕', emoji_html('[em]e142[/em]',lambda _:None))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                get_emoji('../../private',root)

    def test_validated_cache_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            data=io.BytesIO()
            Image.new('RGB',(20,20),'yellow').save(data,format='GIF')
            response=MagicMock()
            response.__enter__.return_value=response
            response.status_code=200
            response.raw.read.return_value=data.getvalue()
            with patch('qzone_memory.emoji.requests.get',return_value=response) as request:
                first=get_emoji('e142',root)
                self.assertTrue(first.is_file())
                self.assertEqual(get_emoji('e142',root),first)
                self.assertEqual(request.call_count,1)

    def test_offline_export_copies_cached_emoji(self):
        from qzone_memory.storage import Archive
        from qzone_memory.exporting import export_archive
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'emojis').mkdir()
            Image.new('RGB',(24,24),'yellow').save(root/'emojis/e142.gif',format='GIF')
            archive=Archive(root/'archive')
            try:
                archive.ingest([dict(source='synthetic',record_key='one',source_id='one',content='你好[em]e142[/em]🥹',photos=[])])
                out=export_archive(archive,root/'export')
                page=(out/'index.html').read_text(encoding='utf-8')
                self.assertIn('assets/emoji/e142.gif',page)
                self.assertNotIn('[em]e142[/em]',page)
                self.assertTrue((out/'assets/emoji/e142.gif').is_file())
            finally:
                archive.close()
