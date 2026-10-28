"""Offline unified-resource contract checks; never write the user's training data."""
import contextlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / '.agents/skills/acm-coach/scripts'
sys.path.insert(0, str(SCRIPTS))
resources = importlib.import_module('resources')
coach = importlib.import_module('coach')


class UnifiedResourceTests(unittest.TestCase):
    def test_oiwiki_result_preserves_provenance(self):
        row = dict(title='树分治', url='https://oi-wiki.org/graph/tree-divide/',
                   source='oi-wiki', resource_type='tutorial', topics=[],
                   retrieved_at='2026-10-27T00:00:00+00:00',
                   verification='navigation_verified', raw_source={'method': 'fixture'})
        with patch.object(resources.oiwiki_adapter, 'search', return_value=[row]):
            result = resources.search('oi-wiki', '分治')
        self.assertTrue(result['ok'])
        self.assertEqual(result['resources'], [row])
        self.assertEqual(result['scope'], 'directory_titles_only')
        self.assertEqual(result['fallback']['web_search_query'], 'site:oi-wiki.org 分治')

    def test_oiwiki_empty_is_success_with_scoped_warning(self):
        with patch.object(resources.oiwiki_adapter, 'search', return_value=[]):
            result = resources.search('oi-wiki', '点分治')
        self.assertTrue(result['ok'])
        self.assertEqual(result['resources'], [])
        self.assertIn('不代表正文不存在', result['warning'])
        self.assertIn('browser', result['warning'])

    def test_oiwiki_network_failure_and_read_failure_have_fallback(self):
        with patch.object(resources.oiwiki_adapter, 'search', side_effect=RuntimeError('offline')):
            result = resources.search('oi-wiki', '分治')
        self.assertFalse(result['ok'])
        self.assertEqual(result['resources'], [])
        self.assertIn('offline', result['error'])
        self.assertIn('fallback', result)
        with patch.object(resources.oiwiki_adapter, 'read', side_effect=RuntimeError('offline')):
            result = resources.read('https://oi-wiki.org/graph/tree-divide/')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['resource'])
        self.assertIn('fallback', result)

    def test_strict_rejects_tutorial_before_network(self):
        with patch.object(resources.oiwiki_adapter, 'read') as read:
            with self.assertRaises(ValueError):
                resources.read('https://oi-wiki.org/graph/tree-divide/', strict=True)
            read.assert_not_called()

    def test_cli_adapter_failure_returns_nonzero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            stderr = io.StringIO()
            with patch.object(resources.oiwiki_adapter, 'search', side_effect=RuntimeError('offline')):
                with contextlib.redirect_stderr(stderr):
                    status = coach.main(['--root', root, 'resource-search', 'oi-wiki', '分治'])
            self.assertEqual(status, 1)
            self.assertFalse(json.loads(stderr.getvalue())['ok'])
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_real_cli_invalid_input_is_nonzero_without_state_writes(self):
        with tempfile.TemporaryDirectory() as root:
            proc = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'coach.py'),
                                   '--root', root, 'resource-read', 'https://example.org/'],
                                  capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('仅支持', proc.stderr)
            self.assertNotIn('Traceback', proc.stderr)
            self.assertEqual(list(Path(root).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
