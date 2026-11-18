"""Metrics for the learned ranking models (H, I, K): end-to-end ranking metrics on v1/v1b/v2, pointwise fit
of the predicted gain, and permutation importance on pool nDCG@10. python eval/ltr_metrics.py -> eval/ltr_metrics.json"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.score import ndcg  # noqa: E402

E = ROOT / 'eval'


def labels(name, prepay=False):
    f = E / f'labels_{name}{"_prepay" if prepay else ""}.jsonl'
    return {(x['qid'], x['opp_id']): x['rel'] for x in map(json.loads, f.open())}


def lang(name):
    return {x['id']: x['lang'] for x in map(json.loads, (E / f'queries_{name}.jsonl').open())}


def query_rows(name, arm):
    """One row of metrics per answerable query, and how many top-10 results had no label."""
    lab, lg = labels(name), lang(name)
    ideal = {}
    for (q, _), r in lab.items():
        ideal.setdefault(q, []).append(r)
    rows, miss = [], 0
    for run in map(json.loads, (E / 'runs' / f'{name}_{arm}.jsonl').open()):
        q = run['qid']
        if max(ideal.get(q, [0])) < 1:
            continue
        rels = []
        for i in run['ids'][:10]:
            r = lab.get((q, i))
            miss += r is None
            rels.append(r or 0)
        first = next((k + 1 for k, r in enumerate(rels) if r >= 2), None)
        rows.append(dict(qid=q, lang=lg[q], best=max(ideal[q]), nd=ndcg(rels, ideal[q]),
                         p5=sum(r >= 2 for r in rels[:5]) / 5, p10=sum(r >= 2 for r in rels) / 10,
                         rr=1 / first if first else 0.0, cov=float(first is not None),
                         ok1=sum(r >= 1 for r in rels) / 10))
    return rows, miss


def end_to_end(name, arms):
    out = {}
    for arm in arms:
        if not (E / 'runs' / f'{name}_{arm}.jsonl').exists():
            continue
        rows, miss = query_rows(name, arm)
        m = lambda k, rs=rows: float(np.mean([r[k] for r in rs]))  # noqa: E731
        res = {k: m(k) for k in ('nd', 'p5', 'p10', 'rr', 'cov', 'ok1')}
        res['covered'] = int(sum(r['cov'] for r in rows))
        res['n'] = len(rows)
        res['unlabeled'] = miss
        for l in ('zh', 'en', 'mix'):
            rs = [r for r in rows if r['lang'] == l]
            res[f'nd_{l}'] = m('nd', rs) if rs else float('nan')
        out[arm] = res
    return out


def feats(name):
    return {(x['qid'], x['opp_id']): x for x in map(json.loads, (E / f'features_{name}.jsonl').open())}


def pairs(names, prepay):
    d = {}
    for n in names:
        lab, fs = labels(n, prepay), feats(n)
        d |= {k: fs[k] | {'rel': r} for k, r in lab.items() if k in fs}
    return list(d.values())


def fit_stats(m, data):
    X = np.array([[x[f] for f in m['feats']] for x in data], dtype=float)
    y = np.array([2 ** x['rel'] - 1 for x in data], dtype=float)
    p = m['model'].predict(X)
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    r2 = float(1 - np.sum((p - y) ** 2) / np.sum((y - y.mean()) ** 2))
    from scipy.stats import spearmanr
    rho = float(spearmanr(p, y).correlation)
    return dict(pairs=len(data), rmse=rmse, r2=r2, spearman=rho, pool_ndcg=pool_ndcg(data, p))


def pool_ndcg(data, pred):
    g = {}
    for x, s in zip(data, pred):
        g.setdefault(x['qid'], []).append((s, x['rel']))
    nds = []
    for xs in g.values():
        rels = [r for _, r in xs]
        if max(rels) < 1:
            continue
        nds.append(ndcg([r for _, r in sorted(xs, key=lambda t: -t[0])], rels))
    return float(np.mean(nds))


def importance(m, data, rounds=5):
    rng = np.random.default_rng(0)
    X = np.array([[x[f] for f in m['feats']] for x in data], dtype=float)
    base = pool_ndcg(data, m['model'].predict(X))
    out = {}
    for j, f in enumerate(m['feats']):
        drops = []
        for _ in range(rounds):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - pool_ndcg(data, m['model'].predict(Xp)))
        out[f] = float(np.mean(drops))
    return base, out


if __name__ == '__main__':
    res = {'end_to_end': {n: end_to_end(n, 'FGHIJK') for n in ('v1', 'v1b', 'v2')}}
    H = pickle.loads((ROOT / 'data' / 'ltr_gbm_v0.pkl').read_bytes())
    K = pickle.loads((ROOT / 'data' / 'ltr_gbm_v0+v1+v1b.pkl').read_bytes())
    res['models'] = {t: {k: v for k, v in d.items() if k != 'models'} | {
        'trees': {a: int(m['model'].n_iter_) for a, m in d['models'].items()},
        'n_feats': {a: len(m['feats']) for a, m in d['models'].items()}} for t, d in (('H', H), ('K', K))}
    fit = {}
    fit['H train v0 (in-sample)'] = fit_stats(H['models']['H'], pairs(['v0'], True))
    fit['I train v0 (in-sample)'] = fit_stats(H['models']['I'], pairs(['v0'], True))
    for n in ('v1', 'v1b', 'v2'):
        fit[f'H on {n} (held-out)'] = fit_stats(H['models']['H'], pairs([n], False))
        fit[f'I on {n} (held-out)'] = fit_stats(H['models']['I'], pairs([n], False))
    fit['K train v0+v1+v1b (in-sample)'] = fit_stats(K['models']['H'], pairs(['v0', 'v1', 'v1b'], True))
    fit['K on v2 (held-out)'] = fit_stats(K['models']['H'], pairs(['v2'], False))
    res['fit'] = fit
    imp = {}
    for tag, m, data in (('H on v0 (in-sample)', H['models']['H'], pairs(['v0'], True)),
                         ('H on v1+v2 (held-out)', H['models']['H'], pairs(['v1', 'v2'], False)),
                         ('K on v2 (held-out)', K['models']['H'], pairs(['v2'], False))):
        base, d = importance(m, data)
        imp[tag] = {'base_pool_ndcg': base, 'drop': d}
    res['importance'] = imp
    (E / 'ltr_metrics.json').write_text(json.dumps(res, indent=1))
    print('ok')
