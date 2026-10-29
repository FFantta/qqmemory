"""Resumable history coverage: paged windows, sparse offsets and feeds3 cursors.

Only QQ responses are ingested. A checkpoint advances after records commit, so
an interrupted page is replayed safely instead of losing its content.
"""
import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import requests
from .online import ProtocolError, history_record
from .parsing import images_from_html
from .social import history_social

ZONE = ZoneInfo('Asia/Shanghai')
STATE_KEY = 'deep-history-v1'
DOMAIN_PATH = '/proxy/domain/ic2.qzone.qq.com/cgi-bin/feeds/'


def plan(target_year=2005, max_offset=25000, now=None):
    now = now or datetime.now(ZONE)
    year = now.year
    tasks = []
    def add(label, params, pages, kind='feeds2', sparse=False):
        tasks.append(dict(label=label, params=params, pages=pages, kind=kind, sparse=sparse))
    add('顺序分页',dict(offset=0),100)
    # Cover old time ranges before the lengthy offset sweeps, so they cannot be
    # starved by the per-run budget. Checkpoints use Beijing calendar boundaries.
    for y in range(year,target_year-1,-1):
        for month in (7,1):
            begin=int(datetime(y,month,1,tzinfo=ZONE).timestamp())
            end=int(datetime(y+1,1,1,tzinfo=ZONE).timestamp())-1 if month==7 else int(datetime(y,7,1,tzinfo=ZONE).timestamp())-1
            add(f'{y}年'+('下半年' if month==7 else '上半年'),dict(begin_time=begin,end_time=end,offset=0),15)
    points=[int(now.timestamp())]
    for y in range(year,target_year-1,-1):
        for month in (10,7,4,1):
            point=int(datetime(y,month,1,tzinfo=ZONE).timestamp())
            if point<=points[0]:points.append(point)
    for point in dict.fromkeys(points):
        add('时间游标 '+datetime.fromtimestamp(point,ZONE).strftime('%Y-%m'),dict(begintime=point),120,'feeds3')
    ranges=[(700,min(6000,max_offset),100,10,'稀疏深扫'),
            (2500,min(3200,max_offset),25,5,'加密2500–3200'),
            (4500,min(5500,max_offset),50,5,'加密4500–5500'),
            (6000,max_offset,100,10,'深层offset'),
            (5500,min(15000,max_offset),20,4,'超细offset'),
            (15000,max_offset,250,3,'远端offset')]
    for begin,end,step,pages,label in ranges:
        for offset in range(begin,end+1,step):add(label,dict(offset=offset),pages,sparse=True)
    for variant in range(4):
        for offset in (0,800,1500,2200,3000,4000,5000,6000,8000,10000,12000,15000,20000):
            if offset<=max_offset:add(f'set={variant}',dict(offset=offset,set=variant),5)
    for scope in (0,1):
        for offset in (0,3000,6000,9000,12000,15000,20000):
            if offset<=max_offset:add(f'scope={scope}',dict(offset=offset,scope=scope),6)
    return sorted(tasks,key=task_order)


def task_order(task):
    # Match the Go scanner's successful coverage order before adding time cursors.
    labels=('顺序分页','稀疏深扫','加密2500','加密4500','深层offset','超细offset','远端offset')
    for index,label in enumerate(labels):
        if task['label'].startswith(label):return index
    if task['kind']=='feeds3':return 9
    if task['label'].startswith(('set=','scope=')):return 8
    return 7


def page_cards(data):
    """Accept the known feeds2/feeds3 envelopes; never turn an unknown page empty."""
    if not isinstance(data,dict):raise ProtocolError('深度历史响应不是对象')
    cards=[]
    known=False
    more=None
    def walk(node,context=False):
        nonlocal known,more
        if isinstance(node,dict):
            if 'hasMoreFeeds' in node:more=node['hasMoreFeeds']
            if 'html' in node and isinstance(node['html'],str):
                known=True
                split(node['html'],node)
            for k in ('data','main','feeds','items'):
                if k in node:
                    walk(node[k],True)
        elif isinstance(node,list):
            known=True
            for item in node:walk(item,context)
        elif isinstance(node,str) and context:
            known=True
            if '<' in node:
                split(node,{})
            elif node.strip():
                raise ProtocolError('深度历史接口返回了非卡片文本')
    def split(markup,meta):
        soup=BeautifulSoup(markup,'html.parser')
        nodes=soup.select('li.f-single')
        if nodes:
            cards.extend(dict(meta,html=str(n)) for n in nodes)
        elif markup.strip():
            # A single card may be a div; retain it including rejected evidence.
            cards.append(dict(meta,html=markup))
    walk(data)
    if not known:raise ProtocolError('未识别的深度历史接口结构')
    return cards,more


