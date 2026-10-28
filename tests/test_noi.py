"""NOI index tests use isolated files and mocked extraction only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / '.agents/skills/acm-coach/scripts/noi_adapter.py'
spec = importlib.util.spec_from_file_location('noi_adapter', SCRIPT)
noi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noi)


class NoiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdf = Path(self.tmp.name) / 'misleading-1999.pdf'
        self.pdf.write_bytes(b'isolated fixture')
        self.index = Path(self.tmp.name) / 'index.json'

    def build(self):
        with patch.object(noi, 'extract_pages', return_value=(['竞赛大纲（2025年修订版）', '高级算法\n点 分 治\n其他条目'], ['fixture', 'fixture'])):
            return noi.build_index(self.pdf, self.index)

    def test_search_preserves_page_original_and_evidence(self):
        self.build()
        results = noi.search('点分治', self.pdf, index_path=self.index)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['page'], 2)
        self.assertIn('点 分 治', results[0]['text'])
        self.assertEqual(results[0]['source_pdf'], str(self.pdf.resolve()))
        self.assertEqual(results[0]['edition_evidence'][0]['page'], 1)
        self.assertIn('2025', results[0]['edition_evidence'][0]['text'])

    def test_model_ocr_consent_source_completeness_and_atomic_import(self):
        self.build()
        old = self.index.read_bytes()
        transcript = Path(self.tmp.name) / 'transcript.json'
        value = {'schema_version': 1, 'sha256': noi.digest(self.pdf),
                 'page_count': 2, 'pages': [
                     {'page': 1, 'text': '竞赛大纲（2025年修订版）'},
                     {'page': 2, 'text': '点分治'}]}
        transcript.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'consent'):
            noi.import_model_ocr(self.pdf, transcript, self.index)
        for field, bad in [('sha256', 'wrong'), ('page_count', 3), ('schema_version', 99),
                           ('pages', [{'page': 2, 'text': '乱序'}, {'page': 1, 'text': '原文'}]),
                           ('pages', [{'page': 1, 'text': ''}, {'page': 2, 'text': '原文'}])]:
            transcript.write_text(json.dumps({**value, field: bad}), encoding='utf-8')
            with self.assertRaises(ValueError):
                noi.import_model_ocr(self.pdf, transcript, self.index, confirmed=True)
            self.assertEqual(old, self.index.read_bytes())
        transcript.write_text(json.dumps(value), encoding='utf-8')
        with patch.object(noi, 'extract_pages', side_effect=AssertionError('local OCR must not run')):
            noi.import_model_ocr(self.pdf, transcript, self.index, confirmed=True)
        result = noi.search('点分治', self.pdf, index_path=self.index)[0]
        self.assertEqual(result['page'], 2)
        self.assertIn('model vision OCR', result['extraction'])

    def test_changed_pdf_rejected(self):
        self.build()
        self.pdf.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            noi.search('算法', self.pdf, index_path=self.index)

    def test_unknown_version_rejected(self):
        index = self.build()
        index['schema_version'] = 999
        self.index.write_text(json.dumps(index), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            noi.search('算法', self.pdf, index_path=self.index)

    def test_no_edition_guess_from_filename(self):
        self.assertIsNone(noi._make_index(self.pdf, ['无版次信息'], ['fixture'])['edition'])

    def test_missing_and_empty_query(self):
        with self.assertRaises(FileNotFoundError):
            noi.search('不存在', self.pdf, index_path=self.index)
        with self.assertRaises(ValueError):
            noi.search(' ', self.pdf, index_path=self.index)

    def test_failed_extraction_preserves_index(self):
        self.build()
        old = self.index.read_bytes()
        with patch.object(noi, 'extract_pages', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                noi.build_index(self.pdf, self.index)
        self.assertEqual(old, self.index.read_bytes())


if __name__ == '__main__':
    unittest.main()
