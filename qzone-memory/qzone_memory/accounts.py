"""Local archive discovery; selecting an archive never authenticates with QQ."""
import json
import sqlite3
from pathlib import Path


def profiles(root):
    result=[]
    for folder in sorted(Path(root).iterdir()):
        if not folder.name.isdigit() or not (folder/'archive.sqlite3').is_file():
            continue
        try:
            profile=json.loads((folder/'profile.json').read_text()) if (folder/'profile.json').exists() else {}
            db=sqlite3.connect(f'file:{folder / "archive.sqlite3"}?mode=ro',uri=True,timeout=2)
            try:
                posts=db.execute('SELECT count(*) FROM posts').fetchone()[0]
                photos=db.execute("SELECT count(*) FROM media WHERE state='saved'").fetchone()[0]
            finally:db.close()
            modified=max(p.stat().st_mtime for p in (folder/'archive.sqlite3',folder/'archive.sqlite3-wal') if p.exists())
            result.append(dict(uin=folder.name,nickname=profile.get('nickname') or folder.name,posts=posts,photos=photos,modified=modified))
        except (OSError,ValueError,sqlite3.Error):
            continue
    return result


def remember(root,uin):
    path=Path(root)/'selected-account.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps({'uin':uin}))
    temp.replace(path)


def selected(root,choices):
    try:
        value=json.loads((Path(root)/'selected-account.json').read_text()).get('uin')
        if value in choices:return value
    except (OSError,ValueError):pass
    return choices[0] if choices else None
