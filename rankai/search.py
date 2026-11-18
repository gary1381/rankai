"""Hybrid retrieval and ranking arms (docs/DESIGN.md).

A  BM25 only                      B  BM25 + e5 vectors, RRF
C  B top 50 reranked (Qwen3)      D  C minus hard-constraint violations (remote, kind, minimum pay)
E  D plus priors: freshness, source trust, completeness, scam rules
F  E with an AI query rewrite (English terms + constraints) added to the first stage
G  F plus the stored AI judgment of each posting (judge.py): not-an-opportunity, scam risk, clarity
H  F's first-stage candidates reordered by gradient boosting learned from the v0 labels (all FEATS)
I  as H without the AI posting-judgment features
J  F's first-stage candidates ordered by the reranker score alone       (the default 2026-10-29 to 11-01)
K  as H, gradient boosting fitted on the v0 + v1 + v1b labels
L  as I, gradient boosting fitted on every label made before v3        <- the default since 2026-11-01
M  J with the constraint penalty as a factor: reranker score x (1 - 0.5 x violations)

L is the default: it ties J on the v3 held-out queries and improves as labels are added, so ranking can keep getting
better from new labels (docs/EVALUATION.md, v3). J is the fallback when L cannot run.
Every result carries `mismatch`, the stated constraints it clearly breaks, for the caller to show: remote, type, pay
and, since 11-06, place and on-site (places.py; these two are display only, so the learned models' features are
unchanged). Live searches (no max_id) leave out postings their board no longer lists and, unless archive=True, jobs
posted more than 30 days ago (fresh.py). where='杭州' (11-07, regions.py) keeps only postings in that place, before the
first stage, so a small place keeps its recall; a place written in the query itself is still only a mismatch tag.
Every result carries `places`, the posting's stored places.
The D-G weights below are hand-set. H / I load data/ltr_gbm_v0.pkl, written by `python eval/ltr.py v0`; their
features come from pair_features(), the same function eval/ltr.py trains on. Postings need a stored judgment
(judge.ensure) before H scores them; a missing one sets ai_missing.
"""
import json
import math
import pickle
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import judge, models, places, qrewrite, regions
from .db import connect
from .fresh import archived_ids, closed_ids
from .text import REMOTE_YES, query_pay, tokens, usd_year

ARMS = ('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M')
AI_ARMS = ('F', 'G', 'H', 'I', 'J', 'K', 'L', 'M')  # arms with the AI query rewrite
TRUST = {'ats': 1.0, 'board': 0.8, 'code': 0.7, 'forum': 0.6}
W = dict(viol=0.5, fresh=0.10, trust=0.05, complete=0.05, scam=0.5, notopp=0.5, ai_scam=0.3, clarity=0.05)


# ---------------------------------------------------------------- index
def doc_text(r) -> str:
    sal = ''
    if r['salary_min']:
        sal = f" | pay {r['salary_min']:.0f}-{r['salary_max']:.0f} {r['currency']}/{r['period']}"
    return (f"{r['title']} | {r['org'] or ''} | {r['location'] or ''} | {r['kind']}{sal}\n"
            f"{r['tags'] or ''}\n{r['text'] or ''}")


def build_vectors(batch: int = 16, pause: float = 0.05):
    c = connect()
    todo = c.execute('select o.* from opps o left join vecs v on v.opp_id=o.id '
                     'where v.opp_id is null or v.content_hash != o.content_hash').fetchall()
    t0 = time.time()
    for i in range(0, len(todo), batch):
        rows = todo[i:i + batch]
        v = models.embed([doc_text(r) for r in rows])
        c.executemany('insert or replace into vecs(opp_id, model, content_hash, v) values (?,?,?,?)',
                      [(r['id'], models.E5_MODEL, r['content_hash'], v[j].tobytes()) for j, r in enumerate(rows)])
        c.commit()  # every batch: ingest may be writing at the same time
        if i // batch % 50 == 0:
            print(f'vectors {i + len(rows)}/{len(todo)} {time.time() - t0:.0f}s', flush=True)
        time.sleep(pause)
    c.commit()
    return len(todo)


_VEC_CACHE: dict = {}


def _matrix(c):
    n = c.execute('select count(*), max(rowid) from vecs').fetchone()
    key = tuple(n)
    if _VEC_CACHE.get('key') != key:
        rows = c.execute('select opp_id, v from vecs order by opp_id').fetchall()
        ids = np.array([r[0] for r in rows])
        _VEC_CACHE.update(key=key, ids=ids, pos={int(i): n for n, i in enumerate(ids)},
                          m=np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]))
    return _VEC_CACHE['ids'], _VEC_CACHE['m']


