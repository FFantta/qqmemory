"""QQ [em] tokens rendered as validated, credential-free cached image assets."""

import html
import re
import threading
import time
import uuid
from pathlib import Path
import requests
from .media import validate_image

CODE = re.compile(r"e\d{1,8}\Z")
TOKEN = re.compile(r"\[em\](e\d{1,8})\[/em\]", re.I)
_locks = {}
_guard = threading.Lock()
_failed = {}


def get_emoji(code, directory):
    code = code.lower()
    if not CODE.fullmatch(code):
        raise ValueError("Invalid QQ emoji code")
    directory = Path(directory)
    path = directory / (code + ".gif")
    key = str(path.resolve())
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if path.is_file():
            return path
        if time.monotonic() - _failed.get(key, float("-inf")) < 60:
            return None
        try:
            with requests.get(
                "https://qzonestyle.gtimg.cn/qzone/em/" + code + ".gif",
                timeout=(3, 5),
                allow_redirects=False,
                stream=True,
            ) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Emoji unavailable")
                data = response.raw.read(512 * 1024 + 1)
                if len(data) > 512 * 1024:
                    raise ValueError("Emoji too large")
                validate_image(data)
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / (code + "-" + uuid.uuid4().hex + ".part")
            try:
                temporary.write_bytes(data)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return path
        except (requests.RequestException, OSError, ValueError):
            _failed[key] = time.monotonic()
            return None


def emoji_html(text, resolve):
    """Escape text first; only application-generated relative image paths are used."""
    out, offset = [], 0
    for match in TOKEN.finditer(text or ""):
        out.append(html.escape(text[offset : match.start()]))
        relative = resolve(match.group(1).lower())
        if relative:
            out.append(
                '<img class="qq-emoji" alt="QQ表情" src="'
                + html.escape(relative, quote=True)
                + '">'
            )
        else:
            out.append('<span class="emoji-missing" title="表情资源暂不可用">〔表情〕</span>')
        offset = match.end()
    out.append(html.escape((text or "")[offset:]))
    return "".join(out)
