import numpy as np

from rankai import db, search as S, sources


def test_any_work_mode_is_not_a_remote_requirement():
    for q in ['data scientist job in the United States, hybrid, remote or on-site all fine, full-time',
              'remote, hybrid or on-site ML engineer', '远程或线下都可以的前端开发']:
        qp = S.parse_query(q)
        assert (qp['remote'], qp['onsite'], qp['any_mode']) == (False, False, True), q
        assert S.ai_constraints(q, {'remote': True, 'kinds': [], 'location': None})['remote'] is False
    assert S.parse_query('远程 RAG 工程师')['remote'] and S.parse_query('杭州 线下 前端开发 全职')['onsite']


def test_ashby_workplace_type_wins_over_is_remote(monkeypatch):
    jobs = [{'id': 1, 'title': 'Research Engineer', 'isRemote': True, 'workplaceType': 'Hybrid'},
            {'id': 2, 'title': 'Engineer', 'isRemote': True, 'workplaceType': 'Remote'},
            {'id': 3, 'title': 'Engineer', 'isRemote': False, 'workplaceType': 'OnSite'},
            {'id': 4, 'title': 'Engineer', 'isRemote': True}]
    monkeypatch.setattr(sources, 'get', lambda url, timeout=40: {'jobs': jobs})
    assert [o['remote'] for _, _, o in sources.ashby('acme')] == [0.5, 1.0, 0.0, 1.0]


def test_a_posting_without_a_vector_is_embedded_on_the_fly(tmp_path, monkeypatch):
    c = db.connect(tmp_path / 'r.sqlite')
    for i in (1, 2):
        c.execute('insert into opps(id, source, source_id, source_type, title, kind, text, lang) values (?,?,?,?,?,?,?,?)',
                  (i, 'greenhouse', str(i), 'ats', f'job {i}', 'fulltime', 'x', 'en'))
    c.execute('insert into vecs values (1, ?, ?, ?)', ('e5', 'h', np.ones(4, dtype=np.float32).tobytes()))
    c.commit()
    S._VEC_CACHE.clear()
    monkeypatch.setattr(S.qrewrite, 'rewrite', lambda q: {'en_query': q, 'remote': None, 'kinds': [], 'location': None})
    monkeypatch.setattr(S.models, 'rerank', lambda q, docs: [0.5] * len(docs))
    monkeypatch.setattr(S.models, 'embed', lambda texts, kind='passage': np.full((len(texts), 4), 0.5, dtype=np.float32))
    rows = c.execute('select * from opps order by id').fetchall()
    f = S.pair_features(c, 'q', rows)  # posting 2 has no stored vector (fetched after the last `rankai vectors`)
    assert [x['dense'] for x in f] == [2.0, 1.0]
    S._VEC_CACHE.clear()
