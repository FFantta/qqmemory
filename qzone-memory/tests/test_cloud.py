import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from qzone_memory.cloud_app import CloudService, create_cloud_app, standalone_html

SECRET = 'test-secret-which-is-at-least-thirty-two-characters'


class FakeQQ:
    def __init__(self):
        self.uin = None
        self.closed = False

    def qr(self):
        return b'test-qr'

    def poll(self):
        self.uin = '123'
        return 'ok'

    def close(self):
        self.closed = True


def fake_runner(qq, root, stop, notify, **kwargs):
    output = Path(root)/'exports'/('test-'+str(len(list((Path(root)/'exports').glob('*')))))
    (output/'media').mkdir(parents=True)
    (output/'media/a.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=='))
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><p>&lt;script&gt;private&lt;/script&gt;</p><img src="media/a.png">', encoding='utf-8')
    return output/'index.html', dict(state='completed',exported_posts=1,exported_photos=1,requests=1)


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.qq = []
        def factory():
            qq = FakeQQ()
            self.qq.append(qq)
            return qq
        self.service = CloudService(self.temp.name,SECRET,qq_factory=factory,runner=fake_runner,poll_seconds=.001)
        self.app = create_cloud_app(secret=SECRET,service=self.service,testing=True,cleaner=False)
        self.client = self.app.test_client()
        self.csrf = self.client.get('/api/session').json['csrf']
        self.headers = {'Origin':'http://localhost','X-CSRF-Token':self.csrf}

    def tearDown(self):
        for job in list(self.service.jobs.values()):
            job.stop.set()
            if job.thread:
                job.thread.join(3)
        self.temp.cleanup()

    def create(self):
        response = self.client.post('/api/jobs',json={'consent':True},headers=self.headers)
        self.assertEqual(response.status_code,201)
        job = self.service.jobs[response.json['id']]
        job.thread.join(3)
        self.assertFalse(job.active)
        return job

    def test_result_download_isolated_and_session_closed(self):
        job = self.create()
        self.assertTrue(self.qq[0].closed)
        state = self.client.get('/api/jobs/'+job.id).json
        self.assertTrue(state['ready'])
        self.assertIsNone(state['qr'])
        other = self.app.test_client()
        self.assertEqual(other.get('/api/jobs/'+job.id).status_code,404)
        self.assertEqual(other.get('/jobs/'+job.id+'/download/html').status_code,404)
        response = self.client.get('/jobs/'+job.id+'/download/html')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'data:image/png;base64,',response.data)
        self.assertNotIn(b'<script>private',response.data)
        response.close()
        zipped = self.client.get('/jobs/'+job.id+'/download/zip')
        self.assertEqual(zipped.status_code,200)
        self.assertTrue(zipped.data.startswith(b'PK'))
        zipped.close()
        self.assertEqual(self.client.get('/jobs/'+job.id+'/preview/../../job.json').status_code,404)
        self.assertEqual(self.client.get('/jobs/'+job.id+'/preview/report.json').status_code,404)

    def test_live_counts_visible_before_export(self):
        entered, release = threading.Event(), threading.Event()
        def runner(qq,root,stop,notify,**kwargs):
            notify('counts',dict(posts=68,photos_found=350,photos_saved=120,photos_failed=2,requests=9,earliest_published=1577836800,earliest_interaction=1230768000))
            notify('progress',dict(stage='deep',done=10,total=100))
            entered.set()
            release.wait(2)
            return fake_runner(qq,root,stop,notify,**kwargs)
        self.service.runner=runner
        response=self.client.post('/api/jobs',json={'consent':True},headers=self.headers)
        try:
            self.assertTrue(entered.wait(2))
            state=self.client.get('/api/jobs/'+response.json['id']).json
            self.assertTrue(state['active'])
            self.assertFalse(state['ready'])
            self.assertEqual(state['counts']['photos_saved'],120)
            self.assertEqual(state['counts']['posts'],68)
            self.assertEqual(state['counts']['earliest_published'],1577836800)
            self.assertEqual(state['counts']['earliest_interaction'],1230768000)
            self.assertEqual(state['progress']['percent'],10)
            self.assertIsNotNone(state['collection_elapsed'])
            self.assertEqual(state['collection_limit'],1800)
        finally:
            release.set()

    def test_pause_acknowledged_during_inflight_work_and_exports(self):
        entered, release = threading.Event(), threading.Event()
        def runner(qq,root,stop,notify,**kwargs):
            entered.set()
            release.wait(2)
            self.assertTrue(stop.is_set())
            return fake_runner(qq,root,stop,notify,**kwargs)
        self.service.runner=runner
        response=self.client.post('/api/jobs',json={'consent':True},headers=self.headers)
        identifier=response.json['id']
        try:
            self.assertTrue(entered.wait(2))
            stopped=self.client.post('/api/jobs/'+identifier+'/stop',json={},headers=self.headers)
            self.assertEqual(stopped.json['phase'],'stopping')
            self.assertTrue(stopped.json['active'])
            job=self.service.jobs[identifier]
            job.notify('status','深度找回：旧请求返回')
            state=self.client.get('/api/jobs/'+identifier).json
            self.assertEqual(state['phase'],'stopping')
            self.assertIn('已收到暂停请求',state['message'])
        finally:
            release.set()
        job.thread.join(3)
        self.assertTrue(job.state()['ready'])
        self.assertFalse(job.state()['active'])

    def test_csrf_origin_and_consent(self):
        self.assertEqual(self.client.post('/api/jobs',json={'consent':True}).status_code,403)
        self.assertEqual(self.client.post('/api/jobs',json={'consent':True},headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/jobs',json={},headers=self.headers).status_code,400)
        cookie = self.client.get('/api/session').headers.get('Cache-Control')
        self.assertIn('no-store',cookie)

    def test_expiration_and_explicit_deletion(self):
        job = self.create()
        response = self.client.delete('/api/jobs/'+job.id,json={},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertFalse(job.root.exists())
        self.assertEqual(self.client.get('/api/jobs/'+job.id).status_code,404)
        job = self.create()
        job.expires = time.time()-1
        self.service.cleanup()
        self.assertFalse(job.root.exists())

    def test_restart_restores_results_but_not_qq_sessions(self):
        job = self.create()
        restored = CloudService(self.temp.name,SECRET)
        self.assertTrue(restored.jobs[job.id].output.is_file())
        self.assertFalse(restored.jobs[job.id].active)
        self.assertIsNone(restored.jobs[job.id].qr)
        manifest = (job.root/'job.json').read_text(encoding='utf-8')
        self.assertNotIn('cookie',manifest.lower())
        self.assertNotIn('qrsig',manifest)

    def test_download_budget_survives_restart(self):
        job = self.create()
        self.service.monthly_bytes = 1
        self.assertEqual(self.client.get('/jobs/'+job.id+'/download/html').status_code,429)
        month = time.strftime('%Y-%m',time.gmtime())
        self.assertTrue(self.service.allowance('bytes',100,100,month))
        restored = CloudService(self.temp.name,SECRET)
        self.assertFalse(restored.allowance('bytes',1,100,month))

    def test_quotas_can_persist_separately_from_private_results(self):
        root = Path(self.temp.name)
        usage = root/'quota-volume'/'usage.sqlite3'
        first = CloudService(root/'ephemeral-a',SECRET,usage_path=usage)
        self.assertTrue(first.allowance('jobs',1,1,'day'))
        second = CloudService(root/'ephemeral-b',SECRET,usage_path=usage)
        self.assertFalse(second.allowance('jobs',1,1,'day'))
        self.assertEqual(list(usage.parent.iterdir()),[usage])
        self.assertEqual(second.jobs,{})

    def test_busy_service_rejects_second_session(self):
        gate = threading.Event()
        def runner(*args,**kwargs):
            gate.wait(2)
            return fake_runner(*args,**kwargs)
        self.service.runner = runner
        response = self.client.post('/api/jobs',json={'consent':True},headers=self.headers)
        other = self.app.test_client()
        csrf = other.get('/api/session').json['csrf']
        try:
            self.assertEqual(other.post('/api/jobs',json={'consent':True},headers={'Origin':'http://localhost','X-CSRF-Token':csrf}).status_code,429)
        finally:
            gate.set()
            self.service.jobs[response.json['id']].thread.join(3)

    def test_no_arbitrary_export_resources(self):
        root = Path(self.temp.name)
        (root/'secret.png').write_bytes(b'private')
        (root/'result').mkdir()
        source = root/'result/index.html'
        source.write_text('<img src="../secret.png">', encoding='utf-8')
        with self.assertRaises(ValueError):
            standalone_html(source,root/'result.html')

    def test_refresh_replaces_challenge_and_failed_login_can_retry(self):
        class Waiting(FakeQQ):
            def poll(self):
                return '66'
        def factory():
            qq = Waiting()
            self.qq.append(qq)
            return qq
        self.service.qq_factory = factory
        response = self.client.post('/api/jobs',json={'consent':True},headers=self.headers)
        job = self.service.jobs[response.json['id']]
        deadline = time.monotonic()+2
        while not job.qr and time.monotonic()<deadline:
            time.sleep(.005)
        first = self.qq[0]
        other = self.app.test_client()
        csrf = other.get('/api/session').json['csrf']
        url = '/api/jobs/'+job.id+'/refresh'
        self.assertEqual(other.post(url,json={},headers={'Origin':'http://localhost','X-CSRF-Token':csrf}).status_code,404)
        self.assertEqual(self.client.post(url,json={}).status_code,403)
        self.assertEqual(self.client.post(url,json={},headers=self.headers).status_code,200)
        deadline = time.monotonic()+2
        while len(self.qq)<2 and time.monotonic()<deadline:
            time.sleep(.005)
        self.assertEqual(len(self.qq),2)
        self.assertTrue(first.closed)
        job.stop.set();job.thread.join(3)
        self.assertEqual(job.phase,'cancelled')
        response = self.client.post(url,json={},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['id'],job.id)
        job.stop.set();job.thread.join(3)
        job.qr_refreshes=5
        self.assertEqual(self.client.post(url,json={},headers=self.headers).status_code,409)

    def test_result_refresh_rejected_and_failure_not_presented_as_budget(self):
        def runner(*args,**kwargs):
            output, report = fake_runner(*args,**kwargs)
            report.update(state='failed',diagnostic={'exception':'builtins.AttributeError','frames':[{'file':'trial.py','line':1,'function':'history'}]})
            return output,report
        self.service.runner=runner
        job=self.create()
        self.assertEqual(job.phase,'partial')
        self.assertIn('异常',job.message)
        self.assertEqual(job.stats['scan_state'],'failed')
        self.assertFalse(job.state()['can_refresh'])
        self.assertEqual(self.client.post('/api/jobs/'+job.id+'/refresh',json={},headers=self.headers).status_code,409)

    def test_continue_keeps_account_and_checkpoints(self):
        job=self.create()
        checkpoint=job.root/'123'/'checkpoint.txt'
        checkpoint.parent.mkdir();checkpoint.write_text('keep')
        old=job.output
        response=self.client.post('/api/jobs/'+job.id+'/continue',json={},headers=self.headers)
        self.assertEqual(response.status_code,200)
        job.thread.join(3)
        self.assertFalse(job.active)
        self.assertTrue(job.output.is_file())
        self.assertNotEqual(job.output,old)
        self.assertFalse(old.exists())
        self.assertEqual(checkpoint.read_text(),'keep')
        self.assertEqual(job.rounds,2)
        current=job.output
        class Wrong(FakeQQ):
            def poll(self):
                self.uin='456'
                return 'ok'
        self.service.qq_factory=Wrong
        self.assertEqual(self.client.post('/api/jobs/'+job.id+'/continue',json={},headers=self.headers).status_code,200)
        job.thread.join(3)
        self.assertEqual(job.phase,'error')
        self.assertIn('账号',job.message)
        self.assertEqual(job.output,current)
        self.assertTrue(current.exists())

    def test_resource_capacity_stops_without_counting_photo_limit(self):
        job=self.create()
        self.service.photo_byte_limit=1
        media=job.root/'123'/'media'
        media.mkdir(parents=True)
        (media/'a.jpg').write_bytes(b'over-limit')
        job.storage_checked=0
        self.assertFalse(job.resource_guard())
        self.assertIn('容量',job.budget_reason)
        self.assertFalse(job.state()['can_continue'])

    def test_secret_required_and_login_timeout(self):
        with self.assertRaises(ValueError):
            create_cloud_app(secret='short',testing=True,cleaner=False)
        class Waiting(FakeQQ):
            def poll(self):
                return '66'
        self.service.qq_factory = Waiting
        self.service.login_seconds = .02
        job = self.create()
        self.assertEqual(job.phase,'error')
        self.assertIsNone(job.qr)


if __name__ == '__main__':
    unittest.main()
