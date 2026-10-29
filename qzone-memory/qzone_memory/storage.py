import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from .parsing import http_url


def now():
    return datetime.now(timezone.utc).isoformat()


class Archive:
    """One database per account archive; short, transactional batch writes."""
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'archive.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS posts(
          id TEXT PRIMARY KEY, source_id TEXT UNIQUE, content TEXT NOT NULL,
          published_at TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(
          id INTEGER PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id),
          source TEXT NOT NULL, record_key TEXT NOT NULL, payload TEXT NOT NULL,
          UNIQUE(source,record_key));
        CREATE TABLE IF NOT EXISTS media(
          id TEXT PRIMARY KEY, post_id TEXT NOT NULL REFERENCES posts(id),
          position INTEGER NOT NULL, candidates TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', local_path TEXT, sha256 TEXT,
          error TEXT, UNIQUE(post_id,position));
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
          cursor TEXT, batches INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS scan_checkpoints(name TEXT PRIMARY KEY, payload TEXT NOT NULL);
        PRAGMA user_version=1;
        ''')

        columns = {r[1] for r in self.db.execute('PRAGMA table_info(media)')}
        for name, kind in [('width','INTEGER'),('height','INTEGER'),('byte_size','INTEGER'),('quality_checked','TEXT')]:
            if name not in columns:
                self.db.execute(f'ALTER TABLE media ADD COLUMN {name} {kind}')
        self.db.execute('PRAGMA user_version=2')
        self.db.commit()

    def close(self):
        self.db.close()

    def create_job(self, kind='import'):
        key = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO jobs(id,kind,state) VALUES(?,?,?)',
                            (key, kind, 'queued'))
        return key

    def transition(self, key, state):
        allowed = {'queued': {'running', 'cancelled'},
                   'running': {'paused', 'waiting_login', 'cooldown', 'completed', 'failed', 'cancelled'},
                   'paused': {'running', 'cancelled'}, 'waiting_login': {'running', 'cancelled'},
                   'cooldown': {'running', 'cancelled'}, 'failed': {'running', 'cancelled'}}
        with self.db:
            row = self.db.execute('SELECT state FROM jobs WHERE id=?', (key,)).fetchone()
            if not row or state not in allowed.get(row['state'], set()):
                raise ValueError('Invalid job transition')
            self.db.execute('UPDATE jobs SET state=? WHERE id=?', (state, key))

    def recover_jobs(self):
        with self.db:
            return self.db.execute("UPDATE jobs SET state='paused' WHERE state='running'").rowcount

    def ingest(self, records, job_id=None, cursor=None):
        """Atomic records + checkpoint. Input must contain credential-free normalized evidence."""
        with self.db:
            if job_id:
                job = self.db.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()
                if not job or job['state'] != 'running':
                    raise ValueError('Job must be running')
            for record in records:
                source = record['source']
                record_key = str(record['record_key'])
                # Stable true IDs may merge sources. Text alone never establishes identity.
                sid = str(record['source_id']) if record.get('source_id') else None
                prior = self.db.execute('SELECT post_id FROM evidence WHERE source=? AND record_key=?',
                                        (source, record_key)).fetchone()
                post = self.db.execute('SELECT id FROM posts WHERE source_id=?', (sid,)).fetchone() if sid else None
                pid = prior['post_id'] if prior else post['id'] if post else uuid.uuid4().hex
                timestamp = record.get('published_at')
                if timestamp:
                    dt = datetime.fromisoformat(timestamp)
                    if dt.tzinfo is None:
                        raise ValueError('Publication time must include timezone')
                content = record.get('content', '')
                self.db.execute('INSERT OR IGNORE INTO posts VALUES(?,?,?,?,?)',
                                (pid, sid, content, timestamp, now()))
                self.db.execute('UPDATE posts SET content=CASE WHEN length(?)>length(content) THEN ? ELSE content END, published_at=COALESCE(published_at,?) WHERE id=?',
                                (content, content, timestamp, pid))
                self.db.execute('INSERT INTO evidence(post_id,source,record_key,payload) VALUES(?,?,?,?) ON CONFLICT(source,record_key) DO UPDATE SET payload=excluded.payload WHERE evidence.post_id=excluded.post_id',
                                (pid, source, record_key, json.dumps(record, ensure_ascii=False)))
                from .photo_slots import merge
                merge(self, pid, record)
            if job_id:
                self.db.execute('UPDATE jobs SET cursor=?,batches=batches+1 WHERE id=?', (json.dumps(cursor), job_id))

    def posts(self, search='', limit=50, offset=0):
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError('Invalid pagination')
        rows = self.db.execute('SELECT * FROM posts WHERE instr(content,?)>0 ORDER BY published_at DESC,id LIMIT ? OFFSET ?',
                               (search, limit, offset)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['media'] = [dict(m) for m in self.db.execute('SELECT * FROM media WHERE post_id=? ORDER BY position', (row['id'],))]
            for m in item['media']:
                m['candidates'] = json.loads(m['candidates'])
            result.append(item)
        return result