# ---------------------------------------------------------------- query understanding (rules, v0)
_KIND_Q = [('parttime', r'(?i)part[- ]?time|兼职|副业'), ('internship', r'(?i)\bintern|实习'),
           ('outsourcing', r'外包|私活|接单|项目'), ('contract', r'(?i)\bcontract|freelanc|gig\b|自由职业|合同'),
           ('bounty', r'(?i)bount|悬赏|赏金|open[- ]source|开源'), ('cofounder', r'(?i)co-?founder|合伙|创业伙伴'),
           ('fulltime', r'(?i)full[- ]?time|全职')]
_COLLAB = re.compile(r'(?i)collaborat|partner|合作')
ONSITE_Q = re.compile(r'(?i)线下|现场|到岗|坐班|驻场|\bon[- ]?site\b|\bin[- ]person\b|\bin[- ]office\b')
# "remote or on-site", "远程线下都可以": any work mode (11-06). Without this the bare word made remote a requirement. No
# v0-v3 query matches, so evaluation features are unchanged.
ANY_MODE_Q = re.compile(
    r'(?i)\bremote,? (or|and|/) (on[- ]?site|in[- ]office|in[- ]person|hybrid)\b|\bremote, (hybrid|on[- ]?site)\b'
    r'|\b(on[- ]?site|in[- ]office|hybrid),? (or|and|/) remote\b|\b(any|either) (work )?(mode|arrangement|setup|location)'
    r'|\bremote (is )?(optional|fine|ok(ay)?)\b|work arrangement (is )?flexible'
    r'|远程(或|或者|和|/|、)(现场|线下|坐班|驻场|办公室)|(现场|线下|坐班)(或|或者|和|/|、)远程|远程(也)?(可以|都行|均可)'
    r'|(线上|远程)线下(都|均)(可|行)|不限(远程|办公方式|工作方式)|远程不限')


def parse_query(q: str) -> dict:
    kinds = {k for k, rx in _KIND_Q if re.search(rx, q)}
    if _COLLAB.search(q) and not kinds:
        kinds = {'cofounder', 'outsourcing', 'bounty', 'contract'}
    if 'contract' in kinds:
        kinds |= {'outsourcing', 'parttime'}  # a freelancer searching also takes small projects
    p = query_pay(q)  # 10-30: replaced ad-hoc patterns that missed 万 / 两万 / NZD / CAD / 欧元 and read 日元 as CNY
    any_mode = bool(ANY_MODE_Q.search(q))
    remote, pl = bool(REMOTE_YES.search(q)) and not any_mode, places.parse(q)
    # place / onsite (11-06) only feed mismatches(), not violations(): the learned models were trained without them
    return dict(remote=remote, kinds=kinds, min_usd_year=usd_year(*p) if p else None, place=pl,
                place_name=places.name(pl), onsite=bool(ONSITE_Q.search(q)) and not remote and not any_mode,
                any_mode=any_mode)


# ---------------------------------------------------------------- first stage
def bm25(c, q: str, k: int = 100, max_id: int | None = None, allow: set[int] | None = None) -> list[tuple[int, float]]:
    """allow: only these postings (a region filter), so the top k are all candidates."""
    toks = list(dict.fromkeys(tokens(q)))
    if not toks:
        return []
    expr = ' OR '.join(f'"{t}"' for t in toks)
    sql = 'select rowid, bm25(opps_fts, 3.0, 1.0) s from opps_fts where opps_fts match ?'
    args: list = [expr]
    if max_id:
        sql += ' and rowid <= ?'
        args.append(max_id)
    if allow is not None:
        sql += ' and rowid in (select value from json_each(?))'
        args.append(json.dumps(sorted(allow)))
    return [(r[0], -r[1]) for r in c.execute(sql + ' order by s limit ?', (*args, k))]


def dense(c, q: str, k: int = 100, max_id: int | None = None, allow: set[int] | None = None) -> list[tuple[int, float]]:
    ids, m = _matrix(c)
    s = m @ models.embed([q], kind='query')[0]
    if max_id:
        s = np.where(ids <= max_id, s, -9)
    if allow is not None:
        s = np.where(np.isin(ids, np.fromiter(allow, dtype=ids.dtype, count=len(allow))), s, -9)
        return [(int(ids[i]), float(s[i])) for i in np.argsort(-s)[:k] if s[i] > -9]
    top = np.argsort(-s)[:k]
    return [(int(ids[i]), float(s[i])) for i in top]


