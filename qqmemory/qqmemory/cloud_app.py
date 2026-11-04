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
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature
from .config import setting
from .version import VERSION, release_info
from .online import QQSession
from .trial import run_trial, TrialLimits
from .progress import TaskProgress
from .large_export import standalone_html, bundle_exports, PART_BYTES, SINGLE_HTML_BYTES

JOB_ID = re.compile(r"^[a-f0-9]{32}$")
CLOUD_LIMITS = TrialLimits(
    scan_seconds=1200,
    total_seconds=1800,
    requests=1200,
    media=2**31 - 1,
    photo_bytes=4 * 1024 * 1024,
)


class CloudJob:
    def __init__(self, service, owner, identifier=None):
        self.service = service
        self.id = identifier or secrets.token_hex(16)
        self.owner = owner
        self.root = service.root / self.id
        self.root.mkdir(mode=0o700)
        self.created = time.time()
        self.expires = self.created + service.retention
        self.phase = "login"
        self.message = "正在申请 QQ 二维码"
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
        self.counts = {}
        self.collection_started = None
        self.deleted = False
        self.active = True
        self.thread = None
        self.account = None
        self.rounds = 1
        self.mode = "collect"
        self.bundle_dir = None
        self.parts = []
        self.inline_ready = False
        self.budget_reason = None
        self.storage_checked = 0
        self.storage_lock = threading.Lock()
        self.previous_output = None
        self.persist()

    def persist(self):
        value = dict(
            schema=1,
            id=self.id,
            owner=self.owner,
            created=self.created,
            expires=self.expires,
            phase=self.phase,
            message=self.message,
            stats=self.stats,
            counts=self.counts,
            qr_refreshes=self.qr_refreshes,
            login_finished=self.login_finished,
            account=self.account,
            rounds=self.rounds,
            mode=self.mode,
            parts=self.parts,
            inline_ready=self.inline_ready,
            budget_reason=self.budget_reason,
            bundle_dir=str(self.bundle_dir.relative_to(self.root)) if self.bundle_dir else None,
            output=str(self.output.relative_to(self.root)) if self.output else None,
        )
        path = self.root / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)

    def state(self):
        with self.lock:
            # Worker threads save images independently of text scans. Poll SQLite so
            # their completed downloads are visible even while a QQ request is slow.
            if self.account and str(self.account).isdigit():
                database = self.root / self.account / "archive.sqlite3"
                if database.is_file():
                    db = None
                    try:
                        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
                        media = db.execute(
                            "SELECT count(*),sum(state='saved'),sum(state='failed'),sum(state='saved' AND quality_checked IS NULL) FROM media"
                        ).fetchone()
                        self.counts.update(
                            photos_found=media[0],
                            photos_saved=media[1] or 0,
                            photos_failed=media[2] or 0,
                            photos_quality_pending=media[3] or 0,
                        )
                        self.counts["posts"] = db.execute("SELECT count(*) FROM posts").fetchone()[
                            0
                        ]
                    except sqlite3.OperationalError:
                        pass  # The collector may still be creating its first tables.
                    finally:
                        if db is not None:
                            db.close()
            phase = (
                "stopping"
                if self.active and self.stop.is_set() and self.phase in ("login", "collecting")
                else self.phase
            )
            message = (
                "已收到暂停请求，正在等待当前请求结束，然后保存已有成果；不再开始新的采集请求。"
                if phase == "stopping"
                else self.message
            )
            return dict(
                id=self.id,
                phase=phase,
                message=message,
                qr=self.qr,
                expires=self.expires,
                active=self.active,
                can_live_preview=bool(
                    self.account and (self.root / self.account / "archive.sqlite3").is_file()
                ),
                stats=self.stats,
                counts=self.counts,
                collection_elapsed=max(0, int(time.monotonic() - self.collection_started))
                if self.collection_started and self.active
                else None,
                collection_limit=self.service.limits.total_seconds,
                progress=self.progress.snapshot(self.active, phase),
                ready=self.output is not None,
                incomplete=self.phase == "partial",
                can_refresh=self.output is None
                and not self.login_finished
                and self.phase in ("login", "error", "cancelled"),
                qr_refreshes=self.qr_refreshes,
                parts=self.parts,
                inline_ready=self.inline_ready,
                can_continue=self.output is not None and not self.active and not self.budget_reason,
                rounds=self.rounds,
                mode=self.mode,
            )

    def resource_guard(self):
        with self.storage_lock:
            if time.monotonic() - self.storage_checked < 1:
                return not self.budget_reason
            self.storage_checked = time.monotonic()
            photos = (
                self.service.job_bytes(self.root / self.account / "media") if self.account else 0
            )
            if photos > self.service.photo_byte_limit:
                self.budget_reason = "本轮图片达到临时容量上限，请下载已有成果；云端容量有限"
            elif (
                self.account
                and self.service.job_bytes(self.root / self.account / "evidence") > 64 * 1024**2
            ):
                self.budget_reason = "历史证据达到本轮内存保护容量，已保留断点和现有成果"
            elif (
                self.service.job_bytes(self.root) > self.service.job_byte_limit
                or self.service.job_bytes(self.service.root) > self.service.disk_limit
            ):
                self.budget_reason = "临时存储容量不足，已停止新采集并保留现有成果"
            elif shutil.disk_usage(self.root).free < self.service.disk_reserve + photos:
                self.budget_reason = "服务器可用磁盘不足，已预留打包空间并停止新采集"
            return not self.budget_reason

    def notify(self, kind, value):
        with self.lock:
            if kind == "progress":
                self.progress.update(value)
                if value.get("stage") == "export":
                    self.phase = "exporting"
                    self.message = "正在生成离线档案与下载文件"
            elif kind == "counts":
                self.counts = {
                    k: max(0, int(value.get(k, 0)))
                    for k in (
                        "posts",
                        "photos_found",
                        "photos_saved",
                        "photos_failed",
                        "photos_quality_pending",
                        "requests",
                        "details_pending",
                    )
                }
                self.counts.update(
                    {
                        k: int(value[k]) if value.get(k) is not None else None
                        for k in ("earliest_published", "earliest_interaction")
                    }
                )
            elif kind == "status":
                self.message = str(value)
            if not self.resource_guard():
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
                    raise TimeoutError("login_timeout")
                image = qq.qr()
                with self.lock:
                    self.qr = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                    self.message = "请用手机 QQ 扫码，并确认登录"
                while not self.stop.wait(self.service.poll_seconds):
                    if self.refresh_qr.is_set():
                        break
                    if time.monotonic() >= login_deadline:
                        raise TimeoutError("login_timeout")
                    result = qq.poll()
                    if result in ("ok", "65"):
                        break
                    if result in ("67", "68"):
                        self.notify("status", "已扫码，请在 QQ 中确认登录")
            if self.stop.is_set():
                self.phase, self.message = "cancelled", "已取消扫码"
                return
            with self.lock:
                if self.account and self.account != str(qq.uin):
                    raise ValueError("account_mismatch")
                self.account = str(qq.uin)
                self.login_finished = True
                self.collection_started = time.monotonic()
                self.phase, self.qr = "collecting", None
                self.message = (
                    "正在检查并补全高清图片；不重新扫描文字"
                    if self.mode == "quality"
                    else "正在边扫描边保存图片，已取得的内容可实时预览"
                )
            timer = threading.Timer(self.service.limits.total_seconds, self.stop.set)
            timer.daemon = True
            timer.start()
            output, report = self.service.runner(
                qq,
                self.root,
                self.stop,
                self.notify,
                media_workers=2,
                media_quality="best" if self.mode == "quality" else "first",
                media_only=self.mode == "quality",
                limits=self.service.limits,
                deep=self.mode != "quality",
                resource_guard=self.resource_guard,
                media_max_pending=4,
                link_export_media=True,
                text_first=True,
            )
            with self.lock:
                self.phase = "exporting"
                self.message = "正在生成可离线阅读的 HTML 和图片包"
            page = Path(output)
            note = (
                "本轮已暂停或达到预算，深度扫描可能尚未完成；可回到任务页用同一 QQ 继续断点。"
                if report.get("state") == "paused"
                else "本轮采集异常中断，当前为已保存的部分结果。"
                if report.get("state") == "failed"
                else "本轮已结束，不保证覆盖全部历史。"
            )
            note += (
                " 已取得 "
                + str(report.get("exported_posts", 0))
                + " 条记录、"
                + str(report.get("exported_photos", 0))
                + " 张照片。"
            )
            page.write_text(
                page.read_text(encoding="utf-8").replace(
                    "</h1>", '</h1><p class="archive-status">' + html.escape(note) + "</p>", 1
                ),
                encoding="utf-8",
            )
            bundle_dir = self.root / "bundles" / secrets.token_hex(8)
            parts, inline_ready = bundle_exports(
                Path(output), bundle_dir, progress=lambda msg: self.notify("status", msg)
            )
            with self.lock:
                old_output, old_bundle = self.previous_output, self.bundle_dir
                self.bundle_dir, self.parts, self.inline_ready = bundle_dir, parts, inline_ready
                self.output = Path(output)
                self.stats = {
                    key: report.get(key, 0)
                    for key in ("exported_posts", "exported_photos", "requests")
                }
                self.stats["scan_state"] = report.get("state")
                reasons = []
                if report.get("state") == "failed":
                    reasons.append("采集遇到异常而中断，当前为已保存的部分结果")
                elif report.get("state") != "completed":
                    reasons.append("本轮已暂停或达到扫描时间／请求预算")
                if self.budget_reason:
                    reasons.append(self.budget_reason)
                if report.get("exported_photos", 0) >= self.service.limits.media:
                    reasons.append("达到本轮 " + str(self.service.limits.media) + " 张图片上限")
                if report.get("issues") and not reasons:
                    reasons.append("部分来源或图片未取得，详见下载包中的采集报告")
                self.stats["completion_notes"] = reasons
                self.stats["diagnostic"] = report.get("diagnostic")
                self.stats["rounds"] = self.rounds
                self.stats["zip_parts"] = len(parts)
                self.phase = "partial" if reasons else "done"
                self.message = (
                    "；".join(reasons)
                    if reasons
                    else "结果已生成，可预览或下载。体验版仅覆盖本轮取得的内容。"
                )
            if old_bundle and old_bundle != bundle_dir:
                shutil.rmtree(old_bundle, ignore_errors=True)
            if old_output and old_output.parent != Path(output).parent:
                shutil.rmtree(old_output.parent, ignore_errors=True)
        except Exception as exc:
            # Never persist/return requests exception text, signed URLs, cookies or locals.
            self.failure = type(exc).__name__
            with self.lock:
                self.phase = "error"
                self.message = (
                    "扫码账号与原任务不一致，请使用原 QQ 继续。"
                    if str(exc) == "account_mismatch"
                    else "云端任务未完成，请重新扫码尝试；QQ 可能要求额外验证。"
                    if not isinstance(exc, TimeoutError)
                    else "扫码已超时，请重新开始。"
                )
        finally:
            if timer:
                timer.cancel()
            if qq:
                qq.close()
            with self.lock:
                self.qr = None
                self.active = False
                self.expires = time.time() + self.service.retention
                if self.output is None and self.previous_output:
                    self.output = self.previous_output
                self.previous_output = None
                self.progress.finish()
                if not self.deleted:
                    self.persist()
            self.service.slots.release()
            if self.deleted:
                shutil.rmtree(self.root, ignore_errors=True)


