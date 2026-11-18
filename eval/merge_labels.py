"""Merge labeler outputs into final labels and report agreement.

python eval/merge_labels.py v0  -> eval/labels_v0.jsonl, eval/label_agreement_v0.json
python eval/merge_labels.py v1b --reuse v1   pool pairs without a new label take their final label from labels_v1

Final rel per item = mean of every labeler that answered (composer, grok, and gpt-review where the dual labeler ran
it; it skips GPT when >40% of a file disagrees), so grades like 2.5 occur; gain 2^rel-1 and the rel >= 2 cut-off work
on them. is_opportunity = majority (a tie counts as true). Items whose labelers spread by >= 2 are listed.
"""
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL_DIR = Path(os.environ.get('RANKAI_LABEL_DIR') or ROOT / 'data' / 'labeling')
LABELERS = ('composer', 'grok', 'gpt-review')


def _resp(x):
    r = x.get('response')
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except json.JSONDecodeError:
            return None
    return r if isinstance(r, dict) and r.get('rel') in (0, 1, 2, 3) else None


def load(name: str) -> dict[str, dict[str, dict]]:
    got: dict[str, dict[str, dict]] = {}
    for lab in LABELERS:
        for f in sorted((LABEL_DIR / 'outbox' / lab).glob(f'rankai_rel_{name}_[0-9]*.out.jsonl')):
            for l in f.open():
                x = json.loads(l)
                r = _resp(x)
                if r:
                    got.setdefault(x['id'], {})[lab] = r
    return got


def wkappa(a: list[int], b: list[int], k: int = 4) -> float:
    """Quadratic-weighted Cohen's kappa for 0..k-1 grades."""
    n = len(a)
    if not n:
        return float('nan')
    w = [[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]
    obs = sum(w[x][y] for x, y in zip(a, b)) / n
    pa = [a.count(i) / n for i in range(k)]
    pb = [b.count(i) / n for i in range(k)]
    exp = sum(w[i][j] * pa[i] * pb[j] for i in range(k) for j in range(k))
    return 1 - obs / exp if exp else float('nan')


def main(name: str, reuse: str | None = None):
    got = load(name)
    pool = [json.loads(l) for l in (ROOT / 'eval' / f'pool_{name}.jsonl').open()]
    old = {(x['qid'], x['opp_id']): x for x in map(json.loads, (ROOT / 'eval' / f'labels_{reuse}.jsonl').open())} \
        if reuse else {}
    out, spread, missing, reused = [], [], 0, 0
    for p in pool:
        key = f"{p['qid']}:{p['opp_id']}"
        labs = got.get(key, {})
        if not labs and (p['qid'], p['opp_id']) in old:
            out.append(old[(p['qid'], p['opp_id'])] | {'reused_from': reuse})
            reused += 1
            continue
        if not labs:
            missing += 1
            continue
        rels = [v['rel'] for v in labs.values()]
        opp = [bool(v.get('is_opportunity', True)) for v in labs.values()]
        rel = round(statistics.mean(rels), 3)
        is_opp = sum(opp) * 2 >= len(opp)
        out.append({'qid': p['qid'], 'opp_id': p['opp_id'], 'rel': rel, 'is_opportunity': is_opp,
                    'by': {k: v['rel'] for k, v in labs.items()}})
        if max(rels) - min(rels) >= 2:
            spread.append(key)
    with (ROOT / 'eval' / f'labels_{name}.jsonl').open('w') as f:
        for x in out:
            f.write(json.dumps(x) + '\n')
    both = [(v['composer']['rel'], v['grok']['rel']) for v in got.values() if 'composer' in v and 'grok' in v]
    a, b = [x for x, _ in both], [y for _, y in both]
    rep = {'items': len(pool), 'labeled': len(out), 'reused': reused, 'missing': missing,
           'composer_vs_grok': {'n': len(both), 'exact': round(sum(x == y for x, y in both) / max(len(both), 1), 3),
                                'within1': round(sum(abs(x - y) <= 1 for x, y in both) / max(len(both), 1), 3),
                                'weighted_kappa': round(wkappa(a, b), 3)},
           'gpt_reviewed': sum('gpt-review' in v for v in got.values()),
           'rel_distribution': {f'{lo}-{lo + 1}': sum(lo <= x['rel'] < lo + 1 or (lo == 3 and x['rel'] == 3) for x in out)
                                for lo in range(4)},
           'not_opportunity': sum(not x['is_opportunity'] for x in out),
           'spread_ge2': spread}
    (ROOT / 'eval' / f'label_agreement_{name}.json').write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != 'spread_ge2'} | {'spread_ge2': len(spread)}, indent=1))


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0] if a else 'v0', a[a.index('--reuse') + 1] if '--reuse' in a else None)
