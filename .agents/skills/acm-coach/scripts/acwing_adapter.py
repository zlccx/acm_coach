"""Read public AcWing course metadata, without sessions or paid lesson bodies.

search searches the live course catalogue, not AcWing's entire article index.
read accepts course overview/introduction URLs and preserves public outline order.
"""
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

BASE = 'https://www.acwing.com'
CATALOGUE = BASE + '/activity/'


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(' '.join(x.text() if isinstance(x, Node) else x for x in self.children).split())

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _fetch(url):
    req = Request(url, headers={'User-Agent': 'ACM-Coach/1.0 public-course-metadata', 'Accept': 'text/html'})
    with urlopen(req, timeout=20) as response:
        final = urlparse(response.geturl())
        if final.hostname != 'www.acwing.com' or final.path != urlparse(url).path:
            raise ValueError('unexpected redirect; target content was not verified')
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('page exceeds metadata size limit')
        return data.decode('utf-8')


def fallback(query):
    return {'browser_url': BASE + '/file_system/search_engine/web_all/result/index/?' + urlencode({'search_type': 'web_entry_all', 'search_content': query}),
            'catalogue_url': CATALOGUE, 'web_search_query': 'site:acwing.com ' + query,
            'instruction': 'Open the public site in a browser or use web search; verify each candidate before citing it.'}


def _resource(title, url, kind, raw_source, topics=None):
    return {'title': title, 'url': url, 'source': 'AcWing', 'resource_type': kind,
            'topics': topics or [], 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'verification': 'page_verified', 'raw_source': raw_source}


def _list_label(node):
    """A parent bullet's label excludes its nested bullets (emitted separately)."""
    return ' '.join(' '.join(child.text() if isinstance(child, Node) else child
                             for child in node.children
                             if not isinstance(child, Node) or child.tag not in {'ul', 'ol'}).split())


def search(query, limit=10):
    """Return matching live public course cards; no match is explicit, not invented."""
    if not isinstance(query, str) or not query.strip() or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError('query must be nonempty; limit must be 1..100')
    try:
        root = Document(_fetch(CATALOGUE)).root
        cards = []
        seen = set()
        for n in root.walk():
            href = urljoin(CATALOGUE, n.attrs.get('href', ''))
            if n.tag != 'a' or not re.fullmatch(re.escape(BASE) + r'/activity/content/\d+/', href) or href in seen:
                continue
            seen.add(href)
            text = n.text()
            title = re.split(r'进行中|已结束|未开始|1024优惠', text)[0].strip()
            if title and all(word.casefold() in text.casefold() for word in query.split()):
                cards.append(_resource(title, href, 'course', {'url': CATALOGUE, 'method': 'public_course_catalogue', 'card_text': text[:600]}))
        if not seen:
            raise ValueError('public course cards missing; layout/access may have changed')
        return {'ok': True, 'scope': 'public_course_catalogue', 'resources': cards[:limit], 'fallback': fallback(query), 'warning': None if cards else 'No matching public course cards; broader site search is available in fallback.'}
    except Exception as exc:
        return {'ok': False, 'resources': [], 'error': str(exc), 'fallback': fallback(query)}


def read(url):
    """Read only the public introduction and its outline, never lesson endpoints."""
    parsed = urlparse(url)
    match = re.fullmatch(r'/activity/content/(?:introduction/)?(\d+)/?', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'www.acwing.com' or not match or parsed.query or parsed.fragment:
        raise ValueError('only HTTPS www.acwing.com course/introduction URLs are supported')
    target = BASE + '/activity/content/introduction/' + match.group(1) + '/'
    try:
        root = Document(_fetch(target)).root
        title_nodes = [n for n in root.walk() if 'activity_title' in n.attrs.get('class', '').split()]
        previews = [n for n in root.walk() if 'martor-preview' in n.attrs.get('class', '').split()]
        if not title_nodes or not previews or not previews[0].text():
            raise ValueError('public course introduction missing; login/block/layout change possible')
        preview = previews[0]
        # Only lists under the public syllabus heading are teaching topics.
        # Price/group-purchase lists elsewhere in the introduction are not topics.
        outline = []
        in_syllabus = False
        for n in preview.children:
            if not isinstance(n, Node):
                continue
            if n.tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
                in_syllabus = any(word in n.text() for word in ('知识点', '课程大纲', '课程目录'))
            elif in_syllabus and n.tag in {'ol', 'ul'}:
                outline.extend(label for item in n.walk() if item.tag == 'li'
                               for label in [_list_label(item)] if label)
        resource = _resource(title_nodes[0].text(), target, 'course', {'url': target, 'method': 'public_course_introduction', 'scope': 'public introduction and outline only'}, outline)
        resource['content'] = preview.text()
        resource['outline'] = outline
        resource['ordering'] = 'original'
        resource['links'] = [{'title': n.text(), 'url': urljoin(target, n.attrs['href'])} for n in preview.walk() if n.tag == 'a' and n.attrs.get('href') and urlparse(urljoin(target, n.attrs['href'])).scheme in {'http', 'https'}]
        return {'ok': True, 'resource': resource}
    except Exception as exc:
        return {'ok': False, 'resource': None, 'error': str(exc), 'fallback': fallback(url)}


if __name__ == '__main__':
    import argparse
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['search', 'read'])
    parser.add_argument('value')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    result = search(args.value, args.limit) if args.operation == 'search' else read(args.value)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
