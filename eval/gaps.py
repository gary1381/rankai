"""Which held-out queries have no good answer anywhere in the labeled pool, and what kind of query are they?
Descriptive, run after the v2 results (10-30); it tests nothing.

python eval/gaps.py   -> eval/gaps.json; prints coverage by segment and the gap list
  queries: v1 scored on the new corpus (labels_v1b) + v2 (labels_v2), 96 in all.
  covered = some pooled posting has mean rel >= 2. The pool holds every evaluated arm's top 10, so this is a lower
  bound on what the corpus holds; a good posting that no arm ranks in the top 10 does not reach the searcher either.
  Segments use the constraints F and J use: rule parse + cached AI rewrite (remote, kinds, location).
  Category, first rule that applies: co-founder; bounty; local (a location and not remote);
  project outsourcing (kinds = outsourcing only, not remote); remote, other.
  supply: for each city a local query names, postings in the v2 snapshot whose location field names that city,
  by source (is the gap in the corpus or in the ranking?).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rankai import qrewrite, search  # noqa: E402
from rankai.db import connect  # noqa: E402

SETS = [('v1', 'v1b'), ('v2', 'v2')]  # (query set, labels file)
CATEGORIES = ['local', 'project outsourcing', 'co-founder', 'bounty', 'remote, other']
ALIASES = {'hangzhou': ['杭州'], 'beijing': ['北京'], 'chengdu': ['成都'], 'guangzhou': ['广州'], 'nanjing': ['南京'],
           'suzhou': ['苏州'], 'shanghai': ['上海'], 'shenzhen': ['深圳'], 'wuhan': ['武汉'], 'taipei': ['台北', '臺北'],
           'osaka': ['大阪'], 'tokyo': ['东京', '東京'], 'melbourne': ['墨尔本'],
           'new zealand': ['auckland', 'wellington', 'christchurch']}


def supply(rows: list[dict]) -> dict:
    c = connect()
    mx = c.execute("select max_opp_id from snapshots where name='v2'").fetchone()[0]
    opps = [(o['location'].lower(), o['source']) for o in c.execute(
        'select location, source from opps where id <= ? and location is not null', (mx,))]
    out = {}
    for r in rows:
        if r['category'] != 'local':
            continue
        city = r['location'].split(',')[0].strip().lower()
        if city not in out:
            names = [city] + ALIASES.get(city, [])
            src = Counter(s for loc, s in opps if any(n in loc for n in names))
            out[city] = {'postings': sum(src.values()), 'by_source': dict(src.most_common()), 'queries': {}}
        out[city]['queries'][r['qid']] = r['covered']
    return out


def category(qp: dict, location) -> str:
    kinds = qp['kinds']
    if 'cofounder' in kinds:
        return 'co-founder'
    if 'bounty' in kinds:
        return 'bounty'
    if location and not qp['remote']:
        return 'local'
    if kinds == {'outsourcing'} and not qp['remote']:
        return 'project outsourcing'
    return 'remote, other'


def buyer_side(q: str) -> bool:
    """The searcher wants a provider for a project, not work: the corpus holds job posts, so these are reported apart
    from coverage (docs/EVALUATION.md, coverage gaps). All 12 such queries in v1 + v2 fit, read by hand."""
    rw = qrewrite.rewrite(q)
    return category(search.ai_constraints(q, rw), rw.get('location')) == 'project outsourcing'


def main():
    rows = []
    for qset, labels in SETS:
        best: dict[str, float] = {}
        for x in map(json.loads, (ROOT / 'eval' / f'labels_{labels}.jsonl').open()):
            best[x['qid']] = max(best.get(x['qid'], 0), x['rel'])
        for q in map(json.loads, (ROOT / 'eval' / f'queries_{qset}.jsonl').open()):
            rw = qrewrite.rewrite(q['query'])
            qp = search.ai_constraints(q['query'], rw)
            rows.append({'qid': q['id'], 'set': qset, 'lang': q['lang'], 'query': q['query'],
                         'remote': bool(qp['remote']), 'location': rw.get('location'),
                         'kinds': ','.join(sorted(qp['kinds'])) or '-', 'category': category(qp, rw.get('location')),
                         'best_rel': round(best.get(q['id'], 0), 2), 'covered': best.get(q['id'], 0) >= 2})

    def seg(key) -> dict:
        n, k = Counter(), Counter()
        for r in rows:
            n[key(r)] += 1
            k[key(r)] += r['covered']
        return {g: {'covered': k[g], 'queries': n[g]} for g in sorted(n, key=lambda g: -n[g])}

    rep = {'queries': len(rows), 'covered': sum(r['covered'] for r in rows),
           'by_category': {c: seg(lambda r: r['category'])[c] for c in CATEGORIES},
           'by_lang': seg(lambda r: r['lang']), 'by_remote': seg(lambda r: 'remote' if r['remote'] else 'not remote'),
           'by_location': seg(lambda r: 'location named' if r['location'] else 'no location'),
           'by_kinds': seg(lambda r: r['kinds']), 'local_supply': supply(rows), 'rows': rows}
    buy = rep['by_category']['project outsourcing']
    rep['no_buyer_side'] = {'covered': rep['covered'] - buy['covered'], 'queries': rep['queries'] - buy['queries']}
    (ROOT / 'eval' / 'gaps.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"{rep['covered']}/{rep['queries']} queries have a pooled posting with rel >= 2")
    print(f"without buyer-side outsourcing: {rep['no_buyer_side']['covered']}/{rep['no_buyer_side']['queries']}"
          f" (buyer-side alone {buy['covered']}/{buy['queries']})")
    for k in ('by_category', 'by_lang', 'by_remote', 'by_location', 'by_kinds'):
        print(k, {g: f"{v['covered']}/{v['queries']}" for g, v in rep[k].items()})
    print('\npostings per city named by a local query (v2 snapshot); query + = covered, - = gap:')
    for city, v in sorted(rep['local_supply'].items(), key=lambda kv: kv[1]['postings']):
        q = ' '.join(f"{k}{'+' if ok else '-'}" for k, ok in v['queries'].items())
        print(f"  {city:18.18} {v['postings']:5}  {q:22} {dict(list(v['by_source'].items())[:3])}")
    for c in CATEGORIES:
        print(f'\n-- gaps: {c}')
        for r in rows:
            if r['category'] == c and not r['covered']:
                print(f"  {r['qid']:7} best {r['best_rel']:.2f}  {r['location'] or '-':22.22} {r['kinds']:12.12} {r['query']}")


if __name__ == '__main__':
    main()
