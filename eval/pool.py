"""Run arms on a frozen snapshot, save the runs, pool the top 10 of each arm, write labeling task files.

python eval/pool.py v0 [ABCDEF]   -> eval/runs/v0_<arm>.jsonl, eval/pool_v0.jsonl,
                                     $RANKAI_LABEL_DIR/inbox/rankai_rel_v0_NN.{jsonl,md}
python eval/pool.py v1 EFGHI      held-out queries eval/queries_v1.jsonl; G/H/I first get an AI judgment for every
                                  posting in F's top-50 candidates (judge.ensure), so no candidate lacks one
python eval/pool.py v1b FH --reuse v1
                                  same queries on a newer corpus; pairs already in labels_v1.jsonl get no new task
python eval/pool.py v2o FH --skip-pool v2
                                  pairs already in pool_v2.jsonl get no new task (labeled under v2; merge with --reuse v2)
"""
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rankai import judge, search  # noqa: E402
from rankai.db import connect  # noqa: E402
from rankai.text import redact  # noqa: E402

LABEL_DIR = Path(os.environ.get('RANKAI_LABEL_DIR') or ROOT / 'data' / 'labeling')
CHUNK = 100

INSTRUCTIONS = """# rankai_rel — is this posting a good result for this opportunity search?

Each line has a searcher's query (Chinese, English or mixed) and ONE posting (a job, gig, open-source issue or
collaboration post) taken from a job board, a company careers page, a government job service, Hacker News, V2EX or GitHub. Contact details were
removed. Use only the text given; do not look anything up.

Output one line per input line, same `id`:
`{"id": "...", "response": {"rel": 0|1|2|3, "is_opportunity": true|false, "confidence": 0.0-1.0}}`
then create the `.done` file.

## rel — how well the posting satisfies the query
- **3** right role/skills AND right type of engagement, and every constraint the query states (remote, location,
  minimum pay, part-time / freelance / internship / outsourcing / bounty / co-founder) is clearly met.
- **2** right role/skills, but one stated constraint is not shown in the posting (e.g. query asks for remote and the
  posting does not say), or one minor mismatch (adjacent seniority, close but not identical stack).
- **1** same broad field but a clear mismatch in role, type of engagement or a stated constraint
  (e.g. query wants part-time, posting is full-time; query wants a backend role, posting is sales at a tech company).
- **0** unrelated, OR the posting explicitly violates a stated hard constraint (query wants remote, posting is on-site
  only; query wants >= X pay, posting states less), OR it is not an opportunity at all (see below).
Do not reward a posting for merely sharing keywords. Judge what the searcher would actually want to open.

## is_opportunity
true if the post offers work, pay, a role, a bounty or a collaboration that someone could take up. false for job
seekers advertising themselves, questions/advice threads ("help me improve my resume"), news, or spam.
If is_opportunity is false, rel must be 0.

## confidence
Your confidence in `rel`, 0.0-1.0.
"""


# The source's own job-type field (11-07). Cards had no type line until then, so labelers guessed it from the text,
# and the "type" mismatch tag flagged 97 of 576 good results (docs/EVALUATION.md, labeler calibration). Our
# `kind` falls back to full-time when nothing is stated, so it is not shown. ncss states a type only through the city
# pass's filter, which the Tags line already shows (ncss:北京/parttime).
STATED_TYPE = {
    'ashby': lambda j: j.get('employmentType'),
    'lever': lambda j: (j.get('categories') or {}).get('commitment'),
    'smartrecruiters': lambda j: (j.get('typeOfEmployment') or {}).get('label'),
    'himalayas': lambda j: j.get('employmentType'),
    'remotive': lambda j: (j.get('job_type') or '').replace('_', ' '),
    'jobicy': lambda j: j.get('jobType'),
    'arbeitnow': lambda j: j.get('job_types'),
    'wwr': lambda j: j.get('type'),
    'taiwanjobs': lambda j: j.get('type'),
}


def stated_types(c, rows) -> dict[int, str]:
    """opp id -> the job type its source states, from the posting's latest raw payload (none: left out)."""
    out = {}
    for r in rows:
        get = STATED_TYPE.get(r['source'])
        p = get and c.execute('select payload from raw_items where source=? and source_id=? order by id desc limit 1',
                              (r['source'], r['source_id'])).fetchone()
        t = get(json.loads(p[0])) if p else None
        t = ', '.join(map(str, t)) if isinstance(t, list) else str(t or '')
        if t.strip():
            out[r['id']] = t.strip()
    return out


def posting_text(r, stated_type: str = '') -> str:
    """stated_type: from stated_types(). Rounds labeled before 11-07 had no type line; relabel_pay.py and
    add_arm.py rebuild their cards without it."""
    sal = f"\nPay: {r['salary_min']:.0f}-{r['salary_max']:.0f} {r['currency']} per {r['period']}" if r['salary_min'] else ''
    # work mode only where the source API states it (Ashby/Lever workplaceType); elsewhere it is our own rule guess
    rem = ''
    if r['source'] in ('ashby', 'lever') and r['remote'] is not None:
        rem = ' | work mode: ' + {1.0: 'remote', 0.5: 'hybrid', 0.0: 'on-site'}[r['remote']]
    if stated_type:
        rem += f'\nType: {redact(stated_type)}'
    # redact every free-text field (HN titles carry emails); pay, date and source are our own structured fields and
    # stay as they are (until 10-29 the whole card went through redact, which turned them into "[phone]")
    title, org, loc, tags, body = (redact(x or '') for x in (r['title'], r['org'], r['location'], r['tags'],
                                                            (r['text'] or '')[:1800]))
    return (f"Title: {title}\nOrganization: {org or '(not given)'}\nLocation: {loc or '(not given)'}"
            f"{rem}\nSource: {r['source']} | posted {(r['posted_at'] or '')[:10]}{sal}\n"
            f"Tags: {tags}\n---\n{body}")


