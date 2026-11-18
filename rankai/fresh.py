"""Which postings have closed (11-06), so live search stops showing them.

Greenhouse, Ashby and Lever answer with a board's full listing, so a posting missing from its board's latest
successful fetch is no longer open. Per source, the cutoff is the oldest of the latest ok fetches of the boards in
sources.all_fetchers(); a posting last seen before it was not in its own board's latest listing, whichever board that
is. A board whose fetch failed keeps the cutoff at its previous fetch, so its postings are not called closed.
Every other source returns a sample (capped pages, search results, recent forum topics): a posting missing from one
fetch says nothing there, so those postings are never called closed.
Jobs posted more than ARCHIVE_DAYS ago are archived (11-07: a job over a month old is old news): they stay in
the corpus, but live searches leave them out unless asked to include the archive. Bounties, co-founder and outsourcing
posts are not archived by age.
Evaluation runs pass a snapshot max_id to search.search() and are not filtered.
"""
from datetime import datetime, timedelta, timezone

from . import sources

FULL_LISTING = ('greenhouse', 'ashby', 'lever')
JOB_KINDS = ('fulltime', 'parttime', 'contract', 'internship')
ARCHIVE_DAYS = 30


def cutoffs(c) -> dict[str, str]:
    """source -> the last_seen a posting needs to still be listed; sources with an unfetched board are left out."""
    boards: dict[str, list[str]] = {}
    for source, key, _ in sources.all_fetchers():
        if source in FULL_LISTING:
            boards.setdefault(source, []).append(key)
    out = {}
    for s, keys in boards.items():
        # fetch_log.note is the board key, followed by the error text when ok=0
        last = dict(c.execute("select substr(note, 1, instr(note || ' ', ' ') - 1) k, max(ts) from fetch_log "
                              'where source=? and ok=1 group by k', (s,)).fetchall())
        if all(k in last for k in keys):
            out[s] = min(last[k] for k in keys)
    return out


def closed_ids(c) -> set[int]:
    ids: set[int] = set()
    for s, t in cutoffs(c).items():
        ids |= {r[0] for r in c.execute('select id from opps where source=? and last_seen < ?', (s, t))}
    return ids


def archive_cutoff(days: int = ARCHIVE_DAYS, now: datetime | None = None) -> str:
    """The posted_at a job needs to stay out of the archive; posted_at is always stored as %Y-%m-%dT%H:%M:%SZ."""
    return ((now or datetime.now(timezone.utc)) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')


def archived(r, cutoff: str) -> bool:
    return r['kind'] in JOB_KINDS and bool(r['posted_at']) and r['posted_at'] < cutoff


def archived_where(days: int = ARCHIVE_DAYS, now: datetime | None = None) -> tuple[str, tuple]:
    """SQL condition on opps, and its arguments, for archived postings."""
    return f"kind in ({','.join('?' * len(JOB_KINDS))}) and posted_at < ?", (*JOB_KINDS, archive_cutoff(days, now))


def archived_ids(c, days: int = ARCHIVE_DAYS, now: datetime | None = None) -> set[int]:
    w, args = archived_where(days, now)
    return {r[0] for r in c.execute(f'select id from opps where {w}', args)}


def listed(r, cut: dict[str, str]) -> bool | None:
    """True / False: in / missing from its board's latest listing; None: the source cannot tell."""
    t = cut.get(r['source'])
    return None if t is None else (r['last_seen'] or '') >= t
