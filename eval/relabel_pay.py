"""Relabel the pairs of every query that states a pay requirement, with the fixed labeling card (10-29).

Until 10-29 `redact` turned the card's "Pay:" line and posting date into "[phone]", so labelers could not check a
stated minimum pay. The query list below was fixed before any new label existed.

python eval/relabel_pay.py tasks   -> labeling tasks rankai_rel_payfix_<set>_NN (one per query set; a pair pooled
                                      under two evals of the same queries, e.g. v1 and v1b, is labeled once)
bash eval/run_labels.sh payfix_v0; bash eval/run_labels.sh payfix_v1; bash eval/run_labels.sh payfix_v2 --gpt-review none
                                      (same labelers as each set's first round: GPT did not label v2, it wrote the queries)
python eval/relabel_pay.py merge   -> eval/labels_<name>.jsonl updated in place for v0 v1 v1b v2 v2o; the first merge
                                      keeps the old file as eval/labels_<name>_prepay.jsonl; report -> eval/relabel_pay.json
                                      Safe to run again, and needed again after `merge_labels.py <name>` rebuilds a
                                      labels file from the outbox (that rebuild brings back the pre-fix labels).
"""
import json
import random
import shutil
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.merge_labels import load, wkappa  # noqa: E402
from eval.pool import CHUNK, INSTRUCTIONS, LABEL_DIR, posting_text  # noqa: E402
from rankai.db import connect  # noqa: E402

PAY_QUERIES = {  # chosen by reading every query; "Europe" (en07, mix11) only matched a currency pattern
    'v0': ['zh03', 'en02', 'mix09'],
    'v1': ['hzh01', 'hzh03', 'hzh09', 'hzh16', 'hen01', 'hen02', 'hen16', 'hmix01', 'hmix09', 'hmix16'],
    'v2': ['gzh01', 'gzh05', 'gen01', 'gen05', 'gmix01', 'gmix05'],
}
EVALS = {'v0': ['v0'], 'v1': ['v1', 'v1b'], 'v2': ['v2', 'v2o']}  # query set -> evals that pooled those queries
TAG = 'payfix-20261029'


def _labels(name: str, suffix: str = '') -> list[dict]:
    return [json.loads(l) for l in (ROOT / 'eval' / f'labels_{name}{suffix}.jsonl').open()]


def tasks():
    c = connect()
    for qset, qids in PAY_QUERIES.items():
        qmap = {q['id']: q for q in map(json.loads, (ROOT / 'eval' / f'queries_{qset}.jsonl').open())}
        pairs = sorted({(x['qid'], x['opp_id']) for n in EVALS[qset] for x in _labels(n) if x['qid'] in qids})
        present = {r[0] for r in c.execute('select id from opps')}
        pairs = [p for p in pairs if p[1] in present]
        rows = {r['id']: r for r in c.execute(
            f"select * from opps where id in ({','.join('?' * len(pairs))})", [o for _, o in pairs])}
        random.Random(7).shuffle(pairs)
        for n in range(0, len(pairs), CHUNK):
            task = f'rankai_rel_payfix_{qset}_{n // CHUNK:02d}'
            with (LABEL_DIR / 'inbox' / f'{task}.jsonl').open('w') as f:
                for qid, oid in pairs[n:n + CHUNK]:
                    f.write(json.dumps({'id': f'{qid}:{oid}', 'prompt': f"QUERY: {qmap[qid]['query']}\n\nPOSTING:\n"
                                        f"{posting_text(rows[oid])}"}, ensure_ascii=False) + '\n')
            (LABEL_DIR / 'inbox' / f'{task}.md').write_text(INSTRUCTIONS)
        print(f'{qset}: {len(qids)} queries, {len(pairs)} pairs -> {(len(pairs) + CHUNK - 1) // CHUNK} task files')


def merge():
    rep = {}
    for qset in PAY_QUERIES:
        got = load(f'payfix_{qset}')
        new = {}
        for key, labs in got.items():
            qid, oid = key.split(':')
            rels = [v['rel'] for v in labs.values()]
            opp = [bool(v.get('is_opportunity', True)) for v in labs.values()]
            new[(qid, int(oid))] = {'rel': round(statistics.mean(rels), 3), 'is_opportunity': sum(opp) * 2 >= len(opp),
                                    'by': {k: v['rel'] for k, v in labs.items()}}
        both = [(v['by']['composer'], v['by']['grok']) for v in new.values() if {'composer', 'grok'} <= set(v['by'])]
        for name in EVALS[qset]:
            backup = ROOT / 'eval' / f'labels_{name}_prepay.jsonl'
            if not backup.exists():
                shutil.copy(ROOT / 'eval' / f'labels_{name}.jsonl', backup)
            old = _labels(name)  # current file: a fresh merge_labels rebuild, or an earlier run of this merge
            out, changed, diffs, trans = [], 0, [], {}
            for x in old:
                k = (x['qid'], x['opp_id'])
                if k in new:
                    before = x.get('rel_before', x['rel'])
                    y = {kk: vv for kk, vv in x.items() if kk not in ('rel', 'is_opportunity', 'by', 'reused_from',
                                                                     'relabel', 'rel_before')}
                    y |= new[k] | {'relabel': TAG, 'rel_before': before}
                    out.append(y)
                    changed += 1
                    diffs.append(new[k]['rel'] - before)
                    t = f"{int(before >= 2)}->{int(new[k]['rel'] >= 2)}"
                    trans[t] = trans.get(t, 0) + 1
                else:
                    out.append(x)
            with (ROOT / 'eval' / f'labels_{name}.jsonl').open('w') as f:
                for x in out:
                    f.write(json.dumps(x, ensure_ascii=False) + '\n')
            rep[name] = {'relabeled': changed, 'mean_rel_change': round(statistics.mean(diffs), 3) if diffs else 0,
                         'good_(rel>=2)_before->after': trans,
                         'raised_by_1+': sum(d >= 1 for d in diffs), 'lowered_by_1+': sum(d <= -1 for d in diffs)}
        rep[f'payfix_{qset}'] = {'pairs': len(new), 'gpt_reviewed': sum('gpt-review' in v['by'] for v in new.values()),
                                 'composer_vs_grok_kappa': round(wkappa(*map(list, zip(*both))), 3) if both else None}
    (ROOT / 'eval' / 'relabel_pay.json').write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == '__main__':
    {'tasks': tasks, 'merge': merge}[sys.argv[1]]()
