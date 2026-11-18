"""Can Claude Haiku + GPT-6-Luna replace composer-2.5 + grok-4.7 as the rankai labelers? (11-06)

The previous labelers were no longer available, so the next label round needs a new pair. Before mixing new labels with the old ones,
both new labelers grade a sample of already-labeled pairs with the same rubric and the same posting cards.

python eval/labeler_calib.py make      -> 2 tasks of 100 in $RANKAI_LABEL_DIR/inbox
python eval/labeler_calib.py haiku     -> outbox/haiku/<task>.out.jsonl, one Haiku API call per item (rankai/llm.py)
  GPT-6-Luna: the dual-labeling tool (not included) on <task> with one labeler, gpt-6-luna at high effort
python eval/labeler_calib.py report    -> eval/labeler_calib_v1.json

Sample: v1 pairs (grok-4.7 wrote the v1 queries, so neither new labeler grades queries it wrote; GPT wrote v2 and
v3) whose card was not rebuilt by the 10-29 pay fix, so the old raw grades (`by`) are for the same text the new
labelers see. All pairs whose old mean is >= 2 are taken (few, and they decide coverage), the rest at random; the
report gives agreement on the sample and, with inverse sampling weights, for the v1 mix. Haiku also writes the
query rewrites (qrewrite.py); if it labels, the AI-rewrite arms could be favored, so the report checks whether Haiku
rates the pairs that only rewrite arms found higher than the old labelers did.
"""
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rankai import llm  # noqa: E402

LAB = Path(os.environ.get('RANKAI_LABEL_DIR') or ROOT / 'data' / 'labeling')
TASKS = ('rankai_calib_v1_00', 'rankai_calib_v1_01')
N_GOOD, N_ALL = 70, 200
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['rel', 'is_opportunity', 'confidence'],
          'properties': {'rel': {'type': 'integer', 'enum': [0, 1, 2, 3]}, 'is_opportunity': {'type': 'boolean'},
                         'confidence': {'type': 'number'}}}


def _pairs() -> dict[str, dict]:
    """id -> {prompt, task, old: {composer, grok}, mean} for v1 pairs labeled on the original card."""
    prompts = {}
    for f in sorted(LAB.glob('inbox/rankai_rel_v1_[0-9][0-9].jsonl')):
        for x in map(json.loads, f.open()):
            prompts[x['id']] = (x['prompt'], f.stem)
    out = {}
    for r in map(json.loads, (ROOT / 'eval' / 'labels_v1.jsonl').open()):
        i = f"{r['qid']}:{r['opp_id']}"
        if 'relabel' in r or i not in prompts:
            continue
        old = {k: r['by'][k] for k in ('composer', 'grok')}
        out[i] = {'prompt': prompts[i][0], 'task': prompts[i][1], 'old': old, 'mean': sum(old.values()) / 2,
                  'gpt_review': r['by'].get('gpt-review')}
    return out


def make():
    pairs = _pairs()
    rng = random.Random(1106)
    good = sorted(i for i, p in pairs.items() if p['mean'] >= 2)
    rest = sorted(i for i, p in pairs.items() if p['mean'] < 2)
    pick = rng.sample(good, min(N_GOOD, len(good)))
    pick += rng.sample(rest, N_ALL - len(pick))
    rng.shuffle(pick)
    md = (LAB / 'inbox' / f"{pairs[pick[0]]['task']}.md").read_text()
    for t, chunk in zip(TASKS, (pick[:100], pick[100:])):
        (LAB / 'inbox' / f'{t}.md').write_text(md.replace(pairs[pick[0]]['task'], t))
        with (LAB / 'inbox' / f'{t}.jsonl').open('w') as f:
            for i in chunk:
                f.write(json.dumps({'id': i, 'prompt': pairs[i]['prompt']}, ensure_ascii=False) + '\n')
    meta = {'good_pool': len(good), 'rest_pool': len(rest), 'good_taken': min(N_GOOD, len(good)),
            'rest_taken': N_ALL - min(N_GOOD, len(good)), 'ids': pick}
    (ROOT / 'eval' / 'labeler_calib_sample.json').write_text(json.dumps(meta, indent=1))
    print({k: v for k, v in meta.items() if k != 'ids'})


