import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from rankai import web


def _get(port, path, host=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers={'Host': host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_search_page_serves_the_mcp_search_to_this_machine_only(monkeypatch):
    calls = []

    def search(q, k, archive):
        calls.append((q, k, archive))
        return {'verdict': 'nothing good', 'results': []}

    monkeypatch.setattr(web.mcp_server, 'search_opportunities', search)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_port
    try:
        assert _get(port, '/')[0] == 200 and 'rankai 职位搜索' in _get(port, '/')[1]
        code, body = _get(port, '/api/search?q=%E8%BF%9C%E7%A8%8B%20React&k=20&archive=1')
        assert code == 200 and json.loads(body)['verdict'] == 'nothing good' and calls == [('远程 React', 20, True)]
        assert _get(port, '/api/search?q=')[0] == 400
        assert _get(port, '/api/search?q=x', host=f'attacker.example:{port}')[0] == 403  # DNS rebinding
        assert len(calls) == 1
    finally:
        srv.shutdown()


def test_field_box_is_passed_to_the_search(monkeypatch):
    calls = []

    def search(q, k, archive, where='', field=''):
        calls.append((q, where, field))
        return {'verdict': 'nothing good', 'results': []}

    monkeypatch.setattr(web.mcp_server, 'search_opportunities', search)
    monkeypatch.setattr(web, 'HAS_FIELD', True)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert json.loads(_get(srv.server_port, '/api/config')[1])['field'] is True
        assert _get(srv.server_port, '/api/search?q=go&field=engineering,data_ml')[0] == 200
        assert calls == [('go', '', 'engineering,data_ml')]
    finally:
        srv.shutdown()
