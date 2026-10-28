import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / ".agents/skills/acm-coach/scripts/oiwiki_adapter.py"
SPEC = importlib.util.spec_from_file_location("oiwiki_adapter", PATH)
oiwiki = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oiwiki)

DIRECTORY = '''<nav class="md-nav md-nav--primary"><ul><li>
<a class="md-nav__link" href="basic/divide-and-conquer/"><span>递归 &amp; 分治</span></a>
<a class="md-nav__link" href="graph/tree-divide/">树分治</a>
<a class="md-nav__link" href="graph/tree-divide/#section">树分治重复</a>
<a class="md-nav__link" href="https://evil.example/x">外站分治</a>
</li></ul></nav><a href="ignored/">非目录分治</a>'''
ARTICLE = '''<html><nav>导航不应混入正文</nav><article class="md-content__inner md-typeset">
<h1>树分治<a href="#">¶</a></h1><h2>点分治</h2>
<p>点分治适合处理大规模的树上路径信息问题。这段文字是测试 fixture，并非已验证的线上内容。</p>
<pre><code>if (a &lt; b) return;</code></pre><script>bad()</script></article></html>'''


class OIWikiTests(unittest.TestCase):
    def setUp(self):
        oiwiki._directory.cache_clear()

    def tearDown(self):
        oiwiki._directory.cache_clear()

    def test_search_directory_only_deduplicates_and_caches(self):
        with patch.object(oiwiki, "_fetch", return_value=DIRECTORY) as fetch:
            rows = oiwiki.search("分治")
            self.assertEqual([r["title"] for r in rows], ["递归 & 分治", "树分治"])
            self.assertEqual(rows[0]["verification"], "navigation_verified")
            self.assertEqual(rows[0]["raw_source"]["scope"], "directory_titles_only")
            self.assertEqual(oiwiki.search("点分治"), [])
            self.assertEqual(len(oiwiki.search("分治", 1)), 1)
            self.assertEqual(fetch.call_count, 1)

    def test_read_extracts_article_and_provenance(self):
        with patch.object(oiwiki, "_fetch", return_value=ARTICLE):
            row = oiwiki.read("https://oi-wiki.org/graph/tree-divide/#x")
        self.assertEqual(row["title"], "树分治")
        self.assertEqual(row["verification"], "page_verified")
        self.assertEqual(row["url"], "https://oi-wiki.org/graph/tree-divide/")
        self.assertIn("if (a < b) return;", row["content"])
        self.assertNotIn("导航不应混入正文", row["content"])
        self.assertNotIn("bad()", row["content"])
        self.assertTrue({"title", "url", "source", "resource_type", "topics", "retrieved_at", "verification", "raw_source"}.issubset(row))

    def test_invalid_inputs_and_changed_page(self):
        for url in ["http://oi-wiki.org/", "https://oi-wiki.org.evil.test/", "https://user@oi-wiki.org/", "file:///etc/passwd"]:
            with self.assertRaises(oiwiki.AdapterError):
                oiwiki.read(url)
        for query, limit in [("", 10), ("x", 0), ("x", True)]:
            with self.assertRaises(oiwiki.AdapterError):
                oiwiki.search(query, limit)
        with patch.object(oiwiki, "_fetch", return_value="<html><h1>Login</h1></html>"):
            with self.assertRaisesRegex(oiwiki.AdapterError, "fallback"):
                oiwiki.search("分治")
            with self.assertRaisesRegex(oiwiki.AdapterError, "fallback"):
                oiwiki.read(oiwiki.BASE)

    def test_network_failure_has_fallback(self):
        with patch.object(oiwiki, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(oiwiki.AdapterError, "timed out.*fallback"):
                oiwiki.search("分治")


if __name__ == "__main__":
    unittest.main()
