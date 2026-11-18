"""One-off data fixes that re-apply a changed rule to stored rows, so the corpus need not be fetched again.

python -m rankai.maintenance fts                 rebuild the FTS rows of every posting with CJK text (after a
                                                 tokenizer change, e.g. the 10-30 traditional -> simplified fold)
python -m rankai.maintenance parttime            dry run: how many stored postings change
python -m rankai.maintenance parttime --apply
  10-29: text._KIND_RULES now puts part-time before contract. A stored posting changes only if it is 'contract'
  and its title or the source's own type field (from raw_items, the latest payload) says part-time. Kinds a source
  sets itself are left alone: Ashby's structured contract / temporary, HN "Seeking Freelancer" threads.
  content_hash is not touched, so the next ingest sees the row as changed and rewrites it with the same rule.
python -m rankai.maintenance remote [--apply]
  11-06: text.REMOTE_NOT ("不支持远程" was read as remote) and 现场办公 / 线下办公 in REMOTE_NO. Only rows the new
  rules decide change; remote values a source sets from its own fields are otherwise left alone.
python -m rankai.maintenance ashby [--apply]
  11-06: sources.ashby() now lets workplaceType win over isRemote, which Ashby also sets on hybrid jobs. Re-reads
  each Ashby posting's latest raw payload. Changes L's viol feature for those postings when a search asks for remote.
python -m rankai.maintenance places
  11-07: rebuild opp_places (regions.py) from every posting's location and title. Run it after places.py changes;
  ingest keeps the table current for new and changed postings.
"""
import json
import re
import sys
from collections import Counter

from .db import ROOT, connect
from .text import _KIND_RULES, HYBRID, REMOTE_NOT

PART = dict(_KIND_RULES)['parttime']


def _type_text(raw: dict) -> str:
    out = []
    for k in ('employmentType', 'jobType', 'job_types', 'job_type', 'type'):
        v = raw.get(k)
        out += v if isinstance(v, list) else [str(v)] if v else []
    for k, sub in (('typeOfEmployment', 'label'), ('categories', 'commitment')):  # SmartRecruiters, Lever
        if isinstance(raw.get(k), dict):
            out.append(str(raw[k].get(sub) or ''))
    return ' '.join(x.replace('_', ' ') for x in out if x)


def parttime(apply: bool = False):
    c = connect()
    rows = c.execute("""select o.id, o.source, o.title, o.tags, r.payload from opps o
                        left join raw_items r on r.rowid = (select max(rowid) from raw_items
                                                            where source=o.source and source_id=o.source_id)
                        where o.kind='contract'""").fetchall()
    change, by = [], Counter()
    for r in rows:
        raw = json.loads(r['payload']) if r['payload'] else {}
        if r['source'] == 'hn' and r['tags'] == 'hn:freelancer':
            continue
        if r['source'] == 'ashby' and (raw.get('employmentType') or '').lower() in ('contract', 'temporary'):
            continue
        if PART.search(f"{r['title']} {_type_text(raw)}"):
            change.append(r['id'])
            by[r['source']] += 1
    print(f'contract postings: {len(rows)}; contract -> parttime: {len(change)} {dict(by.most_common())}')
    for r in c.execute(f"select title from opps where id in ({','.join(map(str, change[:8]))})"):
        print('  e.g.', r['title'][:90])
    if apply and change:  # the id list is the undo record: set these back to 'contract'
        (ROOT / 'data' / 'maintenance_parttime_20261029.json').write_text(json.dumps(
            {'rule': 'contract -> parttime (part-time before contract)', 'ids': change}))
        c.executemany("update opps set kind='parttime' where id=?", [(i,) for i in change])
        c.commit()
        print('applied')


def remote(apply: bool = False):
    c = connect()
    new_no = re.compile(r'现场办公|线下办公')
    change = []
    for r in c.execute('select id, remote, title, location, substr(text, 1, 800) t from opps'):
        s = f"{r['title']} {r['location'] or ''} {r['t'] or ''}"
        if HYBRID.search(s) or r['remote'] == 0.0:
            continue
        if REMOTE_NOT.search(s) or (r['remote'] is None and new_no.search(s)):
            change.append((r['id'], r['remote']))
    print(f'remote -> on-site: {len(change)}')
    for r in c.execute(f"select id, title from opps where id in ({','.join(str(i) for i, _ in change[:8])})"):
        print('  e.g.', r['id'], r['title'][:90])
    if apply and change:  # (id, old value) pairs are the undo record
        (ROOT / 'data' / 'maintenance_remote_20261106.json').write_text(json.dumps(
            {'rule': 'REMOTE_NOT / 现场办公 -> remote 0.0', 'ids_old': change}))
        c.executemany('update opps set remote=0.0 where id=?', [(i,) for i, _ in change])
        c.commit()
        print('applied')


def ashby(apply: bool = False):
    c = connect()
    change = []
    for r in c.execute("""select o.id, o.remote, r.payload from opps o
                          join raw_items r on r.rowid = (select max(rowid) from raw_items
                                                         where source=o.source and source_id=o.source_id)
                          where o.source='ashby'"""):
        j = json.loads(r['payload'])
        new = {'remote': 1.0, 'hybrid': 0.5, 'onsite': 0.0}.get((j.get('workplaceType') or '').lower(),
                                                                1.0 if j.get('isRemote') else None)
        if new != r['remote']:
            change.append((r['id'], r['remote'], new))
    print(f'ashby remote changes: {len(change)} {dict(Counter((a, b) for _, a, b in change))}')
    if apply and change:  # (id, old, new) triples are the undo record
        (ROOT / 'data' / 'maintenance_ashby_20261106.json').write_text(json.dumps(
            {'rule': 'ashby workplaceType before isRemote', 'id_old_new': change}))
        c.executemany('update opps set remote=? where id=?', [(n, i) for i, _, n in change])
        c.commit()
        print('applied')


def fts():
    from .ingest import fts_row
    from .text import has_cjk
    c = connect()
    n = 0
    for r in c.execute('select * from opps').fetchall():
        o = dict(r)
        if any(has_cjk(o.get(k) or '') for k in ('title', 'org', 'tags', 'location', 'text')):
            fts_row(c, o['id'], o)
            n += 1
    c.commit()
    print(f'rebuilt FTS rows: {n}')


if __name__ == '__main__':
    if sys.argv[1:2] == ['fts']:
        fts()
    elif sys.argv[1:2] == ['ashby']:
        ashby('--apply' in sys.argv)
    elif sys.argv[1:2] == ['remote']:
        remote('--apply' in sys.argv)
    elif sys.argv[1:2] == ['parttime']:
        parttime('--apply' in sys.argv)
    elif sys.argv[1:2] == ['places']:
        from . import regions
        print('postings by place:', dict(regions.backfill(connect())))
    else:
        sys.exit(__doc__)
