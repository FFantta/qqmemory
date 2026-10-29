import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from qzone_memory.deep_history import plan, page_cards, record, scan, persist, load_state, ZONE
from qzone_memory.storage import Archive
from qzone_memory.online import ProtocolError


def card(tid='post',owner='123',ts=1500000000,extra=''):
    return {'html':f'<li class="f-single f-s-s" data-tid="{tid}" data-uin="{owner}" data-appid="311" data-abstime="{ts}"><a class="f-name" link="nameCard_456">好友</a><span class="state">赞了我的说说</span><p class="txt-box-title"><a class="nickname" link="nameCard_{owner}">作者</a>：旧内容{extra}</p></li>'}


class DeepHistoryTests(unittest.TestCase):
    def test_plan_covers_go_ranges_and_time_cursors(self):
        tasks=plan(now=datetime(2026,10,28,tzinfo=ZONE))
        offsets={t['params'].get('offset') for t in tasks}
        for offset in (700,2525,4550,5520,14980,25000):self.assertIn(offset,offsets)
        self.assertTrue(any(t['kind']=='feeds3' and t['label']=='时间游标 2013-01' for t in tasks))
        self.assertTrue(any(t['label']=='2014年上半年' and t['pages']==15 for t in tasks))
        self.assertTrue(any(t['params'].get('scope')==0 for t in tasks))
        self.assertTrue(any(t['params'].get('set')==3 for t in tasks))

    def test_envelopes_split_cards_and_reject_unknown(self):
        markup=card()['html']+card('other')['html']
        for data in ({'data':{'data':[None,card()],'main':{'hasMoreFeeds':False}}}, {'data':{'html':markup}}, {'data':[{'html':markup}]}):
            parsed,_=page_cards(data)
            self.assertTrue(parsed)
        self.assertEqual(len(page_cards({'data':{'html':markup}})[0]),2)
        for invalid in ({'unexpected':True},{'data':{}},{'data':'need login'}):
            with self.assertRaises(ProtocolError):page_cards(invalid)

    def test_owned_interactions_without_tid_are_kept_as_clues(self):
        c=card('',extra='@好友')
        parsed,reason=record(c,'123')
        self.assertEqual(reason,'activity_clue')
        self.assertIsNone(parsed['source_id'])
        self.assertIsNone(parsed['published_at'])
        self.assertEqual(parsed['interaction_time'],'1500000000')
        self.assertIsNone(record(card('','999'),'123')[0])
        self.assertIsNone(record({'html':'<li><p class="txt-box-title">朋友的内容</p></li>'},'123')[0])
        # Actor is someone else; the private notification wording proves target.
        c={'html':'<li id="activity-1"><span class="state">评论了我的说说</span><p class="txt-box-title">旧原文</p></li>'}
        self.assertEqual(record(c,'123')[0]['ownership_basis'],'my_mood_activity')
        a=record(c,'123')[0]
        c['html']=c['html'].replace('activity-1','activity-2')
        self.assertNotEqual(a['record_key'],record(c,'123')[0]['record_key'])

    def test_checkpoint_resumes_at_next_page_and_preserves_filtered_cursor(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                tasks=[dict(label='test',params={'offset':700},pages=5,kind='feeds2',sparse=True)]
                persist(a,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None))
                seen=[]
                def request(url,params):
                    seen.append(params['offset'])
                    if len(seen)>1:raise InterruptedError('pause')
                    return {'data':{'data':[card()],'main':{'hasMoreFeeds':True}}}
                def save(records,cursor):a.ingest(records)
                with self.assertRaises(InterruptedError):scan(a,SimpleNamespace(uin='123',token=1),request,save,lambda *_:None,'first')
                self.assertEqual(load_state(a)['next'],701)
                self.assertEqual(len(a.posts()),1)
                next_seen=[]
                def resumed(url,params):next_seen.append(params['offset']);return {'data':{'data':[]}}
                scan(a,SimpleNamespace(uin='123',token=1),resumed,save,lambda *_:None,'second')
                self.assertEqual(next_seen,[701])
                self.assertTrue(load_state(a)['complete'])
            finally:a.close()

    def test_feeds3_advances_from_raw_cards_even_if_ownership_rejects_them(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                tasks=[dict(label='cursor',params={'begintime':1600000000},pages=5,kind='feeds3',sparse=False)]
                persist(a,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None))
                seen=[]
                def request(url,params):
                    seen.append(params['begintime'])
                    return {'data':{'data':[card(owner='999')]}} if len(seen)==1 else {'data':{'data':[]}}
                scan(a,SimpleNamespace(uin='123',token=1),request,lambda records,cursor:a.ingest(records),lambda *_:None,'job')
                self.assertEqual(seen,[1600000000,1500000000])
                self.assertEqual(a.posts(),[])
                self.assertEqual(load_state(a)['rejected']['other_owner'],1)
            finally:a.close()

    def test_failed_page_keeps_cursor_and_replay_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                tasks=[dict(label='test',params={'offset':0},pages=1,kind='feeds2',sparse=False)]
                persist(a,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None))
                def save_then_crash(records,cursor):a.ingest(records);raise InterruptedError('after commit')
                request=lambda *_:{'data':{'data':[card()]}}
                with self.assertRaises(InterruptedError):scan(a,SimpleNamespace(uin='123',token=1),request,save_then_crash,lambda *_:None,'one')
                self.assertEqual(load_state(a)['index'],0)
                scan(a,SimpleNamespace(uin='123',token=1),request,lambda records,cursor:a.ingest(records),lambda *_:None,'two')
                self.assertEqual(len(a.posts()),1)
            finally:a.close()

    def test_full_deep_run_ingests_legacy_clues_and_exports(self):
        import threading
        from unittest.mock import patch
        from qzone_memory.trial import run_trial
        phrases=['RNG坐等3:1','牛顿死后，留下了一堆公式','祝大家新年快乐','刚买的手表打碎了']
        class Stop:
            def is_set(self):return False
            def wait(self,_):return False
        class QQ:
            uin='123'
            token=1
            def data(self,url,params):
                if 'emotion_cgi' in url:return {'msglist':[],'total':0}
                if 'get_feeds' in url:return {'data':{'vFeeds':[]}}
                return {'data':{'data':[{'html':'<li class="f-single" id="event-'+str(i)+'"><span class="state">赞了我的说说</span><p class="txt-box-title">'+phrase+'</p></li>','abstime':str(1377500000+i)} for i,phrase in enumerate(phrases)],'main':{'hasMoreFeeds':False}}}
        task=dict(label='test',params={'offset':0},pages=1,kind='feeds2',sparse=False)
        with tempfile.TemporaryDirectory() as root:
            with patch('qzone_memory.deep_history.plan',return_value=[task]):
                output,report=run_trial(QQ(),root,Stop(),lambda *_:None,deep=True)
            self.assertEqual(report['exported_posts'],4)
            self.assertEqual(report['raw_history_cards'],4)
            self.assertEqual(report['mode'],'deep')
            self.assertTrue(report['deep_scan']['complete'])
            page=output.read_text(encoding='utf-8')
            for phrase in phrases:self.assertIn(phrase,page)
            trace=json.loads(next((Path(root)/'123/evidence/deep').glob('*.json')).read_text(encoding='utf-8'))
            self.assertNotIn('g_tk',trace['params'])

    def test_api_accepts_deep_mode(self):
        from unittest.mock import patch
        from qzone_memory.mac_app import Controller,create_server
        with tempfile.TemporaryDirectory() as root:
            c=Controller(root)
            _,url,app=create_server(c,bind=False)
            prefix='/' + url.split('/')[-2]
            with patch.object(c,'start') as start:
                self.assertEqual(app.test_client().post(prefix+'/api/start',json={'workers':6,'mode':'deep'}).status_code,200)
                start.assert_called_once_with(6,mode='deep',intent='update')
            self.assertEqual(app.test_client().post(prefix+'/api/start',json={'mode':'invalid'}).status_code,400)

    def test_album_notifications_are_not_mood_records_and_cleanup_is_reversible(self):
        from qzone_memory.deep_history import quarantine_non_moods
        album='<li><div data-appid="4" data-tid="album"><p class="txt-box-title"><a class="nickname" link="nameCard_123">作者</a>的相册</p></div><span class="state">赞了</span><span class="state">的相册</span></li>'
        self.assertEqual(record({'html':album},'123'),(None,'other_app'))
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                a.ingest([dict(source='deep-history',record_key='bad',source_id='album',content='的相册',photos=[],evidence_html=album)])
                self.assertEqual(quarantine_non_moods(a),1)
                self.assertEqual(a.posts(),[])
                kept=json.loads(a.db.execute('select payload from quarantined_history').fetchone()[0])
                self.assertEqual(kept['post']['source_id'],'album')
                self.assertEqual(kept['evidence'][0]['source'],'deep-history')
            finally:a.close()

    def test_http_hole_is_saved_for_retry_and_next_segment_still_scans(self):
        import requests
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                tasks=[dict(label=str(n),params={'offset':n},pages=1,kind='feeds2',sparse=False) for n in (753,1000)]
                persist(a,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None))
                calls=[]
                def request(url,params):
                    calls.append(params['offset'])
                    if params['offset']==753:
                        response=requests.Response();response.status_code=502
                        raise requests.HTTPError(response=response)
                    return {'data':{'data':[card()]}}
                with self.assertRaises(ProtocolError):scan(a,SimpleNamespace(uin='123',token=1),request,lambda rows,cursor:a.ingest(rows),lambda *_:None,'test')
                self.assertIn(1000,calls)
                self.assertEqual(len(a.posts()),1)
                state=load_state(a)
                self.assertFalse(state['complete'])
                self.assertEqual(state['tasks'][0]['params']['offset'],753)
                self.assertEqual(state['last_error'][-1]['status'],502)
            finally:a.close()

    def test_online_update_requires_new_session_even_after_pause(self):
        from unittest.mock import patch,Mock
        from qzone_memory.mac_app import Controller
        with tempfile.TemporaryDirectory() as root:
            c=Controller(root)
            old=SimpleNamespace(uin='123',close=Mock());c.qq=old
            fresh=SimpleNamespace(uin='123',nickname='我的空间',close=Mock())
            report=dict(state='paused',exported_posts=4,exported_photos=0,issues=[])
            with patch('qzone_memory.mac_app.QQSession',return_value=fresh) as factory,patch('qzone_memory.mac_app.run_trial',return_value=(Path(root)/'export.html',report)):
                c.start(6,mode='deep');c.thread.join(timeout=2)
            self.assertFalse(c.active)
            old.close.assert_called_once()
            factory.assert_called_once()
            self.assertIs(c.qq,fresh)

    def test_relogin_discards_only_this_apps_in_memory_session(self):
        from unittest.mock import patch,Mock
        from qzone_memory.mac_app import Controller,create_server
        with tempfile.TemporaryDirectory() as root:
            c=Controller(root);qq=SimpleNamespace(close=Mock());c.qq=qq
            _,url,app=create_server(c,bind=False)
            prefix='/' + url.split('/')[-2]
            with patch.object(c,'start'):
                self.assertEqual(app.test_client().post(prefix+'/api/relogin',json={}).status_code,200)
            qq.close.assert_called_once()
            self.assertIsNone(c.qq)

    def test_generic_negative_code_is_not_assumed_to_be_expired_login(self):
        from qzone_memory.online import decode_response
        with tempfile.TemporaryDirectory() as root:
            a=Archive(root)
            try:
                tasks=[dict(label=str(n),params={'offset':n},pages=1,kind='feeds2',sparse=False) for n in (755,800)]
                persist(a,dict(tasks=tasks,index=0,page=0,next=None,requests=0,complete=False,rejected={},last_digest=None))
                seen=[]
                def request(url,params):
                    seen.append(params['offset'])
                    if params['offset']==755:return decode_response('{"code":-10001,"message":"获取失败"}')
                    return {'data':{'data':[card()]}}
                with self.assertRaises(ProtocolError):scan(a,SimpleNamespace(uin='123',token=1),request,lambda rows,cursor:a.ingest(rows),lambda *_:None,'negative')
                self.assertIn(800,seen)
                self.assertEqual(len(a.posts()),1)
                self.assertEqual(load_state(a)['last_error'][0]['code'],-10001)
            finally:a.close()

    def test_resume_skips_visible_backup_and_preserves_post_identity(self):
        from qzone_memory.trial import run_trial
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root)/'123')
            persist(a,dict(tasks=[dict(label='resume',params={'offset':1600},pages=1,kind='feeds2',sparse=False)],index=0,page=0,next=None,requests=1,complete=False,rejected={},last_digest=None))
            a.close()
            class Stop:
                def is_set(self):return False
                def wait(self,_):return False
                def set(self):pass
            class QQ:
                uin='123';token=1
                def data(self,url,params):
                    if 'emotion_cgi' in url or 'get_feeds' in url:raise AssertionError('resume must not redo visible pages')
                    return {'data':{'data':[]}}
            output,report=run_trial(QQ(),root,Stop(),lambda *_:None,deep=True)
            self.assertEqual(report['requests'],1)
            self.assertTrue(report['deep_scan']['complete'])
            self.assertTrue(output.exists())

    def test_friend_mentioning_me_is_preserved_with_real_author(self):
        c=card('friend-post',owner='999',extra='<a class="nickname" link="nameCard_123">@我</a>')
        parsed,reason=record(c,'123')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['source'],'related-history')
        self.assertEqual(parsed['author']['uin'],'999')
        self.assertEqual(parsed['source_id'],'friend-post')
        self.assertEqual(parsed['relation'],'mentioned')
        self.assertIn('@{uin:123,nick:我,who:1}',parsed['content'])
        self.assertIsNone(record(card('unrelated',owner='999'),'123')[0])

    def test_export_refreshes_after_new_archive_records(self):
        from unittest.mock import patch
        from qzone_memory.mac_app import Controller,create_server
        with tempfile.TemporaryDirectory() as root:
            a=Archive(Path(root)/'123')
            a.ingest([dict(source='test',record_key='new',source_id='new',content='新采集到的旧内容',photos=[])])
            a.close()
            c=Controller(root)
            c.output=Path(root)/'stale.html';c.output.write_text('旧导出', encoding='utf-8')
            _,url,app=create_server(c,bind=False)
            prefix='/' + url.split('/')[-2]
            with patch('qzone_memory.mac_app.webbrowser.open'):
                response=app.test_client().post(prefix+'/api/export',json={})
            self.assertEqual(response.status_code,200)
            self.assertNotEqual(c.output,Path(root)/'stale.html')
            self.assertIn('新采集到的旧内容',c.output.read_text(encoding='utf-8'))