def main(name: str, arms: str = 'ABCDEF', reuse: str | None = None, skip_pool: str | None = None):
    c = connect()
    snap = c.execute('select * from snapshots where name=?', (name,)).fetchone()
    if not snap:
        sys.exit(f'no snapshot {name}: run `python -m rankai snapshot {name}` first')
    qs = [json.loads(l) for l in (ROOT / 'eval' / f'queries_{name}.jsonl').open()]
    if set(arms) & {'G', 'H', 'I', 'K'}:
        cand = [i for q in qs for i, _ in search.first_stage(c, q['query'], 'F', snap['max_opp_id'])[0][:50]]
        print('judged', judge.ensure(list(dict.fromkeys(cand))), 'new postings', flush=True)
    (ROOT / 'eval' / 'runs').mkdir(exist_ok=True)
    pool: dict[str, set[int]] = {}
    for arm in arms:
        with (ROOT / 'eval' / 'runs' / f'{name}_{arm}.jsonl').open('w') as f:
            for q in qs:
                res = search.search(q['query'], arm, 10, snap['max_opp_id'], c=c)
                f.write(json.dumps({'qid': q['id'], 'ids': [r['id'] for r in res],
                                    'scores': [round(r['score'], 4) for r in res],
                                    'feats': [r.get('feats') for r in res]}) + '\n')
                pool.setdefault(q['id'], set()).update(r['id'] for r in res)
        print(f'arm {arm} done', flush=True)
    items = []
    for qid, ids in pool.items():
        for oid in sorted(ids):
            items.append((qid, oid))
    with (ROOT / 'eval' / f'pool_{name}.jsonl').open('w') as f:
        for qid, oid in items:
            f.write(json.dumps({'qid': qid, 'opp_id': oid}) + '\n')
    write_tasks(name, reuse, skip_pool)


def write_tasks(name: str, reuse: str | None = None, skip_pool: str | None = None):
    c = connect()
    snap = c.execute('select * from snapshots where name=?', (name,)).fetchone()
    qmap = {q['id']: q for q in map(json.loads, (ROOT / 'eval' / f'queries_{name}.jsonl').open())}
    items = [(x['qid'], x['opp_id']) for x in map(json.loads, (ROOT / 'eval' / f'pool_{name}.jsonl').open())]
    if reuse:  # already labeled under another eval name with the same queries
        have = {(x['qid'], x['opp_id']) for x in map(json.loads, (ROOT / 'eval' / f'labels_{reuse}.jsonl').open())}
        items = [x for x in items if x not in have]
    if skip_pool:  # same queries, pooled under another eval that is being labeled anyway
        have = {(x['qid'], x['opp_id']) for x in map(json.loads, (ROOT / 'eval' / f'pool_{skip_pool}.jsonl').open())}
        items = [x for x in items if x not in have]
    random.Random(7).shuffle(items)  # mix queries across files so one file is not one query
    (LABEL_DIR / 'inbox').mkdir(parents=True, exist_ok=True)
    (LABEL_DIR / 'outbox').mkdir(exist_ok=True)
    rows = {r['id']: r for r in c.execute('select * from opps where id<=?', (snap['max_opp_id'],))}
    types = stated_types(c, [rows[oid] for oid in {oid for _, oid in items}])
    for n in range(0, len(items), CHUNK):
        task = f'rankai_rel_{name}_{n // CHUNK:02d}'
        with (LABEL_DIR / 'inbox' / f'{task}.jsonl').open('w') as f:
            for qid, oid in items[n:n + CHUNK]:
                prompt = f"QUERY: {qmap[qid]['query']}\n\nPOSTING:\n{posting_text(rows[oid], types.get(oid, ''))}"
                f.write(json.dumps({'id': f'{qid}:{oid}', 'prompt': prompt}, ensure_ascii=False) + '\n')
        (LABEL_DIR / 'inbox' / f'{task}.md').write_text(INSTRUCTIONS)
    print(f'pool: {len(items)} pairs over {len(qmap)} queries -> {(len(items) + CHUNK - 1) // CHUNK} task files')


if __name__ == '__main__':
    a = sys.argv[1:]
    reuse = a[a.index('--reuse') + 1] if '--reuse' in a else None
    skip = a[a.index('--skip-pool') + 1] if '--skip-pool' in a else None
    if '--tasks-only' in a:
        write_tasks(a[0], reuse, skip)
    else:
        main(a[0] if a else 'v0', *[x for x in a[1:2] if not x.startswith('--')], reuse=reuse, skip_pool=skip)
