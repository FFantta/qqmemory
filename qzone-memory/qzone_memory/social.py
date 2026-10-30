"""Normalize available social fields. Missing names/counts are never invented."""
import re
from functools import lru_cache
from bs4 import BeautifulSoup


def person(value):
    return {'uin': str(value.get('uin') or ''), 'nickname': value.get('nickname') or value.get('name') or ''}


def visible_social(mood):
    comments = []
    for c in mood.get('commentlist') or []:
        comments.append(dict(**person(c), content=c.get('content') or '', time=c.get('create_time'),
            replies=[dict(**person(r), content=r.get('content') or '', time=r.get('create_time')) for r in c.get('list_3') or []]))
    return dict(author=person({'uin': mood.get('uin'), 'name': mood.get('name')}),
        likes=[person(p) for p in mood.get('likelist') or [] if isinstance(p, dict)], comments=comments,
        like_count=mood.get('likenum') or 0, comment_count=mood.get('cmtnum') or len(comments))


@lru_cache(maxsize=8192)
def history_social(markup):
    return social_from_tree(BeautifulSoup(markup, 'html.parser'), markup)


def social_from_tree(soup, markup):
    state = soup.select_one('span.state')
    action = state.get_text(' ', strip=True) if state else ''
    actor = soup.select_one('a.f-name')
    uin = ''
    match = re.search(r'id=["\']fct_(\d+)_', markup)
    if match:
        uin = match.group(1)
    likes = [{'uin': uin, 'nickname': actor.get_text(strip=True)}] if actor and '赞' in action else []
    comments = []
    for node in soup.select('.comments-item'):
        container = node.select_one('.comments-content') or node
        author = container.select_one('a.nickname')
        body = BeautifulSoup(str(container), 'html.parser')
        for unwanted in body.select('.comments-op, .comments-list, .comments-thumbnails'):
            unwanted.decompose()
        first = body.select_one('a.nickname')
        if first:
            first.decompose()
        from .activities import uid
        reply_to = None
        for anchor in body.select('a.nickname'):
            identifier = uid(anchor)
            name = anchor.get_text(strip=True).lstrip('@')
            if identifier:
                if reply_to is None and '回复' in body.get_text():
                    reply_to = {'uin': identifier, 'nickname': name}
                anchor.replace_with('@{uin:' + identifier + ',nick:' + name + ',who:1}')
        content = re.sub(r'[\t\r ]+', ' ', body.get_text(' ', strip=True)).strip(':： \n')
        if content:
            date_node = node.select_one('.comments-op span.state')
            comments.append({'uin': node.get('data-uin') or uid(author), 'nickname': node.get('data-nick') or (author.get_text(strip=True) if author else ''), 'content': content, 'time': date_node.get_text(strip=True) if date_node else None, 'reply_to': reply_to, 'replies': []})
    return {'likes': likes, 'comments': comments, 'social_version': 2}
