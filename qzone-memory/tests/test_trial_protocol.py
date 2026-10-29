import tempfile
import threading
import unittest
from qzone_memory.trial import run_trial, TrialLimits


class ImmediateStop(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class TrialProtocolTests(unittest.TestCase):
    def test_null_history_pagination_metadata_does_not_crash(self):
        class QQ:
            uin='123'
            token='test-token'
            def data(self,url,params):
                if 'emotion_cgi_msglist' in url:
                    return {'msglist':[],'total':0}
                if 'get_feeds' in url:
                    return {'data':{'vFeeds':[]}}
                return {'data':{'data':[],'main':None}}
        with tempfile.TemporaryDirectory() as root:
            output,report=run_trial(QQ(),root,ImmediateStop(),lambda *args:None,
                limits=TrialLimits(scan_seconds=10,total_seconds=20,requests=4,media=1))
            self.assertEqual(report['state'],'paused')
            self.assertNotIn('diagnostic',report)
            self.assertTrue(output.is_file())
