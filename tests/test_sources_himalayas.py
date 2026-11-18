from rankai import db, sources


def test_himalayas_reads_back_until_a_page_is_already_stored(tmp_path, monkeypatch):
    c = db.connect(tmp_path / 'r.sqlite')
    for i in range(20, 40):  # yesterday's pass stored the jobs on page 2
        c.execute("insert into opps(source, source_id, source_type, title, text) "
                  "values ('himalayas', ?, 'board', 'x', 'x')", (f'g{i}',))
    c.commit()
    monkeypatch.setattr(sources, 'connect', lambda: db.connect(tmp_path / 'r.sqlite'))
    pages = {None: (0, 'p1'), 'p1': (20, 'p2'), 'p2': (40, 'p3')}
    asked = []

    def get(url):
        cur = url.partition('cursor=')[2] or None
        asked.append(cur)
        start, nxt = pages[cur]
        return {'jobs': [{'guid': f'g{i}', 'title': 't', 'companyName': 'o'} for i in range(start, start + 20)],
                'nextCursor': nxt}

    monkeypatch.setattr(sources, 'get', get)
    got = [sid for sid, _, _ in sources.himalayas(pause=0)]
    assert got == [f'g{i}' for i in range(20)] and asked == [None, 'p1']  # page 3 is never requested
