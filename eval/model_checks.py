"""Checks behind making L the default ranker. Pool reordering on the v3 labels, so no unlabeled items are involved.

python eval/model_checks.py -> eval/model_checks_v3.json (features cached in eval/features_v3.jsonl)
  saved:      the saved models with no AI posting judgment, fitted on 48, 96 and 144 queries, and rerank only
  curve:      L's recipe refitted on random subsets of its 144 training queries (more data, same mix of query sets)
  ageing:     L's order if every posting were 30 / 90 / 180 days older (only `fresh` moves): no fetch job is running
  importance: drop in pool nDCG@10 when one feature is shuffled across the pool
Exploratory: L's first-stage candidates and the pool are shared with F, J and M, and none of this was in eval/PLAN_v3.md.
"""
import json
import pickle
import random
import sys
from math import exp
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval import ltr  # noqa: E402
from eval.coverage import signflip  # noqa: E402
from eval.ltr_metrics import importance, pool_ndcg  # noqa: E402
from eval.score import ndcg  # noqa: E402
from rankai import search  # noqa: E402

TRAIN = 'v0 v1 v1b v2 v2o v1c v2c'.split()
SIZES = (24, 48, 72, 96, 120, 144)
ROUNDS = 20


def per_query(data: list[dict], pred) -> dict[str, float]:
    by: dict[str, list] = {}
    for x, s in zip(data, pred):
        by.setdefault(x['qid'], []).append((s, x['rel']))
    return {q: ndcg([r for _, r in sorted(xs, key=lambda t: -t[0])], [r for _, r in xs])
            for q, xs in by.items() if max(r for _, r in xs) >= 1}


def predict(m: dict, data: list[dict]):
    return m['model'].predict(np.array([[x[f] for f in m['feats']] for x in data], dtype=float))


def top10(data: list[dict], pred) -> dict[str, set]:
    by: dict[str, list] = {}
    for x, s in zip(data, pred):
        by.setdefault(x['qid'], []).append((s, x['opp_id']))
    return {q: {i for _, i in sorted(xs, key=lambda t: -t[0])[:10]} for q, xs in by.items()}


def fit_on(train: list[dict], fs: list[str]):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return {'feats': fs, 'model': HistGradientBoostingRegressor(**ltr.GBM).fit(ltr._mat(train, fs), ltr._gain(train))}


def main():
    test = ltr.features('v3')
    L = search.learned_model('L')
    base_pred = predict(L, test)
    base = per_query(test, base_pred)
    rerank = per_query(test, [x['rerank'] for x in test])
    rep = {'pairs': len(test), 'queries': len(base)}

    rep['saved'] = {'rerank only': sum(rerank.values()) / len(rerank)}
    for tag, f in (('48 queries', 'ltr_gbm_v0.pkl'), ('96 queries', 'ltr_gbm_v0+v1+v1b.pkl')):
        m = pickle.loads((ROOT / 'data' / f).read_bytes())['models']['I']
        got = per_query(test, predict(m, test))
        d = [base[q] - got[q] for q in base]
        rep['saved'][tag] = sum(got.values()) / len(got)
        rep['saved'][f'L minus {tag}'] = {'diff': sum(d) / len(d), 'p': signflip(d)}
    rep['saved']['144 queries (L)'] = sum(base.values()) / len(base)
    d = [base[q] - rerank[q] for q in base]
    rep['saved']['L minus rerank only'] = {'diff': sum(d) / len(d), 'p': signflip(d)}

    data = {}
    for n in TRAIN:
        data |= {(x['qid'], x['opp_id']): x for x in ltr.features(n)}
    train = list(data.values())
    assert np.allclose(predict(fit_on(train, L['feats']), test), base_pred), 'refit does not reproduce L'
    qids = sorted({x['qid'] for x in train})
    rng = random.Random(0)
    rep['curve'] = {}
    for n in SIZES:
        scores = []
        for _ in range(1 if n == len(qids) else ROUNDS):
            keep = set(rng.sample(qids, n))
            got = per_query(test, predict(fit_on([x for x in train if x['qid'] in keep], L['feats']), test))
            scores.append(sum(got.values()) / len(got))
        rep['curve'][n] = {'mean': float(np.mean(scores)), 'min': min(scores), 'max': max(scores)}

    j = L['feats'].index('fresh')
    X = np.array([[x[f] for f in L['feats']] for x in test], dtype=float)
    base_top = top10(test, base_pred)
    rep['ageing'] = {}
    for days in (30, 90, 180):
        A = X.copy()
        A[:, j] *= exp(-days / 45)
        pred = L['model'].predict(A)
        got, top = per_query(test, pred), top10(test, pred)
        d = [got[q] - base[q] for q in base]
        rep['ageing'][days] = {'nDCG@10': sum(got.values()) / len(got), 'p': signflip(d),
                               'top10_overlap': float(np.mean([len(top[q] & base_top[q]) / len(base_top[q]) for q in base]))}

    rep['importance'] = dict(sorted(importance(L, test)[1].items(), key=lambda kv: -kv[1]))
    (ROOT / 'eval' / 'model_checks_v3.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    print('pool nDCG@10 of L, as ltr_metrics computes it:', round(pool_ndcg(test, base_pred), 3))


if __name__ == '__main__':
    main()
