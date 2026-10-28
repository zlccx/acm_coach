"""Public Luogu HTML context adapter, observed in Chrome, no browser credentials."""
import datetime as dt
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

BASE = 'https://www.luogu.com.cn'


class AdapterError(ValueError):
    pass


def fallback(query, kind='problem'):
    entry = {'problem': BASE + '/problem/list', 'playlist': BASE + '/training/list',
             'article': BASE + '/article', 'daily': BASE + '/article/collection/1'}[kind]
    return {'browser_url': entry, 'web_search_query': 'site:luogu.com.cn ' + ('洛谷日报 ' if kind == 'daily' else '') + query,
            'instruction': 'Use browser search or web search, then open candidate pages. A plan is not verified content.'}


class Context(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.record = False
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'lentille-context':
            self.record = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.record = False

    def handle_data(self, text):
        if self.record:
            self.parts.append(text)


def _fetch(address):
    req = Request(address, headers={'User-Agent': 'ACM-Coach/0.2 (public learning resources)', 'Accept': 'text/html'})
    with urlopen(req, timeout=20) as response:
        final = urlsplit(response.geturl())
        expected = urlsplit(address)
        if final.hostname != 'www.luogu.com.cn' or final.path != expected.path:
            raise AdapterError('重定向到其他页面，未验证目标内容')
        raw = response.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise AdapterError('页面超出 5 MiB 上限')
        return raw.decode('utf-8')


def _data(address):
    parsed = Context(_fetch(address))
    if not parsed.parts:
        raise AdapterError('缺少 lentille-context，可能为登录/风控/页面结构变化')
    context = json.loads(''.join(parsed.parts))
    if context.get('status') != 200 or not isinstance(context.get('data'), dict):
        raise AdapterError('洛谷返回异常上下文状态或结构')
    # Callers whitelist fields below. Never return context.user, lastCode, votes or records.
    return context['data']


def _record(title, address, kind, origin, **fields):
    if not isinstance(title, str) or not title.strip():
        raise AdapterError('资源标题缺失')
    return {'title': title, 'url': address, 'source': '洛谷', 'resource_type': kind, 'topics': [],
            'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'verification': 'page_verified',
            'raw_source': {'url': origin, 'method': 'public_html_lentille_context'}, **fields}


def _problem(p, origin, strict=False):
    pid = p.get('pid', '')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', pid):
        raise AdapterError('题号格式异常')
    result = _record(p.get('name'), BASE + '/problem/' + pid, 'problem', origin, problem_id=pid)
    if not strict:
        result['difficulty'] = p.get('difficulty')
        result['topics'] = p.get('tags', [])
    return result


def _article(a, origin, daily=False, full=False):
    lid = a.get('lid', '')
    if not re.fullmatch('[A-Za-z0-9]+', lid):
        raise AdapterError('文章 ID 格式异常')
    result = _record(a.get('title'), BASE + '/article/' + lid, 'article', origin)
    collection = a.get('collection')
    if daily and (not isinstance(collection, dict) or collection.get('id') != 1):
        raise AdapterError('返回文章不属于洛谷日报合集，不冒充日报结果')
    if isinstance(collection, dict):
        result['collection'] = {k: collection.get(k) for k in ('id', 'name')}
    author = a.get('author')
    if isinstance(author, dict):
        result['author'] = author.get('name')  # public attribution only
    if full:
        content = a.get('content')
        if not isinstance(content, str) or not content.strip():
            raise AdapterError('文章正文不可用或受限')
        result['content'] = content
        result['content_complete'] = a.get('contentFull') is True
        if a.get('contentFull') is not True:
            result['warning'] = '仅验证返回的公开内容，不保证完整正文；请浏览器核对'
    return result


def search(query, limit=10, kind='problem', page=1):
    if kind not in ('problem', 'playlist', 'article', 'daily'):
        raise AdapterError('kind 应为 problem/playlist/article/daily')
    if not query.strip() or not 1 <= limit <= 100 or not 1 <= page <= 100:
        raise AdapterError('关键词非空，limit/page 为 1..100')
    path = {'problem': '/problem/list', 'playlist': '/training/list', 'article': '/article', 'daily': '/article/collection/1'}[kind]
    params = {'page': page}
    if kind != 'playlist':
        params['keyword'] = query
    if kind == 'problem':
        params['type'] = 'all'
    address = BASE + path + '?' + urlencode(params)
    try:
        d = _data(address)
        key = {'problem': 'problems', 'playlist': 'trainings', 'article': 'articles', 'daily': 'articles'}[kind]
        container = d.get(key)
        if not isinstance(container, dict) or not isinstance(container.get('result'), list):
            raise AdapterError('资源列表结构变化')
        rows = container['result']
        if kind == 'problem':
            resources = [_problem(p, address) for p in rows]
        elif kind == 'playlist':
            resources = [_record(p.get('name'), BASE + '/training/' + str(p['id']), 'playlist', address)
                         for p in rows if query.casefold() in str(p.get('name', '')).casefold()]
        else:
            resources = [_article(p, address, daily=kind == 'daily') for p in rows]
        return {'ok': True, 'resources': resources[:limit], 'scope': 'current_catalogue_page_title_match' if kind == 'playlist' else 'site_keyword_search',
                'page': page, 'total': container.get('count'), 'fallback': fallback(query, kind),
                'warning': '题单检索只匹配当前目录页标题，可用 web search 扩展' if kind == 'playlist' else None}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'resources': [], 'error': str(exc), 'fallback': fallback(query, kind)}


