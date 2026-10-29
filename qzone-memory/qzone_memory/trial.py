"""Bounded real-account trial. No claim that history-only records are deleted posts."""
import json
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .deep_history import record as parse_history
from .online import FEEDS, MOODS, ProtocolError, mood_record, history_record, mobile_record
from .storage import Archive
from .media import download
from .parsing import photo_candidates
from .quality import needs_quality_check
from .exporting import export_archive
from .parallel import MediaPipeline
from .locking import collection_lock


class Stopped(Exception):
    pass


@dataclass(frozen=True)
class TrialLimits:
    scan_seconds: int = 600
    total_seconds: int = 1200
    requests: int = 120
    media: int = 300
    photo_bytes: int = 25 * 1024 * 1024

    def __post_init__(self):
        if min(self.scan_seconds, self.total_seconds, self.requests, self.media, self.photo_bytes) <= 0 or self.total_seconds < self.scan_seconds:
            raise ValueError('Invalid collection limits')


def run_trial(qq, root, stop, notify, media_workers=6, media_only=False, deep=False, backup_only=False, limits=None, resource_guard=None, media_max_pending=None, link_export_media=False):
    with collection_lock(Path(root) / qq.uin):
        return _run_trial(qq, root, stop, notify, media_workers, media_only, deep, backup_only, limits, resource_guard, media_max_pending, link_export_media)


