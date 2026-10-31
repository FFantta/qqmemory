"""Pure parsers for normalized imports and historical HTML media."""
import json
from html.parser import HTMLParser
from urllib.parse import urlsplit


def http_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith('//'):
        value = 'https:' + value
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        return None
    if '/ac/' in p.path:
        return None
    return value


class ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.photos = []

    def handle_starttag(self, tag, attrs):
        if tag != 'img':
            return
        a = dict(attrs)
        if any(x in (a.get('class', '') + ' ' + a.get('id', '')).lower()
               for x in ('avatar', 'icon', 'logo')):
            return
        candidates = []
        for key in ('truesrc', 'data-src', 'src'):
            url = http_url(a.get(key))
            host = urlsplit(url).hostname if url else ''
            if url and any(host == d or host.endswith('.' + d) for d in ('qpic.cn', 'photo.store.qq.com')) and url not in candidates:
                candidates.append(url)
        if candidates:
            self.photos.append(candidates)


def images_from_html(html):
    parser = ImageParser()
    parser.feed(html)
    return parser.photos


def unwrap_jsonp(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('(')
        end = text.rfind(')')
        callback = text[:start]
        if start < 1 or end < start or text[end + 1:].strip() not in ('', ';'):
            raise ValueError('Invalid JSONP envelope')
        if not all(c.isalnum() or c in '_.$' for c in callback):
            raise ValueError('Invalid JSONP callback')
        return json.loads(text[start + 1:end])


def photo_candidates(values):
    """Exclude known avatar/decorative domains without deleting original evidence."""
    for value in values:
        url = http_url(value)
        host = urlsplit(url).hostname if url else ''
        if url and any(host == d or host.endswith('.' + d) for d in ('qpic.cn', 'photo.store.qq.com')):
            return True
    return False
