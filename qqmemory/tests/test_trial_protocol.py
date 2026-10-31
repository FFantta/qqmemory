import tempfile
import threading
import unittest
from qqmemory.trial import run_trial, TrialLimits


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

    def test_earliest_publication_does_not_use_interaction_as_post_time(self):
        from qqmemory.storage import Archive
        from qqmemory.trial import archive_date_bounds
        from datetime import datetime
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            try:
                self.assertEqual(archive_date_bounds(archive),dict(earliest_published=None,earliest_interaction=None))
                def put(key,date=None,interaction=None):
                    archive.ingest([dict(source='synthetic',record_key=key,source_id=key,content='text',photos=[],published_at=date,interaction_time=interaction)])
                put('new','2020-01-01T00:00:00+00:00')
                put('unknown',interaction=1230768000)
                values=archive_date_bounds(archive)
                self.assertEqual(values['earliest_published'],1577836800)
                self.assertEqual(values['earliest_interaction'],1230768000)
                put('older','2019-01-01T08:00:00+08:00')
                self.assertEqual(archive_date_bounds(archive)['earliest_published'],1546300800)
                put('unknown','2008-01-01T00:00:00+00:00',1230768000)
                values=archive_date_bounds(archive)
                self.assertEqual(values['earliest_published'],1199145600)
                self.assertIsNone(values['earliest_interaction'])
            finally:archive.close()
