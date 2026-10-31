import hashlib
import html
import json
import shutil
import tempfile
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from .timeline import timeline
from .activities import CATEGORIES
from .parsing import photo_candidates
from .richtext import rich_html, person_html
from pathlib import Path


def export_archive(archive, destination, progress=None, link_media=False, fetch_assets=False):
    """Snapshot rows and copy immutable verified media into a new offline directory."""
    progress = progress or (lambda message: None)
    progress("正在读取导出快照…")
    dest = Path(destination).expanduser().resolve()
    if dest == archive.root or dest.is_relative_to(archive.root):
        raise ValueError("Export outside the live archive")
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".qzone-export-", dir=dest.parent))
    try:
        with archive.db:
            archive.db.execute("BEGIN")
            posts = [
                dict(r)
                for r in archive.db.execute("SELECT * FROM posts ORDER BY published_at DESC,id")
            ]
            media = [
                dict(r)
                for r in archive.db.execute("SELECT * FROM media ORDER BY position")
                if photo_candidates(json.loads(r["candidates"]))
            ]
            sources = {}
            interactions = {}
            for row in archive.db.execute("SELECT post_id,source,payload FROM evidence"):
                sources.setdefault(row["post_id"], set()).add(row["source"])
                timestamp = json.loads(row["payload"]).get("interaction_time")
                if timestamp:
                    try:
                        dt = datetime.fromtimestamp(int(timestamp), ZoneInfo("Asia/Shanghai"))
                        interactions.setdefault(row["post_id"], set()).add(
                            dt.strftime("%Y-%m-%d %H:%M:%S")
                        )
                    except (ValueError, TypeError, OverflowError, OSError):
                        pass
            display_posts = {p["id"]: p for p in timeline(archive, limit=1000000)["posts"]}
            posts.sort(key=lambda p: (-display_posts[p["id"]]["sort_time"], p["id"]))
        report = []
        copied = 0
        for index, m in enumerate(media, 1):
            m.pop("candidates")  # Signed source URLs are excluded from public exports.
            relative = m["local_path"]
            valid = False
            if relative and not Path(relative).is_absolute() and m["state"] == "saved":
                source = (archive.root / relative).resolve()
                if source.is_relative_to(archive.root) and source.is_file():
                    digest = hashlib.sha256()
                    with source.open("rb") as stream:
                        while chunk := stream.read(256 * 1024):
                            digest.update(chunk)
                    valid = digest.hexdigest() == m["sha256"]
                    if valid:
                        target = stage / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            pass  # Repeated slots can point to one immutable media file.
                        elif link_media:
                            try:
                                os.link(source, target)
                            except OSError:
                                shutil.copyfile(source, target)
                        else:
                            shutil.copyfile(source, target)
                        copied += 1
            if not valid:
                m["local_path"] = None
                report.append({"media_id": m["id"], "reason": m["error"] or "not_saved_or_invalid"})
            progress(f"正在导出照片 {index}/{len(media)}；已写入 {copied} 张")
        progress(f"正在生成 HTML：{len(posts)} 条说说、{copied} 张照片…")
        if fetch_assets:
            progress("正在补齐离线头像与 QQ 表情…")
            from .export_assets import prepare_assets

            prepare_assets(
                [{"author": {"uin": archive.root.name}}] + list(display_posts.values()),
                archive.root.parent,
            )
        asset_prefix = "media" if fetch_assets else "assets"

        def resolve_emoji(code):
            source = archive.root.parent / "emojis" / (code + ".gif")
            if not source.is_file():
                return None
            target = stage / asset_prefix / "emoji" / (code + ".gif")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(source.read_bytes())
            return asset_prefix + "/emoji/" + code + ".gif"

        def rich(value):
            return rich_html(value or "", resolve_emoji)

        cards = []
        media_by_post = {}
        for m in media:
            media_by_post.setdefault(m["post_id"], []).append(m)
        for post in posts:
            photos = []
            for m in media_by_post.get(post["id"], []):
                photos.append(
                    f'<a href="{html.escape(m["local_path"], quote=True)}"><img loading="lazy" src="{html.escape(m["local_path"], quote=True)}"></a>'
                    if m["local_path"]
                    else "<span>图片尚未保存</span>"
                )
            display = display_posts[post["id"]]
            time_label = (
                CATEGORIES[display["category"]]
                + " · "
                + display["date"]
                + (" · ≈ 最早互动" if display["time_basis"] == "interaction" else "")
            )
            author_uin = str(
                display["author"].get("uin")
                or (archive.root.name if archive.root.name.isdigit() else "")
            )
            author = person_html(
                dict(uin=author_uin, nickname=display["author"].get("nickname") or "我的空间")
            )
            avatar = '<span class="avatar" title="头像未取得">忆</span>'
            if author_uin.isdigit():
                source = archive.root.parent / "avatars" / (author_uin + ".img")
                if source.is_file():
                    relative = asset_prefix + "/avatars/" + author_uin + ".jpg"
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(source, target)
                    avatar = (
                        '<img class="avatar" alt="头像" title="QQ：'
                        + author_uin
                        + '" src="'
                        + relative
                        + '">'
                    )

            social = ""
            if display["likes"]:
                social += (
                    '<div class="likes">♥ '
                    + "、".join(person_html(p) for p in display["likes"])
                    + " 觉得很赞</div>"
                )
            for comment in display["comments"]:
                social += (
                    '<div class="comment"><b>'
                    + person_html(comment)
                    + "：</b>"
                    + rich(comment.get("content") or "")
                    + "</div>"
                )
                for reply in comment.get("replies", []):
                    social += (
                        '<div class="comment"><b>'
                        + person_html(reply)
                        + " 回复：</b>"
                        + rich(reply.get("content") or "")
                        + "</div>"
                    )
            cards.append(
                '<article data-category="'
                + display["category"]
                + '"><div class="card-head">'
                + avatar
                + "<div><b>"
                + author
                + "</b><time>"
                + html.escape(time_label)
                + "</time></div></div><p>"
                + rich(display["content"])
                + '</p><div class="photos">'
                + "".join(photos)
                + "</div>"
                + social
                + "</article>"
            )
        template = Path(__file__).parent / "templates" / "offline.html"
        document = template.read_text(encoding="utf-8").replace(
            "<!-- ARCHIVE_CARDS -->", "".join(cards)
        )
        (stage / "index.html").write_text(document, encoding="utf-8")
        for name, value in [
            (
                "data.json",
                {
                    "posts": [
                        dict(
                            p,
                            category=display_posts[p["id"]]["category"],
                            author=display_posts[p["id"]]["author"],
                            comments=display_posts[p["id"]]["comments"],
                            likes=display_posts[p["id"]]["likes"],
                        )
                        for p in posts
                    ],
                    "media": media,
                },
            ),
            ("report.json", report),
            (
                "manifest.json",
                {
                    "version": 1,
                    "posts": len(posts),
                    "media": len(media),
                    "missing_media": len(report),
                },
            ),
        ]:
            (stage / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        stage.rename(dest)
        progress(f"导出完成：{len(posts)} 条说说、{copied} 张照片，{len(report)} 张未保存")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return dest