def read(address, strict=False):
    parsed = urlsplit(address)
    if parsed.scheme != 'https' or parsed.netloc != 'www.luogu.com.cn' or parsed.query or parsed.fragment:
        raise AdapterError('仅接受无查询/片段的 HTTPS www.luogu.com.cn 公开资源 URL')
    match = re.fullmatch(r'/(problem|training|article)/([A-Za-z0-9_]+)', parsed.path.rstrip('/'))
    if not match or match[2] in ('list', 'mine', '_new'):
        raise AdapterError('仅接受题目、数字题单 ID 或文章 URL')
    kind, ident = match.groups()
    if kind == 'training' and not ident.isdigit():
        raise AdapterError('题单 ID 必须为数字')
    if strict and kind != 'problem':
        raise AdapterError('严格模式只允许读取题面，不能读取题单和文章')
    try:
        d = _data(address)
        if kind == 'problem':
            p = d.get('problem')
            if not isinstance(p, dict) or p.get('pid') != ident:
                raise AdapterError('题目不存在或标识不匹配')
            result = _problem(p, address, strict)
            # The multilingual problem statement is distinct from tags/recommendations/lastCode.
            for key in ('content', 'samples', 'limits'):
                if key in p:
                    result[key] = p[key]
            if not result.get('content'):
                raise AdapterError('题面缺失，不将登录页当题目')
        elif kind == 'article':
            a = d.get('article')
            if not isinstance(a, dict) or a.get('lid') != ident:
                raise AdapterError('文章不存在或标识不匹配')
            result = _article(a, address, full=True)
        else:
            t = d.get('training')
            if not isinstance(t, dict) or str(t.get('id')) != ident or not isinstance(t.get('problems'), list) or not t['problems']:
                raise AdapterError('题单不存在、为空或受限')
            items = [_problem(p, address) for p in t['problems']]
            for position, item in enumerate(items, 1):
                item['position'] = position
            result = _record(t.get('name'), address, 'playlist', address, id='luogu-' + ident,
                             source_url=address, items=items, ordering='original', description=t.get('description', ''))
        return {'ok': True, 'resource': result}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'resource': None, 'error': str(exc),
                'fallback': fallback(ident, {'problem': 'problem', 'training': 'playlist', 'article': 'article'}[kind])}
