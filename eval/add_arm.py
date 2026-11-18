"""Run one more arm on a frozen snapshot and send only its unlabeled (query, posting) pairs to labeling.

python eval/add_arm.py v0 G   -> eval/runs/v0_G.jsonl; new pairs appended to eval/pool_v0.jsonl and written as
                                 new task files rankai_rel_v0_NN (numbering continues; existing files untouched)
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval.pool import CHUNK, INSTRUCTIONS, LABEL_DIR, posting_text  # noqa: E402
from rankai import search  # noqa: E402
from rankai.db import connect  # noqa: E402


def main(name: str, arm: str):
    c = connect()
    snap = c.execute('select * from snapshots where name=?', (name,)).fetchone()
    qs = [json.loads(l) for l in (ROOT / 'eval' / f'queries_{name}.jsonl').open()]
    pool_f = ROOT / 'eval' / f'pool_{name}.jsonl'
    have = {(x['qid'], x['opp_id']) for x in map(json.loads, pool_f.open())}
    new = []
    with (ROOT / 'eval' / 'runs' / f'{name}_{arm}.jsonl').open('w') as f:
        for q in qs:
            res = search.search(q['query'], arm, 10, snap['max_opp_id'], c=c)
            f.write(json.dumps({'qid': q['id'], 'ids': [r['id'] for r in res],
                                'scores': [round(r['score'], 4) for r in res],
                                'feats': [r.get('feats') for r in res]}) + '\n')
            new += [(q['id'], r['id']) for r in res if (q['id'], r['id']) not in have]
    new = list(dict.fromkeys(new))
    with pool_f.open('a') as f:
        for qid, oid in new:
            f.write(json.dumps({'qid': qid, 'opp_id': oid, 'added_by': arm}) + '\n')
    existing = sorted(int(p.stem.rsplit('_', 1)[1]) for p in (LABEL_DIR / 'inbox').glob(f'rankai_rel_{name}_[0-9]*.jsonl'))
    nxt = (existing[-1] + 1) if existing else 0
    qmap = {q['id']: q for q in qs}
    rows = {r['id']: r for r in c.execute('select * from opps where id<=?', (snap['max_opp_id'],))}
    random.Random(7).shuffle(new)
    files = []
    for n in range(0, len(new), CHUNK):
        task = f'rankai_rel_{name}_{nxt + n // CHUNK:02d}'
        with (LABEL_DIR / 'inbox' / f'{task}.jsonl').open('w') as f:
            for qid, oid in new[n:n + CHUNK]:
                f.write(json.dumps({'id': f'{qid}:{oid}', 'prompt': f"QUERY: {qmap[qid]['query']}\n\nPOSTING:\n"
                                    f"{posting_text(rows[oid])}"}, ensure_ascii=False) + '\n')
        (LABEL_DIR / 'inbox' / f'{task}.md').write_text(INSTRUCTIONS)
        files.append(task)
    print(f'arm {arm}: {len(new)} new pairs -> {files}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
