import pytest

from rankai import search


class Conn:
    def execute(self, sql, ids):
        return [dict(id=i, title=f't{i}', org='', location='', kind='fulltime', salary_min=None, tags='', text='',
                     remote=1.0, salary_usd_year=None) for i in ids]


QP = dict(remote=False, kinds=set(), min_usd_year=None)
RANKED = [(1, 2.0), (2, 1.0)]


def broken(*_):
    raise RuntimeError('no rewrite')


def test_default_arm_falls_back_to_the_reranker_score(monkeypatch):
    monkeypatch.setattr(search, 'pair_features', broken)
    monkeypatch.setattr(search.models, 'rerank', lambda q, docs: [0.1, 0.9])
    assert [r['id'] for r in search._rank(Conn(), 'q', 'L', 10, 50, RANKED, QP, fallback=True)] == [2, 1]


@pytest.mark.skipif(not search.LTR_MODELS['L'][0].exists(),
                    reason="L's model file is not distributed; build it with eval/ltr.py --fit (docs/DATA.md)")
def test_learned_arm_raises_when_evaluating(monkeypatch):
    monkeypatch.setattr(search, 'pair_features', broken)
    with pytest.raises(RuntimeError):
        search._rank(Conn(), 'q', 'L', 10, 50, RANKED, QP)
