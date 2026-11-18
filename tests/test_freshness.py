from datetime import datetime, timedelta, timezone

from rankai import db, fresh, search as S

T0, T1, T2 = '2026-10-29T21:00:00Z', '2026-11-07T03:50:00Z', '2026-11-07T03:52:00Z'


def corpus(tmp_path, monkeypatch, fetches):
    c = db.connect(tmp_path / 'r.sqlite')
    rows = [(1, 'greenhouse', T1), (2, 'greenhouse', T0), (3, 'lever', T0), (4, 'himalayas', T0), (5, 'greenhouse', T2)]
    for i, src, seen in rows:
        c.execute('insert into opps(id, source, source_id, source_type, title, text, first_seen, last_seen) '
                  'values (?,?,?,?,?,?,?,?)', (i, src, str(i), 'ats', f'job {i}', 'x', T0, seen))
    c.executemany('insert into fetch_log values (?,?,?,?,?)', fetches)
    c.commit()
    monkeypatch.setattr(fresh.sources, 'all_fetchers', lambda: [
        ('greenhouse', 'acme', None), ('greenhouse', 'beta', None), ('lever', 'zed', None), ('himalayas', '', None)])
    return c


def test_missing_from_the_latest_listing_is_closed(tmp_path, monkeypatch):
    c = corpus(tmp_path, monkeypatch, [('greenhouse', T0, 9, 1, 'acme'), ('greenhouse', T0, 9, 1, 'beta'),
                                       ('greenhouse', T1, 9, 1, 'acme'), ('greenhouse', T2, 9, 1, 'beta'),
                                       ('lever', T0, 9, 1, 'zed'), ('himalayas', T1, 9, 1, '')])
    assert fresh.cutoffs(c) == {'greenhouse': T1, 'lever': T0}
    assert fresh.closed_ids(c) == {2}  # 3 is still on lever's only (old) listing; himalayas is a sample
    r = {x['id']: x for x in c.execute('select * from opps')}
    assert [fresh.listed(r[i], fresh.cutoffs(c)) for i in (1, 2, 4)] == [True, False, None]


def test_a_failed_board_keeps_its_postings(tmp_path, monkeypatch):
    c = corpus(tmp_path, monkeypatch, [('greenhouse', T0, 9, 1, 'acme'), ('greenhouse', T0, 9, 1, 'beta'),
                                       ('greenhouse', T1, 9, 1, 'acme'),
                                       ('greenhouse', T2, 0, 0, 'beta HTTPError: HTTP Error 503')])
    assert fresh.cutoffs(c) == {'greenhouse': T0}  # beta's last good listing is the old one
    assert fresh.closed_ids(c) == set()


def test_a_board_never_fetched_closes_nothing(tmp_path, monkeypatch):
    c = corpus(tmp_path, monkeypatch, [('greenhouse', T1, 9, 1, 'acme')])
    assert fresh.closed_ids(c) == set()


def test_live_search_drops_closed_postings_and_eval_runs_do_not(tmp_path, monkeypatch):
    c = corpus(tmp_path, monkeypatch, [('greenhouse', T1, 9, 1, 'acme'), ('greenhouse', T2, 9, 1, 'beta')])
    monkeypatch.setattr(S, 'first_stage',
                        lambda c, q, arm, max_id, fallback, allow=None: ([(2, 0.9), (1, 0.8), (4, 0.7)], {}))
    monkeypatch.setattr(S, '_rank', lambda c, q, arm, k, depth, ranked, qp, fallback: [{'id': i} for i, _ in ranked])
    monkeypatch.setattr(S, 'mismatches', lambda r, qp: [])
    assert [r['id'] for r in S.search('q', c=c)] == [1, 4]
    assert [r['id'] for r in S.search('q', max_id=10, c=c)] == [2, 1, 4]


def jobs(tmp_path, rows):
    c = db.connect(tmp_path / 'r.sqlite')
    for i, kind, posted in rows:
        c.execute('insert into opps(id, source, source_id, source_type, title, text, kind, posted_at) '
                  'values (?,?,?,?,?,?,?,?)', (i, 'himalayas', str(i), 'board', f'job {i}', 'x', kind, posted))
    c.commit()
    return c


def test_jobs_posted_over_30_days_ago_are_archived(tmp_path):
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)  # cutoff 2026-10-08T12:00:00Z
    c = jobs(tmp_path, [(1, 'fulltime', '2026-11-01T00:00:00Z'), (2, 'fulltime', '2026-09-30T00:00:00Z'),
                        (3, 'bounty', '2026-08-01T00:00:00Z'), (4, 'internship', '2026-10-08T11:59:59Z'),
                        (5, 'contract', None), (6, 'parttime', '2026-10-08T12:00:00Z')])
    assert fresh.archived_ids(c, now=now) == {2, 4}  # bounties are not archived by age; no date is not old
    cut = fresh.archive_cutoff(now=now)
    assert [fresh.archived(r, cut) for r in c.execute('select * from opps order by id')] == [
        False, True, False, True, False, False]


def test_live_search_leaves_out_the_archive_unless_asked(tmp_path, monkeypatch):
    ago = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)).strftime('%Y-%m-%dT%H:%M:%SZ')
    c = jobs(tmp_path, [(1, 'fulltime', ago(2)), (2, 'fulltime', ago(45)), (3, 'bounty', ago(45))])
    monkeypatch.setattr(S, 'first_stage',
                        lambda c, q, arm, max_id, fallback, allow=None: ([(2, 0.9), (1, 0.8), (3, 0.7)], {}))
    monkeypatch.setattr(S, '_rank', lambda c, q, arm, k, depth, ranked, qp, fallback: [{'id': i} for i, _ in ranked])
    monkeypatch.setattr(S, 'mismatches', lambda r, qp: [])
    assert [r['id'] for r in S.search('q', c=c)] == [1, 3]
    assert [r['id'] for r in S.search('q', c=c, archive=True)] == [2, 1, 3]
    assert [r['id'] for r in S.search('q', max_id=10, c=c)] == [2, 1, 3]  # eval snapshots are not filtered