def user_id(node):
    if node is None:return ''
    for key in ('data-uin','uin','link','href'):
        value=str(node.get(key) or '')
        if key in ('uin','data-uin') and value.isdigit():return value
        m=re.search(r'(?:nameCard_|user\.qzone\.qq\.com/)(\d+)',value)
        if m:return m.group(1)
    return ''


def non_mood(markup):
    soup=BeautifulSoup(markup,'html.parser')
    app=soup.select_one('[data-appid]')
    if app and str(app.get('data-appid')) not in ('','311'):
        return True
    state=' '.join(n.get_text(' ',strip=True) for n in soup.select('span.state'))
    return '说说' not in state and any(word in state for word in ('相册','照片','留言','日志','主页'))


def record(card,uin):
    from .activities import activity_record
    typed = activity_record(card, uin)
    if typed:return typed,'typed_activity'
    if non_mood(card.get('html','')):return None,'other_app'
    existing=history_record(card,uin)
    if existing:
        existing['interaction_time']=existing.get('interaction_time') or card.get('abstime')
        return existing,'id'
    markup=card.get('html','')
    soup=BeautifulSoup(markup,'html.parser')
    title=soup.select_one('p.txt-box-title')
    if title is None:return None,'missing_title'
    body_author=title.select_one('a.nickname')
    if body_author and body_author.get_text(strip=True).startswith('@'):
        body_author=None
    owner=user_id(body_author)
    mentioned=any(user_id(a)==str(uin) and a.get_text(strip=True).startswith('@') for a in title.select('a'))
    mentioned=mentioned or bool(re.search(r'@\{uin:'+re.escape(str(uin))+r',',title.get_text()))
    social = history_social(markup)
    participated = any(str(c.get('uin')) == str(uin) or any(str(r.get('uin')) == str(uin) for r in c.get('replies', [])) for c in social['comments'])
    related=bool(owner and owner!=str(uin) and (mentioned or participated))
    author_name=body_author.get_text(strip=True) if body_author else ''
    state=' '.join(n.get_text(' ',strip=True) for n in soup.select('span.state'))
    root=soup.find(attrs={'data-tid':True}) or soup.find('li') or soup.find()
    root_owner=str(root.get('data-uin') or '') if root else ''
    appid=str(root.get('data-appid') or '') if root else ''
    if appid not in ('','311'):return None,'other_app'
    # An interaction sender is not the post author. Explicit body ownership or
    # "my mood" wording establishes ownership in the logged-in private feed.
    if owner and owner!=str(uin) and not related:return None,'other_owner'
    if not (related or owner==str(uin) or root_owner==str(uin) or '我的说说' in state):return None,'unknown_owner'
    if owner!=str(uin) and root_owner!=str(uin) and any(word in state for word in ('相册','留言','日志')):return None,'other_app'
    if body_author and not body_author.get_text(strip=True).startswith('@'):body_author.decompose()
    # Keep identifiable mentions rather than dropping every nickname anchor.
    for anchor in title.select('a.nickname'):
        uid=user_id(anchor)
        name=anchor.get_text(strip=True).lstrip('@')
        if uid:anchor.replace_with('@{uin:'+uid+',nick:'+name+',who:1}')
    content=title.get_text('',strip=False).strip().lstrip(':：').strip()
    if not content:return None,'empty_title'
    timestamp=next((n.get('data-abstime') for n in soup.select('[data-abstime]') if str(n.get('data-abstime','')).isdigit()),None)
    timestamp=timestamp or card.get('abstime')
    # A quoted author's title does not establish ownership of an outer forward ID.
    target_owner=owner if related else str(uin)
    owned=soup.find(attrs={'data-uin':target_owner,'data-tid':True})
    tid=str(owned.get('data-tid') or '') if owned else ''
    actor=soup.select_one('a.f-name')
    activity_id=str(root.get('id') or '') if root else ''
    identity=[activity_id,tid,user_id(actor),str(timestamp or ''),content]
    if not activity_id and not tid and not timestamp:
        identity.append(hashlib.sha256(markup.encode()).hexdigest())
    key=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
    return dict(source='related-history' if related else 'deep-history',record_key=key,source_id=tid or None,content=content,
        published_at=None,interaction_time=timestamp,photos=images_from_html(markup),evidence_html=markup,
        author={'uin':target_owner,'nickname':author_name if related else ''},category='interactions' if related else 'posts',relation='participated' if related and participated else 'mentioned' if related else 'own',ownership_basis='mentioned_account' if related else 'body_author' if owner==str(uin) else 'card_owner' if root_owner==str(uin) else 'my_mood_activity',
        **history_social(markup)), 'id' if tid else 'activity_clue'


