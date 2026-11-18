"""Learn ranking weights from the labels (design doc §5: weights are learned, not hand-set).

python eval/ltr.py v0
  1. features for every labeled (query, posting) pair -> eval/features_v0.jsonl (cached; search.pair_features)
  2. leave-one-query-out: reorder each query's labeled pool by
       rerank only | hand-set G formula | linear (ridge) | gradient boosting (+ ablations)
     and report nDCG@10 / P@5 overall and per language -> eval/ltr_v0.json, eval/ltr_tests_v0.json
  3. fitted on all queries: ridge -> data/ltr_weights_v0.json (standardized coefficients);
     gradient boosting for search arms H (all features) and I (no AI judgment) -> data/ltr_gbm_v0.pkl
python eval/ltr.py v1 --train v0
  the same orderings fitted on v0 and applied to the v1 labeled pool (held-out queries)
  -> eval/ltr_v1_from_v0.json, eval/ltr_tests_v1_from_v0.json
python eval/ltr.py --fit v0 v1 v1b
  gradient boosting fitted on the labels of several evals together (a pair labeled under two names counts once)
  -> data/ltr_gbm_v0+v1+v1b.pkl, used by search arm K
Pool reordering compares orderings on the same judged candidates, so no unlabeled items are involved.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.score import ndcg  # noqa: E402
from rankai import search  # noqa: E402
from rankai.db import connect  # noqa: E402

FEATS, AI_JUDGE, AI_REWRITE = search.FEATS, search.AI_JUDGE_FEATS, search.AI_REWRITE_FEATS
GBM = dict(max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=20, random_state=0)


def queries(name: str) -> dict[str, dict]:
    return {q['id']: q for q in map(json.loads, (ROOT / 'eval' / f'queries_{name}.jsonl').open())}


def features(name: str) -> list[dict]:
    cache = ROOT / 'eval' / f'features_{name}.jsonl'
    labels = {(x['qid'], x['opp_id']): x['rel'] for x in map(json.loads, (ROOT / 'eval' / f'labels_{name}.jsonl').open())}
    done = {}
    if cache.exists():
        for x in map(json.loads, cache.open()):
            done[(x['qid'], x['opp_id'])] = x
    qs = queries(name)
    c = connect()
    by_q: dict[str, list[int]] = {}
    present = {r[0] for r in c.execute('select id from opps')}  # a few HN seeker posts were deleted for privacy
    for qid, oid in labels:
        if (qid, oid) not in done and oid in present:
            by_q.setdefault(qid, []).append(oid)
    ids_all = [oid for v in by_q.values() for oid in v]
    rows = {r['id']: r for r in c.execute(f"select * from opps where id in ({','.join('?' * len(ids_all))})", ids_all)} if ids_all else {}
    with cache.open('a') as f:
        for qid, oids in by_q.items():
            for o, x in zip(oids, search.pair_features(c, qs[qid]['query'], [rows[o] for o in oids])):
                x = {'qid': qid, 'opp_id': o} | x
                done[(qid, o)] = x
                f.write(json.dumps(x) + '\n')
    out = []
    for key, rel in labels.items():
        if key in done:
            out.append(done[key] | {'rel': rel})
    return out


def hand_g(x) -> float:
    W = search.W
    return (x['rerank'] - W['viol'] * x['viol'] + W['fresh'] * x['fresh'] + W['trust'] * x['trust']
            + W['complete'] * x['complete'] - W['scam'] * x['scam_rule'] - W['notopp'] * x['ai_notopp']
            - W['ai_scam'] * x['ai_scam'] + W['clarity'] * x['ai_clarity'])


def evaluate(groups: dict[str, list[dict]], score_of: dict[str, dict]) -> dict:
    """score_of[qid][opp_id] -> score; returns mean nDCG@10 and P@5 over queries with at least one rel >= 1."""
    nd, p5, per = [], [], {}
    for qid, xs in groups.items():
        rels = [x['rel'] for x in xs]
        if max(rels) == 0:
            continue
        order = sorted(xs, key=lambda x: -score_of[qid][x['opp_id']])
        r = [x['rel'] for x in order]
        nd.append(ndcg(r, rels))
        p5.append(sum(v >= 2 for v in r[:5]) / 5)
        per[qid] = nd[-1]
    return {'nDCG@10': float(np.mean(nd)), 'P@5': float(np.mean(p5)), 'queries': len(nd), 'per_query': per}


VARIANTS = {'gbm': set(FEATS), 'gbm -ai_judge': set(FEATS) - AI_JUDGE, 'gbm -ai_rewrite': set(FEATS) - AI_REWRITE,
            'gbm -both': set(FEATS) - AI_JUDGE - AI_REWRITE}


def paired_p(a: dict, b: dict, rounds: int = 20000) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    d = np.array([b[q] - a[q] for q in a])
    signs = rng.choice((-1, 1), size=(rounds, len(d)))
    return float(d.mean()), float(((np.abs((signs * d).mean(1)) >= abs(d.mean()) - 1e-12).sum() + 1) / (rounds + 1))


def _groups(data: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for x in data:
        g.setdefault(x['qid'], []).append(x)
    return g


def _gain(xs):
    return np.array([2 ** x['rel'] - 1 for x in xs], dtype=float)


def _mat(xs, fs=FEATS):
    return np.array([[x[f] for f in fs] for x in xs], dtype=float)


def fit(tr: list[dict]) -> dict:
    """Every learned ordering, fitted on training pairs; returns name -> function(test pairs) -> scores."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    sc = StandardScaler().fit(_mat(tr))
    ridge = Ridge(alpha=10.0).fit(sc.transform(_mat(tr)), _gain(tr))
    out = {'rerank': lambda te: [x['rerank'] for x in te], 'hand_G': lambda te: [hand_g(x) for x in te],
           'ridge': lambda te: ridge.predict(sc.transform(_mat(te)))}
    for k, keep in VARIANTS.items():
        fs = [f for f in FEATS if f in keep]
        gbm = HistGradientBoostingRegressor(**GBM).fit(_mat(tr, fs), _gain(tr))
        out[k] = lambda te, gbm=gbm, fs=fs: gbm.predict(_mat(te, fs))
    return out


