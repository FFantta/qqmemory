import tempfile
import unittest
from pathlib import Path
from qzone_memory.richtext import tokens, rich_html, person_html
from qzone_memory.storage import Archive
from qzone_memory.timeline import timeline
from qzone_memory.exporting import export_archive


class RichTextTests(unittest.TestCase):
    def test_adjacent_mentions_emoji_and_comma_in_nickname(self):
        parsed=tokens('@{uin:123456,nick:Fr.Z,who:1}@{uin:456789,nick:乙,甲,who:1} 真活虾[em]e142[/em]👏')
        self.assertEqual(parsed[0],dict(type='mention',uin='123456',nickname='Fr.Z'))
        self.assertEqual(parsed[1]['nickname'],'乙,甲')
        self.assertEqual(parsed[-2],dict(type='emoji',code='e142'))
        self.assertEqual(parsed[-1]['text'],'👏')

    def test_escape_and_malformed_token(self):
        out=rich_html('@{uin:123456,nick:<script>x</script>,who:1}',lambda _:None)
        self.assertIn('title="QQ：123456"',out)
        self.assertIn('@&lt;script&gt;',out)
        self.assertNotIn('<script>',out)
        self.assertEqual(tokens('@{uin:bad,nick:人,who:1}')[0]['type'],'text')
        self.assertIn('QQ号未取得',person_html(dict(nickname='人')))

    def test_timeline_and_offline_export_keep_qq_identity(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root)/'123456')
            try:
                a.ingest([dict(source='test',record_key='a',source_id='a',content='@{uin:234567,nick:好友,who:1}',photos=[],likes=[dict(uin='345678',nickname='点赞人')],comments=[dict(uin='456789',nickname='评论人',content='@{uin:234567,nick:好友,who:1}',replies=[])])])
                post=timeline(a)['posts'][0]
                self.assertEqual(post['content_tokens'][0]['uin'],'234567')
                self.assertEqual(post['comments'][0]['content_tokens'][0]['type'],'mention')
                page=(export_archive(a,Path(root)/'export')/'index.html').read_text()
                self.assertNotIn('@{uin:',page)
                for uin in ('234567','345678','456789'):self.assertIn('title="QQ：'+uin+'"',page)
            finally:a.close()
