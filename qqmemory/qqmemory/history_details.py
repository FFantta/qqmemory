"""Enrich persisted text evidence later, with resumable per-evidence commits."""

import json
import time
from bs4 import BeautifulSoup
from .social import social_from_tree


def pending_count(archive):
    return archive.db.execute(
        "SELECT count(*) FROM evidence WHERE json_extract(payload,'$.details_pending')=1"
    ).fetchone()[0]


def enrich(archive, notify, check_stop, seconds=120):
    total = pending_count(archive)
    deadline = time.monotonic() + seconds
    done = 0
    announced = 0
    notify("progress", dict(stage="details", done=0, total=total))
    cursor = archive.db.execute(
        "SELECT id,payload FROM evidence WHERE json_extract(payload,'$.details_pending')=1 ORDER BY id"
    )
    for row in cursor:
        check_stop()
        if time.monotonic() >= deadline:
            break
        record = json.loads(row["payload"])
        markup = record.get("evidence_html", "")
        record.update(social_from_tree(BeautifulSoup(markup, "html.parser"), markup))
        record.pop("details_pending", None)
        with archive.db:
            archive.db.execute(
                "UPDATE evidence SET payload=? WHERE id=?",
                (json.dumps(record, ensure_ascii=False), row["id"]),
            )
        done += 1
        if done % 10 == 0 or time.monotonic() - announced >= 1:
            notify("progress", dict(stage="details", done=done, total=total))
            announced = time.monotonic()
    notify("progress", dict(stage="details", done=done, total=total))
    return total - done
