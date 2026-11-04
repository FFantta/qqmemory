"""Read model: publish time first, earliest observed interaction as fallback."""

import json
import re
from .social import history_social
from .parsing import photo_candidates
from .richtext import tokens
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def timestamp(value):
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return int(value) if int(value) > 0 else None
        return int(datetime.fromisoformat(value).timestamp()) if value else None
    except (ValueError, TypeError, OverflowError):
        return None


def clean_content(value):
    lines = [line.strip() for line in (value or "").splitlines()]
    while lines and lines[0] in ("", ":", "："):
        lines.pop(0)
    return re.sub(r"^[：:]\s*", "", "\n".join(lines).strip(), count=1)


def timeline(
    archive, search="", year="", limit=30, offset=0, photos_only=False, category="", post_ids=None
):
    from .quality import fingerprint

    if post_ids is not None and not post_ids:
        return {"posts": [], "total": 0, "years": [], "category_counts": {}}
    args = tuple(post_ids or ())
    marks = ",".join("?" for _ in args)
    evidence_filter = f" WHERE post_id IN ({marks})" if post_ids is not None else ""
    post_filter = f" WHERE id IN ({marks})" if post_ids is not None else ""
    sources = {}
    for row in archive.db.execute(
        "SELECT post_id,source,payload FROM evidence" + evidence_filter, args
    ):
        record = json.loads(row["payload"])
        if (
            record.get("evidence_html")
            and record.get("social_version") != 2
            and not record.get("details_pending")
        ):
            record.update(history_social(record["evidence_html"]))
        sources.setdefault(row["post_id"], []).append(record)
    media_by_post = {}
    for row in archive.db.execute(
        "SELECT post_id,id,state,position,error,candidates,width,height,sha256,quality_checked FROM media"
        + evidence_filter
        + " ORDER BY post_id,position",
        args,
    ):
        if photo_candidates(json.loads(row["candidates"])):
            item = dict(row)
            item["quality_verified"] = item.pop("quality_checked") == fingerprint(
                json.loads(item["candidates"])
            )
            pid = item.pop("post_id")
            item.pop("candidates")
            media_by_post.setdefault(pid, []).append(item)
    result = []
    available_years = set()
    counts = dict.fromkeys(("posts", "interactions", "gifts", "blogs"), 0)
    for row in archive.db.execute("SELECT * FROM posts" + post_filter, args):
        post = dict(row)
        post["content"] = clean_content(post["content"])
        post["content_tokens"] = tokens(post["content"])
        records = sources.get(post["id"], [])
        post["is_related"] = any(
            r.get("relation") in ("mentioned", "participated") for r in records
        )
        post["category"] = next(
            (r["category"] for r in records if r.get("category") in counts),
            "interactions" if post["is_related"] else "posts",
        )
        counts[post["category"]] += 1
        if search and search not in post["content"]:
            continue
        if category and post["category"] != category:
            continue
        post["title"] = next((r["title"] for r in records if r.get("title")), "")
        post["notification_actions"] = sorted(
            set(r["notification_action"] for r in records if r.get("notification_action"))
        )
        published = timestamp(post["published_at"])
        times = [t for r in records if (t := timestamp(r.get("interaction_time")))]
        effective = published or (min(times) if times else None)
        date = datetime.fromtimestamp(effective, ZoneInfo("Asia/Shanghai")) if effective else None
        if date:
            available_years.add(str(date.year))
        if photos_only and not media_by_post.get(post["id"]):
            continue
        if year and (not date or str(date.year) != str(year)):
            continue
        post.update(
            sort_time=effective or 0,
            date=date.strftime("%Y年%m月%d日 %H:%M") if date else "时间待确认",
            year=str(date.year) if date else "未知",
            time_basis="published" if published else "interaction" if times else "unknown",
        )
        post["author"] = next((r["author"] for r in records if r.get("author")), {})
        likes, comments = {}, {}
        for record in records:
            for like in record.get("likes", []):
                likes[str(like.get("uin") or like.get("nickname"))] = like
            for comment in record.get("comments", []):
                comments[
                    (str(comment.get("uin")), comment.get("content"), str(comment.get("time")))
                ] = comment
        post["social_available"] = any("comments" in r or "likes" in r for r in records)
        post["likes"] = list(likes.values())
        post["like_count"] = max([len(likes)] + [int(r.get("like_count") or 0) for r in records])
        post["comments"] = [
            dict(
                c,
                content_tokens=tokens(c.get("content")),
                replies=[
                    dict(r, content_tokens=tokens(r.get("content"))) for r in c.get("replies", [])
                ],
            )
            for c in comments.values()
        ]
        post["comment_count"] = max(
            [len(comments)] + [int(r.get("comment_count") or 0) for r in records]
        )
        post["media"] = media_by_post.get(post["id"], [])
        result.append(post)
    result.sort(key=lambda p: (-p["sort_time"], p["id"]))
    years = sorted(available_years, reverse=True)
    return {
        "posts": result[offset : offset + limit],
        "total": len(result),
        "years": years,
        "category_counts": counts,
    }
