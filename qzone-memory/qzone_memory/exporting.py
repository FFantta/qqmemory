import hashlib
import html
import json
import shutil
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from .timeline import timeline
from .activities import CATEGORIES
from .parsing import photo_candidates
from .richtext import rich_html, person_html
from pathlib import Path


def export_archive(archive, destination, progress=None):
    """Snapshot rows and copy immutable verified media into a new offline directory."""
    progress = progress or (lambda message: None)
    progress('正在读取导出快照…')
    dest = Path(destination).expanduser().resolve()
    if dest == archive.root or dest.is_relative_to(archive.root):
        raise ValueError('Export outside the live archive')
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.qzone-export-', dir=dest.parent))
    try:
        with archive.db:
            archive.db.execute('BEGIN')
            posts = [dict(r) for r in archive.db.execute('SELECT * FROM posts ORDER BY published_at DESC,id')]
            media = [dict(r) for r in archive.db.execute('SELECT * FROM media ORDER BY position') if photo_candidates(json.loads(r['candidates']))]
            evidence = [dict(r) for r in archive.db.execute('SELECT post_id,source,payload FROM evidence')]
            display_posts = {p['id']: p for p in timeline(archive, limit=1000000)['posts']}
            posts.sort(key=lambda p: (-display_posts[p['id']]['sort_time'], p['id']))
        report = []
        copied = 0
        for index, m in enumerate(media, 1):
            m.pop('candidates')  # Signed source URLs are excluded from public exports.
            relative = m['local_path']
            valid = False
            if relative and not Path(relative).is_absolute() and m['state'] == 'saved':
                source = (archive.root / relative).resolve()
                if source.is_relative_to(archive.root) and source.is_file():
                    data = source.read_bytes()
                    valid = hashlib.sha256(data).hexdigest() == m['sha256']
                    if valid:
                        target = stage / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                        copied += 1
            if not valid:
                m['local_path'] = None
                report.append({'media_id': m['id'], 'reason': m['error'] or 'not_saved_or_invalid'})
            progress(f'正在导出照片 {index}/{len(media)}；已写入 {copied} 张')
        progress(f'正在生成 HTML：{len(posts)} 条说说、{copied} 张照片…')
        sources = {}
        interactions = {}
        for row in evidence:
            sources.setdefault(row['post_id'], set()).add(row['source'])
            timestamp = json.loads(row['payload']).get('interaction_time')
            if timestamp:
                try:
                    dt = datetime.fromtimestamp(int(timestamp), ZoneInfo('Asia/Shanghai'))
                    interactions.setdefault(row['post_id'], set()).add(dt.strftime('%Y-%m-%d %H:%M:%S'))
                except (ValueError, TypeError, OverflowError, OSError):
                    pass
        def resolve_emoji(code):
            source = archive.root.parent / 'emojis' / (code + '.gif')
            if not source.is_file():
                return None
            target = stage / 'assets' / 'emoji' / (code + '.gif')
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(source.read_bytes())
            return 'assets/emoji/' + code + '.gif'
        def rich(value):
            return rich_html(value or '', resolve_emoji)
        cards = []
        for post in posts:
            photos = []
            for m in media:
                if m['post_id'] != post['id']:
                    continue
                photos.append(f'<a href="{html.escape(m["local_path"], quote=True)}"><img loading="lazy" src="{html.escape(m["local_path"], quote=True)}"></a>'
                              if m['local_path'] else '<span>图片尚未保存</span>')
            display = display_posts[post['id']]
            time_label = CATEGORIES[display['category']] + ' · ' + display['date'] + (' · ≈ 最早互动' if display['time_basis'] == 'interaction' else '')
            author = person_html(dict(uin=display['author'].get('uin') or (archive.root.name if archive.root.name.isdigit() else ''), nickname=display['author'].get('nickname') or '我的空间'))
            social = ''
            if display['likes']:
                social += '<div class="likes">♥ ' + '、'.join(person_html(p) for p in display['likes']) + ' 觉得很赞</div>'
            for comment in display['comments']:
                social += '<div class="comment"><b>' + person_html(comment) + '：</b>' + rich(comment.get('content') or '') + '</div>'
                for reply in comment.get('replies',[]):
                    social += '<div class="comment"><b>' + person_html(reply) + ' 回复：</b>' + rich(reply.get('content') or '') + '</div>'
            cards.append('<article data-category="' + display['category'] + '"><div class="card-head"><span class="avatar">忆</span><div><b>' + author + '</b><time>' + html.escape(time_label) + '</time></div></div><p>' + rich(display['content']) + '</p><div class="photos">' + ''.join(photos) + '</div>' + social + '</article>')
        document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>空间记忆 · 离线档案</title><style>body{max-width:820px;margin:40px auto;padding:24px;font-family:system-ui;background:#f7f5fa;color:#44364f}article{padding:28px;margin:22px 0;background:white;border-radius:18px;border:1px solid #eee7f3}.card-head{display:flex;align-items:center;gap:12px;font-size:13px}.avatar{display:grid;place-items:center;width:40px;height:40px;background:#e9dff3;border-radius:50%;color:#9875b4}time{display:block;color:#ac9cbb;font-size:11px;margin-top:6px}.likes,.comment{background:#faf8fc;font-size:12px;padding:10px;margin-top:8px;color:#9881b0}p{white-space:pre-wrap;overflow-wrap:anywhere}.photos{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}img{width:100%;height:100%;object-fit:cover}.photos>a,.photos>span{aspect-ratio:1;display:block;overflow:hidden;border-radius:10px;background:#f3eff8}.photos>span{display:grid;place-items:center;font-size:12px;color:#ad9dbf}.qq-emoji{width:1.45em;height:1.45em;vertical-align:-.28em;object-fit:contain;display:inline-block}.emoji-missing{color:#a897b9}input{padding:12px;width:80%}</style>
<h1>空间记忆 · 离线年鉴</h1><p>按时间从新到旧 · ≈ 表示以最早互动时间代替缺失的发布时间。照片点击查看原始文件。</p><select id="category"><option value="">全部回忆</option><option value="posts">我的说说</option><option value="interactions">与他人互动</option><option value="gifts">礼物与游戏</option><option value="blogs">我的日志</option></select><input id="search" placeholder="搜索正文与评论">'''
        document += ''.join(cards)
        document += """<script>function filter(){const q=document.getElementById('search').value,c=document.getElementById('category').value;for(const a of document.querySelectorAll('article'))a.hidden=!(a.textContent.includes(q)&&(!c||a.dataset.category===c))}document.getElementById('search').oninput=filter;document.getElementById('category').onchange=filter;</script></html>"""
        (stage / 'index.html').write_text(document, encoding='utf-8')
        for name, value in [('data.json', {'posts': [dict(p, category=display_posts[p['id']]['category'], author=display_posts[p['id']]['author'], comments=display_posts[p['id']]['comments'], likes=display_posts[p['id']]['likes']) for p in posts], 'media': media}), ('report.json', report),
                            ('manifest.json', {'version': 1, 'posts': len(posts), 'media': len(media), 'missing_media': len(report)})]:
            (stage / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        stage.rename(dest)
        progress(f'导出完成：{len(posts)} 条说说、{copied} 张照片，{len(report)} 张未保存')
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return dest
