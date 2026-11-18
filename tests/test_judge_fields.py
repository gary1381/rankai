import json

import pytest

from rankai import db, judge


def test_fields_filter_reads_the_latest_judgment_and_rejects_unknown_names(tmp_path):
    c = db.connect(tmp_path / 'r.sqlite')
    rows = [(1, 'engineering'), (2, 'design'), (3, 'sales_marketing'), (2, 'engineering')]  # 2 was re-judged
    c.executemany("insert into judgments(ts, kind, opp_id, scores, judge, prompt_version) values ('t','posting',?,?,?,?)",
                  [(i, json.dumps({'role_family': f}), judge.JUDGE, judge.VERSION) for i, f in rows])
    assert judge.ids_in_fields(c, 'engineering') == {1, 2}
    assert judge.ids_in_fields(c, 'design, sales_marketing') == {3}
    assert judge.fields(c, [1, 2, 9]) == {1: 'engineering', 2: 'engineering'}
    with pytest.raises(ValueError, match='unknown field'):
        judge.ids_in_fields(c, 'engineering,cooking')
