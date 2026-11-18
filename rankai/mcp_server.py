"""MCP server: the opportunity search for agents (docs/MCP.md).

python -m rankai.mcp_server        stdio; register with, e.g.
  claude mcp add rankai -e PYTHONPATH=/path/to/rankai -- /path/to/python3 -m rankai.mcp_server

Tools: search_opportunities (default arm L, J if L cannot run; `where` keeps one place, 11-07; `field` keeps fields, 11-08), get_opportunity (full
posting + the same job from other sources), corpus_info (what the corpus covers and how fresh it is), list_regions
(live postings by continent and country, or below one place), rate_result (an agent's 0-3 grade of one result).
Free text is redacted (rankai.text.redact) because the caller is usually a cloud model; url / apply_url stay.
Searches leave out postings their board no longer lists (rankai/fresh.py); every card says when the posting was last
seen and, where the source can tell, whether it is still listed.
Every search is logged to data/mcp_searches.jsonl and every rating to data/agent_feedback.jsonl (outside git), so
agent use can become labels for L later. Searches run one at a time: the reranker is one GPU service and the
rewrite cache is one file.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import fresh, judge, places, regions, search as S
from .db import ROOT, connect
from .text import plain, redact

SEARCH_LOG = ROOT / 'data' / 'mcp_searches.jsonl'
FEEDBACK = ROOT / 'data' / 'agent_feedback.jsonl'
# L predicts the gain 2^grade - 1 (0-7; 2.0 is a grade of about 1.6), not the grade itself. The bands are set from
# the v3 held-out pairs (756, labels L never saw): >= 2.0 -> 54% good (label >= 2),
# 92% useful (>= 1); 1.0-2.0 -> 6% good, 65% useful; < 1.0 -> 0% good, 18% useful. Every v3 query whose top result
# was >= 2.0 had a good posting in the pool (12/12); none whose top was < 1.0 did (0/11).
STRONG, POSSIBLE = 2.0, 1.0
REMOTE = {1.0: 'remote', 0.5: 'hybrid', 0.0: 'on-site'}
_LOCK = threading.Lock()

INSTRUCTIONS = """Search a local corpus of job, gig, bounty and collaboration postings (Chinese and English; corpus_info has the count).
Write the searcher's need as one natural query in any language, with constraints in words (remote, part-time,
minimum pay, city); the server rewrites it with AI and ranks with a learned model. A search takes 5-20 seconds.
Each result has `fit` (strong / possible / weak) and `mismatch` (stated constraints the posting clearly breaks).
`verdict` says whether the corpus likely holds a good match. Unless it is "good match likely", tell the user that no
good match was found and present results only as loosely related. Coverage is good for remote tech jobs and poor for city-specific jobs,
outsourcing buyers, bounties and co-founder searches; corpus_info has the numbers and the data date.
Jobs posted more than 30 days ago are archived and left out; search again with include_archive=true when the user
wants older postings too.
When the user wants jobs in one place, pass where (a city, province, country or region in any language, e.g. 杭州,
Berlin, Europe): only postings there are ranked, plus remote ones open to that country; postings open to anywhere
count only when the query asks for remote work. list_regions shows how many postings each place has.
After using results, rate the ones you looked at with rate_result (0 not useful ... 3 exactly what was asked)."""

mcp = MCPServer('rankai', instructions=INSTRUCTIONS)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _pay(r) -> str | None:
    if not r['salary_min']:
        return None
    return f"{r['salary_min']:,.0f}-{r['salary_max']:,.0f} {r['currency']}/{r['period']}"


def _fit(score: float | None) -> str | None:
    if score is None:
        return None
    return 'strong' if score >= STRONG else 'possible' if score >= POSSIBLE else 'weak'


def _card(r, body_chars: int | None, cut: dict, arch: str) -> dict:
    """cut: fresh.cutoffs(); arch: fresh.archive_cutoff()."""
    body = redact(plain(r['text']))
    return {'opp_id': r['id'], 'title': redact(r['title'] or ''), 'org': redact(r['org'] or '') or None,
            'location': redact(r['location'] or '') or None, 'kind': r['kind'],
            'work_mode': REMOTE.get(r['remote'], 'unknown'), 'pay': _pay(r), 'posted': (r['posted_at'] or '')[:10] or None,
            'places': [places.label(p) for p in r['places']] if 'places' in r.keys() else None,  # search() sets it
            'source': r['source'], 'url': r['url'], 'apply_url': r['apply_url'] or None,
            'last_seen': (r['last_seen'] or '')[:10] or None, 'still_listed': fresh.listed(r, cut),
            'archived': fresh.archived(r, arch),
            'text': body if body_chars is None else body[:body_chars] + ('…' if len(body) > body_chars else '')}


def _append(path, rec: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@mcp.tool(annotations=READ)
def search_opportunities(query: str, k: int = 10, include_archive: bool = False, where: str = '',
                         field: str = '') -> dict:
    """Find postings for a searcher's need, best first. query: the need in natural language, any language, with its
    constraints (e.g. "远程 兼职 RAG 工程师，时薪 50 美元以上"). k: number of results, 1-30. include_archive: also rank
    jobs posted more than 30 days ago, which are left out by default (each result's `archived` says which it is).
    where: keep only postings in this place (city, province, country or region, any language: 杭州, Berlin, Europe);
    remote postings count when open to its country, open-to-anywhere ones only if the query asks for remote work.
    Each result's `places` says where the posting is. field: keep only postings in these fields, comma-separated:
    engineering, data_ml, design, product, sales_marketing, support_success, operations, research, other (an AI label
    per posting; postings not labeled yet are left out). Each result's `field` says its label."""
    k = max(1, min(int(k), 30))
    t0 = time.time()
    with _LOCK:
        try:
            res = S.search(query, 'L', k + 10, fallback=True, archive=include_archive, where=where or None,
                           field=field or None)
        except ValueError as e:  # where names no known place, or field an unknown field
            raise ToolError(str(e)) from None
    arm = 'L' if res and set(res[0].get('feats') or {}) != {'rerank'} else 'J'  # search() falls back to J silently
    sid = uuid.uuid4().hex[:12]
    cut, arch = fresh.cutoffs(connect()), fresh.archive_cutoff()
    fam = judge.fields(connect(), [r['id'] for r in res])
    out, seen = [], {}
    for r in res:
        cl = r['cluster_id'] or -r['id']
        if cl in seen:  # the same job from another source or a repost: keep the higher-ranked one
            seen[cl]['duplicates_hidden'] += 1
            continue
        if len(out) == k:
            continue
        score = float(r['score'])
        out.append(_card(r, 300, cut, arch) | {'score': round(score, 3), 'fit': _fit(score) if arm == 'L' else None,
                                         'mismatch': r['mismatch'], 'field': fam.get(r['id']),
                                         'duplicates_hidden': 0})
        seen[cl] = out[-1]
    top = max((x['score'] for x in out), default=None) if arm == 'L' else None
    verdict = ('unknown (fallback ranking, no calibrated score)' if arm != 'L' else
               'nothing good' if top is None or top < POSSIBLE else
               'good match likely' if top >= STRONG else 'good match unlikely (related results only)')
    _append(SEARCH_LOG, {'search_id': sid, 'ts': _now(), 'query': query, 'k': k, 'arm': arm,
                         'include_archive': include_archive, 'where': where or None, 'field': field or None,
                         'ms': round(1000 * (time.time() - t0)),
                         'results': [{'opp_id': x['opp_id'], 'score': x['score']} for x in out]})
    return {'search_id': sid, 'ranking': arm, 'verdict': verdict, 'results': out} | (
        {'why_not_L': res[0].get('fallback')} if arm == 'J' and res and res[0].get('fallback') else {})


@mcp.tool(annotations=READ)
def get_opportunity(opp_id: int) -> dict:
    """One posting in full (contact details redacted; use url / apply_url to apply), plus the same job as listed by
    other sources. still_listed false: the board no longer lists it, so it has most likely closed."""
    c = connect()
    r = c.execute('select * from opps where id=?', (opp_id,)).fetchone()
    if r is None:
        raise ToolError(f'no posting {opp_id}')
    same = c.execute('select id, source, url, posted_at from opps where cluster_id=? and id!=? order by id',
                     (r['cluster_id'], r['id'])).fetchall() if r['cluster_id'] else []
    return _card(r, None, fresh.cutoffs(c), fresh.archive_cutoff()) | {
        'places': [places.label(x) for x in regions.of(c, [r['id']]).get(r['id'], [])],
        'tags': redact(r['tags'] or '') or None, 'first_seen': (r['first_seen'] or '')[:10] or None,
        'also_listed': [{'opp_id': x['id'], 'source': x['source'], 'url': x['url'],
                         'posted': (x['posted_at'] or '')[:10] or None} for x in same]}


@mcp.tool(annotations=READ)
def corpus_info() -> dict:
    """What the corpus covers: postings by source, kind and language, and when each source was last fetched."""
    c = connect()
    closed = {s: c.execute('select count(*) from opps where source=? and last_seen < ?', (s, t)).fetchone()[0]
              for s, t in fresh.cutoffs(c).items()}
    w, args = fresh.archived_where()
    arch = dict(c.execute(f'select source, count(*) from opps where {w} group by source', args).fetchall())
    src = [{'source': r['source'], 'type': r['source_type'], 'postings': r['n'], 'remote': r['rem'],
            'chinese': r['zh'], 'closed_hidden': closed.get(r['source'], 0), 'archived': arch.get(r['source'], 0),
            'last_fetched': r['fetched']}
           for r in c.execute("select o.source, o.source_type, count(*) n, sum(o.remote=1) rem, sum(o.lang='zh') zh, "
                              '(select max(ts) from fetch_log f where f.source=o.source and f.ok=1) fetched '
                              'from opps o group by o.source order by n desc')]
    return {'postings': sum(x['postings'] for x in src),
            'closed_hidden': sum(closed.values()),  # no longer on their board: kept, but searches leave them out
            # jobs posted more than 30 days ago (some also closed): kept, left out unless include_archive
            'archived': sum(arch.values()),
            'by_kind': dict(c.execute('select kind, count(*) from opps group by kind order by 2 desc').fetchall()),
            'by_language': dict(c.execute('select lang, count(*) from opps group by lang order by 2 desc').fetchall()),
            'last_fetched': max((x['last_fetched'] or '' for x in src), default=None) or None,
            'sources': src,
            'coverage_note': 'On 48 held-out test queries (v3, 2026-11-01) the corpus had a good posting for 15, all '
                             'remote: remote full-time 11/12, remote part-time or internship 4/6, every other kind of '
                             'query 0/30 (city-specific, outsourcing buyers, bounties, co-founders).',
            'fit_bands': {'strong': f'score >= {STRONG}: about half are good matches, 9 in 10 useful',
                          'possible': f'{POSSIBLE} <= score < {STRONG}: mostly loosely related, few good matches',
                          'weak': f'score < {POSSIBLE}: rarely useful'}}


@mcp.tool(annotations=READ)
def list_regions(place: str = '', include_archive: bool = False) -> dict:
    """How many live postings each place has. No place: by continent, then country (a remote posting open to several
    countries counts in each), plus postings open to anywhere and ones with no known place. With a place (city,
    province, country or region, any language): how many a search with where=place draws from, split into on-site /
    hybrid and remote, and the places one level below it."""
    try:
        return regions.counts(connect(), place, include_archive)
    except ValueError as e:
        raise ToolError(str(e)) from None


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                                      open_world_hint=False))
def rate_result(search_id: str, opp_id: int, grade: int, note: str = '') -> dict:
    """Grade one result of an earlier search for that search's need: 0 not useful, 1 related but misses a stated
    need, 2 good, 3 exactly what was asked. note: optional reason, one sentence. Stored as a label for the ranker."""
    if grade not in (0, 1, 2, 3):
        raise ToolError('grade must be 0, 1, 2 or 3')
    hit = None
    if SEARCH_LOG.exists():
        with SEARCH_LOG.open() as f:
            for line in f:
                x = json.loads(line)
                if x['search_id'] == search_id:
                    hit = x
    if hit is None:
        raise ToolError(f'unknown search_id {search_id}')
    rank = next((i for i, x in enumerate(hit['results'], 1) if x['opp_id'] == opp_id), None)
    if rank is None:
        raise ToolError(f'posting {opp_id} was not a result of search {search_id}')
    _append(FEEDBACK, {'ts': _now(), 'search_id': search_id, 'query': hit['query'], 'opp_id': opp_id, 'rank': rank,
                       'arm': hit['arm'], 'grade': grade, 'note': note[:500]})
    return {'stored': True, 'search_id': search_id, 'opp_id': opp_id, 'rank': rank, 'grade': grade}


if __name__ == '__main__':
    mcp.run()