def load_state(archive):
    row=archive.db.execute('SELECT payload FROM scan_checkpoints WHERE name=?',(STATE_KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def persist(archive,state):
    with archive.db:
        archive.db.execute('INSERT INTO scan_checkpoints VALUES(?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload',(STATE_KEY,json.dumps(state,ensure_ascii=False)))


def scan(archive,qq,request,save,notify,job):
    state=load_state(archive)
    if not state or state.get('complete'):
        state=dict(tasks=plan(),index=0,page=0,next=None,requests=0,raw_cards=0,complete=False,rejected={},last_digest=None)
        persist(archive,state)
    tasks=state['tasks']
    if not state.get('go_order'):
        index=state['index']
        # Preserve the in-progress page, only reorder as-yet untouched segments.
        tasks=tasks[:index+1]+sorted(tasks[index+1:],key=task_order)
        state.update(tasks=tasks,go_order=True)
        persist(archive,state)
    evidence=archive.root/'evidence'/'deep'
    evidence.mkdir(parents=True,exist_ok=True)
    while state['index']<len(tasks):
        notify('progress',dict(stage='deep',done=state['index'],total=len(tasks)))
        task=tasks[state['index']]
        params=dict(task['params'])
        key='begintime' if task['kind']=='feeds3' else 'offset'
        if state['next'] is not None:params[key]=state['next']
        public=dict(params)
        base=dict(uin=qq.uin,g_tk=qq.token,useutf8=1,outputhtmlfeed=1,format='jsonp')
        if task['kind']=='feeds3':
            base.update(scope=0,view=1,flag=1,filter='all',count=50)
            endpoint='feeds3_html_more'
        else:
            base.update(begin_time=0,end_time=0,getappnotification=1,getnotifi=1,has_get_key=0,offset=0,set=0,count=100,scope=1)
            endpoint='feeds2_html_pav_all'
        base.update(params)
        notify('status',f'深度找回：{task["label"]}，分段 {state["index"]+1}/{len(tasks)}，第 {state["page"]+1} 页（断点自动保存）')
        # Match the Go H5 gateway first, retaining its legacy user-domain fallback.
        errors=[]
        for host in ('h5.qzone.qq.com','user.qzone.qq.com'):
            counted=False
            try:
                payload=request('https://'+host+DOMAIN_PATH+endpoint,base)
                state['requests']+=1
                counted=True
                cards,more=page_cards(payload)
                break
            except (requests.RequestException,ProtocolError,ValueError) as exc:
                if not counted:state['requests']+=1
                status=getattr(getattr(exc,'response',None),'status_code',None)
                errors.append(dict(gateway=host,error=type(exc).__name__,status=status,code=getattr(exc,'code',None)))
                message=getattr(exc,'remote_message','').lower()
                authentication=any(word in message for word in ('未登录','登录失效','登录过期','请先登录','need login','not login','login required'))
                limited=any(word in message for word in ('访问过于频繁','操作频繁','请求过于频繁','rate limit'))
                if status in (401,403,429) or authentication or limited:
                    state['last_error']=errors
                    persist(archive,state)
                    raise ProtocolError('QQ拒绝历史请求，已保留断点；请稍后重试。'+(' HTTP '+str(status) if status else str(exc))) from exc
        else:
            # A hole or transient failure must not abort all subsequent ranges.
            retries=state.setdefault('retry_tasks',[])
            retry=dict(task,params=public,pages=max(1,task['pages']-state['page']))
            retries.append(retry)
            state['last_error']=errors
            state['consecutive_errors']=state.get('consecutive_errors',0)+1
            notify('status',f'分段请求失败，已保存重试点：{task["label"]}；继续其他分段')
            state.update(index=state['index']+1,page=0,next=None,last_digest=None)
            persist(archive,state)
            if state['consecutive_errors']>=3:
                raise ProtocolError('连续三个分段请求失败，已暂停并保存断点，避免重复空转；稍后可继续。')
            continue
        state['consecutive_errors']=0
        state['raw_cards']=state.get('raw_cards',0)+len(cards)
        trace={'endpoint':endpoint,'gateway':host,'params':public,'response':payload}
        dest=evidence/f'{job}-{state["requests"]}.json'
        dest.write_text(json.dumps(trace,ensure_ascii=False),encoding='utf-8')
        dest.chmod(0o600)
        records=[]
        for card in cards:
            parsed,reason=record(card,qq.uin)
            if parsed:records.append(parsed)
            else:state['rejected'][reason]=state['rejected'].get(reason,0)+1
        save(records,dict(phase='deep-history',segment=state['index'],params=public))
        digest=hashlib.sha256(json.dumps(cards,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        done=not cards or digest==state['last_digest'] or state['page']+1>=task['pages']
        if task['kind']=='feeds3':
            times=[]
            for card in cards:
                times.extend(int(t) for t in re.findall(r'data-abstime=["\'](\d+)',card.get('html','')))
                t=card.get('abstime')
                if str(t).isdigit():times.append(int(t))
            earliest=min((t for t in times if t>0),default=0)
            if not earliest or earliest>=params['begintime']:done=True
            state['next']=earliest
        else:
            state['next']=params['offset']+len(cards)
            if more in (False,0,'0','false') and (not task['sparse'] or state['page']>=2):done=True
        state['last_digest']=digest
        state['page']+=1
        if done:
            state.update(index=state['index']+1,page=0,next=None,last_digest=None)
        state['complete']=state['index']>=len(tasks) and not state.get('retry_tasks')
        persist(archive,state)
    notify('progress',dict(stage='deep',done=state['index'],total=len(tasks)))
    if state.get('retry_tasks'):
        state.update(tasks=state.pop('retry_tasks'),index=0,page=0,next=None,last_digest=None,consecutive_errors=0)
        persist(archive,state)
        raise ProtocolError('本轮可访问分段已扫描，仍有失败分段待重试；断点已保留。')
    return state


def quarantine_non_moods(archive):
    """Reversible cleanup of this adapter's mistaken album-only records."""
    archive.db.execute('CREATE TABLE IF NOT EXISTS quarantined_history(post_id TEXT PRIMARY KEY,payload TEXT NOT NULL,reason TEXT NOT NULL)')
    ids=[r[0] for r in archive.db.execute("SELECT DISTINCT post_id FROM evidence WHERE source='deep-history'")]
    moved=0
    with archive.db:
        for pid in ids:
            evidence=[dict(r) for r in archive.db.execute('SELECT * FROM evidence WHERE post_id=?',(pid,))]
            if any(r['source']!='deep-history' or not non_mood(json.loads(r['payload']).get('evidence_html','')) for r in evidence):continue
            post=dict(archive.db.execute('SELECT * FROM posts WHERE id=?',(pid,)).fetchone())
            media=[dict(r) for r in archive.db.execute('SELECT * FROM media WHERE post_id=?',(pid,))]
            snapshot=dict(post=post,evidence=evidence,media=media)
            archive.db.execute('INSERT OR IGNORE INTO quarantined_history VALUES(?,?,?)',(pid,json.dumps(snapshot,ensure_ascii=False),'non_mood_activity'))
            archive.db.execute('DELETE FROM evidence WHERE post_id=?',(pid,))
            archive.db.execute('DELETE FROM media WHERE post_id=?',(pid,))
            archive.db.execute('DELETE FROM posts WHERE id=?',(pid,))
            moved+=1
    return moved
