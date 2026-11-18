"""Did the new sources fill the gaps? Same queries, old corpus vs new corpus.

python eval/coverage.py v1 v1b F H
  per arm: queries with at least one rel >= 2 posting in the top 10, mean count of rel >= 2 in the top 10, P@5,
  overall and per language; queries newly covered; which sources supplied the rel >= 2 results on the new corpus;
  exact McNemar p on covered (newly covered vs lost) and a paired sign-flip p on P@5.
  Buyer-side outsourcing queries (gaps.buyer_side) want providers, not job posts: the 'no buyer' row and
  mcnemar_p_no_buyer leave them out.
  -> eval/coverage_<old>_<new>.json
Each corpus is scored with its own labels (labels_<name>.jsonl); unlabeled results count as 0.
"""
import json
import random
import sqlite3
import sys
from collections import Counter
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.gaps import buyer_side  # noqa: E402


def load(name: str, arm: str):
    lab = {(x['qid'], x['opp_id']): x['rel'] for x in map(json.loads, (ROOT / 'eval' / f'labels_{name}.jsonl').open())}
    runs = {r['qid']: r['ids'] for r in map(json.loads, (ROOT / 'eval' / 'runs' / f'{name}_{arm}.jsonl').open())}
    return {q: [lab.get((q, i), 0) for i in ids] for q, ids in runs.items()}, runs


def stats(rels: dict, qs: list[str]) -> dict:
    n = len(qs) or 1
    return {'queries': len(qs), 'covered': sum(any(r >= 2 for r in rels[q][:10]) for q in qs),
            'good_in_top10': round(sum(sum(r >= 2 for r in rels[q][:10]) for q in qs) / n, 2),
            'P@5': round(sum(sum(r >= 2 for r in rels[q][:5]) / 5 for q in qs) / n, 3)}


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p from the discordant counts."""
    n = b + c
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n) if n else 1.0


def signflip(d: list[float], rounds: int = 20000) -> float:
    rng, obs = random.Random(0), abs(sum(d) / len(d))
    hits = sum(abs(sum(v * rng.choice((1, -1)) for v in d) / len(d)) >= obs - 1e-12 for _ in range(rounds))
    return (hits + 1) / (rounds + 1)


def main(old: str, new: str, arms: list[str]):
    lang = {q['id']: q['lang'] for q in map(json.loads, (ROOT / 'eval' / f'queries_{new}.jsonl').open())}
    text = {q['id']: q['query'] for q in map(json.loads, (ROOT / 'eval' / f'queries_{new}.jsonl').open())}
    c = sqlite3.connect(ROOT / 'data' / 'rankai.sqlite')
    src = dict(c.execute('select id, source from opps'))
    buyers = {q for q, t in text.items() if buyer_side(t)}
    rep = {}
    for arm in arms:
        a, _ = load(old, arm)
        b, runs = load(new, arm)
        qs = sorted(b)
        rep[arm] = {'old': {'all': stats(a, qs)}, 'new': {'all': stats(b, qs)}}
        for lg in ('zh', 'en', 'mix'):
            sub = [q for q in qs if lang[q] == lg]
            rep[arm]['old'][lg], rep[arm]['new'][lg] = stats(a, sub), stats(b, sub)
        rest = [q for q in qs if q not in buyers]
        rep[arm]['old']['no buyer'], rep[arm]['new']['no buyer'] = stats(a, rest), stats(b, rest)
        rep[arm]['newly_covered'] = [f'{q} {text[q]}' for q in qs
                                     if any(r >= 2 for r in b[q][:10]) and not any(r >= 2 for r in a[q][:10])]
        rep[arm]['lost'] = [f'{q} {text[q]}' for q in qs
                            if any(r >= 2 for r in a[q][:10]) and not any(r >= 2 for r in b[q][:10])]
        rep[arm]['mcnemar_p'] = mcnemar(len(rep[arm]['newly_covered']), len(rep[arm]['lost']))
        gained, lost = [[x for x in rep[arm][k] if x.split()[0] not in buyers] for k in ('newly_covered', 'lost')]
        rep[arm]['mcnemar_p_no_buyer'] = mcnemar(len(gained), len(lost))
        rep[arm]['p5_signflip_p'] = signflip([(sum(r >= 2 for r in b[q][:5]) - sum(r >= 2 for r in a[q][:5])) / 5
                                              for q in qs])
        rep[arm]['good_by_source'] = dict(Counter(src.get(i, '?') for q in qs for i, r in zip(runs[q][:10], b[q][:10])
                                                  if r >= 2).most_common())
    (ROOT / 'eval' / f'coverage_{old}_{new}.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    for arm, r in rep.items():
        print(f'\n## arm {arm}\n| corpus | lang | covered / queries | rel>=2 in top 10 | P@5 |\n|---|---|---|---|---|')
        for side in ('old', 'new'):
            for lg in ('all', 'no buyer', 'zh', 'en', 'mix'):
                s = r[side][lg]
                print(f"| {side} | {lg} | {s['covered']} / {s['queries']} | {s['good_in_top10']} | {s['P@5']:.3f} |")
        print('newly covered:', r['newly_covered'])
        print('lost:', r['lost'])
        print(f"covered: +{len(r['newly_covered'])} / -{len(r['lost'])}, exact McNemar p = {r['mcnemar_p']:.4f}; "
              f"P@5 sign-flip p = {r['p5_signflip_p']:.4f}; without buyer-side p = {r['mcnemar_p_no_buyer']:.4f}")
        print('rel>=2 results by source (new):', r['good_by_source'])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or ['F', 'H'])