class CloudService:
    def __init__(
        self,
        root,
        secret,
        *,
        qq_factory=QQSession,
        runner=run_trial,
        concurrency=1,
        retention=3600,
        login_seconds=180,
        poll_seconds=2,
        limits=CLOUD_LIMITS,
        daily_jobs=20,
        monthly_bytes=4 * 1024**3,
        usage_path=None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secret = secret.encode()
        self.usage_path = Path(usage_path) if usage_path else self.root / "usage.sqlite3"
        self.usage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.qq_factory, self.runner = qq_factory, runner
        self.retention, self.login_seconds, self.poll_seconds = (
            retention,
            login_seconds,
            poll_seconds,
        )
        self.limits, self.daily_jobs, self.monthly_bytes = limits, daily_jobs, monthly_bytes
        self.job_byte_limit = 2 * 1024**3
        self.photo_byte_limit = 512 * 1024**2
        self.disk_reserve = 512 * 1024**2
        self.disk_limit = 3 * 1024**3
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(concurrency)
        self.jobs = {}
        with self.database() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS usage (period TEXT, metric TEXT, value INTEGER NOT NULL, PRIMARY KEY(period,metric))"
            )
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
            db.execute("BEGIN IMMEDIATE")
            value = db.execute(
                "SELECT value FROM usage WHERE period=? AND metric=?", (period, metric)
            ).fetchone()
            if (value[0] if value else 0) + amount > limit:
                return False
            db.execute(
                "INSERT INTO usage VALUES (?,?,?) ON CONFLICT(period,metric) DO UPDATE SET value=value+excluded.value",
                (period, metric, amount),
            )
        return True

    @staticmethod
    def job_bytes(path):
        total = 0
        seen = set()
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    stat = p.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    if identity not in seen:
                        seen.add(identity)
                        total += stat.st_size
            except FileNotFoundError:
                pass
        return total

    def restore(self):
        # Login sessions are deliberately not recovered after a restart.
        for path in self.root.iterdir():
            if not path.is_dir() or path.is_symlink() or not JOB_ID.fullmatch(path.name):
                continue
            try:
                value = json.loads((path / "job.json").read_text(encoding="utf-8"))
                if value.get("schema") != 1 or value.get("id") != path.name:
                    continue
                if value["expires"] <= time.time():
                    shutil.rmtree(path)
                    continue
                job = object.__new__(CloudJob)
                job.service, job.id, job.root = self, path.name, path
                job.owner, job.created, job.expires = (
                    value["owner"],
                    value["created"],
                    value["expires"],
                )
                job.lock, job.stop, job.progress = (
                    threading.RLock(),
                    threading.Event(),
                    TaskProgress(),
                )
                job.refresh_qr = threading.Event()
                job.qr_refreshes = value.get("qr_refreshes", 0)
                job.login_finished = value.get("login_finished", bool(value.get("output")))
                job.qr, job.thread, job.failure = None, None, None
                job.active, job.deleted, job.stats = False, False, value.get("stats", {})
                job.counts, job.collection_started = value.get("counts", {}), None
                job.account, job.rounds = value.get("account"), value.get("rounds", 1)
                job.mode = value.get("mode", "collect")
                job.parts, job.inline_ready = (
                    value.get("parts", []),
                    value.get("inline_ready", False),
                )
                bundle = (path / value["bundle_dir"]).resolve() if value.get("bundle_dir") else None
                job.bundle_dir = (
                    bundle if bundle and bundle.is_relative_to(path) and bundle.is_dir() else None
                )
                job.budget_reason, job.storage_checked = value.get("budget_reason"), 0
                job.storage_lock, job.previous_output = threading.Lock(), None
                candidate = (path / value["output"]).resolve() if value.get("output") else None
                job.output = (
                    candidate
                    if candidate and candidate.is_relative_to(path) and candidate.is_file()
                    else None
                )
                job.phase = value["phase"] if job.output else "error"
                job.message = (
                    value["message"] if job.output else "服务已重启，原 QQ 会话已清除，请重新开始。"
                )
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
                raise ValueError("任务已开始采集或已结束，不能刷新登录二维码")
            if job.qr_refreshes >= 5 or time.time() - job.created >= 900:
                raise ValueError("本轮扫码重试次数或时间已用完，请重新申请任务")
            if not job.active:
                if not self.slots.acquire(blocking=False):
                    raise ValueError("云端正在处理其他任务，请稍后重试")
                job.stop = threading.Event()
                job.progress = TaskProgress()
                job.active = True
                job.phase = "login"
                job.failure = None
                job.refresh_qr.clear()
                job.thread = threading.Thread(target=job.run, daemon=True)
                job.thread.start()
            else:
                job.refresh_qr.set()
            job.qr_refreshes += 1
            job.qr = None
            job.message = "正在刷新二维码，请重新扫码并确认登录"
            job.persist()

    def continue_job(self, job, *, quality_only=False):
        with self.lock, job.lock:
            if job.active or not job.output or job.deleted or job.budget_reason:
                raise ValueError("当前任务不能继续；请先下载已有结果")
            if (
                self.job_bytes(self.root) > self.disk_limit
                or shutil.disk_usage(self.root).free < self.disk_reserve
            ):
                raise ValueError("临时存储不足，请先下载结果并释放不再需要的任务")
            if not self.slots.acquire(blocking=False):
                raise ValueError("云端正在处理其他任务，请稍后重试")
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if not self.allowance("jobs", 1, self.daily_jobs, day) or not self.allowance(
                "owner:" + job.owner, 1, 10, day
            ):
                self.slots.release()
                raise ValueError("今日任务额度已用完")
            job.mode = "quality" if quality_only else "collect"
            job.previous_output, job.output = job.output, None
            job.active, job.login_finished = True, False
            job.phase, job.message, job.qr = (
                "login",
                (
                    "请用同一个 QQ 扫码，仅检查并补全高清图片"
                    if quality_only
                    else "请用同一个 QQ 扫码，继续本任务"
                ),
                None,
            )
            job.stop, job.refresh_qr, job.progress = (
                threading.Event(),
                threading.Event(),
                TaskProgress(),
            )
            job.qr_refreshes, job.storage_checked = 0, 0
            job.expires = (
                time.time() + self.retention + self.limits.total_seconds + self.login_seconds
            )
            job.collection_started = None
            job.rounds += 1
            job.persist()
            job.thread = threading.Thread(target=job.run, daemon=True)
            job.thread.start()

    def create(self, owner):
        self.cleanup()
        with self.lock:
            if any(j.owner == owner and j.active for j in self.jobs.values()):
                raise ValueError("你已有任务正在处理")
            if self.job_bytes(self.root) > self.disk_limit:
                raise ValueError("临时存储已满，请稍后再试")
            if not self.slots.acquire(blocking=False):
                raise ValueError("云端体验正在处理其他任务，请稍后再试")
            try:
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if not self.allowance("jobs", 1, self.daily_jobs, day):
                    raise ValueError("今日体验名额已用完，请明天再试")
                # Daily allowance includes new tasks and continuation rounds.
                if not self.allowance("owner:" + owner, 1, 10, day):
                    raise ValueError("本浏览器今日体验次数已用完")
                job = CloudJob(self, owner)
                self.jobs[job.id] = job
                job.thread = threading.Thread(target=job.run, daemon=True)
                job.thread.start()
                return job
            except BaseException:
                self.slots.release()
                raise


