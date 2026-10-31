"""Reuse a credential-free view until the SQLite database or WAL changes."""
import threading
from pathlib import Path
from .timeline import timeline
from .statistics import archive_statistics


def revision(root):
    values = []
    for name in ('archive.sqlite3', 'archive.sqlite3-wal'):
        try:
            stat = (Path(root) / name).stat()
            values.append((stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            values.append(None)
    return tuple(values)


class ArchiveView:
    def __init__(self):
        self.lock = threading.RLock()
        self.key = None
        self.snapshot = None
        self.stats = None

    def page(self, archive, search='', year='', limit=30, offset=0, photos_only=False, category=''):
        with self.lock:
            key = (str(archive.root.resolve()), revision(archive.root))
            if key != self.key:
                with archive.db:
                    archive.db.execute('BEGIN')
                    snapshot = timeline(archive, limit=1000000000)
                    stats = archive_statistics(archive.root/'archive.sqlite3')
                self.snapshot, self.stats, self.key = snapshot, stats, key
            posts = [p for p in self.snapshot['posts']
                     if (not search or search in p['content'])
                     and (not category or p['category'] == category)]
            years = sorted({p['year'] for p in posts if p['year'] != '未知'}, reverse=True)
            if photos_only:
                posts = [p for p in posts if p['media']]
            if year:
                posts = [p for p in posts if p['year'] == str(year)]
            return dict(posts=posts[offset:offset+limit], total=len(posts), years=years,
                        category_counts=self.snapshot['category_counts'], stats=self.stats)


def normalize_social(archive):
    """One-time local parser migration, under the caller's collection lock."""
    import json
    from .social import history_social
    changed = []
    for row in archive.db.execute('SELECT id,payload FROM evidence'):
        record = json.loads(row['payload'])
        if record.get('evidence_html') and record.get('social_version') != 2:
            record.update(history_social(record['evidence_html']))
            changed.append((json.dumps(record, ensure_ascii=False), row['id']))
    if changed:
        with archive.db:
            archive.db.executemany('UPDATE evidence SET payload=? WHERE id=?', changed)
    return len(changed)