def _rubric(task: str) -> str:
    """The task .md without its file-output paragraph: Haiku answers one item per call through a JSON schema."""
    md = (LAB / 'inbox' / f'{task}.md').read_text()
    head, _, rest = md.partition('Output one line per input line')
    return head + rest[rest.index('## rel'):]


def haiku(workers: int = 2):
    for t in TASKS:
        out = LAB / 'outbox' / 'haiku' / f'{t}.out.jsonl'
        out.parent.mkdir(parents=True, exist_ok=True)
        done = {json.loads(l)['id'] for l in out.open()} if out.exists() else set()
        items = [x for x in map(json.loads, (LAB / 'inbox' / f'{t}.jsonl').open()) if x['id'] not in done]
        system = _rubric(t)

        def one(x):
            try:
                return x['id'], llm.claude_json(system, x['prompt'], SCHEMA, 'haiku', purpose='labeler_calib')
            except Exception as e:  # noqa: BLE001 - one failed call is retried on the next run
                print(x['id'], 'failed:', str(e)[:200], flush=True)
                return x['id'], None

        with ThreadPoolExecutor(workers) as ex, out.open('a') as f:
            for n, (i, r) in enumerate(ex.map(one, items), 1):
                if r is not None:
                    f.write(json.dumps({'id': i, 'response': r}) + '\n')
                    f.flush()
                if n % 20 == 0:
                    print(t, n, '/', len(items), flush=True)
    print('haiku spent USD', round(llm.spent('labeler_calib'), 3))


def _load(name: str) -> dict[str, dict]:
    out = {}
    for t in TASKS:
        p = LAB / 'outbox' / name / f'{t}.out.jsonl'
        if p.exists():
            for x in map(json.loads, p.open()):
                r = x.get('response') or {}
                if isinstance(r.get('rel'), (int, float)):
                    out[x['id']] = r
    return out


def wkappa(a: list[float], b: list[float], w: list[float] | None = None) -> float:
    """Quadratic-weighted kappa on the 0-3 scale (half grades allowed: they are means of two labelers)."""
    w = w or [1.0] * len(a)
    tw = sum(w)
    obs = sum(wi * (x - y) ** 2 for wi, x, y in zip(w, a, b)) / tw
    ma, mb = sum(wi * x for wi, x in zip(w, a)) / tw, sum(wi * y for wi, y in zip(w, b)) / tw
    va = sum(wi * (x - ma) ** 2 for wi, x in zip(w, a)) / tw
    vb = sum(wi * (y - mb) ** 2 for wi, y in zip(w, b)) / tw
    exp = va + vb + (ma - mb) ** 2
    return 1 - obs / exp if exp else float('nan')


def _agree(a, b, w):
    tw = sum(w)
    return {'n': len(a), 'weighted_kappa': round(wkappa(a, b, w), 3),
            'exact': round(sum(wi for wi, x, y in zip(w, a, b) if x == y) / tw, 3),
            'within1': round(sum(wi for wi, x, y in zip(w, a, b) if abs(x - y) <= 1) / tw, 3),
            'good_agree': round(sum(wi for wi, x, y in zip(w, a, b) if (x >= 2) == (y >= 2)) / tw, 3),
            'mean_a': round(sum(wi * x for wi, x in zip(w, a)) / tw, 3),
            'mean_b': round(sum(wi * y for wi, y in zip(w, b)) / tw, 3)}


def _rewrite_only() -> set[str]:
    """Pairs that only AI-rewrite arms (F-M) put in their top 10, none of A-E."""
    first, plain = {}, set()
    for f in (ROOT / 'eval' / 'runs').glob('v1_*.jsonl'):
        arm = f.stem.split('_', 1)[1]
        for r in map(json.loads, f.open()):
            for i in r['ids']:
                k = f"{r['qid']}:{i}"
                if arm in 'ABCDE':
                    plain.add(k)
                first[k] = True
    return {k for k in first if k not in plain}


