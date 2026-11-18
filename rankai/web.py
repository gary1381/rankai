"""Local search page: the MCP server's search in a browser (11-07; the page UI is in Chinese).

python -m rankai.web [--port 8793]      -> http://127.0.0.1:8793/      (#q=... runs that search when the page opens)

Results come from mcp_server.search_opportunities, so the page shows exactly what an agent gets: L's order, the fit
band and verdict, mismatch tags, duplicates folded, closed postings left out and the archive only on request.
Listens on 127.0.0.1 and answers only requests addressed to this machine by name (no CORS headers), so other web pages
cannot read results. Searches are logged to data/web_searches.jsonl, apart from the agents' log.
"""
import argparse
import inspect
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mcp.server.mcpserver.exceptions import ToolError

from . import mcp_server
from .db import ROOT

mcp_server.SEARCH_LOG = ROOT / 'data' / 'web_searches.jsonl'  # a person's own searches are not agent use
# a region filter is being added to search_opportunities (11-07); offer it on the page once the tool takes it
HAS_WHERE = 'where' in inspect.signature(mcp_server.search_opportunities).parameters
HAS_FIELD = 'field' in inspect.signature(mcp_server.search_opportunities).parameters
PORT = 8793


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return self._json(403, {'error': f'open this page as http://127.0.0.1:{port}/'})
        u = urlparse(self.path)
        a = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == '/':
                return self._send(200, PAGE.encode(), 'text/html; charset=utf-8')
            if u.path == '/api/config':
                return self._json(200, {'where': HAS_WHERE, 'field': HAS_FIELD})
            if u.path == '/api/search':
                q = (a.get('q') or '').strip()[:500]
                if not q:
                    return self._json(400, {'error': 'empty query'})
                kw = {'where': a['where']} if HAS_WHERE and a.get('where') else {}
                if HAS_FIELD and a.get('field'):
                    kw['field'] = a['field']
                return self._json(200, mcp_server.search_opportunities(
                    q, int(a.get('k') or 10), a.get('archive') == '1', **kw))
            if u.path == '/api/opportunity':
                return self._json(200, mcp_server.get_opportunity(int(a.get('id') or 0)))
            return self._json(404, {'error': 'not found'})
        except ToolError as e:
            return self._json(404, {'error': str(e)})
        except Exception as e:  # noqa: BLE001 - the page shows the error instead of a dead request
            return self._json(500, {'error': f'{type(e).__name__}: {e}'[:300]})

    def log_message(self, fmt, *args):  # one short line per request on stderr (the journal)
        print(f'{self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ""}', flush=True)


PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>rankai 职位搜索</title>
<style>
:root{--bg:#fafaf8;--card:#fff;--ink:#1d1d1b;--ink2:#56554f;--ink3:#86857d;--line:#e4e3dc;--accent:#2f5bd3;
--good:#1f7a4d;--goodbg:#e3f3ea;--mid:#8a5a00;--midbg:#fbf0d9;--bad:#a1322a;--badbg:#f9e3e0;--chip:#efeee8}
@media (prefers-color-scheme:dark){:root{--bg:#18181a;--card:#222225;--ink:#ecebe6;--ink2:#b5b4ad;--ink3:#86857d;
--line:#36363a;--accent:#8aa8ff;--good:#7fd1a3;--goodbg:#1f3a2c;--mid:#e6be6a;--midbg:#3d3220;--bad:#f0948b;
--badbg:#43251f;--chip:#2e2e32}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,
"PingFang SC","Noto Sans CJK SC",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--ink3);font-size:13px;margin:0 0 16px}
form{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
input[type=search],input[type=text]{flex:1 1 320px;min-width:0;padding:10px 12px;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--ink);font:inherit}
#where{flex:0 1 160px}select{padding:9px 8px;border:1px solid var(--line);border-radius:8px;background:var(--card);
color:var(--ink);font:inherit}label{color:var(--ink2);font-size:13px;display:flex;gap:4px;align-items:center}
button{padding:10px 18px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}
.verdict{padding:10px 12px;border-radius:8px;margin:12px 0;font-size:14px}
.v-good{background:var(--goodbg);color:var(--good)}.v-mid{background:var(--midbg);color:var(--mid)}
.v-bad{background:var(--badbg);color:var(--bad)}.v-none{background:var(--chip);color:var(--ink2)}
.meta{color:var(--ink3);font-size:12px;margin:4px 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.top{display:flex;gap:10px;align-items:baseline}.rank{color:var(--ink3);font-variant-numeric:tabular-nums;min-width:22px}
.title{font-weight:600;color:var(--accent);text-decoration:none;overflow-wrap:anywhere}.title:hover{text-decoration:underline}
.facts{color:var(--ink2);font-size:13px;margin:4px 0 0 32px;overflow-wrap:anywhere}
.chips{margin:6px 0 0 32px;display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--chip);color:var(--ink2)}
.f-strong{background:var(--goodbg);color:var(--good)}.f-possible{background:var(--midbg);color:var(--mid)}
.f-weak,.c-bad{background:var(--badbg);color:var(--bad)}
.text{margin:8px 0 0 32px;color:var(--ink2);font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}
.more{margin:6px 0 0 32px;background:none;color:var(--accent);padding:0;font-size:13px}
.err{color:var(--bad)}.empty{color:var(--ink3)}
</style></head><body><main>
<h1>rankai 职位搜索</h1>
<p class="sub">和 MCP 搜索一样：AI 改写查询，L 排序，已下架的不显示。一次搜索约 5–20 秒。用自然语言写需求，条件写在里面（远程、兼职、薪资、城市）。</p>
<form id="f"><input id="q" type="search" placeholder="例如：远程 兼职 React 前端，时薪 40 美元以上" autofocus>
<input id="where" type="text" placeholder="地域（可选）" hidden>
<select id="field" hidden><option value="">全部领域</option><option value="engineering">工程开发</option>
<option value="data_ml">数据 / 机器学习</option><option value="design">设计</option><option value="product">产品</option>
<option value="research">研究</option><option value="sales_marketing">销售 / 市场</option>
<option value="support_success">客服 / 客户成功</option><option value="operations">运营 / 行政</option>
<option value="other">其他</option></select>
<select id="k"><option>10</option><option>20</option><option>30</option></select>
<label><input id="archive" type="checkbox">包括存档（发布超过 30 天）</label>
<button id="go">搜索</button></form>
<div id="out"></div>
</main><script>
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls;
  if (text != null) e.textContent = text; return e; };
const MODE = {remote: '远程', hybrid: '混合', 'on-site': '现场', unknown: '工作方式未说明'};
const KIND = {fulltime: '全职', parttime: '兼职', contract: '合同', internship: '实习', outsourcing: '外包',
  bounty: '悬赏', cofounder: '合伙人'};
const FIT = {strong: '很符合', possible: '可能符合', weak: '不太符合'};
const WORD = {...KIND, remote: '远程', hybrid: '混合', 'on-site': '现场'};
// search.mismatches() writes English tags: "fulltime, not parttime", "in 广州, 广东, not Hangzhou", "pay up to ~…"
function tag(m) {
  let x;
  if ((x = m.match(/^pay up to ~([\d,]+) USD\/yr, below the asked ~([\d,]+)$/))) return `薪资最高约 ${x[1]} 美元/年，低于要求的约 ${x[2]}`;
  if ((x = m.match(/^remote from (.+), not (.+)$/))) return `远程但限 ${x[1]}，要求是 ${x[2]}`;
  if ((x = m.match(/^in (.+), not (.+)$/))) return `在 ${x[1]}，要求是 ${x[2]}`;
  if ((x = m.match(/^(.+), not (.+)$/))) {
    const w = (s) => s.split(' / ').map((y) => WORD[y] || y).join(' / ');
    return `${w(x[1])}，要求是${w(x[2])}`;
  }
  return m;
}
const VERDICT = {'good match likely': ['很可能有合适的结果', 'v-good'],
  'good match unlikely (related results only)': ['可能没有合适的，下面只是相关的结果', 'v-mid'],
  'nothing good': ['语料里很可能没有合适的', 'v-bad']};
fetch('/api/config').then((r) => r.json()).then((c) => { $('where').hidden = !c.where; $('field').hidden = !c.field; }).catch(() => {});

