import json
import tempfile
import threading
import unittest
from pathlib import Path
from qqmemory.online import decode_response, history_record, mood_record, ProtocolError, hash33
from qqmemory.trial import run_trial


class OnlineTests(unittest.TestCase):
    def test_js_envelope(self):
        value = decode_response("_Callback({code:0,data:{data:[], main:{hasMoreFeeds:false}},optional:undefined,label:'undefined'})")
        self.assertIsNone(value['optional'])
        self.assertEqual(value['label'], 'undefined')
        with self.assertRaises(ProtocolError):
            decode_response('callback({code:-3})')
        with self.assertRaises(ProtocolError):
            decode_response('<html>login</html>')

    def test_ownership_and_unknown_publication(self):
        card = {'html': '<div data-uin="123" data-tid="abc" data-appid="311" data-abstime="1700000000"><p class="txt-box-title">旧内容</p></div>'}
        self.assertIsNone(history_record(card, '456'))
        post = history_record(card, '123')
        self.assertIsNone(post['published_at'])
        self.assertEqual(post['content'], '旧内容')
        self.assertEqual(post['source_id'], 'abc')

    def test_visible_photos(self):
        post = mood_record({'tid': 'a', 'pic': [{'url1': 'https://a.qpic.cn/a', 'url2': 'https://a.qpic.cn/b'}]})
        self.assertEqual(len(post['photos']), 1)
        self.assertEqual(len(post['photos'][0]), 2)
        self.assertEqual(hash33('a'), 97)

    def test_trial_stopped_still_exports(self):
        class QQ:
            uin = '123'
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            stop.set()
            path, report = run_trial(QQ(), directory, stop, lambda *args: None)
            self.assertTrue(path.is_file())
            self.assertEqual(report['state'], 'paused')
            self.assertEqual(json.loads((path.parent/'manifest.json').read_text(encoding='utf-8'))['posts'], 0)

class LoginRedirectTests(unittest.TestCase):
    def test_http_qq_landing_is_upgraded_before_request(self):
        from qqmemory.online import QQSession
        from unittest.mock import Mock
        qq = QQSession()
        response = Mock()
        response.is_redirect = False
        response.iter_content.return_value = [b'ok']
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        qq.session.get = Mock(return_value=response)
        self.assertEqual(qq.get('http://user.qzone.qq.com/'), b'ok')
        self.assertEqual(qq.session.get.call_args.args[0], 'https://user.qzone.qq.com/')
        with self.assertRaises(ProtocolError):
            qq.get('http://qq.com.evil.example/')
        self.assertEqual(qq.session.get.call_count, 1)
        qq.close()

class DecorativeImageTests(unittest.TestCase):
    def test_body_images_exclude_avatar_and_decoration_hosts(self):
        from qqmemory.parsing import images_from_html
        self.assertEqual(images_from_html('<img src="https://qlogo1.store.qq.com/a"><img src="https://qzonestyle.gtimg.cn/a"><img src="https://a.qpic.cn/photo">'), [['https://a.qpic.cn/photo']])

class ResponseFailureTests(unittest.TestCase):
    def test_json_jsonp_and_undefined_are_supported_without_changing_string_values(self):
        for body in ('{"code":0,"total":0,"msglist":[]}', '_preloadCallback({"code":0,"total":0,"msglist":[]});'):
            self.assertEqual(decode_response(body)['msglist'],[])
        self.assertEqual(decode_response('cb({code:0,missing:undefined,text:"undefined"})')['text'],'undefined')
        with self.assertRaises(ProtocolError):
            decode_response('cb({invalid: malformed})')

    def test_unexpected_failure_keeps_safe_locations_without_credentials(self):
        import struct
        class QQ:
            uin='123'
            token='secret-not-to-log'
            def data(self,*args):raise struct.error('secret-response-not-to-log')
        class Stop:
            def is_set(self):return False
            def wait(self,n):return False
            def set(self):pass
        with tempfile.TemporaryDirectory() as root:
            path,report=run_trial(QQ(),root,Stop(),lambda *args:None)
            diagnostic=(Path(root)/'123'/'last-error.json').read_text(encoding='utf-8')
            self.assertIn('struct.error',diagnostic)
            self.assertIn('function',diagnostic)
            self.assertNotIn('secret',diagnostic)
            self.assertNotIn('secret',str(report))
            self.assertEqual(report['state'],'failed')
            self.assertTrue(path.is_file())

class CancellationTests(unittest.TestCase):
    def test_cancel_during_redirect_does_not_make_next_request(self):
        from qqmemory.online import QQSession
        from qqmemory.trial import Stopped
        from unittest.mock import Mock
        qq=QQSession()
        stop=threading.Event()
        def check():
            if stop.is_set():raise Stopped()
        qq.cancel_check=check
        response=Mock()
        response.is_redirect=True
        response.url='https://user.qzone.qq.com/'
        response.headers={'Location':'https://user.qzone.qq.com/next'}
        response.__enter__=Mock(side_effect=lambda:(stop.set(),response)[1])
        response.__exit__=Mock(return_value=False)
        qq.session.get=Mock(return_value=response)
        try:
            with self.assertRaises(Stopped):qq.get('https://user.qzone.qq.com/')
            self.assertEqual(qq.session.get.call_count,1)
        finally:qq.close()