def rrf(*lists, k: int = 60) -> list[tuple[int, float]]:
    acc: dict[int, float] = {}
    for lst in lists:
        for rank, (i, _) in enumerate(lst):
            acc[i] = acc.get(i, 0) + 1 / (k + rank + 1)
    return sorted(acc.items(), key=lambda x: -x[1])


# ---------------------------------------------------------------- features for D / E
SCAM = re.compile(r'(?i)registration fee|training fee|pay (a|the) (fee|deposit)|send (us )?money|buy (your own )?equipment'
                  r'|押金|培训费|报名费|先交|垫付|刷单|\bwhatsapp\b|telegram|t\.me/')


def violations(o, qp: dict) -> float:
    v = 0.0
    if qp['remote'] and o['remote'] is not None:
        v += 1 - o['remote']  # on-site 1, hybrid 0.5
    if qp['kinds'] and o['kind'] not in qp['kinds']:
        v += 1
    if qp['min_usd_year'] and o['salary_usd_year']:
        top = usd_year(o['salary_max'], o['currency'], o['period'])
        if top and top < qp['min_usd_year'] * 0.9:
            v += 1
    return v


def mismatches(o, qp: dict) -> list[str]:
    """The query constraints a posting clearly breaks, as short tags (the parts of violations(), unscored)."""
    out = []
    if qp['remote'] and o['remote'] is not None and o['remote'] < 1:
        out.append('hybrid, not remote' if o['remote'] == 0.5 else 'on-site, not remote')
    if qp['kinds'] and o['kind'] not in qp['kinds']:
        out.append(f"{o['kind']}, not {' / '.join(sorted(qp['kinds']))}")
    if qp['min_usd_year'] and o['salary_usd_year']:
        top = usd_year(o['salary_max'], o['currency'], o['period'])
        if top and top < qp['min_usd_year'] * 0.9:
            out.append(f"pay up to ~{top:,.0f} USD/yr, below the asked ~{qp['min_usd_year']:,.0f}")
    if qp.get('onsite') and o['remote'] == 1.0:
        out.append('remote, not on-site')
    if qp.get('place'):  # titles name places too: '游戏策划助理（武汉广州杭州）' has location 广东 (ncss gives the province)
        have = places.parse(o['location']) + places.parse(o['title'])
        if o['remote'] == 1.0 or qp['remote']:  # working remotely: only the country has to fit
            ok = places.fits(places.countries(qp['place']), places.countries(have))
        else:
            ok = places.fits(qp['place'], have)
        if have and not ok:
            out.append(f"remote from {places.name(places.countries(have))}, not {qp['place_name']}" if o['remote'] == 1.0
                       else f"in {(o['location'] or places.name(have))[:40]}, not {qp['place_name']}")
    return out


def priors(o) -> dict:
    age = 365.0
    if o['posted_at']:
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(o['posted_at'].replace('Z', '+00:00')))
                  .total_seconds() / 86400)
    complete = (bool(o['salary_min']) + (len(o['text'] or '') > 500) + bool(o['org'])) / 3
    return dict(fresh=math.exp(-age / 45), trust=TRUST.get(o['source_type'], 0.6), complete=complete,
                scam=1.0 if SCAM.search(o['text'] or '') else 0.0)


# ---------------------------------------------------------------- learned ranking (H, I)
FEATS = ['rerank', 'rerank_en', 'dense', 'dense_en', 'viol', 'fresh', 'trust', 'complete', 'scam_rule',
         'ai_notopp', 'ai_scam', 'ai_clarity', 'ai_missing', 'forum', 'doc_zh']
AI_JUDGE_FEATS = {'ai_notopp', 'ai_scam', 'ai_clarity', 'ai_missing'}
AI_REWRITE_FEATS = {'rerank_en', 'dense_en'}
_DATA = Path(__file__).resolve().parent.parent / 'data'
# arm -> (pickle written by eval/ltr.py, model inside it); K is H's recipe fitted on every label up to v1b,
# L is I's recipe (no AI judgment, so a new posting needs no stored judgment) fitted on every label before v3
LTR_MODELS = {'H': (_DATA / 'ltr_gbm_v0.pkl', 'H'), 'I': (_DATA / 'ltr_gbm_v0.pkl', 'I'),
              'K': (_DATA / 'ltr_gbm_v0+v1+v1b.pkl', 'H'), 'L': (_DATA / 'ltr_gbm_v0+v1+v1b+v2+v2o+v1c+v2c.pkl', 'I')}