const FIELD = {engineering: '工程开发', data_ml: '数据 / 机器学习', design: '设计', product: '产品', research: '研究',
  sales_marketing: '销售 / 市场', support_success: '客服 / 客户成功', operations: '运营 / 行政', other: '其他领域'};
function card(r, i) {
  const c = el('div', 'card'), top = el('div', 'top');
  top.append(el('span', 'rank', i + 1));
  const a = el('a', 'title', r.title || '(无标题)'); a.href = r.url; a.target = '_blank'; a.rel = 'noopener';
  top.append(a); c.append(top);
  c.append(el('div', 'facts', [r.org, r.location, MODE[r.work_mode] || r.work_mode, KIND[r.kind] || r.kind, r.pay,
    r.posted && '发布 ' + r.posted, r.source].filter(Boolean).join(' · ')));
  const chips = el('div', 'chips');
  if (r.fit) chips.append(el('span', 'chip f-' + r.fit, FIT[r.fit] + ' ' + r.score.toFixed(2)));
  for (const m of r.mismatch || []) chips.append(el('span', 'chip c-bad', '不符合：' + tag(m)));
  if (r.still_listed === false) chips.append(el('span', 'chip c-bad', '招聘页已不再列出'));
  if (r.archived) chips.append(el('span', 'chip', '存档'));
  if (r.field) chips.append(el('span', 'chip', FIELD[r.field] || r.field));
  if (r.duplicates_hidden) chips.append(el('span', 'chip', `另有 ${r.duplicates_hidden} 条重复已合并`));
  c.append(chips);
  const t = el('div', 'text', r.text || ''); c.append(t);
  const more = el('button', 'more', '展开全文'); more.type = 'button';
  more.onclick = async () => {
    more.disabled = true;
    try { const full = await (await fetch('/api/opportunity?id=' + r.opp_id)).json();
      t.textContent = full.text || full.error || ''; more.remove(); }
    catch (e) { more.textContent = '读取失败'; }
  };
  c.append(more);
  return c;
}

async function run() {
  const q = $('q').value.trim(); if (!q) return;
  const p = new URLSearchParams({q, k: $('k').value, archive: $('archive').checked ? '1' : '0'});
  if (!$('where').hidden && $('where').value.trim()) p.set('where', $('where').value.trim());
  if (!$('field').hidden && $('field').value) p.set('field', $('field').value);
  history.replaceState(null, '', '#' + p.toString());
  const out = $('out'); out.replaceChildren(el('p', 'empty', '搜索中…')); $('go').disabled = true;
  const t0 = performance.now();
  try {
    const d = await (await fetch('/api/search?' + p)).json();
    out.replaceChildren();
    if (d.error) { out.append(el('p', 'err', '出错了：' + d.error)); return; }
    const [vt, vc] = VERDICT[d.verdict] || ['排序回退到 J（L 没能运行），分数没有校准', 'v-none'];
    out.append(el('div', 'verdict ' + vc, vt));
    out.append(el('div', 'meta', `${d.results.length} 条结果 · 排序 ${d.ranking} · ${((performance.now() - t0) / 1000).toFixed(1)} 秒`
      + (d.why_not_L ? ' · L 没能运行：' + d.why_not_L : '')));
    if (!d.results.length) out.append(el('p', 'empty', '没有结果。'));
    d.results.forEach((r, i) => out.append(card(r, i)));
  } catch (e) { out.replaceChildren(el('p', 'err', '连不上搜索服务：' + e)); }
  finally { $('go').disabled = false; }
}
$('f').onsubmit = (e) => { e.preventDefault(); run(); };
function fromHash() {  // another page can link here as #q=...; run() rewrites the hash with replaceState (no event)
  const h = new URLSearchParams(location.hash.slice(1));
  if (!h.get('q')) return;
  $('q').value = h.get('q'); if (h.get('k')) $('k').value = h.get('k');
  $('archive').checked = h.get('archive') === '1'; if (h.get('where')) $('where').value = h.get('where');
  if (h.get('field')) $('field').value = h.get('field');
  run();
}
window.addEventListener('hashchange', fromHash);
fromHash();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(prog='rankai.web')
    ap.add_argument('--port', type=int, default=PORT)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'rankai search page: http://127.0.0.1:{a.port}/', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