def _run_trial(qq, root, stop, notify, media_workers=6, media_only=False, deep=False, backup_only=False, limits=None, resource_guard=None, media_max_pending=None, link_export_media=False):
    limits = limits or (TrialLimits(5400, 6000, 3600, 3000) if deep else TrialLimits())
    account = Path(root) / qq.uin
    archive = Archive(account)
    if deep:
        from .deep_history import load_state
        initial_deep = load_state(archive)
        deep_raw_before = initial_deep.get('raw_cards',0) if initial_deep and not initial_deep.get('complete') else 0
    archive.recover_jobs()
    job = archive.create_job('online-trial')
    archive.transition(job, 'running')
    started = time.monotonic()
    issues = []
    requests_count = 0
    raw_cards = 0
    visible_ids = set()
    def guard():
        if resource_guard and not resource_guard():
            stop.set()
        if stop.is_set() or time.monotonic() - started > limits.scan_seconds:
            raise Stopped()
    def media_guard():
        if resource_guard and not resource_guard():
            stop.set()
        if stop.is_set() or time.monotonic() - started > limits.total_seconds:
            raise Stopped()
    # Cookie jar chooses domain-scoped cookies; requests never follows media redirects.
    cookie_snapshot = qq.session.cookies.copy() if hasattr(qq, 'session') else None
    user_agent = qq.session.headers['User-Agent'] if hasattr(qq, 'session') else 'QzoneMemory'
    def media_fetch(url, client):
        media_guard()
        p = urlsplit(url)
        host = p.hostname or ''
        if p.scheme == 'http':
            url = 'https:' + url[5:]
            p = urlsplit(url)
        if (p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password or
            not any(host == d or host.endswith('.' + d) for d in ('qpic.cn', 'photo.store.qq.com'))):
            raise ValueError('unsupported_media_origin')
        for authenticated in (False, True):
            if authenticated:
                client.cookies.update(cookie_snapshot)
            else:
                client.cookies.clear()
            with client.get(url, headers={'User-Agent': user_agent,
                    'Referer': f'https://user.qzone.qq.com/{qq.uin}/'}, timeout=(5, 8),
                    stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    if not authenticated:
                        continue
                    raise ValueError('media_http_error')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    media_guard()
                    size += len(chunk)
                    if size > limits.photo_bytes:
                        raise ValueError('media_too_large')
                    chunks.append(chunk)
                return b''.join(chunks)
        raise ValueError('media_unavailable')
    def worker(mid):
        media_guard()
        local = Archive(account)
        try:
            with requests.Session() as client:
                photo_started = time.monotonic()
                def transport(url):
                    if time.monotonic() - photo_started > 35:
                        raise OSError('photo_time_budget')
                    try:
                        return media_fetch(url, client)
                    except requests.RequestException as exc:
                        # Let the downloader try the next candidate on network errors.
                        raise OSError('media_network_error') from exc
                return download(local, mid, transport)
        finally:
            local.close()
    saving_images = False
    def media_progress(done,total,saved,failed):
        if saving_images:
            notify('progress',dict(stage='media',done=done,total=total))
        notify('media',f'图片 {done}/{total}：本地可用 {saved}，失败 {failed}（{media_workers} 路并发）')
    pipeline = MediaPipeline(worker, media_progress,
        workers=media_workers, limit=limits.media, max_pending=media_max_pending, should_stop=stop.is_set)
    def enqueue_media():
        ids = [r['id'] for r in archive.db.execute("SELECT * FROM media ORDER BY rowid") if photo_candidates(json.loads(r['candidates'])) and needs_quality_check(r)]
        pipeline.enqueue(ids)
    def request(url, params):
        nonlocal requests_count
        guard()
        if requests_count >= limits.requests:
            raise Stopped()
        if stop.wait(0.8):
            raise Stopped()
        requests_count += 1
        return qq.data(url, params)
    def save(records, cursor):
        records = [r for r in records if r]
        archive.ingest(records, job, cursor)
        enqueue_media()
        times = sorted({r.get('published_at') for r in records if r.get('published_at')})
        interactions = sorted({int(r['interaction_time']) for r in records if str(r.get('interaction_time', '')).isdigit() and int(r['interaction_time']) > 0})
        label = ('最近一批发帖时间：' + times[0][:10] + ' 至 ' + times[-1][:10]) if times else ('最近一批互动时间：' + datetime.fromtimestamp(interactions[0], timezone.utc).strftime('%Y-%m-%d') + '（不是发帖时间，UTC）') if interactions else '最近一批时间未知或无新增记录'
        notify('batch', label)
        total = archive.db.execute('SELECT count(*) FROM posts').fetchone()[0]
        notify('status', f'已保存 {total} 条说说；本轮请求 {requests_count} 次')
    def history(params, phase):
        nonlocal raw_cards
        base = dict(uin=qq.uin, g_tk=qq.token, getappnotification=1, getnotifi=1,
                    has_get_key=0, offset=0, count=10, set=0, scope=1, useutf8=1,
                    outputhtmlfeed=1, begin_time=0, end_time=0, format='jsonp')
        base.update(params)
        data = request(FEEDS, base)
        body = data.get('data')
        if not isinstance(body, dict) or not isinstance(body.get('data'), list):
            raise ProtocolError('历史接口结构与已知版本不同，未将其当作空页')
        cards = body['data']
        raw_cards += len(cards)
        # Keep rejected cards for later ownership/parser investigation, not as posts.
        rawdir = account / 'evidence'
        rawdir.mkdir(exist_ok=True)
        (rawdir / f'{job}-{requests_count}.json').write_text(json.dumps(cards, ensure_ascii=False), encoding='utf-8')
        save([parse_history(c, qq.uin)[0] for c in cards], {'phase': phase, 'params': params})
        main = body.get('main')
        if main is not None and not isinstance(main, dict):
            raise ProtocolError('历史分页信息格式异常，未将其当作空页')
        return cards, (main or {}).get('hasMoreFeeds')
    state = 'completed'
    try:
        guard()
        enqueue_media()
        if not media_only:
            if not (deep and initial_deep and not initial_deep.get('complete')):
                notify('progress',dict(stage='visible'))
                notify('status', '登录成功，正在备份当前可见说说…')
                try:
                    pos = 0
                    for _ in range(30):
                        data = request(MOODS, dict(uin=qq.uin, g_tk=qq.token, ftype=0, sort=0,
                            pos=pos, num=30, replynum=10, callback='_preloadCallback',
                            code_version=1, format='jsonp', need_private_comment=1))
                        rows = data.get('msglist')
                        if rows is None and data.get('total') not in (0, '0'):
                            raise ProtocolError('当前说说接口缺少列表，不能认定没有数据')
                        if rows is not None and not isinstance(rows, list):
                            raise ProtocolError('说说列表格式异常')
                        rows = rows or []
                        total=data.get('total')
                        notify('progress',dict(stage='visible',done=pos+len(rows),total=int(total) if str(total).isdigit() and int(total)>0 else None))
                        records = [mood_record(m) for m in rows]
                        visible_ids.update(r['source_id'] for r in records if r)
                        save(records, {'phase': 'visible', 'pos': pos})
                        if len(rows) < 30:
                            break
                        pos += len(rows)
                    else:
                        issues.append('当前可见说说达到试跑 30 页上限，尚未完整遍历')
                except (ProtocolError, requests.RequestException, ValueError) as exc:
                    issues.append('当前说说阶段：' + (str(exc) if isinstance(exc, ProtocolError) else type(exc).__name__))
                notify('progress',dict(stage='mobile'))
                notify('status', '正在补充移动端互动中的多图与评论…')
                try:
                    attach = None
                    seen_cursors = set()
                    for page in range(5):
                        params = {'g_tk':qq.token, 'res_type':'1', 'refresh_type':'1' if page == 0 else '2', 'format':'json'}
                        if attach:
                            params['res_attach'] = attach
                        data = request('https://mobile.qzone.qq.com/get_feeds', params)
                        body = data.get('data') or {}
                        feeds = body.get('vFeeds')
                        if not isinstance(feeds, list):
                            raise ProtocolError('移动端互动结构异常，已跳过此来源')
                        save([mobile_record(f, qq.uin) for f in feeds], {'phase':'mobile', 'page':page})
                        attach = body.get('attachinfo')
                        if not feeds or not body.get('hasmore') or not attach or attach in seen_cursors:
                            break
                        seen_cursors.add(attach)
                except (ProtocolError, requests.RequestException, ValueError) as exc:
                    issues.append('移动端互动阶段：' + (str(exc) if isinstance(exc, ProtocolError) else type(exc).__name__))
            if deep:
                notify('progress',dict(stage='deep'))
                from .deep_history import scan
                scan(archive, qq, request, save, notify, job)
            elif not backup_only:
                notify('progress',dict(stage='history'))
                notify('status', '正在查找历史互动中仍保留的说说线索…')
                try:
                    offset = 0
                    for _ in range(30):
                        cards, more = history({'offset': offset}, 'history')
                        if not cards or more in (False, 0, '0'):
                            break
                        offset += len(cards)
                    # Small sparse probes and time windows supplement a prematurely empty page.
                    for offset in (100, 300, 800, 1500, 3000, 6000, 10000, 20000):
                        history({'offset': offset}, 'offset-probe')
                    year = datetime.now(timezone.utc).year
                    for y in range(year, 2004, -1):
                        begin = int(datetime(y, 1, 1, tzinfo=timezone.utc).timestamp())
                        end = int(datetime(y + 1, 1, 1, tzinfo=timezone.utc).timestamp()) - 1
                        history({'begin_time': begin, 'end_time': end}, f'year-{y}')
                    for variant in (1, 2, 3):
                        history({'set': variant}, f'set-{variant}')
                except (ProtocolError, requests.RequestException, ValueError) as exc:
                    issues.append('历史阶段：' + (str(exc) if isinstance(exc, ProtocolError) else type(exc).__name__))
        notify('status', '正在保存已发现的图片；失败位置将保留在导出中…')
        notify('status', '正在补全高清图片…' if media_only else '文字采集结束，正在等待并发图片下载…')
    except Stopped:
        state = 'paused'
        issues.append('用户停止或达到试跑预算，已导出已有成果')
    except Exception as exc:
        state = 'failed'
        # Persist stack locations only: no cookies, response bodies or local values.
        diagnostic = {'exception': type(exc).__module__+'.'+type(exc).__name__,
            'frames': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                       for f in traceback.extract_tb(exc.__traceback__)]}
        (account/'last-error.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
        issues.append(str(exc) if isinstance(exc, ProtocolError) else '处理异常：' + type(exc).__module__+'.'+type(exc).__name__+'；定位信息已保存到 last-error.json')
        notify('error', issues[-1])
        stop.set()
    finally:
        saving_images = True
        notify('progress',dict(stage='media'))
        notify('status', '正在停止并收尾图片任务…' if stop.is_set() else '正在等待图片任务收尾…')
        saved, failed, interrupted = pipeline.finish(cancel=stop.is_set())
        if interrupted:
            issues.append(f'图片队列有 {interrupted} 项中断或尚未处理，已保留待补全状态')
        if archive.db.execute("SELECT count(*) FROM media WHERE state!='saved'").fetchone()[0]:
            issues.append('仍有未保存媒体，参见 report.json；本轮最多调度 '+str(limits.media)+' 张')
        archive.transition(job, state)
        destination = Path(root) / 'exports' / f'{qq.uin}-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{job[:6]}'
        notify('progress',dict(stage='export'))
        export_archive(archive, destination, progress=lambda message: notify('status', message), link_media=link_export_media)
        summary = {'job': job, 'state': state, 'requests': requests_count, 'raw_history_cards': raw_cards,
                   'current_visible_this_run': len(visible_ids), 'mode': 'media' if media_only else 'deep' if deep else 'backup' if backup_only else 'collect', 'issues': issues,
                   'exported_posts': archive.db.execute('SELECT count(*) FROM posts').fetchone()[0],
                   'exported_photos': json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))['media'] - json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))['missing_media'],
                   'media_concurrency': media_workers, 'media_saved_this_run': saved, 'media_failed_this_run': failed,
                   'note': '历史来源不等于已确认删除；可能是当前列表遗漏或接口范围差异。年份窗是有限探测，不是完整历史覆盖。'}
        if state == 'failed':
            summary['diagnostic'] = diagnostic
        if deep:
            from .deep_history import load_state
            progress = load_state(archive)
            summary['deep_scan'] = {k:v for k,v in (progress or {}).items() if k!='tasks'}
            summary['raw_history_cards'] = (progress or {}).get('raw_cards',0)-deep_raw_before
        (destination / 'trial-report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        archive.close()
    return destination / 'index.html', summary
