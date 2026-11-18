"""python -m rankai {ingest [source ...] | vectors | search "query" [--arm L] [-k 10] [--archive] [--where PLACE] [--field F] |
regions [PLACE] [--archive] | judge-live [--max-usd 0.5] [--workers 2] | stats | snapshot NAME}"""
import argparse
import json

from . import ingest, judge, places, regions, search
from .db import connect, now


def stats():
    c = connect()
    print('by source:')
    for r in c.execute('select source, source_type, count(*) n, sum(salary_min is not null) sal, sum(remote=1) rem, '
                       "sum(lang='zh') zh, max(posted_at) newest from opps group by source order by n desc"):
        print(' ', dict(r))
    print('by kind:', dict(c.execute('select kind, count(*) from opps group by kind').fetchall()))
    n, cl = c.execute('select count(*), count(distinct cluster_id) from opps').fetchone()
    print(f'opps {n}, clusters {cl}, vectors {c.execute("select count(*) from vecs").fetchone()[0]}')
    print('last fetch errors:', [dict(r) for r in c.execute('select source, ts, note from fetch_log where ok=0 '
                                                            'order by ts desc limit 5')])


def show(results):
    for i, r in enumerate(results, 1):
        sal = f" {r['salary_min']:.0f}-{r['salary_max']:.0f} {r['currency']}/{r['period']}" if r['salary_min'] else ''
        f = r.get('feats') or {}
        print(f"{i:2d}. [{r['score']:.3f}] {r['title'][:70]} — {r['org'] or '?'} | {r['location'] or ''} | "
              f"{r['kind']}{sal} | {r['source']} {(r['posted_at'] or '')[:10]}")
        if r.get('places'):
            print('     places: ' + places.name([tuple(p.split('/')) for p in r['places']]).replace('*', 'anywhere'))
        if r.get('mismatch'):
            print('     does not match: ' + '; '.join(r['mismatch']))
        if f:
            print('     ' + ' '.join(f'{k}={v:.2f}' for k, v in f.items()))
        print(f"     {r['url']}")


def show_regions(d: dict):
    if 'continents' in d:
        print(f"{d['postings']:,} live postings; anywhere {d['anywhere']:,}, no known place {d['unknown']:,}")
        for ct in d['continents']:
            print(f"{ct['continent']}: {ct['postings']:,}")
            for x in ct['countries'][:12]:
                print(f"  {x['place']:<24} {x['postings']:>6,}  (remote {x['remote']:,})")
            if len(ct['countries']) > 12:
                print(f"  ... {len(ct['countries']) - 12} more")
        return
    print(f"{d['where']} = {' / '.join(d['asked'][:6])}{' …' if len(d['asked']) > 6 else ''}: {d['postings']:,} "
          f"postings (on-site or hybrid {d['onsite_or_hybrid']:,}, remote open to it {d['remote']:,}; a remote "
          f"search adds {d['anywhere_if_remote_asked']:,} open to anywhere); {d['only_larger_place_known']:,} "
          f"on-site ones name only a larger place")
    for x in d['below'][:30]:
        print(f"  {x['place']:<40} {x['postings']:>6,}  (remote {x['remote']:,})")


def main():
    ap = argparse.ArgumentParser(prog='rankai')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('ingest')
    p.add_argument('sources', nargs='*')
    sub.add_parser('vectors')
    p = sub.add_parser('search')
    p.add_argument('query')
    p.add_argument('--arm', default='L', choices=search.ARMS)
    p.add_argument('-k', type=int, default=10)
    p.add_argument('--json', action='store_true')
    p.add_argument('--archive', action='store_true', help='also rank jobs posted more than 30 days ago')
    p.add_argument('--where', help='only postings in this place or region, e.g. 杭州, Berlin, Europe')
    p.add_argument('--field', help='only these fields, comma-separated: ' + ', '.join(judge.FAMILIES))
    p = sub.add_parser('regions', help='live postings by continent and country, or below one place')
    p.add_argument('place', nargs='?', default='')
    p.add_argument('--archive', action='store_true')
    p = sub.add_parser('judge-live', help='Haiku field / scam judgment for live postings that have none')
    p.add_argument('--max-usd', type=float, default=0.5, help='stop after this much spend in this run')
    p.add_argument('--workers', type=int, default=2, help='API calls in flight at once')
    sub.add_parser('stats')
    p = sub.add_parser('snapshot')
    p.add_argument('name')
    p.add_argument('--note', default='')
    a = ap.parse_args()
    if a.cmd == 'ingest':
        ingest.run(set(a.sources) or None)
    elif a.cmd == 'vectors':
        print('embedded', search.build_vectors())
    elif a.cmd == 'search':
        try:
            res = search.search(a.query, a.arm, a.k, fallback=True, archive=a.archive, where=a.where,
                                field=a.field)
        except ValueError as e:
            raise SystemExit(str(e))
        print(json.dumps(res, ensure_ascii=False, default=str) if a.json else '', end='')
        if not a.json:
            print('parsed:', search.parse_query(a.query))
            show(res)
    elif a.cmd == 'regions':
        try:
            show_regions(regions.counts(connect(), a.place, a.archive))
        except ValueError as e:
            raise SystemExit(str(e))
    elif a.cmd == 'judge-live':
        ids = judge.live_unjudged(connect())
        print(f'{len(ids)} live postings without a judgment', flush=True)
        print('judged', judge.ensure(ids, a.max_usd, a.workers))
    elif a.cmd == 'stats':
        stats()
    elif a.cmd == 'snapshot':
        c = connect()
        mx, n = c.execute('select max(id), count(*) from opps').fetchone()
        c.execute('insert into snapshots values (?,?,?,?,?)', (a.name, now(), mx, n, a.note))
        c.commit()
        print(f'snapshot {a.name}: max_opp_id={mx} n={n}')


if __name__ == '__main__':
    main()
