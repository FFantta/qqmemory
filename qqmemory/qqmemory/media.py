"""Bounded HTTPS downloads; no credentials or redirects to arbitrary hosts."""
import hashlib
import io
import json
import os
import urllib.error
import requests
from pathlib import Path
from urllib.parse import urlsplit


def fetch(url, max_bytes=25 * 1024 * 1024):
    p = urlsplit(url)
    # Deliberately narrow initial media policy. Expand only with verified samples.
    host = p.hostname or ''
    if (p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password
            or not any(host == d or host.endswith('.' + d) for d in ('qpic.cn', 'photo.store.qq.com'))):
        raise ValueError('unsupported_media_origin')
    try:
        with requests.get(url, headers={'User-Agent': 'QzoneMemory/0.1',
                'Referer': 'https://user.qzone.qq.com/'}, timeout=(5, 8),
                stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError('media_http_error')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('response_too_large')
                chunks.append(chunk)
            return b''.join(chunks)
    except requests.RequestException as exc:
        raise OSError('media_network_error') from exc


def validate_image(data):
    # Actual decode is required; file signatures alone accept corrupt images.
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        fmt = image.format
        size = image.size
        if fmt not in ('JPEG', 'PNG', 'GIF', 'WEBP'):
            raise ValueError('unsupported_image')
        if image.width * image.height > 40_000_000:
            raise ValueError('image_too_large')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
    # Known heuristic, not proof that every other image is genuine.
    if fmt == 'GIF' and size == (340, 320) and len(data) == 2038:
        raise ValueError('known_placeholder')
    return {'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif', 'WEBP': 'webp'}[fmt]


def image_size(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def download(archive, media_id, transport=fetch):
    from .quality import attempts, fingerprint
    row = archive.db.execute('SELECT * FROM media WHERE id=?', (media_id,)).fetchone()
    if row is None:
        raise KeyError(media_id)
    urls = attempts(json.loads(row['candidates']))
    key = fingerprint(json.loads(row['candidates']))
    best = None
    best_area = 0
    cached = False
    if row['local_path']:
        path = (archive.root / row['local_path']).resolve()
        if path.is_relative_to(archive.root) and path.is_file():
            try:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() == row['sha256']:
                    validate_image(data)
                    width, height = image_size(data)
                    best_area = width * height
                    cached = True
                    if row['quality_checked'] == key:
                        return row['local_path']
            except (OSError, ValueError):
                pass
    errors = []
    for url in urls[:4]:
        try:
            data = transport(url)
            ext = validate_image(data)
            width, height = image_size(data)
            if width * height > best_area:
                best = (data, ext, width, height)
                best_area = width * height
        except (OSError, ValueError, urllib.error.URLError) as exc:
            errors.append(type(exc).__name__)
    if best is not None:
        data, ext, width, height = best
        digest = hashlib.sha256(data).hexdigest()
        # Content-addressed filenames preserve old files and immutable exports.
        relative = f'media/{media_id}-{digest[:12]}.{ext}'
        path = archive.root / relative
        path.parent.mkdir(exist_ok=True)
        part = path.with_suffix(path.suffix + '.part')
        try:
            with part.open('wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            part.replace(path)
            with archive.db:
                archive.db.execute("UPDATE media SET state='saved',local_path=?,sha256=?,error=NULL,width=?,height=?,byte_size=?,quality_checked=? WHERE id=?",
                                   (relative, digest, width, height, len(data), key, media_id))
        finally:
            part.unlink(missing_ok=True)
        return relative
    if cached:
        with archive.db:
            archive.db.execute('UPDATE media SET width=?,height=?,byte_size=?,quality_checked=? WHERE id=?',
                               (*image_size((archive.root / row['local_path']).read_bytes()), (archive.root / row['local_path']).stat().st_size, key, media_id))
        return row['local_path']
    with archive.db:
        archive.db.execute("UPDATE media SET state='failed',error=?,local_path=NULL,sha256=NULL,quality_checked=? WHERE id=?",
                           (','.join(errors) or 'no_candidates', key, media_id))
    return None