def create_cloud_app(root=None, secret=None, *, service=None, testing=False, cleaner=True):
    secret = secret or setting("CLOUD_SECRET", "")
    if len(secret) < 32:
        raise ValueError("QQMEMORY_CLOUD_SECRET must contain at least 32 characters")
    app = Flask(__name__, static_folder=None)

    class CompatibleSession(SecureCookieSessionInterface):
        def open_session(self, app, request):
            result = super().open_session(app, request)
            if not request.cookies.get(self.get_cookie_name(app)) and request.cookies.get(
                "space_memory_cloud"
            ):
                try:
                    result = self.session_class(
                        self.get_signing_serializer(app).loads(
                            request.cookies["space_memory_cloud"],
                            max_age=int(app.permanent_session_lifetime.total_seconds()),
                        )
                    )
                    result.modified = True
                except BadSignature:
                    pass
            return result

    app.session_interface = CompatibleSession()
    if setting("CLOUD_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0)
    app.config.update(
        SECRET_KEY=secret,
        MAX_CONTENT_LENGTH=4096,
        SESSION_COOKIE_NAME="qqmemory_cloud",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=not testing,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    root = root or setting("CLOUD_ROOT", "/tmp/qqmemory-cloud")
    persistent = setting("CLOUD_PERSISTENT") == "1"
    if persistent:
        mount = Path(setting("CLOUD_DISK_MOUNT", "/var/data")).resolve()
        actual_root = service.root if service is not None else Path(root).resolve()
        if (
            not actual_root.is_relative_to(mount)
            or actual_root == mount
            or not os.path.ismount(mount)
        ):
            raise ValueError("Persistent archive root must be beneath the mounted data disk")
    if persistent and service is None:
        preferred = Path(root).resolve()
        legacy = preferred.with_name("space-memory-cloud")
        if (
            preferred.name == "qqmemory-cloud"
            and not preferred.exists()
            and legacy.is_dir()
            and not legacy.is_symlink()
        ):
            legacy.rename(preferred)
            # Old deployments can still find the same files during a rollback.
            legacy.symlink_to(preferred.name, target_is_directory=True)
    service = service or CloudService(root, secret, usage_path=setting("CLOUD_USAGE_PATH"))
    if persistent:
        # Keep room for export files; resource_guard also reserves the current photo size.
        service.disk_reserve = 64 * 1024**2
    app.extensions["cloud_service"] = service
    assets = Path(__file__).parent / "cloud_ui"

    @app.before_request
    def protect():
        if request.path == "/healthz":
            return
        if "owner" not in session:
            session["owner"] = secrets.token_urlsafe(32)
            session["csrf"] = secrets.token_urlsafe(32)
        if request.method in ("POST", "DELETE"):
            origin = setting("CLOUD_ORIGIN") or request.host_url.rstrip("/")
            if request.headers.get("Origin") != origin or not hmac.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session["csrf"]
            ):
                abort(403)
            if not request.is_json:
                abort(415)

    @app.after_request
    def headers(response):
        response.headers.update(
            {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "X-Robots-Tag": "noindex, nofollow",
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            }
        )
        if request.path.startswith("/jobs/") and response.status_code == 200:
            # Exporter produces a self-contained document with escaped user text.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        return response

    @app.errorhandler(500)
    def server_error(error):
        return jsonify(error="服务暂时不可用，请稍后再试"), 500

    @app.get("/healthz")
    def health():
        return jsonify(ok=True, persistent_storage=persistent, **release_info())

    @app.get("/")
    def index():
        page = (assets / "index.html").read_text(encoding="utf-8")
        page = page.replace("<!-- APP_VERSION -->", html.escape(VERSION))
        return app.response_class(page, mimetype="text/html")

    @app.get("/assets/<name>")
    def asset(name):
        if name not in ("app.js", "app.css"):
            abort(404)
        return send_file(assets / name)

    def owned(identifier):
        job = service.jobs.get(identifier)
        if (
            not job
            or job.deleted
            or job.expires <= time.time()
            or not hmac.compare_digest(job.owner, service.owner_hash(session["owner"]))
        ):
            abort(404)
        return job

    @app.get("/api/session")
    def current():
        owner = service.owner_hash(session["owner"])
        with service.lock:
            jobs = [
                j.state()
                for j in service.jobs.values()
                if j.owner == owner and j.expires > time.time() and not j.deleted
            ]
        return jsonify(
            csrf=session["csrf"],
            jobs=jobs,
            limits=dict(
                retention_seconds=service.retention,
                scan_seconds=service.limits.scan_seconds,
                total_seconds=service.limits.total_seconds,
                max_photos=None if service.limits.media == 2**31 - 1 else service.limits.media,
                photo_bytes=service.photo_byte_limit,
                part_bytes=PART_BYTES,
                persistent_storage=persistent,
            ),
        )

    @app.post("/api/jobs")
    def create():
        if (request.json or {}).get("consent") is not True:
            return jsonify(error="请先确认云端临时处理说明"), 400
        try:
            job = service.create(service.owner_hash(session["owner"]))
        except ValueError as exc:
            return jsonify(error=str(exc)), 429
        return jsonify(job.state()), 201

    @app.get("/api/jobs/<identifier>")
    def status(identifier):
        return jsonify(owned(identifier).state())

    def live_archive(job):
        from types import SimpleNamespace

        if not job.account or not str(job.account).isdigit():
            abort(409)
        root = job.root / job.account
        database = root / "archive.sqlite3"
        if not database.is_file():
            abort(409)
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return SimpleNamespace(root=root, db=db)

    @app.get("/api/jobs/<identifier>/live")
    def live(identifier):
        from .timeline import timeline

        job = owned(identifier)
        try:
            offset = max(0, min(1000000, int(request.args.get("offset", 0))))
        except ValueError:
            return jsonify(error="分页参数无效"), 400
        archive = live_archive(job)
        try:
            with archive.db:
                archive.db.execute("BEGIN")
                ids = [
                    row[0]
                    for row in archive.db.execute(
                        "SELECT id FROM posts ORDER BY created_at DESC,id LIMIT 20 OFFSET ?",
                        (offset,),
                    )
                ]
                total = archive.db.execute("SELECT count(*) FROM posts").fetchone()[0]
                posts = timeline(archive, limit=20, post_ids=ids)["posts"]
                result = []
                for post in posts:
                    result.append(
                        dict(
                            id=post["id"],
                            content=post["content"][:12000],
                            date=post["date"],
                            time_basis=post["time_basis"],
                            category=post["category"],
                            author=str(post["author"].get("nickname") or "我的空间")[:200],
                            likes=post["like_count"],
                            comment_count=post["comment_count"],
                            comments=[
                                dict(
                                    author=str(c.get("nickname") or c.get("uin") or "空间用户")[
                                        :200
                                    ],
                                    content=str(c.get("content") or "")[:2000],
                                    replies=[
                                        dict(
                                            author=str(
                                                r.get("nickname") or r.get("uin") or "空间用户"
                                            )[:200],
                                            content=str(r.get("content") or "")[:2000],
                                        )
                                        for r in c.get("replies", [])[:10]
                                    ],
                                )
                                for c in post["comments"][:20]
                            ],
                            media=[
                                dict(
                                    id=m["id"],
                                    state=m["state"],
                                    quality_verified=m["quality_verified"],
                                    url=f"/api/jobs/{job.id}/media/{m['id']}?v={m['sha256']}"
                                    if m["state"] == "saved"
                                    else None,
                                )
                                for m in post["media"][:36]
                            ],
                        )
                    )
            return jsonify(posts=result, total=total, offset=offset, limit=20, active=job.active)
        finally:
            archive.db.close()

    @app.get("/api/jobs/<identifier>/media/<media_id>")
    def live_media(identifier, media_id):
        job = owned(identifier)
        archive = live_archive(job)
        try:
            row = archive.db.execute(
                "SELECT local_path FROM media WHERE id=? AND state='saved'", (media_id,)
            ).fetchone()
            if not row or not row[0]:
                abort(404)
            path = (archive.root / row[0]).resolve()
            if not path.is_relative_to((archive.root / "media").resolve()) or path.suffix not in (
                ".jpg",
                ".png",
                ".gif",
                ".webp",
            ):
                abort(404)
            return private_file(job, path, unfinished=True)
        finally:
            archive.db.close()

    @app.post("/api/jobs/<identifier>/stop")
    def stop(identifier):
        job = owned(identifier)
        job.stop.set()
        return jsonify(job.state())

    @app.post("/api/jobs/<identifier>/refresh")
    def refresh(identifier):
        job = owned(identifier)
        try:
            service.refresh(job)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(job.state())

    @app.post("/api/jobs/<identifier>/continue")
    def continue_job(identifier):
        job = owned(identifier)
        try:
            quality_only = (request.json or {}).get("quality_only", False)
            if not isinstance(quality_only, bool):
                return jsonify(error="高清检查参数无效"), 400
            service.continue_job(job, quality_only=quality_only)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(job.state())

    @app.delete("/api/jobs/<identifier>")
    def delete(identifier):
        service.delete(owned(identifier))
        return jsonify(ok=True, persistent_storage=persistent, **release_info())

    def private_file(job, path, attachment=False, name=None, unfinished=False):
        if not job.output and not unfinished:
            abort(409)
        if not path.is_file():
            abort(404)
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        if not service.allowance("bytes", path.stat().st_size, service.monthly_bytes, month):
            return jsonify(error="本月云端体验下载额度已用完，请稍后再试"), 429
        return send_file(path, as_attachment=attachment, download_name=name, conditional=False)

    @app.get("/jobs/<identifier>/download/<kind>")
    def download(identifier, kind):
        job = owned(identifier)
        if kind == "html" and job.inline_ready and job.bundle_dir:
            return private_file(job, job.bundle_dir / "空间记忆.html", True, "空间记忆.html")
        if kind == "zip" and len(job.parts) == 1:
            kind = job.parts[0]["kind"]
        part = next((p for p in job.parts if p["kind"] == kind), None)
        if not part or not job.bundle_dir:
            abort(404)
        return private_file(job, job.bundle_dir / part["file"], True, "空间记忆-" + part["file"])

    @app.get("/jobs/<identifier>/preview/<path:filename>")
    def preview(identifier, filename):
        job = owned(identifier)
        if not job.output and not unfinished:
            abort(409)
        path = (job.output.parent / filename).resolve()
        if (
            not path.is_relative_to(job.output.parent.resolve())
            or path.is_symlink()
            or path.suffix.lower() not in (".html", ".jpg", ".jpeg", ".png", ".gif", ".webp")
        ):
            abort(404)
        return private_file(job, path)

    if cleaner:

        def clean_loop():
            while True:
                time.sleep(30)
                service.cleanup()

        threading.Thread(target=clean_loop, daemon=True).start()
    return app
