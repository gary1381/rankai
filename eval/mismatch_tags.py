"""How the `mismatch` tags line up with the labels: every labeled (query, posting) pair of v0-v3, deduplicated.

python eval/mismatch_tags.py   -> eval/mismatch_tags.json

A tag claims the posting clearly breaks a stated need, so a tagged pair should rarely be labeled good (rel >= 2).
For each tag kind: tagged pairs, their mean label and how many are rel >= 2, and the share of the rel >= 2 pairs (of
queries that state that need) that the tag would wrongly flag. Written 11-06 for the place / on-site tags; the
remote, type and pay tags are the reference. Labels were made before the new tags existed, by labelers who saw the
posting's location, so this measures agreement, not effect on users.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rankai import qrewrite, search  # noqa: E402
from rankai.db import connect  # noqa: E402

ROUNDS = ('v0', 'v1', 'v1b', 'v1c', 'v2', 'v2o', 'v2c', 'v3', 'v3o')


def kind(tag: str) -> str:
    return ('remote' if tag.endswith('not remote') else 'pay' if tag.startswith('pay') else
            'on-site' if tag == 'remote, not on-site' else 'place' if tag.startswith(('in ', 'remote from ')) else 'type')


def needs(qp: dict) -> set[str]:
    return {k for k, on in (('remote', qp['remote']), ('type', qp['kinds']), ('pay', qp['min_usd_year']),
                            ('on-site', qp['onsite']), ('place', qp['place'])) if on}


def main():
    c = connect()
    pairs = {}
    for r in ROUNDS:
        qs = {q['id']: q['query'] for q in map(json.loads, (ROOT / 'eval' / f'queries_{r}.jsonl').open())}
        for x in map(json.loads, (ROOT / 'eval' / f'labels_{r}.jsonl').open()):
            pairs.setdefault((qs[x['qid']], x['opp_id']), x['rel'])
    rows = {o['id']: o for o in c.execute('select * from opps')}
    qp = {q: search.ai_constraints(q, qrewrite.rewrite(q)) for q in {q for q, _ in pairs}}
    tagged, asked, examples = defaultdict(list), defaultdict(list), defaultdict(list)
    for (q, oid), rel in pairs.items():
        if oid not in rows:
            continue
        ks = {kind(t): t for t in search.mismatches(rows[oid], qp[q])}
        for k in needs(qp[q]):
            asked[k].append((rel, k in ks))
        for k, t in ks.items():
            tagged[k].append(rel)
            if rel >= 2 and len(examples[k]) < 5:
                examples[k].append({'query': q, 'opp_id': oid, 'rel': rel, 'tag': t})
    out = {'pairs': len(pairs), 'queries': len(qp), 'by_tag': {}}
    for k in ('remote', 'type', 'pay', 'on-site', 'place'):
        t, a = tagged[k], asked[k]
        good = [hit for rel, hit in a if rel >= 2]
        out['by_tag'][k] = {'queries_asking': sum(bool(needs(v) & {k}) for v in qp.values()), 'pairs_asking': len(a),
                            'tagged': len(t), 'tagged_mean_rel': sum(t) / len(t) if t else None,
                            'tagged_rel_ge2': sum(x >= 2 for x in t),
                            'untagged_mean_rel': (sum(r for r, hit in a if not hit) / max(1, sum(not h for _, h in a))),
                            'good_pairs': len(good), 'good_pairs_tagged': sum(good),
                            'examples_tagged_but_good': examples[k]}
    (ROOT / 'eval' / 'mismatch_tags.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{out['pairs']} pairs, {out['queries']} queries")
    print('| tag | queries asking | pairs asking | tagged | tagged mean rel | tagged rel>=2 | untagged mean rel | '
          'good pairs tagged |\n|---|---|---|---|---|---|---|---|')
    for k, v in out['by_tag'].items():
        m = f"{v['tagged_mean_rel']:.2f}" if v['tagged_mean_rel'] is not None else '-'
        print(f"| {k} | {v['queries_asking']} | {v['pairs_asking']} | {v['tagged']} | {m} | {v['tagged_rel_ge2']} | "
              f"{v['untagged_mean_rel']:.2f} | {v['good_pairs_tagged']} / {v['good_pairs']} |")


if __name__ == '__main__':
    main()
