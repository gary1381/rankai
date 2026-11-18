"""AI judgment of each posting on its own, without any query (arm G). Judged once, stored append-only in `judgments`
(kind='posting'), reused by every later search.

Fields: is_opportunity, role_family, clarity 0-2, scam_risk 0-2. Judge = Claude Haiku, which is not one of the
evaluation labelers. Contact details are redacted before the text leaves the machine.

role_family is also the posting's field for search(field=...). The daily timer judges new live postings
(`python -m rankai judge-live`, spend cap per run). Judgments up to 10-30 came from Haiku through the claude CLI,
later ones from claude-haiku-5-5 through the API; both are stored under the same judge/version, since the prompt and
schema did not change.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from . import llm
from .db import connect, now
from .fresh import archived_ids, closed_ids
from .text import redact

JUDGE, VERSION = 'claude-haiku', 'pj-v1'
BATCH = 10
FAMILIES = ['engineering', 'data_ml', 'design', 'product', 'sales_marketing', 'support_success', 'operations',
            'research', 'other']
SYSTEM = """You assess job, gig and collaboration postings collected from company career pages, job boards, Hacker News,
V2EX (Chinese forum) and GitHub issues. Judge each posting on its own text only.

is_opportunity: true if the post offers work, pay, a role, a bounty or a collaboration that someone else could take up.
  false for: people advertising their own services or looking for work ("接单", "求职", "SEEKING WORK"),
  questions or advice threads (e.g. resume help), news, discussion, or spam.
role_family: the main kind of role offered (pick the closest).
clarity: 0 = vague (unclear what the work is), 1 = partly clear, 2 = clear role, tasks and requirements.
scam_risk: 0 = no warning signs, 1 = some (vague company, pay far above market, contact only by personal messenger),
  2 = strong (asks the applicant to pay, deposit or buy equipment; phishing; reported as fraud)."""
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['items'],
          'properties': {'items': {'type': 'array', 'items': {
              'type': 'object', 'additionalProperties': False,
              'required': ['id', 'is_opportunity', 'role_family', 'clarity', 'scam_risk'],
              'properties': {'id': {'type': 'integer'}, 'is_opportunity': {'type': 'boolean'},
                             'role_family': {'enum': FAMILIES}, 'clarity': {'enum': [0, 1, 2]},
                             'scam_risk': {'enum': [0, 1, 2]}}}}}}


def _card(r) -> str:
    return redact(f"[id {r['id']}] source={r['source']} | {r['title']} | org: {r['org'] or '-'} | "
                  f"location: {r['location'] or '-'}\n{(r['text'] or '')[:1200]}")


def latest(c, ids) -> dict[int, dict]:
    ids = list(ids)
    if not ids:
        return {}
    out = {}
    for n in range(0, len(ids), 900):  # SQLite caps the number of ? in one statement
        part = ids[n:n + 900]
        q = (f"select opp_id, scores from judgments where kind='posting' and judge=? and prompt_version=? "
             f"and opp_id in ({','.join('?' * len(part))}) order by id")
        out.update({r['opp_id']: json.loads(r['scores']) for r in c.execute(q, (JUDGE, VERSION, *part))})
    return out


def fields(c, ids) -> dict[int, str]:
    """id -> role_family for the ids that have a judgment."""
    return {i: s.get('role_family') for i, s in latest(c, ids).items()}


def ids_in_fields(c, field: str) -> set[int]:
    """Postings whose role_family is one of the comma-separated names in field."""
    want = {f.strip() for f in field.split(',') if f.strip()}
    if bad := want - set(FAMILIES):
        raise ValueError(f"unknown field {', '.join(sorted(bad))}; use {', '.join(FAMILIES)}")
    fam = {}
    for oid, s in c.execute("select opp_id, scores from judgments where kind='posting' and judge=? and "
                            "prompt_version=? order by id", (JUDGE, VERSION)):
        fam[oid] = json.loads(s).get('role_family')
    return {i for i, f in fam.items() if f in want}


def live_unjudged(c) -> list[int]:
    """Live postings (not closed, not archived) without a judgment, newest first."""
    gone = closed_ids(c) | archived_ids(c)
    have = {r[0] for r in c.execute("select distinct opp_id from judgments where kind='posting' and judge=? and "
                                    "prompt_version=?", (JUDGE, VERSION))}
    return [r[0] for r in c.execute('select id from opps order by id desc') if r[0] not in gone and r[0] not in have]


def _ask(part):
    try:
        return part, llm.claude_json(SYSTEM, '\n\n'.join(_card(r) for r in part), SCHEMA, purpose='posting_judge')
    except Exception as e:  # noqa: BLE001 - one failed batch is retried on the next run
        print(f'batch failed ({type(e).__name__}: {str(e)[:120]})', flush=True)
        return part, {}


def ensure(ids, max_usd: float = 3.0, workers: int = 1) -> int:
    """Judge every id that has no judgment yet under this judge/version. Stops at max_usd of spend.
    workers > 1 sends that many batches at once (API calls only; the writes stay in this thread)."""
    c = connect()
    have = latest(c, ids)
    todo = [i for i in ids if i not in have]
    rows = {}
    for n in range(0, len(todo), 900):
        q = todo[n:n + 900]
        rows.update({r['id']: r for r in c.execute(f"select * from opps where id in ({','.join('?' * len(q))})", q)})
    parts = [[rows[i] for i in todo[n:n + BATCH] if i in rows] for n in range(0, len(todo), BATCH)]
    done = 0
    start = llm.spent('posting_judge')
    with ThreadPoolExecutor(workers) as ex:
        for w in range(0, len(parts), workers):
            if llm.spent('posting_judge') - start > max_usd:
                print(f'stopped: spend cap {max_usd} USD reached', flush=True)
                break
            for part, out in ex.map(_ask, parts[w:w + workers]):
                done += _store(c, part, out)
            if w // workers % 20 == 0:
                print(f"judged {done}/{len(todo)} spent {llm.spent('posting_judge') - start:.3f} USD", flush=True)
    return done


def _store(c, part, out) -> int:
    got = {x['id']: x for x in out.get('items', [])}
    ts = now()
    c.executemany('insert into judgments(ts, kind, query, intent, opp_id, scores, rationale, judge, prompt_version) '
                  'values (?,?,?,?,?,?,?,?,?)',
                  [(ts, 'posting', None, None, r['id'], json.dumps({k: v for k, v in got[r['id']].items() if k != 'id'}),
                    None, JUDGE, VERSION) for r in part if r['id'] in got])
    c.commit()
    return sum(r['id'] in got for r in part)


if __name__ == '__main__':
    ids = json.load(open(sys.argv[1]))
    print('judged', ensure(ids[:int(sys.argv[2])] if len(sys.argv) > 2 else ids))
