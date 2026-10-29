import tempfile
import unittest
from qzone_memory.deep_history import record
from qzone_memory.storage import Archive
from qzone_memory.timeline import timeline

class ActivitiesTest(unittest.TestCase):
    def card(self, action, body, owner='123', comment=''):
        return {'html': f'<li class="f-single" id="fct_456_217_3_1400000000_1"><div class="f-nick"><a class="f-name" link="nameCard_456">好友</a><span class="state">{action}</span></div><i name="feed_data" data-uin="{owner}" data-tid="88" data-abstime="1400000000"></i><div class="f-single-content">{body}</div>{comment}</li>'}

    def test_blog_title_excerpt_and_category(self):
        card=self.card('赞了我的日志','<p class="txt-box-title"><a class="nickname" link="nameCard_123">我</a>的日志 <a>《旧时光》</a></p><p class="info">留存摘要</p>')
        item,_=record(card,'123')
        self.assertEqual(item['title'],'旧时光')
        self.assertIsNone(item['published_at'])
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            a.ingest([item,item])
            page=timeline(a,category='blogs')
            self.assertEqual(page['total'],1)
            self.assertEqual(page['posts'][0]['time_basis'],'interaction')
            self.assertIn('留存摘要',page['posts'][0]['content'])
            a.close()

    def test_game_and_gift(self):
        for action in ('邀请我一起玩 幻想之城','送我礼物'):
            item,_=record(self.card(action,'<p class="info">祝你毕业快乐</p>'),'123')
            self.assertEqual(item['category'],'gifts')
            self.assertEqual(item['author']['uin'],'456')

    def test_friend_blog_not_mine(self):
        item,_=record(self.card('赞了日志','<p class="txt-box-title"><a class="nickname" link="nameCard_456">好友</a>的日志《别人的》</p>',owner='456'),'123')
        self.assertIsNone(item)

    def test_friend_post_my_comment_preserves_mentions(self):
        comments='<li class="comments-item" data-uin="123" data-nick="我"><div class="comments-content"><a class="nickname" link="nameCard_123">我</a>: 回复<a class="nickname" link="nameCard_456">好友</a> 记得你<div class="comments-op">回复</div></div></li>'
        card=self.card('评论','<p class="txt-box-title"><a class="nickname" link="nameCard_456">好友</a>明天考试</p>',owner='456',comment=comments)
        item,_=record(card,'123')
        self.assertEqual(item['category'],'interactions')
        self.assertEqual(item['author']['uin'],'456')
        self.assertIn('@{uin:456',item['comments'][0]['content'])
        self.assertEqual(item['comments'][0]['reply_to']['uin'],'456')

    def test_official_birthday_notice(self):
        card=self.card('', '<p class="info">祝您生日快乐，赠送2次抽奖资格</p>')
        card['html']=card['html'].replace('好友</a>', '官方Qzone</a>')
        item,_=record(card,'123')
        self.assertEqual(item['category'],'gifts')
        self.assertEqual(item['title'],'官方祝福与礼物')

    def test_offline_export_keeps_categories_and_comments(self):
        import json
        from pathlib import Path
        from qzone_memory.exporting import export_archive
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root)/'account')
            item,_=record(self.card('送我礼物','<p class="info">毕业快乐</p>'),'123')
            item['comments']=[{'uin':'123','nickname':'我','content':'谢谢你','replies':[]}]
            # Structured social evidence also survives public JSON exports.
            item.pop('evidence_html')
            a.ingest([item])
            output=export_archive(a,Path(root)/'export')
            document=(output/'index.html').read_text(encoding='utf-8')
            self.assertIn('data-category="gifts"',document)
            self.assertIn('谢谢你',document)
            data=json.loads((output/'data.json').read_text(encoding='utf-8'))
            self.assertEqual(data['posts'][0]['category'],'gifts')
            self.assertEqual(data['posts'][0]['comments'][0]['uin'],'123')
            self.assertNotIn('evidence_html',data['posts'][0])
            a.close()
