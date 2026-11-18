"""Score the saved runs against final labels: nDCG@10 and P@5 (rel >= 2), overall and per query language.

python eval/score.py v0     (labels: eval/labels_v0.jsonl, one {"qid","opp_id","rel"} per line)
RANKAI_LABEL_SET=prepay python eval/score.py v0     (labels: eval/labels_v0_prepay.jsonl, the labels before the
                                                    10-29 pay relabel, which the first reports used)

Means are over answerable queries: at least one pooled posting with rel >= 1 (fixed before the v1 labels existed).
A query with nothing relevant in the pool scores 0 for every arm, so it only dilutes differences;
'nDCG all' keeps those queries in for reference.
"""
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def label_file(name: str) -> Path:
    """eval/labels_<name>.jsonl, or eval/labels_<name>_<set>.jsonl when RANKAI_LABEL_SET is set (e.g. prepay)."""
    tag = os.environ.get('RANKAI_LABEL_SET')
    return ROOT / 'eval' / (f'labels_{name}_{tag}.jsonl' if tag else f'labels_{name}.jsonl')


def ndcg(rels: list[int], ideal: list[int], k: int = 10) -> float:
    dcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    idcg = sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(sorted(ideal, reverse=True)[:k]))
    return dcg / idcg if idcg else 0.0


def main(name: str):
    lab = {}
    for l in label_file(name).open():
        x = json.loads(l)
        lab[(x['qid'], x['opp_id'])] = x['rel']
    lang = {json.loads(l)['id']: json.loads(l)['lang'] for l in (ROOT / 'eval' / f'queries_{name}.jsonl').open()}
    ideal: dict[str, list[int]] = {}
    for (qid, _), r in lab.items():
        ideal.setdefault(qid, []).append(r)
    answerable = lambda q: max(ideal.get(q, [0])) >= 1  # noqa: E731
    table = []
    for arm in 'ABCDEFGHIJKLM':
        f = ROOT / 'eval' / 'runs' / f'{name}_{arm}.jsonl'
        if not f.exists():
            continue
        per: dict[str, list[tuple[float, float]]] = {}
        everything: list[float] = []
        missing = 0
        for l in f.open():
            run = json.loads(l)
            rels = []
            for i in run['ids']:
                r = lab.get((run['qid'], i))
                missing += r is None
                rels.append(r or 0)
            p5 = sum(r >= 2 for r in rels[:5]) / 5
            nd = ndcg(rels, ideal.get(run['qid'], []))
            everything.append(nd)
            if answerable(run['qid']):
                per.setdefault(lang[run['qid']], []).append((nd, p5))
        row = {'arm': arm, 'unlabeled': missing, 'nDCG all': sum(everything) / len(everything)}
        row['queries'] = sum(map(len, per.values()))
        allv = [v for vs in per.values() for v in vs]
        row['nDCG@10'] = sum(v[0] for v in allv) / len(allv)
        row['P@5'] = sum(v[1] for v in allv) / len(allv)
        for lg in ('zh', 'en', 'mix'):
            vs = per.get(lg, [])
            row[f'nDCG {lg}'] = sum(v[0] for v in vs) / len(vs) if vs else float('nan')
        table.append(row)
    cols = ['arm', 'nDCG@10', 'P@5', 'nDCG zh', 'nDCG en', 'nDCG mix', 'queries', 'nDCG all', 'unlabeled']
    print('| ' + ' | '.join(cols) + ' |\n|' + '---|' * len(cols))
    for r in table:
        print('| ' + ' | '.join(f'{r[c]:.3f}' if isinstance(r[c], float) else str(r[c]) for c in cols) + ' |')
    return table


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'v0')