def ai_constraints(q: str, rw: dict) -> dict:
    qp = parse_query(q)
    loc = rw.get('location')  # the rewrite's required place wins; null means none was required
    place = places.parse(loc) or (qp['place'] if loc else [])
    remote = (qp['remote'] or bool(rw.get('remote'))) and not qp['any_mode']
    return dict(remote=remote, kinds=qp['kinds'] or set(rw.get('kinds') or []), min_usd_year=qp['min_usd_year'],
                place=place, place_name=loc or '', onsite=qp['onsite'] and not remote)


def pair_features(c, q: str, rows: list) -> list[dict]:
    """FEATS for one query against postings `rows` (sqlite rows), in order."""
    rw = qrewrite.rewrite(q)
    qp = ai_constraints(q, rw)
    docs = [doc_text(r) for r in rows]
    p = models.rerank(q, docs)
    p_en = models.rerank(rw['en_query'], docs)
    qv, qv_en = models.embed([q], 'query')[0], models.embed([rw['en_query']], 'query')[0]
    _, vm = _matrix(c)
    vpos = _VEC_CACHE['pos']
    # postings fetched after the last `rankai vectors` run (11-06: 1,714 during a refresh made L fall back to J)
    miss = [r for r in rows if r['id'] not in vpos]
    late = dict(zip([r['id'] for r in miss], models.embed([doc_text(r) for r in miss]))) if miss else {}
    aj = judge.latest(c, [r['id'] for r in rows])
    out = []
    for r, pi, pe in zip(rows, p, p_en):
        pr = priors(r)
        j = aj.get(r['id'])
        v = late[r['id']] if r['id'] in late else vm[vpos[r['id']]]
        out.append({'rerank': pi, 'rerank_en': pe, 'dense': float(v @ qv), 'dense_en': float(v @ qv_en),
                    'viol': violations(r, qp), 'fresh': pr['fresh'], 'trust': pr['trust'],
                    'complete': pr['complete'], 'scam_rule': pr['scam'],
                    'ai_notopp': float(not j['is_opportunity']) if j else 0.0,
                    'ai_scam': j['scam_risk'] / 2 if j else 0.0, 'ai_clarity': j['clarity'] / 2 if j else 0.0,
                    'ai_missing': float(j is None), 'forum': float(r['source_type'] == 'forum'),
                    'doc_zh': float(r['lang'] == 'zh')})
    return out


_LTR: dict = {}


def learned_model(arm: str) -> dict:
    path, key = LTR_MODELS[arm]
    if path not in _LTR:
        _LTR[path] = pickle.loads(path.read_bytes())
    return _LTR[path]['models'][key]


# ---------------------------------------------------------------- arms
def first_stage(c, q: str, arm: str, max_id: int | None = None, fallback: bool = False,
                allow: set[int] | None = None) -> tuple[list[tuple[int, float]], dict]:
    """Candidate list for an arm, and the query constraints it uses. fallback=True: if the AI rewrite fails, use the
    rule-based candidates (as arm C) instead of raising; evaluation runs leave it off so a failure cannot hide.
    allow: draw candidates only from these postings (search(where=...))."""
    lex = bm25(c, q, 100, max_id, allow)
    if arm == 'A':
        return lex, parse_query(q)
    if arm in AI_ARMS:  # AI rewrite adds English first-stage lists and fills constraints the rules missed
        try:
            rw = qrewrite.rewrite(q)
        except Exception as e:  # noqa: BLE001 - no key, network, rate limit, refusal
            if not fallback:
                raise
            print(f'query rewrite failed, using rule-based candidates: {e}', file=sys.stderr)
            return rrf(lex, dense(c, q, 100, max_id, allow)), parse_query(q)
        en = f"{rw['en_query']} {' '.join(rw['keywords'])}"
        return (rrf(lex, dense(c, q, 100, max_id, allow), bm25(c, en, 100, max_id, allow),
                    dense(c, rw['en_query'], 100, max_id, allow)), ai_constraints(q, rw))
    return rrf(lex, dense(c, q, 100, max_id, allow)), parse_query(q)


