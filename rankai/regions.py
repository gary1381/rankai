"""Postings by place (11-07): classify jobs by region and let the searcher restrict a search to one.

Every posting's places (places.classify: 'China/Zhejiang/Hangzhou', '*' for anywhere) are stored in opp_places when
ingest writes the posting; `python -m rankai.maintenance places` rebuilds the table after places.py changes, since
parsing takes about 1.4 ms a posting and cannot run per search.

region_ids() is the filter behind search(where=...). A posting's places are paths; a place is "in" the asked one
when it is the same place or inside it (Hangzhou is in 浙江):
- on-site, hybrid or unknown work mode: one of its places is in the asked place, or is a larger place that may hold
  it ('浙江' or '全国' for Hangzhou) when the posting names at most 3 countries. A Singapore role titled
  'Asia-Pacific' names 20, so it is not taken as maybe being in Shanghai;
- remote: open to the asked place's country (a country-level place such as 'Remote (Germany)'), or, for a remote
  posting that names a city, that city is in the asked place. When the query asks for remote work, any remote
  posting in the asked country counts, and so do postings open to anywhere. Without that, anywhere postings filled
  the top 10 of every place (前端开发 in 杭州: 7 of 8 were 'Remote (Anywhere in the World)', 11-07), and remote
  posts based in other cities came in through the country (广州, 成都 for 杭州; many remote flags are our own guess);
- a posting with no known place is left out;
- a query that says on-site leaves out remote postings, one that says remote leaves out the others.
counts() is the listing: live postings by continent and country, or below one place.
"""
from collections import Counter, defaultdict

from . import fresh, places


def store(c, oid: int, o: dict):
    """o needs source, location and title."""
    c.execute('delete from opp_places where opp_id=?', (oid,))
    c.executemany('insert into opp_places(opp_id, path) values (?,?)', [(oid, p) for p in places.classify(o)])


def backfill(c) -> Counter:
    n = Counter()
    rows = c.execute('select id, source, location, title from opps').fetchall()
    c.execute('delete from opp_places')
    for r in rows:
        ps = places.classify(r)
        c.executemany('insert into opp_places(opp_id, path) values (?,?)', [(r['id'], p) for p in ps])
        n['anywhere' if ps == ['*'] else 'placed' if ps else 'unknown'] += 1
    c.commit()
    return n


def parse_where(where: str) -> list[tuple] | None:
    """The asked places; None when `where` says anywhere (no filter). ValueError when no known place is named."""
    asked = places.parse(where)
    if asked:
        return asked
    if places.ANYWHERE.search(where):
        return None
    raise ValueError(f'no known place in {where!r}; list_regions / `python -m rankai regions` shows the places known')


def region_ids(c, where: str, remote: bool = False, onsite: bool = False) -> set[int] | None:
    """Ids of postings in `where` (see the module docstring); None: no filter. remote / onsite: what the query says."""
    asked = parse_where(where)
    if asked is None:
        return None
    countries = places.countries(asked)
    by = defaultdict(list)
    rem = {}
    for oid, path, r in c.execute('select p.opp_id, p.path, o.remote from opp_places p join opps o on o.id = p.opp_id'):
        by[oid].append(path)
        rem[oid] = r == 1.0
    out = set()
    for oid, ps in by.items():
        if ps == ['*']:
            ok = remote and not onsite
        elif rem[oid]:
            ts = [tuple(p.split('/')) for p in ps]
            ok = not onsite and (places.fits(countries, [t[:1] for t in ts]) if remote else
                                 any(places.fits(countries, [t]) if len(t) == 1 else _inside(t, asked) for t in ts))
        else:
            ts = [tuple(p.split('/')) for p in ps]
            few = len({t[0] for t in ts}) <= 3
            ok = not remote and any(_inside(t, asked) or (few and places.fits(asked, [t])) for t in ts)
        if ok:
            out.add(oid)
    return out


def _inside(t: tuple, asked: list[tuple]) -> bool:
    """t is one of the asked places or inside one."""
    return any(t[:len(a)] == a for a in asked)


def of(c, ids) -> dict[int, list[str]]:
    """opp id -> its stored places."""
    ids = list(ids)
    out = defaultdict(list)
    for oid, path in c.execute(f"select opp_id, path from opp_places where opp_id in ({','.join('?' * len(ids))})",
                               ids):
        out[oid].append(path)
    return out


def _live(c, archive: bool) -> dict[int, float | None]:
    """id -> remote for the postings a live search can return."""
    gone = fresh.closed_ids(c) | (set() if archive else fresh.archived_ids(c))
    return {i: rem for i, rem in c.execute('select id, remote from opps') if i not in gone}


def counts(c, under: str = '', archive: bool = False) -> dict:
    """Live postings (no closed ones; archived ones only if archive) by place. With no `under`: by continent, then
    country, plus anywhere and unknown; a posting open to several countries counts in each. With `under` (a place or
    region name): how many a search with where=under draws from, split into on-site / hybrid and remote open to it,
    how many open-to-anywhere postings a remote search adds, and the places one level below it, or each asked
    country for a region name."""
    live = _live(c, archive)
    paths = defaultdict(list)
    for oid, path in c.execute('select opp_id, path from opp_places'):
        if oid in live:
            paths[oid].append(path)
    if not under:
        cont, country, rem = defaultdict(set), defaultdict(set), defaultdict(set)
        anywhere = {i for i, ps in paths.items() if ps == ['*']}
        for oid, ps in paths.items():
            for p in ps:
                if p == '*':
                    continue
                k = p.split('/')[0]
                cont[places.CONTINENT.get(k, 'Other')].add(oid)
                country[k].add(oid)
                if live[oid] == 1.0:
                    rem[k].add(oid)
        by_cont = defaultdict(list)
        for k, ids in country.items():
            by_cont[places.CONTINENT.get(k, 'Other')].append({'place': k, 'postings': len(ids), 'remote': len(rem[k])})
        return {'postings': len(live), 'anywhere': len(anywhere), 'unknown': len(live) - len(paths),
                'continents': [{'continent': k, 'postings': len(cont[k]),
                                'countries': sorted(by_cont[k], key=lambda x: -x['postings'])}
                               for k in sorted(cont, key=lambda k: -len(cont[k]))]}
    asked = parse_where(under)
    if asked is None:
        return counts(c, '', archive)
    inside = region_ids(c, under) & set(live)
    below, coarser = defaultdict(set), set()
    for oid in inside:
        for p in paths[oid]:
            t = tuple(p.split('/'))
            for a in asked:
                if t[:len(a)] == a:  # at or below an asked place: group by the next level down
                    below[t[:len(a) + 1] if len(asked) == 1 else a].add(oid)
                elif a[:len(t)] == t and live[oid] != 1.0:  # only a larger place is known ('浙江' for Hangzhou)
                    coarser.add(oid)
    one = asked[0] if len(asked) == 1 else None
    rows = sorted(({'place': places.label('/'.join(k)) + (' (no finer place)' if k == one else ''), 'postings': len(v),
                    'remote': sum(live[i] == 1.0 for i in v)} for k, v in below.items()), key=lambda x: -x['postings'])
    return {'where': under, 'asked': [places.label('/'.join(a)) for a in asked], 'postings': len(inside),
            'onsite_or_hybrid': sum(live[i] != 1.0 for i in inside), 'remote': sum(live[i] == 1.0 for i in inside),
            'anywhere_if_remote_asked': sum(ps == ['*'] for ps in paths.values()),
            'only_larger_place_known': len(coarser),
            'below': rows}
