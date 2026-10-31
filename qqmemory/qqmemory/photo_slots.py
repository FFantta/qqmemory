"""Align partial notifications by image identity, never by their preview index."""

import json
import uuid
from .parsing import http_url
from .quality import candidates as expanded


def identity(values):
    return set(expanded(values))


def backup(archive, row, reason):
    archive.db.execute("""CREATE TABLE IF NOT EXISTS media_revisions(
        id INTEGER PRIMARY KEY,media_id TEXT NOT NULL,reason TEXT NOT NULL,payload TEXT NOT NULL)""")
    archive.db.execute(
        "INSERT INTO media_revisions(media_id,reason,payload) VALUES(?,?,?)",
        (row["id"], reason, json.dumps(dict(row), ensure_ascii=False)),
    )


def merge(archive, post_id, record):
    canonical = []
    for row in archive.db.execute(
        "SELECT payload FROM evidence WHERE post_id=? AND source='visible' ORDER BY id DESC",
        (post_id,),
    ):
        canonical = json.loads(row["payload"]).get("photos") or []
        if canonical:
            break
    old_rows = {
        r["position"]: dict(r)
        for r in archive.db.execute(
            "SELECT * FROM media WHERE post_id=? ORDER BY position", (post_id,)
        )
    }
    groups = list(enumerate(canonical)) if canonical else []
    if not canonical:
        # A notification can show just photo three, or a comment image.
        # Its position in that notification says nothing about the post order.
        groups = []
        pool = {pos: json.loads(row["candidates"]) for pos, row in old_rows.items()}
        for values in record.get("photos", []):
            keys = identity(values)
            if not keys:
                continue
            pos = next((p for p, v in pool.items() if keys & identity(v)), None)
            if pos is None:
                pos = max(pool, default=-1) + 1
            pool[pos] = list(dict.fromkeys(pool.get(pos, []) + values))
        groups = list(pool.items())
    for position, photo in groups:
        values = list(dict.fromkeys(u for value in photo if (u := http_url(value))))
        old = old_rows.get(position)
        if old:
            previous = json.loads(old["candidates"])
            if canonical:
                keys = identity(values)
                safe = [u for u in previous if identity([u]) & keys]
                # Legacy mixed pools cannot establish which image was saved.
                if old["local_path"] and len(safe) != len(previous):
                    backup(archive, old, "mixed_or_shifted_photo_candidates")
                    archive.db.execute(
                        "UPDATE media SET state='pending',local_path=NULL,sha256=NULL,error=NULL,width=NULL,height=NULL,byte_size=NULL,quality_checked=NULL WHERE id=?",
                        (old["id"],),
                    )
                values = list(dict.fromkeys(values + safe))
            else:
                values = list(dict.fromkeys(previous + values))
            if values != previous:
                archive.db.execute(
                    "UPDATE media SET candidates=? WHERE id=?", (json.dumps(values), old["id"])
                )
        else:
            archive.db.execute(
                "INSERT INTO media(id,post_id,position,candidates) VALUES(?,?,?,?)",
                (uuid.uuid4().hex, post_id, position, json.dumps(values)),
            )
    if canonical:
        for position, row in old_rows.items():
            if position >= len(canonical):
                backup(archive, row, "partial_preview_extra_slot")
                archive.db.execute("DELETE FROM media WHERE id=?", (row["id"],))
