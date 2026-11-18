"""Fetch every source, append raw payloads, upsert normalized opps, refresh FTS rows and duplicate clusters."""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from . import regions, sources
from .db import connect, now
from .text import lang, tokens, usd_year

MIN_GAP_H = {'remotive': 6, 'jobicy': 1}  # Remotive: at most 4 calls a day; Jobicy: one pass an hour
FIELDS = ('url', 'apply_url', 'title', 'org', 'kind', 'location', 'remote', 'salary_min', 'salary_max', 'currency',
          'period', 'posted_at', 'tags', 'text')


def _recent(c, source: str) -> bool:
    h = MIN_GAP_H.get(source)
    if not h:
        return False
    r = c.execute('select max(ts) from fetch_log where source=? and ok=1', (source,)).fetchone()[0]
    return bool(r) and datetime.fromisoformat(r.replace('Z', '+00:00')) > datetime.now(timezone.utc) - timedelta(hours=h)


def fts_row(c, oid: int, o: dict):
    c.execute('delete from opps_fts where rowid=?', (oid,))
    head = f"{o.get('title') or ''} {o.get('org') or ''}"
    body = f"{o.get('tags') or ''} {o.get('location') or ''} {(o.get('text') or '')[:20000]}"
    c.execute('insert into opps_fts(rowid, title_tok, body_tok) values (?,?,?)',
              (oid, ' '.join(tokens(head)), ' '.join(tokens(body))))


def upsert(c, source: str, sid: str, raw: dict, o: dict, ts: str) -> str:
    o = {k: o.get(k) for k in FIELDS}
    o['title'] = (o['title'] or '').strip()[:300]
    o['org'] = (o['org'] or '').strip()[:120]
    h = hashlib.sha1(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    row = c.execute('select id, content_hash from opps where source=? and source_id=?', (source, sid)).fetchone()
    if row and row['content_hash'] == h:
        c.execute('update opps set last_seen=? where id=?', (ts, row['id']))
        return 'seen'
    c.execute('insert into raw_items(source, source_id, fetched_at, payload) values (?,?,?,?)',
              (source, sid, ts, json.dumps(raw, ensure_ascii=False, default=str)))
    extra = dict(source_type=sources.SOURCE_TYPE[source], lang=lang(f"{o['title']} {(o['text'] or '')[:2000]}"),
                 salary_usd_year=usd_year(o.get('salary_min'), o.get('currency'), o.get('period')), content_hash=h)
    vals = o | extra
    if row:
        c.execute(f"update opps set {', '.join(f'{k}=?' for k in vals)}, last_seen=? where id=?",
                  (*vals.values(), ts, row['id']))
        oid, what = row['id'], 'changed'
    else:
        cur = c.execute(f"insert into opps(source, source_id, {', '.join(vals)}, first_seen, last_seen) "
                        f"values (?,?,{','.join('?' * len(vals))},?,?)", (source, sid, *vals.values(), ts, ts))
        oid, what = cur.lastrowid, 'new'
    fts_row(c, oid, o)
    regions.store(c, oid, o | {'source': source})
    return what


def _norm(s: str) -> str:
    s = re.sub(r'\(.*?\)|\[.*?\]', ' ', (s or '').lower())
    return re.sub(r'[^a-z0-9㐀-鿿]+', ' ', s).strip()


def cluster(c):
    """Same (org, title) across sources = one cluster; cluster_id = smallest opp id. Orgless forum posts stay alone."""
    groups: dict[tuple, list[int]] = {}
    for r in c.execute('select id, org, title from opps'):
        o, t = _norm(r['org']), _norm(r['title'])
        groups.setdefault((o, t) if o and t else ('#', r['id']), []).append(r['id'])
    c.executemany('update opps set cluster_id=? where id=?', [(min(ids), i) for ids in groups.values() for i in ids])


def run(only: set[str] | None = None, pause: float = 1.0):
    """only: source names, or source/key for one fetcher of a source (e.g. ncss/city)."""
    c = connect()
    for source, key, make in sources.all_fetchers():
        if only and source not in only and f'{source}/{key}' not in only:
            continue
        if not only and source in sources.OPT_IN:  # opt-in sources run only when named (docs/SOURCES.md)
            continue
        if _recent(c, source):
            print(f'{source}: skipped (fetched within {MIN_GAP_H[source]} h)', flush=True)
            continue
        ts, counts, t0 = now(), {'new': 0, 'changed': 0, 'seen': 0}, time.time()
        try:
            for sid, raw, o in make():
                if sid:
                    counts[upsert(c, source, str(sid), raw, o, ts)] += 1
                c.commit()  # per row: a fetcher waiting on the network must not hold the write lock
            ok, note = 1, ''
        except Exception as e:  # one broken source must not stop the others
            ok, note = 0, f'{type(e).__name__}: {e}'[:300]
        c.execute('insert into fetch_log values (?,?,?,?,?)', (source, ts, sum(counts.values()), ok, f'{key} {note}'.strip()))
        c.commit()
        print(f"{source}{'/' + key if key else ''}: {counts} {time.time() - t0:.1f}s {note}", flush=True)
        time.sleep(pause)
    cluster(c)
    c.commit()


if __name__ == '__main__':
    run(set(sys.argv[1:]) or None)
