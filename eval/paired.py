"""Paired randomization test on per-query nDCG@10 between arms (sign-flip, 20k rounds), plus wins/ties/losses.
Answerable queries only (a pooled posting with rel >= 1), as in score.py.

python eval/paired.py v0 A:C D:E E:F F:G     -> eval/paired_v0.json (eval/paired_v0_<set>.json with RANKAI_LABEL_SET)
"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.score import label_file, ndcg  # noqa: E402


def per_query(name: str, arm: str, lab: dict, ideal: dict) -> dict[str, float]:
    out = {}
    for l in (ROOT / 'eval' / 'runs' / f'{name}_{arm}.jsonl').open():
        r = json.loads(l)
        out[r['qid']] = ndcg([lab.get((r['qid'], i), 0) for i in r['ids']], ideal.get(r['qid'], []))
    return out


def main(name: str, pairs: list[str]):
    lab = {(x['qid'], x['opp_id']): x['rel'] for x in map(json.loads, label_file(name).open())}
    ideal: dict[str, list] = {}
    for (q, _), r in lab.items():
        ideal.setdefault(q, []).append(r)
    rng = random.Random(0)
    res = []
    print('| comparison | mean diff | wins / ties / losses | p (two-sided) |\n|---|---|---|---|')
    for p in pairs:
        a, b = p.split(':')
        xa, xb = per_query(name, a, lab, ideal), per_query(name, b, lab, ideal)
        d = [xb[q] - xa[q] for q in xa if max(ideal.get(q, [0])) >= 1]
        obs = sum(d) / len(d)
        hits = sum(abs(sum(v * rng.choice((1, -1)) for v in d) / len(d)) >= abs(obs) - 1e-12 for _ in range(20000))
        w, t, l = sum(v > 1e-9 for v in d), sum(abs(v) <= 1e-9 for v in d), sum(v < -1e-9 for v in d)
        pv = (hits + 1) / 20001
        res.append({'a': a, 'b': b, 'mean_diff': obs, 'wins': w, 'ties': t, 'losses': l, 'p': pv})
        print(f'| {b} vs {a} | {obs:+.3f} | {w} / {t} / {l} | {pv:.4f} |')
    tag = os.environ.get('RANKAI_LABEL_SET')
    (ROOT / 'eval' / (f'paired_{name}_{tag}.json' if tag else f'paired_{name}.json')).write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
