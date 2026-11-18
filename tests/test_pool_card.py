import json
import sqlite3

from eval.pool import posting_text, stated_types


def _row(oid, source, sid):
    return {'id': oid, 'source': source, 'source_id': sid, 'title': 'Frontend engineer', 'org': 'Acme',
            'location': 'Remote (US)', 'remote': 1.0, 'salary_min': None, 'salary_max': None, 'currency': None,
            'period': None, 'posted_at': '2026-11-01', 'tags': '', 'text': 'React'}


def test_card_shows_the_type_the_source_states():
    c = sqlite3.connect(':memory:')
    c.execute('create table raw_items(id integer primary key, source text, source_id text, fetched_at text, '
              'payload text)')
    for source, sid, payload in (('himalayas', 'a', {'employmentType': 'Part Time'}),
                                 ('himalayas', 'a', {'employmentType': 'Full Time'}),  # the latest payload wins
                                 ('arbeitnow', 'b', {'job_types': ['Experienced', 'fulltime permanent']}),
                                 ('himalayas', 'c', {}), ('greenhouse', 'd', {'employmentType': 'x'})):
        c.execute('insert into raw_items(source, source_id, fetched_at, payload) values (?,?,?,?)',
                  (source, sid, '', json.dumps(payload)))
    rows = [_row(1, 'himalayas', 'a'), _row(2, 'arbeitnow', 'b'), _row(3, 'himalayas', 'c'), _row(4, 'greenhouse', 'd')]
    t = stated_types(c, rows)
    assert t == {1: 'Full Time', 2: 'Experienced, fulltime permanent'}  # nothing stated, or a source without the field
    assert '\nType: Full Time\n' in posting_text(rows[0], t[1])
    assert 'Type:' not in posting_text(rows[2])  # rounds built before 11-07 keep their cards
