"""Bounded, single-process cloud trial. QQ sessions never leave job memory."""
import base64
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from flask import Flask, abort, jsonify, request, send_file, session
from .online import QQSession
from .trial import run_trial, TrialLimits
from .progress import TaskProgress

JOB_ID = re.compile(r'^[a-f0-9]{32}$')
CLOUD_LIMITS = TrialLimits(scan_seconds=120, total_seconds=180, requests=40, media=12, photo_bytes=4*1024*1024)


def standalone_html(source, destination):
    """Inline only verified exported image files; leave no server-only image URLs."""
    root = source.parent.resolve()
    document = source.read_text(encoding='utf-8')
    def inline(match):
        value = html.unescape(match.group(2))
        if value.startswith(('data:', '#')):
            return match.group(0)
        target = (root / value).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError('Invalid exported image')
        mime = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.gif':'image/gif','.webp':'image/webp'}.get(target.suffix.lower())
        if not mime:
            raise ValueError('Unexpected exported resource')
        return match.group(1)+'="data:'+mime+';base64,'+base64.b64encode(target.read_bytes()).decode('ascii')+'"'
    document = re.sub(r'(src|href)="([^"]+)"', inline, document)
    destination.write_text(document, encoding='utf-8')


class CloudJob:
    def __init__(self, service, owner, identifier=None):
        self.service = service
        self.id = identifier or secrets.token_hex(16)
        self.owner = owner
        self.root = service.root / self.id
        self.root.mkdir(mode=0o700)
        self.created = time.time()
        self.expires = self.created + service.retention
        self.phase = 'login'
        self.message = '正在申请 QQ 二维码'
        self.qr = None
        self.stop = threading.Event()
        self.refresh_qr = threading.Event()
        self.qr_refreshes = 0
        self.login_finished = False
        self.progress = TaskProgress()
        self.lock = threading.RLock()
        self.output = None
        self.failure = None
        self.stats = {}
        self.deleted = False
        self.active = True
        self.thread = None
        self.persist()

    def persist(self):
        value = dict(schema=1, id=self.id, owner=self.owner, created=self.created, expires=self.expires,
                     phase=self.phase, message=self.message, stats=self.stats,
                     qr_refreshes=self.qr_refreshes, login_finished=self.login_finished,
                     output=str(self.output.relative_to(self.root)) if self.output else None)
        path = self.root/'job.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(path)

    def state(self):
        with self.lock:
            return dict(id=self.id, phase=self.phase, message=self.message, qr=self.qr,
                        expires=self.expires, active=self.active, stats=self.stats,
                        progress=self.progress.snapshot(self.active, self.phase),
                        ready=self.output is not None, incomplete=self.phase == 'partial',
                        can_refresh=not self.login_finished and self.phase in ('login','error','cancelled'),
                        qr_refreshes=self.qr_refreshes)

    def notify(self, kind, value):
        with self.lock:
            if kind == 'progress':
                self.progress.update(value)
            elif kind == 'status':
                self.message = str(value)
            if self.service.job_bytes(self.root) > self.service.job_byte_limit:
                self.stop.set()

    def run(self):
        qq = None
        timer = None
        try:
            qq = self.service.qq_factory()
            login_deadline = time.monotonic() + self.service.login_seconds
            while not self.stop.is_set() and not qq.uin:
                if self.refresh_qr.is_set():
                    self.refresh_qr.clear()
                    qq.close()
                    qq = self.service.qq_factory()
                    login_deadline = time.monotonic() + self.service.login_seconds
                if time.monotonic() >= login_deadline:
                    raise TimeoutError('login_timeout')
                image = qq.qr()
                with self.lock:
                    self.qr = 'data:image/png;base64,'+base64.b64encode(image).decode('ascii')
                    self.message = '请用手机 QQ 扫码，并确认登录'
                while not self.stop.wait(self.service.poll_seconds):
                    if self.refresh_qr.is_set():
                        break
                    if time.monotonic() >= login_deadline:
                        raise TimeoutError('login_timeout')
                    result = qq.poll()
                    if result in ('ok','65'):
                        break
                    if result in ('67','68'):
                        self.notify('status','已扫码，请在 QQ 中确认登录')
            if self.stop.is_set():
                self.phase, self.message = 'cancelled', '已取消扫码'
                return
            with self.lock:
                self.login_finished = True
                self.phase, self.qr = 'collecting', None
                self.message = '正在采集；体验版范围有限，不代表完整深度找回'
            timer = threading.Timer(self.service.limits.total_seconds, self.stop.set)
            timer.daemon = True
            timer.start()
            output, report = self.service.runner(qq, self.root, self.stop, self.notify,
                media_workers=2, limits=self.service.limits)
            with self.lock:
                self.phase = 'exporting'
                self.message = '正在生成可离线阅读的 HTML 和图片包'
            standalone_html(Path(output), self.root/'空间记忆.html')
            with zipfile.ZipFile(self.root/'空间记忆.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(Path(output).parent.rglob('*')):
                    if path.is_file() and not path.is_symlink():
                        archive.write(path, '空间记忆/'+str(path.relative_to(Path(output).parent)))
            with self.lock:
                self.output = Path(output)
                self.stats = {key:report.get(key,0) for key in ('exported_posts','exported_photos','requests')}
                self.stats['scan_state'] = report.get('state')
                reasons = []
                if report.get('state') == 'failed':
                    reasons.append('采集遇到异常而中断，当前为已保存的部分结果')
                elif report.get('state') != 'completed':
                    reasons.append('本轮已暂停或达到扫描时间／请求预算')
                if report.get('exported_photos',0) >= self.service.limits.media:
                    reasons.append('达到本轮 '+str(self.service.limits.media)+' 张图片上限')
                if report.get('issues') and not reasons:
                    reasons.append('部分来源或图片未取得，详见下载包中的采集报告')
                self.stats['completion_notes'] = reasons
                self.stats['diagnostic'] = report.get('diagnostic')
                self.phase = 'partial' if reasons else 'done'
                self.message = '；'.join(reasons) if reasons else '结果已生成，可预览或下载。体验版仅覆盖本轮取得的内容。'
        except Exception as exc:
            # Never persist/return requests exception text, signed URLs, cookies or locals.
            self.failure = type(exc).__name__
            with self.lock:
                self.phase = 'error'
                self.message = '云端任务未完成，请重新扫码尝试；QQ 可能要求额外验证。' if not isinstance(exc, TimeoutError) else '扫码已超时，请重新开始。'
        finally:
            if timer:
                timer.cancel()
            if qq:
                qq.close()
            with self.lock:
                self.qr = None
                self.active = False
                self.progress.finish()
                if not self.deleted:
                    self.persist()
            self.service.slots.release()
            if self.deleted:
                shutil.rmtree(self.root, ignore_errors=True)


class CloudService:
    def __init__(self, root, secret, *, qq_factory=QQSession, runner=run_trial,
                 concurrency=1, retention=3600, login_seconds=180, poll_seconds=2,
                 limits=CLOUD_LIMITS, daily_jobs=20, monthly_bytes=1024**3, usage_path=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secret = secret.encode()
        self.usage_path = Path(usage_path) if usage_path else self.root/'usage.sqlite3'
        self.usage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.qq_factory, self.runner = qq_factory, runner
        self.retention, self.login_seconds, self.poll_seconds = retention, login_seconds, poll_seconds
        self.limits, self.daily_jobs, self.monthly_bytes = limits, daily_jobs, monthly_bytes
        self.job_byte_limit = 80*1024**2
        self.disk_limit = 600*1024**2
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(concurrency)
        self.jobs = {}
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (period TEXT, metric TEXT, value INTEGER NOT NULL, PRIMARY KEY(period,metric))')
        self.restore()

    @contextmanager
    def database(self):
        db = sqlite3.connect(self.usage_path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def owner_hash(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def allowance(self, metric, amount, limit, period):
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            value = db.execute('SELECT value FROM usage WHERE period=? AND metric=?',(period,metric)).fetchone()
            if (value[0] if value else 0)+amount > limit:
                return False
            db.execute('INSERT INTO usage VALUES (?,?,?) ON CONFLICT(period,metric) DO UPDATE SET value=value+excluded.value',(period,metric,amount))
        return True

    @staticmethod
    def job_bytes(path):
        total = 0
        for p in path.rglob('*'):
            try:
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def restore(self):
        # Login sessions are deliberately not recovered after a restart.
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink() or not JOB_ID.fullmatch(path.name):
                continue
            try:
                value = json.loads((path/'job.json').read_text(encoding='utf-8'))
                if value.get('schema') != 1 or value.get('id') != path.name:
                    continue
                if value['expires'] <= time.time():
                    shutil.rmtree(path)
                    continue
                job = object.__new__(CloudJob)
                job.service, job.id, job.root = self, path.name, path
                job.owner, job.created, job.expires = value['owner'], value['created'], value['expires']
                job.lock, job.stop, job.progress = threading.RLock(), threading.Event(), TaskProgress()
                job.refresh_qr = threading.Event()
                job.qr_refreshes = value.get('qr_refreshes',0)
                job.login_finished = value.get('login_finished',bool(value.get('output')))
                job.qr, job.thread, job.failure = None, None, None
                job.active, job.deleted, job.stats = False, False, value.get('stats',{})
                candidate = (path/value['output']).resolve() if value.get('output') else None
                job.output = candidate if candidate and candidate.is_relative_to(path) and candidate.is_file() else None
                job.phase = value['phase'] if job.output else 'error'
                job.message = value['message'] if job.output else '服务已重启，原 QQ 会话已清除，请重新开始。'
                self.jobs[job.id] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def cleanup(self):
        with self.lock:
            for job in list(self.jobs.values()):
                if job.expires <= time.time():
                    self.delete(job)

    def delete(self, job):
        with self.lock, job.lock:
            job.deleted = True
            job.stop.set()
            self.jobs.pop(job.id, None)
            if not job.active:
                shutil.rmtree(job.root, ignore_errors=True)

    def refresh(self, job):
        with self.lock, job.lock:
            if job.deleted or job.expires <= time.time() or job.login_finished or job.output:
                raise ValueError('任务已开始采集或已结束，不能刷新登录二维码')
            if job.qr_refreshes >= 5 or time.time()-job.created >= 900:
                raise ValueError('本轮扫码重试次数或时间已用完，请重新申请任务')
            if not job.active:
                if not self.slots.acquire(blocking=False):
                    raise ValueError('云端正在处理其他任务，请稍后重试')
                job.stop = threading.Event()
                job.progress = TaskProgress()
                job.active = True
                job.phase = 'login'
                job.failure = None
                job.refresh_qr.clear()
                job.thread = threading.Thread(target=job.run,daemon=True)
                job.thread.start()
            else:
                job.refresh_qr.set()
            job.qr_refreshes += 1
            job.qr = None
            job.message = '正在刷新二维码，请重新扫码并确认登录'
            job.persist()

    def create(self, owner):
        self.cleanup()
        with self.lock:
            if any(j.owner==owner and j.active for j in self.jobs.values()):
                raise ValueError('你已有任务正在处理')
            if self.job_bytes(self.root) > self.disk_limit:
                raise ValueError('临时存储已满，请稍后再试')
            if not self.slots.acquire(blocking=False):
                raise ValueError('云端体验正在处理其他任务，请稍后再试')
            try:
                day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                if not self.allowance('jobs',1,self.daily_jobs,day):
                    raise ValueError('今日体验名额已用完，请明天再试')
                # Limit one browser session to three attempts per UTC day.
                if not self.allowance('owner:'+owner,1,3,day):
                    raise ValueError('本浏览器今日体验次数已用完')
                job = CloudJob(self,owner)
                self.jobs[job.id] = job
                job.thread = threading.Thread(target=job.run, daemon=True)
                job.thread.start()
                return job
            except BaseException:
                self.slots.release()
                raise


def create_cloud_app(root=None, secret=None, *, service=None, testing=False, cleaner=True):
    secret = secret or os.environ.get('SPACE_MEMORY_CLOUD_SECRET','')
    if len(secret) < 32:
        raise ValueError('SPACE_MEMORY_CLOUD_SECRET must contain at least 32 characters')
    app = Flask(__name__, static_folder=None)
    if os.environ.get('SPACE_MEMORY_CLOUD_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0)
    app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=4096, SESSION_COOKIE_NAME='space_memory_cloud',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=not testing, SESSION_COOKIE_SAMESITE='Strict')
    root = root or os.environ.get('SPACE_MEMORY_CLOUD_ROOT','/tmp/space-memory-cloud')
    service = service or CloudService(root,secret,usage_path=os.environ.get('SPACE_MEMORY_CLOUD_USAGE_PATH'))
    app.extensions['cloud_service'] = service
    assets = Path(__file__).parent/'cloud_ui'

    @app.before_request
    def protect():
        if request.path == '/healthz':
            return
        if 'owner' not in session:
            session['owner'] = secrets.token_urlsafe(32)
            session['csrf'] = secrets.token_urlsafe(32)
        if request.method in ('POST','DELETE'):
            origin = os.environ.get('SPACE_MEMORY_CLOUD_ORIGIN') or request.host_url.rstrip('/')
            if request.headers.get('Origin') != origin or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf']):
                abort(403)
            if not request.is_json:
                abort(415)

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer', 'X-Frame-Options':'DENY', 'X-Robots-Tag':'noindex, nofollow',
            'Content-Security-Policy':"default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
        if request.path.startswith('/jobs/') and response.status_code==200:
            # Exporter produces a self-contained document with escaped user text.
            response.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        return response

    @app.errorhandler(500)
    def server_error(error):
        return jsonify(error='服务暂时不可用，请稍后再试'),500

    @app.get('/healthz')
    def health():
        return jsonify(ok=True)

    @app.get('/')
    def index():
        return send_file(assets/'index.html')

    @app.get('/assets/<name>')
    def asset(name):
        if name not in ('app.js','app.css'):
            abort(404)
        return send_file(assets/name)

    def owned(identifier):
        job = service.jobs.get(identifier)
        if not job or job.deleted or job.expires <= time.time() or not hmac.compare_digest(job.owner,service.owner_hash(session['owner'])):
            abort(404)
        return job

    @app.get('/api/session')
    def current():
        owner = service.owner_hash(session['owner'])
        with service.lock:
            jobs = [j.state() for j in service.jobs.values() if j.owner==owner and j.expires>time.time() and not j.deleted]
        return jsonify(csrf=session['csrf'], jobs=jobs, limits=dict(retention_seconds=service.retention,scan_seconds=service.limits.scan_seconds,max_photos=service.limits.media))

    @app.post('/api/jobs')
    def create():
        if (request.json or {}).get('consent') is not True:
            return jsonify(error='请先确认云端临时处理说明'),400
        try:
            job = service.create(service.owner_hash(session['owner']))
        except ValueError as exc:
            return jsonify(error=str(exc)),429
        return jsonify(job.state()),201

    @app.get('/api/jobs/<identifier>')
    def status(identifier):
        return jsonify(owned(identifier).state())

    @app.post('/api/jobs/<identifier>/stop')
    def stop(identifier):
        job = owned(identifier)
        job.stop.set()
        return jsonify(ok=True)

    @app.post('/api/jobs/<identifier>/refresh')
    def refresh(identifier):
        job = owned(identifier)
        try:
            service.refresh(job)
        except ValueError as exc:
            return jsonify(error=str(exc)),409
        return jsonify(job.state())

    @app.delete('/api/jobs/<identifier>')
    def delete(identifier):
        service.delete(owned(identifier))
        return jsonify(ok=True)

    def private_file(job, path, attachment=False, name=None):
        if not job.output:
            abort(409)
        if not path.is_file():
            abort(404)
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if not service.allowance('bytes',path.stat().st_size,service.monthly_bytes,month):
            return jsonify(error='本月云端体验下载额度已用完，请稍后再试'),429
        return send_file(path, as_attachment=attachment, download_name=name, conditional=False)

    @app.get('/jobs/<identifier>/download/<kind>')
    def download(identifier,kind):
        job = owned(identifier)
        if kind not in ('html','zip'):
            abort(404)
        return private_file(job,job.root/('空间记忆.'+kind),True,'空间记忆.'+kind)

    @app.get('/jobs/<identifier>/preview/<path:filename>')
    def preview(identifier,filename):
        job = owned(identifier)
        if not job.output:
            abort(409)
        path = (job.output.parent/filename).resolve()
        if not path.is_relative_to(job.output.parent.resolve()) or path.is_symlink() or path.suffix.lower() not in ('.html','.jpg','.jpeg','.png','.gif','.webp'):
            abort(404)
        return private_file(job,path)

    if cleaner:
        def clean_loop():
            while True:
                time.sleep(30)
                service.cleanup()
        threading.Thread(target=clean_loop,daemon=True).start()
    return app
