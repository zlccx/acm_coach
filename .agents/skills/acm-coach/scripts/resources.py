"""Unified public resource facade. No training-state writes and no credentials."""
from pathlib import Path
import datetime as dt
from urllib.parse import urlsplit
import acwing_adapter
import luogu_adapter
import noi_adapter
import oiwiki_adapter

SITES = ('luogu', 'luogu-daily', 'acwing', 'oi-wiki', 'noi')


def fallback(site, query):
    if site in ('luogu', 'luogu-daily'):
        return luogu_adapter.fallback(query, 'daily' if site == 'luogu-daily' else 'problem')
    if site == 'acwing':
        return acwing_adapter.fallback(query)
    if site == 'oi-wiki':
        return {'browser_url': 'https://oi-wiki.org/', 'web_search_query': 'site:oi-wiki.org ' + query,
                'instruction': oiwiki_adapter.FALLBACK}
    if site == 'noi':
        return {'instruction': '打开源 PDF 对应页核对；OCR 查询无命中可尝试较宽关键词，不代表大纲排除该知识点。'}
    raise ValueError('unsupported resource site')


def search(site, query, limit=10, kind='problem', page=1, root=None, pdf=None, index=None):
    if site not in SITES or not query.strip() or not 1 <= limit <= 100:
        raise ValueError('site/query/limit invalid')
    try:
        if site in ('luogu', 'luogu-daily'):
            result = luogu_adapter.search(query, limit, 'daily' if site == 'luogu-daily' else kind, page)
        elif site == 'acwing':
            result = acwing_adapter.search(query, limit)
        elif site == 'oi-wiki':
            rows = oiwiki_adapter.search(query, limit)
            result = {'ok': True, 'resources': rows, 'scope': 'directory_titles_only',
                      'warning': None if rows else '目录标题未匹配；不代表正文不存在，请使用 browser/web search'}
        else:
            root = Path(root or noi_adapter.ROOT)
            source = Path(pdf) if pdf else root / 'NOI_Syllabus_Edition_2025.pdf'
            target = Path(index) if index else (root / 'resources/noi-syllabus-2025.index.json' if not pdf else None)
            pages = noi_adapter.search(query, source, limit, target)
            rows = []
            for p in pages:
                rows.append({'title': f"NOI 大纲 · PDF 第 {p['page']} 页", 'url': source.resolve().as_uri() + '#page=' + str(p['page']),
                             'source': 'NOI local PDF', 'resource_type': 'syllabus', 'topics': [], 'page': p['page'],
                             'verification': 'local_ocr_index', 'retrieved_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'content': p['text'],
                             'raw_source': {k: p[k] for k in ('source_pdf', 'sha256', 'extraction', 'edition_evidence')}})
            result = {'ok': True, 'resources': rows, 'scope': 'local_pdf_literal_match',
                      'warning': 'OCR 结果可能误识别；无命中不能推断大纲未包含该知识点。'}
        return {'site': site, 'fallback': fallback(site, query), **result}
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {'ok': False, 'site': site, 'resources': [], 'error': str(exc), 'fallback': fallback(site, query)}


def read(address, strict=False):
    host = urlsplit(address).hostname
    if strict and host != 'www.luogu.com.cn':
        raise ValueError('严格模式只支持洛谷题面的专用字段过滤，其他资源请使用原始题面')
    if host == 'www.luogu.com.cn':
        return luogu_adapter.read(address, strict)
    if host == 'www.acwing.com':
        return acwing_adapter.read(address)
    if host == 'oi-wiki.org':
        try:
            return {'ok': True, 'resource': oiwiki_adapter.read(address)}
        except (OSError, ValueError, RuntimeError) as exc:
            return {'ok': False, 'resource': None, 'error': str(exc), 'fallback': fallback('oi-wiki', address)}
    raise ValueError('仅支持已验证的洛谷、AcWing、OI Wiki 资源域名')
