"""Opt-in live public adapter checks, local index lookup, no training writes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/acm-coach/scripts'))
import resources


def run():
    cases = [('luogu_problem_search', lambda: resources.search('luogu', '点分治', limit=2)),
             ('luogu_daily_search', lambda: resources.search('luogu-daily', '点分治', limit=2)),
             ('luogu_playlist_read', lambda: resources.read('https://www.luogu.com.cn/training/100')),
             ('luogu_statement_strict', lambda: resources.read('https://www.luogu.com.cn/problem/P3806', strict=True)),
             ('luogu_daily_article_read', lambda: resources.read('https://www.luogu.com.cn/article/zlb69qzs')),
             ('acwing_course_search', lambda: resources.search('acwing', '算法基础课', limit=2)),
             ('acwing_public_introduction', lambda: resources.read('https://www.acwing.com/activity/content/introduction/11/')),
             ('oiwiki_directory_search', lambda: resources.search('oi-wiki', '分治', limit=2)),
             ('oiwiki_article_read', lambda: resources.read('https://oi-wiki.org/graph/tree-divide/')),
             ('noi_local_index', lambda: resources.search('noi', '分治', limit=2, root=ROOT))]
    report = []
    for name, call in cases:
        try:
            result = call()
            rows = result.get('resources', [result.get('resource')])
            rows = [r for r in rows if r]
            ok = result.get('ok') is True and bool(rows)
            if name == 'luogu_statement_strict':
                ok = ok and not any(k in rows[0] for k in ('difficulty', 'lastCode', 'bestRecord')) and not rows[0]['topics']
            report.append({'case': name, 'passed': ok, 'error': result.get('error'),
                           'scope': result.get('scope'), 'resources': [
                               {k: r.get(k) for k in ('title', 'url', 'verification')} |
                               {'items': len(r.get('items', [])), 'outline_items': len(r.get('outline', [])),
                                'content_chars': len(str(r.get('content', '')))} for r in rows]})
        except Exception as exc:
            report.append({'case': name, 'passed': False, 'error': str(exc)})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=True, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    raise SystemExit(0 if all(x['passed'] for x in result) else 1)
