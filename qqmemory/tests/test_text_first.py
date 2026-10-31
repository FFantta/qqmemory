import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from qqmemory.storage import Archive
from qqmemory.deep_history import record, scan, persist, load_state
from qqmemory.history_details import enrich, pending_count
from qqmemory.timeline import timeline, clean_content
from qqmemory.trial import run_trial, TrialLimits
from test_trial_protocol import ImmediateStop


def card(tid='one'):
    return {'html': '<li class="f-single" id="fct_456_one" data-tid="'+tid+'" data-uin="123" data-appid="311" data-abstime="1500000000"><a class="f-name">好友</a><span class="state">赞了我的说说</span><p class="txt-box-title"><a class="nickname" link="nameCard_123">作者</a>：纯文字[em]e142[/em]</p><img src="https://a.qpic.cn/a"><div class="comments-item" data-uin="456"><div class="comments-content"><a class="nickname" link="nameCard_456">好友</a>：还记得</div></div></li>'}


class TextFirstTests(unittest.TestCase):
    def test_text_and_photo_identity_survive_deferred_details(self):
        full,_=record(card(),'123')
        fast,_=record(card(),'123',defer_social=True)
        for key in ('source_id','content','photos','author','interaction_time'):
            self.assertEqual(fast[key],full[key])
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            try:
                archive.ingest([fast])
                before=archive.db.execute('SELECT id FROM media').fetchone()[0]
                with patch('qqmemory.timeline.history_social',side_effect=AssertionError('must not eagerly enrich')):
                    rows=timeline(archive)['posts']
                self.assertEqual(rows[0]['content'],clean_content(full['content']))
                self.assertEqual(pending_count(archive),1)
                self.assertEqual(enrich(archive,lambda *_:None,lambda:None),0)
                result=json.loads(archive.db.execute('SELECT payload FROM evidence').fetchone()[0])
                self.assertEqual(result['comments'],full['comments'])
                self.assertEqual(result['likes'],full['likes'])
                self.assertEqual(archive.db.execute('SELECT id FROM media').fetchone()[0],before)
                self.assertNotIn('details_pending',result)
            finally:archive.close()

    def test_pending_details_resume_after_pause(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            try:
                archive.ingest([record(card(str(i)),'123',defer_social=True)[0] for i in range(3)])
                calls=[0]
                def check():
                    calls[0]+=1
                    if calls[0]>1:raise InterruptedError('pause')
                with self.assertRaises(InterruptedError):enrich(archive,lambda *_:None,check)
                self.assertEqual(pending_count(archive),2)
                self.assertEqual(enrich(archive,lambda *_:None,lambda:None),0)
                self.assertEqual(len(archive.posts()),3)
            finally:archive.close()

    def test_all_visible_text_is_saved_before_first_image_worker(self):
        calls=[]
        class QQ:
            uin='123';token='test'
            def data(self,url,params):
                if 'get_feeds' in url:return {'data':{'vFeeds':[]}}
                calls.append(('page',params['pos']))
                count=30 if params['pos']==0 else 1
                return {'total':31,'msglist':[{'tid':str(params['pos']+i),'uin':'123','content':'text','created_time':1500000000,'pic':[{'url1':'https://a.qpic.cn/a'}]} for i in range(count)]}
        def downloader(archive,mid,transport):
            self.assertEqual(archive.db.execute('SELECT count(*) FROM posts').fetchone()[0],31)
            calls.append(('image',mid));return False
        with tempfile.TemporaryDirectory() as root, patch('qqmemory.trial.download',side_effect=downloader):
            output,report=run_trial(QQ(),root,ImmediateStop(),lambda *_:None,backup_only=True,text_first=True,media_max_pending=1,media_workers=1,
                limits=TrialLimits(scan_seconds=30,total_seconds=60,requests=4,media=40))
            self.assertEqual(calls[:2],[('page',0),('page',30)])
            self.assertTrue(any(kind=='image' for kind,_ in calls))
            self.assertEqual(report['exported_posts'],31)
            self.assertEqual(report['state'],'completed')
            self.assertTrue(output.is_file())

    def test_covered_offset_task_skipped_but_different_scope_is_not(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            try:
                tasks=[dict(label='test',kind='feeds2',params=p,pages=1,sparse=False) for p in ({'offset':0},{'offset':0},{'offset':0,'scope':0},{'offset':0})]
                persist(archive,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None,go_order=True,text_first_order=True))
                calls=[]
                def request(url,params):
                    calls.append(params['scope']);return {'data':{'data':[card(str(i)) for i in range(100)],'main':{'hasMoreFeeds':False}}}
                scan(archive,SimpleNamespace(uin='123',token='test'),request,lambda rows,cursor:archive.ingest(rows),lambda *_:None,'job',text_first=True)
                self.assertEqual(calls,[1,0])
                self.assertEqual(load_state(archive)['skipped_covered_tasks'],2)
                self.assertTrue(load_state(archive)['complete'])
                self.assertEqual(load_state(archive)['duplicate_cards'],100)
                self.assertEqual(archive.db.execute('SELECT count(*) FROM posts').fetchone()[0],100)
            finally:archive.close()
