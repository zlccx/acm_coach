"""Local NOI syllabus page search; no training-data writes.

Only stdlib imports in the coach process. Extraction uses PATH pdftotext,
or an existing Python with pypdf/pypdfium2 (NOI_PDF_PYTHON), then the local
glm-ocr skill (NOI_OCR_SCRIPT) for pages without a text layer. Nothing installs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PDF = ROOT / "NOI_Syllabus_Edition_2025.pdf"
DEFAULT_INDEX = ROOT / "resources/noi-syllabus-2025.index.json"
VERSION = 1


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _python():
    configured = os.environ.get('NOI_PDF_PYTHON')
    if configured:
        return configured
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    return str(bundled) if bundled.is_file() else sys.executable


def _run(args):
    return subprocess.run(args, check=True, capture_output=True, encoding='utf-8').stdout


def extract_pages(pdf_path):
    """Return (page texts, per-page extraction methods). OCR stays local."""
    executable = shutil.which('pdftotext')
    if executable:
        raw = _run([executable, '-layout', '-enc', 'UTF-8', str(pdf_path), '-'])
        pages = raw.split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        methods = ['pdftotext'] * len(pages)
    else:
        raw = _run([_python(), '-c', 'import json,sys,pypdf; print(json.dumps([p.extract_text() or "" for p in pypdf.PdfReader(sys.argv[1]).pages],ensure_ascii=True))', str(pdf_path)])
        pages = json.loads(raw)
        methods = ['pypdf'] * len(pages)
    missing = [i for i, text in enumerate(pages) if not text.strip()]
    if missing:
        script = Path(os.environ.get('NOI_OCR_SCRIPT', str(Path.home() / '.codex/skills/glm-ocr/scripts/ocr.py')))
        if not script.is_file():
            raise RuntimeError('PDF has pages without text. Set NOI_OCR_SCRIPT to the local glm-ocr script; it requires Ollama glm-ocr and pypdfium2 in NOI_PDF_PYTHON.')
        with tempfile.TemporaryDirectory(prefix='noi-ocr-') as tmp:
            render = 'import sys,pypdfium2 as p; d=p.PdfDocument(sys.argv[1]); d[int(sys.argv[2])].render(scale=2).to_pil().save(sys.argv[3])'
            for i in missing:
                image = Path(tmp) / 'page.png'
                _run([_python(), '-c', render, str(pdf_path), str(i), str(image)])
                text = _run([sys.executable, str(script), str(image)])
                if not text.strip() or text.lstrip().startswith('[ERROR]'):
                    raise RuntimeError('Local OCR failed on PDF page %d: %s' % (i + 1, text[:300]))
                pages[i] = text
                methods[i] = 'glm-ocr (local Ollama; OCR may contain errors)'
                print('OCR page %d/%d complete' % (i + 1, len(pages)), file=sys.stderr)
    if not pages:
        raise ValueError('PDF has no pages')
    return pages, methods


def _make_index(pdf_path, texts, methods):
    evidence = []
    for i, text in enumerate(texts):
        for line in text.splitlines():
            if re.search(r'20\d{2}\s*年?\s*修订版', line):
                evidence.append({'page': i + 1, 'text': line.strip()})
    return {'schema_version': VERSION, 'source_pdf': str(Path(pdf_path).resolve()),
            'sha256': digest(pdf_path), 'edition_evidence': evidence,
            'edition': evidence[0]['text'] if evidence else None,
            'page_numbering': '1-based PDF physical pages; printed page numbers may differ',
            'pages': [{'page': i + 1, 'text': text, 'extraction': methods[i]} for i, text in enumerate(texts)]}


def import_model_ocr(pdf_path, transcript_path, index_path=None, confirmed=False):
    """Import a complete, source-bound transcription after the user's consent."""
    if not confirmed:
        raise ValueError('Model OCR requires explicit user consent before reading pages')
    pdf_path = Path(pdf_path).resolve()
    transcript = json.loads(Path(transcript_path).read_text(encoding='utf-8'))
    if transcript.get('schema_version') != 1:
        raise ValueError('Unknown OCR transcript version')
    if transcript.get('sha256') != digest(pdf_path):
        raise ValueError('OCR transcript belongs to another PDF or the PDF changed')
    count = transcript.get('page_count')
    pages = transcript.get('pages')
    if type(count) is not int or count < 1 or not isinstance(pages, list) or len(pages) != count:
        raise ValueError('OCR transcript must contain every physical PDF page')
    texts = []
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or type(page.get('page')) is not int
                or page['page'] != number or not isinstance(page.get('text'), str)
                or not page['text'].strip()):
            raise ValueError('OCR pages must be nonempty and numbered consecutively from 1')
        texts.append(page['text'])
    # Reuse hash, edition evidence and atomic persistence without invoking local OCR.
    return _save_index(pdf_path, texts,
                       ['model vision OCR (user approved; may contain errors)'] * count,
                       index_path)


