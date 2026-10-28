import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/acm-coach/scripts/luogu_adapter.py'
spec = importlib.util.spec_from_file_location('luogu', SCRIPT)
l = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l)


def html(data):
    return '<script type="application/json" id="lentille-context">' + json.dumps({'status': 200, 'data': data, 'user': {'name': 'PRIVATE'}}) + '</script>'


class LuoguTests(unittest.TestCase):
    def test_problem_search_uses_observed_keyword_and_ignores_personal_fields(self):
        def fetch(address):
            self.assertIn('keyword=', address)
            return html({'problems': {'count': 1, 'result': [{'pid': 'P3806', 'name': '题目', 'difficulty': 7,
                                                          'accepted': True, 'submitted': True, 'provider': {'name': 'PRIVATE'}}]}})
        with patch.object(l, '_fetch', fetch):
            result = l.search('点分治')
        self.assertTrue(result['ok'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('accepted', json.dumps(result))

    def test_daily_membership_is_verified(self):
        with patch.object(l, '_fetch', return_value=html({'articles': {'count': 1, 'result': [{'lid': 'abc123', 'title': '日报', 'collection': {'id': 1, 'name': '洛谷日报'}}]}})):
            result = l.search('分治', kind='daily')
            self.assertTrue(result['ok'])
            self.assertEqual(result['resources'][0]['collection']['id'], 1)
        with patch.object(l, '_fetch', return_value=html({'articles': {'result': [{'lid': 'abc', 'title': '其他', 'collection': None}]}})):
            self.assertFalse(l.search('分治', kind='daily')['ok'])

    def test_training_preserves_order_and_is_importable(self):
        data = {'training': {'id': 100, 'name': '原题单', 'problems': [{'pid': 'B2002', 'name': 'First'}, {'pid': 'P1001', 'name': 'Second'}]}}
        with patch.object(l, '_fetch', return_value=html(data)):
            result = l.read('https://www.luogu.com.cn/training/100')['resource']
        self.assertEqual(result['id'], 'luogu-100')
        self.assertEqual(result['ordering'], 'original')
        self.assertEqual([p['problem_id'] for p in result['items']], ['B2002', 'P1001'])
        self.assertEqual([p['position'] for p in result['items']], [1, 2])

    def test_strict_problem_whitelist_drops_tags_records_and_saved_code(self):
        data = {'problem': {'pid': 'P3806', 'name': 'Original statement', 'content': {'description': '题面'},
                            'tags': ['SECRET'], 'bestRecord': 'PRIVATE'}, 'lastCode': 'PRIVATE'}
        with patch.object(l, '_fetch', return_value=html(data)):
            result = l.read('https://www.luogu.com.cn/problem/P3806', strict=True)
        self.assertTrue(result['ok'])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('PRIVATE', json.dumps(result))
        with self.assertRaises(l.AdapterError):
            l.read('https://www.luogu.com.cn/training/100', strict=True)

    def test_article_contentfull_is_a_boolean_not_body(self):
        with patch.object(l, '_fetch', return_value=html({'article': {'lid': 'abc', 'title': '标题', 'content': '正文', 'contentFull': True}})):
            r = l.read('https://www.luogu.com.cn/article/abc')['resource']
            self.assertEqual(r['content'], '正文')
            self.assertTrue(r['content_complete'])

    def test_network_failure_and_login_page_produce_fallback(self):
        with patch.object(l, '_fetch', side_effect=OSError('403')):
            result = l.search('分治')
            self.assertFalse(result['ok'])
            self.assertIn('403', result['error'])
            self.assertIn('web_search_query', result['fallback'])
        with patch.object(l, '_fetch', return_value='<html>Login</html>'):
            self.assertFalse(l.read('https://www.luogu.com.cn/problem/P1001')['ok'])

    def test_reject_nonpublic_routes(self):
        for url in ('https://evil.test/problem/P1001', 'https://www.luogu.com.cn/article/mine', 'https://www.luogu.com.cn/training/private'):
            with self.assertRaises(l.AdapterError):
                l.read(url)
