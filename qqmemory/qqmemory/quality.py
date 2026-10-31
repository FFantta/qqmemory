"""High resolution QQ candidates, retaining every original URL as fallback."""

import hashlib
import json
import re
from urllib.parse import urlsplit
from .parsing import http_url


def candidates(values):
    high, original = [], []
    for value in values:
        url = (
            http_url(value.replace("\\/", "/").replace("&amp;", "&"))
            if isinstance(value, str)
            else None
        )
        if not url:
            continue
        host = urlsplit(url).hostname or ""
        if not any(host == d or host.endswith("." + d) for d in ("qpic.cn", "photo.store.qq.com")):
            continue
        if url.startswith("http://"):
            url = "https://" + url[7:]
        if "/psc" in url:
            hd = re.sub(r"/[msbn](?=&|$|\?)", "/q", url)
            if hd != url:
                high.append(hd)
            elif re.search(r"/q(?=&|$|\?)", url):
                high.append(url)
        original.append(url)
    return list(dict.fromkeys(high + original))


def attempts(values):
    """Bound requests, reserving a slot for an unmodified fallback."""
    urls = candidates(values)
    selected = urls[:4]
    fallback = next((u for u in urls if not re.search(r"/q(?=&|$|\?)", u)), None)
    if fallback and fallback not in selected:
        selected[-1] = fallback
    return selected


def fingerprint(values):
    return hashlib.sha256(json.dumps(candidates(values), ensure_ascii=True).encode()).hexdigest()


def needs_quality_check(row):
    return row["state"] != "saved" or row["quality_checked"] != fingerprint(
        json.loads(row["candidates"])
    )
