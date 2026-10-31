"""QQ protocol adapters. Credentials exist only in this session's memory."""
import hashlib
import html
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin, parse_qs, urlunsplit
import json5
import requests
from .parsing import images_from_html, http_url
from .social import visible_social, history_social

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
REFERER = 'https://xui.ptlogin2.qq.com/cgi-bin/xlogin?appid=549000912&daid=5&s_url=https%3A%2F%2Fuser.qzone.qq.com%2F'
FEEDS = 'https://user.qzone.qq.com/proxy/domain/ic2.qzone.qq.com/cgi-bin/feeds/feeds2_html_pav_all'
MOODS = 'https://user.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6'


class ProtocolError(RuntimeError):
    pass


def hash33(value, seed=0):
    for character in value:
        seed = (seed * 33 + ord(character)) & 0x7fffffff
    return seed


def decode_response(text):
    text = text.strip().lstrip('\ufeff')
    if text.startswith('{'):
        payload = text
    else:
        match = re.fullmatch(r'[\w.$]+\s*\((.*)\)\s*;?', text, re.S)
        if not match:
            raise ProtocolError('接口返回了非数据页面，可能需要重新登录或遇到访问限制')
        payload = match.group(1)
    try:
        value = json.loads(payload)
    except ValueError:
        try:
            value = json5.loads(payload)
        except ValueError:
            # JS undefined is permitted only outside quoted strings.
            tokens = re.compile(r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|\bundefined\b", re.S)
            cleaned = tokens.sub(lambda m: m.group(1) if m.group(1) else 'null', payload)
            try:
                value = json5.loads(cleaned)
            except ValueError:
                raise ProtocolError('QQ 返回的数据无法解析；该来源未被当作空记录') from None
    if not isinstance(value, dict):
        raise ProtocolError('接口数据结构异常')
    if value.get('code', 0) not in (0, '0'):
        error = ProtocolError(f'QQ 接口拒绝请求（code={value.get("code")}），已保存内容仍会导出')
        error.code = value.get('code')
        error.remote_message = str(value.get('message') or value.get('msg') or '')[:200]
        raise error
    return value


class QQSession:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': UA, 'Referer': REFERER})
        self.uin = None
        self.token = None

    def get(self, url, params=None, limit=12*1024*1024):
        for _ in range(8):
            check_cancel = getattr(self, 'cancel_check', lambda: None)
            check_cancel()
            p = urlsplit(url)
            # QQ check_sig can return an old HTTP landing URL. Upgrade before
            # any request; never send credentials over cleartext HTTP.
            if p.scheme == 'http' and p.port in (None, 80) and (p.hostname or '').endswith('.qq.com') and not p.username and not p.password:
                url = urlunsplit(('https', p.hostname, p.path, p.query, p.fragment))
                p = urlsplit(url)
            if p.scheme != 'https' or p.port not in (None, 443) or p.username or p.password or not (p.hostname == 'qq.com' or (p.hostname or '').endswith('.qq.com')):
                raise ProtocolError('登录跳转目标不在可信 QQ 域名内')
            with self.session.get(url, params=params, timeout=(10, 20), allow_redirects=False, stream=True) as response:
                check_cancel()
                if response.is_redirect:
                    url = urljoin(response.url, response.headers['Location'])
                    params = None
                    continue
                response.raise_for_status()
                parts, size = [], 0
                for block in response.iter_content(65536):
                    check_cancel()
                    size += len(block)
                    if size > limit:
                        raise ProtocolError('接口响应超过大小限制')
                    parts.append(block)
                return b''.join(parts)
        raise ProtocolError('QQ 登录跳转次数异常')

    def qr(self):
        self.session.cookies.clear()
        data = self.get('https://ssl.ptlogin2.qq.com/ptqrshow',
                        {'appid': '549000912', 'e': 2, 'l': 'M', 's': 3, 'd': 72,
                         'v': 4, 't': time.time(), 'daid': 5})
        sig = next((c.value for c in self.session.cookies if c.name == 'qrsig'), None)
        if not sig:
            raise ProtocolError('未取得二维码会话，请重试')
        self.qr_token = hash33(sig)
        return data

    def poll(self):
        body = self.get('https://ssl.ptlogin2.qq.com/ptqrlogin', {
            'u1': 'https://user.qzone.qq.com/', 'ptqrtoken': self.qr_token,
            'ptredirect': 0, 'h': 1, 't': 1, 'g': 1, 'from_ui': 1,
            'ptlang': 2052, 'action': f'0-0-{int(time.time()*1000)}',
            'js_ver': '24082614', 'js_type': 1, 'login_sig': '',
            'pt_uistyle': 40, 'aid': '549000912', 'daid': 5, 'o1v': 1}).decode('utf-8', errors='replace')
        match = re.fullmatch(r'\s*ptuiCB\((.*)\)\s*;?\s*', body, re.S)
        if not match:
            raise ProtocolError('QQ 扫码接口返回异常，请刷新二维码')
        args = json5.loads('[' + match.group(1) + ']')
        code = str(args[0])
        if code in ('66', '67', '68', '65'):
            return code
        if code != '0':
            raise ProtocolError(f'扫码登录失败（code={code}）')
        redirect = args[2]
        self.get(redirect)
        values = {c.name: c.value for c in self.session.cookies if c.domain.endswith('qq.com')}
        uin = parse_qs(urlsplit(redirect).query).get('uin', [values.get('uin', '')])[0].lstrip('o')
        if not uin.isdigit():
            raise ProtocolError('未识别到已登录账号')
        key = values.get('p_skey')
        if not key:
            raise ProtocolError('手机已确认，但 QQ 未返回空间会话密钥，请刷新后重试')
        self.nickname = args[5] if len(args) > 5 else ''
        self.uin, self.token = uin, hash33(key, 5381)
        self.session.headers['Referer'] = f'https://user.qzone.qq.com/{uin}/'
        return 'ok'

    def data(self, url, params):
        return decode_response(self.get(url, params).decode('utf-8', errors='replace'))

    def close(self):
        self.session.cookies.clear()
        self.session.close()


def mood_record(mood):
    tid = str(mood.get('tid') or '')
    if not tid:
        return None
    photos = []
    for pic in mood.get('pic') or []:
        candidates = []
        for raw_key in ('rawUrl','origin_url','originalUrl'):
            if (url := http_url(pic.get(raw_key))) and url not in candidates:
                candidates.append(url)
        for key in ('-1','0'):
            bp = pic.get('busi_param') or {}
            if isinstance(bp,dict) and (url := http_url(bp.get(key))) and url not in candidates:
                candidates.append(url)
        for item in (pic.get('photourl') or {}).values() if isinstance(pic.get('photourl'),dict) else []:
            if isinstance(item,dict) and (url := http_url(item.get('url'))) and url not in candidates:
                candidates.append(url)
        for key in ('rawUrl', 'origin_url', 'originalUrl', 'url3', 'url2', 'url1', 'url', 'smallurl'):
            value = pic.get(key)
            if isinstance(value, dict):
                value = value.get('url')
            if (url := http_url(value)) and url not in candidates:
                candidates.append(url)
        if candidates:
            photos.append(candidates)
    timestamp = mood.get('created_time')
    return {'source': 'visible', 'record_key': tid, 'source_id': tid,
            'content': mood.get('content') or '',
            'published_at': datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat() if timestamp else None,
            'photos': photos, **visible_social(mood)}


def history_record(card, uin, defer_social=False, social=None, soup=None):
    """Conservative authorship: only clearly owned mood cards become posts."""
    markup = card.get('html', '') if isinstance(card, dict) else ''
    def attr(name):
        match = re.search(r'\b' + re.escape(name) + r'=["\']([^"\']*)["\']', markup)
        return html.unescape(match.group(1)) if match else ''
    tid, author = attr('data-tid'), attr('data-uin')
    if not tid or author != str(uin) or attr('data-appid') not in ('', '311'):
        return None
    match = re.search(r'<p\b[^>]*class=["\'][^"\']*txt-box-title[^"\']*["\'][^>]*>(.*?)</p>', markup, re.S)
    if not match:
        return None
    body=match.group(1)
    if soup is not None:
        title=soup.select_one('p.txt-box-title')
        if title is not None:body=title.decode_contents()
    text = re.sub(r'<a\b[^>]*class=["\'][^"\']*nickname[^"\']*["\'][^>]*>.*?</a>', '', body, flags=re.S)
    text = html.unescape(re.sub('<[^>]+>', '', text)).strip()
    photos = images_from_html(markup)
    for url in re.findall(r'trueSrc\s*:\s*["\']([^"\']+)["\']', markup):
        url = http_url(html.unescape(url))
        host = urlsplit(url).hostname if url else ''
        if url and any(host == d or host.endswith('.' + d) for d in ('qpic.cn', 'photo.store.qq.com')) and not any(url in p for p in photos):
            photos.append([url])
    return {'source': 'history', 'record_key': hashlib.sha256(markup.encode()).hexdigest(),
            'source_id': tid, 'content': text, 'published_at': None, 'photos': photos,
            'interaction_time': attr('data-abstime'), 'evidence_html': markup,
            'author': {'uin': str(uin), 'nickname': ''}, **({'likes':[],'comments':[],'social_version':1,'details_pending':True} if defer_social else social if social is not None else history_social(markup))}


def mobile_record(feed, uin):
    """Structured mobile interaction source; retain uncertain time as interaction."""
    original = feed.get('original') or {}
    author = ((original.get('cell_userinfo') or {}).get('user') or {})
    if str(author.get('uin') or '') != str(uin):
        return None
    cell = original.get('cell_id') or {}
    tid = str(cell.get('cellid') or '')
    if not tid:
        return None
    photos = []
    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            candidates = []
            bp = value.get('busi_param') or {}
            if isinstance(bp, dict):
                for key in ('-1','0'):
                    if (url := http_url(bp.get(key))) and url not in candidates:
                        candidates.append(url)
            ph = value.get('photourl') or {}
            if isinstance(ph, dict):
                for item in ph.values():
                    if isinstance(item, dict) and (url := http_url(item.get('url'))) and url not in candidates:
                        candidates.append(url)
            if candidates:
                if not any(set(candidates) & set(p) for p in photos):
                    photos.append(candidates)
                return
            for key, item in value.items():
                if key not in ('cell_video','cell_userinfo','cell_comment','cell_like'):
                    collect(item)
    collect(original)
    cc = original.get('cell_comment') or {}
    rows = list(cc.get('comments') or [])
    if (cc.get('main_comment') or {}).get('content'):
        rows.append(cc['main_comment'])
    comments = []
    for c in rows:
        user = c.get('user') or {}
        comments.append({'uin':str(user.get('uin') or ''), 'nickname':user.get('nickname') or '',
                         'content':c.get('content') or '', 'time':c.get('date'), 'replies':[]})
    return {'source':'mobile', 'record_key':str((feed.get('comm') or {}).get('feedskey') or tid),
            'source_id':tid, 'published_at':None, 'interaction_time':(feed.get('comm') or {}).get('time'),
            'content':(original.get('cell_summary') or {}).get('summary') or '', 'photos':photos,
            'author':{'uin':str(uin),'nickname':author.get('nickname') or ''}, 'comments':comments}
