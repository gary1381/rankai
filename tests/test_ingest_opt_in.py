from rankai import db, ingest, sources


def test_opt_in_sources_run_only_when_named(tmp_path, monkeypatch):
    called = []

    def fetcher(name):
        def gen():
            called.append(name)
            return iter(())
        return gen

    monkeypatch.setattr(ingest, 'connect', lambda: db.connect(tmp_path / 'r.sqlite'))
    monkeypatch.setattr(sources, 'all_fetchers', lambda: [('ncss', '', fetcher('ncss')), ('v2ex', '', fetcher('v2ex')),
                                                          ('ncss', 'city', fetcher('ncss/city'))])
    assert 'ncss' in sources.OPT_IN
    ingest.run(None, pause=0)
    assert called == ['v2ex']
    called.clear()
    ingest.run({'ncss'}, pause=0)
    assert called == ['ncss', 'ncss/city']