def _save_index(pdf_path, texts, methods, index_path=None):
    pdf_path = Path(pdf_path).resolve()
    target = Path(index_path) if index_path else (DEFAULT_INDEX if pdf_path == DEFAULT_PDF.resolve() else pdf_path.with_suffix('.index.json'))
    result = _make_index(pdf_path, texts, methods)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement: a failed extraction never destroys the existing index.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        temp = Path(stream.name)
    try:
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return result


def build_index(pdf_path=DEFAULT_PDF, index_path=None):
    texts, methods = extract_pages(Path(pdf_path).resolve())
    return _save_index(pdf_path, texts, methods, index_path)


def search(query, pdf_path=None, limit=10, index_path=None):
    if not query.strip() or limit < 1:
        raise ValueError('query must not be empty and limit must be positive')
    pdf = Path(pdf_path or DEFAULT_PDF).resolve()
    target = Path(index_path) if index_path else (DEFAULT_INDEX if pdf == DEFAULT_PDF.resolve() else pdf.with_suffix('.index.json'))
    if not target.is_file():
        raise FileNotFoundError('Index missing; run noi_adapter.py build --pdf ... first')
    index = json.loads(target.read_text(encoding='utf-8'))
    if index.get('schema_version') != VERSION:
        raise ValueError('Unknown NOI index version; rebuild explicitly')
    if index['source_pdf'] != str(pdf) or index['sha256'] != digest(pdf):
        raise ValueError('NOI index is stale or belongs to another PDF; rebuild explicitly')
    normalize = lambda text: re.sub(r'\s+', '', text).casefold()
    needle = normalize(query)
    results = []
    for page in index['pages']:
        if needle in normalize(page['text']):
            results.append({**page, 'source_pdf': index['source_pdf'], 'sha256': index['sha256'],
                            'edition_evidence': index['edition_evidence']})
    return results[:limit]


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'search', 'import-model-ocr'])
    parser.add_argument('query', nargs='?')
    parser.add_argument('--pdf', type=Path, default=DEFAULT_PDF)
    parser.add_argument('--index', type=Path)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--transcript', type=Path, help='Complete model OCR JSON transcript')
    parser.add_argument('--user-approved', action='store_true', help='Use only after the user explicitly chose model vision OCR')
    args = parser.parse_args()
    try:
        if args.command in ('build', 'import-model-ocr'):
            if args.command == 'import-model-ocr':
                if not args.transcript:
                    parser.error('import-model-ocr requires --transcript')
                result = import_model_ocr(args.pdf, args.transcript, args.index, args.user_approved)
            else:
                result = build_index(args.pdf, args.index)
            output = {k: v for k, v in result.items() if k != 'pages'}
            output['page_count'] = len(result['pages'])
        else:
            if not args.query:
                parser.error('search requires a query')
            output = search(args.query, args.pdf, args.limit, args.index)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
