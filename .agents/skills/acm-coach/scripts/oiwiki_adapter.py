"""OI Wiki public navigation search and article reader (standard library only).

Observed 2026-10-27: homepage primary navigation exposes the public directory;
the site's advertised /search/search_index.json returns 404. Search deliberately
matches directory titles, not article bodies, and never crawls linked articles.
"""
import json
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

BASE = "https://oi-wiki.org/"
FALLBACK = "使用已打开的浏览器读取 OI Wiki，或 web search 搜索 site:oi-wiki.org 加关键词；候选页面需实际打开验证。"


class AdapterError(RuntimeError):
    def __init__(self, message):
        super().__init__(message + "；fallback: " + FALLBACK)


def _url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "oi-wiki.org" or p.username or p.password:
        raise AdapterError("只支持 https://oi-wiki.org/ 的公开页面")
    return urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))


def _fetch(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": "ACM-Coach/1.0 (public resource reader)"}), timeout=25) as response:
            _url(response.geturl())
            if "text/html" not in response.headers.get("Content-Type", ""):
                raise AdapterError("站点返回非 HTML 内容")
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise AdapterError("页面超过 4 MiB 读取上限")
            return raw.decode("utf-8")
    except AdapterError:
        raise
    except Exception as exc:
        raise AdapterError("OI Wiki 请求失败: " + str(exc)) from exc


class _Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []
        self.anchor = None
        self.article = []
        self.heading = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        inherited = self.stack[-1][1] if self.stack else set()
        flags = set(inherited)
        if tag == "nav" and "md-nav--primary" in attrs.get("class", "").split():
            flags.add("nav")
        if tag == "article":
            flags.add("article")
        if tag in ("script", "style"):
            flags.add("skip")
        if tag == "h1" and "article" in flags:
            flags.add("heading")
        if tag == "a" and "nav" in flags and "md-nav__link" in attrs.get("class", "").split():
            self.anchor = [attrs.get("href", ""), []]
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"):
            self.stack.append((tag, flags))
        if "article" in flags and tag in ("p", "div", "pre", "li", "h1", "h2", "h3", "br"):
            self.article.append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            href, parts = self.anchor
            self.links.append((" ".join("".join(parts).split()), href))
            self.anchor = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        flags = self.stack[-1][1] if self.stack else set()
        if "skip" in flags:
            return
        if self.anchor is not None:
            self.anchor[1].append(data)
        if "article" in flags:
            self.article.append(data)
        if "heading" in flags:
            self.heading.append(data)


def _record(title, url, verification, raw_source, retrieved_at):
    return dict(title=title, url=url, source="oi-wiki", resource_type="tutorial",
                topics=[], retrieved_at=retrieved_at, verification=verification,
                raw_source=raw_source)


def _now():
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=1)
def _directory():
    page = _Page(_fetch(BASE))
    entries = []
    seen = set()
    for title, href in page.links:
        if not href or href.startswith("#"):
            continue
        try:
            url = _url(urljoin(BASE, href))
        except AdapterError:
            continue
        if title and url not in seen:
            entries.append((title, url))
            seen.add(url)
    if not entries:
        raise AdapterError("OI Wiki 主导航为空或页面结构已变化")
    return entries, _now()


def search(query, limit=10):
    """Return title matches from one in-memory cached homepage directory fetch.

    Results verify directory membership only; use read() to verify article text.
    An empty result does not establish absence from OI Wiki's article bodies.
    Call _directory.cache_clear() to refresh a long-lived process explicitly.
    """
    if not isinstance(query, str) or not query.strip():
        raise AdapterError("query 必须是非空字符串")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise AdapterError("limit 必须是 1..100 的整数")
    entries, timestamp = _directory()
    terms = query.casefold().split()
    matches = [(t, u) for t, u in entries if all(x in t.casefold() for x in terms)]
    return [_record(t, u, "navigation_verified", {"url": BASE,
                    "method": "primary_navigation_title_match", "query": query,
                    "scope": "directory_titles_only", "fallback": FALLBACK}, timestamp)
            for t, u in matches[:limit]]


def read(url):
    """Read an explicit public article; preserve text without storing a mirror."""
    url = _url(url)
    page = _Page(_fetch(url))
    title = " ".join("".join(page.heading).split()).rstrip("¶ ")
    content = re.sub(r"\n[ \t]*\n+", "\n\n", "".join(page.article)).strip()
    if not title or not content or len(content) < 40:
        raise AdapterError("未找到有效 article/h1 正文，可能是拦截页或站点结构变化")
    result = _record(title, url, "page_verified", {"url": url, "method": "html_article"}, _now())
    result["content"] = content
    return result


if __name__ == "__main__":
    try:
        if len(sys.argv) < 3 or sys.argv[1] not in ("search", "read"):
            raise AdapterError("用法: oiwiki_adapter.py search <关键词> [limit] | read <URL>")
        result = search(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10) if sys.argv[1] == "search" else read(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (AdapterError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "fallback": FALLBACK}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
