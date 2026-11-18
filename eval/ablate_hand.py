"""Which hand-set term in arm F's score helps or hurts? Exploratory: run after the v2 results, on labels that exist.

python eval/ablate_hand.py v0 v1 v1b v2
  F's score = rerank - W.viol * (remote + kind + pay violations) + W.fresh * fresh + W.trust * trust
              + W.complete * complete - W.scam * scam
  Each labeled pool is reordered by: rerank only (= arm J), F in full, F without one term, rerank plus one term.
  nDCG@10 over answerable queries (a pooled posting with mean rel >= 1), per eval and pooled over v1 + v2 (different queries, both held out);
  paired sign-flip p against rerank only and against F. -> eval/ablate_hand.json
Features come from eval/features_<name>.jsonl (eval/ltr.py computes missing ones); the three violation parts are
recomputed here with the same constraints F uses (rules + cached AI rewrite).
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.ltr import evaluate, features, paired_p, queries  # noqa: E402
from rankai import qrewrite, search  # noqa: E402
from rankai.db import connect  # noqa: E402
from rankai.text import usd_year  # noqa: E402

W = search.W
TERMS = ['viol_remote', 'viol_kind', 'viol_pay', 'fresh', 'trust', 'complete', 'scam']
SIGN = {'viol_remote': -W['viol'], 'viol_kind': -W['viol'], 'viol_pay': -W['viol'], 'fresh': W['fresh'],
        'trust': W['trust'], 'complete': W['complete'], 'scam': -W['scam']}
LABEL = {'viol_remote': 'remote violation', 'viol_kind': 'engagement-type violation', 'viol_pay': 'pay violation',
         'fresh': 'freshness', 'trust': 'source trust', 'complete': 'completeness', 'scam': 'scam rule'}


def parts(o, qp) -> dict:
    """search.violations split into its three parts."""
    r = 1 - o['remote'] if qp['remote'] and o['remote'] is not None else 0.0
    k = 1.0 if qp['kinds'] and o['kind'] not in qp['kinds'] else 0.0
    p = 0.0
    if qp['min_usd_year'] and o['salary_usd_year']:
        top = usd_year(o['salary_max'], o['currency'], o['period'])
        p = 1.0 if top and top < qp['min_usd_year'] * 0.9 else 0.0
    return {'viol_remote': r, 'viol_kind': k, 'viol_pay': p}


def load(name: str) -> list[dict]:
    data = features(name)
    qs = queries(name)
    c = connect()
    rows = {r['id']: r for r in c.execute(
        f"select * from opps where id in ({','.join('?' * len(data))})", [x['opp_id'] for x in data])}
    qp = {q: search.ai_constraints(v['query'], qrewrite.rewrite(v['query'])) for q, v in qs.items()}
    # the cached features (and the evaluated runs) predate the 10-29 part-time fix: use the kinds they saw
    fix = ROOT / 'data' / 'maintenance_parttime_20261029.json'
    was_contract = set(json.loads(fix.read_text())['ids']) if fix.exists() else set()
    out = []
    for x in data:
        o = rows[x['opp_id']]
        p = parts(dict(o) | {'kind': 'contract'} if o['id'] in was_contract else o, qp[x['qid']])
        assert abs(sum(p.values()) - x['viol']) < 1e-6, (name, x['qid'], x['opp_id'])
        out.append(x | p | {'scam': x['scam_rule']})
    return out


def score(x, drop=(), only=None) -> float:
    terms = [only] if only else [t for t in TERMS if t not in drop]
    return x['rerank'] + sum(SIGN[t] * x[t] for t in terms)


ORDERINGS = {'rerank only (J)': lambda x: x['rerank'], 'F (all terms)': score,
             'F without violations': lambda x: score(x, drop=('viol_remote', 'viol_kind', 'viol_pay')),
             'F without priors': lambda x: score(x, drop=('fresh', 'trust', 'complete', 'scam'))}
ORDERINGS |= {f'F without {LABEL[t]}': (lambda x, t=t: score(x, drop=(t,))) for t in TERMS}
ORDERINGS |= {f'rerank + {LABEL[t]} only': (lambda x, t=t: score(x, only=t)) for t in TERMS}
# scale-aware variant, added after seeing the results above (so exploratory): the penalty shrinks the reranker
# score instead of subtracting a fixed 0.5, which outweighs every reranker score below 0.5
ORDERINGS['rerank x (1 - 0.5 x violations)'] = lambda x: x['rerank'] * max(0.0, 1 - W['viol'] * (
    x['viol_remote'] + x['viol_kind'] + x['viol_pay']))


def main(names: list[str]):
    rep, per = {}, {}
    for name in names:
        data = load(name)
        groups: dict[str, list[dict]] = {}
        for x in data:
            groups.setdefault(x['qid'], []).append(x)
        # answerable = a pooled posting with mean rel >= 1, the rule in the eval plans and score.py
        # (ltr.evaluate alone keeps any query with a rel > 0)
        groups = {q: xs for q, xs in groups.items() if max(x['rel'] for x in xs) >= 1}
        lang = {q: v['lang'] for q, v in queries(name).items()}
        active = {t: sum(x[t] > 0 for x in data) for t in TERMS}
        rep[name] = {'pairs': len(data), 'active': active, 'orderings': {}}
        for k, fn in ORDERINGS.items():
            s = {q: {x['opp_id']: fn(x) for x in xs} for q, xs in groups.items()}
            ev = evaluate(groups, s)
            per[(name, k)] = {f'{name}:{q}': v for q, v in ev['per_query'].items()}
            rep[name]['orderings'][k] = {'nDCG@10': ev['nDCG@10'], 'queries': ev['queries']} | {
                lg: evaluate({q: v for q, v in groups.items() if lang[q] == lg}, s)['nDCG@10'] for lg in ('zh', 'en', 'mix')}
    pooled = [n for n in ('v1', 'v2') if n in names]
    if len(pooled) == 2:
        rep['v1+v2'] = {'orderings': {}}
        for k in ORDERINGS:
            per[('v1+v2', k)] = per[('v1', k)] | per[('v2', k)]
            rep['v1+v2']['orderings'][k] = {'nDCG@10': float(np.mean(list(per[('v1+v2', k)].values()))),
                                            'queries': len(per[('v1+v2', k)])}
    for name in rep:
        for k, v in rep[name]['orderings'].items():
            for base in ('rerank only (J)', 'F (all terms)'):
                if k != base:
                    d, p = paired_p(per[(name, base)], per[(name, k)])
                    v[f'vs {base}'] = {'diff': d, 'p': p}
    (ROOT / 'eval' / 'ablate_hand.json').write_text(json.dumps(rep, indent=1))
    cols = list(rep)
    print('| ordering | ' + ' | '.join(cols) + ' |\n|---|' + '---|' * len(cols))
    for k in ORDERINGS:
        cells = []
        for n in cols:
            v = rep[n]['orderings'][k]
            ref = v.get('vs F (all terms)')
            cells.append(f"{v['nDCG@10']:.3f}" + (f" ({ref['diff']:+.3f}, p={ref['p']:.3f})" if ref else ''))
        print(f'| {k} | ' + ' | '.join(cells) + ' |')
    for n in names:
        print(n, 'pairs where a term is non-zero:', rep[n]['active'])


if __name__ == '__main__':
    main(sys.argv[1:] or ['v0', 'v1', 'v1b', 'v2'])
