from rankai import places, search


def test_parse_picks_the_most_specific_place():
    assert places.parse('杭州, 浙江') == [('China', 'Zhejiang', 'Hangzhou')]
    assert places.parse('Toronto, ON, CA') == [('Canada', 'ON', 'Toronto')]          # CA is Canada here
    assert places.parse('Palo Alto, CA') == [('United States', 'CA', 'San Francisco Bay Area')]
    assert places.parse('新北市三重區') == [('Taiwan', 'Taipei')]
    assert places.parse('Remote (Anywhere in the World)') == [] and places.parse('Hybrid') == []
    assert ('Germany',) in places.parse('Remote (Europe)')


def test_fits_is_a_prefix_match():
    hz = places.parse('Hangzhou, China')
    assert places.fits(hz, places.parse('浙江')) and not places.fits(hz, places.parse('山东'))
    assert places.fits(places.parse('Austin, TX'), places.parse('Remote (United States)'))


def _post(location, remote, title='Frontend engineer'):
    return {'location': location, 'remote': remote, 'title': title, 'kind': 'fulltime', 'salary_usd_year': None}


def test_place_and_on_site_tags():
    qp = search.parse_query('杭州 线下 前端开发 全职')
    assert search.mismatches(_post('广州, 广东', 0.0), qp) == ['in 广州, 广东, not Hangzhou']
    assert search.mismatches(_post('Remote (United States)', 1.0), qp) == [
        'remote, not on-site', 'remote from United States, not Hangzhou']
    assert search.mismatches(_post('浙江', None), qp) == []                       # may be in Hangzhou
    assert search.mismatches(_post('广东', None, '游戏策划助理（武汉广州杭州）'), qp) == []  # the title names Hangzhou
    assert search.mismatches(_post('', None), qp) == []                           # no place known: no tag
