import pytest

from rankai import db, places, regions

POSTS = [  # id, source, location, title, remote
    (1, 'ncss', '杭州, 浙江', '前端开发', None),
    (2, 'ncss', '浙江', '研发工程师', None),                                   # may be in Hangzhou
    (3, 'ncss', '全国', '软件设计助理', None),                                 # anywhere in China
    (4, 'v2ex', '', '[广州/Remote] 前端', 1.0),                               # remote, but based in Guangzhou
    (5, 'himalayas', 'Remote (China, Singapore)', 'Frontend', 1.0),           # open to China
    (6, 'wwr', 'Remote (Anywhere in the World)', 'Front-End Developer', 1.0),
    (7, 'greenhouse', 'Singapore', 'Solutions Architect (Asia-Pacific)', 0.0),  # 20 countries: not maybe-Hangzhou
    (8, 'arbeitnow', 'Ulm', 'Entwickler', None),
    (9, 'v2ex', '', '招人', None),                                            # no known place
    (10, 'github', 'Remote (open source)', 'Bounty: fix parser', 1.0),
]


@pytest.fixture
def c(tmp_path):
    c = db.connect(tmp_path / 'r.sqlite')
    for i, src, loc, title, rem in POSTS:
        c.execute('insert into opps(id, source, source_id, source_type, title, location, remote) '
                  'values (?,?,?,?,?,?,?)', (i, src, str(i), 'board', title, loc, rem))
    regions.backfill(c)
    return c


def test_classify_reads_source_conventions():
    def cl(loc, title='x', source='x'):
        return places.classify({'location': loc, 'title': title, 'source': source})

    assert cl('Speyer, RP, DE', source='smartrecruiters') == ['Germany']  # ISO code at the end
    assert cl('全国') == ['China'] and cl('Ulm') == ['Germany/Ulm']
    assert cl('Remote (Anywhere in the World)') == ['*']
    assert cl('Remote (Anywhere in the World)', 'Backend (USA Only, 100% Remote)') == ['United States']
    assert cl('Remote (open source)', source='github') == ['*'] and cl('') == []


def test_a_place_keeps_postings_there(c):
    assert regions.region_ids(c, '杭州') == {1, 2, 3, 5}
    assert regions.region_ids(c, '杭州', remote=True) == {4, 5, 6, 10}  # any remote one in China, and anywhere
    assert regions.region_ids(c, '杭州', onsite=True) == {1, 2, 3}
    assert regions.region_ids(c, 'Germany') == {8} and regions.region_ids(c, 'Europe') == {8}
    assert regions.region_ids(c, 'anywhere') is None
    with pytest.raises(ValueError):
        regions.region_ids(c, '火星')


def test_counts(c):
    top = regions.counts(c)
    assert top['postings'] == 10 and top['anywhere'] == 2 and top['unknown'] == 1
    asia = next(x for x in top['continents'] if x['continent'] == 'Asia')
    assert {x['place']: x['postings'] for x in asia['countries']}['China'] == 5
    hz = regions.counts(c, '杭州')
    assert (hz['postings'], hz['onsite_or_hybrid'], hz['remote'], hz['only_larger_place_known']) == (4, 3, 1, 2)
    assert hz['anywhere_if_remote_asked'] == 2
