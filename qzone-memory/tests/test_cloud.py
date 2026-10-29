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
    output = Path(root)/'exports'/'test'
    (output/'media').mkdir(parents=True)
    (output/'media/a.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=='))
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><p>&lt;script&gt;private&lt;/script&gt;</p><img src="media/a.png">')
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
        manifest = (job.root/'job.json').read_text()
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
        source.write_text('<img src="../secret.png">')
        with self.assertRaises(ValueError):
            standalone_html(source,root/'result.html')

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
