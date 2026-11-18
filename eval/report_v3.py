"""The v3 numbers eval/PLAN_v3.md names that score.py, paired.py and coverage.py do not print.

python eval/paired.py v3 M:J F:J J:L F:L; python eval/coverage.py v3o v3 J; python eval/report_v3.py
  -> eval/report_v3.json: Holm-adjusted p for the three primaries, metrics per arm (eval/ltr_metrics.end_to_end),
  paired tests on P@5, MRR and rel >= 1 share, how often M changes J's top 10, how many of J's top-10 results carry a
  `mismatch` tag and how those are labeled. Not in the plan, so exploratory: the same arms over queries whose pool holds
  a rel >= 2 posting vs queries whose best posting is below 2 (`by_best`), and the main tests redone over themes
  (`by_theme`), since the query set is mostly one need written three ways.
"""
import json
import re
import sys
from collections import Counter
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.coverage import signflip  # noqa: E402
from eval.ltr_metrics import end_to_end, labels, query_rows  # noqa: E402
from rankai import qrewrite, search  # noqa: E402
from rankai.db import connect  # noqa: E402

E = ROOT / 'eval'


def holm(ps: dict[str, float]) -> dict[str, float]:
    out, top = {}, 0.0
    for i, (k, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        top = max(top, min(1.0, p * (len(ps) - i)))
        out[k] = top
    return out


def runs(arm: str) -> dict[str, list[int]]:
    return {r['qid']: r['ids'] for r in map(json.loads, (E / 'runs' / f'v3_{arm}.jsonl').open())}


def tags(j: dict[str, list[int]]) -> dict:
    c = connect()
    qs = {q['id']: q['query'] for q in map(json.loads, (E / 'queries_v3.jsonl').open())}
    lab = labels('v3')
    n, kinds, tagged = 0, Counter(), 0
    rel = {True: [], False: []}
    for qid, ids in j.items():
        rw = qrewrite.rewrite(qs[qid])
        qp = search.ai_constraints(qs[qid], rw)
        rows = c.execute(f"select * from opps where id in ({','.join('?' * len(ids))})", ids).fetchall()
        for r in rows:
            # §10 counted the remote / type / pay tags; the 11-06 place and on-site tags are left out to keep it
            m = [x for x in search.mismatches(r, qp) if not x.startswith(('in ', 'remote from ', 'remote, not on'))]
            n += 1
            tagged += bool(m)
            kinds.update('remote' if x.endswith('not remote') else 'pay' if x.startswith('pay') else 'type' for x in m)
            rel[bool(m)].append(lab.get((qid, r['id']), 0))
    stat = lambda xs: {'n': len(xs), 'mean_rel': sum(xs) / len(xs), 'rel_ge2': sum(x >= 2 for x in xs)}  # noqa: E731
    return {'results': n, 'tagged': tagged, 'by_tag': dict(kinds.most_common()),
            'with_tag': stat(rel[True]), 'without_tag': stat(rel[False])}


def secondary(rows: dict[str, dict]) -> dict:
    """Mean difference and sign-flip p of P@5, MRR and the share of rel >= 1 in the top 10."""
    out = {}
    for b, a in ('JF', 'MJ', 'LJ', 'LF'):
        out[f'{b} vs {a}'] = {}
        for k in ('p5', 'rr', 'ok1'):
            d = [rows[b][q][k] - rows[a][q][k] for q in rows[a]]
            out[f'{b} vs {a}'][k] = {'diff': sum(d) / len(d), 'p': signflip(d)}
    return out


def theme_flip(rows: dict[str, dict], b: str, a: str, key: str = 'nd', qs: list[str] | None = None) -> dict:
    """Exact sign-flip over themes (kzh05, ken05, kmix05 = theme 05): each theme's mean difference counts once."""
    by: dict[str, list[float]] = {}
    for q in qs or rows[a]:
        by.setdefault(re.sub(r'\D', '', q), []).append(rows[b][q][key] - rows[a][q][key])
    d = [sum(v) / len(v) for v in by.values()]
    hits = sum(abs(sum(s * x for s, x in zip(flip, d))) >= abs(sum(d)) - 1e-12 for flip in product((1, -1), repeat=len(d)))
    return {'themes': len(d), 'diff': sum(d) / len(d), 'p': hits / 2 ** len(d)}


def by_best(rows: dict[str, dict]) -> dict:
    """nDCG@10 per arm, split by whether the pool holds a rel >= 2 posting; J vs F and M vs J inside each group."""
    out = {}
    for name, qs in (('best_ge2', [q for q, r in rows['J'].items() if r['best'] >= 2]),
                     ('best_below2', [q for q, r in rows['J'].items() if r['best'] < 2])):
        d = [rows['J'][q]['nd'] - rows['F'][q]['nd'] for q in qs]
        e = [rows['M'][q]['nd'] - rows['J'][q]['nd'] for q in qs]
        out[name] = {'queries': len(qs), 'J_minus_F': sum(d) / len(d), 'p': signflip(d),
                     'M_minus_J': sum(e) / len(e), 'M_p': signflip(e),
                     'J_vs_F_theme': theme_flip(rows, 'J', 'F', qs=qs), 'M_vs_J_theme': theme_flip(rows, 'M', 'J', qs=qs)}
        out[name] |= {a: sum(rows[a][q]['nd'] for q in qs) / len(qs) for a in 'FJLM'}
    return out


def main():
    paired = {f"{x['b']} vs {x['a']}": x for x in json.loads((E / 'paired_v3.json').read_text())}
    cov = json.loads((E / 'coverage_v3o_v3.json').read_text())['J']
    ps = {'J vs M': paired['J vs M']['p'], 'J vs F': paired['J vs F']['p'], 'coverage': cov['mcnemar_p_no_buyer']}
    j, m = runs('J'), runs('M')
    rows = {a: {r['qid']: r for r in query_rows('v3', a)[0]} for a in 'FJLM'}
    covered = {a: {q for q, r in rows[a].items() if r['cov']} for a in 'FJLM'}
    rep = {'primary_p': ps, 'holm_p': holm(ps), 'paired': paired, 'arms': end_to_end('v3', 'FJLM'),
           'secondary': secondary(rows), 'by_best': by_best(rows),
           'by_theme': {f'{b} vs {a}': theme_flip(rows, b, a) for b, a in ('JF', 'JM', 'LJ', 'LF')},
           'covered_by_all_arms': len(set.intersection(*covered.values())),
           'covered_by_any_arm': len(set.union(*covered.values())),
           'j_m_same_order': sum(j[q] == m[q] for q in j), 'j_m_same_set': sum(set(j[q]) == set(m[q]) for q in j),
           'j_m_overlap': sum(len(set(j[q]) & set(m[q])) for q in j) / sum(len(j[q]) for q in j),
           'queries': len(j), 'j_mismatch_tags': tags(j)}
    (E / 'report_v3.json').write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in rep.items() if k not in ('paired', 'arms')}, indent=1, ensure_ascii=False))
    for a, r in rep['arms'].items():
        print(a, {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})


if __name__ == '__main__':
    main()