def report():
    pairs = _pairs()
    meta = json.loads((ROOT / 'eval' / 'labeler_calib_sample.json').read_text())
    ids = meta['ids']
    wt = {True: meta['good_pool'] / meta['good_taken'], False: meta['rest_pool'] / meta['rest_taken']}
    new = {'haiku': _load('haiku'), 'luna': _load('luna')}
    both = [i for i in ids if all(i in new[n] for n in new)]
    w = [wt[pairs[i]['mean'] >= 2] for i in both]
    col = {'composer': [pairs[i]['old']['composer'] for i in both], 'grok': [pairs[i]['old']['grok'] for i in both],
           'old_mean': [pairs[i]['mean'] for i in both]}
    col |= {n: [float(new[n][i]['rel']) for i in both] for n in new}
    col['new_mean'] = [(a + b) / 2 for a, b in zip(col['haiku'], col['luna'])]
    comps = [('composer', 'grok'), ('haiku', 'luna'), ('haiku', 'composer'), ('haiku', 'grok'), ('luna', 'composer'),
             ('luna', 'grok'), ('new_mean', 'old_mean'), ('haiku', 'old_mean'), ('luna', 'old_mean')]
    rep = {'sample': {k: v for k, v in meta.items() if k != 'ids'}, 'graded_by_both': len(both),
           'missing': {n: sum(i not in new[n] for i in ids) for n in new},
           'weighted_to_v1_mix': {f'{a} vs {b}': _agree(col[a], col[b], w) for a, b in comps},
           'on_sample': {f'{a} vs {b}': _agree(col[a], col[b], [1.0] * len(both)) for a, b in comps}}
    ro = _rewrite_only()
    for name, keep in (('rewrite_only', lambda i: i in ro), ('other', lambda i: i not in ro)):
        sel = [k for k, i in enumerate(both) if keep(i)]
        if sel:
            rep.setdefault('haiku_bias_check', {})[name] = {
                'n': len(sel), 'haiku_minus_old': round(sum(col['haiku'][k] - col['old_mean'][k] for k in sel) / len(sel), 3),
                'luna_minus_old': round(sum(col['luna'][k] - col['old_mean'][k] for k in sel) / len(sel), 3)}
    by_lang = {}
    for lang in ('zh', 'en', 'mix'):  # v1 ids: hzh01 / hen01 / hmix01
        sel = [k for k, i in enumerate(both) if i.split(':')[0][1:].rstrip('0123456789') == lang]
        pick = lambda xs: [xs[k] for k in sel]  # noqa: E731
        by_lang[lang] = {f'{a} vs {b}': _agree(pick(col[a]), pick(col[b]), pick(w))
                         for a, b in (('haiku', 'luna'), ('composer', 'grok'), ('new_mean', 'old_mean'))}
    rep['by_language'] = by_lang
    conf = {}
    for n in ('haiku', 'luna'):
        m = [[0] * 4 for _ in range(4)]
        for k, i in enumerate(both):
            m[min(3, int(col['old_mean'][k]))][int(col[n][k])] += 1
        conf[n] = m
    rep['confusion_old_floor_by_new'] = conf
    (ROOT / 'eval' / 'labeler_calib_v1.json').write_text(json.dumps(rep, indent=1))
    print(f"graded by both: {len(both)} / {len(ids)}; missing {rep['missing']}")
    print('| pair | weighted kappa | exact | within 1 | agree on good (>=2) | mean a | mean b |\n|---|---|---|---|---|---|---|')
    for k, v in rep['weighted_to_v1_mix'].items():
        print(f"| {k} | {v['weighted_kappa']} | {v['exact']} | {v['within1']} | {v['good_agree']} | {v['mean_a']} | "
              f"{v['mean_b']} |")
    print(json.dumps(rep.get('haiku_bias_check'), indent=1))


if __name__ == '__main__':
    {'make': make, 'haiku': haiku, 'report': report}[sys.argv[1]]()
