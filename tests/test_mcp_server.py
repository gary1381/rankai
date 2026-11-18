import asyncio

import pytest

from rankai import db, mcp_server as M


@pytest.fixture
def server(tmp_path, monkeypatch):
    path = tmp_path / 'r.sqlite'
    c = db.connect(path)
    for i, (src, cl) in enumerate([('greenhouse', 1), ('lever', 1), ('v2ex', 3)], 1):
        c.execute('insert into opps(id, source, source_id, source_type, url, apply_url, title, org, kind, location, '
                  'remote, salary_min, salary_max, currency, period, posted_at, tags, text, lang, cluster_id) '
                  'values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (i, src, str(i), 'ats', f'https://x/{i}', None, f'RAG engineer {i}', 'Acme', 'fulltime', 'Remote',
                   1.0, 100000, 150000, 'USD', 'year', '2026-10-20T00:00:00Z', 'python',
                   '<p>Build RAG. Contact jane@acme.io or 微信: abc12345</p>', 'en', cl))
    c.commit()
    monkeypatch.setattr(M, 'connect', lambda: db.connect(path))
    monkeypatch.setattr(M, 'SEARCH_LOG', tmp_path / 'searches.jsonl')
    monkeypatch.setattr(M, 'FEEDBACK', tmp_path / 'feedback.jsonl')

    def fake_search(q, arm, k, fallback, archive=False, where=None, field=None):
        rows = [dict(r) for r in db.connect(path).execute('select * from opps order by id')]
        feats = {'rerank': 0.9, 'rerank_en': 0.8}
        return [r | {'score': s, 'feats': feats, 'mismatch': []} for r, s in zip(rows, (2.4, 1.3, 0.2))][:k]
    monkeypatch.setattr(M.S, 'search', fake_search)
    return path


def test_search_gives_fit_verdict_and_redacts(server):
    out = M.search_opportunities('remote RAG', 3)
    assert out['ranking'] == 'L' and out['verdict'] == 'good match likely'
    assert [r['fit'] for r in out['results']] == ['strong', 'weak']  # posting 2 is the same job as 1 (cluster 1)
    assert out['results'][0]['duplicates_hidden'] == 1
    text = out['results'][0]['text']
    assert 'jane@acme.io' not in text and 'abc12345' not in text and '<p>' not in text
    assert out['results'][0]['pay'] == '100,000-150,000 USD/year'
    assert out['results'][0]['work_mode'] == 'remote'
    assert out['results'][0]['still_listed'] is None  # the fixture has no board listing in fetch_log


def test_fallback_ranking_has_no_fit(server, monkeypatch):
    row = dict(db.connect(server).execute('select * from opps where id=1').fetchone())
    monkeypatch.setattr(M.S, 'search', lambda q, arm, k, fallback, archive=False, where=None, field=None: [
        row | {'score': 0.7, 'feats': {'rerank': 0.7}, 'mismatch': [], 'fallback': 'KeyError: 27096'}])
    out = M.search_opportunities('anything', 5)
    assert out['ranking'] == 'J' and out['results'][0]['fit'] is None and out['verdict'].startswith('unknown')
    assert out['why_not_L'] == 'KeyError: 27096'


def test_archive_is_left_out_unless_asked(server, monkeypatch):
    asked = []
    row = dict(db.connect(server).execute('select * from opps where id=1').fetchone())  # posted 2026-10-20
    monkeypatch.setattr(M.S, 'search', lambda q, arm, k, fallback, archive=False, where=None, field=None: asked.append(archive) or [
        row | {'score': 2.4, 'feats': {'rerank': 0.9}, 'mismatch': []}])
    monkeypatch.setattr(M.fresh, 'archive_cutoff', lambda days=30, now=None: '2026-11-01T00:00:00Z')
    assert M.search_opportunities('remote RAG', 3)['results'][0]['archived'] is True
    M.search_opportunities('remote RAG', 3, include_archive=True)
    assert asked == [False, True]
    assert M.corpus_info()['archived'] == 3


def test_rating_needs_a_logged_result(server):
    sid = M.search_opportunities('remote RAG', 2)['search_id']
    assert M.rate_result(sid, 3, 3, 'exact')['rank'] == 2
    assert M.FEEDBACK.read_text().count('\n') == 1
    with pytest.raises(M.ToolError):
        M.rate_result(sid, 2, 2)          # hidden as a duplicate of posting 1
    with pytest.raises(M.ToolError):
        M.rate_result('nope', 1, 2)
    with pytest.raises(M.ToolError):
        M.rate_result(sid, 1, 5)


def test_get_opportunity_lists_the_same_job_elsewhere(server):
    o = M.get_opportunity(1)
    assert [x['source'] for x in o['also_listed']] == ['lever']
    assert M.get_opportunity(3)['also_listed'] == []
    with pytest.raises(M.ToolError):
        M.get_opportunity(99)


def test_tools_are_registered_with_read_only_hints():
    tools = {t.name: t for t in asyncio.run(M.mcp.list_tools())}
    assert set(tools) == {'search_opportunities', 'get_opportunity', 'corpus_info', 'list_regions', 'rate_result'}
    assert all(tools[n].annotations.read_only_hint
               for n in ('search_opportunities', 'get_opportunity', 'corpus_info', 'list_regions'))
    assert tools['rate_result'].annotations.read_only_hint is False


def test_corpus_info_counts(server):
    info = M.corpus_info()
    assert info['postings'] == 3 and info['by_kind'] == {'fulltime': 3}


def test_where_reaches_search_and_an_unknown_place_is_a_tool_error(server, monkeypatch):
    asked = []
    row = dict(db.connect(server).execute('select * from opps where id=1').fetchone())

    def fake(q, arm, k, fallback, archive=False, where=None, field=None):
        asked.append(where)
        if where == '火星':
            raise ValueError("no known place in '火星'")
        return [row | {'score': 2.4, 'feats': {'rerank': 0.9}, 'mismatch': [], 'places': ['Germany/Berlin']}]
    monkeypatch.setattr(M.S, 'search', fake)
    assert M.search_opportunities('backend', 3, where='Berlin')['results'][0]['places'] == ['Berlin, Germany']
    M.search_opportunities('backend', 3)
    with pytest.raises(M.ToolError):
        M.search_opportunities('backend', 3, where='火星')
    assert asked == ['Berlin', None, '火星']