def search(q: str, arm: str = 'L', k: int = 10, max_id: int | None = None, depth: int = 50, c=None,
           fallback: bool = False, archive: bool = False, where: str | None = None,
           field: str | None = None) -> list[dict]:
    """archive: also rank jobs posted more than fresh.ARCHIVE_DAYS ago (live searches leave them out by default).
    where: only postings in this place or region (regions.region_ids; ValueError if it names no known place).
    field: only postings whose Haiku role_family is one of these (comma-separated judge.FAMILIES names; postings
    not judged yet are left out; ValueError for an unknown name)."""
    c = c or connect()
    gone = closed_ids(c) | (set() if archive else archived_ids(c)) if max_id is None else set()
    allow = None
    if field:
        allow = judge.ids_in_fields(c, field)
    if where:  # on-site / remote in the query decide which postings a place keeps (rule parse, as violations())
        rq = parse_query(q)
        inside = regions.region_ids(c, where, remote=rq['remote'], onsite=rq['onsite'])
        if inside is not None:
            allow = inside if allow is None else allow & inside
    if allow is not None:
        allow -= gone
        if not allow:
            return []
    ranked, qp = first_stage(c, q, arm, max_id, fallback, allow)
    if max_id is None:  # live use: leave out closed and (unless asked) archived postings (fresh.py); eval passes max_id
        ranked = [x for x in ranked if x[0] not in gone]
    out = _rank(c, q, arm, k, depth, ranked, qp, fallback)
    pl = regions.of(c, [r['id'] for r in out])
    for r in out:
        r['mismatch'] = mismatches(r, qp)
        r['places'] = pl.get(r['id'], [])
    return out


def _rank(c, q: str, arm: str, k: int, depth: int, ranked: list[tuple[int, float]], qp: dict,
          fallback: bool = False) -> list[dict]:
    if arm in ('A', 'B'):
        ids = [i for i, _ in ranked[:k]]
        rows = {r['id']: r for r in c.execute(f"select * from opps where id in ({','.join('?' * len(ids))})", ids)}
        return [dict(rows[i]) | {'score': s} for i, s in ranked[:k] if i in rows]
    ids = [i for i, _ in ranked[:depth]]
    rows = {r['id']: r for r in c.execute(f"select * from opps where id in ({','.join('?' * len(ids))})", ids)}
    ids = [i for i in ids if i in rows]
    why = None  # set when a learned arm falls back to J
    if arm in LTR_MODELS:
        try:
            m = learned_model(arm)
            feats = pair_features(c, q, [rows[i] for i in ids])
        except Exception as e:  # noqa: BLE001 - pair_features needs the AI rewrite; the model file is outside git
            if not fallback:
                raise
            print(f'learned ranking failed, using the reranker score alone: {e}', file=sys.stderr)
            arm, why = 'J', f'{type(e).__name__}: {e}'[:200]
        else:
            pred = m['model'].predict(np.array([[x[f] for f in m['feats']] for x in feats], dtype=float))
            out = [dict(rows[i]) | {'score': float(s), 'feats': {f: x[f] for f in m['feats']}}
                   for i, s, x in zip(ids, pred, feats)]
            out.sort(key=lambda x: -x['score'])
            return out[:k]
    p = models.rerank(q, [doc_text(rows[i]) for i in ids])
    if arm in ('J', 'M'):  # F's candidates by reranker score alone: no rule penalties, no priors
        # M: a broken constraint shrinks the score, so it cannot swamp scores near 0 the way F's fixed -0.5 does
        keep = (lambda o: max(0.0, 1 - W['viol'] * violations(o, qp))) if arm == 'M' else (lambda o: 1.0)
        out = [dict(rows[i]) | {'score': pi * keep(rows[i]), 'feats': {'rerank': pi}} for i, pi in zip(ids, p)]
        if why:
            for x in out:
                x['fallback'] = why
        out.sort(key=lambda x: -x['score'])
        return out[:k]
    aj = judge.latest(c, ids) if arm == 'G' else {}
    out = []
    for i, pi in zip(ids, p):
        o = rows[i]
        s = pi
        feats = {'rerank': pi}
        if arm in ('D', 'E', 'F', 'G'):
            feats['viol'] = violations(o, qp)
            s -= W['viol'] * feats['viol']
        if arm in ('E', 'F', 'G'):
            pr = priors(o)
            feats |= pr
            s += W['fresh'] * pr['fresh'] + W['trust'] * pr['trust'] + W['complete'] * pr['complete'] - W['scam'] * pr['scam']
        if arm == 'G' and i in aj:  # unjudged postings get no AI term
            feats |= {'notopp': float(not aj[i]['is_opportunity']), 'ai_scam': aj[i]['scam_risk'] / 2,
                      'clarity': aj[i]['clarity'] / 2}
            s += -W['notopp'] * feats['notopp'] - W['ai_scam'] * feats['ai_scam'] + W['clarity'] * feats['clarity']
        out.append(dict(o) | {'score': s, 'feats': feats})
    out.sort(key=lambda x: -x['score'])
    return out[:k]