def report(name: str, tag: str, groups: dict, scores: dict, lang: dict):
    rep = {}
    for k, s in scores.items():
        rep[k] = {'all': evaluate(groups, s)}
        for lg in ('zh', 'en', 'mix'):
            rep[k][lg] = evaluate({q: v for q, v in groups.items() if lang[q] == lg}, s)
    (ROOT / 'eval' / f'ltr_{tag}.json').write_text(json.dumps(rep, indent=1))
    print('| ordering | nDCG@10 | P@5 | nDCG zh | nDCG en | nDCG mix |\n|---|---|---|---|---|---|')
    for k, v in rep.items():
        print(f"| {k} | {v['all']['nDCG@10']:.3f} | {v['all']['P@5']:.3f} | {v['zh']['nDCG@10']:.3f} | "
              f"{v['en']['nDCG@10']:.3f} | {v['mix']['nDCG@10']:.3f} |")
    print('\n| comparison | mean diff | p |\n|---|---|---|')
    tests = {}
    for a, b in (('rerank', 'gbm'), ('hand_G', 'gbm'), ('gbm -ai_judge', 'gbm'), ('gbm -ai_rewrite', 'gbm'),
                 ('gbm -both', 'gbm')):
        d, pv = paired_p(rep[a]['all']['per_query'], rep[b]['all']['per_query'])
        tests[f'{b} vs {a}'] = {'mean_diff': d, 'p': pv}
        print(f'| {b} vs {a} | {d:+.3f} | {pv:.4f} |')
    (ROOT / 'eval' / f'ltr_tests_{tag}.json').write_text(json.dumps(tests, indent=1))


def main(name: str):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    data = features(name)
    lang = {q: v['lang'] for q, v in queries(name).items()}
    groups = _groups(data)
    qids = sorted(groups)
    scores = {k: {} for k in ('rerank', 'hand_G', 'ridge', *VARIANTS)}
    for held in qids:  # leave one query out
        fns = fit([x for q in qids if q != held for x in groups[q]])
        te = groups[held]
        for k, fn in fns.items():
            scores[k][held] = dict(zip([x['opp_id'] for x in te], fn(te)))
    report(name, name, groups, scores, lang)
    sc = StandardScaler().fit(_mat(data))
    ridge = Ridge(alpha=10.0).fit(sc.transform(_mat(data)), _gain(data))
    weights = dict(zip(FEATS, map(float, ridge.coef_)))
    (ROOT / 'data' / f'ltr_weights_{name}.json').write_text(json.dumps(
        {'features': FEATS, 'coef_standardized': weights, 'mean': sc.mean_.tolist(), 'scale': sc.scale_.tolist(),
         'intercept': float(ridge.intercept_), 'target': 'gain = 2^rel - 1', 'alpha': 10.0}, indent=1))
    save_gbm(data, name)
    print('ridge standardized coefficients:', {k: round(v, 3) for k, v in sorted(weights.items(), key=lambda t: -abs(t[1]))})


def save_gbm(data: list[dict], tag: str):
    """Fit the H (all features) and I (no AI judgment) models on every pair in `data` -> data/ltr_gbm_<tag>.pkl."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    models = {}
    for arm, keep in (('H', set(FEATS)), ('I', set(FEATS) - AI_JUDGE)):
        fs = [f for f in FEATS if f in keep]
        models[arm] = {'feats': fs, 'model': HistGradientBoostingRegressor(**GBM).fit(_mat(data, fs), _gain(data))}
    (ROOT / 'data' / f'ltr_gbm_{tag}.pkl').write_bytes(pickle.dumps(
        {'trained_on': tag, 'pairs': len(data), 'queries': len({x['qid'] for x in data}), 'params': GBM,
         'target': 'gain = 2^rel - 1', 'models': models}))
    print(f'data/ltr_gbm_{tag}.pkl: {len(data)} pairs, {len({x["qid"] for x in data})} queries')


def fit_many(names: list[str]):
    data = {}
    for n in names:  # v1b repeats v1's queries; a pair labeled under both keeps the later label
        data |= {(x['qid'], x['opp_id']): x for x in features(n)}
    save_gbm(list(data.values()), '+'.join(names))


def transfer(name: str, train: str):
    """Fit on all of `train`, reorder the labeled pool of `name` (held-out queries)."""
    data = features(name)
    groups = _groups(data)
    fns = fit(features(train))
    scores = {k: {q: dict(zip([x['opp_id'] for x in te], fn(te))) for q, te in groups.items()} for k, fn in fns.items()}
    report(name, f'{name}_from_{train}', groups, scores, {q: v['lang'] for q, v in queries(name).items()})


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit_many(sys.argv[sys.argv.index('--fit') + 1:])
    elif '--train' in sys.argv:
        transfer(sys.argv[1], sys.argv[sys.argv.index('--train') + 1])
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else 'v0')
