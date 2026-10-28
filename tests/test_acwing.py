"""Public metadata fixtures; no training data or authenticated requests."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / '.agents/skills/acm-coach/scripts/acwing_adapter.py'
SPEC = importlib.util.spec_from_file_location('acwing_adapter', PATH)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

CATALOGUE = '''<html><a href="/activity/content/11/"><span>算法基础课</span>
<span>进行中</span><p>基础算法与数据结构</p></a>
<a href="/activity/content/16/">算法提高课 进行中 图论</a></html>'''
INTRO = '''<span class="activity_title nice_font">算法基础课</span>
<div class="main-martor"><div class="martor-preview"><h4>费用</h4><ul><li>200元</li></ul><h4>知识点</h4>
<ol><li><p>基础算法</p><ul><li>排序</li><li>二分</li></ul></li>
<li>动态规划</li></ol><h4>课程交流</h4><ul><li>交流群</li></ul><a href="/blog/content/277/">模板</a></div></div>'''


class AcWingTests(unittest.TestCase):
    def test_search_actual_card_structure(self):
        with patch.object(adapter, '_fetch', return_value=CATALOGUE):
            result = adapter.search('算法', 1)
        self.assertTrue(result['ok'])
        self.assertEqual(result['scope'], 'public_course_catalogue')
        self.assertEqual(result['resources'][0]['title'], '算法基础课')
        self.assertEqual(len(result['resources']), 1)
        self.assertEqual(result['resources'][0]['verification'], 'page_verified')

    def test_read_introduction_preserves_order(self):
        with patch.object(adapter, '_fetch', return_value=INTRO) as fetch:
            result = adapter.read(adapter.BASE + '/activity/content/11/')
        fetch.assert_called_once_with(adapter.BASE + '/activity/content/introduction/11/')
        self.assertEqual(result['resource']['outline'], ['基础算法', '排序', '二分', '动态规划'])
        self.assertEqual(result['resource']['links'][0]['url'], adapter.BASE + '/blog/content/277/')

    def test_failure_and_login_page_never_success(self):
        for html in ['<title>登录</title>', '<html>验证后继续</html>']:
            with patch.object(adapter, '_fetch', return_value=html):
                self.assertFalse(adapter.search('图论')['ok'])
                self.assertFalse(adapter.read(adapter.BASE + '/activity/content/11/')['ok'])
        with patch.object(adapter, '_fetch', side_effect=OSError('HTTP 403')):
            result = adapter.search('点分治')
        self.assertFalse(result['ok'])
        self.assertIn('HTTP 403', result['error'])
        self.assertIn('site:acwing.com 点分治', result['fallback']['web_search_query'])

    def test_no_match_and_invalid_input(self):
        with patch.object(adapter, '_fetch', return_value=CATALOGUE):
            result = adapter.search('不存在')
        self.assertTrue(result['ok'])
        self.assertEqual(result['resources'], [])
        self.assertTrue(result['warning'])
        for url in ['https://evil.example/activity/content/11/', 'https://www.acwing.com/activity/content/problem/content/1/', 'https://www.acwing.com/user/account/']:
            with self.assertRaises(ValueError):
                adapter.read(url)
        with self.assertRaises(ValueError):
            adapter.search('')


if __name__ == '__main__':
    unittest.main()
