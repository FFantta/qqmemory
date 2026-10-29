"""Native Mac app + private loopback UI. All QQ credentials stay in memory."""
import base64
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from pathlib import Path
from types import SimpleNamespace
import requests
from flask import Flask, request, jsonify, send_file, abort
from werkzeug.serving import make_server, WSGIRequestHandler
from .online import QQSession, ProtocolError
from .locking import CollectionBusy, collection_lock
from .timeline import timeline
from .read_model import ArchiveView, normalize_social
from .storage import Archive
from .statistics import archive_statistics
from .trial import run_trial
from .exporting import export_archive
from .media import validate_image
from .emoji import get_emoji
from .accounts import profiles as local_profiles, remember, selected
from .progress import TaskProgress
from .version import VERSION


def data_root():
    if os.environ.get('SPACE_MEMORY_DATA_DIR'):
        return Path(os.environ['SPACE_MEMORY_DATA_DIR']).expanduser().resolve()
    config = Path(__file__).parent / 'ui' / 'local-config.json'
    if config.exists():
        candidate = Path(json.loads(config.read_text(encoding='utf-8'))['archive_root'])
        if candidate.exists():
            return candidate
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'SpaceMemory'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'SpaceMemory'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'SpaceMemory'


class Controller:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.refresh_qr = threading.Event()
        self.progress = TaskProgress()
        self.task_account = None
        self.outcome = None
        self.active = False
        self.media_running = set()
        self.media_queued = set()
        self.media_workers = 6
        self.phase = 'ready'
        self.message = '已保存的回忆随时可看'
        self.qr = None
        self.output = None
        self.events = []
        profiles = sorted(p.name for p in self.root.iterdir() if p.is_dir() and p.name.isdigit() and (p/'archive.sqlite3').exists())
        self.account = selected(self.root, profiles)
        self.nickname = '我的空间'
        self.mode = 'collect'
        self.qq = None
        self.load_profile()
        if self.account:
            Archive(self.root/self.account).close()
            from .deep_history import quarantine_non_moods
            try:
                with collection_lock(self.root/self.account):
                    archive=Archive(self.root/self.account)
                    try:
                        normalize_social(archive)
                        quarantine_non_moods(archive)
                    finally:archive.close()
            except CollectionBusy:
                pass

    def load_profile(self):
        self.nickname = '我的空间'
        if self.account:
            p = self.root/self.account/'profile.json'
            if p.exists():
                self.nickname = json.loads(p.read_text(encoding='utf-8')).get('nickname') or '我的空间'

    def notify(self, kind, value):
        with self.lock:
            if kind == 'progress':
                self.progress.update(value)
                return
            if kind == 'status':
                self.message = str(value)
            self.events.append({'kind':kind, 'message':str(value), 'time':time.strftime('%H:%M:%S')})
            self.events = self.events[-80:]

    def switch_account(self, uin):
        if not isinstance(uin,str) or not uin.isdigit() or len(uin)>20:
            raise ValueError('无效的档案账号')
        if uin not in {p['uin'] for p in local_profiles(self.root)}:
            raise ValueError('本机没有这个账号的档案')
        with self.lock:
            self.account = uin
            self.load_profile()
            remember(self.root,uin)

    def read_archive(self, account=None):
        account = account or self.account
        if account and (not str(account).isdigit() or len(str(account))>20):
            return None
        path = self.root / account if account else None
        if not path or not (path/'archive.sqlite3').exists():
            return None
        db = sqlite3.connect(f'file:{path / "archive.sqlite3"}?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return SimpleNamespace(root=path, db=db)

    def resume_media(self, retry_id=None, transport=None):
        """Download replayed discoveries without requiring a new QQ login."""
        from .media import download, fetch
        from .parallel import process_media
        with self.lock:
            if self.active or not self.account:
                return False
            archive = self.read_archive()
            try:
                sql = "SELECT id FROM media WHERE state='pending'" if retry_id is None else "SELECT id FROM media WHERE id=? AND state!='saved'"
                ids = [row[0] for row in archive.db.execute(sql, () if retry_id is None else (retry_id,))]
            finally:
                archive.db.close()
            if not ids:
                return False
            root = self.root / self.account
            self.task_account = self.account
            self.progress.reset()
            self.outcome = None
            self.progress.update(dict(stage="media",total=len(ids)))
            self.active = True
            self.mode = 'backfill'
            self.phase = 'collecting'
            self.stop.clear()
            self.media_queued = set(ids)
            self.message = f'正在补全 {len(ids)} 张历史记录图片'

        def worker(mid):
            with self.lock:
                if self.stop.is_set():
                    self.media_queued.discard(mid)
                    return False
                self.media_queued.discard(mid)
                self.media_running.add(mid)
            db = sqlite3.connect(root/'archive.sqlite3', timeout=30)
            db.row_factory = sqlite3.Row
            try:
                return bool(download(SimpleNamespace(root=root, db=db), mid, transport=transport or fetch))
            finally:
                db.close()
                with self.lock:
                    self.media_running.discard(mid)

        def work():
            try:
                with collection_lock(root):
                    saved, failed = process_media(ids, worker,
                        lambda done,total,saved,failed: (self.notify('progress',dict(stage='media',done=done,total=total)),self.notify('media', f'补图 {done}/{total} · 成功 {saved}')),
                        workers=self.media_workers)
                self.notify('status', f'图片补全已停止，已保存 {saved} 张' if self.stop.is_set() else f'图片补全完成，已保存 {saved} 张，未取得 {failed} 张')
                self.phase = 'done'
                self.outcome = 'paused' if self.stop.is_set() else 'completed'
            except Exception as exc:
                self.notify('status', '图片补全未完成，可点击未保存图片重试：'+type(exc).__name__)
                self.phase = 'error'
            finally:
                with self.lock:
                    self.progress.finish()
                    self.media_running.clear()
                    self.media_queued.clear()
                    self.active = False
        self.thread = threading.Thread(target=work, daemon=False)
        self.thread.start()
        return True

    def start(self, workers, mode="collect", intent="update"):
        with self.lock:
            if self.active:
                if self.phase == 'login':
                    self.media_workers = workers
                    self.mode = mode
                return
            expected = self.account if intent == 'update' else None
            self.task_account = expected
            self.progress.reset()
            self.outcome = None
            self.events.clear()
            self.refresh_qr.clear()
            if self.qq:
                self.qq.close()
                self.qq = None
            self.media_workers = workers
            self.mode = mode
            self.active = True
            self.stop.clear()
            self.phase = 'login'
            self.message = '正在获取 QQ 二维码'
            self.qr = None
        def work():
            qq = None
            try:
                qq = QQSession()
                while not qq.uin and not self.stop.is_set():
                    qr = base64.b64encode(qq.qr()).decode()
                    with self.lock:
                        self.qr = 'data:image/png;base64,' + qr
                        self.message = '用手机 QQ 扫码，并在手机上确认登录'
                    while not self.stop.wait(2):
                        if self.refresh_qr.is_set():
                            self.refresh_qr.clear()
                            break
                        result = qq.poll()
                        if result in ('65','ok'):
                            break
                        if result in ('67','68'):
                            self.notify('status', '已扫码，请在手机 QQ 上确认')
                if qq.uin and not self.stop.is_set():
                    if expected and qq.uin != expected:
                        raise ProtocolError('扫码账号与待更新档案不一致。请用该档案账号扫码；新账号请从“切换档案 → 添加账号”进入。')
                    self.qq = qq
                    with self.lock:
                        self.task_account = qq.uin
                        if self.account != qq.uin:
                            self.events.clear()
                            self.output = None
                        self.account = qq.uin
                        self.nickname = getattr(qq, 'nickname', '') or self.nickname
                        self.qr = None
                        self.phase = 'collecting'
                        remember(self.root,qq.uin)
                    profile = self.root/qq.uin
                    profile.mkdir(exist_ok=True)
                    (profile/'profile.json').write_text(json.dumps({'nickname':self.nickname, 'uin':qq.uin}, ensure_ascii=False), encoding='utf-8')
                    output, report = run_trial(qq, self.root, self.stop, self.notify, media_workers=self.media_workers, media_only=self.mode=='media', deep=self.mode=='deep', backup_only=self.mode=='backup')
                    self.output = output
                    self.outcome = report['state']
                    self.progress.finish()
                    self.phase = 'done'
                    label = '已暂停，断点已保存；' if report['state']=='paused' else '任务中断，已有成果已保存；' if report['state']=='failed' else ''
                    self.notify('status', label + f'已导出 {report["exported_posts"]} 条记录、{report["exported_photos"]} 张照片')
                    if report['state']=='failed':
                        self.phase='error'
                        for issue in report['issues']:self.notify('error',issue)
            except Exception as exc:
                self.outcome = 'failed'
                self.phase = 'error'
                self.notify('status', str(exc) if isinstance(exc, (ProtocolError, CollectionBusy)) else '处理未完成：'+type(exc).__name__+'。已有档案仍可查看。')
            finally:
                if qq is not None and self.qq is not qq:
                    qq.close()
                with self.lock:
                    self.progress.finish()
                    self.active = False
                    self.qr = None
                    if self.phase in ('login','stopping'):
                        self.phase = 'ready'
                        self.message = '已取消扫码；本地档案仍可浏览'
        self.thread=threading.Thread(target=work, daemon=False)
        self.thread.start()


def create_server(controller, bind=True, token=None):
    view = ArchiveView()
    token = token or secrets.token_urlsafe(32)
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise ValueError('Invalid local UI token')
    app = Flask(__name__, static_folder=None)
    prefix = '/' + token
    @app.before_request
    def protect():
        if not request.path.startswith(prefix+'/'):
            abort(404)
        if request.method == 'POST':
            if request.headers.get('Origin') not in (None, request.host_url.rstrip('/')):
                abort(403)
            if not request.is_json:
                abort(415)
    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith((prefix+'/avatar/', prefix+'/emoji/')):
            response.headers['Cache-Control'] = 'private, max-age=86400'
        elif request.path.startswith(prefix+'/media/') and response.status_code == 200 and request.args.get('v'):
            response.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response
    @app.get(prefix+'/')
    def index():
        return send_file(Path(__file__).parent/'ui'/'index.html')
    @app.get(prefix+'/assets/<name>')
    def asset(name):
        if name not in ('app.js','app.css'):
            abort(404)
        return send_file(Path(__file__).parent/'ui'/name)
    @app.get(prefix+'/api/state')
    def state():
        with controller.lock:
            state = dict(active=controller.active, phase=controller.phase, message=controller.message,
                         mode=controller.mode, media_running=list(controller.media_running),
                         media_queued=list(controller.media_queued),
                         qr=controller.qr, account=controller.account, nickname=controller.nickname,
                         events=list(controller.events), task_account=controller.task_account, outcome=controller.outcome,
                         progress=controller.progress.snapshot(controller.active,controller.phase))
        archive = controller.read_archive(state['account'])
        if archive:
            try:
                page = view.page(archive, request.args.get('search',''), request.args.get('year',''),
                                min(100,max(1,int(request.args.get('limit',30)))), max(0,int(request.args.get('offset',0))), photos_only=request.args.get('photos')=='1', category=request.args.get('category',''))
                state.update(page)
                from .deep_history import load_state
                deep = load_state(archive)
                if deep:
                    index=deep['index']
                    state['deep_scan']=dict(segment=index,total=len(deep['tasks']),page=deep['page'],complete=deep['complete'],
                        requests=deep['requests'],raw_cards=deep.get('raw_cards',0),
                        label=deep['tasks'][index]['label'] if index<len(deep['tasks']) else '等待失败分段重试' if deep.get('retry_tasks') else '全部分段已扫描')
            finally:
                archive.db.close()
        else:
            state.update(posts=[], total=0, years=[], stats={})
        return jsonify(state)
    @app.get(prefix+'/api/accounts')
    def accounts():
        return jsonify(accounts=local_profiles(controller.root),selected=controller.account)
    @app.post(prefix+'/api/accounts/select')
    def select_account():
        uin=(request.json or {}).get('uin')
        try:controller.switch_account(uin)
        except ValueError as exc:return jsonify(error=str(exc)),400
        return jsonify(ok=True)
    @app.post(prefix+'/api/qr/refresh')
    def refresh_qr():
        if not controller.active or controller.phase!='login':
            return jsonify(error='请先打开扫码窗口'),409
        with controller.lock:
            controller.qr=None
            controller.refresh_qr.set()
        return jsonify(ok=True)
    @app.post(prefix+'/api/start')
    def start():
        workers = int((request.json or {}).get('workers',6))
        if not 1 <= workers <= 12:
            abort(400)
        mode=(request.json or {}).get('mode',controller.mode if controller.active else 'collect')
        if mode not in ('backup','collect','deep'):
            abort(400)
        intent=(request.json or {}).get('intent','update')
        if intent not in ('update','add'):abort(400)
        controller.start(workers, mode=mode, intent=intent)
        return jsonify(ok=True)
    @app.post(prefix+'/api/media/retry')
    def retry_media():
        mid = (request.json or {}).get('id')
        if not isinstance(mid, str) or not re.fullmatch(r'[a-f0-9]{32}', mid):
            abort(400)
        if controller.active:
            return jsonify(error='已有任务正在运行，请稍后重试'), 409
        return jsonify(ok=controller.resume_media(mid))
    @app.post(prefix+'/api/upgrade')
    def upgrade():
        if controller.active:
            return jsonify(error='请先停止当前采集任务'), 409
        # Checked caches remain reusable; subsequent runs continue beyond the budget.
        controller.start(6, mode='media')
        return jsonify(ok=True)
    @app.post(prefix+'/api/relogin')
    def relogin():
        if controller.active:
            return jsonify(error='请先停止当前任务，再重新扫码'),409
        if controller.qq:
            controller.qq.close()
            controller.qq=None
        controller.start(controller.media_workers, mode=controller.mode)
        return jsonify(ok=True)
    @app.post(prefix+'/api/stop')
    def stop():
        if controller.active:
            login = controller.phase == 'login'
            controller.stop.set()
            controller.phase='stopping'
            controller.notify('status','正在取消扫码…' if login else '正在停止网络任务，已有回忆已保存，准备导出…')
        return jsonify(ok=True)
    @app.post(prefix+'/api/export')
    def export():
        if controller.active:
            return jsonify(error='请先停止采集，收尾后可打开导出结果'),409
        # New evidence can be reparsed after a collection run. Export a fresh
        # snapshot rather than reopening an older HTML with stale contents.
        archive = controller.read_archive()
        if not archive:
            return jsonify(error='还没有归档数据'),400
        try:
            dest = controller.root/'exports'/('desktop-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(2))
            controller.output = export_archive(archive,dest,progress=lambda m:controller.notify('status',m))/'index.html'
            webbrowser.open(controller.output.as_uri())
        finally:
            archive.db.close()
        return jsonify(ok=True)
    @app.get(prefix+'/media/<mid>')
    def media(mid):
        archive = controller.read_archive(request.args.get('account'))
        if not archive:
            abort(404)
        try:
            row = archive.db.execute("SELECT local_path,sha256 FROM media WHERE id=? AND state='saved'",(mid,)).fetchone()
            if not row or not row['local_path']:
                abort(404)
            path = (archive.root/row['local_path']).resolve()
            if not path.is_relative_to(archive.root.resolve()) or not path.is_file():
                abort(404)
            if request.args.get('thumb') == '1':
                from .thumbnails import thumbnail
                path = thumbnail(path, row['sha256'], archive.root/'thumbnails')
            return send_file(path)
        finally:
            archive.db.close()
    @app.get(prefix+'/emoji/<code>')
    def emoji(code):
        try:
            path = get_emoji(code, controller.root/'emojis')
        except ValueError:
            abort(404)
        if not path:
            abort(404)
        ext = validate_image(path.read_bytes())
        return send_file(path, mimetype='image/' + ('jpeg' if ext == 'jpg' else ext))
    @app.get(prefix+'/avatar/<uin>')
    def avatar(uin):
        if not uin.isdigit() or len(uin)>15:
            abort(404)
        cache = controller.root/'avatars'
        cache.mkdir(exist_ok=True)
        path = cache/(uin+'.img')
        if not path.exists():
            try:
                with requests.get('https://q1.qlogo.cn/g',params={'b':'qq','nk':uin,'s':100},timeout=(3,4),allow_redirects=False,stream=True) as r:
                    r.raise_for_status()
                    content = r.raw.read(512*1024+1)
                    if len(content)>512*1024:
                        abort(404)
                    validate_image(content)
                    temp = cache/(uin+'-'+secrets.token_hex(4)+'.part')
                    temp.write_bytes(content)
                    temp.replace(path)
            except (requests.RequestException, OSError, ValueError):
                abort(404)
        return send_file(path, mimetype='image/jpeg')
    class QuietHandler(WSGIRequestHandler):
        def log_request(self, *args, **kwargs):
            pass
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler) if bind else None
    return server, f'http://127.0.0.1:{server.server_port if server else 0}{prefix}/', app


def main():
    os.umask(0o077)
    import webview
    controller = Controller(data_root())
    server, url, _ = create_server(controller)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = webview.create_window('空间记忆 · '+VERSION,url,width=1240,height=860,min_size=(960,680),background_color='#fafaf7')
    def closing():
        if controller.active:
            controller.stop.set()
            controller.notify('status','正在停止并保存，请等待完成后再关闭窗口')
            return False
        return True
    window.events.closing += closing
    webview.start(gui='cocoa' if sys.platform == 'darwin' else 'edgechromium' if sys.platform == 'win32' else None)
    server.shutdown()
    if controller.qq:controller.qq.close()


if __name__ == '__main__':
    main()
