"""Typed related-feed evidence. Notification dates are never publication dates."""
import hashlib
import re
from bs4 import BeautifulSoup
from .parsing import images_from_html
from .social import history_social

CATEGORIES = {'posts': '我的说说', 'interactions': '与他人互动', 'gifts': '礼物与游戏', 'blogs': '我的日志'}


def uid(node):
    if node is None:
        return ''
    for key in ('data-uin', 'uin', 'link', 'href'):
        value = str(node.get(key) or '')
        if key in ('data-uin', 'uin') and value.isdigit():
            return value
        match = re.search(r'(?:nameCard_|user\.qzone\.qq\.com/)(\d+)', value)
        if match:
            return match[1]
    return ''


def activity_record(card, account, soup=None, defer_social=False):
    markup = card.get('html', '')
    soup = soup if soup is not None else BeautifulSoup(markup, 'html.parser')
    head = soup.select_one('.f-nick span.state') or soup.select_one('span.state')
    action = head.get_text(' ', strip=True) if head else ''
    category = 'blogs' if '日志' in action else 'gifts' if any(w in action for w in ('送我', '赠送', '邀请我', '邀请你', '礼物', '卡片')) else ''
    official = soup.select_one('a.f-name')
    if not category and official and '官方' in official.get_text() and any(w in soup.get_text() for w in ('生日快乐', '赠送', '礼物', '抽奖资格')):
        category = 'gifts'
        action = action or '官方祝福与礼物'
    if not category:
        return None
    title_node = soup.select_one('p.txt-box-title')
    author_node = title_node.select_one('a.nickname') if title_node else None
    meta = soup.select_one('[name=feed_data]') or soup.select_one('[data-tid]')
    owner = uid(author_node) or (str(meta.get('data-origuin') or meta.get('data-uin') or '') if meta else '')
    if category == 'blogs' and not (owner == str(account) or '我的日志' in action):
        return None
    # These notifications belong to the authenticated account's related feed.
    actor = soup.select_one('a.f-name')
    sender = {'uin': uid(actor), 'nickname': actor.get_text(strip=True) if actor else ''}
    title = ''
    if category == 'blogs' and title_node:
        title = title_node.get_text(' ', strip=True)
        match = re.search(r'《(.*?)》', title)
        title = match.group(1) if match else re.sub(r'^.*?的日志\s*', '', title)
    excerpts = [n.get_text(' ', strip=True) for n in soup.select('.f-single-content p.info')]
    excerpt = '\n'.join(dict.fromkeys(t for t in excerpts if t))
    title = title or action
    content = title + ('\n' + excerpt if excerpt and excerpt != title else '')
    stamp = meta.get('data-abstime') if meta else card.get('abstime')
    stamp = stamp or card.get('abstime')
    root = soup.select_one('li.f-single') or soup.find()
    resource = str(meta.get('data-tid') or '') if meta else ''
    identity = str(root.get('id') or '') if root else ''
    canonical=str(root) if root and root.name=='li' and 'f-single' in root.get('class',[]) else markup
    key = hashlib.sha256((identity or canonical).encode()).hexdigest()
    sid = f'blog:{account}:{resource}' if category == 'blogs' and resource else f'{category}:{key}'
    return dict(source='activity-history', record_key=key, source_id=sid, category=category,
                title=title, excerpt=excerpt, content=content, published_at=None,
                interaction_time=stamp, notification_action=action, sender=sender,
                author={'uin': str(account), 'nickname': author_node.get_text(strip=True) if author_node else ''} if category == 'blogs' else sender,
                photos=images_from_html(str(soup.select_one('.f-single-content') or '')),
                evidence_html=markup, **({'likes':[],'comments':[],'social_version':1,'details_pending':True} if defer_social else history_social(markup)))
