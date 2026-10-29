"""Credential-free archive counters for the native progress window."""
import json
import sqlite3
from collections import Counter
from .parsing import photo_candidates
from datetime import datetime
from zoneinfo import ZoneInfo


def archive_statistics(path):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=1)
    try:
        posts, dated, earliest, latest = db.execute(
            'SELECT count(*),count(published_at),min(published_at),max(published_at) FROM posts').fetchone()
        states = Counter(state for state, candidates in db.execute('SELECT state,candidates FROM media') if photo_candidates(json.loads(candidates)))
        interactions = []
        for (payload,) in db.execute("SELECT payload FROM evidence WHERE source IN ('history','mobile','deep-history','related-history')"):
            try:
                value = int(json.loads(payload).get('interaction_time') or 0)
                if value > 0:
                    interactions.append(value)
            except (ValueError, TypeError):
                pass
        def display(value):
            if not value:
                return '未知'
            dt = datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai')) if isinstance(value, int) else datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai'))
            return dt.strftime('%Y-%m-%d')
        return dict(posts=posts, unknown_time=posts-dated,
                    earliest=display(earliest), latest=display(latest),
                    earliest_interaction=display(min(interactions)) if interactions else '未知',
                    photos_saved=states.get('saved', 0), photos_found=sum(states.values()),
                    photos_failed=states.get('failed', 0), photos_pending=states.get('pending', 0))
    finally:
        db.close()


def format_statistics(data):
    return (f'已入库说说 {data["posts"]} 条（时间未知 {data["unknown_time"]} 条）\n'
            f'已知发帖范围：{data["earliest"]} 至 {data["latest"]}（北京时间）\n'
            f'最早历史互动：{data["earliest_interaction"]}（不是原帖时间）\n'
            f'照片已保存 {data["photos_saved"]}/{data["photos_found"]} 张 · '
            f'失败 {data["photos_failed"]} · 待处理 {data["photos_pending"]}')
